"""News articles, refresh jobs, and owner-confirmed news risks.

Revision ID: 0005_news
Revises: 0004_assets
Create Date: 2026-11-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_news"
down_revision = "0004_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_articles",
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("excerpt", sa.Text(), server_default="", nullable=False),
        sa.Column("language", sa.String(8), server_default="", nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("asset_id", "source", "provider_id", name="pk_news_articles"),
        sa.CheckConstraint("url LIKE 'https://%'", name="ck_news_articles_https_url"),
    )
    op.create_index("ix_news_articles_asset_published", "news_articles", ["asset_id", "published_at"])

    op.create_table(
        "news_refresh_jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column("dedupe_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requests_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("article_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_news_refresh_jobs"),
        sa.UniqueConstraint("asset_id", "dedupe_key", name="uq_news_refresh_jobs_asset_id_dedupe_key"),
    )
    op.create_index("ix_news_refresh_jobs_status", "news_refresh_jobs", ["status"])

    op.create_table(
        "news_risk_confirmations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_news_risk_confirmations"),
    )
    op.create_index("ix_news_risk_confirmations_asset_expires", "news_risk_confirmations", ["asset_id", "expires_at"])


def downgrade() -> None:
    for table in ("news_risk_confirmations", "news_refresh_jobs", "news_articles"):
        op.drop_table(table)
