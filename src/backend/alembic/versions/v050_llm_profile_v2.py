"""v050 — LLM Profile v2 (clean rebuild)

Revision ID: 050
Revises: 049
Create Date: 2026-03-22

Phase A of the LLM Profile redesign:

A1. Extend llm_library:
    - capabilities JSONB (eligible_slots, supports_vision, supports_tool_calling, etc.)
    - health_status / health_checked_at (background health probe results)
    - is_byollm BOOLEAN (tenant-owned entries)
    - owner_tenant_id UUID (BYOLLM: null = platform-owned)
    - Status constraint migrated from Title Case to lowercase + 'disabled' state added

A2. Drop and recreate llm_profiles:
    - Two-track architecture: owner_tenant_id IS NULL = platform, otherwise = BYOLLM
    - Four slot columns (chat/intent/vision/agent) → UUID FKs to llm_library
    - Per-slot params + traffic split JSONB for A/B model testing
    - is_platform_default with unique partial index (one platform default at a time)
    - plan_tiers TEXT[] controls tenant tier gating

A3. Create llm_profile_history (rollback support)
A4. Create llm_profile_audit_log (SOC 2 compliance)
A5. Restore tenants.llm_profile_id FK to new llm_profiles table

DOWN migration fully restores prior state (original llm_profiles schema,
llm_library constraints restored, supporting tables dropped).
"""
from alembic import op

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # A1. Extend llm_library
    # -------------------------------------------------------------------------

    # Fix RLS policy BEFORE migrating status values.
    # The v009 policy uses status = 'Published' (Title Case). After we convert
    # all values to lowercase, that policy would match zero rows — silently
    # locking all tenants out of the library. Drop and recreate it now.
    op.execute(
        "DROP POLICY IF EXISTS llm_library_tenant_read ON llm_library"
    )
    op.execute(
        "CREATE POLICY llm_library_tenant_read ON llm_library "
        "FOR SELECT "
        "USING (status = 'published')"
    )

    # Drop old Title Case status constraint BEFORE migrating values
    op.execute(
        "ALTER TABLE llm_library "
        "DROP CONSTRAINT IF EXISTS llm_library_status_check"
    )

    # Migrate existing status values from Title Case to lowercase
    # (existing rows: 'Draft' → 'draft', 'Published' → 'published',
    #  'Deprecated' → 'deprecated')
    op.execute(
        "UPDATE llm_library SET status = LOWER(status) "
        "WHERE status IN ('Draft', 'Published', 'Deprecated')"
    )

    # Add four-state status constraint (draft → published → deprecated → disabled)
    op.execute(
        "ALTER TABLE llm_library "
        "ADD CONSTRAINT llm_library_status_check "
        "CHECK (status IN ('draft','published','deprecated','disabled'))"
    )

    # New columns on llm_library
    op.execute(
        "ALTER TABLE llm_library "
        "ADD COLUMN IF NOT EXISTS capabilities     JSONB DEFAULT '{}', "
        "ADD COLUMN IF NOT EXISTS health_status    VARCHAR(50) DEFAULT 'unknown' "
        "    CHECK (health_status IN ('healthy','degraded','unknown')), "
        "ADD COLUMN IF NOT EXISTS health_checked_at TIMESTAMPTZ, "
        "ADD COLUMN IF NOT EXISTS is_byollm        BOOLEAN DEFAULT false, "
        "ADD COLUMN IF NOT EXISTS owner_tenant_id  UUID REFERENCES tenants(id)"
    )

    # -------------------------------------------------------------------------
    # A2. Rebuild llm_profiles (DROP CASCADE removes any dependent FKs,
    #     including tenants_llm_profile_id_fkey if it existed)
    # -------------------------------------------------------------------------

    # GAP-03: Intentional clean slate — the old llm_profiles table stored
    # per-tenant profiles with raw model name strings (no Library FK). There is
    # no meaningful data to carry forward. Null out tenant assignments now so the
    # FK drop is explicit and documented, not a silent CASCADE side-effect.
    # Post-migration: platform admin must create profiles and assign tenants.
    op.execute("UPDATE tenants SET llm_profile_id = NULL")

    # Remove FK from tenants before drop
    op.execute(
        "ALTER TABLE tenants "
        "DROP CONSTRAINT IF EXISTS tenants_llm_profile_id_fkey"
    )

    op.execute("DROP TABLE IF EXISTS llm_profiles CASCADE")

    op.execute(
        """
        CREATE TABLE llm_profiles (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name                 VARCHAR(255) NOT NULL,
            description          VARCHAR(1000),
            status               VARCHAR(50) NOT NULL DEFAULT 'active'
                                 CHECK (status IN ('active', 'deprecated')),

            -- Slot assignments (FK → llm_library entries)
            chat_library_id      UUID REFERENCES llm_library(id),
            intent_library_id    UUID REFERENCES llm_library(id),
            vision_library_id    UUID REFERENCES llm_library(id),
            agent_library_id     UUID REFERENCES llm_library(id),

            -- Per-slot inference parameters (temperature, max_tokens, etc.)
            chat_params          JSONB DEFAULT '{}',
            intent_params        JSONB DEFAULT '{}',
            vision_params        JSONB DEFAULT '{}',
            agent_params         JSONB DEFAULT '{}',

            -- Traffic splitting for A/B model testing (Enterprise)
            -- Format: [{"library_entry_id": "uuid", "weight": 90}, ...]
            chat_traffic_split   JSONB DEFAULT '[]',
            intent_traffic_split JSONB DEFAULT '[]',
            vision_traffic_split JSONB DEFAULT '[]',
            agent_traffic_split  JSONB DEFAULT '[]',

            -- Extensibility for future slots
            custom_slots         JSONB DEFAULT '{}',

            -- Platform default and tier availability
            is_platform_default  BOOLEAN NOT NULL DEFAULT false,
            plan_tiers           TEXT[] DEFAULT '{}',

            -- Two-track: NULL = platform-owned; UUID = BYOLLM (tenant-owned)
            owner_tenant_id      UUID REFERENCES tenants(id),

            created_by           UUID,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            UNIQUE (name, owner_tenant_id)
        )
        """
    )

    # Only one platform default at a time
    op.execute(
        "CREATE UNIQUE INDEX uq_llm_profiles_platform_default "
        "ON llm_profiles ((true)) "
        "WHERE is_platform_default = true AND owner_tenant_id IS NULL"
    )

    # -------------------------------------------------------------------------
    # A3. Profile version history (rollback support)
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_profile_history (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            profile_id    UUID NOT NULL REFERENCES llm_profiles(id) ON DELETE CASCADE,
            slot_snapshot JSONB NOT NULL,
            changed_by    UUID,
            changed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            change_reason TEXT
        )
        """
    )

    # -------------------------------------------------------------------------
    # A4. Audit log (SOC 2 compliance — all mutations recorded)
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_profile_audit_log (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_type VARCHAR(50),
            entity_id   UUID,
            action      VARCHAR(50),
            actor_id    UUID,
            tenant_id   UUID,
            diff        JSONB,
            ip_address  INET,
            logged_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # -------------------------------------------------------------------------
    # A5. Restore FK: tenants.llm_profile_id → llm_profiles.id
    # -------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE tenants "
        "ADD CONSTRAINT tenants_llm_profile_id_fkey "
        "FOREIGN KEY (llm_profile_id) REFERENCES llm_profiles(id)"
    )

    # -------------------------------------------------------------------------
    # RLS policies for new tables
    # -------------------------------------------------------------------------

    # llm_profiles: platform admin full access; tenants see only profiles they
    # can use (platform-owned matching their tier, or their own BYOLLM profile)
    op.execute("ALTER TABLE llm_profiles ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY llm_profiles_platform_admin ON llm_profiles "
        "USING (current_setting('app.user_role', true) = 'platform_admin')"
    )
    op.execute(
        "CREATE POLICY llm_profiles_tenant_read ON llm_profiles "
        "FOR SELECT "
        "USING ("
        "    owner_tenant_id IS NULL "  # platform profiles (all tenants can read)
        "    OR owner_tenant_id::text = current_setting('app.tenant_id', true)"  # own BYOLLM
        ")"
    )

    # llm_profile_history: platform admin only
    op.execute("ALTER TABLE llm_profile_history ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY llm_profile_history_platform_admin ON llm_profile_history "
        "USING (current_setting('app.user_role', true) = 'platform_admin')"
    )

    # llm_profile_audit_log: platform admin only
    op.execute("ALTER TABLE llm_profile_audit_log ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY llm_profile_audit_log_platform_admin ON llm_profile_audit_log "
        "USING (current_setting('app.user_role', true) = 'platform_admin')"
    )


def downgrade() -> None:
    # -------------------------------------------------------------------------
    # Remove FK from tenants before dropping tables
    # -------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE tenants "
        "DROP CONSTRAINT IF EXISTS tenants_llm_profile_id_fkey"
    )

    # -------------------------------------------------------------------------
    # Drop new tables
    # -------------------------------------------------------------------------
    op.execute("DROP TABLE IF EXISTS llm_profile_audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS llm_profile_history CASCADE")
    op.execute("DROP TABLE IF EXISTS llm_profiles CASCADE")

    # -------------------------------------------------------------------------
    # Restore original llm_profiles schema
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE llm_profiles (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name           VARCHAR(255) NOT NULL,
            provider       VARCHAR(100) NOT NULL,
            primary_model  VARCHAR(255) NOT NULL,
            intent_model   VARCHAR(255) NOT NULL,
            embedding_model VARCHAR(255) NOT NULL,
            endpoint_url   VARCHAR(500),
            api_key_ref    VARCHAR(500),
            is_default     BOOLEAN DEFAULT false,
            status         VARCHAR(50) NOT NULL DEFAULT 'active'
                           CHECK (status IN ('active', 'deprecated')),
            created_at     TIMESTAMPTZ DEFAULT NOW(),
            updated_at     TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )

    # -------------------------------------------------------------------------
    # Revert llm_library extensions
    # -------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE llm_library "
        "DROP COLUMN IF EXISTS owner_tenant_id, "
        "DROP COLUMN IF EXISTS is_byollm, "
        "DROP COLUMN IF EXISTS health_checked_at, "
        "DROP COLUMN IF EXISTS health_status, "
        "DROP COLUMN IF EXISTS capabilities"
    )

    # Restore status constraint (lowercase → Title Case)
    op.execute(
        "ALTER TABLE llm_library "
        "DROP CONSTRAINT IF EXISTS llm_library_status_check"
    )
    op.execute(
        "UPDATE llm_library SET status = "
        "CASE status "
        "  WHEN 'draft' THEN 'Draft' "
        "  WHEN 'published' THEN 'Published' "
        "  WHEN 'deprecated' THEN 'Deprecated' "
        "  WHEN 'disabled' THEN 'Deprecated' "  # map disabled → deprecated (no prior state)
        "  ELSE status END"
    )
    op.execute(
        "ALTER TABLE llm_library "
        "ADD CONSTRAINT llm_library_status_check "
        "CHECK (status IN ('Draft', 'Published', 'Deprecated'))"
    )

    # Restore Title Case RLS policy
    op.execute("DROP POLICY IF EXISTS llm_library_tenant_read ON llm_library")
    op.execute(
        "CREATE POLICY llm_library_tenant_read ON llm_library "
        "FOR SELECT "
        "USING (status = 'Published')"
    )
