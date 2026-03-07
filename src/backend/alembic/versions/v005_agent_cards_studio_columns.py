"""
005 Agent Cards Studio Columns.

Adds Agent Studio management columns to agent_cards (API-069 to API-073):
- category: VARCHAR(100) for agent classification
- source: VARCHAR(50) for library|custom|seed
- avatar: TEXT for avatar URL
- template_id: TEXT nullable for templates deployed from library
- template_version: INTEGER nullable for template version pinning

Revision ID: 005
Revises: 004
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add category column
    op.add_column(
        "agent_cards",
        sa.Column("category", sa.String(100), nullable=True),
    )
    # Add source column — library|custom|seed
    op.add_column(
        "agent_cards",
        sa.Column(
            "source",
            sa.String(50),
            nullable=False,
            server_default="custom",
        ),
    )
    # Add avatar column
    op.add_column(
        "agent_cards",
        sa.Column("avatar", sa.Text(), nullable=True),
    )
    # Add template_id column (nullable FK to agent_cards.id for library templates)
    op.add_column(
        "agent_cards",
        sa.Column("template_id", sa.Text(), nullable=True),
    )
    # Add template_version column
    op.add_column(
        "agent_cards",
        sa.Column("template_version", sa.Integer(), nullable=True),
    )

    # Index for source lookups
    op.create_index("ix_agent_cards_source", "agent_cards", ["source"])
    op.create_index(
        "ix_agent_cards_tenant_status", "agent_cards", ["tenant_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_cards_tenant_status", "agent_cards")
    op.drop_index("ix_agent_cards_source", "agent_cards")
    op.drop_column("agent_cards", "template_version")
    op.drop_column("agent_cards", "template_id")
    op.drop_column("agent_cards", "avatar")
    op.drop_column("agent_cards", "source")
    op.drop_column("agent_cards", "category")
