"""Initial schema: observations, revisions, collection runs. TimescaleDB hypertables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _ingested(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _flags(name: str = "quality_flags") -> sa.Column:
    return sa.Column(name, postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False)


def _revision() -> sa.Column:
    return sa.Column("revision", sa.Integer(), server_default="0", nullable=False)


def upgrade() -> None:
    # TimescaleDB is optional: Neon and other hosted Postgres services don't offer it.
    bind = op.get_bind()
    timescale = bind.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'")
    ).scalar() is not None
    if timescale:
        op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "spot_quotes",
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("instrument", sa.String(32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(14, 4), nullable=False),
        _flags(),
        _ingested("ingested_at"),
        sa.PrimaryKeyConstraint("source", "instrument", "observed_at", name="pk_spot_quotes"),
        sa.CheckConstraint("price > 0", name="ck_spot_quotes_price_positive"),
    )
    if timescale:
        op.execute("SELECT create_hypertable('spot_quotes', by_range('observed_at', INTERVAL '7 days'))")

    op.create_table(
        "candles",
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("instrument", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(14, 4), nullable=False),
        sa.Column("high", sa.Numeric(14, 4), nullable=False),
        sa.Column("low", sa.Numeric(14, 4), nullable=False),
        sa.Column("close", sa.Numeric(14, 4), nullable=False),
        sa.Column("volume", sa.Numeric(20, 6), nullable=True),
        sa.Column("price_side", sa.String(8), nullable=False),
        sa.Column("derived", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("component_count", sa.Integer(), nullable=True),
        _flags(),
        _revision(),
        _ingested("ingested_at"),
        _ingested("updated_at"),
        sa.PrimaryKeyConstraint("source", "instrument", "timeframe", "bucket_start", name="pk_candles"),
        sa.CheckConstraint(
            "low <= LEAST(open, close) AND high >= GREATEST(open, close)", name="ck_candles_ohlc_consistent"
        ),
    )
    if timescale:
        op.execute("SELECT create_hypertable('candles', by_range('bucket_start', INTERVAL '90 days'))")

    op.create_table(
        "local_metal_rates",
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("metal", sa.String(16), nullable=False),
        sa.Column("purity", sa.String(16), nullable=False),
        sa.Column("unit", sa.String(8), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price_npr", sa.Numeric(14, 2), nullable=False),
        sa.Column("source_label", sa.Text(), nullable=False),
        _flags(),
        _revision(),
        _ingested("ingested_at"),
        _ingested("updated_at"),
        sa.PrimaryKeyConstraint("source", "metal", "purity", "unit", "rate_date", name="pk_local_metal_rates"),
        sa.CheckConstraint("price_npr > 0", name="ck_local_metal_rates_price_positive"),
    )

    op.create_table(
        "fx_rates",
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("unit", sa.Integer(), nullable=False),
        sa.Column("buy", sa.Numeric(12, 4), nullable=False),
        sa.Column("sell", sa.Numeric(12, 4), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True),
        _revision(),
        _ingested("ingested_at"),
        _ingested("updated_at"),
        sa.PrimaryKeyConstraint("source", "currency", "rate_date", name="pk_fx_rates"),
        sa.CheckConstraint("buy > 0 AND sell > 0 AND unit > 0", name="ck_fx_rates_rates_positive"),
    )

    op.create_table(
        "macro_observations",
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("series_id", sa.String(32), nullable=False),
        sa.Column("obs_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(14, 6), nullable=True),
        _revision(),
        _ingested("ingested_at"),
        _ingested("updated_at"),
        sa.PrimaryKeyConstraint("source", "series_id", "obs_date", name="pk_macro_observations"),
    )

    op.create_table(
        "observation_revisions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("table_name", sa.String(64), nullable=False),
        sa.Column("record_key", postgresql.JSONB(), nullable=False),
        sa.Column("previous", postgresql.JSONB(), nullable=False),
        sa.Column("current", postgresql.JSONB(), nullable=False),
        _ingested("revised_at"),
        sa.PrimaryKeyConstraint("id", name="pk_observation_revisions"),
    )
    op.create_index(
        "ix_observation_revisions_table_name_revised_at", "observation_revisions", ["table_name", "revised_at"]
    )

    op.create_table(
        "collection_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("job", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rows_inserted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_revised", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_unchanged", sa.Integer(), server_default="0", nullable=False),
        _flags("notes"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_collection_runs"),
    )
    op.create_index("ix_collection_runs_job_started_at", "collection_runs", ["job", "started_at"])


def downgrade() -> None:
    for table in (
        "collection_runs",
        "observation_revisions",
        "macro_observations",
        "fx_rates",
        "local_metal_rates",
        "candles",
        "spot_quotes",
    ):
        op.drop_table(table)
