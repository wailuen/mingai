"""
007 Agent Registry Columns.

Adds public registry columns to agent_cards (API-089 to API-098):
- is_public: BOOLEAN — whether the agent is visible in the global registry
- a2a_endpoint: TEXT — HTTPS endpoint for A2A protocol communication
- transaction_types: TEXT[] — supported transaction types (RFQ, CAPABILITY_QUERY, etc.)
- industries: TEXT[] — industry verticals the agent serves
- languages: TEXT[] — supported languages (ISO 639-1 codes)
- health_check_url: TEXT — HTTPS URL for health monitoring

Revision ID: 007
Revises: 006
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # is_public flag — registry visibility
    op.add_column(
        "agent_cards",
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    # A2A protocol endpoint
    op.add_column(
        "agent_cards",
        sa.Column("a2a_endpoint", sa.Text(), nullable=True),
    )
    # Supported transaction types (TEXT array)
    op.add_column(
        "agent_cards",
        sa.Column(
            "transaction_types",
            ARRAY(sa.Text()),
            nullable=True,
            server_default=sa.text("'{}'"),
        ),
    )
    # Industry verticals
    op.add_column(
        "agent_cards",
        sa.Column(
            "industries",
            ARRAY(sa.Text()),
            nullable=True,
            server_default=sa.text("'{}'"),
        ),
    )
    # Supported languages
    op.add_column(
        "agent_cards",
        sa.Column(
            "languages",
            ARRAY(sa.Text()),
            nullable=True,
            server_default=sa.text("'{}'"),
        ),
    )
    # Health check URL for registry monitor
    op.add_column(
        "agent_cards",
        sa.Column("health_check_url", sa.Text(), nullable=True),
    )

    # Indexes for registry queries
    op.create_index(
        "ix_agent_cards_is_public",
        "agent_cards",
        ["is_public"],
        postgresql_where=sa.text("is_public = true"),
    )
    op.create_index(
        "ix_agent_cards_tenant_is_public",
        "agent_cards",
        ["tenant_id", "is_public"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_cards_tenant_is_public", "agent_cards")
    op.drop_index("ix_agent_cards_is_public", "agent_cards")
    op.drop_column("agent_cards", "health_check_url")
    op.drop_column("agent_cards", "languages")
    op.drop_column("agent_cards", "industries")
    op.drop_column("agent_cards", "transaction_types")
    op.drop_column("agent_cards", "a2a_endpoint")
    op.drop_column("agent_cards", "is_public")
