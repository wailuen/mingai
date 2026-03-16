"""
009 LLM Library Table.

Creates the llm_library table for platform-managed model catalogue.
Platform admins curate model entries; tenants see only Published entries.

Schema:
  llm_library(id, provider, model_name, display_name, plan_tier,
              is_recommended, status, best_practices_md,
              pricing_per_1k_tokens_in, pricing_per_1k_tokens_out,
              created_at, updated_at)

Status lifecycle: Draft → Published → Deprecated
  (Deprecated cannot transition back — enforced at API layer)

RLS policies:
  - platform_admin: bypass via app.user_role = 'platform_admin'
  - tenant: SELECT only Published rows

Revision ID: 009
Revises: 008
Create Date: 2026-03-16
"""
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_library (
            id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            provider                   VARCHAR(50) NOT NULL,
            model_name                 VARCHAR(200) NOT NULL,
            display_name               VARCHAR(200) NOT NULL,
            plan_tier                  VARCHAR(50) NOT NULL,
            is_recommended             BOOLEAN NOT NULL DEFAULT false,
            status                     VARCHAR(50) NOT NULL DEFAULT 'Draft',
            best_practices_md          TEXT,
            pricing_per_1k_tokens_in   NUMERIC(10,6),
            pricing_per_1k_tokens_out  NUMERIC(10,6),
            created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT llm_library_status_check
                CHECK (status IN ('Draft', 'Published', 'Deprecated')),
            CONSTRAINT llm_library_provider_check
                CHECK (provider IN ('azure_openai', 'openai_direct', 'anthropic'))
        )
        """
    )

    # Enable RLS
    op.execute("ALTER TABLE llm_library ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE llm_library FORCE ROW LEVEL SECURITY")

    # Platform admin bypass — full access when app.user_role = 'platform_admin'
    op.execute(
        """
        CREATE POLICY llm_library_platform_admin ON llm_library
            USING (current_setting('app.user_role', true) = 'platform_admin')
        """
    )

    # Tenant read — Published rows only
    op.execute(
        """
        CREATE POLICY llm_library_tenant_read ON llm_library
            FOR SELECT
            USING (status = 'Published')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS llm_library_tenant_read ON llm_library")
    op.execute("DROP POLICY IF EXISTS llm_library_platform_admin ON llm_library")
    op.execute("DROP TABLE IF EXISTS llm_library")
