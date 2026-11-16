"""Read-only /api/v1 resources over collected data. Requests never trigger provider calls."""

import sys
from pathlib import Path

# Vercel loads this file directly by path (pyproject [tool.vercel] entrypoint), without
# installing the package. Make src/ importable so "gold_advisor.*" imports resolve.
_SRC = str(Path(__file__).resolve().parent.parent)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel, Field, model_validator
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
SELF_AUTHENTICATED_PREFIXES = (
    "/api/v1/runner/",  # checked against the runner token instead
    "/api/v1/cron/",  # checked against the cron token: the outside timer never holds the internal token
)


@app.middleware("http")
async def require_internal_token(request, call_next):
    """In the cloud the API is public, so only the dashboard (which holds the token) may call it."""
    import hmac

    from fastapi.responses import JSONResponse

    from gold_advisor.config import get_settings as _settings

    token = _settings().internal_token
    path = request.url.path
    if token and path not in OPEN_PATHS and not path.startswith(SELF_AUTHENTICATED_PREFIXES):
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


# Indicator series for the chart. Same formulas as the analysis (analytics/indicators.py).
INDICATOR_FIELDS = (
    "sma_50", "sma_200", "bb_upper", "bb_middle", "bb_lower", "rsi_14", "macd", "macd_signal", "macd_hist",
    "stoch_k", "stoch_d", "adx_14", "plus_di", "minus_di", "atr_14", "realized_vol",
)
# Extra bars loaded before the visible window so the 200-bar average is defined from the first bar shown.
INDICATOR_WARMUP_BARS = 300


class IndicatorPointOut(BaseModel):
    bucket_start: datetime
    values: dict[str, float | None]


class IndicatorSeriesOut(BaseModel):
    instrument: str
    timeframe: Timeframe
    fields: list[str]
    points: list[IndicatorPointOut]


@app.get("/api/v1/indicators", response_model=IndicatorSeriesOut)
def indicator_series(
    session: SessionDep,
    asset: AssetDep,
    timeframe: Timeframe,
    limit: Annotated[int, Query(ge=1, le=1000)] = 192,
) -> IndicatorSeriesOut:
    import math

    import pandas as pd

    from gold_advisor.analytics import indicators

    try:
        query = market_data.MarketQuery(asset, timeframe, None, None, limit + INDICATOR_WARMUP_BARS)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    rows = market_data.candles(session, query)
    if not rows:
        return IndicatorSeriesOut(instrument=asset.instrument, timeframe=timeframe, fields=list(INDICATOR_FIELDS), points=[])
    bars = pd.DataFrame(
        [(r.bucket_start, float(r.open), float(r.high), float(r.low), float(r.close)) for r in rows],
        columns=["bucket_start", "open", "high", "low", "close"],
    ).set_index("bucket_start")
    ind = indicators.compute(bars, timeframe).tail(limit)

    def clean(value) -> float | None:
        number = float(value)
        return None if math.isnan(number) or math.isinf(number) else round(number, 4)

    return IndicatorSeriesOut(
        instrument=asset.instrument,
        timeframe=timeframe,
        fields=list(INDICATOR_FIELDS),
        points=[
            IndicatorPointOut(bucket_start=ts, values={f: clean(row[f]) for f in INDICATOR_FIELDS})
            for ts, row in ind.iterrows()
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
# Start a cycle from the timer or on page open only when the newest advice is older than this,
# and at most once per CYCLE_COOLDOWN_SECONDS (a cloud cycle takes 2-4 minutes).
ADVICE_MAX_AGE_SECONDS = 20 * 60
CYCLE_COOLDOWN_SECONDS = 600
RECENT_START = "an update was started less than 10 minutes ago"


def ensure_fresh(session: Session, now: datetime) -> tuple[bool, str]:
    """Start a cycle when the newest advice is over 20 minutes old, none was started in the last
    10 minutes, and it is not Saturday in Nepal. Returns (started, reason in plain words)."""
    from sqlalchemy import func

    from gold_advisor.cycle import nepal_saturday

    newest = session.scalar(select(func.max(AnalysisSnapshotRow.created_at)))
    if newest is not None and (now - newest).total_seconds() <= ADVICE_MAX_AGE_SECONDS:
        return False, f"advice is {max(0, round((now - newest).total_seconds() / 60))} minutes old"
    if nepal_saturday(now):
        return False, "Saturday in Nepal: no new prices to collect"
    if not cooldown_passed(session, "cycle", CYCLE_COOLDOWN_SECONDS):
        return False, RECENT_START
    if not dispatch_cycle(force_daily=False):
        return False, "cloud updates are not configured"
    return True, "update started"


class TickOut(BaseModel):
    started: bool
    reason: str
    # True when an update is running now: just started, or started by someone in the last 10 minutes.
    updating: bool = False


@app.post("/api/v1/cron/tick", response_model=TickOut)
def cron_tick(session: SessionDep, authorization: Annotated[str | None, Header()] = None) -> TickOut:
    """For the outside timer (cron-job.org, every 30 minutes). Bearer GA_CRON_TOKEN; 404 when unset."""
    import hmac

    from gold_advisor.config import get_settings as _settings

    token = _settings().cron_token
    if not token:
        raise HTTPException(status_code=404, detail="Not Found")
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(status_code=401, detail="not authorised")
    started, reason = ensure_fresh(session, datetime.now(UTC))
    return TickOut(started=started, reason=reason, updating=started or reason == RECENT_START)


@app.post("/api/v1/refresh/auto", response_model=TickOut)
def refresh_auto(session: SessionDep) -> TickOut:
    """Called once when the owner opens Today or Details, so old advice heals itself."""
    started, reason = ensure_fresh(session, datetime.now(UTC))
    return TickOut(started=started, reason=reason, updating=started or reason == RECENT_START)


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


class NepalNextOut(BaseModel):
    """Nepal's expected price at its next publication, with an 80% likely range."""

    publish_at: datetime
    estimate: float
    low: float
    high: float
    hours_ahead: float
    market_hours_ahead: float
    change_pct: float = 0.0
    basis: str


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
    nepal_next: NepalNextOut | None = None


class SourceStatusOut(BaseModel):
    dataset: str
    status: FreshnessStatus
    latest: datetime | date | None


class NextEventOut(BaseModel):
    title: str
    scheduled_at: datetime
    hours_away: float
    forces_wait: bool = True  # FOMC decisions force WAIT within 24 h; US data releases are shown as a risk only


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
    tradable: bool = False


class PositionOut(BaseModel):
    nepal_price: float | None
    nepal_low: float | None
    nepal_low_date: date | None
    nepal_high: float | None
    nepal_high_date: date | None
    nepal_window_start: date | None
    nepal_publications: int
    above_low_npr: float | None
    below_high_npr: float | None
    world_price: float | None
    world_52w_low: float | None
    world_52w_high: float | None
    days_since_52w_low: int | None
    plain: str | None


class KeyLevelOut(BaseModel):
    kind: Literal["floor", "ceiling"]
    timeframe: str
    world_price: float
    rupees: float | None  # world_price x rupees_per_usd_oz, rounded
    touches: int
    manual: bool
    state: str


class SplitOut(BaseModel):
    """Present when a BUY in a falling market becomes "buy half now"."""

    reason: str
    dip_npr: float | None
    recovery_npr: float | None
    deadline: date
    deadline_reason: str
    triggers: list[str]


class SecondHalfOut(BaseModel):
    first_part_at: datetime
    first_part_price: float | None
    dip_npr: float | None
    recovery_npr: float | None
    deadline: date | None
    reached: str | None
    plain: str


class AnnouncementOut(BaseModel):
    event_type: str
    title: str
    scheduled_at: datetime
    importance: str
    plain: str


class AnnouncementsOut(BaseModel):
    calendar_stale: bool
    items: list[AnnouncementOut]


class DashboardOut(BaseModel):
    """Plain-language summary first. Technical detail lives at ``/snapshots/{id}``."""

    asset: AssetOut
    snapshot_id: str
    created_at: datetime
    age_seconds: float  # now minus created_at, at request time
    market_open: bool  # the world market, at request time
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
    # Concrete answers (rules-7 snapshots onward; older snapshots give the defaults).
    position: PositionOut | None = None
    key_levels: list[KeyLevelOut] = []
    rupees_per_usd_oz: float | None = None
    split: SplitOut | None = None
    second_half: SecondHalfOut | None = None
    announcements: AnnouncementsOut | None = None


class NewsRiskOverrideOut(BaseModel):
    """Present only when an owner-confirmed news risk changed BUY into WAIT."""

    original_decision: str
    reason: str
    expires_at: datetime
    article_title: str | None
    article_publisher: str | None
    article_url: str | None


class LiveOut(BaseModel):
    """World price now. ``available`` is false when no source gave a recent price; then no numbers
    are returned, so an older price is never shown as live."""

    available: bool
    market_open: bool
    price: float | None = None
    observed_at: datetime | None = None
    age_seconds: float | None = None
    source: Source | None = None
    nepal_next: NepalNextOut | None = None


@app.get("/api/v1/live", response_model=LiveOut)
def live_price(session: SessionDep, asset: AssetDep) -> LiveOut:
    """Never writes a snapshot or changes the decision. At most one upstream call per asset per 60 s."""
    from gold_advisor import live

    now = datetime.now(UTC)
    market_open = asset.calendar.is_open(now)
    row = live.latest(session, asset)
    if live.needs_fetch(row.observed_at if row else None, now, asset):
        with session_scope() as write:
            allowed = cooldown_passed(write, f"live:{asset.id}", int(live.CACHE.total_seconds()))
        if allowed and live.fetch(asset, now) is not None:
            row = live.latest(session, asset)
    if row is None or not live.is_live(row.observed_at, now, asset):
        return LiveOut(available=False, market_open=market_open)
    price = float(row.price)
    nxt = live.estimate(session, asset, price, now)
    return LiveOut(
        available=True,
        market_open=market_open,
        price=price,
        observed_at=row.observed_at,
        age_seconds=round(max(0.0, (now - row.observed_at).total_seconds()), 1),
        source=Source(row.source),
        nepal_next=NepalNextOut(**asdict(nxt)) if nxt else None,
    )


def _latest_snapshot(session: Session, asset: AssetDefinition) -> AnalysisSnapshotRow:
    row = market_data.latest_snapshot(session, asset)
    if row is None:
        raise HTTPException(status_code=404, detail="no analysis has run yet")
    return row


def _status_now(source: dict, now: datetime, asset: AssetDefinition) -> FreshnessStatus:
    """A snapshot's stored source status is frozen at snapshot time; judge it again at ``now`` so an
    old snapshot never says "up to date"."""
    again = freshness.for_dataset(
        source["dataset"], source.get("latest_observation"), now, asset.calendar,
        (source.get("collector") or {}).get("last_success_at"),
    )
    return again.status if again is not None else FreshnessStatus(source["freshness"]["status"])


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
        age_seconds=round((now - row.created_at).total_seconds(), 1),
        market_open=asset.calendar.is_open(now),
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
            nepal_next=p["prices"].get("nepal_next"),
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
            SourceStatusOut(dataset=s["dataset"], status=_status_now(s, now, asset), latest=s["latest_observation"])
            for s in p["sources"]
        ],
        news_risk=NewsRiskOverrideOut(**override) if override else None,
        position=PositionOut(**p["position"]) if p.get("position") else None,
        key_levels=[KeyLevelOut(**k) for k in p.get("key_levels") or []],
        rupees_per_usd_oz=p.get("rupees_per_usd_oz"),
        split=_split_out(p.get("split")) if d["decision"] == "BUY" else None,
        second_half=SecondHalfOut(**p["second_half"]) if p.get("second_half") else None,
        announcements=AnnouncementsOut(**p["announcements"]) if p.get("announcements") else None,
    )


def _split_out(raw: dict | None) -> SplitOut | None:
    from gold_advisor.decision import split

    if not raw:
        return None
    deadline = date.fromisoformat(raw["deadline"][:10])
    return SplitOut(**{**raw, "deadline": deadline}, triggers=split.triggers_plain(raw.get("dip_npr"), raw.get("recovery_npr"), deadline))


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


class TrackForecastRowOut(BaseModel):
    rate_date: date
    estimate: float
    low: float
    high: float
    actual: float
    error_npr: float
    error_pct: float
    inside_range: bool
    hours_before: float
    snapshot_at: datetime


class TrackForecastSummaryOut(BaseModel):
    count: int
    mean_abs_error_pct: float | None
    mean_abs_error_npr: float | None
    inside_range: int
    small_sample: bool


class TrackAdviceRowOut(BaseModel):
    rate_date: date
    decision: str
    rule: str | None
    price: float
    advice_at: datetime
    later_count: int
    later_low: float | None
    later_high: float | None
    later_last: float | None
    open: bool
    outcome: str
    good: bool | None


class TrackAdviceSummaryOut(BaseModel):
    days: int
    status: str
    windows: int
    windows_needed: int
    buys: int
    mean_cost_vs_immediate: float | None


class TrackForecastOut(BaseModel):
    summary: TrackForecastSummaryOut
    rows: list[TrackForecastRowOut]


class TrackAdviceOut(BaseModel):
    summary: TrackAdviceSummaryOut
    rows: list[TrackAdviceRowOut]


class TrackRecordOut(BaseModel):
    """Computed at request time from stored snapshots and published prices. Rows newest first."""

    asset: AssetOut
    forecast: TrackForecastOut
    advice: TrackAdviceOut


@app.get("/api/v1/track-record", response_model=TrackRecordOut)
def track_record(session: SessionDep, asset: AssetDep, limit: Annotated[int, Query(ge=1, le=400)] = 60) -> TrackRecordOut:
    from datetime import timedelta
    from types import SimpleNamespace

    from gold_advisor.analytics import track_record as tr
    from gold_advisor.domain import Decision

    pub_rows = session.execute(
        select(LocalMetalRateRow.rate_date, LocalMetalRateRow.published_at, LocalMetalRateRow.price_npr)
        .where(
            LocalMetalRateRow.source == Source.FENEGOSIDA.value,
            LocalMetalRateRow.metal == asset.metal.value,
            LocalMetalRateRow.purity == asset.purity.value,
            LocalMetalRateRow.unit == MassUnit.TOLA.value,
        )
        .order_by(LocalMetalRateRow.rate_date.desc())
        .limit(limit)
    ).all()
    publications = [tr.Publication(d, at, float(p)) for d, at, p in pub_rows]
    snapshots: list[tr.Snapshot] = []
    if publications:
        since = datetime.combine(min(p.rate_date for p in publications) - timedelta(days=3), datetime.min.time(), tzinfo=UTC)
        # Only the parts used here, not the full ~11 kB payloads.
        for created_at, prices, decision in session.execute(
            select(AnalysisSnapshotRow.created_at, AnalysisSnapshotRow.payload["prices"], AnalysisSnapshotRow.payload["decision"])
            .where(AnalysisSnapshotRow.asset_id == asset.id, AnalysisSnapshotRow.created_at >= since)
            .order_by(AnalysisSnapshotRow.created_at)
        ):
            p = market_data.normalized_payload(SimpleNamespace(payload={"prices": prices or {}, "decision": decision or {}}))
            latest, nxt, d = p["prices"].get("nepal_latest") or {}, p["prices"].get("nepal_next") or {}, p["decision"]
            snapshots.append(
                tr.Snapshot(
                    created_at=created_at,
                    nepal_rate_date=date.fromisoformat(latest["rate_date"][:10]) if latest.get("rate_date") else None,
                    next_estimate=nxt.get("estimate"),
                    next_low=nxt.get("low"),
                    next_high=nxt.get("high"),
                    decision=Decision(d["decision"]) if d.get("decision") in Decision._value2member_map_ else None,
                    rule=d.get("rule"),
                )
            )
    # Outcomes need the 5 publications after each day, so they come from the same list.
    forecast_rows = tr.forecast_rows(publications, snapshots)
    advice_rows = tr.advice_rows(publications, snapshots)
    return TrackRecordOut(
        asset=AssetOut(**asset.public()),
        forecast=TrackForecastOut(
            summary=TrackForecastSummaryOut(**asdict(tr.forecast_summary(forecast_rows))),
            rows=[TrackForecastRowOut(**asdict(r)) for r in forecast_rows],
        ),
        advice=TrackAdviceOut(
            summary=TrackAdviceSummaryOut(**asdict(tr.advice_summary(advice_rows))),
            rows=[TrackAdviceRowOut(**asdict(r)) for r in advice_rows],
        ),
    )


class PlanOut(BaseModel):
    waiting_since: datetime | None
    completed_at: datetime | None
    first_part_at: datetime | None = None
    first_part_price: float | None = None
    second_dip_npr: float | None = None
    second_recovery_npr: float | None = None
    second_deadline: date | None = None


def _plan_out(plan: PurchasePlanRow | None) -> PlanOut:
    if plan is None:
        return PlanOut(waiting_since=None, completed_at=None)
    num = lambda v: float(v) if v is not None else None  # noqa: E731
    return PlanOut(
        waiting_since=plan.waiting_since,
        completed_at=plan.completed_at,
        first_part_at=plan.first_part_at,
        first_part_price=num(plan.first_part_price),
        second_dip_npr=num(plan.second_dip_npr),
        second_recovery_npr=num(plan.second_recovery_npr),
        second_deadline=plan.second_deadline,
    )


@app.get("/api/v1/plan", response_model=PlanOut)
def get_plan(session: SessionDep, asset: AssetDep) -> PlanOut:
    return _plan_out(session.get(PurchasePlanRow, asset.id))


@app.post("/api/v1/plan/{action}", response_model=PlanOut)
def update_plan(session: SessionDep, asset: AssetDep, action: Annotated[str, Path(pattern="^(purchased|restart|first_part)$")]) -> PlanOut:
    """``purchased`` closes the plan; ``restart`` starts a new one; ``first_part`` records the first
    half of a two-part purchase and keeps the latest advice's second-half triggers. Nothing else
    resets the clock, and ``first_part`` does not."""
    now = datetime.now(UTC)
    plan = session.get(PurchasePlanRow, asset.id) or PurchasePlanRow(asset_id=asset.id)
    if action == "purchased":
        plan.completed_at = now
    elif action == "first_part":
        payload = market_data.normalized_payload(_latest_snapshot(session, asset))
        raw = payload.get("split")
        if not raw or payload["decision"]["decision"] != "BUY":
            raise HTTPException(status_code=409, detail="The latest advice is not to buy in two parts.")
        latest = payload["prices"].get("nepal_latest") or {}
        plan.first_part_at = now
        plan.first_part_price = latest.get("nepal_price")
        plan.second_dip_npr, plan.second_recovery_npr = raw.get("dip_npr"), raw.get("recovery_npr")
        plan.second_deadline = date.fromisoformat(raw["deadline"][:10])
    else:
        plan.waiting_since, plan.completed_at = None, None
        plan.first_part_at = plan.first_part_price = None
        plan.second_dip_npr = plan.second_recovery_npr = plan.second_deadline = None
    plan.updated_at = now
    session.add(plan)
    session.flush()
    out = _plan_out(plan)
    session.commit()  # the page reloads straight after
    return out


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


# Lines the owner draws on the full-screen chart. Anchored by time and price, so one set shows on
# every timeframe. Stored per asset in app_settings; they never feed the analysis.
DRAWING_POINTS = {"trend": 2, "horizontal": 1, "rectangle": 2, "fib": 2}


class DrawingPoint(BaseModel):
    time: Annotated[int, Field(ge=946684800, le=4102444800)]  # Unix seconds, 2000 to 2100
    price: Annotated[float, Field(gt=0, lt=1_000_000)]


class Drawing(BaseModel):
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")]
    kind: Literal["trend", "horizontal", "rectangle", "fib"]
    points: list[DrawingPoint] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def _point_count(self) -> "Drawing":
        if len(self.points) != DRAWING_POINTS[self.kind]:
            raise ValueError(f"a {self.kind} drawing needs {DRAWING_POINTS[self.kind]} point(s)")
        return self


class DrawingsIn(BaseModel):
    drawings: list[Drawing] = Field(max_length=100)


@app.get("/api/v1/settings/drawings", response_model=DrawingsIn)
def get_drawings(session: SessionDep, asset: AssetDep) -> DrawingsIn:
    row = session.get(AppSettingRow, f"drawings:{asset.id}")
    return DrawingsIn(drawings=row.value.get("value", []) if row else [])


@app.put("/api/v1/settings/drawings", response_model=DrawingsIn)
def put_drawings(session: SessionDep, asset: AssetDep, body: DrawingsIn) -> DrawingsIn:
    key = f"drawings:{asset.id}"
    row = session.get(AppSettingRow, key) or AppSettingRow(key=key, value={})
    row.value = {"value": [d.model_dump() for d in body.drawings]}
    row.updated_at = datetime.now(UTC)
    session.add(row)
    return body


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


# --- Silver trading (Trade screen) ------------------------------------------------------
# The app never places orders: it shows a plan and records what the owner says they did.


def tradable_asset(asset: AssetDep) -> AssetDefinition:
    if not asset.tradable:
        raise HTTPException(status_code=404, detail="Trading is only for silver.")
    return asset


TradableDep = Annotated[AssetDefinition, Depends(tradable_asset)]


class TradeSettingsIn(BaseModel):
    budget: Annotated[float, Field(ge=1000, le=10_000_000)] = 100_000
    gap_pct: Annotated[float | None, Field(ge=0, le=20)] = None  # the shop's buy-back gap; no default


class TradeIn(BaseModel):
    side: Literal["buy", "sell"]
    quantity_tola: Annotated[float, Field(gt=0, le=10_000)]
    price_npr: Annotated[float, Field(gt=0, le=10_000_000)]
    traded_at: datetime
    note: Annotated[str, Field(max_length=300)] = ""


class TradeRecordOut(TradeIn):
    id: int


class TradePositionOut(BaseModel):
    quantity_tola: float
    cost_npr: float
    average_price_npr: float | None
    value_after_gap_npr: float | None  # at the latest Nepal price less the buy-back gap
    unrealised_npr: float | None
    realised_npr: float  # sales as entered minus average cost
    parts: int


class TradeReplayRowOut(BaseModel):
    gap_pct: float
    trades: int
    winning: int
    share_winning: float | None
    total_npr: float
    open_at_end: bool
    first_day: str | None
    last_day: str | None


class TradeReplayOut(BaseModel):
    computed_at: datetime | None
    budget_npr: float
    results: list[TradeReplayRowOut]


class TradeOut(BaseModel):
    asset: AssetOut
    approved: bool  # false: the rule is a trial until the owner approves the replay numbers
    state: str | None
    plain: str | None
    budget_npr: float
    gap_pct: float | None
    nepal_price: float | None
    nepal_date: date | None
    second_npr: float | None
    target_npr: float | None
    cut_npr: float | None
    half_quantity_tola: float | None
    profit_at_target_npr: float | None
    loss_at_cut_npr: float | None
    position: TradePositionOut
    replay: TradeReplayOut | None
    snapshot_created_at: datetime | None
    trades: list[TradeRecordOut]


@app.get("/api/v1/trade", response_model=TradeOut)
def trade_overview(session: SessionDep, asset: TradableDep) -> TradeOut:
    from gold_advisor import analysis, trading
    from gold_advisor.persistence.models import TradeRow

    budget, gap = analysis.trade_settings(session, asset)
    held = analysis.trade_book(session, asset)
    row = market_data.latest_snapshot(session, asset)
    p = market_data.normalized_payload(row) if row else {"prices": {}}
    latest = p["prices"].get("nepal_latest") or {}
    price = latest.get("nepal_price")
    factor = p.get("rupees_per_usd_oz")
    raw = p.get("trade_plan") or {}
    money, state, plain = {}, None, None
    if raw.get("facts"):
        facts = trading.MarketFacts(**{**raw["facts"], "levels": tuple(raw["facts"]["levels"])})
        plan = trading.plan(facts, analysis.trade_holding(session, asset, held, factor))
        money, state, plain = trading.money(plan, price, factor, asset.level_rupee_step, budget, gap, held), plan.state, plan.plain
    value = round(held.quantity_tola * price * (1 - gap), 2) if (gap is not None and price and held.quantity_tola) else None
    stored = session.get(AppSettingRow, f"trade_replay:{asset.id}")
    replay = None
    if stored is not None:
        v = stored.value.get("value", {})
        replay = TradeReplayOut(computed_at=v.get("computed_at"), budget_npr=v.get("budget_npr", budget),
                                results=[TradeReplayRowOut(**r) for r in v.get("results", [])])
    rows = session.scalars(select(TradeRow).where(TradeRow.asset_id == asset.id).order_by(TradeRow.traded_at.desc())).all()
    return TradeOut(
        asset=AssetOut(**asset.public()),
        approved=trading.APPROVED,
        state=state,
        plain=plain,
        budget_npr=budget,
        gap_pct=gap * 100 if gap is not None else None,
        nepal_price=price,
        nepal_date=latest.get("rate_date"),
        second_npr=money.get("second_npr"),
        target_npr=money.get("target_npr"),
        cut_npr=money.get("cut_npr"),
        half_quantity_tola=money.get("half_quantity_tola"),
        profit_at_target_npr=money.get("profit_at_target_npr"),
        loss_at_cut_npr=money.get("loss_at_cut_npr"),
        position=TradePositionOut(
            quantity_tola=held.quantity_tola,
            cost_npr=held.cost_npr,
            average_price_npr=round(held.cost_npr / held.quantity_tola, 2) if held.quantity_tola else None,
            value_after_gap_npr=value,
            unrealised_npr=round(value - held.cost_npr, 2) if value is not None else None,
            realised_npr=held.realised_npr,
            parts=held.parts,
        ),
        replay=replay,
        snapshot_created_at=row.created_at if row else None,
        trades=[
            TradeRecordOut(id=r.id, side=r.side, quantity_tola=float(r.quantity_tola), price_npr=float(r.price_npr),
                           traded_at=r.traded_at, note=r.note)
            for r in rows
        ],
    )


@app.put("/api/v1/trade/settings", response_model=TradeSettingsIn)
def put_trade_settings(session: SessionDep, asset: TradableDep, body: TradeSettingsIn) -> TradeSettingsIn:
    key = f"trade:{asset.id}"
    row = session.get(AppSettingRow, key) or AppSettingRow(key=key, value={})
    row.value, row.updated_at = {"value": body.model_dump()}, datetime.now(UTC)
    session.add(row)
    session.commit()  # the page reloads straight after; don't race the dependency's commit
    return body


@app.post("/api/v1/trade/trades", response_model=TradeRecordOut)
def add_trade(session: SessionDep, asset: TradableDep, body: TradeIn) -> TradeRecordOut:
    from gold_advisor.persistence.models import TradeRow

    row = TradeRow(asset_id=asset.id, **body.model_dump())
    session.add(row)
    session.flush()
    trade_id = row.id
    session.commit()
    return TradeRecordOut(id=trade_id, **body.model_dump())


@app.put("/api/v1/trade/trades/{trade_id}", response_model=TradeRecordOut)
def correct_trade(session: SessionDep, asset: TradableDep, trade_id: int, body: TradeIn) -> TradeRecordOut:
    from gold_advisor.persistence.models import TradeRow

    row = session.get(TradeRow, trade_id)
    if row is None or row.asset_id != asset.id:
        raise HTTPException(status_code=404, detail="trade not found")
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    row.updated_at = datetime.now(UTC)
    session.commit()
    return TradeRecordOut(id=trade_id, **body.model_dump())


@app.delete("/api/v1/trade/trades/{trade_id}")
def delete_trade(session: SessionDep, asset: TradableDep, trade_id: int) -> dict:
    """The owner's own record, entered by mistake. Market data is never deleted."""
    from gold_advisor.persistence.models import TradeRow

    row = session.get(TradeRow, trade_id)
    if row is None or row.asset_id != asset.id:
        raise HTTPException(status_code=404, detail="trade not found")
    session.delete(row)
    session.commit()
    return {"deleted": trade_id}


# --- Browser notifications (Web Push) ----------------------------------------------------


class PushKeys(BaseModel):
    p256dh: Annotated[str, Field(min_length=10, max_length=200, pattern=r"^[A-Za-z0-9_=-]+$")]
    auth: Annotated[str, Field(min_length=10, max_length=200, pattern=r"^[A-Za-z0-9_=-]+$")]


class PushSubscriptionIn(BaseModel):
    endpoint: Annotated[str, Field(min_length=12, max_length=2000, pattern=r"^https://")]
    keys: PushKeys


class PushEndpointIn(BaseModel):
    endpoint: Annotated[str, Field(min_length=12, max_length=2000, pattern=r"^https://")]


class AlertSettingsIn(BaseModel):
    kinds: dict[str, bool]


class PushStatusOut(BaseModel):
    enabled: bool
    subscribed: bool
    kinds: dict[str, str]  # kind -> plain label
    settings: dict[str, bool]


def _push_enabled() -> None:
    from gold_advisor import alerts

    if not alerts.enabled():
        raise HTTPException(status_code=404, detail="Notifications are not set up.")


@app.post("/api/v1/push/status", response_model=PushStatusOut)
def push_status(session: SessionDep, body: PushEndpointIn | None = None) -> PushStatusOut:
    """POST so the endpoint URL (a capability) never lands in access logs as a query string."""
    from gold_advisor import alerts
    from gold_advisor.persistence.models import PushSubscriptionRow

    subscribed = False
    if body is not None:
        subscribed = session.scalar(select(PushSubscriptionRow.id).where(PushSubscriptionRow.endpoint == body.endpoint)) is not None
    from gold_advisor.decision import split

    kinds = {k: v for k, v in alerts.KINDS.items() if k != "second_half" or split.ENABLED}
    return PushStatusOut(enabled=alerts.enabled(), subscribed=subscribed, kinds=kinds, settings=alerts.settings(session))


@app.post("/api/v1/push/subscriptions")
def push_subscribe(session: SessionDep, body: PushSubscriptionIn) -> dict:
    from sqlalchemy.dialects.postgresql import insert

    from gold_advisor.persistence.models import PushSubscriptionRow

    _push_enabled()
    session.execute(
        insert(PushSubscriptionRow)
        .values(endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth)
        .on_conflict_do_update(index_elements=["endpoint"], set_={"p256dh": body.keys.p256dh, "auth": body.keys.auth, "failure_count": 0})
    )
    session.commit()
    return {"subscribed": True}


@app.post("/api/v1/push/subscriptions/remove")
def push_unsubscribe(session: SessionDep, body: PushEndpointIn) -> dict:
    from sqlalchemy import delete

    from gold_advisor.persistence.models import PushSubscriptionRow

    session.execute(delete(PushSubscriptionRow).where(PushSubscriptionRow.endpoint == body.endpoint))
    session.commit()
    return {"subscribed": False}


PUSH_TEST_COOLDOWN_SECONDS = 30


@app.post("/api/v1/push/test")
def push_test(session: SessionDep, body: PushEndpointIn, response: Response) -> dict:
    from gold_advisor import alerts

    _push_enabled()
    if not cooldown_passed(session, "push_test", PUSH_TEST_COOLDOWN_SECONDS):
        response.status_code = status.HTTP_429_TOO_MANY_REQUESTS
        return {"sent": 0, "message": "A test was sent a moment ago."}
    sent = alerts.send(session, "Test from Metal Advisor", "Notifications work on this device.", "/", endpoints=[body.endpoint])
    return {"sent": sent, "message": "Sent. It should appear in a few seconds." if sent else "This device isn't subscribed any more. Turn notifications on again."}


@app.put("/api/v1/settings/alerts")
def put_alert_settings(session: SessionDep, body: AlertSettingsIn) -> dict:
    from gold_advisor import alerts

    value = {k: bool(v) for k, v in body.kinds.items() if k in alerts.KINDS}
    row = session.get(AppSettingRow, alerts.SETTINGS_KEY) or AppSettingRow(key=alerts.SETTINGS_KEY, value={})
    row.value, row.updated_at = {"value": {**alerts.settings(session), **value}}, datetime.now(UTC)
    session.add(row)
    out = row.value["value"]
    session.commit()
    return {"settings": out}
