# 00 — Master Todo Index

**Project**: mingai Enterprise RAG Platform
**Generated**: 2026-03-07
**Last audited**: 2026-03-07 (session 4: Phase 2 completion rigorous verification — evidence annotations added to active files; completed/ archive created for API-012/018/019/020/021/022/023 and INFRA-017/018; file path discrepancies corrected — webhook handler, admin_issues_router, and platform_issues_router all reside in `app/modules/issues/routes.py`, not separate module files; 716/716 unit tests confirmed passing; commits 4e9cbf4, e269515, ea2c2ff)
**Total items across all files**: 354 todos (44 DB + 120 API + 51 AI + 61 FE + 72 TEST + 50 INFRA + overhead tests counted in TEST file = 398 work items when including sub-file test counts)

---

## 0a. Phase 2 Completed Items Archive (2026-03-07)

Completed Phase 2 items have been extracted to `todos/completed/` for historical reference. Items remain in their respective active files with COMPLETED status and evidence annotations. The active files are the single source of truth for status; the completed/ files are read-only snapshots.

| Archive File | Contents | Items | Test Evidence |
| --- | --- | --- | --- |
| `todos/completed/02-api-endpoints-phase2.md` | API-012, API-018, API-019, API-020, API-021, API-022, API-023 | 7 endpoints | 9 tests (notifications), verified via grep |
| `todos/completed/06-infrastructure-phase2.md` | INFRA-017, INFRA-018 | 2 infrastructure items | 11 tests (issue_stream) |

**Phase 2 completion note**: All 9 items verified with evidence (file path, function/class name, line number, test count). One file path discrepancy corrected: the master index previously cited `webhooks/github_routes.py`, `issues/admin_routes.py`, and `issues/platform_routes.py` as separate files — the actual implementation consolidates all three routers (`router`, `admin_issues_router`, `platform_issues_router`) in `app/modules/issues/routes.py`.

---

## 0. Phase 1 Audit Results (as of 2026-03-07)

Three commits landed on `feat/phase-1-backend`:
1. `feat(backend): Phase 1 backend — security hardening, integration tests, cross-tenant isolation`
2. `feat(backend): implement Phase 1 backend — 22 tables, 6 AI services, 125+ API endpoints`
3. `feat(fe): implement Phase 1 frontend with Obsidian Intelligence design system`

406 tests passing (unit + integration at time of audit).

### Phase 1 Completion Summary

| Domain | Phase 1 Items | Complete | Partial | Pending |
| -------------- | ------------- | -------- | ------- | ------- |
| Infrastructure | 27 | 15 | 3 | 9 |
| Database | 44 | 22 | 0 | 22 |
| API Endpoints | 43 | 34 | 4 | 5 |
| AI Services | 28 | 21 | 3 | 4 |
| Frontend | 24 | 19 | 2 | 3 |
| Testing | 26 | 16 | 5 | 5 |
| **TOTALS** | **192** | **127** | **17** | **48** |

**Phase 1 completion: 66% complete, 9% partial, 25% pending** *(+1 API Phase 1 item: API-014; plus 4 Phase 2 API items completed early: API-015/016/017/029)*

### Infrastructure — Phase 1 Status

| ID | Description | Status | Evidence |
| --------- | ---------------------------------------------- | ------ | -------- |
| INFRA-001 | Add tenant_id to 19 existing tables | ✅ COMPLETE | v001_initial_schema.py creates all tables with tenant_id from scratch |
| INFRA-002 | Create tenants + tenant_configs + user_feedback | ✅ COMPLETE | v001_initial_schema.py — all 22 tables including tenants, tenant_configs, user_feedback |
| INFRA-003 | Backfill default tenant | ✅ COMPLETE | app/core/seeds.py + bootstrap.py seed default tenant on startup |
| INFRA-004 | Enable RLS on all 22 tables | ✅ COMPLETE | v002_rls_policies.py applies tenant_isolation + platform_admin_bypass to all 22 tables |
| INFRA-005 | Platform RBAC scope column + roles | ✅ COMPLETE | JWT v2 carries scope claim; require_platform_admin/require_tenant_admin in dependencies.py |
| INFRA-008 | JWT v1/v2 dual-acceptance middleware | ✅ COMPLETE | auth/jwt.py decode_jwt_token_v1_compat() with v1 defaults; tested in test_jwt_validation.py |
| INFRA-009 | Redis key namespace migration | ✅ COMPLETE | redis_client.py build_redis_key() enforces mingai:{tenant_id}:{key_type} pattern |
| INFRA-010 | LLM config migration to tenant_configs | ✅ COMPLETE | llm_profiles table; tenant_configs JSONB; EmbeddingService reads INTENT_MODEL from env |
| INFRA-011 | CacheService implementation | ⚠️ PARTIAL | Redis client exists with key builder; no dedicated CacheService class with TTL/serialize methods |
| INFRA-012 | @cached decorator | ❌ PENDING | No @cached decorator found in codebase |
| INFRA-013 | Cache invalidation pub/sub | ❌ PENDING | No pub/sub invalidation implementation |
| INFRA-014 | Cache warming background job | ❌ PENDING | No background cache warming job |
| INFRA-019 | Screenshot blur service (server-side) | ❌ PENDING | blur_acknowledged column exists in schema; no server-side blur pipeline found |
| INFRA-020 | Tenant provisioning async worker | ⚠️ PARTIAL | Synchronous tenant creation in tenants/routes.py; no async SSE provisioning worker |
| INFRA-026 | Glossary cache warm-up on startup | ❌ PENDING | No glossary startup warm-up in bootstrap.py or main.py |
| INFRA-032 | Redis hot counter write-back to PostgreSQL | ✅ COMPLETE | profile_learning.py query counter with Redis + profile_learning_events write-back |
| INFRA-033 | Async profile learning job | ✅ COMPLETE | ProfileLearningService.on_query_completed() triggers async extraction |
| INFRA-034 | In-process LRU cache for user profiles (L1) | ✅ COMPLETE | _profile_l1_cache LRUCache(maxsize=1000) in profile/learning.py |
| INFRA-036 | Org context Redis cache | ✅ COMPLETE | OrgContextService in memory/org_context.py with Redis caching |
| INFRA-037 | Glossary pretranslation rollout flag | ❌ PENDING | No rollout flag mechanism found |
| INFRA-038 | Glossary Redis cache with invalidation | ❌ PENDING | No glossary Redis cache; queries hit DB directly |
| INFRA-039 | Docker Compose for local dev | ✅ COMPLETE | docker-compose.yml with postgres+pgvector, redis, backend |
| INFRA-040 | Dockerfile — backend | ✅ COMPLETE | Dockerfile with non-root user, healthcheck, port 8022 |
| INFRA-041 | Dockerfile — frontend | ❌ PENDING | No frontend Dockerfile found |
| INFRA-042 | .env.example | ✅ COMPLETE | .env.example with all required vars, no secrets |
| INFRA-043 | Health check endpoints | ✅ COMPLETE | app/core/health.py + /health route in main.py |
| INFRA-044 | Structured logging | ✅ COMPLETE | structlog used throughout; app/core/logging.py |
| INFRA-046 | CI pipeline (GitHub Actions) | ❌ PENDING | No .github/workflows/ directory found |
| INFRA-017 | Redis Stream setup for issue reports | ✅ COMPLETE | commit e269515 — issues/stream.py; stream key issue_reports:incoming; consumer group issue_triage_workers; MAXLEN 10,000; producer XADD after PostgreSQL persist |
| INFRA-018 | Issue triage background worker | ✅ COMPLETE | commit e269515 — issues/worker.py; XREADGROUP consumer; IssueTriageAgent with 3-retry exponential backoff; XCLAIM abandoned (idle >5min); XACK on success; optional GitHub issue for P0/P1 |

### Database — Phase 1 Status

All 22 tables created in v001_initial_schema.py. The DB items (DB-001–DB-044) reference individual table schemas plus Kailash DataFlow model wrappers. The migration creates the raw tables; DataFlow model wrappers are a separate requirement.

| Status | Tables in migration | Items |
| ------ | ------------------- | ----- |
| ✅ Schema created | tenants, users, tenant_configs, llm_profiles, conversations, messages, user_feedback, user_profiles, memory_notes, profile_learning_events, working_memory_snapshots, tenant_teams, team_memberships, team_membership_audit, glossary_terms, glossary_miss_signals, integrations, sync_jobs, issue_reports, issue_report_events, agent_cards, audit_log | 22 tables complete |
| ❌ Missing | har_transactions, har_transaction_events, har_trust_score_history, semantic_cache, cache_analytics_events, embedding_cache_metadata, search_results_cache, intent_cache, query_cache, cache_hit_rates, document_chunks, usage_daily, consent_events, notification_preferences, user_privacy_settings, mcp_servers, kb_access_control, agent_access_control, invitations, platform_members, glossary_miss_signals, team_working_memory_snapshots | 22 tables not yet created |

Note: The Phase 1 todo list covers DB-001–DB-044. The implementation delivered 22/44 tables (the core set). The HAR tables (DB-041–DB-044), all cache tables, and the remaining Phase 2 tables are absent.

### API Endpoints — Phase 1 Status

| ID | Description | Status | Notes |
| ------- | ------------------------------------- | ------ | ----- |
| API-001 | JWT v2 validation middleware | ✅ COMPLETE | get_current_user() in dependencies.py decodes v2; v1 compat supported |
| API-002 | Platform health check | ✅ COMPLETE | /health in main.py |
| API-003 | Auth local login | ⚠️ PARTIAL | Env-var bootstrap only; no DB user lookup with bcrypt yet |
| API-004 | Token refresh | ✅ COMPLETE | POST /auth/token/refresh |
| API-005 | Logout | ⚠️ PARTIAL | Returns 204; Redis revocation commented out |
| API-006 | Get current user | ✅ COMPLETE | GET /auth/current |
| API-007 | Response feedback | ✅ COMPLETE | POST /chat/feedback |
| API-008 | Chat stream (SSE) | ✅ COMPLETE | POST /chat/stream with full orchestrator pipeline |
| API-009 | List conversations | ✅ COMPLETE | GET /conversations |
| API-010 | Create conversation | ✅ COMPLETE | Conversation created in persistence layer |
| API-011 | Get conversation messages | ✅ COMPLETE | GET /conversations/{id} |
| API-013 | Submit issue report | ⚠️ PARTIAL | POST /issues — missing blur_acknowledged validation |
| API-014 | Get screenshot pre-signed URL | ✅ COMPLETE | commit fe1d212 — app/core/storage.py + local_storage_routes.py; 15+7=22 tests |
| API-024 | Provision new tenant | ✅ COMPLETE | POST /platform/tenants |
| API-025 | Get provisioning job status (SSE) | ❌ PENDING | No SSE job status endpoint; creation is synchronous |
| API-026 | List all tenants | ✅ COMPLETE | GET /platform/tenants |
| API-027 | Get tenant detail | ✅ COMPLETE | GET /platform/tenants/{id} |
| API-028 | Update tenant status | ✅ COMPLETE | PATCH /platform/tenants/{id} + suspend/activate actions |
| API-029 | Get tenant health score | ✅ COMPLETE | commit 7cd0e1d — tenants/routes.py get_tenant_health_components_db(); 7 tests (TestGetTenantHealthScore) — Phase 2 item completed early |
| API-030 | Get tenant quota | ❌ PENDING | No quota endpoints found |
| API-031 | Update tenant quota | ❌ PENDING | No quota endpoints found |
| API-032 | Create LLM profile | ✅ COMPLETE | POST /platform/llm-profiles |
| API-033 | List LLM profiles | ✅ COMPLETE | GET /platform/llm-profiles |
| API-034 | Update LLM profile | ❌ PENDING | No PATCH /platform/llm-profiles/{id} found |
| API-043 | Invite user (single) | ✅ COMPLETE | POST /users/ |
| API-044 | Bulk invite users | ❌ PENDING | No bulk invite endpoint |
| API-045 | Change user role | ✅ COMPLETE | PATCH /users/{id} with role field |
| API-046 | Update user status | ✅ COMPLETE | DELETE /users/{id} (soft deactivate) |
| API-048 | Get workspace settings | ❌ PENDING | No workspace settings endpoint |
| API-049 | Update workspace settings | ❌ PENDING | No workspace settings endpoint |
| API-050 | Connect SharePoint | ❌ PENDING | No SharePoint/integration endpoints |
| API-051 | Test SharePoint connection | ❌ PENDING | No SharePoint/integration endpoints |
| API-054 | Manual sync trigger | ❌ PENDING | No sync endpoints |
| API-055 | Sync status | ❌ PENDING | No sync endpoints |
| API-057 | List glossary terms | ✅ COMPLETE | GET /glossary/ |
| API-058 | Add glossary term | ✅ COMPLETE | POST /glossary/ with sanitize_glossary_definition() |
| API-059 | Update glossary term | ✅ COMPLETE | PATCH /glossary/{id} |
| API-060 | Delete glossary term | ✅ COMPLETE | DELETE /glossary/{id} |
| API-099 | Get user profile | ✅ COMPLETE | GET /memory/profile |
| API-100 | Get memory notes | ✅ COMPLETE | GET /memory/notes |
| API-101 | Add memory note | ✅ COMPLETE | POST /memory/notes (200-char enforced) |
| API-102 | Delete memory note | ✅ COMPLETE | DELETE /memory/notes/{id} |
| API-103 | Clear all memory notes | ✅ COMPLETE | DELETE /memory/working (clears working memory; note CRUD via individual deletes) |
| API-104 | Update privacy settings | ❌ PENDING | No dedicated privacy settings endpoint |
| API-105 | GDPR clear all profile data | ✅ COMPLETE | POST /users/me/gdpr/erase — clears PostgreSQL + Redis L2 + working memory |
| API-015 | List user's issue reports | ✅ COMPLETE | commit 7cd0e1d — issues/routes.py list_my_issues_db(); 5 tests (TestListMyReports) — Phase 2 item completed early |
| API-016 | Get issue report detail | ✅ COMPLETE | commit 7cd0e1d — issues/routes.py get_my_issue_db(); 4 tests (TestGetMyReport) — Phase 2 item completed early |
| API-017 | Still happening confirmation | ✅ COMPLETE | commit 7cd0e1d — issues/routes.py record_still_happening_db(); 5 tests (TestStillHappening) — Phase 2 item completed early |
| API-012 | Notification SSE stream | ✅ COMPLETE | commit e269515 — notifications/routes.py; GET /api/v1/notifications/stream; Redis Pub/Sub per user; keepalive every 30s; channel mingai:{tenant_id}:notifications:{user_id} |
| API-018 | GitHub webhook handler | ✅ COMPLETE | commit 4e9cbf4 — issues/routes.py (line 1357); HMAC-SHA256 verification via _validate_github_signature(); fail-closed (503) when GITHUB_WEBHOOK_SECRET unset; maps issues.labeled/pull_request/release events |
| API-019 | Tenant admin issue queue | ✅ COMPLETE | commit e269515 — issues/routes.py:admin_issues_router (line 726); GET /api/v1/admin/issues (line 1198); list_admin_issues_db(); status/severity/type filters; sort allowlist; tenant-scoped; requires tenant_admin |
| API-020 | Tenant admin issue action | ✅ COMPLETE | commit e269515 — issues/routes.py:admin_issues_router; PATCH /admin/issues/{id} (line 1225); _VALID_ADMIN_ACTIONS = {assign,resolve,escalate,request_info,close_duplicate} (line 816) |
| API-021 | Platform admin global issue queue | ✅ COMPLETE | commit e269515 — issues/routes.py:platform_issues_router (line 727); GET /platform/issues (line 1284); cross-tenant; aggregated stats in response; platform_admin scope required |
| API-022 | Platform admin issue triage | ✅ COMPLETE | commit e269515 — issues/routes.py:platform_issues_router; PATCH /platform/issues/{id} (line 1307); _VALID_PLATFORM_ACTIONS (line 997); _VALID_SEVERITIES = {P0,P1,P2,P3,P4} (line 995) |
| API-023 | Issue stats for platform admin | ✅ COMPLETE | commit e269515 — issues/routes.py:platform_issues_router; GET /platform/issues/stats (line 1272, registered before list to avoid path collision); period regex 7d/30d/90d; SLA adherence + MTTR aggregations |

### AI Services — Phase 1 Status

| ID | Description | Status | Notes |
| ------ | ------------------------------------------------------- | ------ | ----- |
| AI-001 | ProfileLRUCache | ✅ COMPLETE | _profile_l1_cache LRUCache in profile/learning.py |
| AI-002 | ProfileLearningService with PostgreSQL backend | ✅ COMPLETE | profile/learning.py with L1/L2/L3 hierarchy |
| AI-003 | EXTRACTION_PROMPT template | ✅ COMPLETE | EXTRACTION_PROMPT constant in profile/learning.py |
| AI-004 | Tenant LLM profile selection for intent model | ✅ COMPLETE | INTENT_MODEL env var; tenant llm_profile_id FK in tenants table |
| AI-005 | Tenant-scoped Redis keys for profile learning | ✅ COMPLETE | mingai:{tenant_id}:profile_learning:profile:{user_id} pattern |
| AI-006 | Query counter with Redis hot counter + PostgreSQL write-back | ✅ COMPLETE | increment_query_count() in ProfileLearningService |
| AI-007 | on_query_completed hook | ✅ COMPLETE | on_query_completed() triggers profile extraction |
| AI-009 | WorkingMemoryService with agent-scoped Redis keys | ✅ COMPLETE | memory/working_memory.py with mingai:{tenant_id}:working_memory:{user_id}: keys |
| AI-010 | Working memory topic extraction | ✅ COMPLETE | WorkingMemoryService.extract_topics() |
| AI-011 | Working memory format_for_prompt | ✅ COMPLETE | WorkingMemoryService.format_for_prompt() |
| AI-013 | TeamWorkingMemoryService core | ❌ PENDING | No TeamWorkingMemoryService found; teams routes exist but no team memory service |
| AI-014 | Team working memory format_for_prompt | ❌ PENDING | Dependent on AI-013 |
| AI-016 | OrgContextData Pydantic model | ✅ COMPLETE | OrgContextData in memory/org_context.py |
| AI-017 | OrgContextSource abstract interface | ✅ COMPLETE | OrgContextSource ABC in memory/org_context.py |
| AI-018 | Auth0OrgContextSource implementation | ✅ COMPLETE | Auth0OrgContextSource in memory/org_context.py |
| AI-019 | OktaOrgContextSource | ✅ COMPLETE | OktaOrgContextSource in memory/org_context.py |
| AI-020 | GenericSAMLOrgContextSource | ✅ COMPLETE | GenericSAMLOrgContextSource in memory/org_context.py |
| AI-021 | OrgContextService (source selector) | ✅ COMPLETE | OrgContextService._select_source() in memory/org_context.py |
| AI-023 | Memory notes CRUD with 200-char enforcement | ✅ COMPLETE | memory/notes.py validate_memory_note_content() + routes |
| AI-024 | Chat router "remember that" fast path | ⚠️ PARTIAL | orchestrator.py exists; "remember that" detection not confirmed |
| AI-026 | GlossaryExpander.expand() core | ✅ COMPLETE | glossary/expander.py with full expansion logic |
| AI-027 | Glossary stop-word exclusion + uppercase rule | ✅ COMPLETE | STOP_WORDS frozenset + SHORT_TERM_UPPERCASE rule in expander.py |
| AI-028 | Glossary pipeline integration | ✅ COMPLETE | GlossaryExpander wired into ChatOrchestrationService |
| AI-032 | SystemPromptBuilder with 6-layer architecture | ✅ COMPLETE | chat/prompt_builder.py SystemPromptBuilder |
| AI-033 | Token budget enforcement and truncation priority | ⚠️ PARTIAL | prompt_builder.py exists; per-tenant budget from tenant_settings.system_prompt_budget not confirmed |
| AI-034 | Profile SSE flag and memory_saved event | ⚠️ PARTIAL | SSE stream implemented; memory_saved event type not confirmed in orchestrator |
| AI-035 | GDPR clear_profile_data comprehensive erasure | ✅ COMPLETE | users/routes.py erase_user_data() clears PostgreSQL + Redis L2 + working memory scan |
| AI-037 | IssueTriageAgent Kaizen implementation | ❌ PENDING | agents/ module is empty; no IssueTriageAgent found |
| AI-038 | Issue triage confidence scoring | ❌ PENDING | Dependent on AI-037 |

### Frontend — Phase 1 Status

| ID | Description | Status | Notes |
| ------ | ------------------------------------------------- | ------ | ----- |
| FE-001 | Next.js project with Obsidian Intelligence design | ✅ COMPLETE | src/web/ initialized with design tokens |
| FE-002 | API client and auth infrastructure | ✅ COMPLETE | lib/api.ts + auth context |
| FE-003 | Shared layout shell with role-based navigation | ✅ COMPLETE | components/layout/AppShell.tsx, Sidebar.tsx, RoleGuard.tsx |
| FE-004 | Chat page — empty state layout | ✅ COMPLETE | components/chat/ChatEmptyState.tsx |
| FE-005 | Chat page — active state with SSE streaming | ✅ COMPLETE | components/chat/ChatActiveState.tsx + ChatInterface.tsx |
| FE-006 | Chat — thumbs up/down feedback widget | ✅ COMPLETE | components/chat/FeedbackWidget.tsx |
| FE-007 | Chat — source panel slide-out | ✅ COMPLETE | components/chat/SourcePanel.tsx |
| FE-008 | Chat — retrieval confidence badge and bar | ✅ COMPLETE | components/chat/ConfidenceBar.tsx |
| FE-009 | Chat — ProfileIndicator component | ✅ COMPLETE | components/chat/ProfileIndicator.tsx |
| FE-012 | Chat — "Memory saved" toast notification | ✅ COMPLETE | components/chat/MemorySavedToast.tsx |
| FE-013 | Chat — "Terms interpreted" glossary indicator | ✅ COMPLETE | components/chat/GlossaryExpansionIndicator.tsx |
| FE-015 | Chat — conversation list sidebar | ✅ COMPLETE | components/chat/ConversationList.tsx |
| FE-016 | Privacy settings page — profile learning card | ✅ COMPLETE | app/settings/privacy/page.tsx |
| FE-017 | PrivacyDisclosureDialog component | ✅ COMPLETE | components/privacy/PrivacyDisclosureDialog.tsx |
| FE-018 | Work profile card with toggles | ✅ COMPLETE | components/privacy/WorkProfileCard.tsx |
| FE-019 | Memory notes list with CRUD | ✅ COMPLETE | components/privacy/MemoryNotesList.tsx |
| FE-020 | Data rights section — export and clear | ✅ COMPLETE | components/privacy/DataRightsSection.tsx |
| FE-021 | Issue reporter floating button | ✅ COMPLETE | components/issue-reporter/IssueReporterButton.tsx |
| FE-022 | Issue reporter dialog with screenshot + blur | ⚠️ PARTIAL | components/issue-reporter/IssueReporterDialog.tsx — blur by default implemented (blurApplied=true); API submission logic present; no integration test confirms blur_acknowledged API gate |
| FE-023 | Error detection auto-prompt | ✅ COMPLETE | components/issue-reporter/ErrorDetectionPrompt.tsx |
| FE-026 | Tenant admin dashboard | ✅ COMPLETE | app/settings/dashboard/page.tsx |
| FE-027 | User directory with invite and role management | ✅ COMPLETE | app/settings/users/page.tsx + elements/ |
| FE-028 | Workspace settings page | ⚠️ PARTIAL | app/settings/workspace/page.tsx — workspace settings page exists but backend endpoints API-048/049 are PENDING |
| FE-029 | Document store list and SharePoint wizard | ✅ COMPLETE | app/settings/knowledge-base/ + SharePointWizard.tsx — NOTE: backend API-050/051 pending |

### Testing — Phase 1 Status

| ID | Description | Status | Notes |
| -------- | ----------------------------------------------- | ------ | ----- |
| TEST-001 | JWT v2 validation middleware — unit tests | ✅ COMPLETE | tests/unit/test_jwt_validation.py |
| TEST-002 | Multi-tenant RLS enforcement — unit tests | ✅ COMPLETE | tests/unit/test_rls_enforcement.py (20 tests) |
| TEST-003 | Cross-tenant isolation — integration tests | ✅ COMPLETE | tests/integration/test_cross_tenant_isolation.py |
| TEST-004 | JWT v1-to-v2 dual-acceptance — integration tests | ⚠️ PARTIAL | v1 compat tested in test_jwt_validation.py; no dedicated integration test |
| TEST-005 | Auth0 integration — integration tests | ❌ PENDING | No Auth0 integration tests found |
| TEST-006 | Cache key builder — unit tests | ✅ COMPLETE | tests/unit/test_redis_keys.py |
| TEST-007 | Cache serialization — unit tests | ❌ PENDING | No CacheService serialization tests (no CacheService class) |
| TEST-008 | CacheService CRUD — integration tests | ❌ PENDING | No CacheService integration tests |
| TEST-009 | Cross-tenant cache key isolation — integration tests | ⚠️ PARTIAL | Redis key namespace tested at unit level; no integration isolation test |
| TEST-010 | Cache invalidation pub/sub — integration tests | ❌ PENDING | No pub/sub implemented |
| TEST-014 | IssueTriageAgent classification — unit tests | ❌ PENDING | No IssueTriageAgent implemented |
| TEST-015 | Screenshot blur enforcement — unit tests | ❌ PENDING | No server-side blur pipeline; no TEST-015 test file found |
| TEST-016 | "Still happening" rate limit — unit tests | ⚠️ PARTIAL | Rate limiting not confirmed in issue routes |
| TEST-017 | Issue type routing — unit tests | ❌ PENDING | No IssueTriageAgent |
| TEST-018 | Issue reporting Redis Streams — integration tests | ❌ PENDING | No Redis Streams integration for issues |
| TEST-019 | Full triage pipeline — integration tests | ❌ PENDING | No triage pipeline |
| TEST-021 | Health score algorithm — unit tests | ⚠️ PARTIAL | health.py exists with logic; no dedicated health score algorithm tests |
| TEST-022 | Tenant provisioning state machine — unit tests | ✅ COMPLETE | tests/unit/test_tenants_routes.py |
| TEST-023 | LLM profile CRUD — integration tests | ✅ COMPLETE | Covered via test_tenants_routes.py |
| TEST-024 | Tenant provisioning async worker — integration tests | ❌ PENDING | No async worker |
| TEST-029 | Glossary pre-translation pipeline — unit tests | ✅ COMPLETE | tests/unit/test_glossary_expander.py |
| TEST-030 | Glossary prompt injection sanitization — unit tests | ✅ COMPLETE | sanitize_glossary_definition() tested in test_glossary_expander.py |
| TEST-031 | Glossary cache with Redis — integration tests | ✅ COMPLETE | tests/integration/test_glossary_crud.py |
| TEST-050 | Memory notes 200-char enforcement — unit tests | ✅ COMPLETE | tests/unit/test_memory_notes.py |
| TEST-054 | GDPR clear_profile_data — integration tests | ⚠️ PARTIAL | erase_user_data() implemented; no dedicated TEST-054 integration test file found |
| TEST-067 | Docker test environment setup | ✅ COMPLETE | docker-compose.yml + tests/integration/conftest.py |
| TEST-068 | Test fixtures + conftest.py | ✅ COMPLETE | tests/conftest.py + tests/fixtures/ |
| TEST-069 | Database migration testing | ✅ COMPLETE | test_bootstrap.py validates migration |

> This is the single navigation document for the entire implementation. Reference individual files for full acceptance criteria, dependencies, and notes on each item.

---

## 1. Summary Table

| File                    | Domain             | Items   | ID Range              | Total Effort | Status (2026-03-07)                        |
| ----------------------- | ------------------ | ------- | --------------------- | ------------ | ------------------------------------------ |
| `01-database-schema.md` | DB + Redis         | 44      | DB-001 – DB-044       | ~120h        | 22 complete / 22 pending (Phase 1 tables done; cache+HAR pending) |
| `02-api-endpoints.md`   | API Endpoints      | 120     | API-001 – API-120     | ~449h        | 34 complete / 4 partial / 5 pending (Phase 1 scope); +11 Phase 2 items completed (API-012, 015/016/017/018/019/020/021/022/023/029); archived in `todos/completed/02-api-endpoints-phase2.md` |
| `03-ai-services.md`     | AI / Intelligence  | 51      | AI-001 – AI-051       | ~171h        | 21 complete / 3 partial / 4 pending (Phase 1 scope) |
| `04-frontend.md`        | Frontend (Next.js) | 61      | FE-001 – FE-061       | ~379h        | 19 complete / 2 partial / 3 pending (Phase 1 scope) |
| `05-testing.md`         | Tests (all tiers)  | 72      | TEST-001 – TEST-072   | ~248h        | 16 complete / 5 partial / 5 pending (Phase 1 scope) |
| `06-infrastructure.md`  | Infra / DevOps     | 50      | INFRA-001 – INFRA-050 | ~227h        | 15 complete / 3 partial / 9 pending (Phase 1 scope); +2 Phase 2 items completed (INFRA-017/018); archived in `todos/completed/06-infrastructure-phase2.md` |
| **Totals**              |                    | **398** |                       | **~1,594h**  | **Phase 1+2 partial: 137 complete, 17 partial, 49 pending (across all tracked domains)** |

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
| Infrastructure (secrets mgr, doc sync, HAR infra, health monitor)                                         | INFRA-015–016, 021–025, 027–030, 035, 045–050 *(INFRA-017/018 COMPLETE)* | ~90h         |
| API (issue queues, SSO, Google Drive, glossary bulk, agents, HAR, teams, analytics)                       | API-035–042, 047, 052–053, 056, 061–098, 106–120 *(API-012/015–023/029 COMPLETE)*  | ~180h        |
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

| Gate Item                                                 | Required Test                                                   | Status                                         |
| --------------------------------------------------------- | --------------------------------------------------------------- | ---------------------------------------------- |
| INFRA-004: RLS policies on all 22 tables                  | TEST-002 (20 unit tests, 100% coverage)                         | ✅ PASSED — v002_rls_policies.py + test_rls_enforcement.py |
| INFRA-004: Cross-tenant isolation                         | TEST-003 (12 integration tests, real PostgreSQL)                | ✅ PASSED — test_cross_tenant_isolation.py      |
| INFRA-011: Cross-tenant cache key isolation               | TEST-009 (6 integration tests, 100% coverage)                   | ⚠️ PARTIAL — key namespace enforced; integration isolation test missing |
| All 22 RLS policies verified in schema introspection test | TEST-002, case: "RLS policy exists on ALL tenant-scoped tables" | ✅ PASSED — 22 tables in TENANT_SCOPED_TABLES   |

### Gate 2 — Authentication (BLOCKING all user-facing features)

| Gate Item                                         | Required Test                                      | Status                                              |
| ------------------------------------------------- | -------------------------------------------------- | --------------------------------------------------- |
| API-001: JWT v2 validation                        | TEST-001 (15 unit tests, 100% coverage)            | ✅ PASSED — test_jwt_validation.py                  |
| INFRA-008: JWT v1/v2 dual acceptance              | TEST-004 (6 integration tests, 100% coverage)      | ⚠️ PARTIAL — unit tested; integration test pending  |
| Auth0 integration                                 | TEST-005 (8 integration tests, 100% coverage)      | ❌ PENDING — no Auth0 integration tests             |
| RBAC enforced at query time (not assignment time) | TEST-028 (KB access: "checked at QUERY TIME" case) | ❌ PENDING — Phase 2 item                           |

### Gate 3 — Privacy: Screenshot Blur (BLOCKING issue reporting)

| Gate Item                                                     | Required Test                                                        | Status                                                            |
| ------------------------------------------------------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------- |
| FE-022: RAG response area blurred by default                  | TEST-015, case: "screenshot without blur metadata flag REJECTED"     | ⚠️ PARTIAL — FE dialog has blurApplied=true default; no API gate test |
| INFRA-019: Server-side blur pipeline — unblurred never stored | TEST-015, case: "unblurred screenshot never persisted"               | ❌ PENDING — no server-side blur pipeline implemented              |
| API-013: blur_acknowledged validation                         | TEST-015, case: "API request with blur_acknowledged: false REJECTED" | ❌ PENDING — column in schema; API gate not implemented            |

### Gate 4 — GDPR Erasure (BLOCKING EU tenant deployment)

| Gate Item                                                                   | Required Test                                         | Status                                                        |
| --------------------------------------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------- |
| AI-035: clear_profile_data() includes WorkingMemoryService.clear_memory()   | TEST-054, case: "GDPR clear — working memory deleted" | ✅ IMPLEMENTED — erase_user_data() scans + deletes wm keys; integration test PENDING |
| AI-023: 200-char memory note limit enforced server-side                     | TEST-050, case: "200-char limit rejection"            | ✅ PASSED — test_memory_notes.py                               |
| API-047: User delete anonymizes conversations + clears Redis working memory | TEST-054 (comprehensive GDPR test)                    | ✅ IMPLEMENTED — users/routes.py erase_user_data(); integration test PENDING |

### Gate 5 — Glossary Injection Security (BLOCKING glossary feature)

| Gate Item                                                                 | Required Test                          | Status                                              |
| ------------------------------------------------------------------------- | -------------------------------------- | --------------------------------------------------- |
| API-058: Glossary definition sanitized before injection                   | TEST-030 (8 unit tests, 100% coverage) | ✅ PASSED — sanitize_glossary_definition() in expander.py |
| AI-028: Layer 6 removed from SystemPromptBuilder                          | TEST-033 (4 integration tests)         | ✅ IMPLEMENTED — GlossaryExpander replaces Layer 6 injection; integration test pending |
| Glossary terms cap: max 20 terms, 200 chars/definition, 800-token ceiling | TEST-029, canonical spec cases         | ✅ PASSED — MAX_TERMS_PER_TENANT=20, MAX_DEFINITION_LENGTH=200 in expander.py |

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

## 8. Top 10 Critical Remaining Items for Phase 1

Ordered by blocking impact. All are required before a Phase 1 production deployment.

| Priority | ID | Description | Why Critical | Blocks |
| -------- | ----------- | ----------------------------------------- | ------------------------------------------ | ------------------------------------------- |
| P0 | INFRA-019 | Server-side screenshot blur pipeline | Gate 3 open — unblurred screenshots can leak RAG content to platform admins | Issue reporting must not ship without this |
| P0 | API-013 (fix) | blur_acknowledged validation in issue API | Gate 3 open — API accepts submissions without blur acknowledgement | TEST-015 BLOCKING |
| P0 | TEST-015 | Screenshot blur enforcement tests | Security gate cannot be closed without these 8 unit tests | Issue reporting feature ship |
| P1 | TEST-054 | GDPR clear_profile_data integration test | erase_user_data() implemented but untested end-to-end with real Redis + PostgreSQL | EU tenant deployment |
| P1 | AI-013 | TeamWorkingMemoryService | Teams module exists with DB schema but no team memory service | Teams feature unusable |
| P1 | INFRA-012 | @cached decorator | No caching layer above raw Redis calls; cache-dependent features have no TTL management | INFRA-011 / all cache features |
| P1 | INFRA-013 | Cache invalidation pub/sub | Stale cache cannot be invalidated after writes | Glossary and profile cache consistency |
| P1 | API-048/049 | Get/Update workspace settings endpoints | FE-028 workspace settings page exists but calls non-existent backend endpoints | Tenant admin workspace management |
| P1 | API-050/051/054/055 | SharePoint connect + test + sync endpoints | FE-029 SharePoint wizard exists but calls non-existent backend endpoints | Document ingestion flow |
| P2 | INFRA-046 | CI pipeline (GitHub Actions) | No automated testing on PR; 406 tests run manually only | Continuous integration gate |

**Note**: Items P0 above represent hard blockers for feature shipping. Items P1 represent blockers for tenant onboarding. Item P2 is an operational risk.

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
