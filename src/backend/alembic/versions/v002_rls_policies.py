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
    TENANT_SCOPED_TABLES,
    get_rls_policy_sql,
    get_platform_bypass_policy_sql,
)

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

# All tables that get RLS policies
RLS_TABLES = TENANT_SCOPED_TABLES + ["tenants"]


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
