"""
036 mcp_servers table for MCP server registry (DEF-005).

Stores per-tenant MCP server configurations. Credentials are NEVER stored
as plaintext — auth_config stores only a vault reference URI.

Table:
  mcp_servers(
    id               UUID PK,
    tenant_id        UUID NOT NULL FK tenants(id),
    name             VARCHAR NOT NULL,
    endpoint         VARCHAR NOT NULL,
    auth_type        VARCHAR CHECK('none','api_key','oauth2'),
    auth_config      JSONB nullable  -- vault ref only, never plaintext,
    status           VARCHAR CHECK('active','inactive') DEFAULT 'active',
    last_verified_at TIMESTAMPTZ nullable,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
  )
  UNIQUE(tenant_id, name)

RLS: tenant_isolation + platform_admin_bypass (in this migration)

Revision ID: 036
Revises: 035
Create Date: 2026-03-17
"""
from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mcp_servers (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name             VARCHAR(200) NOT NULL,
            endpoint         VARCHAR(2048) NOT NULL,
            auth_type        VARCHAR(20) NOT NULL DEFAULT 'none'
                CHECK (auth_type IN ('none', 'api_key', 'oauth2')),
            auth_config      JSONB,
            status           VARCHAR(10) NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'inactive')),
            last_verified_at TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT mcp_servers_tenant_name_unique UNIQUE (tenant_id, name)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mcp_servers_tenant "
        "ON mcp_servers (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mcp_servers_status "
        "ON mcp_servers (tenant_id, status)"
    )
    op.execute("ALTER TABLE mcp_servers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mcp_servers FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY mcp_servers_tenant ON mcp_servers
        FOR ALL
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
        """
    )
    op.execute(
        """
        CREATE POLICY mcp_servers_platform ON mcp_servers
        FOR ALL
        USING (current_setting('app.scope', true) = 'platform')
        WITH CHECK (current_setting('app.scope', true) = 'platform')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS mcp_servers_platform ON mcp_servers")
    op.execute("DROP POLICY IF EXISTS mcp_servers_tenant ON mcp_servers")
    op.execute("DROP TABLE IF EXISTS mcp_servers")
