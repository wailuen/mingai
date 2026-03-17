"""
039 llm_providers table for platform-level LLM credential management (PVDR-001).

Stores encrypted API credentials for each LLM provider (Azure OpenAI, OpenAI,
Anthropic, etc.). Credentials are encrypted at rest using Fernet symmetric
encryption derived from JWT_SECRET_KEY. api_key_encrypted is BYTEA — never
plaintext.

Table:
  llm_providers(
    id                  UUID PK,
    provider_type       VARCHAR(50) NOT NULL CHECK(azure_openai|openai|anthropic|deepseek|dashscope|doubao|gemini),
    display_name        VARCHAR(200) NOT NULL,
    description         TEXT,
    endpoint            VARCHAR(500),
    api_key_encrypted   BYTEA NOT NULL,
    models              JSONB NOT NULL DEFAULT '{}',
    options             JSONB NOT NULL DEFAULT '{}',
    pricing             JSONB,
    is_enabled          BOOLEAN NOT NULL DEFAULT true,
    is_default          BOOLEAN NOT NULL DEFAULT false,
    provider_status     VARCHAR(50) NOT NULL DEFAULT 'unchecked',
    last_health_check_at TIMESTAMPTZ,
    health_error        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by          UUID FK users(id)
  )

Partial unique index: only one row may have is_default = true.

RLS: platform_admin_bypass ONLY (no tenant isolation — this is platform-level).

Revision ID: 039
Revises: 038
Create Date: 2026-03-17
"""
from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_providers (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            provider_type        VARCHAR(50) NOT NULL
                CHECK (provider_type IN (
                    'azure_openai', 'openai', 'anthropic',
                    'deepseek', 'dashscope', 'doubao', 'gemini'
                )),
            display_name         VARCHAR(200) NOT NULL,
            description          TEXT,
            endpoint             VARCHAR(500),
            api_key_encrypted    BYTEA NOT NULL,
            models               JSONB NOT NULL DEFAULT '{}',
            options              JSONB NOT NULL DEFAULT '{}',
            pricing              JSONB,
            is_enabled           BOOLEAN NOT NULL DEFAULT true,
            is_default           BOOLEAN NOT NULL DEFAULT false,
            provider_status      VARCHAR(50) NOT NULL DEFAULT 'unchecked',
            last_health_check_at TIMESTAMPTZ,
            health_error         TEXT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by           UUID REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    # Unique partial index enforces single-default invariant AND serves as lookup index.
    # No separate plain index needed — unique index covers both purposes.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS llm_providers_single_default "
        "ON llm_providers (is_default) WHERE is_default = true"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_providers_enabled "
        "ON llm_providers (is_enabled)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_providers_type "
        "ON llm_providers (provider_type)"
    )
    # Platform-level table — no tenant isolation RLS.
    # Only platform admins (scope='platform') may access this table.
    op.execute("ALTER TABLE llm_providers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE llm_providers FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY llm_providers_platform ON llm_providers
        FOR ALL
        USING (current_setting('app.scope', true) = 'platform')
        WITH CHECK (current_setting('app.scope', true) = 'platform')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS llm_providers_platform ON llm_providers")
    op.execute("DROP TABLE IF EXISTS llm_providers")
