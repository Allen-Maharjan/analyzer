"""Source health: data freshness plus collector status, kept separate so a market closure
is never confused with a broken collector."""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gold_advisor import freshness
from gold_advisor.assets import AssetDefinition, GOLD
from gold_advisor.config import get_settings
from gold_advisor.domain import (
    COLLECTED_TIMEFRAMES,
    DERIVED_TIMEFRAMES,
    CollectorStatus,
    Instrument,
    MassUnit,
    Metal,
    Purity,
    RunStatus,
    Source,
    Timeframe,
)
from gold_advisor.persistence.models import (
    CandleRow,
    CollectionRunRow,
    FxRateRow,
    LocalMetalRateRow,
    MacroObservationRow,
    SpotQuoteRow,
)


@dataclass(frozen=True)
class CollectorHealth:
    status: CollectorStatus
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None
    consecutive_failures: int


@dataclass(frozen=True)
class DatasetHealth:
    dataset: str
    source: Source
    latest_observation: datetime | date | None
    freshness: freshness.Freshness
    collector: CollectorHealth


def collector_health(session: Session, job: str) -> CollectorHealth:
    finished = (
        select(CollectionRunRow)
        .where(CollectionRunRow.job == job, CollectionRunRow.status != RunStatus.RUNNING.value)
        .order_by(CollectionRunRow.started_at.desc())
    )
    last = session.scalars(finished.limit(1)).first()
    if last is None:
        return CollectorHealth(CollectorStatus.NEVER_RUN, None, None, None, 0)
    last_success = session.scalar(
        select(func.max(CollectionRunRow.finished_at)).where(
            CollectionRunRow.job == job, CollectionRunRow.status == RunStatus.SUCCESS.value
        )
    )
    last_failure_row = session.scalars(
        finished.where(CollectionRunRow.status == RunStatus.FAILED.value).limit(1)
    ).first()
    failures_query = select(func.count()).where(
        CollectionRunRow.job == job, CollectionRunRow.status == RunStatus.FAILED.value
    )
    if last_success is not None:
        failures_query = failures_query.where(CollectionRunRow.started_at > last_success)
    consecutive = session.scalar(failures_query) or 0
    return CollectorHealth(
        status=CollectorStatus.OK if last.status == RunStatus.SUCCESS.value else CollectorStatus.FAILING,
        last_success_at=last_success,
        last_failure_at=last_failure_row.finished_at if last_failure_row else None,
        last_error=last_failure_row.error if last_failure_row and last.status != RunStatus.SUCCESS.value else None,
        consecutive_failures=consecutive,
    )


def _candle_job(timeframe: Timeframe) -> str:
    return f"dukascopy.{DERIVED_TIMEFRAMES.get(timeframe, timeframe).value}"


def all_sources(session: Session, now: datetime, asset: AssetDefinition = GOLD) -> list[DatasetHealth]:
    out: list[DatasetHealth] = []

    for dataset, source in ((f"{asset.dataset_prefix}_spot", Source.GOLD_API), (f"{asset.dataset_prefix}_spot_backup", Source.SWISSQUOTE)):
        quote_at = session.scalar(
            select(func.max(SpotQuoteRow.observed_at)).where(
                SpotQuoteRow.source == source.value, SpotQuoteRow.instrument == asset.instrument
            )
        )
        out.append(
            DatasetHealth(
                dataset,
                source,
                quote_at,
                freshness.live_quote(quote_at, now, asset.calendar),
                collector_health(session, asset.job(f"{source.value}.spot")),
            )
        )

    for timeframe in (*COLLECTED_TIMEFRAMES, *DERIVED_TIMEFRAMES):
        latest = session.scalar(
            select(func.max(CandleRow.bucket_start)).where(
                CandleRow.source == asset.candle_source.value,
                CandleRow.instrument == asset.instrument,
                CandleRow.timeframe == timeframe.value,
            )
        )
        out.append(
            DatasetHealth(
                f"{asset.dataset_prefix}_candles_{timeframe.value}",
                Source.DUKASCOPY,
                latest,
                freshness.candles(timeframe, latest, now, asset.calendar),
                collector_health(session, asset.job(_candle_job(timeframe))),
            )
        )

    nepal_date = session.scalar(
        select(func.max(LocalMetalRateRow.rate_date)).where(
            LocalMetalRateRow.source == Source.FENEGOSIDA.value,
            LocalMetalRateRow.metal == asset.metal.value,
            LocalMetalRateRow.purity == asset.purity.value,
            LocalMetalRateRow.unit == MassUnit.TOLA.value,
        )
    )
    out.append(
        DatasetHealth(
            asset.local_dataset,
            Source.FENEGOSIDA,
            nepal_date,
            freshness.nepal_publication(nepal_date, now),
            collector_health(session, "fenegosida.today"),
        )
    )

    fx_date = session.scalar(
        select(func.max(FxRateRow.rate_date)).where(FxRateRow.source == Source.NRB.value, FxRateRow.currency == "USD")
    )
    out.append(
        DatasetHealth("usd_npr", Source.NRB, fx_date, freshness.nrb_rate(fx_date, now), collector_health(session, "nrb.fx"))
    )

    fred_health = collector_health(session, "fred.yields")
    for series_id in get_settings().fred_series:
        latest = session.scalar(
            select(func.max(MacroObservationRow.obs_date)).where(
                MacroObservationRow.source == Source.FRED.value,
                MacroObservationRow.series_id == series_id,
                MacroObservationRow.value.is_not(None),
            )
        )
        out.append(
            DatasetHealth(f"fred_{series_id}", Source.FRED, latest, freshness.fred_daily(latest, now), fred_health)
        )
    return out
