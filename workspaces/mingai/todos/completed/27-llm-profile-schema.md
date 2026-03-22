---
id: 27
title: LLM Profile Redesign — Phase A: Schema Migration
status: pending
priority: critical
phase: A
estimated_days: 2
---

# LLM Profile Redesign — Phase A: Schema Migration

## Context

The existing `llm_profiles` table uses a flat provider/model structure that cannot support multi-slot profiles, BYOLLM, or plan-tier gating. This todo covers the schema layer that everything else depends on. The Alembic migration file `v050_llm_profile_v2.py` already exists — the work here is to bring `schema.py` into alignment with it and write the schema integrity tests.

Two design principles drive this schema:

- Platform profiles: `owner_tenant_id IS NULL`
- BYOLLM profiles: `owner_tenant_id = tenant_id`

These are the only two tracks. Slot mixing across tracks is prohibited at the DB constraint level.

## Scope

Files to modify:

- `src/backend/app/core/schema.py` — update `llm_profiles` table definition to v2, add `llm_profile_history` and `llm_profile_audit_log` to TABLE_NAMES and TABLE_DEFINITIONS

Files to create:

- `tests/unit/test_migration_v050.py` — schema integrity test suite

The migration file (`src/backend/alembic/versions/v050_llm_profile_v2.py`) has been created with the following critical fixes already applied:

- RLS policy `llm_library_tenant_read` updated from `status = 'Published'` → `status = 'published'` (GAP-01: prevents tenant lockout after status lowercase migration)
- `UPDATE tenants SET llm_profile_id = NULL` added before DROP (GAP-03: explicit clean slate, prevents silent CASCADE ambiguity)

**ALSO REQUIRED as part of Phase A**: Search all Python source files and update all hardcoded Title Case status strings. Every file that queries `status = 'Published'`, `status = 'Draft'`, or `status = 'Deprecated'` against `llm_library` must be updated to lowercase before the migration runs:

```bash
grep -rn "'Published'\|'Draft'\|'Deprecated'" src/backend --include="*.py"
```

Known affected files (confirmed by red team): `app/modules/admin/llm_config.py`, `app/core/llm/instrumented_client.py`, `app/modules/documents/reindex.py`, `app/modules/platform/llm_library/routes.py`. Update these BEFORE running v050. Failure to do so will silently break all LLM resolution after migration.

## Requirements

### llm_profiles v2 columns (replace old structure)

Drop from old schema:

- `tenant_id` (FK to tenants)
- `provider`
- `primary_model`
- `intent_model`
- `embedding_model`

Add to new schema:

- `chat_library_id UUID REFERENCES llm_library(id)` — nullable (slot not yet assigned)
- `intent_library_id UUID REFERENCES llm_library(id)` — nullable
- `vision_library_id UUID REFERENCES llm_library(id)` — nullable
- `agent_library_id UUID REFERENCES llm_library(id)` — nullable
- `chat_params JSONB DEFAULT '{}'` — per-slot override params (temperature, max_tokens, etc.)
- `intent_params JSONB DEFAULT '{}'`
- `vision_params JSONB DEFAULT '{}'`
- `agent_params JSONB DEFAULT '{}'`
- `chat_traffic_split JSONB DEFAULT '{}'` — weighted map: {library_id: weight} for A/B routing
- `is_platform_default BOOLEAN NOT NULL DEFAULT FALSE`
- `plan_tiers TEXT[] NOT NULL DEFAULT '{}'` — values: 'starter', 'professional', 'enterprise'
- `owner_tenant_id UUID REFERENCES tenants(id)` — NULL = platform-owned
- `custom_slots JSONB DEFAULT '{}'` — reserved for future extension
- `status TEXT NOT NULL DEFAULT 'draft'` — CHECK IN ('draft', 'active', 'deprecated')

Retain from old schema:

- `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
- `name TEXT NOT NULL`
- `description TEXT`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`

New unique constraints:

- `UNIQUE (name, owner_tenant_id)` — profile names unique per owner (NULL treated as platform namespace)
- Partial unique index: `CREATE UNIQUE INDEX ON llm_profiles (is_platform_default) WHERE is_platform_default = TRUE AND owner_tenant_id IS NULL` — only one platform default

### llm_profile_history table

New table tracking every mutation to a profile:

- `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
- `profile_id UUID NOT NULL REFERENCES llm_profiles(id) ON DELETE CASCADE`
- `actor_id UUID NOT NULL` — user who made the change
- `action TEXT NOT NULL` — e.g. 'created', 'slot_assigned', 'default_set', 'deprecated'
- `previous_state JSONB` — snapshot before change
- `new_state JSONB` — snapshot after change
- `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`

### llm_profile_audit_log table

Immutable audit trail (never DELETE):

- `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
- `profile_id UUID NOT NULL REFERENCES llm_profiles(id)`
- `tenant_id UUID REFERENCES tenants(id)` — nullable (platform actions have no tenant)
- `actor_id UUID NOT NULL`
- `event_type TEXT NOT NULL` — 'profile_created', 'slot_assigned', 'default_changed', 'tenant_selected', 'profile_deprecated', 'byollm_activated'
- `details JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`

No DELETE, no UPDATE on this table. Append-only enforced at application layer.

### schema.py TABLE_NAMES and TABLE_DEFINITIONS

Add both new tables to the existing TABLE_NAMES list and TABLE_DEFINITIONS dict following the existing pattern in that file.

## Acceptance Criteria

- `schema.py` TABLE_DEFINITIONS for `llm_profiles` exactly matches what `v050` migration creates (column names, types, constraints)
- `llm_profile_history` and `llm_profile_audit_log` present in both TABLE_NAMES and TABLE_DEFINITIONS
- `tests/unit/test_migration_v050.py` passes with all of:
  - All v2 FK columns present (chat/intent/vision/agent \_library_id)
  - Unique index prevents two platform defaults (`is_platform_default = TRUE, owner_tenant_id IS NULL`)
  - `(name, owner_tenant_id)` uniqueness enforced
  - `status` CHECK rejects values outside ('draft', 'active', 'deprecated')
  - `llm_library.status` accepts lowercase 'draft'/'published'/'deprecated'/'disabled'
  - Old columns (tenant_id, provider, primary_model, intent_model, embedding_model) absent
- No Alembic downgrade errors (migration is reversible)

## Dependencies

- None — this is the foundation todo for the entire LLM Profile redesign
