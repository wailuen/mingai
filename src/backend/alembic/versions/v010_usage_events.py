"""
010 Usage Events Table.

Creates the usage_events table for per-request LLM cost tracking.
Each LLM call (completion or embedding) writes one row with token counts,
model source, cost_usd (nullable if pricing unavailable), and latency.

Schema:
  usage_events(id, tenant_id, user_id, conversation_id, provider, model,
               tokens_in, tokens_out, model_source, cost_usd, latency_ms,
               created_at)

RLS policies:
  - platform_admin: sees all rows
  - tenant: sees only own rows (tenant_id = app.tenant_id)

Indexes:
  - idx_usage_events_tenant_date: (tenant_id, created_at DESC) — cost dashboards
  - idx_usage_events_tenant_model_date: (tenant_id, model, created_at) — per-model breakdown

Revision ID: 010
Revises: 009
Create Date: 2026-03-16
"""
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_events (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID NOT NULL REFERENCES tenants(id),
            user_id          UUID,
            conversation_id  UUID,
            provider         VARCHAR(50) NOT NULL,
            model            VARCHAR(200) NOT NULL,
            tokens_in        INTEGER NOT NULL DEFAULT 0,
            tokens_out       INTEGER NOT NULL DEFAULT 0,
            model_source     VARCHAR(50) NOT NULL,
            cost_usd         NUMERIC(10,8),
            latency_ms       INTEGER,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT usage_events_model_source_check
                CHECK (model_source IN ('library', 'byollm'))
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_events_tenant_date "
        "ON usage_events (tenant_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_events_tenant_model_date "
        "ON usage_events (tenant_id, model, created_at)"
    )

    # Enable RLS
    op.execute("ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE usage_events FORCE ROW LEVEL SECURITY")

    # Platform admin sees all rows
    op.execute(
        """
        CREATE POLICY usage_events_platform_admin ON usage_events
            USING (current_setting('app.user_role', true) = 'platform_admin')
        """
    )

    # Tenant sees only own rows
    op.execute(
        """
        CREATE POLICY usage_events_tenant ON usage_events
            USING (
                tenant_id = current_setting('app.tenant_id', true)::uuid
            )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS usage_events_tenant ON usage_events")
    op.execute("DROP POLICY IF EXISTS usage_events_platform_admin ON usage_events")
    op.execute("DROP INDEX IF EXISTS idx_usage_events_tenant_model_date")
    op.execute("DROP INDEX IF EXISTS idx_usage_events_tenant_date")
    op.execute("DROP TABLE IF EXISTS usage_events")
