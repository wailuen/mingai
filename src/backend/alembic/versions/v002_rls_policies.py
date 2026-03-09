"""
002 RLS Policies - Enable Row-Level Security on all 22 tables.

INFRA-004: Every table gets:
- ENABLE ROW LEVEL SECURITY
- FORCE ROW LEVEL SECURITY
- tenant_isolation policy (USING + WITH CHECK)
- platform_admin_bypass policy

Revision ID: 002
Revises: 001
Create Date: 2026-03-07
"""
from alembic import op
from app.core.database import (
    get_rls_policy_sql,
    get_platform_bypass_policy_sql,
)

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

# Snapshot of the 22 tables that existed at v001.
# IMPORTANT: Do NOT import TENANT_SCOPED_TABLES here — that list grows with
# later migrations (e.g. har_transactions added in v003) and would cause
# downgrade() to reference tables that don't exist when rolling back to v001.
_V001_TABLES = [
    "users",
    "conversations",
    "messages",
    "user_feedback",
    "user_profiles",
    "memory_notes",
    "profile_learning_events",
    "working_memory_snapshots",
    "tenant_configs",
    "llm_profiles",
    "tenant_teams",
    "team_memberships",
    "team_membership_audit",
    "glossary_terms",
    "glossary_miss_signals",
    "integrations",
    "sync_jobs",
    "issue_reports",
    "issue_report_events",
    "agent_cards",
    "audit_log",
]

# All tables that get RLS policies in this migration
RLS_TABLES = _V001_TABLES + ["tenants"]


def upgrade() -> None:
    """Enable RLS on all tables with tenant isolation and platform bypass."""
    for table_name in RLS_TABLES:
        # Enable RLS + create tenant isolation policy
        rls_sql = get_rls_policy_sql(table_name)
        for statement in rls_sql.split(";"):
            stmt = statement.strip()
            if stmt:
                op.execute(stmt + ";")

        # Create platform admin bypass policy
        bypass_sql = get_platform_bypass_policy_sql(table_name)
        op.execute(bypass_sql)


def downgrade() -> None:
    """Remove RLS policies and disable RLS on all tables."""
    for table_name in reversed(RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS platform_admin_bypass ON {table_name};")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table_name};")
        op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY;")
