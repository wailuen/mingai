"""040 search_index_registry — logical index lifecycle tracking for pgvector.

Stores per-tenant, per-source index metadata: doc/chunk counts, embedding model,
version counter (for cache invalidation), and last indexed timestamp.

Revision ID: 040
Revises: 039
Create Date: 2026-03-18
"""
from alembic import op
from app.core.database import get_rls_policy_sql, get_platform_bypass_policy_sql

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE search_index_registry (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            index_id        TEXT NOT NULL,
            source_type     TEXT NOT NULL,
            display_name    TEXT,
            embedding_model TEXT NOT NULL DEFAULT 'text-embedding-3-small',
            dimensions      INTEGER NOT NULL DEFAULT 1536,
            doc_count       INTEGER NOT NULL DEFAULT 0,
            chunk_count     INTEGER NOT NULL DEFAULT 0,
            storage_bytes   BIGINT NOT NULL DEFAULT 0,
            version         INTEGER NOT NULL DEFAULT 1,
            last_indexed_at TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(tenant_id, index_id)
        )
    """
    )
    op.execute("CREATE INDEX idx_sir_tenant ON search_index_registry(tenant_id)")
    op.execute("CREATE INDEX idx_sir_index_id ON search_index_registry(index_id)")

    # RLS: use standard helpers — consistent with all other tenant-scoped tables
    for stmt in get_rls_policy_sql("search_index_registry").split(";"):
        stmt = stmt.strip()
        if stmt:
            op.execute(stmt + ";")
    op.execute(get_platform_bypass_policy_sql("search_index_registry"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS search_index_registry CASCADE")
