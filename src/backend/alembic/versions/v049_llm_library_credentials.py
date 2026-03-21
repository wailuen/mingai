"""v049 — Add credential columns to llm_library

Revision ID: 049
Revises: 048
Create Date: 2026-03-21

Adds endpoint_url, api_key_encrypted (BYTEA), api_key_last4, api_version,
and last_test_passed_at to the llm_library table.

All new columns are nullable — existing rows are unaffected.
Uses IF NOT EXISTS / IF EXISTS guards to make the migration re-runnable in dev.

No RLS policy changes needed — existing llm_library_platform_admin and
llm_library_tenant_read policies remain correct; the new columns follow
the same access pattern as existing columns.
"""
from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE llm_library ADD COLUMN IF NOT EXISTS endpoint_url VARCHAR(500)")
    op.execute("ALTER TABLE llm_library ADD COLUMN IF NOT EXISTS api_key_encrypted BYTEA")
    op.execute("ALTER TABLE llm_library ADD COLUMN IF NOT EXISTS api_key_last4 VARCHAR(4)")
    op.execute("ALTER TABLE llm_library ADD COLUMN IF NOT EXISTS api_version VARCHAR(50)")
    op.execute("ALTER TABLE llm_library ADD COLUMN IF NOT EXISTS last_test_passed_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE llm_library DROP COLUMN IF EXISTS last_test_passed_at")
    op.execute("ALTER TABLE llm_library DROP COLUMN IF EXISTS api_version")
    op.execute("ALTER TABLE llm_library DROP COLUMN IF EXISTS api_key_last4")
    op.execute("ALTER TABLE llm_library DROP COLUMN IF EXISTS api_key_encrypted")
    op.execute("ALTER TABLE llm_library DROP COLUMN IF EXISTS endpoint_url")
