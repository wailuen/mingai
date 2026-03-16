"""
029 access_requests table for TA-010 access request workflow.

Stores KB and agent access requests from end users.
Tenant admins can approve or deny requests.
On approval: user_id is added to allowed_user_ids in the relevant
  kb_access_control or agent_access_control row.

Table:
  access_requests(
    id              UUID PK,
    tenant_id       UUID NOT NULL FK tenants(id),
    user_id         UUID NOT NULL,       -- requester
    resource_type   VARCHAR(10) CHECK('kb'|'agent'),
    resource_id     UUID NOT NULL,       -- index_id or agent_id
    justification   TEXT NOT NULL,
    status          VARCHAR(10) CHECK('pending'|'approved'|'denied'),
    admin_note      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
  )
  UNIQUE(tenant_id, user_id, resource_type, resource_id)
    WHERE status = 'pending'    -- one pending request per user per resource

RLS: tenant isolation. Platform admin bypass.

Revision ID: 029
Revises: 028
Create Date: 2026-03-16
"""
from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS access_requests (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id         UUID NOT NULL,
            resource_type   VARCHAR(10) NOT NULL
                CHECK (resource_type IN ('kb', 'agent')),
            resource_id     UUID NOT NULL,
            justification   TEXT NOT NULL DEFAULT '',
            status          VARCHAR(10) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'denied')),
            admin_note      TEXT,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    # Partial unique index: one pending request per user per resource
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_access_requests_pending_unique "
        "ON access_requests (tenant_id, user_id, resource_type, resource_id) "
        "WHERE status = 'pending'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_access_requests_tenant "
        "ON access_requests (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_access_requests_status "
        "ON access_requests (tenant_id, status)"
    )
    op.execute("ALTER TABLE access_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE access_requests FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY access_requests_tenant ON access_requests
        FOR ALL
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
        """
    )
    op.execute(
        """
        CREATE POLICY access_requests_platform ON access_requests
        FOR ALL
        USING (current_setting('app.scope', true) = 'platform')
        WITH CHECK (current_setting('app.scope', true) = 'platform')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS access_requests_platform ON access_requests")
    op.execute("DROP POLICY IF EXISTS access_requests_tenant ON access_requests")
    op.execute("DROP TABLE IF EXISTS access_requests")
