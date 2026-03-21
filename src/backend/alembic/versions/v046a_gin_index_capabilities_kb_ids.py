"""Add GIN index on agent_cards capabilities->kb_ids for reverse KB lookup.

ATA-011: GIN index for "which agents reference this KB?" queries.
NO CONCURRENTLY — table is small, plain CREATE INDEX is correct in a transaction.

Revision ID: 046a
Revises: 045
"""
from alembic import op

revision = "046a"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_agent_cards_capabilities_gin",
        "agent_cards",
        ["capabilities"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_agent_cards_capabilities_gin", table_name="agent_cards")
