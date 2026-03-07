# 13-04 — Implementation Alignment: aihub2 → mingai

**Focus**: How to adapt the aihub2 profile/memory system to mingai's multi-tenant, multi-agent architecture.
**Key differences**: Single-tenant → Multi-tenant; Single-agent → Multi-agent registry; CosmosDB → Cloud-agnostic PostgreSQL+Redis

---

## 1. Critical Architecture Differences

### 1.1 Database: CosmosDB → PostgreSQL (Cloud-Agnostic)

**aihub2**: Uses CosmosDB `user_profiles` container for persistent profile storage.

**mingai**: PostgreSQL via Kailash DataFlow. Profile data maps naturally to relational schema.

| aihub2 Field                      | mingai Table/Column                     | Notes                         |
| --------------------------------- | --------------------------------------- | ----------------------------- |
| `user_profiles.id` (user_id)      | `user_profiles.user_id` FK → `users.id` | Add `tenant_id` scope         |
| `user_profiles.interests[]`       | `user_profiles.interests JSONB`         | PostgreSQL JSONB array        |
| `user_profiles.memory_notes[]`    | `memory_notes` table (separate)         | Normalized for efficient CRUD |
| `user_profiles.technical_level`   | `user_profiles.technical_level VARCHAR` | Enum-backed                   |
| `user_profiles.learning_events[]` | `profile_learning_events` table         | Normalized audit trail        |

**Key change**: Memory notes should be a SEPARATE table in mingai (not embedded in the profile document). This enables:

- Efficient `DELETE /memory/{note_id}` without full document rewrite
- Agent-scoped notes without full profile rewrite
- Better indexing on `created_at` for newest-first queries

### 1.2 Multi-Tenant Key Scoping

All Redis keys MUST be scoped by `tenant_id`:

| aihub2 Key                               | mingai Key                                           |
| ---------------------------------------- | ---------------------------------------------------- |
| `profile_learning:query_count:{user_id}` | `{tenant_id}:profile_learning:query_count:{user_id}` |
| `profile_learning:profile:{user_id}`     | `{tenant_id}:profile_learning:profile:{user_id}`     |
| `working_memory:{user_id}`               | `{tenant_id}:working_memory:{user_id}:{agent_id}`    |

The `{tenant_id}` prefix MUST come first for efficient Redis key-space management and tenant isolation.

### 1.3 Multi-Agent Scoping (New in mingai)

aihub2 has a single agent per tenant. mingai has a multi-agent registry. Profile/memory must be agent-aware.

**Working memory**: Should be scoped to `{tenant_id}:{user_id}:{agent_id}` for agent-specific session continuity.

**Profile learning**: The core profile (technical_level, communication_style) should remain global — these don't change per agent. But `interests`, `common_tasks`, and `memory_notes` should be optionally agent-scoped.

**Proposed scoping model**:

```
Global profile (cross-agent): technical_level, communication_style, org_context
Agent-scoped profile: interests[], common_tasks[], specific memory_notes[]
Working memory: always agent-scoped (different agents = different task contexts)
```

Implementation: Add `agent_id` field to `ProfileLearningEvent`, `MemoryNote`, and `working_memory` Redis key. Pass `agent_id` from the chat request through the profile learning pipeline.

### 1.4 Org Context: Azure AD Only → SSO-Agnostic

**aihub2**: Hardcoded to Azure AD (MSGraph API).

**mingai**: Cloud-agnostic platform supports Okta, Azure AD, Google Workspace, and custom LDAP.

**Adaptation**:

- Create `OrgContextSource` abstraction with implementations:
  - `AzureADOrgContextSource`
  - `OktaOrgContextSource`
  - `GenericSAMLOrgContextSource` (falls back to SAML attributes)
- All sources must produce the same normalized `OrgContextData`:
  ```python
  class OrgContextData(BaseModel):
      job_title: Optional[str]
      department: Optional[str]
      country: Optional[str]
      company: str
      manager_name: Optional[str]
  ```
- Source selection configured per-tenant in tenant settings

### 1.5 Learning Model: GPT-4.1-mini → Tenant LLM Profile

**aihub2**: Uses `get_intent_openai_client()` (GPT-4.1-mini, fixed).

**mingai**: Tenants have configurable LLM profiles (doc 21: LLM model slot analysis). Profile learning should use the tenant's configured `intent` slot model, not a hardcoded model.

**Risk**: If tenant configures a weaker intent model, profile extraction quality degrades.
**Mitigation**: Profile learning should have a minimum model quality check. If tenant's intent model is below threshold (e.g., context window < 16K), use platform default.

---

## 2. Data Model (mingai PostgreSQL)

```sql
-- Core profile (global per user per tenant)
CREATE TABLE user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    technical_level VARCHAR(20),      -- beginner/intermediate/expert
    communication_style VARCHAR(20),   -- concise/detailed/formal/casual
    interests JSONB DEFAULT '[]',
    expertise_areas JSONB DEFAULT '[]',
    common_tasks JSONB DEFAULT '[]',
    profile_learning_enabled BOOLEAN DEFAULT true,
    org_context_enabled BOOLEAN DEFAULT true,
    share_manager_info BOOLEAN DEFAULT true,
    query_count INTEGER DEFAULT 0,  -- durable checkpoint; Redis hot counter writes back here every 10 queries
    last_learned_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, user_id)
);

-- Memory notes (normalized, agent-scopable)
CREATE TABLE memory_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,  -- NULL = global
    content TEXT NOT NULL,
    source VARCHAR(20) NOT NULL,  -- user_directed / auto_extracted
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_memory_notes_user ON memory_notes(tenant_id, user_id, created_at DESC);

-- Profile learning audit trail
CREATE TABLE profile_learning_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,
    extracted_attributes JSONB,
    conversations_analyzed INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 3. Redis Key Architecture (mingai)

```
# Working memory (agent-scoped)
{tenant_id}:working_memory:{user_id}:{agent_id}
TTL: 7 days (configurable 1-30 days by tenant admin)

# Profile query counter (sync to PostgreSQL every 10 queries)
{tenant_id}:profile_learning:query_count:{user_id}
TTL: 30 days (auto-reset on learning trigger)
# Phase 1: global counter (cross-agent). Phase 2: switch to `{user_id}:{agent_id}` when agent-scoped learning is enabled.

# Profile L2 cache
{tenant_id}:profile_learning:profile:{user_id}
TTL: 1 hour

# Org context cache (new optimization vs aihub2)
{tenant_id}:org_context:{user_id}
TTL: 24 hours (invalidated on login)
```

---

## 3a. query_count Sync Strategy

Two-layer counter design:

- Redis (hot): `{tenant_id}:profile_learning:query_count:{user_id}` — fast increment per query, TTL 30 days
- PostgreSQL (checkpoint): `user_profiles.query_count` — written when Redis counter reaches 10 (triggers learning job)

Write-back flow:

1. Every query: INCR Redis counter (atomic, no DB hit)
2. When Redis counter = 10: trigger learning job → write `query_count += 10` to PostgreSQL → reset Redis counter to 0
3. On Redis cache miss (key evicted): read `user_profiles.query_count` from PostgreSQL → seed Redis counter → continue

This ensures infrequent users (e.g., 9 queries over 25 days, key expires) do not lose their accumulated count.

---

## 4. System Prompt Layer Stack (mingai)

Updated 7-layer stack for mingai, with agent-scoping adjustment and canonical token budget:

```
Layer 0:  Agent base prompt (agent-specific, from tenant admin config)
Layer 1:  Platform base (universal standards, safety)
Layer 2:  Org Context (100 tokens, SSO-agnostic; right-sized from 500 — actual usage ~70 tokens)
Layer 3:  Profile Context (200 tokens, global profile + agent-scoped memory notes top 5)
Layer 4a: Individual Working Memory (100 tokens, agent-scoped)
Layer 4b: Team Working Memory (150 tokens, NEW — shared bucket for active team)
Layer 5:  Domain Context (RAG content, remaining budget)
Layer 6:  Glossary (REMOVED from prompt — pre-translated inline in query at pipeline step 3b)
```

Token budget at 2K limit (canonical):

- Memory overhead (Layers 2, 3, 4a, 4b): 550 tokens
- RAG context available: 1,450 tokens

Note: Layer 0+1 (agent base + platform base, ~200 tokens fixed) are excluded from the canonical overhead figure above, per the token budget specification.

**Improvement over old budget**: RAG context increased from ~700 tokens to 1,450 tokens at 2K — a 107% improvement, achieved by right-sizing Org Context (500 → 100) and removing the Glossary layer from prompt overhead (now handled via pre-translation in doc 37). Tenant admins can still adjust individual layer budgets via tenant settings.

---

## 5. Tenant Admin Controls (New in mingai)

Tenant admins should be able to configure:

| Setting                                  | Default    | Notes                                     |
| ---------------------------------------- | ---------- | ----------------------------------------- |
| Profile learning enabled                 | ON         | Master toggle for all users in tenant     |
| Working memory TTL                       | 7 days     | 1-30 days range                           |
| Memory notes max                         | 15         | 5-50 range                                |
| Memory note source: allow auto-extracted | ON         | Some tenants may want user-only           |
| Org context enabled                      | ON         | Can disable for privacy-sensitive tenants |
| Profile learning trigger                 | 10 queries | 5-25 query range                          |
| Agent-scoped memory                      | OFF        | Phase 2 feature                           |

These settings live in the `tenant_settings` table and are enforced server-side.

---

## 6. Carry-Forward Without Change

The following aihub2 components can be ported with minimal modification:

| Component                                  | File                        | Change needed                  |
| ------------------------------------------ | --------------------------- | ------------------------------ |
| `ProfileLRUCache`                          | `profile_learning.py`       | None — pure Python, no DB deps |
| `WorkingMemoryService._extract_topics()`   | `working_memory.py`         | None — pure NLP                |
| `WorkingMemoryService.format_for_prompt()` | `working_memory.py`         | None                           |
| Memory intent detection regex              | `chat/router.py`            | None                           |
| `MemoryNote` Pydantic schema               | `schemas.py`                | Add `agent_id` field           |
| `EXTRACTION_PROMPT`                        | `profile_learning.py`       | None                           |
| Privacy settings UI components             | `settings/privacy/page.tsx` | Add tenant-level toggles       |
| `MemoryNotesList.tsx`                      | `components/memory/`        | Add agent badge to notes       |
| `useUserMemory.ts`                         | `hooks/`                    | None                           |

---

## 7. Net New Implementation (mingai-specific)

1. **`OrgContextSource` abstraction** — SSO-agnostic org identity fetcher
2. **`AgentProfileScope` service** — filters profile context to agent-relevant attributes
3. **Tenant admin memory policy API** — CRUD for tenant-level memory settings
4. **Org context Redis cache** — 24h cache (not in aihub2, optimization for mingai scale)
5. **`memory_notes` as normalized table** — replaces embedded document approach
6. **Working memory keyed by `agent_id`** — agent-specific session continuity
7. **Token budget configurable per-tenant** — layer priority and size adjustable

---

## 8. Migration Risk Assessment

| Risk                                                         | Severity | Mitigation                                                                                              |
| ------------------------------------------------------------ | -------- | ------------------------------------------------------------------------------------------------------- |
| CosmosDB-to-PostgreSQL data model mismatch                   | Medium   | Normalize embedded arrays to separate tables; scripted migration                                        |
| Agent-scoped memory breaks existing global memory on upgrade | Low      | Default `agent_id = NULL` means "global" — backward compatible                                          |
| Tenant LLM config affects profile quality                    | Medium   | Minimum quality guardrail; fallback to platform default model                                           |
| Redis key namespace collision at scale                       | Low      | Strict `{tenant_id}:` prefix enforcement in all service methods                                         |
| Token budget compression at high glossary load               | Low      | Glossary removed from prompt overhead — now pre-translated inline in query; zero prompt tokens consumed |
