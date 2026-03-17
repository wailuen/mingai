"""
032 issue_embeddings table for semantic issue search (DEF-001).

Stores 1536-dim embeddings for issue reports using Azure OpenAI
text-embedding-3-small. Enables semantic similarity search across issues.

Table:
  issue_embeddings(
    id          UUID PK,
    issue_id    UUID FK issue_reports(id) ON DELETE CASCADE,
    tenant_id   UUID FK tenants(id),
    embedding   VECTOR(1536),
    created_at  TIMESTAMPTZ DEFAULT NOW()
  )

HNSW index: vector_cosine_ops, m=16, ef_construction=64
RLS: tenant_isolation + platform_admin_bypass (defined in this migration)
Depends_on: v011_semantic_cache (pgvector extension already enabled there)

Revision ID: 032
Revises: 030
Create Date: 2026-03-17
"""
from alembic import op

revision = "032"
down_revision = "030"
branch_labels = None
depends_on = "011"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS issue_embeddings (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            issue_id    UUID NOT NULL REFERENCES issue_reports(id) ON DELETE CASCADE,
            tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            embedding   VECTOR(1536) NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_issue_embeddings_issue "
        "ON issue_embeddings (issue_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_issue_embeddings_tenant "
        "ON issue_embeddings (tenant_id)"
    )
    # HNSW index for approximate nearest-neighbour cosine search
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_issue_embeddings_hnsw "
        "ON issue_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m=16, ef_construction=64)"
    )
    op.execute("ALTER TABLE issue_embeddings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE issue_embeddings FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY issue_embeddings_tenant ON issue_embeddings
        FOR ALL
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
        """
    )
    op.execute(
        """
        CREATE POLICY issue_embeddings_platform ON issue_embeddings
        FOR ALL
        USING (current_setting('app.scope', true) = 'platform')
        WITH CHECK (current_setting('app.scope', true) = 'platform')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS issue_embeddings_platform ON issue_embeddings")
    op.execute("DROP POLICY IF EXISTS issue_embeddings_tenant ON issue_embeddings")
    op.execute("DROP TABLE IF EXISTS issue_embeddings")
    # pgvector extension is NOT dropped — it is shared with semantic_cache
