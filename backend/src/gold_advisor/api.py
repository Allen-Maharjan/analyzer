"""Read-only /api/v1 resources over collected data. Requests never trigger provider calls."""

import sys
from pathlib import Path

# Vercel loads this file directly by path (pyproject [tool.vercel] entrypoint), without
# installing the package. Make src/ importable so "gold_advisor.*" imports resolve.
_SRC = str(Path(__file__).resolve().parent.parent)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from gold_advisor import freshness, health
from gold_advisor.assets import ASSETS, GOLD, AssetDefinition, get_asset
from gold_advisor.persistence import market_data
from gold_advisor.domain import (
    UTC,
    CollectorStatus,
    FreshnessStatus,
    Instrument,
    MassUnit,
    Metal,
    Purity,
    Source,
    Timeframe,
)
from gold_advisor.persistence.db import read_session_scope, session_scope
from gold_advisor.persistence.models import (
    AnalysisSnapshotRow,
    AppSettingRow,
    CandleRow,
    FxRateRow,
    LocalMetalRateRow,
    MacroObservationRow,
    PurchasePlanRow,
    SpotQuoteRow,
)

app = FastAPI(title="Nepal Gold Purchase Advisor API", version="0.1.0")

OPEN_PATHS = ("/api/v1/health",)
SELF_AUTHENTICATED_PREFIX = "/api/v1/runner/"  # checked against the runner token instead


@app.middleware("http")
async def require_internal_token(request, call_next):
    """In the cloud the API is public, so only the dashboard (which holds the token) may call it."""
    import hmac

    from fastapi.responses import JSONResponse

    from gold_advisor.config import get_settings as _settings

    token = _settings().internal_token
    path = request.url.path
    if token and path not in OPEN_PATHS and not path.startswith(SELF_AUTHENTICATED_PREFIX):
        given = request.headers.get("x-internal-token", "")
        if not hmac.compare_digest(given.encode(), token.encode()):
            return JSONResponse({"detail": "not authorised"}, status_code=401)
    return await call_next(request)


def cooldown_passed(session: Session, key: str, seconds: int) -> bool:
    """Database-backed rate limit, so it works without Redis (Vercel) and with it (Docker)."""
    from datetime import timedelta

    row = session.get(AppSettingRow, f"cooldown:{key}")
    now = datetime.now(UTC)
    if row is not None and row.updated_at > now - timedelta(seconds=seconds):
        return False
    row = row or AppSettingRow(key=f"cooldown:{key}", value={})
    row.value, row.updated_at = {"at": now.isoformat()}, now
    session.add(row)
    session.flush()
    return True


def dispatch_cycle(force_daily: bool = False) -> bool:
    """Start the GitHub Actions cycle. Returns False when cloud dispatch is not configured."""
    import httpx

    from gold_advisor.config import get_settings as _settings

    cfg = _settings()
    if not (cfg.github_dispatch_token and cfg.github_repo):
        return False
    response = httpx.post(
        f"https://api.github.com/repos/{cfg.github_repo}/actions/workflows/{cfg.github_workflow}/dispatches",
        headers={
            "Authorization": f"Bearer {cfg.github_dispatch_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"ref": cfg.github_ref, "inputs": {"force_daily": "true" if force_daily else "false"}},
        timeout=15,
    )
    if response.status_code != 204:
        raise HTTPException(status_code=502, detail=f"Couldn't start the update on GitHub ({response.status_code}).")
    return True

MAX_ROWS = 5000


def get_session(request: Request):
    # GET requests only read, so skip the transaction round trips.
    scope = read_session_scope if request.method in ("GET", "HEAD") else session_scope
    with scope() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def selected_asset(asset: str = "gold") -> AssetDefinition:
    try:
        return get_asset(asset)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

AssetDep = Annotated[AssetDefinition, Depends(selected_asset)]

@app.get("/api/v1/assets")
def assets() -> list[dict]:
    return [asset.public() for asset in ASSETS.values()]


class FreshnessOut(BaseModel):
    status: FreshnessStatus
    reason: str
    age_seconds: float | None


class CollectorOut(BaseModel):
    status: CollectorStatus
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None
    consecutive_failures: int


class SourceHealthOut(BaseModel):
    dataset: str
    source: Source
    latest_observation: datetime | date | None
    freshness: FreshnessOut
    collector: CollectorOut


class SpotQuoteOut(BaseModel):
    source: Source
    instrument: str
    observed_at: datetime
    price: Decimal
    quality_flags: list[str]
    freshness: FreshnessOut


class CandleOut(BaseModel):
    bucket_start: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    derived: bool
    component_count: int | None
    quality_flags: list[str]
    revision: int


class CandleSeriesOut(BaseModel):
    source: Source
    instrument: str
    timeframe: Timeframe
    price_side: str
    bucket_alignment: str
    candles: list[CandleOut]


class LocalRateOut(BaseModel):
    rate_date: date
    published_at: datetime | None
    publication_time_known: bool
    price_npr: Decimal
    source_label: str
    quality_flags: list[str]
    revision: int


class FxRateOut(BaseModel):
    rate_date: date
    unit: int
    buy: Decimal
    sell: Decimal
    analytical_midpoint: Decimal
    published_at: datetime | None
    revision: int


class MacroOut(BaseModel):
    obs_date: date
    value: Decimal | None
    revision: int


def _freshness_out(f) -> FreshnessOut:
    return FreshnessOut(status=f.status, reason=f.reason, age_seconds=f.age_seconds)


@app.get("/api/v1/health")
def liveness(session: SessionDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/api/v1/sources", response_model=list[SourceHealthOut])
def sources(session: SessionDep, asset: AssetDep) -> list[SourceHealthOut]:
    return [
        SourceHealthOut(
            dataset=d.dataset,
            source=d.source,
            latest_observation=d.latest_observation,
            freshness=_freshness_out(d.freshness),
            collector=CollectorOut(**d.collector.__dict__),
        )
        for d in health.all_sources(session, datetime.now(UTC), asset)
    ]


@app.get("/api/v1/quotes/latest", response_model=SpotQuoteOut)
def latest_quote(session: SessionDep, asset: AssetDep) -> SpotQuoteOut:
    row = market_data.latest_quote(session, asset, (Source.GOLD_API, Source.SWISSQUOTE))
    if row is None:
        raise HTTPException(status_code=404, detail="no verified quote collected yet")
    return SpotQuoteOut(
        source=Source(row.source),
        instrument=row.instrument,
        observed_at=row.observed_at,
        price=row.price,
        quality_flags=row.quality_flags,
        freshness=_freshness_out(freshness.live_quote(row.observed_at, datetime.now(UTC), asset.calendar)),
    )


@app.get("/api/v1/candles", response_model=CandleSeriesOut)
def candles(
    session: SessionDep,
    asset: AssetDep,
    timeframe: Timeframe,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_ROWS)] = 500,
) -> CandleSeriesOut:
    try:
        query = market_data.MarketQuery(asset, timeframe, start, end, limit)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    rows = market_data.candles(session, query)
    return CandleSeriesOut(
        source=asset.candle_source,
        instrument=asset.instrument,
        timeframe=timeframe,
        price_side=asset.price_side,
        bucket_alignment=asset.bucket_alignment,
        candles=[
            CandleOut(
                bucket_start=r.bucket_start,
                open=r.open,
                high=r.high,
                low=r.low,
                close=r.close,
                volume=r.volume,
                derived=r.derived,
                component_count=r.component_count,
                quality_flags=r.quality_flags,
                revision=r.revision,
            )
            for r in rows
        ],
    )


@app.get("/api/v1/nepal-rates", response_model=list[LocalRateOut])
def nepal_rates(
    session: SessionDep,
    metal: Metal = Metal.GOLD,
    unit: MassUnit = MassUnit.TOLA,
    start: date | None = None,
    end: date | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_ROWS)] = 400,
) -> list[LocalRateOut]:
    purity = Purity.HALLMARK if metal is Metal.GOLD else Purity.PURE_SILVER
    query = select(LocalMetalRateRow).where(
        LocalMetalRateRow.source == Source.FENEGOSIDA.value,
        LocalMetalRateRow.metal == metal.value,
        LocalMetalRateRow.purity == purity.value,
        LocalMetalRateRow.unit == unit.value,
    )
    if start:
        query = query.where(LocalMetalRateRow.rate_date >= start)
    if end:
        query = query.where(LocalMetalRateRow.rate_date <= end)
    rows = reversed(session.scalars(query.order_by(LocalMetalRateRow.rate_date.desc()).limit(limit)).all())
    return [
        LocalRateOut(
            rate_date=r.rate_date,
            published_at=r.published_at,
            publication_time_known=r.published_at is not None,
            price_npr=r.price_npr,
            source_label=r.source_label,
            quality_flags=r.quality_flags,
            revision=r.revision,
        )
        for r in rows
    ]


@app.get("/api/v1/fx-rates", response_model=list[FxRateOut])
def fx_rates(
    session: SessionDep,
    currency: Annotated[str, Query(pattern="^[A-Z]{3}$")] = "USD",
    start: date | None = None,
    end: date | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_ROWS)] = 400,
) -> list[FxRateOut]:
    query = select(FxRateRow).where(FxRateRow.source == Source.NRB.value, FxRateRow.currency == currency)
    if start:
        query = query.where(FxRateRow.rate_date >= start)
    if end:
        query = query.where(FxRateRow.rate_date <= end)
    rows = reversed(session.scalars(query.order_by(FxRateRow.rate_date.desc()).limit(limit)).all())
    return [
        FxRateOut(
            rate_date=r.rate_date,
            unit=r.unit,
            buy=r.buy,
            sell=r.sell,
            analytical_midpoint=((r.buy + r.sell) / 2).quantize(Decimal("0.0001")),
            published_at=r.published_at,
            revision=r.revision,
        )
        for r in rows
    ]


@app.get("/api/v1/macro/{series_id}", response_model=list[MacroOut])
def macro(
    session: SessionDep,
    series_id: str,
    start: date | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_ROWS)] = 400,
) -> list[MacroOut]:
    query = select(MacroObservationRow).where(
        MacroObservationRow.source == Source.FRED.value, MacroObservationRow.series_id == series_id
    )
    if start:
        query = query.where(MacroObservationRow.obs_date >= start)
    rows = list(reversed(session.scalars(query.order_by(MacroObservationRow.obs_date.desc()).limit(limit)).all()))
    if not rows:
        raise HTTPException(status_code=404, detail=f"no observations for {series_id}")
    return [MacroOut(obs_date=r.obs_date, value=r.value, revision=r.revision) for r in rows]


class RefreshTarget(StrEnum):
    """Daily-published data that the dashboard refresh button can re-fetch on demand."""

    NEPAL_GOLD = "nepal_gold"
    NEPAL_RATES = "nepal_rates"
    USD_NPR = "usd_npr"


REFRESH_COOLDOWN_SECONDS = 60


class RefreshOut(BaseModel):
    target: RefreshTarget
    queued: bool
    message: str


@app.post("/api/v1/refresh/{target}", response_model=RefreshOut, status_code=status.HTTP_202_ACCEPTED)
def refresh(session: SessionDep, target: RefreshTarget, response: Response) -> RefreshOut:
    from gold_advisor.config import get_settings as _settings

    cloud = bool(_settings().github_dispatch_token)
    # In the cloud one GitHub run refreshes everything, so all targets share one cooldown.
    key = "refresh" if cloud else f"refresh:{'usd_npr' if target is RefreshTarget.USD_NPR else 'nepal_rates'}"
    if not cooldown_passed(session, key, REFRESH_COOLDOWN_SECONDS):
        response.status_code = status.HTTP_429_TOO_MANY_REQUESTS
        response.headers["Retry-After"] = str(REFRESH_COOLDOWN_SECONDS)
        return RefreshOut(target=target, queued=False, message="Refreshed less than a minute ago. Try again shortly.")
    if dispatch_cycle(force_daily=True):
        return RefreshOut(target=target, queued=True, message="Update started. New prices appear in about 2–3 minutes.")
    from gold_advisor import tasks

    task = tasks.collect_nepal_today if target is not RefreshTarget.USD_NPR else tasks.collect_fx
    task.delay(force=True)
    return RefreshOut(target=target, queued=True, message="Checking the source now. Results appear within a minute.")


# --- Analysis, purchase plan, settings ---------------------------------------------------


class ReasonOut(BaseModel):
    plain: str
    detail: str


class WaitingOut(BaseModel):
    days: float | None
    review_due: bool


class PricePointOut(BaseModel):
    date: date
    price: float


class PriceSummaryOut(BaseModel):
    nepal_per_tola: float | None
    nepal_date: date | None
    nepal_published_at: datetime | None
    nepal_time_known: bool
    nepal_history: list[PricePointOut]
    world_usd_per_ounce: float | None
    world_price_source: str
    usd_npr: float | None
    changes: dict[str, float | None]


class SourceStatusOut(BaseModel):
    dataset: str
    status: FreshnessStatus
    latest: datetime | date | None


class NextEventOut(BaseModel):
    title: str
    scheduled_at: datetime
    hours_away: float


class ForecastSummaryOut(BaseModel):
    label: str
    status: str
    reason: str | None = None
    sample_size: int | None = None
    most_likely: str | None = None
    probabilities: dict[str, float] = {}
    range_npr_per_tola: list[float | None] | None = None


class AssetOut(BaseModel):
    id: str
    label: str
    instrument: str
    quote_currency: str
    price_unit: str
    local_label: str | None
    timeframes: list[Timeframe]


class DashboardOut(BaseModel):
    """Plain-language summary first. Technical detail lives at ``/snapshots/{id}``."""

    asset: AssetOut
    snapshot_id: str
    created_at: datetime
    decision: str
    headline: str
    summary: str
    confidence: str
    next_review: str
    what_would_change: str
    reasons: list[ReasonOut]
    upside_risks: list[str]
    downside_risks: list[str]
    limitations: list[str]
    waiting: WaitingOut
    prices: PriceSummaryOut
    next_event: NextEventOut | None
    sources: list[SourceStatusOut]
    forecasts: list[ForecastSummaryOut]
    news_risk: "NewsRiskOverrideOut | None" = None


class NewsRiskOverrideOut(BaseModel):
    """Present only when an owner-confirmed news risk changed BUY into WAIT."""

    original_decision: str
    reason: str
    expires_at: datetime
    article_title: str | None
    article_publisher: str | None
    article_url: str | None


def _latest_snapshot(session: Session, asset: AssetDefinition) -> AnalysisSnapshotRow:
    row = market_data.latest_snapshot(session, asset)
    if row is None:
        raise HTTPException(status_code=404, detail="no analysis has run yet")
    return row


@app.get("/api/v1/dashboard", response_model=DashboardOut)
def dashboard(session: SessionDep, asset: AssetDep) -> DashboardOut:
    from gold_advisor import news_service
    from gold_advisor.decision import news_risk

    row = _latest_snapshot(session, asset)
    p = market_data.normalized_payload(row)
    now = datetime.now(UTC)
    active = news_service.active_risk(session, asset, now)
    risk = (
        news_risk.Risk(
            active.reason, active.expires_at,
            active.article.title if active.article else None,
            active.article.publisher if active.article else None,
            active.article.url if active.article else None,
        )
        if active
        else None
    )
    d, override = news_risk.apply(p["decision"], risk, now)
    nepal_latest = p["prices"]["nepal_latest"] or {}
    return DashboardOut(
        asset=AssetOut(**asset.public()),
        snapshot_id=row.id,
        created_at=row.created_at,
        decision=d["decision"],
        headline=d["headline"],
        summary=d["summary"],
        confidence=d["confidence"],
        next_review=d["next_review"],
        what_would_change=d["what_would_change"],
        reasons=d["reasons"],
        upside_risks=d["upside_risks"],
        downside_risks=d["downside_risks"],
        limitations=d["limitations"],
        waiting=WaitingOut(days=d["waiting_days"], review_due=d["review_due"]),
        prices=PriceSummaryOut(
            nepal_per_tola=nepal_latest.get("nepal_price"),
            nepal_date=nepal_latest.get("rate_date"),
            nepal_published_at=nepal_latest.get("at"),
            nepal_time_known=bool(nepal_latest.get("time_known")),
            nepal_history=p["prices"].get("nepal_history", []),
            world_usd_per_ounce=p["prices"]["world_usd_now"],
            world_price_source=p["prices"]["world_usd_source"],
            usd_npr=p["prices"]["usd_npr_mid"],
            changes=p["prices"]["changes"],
        ),
        next_event=p["next_event"],
        forecasts=[
            ForecastSummaryOut(
                label=f["label"],
                status=f["status"],
                reason=f.get("reason"),
                sample_size=f.get("sample_size"),
                most_likely=f.get("most_likely"),
                probabilities={s["name"]: s["probability"] for s in f.get("scenarios", [])},
                range_npr_per_tola=f.get("range_npr_per_tola"),
            )
            for f in p.get("forecasts", [])
        ],
        sources=[
            SourceStatusOut(dataset=s["dataset"], status=s["freshness"]["status"], latest=s["latest_observation"])
            for s in p["sources"]
        ],
        news_risk=NewsRiskOverrideOut(**override) if override else None,
    )


@app.get("/api/v1/snapshots/{snapshot_id}")
def snapshot_detail(session: SessionDep, snapshot_id: str, asset: AssetDep) -> dict:
    """Full technical detail for the 'View detailed analysis' screen."""
    row = session.get(AnalysisSnapshotRow, snapshot_id)
    if row is None or row.asset_id != asset.id:
        raise HTTPException(status_code=404, detail="snapshot not found")
    payload = market_data.normalized_payload(row)
    if asset.id == "gold":
        payload["prices"]["xau_usd_now"] = payload["prices"]["world_usd_now"]
        payload["prices"]["xau_usd_source"] = payload["prices"]["world_usd_source"]
    return {"id": row.id, "created_at": row.created_at, **payload, "asset": asset.public()}


class PlanOut(BaseModel):
    waiting_since: datetime | None
    completed_at: datetime | None


@app.get("/api/v1/plan", response_model=PlanOut)
def get_plan(session: SessionDep, asset: AssetDep) -> PlanOut:
    plan = session.get(PurchasePlanRow, asset.id)
    return PlanOut(waiting_since=plan.waiting_since if plan else None, completed_at=plan.completed_at if plan else None)


@app.post("/api/v1/plan/{action}", response_model=PlanOut)
def update_plan(session: SessionDep, asset: AssetDep, action: Annotated[str, Path(pattern="^(purchased|restart)$")]) -> PlanOut:
    """``purchased`` closes the plan; ``restart`` starts a new one. Nothing else resets the clock."""
    now = datetime.now(UTC)
    plan = session.get(PurchasePlanRow, asset.id) or PurchasePlanRow(asset_id=asset.id)
    if action == "purchased":
        plan.completed_at = now
    else:
        plan.waiting_since, plan.completed_at = None, None
    plan.updated_at = now
    session.add(plan)
    session.flush()
    return PlanOut(waiting_since=plan.waiting_since, completed_at=plan.completed_at)


class WatchLevelsIn(BaseModel):
    levels: list[Annotated[float, Field(gt=0, lt=100000)]] = Field(max_length=10)


@app.get("/api/v1/settings/watch-levels", response_model=WatchLevelsIn)
def get_watch_levels(session: SessionDep, asset: AssetDep) -> WatchLevelsIn:
    row = session.get(AppSettingRow, asset.watch_key)
    return WatchLevelsIn(levels=row.value["value"] if row else list(asset.watch_levels))


@app.put("/api/v1/settings/watch-levels", response_model=WatchLevelsIn)
def put_watch_levels(session: SessionDep, asset: AssetDep, body: WatchLevelsIn) -> WatchLevelsIn:
    row = session.get(AppSettingRow, asset.watch_key) or AppSettingRow(key=asset.watch_key, value={})
    row.value = {"value": sorted(set(body.levels))}
    row.updated_at = datetime.now(UTC)
    session.add(row)
    return WatchLevelsIn(levels=row.value["value"])


# --- AI analysis -----------------------------------------------------------------------

from gold_advisor.ai import contract as ai_contract  # noqa: E402
from gold_advisor.ai import service as ai_service  # noqa: E402
from gold_advisor.config import get_settings as get_app_settings  # noqa: E402


class AiSettingsIn(BaseModel):
    provider: Annotated[str, Field(pattern=f"^({'|'.join(ai_contract.PROVIDERS)})$")]
    model: Annotated[str | None, Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9._:\-]*$")] = None
    automatic: bool = True


@app.get("/api/v1/ai")
def ai_overview(session: SessionDep, asset: AssetDep) -> dict:
    # Read-only: stale jobs are expired by the scheduled cycle, not on every page load.
    return {**ai_service.latest(session, asset), "settings": ai_service.get_settings(session), "runner": ai_service.runner_status(session)}


@app.put("/api/v1/ai/settings")
def ai_put_settings(session: SessionDep, body: AiSettingsIn) -> dict:
    return ai_service.put_settings(session, {"provider": body.provider, "model": None if body.provider == "openrouter" else body.model or None, "automatic": body.automatic})


AI_REQUEST_COOLDOWN_SECONDS = 60


@app.post("/api/v1/ai/request", status_code=status.HTTP_202_ACCEPTED)
def ai_request(session: SessionDep, asset: AssetDep, response: Response) -> dict:
    if not cooldown_passed(session, f"ai_request:{asset.id}", AI_REQUEST_COOLDOWN_SECONDS):
        response.status_code = status.HTTP_429_TOO_MANY_REQUESTS
        return {"queued": False, "message": "AI was asked less than a minute ago."}
    row = ai_service.enqueue(session, "manual", asset=asset)
    if row is None:
        response.status_code = status.HTTP_409_CONFLICT
        return {"queued": False, "message": "An AI check is already running."}
    job_id = row.id
    session.commit()  # the GitHub run must see the queued job
    if dispatch_cycle():
        return {"queued": True, "id": job_id, "message": "Asked the AI. Its answer appears in about 3–4 minutes."}
    return {"queued": True, "id": job_id, "message": "Asked the AI. Its answer appears within about two minutes."}


def _runner_auth(authorization: str | None) -> None:
    import hmac

    token = get_app_settings().runner_token
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not token or len(token) < 32 or not hmac.compare_digest(given, token):
        raise HTTPException(status_code=401, detail="runner not authorised")


from fastapi import Header  # noqa: E402


class HeartbeatIn(BaseModel):
    providers: dict[str, dict]


@app.post("/api/v1/runner/heartbeat", include_in_schema=False)
def runner_heartbeat(session: SessionDep, body: HeartbeatIn, authorization: Annotated[str | None, Header()] = None) -> dict:
    _runner_auth(authorization)
    ai_service.record_heartbeat(session, {k: v for k, v in body.providers.items() if k in ai_contract.PROVIDERS})
    return {"ok": True}


@app.post("/api/v1/runner/claim", include_in_schema=False)
def runner_claim(session: SessionDep, response: Response, authorization: Annotated[str | None, Header()] = None) -> dict:
    _runner_auth(authorization)
    row = ai_service.claim(session)
    if row is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return {}
    return {
        "id": row.id,
        "provider": row.provider,
        "model": row.model,
        "prompt": ai_contract.prompt(row.input),
        "schema": ai_contract.OUTPUT_SCHEMA,
    }


class RunnerResultIn(BaseModel):
    raw_output: Annotated[str | None, Field(max_length=200000)] = None
    model: Annotated[str | None, Field(max_length=64, pattern=r"^[A-Za-z0-9._/:-]+:free$")] = None
    cli_version: Annotated[str | None, Field(max_length=200)] = None
    error: Annotated[str | None, Field(max_length=4000)] = None


@app.post("/api/v1/runner/jobs/{job_id}", include_in_schema=False)
def runner_result(session: SessionDep, job_id: int, body: RunnerResultIn, authorization: Annotated[str | None, Header()] = None) -> dict:
    _runner_auth(authorization)
    row = ai_service.complete(session, job_id, body.raw_output, body.cli_version, body.error, body.model)
    if row is None:
        raise HTTPException(status_code=409, detail="job is not running")
    return {"status": row.status, "error": row.error}


# --- News --------------------------------------------------------------------------------


class NewsArticleOut(BaseModel):
    id: str
    title: str
    publisher: str
    published_at: datetime
    url: str
    excerpt: str
    can_flag: bool  # published within 24 hours, so it can be marked as a reason to wait


class NewsStatusOut(BaseModel):
    state: str  # fresh | stale | empty | unavailable | pending
    refreshed_at: datetime | None
    refreshing: bool
    last_attempt_failed: bool


class NewsAiOut(BaseModel):
    summary: str
    cited: list[str]
    finished_at: datetime


class NewsRiskOut(BaseModel):
    article_id: str
    reason: str
    confirmed_at: datetime
    expires_at: datetime


class NewsOut(BaseModel):
    status: NewsStatusOut
    articles: list[NewsArticleOut]
    ai: NewsAiOut | None
    risk: NewsRiskOut | None


@app.get("/api/v1/news", response_model=NewsOut)
def news(session: SessionDep, asset: AssetDep) -> NewsOut:
    from gold_advisor import news_service
    from gold_advisor.persistence.models import AiAnalysisRow

    now = datetime.now(UTC)
    articles = news_service.recent_articles(session, asset)
    ids = {f"news-{a.provider_id}" for a in articles}
    latest_ai = session.execute(
        select(AiAnalysisRow.output, AiAnalysisRow.finished_at)
        .where(AiAnalysisRow.asset_id == asset.id, AiAnalysisRow.status == "succeeded")
        .order_by(AiAnalysisRow.finished_at.desc())
        .limit(1)
    ).first()
    ai = None
    if latest_ai and isinstance(latest_ai.output, dict) and (latest_ai.output.get("news_summary") or "").strip():
        cited = [c for c in latest_ai.output.get("news_citations") or [] if c in ids]
        if cited:  # only show an AI news summary whose sources are still listed
            ai = NewsAiOut(summary=latest_ai.output["news_summary"], cited=cited, finished_at=latest_ai.finished_at)
    active = news_service.active_risk(session, asset, now)
    st = news_service.status(session, asset, now)
    return NewsOut(
        status=NewsStatusOut(**{k: st[k] for k in ("state", "refreshed_at", "refreshing", "last_attempt_failed")}),
        articles=[
            NewsArticleOut(
                id=f"news-{a.provider_id}", title=a.title, publisher=a.publisher, published_at=a.published_at,
                url=a.url, excerpt=a.excerpt, can_flag=now - a.published_at < news_service.RISK_WINDOW,
            )
            for a in articles
        ],
        ai=ai,
        risk=(
            NewsRiskOut(
                article_id=f"news-{active.article.provider_id}" if active.article else "",
                reason=active.reason, confirmed_at=active.confirmed_at, expires_at=active.expires_at,
            )
            if active
            else None
        ),
    )


NEWS_REFRESH_COOLDOWN_SECONDS = 60


@app.post("/api/v1/news/refresh", status_code=status.HTTP_202_ACCEPTED)
def news_refresh(session: SessionDep, asset: AssetDep, response: Response) -> dict:
    from gold_advisor import news_service

    if not cooldown_passed(session, f"news_refresh:{asset.id}", NEWS_REFRESH_COOLDOWN_SECONDS):
        response.status_code = status.HTTP_429_TOO_MANY_REQUESTS
        response.headers["Retry-After"] = str(NEWS_REFRESH_COOLDOWN_SECONDS)
        return {"queued": False, "message": "News was refreshed less than a minute ago."}
    now = datetime.now(UTC)
    news_service.enqueue(session, asset, "manual", f"manual:{now:%Y%m%d%H%M}", now)
    session.commit()  # the GitHub run or Celery worker must see the job
    if dispatch_cycle():
        return {"queued": True, "message": "Looking for news. New articles appear in about 2–3 minutes."}
    from gold_advisor import tasks

    tasks.process_news.delay()
    return {"queued": True, "message": "Looking for news. New articles appear within a minute."}


class NewsRiskIn(BaseModel):
    article_id: Annotated[str, Field(pattern=r"^news-[0-9A-Za-z-]{8,64}$")]
    reason: Annotated[str, Field(min_length=1, max_length=300)]


@app.post("/api/v1/news/risk", response_model=NewsRiskOut)
def news_risk_confirm(session: SessionDep, asset: AssetDep, body: NewsRiskIn) -> NewsRiskOut:
    from gold_advisor import news_service

    now = datetime.now(UTC)
    try:
        row = news_service.confirm_risk(session, asset, body.article_id.removeprefix("news-"), body.reason, now)
    except news_service.RiskRejected as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return NewsRiskOut(article_id=body.article_id, reason=row.reason, confirmed_at=row.confirmed_at, expires_at=row.expires_at)


@app.post("/api/v1/news/risk/clear")
def news_risk_clear(session: SessionDep, asset: AssetDep) -> dict:
    from gold_advisor import news_service

    return {"cleared": news_service.clear_risk(session, asset, datetime.now(UTC))}
