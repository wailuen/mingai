"""v053 — Agent Studio: Agent Template Extensions + Join Tables

Revision ID: 053
Revises: 052
Create Date: 2026-03-22

Extends agent_cards with 7-dimension template configuration columns.
Creates join tables:
  - tenant_skills: tenant skill adoptions
  - agent_template_skills: skills attached to a template/agent
  - agent_template_tools: tools attached to a template/agent
  - mcp_integration_imports: PA MCP Integration Builder import sessions

Safe defaults ensure the 4 existing seed templates are unaffected.
"""
from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # Extend agent_cards with studio columns
    # Use IF NOT EXISTS to be safe for idempotency
    # -------------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE agent_cards
            ADD COLUMN IF NOT EXISTS template_type VARCHAR(32) NOT NULL DEFAULT 'rag'
                CHECK (template_type IN ('rag', 'skill_augmented', 'tool_augmented', 'credentialed', 'registered_a2a')),
            ADD COLUMN IF NOT EXISTS llm_policy JSONB NOT NULL DEFAULT
                '{"tenant_can_override": true, "defaults": {"temperature": 0.3, "max_tokens": 2000}}',
            ADD COLUMN IF NOT EXISTS kb_policy JSONB NOT NULL DEFAULT
                '{"ownership": "tenant_managed", "recommended_categories": [], "required_kb_ids": []}',
            ADD COLUMN IF NOT EXISTS attached_skills JSONB NOT NULL DEFAULT '[]',
            ADD COLUMN IF NOT EXISTS attached_tools JSONB NOT NULL DEFAULT '[]',
            ADD COLUMN IF NOT EXISTS a2a_interface JSONB NOT NULL DEFAULT
                '{"a2a_enabled": false, "operations": [], "auth_required": false}',
            ADD COLUMN IF NOT EXISTS source_card_url TEXT,
            ADD COLUMN IF NOT EXISTS imported_card JSONB
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_cards_template_type "
        "ON agent_cards(template_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_cards_attached_skills "
        "ON agent_cards USING GIN(attached_skills)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_cards_attached_tools "
        "ON agent_cards USING GIN(attached_tools)"
    )

    # -------------------------------------------------------------------------
    # tenant_skills — skill adoptions per tenant
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_skills (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            skill_id        UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            pinned_version  VARCHAR(20),
            adopted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(tenant_id, skill_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tenant_skills_tenant_id "
        "ON tenant_skills(tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tenant_skills_skill_id "
        "ON tenant_skills(skill_id)"
    )
    op.execute("ALTER TABLE tenant_skills ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_skills FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_skills_tenant_isolation ON tenant_skills
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
        """
    )
    op.execute(
        """
        CREATE POLICY tenant_skills_platform_admin ON tenant_skills
        FOR ALL
        USING (current_setting('app.scope', true) = 'platform')
        WITH CHECK (current_setting('app.scope', true) = 'platform')
        """
    )

    # -------------------------------------------------------------------------
    # agent_template_skills — skills attached to a specific agent/template
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_template_skills (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            template_id         UUID NOT NULL REFERENCES agent_cards(id) ON DELETE CASCADE,
            skill_id            UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            pinned_version      VARCHAR(20),
            invocation_override JSONB,
            UNIQUE(template_id, skill_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ats_template_id "
        "ON agent_template_skills(template_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ats_skill_id "
        "ON agent_template_skills(skill_id)"
    )

    # -------------------------------------------------------------------------
    # agent_template_tools — tools attached to a specific agent/template
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_template_tools (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            template_id UUID NOT NULL REFERENCES agent_cards(id) ON DELETE CASCADE,
            tool_id     UUID NOT NULL REFERENCES tool_catalog(id) ON DELETE CASCADE,
            UNIQUE(template_id, tool_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_att_template_id "
        "ON agent_template_tools(template_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_att_tool_id "
        "ON agent_template_tools(tool_id)"
    )

    # -------------------------------------------------------------------------
    # mcp_integration_imports — PA MCP Integration Builder import sessions
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mcp_integration_imports (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID REFERENCES tenants(id) ON DELETE CASCADE,
            source_type         VARCHAR(20) NOT NULL
                                CHECK (source_type IN ('openapi', 'postman', 'raw_text')),
            source_filename     TEXT,
            source_url          TEXT,
            parsed_endpoints    JSONB,
            selected_endpoints  JSONB,
            generated_tool_ids  UUID[],
            imported_by         UUID REFERENCES users(id) ON DELETE SET NULL,
            imported_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mcp_imports_tenant_id "
        "ON mcp_integration_imports(tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mcp_imports_imported_at "
        "ON mcp_integration_imports(imported_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mcp_integration_imports CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_template_tools CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_template_skills CASCADE")
    op.execute("DROP POLICY IF EXISTS tenant_skills_platform_admin ON tenant_skills")
    op.execute("DROP POLICY IF EXISTS tenant_skills_tenant_isolation ON tenant_skills")
    op.execute("DROP TABLE IF EXISTS tenant_skills CASCADE")
    # Drop agent_cards extension columns
    op.execute(
        """
        ALTER TABLE agent_cards
            DROP COLUMN IF EXISTS imported_card,
            DROP COLUMN IF EXISTS source_card_url,
            DROP COLUMN IF EXISTS a2a_interface,
            DROP COLUMN IF EXISTS attached_tools,
            DROP COLUMN IF EXISTS attached_skills,
            DROP COLUMN IF EXISTS kb_policy,
            DROP COLUMN IF EXISTS llm_policy,
            DROP COLUMN IF EXISTS template_type
        """
    )
