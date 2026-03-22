"""
Add last_tested_at column to agent_cards.

Allows publish gate to require at least one successful test run before
an agent can be published. Nullable — existing agents are unaffected.
"""

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_cards "
        "ADD COLUMN IF NOT EXISTS last_tested_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agent_cards "
        "DROP COLUMN IF EXISTS last_tested_at"
    )
