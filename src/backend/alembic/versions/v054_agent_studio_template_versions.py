"""v054 — Agent Studio: Agent Template Versions + Skill Promotion Requests

Revision ID: 054
Revises: 053
Create Date: 2026-03-22

Creates:
  - agent_template_versions: immutable version history for PA-authored templates
  - skill_promotion_requests: tenant-to-platform skill promotion workflow

Also extends tool_catalog with new Agent Studio columns needed for the
skill/tool executor (executor_type, rate_limit_rpm, credential_source, etc.)
that go beyond the existing v026 schema.
"""
from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # agent_template_versions — immutable publish history
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_template_versions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            template_id     UUID NOT NULL REFERENCES agent_cards(id) ON DELETE CASCADE,
            version_label   VARCHAR(20) NOT NULL,
            change_type     VARCHAR(10) NOT NULL
                            CHECK (change_type IN ('initial', 'patch', 'minor', 'major')),
            changelog       TEXT NOT NULL,
            published_by    UUID NOT NULL,
            published_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            snapshot        JSONB
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_atv_template_id "
        "ON agent_template_versions(template_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_atv_published_at "
        "ON agent_template_versions(published_at DESC)"
    )

    # -------------------------------------------------------------------------
    # skill_promotion_requests — tenant skill → platform library workflow
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_promotion_requests (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            skill_id            UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            tenant_id           UUID NOT NULL,
            submitted_by        UUID NOT NULL,
            submitted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            status              VARCHAR(32) NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'approved', 'rejected')),
            reviewed_by         UUID,
            reviewed_at         TIMESTAMPTZ,
            rejection_reason    TEXT,
            platform_skill_id   UUID REFERENCES skills(id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_spr_tenant_id "
        "ON skill_promotion_requests(tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_spr_status "
        "ON skill_promotion_requests(status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_spr_skill_id "
        "ON skill_promotion_requests(skill_id)"
    )

    # -------------------------------------------------------------------------
    # Extend tool_catalog with Agent Studio executor columns
    # The v026 table has mcp_endpoint/auth_type/capabilities/safety_classification.
    # We add the new Agent Studio columns using IF NOT EXISTS for safety.
    # -------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE tool_catalog "
        "ADD COLUMN IF NOT EXISTS executor_type VARCHAR(20) DEFAULT 'mcp_sse' "
        "    CHECK (executor_type IN ('builtin', 'http_wrapper', 'mcp_sse'))"
    )
    op.execute(
        "ALTER TABLE tool_catalog "
        "ADD COLUMN IF NOT EXISTS rate_limit_rpm INT NOT NULL DEFAULT 60"
    )
    op.execute(
        "ALTER TABLE tool_catalog "
        "ADD COLUMN IF NOT EXISTS credential_source VARCHAR(32) NOT NULL DEFAULT 'none' "
        "    CHECK (credential_source IN ('none', 'platform_managed', 'tenant_managed'))"
    )
    op.execute(
        "ALTER TABLE tool_catalog "
        "ADD COLUMN IF NOT EXISTS credential_schema JSONB NOT NULL DEFAULT '[]'"
    )
    op.execute(
        "ALTER TABLE tool_catalog "
        "ADD COLUMN IF NOT EXISTS input_schema JSONB NOT NULL DEFAULT '{}'"
    )
    op.execute(
        "ALTER TABLE tool_catalog "
        "ADD COLUMN IF NOT EXISTS output_schema JSONB NOT NULL DEFAULT '{}'"
    )
    op.execute(
        "ALTER TABLE tool_catalog "
        "ADD COLUMN IF NOT EXISTS endpoint_url TEXT"
    )
    op.execute(
        "ALTER TABLE tool_catalog "
        "ADD COLUMN IF NOT EXISTS plan_required VARCHAR(32) "
        "    CHECK (plan_required IS NULL OR plan_required IN ('starter', 'professional', 'enterprise'))"
    )
    op.execute(
        "ALTER TABLE tool_catalog "
        "ADD COLUMN IF NOT EXISTS scope VARCHAR(255) NOT NULL DEFAULT 'platform'"
    )
    op.execute(
        "ALTER TABLE tool_catalog "
        "ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute(
        "ALTER TABLE tool_catalog "
        "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
    )
    op.execute(
        "ALTER TABLE tool_catalog "
        "ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL"
    )
    # Indexes for new columns
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_catalog_executor_type "
        "ON tool_catalog(executor_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_catalog_scope "
        "ON tool_catalog(scope)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_catalog_is_active "
        "ON tool_catalog(is_active)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_catalog_credential_schema "
        "ON tool_catalog USING GIN(credential_schema)"
    )

    # -------------------------------------------------------------------------
    # tenant_mcp_servers — tenant-registered external MCP servers
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_mcp_servers (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name            VARCHAR(255) NOT NULL,
            description     TEXT,
            endpoint_url    TEXT NOT NULL,
            transport       VARCHAR(32) NOT NULL DEFAULT 'sse'
                            CHECK (transport IN ('sse', 'streamable_http')),
            auth_type       VARCHAR(32) NOT NULL DEFAULT 'none'
                            CHECK (auth_type IN ('none', 'bearer', 'api_key', 'oauth2')),
            auth_config     JSONB NOT NULL DEFAULT '{}',
            status          VARCHAR(32) NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'verified', 'error', 'inactive')),
            last_verified_at TIMESTAMPTZ,
            last_error      TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by      UUID NOT NULL,
            UNIQUE (tenant_id, name)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tenant_mcp_tenant_id "
        "ON tenant_mcp_servers(tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tenant_mcp_status "
        "ON tenant_mcp_servers(status)"
    )
    op.execute("ALTER TABLE tenant_mcp_servers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_mcp_servers FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_mcp_servers_tenant_isolation ON tenant_mcp_servers
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
        """
    )
    op.execute(
        """
        CREATE POLICY tenant_mcp_servers_platform_admin ON tenant_mcp_servers
        FOR ALL
        USING (current_setting('app.scope', true) = 'platform')
        WITH CHECK (current_setting('app.scope', true) = 'platform')
        """
    )


def downgrade() -> None:
    # Drop tenant_mcp_servers
    op.execute("DROP POLICY IF EXISTS tenant_mcp_servers_platform_admin ON tenant_mcp_servers")
    op.execute("DROP POLICY IF EXISTS tenant_mcp_servers_tenant_isolation ON tenant_mcp_servers")
    op.execute("DROP TABLE IF EXISTS tenant_mcp_servers CASCADE")
    # Drop tool_catalog extensions
    for col in [
        "created_by", "updated_at", "is_active", "scope", "plan_required",
        "endpoint_url", "output_schema", "input_schema", "credential_schema",
        "credential_source", "rate_limit_rpm", "executor_type",
    ]:
        op.execute(f"ALTER TABLE tool_catalog DROP COLUMN IF EXISTS {col}")
    # Drop new tables
    op.execute("DROP TABLE IF EXISTS skill_promotion_requests CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_template_versions CASCADE")
