"""
015 Notifications Platform Outreach Columns (PA-011).

Adds two columns to the notifications table to support platform admin
proactive outreach (PA-011):

  - from_platform_admin BOOLEAN NOT NULL DEFAULT FALSE
    Marks notifications sent by a platform admin via the outreach endpoint.

  - read_at TIMESTAMPTZ
    Timestamp when the notification was read (NULL = unread).
    Complements the existing 'read' boolean flag for analytics/audit.

Revision ID: 015
Revises: 014
Create Date: 2026-03-16
"""
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE notifications "
        "ADD COLUMN IF NOT EXISTS from_platform_admin BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE notifications " "ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ"
    )

    # Index to efficiently surface unread platform-admin outreach notifications
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_platform_outreach "
        "ON notifications (tenant_id, from_platform_admin, read) "
        "WHERE from_platform_admin = TRUE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_notifications_platform_outreach")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS read_at")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS from_platform_admin")
