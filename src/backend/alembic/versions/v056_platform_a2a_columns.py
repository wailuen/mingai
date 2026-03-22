"""v056 — Platform A2A Registry: agent_cards platform scope columns

Revision ID: 056
Revises: 055
Create Date: 2026-03-22

Adds platform A2A registry columns to agent_cards:
  - a2a_scope: 'platform' | 'tenant' (default 'tenant')
  - guardrail_overlay: JSONB overlay applied on top of agent response
  - assigned_tenants: JSONB list of tenant IDs with explicit access
  - deprecation_at: scheduled deprecation timestamp
  - deprecated_by: UUID of PA who scheduled deprecation
  - health_consecutive_failures: counter for health check failure streak
  - last_health_check_at: timestamp of last health check run
  - last_health_http_status: HTTP status from last health probe

Also adds source_mcp_server_id FK column to tool_catalog for tracking
which tenant MCP server a tool was enumerated from.
"""
from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # Platform A2A columns on agent_cards
    # -------------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE agent_cards
            ADD COLUMN IF NOT EXISTS a2a_scope VARCHAR(32) NOT NULL DEFAULT 'tenant'
                CHECK (a2a_scope IN ('platform', 'tenant')),
            ADD COLUMN IF NOT EXISTS guardrail_overlay JSONB NOT NULL DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS assigned_tenants JSONB NOT NULL DEFAULT '[]',
            ADD COLUMN IF NOT EXISTS deprecation_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS deprecated_by UUID,
            ADD COLUMN IF NOT EXISTS health_consecutive_failures INT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS last_health_check_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS last_health_http_status INT
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_cards_a2a_scope "
        "ON agent_cards(a2a_scope)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_cards_deprecation_at "
        "ON agent_cards(deprecation_at) WHERE deprecation_at IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_cards_health_check "
        "ON agent_cards(last_health_check_at) WHERE a2a_endpoint IS NOT NULL"
    )

    # -------------------------------------------------------------------------
    # source_mcp_server_id on tool_catalog (for tenant MCP-enumerated tools)
    # FK to tenant_mcp_servers; nullable because platform tools have no MCP server
    # -------------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE tool_catalog
            ADD COLUMN IF NOT EXISTS source_mcp_server_id UUID
                REFERENCES tenant_mcp_servers(id) ON DELETE SET NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_catalog_source_mcp_server_id "
        "ON tool_catalog(source_mcp_server_id) WHERE source_mcp_server_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS idx_tool_catalog_source_mcp_server_id"
    )
    op.execute(
        "ALTER TABLE tool_catalog DROP COLUMN IF EXISTS source_mcp_server_id"
    )
    op.execute(
        "DROP INDEX IF EXISTS idx_agent_cards_health_check"
    )
    op.execute(
        "DROP INDEX IF EXISTS idx_agent_cards_deprecation_at"
    )
    op.execute(
        "DROP INDEX IF EXISTS idx_agent_cards_a2a_scope"
    )
    op.execute(
        """
        ALTER TABLE agent_cards
            DROP COLUMN IF EXISTS a2a_scope,
            DROP COLUMN IF EXISTS guardrail_overlay,
            DROP COLUMN IF EXISTS assigned_tenants,
            DROP COLUMN IF EXISTS deprecation_at,
            DROP COLUMN IF EXISTS deprecated_by,
            DROP COLUMN IF EXISTS health_consecutive_failures,
            DROP COLUMN IF EXISTS last_health_check_at,
            DROP COLUMN IF EXISTS last_health_http_status
        """
    )
