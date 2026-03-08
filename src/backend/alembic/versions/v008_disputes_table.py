"""
008 Disputes Table.

Creates the disputes table for filing and resolving transaction disputes (GAP-036 / API-124, API-125).

Schema:
  disputes(id, transaction_id, filed_by_tenant_id, reason, category,
           evidence_urls, desired_resolution, status, resolved_by,
           resolution, resolution_notes, filed_at, resolved_at)

Revision ID: 008
Revises: 007
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS disputes (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            transaction_id      UUID NOT NULL REFERENCES har_transactions(id),
            filed_by_tenant_id  UUID NOT NULL,
            reason              TEXT NOT NULL,
            category            VARCHAR(50) NOT NULL,
            evidence_urls       JSONB DEFAULT '[]',
            desired_resolution  TEXT NOT NULL,
            status              VARCHAR(50) NOT NULL DEFAULT 'open',
            resolved_by         UUID,
            resolution          VARCHAR(50),
            resolution_notes    TEXT,
            filed_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at         TIMESTAMPTZ
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_disputes_transaction_id "
        "ON disputes (transaction_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_disputes_filed_by_tenant "
        "ON disputes (filed_by_tenant_id, filed_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_disputes_status "
        "ON disputes (status) WHERE status = 'open'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_disputes_status")
    op.execute("DROP INDEX IF EXISTS idx_disputes_filed_by_tenant")
    op.execute("DROP INDEX IF EXISTS idx_disputes_transaction_id")
    op.execute("DROP TABLE IF EXISTS disputes")
