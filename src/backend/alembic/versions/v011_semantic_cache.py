"""
011 Semantic Cache Table (CACHE-007).

Creates the semantic_cache table for pgvector-based semantic similarity
caching of LLM responses. Enables near-duplicate query deduplication.

Prerequisites: PostgreSQL with the pgvector extension available.
This migration creates the extension if not already present.

Schema:
  semantic_cache(id, tenant_id, query_embedding VECTOR(1536), query_text,
                 response_text, agent_id, similarity_threshold, hit_count,
                 created_at, expires_at)

Indexes:
  - idx_semantic_cache_tenant: (tenant_id) — filter before ANN search
  - idx_semantic_cache_embedding: HNSW index on query_embedding
    using cosine distance (vector_cosine_ops)
    m=16, ef_construction=64

RLS:
  - tenant sees only own rows (tenant_id = app.tenant_id)

Revision ID: 011
Revises: 010
Create Date: 2026-03-16
"""
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure pgvector extension exists
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS semantic_cache (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID NOT NULL,
            query_embedding      VECTOR(1536) NOT NULL,
            query_text           TEXT NOT NULL,
            response_text        TEXT NOT NULL,
            agent_id             VARCHAR(200),
            similarity_threshold FLOAT NOT NULL DEFAULT 0.92,
            hit_count            INTEGER NOT NULL DEFAULT 0,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at           TIMESTAMPTZ NOT NULL,
            CONSTRAINT semantic_cache_threshold_check
                CHECK (similarity_threshold BETWEEN 0.5 AND 1.0)
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_semantic_cache_tenant "
        "ON semantic_cache (tenant_id)"
    )

    # HNSW index for approximate nearest neighbour search using cosine distance.
    # m=16 (max connections per node), ef_construction=64 (build-time beam width).
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_semantic_cache_embedding
            ON semantic_cache
            USING hnsw (query_embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """
    )

    # Enable RLS
    op.execute("ALTER TABLE semantic_cache ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE semantic_cache FORCE ROW LEVEL SECURITY")

    # Tenant sees only own rows
    op.execute(
        """
        CREATE POLICY semantic_cache_tenant ON semantic_cache
            USING (
                tenant_id = current_setting('app.tenant_id', true)::uuid
            )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS semantic_cache_tenant ON semantic_cache")
    op.execute("DROP INDEX IF EXISTS idx_semantic_cache_embedding")
    op.execute("DROP INDEX IF EXISTS idx_semantic_cache_tenant")
    op.execute("DROP TABLE IF EXISTS semantic_cache")
    # Note: we do NOT drop the vector extension — other tables may use it
