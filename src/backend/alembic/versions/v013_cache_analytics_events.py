"""
013 Cache analytics events table (CACHE-015).

Creates cache_analytics_events for tracking cache hit/miss events across
all cache tiers (semantic, search, intent, embedding).

Schema:
  cache_analytics_events(
    id UUID PK,
    tenant_id UUID NOT NULL,
    cache_type TEXT NOT NULL,   -- 'semantic' | 'search' | 'intent' | 'embedding'
    event_type TEXT NOT NULL,   -- 'hit' | 'miss'
    index_name TEXT,            -- for search tier (optional)
    query_hash TEXT,            -- SHA256 prefix of normalized query (no raw text)
    cost_saved_usd FLOAT,       -- estimated cost saving on hit (NULL on miss)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  )

Indexes:
  - (tenant_id, created_at) — primary analytics filter
  - (tenant_id, cache_type) — per-type breakdown
  - (tenant_id, query_hash) — top-cached-queries

RLS: tenants see only their own rows.

Revision ID: 013
Revises: 012
Create Date: 2026-03-16
"""
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cache_analytics_events (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL,
            cache_type  TEXT        NOT NULL,
            event_type  TEXT        NOT NULL
                CONSTRAINT cache_event_type_check CHECK (event_type IN ('hit', 'miss')),
            index_name  TEXT,
            query_hash  TEXT,
            cost_saved_usd FLOAT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cache_analytics_tenant_time "
        "ON cache_analytics_events (tenant_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cache_analytics_type "
        "ON cache_analytics_events (tenant_id, cache_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cache_analytics_query_hash "
        "ON cache_analytics_events (tenant_id, query_hash) "
        "WHERE query_hash IS NOT NULL"
    )

    # Enable RLS
    op.execute("ALTER TABLE cache_analytics_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cache_analytics_events FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY cache_analytics_tenant ON cache_analytics_events
            USING (
                tenant_id = current_setting('app.tenant_id', true)::uuid
            )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS cache_analytics_tenant ON cache_analytics_events")
    op.execute("DROP INDEX IF EXISTS idx_cache_analytics_query_hash")
    op.execute("DROP INDEX IF EXISTS idx_cache_analytics_type")
    op.execute("DROP INDEX IF EXISTS idx_cache_analytics_tenant_time")
    op.execute("DROP TABLE IF EXISTS cache_analytics_events")
