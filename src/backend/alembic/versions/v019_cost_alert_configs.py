"""
019 Cost Alert Configurations Table (PA-015).

Creates the cost_alert_configs table for storing per-tenant (or global default)
spend/margin alert thresholds used by the nightly cost alert evaluation job.

Schema:
  cost_alert_configs(id, tenant_id, daily_spend_threshold_usd,
    margin_floor_pct, created_at, updated_at)

  tenant_id = NULL  → global default config (one row, enforced by UNIQUE)
  tenant_id = UUID  → per-tenant override (one row per tenant)

RLS: platform admin only (app.current_scope = 'platform') — same pattern
     as v014 tenant_health_scores and v016 cost_summary_daily.

Revision ID: 019
Revises: 018
Create Date: 2026-03-16
"""
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cost_alert_configs (
            id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                   UUID REFERENCES tenants(id) ON DELETE CASCADE,
            daily_spend_threshold_usd   NUMERIC(10, 2),
            margin_floor_pct            NUMERIC(5, 2),
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id)
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cost_alert_configs_tenant "
        "ON cost_alert_configs (tenant_id)"
    )

    # RLS: platform admin only.
    # Application connections must set app.current_scope = 'platform' to access.
    # Superuser / migration connections bypass RLS — safe.
    op.execute("ALTER TABLE cost_alert_configs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cost_alert_configs FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY cost_alert_configs_platform_only ON cost_alert_configs
            USING (
                current_setting('app.current_scope', true) = 'platform'
            )
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS cost_alert_configs_platform_only "
        "ON cost_alert_configs"
    )
    op.execute("DROP INDEX IF EXISTS idx_cost_alert_configs_tenant")
    op.execute("DROP TABLE IF EXISTS cost_alert_configs")
