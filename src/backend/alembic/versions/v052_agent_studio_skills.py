"""v052 — Agent Studio: Skills Library tables

Revision ID: 052
Revises: 050
Create Date: 2026-03-22

Creates:
  - skills: platform and tenant-authored skills (prompt/tool_composing/sequential_pipeline)
  - skill_versions: immutable version history for each published skill
  - skill_tool_dependencies: relational join for skill → tool_catalog FK integrity

RLS:
  - platform-scoped skills (scope='platform') visible to all authenticated users
  - tenant-scoped skills (scope=tenant_id) visible only to that tenant

Note: v051 is reserved for Bedrock provider migration.
"""
from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # skills table
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS skills (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name                VARCHAR(255) NOT NULL,
            description         TEXT,
            category            VARCHAR(100),
            version             VARCHAR(20) NOT NULL DEFAULT '1.0.0',
            changelog           TEXT,
            input_schema        JSONB NOT NULL DEFAULT '{}',
            output_schema       JSONB NOT NULL DEFAULT '{}',
            prompt_template     TEXT,
            execution_pattern   VARCHAR(32) NOT NULL DEFAULT 'prompt'
                                CHECK (execution_pattern IN ('prompt', 'tool_composing', 'sequential_pipeline')),
            tool_dependencies   JSONB NOT NULL DEFAULT '[]',
            pipeline_steps      JSONB,
            invocation_mode     VARCHAR(32) NOT NULL DEFAULT 'llm_invoked'
                                CHECK (invocation_mode IN ('llm_invoked', 'pipeline')),
            pipeline_trigger    TEXT,
            llm_config          JSONB NOT NULL DEFAULT '{"temperature": 0.3, "max_tokens": 2000}',
            plan_required       VARCHAR(32)
                                CHECK (plan_required IS NULL OR plan_required IN ('starter', 'professional', 'enterprise')),
            scope               VARCHAR(255) NOT NULL DEFAULT 'platform',
            mandatory           BOOLEAN NOT NULL DEFAULT FALSE,
            status              VARCHAR(32) NOT NULL DEFAULT 'draft'
                                CHECK (status IN ('draft', 'published', 'deprecated')),
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            published_at        TIMESTAMPTZ,
            created_by          UUID REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_skills_scope ON skills(scope)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_skills_category ON skills(category)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_skills_mandatory ON skills(mandatory)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_skills_tool_dependencies "
        "ON skills USING GIN(tool_dependencies)"
    )

    # -------------------------------------------------------------------------
    # RLS for skills
    # -------------------------------------------------------------------------
    op.execute("ALTER TABLE skills ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE skills FORCE ROW LEVEL SECURITY")
    # Platform-scoped skills: visible to any authenticated session
    op.execute(
        """
        CREATE POLICY skills_platform_read ON skills
        FOR SELECT
        USING (scope = 'platform')
        """
    )
    # Tenant-scoped skills: visible only to the owning tenant
    op.execute(
        """
        CREATE POLICY skills_tenant_read ON skills
        FOR SELECT
        USING (scope = current_setting('app.current_tenant_id', true))
        """
    )
    # Platform admins: full access
    op.execute(
        """
        CREATE POLICY skills_platform_admin ON skills
        FOR ALL
        USING (current_setting('app.scope', true) = 'platform')
        WITH CHECK (current_setting('app.scope', true) = 'platform')
        """
    )
    # Tenant admins: can write to their own tenant-scoped skills
    op.execute(
        """
        CREATE POLICY skills_tenant_write ON skills
        FOR ALL
        USING (scope = current_setting('app.current_tenant_id', true))
        WITH CHECK (scope = current_setting('app.current_tenant_id', true))
        """
    )

    # -------------------------------------------------------------------------
    # skill_versions table — immutable version history
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_versions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            skill_id        UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            version_label   VARCHAR(20) NOT NULL,
            change_type     VARCHAR(10) NOT NULL CHECK (change_type IN ('initial', 'patch', 'minor', 'major')),
            changelog       TEXT NOT NULL,
            published_by    UUID NOT NULL,
            published_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            snapshot        JSONB
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_skill_versions_skill_id "
        "ON skill_versions(skill_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_skill_versions_published_at "
        "ON skill_versions(published_at DESC)"
    )

    # -------------------------------------------------------------------------
    # skill_tool_dependencies — relational join for FK integrity
    # Canonical source of truth; skills.tool_dependencies JSONB is denormalized cache
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_tool_dependencies (
            id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            skill_id UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
            tool_id  UUID NOT NULL REFERENCES tool_catalog(id) ON DELETE CASCADE,
            required BOOLEAN NOT NULL DEFAULT TRUE,
            UNIQUE(skill_id, tool_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_skill_tool_deps_skill_id "
        "ON skill_tool_dependencies(skill_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_skill_tool_deps_tool_id "
        "ON skill_tool_dependencies(tool_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS skill_tool_dependencies CASCADE")
    op.execute("DROP TABLE IF EXISTS skill_versions CASCADE")
    op.execute("DROP POLICY IF EXISTS skills_tenant_write ON skills")
    op.execute("DROP POLICY IF EXISTS skills_platform_admin ON skills")
    op.execute("DROP POLICY IF EXISTS skills_tenant_read ON skills")
    op.execute("DROP POLICY IF EXISTS skills_platform_read ON skills")
    op.execute("DROP TABLE IF EXISTS skills CASCADE")
