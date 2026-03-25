"""v061 — add tool_health_checks table for per-check health history

Revision ID: v061
Revises: 060
Create Date: 2026-03-23

Adds tool_health_checks to persist one row per health-check ping so the
GET /platform/tool-catalog/{id}/health endpoint can return time-series data
instead of only the current health_status column on tool_catalog.

Retention: 30 days (enforced by cleanup query inside run_tool_health_job).
"""
from alembic import op
import sqlalchemy as sa

revision = 'v061'
down_revision = '060'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE tool_health_checks (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tool_id     UUID NOT NULL REFERENCES tool_catalog(id) ON DELETE CASCADE,
            checked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            status      VARCHAR(20) NOT NULL CHECK (status IN ('healthy', 'degraded', 'unavailable')),
            latency_ms  INTEGER,
            error_msg   TEXT
        )
    """)
    op.execute("""
        CREATE INDEX idx_tool_health_checks_tool_id_checked_at
        ON tool_health_checks (tool_id, checked_at DESC)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_tool_health_checks_tool_id_checked_at")
    op.execute("DROP TABLE IF EXISTS tool_health_checks")
