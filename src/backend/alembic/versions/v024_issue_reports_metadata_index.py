"""
024 GIN index on issue_reports.metadata for platform alert queries (PA-027).

The underperforming template alert batch (check_underperforming_alerts) queries
issue_reports by metadata->>'template_id' to detect existing open alerts:

  SELECT id FROM issue_reports
  WHERE issue_type = 'template_performance'
    AND status NOT IN ('resolved', 'closed')
    AND metadata->>'template_id' = :template_id

Without an index, this is a full table scan. A functional B-tree index on the
extracted text value avoids sequential scans as the issue_reports table grows.

A partial GIN index on metadata would also work but a functional B-tree on the
specific extracted key is smaller and faster for equality lookups.

Revision ID: 024
Revises: 023
Create Date: 2026-03-16
"""
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Functional B-tree index on the extracted template_id from metadata jsonb.
    # Supports equality lookups used in _OPEN_ALERT_QUERY.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_issue_reports_metadata_template_id "
        "ON issue_reports ((metadata->>'template_id')) "
        "WHERE metadata->>'template_id' IS NOT NULL"
    )
    # Composite index to support the full _OPEN_ALERT_QUERY filter efficiently:
    # issue_type = 'template_performance' AND status NOT IN (...) AND template_id = X
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_issue_reports_template_perf_open "
        "ON issue_reports (issue_type, status, (metadata->>'template_id')) "
        "WHERE issue_type = 'template_performance'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_issue_reports_template_perf_open")
    op.execute("DROP INDEX IF EXISTS idx_issue_reports_metadata_template_id")
