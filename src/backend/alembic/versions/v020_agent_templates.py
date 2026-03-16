"""
020 Agent Templates Table (PA-019).

Creates the agent_templates platform-level table. No tenant_id — templates are
owned by the platform and published to tenants (read-only via RLS).

Schema:
  agent_templates(
    id, name, description, category,
    system_prompt, variable_definitions, guardrails,
    confidence_threshold, version, status, changelog,
    created_by, created_at, updated_at
  )

  status CHECK: Draft | Published | Deprecated | seed
    - Draft    → editable, not visible to tenants
    - Published → immutable system_prompt; visible to tenants
    - Deprecated → read-only; still visible to tenants for running instances
    - seed     → system-seeded templates; treated as Published for tenant access

  version INTEGER: starts at 1, incremented on each new-version creation
  variable_definitions JSONB: validated at API layer (not DB constraint)
  guardrails JSONB: list of {pattern, action, reason} objects

RLS:
  platform_admin (app.current_scope = 'platform')  → full CRUD
  tenant scope   (app.current_scope = 'tenant')     → SELECT WHERE status IN ('Published', 'seed')

NOTE: RLS is defined here (not relying on v002's frozen _V001_TABLES list).

Revision ID: 020
Revises: 019
Create Date: 2026-03-16
"""
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_templates (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name                    VARCHAR(255) NOT NULL,
            description             TEXT,
            category                VARCHAR(100),
            system_prompt           TEXT NOT NULL,
            variable_definitions    JSONB NOT NULL DEFAULT '[]',
            guardrails              JSONB NOT NULL DEFAULT '[]',
            confidence_threshold    NUMERIC(3, 2) CHECK (
                                        confidence_threshold IS NULL
                                        OR (confidence_threshold >= 0.00 AND confidence_threshold <= 1.00)
                                    ),
            version                 INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
            status                  VARCHAR(20) NOT NULL DEFAULT 'Draft'
                                        CHECK (status IN ('Draft', 'Published', 'Deprecated', 'seed')),
            changelog               TEXT,
            created_by              UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_templates_status "
        "ON agent_templates (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_templates_category "
        "ON agent_templates (category)"
    )

    # RLS: platform admin gets full CRUD; tenant scope gets SELECT on published templates.
    # Application connections must SET app.current_scope appropriately.
    # Superuser / migration connections bypass RLS — safe.
    op.execute("ALTER TABLE agent_templates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_templates FORCE ROW LEVEL SECURITY")

    # Platform admin: read + write
    op.execute(
        """
        CREATE POLICY agent_templates_platform_all ON agent_templates
            FOR ALL
            USING (
                current_setting('app.current_scope', true) = 'platform'
            )
            WITH CHECK (
                current_setting('app.current_scope', true) = 'platform'
            )
        """
    )

    # Tenant scope: read-only, published/seed templates only
    op.execute(
        """
        CREATE POLICY agent_templates_tenant_read ON agent_templates
            FOR SELECT
            USING (
                current_setting('app.current_scope', true) = 'tenant'
                AND status IN ('Published', 'seed')
            )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS agent_templates_tenant_read ON agent_templates")
    op.execute("DROP POLICY IF EXISTS agent_templates_platform_all ON agent_templates")
    op.execute("DROP INDEX IF EXISTS idx_agent_templates_category")
    op.execute("DROP INDEX IF EXISTS idx_agent_templates_status")
    op.execute("DROP TABLE IF EXISTS agent_templates")
