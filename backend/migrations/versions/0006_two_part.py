"""Two-part purchase: the first half and the second-half triggers on the purchase plan. Additive.

Revision ID: 0006_two_part
Revises: 0005_news
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_two_part"
down_revision = "0005_news"
branch_labels = None
depends_on = None

COLUMNS = (
    ("first_part_at", sa.DateTime(timezone=True)),
    ("first_part_price", sa.Numeric(14, 2)),
    ("second_dip_npr", sa.Numeric(14, 2)),
    ("second_recovery_npr", sa.Numeric(14, 2)),
    ("second_deadline", sa.Date()),
)


def upgrade() -> None:
    for name, kind in COLUMNS:
        op.add_column("purchase_plan", sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("purchase_plan", name)
