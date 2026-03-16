"""
014 Tenant Health Scores Table (PA-006).

Creates the tenant_health_scores table for storing nightly computed health
score snapshots per tenant.

Schema:
  tenant_health_scores(id, tenant_id, date, usage_trend_score,
    feature_breadth_score, satisfaction_score, error_rate_score,
    composite_score, at_risk_flag, at_risk_reason, created_at)

RLS: platform admin only (app.tenant_id setting not applicable for
     platform-scoped tables — policy restricts to platform scope via
     a permissive deny-all / allow-platform pattern using current_setting).

Revision ID: 014
Revises: 013
Create Date: 2026-03-16
"""
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_health_scores (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID NOT NULL REFERENCES tenants(id),
            date                 DATE NOT NULL,
            usage_trend_score    NUMERIC(5,2),
            feature_breadth_score NUMERIC(5,2),
            satisfaction_score   NUMERIC(5,2),
            error_rate_score     NUMERIC(5,2),
            composite_score      NUMERIC(5,2),
            at_risk_flag         BOOLEAN NOT NULL DEFAULT FALSE,
            at_risk_reason       TEXT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(tenant_id, date)
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tenant_health_scores_tenant_date "
        "ON tenant_health_scores(tenant_id, date DESC)"
    )

    # RLS: platform admin only.
    # Platform admin requests set app.current_scope = 'platform' via
    # TenantContextMiddleware / require_platform_admin.
    # All other callers are denied access entirely.
    op.execute("ALTER TABLE tenant_health_scores ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_health_scores FORCE ROW LEVEL SECURITY")

    # Superuser / migration connections bypass RLS — safe.
    # Application connections must satisfy this policy.
    op.execute(
        """
        CREATE POLICY tenant_health_scores_platform_only ON tenant_health_scores
            USING (
                current_setting('app.current_scope', true) = 'platform'
            )
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_health_scores_platform_only "
        "ON tenant_health_scores"
    )
    op.execute("DROP INDEX IF EXISTS idx_tenant_health_scores_tenant_date")
    op.execute("DROP TABLE IF EXISTS tenant_health_scores")
