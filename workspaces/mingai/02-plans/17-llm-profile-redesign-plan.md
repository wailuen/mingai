# LLM Profile Redesign — Implementation Plan (Final)

**Date**: 2026-03-22 (revised post-decisions)
**Research**: `01-research/55-llm-profile-redesign-analysis.md`
**Status**: Final — clean rebuild, no migration from legacy data

---

## Design Decisions (Locked)

| Decision          | Resolution                                                                |
| ----------------- | ------------------------------------------------------------------------- |
| Profile ownership | Platform admin creates; tenants select whole profile — no slot mixing     |
| BYOLLM scope      | Per-slot, fully separate track. Platform profiles are default path.       |
| Launch profiles   | Fully platform-admin-configurable — no hardcoded profiles, no seeded data |

## Two Tracks, Zero Mixing

```
Track 1 (Platform): tenant.llm_profile_id → platform-owned profile (owner_tenant_id IS NULL)
Track 2 (BYOLLM):   tenant.llm_profile_id → tenant-owned profile  (owner_tenant_id = tenant_id)
```

No hybrid. No tenant slot overrides on top of platform profiles. Profile IS the configuration.

---

## Phase A — Schema (Sprint 1 — 2 days)

**Goal**: Clean schema in place. Fresh start — no migration from legacy `llm_profiles` data.

### A1. Extend `llm_library`

```sql
ALTER TABLE llm_library
    ADD COLUMN capabilities        JSONB DEFAULT '{}',
    ADD COLUMN health_status       VARCHAR(50) DEFAULT 'unknown'
                                   CHECK (health_status IN ('healthy','degraded','unknown')),
    ADD COLUMN health_checked_at   TIMESTAMPTZ,
    ADD COLUMN is_byollm           BOOLEAN DEFAULT false,
    ADD COLUMN owner_tenant_id     UUID REFERENCES tenants(id);

-- Four-state lifecycle (replace two-state)
ALTER TABLE llm_library
    DROP CONSTRAINT llm_library_status_check,
    ADD CONSTRAINT llm_library_status_check
        CHECK (status IN ('draft','published','deprecated','disabled'));
```

### A2. Rebuild `llm_profiles`

Drop and recreate (no data worth migrating):

```sql
DROP TABLE IF EXISTS llm_profiles CASCADE;

CREATE TABLE llm_profiles (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 VARCHAR(255) NOT NULL,
    description          VARCHAR(1000),
    status               VARCHAR(50) DEFAULT 'active'
                         CHECK (status IN ('active', 'deprecated')),

    -- Slot assignments
    chat_library_id      UUID REFERENCES llm_library(id),
    intent_library_id    UUID REFERENCES llm_library(id),
    vision_library_id    UUID REFERENCES llm_library(id),
    agent_library_id     UUID REFERENCES llm_library(id),

    -- Per-slot parameters
    chat_params          JSONB DEFAULT '{}',
    intent_params        JSONB DEFAULT '{}',
    vision_params        JSONB DEFAULT '{}',
    agent_params         JSONB DEFAULT '{}',

    -- Traffic splitting (A/B model testing, Enterprise)
    chat_traffic_split   JSONB DEFAULT '[]',
    intent_traffic_split JSONB DEFAULT '[]',
    vision_traffic_split JSONB DEFAULT '[]',
    agent_traffic_split  JSONB DEFAULT '[]',

    -- Extensibility
    custom_slots         JSONB DEFAULT '{}',

    -- Availability
    is_platform_default  BOOLEAN DEFAULT false,
    plan_tiers           TEXT[] DEFAULT '{}',

    -- BYOLLM: null = platform-owned; tenant_id = BYOLLM
    owner_tenant_id      UUID REFERENCES tenants(id),

    created_by           UUID,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (name, owner_tenant_id)  -- unique per scope (platform / per tenant)
);

-- Only one platform default
CREATE UNIQUE INDEX uq_llm_profiles_platform_default
    ON llm_profiles ((true))
    WHERE is_platform_default = true AND owner_tenant_id IS NULL;
```

### A3. Supporting Tables

```sql
CREATE TABLE llm_profile_history (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id    UUID NOT NULL REFERENCES llm_profiles(id) ON DELETE CASCADE,
    slot_snapshot JSONB NOT NULL,
    changed_by    UUID,
    changed_at    TIMESTAMPTZ DEFAULT NOW(),
    change_reason TEXT
);

CREATE TABLE llm_profile_audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(50),
    entity_id   UUID,
    action      VARCHAR(50),
    actor_id    UUID,
    tenant_id   UUID,
    diff        JSONB,
    ip_address  INET,
    logged_at   TIMESTAMPTZ DEFAULT NOW()
);
```

### A4. Tenant Assignment Column

```sql
-- Already exists; ensure references new llm_profiles table
ALTER TABLE tenants
    DROP CONSTRAINT IF EXISTS tenants_llm_profile_id_fkey,
    ADD CONSTRAINT tenants_llm_profile_id_fkey
        FOREIGN KEY (llm_profile_id) REFERENCES llm_profiles(id);
```

**DOWN migration**: Full schema rollback script (restore original `llm_profiles`, drop new tables).

**Phase A tests**:

- Schema integrity: all FKs and constraints in place
- Unique index: cannot create two platform defaults
- Unique name: `(name, owner_tenant_id)` uniqueness enforced
- Status check: invalid status values rejected

---

## Phase B — Backend Services (Sprint 2 — 5 days)

**Goal**: Slot-aware runtime. Platform profile CRUD. BYOLLM as separate track. All security gates in place.

### B0. Pre-implementation: Call-Site Enumeration (required gate)

Before touching `InstrumentedLLMClient`:

```bash
grep -r "InstrumentedLLMClient" src/backend --include="*.py"
grep -r "get_openai_client\|get_intent_openai_client\|get_doc_openai_client" src/backend --include="*.py"
```

Document every call site. Make `slot` a **required parameter** (no default value). Every missed call site becomes a type error, not a silent runtime bug.

### B1. SSRF Validation Middleware (`app/core/security/url_validator.py`)

```python
ALLOWED_DOMAINS = [
    r".*\.openai\.azure\.com$",
    r"api\.openai\.com$",
    r"api\.anthropic\.com$",
    r"generativelanguage\.googleapis\.com$",
    r"api\.groq\.com$",
]
PRIVATE_RANGES = [
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "127.0.0.0/8", "::1/128",
]

def validate_llm_endpoint(url: str) -> None:
    """Raises ValueError for disallowed endpoints. Called before any network contact."""
    # 1. Domain allowlist check
    # 2. RFC 1918 denylist
    # 3. DNS resolve → validate resolved IP against private ranges
```

Implemented BEFORE any BYOLLM endpoint is live.

### B2. `LLMProfileService` (`app/modules/llm_profiles/service.py`)

```python
class LLMProfileService:
    # Platform profile management (platform admin)
    async def create_profile(self, req: CreateProfileRequest, actor_id: UUID) -> LLMProfile
    async def update_profile(self, profile_id: UUID, req: UpdateProfileRequest, actor_id: UUID) -> LLMProfile
    async def assign_slot(self, profile_id: UUID, slot: SlotName, library_id: UUID, params: dict) -> None
    async def set_platform_default(self, profile_id: UUID, actor_id: UUID) -> None
    async def deprecate_profile(self, profile_id: UUID) -> None  # blocked if tenants using it
    async def list_platform_profiles(self, plan_tier: Optional[str] = None) -> list[LLMProfile]

    # Tenant profile management
    async def select_profile(self, tenant_id: UUID, profile_id: UUID, actor_id: UUID) -> None
    async def get_effective_profile(self, tenant_id: UUID) -> EffectiveProfile

    # BYOLLM profile management (Enterprise tenant)
    async def create_byollm_profile(self, tenant_id: UUID, req: CreateBYOLLMProfileRequest) -> LLMProfile
    async def update_byollm_slot(self, tenant_id: UUID, profile_id: UUID, slot: SlotName, library_id: UUID) -> None
    async def activate_byollm_profile(self, tenant_id: UUID, profile_id: UUID) -> None

    # Internal
    async def _compute_effective_profile(self, tenant_id: UUID) -> EffectiveProfile
    async def _write_history(self, profile_id: UUID, changed_by: UUID, reason: str) -> None
    async def _write_audit(self, entity_id: UUID, action: str, actor_id: UUID, diff: dict) -> None
    async def _invalidate_cache(self, tenant_ids: list[UUID]) -> None
```

### B3. Three-Tier Profile Resolution (`app/core/llm/profile_resolver.py`)

```python
class ProfileResolver:
    async def resolve(self, tenant_id: UUID) -> EffectiveProfile:
        # Tier 1: Redis
        cached = await self._redis_get(tenant_id)
        if cached: return cached

        # Tier 2: Local in-memory LRU (max 1000 entries, 5-min TTL)
        local = self._local_cache.get(tenant_id)
        if local:
            await self._redis_set(tenant_id, local)  # refresh Redis
            return local

        # Tier 3: DB
        profile = await self._db_resolve(tenant_id)
        await self._redis_set(tenant_id, profile)
        self._local_cache.set(tenant_id, profile)
        return profile

    async def _db_resolve(self, tenant_id: UUID) -> EffectiveProfile:
        # 1. tenant.llm_profile_id IS NOT NULL → use that profile
        # 2. IS NULL → use platform default (is_platform_default=true AND owner_tenant_id IS NULL)
        # 3. No default → use PLATFORM_DEFAULT_PROFILE_ID env var
        # 4. NEVER return None — raise ProfileResolutionError with clear message

    def validate_tenant_ownership(self, tenant_id: UUID, profile: EffectiveProfile) -> None:
        """Ensures BYOLLM entries belong to this tenant."""
        for slot in profile.slots.values():
            if slot.is_byollm and slot.owner_tenant_id != tenant_id:
                raise SecurityError(f"Cross-tenant slot access denied")
```

Feature flag: `LLM_PROFILE_SLOT_ROUTING=false` (default). When false, falls back to legacy single-model resolution. Enables canary rollout per tenant.

### B4. Slot-Aware `InstrumentedLLMClient`

```python
# BEFORE (broken):
async def _resolve_adapter(self, tenant_id: UUID) -> LLMAdapter:
    # returns one hardcoded "primary" model

# AFTER (correct):
async def _resolve_adapter(self, tenant_id: UUID, slot: SlotName) -> LLMAdapter:
    # slot is REQUIRED — no default value
    profile = await self._resolver.resolve(tenant_id)
    resolved_slot = profile.slots[slot]
    key = await self._fetch_and_decrypt_key(resolved_slot.library_id)
    try:
        return self._build_adapter(resolved_slot, key)
    finally:
        key = ""  # always clear
```

Remove hardcoded `auxiliary_operations` routing from `ModelRegistry`. Route by `slot` parameter instead.

### B5. Platform Profile API (`app/modules/llm_profiles/routes.py`)

```
GET    /platform/llm-profiles                          — list all profiles
POST   /platform/llm-profiles                          — create profile
GET    /platform/llm-profiles/{id}                     — detail with slot info
PATCH  /platform/llm-profiles/{id}                     — update name/description/plan_tiers
PUT    /platform/llm-profiles/{id}/slots               — assign all slots (atomic)
PATCH  /platform/llm-profiles/{id}/slots/{slot}        — assign single slot
DELETE /platform/llm-profiles/{id}/slots/{slot}        — unassign slot
POST   /platform/llm-profiles/{id}/set-default         — make platform default
DELETE /platform/llm-profiles/{id}                     — deprecate (blocked if tenants active)
POST   /platform/llm-profiles/{id}/test                — test all slots with canned prompt
GET    /platform/llm-profiles/{id}/tenants             — list tenants using this profile
GET    /platform/llm-profiles/available-models/{slot}  — library entries eligible for slot
```

Slot assignment validation: published + test passed + slot eligibility + capability gates.
Every mutation: write to `llm_profile_history` and `llm_profile_audit_log`.
Tier enforcement: `platform_admin` role required on all endpoints.

### B6. Tenant Admin API (`app/modules/admin/llm_config.py` — rewrite)

```
GET    /admin/llm-config                               — EffectiveProfile per slot (resolved)
GET    /admin/llm-config/available-profiles            — profiles available for tenant's plan tier
POST   /admin/llm-config/select-profile                — select a platform profile (plan-tier gated)
```

No slot override endpoints. No BYOLLM endpoints here — BYOLLM has its own module.
Tier enforcement: middleware validates JWT `plan_tier` claim on `select-profile`.

### B7. BYOLLM API (`app/modules/admin/byollm/routes.py` — rewrite)

```
# Library entry management
GET    /admin/byollm/library-entries                   — list tenant's BYOLLM entries
POST   /admin/byollm/library-entries                   — create entry (Enterprise only)
PATCH  /admin/byollm/library-entries/{id}              — update metadata (not credentials)
PATCH  /admin/byollm/library-entries/{id}/rotate-key   — rotate API key (credential update)
POST   /admin/byollm/library-entries/{id}/test         — connectivity test
DELETE /admin/byollm/library-entries/{id}              — delete (blocked if assigned to active profile)

# Profile management
GET    /admin/byollm/profiles                          — list tenant's BYOLLM profiles
POST   /admin/byollm/profiles                          — create BYOLLM profile
PATCH  /admin/byollm/profiles/{id}/slots/{slot}        — assign library entry to slot
POST   /admin/byollm/profiles/{id}/activate            — activate (requires all 3 required slots assigned + tested)
DELETE /admin/byollm/profiles/{id}                     — delete profile
```

BYOLLM profile activation requirements: `chat`, `intent`, and `agent` slots must be assigned and tested. `vision` is optional.

SSRF validation on all `endpoint_url` fields before any DB write.
Credentials: write-only (`api_key_encrypted` never in responses; only `api_key_last4`).

### B8. Plan Tier Middleware

```python
@require_plan_tier(minimum="enterprise")
async def create_byollm_entry(...): ...

@require_plan_tier(minimum="professional")
async def select_profile(...): ...
```

Server-side enforcement on every mutation. Integration tests cover all tier bypass attempts.

**Phase B tests**:

Security:

- `test_tier_bypass_starter.py` — Starter cannot call `select-profile`
- `test_tier_bypass_professional.py` — Professional cannot access any BYOLLM endpoint
- `test_byollm_cross_tenant_isolation.py` — Tenant A cannot read Tenant B's entries
- `test_ssrf_domain_allowlist.py` — only approved domains pass
- `test_ssrf_private_ip.py` — RFC 1918 rejected before network call
- `test_ssrf_dns_rebinding.py` — hostname resolving to private IP rejected
- `test_credential_never_returned.py` — GET on any endpoint never includes `api_key_encrypted`

Resolution:

- `test_resolution_platform_profile.py` — tenant on platform profile resolves correctly
- `test_resolution_byollm_profile.py` — BYOLLM tenant resolves their own entries
- `test_resolution_default_fallback.py` — null `llm_profile_id` → platform default
- `test_resolution_redis_failure.py` — Redis down → local cache → DB, never fail-open
- `test_resolution_null_slot.py` — null vision slot → fall back to default → graceful error if default also null
- `test_cache_invalidation_on_profile_update.py`
- `test_cache_invalidation_on_library_deprecate.py`

Profile integrity:

- `test_slot_assignment_validation.py` — capability gate per slot
- `test_profile_deprecation_blocked_if_active.py`
- `test_byollm_activation_requires_required_slots.py`
- `test_concurrent_profile_update.py` — no silent data loss

---

## Phase C — Platform Admin Frontend (Sprint 3 — 3 days)

**Goal**: Platform admin can build and publish LLM Profiles from the UI.

### C1. Navigation

Add **LLM Profiles** to Platform sidebar under Intelligence section, below LLM Library.

### C2. LLM Profiles Page

```
/platform/llm-profiles
└── ProfileListTable
    Columns: Name | Chat | Intent | Vision | Agent | Plan Tiers | Tenants | Status
    └── ProfileDetailPanel (slide-in, 480px)
        ├── ProfileIdentitySection    (name, description)
        ├── SlotAssignmentSection     (4 slot selectors + params)
        ├── PlanAvailabilitySection   (plan tier checkboxes)
        ├── TenantUsageSection        (count + list)
        └── TestProfileSection        (fire test prompts through all slots)
```

### C3. SlotSelector Component (`platform/llm-profiles/elements/SlotSelector.tsx`)

- Fetches `GET /platform/llm-profiles/available-models/{slot}`
- Searchable dropdown filtered by `eligible_slots` capability
- Each option: model name (DM Mono) + provider badge + health status dot + test age
- Deprecation warning inline when deprecated entry selected
- Empty state: links to LLM Library to add entries first

### C4. "Test This Profile" Panel Section

- Sends canned prompts through each configured slot in parallel
- Shows per-slot: model name, latency (DM Mono), token count, response snippet
- Vision slot: sends a sample image
- Only enabled when all required slots are assigned

### C5. LLM Library Form Cleanup

Remove remaining slot UI from `LibraryForm.tsx` (SLOT_KEYS, SlotFormState, etc.).
Add capabilities JSON editor for platform admins.
Add health status display.

**Phase C tests**:

- E2E: Create profile → assign all slots → verify list shows slot names
- E2E: Slot dropdown shows only eligible models per slot type
- E2E: Cannot assign unpublished entry
- E2E: Set platform default → previous default loses indicator
- E2E: Test Profile → results appear per slot

---

## Phase D — Tenant Admin Frontend (Sprint 4 — 3 days)

**Goal**: Tenant admin can select a platform profile or configure BYOLLM.

### D1. Settings > LLM Profile Page

Three distinct experiences based on plan + track:

**Starter**:

- Read-only: shows active profile name + description + slot model names
- Embedding slots shown as read-only informational rows
- Plan gate card: "Upgrade to Professional to choose from additional profiles"

**Professional**:

- Profile selector dropdown (shows profiles available for Professional)
- Each option shows: name, description, estimated cost/1K queries
- Selected profile shows per-slot model names (read-only — they selected the whole profile)
- Vision + Agent slots: visible as read-only, "Enterprise" badge, upgrade link
- [Save] with confirmation dialog

**Enterprise (Platform Profile track)**:

- Full profile selector (all profiles)
- Prominent "Advanced: Bring Your Own LLM" section below
- All 4 slots read-only (profile determines them)
- Visible slot values with "Enterprise" upgrade context removed

**Enterprise (BYOLLM track)**:

- Shows BYOLLM profile is active
- Per-slot: entry name (DM Mono) + provider + last test timestamp + [Re-test]
- [Edit BYOLLM Configuration] → full BYOLLM builder

### D2. BYOLLM Configuration Flow

Accessible under Settings > LLM Profile > Advanced > Configure Custom Models

1. **Acknowledgement gate**: "You are responsible for availability, cost, and performance of your endpoints. Platform SLAs do not apply to custom model endpoints." → [I understand, continue]

2. **Library entry management**: per-slot cards:

   ```
   CHAT SLOT
   ┌─────────────────────────────────────────────┐
   │ Not configured                              │
   │ [Add Model Endpoint]                        │
   └─────────────────────────────────────────────┘
   ```

   After adding:

   ```
   CHAT SLOT
   ┌─────────────────────────────────────────────┐
   │ my-gpt5-prod         Azure OpenAI  ✓ 2h ago │
   │ https://contoso.openai.azure.com/   ••••1234 │
   │ [Re-test]  [Edit]  [Remove]                 │
   └─────────────────────────────────────────────┘
   ```

3. **Profile activation**: [Activate Custom Profile] button enabled only when Chat, Intent, and Agent slots are configured and tested.

4. **Switch back**: [Use Platform Profile] → select from platform profiles, confirms deactivating BYOLLM.

### D3. Add Model Endpoint Modal (per slot)

Fields conditional on provider:

- Provider: [Azure OpenAI | OpenAI | Anthropic | Google]
- Endpoint URL (Azure only)
- API Key (password field, write-only after save)
- API Version (Azure only)
- Deployment / Model name

[Test Connection] → inline result with latency, model name, capability confirmation.
SSRF validation fires before any network call. Private IP → immediate error, no network contact.

**Phase D tests**:

- E2E: Starter → read-only, no selector visible
- E2E: Professional → profile selector shows eligible profiles, locked slots visible with badge
- E2E: Enterprise → BYOLLM acknowledgement gate → add per-slot entry → test → activate
- E2E: Private IP endpoint → rejected immediately
- E2E: Wrong API key → 401 error in plain language
- E2E: Switch from BYOLLM back to platform profile

---

## Phase E — Health Monitoring (Sprint 5 — 2 days)

**Goal**: Platform admin knows when a Library entry becomes unhealthy.

### E1. Background Health Check Job

- Runs every 24h via APScheduler/Celery
- For each `published` Library entry with `last_test_passed_at IS NOT NULL`:
  - Send lightweight connectivity probe (not completion, not stored)
  - On success: update `health_checked_at`, set `health_status = 'healthy'`
  - On failure: set `health_status = 'degraded'`, create platform admin notification
- Probe stores only: HTTP status, latency_ms, error_message (truncated 200 chars). Never response body.

### E2. Health Status in UI

- Library list: health dot (accent=healthy, alert=degraded, warn=unknown) per row
- Profile detail: degraded slot shows warn indicator + "This model reported issues 3h ago"
- Platform admin notification: in-app banner + email with affected profile count

**Phase E tests**:

- Unit: health check uses entry credentials, not env vars
- Unit: degraded entry triggers notification, does NOT auto-deprecate
- Integration: degraded entry shows warn state in profile detail

---

## Sprint Summary

| Sprint | Phase                 | Duration | Deliverable                                                        |
| ------ | --------------------- | -------- | ------------------------------------------------------------------ |
| 1      | A — Schema            | 2 days   | Clean schema: library extensions, profiles v2, history, audit log  |
| 2      | B — Backend           | 5 days   | Slot-aware runtime, profile CRUD, BYOLLM track, all security gates |
| 3      | C — Platform Admin UI | 3 days   | Profile list + detail, slot selectors, test panel                  |
| 4      | D — Tenant Admin UI   | 3 days   | Profile selector (3 tiers), BYOLLM builder (Enterprise)            |
| 5      | E — Health Monitoring | 2 days   | 24h health checks, degraded alerts                                 |

**Total: 15 working days (3 weeks)**

## Sequencing

```
Phase A → Phase B → Phase C + D (parallel) → Phase E (parallel with C+D)
```

Phase B gates everything. Feature flag `LLM_PROFILE_SLOT_ROUTING=false` enables safe rollout — old single-model resolution remains active until flag is enabled per tenant.

## Rollback Procedures

| Phase | Rollback                                                                           |
| ----- | ---------------------------------------------------------------------------------- |
| A     | DOWN migration restores original schema                                            |
| B     | Set `LLM_PROFILE_SLOT_ROUTING=false` → reverts to legacy resolution without deploy |
| C/D   | Revert UI deploy — no schema impact                                                |
| E     | Disable background job via config — no schema impact                               |

---

**Document Version**: 2.0 (final)
**All decisions resolved**: D1 ✓ D2 ✓ D3 ✓
