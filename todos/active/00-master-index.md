# 00 — Master Todo Index

**Project**: mingai Enterprise RAG Platform
**Generated**: 2026-03-07
**Status**: IN PROGRESS — Phase 1 backend complete | Phase 1 frontend 24/24 items done
**Progress**: Phase 1 backend complete | Phase 1 frontend 24/24 items implemented | 694 unit tests + 69 integration tests passing
**Last updated**: 2026-03-07 (this session: AI-034/INFRA-014/INFRA-020 complete; security hardening (H1-H4); path validation on all tenant/profile route params; FE-001–FE-029 audited — 23 Phase 1 frontend items implemented; FE-018 WorkProfileCard completed with smooth sub-toggle animation)
**Total items across all files**: 354 todos (44 DB + 120 API + 51 AI + 61 FE + 72 TEST + 50 INFRA + overhead tests counted in TEST file = 398 work items when including sub-file test counts)

> This is the single navigation document for the entire implementation. Reference individual files for full acceptance criteria, dependencies, and notes on each item.

---

## 1. Summary Table

| File                    | Domain             | Items   | ID Range              | Total Effort | Status                                                                                                                                                |
| ----------------------- | ------------------ | ------- | --------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `01-database-schema.md` | DB + Redis         | 44      | DB-001 – DB-044       | ~120h        | 22/44 DONE (DB-001–DB-022)                                                                                                                            |
| `02-api-endpoints.md`   | API Endpoints      | 120     | API-001 – API-120     | ~449h        | ~60/120 DONE (Phase 1 core + API-025/030/031 evidence confirmed, 50%)                                                                                 |
| `03-ai-services.md`     | AI / Intelligence  | 51      | AI-001 – AI-051       | ~171h        | 23/51 DONE (AI-001–021/032/033/034/035, 45%)                                                                                                          |
| `04-frontend.md`        | Frontend (Next.js) | 61      | FE-001 – FE-061       | ~379h        | 24/61 DONE (Phase 1 implemented: FE-001–009/012–013/015–023/026–029; FE-010/011/014/024/025/030–035/036–048 are Phase 2)      |
| `05-testing.md`         | Tests (all tiers)  | 72      | TEST-001 – TEST-072   | ~248h        | 30/72 DONE (auth/RLS/blur/GDPR/memory/cache/routing + TEST-008/009/010/023 integration, ~42%)                                                         |
| `06-infrastructure.md`  | Infra / DevOps     | 50      | INFRA-001 – INFRA-050 | ~227h        | 28/50 DONE (migrations+DevOps+CacheService+ProfileLRU+OrgCtx+GlossaryCache+INFRA-019 blur+INFRA-014 cache warming+INFRA-020 provisioning worker, 56%) |
| **Totals**              |                    | **398** |                       | **~1,594h**  | **~166/398 DONE (~42% overall)**                                                                                                                      |

> Effort estimate: ~1,594 hours total. At 2 engineers full-time = ~100 working days (~20 weeks). Parallelism across domains reduces calendar time significantly.

---

## 2. Critical Path (Sequential Dependencies)

The following chain is the strict sequential gate. Nothing downstream can begin until the item above it is complete.

```
INFRA-001 (add tenant_id to 19 tables — migration 001)
  -> INFRA-002 (create tenants + tenant_configs + user_feedback tables — migration 002)
    -> INFRA-003 (backfill default tenant — migration 003)
      -> INFRA-004 (enable RLS on all 22 tables — migration 004)
        -> INFRA-005 (platform RBAC scope column + platform roles — migration 005)
          -> INFRA-008 (JWT v1/v2 dual-acceptance middleware)
            -> DB-001 (tenants table — Kailash DataFlow model)
              -> API-001 (JWT v2 validation middleware)
                -> [ALL remaining API endpoints]
                -> [ALL frontend pages that make API calls]
                -> [ALL integration + E2E tests]
```

**Critical path for caching** (feeds chat and semantic search):

```
INFRA-006 (pgvector + semantic_cache migration)
  -> INFRA-009 (Redis key namespace migration)
    -> INFRA-010 (LLM config migration from @lru_cache to tenant_configs)
      -> INFRA-011 (CacheService implementation)
        -> INFRA-012 (@cached decorator)
          -> INFRA-013 (cache invalidation pub/sub)
            -> API-008 (chat/stream endpoint — uses cache)
```

**Critical path for multi-tenant isolation** (BLOCKING all features):

```
INFRA-004 (RLS policies applied) -> TEST-002 (RLS unit tests)
  -> TEST-003 (cross-tenant isolation integration tests — MUST PASS before any feature ships)
```

**Critical path for issue reporting** (screenshot blur is a CRITICAL blocker):

```
INFRA-019 (screenshot blur service — server-side)
  -> FE-022 (issue reporter dialog — client-side blur default)
    -> TEST-015 (screenshot blur enforcement — MUST PASS before issue reporting ships)
```

**Critical path for GDPR compliance**:

```
AI-009 (WorkingMemoryService with agent-scoped keys)
  -> AI-023 (memory notes CRUD with 200-char enforcement)
    -> AI-035 (GDPR clear_profile_data — fixes aihub2 bug)
      -> TEST-054 (GDPR erasure test — working memory included)
```

**Summary of absolute blockers** (items that block everything else):

| Priority | Item                               | Blocks                                       |
| -------- | ---------------------------------- | -------------------------------------------- |
| P0       | INFRA-001–005 (migrations 001–005) | All DB work, all API work                    |
| P0       | INFRA-004 (RLS policies)           | All multi-tenant security                    |
| P0       | INFRA-008 (JWT middleware)         | All auth, all API endpoints                  |
| P0       | API-001 (JWT v2 middleware)        | All 119 other API endpoints                  |
| P0       | TEST-002 + TEST-003 (RLS tests)    | Platform may not ship without passing        |
| P1       | INFRA-009 (Redis namespace) ✅     | All caching                                  |
| P1       | INFRA-011 (CacheService) ✅        | All cache-dependent features                 |
| P1       | TEST-015 (screenshot blur)         | Issue reporting may not ship without passing |
| P1       | AI-035 (GDPR erasure fix) ✅       | GDPR compliance                              |
| P1       | TEST-054 (GDPR test)               | EU tenant deployment                         |

---

## 3. Phase 1 MVP Scope

Phase 1 targets the Foundation + Profile & Memory + Issue Reporting (intake only) + Chat + Core DevOps.

### Infrastructure (Phase 1)

| ID        | Description                                            | File |
| --------- | ------------------------------------------------------ | ---- |
| INFRA-001 | Add tenant_id to 19 existing tables                    | 06   |
| INFRA-002 | Create tenants + tenant_configs + user_feedback tables | 06   |
| INFRA-003 | Backfill default tenant                                | 06   |
| INFRA-004 | Enable RLS on all 22 tables                            | 06   |
| INFRA-005 | Platform RBAC scope column + roles                     | 06   |
| INFRA-008 | JWT v1/v2 dual-acceptance middleware                   | 06   |
| INFRA-009 | Redis key namespace migration                          | 06   |
| INFRA-010 | LLM config migration to tenant_configs                 | 06   |
| INFRA-011 | CacheService implementation                            | 06   |
| INFRA-012 | @cached decorator                                      | 06   |
| INFRA-013 | Cache invalidation pub/sub                             | 06   |
| INFRA-014 | Cache warming background job                           | 06   |
| INFRA-019 | Screenshot blur service (CRITICAL — R4.1)              | 06   |
| INFRA-020 | Tenant provisioning async worker                       | 06   |
| INFRA-026 | Glossary cache warm-up on startup                      | 06   |
| INFRA-032 | Redis hot counter write-back to PostgreSQL             | 06   |
| INFRA-033 | Async profile learning job                             | 06   |
| INFRA-034 | In-process LRU cache for user profiles (L1)            | 06   |
| INFRA-036 | Org context Redis cache                                | 06   |
| INFRA-037 | Glossary pretranslation rollout flag                   | 06   |
| INFRA-038 | Glossary Redis cache with invalidation                 | 06   |
| INFRA-039 | Docker Compose for local dev                           | 06   |
| INFRA-040 | Dockerfile — backend                                   | 06   |
| INFRA-041 | Dockerfile — frontend                                  | 06   |
| INFRA-042 | .env.example                                           | 06   |
| INFRA-043 | Health check endpoints                                 | 06   |
| INFRA-044 | Structured logging                                     | 06   |
| INFRA-046 | CI pipeline (GitHub Actions)                           | 06   |

### Database (Phase 1)

All DB-001 through DB-045 items are Phase 1. The DB file defines the core multi-tenant schema including:

- DB-001: `tenants` table + DataFlow model
- DB-002–DB-010: Core auth tables (users, roles, user_roles, platform_members, audit_log, invitations, tenant_configs, kb_access_control, agent_access_control)
- DB-011–DB-020: Chat + caching tables (conversations, messages, user_feedback, semantic_cache, cache_analytics_events, embedding_cache_metadata, search_results_cache, intent_cache, query_cache, cache_hit_rates)
- DB-021–DB-030: Profile + memory tables (user_profiles, profile_learning_events, memory_notes, working_memory_snapshots, consent_events, notification_preferences, user_privacy_settings, team_memberships, team_working_memory_snapshots, teams)
- DB-031–DB-040: Sync + Glossary + Issue tables (integrations, sync_jobs, sync_file_errors, document_chunks, glossary_terms, glossary_miss_signals, issue_reports, issue_report_events, mcp_servers, usage_daily)
- DB-041–DB-044: HAR tables (agent_cards, har_transactions, har_transaction_events, har_trust_score_history)

### API Endpoints (Phase 1)

| IDs     | Description                              |
| ------- | ---------------------------------------- |
| API-001 | JWT v2 validation middleware             |
| API-002 | Platform health check                    |
| API-003 | Auth local login                         |
| API-004 | Token refresh                            |
| API-005 | Logout                                   |
| API-006 | Get current user                         |
| API-007 | Response feedback (retrieval confidence) |
| API-008 | Chat stream (SSE — main pipeline)        |
| API-009 | List conversations                       |
| API-010 | Create conversation                      |
| API-011 | Get conversation messages                |
| API-013 | Submit issue report                      |
| API-014 | Get screenshot pre-signed URL            |
| API-024 | Provision new tenant                     |
| API-025 | Get provisioning job status (SSE)        |
| API-026 | List all tenants                         |
| API-027 | Get tenant detail                        |
| API-028 | Update tenant status                     |
| API-030 | Get tenant quota                         |
| API-031 | Update tenant quota                      |
| API-032 | Create LLM profile                       |
| API-033 | List LLM profiles                        |
| API-034 | Update LLM profile                       |
| API-043 | Invite user (single)                     |
| API-044 | Bulk invite users                        |
| API-045 | Change user role                         |
| API-046 | Update user status                       |
| API-048 | Get workspace settings                   |
| API-049 | Update workspace settings                |
| API-050 | Connect SharePoint                       |
| API-051 | Test SharePoint connection               |
| API-054 | Manual sync trigger                      |
| API-055 | Sync status                              |
| API-057 | List glossary terms                      |
| API-058 | Add glossary term                        |
| API-059 | Update glossary term                     |
| API-060 | Delete glossary term                     |
| API-099 | Get user profile                         |
| API-100 | Get memory notes                         |
| API-101 | Add memory note                          |
| API-102 | Delete memory note                       |
| API-103 | Clear all memory notes                   |
| API-104 | Update privacy settings                  |
| API-105 | GDPR clear all profile data              |

### AI Services (Phase 1)

| IDs    | Description                                                                 |
| ------ | --------------------------------------------------------------------------- |
| AI-001 | Port ProfileLRUCache                                                        |
| AI-002 | Port ProfileLearningService with PostgreSQL backend                         |
| AI-003 | Port EXTRACTION_PROMPT template                                             |
| AI-004 | Tenant LLM profile selection for intent model                               |
| AI-005 | Tenant-scoped Redis keys for profile learning                               |
| AI-006 | Query counter with Redis hot counter + PostgreSQL write-back                |
| AI-007 | on_query_completed hook                                                     |
| AI-009 | Port WorkingMemoryService with agent-scoped Redis keys                      |
| AI-010 | Working memory topic extraction                                             |
| AI-011 | Working memory format_for_prompt                                            |
| AI-013 | TeamWorkingMemoryService core                                               |
| AI-014 | Team working memory format_for_prompt                                       |
| AI-016 | OrgContextData Pydantic model                                               |
| AI-017 | OrgContextSource abstract interface                                         |
| AI-018 | Auth0OrgContextSource implementation                                        |
| AI-019 | OktaOrgContextSource (JWT-only, zero-data)                                  |
| AI-020 | GenericSAMLOrgContextSource                                                 |
| AI-021 | OrgContextService (source selector)                                         |
| AI-023 | Memory notes CRUD service (200-char enforcement)                            |
| AI-024 | Chat router "remember that" fast path                                       |
| AI-026 | GlossaryExpander.expand() core                                              |
| AI-027 | Glossary stop-word exclusion + uppercase rule                               |
| AI-028 | Glossary pipeline integration                                               |
| AI-032 | SystemPromptBuilder with 6-layer architecture                               |
| AI-033 | Token budget enforcement and truncation priority                            |
| AI-034 | Profile SSE flag and memory_saved event                                     |
| AI-035 | GDPR clear_profile_data comprehensive erasure (CRITICAL — fixes aihub2 bug) |
| AI-037 | IssueTriageAgent Kaizen BaseAgent implementation                            |
| AI-038 | Issue triage confidence scoring and routing rules                           |

### Frontend (Phase 1)

| IDs    | Description                                                          |
| ------ | -------------------------------------------------------------------- |
| FE-001 | Initialize Next.js project with Obsidian Intelligence design system  |
| FE-002 | API client and auth infrastructure                                   |
| FE-003 | Shared layout shell with role-based navigation                       |
| FE-004 | Chat page — empty state layout                                       |
| FE-005 | Chat page — active state layout with SSE streaming                   |
| FE-006 | Chat — thumbs up/down feedback widget                                |
| FE-007 | Chat — source panel slide-out                                        |
| FE-008 | Chat — retrieval confidence badge and bar                            |
| FE-009 | Chat — ProfileIndicator component                                    |
| FE-012 | Chat — "Memory saved" toast notification                             |
| FE-013 | Chat — "Terms interpreted" glossary indicator (MANDATORY)            |
| FE-015 | Chat — conversation list sidebar                                     |
| FE-016 | Privacy settings page — profile learning card                        |
| FE-017 | PrivacyDisclosureDialog component                                    |
| FE-018 | Work profile card with toggles                                       |
| FE-019 | Memory notes list with CRUD                                          |
| FE-020 | Data rights section — export and clear                               |
| FE-021 | Issue reporter floating button                                       |
| FE-022 | Issue reporter dialog with screenshot and annotation (blur CRITICAL) |
| FE-023 | Error detection auto-prompt                                          |
| FE-026 | Tenant admin dashboard                                               |
| FE-027 | User directory with invite and role management                       |
| FE-028 | Workspace settings page                                              |
| FE-029 | Document store list and SharePoint wizard                            |

### Testing (Phase 1)

| IDs      | Description                                                     |
| -------- | --------------------------------------------------------------- |
| TEST-001 | JWT v2 validation middleware — unit tests                       |
| TEST-002 | Multi-tenant RLS enforcement — unit tests                       |
| TEST-003 | Cross-tenant isolation — integration tests (BLOCKING)           |
| TEST-004 | JWT v1-to-v2 dual-acceptance window — integration tests         |
| TEST-005 | Auth0 integration — integration tests                           |
| TEST-006 | Cache key builder — unit tests                                  |
| TEST-007 | Cache serialization/deserialization — unit tests                |
| TEST-008 | CacheService CRUD — integration tests                           |
| TEST-009 | Cross-tenant cache key isolation — integration tests (BLOCKING) |
| TEST-010 | Cache invalidation pub/sub — integration tests                  |
| TEST-014 | IssueTriageAgent classification — unit tests                    |
| TEST-015 | Screenshot blur enforcement — unit tests (BLOCKING)             |
| TEST-016 | "Still happening" rate limit — unit tests                       |
| TEST-017 | Issue type routing — unit tests                                 |
| TEST-018 | Issue reporting Redis Streams — integration tests               |
| TEST-019 | Full triage pipeline — integration tests                        |
| TEST-021 | Health score algorithm — unit tests                             |
| TEST-022 | Tenant provisioning state machine — unit tests                  |
| TEST-023 | LLM profile CRUD — integration tests                            |
| TEST-024 | Tenant provisioning async worker — integration tests            |
| TEST-029 | Glossary pre-translation pipeline — unit tests                  |
| TEST-030 | Glossary prompt injection sanitization — unit tests             |
| TEST-031 | Glossary cache with Redis — integration tests                   |
| TEST-050 | Memory notes 200-char enforcement — unit tests                  |
| TEST-054 | GDPR clear_profile_data — integration tests (BLOCKING)          |
| TEST-067 | Docker test environment setup (blocks all Tier 2-3)             |
| TEST-068 | Test fixtures + conftest.py                                     |
| TEST-069 | Database migration testing                                      |

---

## 4. Effort by Phase

### Phase 1 — Foundation + MVP (Target: First ship)

| Domain                                                                    | Phase 1 Items                                                                       | Estimated Hours |
| ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | --------------- |
| Infrastructure (migrations + core infra + DevOps)                         | INFRA-001–005, 008–014, 019–020, 026, 032–034, 036–044, 046                         | ~170h           |
| Database schema (all DB items are Phase 1)                                | DB-001 – DB-044                                                                     | ~120h           |
| API endpoints (auth, chat, core admin, profile, glossary)                 | API-001–011, 013–014, 024–028, 030–034, 043–046, 048–051, 054–055, 057–060, 099–105 | ~235h           |
| AI services (profile, memory, glossary, triage)                           | AI-001–011, 013–014, 016–021, 023–024, 026–028, 032–035, 037–038                    | ~120h           |
| Frontend (chat, privacy, issue reporting, core admin Phase A)             | FE-001–009, 012–013, 015–023, 026–029                                               | ~170h           |
| Testing (auth, RLS, cache isolation, screenshot blur, GDPR, provisioning) | TEST-001–010, 014–019, 021–024, 029–031, 050, 054, 067–069                          | ~115h           |
| **Phase 1 Total**                                                         |                                                                                     | **~930h**       |

### Phase 2 — Intelligence + Extended Admin (Target: Post-MVP)

| Domain                                                                                                    | Phase 2 Items                                                       | Estimated Hours |
| --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | --------------- |
| Infrastructure (secrets mgr, doc sync, HAR infra, health monitor)                                         | INFRA-015–016, 021–025, 027–030, 035, 045–050                       | ~90h            |
| API (issue queues, SSO, Google Drive, glossary bulk, agents, HAR, teams, analytics)                       | API-012, 015–023, 029, 035–042, 047, 052–053, 056, 061–098, 106–120 | ~180h           |
| AI (team memory, org context, HAR A2A, trust score, health monitor, integration tests)                    | AI-008, 012, 015, 022, 025, 029–031, 036, 039–051                   | ~75h            |
| Frontend (SSO, glossary admin, sync health, agents library, tenant analytics, issue queue, notifications) | FE-010–011, 014, 024–025, 030–035, 037–048                          | ~155h           |
| Testing (SAML/OIDC, Tenant Admin, HAR, teams, platform admin E2E)                                         | TEST-020, 025–028, 032–048, 051–053, 055–066, 070–072               | ~100h           |
| **Phase 2 Total**                                                                                         |                                                                     | **~600h**       |

### Phase 3+ — Advanced Features (Gated on usage milestones)

| Domain             | Phase 3+ Items                                                                                   | Estimated Hours |
| ------------------ | ------------------------------------------------------------------------------------------------ | --------------- |
| Infrastructure     | INFRA-031 (blockchain docs), INFRA-015 (semantic cache cleanup)                                  | ~5h             |
| Frontend           | FE-036 (Agent Studio — gated on 5-10 customer interviews), FE-049–061 (Platform Admin Phase B-D) | ~60h            |
| AI                 | Semantic upgrade for working memory (English-only gap), agent-scoped memory UX                   | TBD             |
| HAR                | Blockchain/KYB integration (gated on 100+ transactions)                                          | ~200h+          |
| **Phase 3+ Total** |                                                                                                  | **~265h+**      |

---

## 5. Cross-Cutting Concerns (Items Spanning Multiple Domains)

These items require coordination between engineers working on different files.

### Multi-Tenant Isolation

The most critical cross-cutting concern. A failure here is a data breach.

| Component | Items                                                             | Notes                            |
| --------- | ----------------------------------------------------------------- | -------------------------------- |
| DB        | INFRA-001–004, DB-001 (tenants table)                             | RLS migrations + DataFlow models |
| API       | API-001 (JWT injects tenant_id), all 119 other endpoints          | Every endpoint uses RLS via JWT  |
| Cache     | INFRA-009 (Redis namespace), INFRA-011 (CacheService key builder) | Redis key isolation              |
| Test      | TEST-002, TEST-003, TEST-009                                      | BLOCKING — must pass before ship |

### GDPR Erasure Flow

Bug from aihub2: `clear_profile_data()` did NOT clear working memory. Must be fixed.

| Component | Items                                                                             | Notes     |
| --------- | --------------------------------------------------------------------------------- | --------- |
| AI        | AI-009 (agent-scoped Redis keys), AI-035 (comprehensive erasure fix)              | Core fix  |
| API       | API-105 (GDPR clear all profile data), API-047 (delete user — also clears memory) | Endpoints |
| Frontend  | FE-020 (Data rights section — export + clear)                                     | UI        |
| Test      | TEST-054 (GDPR clear_profile_data integration test)                               | BLOCKING  |

### Token Budget Enforcement

Context window is MARGIN-CRITICAL. At 2K tokens only ~500 tokens for RAG after memory overhead.

| Component | Items                                                                  | Notes                        |
| --------- | ---------------------------------------------------------------------- | ---------------------------- |
| AI        | AI-032 (SystemPromptBuilder), AI-033 (truncation priority enforcement) | Core budget logic            |
| API       | API-008 (chat stream — enforces budget before LLM call)                | Enforcement point            |
| Test      | TEST-056 (token budget overflow test — 2K boundary)                    | Validates budget enforcement |

### Screenshot Blur (CRITICAL — R4.1)

RAG response area MUST be blurred by default before any screenshot is stored or submitted.

| Component      | Items                                                                | Notes                                             |
| -------------- | -------------------------------------------------------------------- | ------------------------------------------------- |
| Frontend       | FE-022 (dialog: blur by default, user must un-blur explicitly)       | Client-side gate                                  |
| Infrastructure | INFRA-019 (server-side blur pipeline — overwrites unblurred uploads) | Server-side defense                               |
| API            | API-013 (issue report endpoint validates blur_acknowledged flag)     | API gate                                          |
| Test           | TEST-015 (blur enforcement unit tests)                               | BLOCKING — must pass before issue reporting ships |

### Glossary Pre-Translation Pipeline

Glossary must be removed from Layer 6 (system prompt) and moved to inline query expansion.

| Component      | Items                                                                                         | Notes                        |
| -------------- | --------------------------------------------------------------------------------------------- | ---------------------------- |
| DB             | DB-035 (glossary_terms table with RLS)                                                        | Data layer                   |
| AI             | AI-026–028 (GlossaryExpander + pipeline wiring)                                               | Core logic — Layer 6 removed |
| API            | API-057–062 (glossary CRUD), API-110 (glossary expansions metadata)                           | Management + metadata        |
| Frontend       | FE-013 (Terms interpreted indicator — MANDATORY), FE-033 (glossary admin page)                | UI                           |
| Infrastructure | INFRA-037 (rollout flag), INFRA-038 (Redis cache + invalidation), INFRA-026 (startup warm-up) | Infra                        |
| Test           | TEST-029–033 (unit + integration), TEST-030 (prompt injection sanitization)                   | Validation                   |

### Retrieval Confidence Label

The label "retrieval confidence" must appear consistently across all layers. Never "answer confidence" or "AI confidence".

| Component | Items                                                                          | Notes      |
| --------- | ------------------------------------------------------------------------------ | ---------- |
| API       | API-007 (feedback endpoint), API-008 (SSE metadata.retrieval_confidence field) | Backend    |
| Frontend  | FE-008 (ConfidenceBadge — label must read exactly "retrieval confidence")      | UI         |
| Test      | TEST-032 (RAG query routing integration test checks metadata field name)       | Validation |

---

## 6. Security and Compliance Gates

These items MUST be completed and verified with passing tests before any production deployment.

### Gate 1 — Multi-Tenant Data Isolation (BLOCKING all features)

| Gate Item                                                 | Required Test                                                   | Status  |
| --------------------------------------------------------- | --------------------------------------------------------------- | ------- |
| INFRA-004: RLS policies on all 22 tables                  | TEST-002 (20 unit tests, 100% coverage)                         | DONE    |
| INFRA-004: Cross-tenant isolation                         | TEST-003 (12 integration tests, real PostgreSQL)                | DONE    |
| INFRA-011: Cross-tenant cache key isolation               | TEST-009 (6 integration tests, 100% coverage)                   | Pending |
| All 22 RLS policies verified in schema introspection test | TEST-002, case: "RLS policy exists on ALL tenant-scoped tables" | DONE    |

### Gate 2 — Authentication (BLOCKING all user-facing features)

| Gate Item                                         | Required Test                                      | Status |
| ------------------------------------------------- | -------------------------------------------------- | ------ |
| API-001: JWT v2 validation                        | TEST-001 (15 unit tests, 100% coverage)            | DONE   |
| INFRA-008: JWT v1/v2 dual acceptance              | TEST-004 (6 integration tests, 100% coverage)      | DONE   |
| Auth0 integration                                 | TEST-005 (8 integration tests, 100% coverage)      | DONE   |
| RBAC enforced at query time (not assignment time) | TEST-028 (KB access: "checked at QUERY TIME" case) | DONE   |

### Gate 3 — Privacy: Screenshot Blur (BLOCKING issue reporting)

| Gate Item                                                     | Required Test                                                        | Status                               |
| ------------------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------ |
| FE-022: RAG response area blurred by default                  | TEST-015, case: "screenshot without blur metadata flag REJECTED"     | DONE (FE-022 implemented)            |
| INFRA-019: Server-side blur pipeline — unblurred never stored | TEST-015, case: "unblurred screenshot never persisted"               | DONE (INFRA-019 + TEST-015 complete) |
| API-013: blur_acknowledged validation                         | TEST-015, case: "API request with blur_acknowledged: false REJECTED" | DONE (API-013 complete)              |

### Gate 4 — GDPR Erasure (BLOCKING EU tenant deployment)

| Gate Item                                                                   | Required Test                                         | Status |
| --------------------------------------------------------------------------- | ----------------------------------------------------- | ------ |
| AI-035: clear_profile_data() includes WorkingMemoryService.clear_memory()   | TEST-054, case: "GDPR clear — working memory deleted" | DONE   |
| AI-023: 200-char memory note limit enforced server-side                     | TEST-050, case: "200-char limit rejection"            | DONE   |
| API-047: User delete anonymizes conversations + clears Redis working memory | TEST-054 (comprehensive GDPR test)                    | DONE   |

### Gate 5 — Glossary Injection Security (BLOCKING glossary feature)

| Gate Item                                                                 | Required Test                          | Status |
| ------------------------------------------------------------------------- | -------------------------------------- | ------ |
| API-058: Glossary definition sanitized before injection                   | TEST-030 (8 unit tests, 100% coverage) | DONE   |
| AI-028: Layer 6 removed from SystemPromptBuilder                          | TEST-033 (4 integration tests)         | DONE   |
| Glossary terms cap: max 20 terms, 200 chars/definition, 800-token ceiling | TEST-029, canonical spec cases         | DONE   |

### Gate 6 — Credentials and Secrets

| Gate Item                                                                             | Required Test                                   | Status  |
| ------------------------------------------------------------------------------------- | ----------------------------------------------- | ------- |
| INFRA-023: Credentials never stored in PostgreSQL or Redis                            | TEST-037 (6 unit tests, 100% coverage)          | Pending |
| API-050: SharePoint client secret stored in vault, never in API response              | TEST-034, case: "credential encryption at rest" | Pending |
| AI-019: Auth0 group claim allowlist filtering (empty allowlist = no groups processed) | INFRA-035 acceptance criteria, TEST-028         | Pending |

### Gate 7 — Financial Controls (HAR — BLOCKING agent transactions)

| Gate Item                                                    | Required Test                                           | Status  |
| ------------------------------------------------------------ | ------------------------------------------------------- | ------- |
| AI-045: Human approval gate fires at $5,000 threshold        | TEST-048 (HAR transaction E2E)                          | Pending |
| AI-044: Signature chain verification detects tampered events | TEST-043 (chain verification unit tests, 100% coverage) | Pending |
| AI-042: Replay attack prevention (nonce deduplication)       | TEST-042, TEST-048                                      | Pending |

---

## 7. Risk Items (Red Team Cross-Reference)

### R01 — GDPR Bug (aihub2): Working Memory Not Cleared on Erasure Request ✅ RESOLVED

**Risk level**: CRITICAL
**Origin**: Red team 13-05, aihub2 source code analysis
**Description**: `clear_profile_data()` in aihub2 does NOT call `WorkingMemoryService.clear_memory()`. Working memory persists in Redis for up to 7 days after an erasure request, violating GDPR Article 17.

| Todo Items | Purpose                                                                                |
| ---------- | -------------------------------------------------------------------------------------- |
| AI-035     | Fix: add `WorkingMemoryService.clear_memory()` call to `clear_profile_data()`          |
| AI-009     | Prerequisite: agent-scoped Redis key pattern `{tenant_id}:working_memory:{user_id}:*`  |
| TEST-054   | Verification: GDPR erasure integration test must confirm working memory key is deleted |

**Acceptance**: TEST-054 must pass before any EU tenant deployment.

---

### R4.1 — Screenshot Blur Default (Issue Reporting): RAG Content Leakage ✅ BACKEND RESOLVED (FE pending)

**Risk level**: CRITICAL
**Origin**: Red team 09-issue-reporting, risk R4.1
**Description**: If screenshots are submitted unblurred, sensitive RAG response content (potentially confidential documents) can be exposed in the issue reporting system, visible to platform admins and engineers.

| Todo Items | Purpose                                                                    |
| ---------- | -------------------------------------------------------------------------- |
| FE-022     | Client: RAG response area blurred by default; user must explicitly un-blur |
| INFRA-019  | Server: blur pipeline overwrites unblurred uploads before storage          |
| API-013    | API: rejects submissions where `blur_acknowledged` is false                |
| TEST-015   | Verification: 8 unit tests, 100% coverage, CRITICAL classification         |

**Acceptance**: TEST-015 must pass. Issue reporting feature must not ship without passing.

---

### R02 (Memory) — Memory Note 200-char Limit Not Enforced in aihub2 ✅ RESOLVED

**Risk level**: HIGH
**Origin**: Red team 13-05, aihub2 source code analysis
**Description**: The 200-character limit on memory notes was documented but NOT enforced server-side in aihub2. mingai must enforce it.

| Todo Items | Purpose                                                         |
| ---------- | --------------------------------------------------------------- |
| AI-023     | Server-side enforcement: reject with 400 if content > 200 chars |
| TEST-050   | Verification: unit test case "200-char limit rejection"         |

---

### R03 (Memory) — Token Budget Overflow at 2K Context

**Risk level**: HIGH
**Origin**: Red team 13-05, token budget analysis in MEMORY.md
**Description**: At 2K system prompt budget, only ~500 tokens remain for RAG after memory overhead. Without strict budget enforcement, RAG context can be squeezed out entirely, producing hallucinations.

| Todo Items | Purpose                                                                                    |
| ---------- | ------------------------------------------------------------------------------------------ |
| AI-033     | Token budget enforcement with truncation priority (working memory truncated first)         |
| AI-032     | SystemPromptBuilder respects per-tenant budget from `tenant_settings.system_prompt_budget` |
| TEST-056   | Token budget overflow test at 2K boundary                                                  |

---

### R04 (Issue Reporting) — Glossary Prompt Injection via Definitions ✅ RESOLVED

**Risk level**: HIGH
**Origin**: Red team analysis, Plan 06 glossary architecture
**Description**: Glossary definitions are injected into the system message. A malicious tenant admin could craft a definition containing prompt injection instructions ("Ignore previous instructions...").

| Todo Items | Purpose                                                                                   |
| ---------- | ----------------------------------------------------------------------------------------- |
| AI-028     | Glossary injection only goes to system message (already per Layer 6 spec)                 |
| API-058    | Sanitize definition before storage: strip injection patterns                              |
| TEST-030   | Prompt injection sanitization: 8 unit tests including "Ignore previous instructions" case |

---

### R05 (Auth) — Auth0 Group Claim Sync: Empty Allowlist Default

**Risk level**: HIGH
**Origin**: Plan 08 red team, INFRA-035 notes
**Description**: If the Auth0 group sync allowlist is empty and the default is "process all groups", a user could be assigned elevated roles via a crafted JWT group claim.

| Todo Items | Purpose                                                                        |
| ---------- | ------------------------------------------------------------------------------ |
| INFRA-035  | Allowlist filtering: empty allowlist = no groups processed (not "process all") |
| TEST-028   | Group mapping: "empty group list -> default role assigned" case                |

---

### R06 — Agent Template Prompt Injection via Variables

**Risk level**: HIGH
**Origin**: Plan 05 Phase D, MEMORY.md
**Description**: Agent template system prompts with variable substitution (`{{variable}}`) could allow tenant admins to inject arbitrary content if variables are concatenated directly into the system prompt.

| Todo Items | Purpose                                                                  |
| ---------- | ------------------------------------------------------------------------ |
| API-038    | Template system prompt never concatenated with raw user variable content |
| API-040    | Published templates maintain immutable system prompt                     |

---

## Total Effort Summary

| Domain                 | Phase 1   | Phase 2   | Phase 3+   | Total        |
| ---------------------- | --------- | --------- | ---------- | ------------ |
| Infrastructure (INFRA) | ~170h     | ~57h      | ~5h        | **~227h**    |
| Database Schema (DB)   | ~120h     | —         | —          | **~120h**    |
| API Endpoints (API)    | ~235h     | ~214h     | —          | **~449h**    |
| AI Services (AI)       | ~120h     | ~51h      | TBD        | **~171h**    |
| Frontend (FE)          | ~170h     | ~209h     | —          | **~379h**    |
| Testing (TEST)         | ~115h     | ~133h     | —          | **~248h**    |
| **Phase Total**        | **~930h** | **~664h** | **~265h+** | **~1,594h+** |

**Calendar estimates** (assumes 2 senior engineers in parallel, ~6 productive hours/day):

| Phase       | Engineer-Hours | Calendar Weeks |
| ----------- | -------------- | -------------- |
| Phase 1 MVP | 930h           | ~12 weeks      |
| Phase 2     | 664h           | ~8 weeks       |
| Phase 3+    | 265h+          | ~4 weeks+      |
| **Total**   | **~1,594h**    | **~24 weeks**  |

---

## Navigation Guide

| I want to...                          | Go to                                                |
| ------------------------------------- | ---------------------------------------------------- |
| See the database schema spec          | `01-database-schema.md`                              |
| Find an API endpoint                  | `02-api-endpoints.md` — use search for API-NNN       |
| Find AI service implementation tasks  | `03-ai-services.md`                                  |
| Find frontend component tasks         | `04-frontend.md`                                     |
| Find test specifications              | `05-testing.md`                                      |
| Find infrastructure/migration tasks   | `06-infrastructure.md`                               |
| Start Day 1                           | INFRA-001 (migration 001) — run before anything else |
| Know what blocks everything           | Section 2 critical path; Section 6 security gates    |
| Know what items are GDPR-critical     | AI-035, TEST-054, API-105, FE-020                    |
| Know what items are privacy-critical  | INFRA-019, FE-022, API-013, TEST-015                 |
| Know what items are security-critical | TEST-002, TEST-003, TEST-009, TEST-030, TEST-037     |
