"""AI job queue: scheduling, claiming by the host runner, and recording results."""

from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, defer

from gold_advisor.ai import contract
from gold_advisor.assets import AssetDefinition, GOLD
from gold_advisor.persistence import market_data
from gold_advisor.domain import NEPAL_TZ, UTC
from gold_advisor.persistence.models import AiAnalysisRow, AnalysisSnapshotRow, AppSettingRow

DEFAULT_SETTINGS = {"provider": "codex", "model": None, "automatic": True}
SCHEDULE_INTERVAL = timedelta(hours=4)
DAILY_AUTOMATIC_CAP = 12
RUNNING_TIMEOUT = timedelta(minutes=5)
QUEUED_TIMEOUT = timedelta(minutes=30)
OPEN = ("queued", "running")


def get_settings(session: Session) -> dict:
    row = session.get(AppSettingRow, "ai")
    return {**DEFAULT_SETTINGS, **(row.value if row else {})}


def put_settings(session: Session, value: dict) -> dict:
    row = session.get(AppSettingRow, "ai") or AppSettingRow(key="ai", value={})
    row.value = {**get_settings(session), **value}
    row.updated_at = datetime.now(UTC)
    session.add(row)
    return row.value


def runner_status(session: Session) -> dict | None:
    row = session.get(AppSettingRow, "runner_status")
    return row.value if row else None


def record_heartbeat(session: Session, providers: dict) -> None:
    row = session.get(AppSettingRow, "runner_status") or AppSettingRow(key="runner_status", value={})
    row.value = {"seen_at": datetime.now(UTC).isoformat(), "providers": providers}
    row.updated_at = datetime.now(UTC)
    session.add(row)


def expire_stale(session: Session, now: datetime) -> None:
    session.execute(
        update(AiAnalysisRow)
        .where(AiAnalysisRow.status == "running", AiAnalysisRow.claimed_at < now - RUNNING_TIMEOUT)
        .values(status="failed", finished_at=now, error="The AI runner did not report back in time.")
    )
    session.execute(
        update(AiAnalysisRow)
        .where(AiAnalysisRow.status == "queued", AiAnalysisRow.created_at < now - QUEUED_TIMEOUT)
        .values(status="expired", finished_at=now, error="No AI runner picked this up. Is the runner service running?")
    )




NEWS_MAX_AGE = timedelta(hours=48)


def news_for_ai(session: Session, asset: AssetDefinition, now: datetime) -> list[dict]:
    from gold_advisor import news_service

    return [
        {
            "id": f"news-{a.provider_id}",
            "title": a.title,
            "publisher": a.publisher,
            "published_at": a.published_at.isoformat(),
            "excerpt": a.excerpt,
        }
        for a in news_service.recent_articles(session, asset, limit=5)
        if now - a.published_at <= NEWS_MAX_AGE
    ]


def enqueue(session: Session, trigger: str, now: datetime | None = None, asset: AssetDefinition = GOLD) -> AiAnalysisRow | None:
    now = now or datetime.now(UTC)
    expire_stale(session, now)
    if session.scalar(select(func.count()).where(AiAnalysisRow.status.in_(OPEN), AiAnalysisRow.asset_id == asset.id)):
        return None
    snap = market_data.latest_snapshot(session, asset)
    if snap is None:
        return None
    cfg = get_settings(session)
    row = AiAnalysisRow(
        snapshot_id=snap.id,
        asset_id=asset.id,
        trigger=trigger,
        status="queued",
        provider=cfg["provider"],
        model=cfg.get("model") or None,
        prompt_version=contract.PROMPT_VERSION,
        created_at=now,
        input=contract.build_input(
            snap.id, {**market_data.normalized_payload(snap), "asset": asset.public()}, news_for_ai(session, asset, now)
        ),
    )
    session.add(row)
    session.flush()
    return row


def maybe_schedule(session: Session, now: datetime | None = None, asset: AssetDefinition = GOLD) -> str:
    """Every 4 hours, or sooner when the decision changes; at most 12 automatic runs a day."""
    now = now or datetime.now(UTC)
    cfg = get_settings(session)
    if not cfg.get("automatic"):
        return "automatic runs are off"
    day_start = datetime.combine(now.astimezone(NEPAL_TZ).date(), datetime.min.time(), tzinfo=NEPAL_TZ)
    automatic_today = session.scalar(
        select(func.count()).where(AiAnalysisRow.trigger != "manual", AiAnalysisRow.created_at >= day_start)
    )
    if automatic_today >= DAILY_AUTOMATIC_CAP:
        return "daily cap reached"
    last = session.scalars(
        select(AiAnalysisRow).where(AiAnalysisRow.status.not_in(["expired"]), AiAnalysisRow.asset_id == asset.id).order_by(AiAnalysisRow.created_at.desc()).limit(1)
    ).first()
    snap = market_data.latest_snapshot(session, asset)
    if snap is None:
        return "no snapshot"
    if last is None or now - last.created_at >= SCHEDULE_INTERVAL:
        trigger = "schedule"
    else:
        last_snap = session.get(AnalysisSnapshotRow, last.snapshot_id)
        if last_snap is None or last_snap.decision == snap.decision:
            return "nothing material changed"
        trigger = "change"
    return "queued" if enqueue(session, trigger, now, asset) else "a run is already open"


def claim(session: Session, now: datetime | None = None) -> AiAnalysisRow | None:
    now = now or datetime.now(UTC)
    expire_stale(session, now)
    row = session.scalars(
        select(AiAnalysisRow).where(AiAnalysisRow.status == "queued").order_by(AiAnalysisRow.created_at).limit(1).with_for_update(skip_locked=True)
    ).first()
    if row is None:
        return None
    row.status, row.claimed_at = "running", now
    return row


def complete(session: Session, job_id: int, raw_output: str | None, cli_version: str | None, error: str | None, model: str | None = None) -> AiAnalysisRow | None:
    row = session.get(AiAnalysisRow, job_id, with_for_update=True)
    if row is None or row.status != "running":
        return None
    if row.provider == "openrouter" and model:
        row.model = model
    row.finished_at, row.cli_version = datetime.now(UTC), (cli_version or "")[:200]
    row.raw_output = (raw_output or "")[:20000]
    if error:
        row.status, row.error = "failed", error[:2000]
        return row
    try:
        out = contract.extract_json(raw_output or "")
    except (ValueError, TypeError) as exc:
        row.status, row.error, row.validation = "invalid", f"Output was not valid JSON: {exc}", {"ok": False, "errors": [str(exc)]}
        return row
    result = contract.validate(row.input, out)
    row.output, row.validation = out, result
    row.status = "succeeded" if result["ok"] else "invalid"
    if not result["ok"]:
        row.error = "; ".join(result["errors"])[:2000]
    return row


def latest(session: Session, asset: AssetDefinition = GOLD) -> dict:
    """Latest good AI result plus the state of the newest run, for the dashboard."""
    # The prompt input and raw model output are large and not shown on the dashboard.
    light = (defer(AiAnalysisRow.input), defer(AiAnalysisRow.raw_output), defer(AiAnalysisRow.validation))
    good = session.scalars(
        select(AiAnalysisRow).options(*light).where(AiAnalysisRow.status == "succeeded", AiAnalysisRow.asset_id == asset.id).order_by(AiAnalysisRow.finished_at.desc()).limit(1)
    ).first()
    newest = session.scalars(select(AiAnalysisRow).options(*light).where(AiAnalysisRow.asset_id == asset.id).order_by(AiAnalysisRow.created_at.desc()).limit(1)).first()
    score = (
        session.scalar(select(AnalysisSnapshotRow.deterministic_score).where(AnalysisSnapshotRow.id == good.snapshot_id))
        if good
        else None
    )
    det = float(score) if score is not None else None
    adjusted = None
    if good and det is not None:
        adjusted = round(max(-100.0, min(100.0, det + float(good.output["adjustment"]))), 2)
    return {
        "result": (
            {
                "id": good.id,
                "snapshot_id": good.snapshot_id,
                "provider": good.provider,
                "model": good.model,
                "cli_version": good.cli_version,
                "finished_at": good.finished_at,
                "output": good.output,
                "deterministic_score": det,
                "adjusted_score": adjusted,
            }
            if good
            else None
        ),
        "latest_run": (
            {"id": newest.id, "status": newest.status, "provider": newest.provider, "created_at": newest.created_at,
             "finished_at": newest.finished_at, "error": newest.error, "trigger": newest.trigger}
            if newest
            else None
        ),
    }
