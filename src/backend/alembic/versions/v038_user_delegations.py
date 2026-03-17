"""
038 user_delegations table for tenant admin role delegation (TA-035).

Table:
  user_delegations(
    id               UUID PK,
    tenant_id        UUID NOT NULL FK tenants(id),
    user_id          UUID NOT NULL FK users(id),
    delegated_scope  VARCHAR(64) NOT NULL — kb_admin | agent_admin | user_admin,
    resource_id      UUID NULL            — specific KB/agent for scoped admins,
    granted_by       UUID NOT NULL FK users(id),
    expires_at       TIMESTAMPTZ NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
  )
  INDEX (tenant_id, user_id)

RLS: tenant_isolation + platform_admin_bypass

Revision ID: 038
Revises: 037
Create Date: 2026-03-17
"""
from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_delegations (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            delegated_scope  VARCHAR(64) NOT NULL
                CHECK (delegated_scope IN ('kb_admin', 'agent_admin', 'user_admin')),
            resource_id      UUID NULL,
            granted_by       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at       TIMESTAMPTZ NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_delegations_tenant_user "
        "ON user_delegations (tenant_id, user_id)"
    )
    op.execute("ALTER TABLE user_delegations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_delegations FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY user_delegations_tenant ON user_delegations
        FOR ALL
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
        """
    )
    op.execute(
        """
        CREATE POLICY user_delegations_platform ON user_delegations
        FOR ALL
        USING (current_setting('app.scope', true) = 'platform')
        WITH CHECK (current_setting('app.scope', true) = 'platform')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS user_delegations_platform ON user_delegations")
    op.execute("DROP POLICY IF EXISTS user_delegations_tenant ON user_delegations")
    op.execute("DROP TABLE IF EXISTS user_delegations")
