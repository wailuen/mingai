"""
006 Notifications Table.

Creates the notifications table for persistent in-app notifications (API-117 to API-120).

Schema:
  notifications(id, tenant_id, user_id, type, title, body, link, read, created_at)

RLS policy scopes notifications to the current tenant.

Revision ID: 006
Revises: 005
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type        VARCHAR(50) NOT NULL,
            title       VARCHAR(200) NOT NULL,
            body        TEXT NOT NULL DEFAULT '',
            link        VARCHAR(500),
            read        BOOLEAN NOT NULL DEFAULT false,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # Indexes for efficient per-user queries (most common access pattern)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_user_tenant "
        "ON notifications (tenant_id, user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_unread "
        "ON notifications (tenant_id, user_id, read) WHERE read = false"
    )

    # Enable RLS
    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY notifications_tenant ON notifications
            USING (tenant_id = current_setting('app.tenant_id')::UUID)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS notifications_tenant ON notifications")
    op.execute("DROP TABLE IF EXISTS notifications")
