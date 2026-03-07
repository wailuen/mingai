# 01 — Pre-Implementation Context Loading

**Read this before starting ANY implementation work.**

Every CodeGen agent MUST complete this checklist before writing a single line of code.
Failure to read the required context will result in architectural violations that are expensive to fix.

---

## Step 1: Load Project Memory

Read these files in order:

```
workspaces/mingai/04-codegen-instructions/00-README.md   ← master overview (you are here)
todos/active/00-master-index.md                          ← implementation master index
todos/active/07-gap-analysis.md                          ← 62 critical gaps to avoid
```

---

## Step 2: Architecture Reference (Required for ALL agents)

Read these architecture documents before implementing anything:

| Document                                                                         | What It Defines                    | Critical For                                 |
| -------------------------------------------------------------------------------- | ---------------------------------- | -------------------------------------------- |
| `workspaces/mingai/01-analysis/01-research/36-profile-memory-architecture.md`    | Profile/memory technical reference | AI services, chat pipeline                   |
| `workspaces/mingai/01-analysis/13-profile-memory/04-implementation-alignment.md` | aihub2 → mingai adaptation spec    | Any memory/profile work                      |
| `workspaces/mingai/02-plans/08-profile-memory-plan.md`                           | Profile & memory sprint plan       | ProfileLearningService, WorkingMemoryService |
| `workspaces/mingai/02-plans/09-glossary-pretranslation-plan.md`                  | GlossaryExpander implementation    | Glossary pre-translation                     |
| `workspaces/mingai/02-plans/10-teams-collaboration-plan.md`                      | Teams + team working memory        | TeamWorkingMemoryService                     |

---

## Step 3: Domain-Specific Reading (Load Based on Your Task)

### If implementing DATABASE work (DB-001 to DB-045):

```
workspaces/mingai/01-analysis/01-research/12-database-architecture-analysis.md
workspaces/mingai/02-plans/01-implementation-roadmap.md (schema section)
todos/active/01-database-schema.md
```

Key rules:

- ALL tables MUST have `tenant_id UUID NOT NULL` + RLS policy
- RLS policy: `USING (tenant_id = current_setting('app.current_tenant_id')::uuid)`
- Primary key always named `id`
- Timestamps: `created_at TIMESTAMPTZ DEFAULT NOW()`, `updated_at TIMESTAMPTZ DEFAULT NOW()`
- Never manually set timestamps in application code
- Memory notes: NORMALIZED table (not embedded in user_profiles document)
- `memory_notes.agent_id` is nullable (NULL = global note)

### If implementing AI SERVICES (AI-001 to AI-060):

```
workspaces/mingai/01-analysis/13-profile-memory/04-implementation-alignment.md
workspaces/mingai/02-plans/08-profile-memory-plan.md
workspaces/mingai/02-plans/09-glossary-pretranslation-plan.md
workspaces/mingai/02-plans/10-teams-collaboration-plan.md
todos/active/03-ai-services.md
/Users/wailuen/Development/aihub2/  ← read existing implementations before porting
```

Start with AI-056 (ChatOrchestrationService) — everything else depends on it.

Critical: GDPR bug in aihub2 `clear_profile_data()` — it does NOT clear working memory. MUST fix in mingai.

### If implementing API ENDPOINTS (API-001 to API-125):

```
workspaces/mingai/03-user-flows/10-issue-reporting-flows.md
workspaces/mingai/03-user-flows/11-platform-admin-ops-flows.md
workspaces/mingai/03-user-flows/12-tenant-admin-flows.md
workspaces/mingai/03-user-flows/13-agent-registry-flows.md
workspaces/mingai/04-codegen-instructions/04-integration-guide.md
todos/active/02-api-endpoints.md
```

### If implementing FRONTEND (FE-001 to FE-063):

```
workspaces/mingai/design/01-design-language.md              ← Obsidian Intelligence design system
workspaces/mingai/04-codegen-instructions/07-design-system.md  ← implementation reference
workspaces/mingai/03-user-flows/12-tenant-admin-flows.md
workspaces/mingai/03-user-flows/11-platform-admin-ops-flows.md
workspaces/mingai/04-codegen-instructions/04-integration-guide.md
todos/active/04-frontend.md
```

### If implementing INFRASTRUCTURE (INFRA-001 to INFRA-067):

```
workspaces/mingai/01-analysis/01-research/29-issue-reporting-architecture.md
workspaces/mingai/02-plans/03-caching-implementation-plan.md
todos/active/06-infrastructure.md
```

Start with INFRA-051 (CORS) — day-1 showstopper.

### If implementing TESTING (TEST-001 to TEST-074):

```
workspaces/mingai/04-codegen-instructions/06-testing-guide.md
todos/active/05-testing.md
```

### If implementing HAR (Hosted Agent Registry):

```
workspaces/mingai/01-analysis/01-research/32-hosted-agent-registry-architecture.md
workspaces/mingai/01-analysis/12-agent-registry/03-unique-selling-points.md
workspaces/mingai/02-plans/07-agent-registry-plan.md
workspaces/mingai/03-user-flows/13-agent-registry-flows.md
```

Phase 0-1 only: NO blockchain. Ed25519 signature chaining only.

---

## Step 4: Internalize the Non-Negotiable Rules

Before writing any code, confirm you understand these:

### Security Rules (Violation = Block commit)

1. All API keys and model names from `.env` — NEVER hardcode
2. All Redis keys prefixed `mingai:{tenant_id}:` — NEVER tenant-unscoped
3. All PostgreSQL queries filtered by `tenant_id` via RLS — NEVER bypass RLS
4. CORS: allow only `FRONTEND_URL` env var — NEVER wildcard origin
5. No `eval()`, `exec()`, `shell=True` on user input
6. No PII or secrets in logs
7. All user input validated (type, length, format) at API boundary
8. Output encoded: use `DOMPurify.sanitize()` on user-generated content in UI
9. Auth0 Management API tokens refresh before expiry — never cache indefinitely

### Architecture Rules (Violation = Review failure)

1. Check Kailash SDK before writing custom code:
   - Database work → DataFlow (not raw SQLAlchemy)
   - API work → Nexus (not raw FastAPI routes)
   - Agent work → Kaizen (not custom agent loops)
2. `runtime.execute(workflow.build())` — always `.build()`, always unpack `(results, run_id)`
3. String-based node IDs only — no variables or f-strings
4. Absolute imports: `from kailash.workflow.builder import WorkflowBuilder`
5. RLS set via `SET LOCAL app.current_tenant_id = '{tenant_id}'` in every DB transaction
6. Async FastAPI → `AsyncLocalRuntime`, scripts → `LocalRuntime`

### Testing Rules (Violation = Tests invalid)

1. Tier 1 (unit): mocking allowed
2. Tier 2 (integration): NO mocking — real PostgreSQL + Redis
3. Tier 3 (E2E): NO mocking — real browser + real backend
4. Coverage minimums: general 80%, auth/security/financial 100%
5. Tests written BEFORE implementation (TDD)

### GDPR Rules (Violation = Critical compliance failure)

1. `clear_profile_data(user_id, tenant_id)` MUST delete from:
   - `user_profiles` table (PostgreSQL)
   - `memory_notes` table (PostgreSQL)
   - `profile_learning_events` table (PostgreSQL)
   - Redis L1 cache (ProfileLRUCache in process memory)
   - Redis L2 cache (`mingai:{tenant_id}:profile_learning:profile:{user_id}`)
   - Working memory (`mingai:{tenant_id}:working_memory:{user_id}:*`)
   - Org context cache (`mingai:{tenant_id}:org_context:{user_id}`)
2. `export_profile_data()` must include all three stores
3. `PrivacyDisclosureDialog` shown on first profile use — transparency only (NOT a consent gate)
4. Screenshot RAG response areas: BLURRED by default before user uploads to issue report

---

## Step 5: Read aihub2 Source for Portability

The following aihub2 components can be ported with minimal change:

| Component                                  | aihub2 File           | Change Needed        |
| ------------------------------------------ | --------------------- | -------------------- |
| `ProfileLRUCache`                          | `profile_learning.py` | None — pure Python   |
| `WorkingMemoryService._extract_topics()`   | `working_memory.py`   | None — pure NLP      |
| `WorkingMemoryService.format_for_prompt()` | `working_memory.py`   | None                 |
| Memory intent detection regex              | `chat/router.py`      | None                 |
| `MemoryNote` Pydantic schema               | `schemas.py`          | Add `agent_id` field |
| `EXTRACTION_PROMPT`                        | `profile_learning.py` | None                 |
| `MemoryNotesList.tsx`                      | `components/memory/`  | Add agent badge      |
| `useUserMemory.ts`                         | `hooks/`              | None                 |

The following require significant adaptation:

| Component                 | Change Required                                                     |
| ------------------------- | ------------------------------------------------------------------- |
| `ProfileLearningService`  | Replace CosmosDB with DataFlow + PostgreSQL                         |
| `WorkingMemoryService`    | Add `{tenant_id}:` Redis prefix + `{agent_id}` in key               |
| `OrgContextService`       | Replace Azure AD hardcoding with `OrgContextSource` abstraction     |
| LLM client initialization | Replace `get_intent_openai_client()` with tenant LLM profile config |
| `clear_profile_data()`    | Add working memory clear (GDPR bug fix)                             |
| All Redis keys            | Add `mingai:{tenant_id}:` prefix                                    |

---

## Step 6: Verify Environment Before Starting

Before running any code:

```bash
# Backend
cp src/backend/.env.example src/backend/.env
# Fill in: DATABASE_URL, REDIS_URL, CLOUD_PROVIDER, PRIMARY_MODEL, INTENT_MODEL,
#          EMBEDDING_MODEL, JWT_SECRET_KEY, FRONTEND_URL

# Verify models are in .env (never hardcode)
grep PRIMARY_MODEL src/backend/.env
grep INTENT_MODEL src/backend/.env
grep EMBEDDING_MODEL src/backend/.env

# Frontend
cp src/web/.env.local.example src/web/.env.local
# Fill in: NEXT_PUBLIC_API_URL, AUTH0_DOMAIN (Phase 2+)
```

---

## Step 7: Confirm Readiness Checklist

Before writing first line of code:

- [ ] Read 00-README.md and this file
- [ ] Read todos/active/00-master-index.md
- [ ] Read domain-specific plans for your task area
- [ ] Read relevant aihub2 source files
- [ ] Understand canonical specs (token budget, Redis namespace, GDPR requirements)
- [ ] .env file exists and validated
- [ ] Kailash SDK installed: `pip install kailash kailash-dataflow kailash-nexus kailash-kaizen`
- [ ] PostgreSQL running and accessible
- [ ] Redis running and accessible
