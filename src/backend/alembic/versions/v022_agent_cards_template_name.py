"""
022 agent_cards: add template_name column (PA-023).

Adds `template_name TEXT` to `agent_cards` so that agents deployed from
`agent_templates` (PA-019) store the template's display name at deploy time.
This avoids a JOIN at query time when building the agent list response.

Revision ID: 022
Revises: 021
Create Date: 2026-03-16
"""
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_cards " "ADD COLUMN IF NOT EXISTS template_name TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE agent_cards DROP COLUMN IF EXISTS template_name")
