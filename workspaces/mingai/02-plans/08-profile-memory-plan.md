# 08 — Profile & Memory Implementation Plan

**Feature**: User Profile Learning + Working Memory + Memory Notes + Org Context
**Analysis refs**: 13-01 through 13-05, 36-profile-memory-architecture.md
**Source**: Ported and adapted from aihub2 (TODO-05, TODO-05A, TODO-23, TODO-70)
**Phase structure**: Phase 1 (MVP), Phase 2 (Differentiation), Phase 3+ (Moat)

---

## 1. Scope

### Phase 1: MVP (Port + Multi-Tenant)

Carry forward all four layers from aihub2 with multi-tenant isolation and PostgreSQL adaptation:

1. **Profile Learning** — LLM-extracted attributes every 10 queries
2. **Working Memory** — Redis session continuity
3. **Memory Notes** — User-directed + auto-extracted persistent facts
4. **Org Context** — SSO identity injection (Azure AD initial; abstraction for others)

**Outcome**: Users experience full personalization stack; platform properly isolates per tenant.

### Phase 2: Differentiation

1. **Agent-Scoped Memory** — Working memory and notes scoped per agent
2. **Team Working Memory** — Shared memory within tenant team/department
3. **Proactive Memory Surfacing** — Explicit prompt instruction to bridge prior context
4. **Configurable TTL** — Tenant-adjustable working memory retention

**Outcome**: Network collaboration score rises 3→7; unique enterprise differentiator.

---

## 2. Phase 1 Sprint Plan

### Sprint 1 — Data Layer (Week 1-2)

**Goal**: PostgreSQL schema + DataFlow models for profiles and memory notes

| Task                                            | Effort | Notes                                                          |
| ----------------------------------------------- | ------ | -------------------------------------------------------------- |
| Create `user_profiles` DataFlow model           | 4h     | Include `technical_level`, `communication_style`, JSONB fields |
| Create `memory_notes` DataFlow model            | 2h     | Add `agent_id` (nullable, Phase 2)                             |
| Create `profile_learning_events` DataFlow model | 2h     | Audit trail                                                    |
| Alembic migrations                              | 2h     | All three tables                                               |
| Unit tests (DataFlow models)                    | 4h     | CRUD per model                                                 |
| Tenant admin memory policy schema               | 2h     | `tenant_settings` extension                                    |

**Deliverable**: Clean schema, migrations passing, unit tests green.

### Sprint 2 — Profile Learning Backend (Week 3-4)

**Goal**: Port `ProfileLearningService` from aihub2 to mingai

| Task                                                                                            | Effort | Notes                                        |
| ----------------------------------------------------------------------------------------------- | ------ | -------------------------------------------- |
| Port `ProfileLRUCache`                                                                          | 1h     | No change needed                             |
| Port `ProfileLearningService` (PostgreSQL backend)                                              | 8h     | Replace Cosmos with DataFlow                 |
| Port `EXTRACTION_PROMPT`                                                                        | 0.5h   | No change                                    |
| Adapt to tenant LLM profile (intent model slot)                                                 | 3h     | Replace hardcoded `get_intent_openai_client` |
| Add tenant_id scoping to all Redis keys                                                         | 2h     | Prefix all keys                              |
| Clarify Phase 1 query counter scope to global `{user_id}` (no agent suffix)                     | 0.5h   | Phase 2 switches to per-agent                |
| Implement query_count write-back: Redis hot counter → PostgreSQL checkpoint on every 10th query | 2h     | On Redis cache miss: seed from PostgreSQL    |
| Port `on_query_completed()` hook                                                                | 2h     | Carry forward, add `agent_id` param stub     |
| Unit tests (30 tests target, 100% coverage)                                                     | 6h     | Port 32 aihub2 tests, adapt for PostgreSQL   |

> **Phase 1 query counter key**: `{tenant_id}:profile_learning:query_count:{user_id}` (global, cross-agent). Agent suffix added in Phase 2 Sprint 9.

**Deliverable**: Profile learning service operational, tests passing.

### Sprint 3 — Working Memory Backend (Week 5)

**Goal**: Port `WorkingMemoryService` with tenant + agent scoping

| Task                                                                      | Effort | Notes                                                  |
| ------------------------------------------------------------------------- | ------ | ------------------------------------------------------ |
| Port `WorkingMemoryService` (tenant-scoped keys)                          | 3h     | Add `{tenant_id}:` prefix                              |
| Use agent_id in Redis key from Day 1 — agent_id sourced from chat request | 1h     | Key: `{tenant_id}:working_memory:{user_id}:{agent_id}` |
| Port `format_for_prompt()`                                                | 0.5h   | No change                                              |
| Org context Redis cache (24h TTL)                                         | 2h     | New optimization vs aihub2                             |
| Unit tests (50 tests target)                                              | 5h     | Port 72 aihub2 working memory tests                    |

**Deliverable**: Working memory service operational, org context cached.

### Sprint 4 — Org Context + SSO Abstraction (Week 6-7)

**Goal**: SSO-agnostic org context layer

| Task                                                                                                                                                | Effort | Notes                                  |
| --------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | -------------------------------------- |
| Create `OrgContextData` normalized schema                                                                                                           | 1h     |                                        |
| Create `OrgContextSource` abstract interface                                                                                                        | 2h     |                                        |
| Implement `AzureADOrgContextSource`                                                                                                                 | 4h     | Port `org_context.py` from aihub2      |
| Implement `OktaOrgContextSource` — returns `OrgContextData` with all fields `None` (valid zero-data behavior until Okta API integration in Phase 2) | 2h     | Null-returning valid class, not a stub |
| Implement `GenericSAMLOrgContextSource`                                                                                                             | 3h     | Falls back to SAML claims              |
| Unit tests (15 tests)                                                                                                                               | 4h     | Per-source + fallback behavior         |

**Deliverable**: Org context works for Azure AD; Okta/SAML sources registered with null-returning implementations (not stubs — correct zero-data behavior when provider not configured).

### Sprint 5 — Memory Notes Backend (Week 8-9)

**Goal**: Port memory notes system

| Task                                                                   | Effort | Notes                                |
| ---------------------------------------------------------------------- | ------ | ------------------------------------ |
| Port memory note CRUD to DataFlow                                      | 4h     | Normalized table vs Cosmos embedding |
| Port intent detection in chat router                                   | 2h     | "remember that..." fast path         |
| Port `add_memory_note()`, `delete_memory_note()`, `get_memory_notes()` | 3h     |                                      |
| Port `clear_memory_notes()` for GDPR                                   | 1h     |                                      |
| Extend `EXTRACTION_PROMPT` for auto-extraction                         | 1h     | No change from aihub2                |
| Unit tests (14 tests target)                                           | 4h     | Port aihub2 test suite               |
| API endpoints: GET/DELETE /me/memory                                   | 3h     | Port from `profile_endpoints.py`     |

**Deliverable**: Memory notes fully functional, GDPR-compliant.

### Sprint 6 — System Prompt Builder + Chat Integration (Week 10-11)

**Goal**: Wire all four memory layers into prompt builder

| Task                                               | Effort | Notes                                      |
| -------------------------------------------------- | ------ | ------------------------------------------ |
| Implement `SystemPromptBuilder` with 6 layers      | 6h     | Migrate from aihub2 pattern                |
| Integrate all four memory layers into chat service | 4h     | Parallel asyncio.gather                    |
| Token budget configuration (per-tenant adjustable) | 4h     | Phase 1: defaults; adjustable via settings |
| Profile SSE flag (`profile_context_used`)          | 2h     | Indicate when profile influences response  |
| Memory saved SSE event                             | 1h     | `memory_saved` event for "remember that"   |
| Integration tests (25 tests target)                | 6h     | Full prompt builder pipeline               |

**Deliverable**: Chat pipeline fully personalized; all layers operational.

### Sprint 7 — Frontend (Week 12-13)

**Goal**: Privacy settings UI + memory management

| Task                                                                                                                                                                                               | Effort | Notes                               |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ----------------------------------- |
| Port `MemoryNotesList.tsx`                                                                                                                                                                         | 4h     | Source badge, delete, empty state   |
| Port `useUserMemory.ts` hooks                                                                                                                                                                      | 2h     | CRUD hooks                          |
| Port privacy settings page memory card                                                                                                                                                             | 3h     | View/edit/clear/export              |
| Port `PrivacyDisclosureDialog` component — informs user what is collected and how, provides right-to-object control. NOT a consent gate. Reframe from 'ConsentDialog' to 'PrivacyDisclosureDialog' | 3h     | Transparency, not consent gate      |
| Port org context toggles                                                                                                                                                                           | 2h     | Master toggle + manager toggle      |
| Port `ProfileIndicator` component                                                                                                                                                                  | 2h     | Shows when profile used in response |
| Playwright E2E tests (10 tests)                                                                                                                                                                    | 6h     | Critical user flows                 |

**Deliverable**: Full privacy settings UI; users can manage all memory data.

### Sprint 8 — Tenant Admin Controls (Week 14)

**Goal**: Tenant-level memory policy management

| Task                                    | Effort | Notes                            |
| --------------------------------------- | ------ | -------------------------------- |
| Tenant memory policy API endpoints      | 4h     | GET/PATCH /admin/memory-policy   |
| Tenant admin UI: memory policy settings | 4h     | Toggle per-setting with defaults |
| Apply tenant policy in all services     | 3h     | Checked at service instantiation |
| Integration tests                       | 3h     | Policy enforcement verified      |

**Deliverable**: Tenant admins can configure memory behavior platform-wide.

---

## 3. Phase 2 Sprint Plan

### Sprint 9 — Agent-Scoped Memory (Week 15-16)

| Task                                                                                                                                      | Effort | Notes                                            |
| ----------------------------------------------------------------------------------------------------------------------------------------- | ------ | ------------------------------------------------ |
| Enable `agent_id` scoping in working memory                                                                                               | 4h     | Key schema change: `:global` → `:{agent_id}`     |
| Enable `agent_id` filtering in memory notes                                                                                               | 3h     | NULL = global; agent_id = agent-specific         |
| Enable `agent_id` scoping in profile learning                                                                                             | 4h     | interests[] and common_tasks[] per-agent         |
| Scope indicator UI: note badge [Global]/[Agent Name], scoped toast "Saved for X Agent", filtered note list per agent with "View all" link | 4h     | Replaces UX research gate per confirmed decision |
| Migration: existing data → `agent_id = NULL`                                                                                              | 1h     | Backward compatible                              |
| Tests                                                                                                                                     | 4h     | Agent isolation tests                            |

### Sprint 10 — Team Working Memory (Week 17-18)

| Task                                          | Effort | Notes                                 |
| --------------------------------------------- | ------ | ------------------------------------- |
| Design team identity source (Azure AD Groups) | 2h     | Group membership → team_id            |
| Create `TeamWorkingMemoryService`             | 8h     | Shared Redis bucket per team          |
| Team memory UI in settings (team view)        | 4h     | View shared team memory, clear button |
| Team admin can set shared memory notes        | 3h     | `source: team_admin` notes            |
| Tests                                         | 5h     | Shared memory + isolation             |

---

## 4. Canonical Specs

### Memory Notes Limits (from aihub2 TODO-70)

- **Max notes per user**: 15 (oldest pruned)
- **Notes injected to prompt**: Top 5 (newest first)
- **Max note content length**: 200 characters

### Working Memory Limits (from aihub2 TODO-23)

- **Max topics**: 5 (newest prepended)
- **Max recent queries**: 3 (newest first, 100-char truncation)
- **TTL**: 7 days default (Phase 2: configurable 1-30 days)
- **Returning user threshold**: 1 hour gap

### Profile Learning Limits (from aihub2 TODO-05)

- **Trigger**: Every 10 queries (configurable 5-25, Phase 2)
- **Conversations analyzed**: Last 10
- **interests[] max**: 20 items
- **expertise_areas[] max**: 10 items
- **common_tasks[] max**: 15 items
- **memory_notes per extraction**: Max 5

### Token Budget (Profile Memory Stack)

| Layer                        | Limit   |
| ---------------------------- | ------- |
| Org Context                  | 100     |
| Profile Context              | 200     |
| Individual Working Memory    | 100     |
| Team Working Memory          | 150     |
| Glossary (pre-translated, 0) | 0       |
| **Total overhead**           | **550** |

At 2K query budget: ~1,450 tokens for RAG/domain context.
At 4K query budget: ~3,450 tokens for RAG/domain context (ideal).

---

## 5. Definition of Done (Phase 1)

### Backend

- [ ] `user_profiles`, `memory_notes`, `profile_learning_events` tables migrated
- [ ] `ProfileLearningService` operational with PostgreSQL backend
- [ ] `WorkingMemoryService` operational with tenant-scoped Redis keys
- [ ] Memory notes CRUD API (GET, DELETE single, DELETE all)
- [ ] Org context layer (Azure AD source, SAML fallback)
- [ ] `SystemPromptBuilder` with all 6 layers
- [ ] Token budget enforcement per layer
- [ ] GDPR: clear_profile_data() wipes all three data types
- [ ] GDPR: export_profile_data() includes all three data types
- [ ] All backend unit tests passing (target: 120+ tests, covering all services)
- [ ] Integration tests for full prompt builder pipeline (25+ tests)

### Frontend

- [ ] Privacy settings page: profile toggle, memory notes list, org context toggles
- [ ] `PrivacyDisclosureDialog` component on first profile use (transparency, not consent gate)
- [ ] `ProfileIndicator` in chat (shows when profile used)
- [ ] "Memory saved" toast in chat
- [ ] Memory notes: source badge, delete, clear all
- [ ] TypeScript compiles with no errors
- [ ] Playwright E2E: 10 critical flow tests passing

### Tenant Admin

- [ ] Memory policy settings page in tenant admin
- [ ] All settings enforced at service layer

### Security

- [ ] All Redis keys include `{tenant_id}:` prefix
- [ ] All PostgreSQL queries filter by `tenant_id`
- [ ] Memory notes cannot be read across tenants (API enforces tenant scope)
- [ ] Profile export includes tenant-scoped data only
- [ ] Security review passed before commit

---

## 6. Risks

| Risk                                             | Severity | Mitigation                                                                       |
| ------------------------------------------------ | -------- | -------------------------------------------------------------------------------- |
| Token budget too tight at 2K (Professional tier) | High     | Make layer limits configurable; log truncation events                            |
| Profile quality varies by tenant's LLM model     | Medium   | Minimum capability check; fallback to platform default                           |
| Working memory topics are keyword-quality only   | Low      | Accept for Phase 1; semantic upgrade in Phase 3                                  |
| Auto-extracted memory notes are low-quality      | Medium   | Raise precision threshold in extraction prompt; manual review path               |
| GDPR: profile data not fully purged              | Critical | Test `clear_profile_data()` covers all three stores (PostgreSQL + Redis L2 + L1) |
| Agent-scoped memory causes user confusion        | Medium   | Clear UI labeling of scope; "global" as visible scope indicator                  |
