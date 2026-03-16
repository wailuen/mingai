"""
028 agent_access_control table for TA-008 Agent access control.

Controls which users/roles can invoke a deployed agent (agent_cards).
Default (no row): workspace_wide — all tenant users can invoke.
agent_only mode does NOT apply to agents (only to KBs).

Table:
  agent_access_control(
    id              UUID PK,
    tenant_id       UUID NOT NULL FK tenants(id),
    agent_id        UUID NOT NULL FK agent_cards(id),
    visibility_mode VARCHAR(20) CHECK(workspace_wide|role_restricted|user_specific),
    allowed_roles   VARCHAR[] nullable,
    allowed_user_ids UUID[] nullable,
    created_at      TIMESTAMPTZ DEFAULT NOW()
  )
  UNIQUE(tenant_id, agent_id)

RLS: tenant isolation. Platform admin bypass.

Revision ID: 028
Revises: 027
Create Date: 2026-03-16
"""
from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_access_control (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            agent_id        UUID NOT NULL REFERENCES agent_cards(id) ON DELETE CASCADE,
            visibility_mode VARCHAR(20) NOT NULL DEFAULT 'workspace_wide'
                CHECK (visibility_mode IN
                    ('workspace_wide', 'role_restricted', 'user_specific')),
            allowed_roles    VARCHAR[] DEFAULT '{}',
            allowed_user_ids UUID[]    DEFAULT '{}',
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT agent_access_control_unique UNIQUE (tenant_id, agent_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_access_control_tenant "
        "ON agent_access_control (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_access_control_agent "
        "ON agent_access_control (agent_id)"
    )
    op.execute("ALTER TABLE agent_access_control ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_access_control FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY agent_access_control_tenant ON agent_access_control
        FOR ALL
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
        """
    )
    op.execute(
        """
        CREATE POLICY agent_access_control_platform ON agent_access_control
        FOR ALL
        USING (current_setting('app.scope', true) = 'platform')
        WITH CHECK (current_setting('app.scope', true) = 'platform')
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS agent_access_control_platform ON agent_access_control"
    )
    op.execute(
        "DROP POLICY IF EXISTS agent_access_control_tenant ON agent_access_control"
    )
    op.execute("DROP TABLE IF EXISTS agent_access_control")
