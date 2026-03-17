"""
035 user_privacy_settings table for DEF-004.

Stores per-user privacy feature flags. Missing row implies all features
enabled (default-permissive). UNIQUE(tenant_id, user_id) — one row per user.

Table:
  user_privacy_settings(
    id                       UUID PK,
    tenant_id                UUID NOT NULL FK tenants(id),
    user_id                  UUID NOT NULL FK users(id),
    profile_learning_enabled BOOLEAN DEFAULT TRUE,
    working_memory_enabled   BOOLEAN DEFAULT TRUE,
    org_context_enabled      BOOLEAN DEFAULT TRUE,
    updated_at               TIMESTAMPTZ DEFAULT NOW()
  )
  UNIQUE(tenant_id, user_id)

RLS: tenant_isolation + platform_admin_bypass (in this migration)

Revision ID: 035
Revises: 034
Create Date: 2026-03-17
"""
from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_privacy_settings (
            id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id                  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            profile_learning_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            working_memory_enabled   BOOLEAN NOT NULL DEFAULT TRUE,
            org_context_enabled      BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT user_privacy_settings_unique UNIQUE (tenant_id, user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_privacy_settings_user "
        "ON user_privacy_settings (tenant_id, user_id)"
    )
    op.execute("ALTER TABLE user_privacy_settings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_privacy_settings FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY user_privacy_settings_tenant ON user_privacy_settings
        FOR ALL
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
        """
    )
    op.execute(
        """
        CREATE POLICY user_privacy_settings_platform ON user_privacy_settings
        FOR ALL
        USING (current_setting('app.scope', true) = 'platform')
        WITH CHECK (current_setting('app.scope', true) = 'platform')
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS user_privacy_settings_platform ON user_privacy_settings"
    )
    op.execute(
        "DROP POLICY IF EXISTS user_privacy_settings_tenant ON user_privacy_settings"
    )
    op.execute("DROP TABLE IF EXISTS user_privacy_settings")
