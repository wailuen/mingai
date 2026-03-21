"""v048 — Update tool_catalog RLS policy to include degraded status

Revision ID: 048
Revises: 047
Create Date: 2026-03-21

Allows tenant sessions to SELECT degraded tools (not just healthy ones),
so ToolResolver can surface graceful degradation signals to the LLM.
inactive tools remain invisible.
"""
from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop existing tenant SELECT policy for tool_catalog
    op.execute("DROP POLICY IF EXISTS tool_catalog_tenant_select ON tool_catalog")
    # Recreate to include both healthy and degraded
    op.execute("""
        CREATE POLICY tool_catalog_tenant_select ON tool_catalog
        FOR SELECT
        USING (
            health_status IN ('healthy', 'degraded')
            AND current_setting('app.tenant_id', true) IS NOT NULL
            AND current_setting('app.tenant_id', true) != ''
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tool_catalog_tenant_select ON tool_catalog")
    op.execute("""
        CREATE POLICY tool_catalog_tenant_select ON tool_catalog
        FOR SELECT
        USING (
            current_setting('app.tenant_id', true) IS NOT NULL
            AND current_setting('app.tenant_id', true) != ''
            AND health_status = 'healthy'
        )
    """)
