---
name: mingai-llm-profile-patterns
description: LLM Profile v2 architecture and patterns for mingai. Use when implementing or debugging the platform LLM profile system, BYOLLM tenant selection, AWS Bedrock provider integration, ProfileResolver slot routing, or InstrumentedLLMClient provider resolution.
---

# mingai LLM Profile v2 — Patterns Reference

Introduced in v050 (migration), this is the production-grade multi-provider slot routing system.

---

## Core Concepts

### Slots

Every LLM operation is typed to a slot:

| Slot     | Used For                              | Embedded in                        |
|----------|---------------------------------------|------------------------------------|
| `chat`   | Primary user-facing completions       | ChatOrchestrationService           |
| `intent` | Intent detection (pre-RAG)            | ChatOrchestrationService           |
| `vision` | Multimodal/image analysis             | ChatOrchestrationService (if image)|
| `agent`  | Agent template execution              | agents/routes.py                   |

Embedding (`embed()` path) is NOT slot-routed — always uses the azure_openai fallback.

### Two-Track Profiles

| Track            | `owner_tenant_id` | Who creates it     | Who uses it          |
|------------------|--------------------|--------------------|-----------------------|
| Platform-managed | `NULL`            | Platform admin     | Any eligible tenant   |
| BYOLLM           | = `tenant_id`     | Tenant admin       | That tenant only      |

---

## ProfileResolver (`app/core/llm/profile_resolver.py`)

Three-tier resolution, highest priority first:

```
Tier 1: In-process LRU cache (TTL=60s, max 1000 entries, key: "{tenant_id}:{slot}")
Tier 2: Redis (key: mingai:{tenant_id}:llm_profile, TTL=300s)
Tier 3: PostgreSQL — precedence:
         1. tenants.llm_profile_id (explicit assignment)
         2. BYOLLM profile (owner_tenant_id = tenant_id)
         3. Platform default (is_platform_default=true, plan tier matches)
```

**Feature flag**: `LLM_PROFILE_SLOT_ROUTING=1` must be set. When `0`/absent, resolver returns `None` and the caller falls back to `PRIMARY_MODEL` env var. This allows gradual rollout without code changes.

```python
from app.core.llm.profile_resolver import ProfileResolver, _slot_routing_enabled

resolver = ProfileResolver(db, redis)
profile = await resolver.resolve(tenant_id, slot="chat")
# Returns ResolvedProfile(library_entry_id, model_name, provider, endpoint_url, ...)
# Returns None if flag disabled or no profile found
```

---

## InstrumentedLLMClient — Provider Dispatch

`app/core/llm/instrumented_client.py` resolves the provider at call time:

```python
# Provider → Client mapping (simplified)
"azure_openai"  → AzureOpenAI (azure_endpoint + api_key + api_version)
"openai_direct" → OpenAI (api_key)
"anthropic"     → Anthropic (api_key)
"bedrock"       → AsyncOpenAI(api_key=bearer_token, base_url=f"{endpoint}/v1")
```

**Bedrock specifics** (BEDROCK-008):
```python
from openai import AsyncOpenAI
# endpoint_url: stored in llm_library.endpoint_url (e.g. https://bedrock-runtime.us-east-1.amazonaws.com)
# api_key: decrypted AWS bearer token (from llm_library.api_key_encrypted)
# model: full ARN passed at call time
client = AsyncOpenAI(
    api_key=decrypted_key,
    base_url=f"{endpoint_url.rstrip('/')}/v1",
)
# MUST call _assert_endpoint_ssrf_safe(endpoint_url) BEFORE instantiation
# MUST zero the key: decrypted_key = "" in finally block
```

Bedrock falls back to azure_openai for embed() — it does NOT support the embeddings path.

---

## AWS Bedrock Provider — Schema

Bedrock reuses existing `llm_library` columns without any schema additions:

| Column               | Bedrock usage                                     |
|----------------------|---------------------------------------------------|
| `provider`           | `'bedrock'` (v051 expanded CHECK constraint)      |
| `endpoint_url`       | Bedrock runtime endpoint, e.g. `https://bedrock-runtime.ap-southeast-1.amazonaws.com` |
| `api_key_encrypted`  | AWS bearer token (Fernet-encrypted)              |
| `api_key_last4`      | Last 4 chars of bearer token (display)           |
| `model_name`         | Full ARN or short model ID (max 200 chars)        |
| `display_name`       | Human-readable label (e.g. "Claude 3.5 Bedrock") |

**SSRF guard**: `_assert_endpoint_ssrf_safe(url)` validates:
- Scheme must be `https`
- Blocks RFC-1918 ranges (10.x, 172.16-31.x, 192.168.x)
- Blocks `.internal`, `.local`, `localhost`, `127.x` hostnames

**No ARN prefix validation** (ADR-5): model_name accepts any non-empty string ≤ 200 chars. The Bedrock API itself will reject invalid ARNs.

---

## Backend API Reference

### Platform Admin

| Endpoint                                          | Method | Description                               |
|---------------------------------------------------|--------|-------------------------------------------|
| `/api/v1/platform/llm-profiles`                   | GET    | List all profiles (paginated)             |
| `/api/v1/platform/llm-profiles`                   | POST   | Create profile (name, description, plan_tiers) |
| `/api/v1/platform/llm-profiles/{id}`             | GET    | Detail with slot assignments              |
| `/api/v1/platform/llm-profiles/{id}`             | PATCH  | Update name / description / plan_tiers    |
| `/api/v1/platform/llm-profiles/{id}/slots`       | POST   | Assign slot: `{slot, library_entry_id}`   |
| `/api/v1/platform/llm-profiles/{id}/set-default` | POST   | Mark as platform default (clears others)  |
| `/api/v1/platform/llm-profiles/{id}`             | DELETE | Deprecate — 409 if active tenants exist   |

### Tenant Admin (BYOLLM)

| Endpoint                                    | Method | Description                                   |
|---------------------------------------------|--------|-----------------------------------------------|
| `/api/v1/admin/llm-config`                  | GET    | Read current effective LLM config             |
| `/api/v1/admin/llm-config/select-profile`   | POST   | Select a platform-managed profile             |

⚠️ `PATCH /api/v1/admin/llm-config` was **REMOVED** in LLM Profile v2 (returns 405). Do not reference it in tests or code.

---

## Frontend Patterns

### `usePlatformLLMProfiles.ts`

```typescript
import { useProfileList } from "@/lib/hooks/usePlatformLLMProfiles";
const { data, isPending } = useProfileList();
// data.profiles: PlatformProfile[]
// PlatformProfile.slots: Record<ProfileSlot, SlotAssignment | null>
// PlatformProfile.plan_tiers: string[] (e.g. ["professional", "enterprise"])
// PlatformProfile.is_platform_default: boolean
```

### `useLLMProfileConfig.ts` (Tenant)

```typescript
import { useEffectiveProfile } from "@/lib/hooks/useLLMProfileConfig";
const { data, isPending, error } = useEffectiveProfile();
// data.profile_name, data.slots (slot → {model_name, provider})
// error.message = "Tenant admin role required." when accessed without tenant_admin scope
```

### Profile Wizard (2-step)

Step 1: `name` (required) + `description` + `plan_tiers` (pill multi-select: starter/professional/enterprise)
Step 2: Slot assignment overview — slots are assigned AFTER creation via ProfileDetailPanel

```tsx
// Pill selector pattern for plan tiers
const PLAN_TIERS = ["starter", "professional", "enterprise"] as const;
const [selectedTiers, setSelectedTiers] = useState<string[]>(["professional", "enterprise"]);

<button
  className={cn(
    "rounded-control border px-3 py-1.5 text-body-default",
    selectedTiers.includes(tier)
      ? "border-accent bg-accent-dim text-accent"
      : "border-border bg-bg-elevated text-text-muted"
  )}
  onClick={() => toggleTier(tier)}
>
  {capitalize(tier)}
</button>
```

### TemplateStudioPanel — Tab Extension

To add a new tab, make exactly 3 changes:

```typescript
// 1. Add to the type union
type StudioTab = "edit" | "test" | "instances" | "versions" | "performance" | "my-new-tab";

// 2. Add to the TABS array (controls render order)
const TABS = [
  ...
  { value: "my-new-tab" as StudioTab, label: "My New Tab" },
];

// 3. Add the conditional render block after existing tab renders
{activeTab === "my-new-tab" && template && (
  <MyNewTab templateId={template.id} />
)}
```

---

## Migration Notes

### v050 Status Values

After v050, `llm_library.status` CHECK constraint is lowercase only:

```sql
-- WRONG (pre-v050, will now violate constraint):
INSERT INTO llm_library (status) VALUES ('Published');

-- CORRECT (post-v050):
INSERT INTO llm_library (status) VALUES ('published');
-- Valid values: 'published', 'draft', 'deprecated', 'disabled'
```

This also affects the RLS policy:
```sql
-- Old (pre-v050): status = 'Published'
-- New (post-v050): status = 'published'
```

### `llm_profiles` Table Rebuild (v050)

The v050 migration **drops and recreates** `llm_profiles`. The old schema (single model reference per profile) is gone. The new schema has 4 slot FK columns:

```sql
llm_profiles (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  owner_tenant_id UUID,           -- NULL = platform-managed, else = BYOLLM
  is_platform_default BOOLEAN,    -- unique partial index (only one per non-null is_platform_default)
  plan_tiers TEXT[],              -- ['starter', 'professional', 'enterprise']
  chat_library_id UUID REFERENCES llm_library(id),
  intent_library_id UUID REFERENCES llm_library(id),
  vision_library_id UUID REFERENCES llm_library(id),
  agent_library_id UUID REFERENCES llm_library(id),
  status TEXT CHECK (status IN ('active', 'draft', 'deprecated')),
  ...
)
```
