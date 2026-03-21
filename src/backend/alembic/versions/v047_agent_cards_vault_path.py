"""v047 — Add credentials_vault_path to agent_cards

Revision ID: 047
Revises: 046b
Create Date: 2026-03-21

Note: platform_credentials auth_mode deferred to Phase C.
"""
from alembic import op
import sqlalchemy as sa

revision = "047"
down_revision = "046b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_cards", sa.Column(
        "credentials_vault_path",
        sa.Text(),
        nullable=True
    ))


def downgrade() -> None:
    op.drop_column("agent_cards", "credentials_vault_path")
