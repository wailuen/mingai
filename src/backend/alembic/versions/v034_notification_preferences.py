"""
034 notification_preferences table for per-user notification control (DEF-003).

Stores per-user notification type preferences. Missing rows imply default
(channel=in_app, enabled=true). UNIQUE(tenant_id, user_id, notification_type)
ensures one setting row per type per user.

Table:
  notification_preferences(
    id                UUID PK,
    tenant_id         UUID NOT NULL FK tenants(id),
    user_id           UUID NOT NULL FK users(id),
    notification_type VARCHAR CHECK('issue_update','sync_failure',
                                    'access_request','platform_message','digest'),
    channel           VARCHAR CHECK('in_app','email','both'),
    enabled           BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
  )
  UNIQUE(tenant_id, user_id, notification_type)

RLS: tenant_isolation + platform_admin_bypass (in this migration)

Revision ID: 034
Revises: 033
Create Date: 2026-03-17
"""
from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_preferences (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            notification_type VARCHAR(50) NOT NULL
                CHECK (notification_type IN (
                    'issue_update', 'sync_failure', 'access_request',
                    'platform_message', 'digest'
                )),
            channel           VARCHAR(10) NOT NULL DEFAULT 'in_app'
                CHECK (channel IN ('in_app', 'email', 'both')),
            enabled           BOOLEAN NOT NULL DEFAULT TRUE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT notification_preferences_unique
                UNIQUE (tenant_id, user_id, notification_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_prefs_user "
        "ON notification_preferences (tenant_id, user_id)"
    )
    op.execute("ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notification_preferences FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY notification_preferences_tenant ON notification_preferences
        FOR ALL
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
        """
    )
    op.execute(
        """
        CREATE POLICY notification_preferences_platform ON notification_preferences
        FOR ALL
        USING (current_setting('app.scope', true) = 'platform')
        WITH CHECK (current_setting('app.scope', true) = 'platform')
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS notification_preferences_platform ON notification_preferences"
    )
    op.execute(
        "DROP POLICY IF EXISTS notification_preferences_tenant ON notification_preferences"
    )
    op.execute("DROP TABLE IF EXISTS notification_preferences")
