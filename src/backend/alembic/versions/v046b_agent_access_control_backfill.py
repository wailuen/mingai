"""Backfill agent_access_control for existing agent_cards rows.

ATA-012: All existing agents get workspace_wide visibility_mode by default.
Uses explicit ARRAY[]::VARCHAR[] and ARRAY[]::UUID[] casts for safety.

Note: Do NOT inject default guardrails object for existing agents —
guardrail key absence is correct and prevents latency regression.

V1 latency regression lesson: injecting {"max_response_length": 0} caused
_has_active_guardrails() to return True for ALL agents, adding 1-2s buffering
to every chat request. Guardrail key must remain ABSENT for existing agents.

ATA-055 PRE-DEPLOY AUDIT (run BEFORE deploying ATA-019 / Stage 7b):
Run the following query to identify agents whose max_response_length will
start truncating responses after Stage 7b goes live. Confirm each is intentional
before deploying:

    SELECT id, capabilities->'guardrails' AS guardrails
    FROM agent_cards
    WHERE capabilities->'guardrails' IS NOT NULL
      AND (capabilities->'guardrails'->>'max_response_length')::int > 0;

Any agent with max_response_length > 0 will start truncating responses after
ATA-019 deploys. If this is unintentional, UPDATE agent_cards SET
capabilities = capabilities #- '{guardrails}' WHERE id = :id before deploying.

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
