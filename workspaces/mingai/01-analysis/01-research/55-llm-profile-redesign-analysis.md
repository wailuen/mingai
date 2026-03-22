# LLM Profile Configuration — Redesign Analysis (Final)

**Date**: 2026-03-22 (revised post-decisions)
**Status**: Final — all open decisions resolved
**Decisions locked**:

- D1: Platform creates profiles; tenants select whole profile — no slot mixing
- D2: BYOLLM is per-slot, fully separate track from platform profiles
- D3: Profiles are fully platform-admin-configurable — no hardcoded profiles

---

## 1. The Two-Level Architecture

```
LLM Library Entry
  = one fully-specified, tested connection to one model deployment
  = platform admin owns all platform entries
  = Enterprise BYOLLM tenant creates their own entries (per-slot)

LLM Profile
  = a named set of 4 slot assignments → Library entry IDs
  = platform admin creates and publishes
  = tenants SELECT a profile (never build one, unless BYOLLM)
```

The current implementation is broken on both levels:

- `llm_library` has no endpoint, credentials, or capability metadata
- `llm_profiles` stores raw model name strings (not FK references to Library)
- `llm_config` returns a single flat `{ model_source, llm_library_id }` — no per-slot info
- `InstrumentedLLMClient._resolve_adapter()` has no slot awareness

Both levels require a clean rebuild. No migration from legacy data — fresh start.

---

## 2. The Two Tracks

Every tenant is on exactly one track. Tracks do not mix.

### Track 1: Platform Profile (Starter / Professional / Enterprise)

```
Platform Admin → creates Library entries → builds Profiles → assigns to plan tiers
Tenant Admin   → sees available profiles for their plan → selects one → done
```

- Tenant selects the whole profile, never individual slots
- If tenant wants something different, they either pick another available profile
  or ask the platform admin to create one
- Professional gets more profile choices than Starter; Enterprise gets all profiles

### Track 2: BYOLLM (Enterprise only)

```
Enterprise Tenant → creates their own Library entries (per-slot) →
                    builds their own Profile →
                    activates it
```

- Completely separate from platform profiles
- BYOLLM tenant never interacts with platform-created profiles
- Each slot can point to a different endpoint/key (per-slot BYOLLM)
- Tenant is responsible for availability, cost, and performance
- Cost analytics shows "Untracked (BYOLLM)" for these slots
- UX positions this as an advanced escape hatch, not the default path

---

## 3. The 4 Tenant-Facing Slots

| Slot       | Operations                                                                                                    | Requirements                                      | Optimal Models                                     |
| ---------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | -------------------------------------------------- |
| **chat**   | Response synthesis, streaming                                                                                 | `supports_streaming`, 128K+ context               | GPT-5.2-chat, Claude 4 Opus, Gemini 2.5 Pro        |
| **intent** | Routing, confidence scoring, auto-titling, profile extraction, suggestions, email generation, index selection | `supports_json_mode`, <500ms latency              | GPT-5 Mini, Claude 3.5 Haiku, Gemini Flash         |
| **vision** | Image OCR, chart extraction, diagram analysis                                                                 | `supports_vision` (multimodal — hard requirement) | GPT-5.2-chat vision, Claude 4 Opus, Gemini 2.5 Pro |
| **agent**  | A2A agent internal reasoning (email triage, financial analysis, MCP endpoints)                                | `supports_tool_calling`, `supports_json_mode`     | GPT-5.2-chat, GPT-5.1-chat, Claude 4 Sonnet        |

### Two Platform-Managed Slots (Never Tenant-Facing)

| Slot            | Model                  | Dimension | Why Excluded                                       |
| --------------- | ---------------------- | --------- | -------------------------------------------------- |
| `doc_embedding` | text-embedding-3-large | 3072d     | Changing requires full re-index of all documents   |
| `kb_embedding`  | text-embedding-ada-002 | 1536d     | Mixed dimensions break vector search compatibility |

Shown as read-only informational rows in the tenant profile UI. Cannot be overridden by anyone — future "Embedding Migration" feature handles this separately with proper safeguards.

---

## 4. Data Model

### 4.1 `llm_library` Table (extended)

```sql
CREATE TABLE llm_library (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name         VARCHAR(255) NOT NULL,
    provider             VARCHAR(50) NOT NULL,         -- azure_openai | openai_direct | anthropic | google
    model_name           VARCHAR(200) NOT NULL,
    endpoint_url         VARCHAR(500),                 -- required for azure_openai
    api_key_encrypted    BYTEA,                        -- Fernet-encrypted, NEVER returned in API
    api_key_last4        VARCHAR(4),                   -- masking only
    api_version          VARCHAR(50),                  -- required for azure_openai
    plan_tier            VARCHAR(50),
    is_recommended       BOOLEAN DEFAULT false,
    status               VARCHAR(50) DEFAULT 'draft'
                         CHECK (status IN ('draft', 'published', 'deprecated', 'disabled')),
    capabilities         JSONB DEFAULT '{}',           -- see §4.3
    pricing_per_1k_in    DECIMAL,
    pricing_per_1k_out   DECIMAL,
    last_test_passed_at  TIMESTAMPTZ,
    health_status        VARCHAR(50) DEFAULT 'unknown'
                         CHECK (health_status IN ('healthy', 'degraded', 'unknown')),
    health_checked_at    TIMESTAMPTZ,

    -- BYOLLM ownership (null = platform-owned)
    is_byollm            BOOLEAN DEFAULT false,
    owner_tenant_id      UUID REFERENCES tenants(id),

    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);
```

**Four-state lifecycle**:

- `draft` → can be edited, not assignable to profiles
- `published` → assignable to profiles, serving requests
- `deprecated` → not assignable, still serving existing assignments (warning shown)
- `disabled` → not serving, emergency stop (requires all profiles to reassign first)

### 4.2 `llm_profiles` Table

```sql
CREATE TABLE llm_profiles (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 VARCHAR(255) NOT NULL UNIQUE,
    description          VARCHAR(1000),
    status               VARCHAR(50) DEFAULT 'active'
                         CHECK (status IN ('active', 'deprecated')),

    -- Slot assignments: FK → published llm_library entry
    chat_library_id      UUID REFERENCES llm_library(id),   -- required
    intent_library_id    UUID REFERENCES llm_library(id),   -- required
    vision_library_id    UUID REFERENCES llm_library(id),   -- optional
    agent_library_id     UUID REFERENCES llm_library(id),   -- required

    -- Per-slot parameter overrides (set by platform admin when building the profile)
    chat_params          JSONB DEFAULT '{}',  -- {temperature, max_tokens, reasoning_effort}
    intent_params        JSONB DEFAULT '{}',
    vision_params        JSONB DEFAULT '{}',
    agent_params         JSONB DEFAULT '{}',

    -- Traffic splitting per slot (Enterprise A/B model testing)
    chat_traffic_split   JSONB DEFAULT '[]',  -- [{library_entry_id, weight}]
    intent_traffic_split JSONB DEFAULT '[]',
    vision_traffic_split JSONB DEFAULT '[]',
    agent_traffic_split  JSONB DEFAULT '[]',

    -- Extensibility: custom slots for future expansion
    custom_slots         JSONB DEFAULT '{}',

    -- Availability
    is_platform_default  BOOLEAN DEFAULT false,
    plan_tiers           TEXT[] DEFAULT '{}',  -- ['starter', 'professional', 'enterprise']

    -- BYOLLM ownership (null = platform-owned; tenant_id = BYOLLM profile)
    owner_tenant_id      UUID REFERENCES tenants(id),

    created_by           UUID,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);

-- Exactly one platform default at all times
CREATE UNIQUE INDEX uq_llm_profiles_single_default
    ON llm_profiles ((true))
    WHERE is_platform_default = true AND owner_tenant_id IS NULL;
```

**Platform profiles**: `owner_tenant_id IS NULL` — created by platform admin, available to tenants per `plan_tiers`.

**BYOLLM profiles**: `owner_tenant_id = tenant_id` — created by Enterprise tenant, visible only to that tenant.

### 4.3 `llm_profile_history` Table

```sql
CREATE TABLE llm_profile_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id      UUID NOT NULL REFERENCES llm_profiles(id) ON DELETE CASCADE,
    slot_snapshot   JSONB NOT NULL,  -- complete slot assignments at change time
    changed_by      UUID,
    changed_at      TIMESTAMPTZ DEFAULT NOW(),
    change_reason   TEXT
);
```

Every profile mutation writes a snapshot. Rollback = copy `slot_snapshot` back to profile.

### 4.4 `llm_profile_audit_log` Table

```sql
CREATE TABLE llm_profile_audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(50),   -- 'profile' | 'library_entry'
    entity_id   UUID,
    action      VARCHAR(50),   -- 'created' | 'updated' | 'activated' | 'deprecated' | ...
    actor_id    UUID,
    tenant_id   UUID,
    diff        JSONB,         -- before/after values
    ip_address  INET,
    logged_at   TIMESTAMPTZ DEFAULT NOW()
);
```

Every mutation to profiles and Library entries is logged here. SOC 2 requirement.

### 4.5 Tenant → Profile Assignment

```sql
-- Existing column on tenants table
ALTER TABLE tenants ADD COLUMN llm_profile_id UUID REFERENCES llm_profiles(id);
```

- Platform profile: `llm_profile_id` points to a platform-owned profile (`owner_tenant_id IS NULL`)
- BYOLLM profile: `llm_profile_id` points to the tenant's own profile (`owner_tenant_id = tenant_id`)
- NULL: use platform default

### 4.6 Capabilities JSONB on Library Entries

```json
{
  "supports_streaming": true,
  "supports_vision": false,
  "supports_json_mode": true,
  "supports_tool_calling": true,
  "supports_reasoning_effort": true,
  "max_context_tokens": 128000,
  "max_output_tokens": 16384,
  "eligible_slots": ["chat", "intent", "agent"]
}
```

`eligible_slots` is the enforcement gate at assignment time. Auto-derived from capability flags; platform admin can manually override.

Slot capability requirements:

- **chat**: `supports_streaming = true`, `max_context_tokens >= 32000`
- **intent**: `supports_json_mode = true`
- **vision**: `supports_vision = true` (hard gate — rejects assignment if missing)
- **agent**: `supports_tool_calling = true`, `supports_json_mode = true`

---

## 5. Plan Tier Gating

| Capability                       | Starter               | Professional                         | Enterprise                         |
| -------------------------------- | --------------------- | ------------------------------------ | ---------------------------------- |
| Profile selection                | Auto-assigned default | All profiles marked for Professional | All profiles marked for Enterprise |
| Per-slot override                | No                    | No                                   | No                                 |
| BYOLLM track                     | No                    | No                                   | Yes                                |
| View embedding slots (read-only) | Yes                   | Yes                                  | Yes                                |

No tier has slot-level mixing. The difference between tiers is how many platform profiles are available, not what can be configured.

**Enforcement**: JWT `plan_tier` claim validated server-side on every mutation endpoint. UI gating is a convenience layer, not the security boundary.

---

## 6. Runtime Resolution

### Resolution Order

```
1. tenant.llm_profile_id IS NOT NULL?
   → Use that profile's slot assignments (platform OR BYOLLM)
2. tenant.llm_profile_id IS NULL?
   → Use platform default profile (is_platform_default = true)
3. No platform default exists?
   → Use PLATFORM_DEFAULT_PROFILE_ID env var (hardcoded emergency fallback)
   → NEVER fail-open to no profile
```

No hybrid computation. No tenant slot overrides on top of platform profiles. The profile IS the configuration.

### Three-Tier Cache

```
Every LLM call: InstrumentedLLMClient(slot="chat")
↓
1. Redis: GET mingai:{tenant_id}:llm_profile:effective   [<5ms]
   Hit → use cached EffectiveProfile
   Miss → tier 2
↓
2. Local in-memory LRU per worker [<1ms, 5-min TTL, 1000 entries]
   Hit → use cached EffectiveProfile, refresh Redis
   Miss → tier 3
↓
3. DB query: JOIN tenants → llm_profiles → llm_library    [<50ms]
   Build EffectiveProfile, cache to Redis and local
↓
EffectiveProfile (cached WITHOUT credentials):
  { tenant_id, profile_id, slots: { chat: {library_id, endpoint, model_name, capabilities, params} } }
↓
Fetch api_key_encrypted from DB for resolved Library entry
Decrypt → construct provider client → execute → clear key
```

### Cache Invalidation

| Event                             | Invalidates                                                    |
| --------------------------------- | -------------------------------------------------------------- |
| Tenant selects new profile        | `mingai:{tenant_id}:llm_profile:effective`                     |
| Platform admin updates profile    | All tenants using that profile                                 |
| Platform admin sets new default   | All tenants on old default                                     |
| Library entry updated             | All profiles referencing it → all tenants using those profiles |
| Library entry deprecated/disabled | Same cascade as update                                         |

Emergency flush: platform admin can force-invalidate all tenant caches for a profile immediately (not waiting for TTL).

### Soft Delete Invariant

Library entries are **never hard-deleted**. Status transitions only. This maintains FK integrity and allows graceful degradation: if resolution returns a deprecated entry, the system logs a warning and alerts the platform admin but continues serving. A disabled entry triggers an error and admin alert.

---

## 7. BYOLLM Security Requirements

### Credential Isolation

- BYOLLM Library entries are tenant-owned (`owner_tenant_id = tenant_id`)
- Column-level encryption; tenant-scoped key material
- `api_key_encrypted` NEVER returned in any API response
- Only `api_key_last4` returned (masking)
- Credential rotation endpoint: `PATCH /admin/llm-config/byollm-entries/{id}/rotate-key`

### SSRF Mitigation

Validated server-side before any network call:

1. Domain allowlist: `*.openai.azure.com`, `api.openai.com`, `api.anthropic.com`, `generativelanguage.googleapis.com`, `api.groq.com`
2. IP denylist: RFC 1918 (10.x, 172.16-31.x, 192.168.x), 169.254.x (metadata), localhost, \*.local
3. DNS rebinding protection: resolve hostname → validate resolved IP against denylist

### Tenant Isolation in Resolution

Resolution validates: `owner_tenant_id IS NULL OR owner_tenant_id = requesting_tenant_id`

A BYOLLM entry from Tenant A is never resolvable by Tenant B, even if there is an FK pointing to it.

---

## 8. Capability Validation at Assignment Time

| Check             | Condition                                      | Response                                       |
| ----------------- | ---------------------------------------------- | ---------------------------------------------- |
| Entry status      | `status = 'published'`                         | 422: "Only published entries can be assigned"  |
| Test passed       | `last_test_passed_at IS NOT NULL`              | 422: "Entry must pass connectivity test first" |
| Slot eligibility  | `slot IN capabilities.eligible_slots`          | 422: "Model not eligible for {slot} slot"      |
| Vision gate       | slot=vision AND `supports_vision = false`      | 422: "Vision slot requires multimodal model"   |
| Streaming gate    | slot=chat AND `supports_streaming = false`     | 422: "Chat slot requires streaming support"    |
| Tool calling gate | slot=agent AND `supports_tool_calling = false` | 422: "Agent slot requires function calling"    |

---

## 9. Risk Register (Post-Decisions)

| ID  | Risk                                                  | Mitigation                                                                                                                                          |
| --- | ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | Library entry deprecated while assigned to profiles   | Block deprecation if referenced; offer bulk migration. `deprecated` state still serves.                                                             |
| R2  | Vision slot null; tenant uploads image                | Fall through to default → if default also null: "Vision not configured. Contact admin."                                                             |
| R3  | Redis + local cache both fail                         | DB query as last resort. `PLATFORM_DEFAULT_PROFILE_ID` env var if DB also fails. Never fail-open.                                                   |
| R4  | BYOLLM endpoint goes down                             | Return error to user: "Your custom model endpoint is unavailable." Do NOT silently fall back to platform model (tenant would be surprised by cost). |
| R5  | SSRF via BYOLLM endpoint                              | Domain allowlist + RFC 1918 denylist + DNS rebinding check before any network call.                                                                 |
| R6  | Tenant A reads Tenant B BYOLLM credentials            | `owner_tenant_id` check in resolution + API endpoint authorization.                                                                                 |
| R7  | InstrumentedLLMClient slot refactor misses call sites | `slot` = required parameter (no default). Pre-implementation: enumerate all call sites. Feature flag + canary rollout.                              |
| R8  | Platform admin updates profile; tenants surprised     | In-app notification to affected tenants with before/after diff. Profile history for rollback.                                                       |

---

## 10. Files Requiring Changes

### Schema (fresh start — no migration)

| File                                      | Change                                                                                                        |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `alembic/versions/vNNN_llm_profile_v2.py` | Full rebuild: `llm_library` extensions, new `llm_profiles` v2, `llm_profile_history`, `llm_profile_audit_log` |

### Backend

| File                                         | Change                                                                   |
| -------------------------------------------- | ------------------------------------------------------------------------ |
| `app/modules/llm_profiles/`                  | New module: `service.py`, `routes.py`                                    |
| `app/modules/platform/llm_library/routes.py` | Add capabilities, four-state lifecycle, health check columns             |
| `app/modules/admin/llm_config.py`            | Rewrite: return EffectiveProfile per slot; tenant profile selection only |
| `app/modules/admin/byollm.py`                | Rewrite: BYOLLM = Library entries + Profile owned by tenant              |
| `app/core/llm/instrumented_client.py`        | Add `slot: SlotName` required parameter; three-tier resolution           |
| `app/modules/tenants/routes.py`              | Remove `LLMSlots`, `router`, `worker`, free-text model fields            |

### Frontend

| File                                            | Change                                                                    |
| ----------------------------------------------- | ------------------------------------------------------------------------- |
| `platform/llm-profiles/page.tsx`                | New: Profile list + detail panel                                          |
| `platform/llm-library/elements/LibraryForm.tsx` | Remove slot UI (already done in 53); add capabilities fields              |
| `settings/llm-profile/page.tsx`                 | Rewrite: profile selector (platform track) OR BYOLLM builder (enterprise) |

---

**Document Version**: 2.0 (final)
**All decisions resolved**: D1 ✓ D2 ✓ D3 ✓
**Red Team**: `01-analysis/18-llm-profile/01-redteam-findings.md`
