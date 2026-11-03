"""AI analyses.

Revision ID: 0003_ai
Revises: 0002_analysis
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_ai"
down_revision = "0002_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_analyses",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cli_version", sa.Text(), nullable=True),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("validation", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ai_analyses"),
    )
    op.create_index("ix_ai_analyses_created_at", "ai_analyses", ["created_at"])
    op.create_index("ix_ai_analyses_status", "ai_analyses", ["status"])


def downgrade() -> None:
    op.drop_table("ai_analyses")
