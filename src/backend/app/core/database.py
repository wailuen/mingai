"""
Database connection and RLS (Row-Level Security) management.

Every database transaction MUST have tenant context set via
set_tenant_context() before any query execution.

RLS ensures multi-tenant data isolation at the PostgreSQL level.
"""
import uuid as uuid_module

import structlog

logger = structlog.get_logger()

# All tables that require tenant_id-based RLS
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

# Tables with special RLS (not standard tenant_id column)
SPECIAL_RLS_TABLES = {
    "tenants": "id",  # self-referencing: id = current_setting
    "team_memberships": "team_id",  # via subquery to tenant_teams
}


def validate_tenant_id(tenant_id: str) -> str:
    """
    Validate that tenant_id is a proper UUID string.

    Raises ValueError with clear message if invalid.
    NEVER returns a default - explicit validation only.
    """
    if tenant_id is None:
        raise ValueError(
            "tenant_id is None - UUID required. " "Ensure JWT contains tenant_id claim."
        )

    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError(
            "tenant_id is empty - UUID required. "
            "Ensure JWT contains tenant_id claim."
        )

    try:
        uuid_module.UUID(tenant_id)
    except (ValueError, AttributeError):
        raise ValueError(
            f"tenant_id '{tenant_id}' is not a valid UUID. "
            f"Expected format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        )

    return tenant_id


def get_set_tenant_sql(tenant_id: str) -> tuple[str, dict]:
    """
    Generate SQL to set tenant context for RLS.

    Uses set_config with 'true' for transaction-local scope (SET LOCAL equivalent).
    The tenant_id MUST be pre-validated via validate_tenant_id().
    """
    validated = validate_tenant_id(tenant_id)
    # validated is always a UUID (no SQL metacharacters), but we use a parameterized
    # form defensively to prevent any future relaxation of validate_tenant_id from
    # introducing injection.
    return (
        "SELECT set_config('app.current_tenant_id', :tid, true)",
        {"tid": validated},
    )


def get_rls_column_for_table(table_name: str) -> str:
    """
    Get the column used for RLS filtering on a given table.

    Most tables use tenant_id. Special cases:
    - tenants: uses 'id' (self-referencing)
    - team_memberships: uses team_id (via subquery)
    """
    if table_name == "tenants":
        return "id"
    return "tenant_id"


def get_rls_policy_sql(table_name: str) -> str:
    """
    Generate the RLS policy SQL for a given table.

    Returns the complete SQL string including:
    - ALTER TABLE ENABLE ROW LEVEL SECURITY
    - CREATE POLICY with USING and WITH CHECK clauses
    """
    if table_name == "tenants":
        return (
            f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;\n"
            f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;\n"
            f"CREATE POLICY tenant_isolation ON {table_name} FOR ALL "
            f"USING (id = current_setting('app.current_tenant_id')::uuid) "
            f"WITH CHECK (id = current_setting('app.current_tenant_id')::uuid);"
        )

    if table_name == "team_memberships":
        return (
            f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;\n"
            f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;\n"
            f"CREATE POLICY tenant_isolation ON {table_name} FOR ALL "
            f"USING (team_id IN ("
            f"SELECT id FROM tenant_teams "
            f"WHERE tenant_id = current_setting('app.current_tenant_id')::uuid"
            f")) "
            f"WITH CHECK (team_id IN ("
            f"SELECT id FROM tenant_teams "
            f"WHERE tenant_id = current_setting('app.current_tenant_id')::uuid"
            f"));"
        )

    # Standard tenant_id-based RLS
    return (
        f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;\n"
        f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;\n"
        f"CREATE POLICY tenant_isolation ON {table_name} FOR ALL "
        f"USING (tenant_id = current_setting('app.current_tenant_id')::uuid) "
        f"WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid);"
    )


def get_platform_bypass_policy_sql(table_name: str) -> str:
    """
    Generate platform admin bypass policy SQL.

    Platform admins (scope='platform') can access all tenant data
    for cross-tenant operations like analytics and support.
    """
    return (
        f"CREATE POLICY platform_admin_bypass ON {table_name} FOR ALL "
        f"USING (current_setting('app.scope', true) = 'platform') "
        f"WITH CHECK (current_setting('app.scope', true) = 'platform');"
    )


def get_recommended_db_user_sql() -> str:
    """
    SQL to create the application database user.

    The application user MUST be NOSUPERUSER because superusers
    bypass RLS entirely, defeating multi-tenant isolation.
    """
    return (
        "CREATE ROLE mingai_app WITH LOGIN PASSWORD 'from_env_not_hardcoded' "
        "NOSUPERUSER NOCREATEDB NOCREATEROLE;\n"
        "GRANT USAGE ON SCHEMA public TO mingai_app;\n"
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mingai_app;"
    )
