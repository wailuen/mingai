"""
Schema definitions for all 22 mingai database tables.

This module contains the canonical table definitions, column specs,
and table names used by both migrations and tests.

Separated from migration files so tests can import without
the alembic runtime dependency.
"""

# All table names created in the initial migration (DB-001 to DB-022)
# + HAR A2A tables (DB-023 to DB-024) added in Phase 1 Sprint 5
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
    "har_transactions",
    "har_transaction_events",
    "notifications",
    "llm_profile_history",
    "llm_profile_audit_log",
]

# All tables requiring RLS (standard tenant_id + special cases)
RLS_TABLES = TABLE_NAMES  # All tables get RLS

# Table SQL definitions for migration and test validation
TABLE_DEFINITIONS = {
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
        # v2 schema (rebuilt by v050 migration — two-track: NULL=platform, UUID=BYOLLM)
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "name VARCHAR(255) NOT NULL, "
        "description VARCHAR(1000), "
        "status VARCHAR(50) NOT NULL DEFAULT 'active' "
        "CHECK (status IN ('active', 'deprecated')), "
        "chat_library_id UUID, "       # REFERENCES llm_library(id)
        "intent_library_id UUID, "     # REFERENCES llm_library(id)
        "vision_library_id UUID, "     # REFERENCES llm_library(id)
        "agent_library_id UUID, "      # REFERENCES llm_library(id)
        "chat_params JSONB DEFAULT '{}', "
        "intent_params JSONB DEFAULT '{}', "
        "vision_params JSONB DEFAULT '{}', "
        "agent_params JSONB DEFAULT '{}', "
        "chat_traffic_split JSONB DEFAULT '[]', "
        "intent_traffic_split JSONB DEFAULT '[]', "
        "vision_traffic_split JSONB DEFAULT '[]', "
        "agent_traffic_split JSONB DEFAULT '[]', "
        "custom_slots JSONB DEFAULT '{}', "
        "is_platform_default BOOLEAN NOT NULL DEFAULT false, "
        "plan_tiers TEXT[] DEFAULT '{}', "
        "owner_tenant_id UUID, "       # REFERENCES tenants(id) — NULL=platform
        "created_by UUID, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
        "UNIQUE (name, owner_tenant_id)"
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
        "category VARCHAR(100), "
        "source VARCHAR(50) NOT NULL DEFAULT 'custom', "
        "avatar TEXT, "
        "template_id TEXT, "
        "template_version INTEGER, "
        "created_by UUID REFERENCES users(id), "
        "public_key TEXT, "
        "private_key_enc TEXT, "
        "trust_score INTEGER DEFAULT 0, "
        "kyb_level INTEGER DEFAULT 0, "
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
    "har_transactions": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "initiator_agent_id UUID NOT NULL REFERENCES agent_cards(id), "
        "counterparty_agent_id UUID NOT NULL REFERENCES agent_cards(id), "
        "state VARCHAR(50) NOT NULL DEFAULT 'DRAFT' "
        "CHECK (state IN ('DRAFT','OPEN','NEGOTIATING','COMMITTED','EXECUTING','COMPLETED','ABANDONED','DISPUTED','RESOLVED')), "
        "amount NUMERIC(18,6), "
        "currency VARCHAR(10), "
        "payload JSONB DEFAULT '{}', "
        "requires_human_approval BOOLEAN DEFAULT false, "
        "human_approved_at TIMESTAMPTZ, "
        "human_approved_by UUID REFERENCES users(id), "
        "approval_deadline TIMESTAMPTZ, "
        "chain_head_hash TEXT, "
        "created_at TIMESTAMPTZ DEFAULT NOW(), "
        "updated_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "har_transaction_events": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "transaction_id UUID NOT NULL REFERENCES har_transactions(id) ON DELETE CASCADE, "
        "event_type VARCHAR(100) NOT NULL, "
        "actor_agent_id UUID REFERENCES agent_cards(id), "
        "actor_user_id UUID REFERENCES users(id), "
        "payload JSONB DEFAULT '{}', "
        "signature TEXT, "
        "nonce VARCHAR(64), "
        "prev_event_hash TEXT, "
        "event_hash TEXT, "
        "created_at TIMESTAMPTZ DEFAULT NOW()"
    ),
    "notifications": (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, "
        "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "type VARCHAR(50) NOT NULL, "
        "title VARCHAR(200) NOT NULL, "
        "body TEXT NOT NULL DEFAULT '', "
        "link VARCHAR(500), "
        "read BOOLEAN NOT NULL DEFAULT false, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
    ),
    # v050 new tables (LLM Profile redesign)
    "llm_profile_history": (
        # Mutation history for rollback support
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "profile_id UUID NOT NULL, "    # REFERENCES llm_profiles(id) ON DELETE CASCADE
        "slot_snapshot JSONB NOT NULL, "
        "changed_by UUID, "
        "changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
        "change_reason TEXT"
    ),
    "llm_profile_audit_log": (
        # SOC 2 append-only audit trail — no DELETE, no UPDATE
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "entity_type VARCHAR(50), "
        "entity_id UUID, "
        "action VARCHAR(50), "
        "actor_id UUID, "
        "tenant_id UUID, "
        "diff JSONB, "
        "ip_address INET, "
        "logged_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
    ),
}


def get_table_definition(table_name: str) -> str:
    """Get the SQL column definition for a table."""
    if table_name not in TABLE_DEFINITIONS:
        raise ValueError(
            f"Unknown table '{table_name}'. "
            f"Known tables: {', '.join(sorted(TABLE_DEFINITIONS.keys()))}"
        )
    return TABLE_DEFINITIONS[table_name]
