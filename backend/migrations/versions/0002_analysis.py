"""Economic events, analysis snapshots, purchase plan, settings.

Revision ID: 0002_analysis
Revises: 0001_initial
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_analysis"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "economic_events",
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("importance", sa.String(16), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        _now("ingested_at"),
        sa.PrimaryKeyConstraint("source", "event_type", "scheduled_at", name="pk_economic_events"),
    )
    op.create_table(
        "analysis_snapshots",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("versions", postgresql.JSONB(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("deterministic_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_snapshots"),
    )
    op.create_index("ix_analysis_snapshots_created_at", "analysis_snapshots", ["created_at"])
    op.create_table(
        "purchase_plan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("waiting_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _now("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_purchase_plan"),
        sa.CheckConstraint("id = 1", name="ck_purchase_plan_single_row"),
    )
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        _now("updated_at"),
        sa.PrimaryKeyConstraint("key", name="pk_app_settings"),
    )
    # Snapshots are evidence for later evaluation: block edits and deletes at the database.
    op.execute(
        """
        CREATE FUNCTION forbid_snapshot_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'analysis_snapshots are immutable'; END $$;
        CREATE TRIGGER trg_analysis_snapshots_immutable BEFORE UPDATE OR DELETE ON analysis_snapshots
        FOR EACH ROW EXECUTE FUNCTION forbid_snapshot_change();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_analysis_snapshots_immutable ON analysis_snapshots")
    op.execute("DROP FUNCTION IF EXISTS forbid_snapshot_change()")
    for table in ("app_settings", "purchase_plan", "analysis_snapshots", "economic_events"):
        op.drop_table(table)
