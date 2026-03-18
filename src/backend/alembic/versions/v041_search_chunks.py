"""041 search_chunks — unified pgvector content store for all source types.

Replaces Azure AI Search as the vector+FTS search backend.
Single table holds conversation docs, SharePoint KB, and Google Drive KB.
Uses halfvec(1536) for text-embedding-3-small compatibility with HNSW indexing.
Full-text search via tsvector GENERATED column using 'simple' config (non-Latin safe).

Architecture:
  - Per-tenant partial HNSW indexes created at provisioning time (not in migration)
  - Global HNSW index serves queries during provisioning window
  - GIN index on fts_doc enables hybrid RRF search
  - RLS provides tenant isolation (consistent with all other tables)

Revision ID: 041
Revises: 040
Create Date: 2026-03-18
"""
from alembic import op
from app.core.database import get_rls_policy_sql, get_platform_bypass_policy_sql

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Main table
    op.execute(
        """
        CREATE TABLE search_chunks (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            chunk_key            TEXT NOT NULL,
            tenant_id            UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            index_id             TEXT NOT NULL,
            source_type          TEXT NOT NULL,
            user_id              UUID REFERENCES users(id) ON DELETE SET NULL,
            conversation_id      UUID,
            integration_id       UUID,
            content              TEXT NOT NULL,
            title                TEXT,
            source_url           TEXT,
            file_name            TEXT,
            file_type            TEXT,
            chunk_type           TEXT NOT NULL DEFAULT 'text',
            chunk_index          INTEGER NOT NULL DEFAULT 0,
            page_number          INTEGER,
            slide_number         INTEGER,
            slide_title          TEXT,
            sheet_name           TEXT,
            row_range            TEXT,
            section_heading      TEXT,
            image_type           TEXT,
            is_image_description BOOLEAN DEFAULT FALSE,
            source_file_id       TEXT,
            content_hash         TEXT,
            etag                 TEXT,
            source_modified_at   TIMESTAMPTZ,
            file_size_bytes      BIGINT,
            embedding            halfvec(1536),
            fts_doc              tsvector GENERATED ALWAYS AS (
                                     setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
                                     setweight(to_tsvector('simple', coalesce(content, '')), 'D')
                                 ) STORED,
            indexed_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(tenant_id, index_id, chunk_key)
        )
    """
    )

    # 2. updated_at trigger (PostgreSQL doesn't auto-update DEFAULT columns on UPDATE)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION search_chunks_set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """
    )
    op.execute(
        """
        CREATE TRIGGER search_chunks_updated_at
        BEFORE UPDATE ON search_chunks
        FOR EACH ROW EXECUTE FUNCTION search_chunks_set_updated_at()
    """
    )

    # 3. RLS — consistent with all other tenant-scoped tables
    for stmt in get_rls_policy_sql("search_chunks").split(";"):
        stmt = stmt.strip()
        if stmt:
            op.execute(stmt + ";")
    op.execute(get_platform_bypass_policy_sql("search_chunks"))

    # 4. Non-vector indexes (transactional — fine inside Alembic's transaction)
    op.execute("CREATE INDEX idx_sc_fts ON search_chunks USING GIN(fts_doc)")
    op.execute(
        "CREATE INDEX idx_sc_conversation ON search_chunks(tenant_id, conversation_id, user_id) "
        "WHERE source_type = 'conversation'"
    )
    op.execute(
        "CREATE INDEX idx_sc_integration ON search_chunks(tenant_id, integration_id) "
        "WHERE integration_id IS NOT NULL"
    )
    op.execute("CREATE INDEX idx_sc_index_id ON search_chunks(tenant_id, index_id)")
    op.execute(
        "CREATE INDEX idx_sc_content_hash ON search_chunks(tenant_id, content_hash) "
        "WHERE content_hash IS NOT NULL"
    )

    # 5. Global HNSW vector index
    #    Table is empty at migration time — plain CREATE INDEX (not CONCURRENTLY)
    #    is safe here: no live readers, no blocking risk. Avoids the need to exit
    #    Alembic's transaction, which can cause the alembic_version stamp to be lost
    #    on some asyncpg + Alembic version combinations.
    op.execute(
        "CREATE INDEX idx_sc_embedding_global "
        "ON search_chunks USING hnsw(embedding halfvec_cosine_ops) "
        "WITH (m = 16, ef_construction = 128)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sc_embedding_global")
    op.execute("DROP TRIGGER IF EXISTS search_chunks_updated_at ON search_chunks")
    op.execute("DROP FUNCTION IF EXISTS search_chunks_set_updated_at")
    op.execute("DROP TABLE IF EXISTS search_chunks CASCADE")
