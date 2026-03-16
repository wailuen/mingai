"""
012 Add version_tag to semantic_cache (CACHE-008).

Adds a version_tag INTEGER column to semantic_cache so that cache entries
can be invalidated by index version bump without a DELETE scan.

On document update, increment_index_version() increments the Redis counter
and semantic_cache entries written with an old version are skipped on lookup.

Revision ID: 012
Revises: 011
Create Date: 2026-03-16
"""
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE semantic_cache
            ADD COLUMN IF NOT EXISTS version_tag INTEGER NOT NULL DEFAULT 0
        """
    )

    # Index to support version-filtered queries
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_semantic_cache_version "
        "ON semantic_cache (tenant_id, version_tag)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_semantic_cache_version")
    op.execute("ALTER TABLE semantic_cache DROP COLUMN IF EXISTS version_tag")
