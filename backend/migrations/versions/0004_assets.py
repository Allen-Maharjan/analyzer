"""Asset ownership; legacy observations and immutable payloads remain intact."""
from alembic import op
import sqlalchemy as sa

revision = '0004_assets'
down_revision = '0003_ai'
branch_labels = None
depends_on = None

def upgrade() -> None:
    for table in ('analysis_snapshots', 'ai_analyses', 'purchase_plan'):
        op.add_column(table, sa.Column('asset_id', sa.String(64), nullable=False, server_default='gold'))
        op.alter_column(table, 'asset_id', server_default=None)
    op.create_index('ix_analysis_snapshots_asset_created', 'analysis_snapshots', ['asset_id', 'created_at', 'id'])
    op.create_index('ix_ai_analyses_asset_created', 'ai_analyses', ['asset_id', 'created_at'])
    op.drop_constraint('ck_purchase_plan_single_row', 'purchase_plan', type_='check')
    op.drop_constraint('pk_purchase_plan', 'purchase_plan', type_='primary')
    op.drop_column('purchase_plan', 'id')
    op.create_primary_key('pk_purchase_plan', 'purchase_plan', ['asset_id'])
    op.execute("UPDATE app_settings SET key = 'watch_levels:gold' WHERE key = 'watch_levels'")

def downgrade() -> None:
    # Never silently discard another asset's evidence or purchase state.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM analysis_snapshots WHERE asset_id <> 'gold')
        OR EXISTS (SELECT 1 FROM ai_analyses WHERE asset_id <> 'gold')
        OR EXISTS (SELECT 1 FROM purchase_plan WHERE asset_id <> 'gold')
        OR EXISTS (SELECT 1 FROM app_settings WHERE key LIKE 'watch_levels:%' AND key <> 'watch_levels:gold')
        THEN RAISE EXCEPTION 'Cannot downgrade while non-gold data exists'; END IF;
    END $$""")
    op.execute("UPDATE app_settings SET key = 'watch_levels' WHERE key = 'watch_levels:gold'")
    op.drop_constraint('pk_purchase_plan', 'purchase_plan', type_='primary')
    op.add_column('purchase_plan', sa.Column('id', sa.Integer(), nullable=False, server_default='1'))
    op.create_primary_key('pk_purchase_plan', 'purchase_plan', ['id'])
    op.create_check_constraint('ck_purchase_plan_single_row', 'purchase_plan', 'id = 1')
    op.drop_index('ix_ai_analyses_asset_created', table_name='ai_analyses')
    op.drop_index('ix_analysis_snapshots_asset_created', table_name='analysis_snapshots')
    for table in ('purchase_plan', 'ai_analyses', 'analysis_snapshots'):
        op.drop_column(table, 'asset_id')
