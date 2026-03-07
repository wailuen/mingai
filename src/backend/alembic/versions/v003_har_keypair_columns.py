"""
003 HAR Keypair Columns and Transaction Tables.

Adds Ed25519 keypair + trust columns to agent_cards (AI-040).
Creates har_transactions and har_transaction_events tables (AI-043).
Adds RLS policies for new tables.

Revision ID: 003
Revises: 002
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, NUMERIC

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. Extend agent_cards with HAR keypair + trust columns
    # -------------------------------------------------------------------------
    op.add_column(
        "agent_cards",
        sa.Column("public_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "agent_cards",
        sa.Column("private_key_enc", sa.Text(), nullable=True),
    )
    op.add_column(
        "agent_cards",
        sa.Column(
            "trust_score",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "agent_cards",
        sa.Column(
            "kyb_level",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # -------------------------------------------------------------------------
    # 2. Create har_transactions table
    # -------------------------------------------------------------------------
    op.create_table(
        "har_transactions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "initiator_agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_cards.id"),
            nullable=False,
        ),
        sa.Column(
            "counterparty_agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_cards.id"),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.String(50),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("amount", NUMERIC(18, 6), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("payload", JSONB(), nullable=True, server_default="{}"),
        sa.Column(
            "requires_human_approval",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("human_approved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "human_approved_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("approval_deadline", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("chain_head_hash", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "state IN ('DRAFT','OPEN','NEGOTIATING','COMMITTED','EXECUTING',"
            "'COMPLETED','ABANDONED','DISPUTED','RESOLVED')",
            name="har_transactions_state_check",
        ),
    )

    op.create_index(
        "ix_har_transactions_tenant_id",
        "har_transactions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_har_transactions_state",
        "har_transactions",
        ["state"],
    )

    # -------------------------------------------------------------------------
    # 3. Create har_transaction_events table
    # -------------------------------------------------------------------------
    op.create_table(
        "har_transaction_events",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            UUID(as_uuid=True),
            sa.ForeignKey("har_transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column(
            "actor_agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_cards.id"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("payload", JSONB(), nullable=True, server_default="{}"),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("nonce", sa.String(64), nullable=True),
        sa.Column("prev_event_hash", sa.Text(), nullable=True),
        sa.Column("event_hash", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_index(
        "ix_har_transaction_events_transaction_id",
        "har_transaction_events",
        ["transaction_id"],
    )
    op.create_index(
        "ix_har_transaction_events_tenant_id",
        "har_transaction_events",
        ["tenant_id"],
    )

    # -------------------------------------------------------------------------
    # 4. RLS policies for new tables
    # -------------------------------------------------------------------------
    for table in ("har_transactions", "har_transaction_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
            f"USING (tenant_id = current_setting('app.current_tenant_id')::uuid) "
            f"WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid);"
        )
        op.execute(
            f"CREATE POLICY platform_admin_bypass ON {table} FOR ALL "
            f"USING (current_setting('app.scope', true) = 'platform') "
            f"WITH CHECK (current_setting('app.scope', true) = 'platform');"
        )


def downgrade() -> None:
    # Remove RLS policies
    for table in ("har_transaction_events", "har_transactions"):
        op.execute(f"DROP POLICY IF EXISTS platform_admin_bypass ON {table};")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # Drop tables
    op.drop_table("har_transaction_events")
    op.drop_table("har_transactions")

    # Remove columns from agent_cards
    op.drop_column("agent_cards", "kyb_level")
    op.drop_column("agent_cards", "trust_score")
    op.drop_column("agent_cards", "private_key_enc")
    op.drop_column("agent_cards", "public_key")
