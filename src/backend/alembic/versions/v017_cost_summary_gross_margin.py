"""
017 Cost Summary Gross Margin Columns (PA-013).

Adds three nullable columns to cost_summary_daily for gross margin tracking:
  - plan_revenue_usd:       Daily plan revenue attributed to this tenant
  - infra_cost_estimate_usd: Estimated daily infrastructure cost for this tenant
  - gross_margin_pct:       (plan_revenue - llm_cost - infra_cost) / plan_revenue * 100

All columns are nullable — existing rows from PA-012 that pre-date this
migration remain valid; gross margin will be populated on the next nightly run.

Revision ID: 017
Revises: 016
Create Date: 2026-03-16
"""
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE cost_summary_daily
            ADD COLUMN IF NOT EXISTS plan_revenue_usd       NUMERIC(10, 2),
            ADD COLUMN IF NOT EXISTS infra_cost_estimate_usd NUMERIC(10, 2),
            ADD COLUMN IF NOT EXISTS gross_margin_pct        NUMERIC(5, 2)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE cost_summary_daily
            DROP COLUMN IF EXISTS gross_margin_pct,
            DROP COLUMN IF EXISTS infra_cost_estimate_usd,
            DROP COLUMN IF EXISTS plan_revenue_usd
        """
    )
