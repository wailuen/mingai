"""
026 tool_catalog table for PA-030 Tool Catalog.

Platform-level registry of external MCP tools available for tenant assignment.
No tenant_id — this is a platform-wide catalog.

Table:
  tool_catalog(
    id                    UUID PK,
    name                  VARCHAR(100) NOT NULL UNIQUE,
    provider              VARCHAR(100) NOT NULL,
    mcp_endpoint          VARCHAR(500) NOT NULL,
    auth_type             VARCHAR(20) CHECK(none|api_key|oauth2) NOT NULL,
    capabilities          JSONB NOT NULL DEFAULT '[]',
    safety_classification VARCHAR(20) CHECK(ReadOnly|Write|Destructive) NOT NULL,
    health_status         VARCHAR(20) CHECK(healthy|degraded|unavailable) NOT NULL DEFAULT 'healthy',
    version               VARCHAR(50),
    last_health_check     TIMESTAMPTZ,
    health_check_url      VARCHAR(500),
    created_at            TIMESTAMPTZ DEFAULT NOW()
  )

Immutability of safety_classification is enforced via a trigger: UPDATE
that changes this column raises an exception. Application code must never
attempt to change it after creation.

RLS:
  - Platform admins (app.scope = 'platform'): full SELECT/INSERT/UPDATE/DELETE.
  - Tenant sessions (app.tenant_id set): SELECT WHERE health_status = 'healthy'.

Revision ID: 026
Revises: 025
Create Date: 2026-03-16
"""
from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_catalog (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name                  VARCHAR(100) NOT NULL,
            provider              VARCHAR(100) NOT NULL,
            mcp_endpoint          VARCHAR(500) NOT NULL,
            auth_type             VARCHAR(20) NOT NULL
                CHECK (auth_type IN ('none', 'api_key', 'oauth2')),
            capabilities          JSONB NOT NULL DEFAULT '[]',
            safety_classification VARCHAR(20) NOT NULL
                CHECK (safety_classification IN ('ReadOnly', 'Write', 'Destructive')),
            health_status         VARCHAR(20) NOT NULL DEFAULT 'healthy'
                CHECK (health_status IN ('healthy', 'degraded', 'unavailable')),
            version               VARCHAR(50),
            last_health_check     TIMESTAMPTZ,
            health_check_url      VARCHAR(500),
            created_at            TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT tool_catalog_name_unique UNIQUE (name)
        )
        """
    )
    # Prevent UPDATE on safety_classification after insertion.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION tool_catalog_immutable_safety()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.safety_classification IS DISTINCT FROM OLD.safety_classification THEN
                RAISE EXCEPTION
                    'safety_classification is immutable after creation (tool_id: %)',
                    OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER tool_catalog_safety_immutable
        BEFORE UPDATE ON tool_catalog
        FOR EACH ROW EXECUTE FUNCTION tool_catalog_immutable_safety();
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_catalog_health_status "
        "ON tool_catalog (health_status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_catalog_safety "
        "ON tool_catalog (safety_classification)"
    )
    op.execute("ALTER TABLE tool_catalog ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tool_catalog FORCE ROW LEVEL SECURITY")
    # Platform admins: full access.
    op.execute(
        """
        CREATE POLICY tool_catalog_platform ON tool_catalog
        FOR ALL
        USING (current_setting('app.scope', true) = 'platform')
        WITH CHECK (current_setting('app.scope', true) = 'platform')
        """
    )
    # Tenant sessions: SELECT healthy tools only.
    op.execute(
        """
        CREATE POLICY tool_catalog_tenant_select ON tool_catalog
        FOR SELECT
        USING (
            current_setting('app.tenant_id', true) IS NOT NULL
            AND current_setting('app.tenant_id', true) != ''
            AND health_status = 'healthy'
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tool_catalog_tenant_select ON tool_catalog")
    op.execute("DROP POLICY IF EXISTS tool_catalog_platform ON tool_catalog")
    op.execute("DROP TRIGGER IF EXISTS tool_catalog_safety_immutable ON tool_catalog")
    op.execute("DROP FUNCTION IF EXISTS tool_catalog_immutable_safety()")
    op.execute("DROP TABLE IF EXISTS tool_catalog")
