"""
027 kb_access_control table for TA-006 KB access control.

Controls which users/roles can access a knowledge base index.
Default (no row): workspace_wide — all tenant users can search the KB.

Table:
  kb_access_control(
    id              UUID PK,
    tenant_id       UUID NOT NULL FK tenants(id),
    index_id        UUID NOT NULL,   -- integrations/indexes id
    visibility_mode VARCHAR(20) CHECK(workspace_wide|role_restricted|user_specific|agent_only),
    allowed_roles   VARCHAR[] nullable,
    allowed_user_ids UUID[] nullable,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
  )
  UNIQUE(tenant_id, index_id)

RLS: tenant isolation (standard). Platform admin bypass for cross-tenant management.

Revision ID: 027
Revises: 026
Create Date: 2026-03-16
"""
from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_access_control (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            index_id        UUID NOT NULL,
            visibility_mode VARCHAR(20) NOT NULL DEFAULT 'workspace_wide'
                CHECK (visibility_mode IN
                    ('workspace_wide', 'role_restricted', 'user_specific', 'agent_only')),
            allowed_roles    VARCHAR[] DEFAULT '{}',
            allowed_user_ids UUID[]    DEFAULT '{}',
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT kb_access_control_unique UNIQUE (tenant_id, index_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kb_access_control_tenant "
        "ON kb_access_control (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kb_access_control_index "
        "ON kb_access_control (index_id)"
    )
    op.execute("ALTER TABLE kb_access_control ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kb_access_control FORCE ROW LEVEL SECURITY")
    # Tenant sessions: own rows only.
    op.execute(
        """
        CREATE POLICY kb_access_control_tenant ON kb_access_control
        FOR ALL
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
        """
    )
    # Platform admin: full access across tenants.
    op.execute(
        """
        CREATE POLICY kb_access_control_platform ON kb_access_control
        FOR ALL
        USING (current_setting('app.scope', true) = 'platform')
        WITH CHECK (current_setting('app.scope', true) = 'platform')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS kb_access_control_platform ON kb_access_control")
    op.execute("DROP POLICY IF EXISTS kb_access_control_tenant ON kb_access_control")
    op.execute("DROP TABLE IF EXISTS kb_access_control")
