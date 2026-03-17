"""
033 consent_events table for GDPR consent audit trail (DEF-002).

Immutable audit trail of user consent actions. No UPDATE or DELETE is
permitted at the application layer (routes return 405). The migration
itself is standard DDL — immutability is enforced at the service layer.

Table:
  consent_events(
    id           UUID PK,
    tenant_id    UUID NOT NULL FK tenants(id),
    user_id      UUID NOT NULL FK users(id),
    consent_type VARCHAR CHECK('data_processing','memory_learning',
                               'org_context','profile_sharing'),
    action       VARCHAR CHECK('granted','revoked'),
    ip_address   INET nullable,
    user_agent   TEXT nullable,
    created_at   TIMESTAMPTZ DEFAULT NOW()
  )

Index: (tenant_id, user_id, created_at DESC)

RLS: 3-tier
  - user sees own rows: user_id = current_setting('app.current_user_id')
  - tenant_admin sees tenant rows: tenant_id = current_setting('app.tenant_id')
  - platform_admin sees all: current_setting('app.scope') = 'platform'

Revision ID: 033
Revises: 032
Create Date: 2026-03-17
"""
from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS consent_events (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            consent_type VARCHAR(50) NOT NULL
                CHECK (consent_type IN (
                    'data_processing', 'memory_learning',
                    'org_context', 'profile_sharing'
                )),
            action       VARCHAR(10) NOT NULL
                CHECK (action IN ('granted', 'revoked')),
            ip_address   INET,
            user_agent   TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_consent_events_user "
        "ON consent_events (tenant_id, user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_consent_events_tenant "
        "ON consent_events (tenant_id)"
    )
    op.execute("ALTER TABLE consent_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE consent_events FORCE ROW LEVEL SECURITY")
    # SELECT: user sees own rows; tenant_admin sees all tenant rows; platform sees all
    op.execute(
        """
        CREATE POLICY consent_events_select ON consent_events
        FOR SELECT
        USING (
            user_id::text = current_setting('app.current_user_id', true)
            OR tenant_id::text = current_setting('app.tenant_id', true)
            OR current_setting('app.scope', true) = 'platform'
        )
        """
    )
    # INSERT: only the consenting user (or platform service role) may create records.
    # Tenant admins may NOT insert consent events on behalf of users.
    op.execute(
        """
        CREATE POLICY consent_events_insert ON consent_events
        FOR INSERT
        WITH CHECK (
            user_id::text = current_setting('app.current_user_id', true)
            OR current_setting('app.scope', true) = 'platform'
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS consent_events_select ON consent_events")
    op.execute("DROP POLICY IF EXISTS consent_events_insert ON consent_events")
    op.execute("DROP TABLE IF EXISTS consent_events")
