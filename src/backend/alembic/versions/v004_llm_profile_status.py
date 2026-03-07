"""
004 Add status column to llm_profiles (API-035).

Supports soft-delete / deprecation lifecycle for LLM profiles.
Status values: 'active' (default) | 'deprecated'

Revision ID: 004
Revises: 003
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE llm_profiles "
        "ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'active' "
        "CHECK (status IN ('active', 'deprecated'))"
    )


def downgrade():
    op.execute("ALTER TABLE llm_profiles DROP COLUMN IF EXISTS status")
