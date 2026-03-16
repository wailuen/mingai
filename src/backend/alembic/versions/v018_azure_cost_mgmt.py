"""
018 Azure Cost Management columns (PA-014).

Adds two columns to cost_summary_daily to track whether the infra cost
estimate came from the live Azure Cost Management API or from the static
INFRA_COST_PER_TENANT_DAILY_USD env constant:

  - infra_is_estimated  BOOLEAN NOT NULL DEFAULT TRUE
        TRUE  → cost came from env constant (no real API data yet)
        FALSE → cost pulled from Azure Cost Management API

  - infra_last_updated_at  TIMESTAMPTZ
        Timestamp of the last successful Azure API pull.  NULL until the
        azure_cost_job has run successfully at least once for this row.

All existing rows keep infra_is_estimated = TRUE (correct default — they were
populated using the env constant before the Azure job existed).

Revision ID: 018
Revises: 017
Create Date: 2026-03-16
"""
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE cost_summary_daily
            ADD COLUMN IF NOT EXISTS infra_is_estimated     BOOLEAN NOT NULL DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS infra_last_updated_at  TIMESTAMPTZ
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE cost_summary_daily
            DROP COLUMN IF EXISTS infra_last_updated_at,
            DROP COLUMN IF EXISTS infra_is_estimated
        """
    )
