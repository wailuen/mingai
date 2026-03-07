# mingai — CodeGen Instructions Master Index

**Status**: Post-analysis complete. All 10 implementation plans analyzed. 434 todos created.
**Phase 1 MVP**: ~930h | **Phase 2**: ~664h | **Phase 3+**: ~265h | **Gap remediation**: ~400h additional
**Source reference**: `/Users/wailuen/Development/aihub2` (single-tenant implementation to port and adapt)

---

## Quick Navigation

| File                                 | Purpose                                   | Read When                 |
| ------------------------------------ | ----------------------------------------- | ------------------------- |
| `01-context-loading.md`              | Pre-implementation required reading list  | Before ANY work           |
| `02-backend-worktree.md`             | FastAPI + Kailash SDK backend guide       | Backend implementation    |
| `03-web-worktree.md`                 | Next.js 14 frontend (all 3 role views)    | Frontend implementation   |
| `04-integration-guide.md`            | Full API contract + SSE + Auth0           | Integration work          |
| `05-ai-services.md`                  | All AI services — ChatOrchestration first | AI service implementation |
| `06-testing-guide.md`                | 3-tier testing, security gates            | Any testing work          |
| `07-design-system.md`                | Obsidian Intelligence design system       | Any UI work               |
| `08-from-todos-to-implementation.md` | Todo workflow, agent team, checkpoints    | Starting implementation   |

**Superseded** (do not use): `01-backend-instructions.md`, `02-web-instructions.md`, `03-integration-guide.md`

---

## Project Overview

mingai is an enterprise RAG platform converting from single-tenant (aihub2) to multi-tenant SaaS.
Read aihub2 source at `/Users/wailuen/Development/aihub2` before implementing any feature that already exists there.

### Tech Stack

| Layer     | Technology                                       | Notes                           |
| --------- | ------------------------------------------------ | ------------------------------- |
| Frontend  | Next.js 14 (App Router) + TypeScript + Shadcn/UI | Port 3022                       |
| Backend   | FastAPI + Python 3.11 + Kailash SDK              | Port 8022                       |
| Database  | PostgreSQL + Row-Level Security                  | Kailash DataFlow ORM            |
| Cache     | Redis                                            | `mingai:{tenant_id}:` namespace |
| Auth      | Auth0 (Phase 2+); JWT local dev (Phase 1)        | Per-tenant IdP config           |
| AI Models | From `.env` only — never hardcode                | See env-models rule             |
| Vector    | OpenSearch / Azure AI Search / Vertex            | Via `CLOUD_PROVIDER`            |
| Object    | S3 / Azure Blob / GCS                            | Via `CLOUD_PROVIDER`            |

### Cloud Provider

Select all cloud services via `CLOUD_PROVIDER` env var:

```
CLOUD_PROVIDER=aws    → Aurora PostgreSQL, OpenSearch, S3
CLOUD_PROVIDER=azure  → Azure DB for PostgreSQL, Azure AI Search, Azure Blob
CLOUD_PROVIDER=gcp    → Cloud SQL, Vertex AI Search, GCS
CLOUD_PROVIDER=local  → Local PostgreSQL, Weaviate (Docker), MinIO (Docker)
```

---

## Phase Structure

### Phase 1 MVP — Build This First

Core platform: multi-tenant isolation, full RAG pipeline, profile/memory, chat, tenant management.

**Non-negotiable Phase 1 deliverables**:

1. 22 PostgreSQL tables with RLS (DB-001 through DB-022)
2. CORS + security headers (INFRA-051, INFRA-052) — day-1 showstoppers
3. ChatOrchestrationService (AI-056) — most critical service, nothing works without it
4. EmbeddingService + VectorSearchService (AI-054, AI-055)
5. ProfileLearningService + WorkingMemoryService (AI-001 through AI-020)
6. GlossaryExpander + SystemPromptBuilder 6-layer (AI-031 through AI-051)
7. All 125 API endpoints (API-001 through API-125)
8. 3 role UIs: End User / Tenant Admin / Platform Admin
9. GDPR: `clear_profile_data()` clears ALL 3 stores including working memory (aihub2 bug fix)
10. Security gates (see `06-testing-guide.md`) — all 7 must pass before deployment

### Phase 2 — After Phase 1 Validated

Agent-scoped memory, Team working memory, Auth0 SSO, HAR Phase 0-1.

### Phase 3+ — After Phase 2

HAR Phase 2 (blockchain), issue reporting advanced features, mobile app.

---

## Canonical Specifications (Never Deviate)

### Token Budget

| Layer                               | Budget           | Critical Note                                    |
| ----------------------------------- | ---------------- | ------------------------------------------------ |
| Layer 2: Org Context                | **100 tokens**   | NOT 500 — right-sized from actual 70-token usage |
| Layer 3: Profile Context            | **200 tokens**   | Global profile + top 5 memory notes              |
| Layer 4a: Individual Working Memory | **100 tokens**   | Agent-scoped                                     |
| Layer 4b: Team Working Memory       | **150 tokens**   | 0 if no active team                              |
| Layer 5: RAG Domain Context         | remaining        |                                                  |
| Layer 6: Glossary                   | **0 tokens**     | REMOVED — pre-translated inline in query         |
| **Total overhead (Layers 2-4b)**    | **550 tokens**   |                                                  |
| **RAG at 2K query budget**          | **1,450 tokens** |                                                  |

Any document referencing "500 tokens" for Org Context is wrong. Canonical = 100 tokens.

### Memory Limits

| Item                       | Value                                                            |
| -------------------------- | ---------------------------------------------------------------- |
| Memory notes max           | 15 (oldest pruned)                                               |
| Notes injected to prompt   | Top 5, newest first                                              |
| Max note content           | **200 chars** (enforce in backend — aihub2 did NOT enforce this) |
| Working memory max topics  | 5                                                                |
| Working memory max queries | 3 (100-char truncation)                                          |
| Working memory TTL         | 7 days default                                                   |
| Profile learning trigger   | Every 10 queries                                                 |

### Redis Key Namespace

Pattern: `mingai:{tenant_id}:{key_type}:{...}`

```
mingai:{tenant_id}:working_memory:{user_id}:{agent_id}     TTL: 7 days
mingai:{tenant_id}:team_memory:{team_id}                   TTL: 7 days
mingai:{tenant_id}:profile_learning:query_count:{user_id}  TTL: 30 days
mingai:{tenant_id}:profile_learning:profile:{user_id}      TTL: 1 hour
mingai:{tenant_id}:org_context:{user_id}                   TTL: 24 hours
mingai:{tenant_id}:session:{user_id}:active_team           TTL: session
mingai:{tenant_id}:glossary:terms                          TTL: 1 hour
mingai:{tenant_id}:embedding_cache:{hash}                  TTL: 24 hours
mingai:{tenant_id}:llm_cache:{hash}                        TTL: 1 hour
```

No user data may use tenant-unscoped Redis keys.

### Other Canonical Values

| Spec                            | Value                  | Source                                     |
| ------------------------------- | ---------------------- | ------------------------------------------ |
| Retrieval confidence label      | "retrieval confidence" | Not "AI confidence" or "answer quality"    |
| RBAC enforcement timing         | Query execution        | NOT assignment time                        |
| HAR blockchain phase            | Phase 2 only           | Phase 0-1 = signed traditional log         |
| HAR human approval threshold    | $5,000 default         | Configurable per tenant                    |
| Auth0 group sync                | Allowlist-gated        | Empty allowlist = no auto-sync by default  |
| Team memory attribution         | "a team member"        | No user ID or display name in Redis        |
| Issue reporting adoption target | Voluntary ≥5%          | Auto-triggered ≥10% of error events        |
| Screenshot blur                 | Blurred by default     | User must explicitly un-blur before upload |
| CredentialTestResult.passed     | None (not True)        | For untested integrations                  |
| Seed templates                  | 4 shipped in codebase  | HR, IT Helpdesk, Procurement, Onboarding   |

---

## Todo Files

All implementation tasks tracked in `todos/active/`:

| File                    | Todo IDs               | Count | Effort |
| ----------------------- | ---------------------- | ----- | ------ |
| `01-database-schema.md` | DB-001 to DB-045       | 45    | ~120h  |
| `02-api-endpoints.md`   | API-001 to API-125     | 125   | ~466h  |
| `03-ai-services.md`     | AI-001 to AI-060       | 60    | ~243h  |
| `04-frontend.md`        | FE-001 to FE-063       | 63    | ~388h  |
| `05-testing.md`         | TEST-001 to TEST-074   | 74    | ~260h  |
| `06-infrastructure.md`  | INFRA-001 to INFRA-067 | 67    | ~309h  |
| `07-gap-analysis.md`    | 62 gaps by severity    | —     | ~400h  |

---

## Critical Implementation Path

Implement in this order to avoid blockers:

1. **INFRA-051** CORS — nothing works without it
2. **DB-001 to DB-022** — 22 tables with RLS
3. **AI-056** ChatOrchestrationService — core RAG orchestrator
4. **AI-054, AI-055** EmbeddingService + VectorSearchService
5. **API-001 to API-010** Auth endpoints
6. **AI-001 to AI-020** ProfileLearning + WorkingMemory
7. **AI-031 to AI-051** GlossaryExpander + SystemPromptBuilder
8. **API-011 to API-125** All remaining endpoints
9. **FE-001 to FE-063** Frontend
10. **TEST-001 to TEST-074** Tests + security gates

---

## Mandatory Review Gates

- **Code review** (intermediate-reviewer) after EVERY file change
- **Security review** (security-reviewer) before EVERY commit
- **Security gates** (see `06-testing-guide.md`) before ANY deployment
