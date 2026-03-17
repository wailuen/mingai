"""
030 Agent Cards HAR Phase 0-1 Columns.

Adds missing HAR-specific columns to agent_cards:
- kyb_level: VARCHAR CHECK (replaces INTEGER from v003 — this migration alters the type)
- public_key_fingerprint: VARCHAR nullable
- health_status: VARCHAR DEFAULT 'AVAILABLE'
- trust_score: already exists as INTEGER in v003, add CHECK constraint

The following columns already exist from earlier migrations and are NOT re-added:
  a2a_endpoint       (v007)
  health_check_url   (v007)
  transaction_types  (v007)
  industries         (v007)
  languages          (v007)
  public_key         (v003)
  private_key_enc    (v003)
  trust_score        (v003) — INTEGER, no change
  kyb_level          (v003) — INTEGER, alter to VARCHAR with CHECK

Also creates har_fee_records table (HAR-011).

Revision ID: 030
Revises: 029
Create Date: 2026-03-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, NUMERIC

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. Alter kyb_level: INTEGER → VARCHAR with CHECK constraint
    # -------------------------------------------------------------------------
    op.execute("ALTER TABLE agent_cards ALTER COLUMN kyb_level DROP DEFAULT")
    op.execute(
        "ALTER TABLE agent_cards ALTER COLUMN kyb_level TYPE VARCHAR(20) "
        "USING CASE kyb_level "
        "  WHEN 0 THEN 'none' "
        "  WHEN 1 THEN 'basic' "
        "  WHEN 2 THEN 'verified' "
        "  WHEN 3 THEN 'enterprise' "
        "  ELSE 'none' END"
    )
    op.execute("ALTER TABLE agent_cards ALTER COLUMN kyb_level SET DEFAULT 'none'")
    op.execute(
        "ALTER TABLE agent_cards ADD CONSTRAINT agent_cards_kyb_level_check "
        "CHECK (kyb_level IN ('none', 'basic', 'verified', 'enterprise'))"
    )

    # -------------------------------------------------------------------------
    # 2. Add public_key_fingerprint (nullable)
    # -------------------------------------------------------------------------
    op.add_column(
        "agent_cards",
        sa.Column("public_key_fingerprint", sa.String(128), nullable=True),
    )

    # -------------------------------------------------------------------------
    # 3. Add health_status column
    # -------------------------------------------------------------------------
    op.add_column(
        "agent_cards",
        sa.Column(
            "health_status",
            sa.String(20),
            nullable=False,
            server_default="AVAILABLE",
        ),
    )
    op.execute(
        "ALTER TABLE agent_cards ADD CONSTRAINT agent_cards_health_status_check "
        "CHECK (health_status IN ('AVAILABLE', 'UNAVAILABLE', 'DEGRADED'))"
    )

    # -------------------------------------------------------------------------
    # 4. Ensure languages column has a proper default of '{en}'
    #    (v007 added it with default '{}' — update if still empty)
    # -------------------------------------------------------------------------
    op.execute("ALTER TABLE agent_cards ALTER COLUMN languages SET DEFAULT '{en}'")

    # -------------------------------------------------------------------------
    # 5. Add kyb_stripe_session_id for Stripe Identity session tracking (HAR-012)
    # -------------------------------------------------------------------------
    op.add_column(
        "agent_cards",
        sa.Column("kyb_stripe_session_id", sa.String(128), nullable=True),
    )

    # -------------------------------------------------------------------------
    # 6. Create har_fee_records table (HAR-011)
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS har_fee_records (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            transaction_id  UUID NOT NULL REFERENCES har_transactions(id) ON DELETE CASCADE,
            tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            fee_type        VARCHAR(20) NOT NULL
                CHECK (fee_type IN ('platform_fee', 'network_fee')),
            amount_usd      NUMERIC(12, 4) NOT NULL,
            currency        VARCHAR(10) NOT NULL DEFAULT 'USD',
            fee_basis       TEXT,
            status          VARCHAR(20) NOT NULL DEFAULT 'accrued'
                CHECK (status IN ('accrued', 'collected', 'waived')),
            accrued_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_har_fee_records_tenant_status "
        "ON har_fee_records (tenant_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_har_fee_records_transaction "
        "ON har_fee_records (transaction_id)"
    )

    # RLS for har_fee_records
    op.execute("ALTER TABLE har_fee_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE har_fee_records FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY har_fee_records_tenant ON har_fee_records
        FOR ALL
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
        """
    )
    op.execute(
        """
        CREATE POLICY har_fee_records_platform ON har_fee_records
        FOR ALL
        USING (current_setting('app.scope', true) = 'platform')
        WITH CHECK (current_setting('app.scope', true) = 'platform')
        """
    )


def downgrade() -> None:
    # Drop har_fee_records
    op.execute("DROP POLICY IF EXISTS har_fee_records_platform ON har_fee_records")
    op.execute("DROP POLICY IF EXISTS har_fee_records_tenant ON har_fee_records")
    op.execute("DROP TABLE IF EXISTS har_fee_records")

    # Remove agent_cards additions
    op.execute(
        "ALTER TABLE agent_cards DROP CONSTRAINT IF EXISTS agent_cards_health_status_check"
    )
    op.drop_column("agent_cards", "health_status")
    op.drop_column("agent_cards", "public_key_fingerprint")
    op.drop_column("agent_cards", "kyb_stripe_session_id")

    # Revert kyb_level back to INTEGER
    op.execute(
        "ALTER TABLE agent_cards DROP CONSTRAINT IF EXISTS agent_cards_kyb_level_check"
    )
    op.execute("ALTER TABLE agent_cards ALTER COLUMN kyb_level DROP DEFAULT")
    op.execute(
        "ALTER TABLE agent_cards ALTER COLUMN kyb_level TYPE INTEGER "
        "USING CASE kyb_level "
        "  WHEN 'none' THEN 0 "
        "  WHEN 'basic' THEN 1 "
        "  WHEN 'verified' THEN 2 "
        "  WHEN 'enterprise' THEN 3 "
        "  ELSE 0 END"
    )
    op.execute("ALTER TABLE agent_cards ALTER COLUMN kyb_level SET DEFAULT 0")
    op.execute("ALTER TABLE agent_cards ALTER COLUMN languages SET DEFAULT '{}'")
