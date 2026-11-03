"""One scheduled cycle for cloud runs (GitHub Actions): collect, analyse, and run the AI
only when something significant changed. Safe to run repeatedly; every step is idempotent.

    python -m gold_advisor.cycle

Daily sources (Nepal gold, NRB) skip themselves once today's value is stored. Slow-moving
sources (FRED, FOMC calendar, Nepal history) run only when their last success is old.
The AI step uses OpenRouter free models (runner/openrouter.py, GA_OPENROUTER_API_KEY).
"""

import logging
import os
import sys
from datetime import datetime, timedelta

from gold_advisor import health, jobs
from gold_advisor.assets import ASSETS, AssetDefinition
from gold_advisor.domain import UTC, Timeframe
from gold_advisor.persistence import market_data
from gold_advisor.persistence.db import session_scope

log = logging.getLogger("cycle")

SLOW_JOBS = {
    "fred.yields": (timedelta(hours=6), jobs.collect_macro),
    "federal_reserve.fomc": (timedelta(hours=6), jobs.collect_events),
    "fenegosida.history": (timedelta(hours=24), lambda: jobs.collect_nepal_history(2)),
}
CANDLE_TIMEFRAMES = (Timeframe.M15, Timeframe.H1, Timeframe.D1)

# What counts as "significant" for the AI step.
AI_WORLD_MOVE = 0.01  # world price moved at least 1% since the last AI run
AI_MAX_SILENCE = timedelta(hours=12)  # refresh at least twice a day
AI_DAILY_CAP = 12


def _step(label: str, fn) -> bool:
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 - one failing source must not stop the cycle
        log.error("FAILED  %s: %s", label, exc)
        return False
    if isinstance(result, str):
        log.info("OK      %s: %s", label, result)
    else:
        log.info("OK      %s: +%s inserted, %s revised", label, result.inserted, result.revised)
    return True


def _due(job: str, every: timedelta, now: datetime) -> bool:
    with session_scope() as session:
        last = health.collector_health(session, job).last_success_at
    return last is None or now - last >= every


def collect(now: datetime) -> None:
    for asset in ASSETS.values():
        _step(f"spot {asset.id}", lambda a=asset: jobs.collect_gold_spot(a))
        for tf in CANDLE_TIMEFRAMES:
            _step(f"candles {tf.value} {asset.id}", lambda a=asset, t=tf: jobs.collect_candles(t, a))
    force = os.environ.get("GA_FORCE_DAILY", "").lower() == "true"  # the dashboard's Refresh button
    _step("nepal today", lambda: jobs.collect_nepal_today(force=force))
    _step("usd/npr", lambda: jobs.collect_fx(force=force))
    for job, (every, fn) in SLOW_JOBS.items():
        if _due(job, every, now):
            _step(job, fn)


def _significance(session, asset: AssetDefinition, now: datetime) -> str | None:
    """Return why the AI should run, or None when nothing material changed."""
    from sqlalchemy import func, select

    from gold_advisor.domain import NEPAL_TZ
    from gold_advisor.persistence.models import AiAnalysisRow, AnalysisSnapshotRow

    snap = market_data.latest_snapshot(session, asset)
    if snap is None:
        return None
    day_start = datetime.combine(now.astimezone(NEPAL_TZ).date(), datetime.min.time(), tzinfo=NEPAL_TZ)
    used_today = session.scalar(
        select(func.count()).where(
            AiAnalysisRow.asset_id == asset.id, AiAnalysisRow.trigger != "manual", AiAnalysisRow.created_at >= day_start
        )
    )
    if used_today >= AI_DAILY_CAP:
        return None
    last = session.scalars(
        select(AiAnalysisRow)
        .where(AiAnalysisRow.asset_id == asset.id, AiAnalysisRow.status == "succeeded")
        .order_by(AiAnalysisRow.created_at.desc())
        .limit(1)
    ).first()
    if last is None:
        return "first AI analysis"
    if now - last.created_at >= AI_MAX_SILENCE:
        return "no AI analysis for 12 hours"
    old = session.get(AnalysisSnapshotRow, last.snapshot_id)
    if old is None:
        return "previous analysis missing"
    if old.decision != snap.decision:
        return f"advice changed {old.decision} -> {snap.decision}"
    new_p, old_p = market_data.normalized_payload(snap)["prices"], market_data.normalized_payload(old)["prices"]
    if (new_p.get("nepal_latest") or {}).get("rate_date") != (old_p.get("nepal_latest") or {}).get("rate_date"):
        return "new Nepal price published"
    a, b = new_p.get("world_usd_now"), old_p.get("world_usd_now")
    if a and b and abs(a / b - 1) >= AI_WORLD_MOVE:
        return f"world price moved {a / b - 1:+.1%}"
    return None


def ai_if_significant(asset: AssetDefinition, now: datetime) -> None:
    if not os.environ.get("GA_OPENROUTER_API_KEY", "").strip():
        log.info("AI skipped: GA_OPENROUTER_API_KEY not set")
        return
    import openrouter  # runner/openrouter.py, on PYTHONPATH

    from gold_advisor.ai import contract, service

    from sqlalchemy import select

    from gold_advisor.persistence.models import AiAnalysisRow

    with session_scope() as session:
        # A job queued by "Ask AI" on the dashboard runs regardless of significance.
        row = session.scalars(
            select(AiAnalysisRow)
            .where(AiAnalysisRow.asset_id == asset.id, AiAnalysisRow.status == "queued")
            .order_by(AiAnalysisRow.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        reason = "requested from the dashboard" if row is not None else _significance(session, asset, now)
        if reason is None:
            log.info("AI %s skipped: nothing significant", asset.id)
            return
        row = row or service.enqueue(session, "change", now, asset)
        if row is None:
            log.info("AI %s skipped: another run is open", asset.id)
            return
        # Claim it here, in the same transaction, so no other runner picks it up.
        row.provider, row.model, row.status, row.claimed_at = "openrouter", None, "running", now
        job_id, prompt = row.id, contract.prompt(row.input)
    log.info("AI %s: running (%s)", asset.id, reason)
    try:
        answer = openrouter.run(prompt, contract.OUTPUT_SCHEMA)
        raw, model, error = answer["raw_output"], answer.get("model"), None
    except openrouter.OpenRouterError as exc:
        raw, model, error = None, None, str(exc)
    with session_scope() as session:
        done = service.complete(session, job_id, raw, "OpenRouter API (GitHub Actions)", error, model)
        log.info("AI %s: %s %s", asset.id, done.status if done else "lost", (done.error or "") if done else "")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    now = datetime.now(UTC)
    collect(now)
    analysed = [_step(f"analysis {a.id}", lambda a=a: jobs.run_analysis(a)) for a in ASSETS.values()]
    from gold_advisor.ai import service

    with session_scope() as session:
        service.expire_stale(session, datetime.now(UTC))
    for asset in ASSETS.values():
        try:
            ai_if_significant(asset, datetime.now(UTC))
        except Exception as exc:  # noqa: BLE001 - AI is optional; never fail the cycle for it
            log.error("AI %s failed: %s", asset.id, exc)
    # Fail the workflow (so GitHub emails you) only when no analysis could be produced.
    return 0 if any(analysed) else 1


if __name__ == "__main__":
    sys.exit(main())
