"""044 integrations.expires_at — OAuth credential expiry timestamp.

Adds expires_at TIMESTAMPTZ NULL to integrations so that:
  - credential_expiry_job can write token expiry after each credential check
  - sync-status endpoint can surface "N days until re-auth required" to tenant admins
  - No existing rows are affected (NULL = expiry unknown / not applicable)

Revision ID: 044
Revises: 043
Create Date: 2026-03-20
"""
from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE integrations
            ADD COLUMN expires_at TIMESTAMPTZ NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE integrations
            DROP COLUMN IF EXISTS expires_at
        """
    )
