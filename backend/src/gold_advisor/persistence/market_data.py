"""Bounded market reads. The caller owns the session and transaction."""
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from gold_advisor.assets import AssetDefinition
from gold_advisor.domain import Source, Timeframe
from gold_advisor.persistence.models import CandleRow, SpotQuoteRow, AnalysisSnapshotRow

@dataclass(frozen=True)
class MarketQuery:
    asset: AssetDefinition
    timeframe: Timeframe
    start: datetime | None = None
    end: datetime | None = None
    limit: int = 500

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 5000:
            raise ValueError('limit must be between 1 and 5000')
        if self.timeframe not in self.asset.timeframes:
            raise ValueError('unsupported timeframe')
        if self.start and self.end and self.start >= self.end:
            raise ValueError('start must precede end')

def candles(session: Session, query: MarketQuery) -> list[CandleRow]:
    stmt = select(CandleRow).where(CandleRow.source == query.asset.candle_source.value,
        CandleRow.instrument == query.asset.instrument, CandleRow.timeframe == query.timeframe.value)
    if query.start is not None:
        stmt = stmt.where(CandleRow.bucket_start >= query.start)
    if query.end is not None:
        stmt = stmt.where(CandleRow.bucket_start < query.end)
    return list(reversed(session.scalars(stmt.order_by(CandleRow.bucket_start.desc()).limit(query.limit)).all()))

def latest_quote(session: Session, asset: AssetDefinition, sources: tuple[Source, ...]) -> SpotQuoteRow | None:
    return session.scalars(select(SpotQuoteRow).where(SpotQuoteRow.instrument == asset.instrument,
        SpotQuoteRow.source.in_([s.value for s in sources])).order_by(SpotQuoteRow.observed_at.desc(), SpotQuoteRow.source).limit(1)).first()

def latest_snapshot(session: Session, asset: AssetDefinition) -> AnalysisSnapshotRow | None:
    return session.scalars(select(AnalysisSnapshotRow).where(AnalysisSnapshotRow.asset_id == asset.id)
        .order_by(AnalysisSnapshotRow.created_at.desc(), AnalysisSnapshotRow.id.desc()).limit(1)).first()

def normalized_payload(row: AnalysisSnapshotRow) -> dict:
    payload = dict(row.payload)
    prices = dict(payload['prices'])
    prices.setdefault('world_usd_now', prices.get('xau_usd_now'))
    prices.setdefault('world_usd_source', prices.get('xau_usd_source'))
    payload['prices'] = prices
    return payload


def recorded_decisions(session: Session, asset: AssetDefinition, since: datetime, limit: int = 50000) -> list[AnalysisSnapshotRow]:
    """Load a bounded chronological snapshot window for evaluation."""
    if not 1 <= limit <= 50000:
        raise ValueError('snapshot limit must be between 1 and 50000')
    statement = (select(AnalysisSnapshotRow)
        .where(AnalysisSnapshotRow.asset_id == asset.id, AnalysisSnapshotRow.created_at >= since)
        .order_by(AnalysisSnapshotRow.created_at.desc(), AnalysisSnapshotRow.id.desc())
        .limit(limit))
    return list(reversed(session.scalars(statement).all()))
