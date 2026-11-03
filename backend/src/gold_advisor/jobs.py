"""Collection jobs: fetch from a source, persist, and record the run.

Each job is idempotent, so overlapping windows and retries are safe. The run record is
written in its own transaction so a failed collection is still visible in source health.
"""

import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from gold_advisor.assets import ASSETS, AssetDefinition, GOLD
from gold_advisor.collectors import dukascopy, fenegosida, fomc, fred, gold_api, nrb, swissquote
from gold_advisor.collectors.http import make_client
from gold_advisor.collectors.types import Candle, CollectionResult
from gold_advisor.config import get_settings
from gold_advisor.domain import (
    DERIVED_TIMEFRAMES,
    NEPAL_TZ,
    UTC,
    Instrument,
    MassUnit,
    Metal,
    PriceSide,
    Purity,
    RunStatus,
    Source,
    Timeframe,
)
from gold_advisor.market import is_xau_open, last_open_instant
from gold_advisor.persistence import repository
from gold_advisor.persistence.db import session_scope
from gold_advisor.persistence.models import (
    CandleRow,
    CollectionRunRow,
    FxRateRow,
    LocalMetalRateRow,
    MacroObservationRow,
)
from gold_advisor.resample import bucket_start, derive

log = logging.getLogger(__name__)

# How far back each incremental run re-reads, so late revisions are picked up.
CANDLE_OVERLAP_BARS = 3
FX_OVERLAP_DAYS = 3
MACRO_OVERLAP_DAYS = 30
NEPAL_HISTORY_PAUSE_SECONDS = 1.0
CANDLE_CHUNK = {Timeframe.M15: timedelta(days=15), Timeframe.H1: timedelta(days=60), Timeframe.D1: timedelta(days=730)}


def _now() -> datetime:
    return datetime.now(UTC)


def run_job(job: str, source: Source, work: Callable[[], CollectionResult]) -> CollectionResult:
    with session_scope() as session:
        run = CollectionRunRow(source=source.value, job=job, status=RunStatus.RUNNING.value, started_at=_now())
        session.add(run)
    try:
        result = work()
    except Exception as exc:
        log.exception("job %s failed", job)
        with session_scope() as session:
            row = session.get(CollectionRunRow, run.id)
            row.status, row.finished_at, row.error = RunStatus.FAILED.value, _now(), f"{type(exc).__name__}: {exc}"[:2000]
        raise
    with session_scope() as session:
        row = session.get(CollectionRunRow, run.id)
        row.status, row.finished_at = RunStatus.SUCCESS.value, _now()
        row.rows_inserted, row.rows_revised, row.rows_unchanged = result.inserted, result.revised, result.unchanged
        row.notes = sorted(set(result.notes))[:50]
    return result


# --- Live spot ---------------------------------------------------------------------------


def _spot_job(source: Source, fetch, asset: AssetDefinition = GOLD) -> CollectionResult:
    def work() -> CollectionResult:
        with make_client() as client:
            quote = fetch(client, now=_now(), asset=asset)
        with session_scope() as session:
            return repository.save_spot_quote(session, quote)

    return run_job(asset.job(f"{source.value}.spot"), source, work)


def collect_gold_spot(asset: AssetDefinition = GOLD) -> CollectionResult:
    """Gold API first; Swissquote only when Gold API fails. Each price keeps its source."""
    try:
        return _spot_job(Source.GOLD_API, gold_api.fetch, asset)
    except Exception:  # noqa: BLE001 - failure already recorded in collection_runs
        return _spot_job(Source.SWISSQUOTE, swissquote.fetch, asset)


# --- Nepal published rates ---------------------------------------------------------------


def _nepal_today() -> date:
    return _now().astimezone(NEPAL_TZ).date()


def has_nepal_rate_for(day: date, asset: AssetDefinition = GOLD) -> bool:
    with session_scope() as session:
        return session.scalar(
            select(func.count()).where(
                LocalMetalRateRow.source == Source.FENEGOSIDA.value,
                LocalMetalRateRow.metal == asset.metal.value,
                LocalMetalRateRow.purity == asset.purity.value,
                LocalMetalRateRow.unit == MassUnit.TOLA.value,
                LocalMetalRateRow.rate_date == day,
            )
        ) > 0


def has_usd_rate_for(day: date) -> bool:
    with session_scope() as session:
        return session.scalar(
            select(func.count()).where(
                FxRateRow.source == Source.NRB.value, FxRateRow.currency == "USD", FxRateRow.rate_date == day
            )
        ) > 0


def _skipped(reason: str) -> CollectionResult:
    return CollectionResult(notes=[f"skipped: {reason}"])


def collect_nepal_today(force: bool = False) -> CollectionResult:
    """Nepal publishes once a day. Scheduled runs stop calling the source once today's rate
    is stored; ``force`` (the refresh button) always calls it, which also picks up corrections."""
    if not force and all(has_nepal_rate_for(_nepal_today(), asset) for asset in ASSETS.values() if asset.metal is not None):
        return _skipped("today's Nepal rate already stored")

    def work() -> CollectionResult:
        from gold_advisor import news_service

        with fenegosida.make_fenegosida_client() as client:
            rates, notes = fenegosida.fetch_today(client)
        today = _nepal_today()
        with session_scope() as session:
            before = news_service.today_prices(session, today)
            result = repository.save_local_rates(session, rates)
            # Same transaction: a news job exists exactly when today's price was inserted or revised.
            queued = news_service.enqueue_for_price_changes(session, before, news_service.today_prices(session, today), today, _now())
        result.notes.extend(notes)
        result.notes.extend(f"news refresh queued for {asset_id}" for asset_id in queued)
        return result

    return run_job("fenegosida.today", Source.FENEGOSIDA, work)


def _month_starts_back(today: date, months: int) -> list[date]:
    out, year, month = [], today.year, today.month
    for _ in range(months):
        out.append(date(year, month, 1))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return out


def collect_nepal_history(months: int | None = None) -> CollectionResult:
    months = months or get_settings().backfill_nepal_months

    def work() -> CollectionResult:
        total = CollectionResult()
        with fenegosida.make_fenegosida_client() as client:
            for month_start in _month_starts_back(_now().astimezone(NEPAL_TZ).date(), months):
                rates, notes = fenegosida.fetch_month(client, month_start)
                with session_scope() as session:
                    total.add(repository.save_local_rates(session, rates))
                total.notes.extend(notes)
                time.sleep(NEPAL_HISTORY_PAUSE_SECONDS)
        return total

    return run_job("fenegosida.history", Source.FENEGOSIDA, work)


# --- NRB USD/NPR -------------------------------------------------------------------------


def collect_fx(force: bool = False) -> CollectionResult:
    """NRB publishes once a day; same skip rule as ``collect_nepal_today``."""
    if not force and has_usd_rate_for(_nepal_today()):
        return _skipped("today's NRB rate already stored")

    def work() -> CollectionResult:
        today = _nepal_today()
        with session_scope() as session:
            latest = session.scalar(
                select(func.max(FxRateRow.rate_date)).where(FxRateRow.source == Source.NRB.value)
            )
        start = latest - timedelta(days=FX_OVERLAP_DAYS) if latest else today - timedelta(days=get_settings().backfill_fx_days)
        total = CollectionResult()
        with nrb.make_nrb_client() as client:
            for rates in nrb.fetch_range(client, start, today):
                with session_scope() as session:
                    total.add(repository.save_fx_rates(session, rates))
        return total

    return run_job("nrb.fx", Source.NRB, work)


# --- FRED yields -------------------------------------------------------------------------


def collect_macro() -> CollectionResult:
    settings = get_settings()

    def work() -> CollectionResult:
        total = CollectionResult()
        today = _now().date()
        with make_client() as client:
            for series_id in settings.fred_series:
                with session_scope() as session:
                    latest = session.scalar(
                        select(func.max(MacroObservationRow.obs_date)).where(
                            MacroObservationRow.source == Source.FRED.value,
                            MacroObservationRow.series_id == series_id,
                        )
                    )
                start = (
                    latest - timedelta(days=MACRO_OVERLAP_DAYS)
                    if latest
                    else today.replace(year=today.year - settings.backfill_macro_years)
                )
                observations = fred.fetch(client, series_id, start)
                with session_scope() as session:
                    total.add(repository.save_macro(session, observations))
        return total

    return run_job("fred.yields", Source.FRED, work)


# --- Dukascopy candles and derived bars --------------------------------------------------


def _backfill_start(timeframe: Timeframe, now: datetime) -> datetime:
    s = get_settings()
    window = {
        Timeframe.M15: timedelta(days=s.backfill_m15_days),
        Timeframe.H1: timedelta(days=s.backfill_hourly_days),
        Timeframe.D1: timedelta(days=365 * s.backfill_daily_years),
    }[timeframe]
    return bucket_start(now - window, Timeframe.D1)


def _latest_bucket(timeframe: Timeframe, asset: AssetDefinition = GOLD) -> datetime | None:
    with session_scope() as session:
        return session.scalar(
            select(func.max(CandleRow.bucket_start)).where(
                CandleRow.source == Source.DUKASCOPY.value,
                CandleRow.instrument == asset.instrument,
                CandleRow.timeframe == timeframe.value,
            )
        )


def collect_candles(timeframe: Timeframe, asset: AssetDefinition = GOLD) -> CollectionResult:
    def work() -> CollectionResult:
        now = _now()
        latest = _latest_bucket(timeframe, asset)
        start = latest - CANDLE_OVERLAP_BARS * timeframe.duration if latest else _backfill_start(timeframe, now)
        total = CollectionResult()
        chunk_start = start
        while chunk_start < now:
            chunk_end = min(now, chunk_start + CANDLE_CHUNK[timeframe])
            candles = dukascopy.fetch(timeframe, chunk_start, chunk_end, now=now, asset=asset)
            with session_scope() as session:
                total.add(repository.save_candles(session, candles))
            chunk_start = chunk_end
        for target, underlying in DERIVED_TIMEFRAMES.items():
            if underlying is timeframe:
                total.add(_derive(target, now, asset))
        return total

    return run_job(asset.job(f"dukascopy.{timeframe.value}"), Source.DUKASCOPY, work)


def _derive(target: Timeframe, now: datetime, asset: AssetDefinition = GOLD) -> CollectionResult:
    underlying_tf = DERIVED_TIMEFRAMES[target]
    latest_derived = _latest_bucket(target, asset)
    with session_scope() as session:
        query = select(CandleRow).where(
            CandleRow.source == Source.DUKASCOPY.value,
            CandleRow.instrument == asset.instrument,
            CandleRow.timeframe == underlying_tf.value,
        )
        if latest_derived is not None:
            query = query.where(CandleRow.bucket_start >= latest_derived - CANDLE_OVERLAP_BARS * target.duration)
        rows = session.scalars(query.order_by(CandleRow.bucket_start)).all()
    bars = [
        Candle(
            source=Source(r.source),
            instrument=r.instrument,
            timeframe=underlying_tf,
            bucket_start=r.bucket_start,
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            volume=r.volume,
            price_side=PriceSide(r.price_side),
        )
        for r in rows
    ]
    if not bars:
        return CollectionResult(notes=[f"no {underlying_tf} bars to derive {target}"])
    complete_through = max(b.bucket_end for b in bars)
    # Over a market closure no further bars will arrive, so data through the close is complete.
    if not asset.calendar.is_open(now) and complete_through >= asset.calendar.last_open(now) - underlying_tf.duration:
        complete_through = now
    derived = derive(bars, target, complete_through)
    with session_scope() as session:
        return repository.save_candles(session, derived)


# --- Economic calendar -------------------------------------------------------------------


def collect_events() -> CollectionResult:
    def work() -> CollectionResult:
        with make_client() as client:
            events = fomc.fetch(client)
        with session_scope() as session:
            return repository.save_events(session, events)

    return run_job("federal_reserve.fomc", Source.FEDERAL_RESERVE, work)


# --- Analysis ----------------------------------------------------------------------------


def run_analysis(asset: AssetDefinition = GOLD) -> str:
    from gold_advisor import analysis

    with session_scope() as session:
        return analysis.build(session, asset=asset).id
