"""
016 Cost Summary Daily Table (PA-012).

Creates the cost_summary_daily table for storing nightly aggregated token
attribution and cost data per tenant per day.

Schema:
  cost_summary_daily(id, tenant_id, date, total_tokens_in, total_tokens_out,
    total_cost_usd, model_breakdown, created_at, updated_at)

model_breakdown JSONB structure:
  [{"provider": "azure_openai", "model": "gpt-5", "tokens_in": 1234,
    "tokens_out": 567, "cost_usd": 0.003456}]

RLS: platform admin only (app.current_scope = 'platform') — same pattern
     as v014 tenant_health_scores. NOT relying on v002 frozen _V001_TABLES.

Revision ID: 016
Revises: 015
Create Date: 2026-03-16
"""
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cost_summary_daily (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            date             DATE NOT NULL,
            total_tokens_in  BIGINT NOT NULL DEFAULT 0,
            total_tokens_out BIGINT NOT NULL DEFAULT 0,
            total_cost_usd   NUMERIC(12, 6) NOT NULL DEFAULT 0,
            model_breakdown  JSONB NOT NULL DEFAULT '[]',
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, date)
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cost_summary_daily_tenant_date "
        "ON cost_summary_daily (tenant_id, date DESC)"
    )

    # RLS: platform admin only.
    # Application connections must set app.current_scope = 'platform' to access.
    # Superuser / migration connections bypass RLS — safe.
    op.execute("ALTER TABLE cost_summary_daily ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cost_summary_daily FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY cost_summary_daily_platform_only ON cost_summary_daily
            USING (
                current_setting('app.current_scope', true) = 'platform'
            )
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS cost_summary_daily_platform_only "
        "ON cost_summary_daily"
    )
    op.execute("DROP INDEX IF EXISTS idx_cost_summary_daily_tenant_date")
    op.execute("DROP TABLE IF EXISTS cost_summary_daily")
