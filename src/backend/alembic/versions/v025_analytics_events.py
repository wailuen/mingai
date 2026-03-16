"""
025 analytics_events table for PA-029 feature adoption tracking.

Adds a tenant-scoped analytics_events table. Each row records that a tenant
session used a specific product feature. Used by the platform feature-adoption
API to compute per-feature adoption rate, sessions/week, and trends.

Table:
  analytics_events(
    id           UUID PK,
    tenant_id    UUID NOT NULL REFERENCES tenants(id),
    user_id      UUID REFERENCES users(id),
    feature_name VARCHAR(100) NOT NULL,  -- e.g. 'chat', 'glossary', 'agent_templates'
    event_type   VARCHAR(50) NOT NULL,   -- e.g. 'session_start', 'action'
    metadata     JSONB DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT NOW()
  )

RLS: Standard tenant isolation (tenant sessions read/write own rows).
     Platform bypass FOR SELECT so the feature-adoption API can aggregate
     across all tenants with app.scope = 'platform'.

Revision ID: 025
Revises: 024
Create Date: 2026-03-16
"""
from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics_events (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
            feature_name VARCHAR(100) NOT NULL
                CHECK (char_length(feature_name) BETWEEN 1 AND 100),
            event_type   VARCHAR(50) NOT NULL DEFAULT 'session',
            metadata     JSONB NOT NULL DEFAULT '{}',
            created_at   TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_analytics_events_tenant_feature "
        "ON analytics_events (tenant_id, feature_name, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_analytics_events_feature_date "
        "ON analytics_events (feature_name, created_at DESC)"
    )
    op.execute("ALTER TABLE analytics_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE analytics_events FORCE ROW LEVEL SECURITY")
    # Tenant sessions read/write their own events.
    op.execute(
        """
        CREATE POLICY analytics_events_tenant_select ON analytics_events
        FOR SELECT
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        """
    )
    op.execute(
        """
        CREATE POLICY analytics_events_tenant_insert ON analytics_events
        FOR INSERT
        WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
        """
    )
    # Platform bypass for cross-tenant adoption aggregation.
    op.execute(
        """
        CREATE POLICY analytics_events_platform ON analytics_events
        FOR SELECT
        USING (current_setting('app.scope', true) = 'platform')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS analytics_events_platform ON analytics_events")
    op.execute(
        "DROP POLICY IF EXISTS analytics_events_tenant_insert ON analytics_events"
    )
    op.execute(
        "DROP POLICY IF EXISTS analytics_events_tenant_select ON analytics_events"
    )
    op.execute("DROP TABLE IF EXISTS analytics_events")
