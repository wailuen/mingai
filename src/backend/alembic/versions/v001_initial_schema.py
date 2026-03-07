"""
001 Initial Schema - Create all 22 tables for mingai platform.

DB-001 through DB-022: Core multi-tenant schema with tenant_id
on every table, proper FK constraints, and indexes.

Revision ID: 001
Revises: None
Create Date: 2026-03-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers
revision = "001"
down_revision = None
branch_labels = None
depends_on = None

# All table names created in this migration
TABLE_NAMES = [
    "tenants",
    "users",
    "tenant_configs",
    "llm_profiles",
    "conversations",
    "messages",
    "user_feedback",
    "user_profiles",
    "memory_notes",
    "profile_learning_events",
    "working_memory_snapshots",
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

# Table definitions for validation (used by tests)
_TABLE_DEFINITIONS = {
    "tenants": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "name VARCHAR(255) NOT NULL, "
        "slug VARCHAR(100) UNIQUE NOT NULL, "
        "plan VARCHAR(50) NOT NULL DEFAULT 'professional' "
        "CHECK (plan IN ('starter','professional','enterprise')), "
        "status VARCHAR(50) NOT NULL DEFAULT 'active' "
        "CHECK (status IN ('draft','active','suspended','scheduled_deletion','deleted')), "
        "primary_contact_email VARCHAR(255) NOT NULL, "
        "llm_profile_id UUID, "
        "created_at TIMESTAMPTZ DEFAULT NOW(), "
        "updated_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "users": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "email VARCHAR(255) NOT NULL, "
        "name VARCHAR(255), "
        "password_hash VARCHAR(255), "
        "role VARCHAR(50) NOT NULL DEFAULT 'user', "
        "status VARCHAR(50) NOT NULL DEFAULT 'active', "
        "last_login_at TIMESTAMPTZ, "
        "created_at TIMESTAMPTZ DEFAULT NOW(), "
        "UNIQUE (tenant_id, email)"
    ),
    "tenant_configs": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "config_type VARCHAR(100) NOT NULL, "
        "config_data JSONB NOT NULL DEFAULT '{}', "
        "api_key_ref VARCHAR(500), "
        "rate_limit_rpm INTEGER DEFAULT 60, "
        "monthly_token_budget INTEGER, "
        "created_at TIMESTAMPTZ DEFAULT NOW(), "
        "updated_at TIMESTAMPTZ DEFAULT NOW(), "
        "UNIQUE (tenant_id, config_type)"
    ),
    "llm_profiles": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "name VARCHAR(255) NOT NULL, "
        "provider VARCHAR(100) NOT NULL, "
        "primary_model VARCHAR(255) NOT NULL, "
        "intent_model VARCHAR(255) NOT NULL, "
        "embedding_model VARCHAR(255) NOT NULL, "
        "endpoint_url VARCHAR(500), "
        "api_key_ref VARCHAR(500), "
        "is_default BOOLEAN DEFAULT false, "
        "created_at TIMESTAMPTZ DEFAULT NOW(), "
        "updated_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "conversations": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "agent_id UUID, "
        "title VARCHAR(500), "
        "created_at TIMESTAMPTZ DEFAULT NOW(), "
        "updated_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "messages": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, "
        "role VARCHAR(20) NOT NULL, "
        "content TEXT NOT NULL, "
        "tokens_used INTEGER, "
        "model_used VARCHAR(255), "
        "retrieval_confidence FLOAT, "
        "metadata JSONB DEFAULT '{}', "
        "created_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "user_feedback": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE, "
        "rating INTEGER NOT NULL CHECK (rating IN (-1, 1)), "
        "comment TEXT, "
        "tags TEXT[] DEFAULT '{}', "
        "created_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "user_profiles": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "technical_level VARCHAR(20), "
        "communication_style VARCHAR(20), "
        "interests JSONB DEFAULT '[]', "
        "expertise_areas JSONB DEFAULT '[]', "
        "common_tasks JSONB DEFAULT '[]', "
        "profile_learning_enabled BOOLEAN DEFAULT true, "
        "org_context_enabled BOOLEAN DEFAULT true, "
        "share_manager_info BOOLEAN DEFAULT true, "
        "query_count INTEGER DEFAULT 0, "
        "last_learned_at TIMESTAMPTZ, "
        "created_at TIMESTAMPTZ DEFAULT NOW(), "
        "updated_at TIMESTAMPTZ DEFAULT NOW(), "
        "UNIQUE (tenant_id, user_id)"
    ),
    "memory_notes": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "agent_id UUID, "
        "content TEXT NOT NULL, "
        "source VARCHAR(20) NOT NULL, "
        "created_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "profile_learning_events": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "agent_id UUID, "
        "extracted_attributes JSONB, "
        "conversations_analyzed INTEGER, "
        "created_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "working_memory_snapshots": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "agent_id UUID, "
        "snapshot_data JSONB NOT NULL, "
        "created_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "tenant_teams": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "name VARCHAR(255) NOT NULL, "
        "description TEXT, "
        "source VARCHAR(20) NOT NULL DEFAULT 'manual', "
        "auth0_group_name VARCHAR(255), "
        "created_at TIMESTAMPTZ DEFAULT NOW(), "
        "UNIQUE (tenant_id, name)"
    ),
    "team_memberships": (
        "team_id UUID NOT NULL REFERENCES tenant_teams(id) ON DELETE CASCADE, "
        "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "source VARCHAR(20) NOT NULL DEFAULT 'manual', "
        "added_at TIMESTAMPTZ DEFAULT NOW(), "
        "PRIMARY KEY (team_id, user_id)"
    ),
    "team_membership_audit": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "team_id UUID NOT NULL REFERENCES tenant_teams(id), "
        "user_id UUID NOT NULL REFERENCES users(id), "
        "action VARCHAR(20) NOT NULL, "
        "actor_id UUID REFERENCES users(id), "
        "source VARCHAR(20) NOT NULL, "
        "created_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "glossary_terms": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "term VARCHAR(200) NOT NULL, "
        "full_form VARCHAR(500) NOT NULL, "
        "aliases JSONB DEFAULT '[]', "
        "created_at TIMESTAMPTZ DEFAULT NOW(), "
        "UNIQUE (tenant_id, term)"
    ),
    "glossary_miss_signals": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "query_text TEXT NOT NULL, "
        "unresolved_term VARCHAR(200) NOT NULL, "
        "occurrence_count INTEGER DEFAULT 1, "
        "created_at TIMESTAMPTZ DEFAULT NOW(), "
        "updated_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "integrations": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "provider VARCHAR(50) NOT NULL, "
        "status VARCHAR(50) NOT NULL DEFAULT 'pending', "
        "config JSONB NOT NULL DEFAULT '{}', "
        "credential_ref VARCHAR(500), "
        "last_sync_at TIMESTAMPTZ, "
        "created_at TIMESTAMPTZ DEFAULT NOW(), "
        "updated_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "sync_jobs": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "integration_id UUID NOT NULL REFERENCES integrations(id) ON DELETE CASCADE, "
        "status VARCHAR(50) NOT NULL DEFAULT 'pending', "
        "files_total INTEGER DEFAULT 0, "
        "files_synced INTEGER DEFAULT 0, "
        "files_failed INTEGER DEFAULT 0, "
        "error_message TEXT, "
        "started_at TIMESTAMPTZ, "
        "completed_at TIMESTAMPTZ, "
        "created_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "issue_reports": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "reporter_id UUID NOT NULL REFERENCES users(id), "
        "conversation_id UUID REFERENCES conversations(id), "
        "message_id UUID REFERENCES messages(id), "
        "issue_type VARCHAR(50) NOT NULL, "
        "description TEXT NOT NULL, "
        "severity VARCHAR(20) NOT NULL DEFAULT 'medium', "
        "status VARCHAR(50) NOT NULL DEFAULT 'open', "
        "screenshot_url VARCHAR(500), "
        "blur_acknowledged BOOLEAN NOT NULL DEFAULT false, "
        "metadata JSONB DEFAULT '{}', "
        "created_at TIMESTAMPTZ DEFAULT NOW(), "
        "updated_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "issue_report_events": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "issue_id UUID NOT NULL REFERENCES issue_reports(id) ON DELETE CASCADE, "
        "event_type VARCHAR(50) NOT NULL, "
        "actor_id UUID REFERENCES users(id), "
        "data JSONB DEFAULT '{}', "
        "created_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "agent_cards": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "name VARCHAR(255) NOT NULL, "
        "description TEXT, "
        "system_prompt TEXT NOT NULL, "
        "capabilities JSONB DEFAULT '[]', "
        "status VARCHAR(50) NOT NULL DEFAULT 'draft', "
        "version INTEGER NOT NULL DEFAULT 1, "
        "created_by UUID REFERENCES users(id), "
        "created_at TIMESTAMPTZ DEFAULT NOW(), "
        "updated_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "audit_log": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "user_id UUID REFERENCES users(id), "
        "action VARCHAR(100) NOT NULL, "
        "resource_type VARCHAR(100), "
        "resource_id UUID, "
        "details JSONB DEFAULT '{}', "
        "ip_address VARCHAR(45), "
        "created_at TIMESTAMPTZ DEFAULT NOW()"
    ),
}


def get_table_definition(table_name: str) -> str:
    """Get the SQL column definition for a table (used by tests and migrations)."""
    if table_name not in _TABLE_DEFINITIONS:
        raise ValueError(
            f"Unknown table '{table_name}'. "
            f"Known tables: {', '.join(sorted(_TABLE_DEFINITIONS.keys()))}"
        )
    return _TABLE_DEFINITIONS[table_name]


def upgrade() -> None:
    """Create all 22 tables in dependency order."""
    # This is called by Alembic. The actual SQL is generated from
    # _TABLE_DEFINITIONS above.
    for table_name in TABLE_NAMES:
        definition = _TABLE_DEFINITIONS[table_name]
        op.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({definition});")

    # Create indexes
    _create_indexes()


def downgrade() -> None:
    """Drop all tables in reverse dependency order."""
    for table_name in reversed(TABLE_NAMES):
        op.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")


def _create_indexes() -> None:
    """Create performance indexes for all tables."""
    index_statements = [
        "CREATE INDEX IF NOT EXISTS idx_users_tenant_email ON users(tenant_id, email);",
        "CREATE INDEX IF NOT EXISTS idx_conversations_tenant_user ON conversations(tenant_id, user_id, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);",
        "CREATE INDEX IF NOT EXISTS idx_messages_tenant ON messages(tenant_id, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_memory_notes_user ON memory_notes(tenant_id, user_id, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_glossary_tenant ON glossary_terms(tenant_id);",
        "CREATE INDEX IF NOT EXISTS idx_team_memberships_user ON team_memberships(user_id);",
        "CREATE INDEX IF NOT EXISTS idx_audit_log_tenant ON audit_log(tenant_id, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_issue_reports_tenant ON issue_reports(tenant_id, status, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_sync_jobs_tenant ON sync_jobs(tenant_id, status);",
    ]
    for stmt in index_statements:
        op.execute(stmt)
