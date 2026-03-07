# 08 — From Todos to Implementation

**This is the operational workflow guide for running the implementation.**

Read this before starting any implementation work.

---

## 1. Pre-Implementation Approval

The todos in `todos/active/` represent the complete implementation plan approved by the user.
**Do NOT deviate from the todo structure without user approval.**

If you discover a gap not captured in the todos:

1. Document it in `todos/active/07-gap-analysis.md` under the appropriate severity level
2. Ask the user for approval before implementing
3. Only after approval: add a new todo ID and implement

---

## 2. How to Use the Todo System

### Reading Todos

Every todo follows this format:

```markdown
### DB-001: Enable Row-Level Security on all tables

**Priority**: CRITICAL
**Phase**: 1 (MVP)
**Effort**: 2h
**Dependencies**: DB-000 (migrations complete)
**Acceptance criteria**:

- [ ] RLS enabled on all 22 tables
- [ ] `USING (tenant_id = current_setting('app.current_tenant_id')::uuid)` policy
- [ ] Integration test: cross-tenant read returns 0 rows
```

### Marking Todos Complete

When you complete a todo:

1. Update the checkbox: `- [x] Criterion`
2. Add completion note: `**Completed**: 2026-03-07 by backend-agent`
3. If tests were written, reference them: `**Tests**: tests/integration/test_rls.py`

### Todo Priority Order

Implement in priority order within each phase:

1. CRITICAL (deployment blocker) → implement immediately
2. HIGH (phase blocker) → implement before phase complete
3. MEDIUM → implement after HIGH items done
4. LOW → Phase 2+ unless time allows

---

## 3. Agent Team Assignment

### Recommended Agent → Task Mapping

| Agent                 | Primary Todos                               |
| --------------------- | ------------------------------------------- |
| dataflow-specialist   | DB-001 to DB-045 (all database work)        |
| nexus-specialist      | API-001 to API-125 (all API endpoints)      |
| kaizen-specialist     | AI-001 to AI-060 (all AI services)          |
| react-specialist      | FE-001 to FE-063 (all frontend)             |
| testing-specialist    | TEST-001 to TEST-074 (all tests)            |
| deployment-specialist | INFRA-001 to INFRA-067 (all infrastructure) |

### Parallel Execution

Independent todo files can run in parallel across agents:

```
Day 1-5 (parallel):
  - Agent A: DB-001 to DB-022 (schema)
  - Agent B: INFRA-001 to INFRA-010 (project setup, Docker, CORS)

Day 6-10 (parallel after DB complete):
  - Agent C: AI-056 (ChatOrchestrationService) — most critical
  - Agent D: AI-054, AI-055 (Embedding, VectorSearch)
  - Agent E: API-001 to API-010 (Auth endpoints)

Day 11-15 (parallel):
  - Agent F: AI-001 to AI-020 (Profile + Working Memory)
  - Agent G: API-011 to API-050 (Chat, Memory endpoints)
  - Agent H: DB-023 to DB-045 (remaining DB work)

Day 16-25 (parallel):
  - Agent I: FE-001 to FE-063 (all frontend)
  - Agent J: API-051 to API-125 (remaining endpoints)
  - Agent K: AI-021 to AI-060 (remaining AI services)

Day 26-30:
  - All agents: TEST-001 to TEST-074 (testing)
  - Security gates: run all 7 gates
```

---

## 4. Implementation Standards Per Todo

Every implementation task MUST follow:

### Before Writing Code

1. Read the relevant plan document (listed in todo's `Source` field)
2. Read existing aihub2 implementation (if porting)
3. Consult the appropriate specialist agent (dataflow-specialist, nexus-specialist, etc.)

### While Writing Code

1. Check Kailash SDK patterns first (see `rules/patterns.md`)
2. All Redis keys: `mingai:{tenant_id}:{type}:{...}` pattern
3. All DB queries: via DataFlow ORM (never raw SQL except migrations)
4. All model names: from `.env` (never hardcode)
5. All user input: validated at API boundary

### After Writing Code

1. Write tests BEFORE or ALONGSIDE implementation (TDD)
2. Delegate to **intermediate-reviewer** (mandatory — agents.md Rule 1)
3. Address all review findings
4. Run tests locally

### Before Committing

1. Delegate to **security-reviewer** (mandatory — agents.md Rule 2)
2. Address all CRITICAL security findings
3. Document any HIGH findings

---

## 5. Implementation Sequence: Phase 1 Detailed

### Week 1-2: Foundation

```
INFRA-001: Docker Compose setup (PostgreSQL + Redis + backend + frontend)
INFRA-051: CORS configuration (day-1 gate)
INFRA-052: Security headers middleware
DB-001 to DB-022: 22 PostgreSQL tables with RLS
DB-023 to DB-030: Alembic migrations (001-005)
DB-031 to DB-035: DataFlow models for all tables
TEST-073: Migration up/down tests (TEST-073 written first — TDD)
```

**Gate**: All migrations pass, RLS canary test passes.

### Week 3-5: AI Services Core

```
AI-056: ChatOrchestrationService (MOST CRITICAL — implement first)
AI-054: EmbeddingService (Redis caching, CLOUD_PROVIDER abstraction)
AI-055: VectorSearchService (tenant-isolated indexes)
AI-059: ConversationPersistenceService
API-001 to API-010: Auth endpoints (JWT validation)
```

**Gate**: Chat endpoint streams successfully end-to-end.

### Week 6-8: Profile + Memory

```
AI-001 to AI-010: ProfileLearningService (port from aihub2)
AI-011 to AI-020: WorkingMemoryService (port from aihub2)
AI-021 to AI-030: OrgContextService + OrgContextSource abstraction
AI-031 to AI-040: GlossaryExpander
AI-041 to AI-051: SystemPromptBuilder (6 layers)
DB-036 to DB-045: Memory tables (user_profiles, memory_notes, etc.)
```

**Gate**: Full prompt pipeline assembles correctly at 550-token overhead.

### Week 9-11: API Layer

```
API-011 to API-040: Chat, Memory, Profile endpoints
API-041 to API-065: Users, Teams endpoints
API-066 to API-090: Knowledge Base, Glossary endpoints
API-091 to API-120: Platform Admin, Memory Policy endpoints
API-121 to API-125: Webhooks, error handlers
```

**Gate**: All 125 endpoints return correct responses with correct auth gates.

### Week 12-14: Frontend

```
FE-001 to FE-010: Project setup, design system, auth
FE-011 to FE-030: End User views (chat, sources, feedback)
FE-031 to FE-050: Tenant Admin views (users, teams, glossary, memory)
FE-051 to FE-063: Platform Admin views + Error Boundaries + SafeHTML
```

**Gate**: All 3 role views functional with real backend.

### Week 15-16: Testing + Security Gates

```
TEST-001 to TEST-020: Unit tests (ProfileLearning, WorkingMemory, GlossaryExpander)
TEST-021 to TEST-040: Integration tests (RLS, GDPR, CORS, rate limiting)
TEST-041 to TEST-060: E2E tests (critical user flows, cross-tenant isolation)
TEST-061 to TEST-074: Load tests, migration tests
7 Security gates: ALL must pass
```

**Gate**: All 7 security gates pass. All test suites green. Coverage targets met.

---

## 6. Handling Blockers

If a blocker is encountered:

1. **Missing implementation**: Implement it (no-stubs rule — `rules/no-stubs.md`)
2. **Missing record (404/403)**: Create the record (god-mode rule — `rules/e2e-god-mode.md`)
3. **Missing endpoint**: Implement the endpoint (god-mode rule)
4. **Architecture question**: Consult appropriate specialist agent
5. **Canonical spec unclear**: Read the source plan document; if still unclear, ask user

**Never**:

- Skip a task and mark it "gap" or "limitation"
- Add stubs or TODOs
- Mock Tier 2/3 tests
- Move on after a graceful failure without investigating

---

## 7. Quality Checkpoints

### Checkpoint 1: After Schema (End of Week 2)

Review with user before proceeding to AI services:

- [ ] All 22 tables created with RLS
- [ ] Alembic migrations reversible
- [ ] RLS canary test passes
- [ ] DataFlow models cover all tables

### Checkpoint 2: After Chat Pipeline (End of Week 5)

Review with user before proceeding to full API:

- [ ] `POST /api/v1/chat/stream` streams SSE correctly
- [ ] All 8 pipeline stages execute in order
- [ ] Retrieval confidence calculated and emitted
- [ ] Working memory updated after each query

### Checkpoint 3: After API Layer (End of Week 11)

Review with user before frontend:

- [ ] All 125 endpoints operational
- [ ] All auth gates enforced
- [ ] GDPR erasure clears all 3 stores
- [ ] Memory note 200-char limit enforced

### Checkpoint 4: Phase 1 Complete (End of Week 16)

Final review before deployment:

- [ ] All 7 security gates pass
- [ ] Coverage targets met
- [ ] All E2E tests green
- [ ] Load test: 100 concurrent users, p95 < 3s

---

## 8. Documentation Updates Required

After implementing each major feature, update:

```
workspaces/mingai/04-codegen-instructions/  ← update if pattern changes
todos/active/                               ← mark todos complete
CLAUDE.md memory files                      ← if architectural decisions change
```

If implementing a new reusable pattern, consider creating a skill:

- Kailash DataFlow patterns → consult `02-dataflow` skill
- Nexus API patterns → consult `03-nexus` skill
- Testing patterns → consult `12-testing-strategies` skill

---

## 9. Seed Data

Phase 1 ships with 4 seed templates (not dependent on platform admin):

| Template    | agent_type  | File                             |
| ----------- | ----------- | -------------------------------- |
| HR Policy   | hr_policy   | `seeds/templates/hr_policy.py`   |
| IT Helpdesk | it_helpdesk | `seeds/templates/it_helpdesk.py` |
| Procurement | procurement | `seeds/templates/procurement.py` |
| Onboarding  | onboarding  | `seeds/templates/onboarding.py`  |

Apply via migration 005 or a separate seed script. These must be in the codebase, not created via admin UI.

Platform admin bootstrap (INFRA-066) creates:

1. First platform admin user (from env vars: `PLATFORM_ADMIN_EMAIL`, `PLATFORM_ADMIN_PASS`)
2. First LLM profile (from env: `PRIMARY_MODEL`, `INTENT_MODEL`, `EMBEDDING_MODEL`)
3. Seed tenant for local testing (from env: `SEED_TENANT_NAME`)

---

## 10. Definition of Done: Phase 1

Phase 1 is complete when ALL of the following are true:

**Backend**:

- [ ] 22 tables with RLS in production
- [ ] All 125 API endpoints operational
- [ ] ChatOrchestrationService streams correctly
- [ ] ProfileLearningService triggers at 10 queries
- [ ] GlossaryExpander replaces Layer 6 (0 tokens in system prompt)
- [ ] SystemPromptBuilder: 550 token overhead at 2K budget
- [ ] GDPR: clear_profile_data() clears all 3 stores
- [ ] GDPR: 200-char memory note limit enforced
- [ ] Auth0 group sync allowlist-gated
- [ ] All background jobs operational (provisioning < 10 min)

**Frontend**:

- [ ] End User: chat with SSE streaming, source panel, confidence bar
- [ ] End User: GlossaryExpansionIndicator on every response with expansions
- [ ] End User: PrivacyDisclosureDialog on first profile use (not consent gate)
- [ ] Tenant Admin: all settings pages operational
- [ ] Platform Admin: tenant provisioning wizard < 10 min
- [ ] Error Boundaries on all major sections
- [ ] SafeHTML on all user-generated content (no raw dangerouslySetInnerHTML)

**Security**:

- [ ] All 7 security gates pass
- [ ] CORS: no wildcard origin
- [ ] Rate limiting: 30/min chat, 10/min auth
- [ ] Security headers: X-Content-Type-Options, X-Frame-Options, HSTS, CSP

**Testing**:

- [ ] Coverage: general 80%, auth/GDPR/RLS/HAR-financial 100%
- [ ] All unit tests pass (>120 tests)
- [ ] All integration tests pass (>50 tests)
- [ ] All E2E tests pass (>30 flows)
- [ ] Load test: 100 concurrent, p95 < 3s

**Infrastructure**:

- [ ] Docker Compose works for local dev
- [ ] CI pipeline green (unit → integration → E2E)
- [ ] DB backup tested (restore verified)
- [ ] Monitoring: structured logs, metrics, alerting
- [ ] Runbook: incident response documented
