from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    UniqueConstraint,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Price = Numeric(14, 4)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _ingested() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _flags() -> Mapped[list[str]]:
    return mapped_column(ARRAY(Text), server_default="{}", nullable=False)


class SpotQuoteRow(Base):
    """Live quotes. Immutable once stored. TimescaleDB hypertable on observed_at."""

    __tablename__ = "spot_quotes"
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    instrument: Mapped[str] = mapped_column(String(32), primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Price, nullable=False)
    quality_flags: Mapped[list[str]] = _flags()
    ingested_at: Mapped[datetime] = _ingested()
    __table_args__ = (CheckConstraint("price > 0", name="price_positive"),)


class CandleRow(Base):
    """OHLC bars from one candle provider. Never mixed with quote providers. Hypertable on bucket_start."""

    __tablename__ = "candles"
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    instrument: Mapped[str] = mapped_column(String(32), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[Decimal] = mapped_column(Price, nullable=False)
    high: Mapped[Decimal] = mapped_column(Price, nullable=False)
    low: Mapped[Decimal] = mapped_column(Price, nullable=False)
    close: Mapped[Decimal] = mapped_column(Price, nullable=False)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    price_side: Mapped[str] = mapped_column(String(8), nullable=False)
    derived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    component_count: Mapped[int | None] = mapped_column(Integer)
    quality_flags: Mapped[list[str]] = _flags()
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ingested_at: Mapped[datetime] = _ingested()
    updated_at: Mapped[datetime] = _ingested()
    __table_args__ = (
        CheckConstraint("low <= LEAST(open, close) AND high >= GREATEST(open, close)", name="ohlc_consistent"),
    )


class LocalMetalRateRow(Base):
    __tablename__ = "local_metal_rates"
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    metal: Mapped[str] = mapped_column(String(16), primary_key=True)
    purity: Mapped[str] = mapped_column(String(16), primary_key=True)
    unit: Mapped[str] = mapped_column(String(8), primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    price_npr: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    source_label: Mapped[str] = mapped_column(Text, nullable=False)
    quality_flags: Mapped[list[str]] = _flags()
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ingested_at: Mapped[datetime] = _ingested()
    updated_at: Mapped[datetime] = _ingested()
    __table_args__ = (CheckConstraint("price_npr > 0", name="price_positive"),)


class FxRateRow(Base):
    __tablename__ = "fx_rates"
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    unit: Mapped[int] = mapped_column(Integer, nullable=False)
    buy: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    sell: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ingested_at: Mapped[datetime] = _ingested()
    updated_at: Mapped[datetime] = _ingested()
    __table_args__ = (CheckConstraint("buy > 0 AND sell > 0 AND unit > 0", name="rates_positive"),)


class MacroObservationRow(Base):
    __tablename__ = "macro_observations"
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    series_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    obs_date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ingested_at: Mapped[datetime] = _ingested()
    updated_at: Mapped[datetime] = _ingested()


class ObservationRevisionRow(Base):
    """Previous values of revised observations, so corrections never erase history."""

    __tablename__ = "observation_revisions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(String(64), nullable=False)
    record_key: Mapped[dict] = mapped_column(JSONB, nullable=False)
    previous: Mapped[dict] = mapped_column(JSONB, nullable=False)
    current: Mapped[dict] = mapped_column(JSONB, nullable=False)
    revised_at: Mapped[datetime] = _ingested()
    __table_args__ = (Index("ix_observation_revisions_table_name_revised_at", "table_name", "revised_at"),)


class CollectionRunRow(Base):
    __tablename__ = "collection_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    job: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_inserted: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rows_revised: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rows_unchanged: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    notes: Mapped[list[str]] = _flags()
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_collection_runs_job_started_at", "job", "started_at"),)


class EconomicEventRow(Base):
    __tablename__ = "economic_events"
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[str] = mapped_column(String(16), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = _ingested()


class AnalysisSnapshotRow(Base):
    """One immutable analysis: the inputs, scores, and decision shown together on screen."""

    __tablename__ = "analysis_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    versions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    deterministic_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    __table_args__ = (Index("ix_analysis_snapshots_created_at", "created_at"), Index("ix_analysis_snapshots_asset_created", "asset_id", "created_at", "id"),)


class PurchasePlanRow(Base):
    """The household's single purchase plan. Waiting time only resets by an owner action."""

    __tablename__ = "purchase_plan"
    asset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    waiting_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _ingested()



class AppSettingRow(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = _ingested()


class AiAnalysisRow(Base):
    """One AI run over one snapshot. Inputs and outputs are kept for audit."""

    __tablename__ = "ai_analyses"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)  # schedule | change | manual
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # queued | running | succeeded | invalid | failed | expired
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cli_version: Mapped[str | None] = mapped_column(Text)
    input: Mapped[dict] = mapped_column(JSONB, nullable=False)
    raw_output: Mapped[str | None] = mapped_column(Text)
    output: Mapped[dict | None] = mapped_column(JSONB)
    validation: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_ai_analyses_created_at", "created_at"), Index("ix_ai_analyses_status", "status"))


class NewsArticleRow(Base):
    """A selected headline for one asset. The full article body is never stored."""

    __tablename__ = "news_articles"
    asset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    language: Mapped[str] = mapped_column(String(8), nullable=False, server_default="")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (Index("ix_news_articles_asset_published", "asset_id", "published_at"),)


class NewsRefreshJobRow(Base):
    """Durable request to search news for one asset. ``dedupe_key`` makes enqueueing idempotent."""

    __tablename__ = "news_refresh_jobs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)  # price_inserted | price_revised | manual
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # pending | running | succeeded | empty | failed
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requests_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    article_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("asset_id", "dedupe_key", name="uq_news_refresh_jobs_asset_id_dedupe_key"),
        Index("ix_news_refresh_jobs_status", "status"),
    )


class NewsRiskRow(Base):
    """The owner marked an article as a reason to wait. Only this, never AI output, can turn BUY into WAIT."""

    __tablename__ = "news_risk_confirmations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_news_risk_confirmations_asset_expires", "asset_id", "expires_at"),)
