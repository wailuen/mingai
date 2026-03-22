"""v059 — tool_catalog: add description column

Adds the description column to tool_catalog for platform tool display (TODO-17).

Revision ID: 059
Revises: 058
"""
from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tool_catalog
            ADD COLUMN IF NOT EXISTS description TEXT
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tool_catalog DROP COLUMN IF EXISTS description")
