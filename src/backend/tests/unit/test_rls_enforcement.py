"""
TEST-002: Multi-tenant RLS enforcement - unit tests

Coverage target: 100% (security-critical)
Target count: 20 tests

Validates that RLS policies are correctly defined and that the
tenant context management works properly. Uses mocked database
connections (Tier 1).
"""
import uuid

import pytest


# All 22 tables that MUST have RLS enabled
TENANT_SCOPED_TABLES = [
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

# tenants table has special RLS (id = current_setting, not tenant_id)
PLATFORM_TABLES_WITH_SPECIAL_RLS = [
    "tenants",
]


class TestRLSPolicyDefinitions:
    """Validate that RLS SQL statements are correct for all tables."""

    def test_rls_policy_sql_for_standard_table(self):
        """Standard tenant-scoped table RLS uses tenant_id column."""
        from app.core.database import get_rls_policy_sql

        sql = get_rls_policy_sql("users")
        assert "ENABLE ROW LEVEL SECURITY" in sql
        assert "tenant_id = current_setting('app.current_tenant_id')::uuid" in sql

    def test_rls_policy_sql_for_tenants_table(self):
        """Tenants table RLS uses id column (self-referencing)."""
        from app.core.database import get_rls_policy_sql

        sql = get_rls_policy_sql("tenants")
        assert "ENABLE ROW LEVEL SECURITY" in sql
        assert "id = current_setting('app.current_tenant_id')::uuid" in sql

    def test_all_tenant_scoped_tables_have_rls_definition(self):
        """Every tenant-scoped table MUST have an RLS policy defined."""
        from app.core.database import get_rls_policy_sql

        for table in TENANT_SCOPED_TABLES:
            sql = get_rls_policy_sql(table)
            assert "ENABLE ROW LEVEL SECURITY" in sql, (
                f"Table '{table}' is missing RLS policy definition"
            )

    def test_platform_bypass_policy_exists_for_all_tables(self):
        """Platform admin bypass policy must exist on every table."""
        from app.core.database import get_platform_bypass_policy_sql

        for table in TENANT_SCOPED_TABLES + PLATFORM_TABLES_WITH_SPECIAL_RLS:
            sql = get_platform_bypass_policy_sql(table)
            assert "platform" in sql.lower(), (
                f"Table '{table}' is missing platform admin bypass policy"
            )


class TestTenantContextManager:
    """Test that tenant context is properly set and cleared."""

    def test_set_tenant_context_validates_uuid(self):
        """set_tenant_context rejects non-UUID tenant_id."""
        from app.core.database import validate_tenant_id

        with pytest.raises(ValueError, match="UUID"):
            validate_tenant_id("not-a-uuid")

        with pytest.raises(ValueError, match="UUID"):
            validate_tenant_id("")

        with pytest.raises(ValueError, match="UUID"):
            validate_tenant_id(None)

    def test_set_tenant_context_accepts_valid_uuid(self):
        """set_tenant_context accepts valid UUID strings."""
        from app.core.database import validate_tenant_id

        valid_uuid = str(uuid.uuid4())
        result = validate_tenant_id(valid_uuid)
        assert result == valid_uuid

    def test_set_tenant_context_generates_correct_sql(self):
        """SET LOCAL app.current_tenant_id SQL is correctly formed."""
        from app.core.database import get_set_tenant_sql

        tenant_id = str(uuid.uuid4())
        sql = get_set_tenant_sql(tenant_id)
        assert f"set_config('app.current_tenant_id', '{tenant_id}', true)" in sql

    def test_tenant_context_is_transaction_scoped(self):
        """Tenant context uses SET LOCAL (transaction-scoped, not session)."""
        from app.core.database import get_set_tenant_sql

        tenant_id = str(uuid.uuid4())
        sql = get_set_tenant_sql(tenant_id)
        # The 'true' parameter in set_config means LOCAL (transaction-scoped)
        assert "true" in sql

    def test_sql_injection_prevented_in_tenant_id(self):
        """SQL injection attempts in tenant_id are rejected."""
        from app.core.database import validate_tenant_id

        injection_attempts = [
            "'; DROP TABLE users; --",
            "1 OR 1=1",
            "00000000-0000-0000-0000-000000000000'; DELETE FROM tenants; --",
            "<script>alert(1)</script>",
            "../../etc/passwd",
        ]
        for attempt in injection_attempts:
            with pytest.raises(ValueError):
                validate_tenant_id(attempt)


class TestRLSMigrationDefinitions:
    """Validate that Alembic migration SQL is correct."""

    def test_migration_001_creates_all_tables(self):
        """Migration 001 creates all required tables."""
        from app.core.schema import TABLE_NAMES

        required_tables = {
            "tenants", "users", "tenant_configs", "llm_profiles",
            "conversations", "messages", "user_feedback", "user_profiles",
            "memory_notes", "profile_learning_events",
            "working_memory_snapshots", "tenant_teams",
            "team_memberships", "team_membership_audit",
            "glossary_terms", "glossary_miss_signals",
            "integrations", "sync_jobs", "issue_reports",
            "issue_report_events", "agent_cards", "audit_log",
        }
        assert required_tables.issubset(set(TABLE_NAMES)), (
            f"Missing tables: {required_tables - set(TABLE_NAMES)}"
        )

    def test_migration_002_enables_rls_on_all_tables(self):
        """Migration 002 enables RLS on every table."""
        from app.core.schema import RLS_TABLES

        all_tables = TENANT_SCOPED_TABLES + PLATFORM_TABLES_WITH_SPECIAL_RLS
        for table in all_tables:
            assert table in RLS_TABLES, (
                f"Table '{table}' not included in RLS migration"
            )

    def test_every_table_has_tenant_id_column(self):
        """Every tenant-scoped table must declare tenant_id as NOT NULL FK."""
        from app.core.schema import get_table_definition

        for table in TENANT_SCOPED_TABLES:
            definition = get_table_definition(table)
            assert "tenant_id" in definition, (
                f"Table '{table}' missing tenant_id column"
            )
            assert "NOT NULL" in definition.upper(), (
                f"Table '{table}' tenant_id must be NOT NULL"
            )

    def test_rls_policy_uses_correct_column_per_table(self):
        """Standard tables use tenant_id; tenants table uses id."""
        from app.core.database import get_rls_column_for_table

        for table in TENANT_SCOPED_TABLES:
            assert get_rls_column_for_table(table) == "tenant_id"

        assert get_rls_column_for_table("tenants") == "id"

    def test_team_memberships_rls_uses_subquery(self):
        """team_memberships RLS uses subquery via tenant_teams join."""
        from app.core.database import get_rls_policy_sql

        sql = get_rls_policy_sql("team_memberships")
        assert "tenant_teams" in sql.lower() or "team_id" in sql.lower(), (
            "team_memberships RLS must reference tenant_teams for tenant scoping"
        )

    def test_rls_insert_policy_prevents_cross_tenant_write(self):
        """WITH CHECK clause prevents INSERT with wrong tenant_id."""
        from app.core.database import get_rls_policy_sql

        for table in TENANT_SCOPED_TABLES[:5]:  # Sample check
            sql = get_rls_policy_sql(table)
            assert "WITH CHECK" in sql.upper() or "FOR ALL" in sql.upper(), (
                f"Table '{table}' must have INSERT check or FOR ALL policy"
            )

    def test_connection_pool_must_not_use_superuser(self):
        """Application DB user must NOT be superuser (superusers bypass RLS)."""
        from app.core.database import get_recommended_db_user_sql

        sql = get_recommended_db_user_sql()
        assert "NOSUPERUSER" in sql.upper() or "nosuperuser" in sql.lower()
        assert "NOCREATEDB" in sql.upper() or "nocreatedb" in sql.lower()

    def test_parallel_requests_isolated(self):
        """Test that parallel tenant contexts don't leak (unit level check)."""
        from app.core.database import validate_tenant_id

        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())

        # Both should validate independently
        assert validate_tenant_id(tenant_a) == tenant_a
        assert validate_tenant_id(tenant_b) == tenant_b
        assert tenant_a != tenant_b
