"""Backfill agent_access_control for existing agent_cards rows.

ATA-012: All existing agents get workspace_wide visibility_mode by default.
Uses explicit ARRAY[]::VARCHAR[] and ARRAY[]::UUID[] casts for safety.

Note: Do NOT inject default guardrails object for existing agents —
guardrail key absence is correct and prevents latency regression.

Revision ID: 046b
Revises: 046a
"""
from alembic import op

revision = "046b"
down_revision = "046a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO agent_access_control (agent_id, tenant_id, visibility_mode, allowed_roles, allowed_user_ids)
        SELECT
            id AS agent_id,
            tenant_id,
            'workspace_wide' AS visibility_mode,
            ARRAY[]::VARCHAR[] AS allowed_roles,
            ARRAY[]::UUID[] AS allowed_user_ids
        FROM agent_cards
        WHERE id NOT IN (SELECT agent_id FROM agent_access_control)
        ON CONFLICT (tenant_id, agent_id) DO NOTHING
    """)


def downgrade() -> None:
    # Cannot safely remove backfill rows without knowing which were pre-existing
    pass
