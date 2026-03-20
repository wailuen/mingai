"""043 glossary_miss_signals unique constraint — enable idempotent upserts.

Adds UNIQUE (tenant_id, unresolved_term) to glossary_miss_signals so that
run_miss_signals_job() can use ON CONFLICT DO UPDATE to increment
occurrence_count instead of silently dropping duplicate rows.

Revision ID: 043
Revises: 042
Create Date: 2026-03-20
"""
from alembic import op

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE glossary_miss_signals
            ADD CONSTRAINT uq_miss_signals_tenant_term
            UNIQUE (tenant_id, unresolved_term)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE glossary_miss_signals
            DROP CONSTRAINT IF EXISTS uq_miss_signals_tenant_term
        """
    )
