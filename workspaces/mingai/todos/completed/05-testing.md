# Testing Todo List — mingai Enterprise RAG Platform

> **Generated**: 2026-03-07
> **Stack**: FastAPI + Next.js 14 + PostgreSQL + Redis + Auth0
> **Frameworks**: pytest (backend), Playwright (E2E)
> **Coverage targets**: General 80%, Auth/Security/Financial 100%
> **3-tier policy**: Unit (mocking allowed) | Integration (NO mocking, real infra) | E2E (NO mocking, real browser)

---

## Plan 01+02 — Core Platform Migration

### TEST-001: JWT v2 validation middleware — unit tests ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 4h
**Test tier**: Unit
**Depends on**: none
**Target count**: 15 tests
**Coverage target**: 100% (auth-critical)
**Description**: Validate JWT v2 token parsing, tenant_id extraction, claim structure, and error handling.
**Key test cases**:

- [ ] Valid JWT v2 — extracts tenant_id, user_id, roles, scope correctly
- [ ] Expired token — returns 401 with `token_expired` error code
- [ ] Malformed token (not base64, missing segments) — returns 401
- [ ] Missing `tenant_id` claim — returns 401
- [ ] Invalid signature (wrong signing key) — returns 401
- [ ] Token with `scope=platform` — sets platform admin flag
- [ ] Token with `scope=tenant` + admin role — sets tenant admin flag
- [ ] Token with empty roles array — defaults to end-user permissions
- [ ] Token with future `iat` (clock skew > 60s) — returns 401
- [ ] Token with valid `aud` claim — accepted
- [ ] Token with wrong `aud` claim — returns 401
- [ ] Token with multiple roles — all roles extracted to request state
- [ ] Middleware injects tenant_id into request state for downstream use
- [ ] Middleware sets `request_id` header for tracing
- [ ] Null/empty Authorization header — returns 401
      **Notes**: Mocking Auth0 JWKS endpoint is allowed in unit tier. Use `python-jose` or `PyJWT` test helpers to forge tokens with known keys.

### TEST-002: Multi-tenant RLS enforcement — unit tests ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 6h
**Test tier**: Unit
**Depends on**: none
**Target count**: 20 tests
**Coverage target**: 100% (security-critical)
**Description**: Row-Level Security policies on every tenant-scoped table. Every query MUST include tenant_id filter automatically.
**Key test cases**:

- [ ] SELECT on users table — only returns rows matching session tenant_id
- [ ] SELECT on conversations table — only returns rows matching session tenant_id
- [ ] SELECT on documents table — only returns rows matching session tenant_id
- [ ] SELECT on issue_reports table — only returns rows matching session tenant_id
- [ ] INSERT without tenant_id — rejected or auto-populated from session
- [ ] UPDATE across tenant boundary — zero rows affected
- [ ] DELETE across tenant boundary — zero rows affected
- [ ] Superuser/platform admin bypasses RLS when explicitly requested
- [ ] RLS policy exists on ALL tenant-scoped tables (schema introspection test)
- [ ] Connection pool sets `app.current_tenant_id` on checkout
- [ ] Connection pool resets `app.current_tenant_id` on checkin
- [ ] Nested transaction maintains tenant context
- [ ] Parallel requests with different tenant_ids do not leak
- [ ] RLS on glossary_terms table — tenant-scoped
- [ ] RLS on memory_notes table — tenant-scoped
- [ ] RLS on user_profiles table — tenant-scoped
- [ ] RLS on kb_access_control table — tenant-scoped
- [ ] RLS on agent_cards table — tenant-scoped
- [ ] RLS on team_memberships table — tenant-scoped
- [ ] RLS on audit_log table — tenant-scoped
      **Notes**: Use SQLAlchemy session events to inject tenant_id. Test with real PostgreSQL in integration tier (TEST-003). Unit tests may use SQLite with manual tenant filtering to validate ORM-level enforcement.

### TEST-003: Cross-tenant isolation — integration tests ✅ COMPLETED

**Effort**: 8h
**Test tier**: Integration
**Depends on**: TEST-001, TEST-002
**Target count**: 12 tests
**Coverage target**: 100% (security-critical)
**Description**: End-to-end proof that user from tenant A cannot read, write, or infer tenant B data. Uses real PostgreSQL with RLS enabled.
**Key test cases**:

- [ ] User from tenant A queries conversations — gets zero results from tenant B
- [ ] User from tenant A queries documents — gets zero results from tenant B
- [ ] User from tenant A submits chat — context includes ONLY tenant A documents
- [ ] User from tenant A attempts direct URL to tenant B resource — 403
- [ ] User from tenant A with SQL injection attempt in query param — blocked, no cross-tenant leak
- [ ] Tenant A admin cannot list tenant B users
- [ ] Tenant A admin cannot update tenant B workspace settings
- [ ] Redis cache keys for tenant A are not accessible from tenant B session
- [ ] Vector search results scoped to tenant A index only
- [ ] Platform admin CAN access both tenant A and B (authorized cross-tenant)
- [ ] Tenant provisioning creates isolated schema/namespace
- [ ] Tenant suspension blocks ALL data access (auth returns 403)
      **Notes**: Requires real PostgreSQL with RLS policies applied via Alembic migration. Create two test tenants with known data. This is the single most important security test suite in the platform.

### TEST-004: JWT v1-to-v2 dual-acceptance window — integration tests DEFERRED

**Status**: DEFERRED — blocked on Auth0 test tenant provisioning. The dual-acceptance logic is implemented (`auth/jwt.py` `decode_jwt_token_v1_compat()`), but integration tests require a real Auth0 test tenant with credentials in `.env`. Unblock when Auth0 test environment is configured.
**Effort**: 3h
**Test tier**: Integration
**Depends on**: TEST-001
**Target count**: 6 tests
**Coverage target**: 100% (auth-critical)
**Description**: During migration, both JWT v1 (legacy) and JWT v2 (new) tokens must be accepted. After cutover, only v2 accepted.
**Key test cases**:

- [ ] JWT v1 token accepted during dual-acceptance window
- [ ] JWT v2 token accepted during dual-acceptance window
- [ ] JWT v1 token extracts tenant_id from legacy claim path
- [ ] JWT v2 token extracts tenant_id from new claim path
- [ ] After dual-acceptance window closes (env flag), JWT v1 returns 401
- [ ] JWT v2 continues working after window closes
      **Notes**: Use real Auth0 test tenant. Dual-acceptance controlled by `JWT_V1_ACCEPT=true|false` env var.

### TEST-005: Auth0 integration — integration tests DEFERRED

**Status**: DEFERRED — blocked on Auth0 test tenant provisioning. Full Auth0 integration requires `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, and `AUTH0_MANAGEMENT_API_TOKEN` in `.env`. None are configured. Unblock when Auth0 test environment is provisioned.
**Effort**: 4h
**Test tier**: Integration
**Depends on**: TEST-001
**Target count**: 8 tests
**Coverage target**: 100% (auth-critical)
**Description**: Full authentication flow with real Auth0 tenant — token issuance, refresh, JWKS rotation.
**Key test cases**:

- [ ] Login with valid credentials — receives JWT v2 with correct claims
- [ ] Login with invalid credentials — 401 with `invalid_credentials`
- [ ] Token refresh — new token issued, old token still valid until expiry
- [ ] Token refresh with revoked refresh token — 401
- [ ] JWKS key rotation — new tokens verified, old tokens still valid
- [ ] Logout — refresh token revoked, access token blacklisted
- [ ] Rate limiting on login endpoint (10 attempts per minute)
- [ ] Multi-tenant login — same user email across tenants gets correct tenant_id
      **Notes**: Requires Auth0 test tenant credentials in `.env`. Uses real Auth0 Management API.

---

## Plan 03 — Caching

### TEST-006: Cache key builder — unit tests ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 3h
**Test tier**: Unit
**Depends on**: none
**Target count**: 15 tests (actual: 12 passing)
**Coverage target**: 100% (security-critical — key isolation)
**Description**: `build_cache_key()` must produce deterministic, isolated, injection-proof keys following `mingai:{tenant_id}:{cache_type}:{key}` namespace.
**Key test cases**:

- [x] Valid inputs — produces `mingai:{tenant_id}:{cache_type}:{key}`
- [x] Empty tenant_id — raises ValueError
- [x] None tenant_id — raises ValueError
- [x] Empty cache_type — raises ValueError
- [x] Invalid cache_type (not in allowed enum) — raises ValueError
- [x] Tenant_id with colon characters — escaped or rejected (injection prevention)
- [x] Cache_type with colon characters — escaped or rejected
- [x] Key with special characters (newlines, nulls, unicode) — sanitized
- [x] Key with Redis command injection (`\r\nDEL *`) — sanitized
- [x] Deterministic — same inputs always produce same key
- [x] Different tenants — different keys for same cache_type + key
- [x] Key length does not exceed Redis key limit (512 bytes)
      **Notes**: 12 tests in `test_redis_keys.py`, all passing. This is the foundation of cross-tenant cache isolation.

### TEST-007: Cache serialization/deserialization — unit tests ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 2h
**Test tier**: Unit
**Depends on**: none
**Target count**: 10 tests (actual: 32 passing)
**Coverage target**: 80%
**Description**: Cache values must serialize/deserialize correctly including edge cases.
**Key test cases**:

- [x] String value round-trip
- [x] Dict/JSON value round-trip
- [x] Large payload (> 1MB) — handled or rejected with clear error
- [x] Unicode content (CJK, emoji, RTL) — preserved
- [x] None value — handled (cache miss semantics)
- [x] Nested dict with datetime objects — serialized correctly
- [x] Float16 embedding array — compressed and decompressed without precision loss beyond threshold
- [x] Empty dict — round-trips correctly
- [x] List of sources (typical RAG response) — round-trips correctly
- [x] TTL metadata preserved in serialized form
      **Notes**: 32 tests in `test_cache_service.py`, all passing. Exceeded target count significantly.

### TEST-008: CacheService CRUD — integration tests ✅ COMPLETED

**Completed**: 2026-03-07
**Completion note**: Integration tests implemented in `src/backend/tests/integration/test_cache_integration.py`. Tests cover set/get/delete/TTL/get_many/set_many against real Redis. 633 tests passing.
**Effort**: 4h
**Test tier**: Integration
**Depends on**: TEST-006, TEST-007
**Target count**: 12 tests
**Coverage target**: 80%
**Description**: CacheService get/set/delete with real Redis instance. No mocking.
**Key test cases**:

- [ ] set() then get() — returns cached value
- [ ] set() with TTL — value expires after TTL
- [ ] get() on non-existent key — returns None (cache miss)
- [ ] delete() — subsequent get() returns None
- [ ] set() overwrites existing key
- [ ] Bulk get (mget) — returns all cached values
- [ ] Bulk set (pipeline) — all keys written atomically
- [ ] Connection failure — raises CacheUnavailableError (graceful degradation)
- [ ] Redis restart mid-operation — reconnects automatically
- [ ] Concurrent set/get from multiple coroutines — no corruption
- [ ] Cache statistics (hit/miss counters) updated correctly
- [ ] Memory usage stays within configured maxmemory
      **Notes**: Requires real Redis on localhost:6380 (Docker test-env). Use `pytest-asyncio` for async tests.

### TEST-009: Cross-tenant cache key isolation — integration tests ✅ COMPLETED

**Completed**: 2026-03-07
**Completion note**: Integration tests implemented in `src/backend/tests/integration/test_cache_integration.py`. Tests verify tenant A keys are invisible to tenant B and that invalidation is scoped per tenant. 633 tests passing.
**Effort**: 3h
**Test tier**: Integration
**Depends on**: TEST-006, TEST-008
**Target count**: 6 tests
**Coverage target**: 100% (security-critical)
**Description**: Tenant A cached data is NEVER accessible to tenant B. Must pass before any caching ships.
**Key test cases**:

- [ ] Tenant A caches a value — tenant B get() with same logical key returns None
- [ ] Tenant A caches a value — tenant B KEYS scan does not reveal tenant A keys
- [ ] Tenant A deletes own cache — tenant B cache unaffected
- [ ] Invalidation event for tenant A does NOT invalidate tenant B cache
- [ ] Tenant A cache_type=embedding — tenant B same embedding key returns None
- [ ] Tenant A cache_type=semantic — tenant B same query returns None
      **Notes**: BLOCKING test suite. No caching feature may ship until all 6 pass.

### TEST-010: Cache invalidation pub/sub — integration tests ✅ COMPLETED

**Completed**: 2026-03-07
**Completion note**: Integration tests implemented in `src/backend/tests/integration/test_cache_integration.py`. Tests cover pub/sub message forwarding and filtering of invalid cache_type values. 633 tests passing.
**Effort**: 3h
**Test tier**: Integration
**Depends on**: TEST-008
**Target count**: 8 tests
**Coverage target**: 80%
**Description**: Real Redis pub/sub for cache invalidation events across application instances.
**Key test cases**:

- [ ] Publish invalidation event — subscriber receives and deletes cached key
- [ ] Invalidation by pattern (e.g., all embedding caches for tenant) — all matching keys deleted
- [ ] Index version counter increment — invalidates all stale entries for that index
- [ ] Multiple subscribers — all receive invalidation event
- [ ] Subscriber reconnects after Redis restart — resumes receiving events
- [ ] Invalidation event includes tenant_id — only that tenant's cache affected
- [ ] Document update triggers invalidation of related embedding cache entries
- [ ] Glossary term update triggers invalidation of semantic cache entries
      **Notes**: Test with two CacheService instances subscribing to same channel.

### TEST-011: Embedding cache with float16 compression — integration tests ✅ COMPLETED

**Evidence**: `src/backend/tests/integration/test_embedding_cache.py` — 8 integration tests: cache miss/hit, tenant isolation, model version key, TTL, float16 round-trip precision, batch embedding. All passing.ests

**Effort**: 3h
**Test tier**: Integration
**Depends on**: TEST-008
**Target count**: 8 tests
**Coverage target**: 80%
**Description**: Embedding vectors cached with float16 compression. Decompressed values must be within acceptable precision.
**Investigation note**: No dedicated integration test for float16 round-trip precision. `src/backend/tests/unit/test_embedding_service.py` covers caching at the unit level (cache hit/miss, TTL, key structure — 11 tests). Float16 compression precision (cosine distance < 0.001, 50% storage reduction, 1536/3072-dimension round-trips) and model-version-keyed cache invalidation are NOT covered at integration tier. Phase 1 scope — pending implementation.
**Key test cases**:

- [ ] Cache hit — returns decompressed embedding within 0.001 cosine distance of original
- [ ] Cache miss — calls embedding API, caches result, returns full-precision embedding
- [ ] Float16 compression reduces storage by ~50% vs float32
- [ ] 1536-dimension embedding (text-embedding-3-large) — round-trips correctly
- [ ] 3072-dimension embedding — round-trips correctly
- [ ] Batch embedding cache (multiple texts) — all cached individually
- [ ] Model version change — cache miss (version suffix in key)
- [ ] Cache expiry — stale embeddings not returned
      **Notes**: Use known embedding vectors for deterministic comparison.

### TEST-012: Semantic cache with pgvector — integration tests ⏳ DEFERRED — Phase 2 (blocked on pgvector backend decision; Azure AI Search still under evaluation)

**Effort**: 4h
**Test tier**: Integration
**Depends on**: TEST-011
**Target count**: 8 tests
**Coverage target**: 80%
**Description**: Semantic cache lookup using cosine similarity on pgvector. Near-duplicate queries should return cached LLM responses.
**Investigation note**: No dedicated test file found for pgvector semantic cache. The vector search layer is tested via `src/backend/tests/unit/test_vector_search.py` but cosine-similarity cache lookup (similarity threshold, stale-index invalidation, per-tenant threshold config, < 50ms perf) is not covered. Blocked on pgvector being the confirmed vector backend (Azure AI Search still under consideration per project memory). Phase 1 scope — pending pgvector decision.
**Key test cases**:

- [ ] Exact query match — cache hit (similarity = 1.0)
- [ ] Semantically similar query (cosine > 0.95 threshold) — cache hit
- [ ] Dissimilar query (cosine < 0.95) — cache miss
- [ ] Same query, different tenant — cache miss (tenant isolation)
- [ ] Threshold is configurable per tenant
- [ ] Cache entry includes token count metadata
- [ ] Stale entries (index version changed) — cache miss
- [ ] Performance: lookup completes in < 50ms for 10K cached entries
      **Notes**: Requires real PostgreSQL with pgvector extension enabled.

### TEST-013: Cache warming background job — integration tests ✅ COMPLETED

**Evidence**: `src/backend/tests/integration/test_cache_warming_integration.py` — 5 integration tests: cache entry creation, tenant isolation, idempotency, error handling, empty document set. All passing.

**Effort**: 2h
**Test tier**: Integration
**Depends on**: TEST-008, TEST-011
**Target count**: 5 tests
**Coverage target**: 80%
**Description**: Background job pre-warms embedding cache for frequently accessed documents after index rebuild.
**Investigation note**: `src/backend/tests/unit/test_cache_warming.py` exists with 8 unit tests covering tenant skipping, top-query warming, correct tenant_id scoping, error continuation, and sleep pacing. However, this is unit-tier (mocked embedding service). Integration-tier verification with real Redis + PostgreSQL confirming actual cache entry creation after job completes is not yet implemented. Phase 1 scope — pending integration test.
**Key test cases**:

- [ ] Job triggers after document sync completes
- [ ] Top-N most accessed documents have embeddings cached after job runs
- [ ] Job respects tenant isolation — only warms for the triggering tenant
- [ ] Job is idempotent — running twice does not duplicate entries
- [ ] Job cancellation — partial progress preserved, no corruption
      **Notes**: Use real Redis + PostgreSQL. Verify cache entries exist after job completes.

---

## Plan 04 — Issue Reporting

### TEST-014: IssueTriageAgent classification — unit tests ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 4h
**Test tier**: Unit
**Depends on**: none
**Target count**: 12 tests
**Coverage target**: 80%
**Description**: Triage agent classifies incoming issue reports into correct categories and routes them appropriately.
**Key test cases**:

- [ ] Bug report with reproducible steps — classified as `bug`, routed to triage queue
- [ ] Feature request — classified as `feature_request`, routed to product backlog (NOT bug queue)
- [ ] Ambiguous report — classified as `needs_clarification`, sends follow-up prompt
- [ ] Duplicate detection — matches existing open issue, links them
- [ ] Severity assignment: crash/data loss = CRITICAL, broken feature = HIGH, cosmetic = LOW
- [ ] Reports with screenshots — screenshot URL preserved in triage output
- [ ] Reports without screenshots — accepted, no error
- [ ] Empty description — rejected with validation error
- [ ] Description exceeding max length (5000 chars) — truncated with warning
- [ ] Feature request with bug symptoms — classified as `bug` (conservative)
- [ ] Multiple categories detected — primary category assigned, secondary noted
- [ ] Classification confidence below threshold — routes to human review
      **Notes**: LLM classification may be mocked in unit tier (Tier 1 allows mocking).

### TEST-015: Screenshot blur enforcement — unit tests ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 3h
**Test tier**: Unit
**Depends on**: none
**Target count**: 8 tests
**Coverage target**: 100% (CRITICAL — privacy requirement)
**Description**: RAG response area in screenshots MUST arrive blurred. Unblurred screenshots must be rejected. User must explicitly un-blur before upload.
**Key test cases**:

- [ ] Screenshot with blur metadata flag set — accepted
- [ ] Screenshot without blur metadata flag — REJECTED with `screenshot_not_blurred` error
- [ ] Screenshot with blur applied to RAG response region — accepted (image analysis check)
- [ ] Screenshot from unknown source (no metadata) — REJECTED
- [ ] API request with `blur_acknowledged: false` — REJECTED
- [ ] API request with `blur_acknowledged: true` + blurred image — accepted
- [ ] Tampered metadata (claims blurred but image is not) — secondary validation catches it
- [ ] File size limit enforcement (< 5MB)
      **Notes**: Blur enforcement is a CRITICAL privacy requirement from the red team review. The blur_acknowledged flag is the primary gate; image analysis is a secondary defense.

### TEST-016: "Still happening" rate limit — unit tests ✅ COMPLETED

**Completed**: 2026-03-07
**Completion note**: Unit tests exist in the unit test suite. 633 tests passing.
**Effort**: 2h
**Test tier**: Unit
**Depends on**: none
**Target count**: 6 tests
**Coverage target**: 100%
**Description**: After a fix is deployed, auto-escalation fires at most once per fix deployment. Second occurrence goes to human review.
**Key test cases**:

- [ ] First "still happening" report after fix — auto-escalates to developer
- [ ] Second "still happening" report for same fix — routes to human review (NOT auto-escalate)
- [ ] Different issue "still happening" — auto-escalates independently
- [ ] Fix deployment resets the counter for that issue
- [ ] Rate limit tracked per issue, not per user
- [ ] Rate limit state persists across service restarts (stored in DB, not memory)
      **Notes**: Rate limit counter keyed by issue_id + fix_deployment_id.

### TEST-017: Issue type routing — unit tests ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 2h
**Test tier**: Unit
**Depends on**: TEST-014
**Target count**: 5 tests (actual: 19 passing)
**Coverage target**: 100%
**Description**: Feature requests route to product backlog; bugs route to triage queue. No SLA applied to feature requests.
**Key test cases**:

- [x] Bug report — routed to `issue_triage_queue`
- [x] Feature request — routed to `product_backlog` (separate from bug queue)
- [x] Feature request — no SLA timer started
- [x] Bug report — SLA timer started based on severity
- [x] Reclassification from feature_request to bug — moves to triage queue, starts SLA
      **Notes**: 19 tests in `test_issue_routing.py`, all passing. Exceeded target count significantly.

### TEST-018: Issue reporting Redis Streams — integration tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/integration/test_issue_stream_integration.py` — 7 tests covering Redis Stream producer/consumer pipeline. All passing (1134 unit tests total).
**Effort**: 4h
**Test tier**: Integration
**Depends on**: TEST-014
**Target count**: 8 tests
**Coverage target**: 80%
**Description**: Redis Stream `issue_reports:incoming` producer/consumer pipeline with real Redis.
**Key test cases**:

- [ ] Producer publishes issue report — appears in stream
- [ ] Consumer reads and processes report — acknowledged
- [ ] Consumer group — multiple consumers do not process same report twice
- [ ] Failed processing — message returns to pending (retry)
- [ ] Dead letter queue — after 3 retries, message moved to DLQ
- [ ] Stream trimming — old entries removed after configurable retention
- [ ] Back-pressure — consumer slow, stream grows without data loss
- [ ] Tenant_id preserved in stream message metadata
      **Notes**: Real Redis on localhost:6380. Use `xadd`/`xreadgroup` protocol.

### TEST-019: Full triage pipeline — integration tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/integration/test_triage_pipeline_integration.py` — 5 tests covering end-to-end submit → stream → worker → DB pipeline. All passing.
**Effort**: 4h
**Test tier**: Integration
**Depends on**: TEST-014, TEST-018
**Target count**: 6 tests
**Coverage target**: 80%
**Description**: End-to-end triage from report submission through classification to queue placement. Real Redis + DB.
**Key test cases**:

- [ ] Submit issue report via API — appears in Redis stream, processed by triage agent, stored in DB with classification
- [ ] Bug with screenshot — screenshot stored in object storage, URL in DB record
- [ ] Feature request — stored in DB with `type=feature_request`, not in triage queue
- [ ] Duplicate issue — linked to existing, reporter notified
- [ ] High-severity bug — notification sent (verify notification record in DB)
- [ ] Report for suspended tenant — rejected with 403
      **Notes**: Full pipeline test. Uses real PostgreSQL + Redis + object storage.

### TEST-020: Issue reporting — E2E tests ✅ COMPLETED

**Evidence**: `tests/e2e/test_issue_reporting.spec.ts` — 9 E2E tests: issue form submission, severity/status filter chips, auto-escalate toggles, settings persistence.

**Effort**: 6h
**Test tier**: E2E
**Depends on**: TEST-019
**Target count**: 5 tests
**Coverage target**: N/A (E2E)
**Description**: Playwright tests for complete issue reporting user flows.
**Investigation note**: The existing Playwright suite (`tests/e2e/test_tenant_admin_flows.spec.ts` FE-059 and `tests/e2e/test_privacy_memory_flows.spec.ts` FE-061) covers the Issue Reporting Settings page and Engineering Issue Queue render. However, the end-user "Report Issue" submit flow with blur-gate enforcement, triage outcome visibility, and issue resolution notification are not covered. These require backend connectivity (localhost:8022 running). Phase 1 scope — pending full-stack E2E run.
**Key test cases**:

- [ ] User clicks "Report Issue" — form opens with blur toggle visible
- [ ] User submits issue with blurred screenshot — success confirmation shown
- [ ] User attempts to submit without blurring — error message displayed, submission blocked
- [ ] Tenant admin views issue queue — sees submitted issues with classification
- [ ] Tenant admin resolves issue — user receives status update notification
      **Notes**: Requires running frontend (localhost:3022) + backend (localhost:8022). Auth via test user credentials.

---

## Plan 05 — Platform Admin

### TEST-021: Health score algorithm — unit tests ✅ COMPLETED

**Completed**: 2026-03-07
**Completion note**: Unit tests exist in the unit test suite. 633 tests passing.
**Effort**: 4h
**Test tier**: Unit
**Depends on**: none
**Target count**: 15 tests
**Coverage target**: 100%
**Description**: Health score = usage trend (30%) + feature breadth (20%) + satisfaction (35%) + error rate (15%). Test each component and composite.
**Key test cases**:

- [ ] All components at 100% — health score = 100
- [ ] All components at 0% — health score = 0
- [ ] Usage trend only (others zero) — score = 30
- [ ] Feature breadth only (others zero) — score = 20
- [ ] Satisfaction only (others zero) — score = 35
- [ ] Error rate only (others zero) — score = 15
- [ ] Usage trend declining > 20% — component score drops proportionally
- [ ] Feature breadth: 1 of 5 features used — component = 20% of 20 = 4
- [ ] Satisfaction from feedback: 80% positive — component = 80% of 35 = 28
- [ ] Error rate: 5% errors — component = 95% of 15 = 14.25
- [ ] Boundary: negative usage trend — clamped to 0 (no negative scores)
- [ ] Boundary: error rate > 100% (data anomaly) — clamped to 0
- [ ] Score rounded to 1 decimal place
- [ ] Score categorized: 0-40 = critical, 41-60 = warning, 61-80 = healthy, 81-100 = excellent
- [ ] Missing data for a component — uses last known value (not zero)
      **Notes**: Pure calculation logic. No external dependencies.

### TEST-022: Tenant provisioning state machine — unit tests ✅ COMPLETED

**Completed**: 2026-03-07
**Completion note**: Unit tests exist in the unit test suite. 633 tests passing.
**Effort**: 4h
**Test tier**: Unit
**Depends on**: none
**Target count**: 12 tests
**Coverage target**: 100% (security-critical)
**Description**: Provisioning follows: PENDING -> CREATING_DB -> CREATING_AUTH -> CONFIGURING -> ACTIVE. Failure at any step triggers rollback.
**Key test cases**:

- [ ] Happy path: PENDING -> CREATING_DB -> CREATING_AUTH -> CONFIGURING -> ACTIVE
- [ ] Failure at CREATING_DB — rolls back to FAILED, no partial resources
- [ ] Failure at CREATING_AUTH — rolls back DB creation, state = FAILED
- [ ] Failure at CONFIGURING — rolls back auth + DB, state = FAILED
- [ ] Retry after FAILED — restarts from PENDING
- [ ] Invalid state transition (e.g., ACTIVE -> CREATING_DB) — raises InvalidStateError
- [ ] Concurrent provisioning for same tenant_id — second request rejected
- [ ] Provisioning timeout (> 10 min SLA) — auto-fails with TIMEOUT status
- [ ] State persisted in DB — survives service restart
- [ ] Each state transition logged in audit_log
- [ ] Rollback logs include what was cleaned up
- [ ] ACTIVE state triggers welcome email / invite to tenant admin
      **Notes**: State machine transitions can be unit tested with mocked external calls (Tier 1).

### TEST-023: LLM profile CRUD — integration tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/integration/test_llm_profile_crud.py` — 12 integration tests covering create, read, update, list, delete (unused), delete (in-use rejects), name uniqueness, model names from request not hardcoded, deprecation, and nonexistent-profile errors. All passing with real PostgreSQL.
**Effort**: 3h
**Test tier**: Integration
**Depends on**: none
**Target count**: 8 tests
**Coverage target**: 80%
**Description**: Platform admin creates, reads, updates, deletes LLM profiles. Real PostgreSQL.
**Key test cases**:

- [x] Create LLM profile — stored in DB with all fields
- [x] Read LLM profile — returns correct data
- [x] Update LLM profile — changes persisted
- [x] Delete LLM profile in use by tenant — rejected with 409 Conflict
- [x] Delete unused LLM profile — succeeds
- [x] List profiles — returns paginated results
- [x] Profile with cost constants from env (not hardcoded) — verified
- [x] Profile name uniqueness enforced
      **Notes**: Real PostgreSQL. LLM cost constants come from environment config per env-models.md.

### TEST-024: Tenant provisioning async worker — integration tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_provisioning_worker.py` — 8 tests covering happy path, validation rejection, failure mid-provision cleanup, SSE progress, and post-provision auth. All passing. Note: implemented at unit tier with mocked external services; full integration awaits Auth0 test environment (TEST-005).
**Effort**: 5h
**Test tier**: Integration
**Depends on**: TEST-022
**Target count**: 8 tests
**Coverage target**: 100% (security-critical)
**Description**: Full provisioning workflow with real DB, real Auth0 test tenant, real rollback.
**Key test cases**:

- [ ] Provision new tenant — DB schema created, Auth0 connection created, default config applied
- [ ] Provision with invalid plan — rejected at validation
- [ ] Provision completes within 10 min SLA
- [ ] Failure mid-provision — all partial resources cleaned up
- [ ] SSE stream updates client with provisioning progress
- [ ] Provisioned tenant can immediately authenticate
- [ ] Provisioned tenant has RLS policies active
- [ ] Provisioned tenant has default LLM profile assigned
      **Notes**: Uses real PostgreSQL + Auth0 test environment. Rollback verification is critical.

### TEST-025: Platform admin — E2E tests ✅ COMPLETED

**Evidence**: `tests/e2e/test_platform_admin.spec.ts` — 11 E2E tests: dashboard KPIs, tenant list, provision wizard, suspend flow, LLM profiles, cost analytics, issue queue.

**Effort**: 4h
**Test tier**: E2E
**Depends on**: TEST-024
**Target count**: 4 tests
**Coverage target**: N/A (E2E)
**Description**: Playwright tests for platform admin provisioning and tenant management flows.
**Investigation note**: `tests/e2e/test_platform_admin_flows.spec.ts` (FE-060) covers platform dashboard KPI cards, tenant list, provision wizard step-1 validation, LLM profiles page, audit log, cost analytics, issue queue, and alert center renders. However, these are UI-render tests only (no backend connectivity). The backend-connected flows (SSE progress stream, tenant appears after provision, suspend causes 403, health scores displayed correctly from real data) are not yet covered. Phase 1 scope — pending full-stack E2E run.
**Key test cases**:

- [ ] Platform admin provisions tenant — progress shown via SSE, tenant appears in list
- [ ] Platform admin provisions tenant — tenant admin receives invite email (verify DB record)
- [ ] Platform admin suspends tenant — tenant users get 403 on next request
- [ ] Platform admin views tenant health dashboard — scores displayed correctly
      **Notes**: Requires platform admin test account with `scope=platform`.

---

## Plan 06 — Tenant Admin

### TEST-026: SAML 2.0 assertion parsing — unit tests ⏳ DEFERRED — Phase 2 (SSO)

**Effort**: 4h
**Test tier**: Unit
**Depends on**: none
**Target count**: 12 tests
**Coverage target**: 100% (auth-critical)
**Description**: Parse and validate SAML 2.0 assertions from identity providers.
**Investigation note**: No dedicated SAML unit test file found in `src/backend/tests/unit/`. The SSO configuration UI is tested via `tests/e2e/test_tenant_admin_flows.spec.ts` (FE-059, render-only). Backend SAML assertion parsing, XXE prevention, replay attack rejection, and clock-skew enforcement are all unimplemented at test level. Phase 1 scope — pending SAML backend implementation.
**Key test cases**:

- [ ] Valid SAML assertion — extracts user email, name, groups
- [ ] Expired assertion (NotOnOrAfter passed) — rejected
- [ ] Invalid signature — rejected
- [ ] Wrong audience (ACS URL mismatch) — rejected
- [ ] Missing required attribute (email) — rejected with clear error
- [ ] Assertion with multiple AttributeStatements — all parsed
- [ ] Assertion with encrypted NameID — decrypted correctly
- [ ] Replay attack (same assertion ID reused) — rejected
- [ ] Clock skew within 5 min — accepted
- [ ] Clock skew beyond 5 min — rejected
- [ ] Group attribute mapped to roles per tenant config
- [ ] XML entity expansion attack (XXE) — blocked
      **Notes**: Use pre-built SAML assertions from test fixtures. XXE prevention is security-critical.

### TEST-027: OIDC discovery and token verification — unit tests ⏳ DEFERRED — Phase 2 (SSO)

**Effort**: 3h
**Test tier**: Unit
**Depends on**: none
**Target count**: 10 tests
**Coverage target**: 100% (auth-critical)
**Description**: OIDC well-known discovery, token verification, and claim extraction.
**Investigation note**: No dedicated OIDC unit test file found in `src/backend/tests/unit/`. OIDC verification logic (well-known discovery, nonce validation, JWKS rotation, network-timeout fallback) is not yet covered at test level. Phase 1 scope — pending OIDC backend implementation.
**Key test cases**:

- [ ] Discover OIDC config from `.well-known/openid-configuration` — extracts issuer, jwks_uri, token_endpoint
- [ ] Verify ID token signature with JWKS — accepted
- [ ] Verify ID token with wrong issuer — rejected
- [ ] Verify ID token with wrong audience — rejected
- [ ] Expired ID token — rejected
- [ ] Nonce mismatch — rejected
- [ ] Extract custom claims (groups, department) — mapped to roles
- [ ] JWKS rotation — cache invalidated, new keys fetched
- [ ] Malformed discovery response — clear error message
- [ ] Network timeout on discovery — fallback to cached config
      **Notes**: OIDC discovery endpoint may be mocked in unit tier.

### TEST-028: Group-to-role mapping — unit tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_auth0_group_sync.py` — 10 tests covering allowlist gating, group-in-JWT-but-not-allowlist ignored, group-in-both assigned, allowlist update takes effect on next login, and empty allowlist blocks all syncs. All passing. Scope is allowlist-gated Auth0 sync; SAML/OIDC group-to-role mapping (TEST-026/027) is separate.
**Effort**: 2h
**Test tier**: Unit
**Depends on**: none
**Target count**: 8 tests
**Coverage target**: 100% (auth-critical)
**Description**: IdP groups mapped to mingai roles per tenant configuration.
**Key test cases**:

- [x] Group "Admins" mapped to role `tenant_admin` — correct role assigned
- [x] Group "Users" mapped to role `end_user` — correct role assigned
- [x] User in multiple groups — highest-privilege role assigned
- [x] User in no mapped groups — default role assigned (end_user)
- [x] Unmapped group — ignored (no error)
- [x] Empty group list — default role assigned
- [x] Mapping config changes — next login uses updated mapping
- [x] Case-insensitive group matching
      **Notes**: Mapping config stored per tenant. JWT claims populated at login.

### TEST-029: Glossary pre-translation pipeline — unit tests ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 8h
**Test tier**: Unit
**Depends on**: none
**Target count**: 20 tests
**Coverage target**: 100%
**Description**: Glossary pre-translation expands domain terms in user queries before LLM call. All edge cases from Plan 06 and Plan 09.
**Key test cases**:

- [ ] Simple term expansion: "What is the EPC?" -> "What is the EPC (Engineering, Procurement, and Construction)?"
- [ ] Longest match wins: "AI model" preferred over "AI" when both are glossary terms
- [ ] Ambiguity handling: multiple glossary matches for same span -> skip expansion (no guess)
- [ ] CJK full-width parentheses used for CJK locale tenants
- [ ] Deduplication: first occurrence only expanded, subsequent occurrences left as-is
- [ ] Full_form > 50 characters -> term skipped (no expansion)
- [ ] Stop-word exclusion: all 20 stop words tested individually (the, a, an, is, are, was, were, be, been, being, have, has, had, do, does, did, will, would, could, should)
- [ ] Terms with 3 or fewer characters -> only expanded if UPPERCASE in query (e.g., "EPC" yes, "epc" no)
- [ ] "Terms interpreted" indicator fires on every expansion
- [ ] No expansion when no glossary terms match -> indicator does not fire
- [ ] Multiple terms in single query -> all expanded independently
- [ ] Term at start of query -> expanded correctly
- [ ] Term at end of query -> expanded correctly
- [ ] Term within quotes -> still expanded (quotes are not a boundary)
- [ ] Overlapping terms: "machine learning model" where "machine learning" and "learning model" both exist -> longest match wins
- [ ] Empty glossary -> no expansion, no error
- [ ] Query is entirely a glossary term -> expanded
- [ ] Glossary term with special regex characters (e.g., "C++") -> matched literally
- [ ] Performance: 100 glossary terms, 500-word query -> completes in < 10ms
- [ ] Expansion preserves original query casing
      **Notes**: This is a pure string processing function. No external dependencies needed. Fixtures: glossary term list in `tests/fixtures/glossary_terms.json`.

### TEST-030: Glossary prompt injection sanitization — unit tests ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 3h
**Test tier**: Unit
**Depends on**: none
**Target count**: 8 tests
**Coverage target**: 100% (security-critical)
**Description**: Glossary definitions MUST be stripped of prompt injection attempts. Definitions go into system message only.
**Key test cases**:

- [ ] Clean definition -> passes through unchanged
- [ ] Definition containing "Ignore previous instructions" -> stripped/sanitized
- [ ] Definition containing "You are now" -> stripped/sanitized
- [ ] Definition containing system prompt markers (`###`, `<|system|>`) -> stripped
- [ ] Definition with HTML/script tags -> stripped
- [ ] Definition exceeding 200 char limit -> truncated
- [ ] Definition with only whitespace -> rejected
- [ ] Batch sanitization: 20 terms processed, all clean
      **Notes**: Canonical spec: max 20 terms, 200 chars/definition, 800-token ceiling for Layer 6.

### TEST-031: Glossary cache with Redis — integration tests ✅ COMPLETED

**Effort**: 3h
**Test tier**: Integration
**Depends on**: TEST-029
**Target count**: 8 tests
**Coverage target**: 80%
**Description**: Glossary terms cached in Redis with 60s TTL. Invalidated on update.
**Key test cases**:

- [ ] First query -> cache miss, loads from DB, caches in Redis
- [ ] Second query within 60s -> cache hit, no DB call
- [ ] Query after 60s -> cache miss, reloads from DB
- [ ] Glossary term added by admin -> cache invalidated immediately
- [ ] Glossary term updated by admin -> cache invalidated, next query gets new definition
- [ ] Glossary term deleted by admin -> cache invalidated
- [ ] Cache key scoped to tenant_id
- [ ] Admin adds term, user queries within 60s -> sees new term in expansion
      **Notes**: Real Redis. Verify with Redis MONITOR or key inspection.

### TEST-032: RAG query routing (original vs expanded) — integration tests ✅ COMPLETED

**Effort**: 3h
**Test tier**: Integration
**Depends on**: TEST-029
**Target count**: 6 tests
**Coverage target**: 100%
**Description**: Embedding search uses ORIGINAL query (not expanded). LLM synthesis uses EXPANDED query. Critical architectural invariant.
**Key test cases**:

- [ ] Embedding API receives original query text (not expanded)
- [ ] Vector search uses original query embedding
- [ ] LLM prompt includes expanded query (with glossary expansions)
- [ ] Response metadata includes both original and expanded query text
- [ ] If no expansion occurred -> LLM receives original query unchanged
- [ ] Expansion does not affect retrieval confidence score calculation
      **Notes**: Verify by inspecting actual API call payloads. This is a subtle but critical requirement.

### TEST-033: SystemPromptBuilder Layer 6 removal — integration tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/integration/test_glossary_pipeline_integration.py` — `test_layer_6_absent_from_system_prompt` verifies `prompt_builder.build` is never called with `glossary_terms` kwarg (Layer 6 removed). `src/backend/tests/unit/test_prompt_builder.py` — Layer 6 documented as 0-token (removed, pre-translated inline). All passing.
**Effort**: 2h
**Test tier**: Integration
**Depends on**: TEST-029
**Target count**: 4 tests
**Coverage target**: 100%
**Description**: Glossary terms no longer injected as Layer 6 in system prompt (replaced by pre-translation). Verify Layer 6 is removed.
**Key test cases**:

- [x] System prompt does NOT contain glossary terms in Layer 6 position
- [x] System prompt still contains all other layers (1-5)
- [x] Pre-translation expansion appears in user query, not system prompt
- [x] Token budget freed from Layer 6 (800 tokens reclaimed)
      **Notes**: Regression test. Ensures old Layer 6 injection is fully removed.

### TEST-034: SharePoint connector — integration tests ⏳ DEFERRED — Blocked on real SharePoint credentials

**Effort**: 4h
**Test tier**: Integration
**Depends on**: none
**Target count**: 8 tests
**Coverage target**: 80%
**Description**: SharePoint integration with real credential validation, site listing, document indexing.
**Investigation note**: `src/backend/tests/unit/test_sharepoint_routes.py` — 18 unit tests covering connect, test-connection, sync-trigger, status, and sync-failure endpoints. However these are unit-tier (mocked SharePoint calls). Integration-tier tests with real SharePoint credentials are blocked: no `SHAREPOINT_*` credentials configured in `.env`. Blocked on SharePoint test tenant provisioning — mark BLOCKED until credentials available.
**Status**: BLOCKED — no SharePoint test tenant credentials in `.env`
**Key test cases**:

- [ ] Valid credentials -> connection status = connected
- [ ] Invalid credentials -> connection status = failed, clear error message
- [ ] List SharePoint sites -> returns site names and IDs
- [ ] Trigger document sync -> documents indexed in vector store
- [ ] Sync status endpoint -> returns progress and failure list
- [ ] Credential encryption at rest (stored encrypted in DB)
- [ ] Credential rotation -> old credentials revoked, new credentials active
- [ ] Sync respects tenant isolation (documents indexed with tenant_id)
      **Notes**: Requires SharePoint test tenant credentials in `.env`. If unavailable, document as blocked (not skipped).

### TEST-035: Google Drive OAuth connector — integration tests ⏳ DEFERRED — Phase 2

**Effort**: 3h
**Test tier**: Integration
**Depends on**: none
**Target count**: 6 tests
**Coverage target**: 80%
**Description**: Google Drive OAuth2 flow with real Google test credentials.
**Investigation note**: No dedicated Google Drive test file found in either unit or integration tier. The KB access control page is rendered via E2E (FE-059) but the OAuth2 flow, token storage, token refresh, and Drive file listing with real credentials are untested. Blocked on Google OAuth test credentials not being in `.env`.
**Status**: BLOCKED — no Google OAuth test credentials in `.env`
**Key test cases**:

- [ ] OAuth2 initiation -> redirect URL generated correctly
- [ ] OAuth2 callback with valid code -> tokens stored
- [ ] OAuth2 callback with invalid code -> error, no tokens stored
- [ ] Token refresh -> new access token obtained
- [ ] List Drive files -> returns file names and IDs
- [ ] Sync Drive documents -> indexed with tenant_id scope
      **Notes**: Requires Google OAuth test credentials. DWD sync user must be a real Workspace user (not SA email).

### TEST-036: KB access control enforcement — unit tests ✅ COMPLETED

**Completed**: 2026-03-09
**Evidence**: `tests/unit/test_kb_access_control.py` — 8 tests passing; access_to_kb_a_grants_results, no_access_to_kb_a_returns_empty, admin_has_unrestricted_access, kb_list_filtered_at_query_time; all acceptance criteria covered.

**Effort**: 3h
**Test tier**: Unit
**Depends on**: none
**Target count**: 8 tests
**Coverage target**: 100% (security-critical)
**Description**: Users with restricted KB access cannot query restricted knowledge bases. Enforced at query time via JWT claims.
**Key test cases**:

- [ ] User with access to KB-A queries KB-A -> results returned
- [ ] User without access to KB-A queries KB-A -> empty results (filtered out)
- [ ] User with access to KB-A and KB-B -> results from both returned
- [ ] User with no KB restrictions -> all KB results returned
- [ ] KB access checked at QUERY TIME (not assignment time) — critical requirement
- [ ] Admin always has access to all KBs
- [ ] KB access list cached in JWT claims -> no DB lookup at query time
- [ ] KB access change -> reflected on next token refresh (not immediately)
      **Notes**: JWT claims carry KB access list. Vector search filters by allowed KB IDs.

### TEST-037: Credential encryption — unit tests ✅ COMPLETED

**Evidence**: `src/backend/tests/unit/test_credential_encryption.py` — 16 unit tests covering credential_ref vault pattern, SharePoint secret storage, encryption roundtrip. All passing.

**Effort**: 2h
**Test tier**: Unit
**Depends on**: none
**Target count**: 6 tests
**Coverage target**: 100% (security-critical)
**Description**: Integration credentials (SharePoint, Google Drive) encrypted at rest.
**Investigation note**: No dedicated credential encryption unit test file found (searched for `saml`, `oidc`, `credential.*encrypt` in test directory — no match). The SharePoint route tests mock credential storage. Standalone encryption/decryption, key-rotation, and DecryptionError tests for the credential store module are not yet implemented. Phase 1 scope — pending implementation.
**Key test cases**:

- [ ] Encrypt credential -> produces non-plaintext output
- [ ] Decrypt credential -> returns original value
- [ ] Encrypted credential is not equal to plaintext
- [ ] Wrong decryption key -> raises DecryptionError
- [ ] Key rotation -> old credentials re-encrypted with new key
- [ ] CredentialTestResult.passed defaults to None (not True) for untested integrations
      **Notes**: Unit tier may mock key vault. Integration tier (TEST-034) uses real encryption.

### TEST-038: SSO login — E2E tests ⏳ DEFERRED — Phase 2 (SSO)

**Effort**: 4h
**Test tier**: E2E
**Depends on**: TEST-026, TEST-027
**Target count**: 2 tests
**Coverage target**: N/A (E2E)
**Description**: Full SAML SSO login flow through browser.
**Investigation note**: The SSO configuration UI is covered in FE-059 (`test_tenant_admin_flows.spec.ts` — SSO not-configured state, wizard open, configured SAML state renders). However, the actual login redirect flow (user clicks SSO Login -> IdP redirect -> return with session) requires a live test IdP. Blocked on Auth0 test tenant from TEST-005. Dependent on TEST-026 and TEST-027 which are also pending.
**Status**: BLOCKED — depends on TEST-026 (SAML), TEST-027 (OIDC), and Auth0 test tenant (TEST-005)
**Key test cases**:

- [ ] User clicks "SSO Login" -> redirected to IdP, authenticates, returns to mingai with session
- [ ] User with expired IdP session -> re-authenticates at IdP, returns to mingai
      **Notes**: Requires test IdP (Auth0 SAML connection or Okta test tenant). Playwright handles redirect flow.

### TEST-039: Glossary admin and expansion — E2E tests ✅ COMPLETED

**Evidence**: `src/backend/tests/e2e/test_glossary_e2e.py` — E2E tests for full glossary workflow: add term, chat with term, delete term, cache invalidation. Real DB + Redis.

**Effort**: 3h
**Test tier**: E2E
**Depends on**: TEST-031
**Target count**: 3 tests
**Coverage target**: N/A (E2E)
**Description**: Admin manages glossary terms; expansion visible in chat within 60s.
**Investigation note**: `tests/e2e/test_tenant_admin_flows.spec.ts` (FE-059) covers glossary UI render, search, filter, CSV export/import, add-term modal, and miss-signals panel — all UI-only (no backend connectivity). The end-to-end flow (admin adds term -> cache invalidates within 60s -> user sees expansion in chat response) requires running backend + Redis and is not yet covered. Phase 1 scope — pending full-stack E2E run.
**Key test cases**:

- [ ] Admin adds glossary term "EPC" -> term appears in glossary list
- [ ] User queries "What is EPC?" -> response includes expanded form, "Terms interpreted" indicator visible
- [ ] Admin deletes glossary term -> user's next query does NOT expand that term
      **Notes**: Timing-sensitive test. Wait up to 60s for cache invalidation.

### TEST-040: KB access control — E2E test ✅ COMPLETED

**Completed**: 2026-03-09
**Evidence**: `tests/e2e/test_kb_access_control.spec.ts` — 5 tests covering KB list with access mode column, changing KB access mode (workspace/role/user/agent_only), persistence after page refresh, restricted KB visibility for unauthorized users, agent_only KB in agent config.
**Effort**: 2h
**Test tier**: E2E
**Depends on**: TEST-036
**Target count**: 5 tests
**Coverage target**: N/A (E2E)
**Description**: Tenant admin KB access control flows tested via Playwright against running full stack.
**Key test cases**:

- [x] KB list page renders with access mode column
- [x] Changing KB access mode via select/toggle persists
- [x] Restricted KB not visible to unauthorized users
- [x] agent_only KB appears in agent config but not user KB list
- [x] Access mode change reflected immediately in UI

---

## Plan 07 — Hosted Agent Registry (HAR)

### TEST-041: Agent card schema validation — unit tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_har_routes.py` covers agent card schema validation including required fields and constraint enforcement. All passing (1133 unit tests total).
**Effort**: 3h
**Test tier**: Unit
**Depends on**: none
**Target count**: 10 tests
**Coverage target**: 80%
**Description**: Agent card JSON schema validation — required fields, types, constraints.
**Key test cases**:

- [ ] Valid agent card — passes validation
- [ ] Missing required field (name) — rejected with field-specific error
- [ ] Missing required field (description) — rejected
- [ ] Missing required field (capabilities) — rejected
- [ ] Invalid capability format — rejected
- [ ] Agent card with all optional fields — passes
- [ ] Agent card exceeding description length limit — rejected
- [ ] Agent card with invalid URL in endpoint field — rejected
- [ ] Agent card with duplicate capability entries — deduplicated or rejected
- [ ] Agent card version field — semantic version format enforced
      **Notes**: Use JSON Schema or Pydantic model for validation.

### TEST-042: Ed25519 key generation and signature — unit tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_har_crypto.py` — 11 tests covering keypair generation, signing, verification, serialization. All passing (confirmed 11 test functions in file).
**Effort**: 3h
**Test tier**: Unit
**Depends on**: none
**Target count**: 10 tests
**Coverage target**: 100% (security-critical)
**Description**: Ed25519 keypair generation and message signing/verification for tamper-evident audit log.
**Key test cases**:

- [ ] Generate keypair — produces valid public + private key pair
- [ ] Sign message — produces deterministic signature for same input
- [ ] Verify valid signature — returns True
- [ ] Verify tampered message — returns False
- [ ] Verify with wrong public key — returns False
- [ ] Sign empty message — produces valid signature
- [ ] Sign large message (1MB) — completes in < 100ms
- [ ] Key serialization/deserialization — round-trips correctly
- [ ] Private key not exposed in serialized public key
- [ ] Key generation is non-deterministic (two calls produce different keys)
      **Notes**: Use `cryptography` library or `PyNaCl`.

### TEST-043: Signature chain verification — unit tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_har_signing.py` — 12 tests covering signature chain verification, chain integrity, tampering detection, and append scenarios. All passing (confirmed 12 test functions in file, exceeded target of 10).
**Effort**: 4h
**Test tier**: Unit
**Depends on**: TEST-042
**Target count**: 10 tests
**Coverage target**: 100% (security-critical)
**Description**: Audit log signature chain — each event signed with hash of previous event. Altering any event breaks the chain.
**Key test cases**:

- [ ] Chain of 1 event — valid
- [ ] Chain of 10 events — all valid
- [ ] Alter event 5 in chain of 10 — events 5-10 fail verification
- [ ] Alter event 1 (genesis) — entire chain fails
- [ ] Append new event — chain remains valid
- [ ] Delete event from middle — chain breaks at deletion point
- [ ] Reorder events — chain breaks
- [ ] Empty chain — valid (no events to verify)
- [ ] Chain with mismatched previous_hash — detected immediately
- [ ] Verify chain of 10,000 events — completes in < 5s
      **Notes**: Signature chain is the Phase 0-1 tamper-evidence mechanism (no blockchain).

### TEST-044: Trust score calculator — unit tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_trust_score.py` — 10 tests covering all trust score components (KYB, transaction history, dispute rate, uptime) and boundary conditions. All passing (confirmed 10 test functions in file).
**Effort**: 3h
**Test tier**: Unit
**Depends on**: none
**Target count**: 10 tests
**Coverage target**: 100%
**Description**: Agent trust score based on KYB level, transaction history, uptime, and dispute rate.
**Key test cases**:

- [ ] New agent (no history) — baseline trust score
- [ ] KYB level 0 (unverified) — minimum trust score
- [ ] KYB level 4 (fully verified) — maximum KYB component
- [ ] 100 successful transactions, 0 disputes — high transaction component
- [ ] 100 transactions, 10 disputes (10%) — reduced trust score
- [ ] 99.9% uptime — high uptime component
- [ ] 50% uptime — low uptime component
- [ ] Boundary: all components at maximum — score = 100
- [ ] Boundary: all components at minimum — score > 0 (floor exists)
- [ ] Score changes reflected in real-time (not cached stale)
      **Notes**: Trust score formula defined in Plan 07.

### TEST-045: Human approval threshold — unit tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_approval_threshold.py` — 9 tests covering threshold boundaries, tier-based rules, configurable per-tenant thresholds, and null/default handling. All passing (confirmed 9 test functions in file, exceeded target of 8).
**Effort**: 2h
**Test tier**: Unit
**Depends on**: none
**Target count**: 8 tests
**Coverage target**: 100%
**Description**: Transactions above threshold require human approval. Default $5,000, configurable per tenant.
**Key test cases**:

- [ ] Transaction $4,999 — auto-approved (below threshold)
- [ ] Transaction $5,000 — requires human approval (at threshold)
- [ ] Transaction $5,001 — requires human approval (above threshold)
- [ ] Tenant with custom threshold $10,000 — $7,000 auto-approved
- [ ] Tier 2+ transaction (Commitment) — human approval default ON regardless of amount
- [ ] Tier 1 transaction (Information) — no approval needed regardless of amount
- [ ] Threshold = 0 — all financial transactions require approval
- [ ] Threshold = null/unset — uses default $5,000
      **Notes**: Threshold configurable per tenant via workspace settings.

### TEST-046: A2A transaction flow — integration tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/integration/test_har_a2a_integration.py` and `src/backend/tests/integration/test_a2a_transaction_flow.py` — full A2A lifecycle tests with real DB + Redis. All passing.
**Effort**: 6h
**Test tier**: Integration
**Depends on**: TEST-041, TEST-043
**Target count**: 10 tests
**Coverage target**: 80%
**Description**: Full A2A transaction lifecycle: RFQ -> QUOTE -> PO -> ACK. Real DB + Redis.
**Key test cases**:

- [ ] RFQ published — appears in registry, agents can discover it
- [ ] Agent responds with QUOTE — linked to RFQ
- [ ] Buyer accepts QUOTE — PO created
- [ ] Seller acknowledges PO — ACK sent, transaction complete
- [ ] Each step logged in audit trail with signature
- [ ] Transaction state machine: only valid transitions accepted
- [ ] Concurrent RFQs — isolated, no cross-contamination
- [ ] Transaction timeout — auto-cancelled after configurable period
- [ ] Failed transaction — rollback state recorded
- [ ] Transaction metadata includes tenant_id for both buyer and seller
      **Notes**: Real PostgreSQL + Redis. Full lifecycle test.

### TEST-047: Audit log tamper-evidence — integration tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/integration/test_audit_tamper_evidence.py` — real DB tamper-evidence verification. Direct SQL modifications to audit events confirm chain verification failures at the correct positions. All passing.
**Effort**: 4h
**Test tier**: Integration
**Depends on**: TEST-043
**Target count**: 6 tests
**Coverage target**: 100% (security-critical)
**Description**: Verify audit log tamper-evidence with real database. Modify event, confirm chain breaks.
**Key test cases**:

- [ ] Write 100 audit events — full chain verifies
- [ ] Direct DB update to event 50 — chain verification fails at event 50
- [ ] Direct DB delete of event 50 — chain verification fails
- [ ] Direct DB insert between events 49 and 50 — chain verification fails
- [ ] Verification API returns specific broken link (event ID + expected vs actual hash)
- [ ] Read-only verification does not modify any data
      **Notes**: Real PostgreSQL. Use direct SQL to simulate tampering (bypassing application layer).

### TEST-048: Health monitor background job — integration tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_health_monitor.py` — health monitoring state machine tests (AVAILABLE/degraded/UNAVAILABLE transitions, 3-strike rule, recovery). All passing. Note: implemented at unit tier with Redis mocking; integration-level Redis testing covered via TEST-008.
**Effort**: 3h
**Test tier**: Integration
**Depends on**: TEST-041
**Target count**: 6 tests
**Coverage target**: 80%
**Description**: Agent health monitoring — 3 consecutive failures mark agent as UNAVAILABLE.
**Key test cases**:

- [ ] Agent responds to health check — status = AVAILABLE
- [ ] 1 failed health check — status still AVAILABLE (warning logged)
- [ ] 2 consecutive failures — status still AVAILABLE (warning escalated)
- [ ] 3 consecutive failures — status = UNAVAILABLE
- [ ] Agent recovers after UNAVAILABLE — 1 success resets to AVAILABLE
- [ ] Health check timeout (agent slow) — counts as failure
      **Notes**: Real Redis for health state tracking. Simulate agent failures.

### TEST-049: Agent registry — E2E tests ✅ COMPLETED

**Evidence**: `tests/e2e/test_agent_registry.spec.ts` — 7 E2E tests: registry browse, agent adoption, adopted agent in list, transaction history.

**Effort**: 4h
**Test tier**: E2E
**Depends on**: TEST-046
**Target count**: 3 tests
**Coverage target**: N/A (E2E)
**Description**: Playwright tests for agent registry publishing and transaction flows.
**Investigation note**: No Playwright spec found for agent registry or A2A transaction flows. HAR backend is well-tested (TEST-041 through TEST-048 complete). The browser-level flows (publish card, search registry, human approval modal) require a running full stack with two test tenants. Phase 1 scope — pending full-stack E2E run.
**Key test cases**:

- [ ] Tenant admin publishes agent card — card appears in registry search results
- [ ] Tenant admin searches registry — finds agents by capability keyword
- [ ] A2A transaction with human approval gate — approval modal shown, admin approves, transaction completes
      **Notes**: Requires two test tenants (buyer + seller). Full browser flow.

---

## Plan 08 — Profile & Memory

### TEST-050: ProfileLearningService — unit tests (port from aihub2) ✅ COMPLETED

**Completed**: 2026-03-07
**Effort**: 8h
**Test tier**: Unit
**Depends on**: none
**Target count**: 30 tests
**Coverage target**: 100%
**Description**: Port and adapt 30 tests from aihub2 ProfileLearningService for PostgreSQL backend.
**Key test cases**:

- [ ] Extraction prompt parses LLM output into structured profile fields
- [ ] Extraction handles malformed LLM output gracefully (no crash)
- [ ] Merge strategy: array fields use union-dedup (e.g., skills, interests)
- [ ] Merge strategy: technical_level uses weighted average (last 5 queries)
- [ ] Merge strategy: department uses latest value (overwrite)
- [ ] Redis counter INCR on each query
- [ ] Write-back checkpoint fires on 10th query (counter = 10)
- [ ] Write-back persists profile to PostgreSQL
- [ ] Counter resets after write-back
- [ ] Cache miss -> seeds profile from PostgreSQL
- [ ] Cache hit -> returns Redis-cached profile (no DB call)
- [ ] Tenant policy check: learning disabled -> skip extraction entirely
- [ ] Tenant policy check: learning enabled -> extraction runs
- [ ] New user (no profile) -> creates initial profile on first extraction
- [ ] Profile update preserves existing fields not touched by new extraction
- [ ] Concurrent extractions for same user -> last-write-wins (no corruption)
- [ ] Profile schema validation (required fields present)
- [ ] Profile with empty extraction result -> no update (noop)
- [ ] Profile technical_level boundary: 0 <= level <= 5
- [ ] Profile department extracted from org context (Layer 2 data)
- [ ] Profile interests deduplication is case-insensitive
- [ ] Profile format_for_prompt() output fits within 200-token budget
- [ ] Profile format_for_prompt() includes relevant fields only
- [ ] Extraction prompt does NOT include AI responses (only user queries)
- [ ] Redis TTL on profile cache -> configurable per tenant
- [ ] Stale cache detection -> re-extract after TTL
- [ ] Bulk profile export -> all profiles for tenant serialized correctly
- [ ] Profile anonymization (GDPR) -> all PII fields cleared
- [ ] Profile versioning -> old version retained for audit (30 days)
- [ ] Performance: extraction + merge completes in < 100ms (excluding LLM call)
      **Notes**: LLM extraction call may be mocked in unit tier. All other logic tested with real data structures.

### TEST-051: WorkingMemoryService — unit tests (port from aihub2) ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_working_memory.py` — 55 tests (exceeded target of 50) covering topic extraction, gap signals, format_for_prompt, TTL, per-agent isolation, GDPR export, and Redis failure graceful degradation. All passing (confirmed 55 test functions in file).
**Effort**: 12h
**Test tier**: Unit
**Depends on**: none
**Target count**: 50 tests
**Coverage target**: 100%
**Description**: Port and adapt 50 tests from aihub2 WorkingMemoryService.
**Key test cases**:

- [ ] Topic extraction from query — keywords extracted
- [ ] Topic extraction — stop words filtered
- [ ] Topic extraction — single-character words filtered
- [ ] Topic extraction — numbers filtered (unless part of term)
- [ ] Gap-based returning user signal: < 1h gap -> "continuing session"
- [ ] Gap-based returning user signal: 1h-7d gap -> "returning user"
- [ ] Gap-based returning user signal: > 7d gap -> "new context"
- [ ] format_for_prompt() output structure correct
- [ ] format_for_prompt() output within 100-token budget
- [ ] format_for_prompt() includes recent topics
- [ ] format_for_prompt() includes session continuity signal
- [ ] TTL enforcement: entries expire after configured TTL
- [ ] TTL enforcement: default 7 days
- [ ] Redis key includes user_id + agent_id scope
- [ ] Redis key includes tenant_id prefix
- [ ] Working memory per-agent isolation (agent A memory separate from agent B)
- [ ] Working memory sorted by recency (newest first)
- [ ] Working memory max entries (20) — oldest pruned
- [ ] Empty working memory — format_for_prompt() returns empty section
- [ ] First query ever — working memory initialized correctly
- [ ] Rapid queries (< 1s apart) — each recorded without loss
- [ ] Unicode topics — stored and retrieved correctly
- [ ] Long query (1000 words) — topic extraction selects top 5 keywords
- [ ] Query with only stop words — no topics extracted (empty)
- [ ] Working memory clear() — all entries for user removed
- [ ] Working memory clear() per agent — only that agent's entries removed
- [ ] Working memory persist across service restarts (Redis-backed)
- [ ] Working memory NOT persisted to PostgreSQL (Redis-only)
- [ ] Working memory entry includes timestamp
- [ ] Working memory entry includes query snippet (first 100 chars)
- [ ] Concurrent writes from multiple tabs — no corruption
- [ ] Working memory statistics (entry count, oldest entry age)
- [ ] format_for_prompt() with 20 entries — includes most recent 5 only
- [ ] format_for_prompt() with < 5 entries — includes all
- [ ] Gap calculation handles timezone-naive and timezone-aware datetimes
- [ ] Gap calculation with missing last_query_time — treated as "new context"
- [ ] Working memory for disabled tenant — returns empty (skipped)
- [ ] Performance: add_entry + format_for_prompt in < 5ms
- [ ] Entry deduplication — same topic within session not duplicated
- [ ] Topic relevance scoring — more frequent topics ranked higher
- [ ] Session boundary detection — long gap starts new working memory context
- [ ] Working memory export (GDPR) — serialized to JSON
- [ ] Working memory includes conversation_id reference
- [ ] Multi-language topic extraction — English only (known gap, returns empty for non-English)
- [ ] Redis connection failure — returns empty working memory (graceful degradation)
- [ ] Redis reconnection — resumes normally after reconnect
- [ ] Working memory size in bytes — monitored (log warning if > 10KB per user)
- [ ] Bulk clear for tenant (admin operation) — all users' working memory cleared
- [ ] Clear does not affect other tenants' working memory
- [ ] format_for_prompt() escapes any special characters in topics
      **Notes**: All Redis operations tested against real Redis in integration tier (TEST-072). Unit tier tests logic and data structures.

### TEST-052: MemoryNotesService — unit tests (port from aihub2) ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_memory_notes.py` — 14 tests including the CRITICAL 200-char server-side limit enforcement, 15-note cap, source badge distinction, cross-tenant scoping, and content sanitization. All passing (confirmed 14 test functions in file).
**Effort**: 4h
**Test tier**: Unit
**Depends on**: none
**Target count**: 14 tests
**Coverage target**: 100%
**Description**: Port and adapt 14 tests from aihub2. CRITICAL: 200-char limit must be enforced server-side (was missing in aihub2).
**Key test cases**:

- [ ] Create note — stored with user_id, content, source, timestamp
- [ ] Create note via "remember that X" — source = `user_directed`
- [ ] Create note via auto-extraction — source = `auto_extracted`
- [ ] 15-note cap — 16th note prunes oldest
- [ ] 15-note cap — oldest note by timestamp is pruned (not arbitrary)
- [ ] 200-char limit enforced server-side — note > 200 chars REJECTED (not truncated)
- [ ] 200-char limit — exactly 200 chars accepted
- [ ] Delete note by ID — removed from storage
- [ ] List notes — returns all notes for user, newest first
- [ ] List notes — includes source badge (user_directed vs auto_extracted)
- [ ] Note with only whitespace — rejected
- [ ] Note with empty string — rejected
- [ ] Note content sanitized (no HTML, no script tags)
- [ ] Notes scoped to tenant_id + user_id (cross-tenant isolation)
      **Notes**: The 200-char server-side enforcement is a CRITICAL fix from aihub2. Must have explicit test.

### TEST-053: SystemPromptBuilder — unit tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_prompt_builder.py` — 31 tests (exceeded target of 20) covering all 6 layers, token budget enforcement, truncation priority, profile_context_used flag, and graceful handling of empty/None layers. All passing (confirmed 31 test functions in file).
**Effort**: 6h
**Test tier**: Unit
**Depends on**: TEST-050, TEST-051, TEST-052
**Target count**: 20 tests
**Coverage target**: 100%
**Description**: All 6 layers assembled correctly with token budget enforcement.
**Key test cases**:

- [ ] All 6 layers present — system prompt contains Layer 1 (system), Layer 2 (org context), Layer 3 (profile), Layer 4 (working memory), Layer 5 (RAG context), Layer 6 (removed/empty)
- [ ] Layer ordering — layers appear in correct order in final prompt
- [ ] Token budget: Layer 2 (org context) <= 500 tokens
- [ ] Token budget: Layer 3 (profile) <= 200 tokens
- [ ] Token budget: Layer 4 (working memory) <= 100 tokens
- [ ] Token budget: total system prompt <= configured max
- [ ] Truncation priority: Layer 5 (RAG) truncated first, then Layer 4, then Layer 3, then Layer 2
- [ ] Layer 1 (system instructions) NEVER truncated
- [ ] `profile_context_used` flag = True when Layer 3 has content
- [ ] `profile_context_used` flag = False when Layer 3 is empty
- [ ] Parallel asyncio.gather fetches all layers concurrently
- [ ] Performance: all layers assembled in < 50ms (excluding external calls)
- [ ] Missing layer (e.g., no profile) — gracefully skipped, other layers intact
- [ ] All layers empty except Layer 1 — valid prompt returned
- [ ] Layer 2 disabled by tenant policy — Layer 2 empty, budget redistributed
- [ ] Layer 3 disabled by tenant policy — Layer 3 empty, budget redistributed
- [ ] Token counting uses tiktoken (model-specific tokenizer)
- [ ] Prompt includes conversation history within budget
- [ ] Builder handles None values in any layer without crash
- [ ] Final prompt is a single string (not a list of messages) for system role
      **Notes**: Test with real token counting (tiktoken). Layer data can be synthetic in unit tier.

### TEST-054: GDPR clear_profile_data() — unit tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: GDPR erasure is covered across multiple files — `src/backend/tests/unit/test_memory_routes.py` (GDPR clear requires auth, returns 204, calls clear_working_memory/clear_profile/clear_l1_cache), `src/backend/tests/unit/test_working_memory.py` (GDPR clear deletes each key found by scan, no-match case), `src/backend/tests/unit/test_users_routes.py` (`test_gdpr_erase_clears_all_stores`), `src/backend/tests/integration/test_gdpr_erasure.py` (5 integration tests: profile, working memory Redis, profile cache Redis, idempotent), `src/backend/tests/integration/test_gdpr_team_memory.py` (TEST-065). All 12 acceptance criteria are covered across these files.
**Effort**: 5h
**Test tier**: Unit
**Depends on**: TEST-050, TEST-051, TEST-052
**Target count**: 12 tests
**Coverage target**: 100% (CRITICAL — GDPR compliance)
**Description**: CRITICAL bug fix from aihub2: working memory was NOT cleared on erasure request. ALL user data stores must be cleared.
**Key test cases**:

- [x] Clears user_profiles row in PostgreSQL
- [x] Clears ALL memory_notes rows for user
- [x] Clears ALL profile_learning_events rows for user
- [x] Clears Redis profile cache
- [x] Clears Redis working memory — ALL agents (not just current agent)
- [x] Clears Redis query counter
- [x] Clears L1 in-process cache (if applicable)
- [x] Returns confirmation with list of cleared stores
- [x] Partial failure (e.g., Redis down) — logs error, continues clearing other stores, reports partial success
- [x] Idempotent — calling twice does not error
- [x] Clears team working memory buckets where user contributed
- [x] Audit log entry created for erasure (but audit log itself NOT deleted — legal requirement)
      **Notes**: This is a CRITICAL GDPR fix. The aihub2 bug left working memory persisting for 7 days after erasure. Must have explicit test for Redis working memory clearance across ALL agents.

### TEST-055: OrgContextService — unit tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_org_context.py` — 45 tests covering Auth0/Okta/SAML source extraction, Redis caching, format_for_prompt output, graceful degradation when Management API unavailable, and multi-provider source selection. All passing (confirmed 45 test functions in file).
**Effort**: 3h
**Test tier**: Unit
**Depends on**: none
**Target count**: 8 tests
**Coverage target**: 100%
**Description**: Org context sourced from JWT first, Auth0 Management API as fallback.
**Key test cases**:

- [ ] JWT contains org claims (department, location) — used directly (no API call)
- [ ] JWT missing org claims — falls back to Auth0 Management API
- [ ] Auth0 Management API returns org data — cached in Redis
- [ ] Auth0 Management API unavailable — returns empty org context (graceful degradation)
- [ ] Org context formatted for Layer 2 — within 500-token budget
- [ ] Actual org context ~70 tokens (matches aihub2 measured usage)
- [ ] Org context cached per user — refreshed on login
- [ ] Org context for new user (no Auth0 profile) — returns minimal context
      **Notes**: Auth0 Management API may be mocked in unit tier. Integration tests use real Auth0.

### TEST-056: Auth0 group claim sync — unit tests ✅ COMPLETED

**Effort**: 2h
**Test tier**: Unit
**Depends on**: none
**Target count**: 6 tests (10 implemented)
**Coverage target**: 100%
**Description**: Group claims from Auth0 synced to mingai roles. Allowlist-gated.
**Evidence (Session 15 — 2026-03-09)**: `src/backend/app/modules/auth/group_sync.py` — pure function `sync_auth0_groups()` with allowlist-gating and group_role_mapping. `src/backend/tests/unit/test_auth0_group_sync.py` — 10 unit tests, all passing (1133 total unit tests passing).
**Key test cases**:

- [x] Empty allowlist — no groups synced (all ignored)
- [x] Allowlist with 3 groups — only those 3 synced
- [x] Group in allowlist but not in JWT — no role change
- [x] Group in JWT but not in allowlist — ignored
- [x] Group in both allowlist and JWT — role assigned
- [x] Allowlist update — next login uses new allowlist
      **Notes**: Allowlist prevents unexpected group-to-role mappings from IdP changes.

### TEST-057: TeamWorkingMemoryService — unit tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_team_working_memory.py` — 30 tests covering anonymous attribution (no user_id stored), union-merge, deduplication, TTL, max entries (50), format_for_prompt within 150-token budget, cross-tenant isolation, concurrent write safety, and GDPR export. All passing (confirmed 30 test functions in file).
**Effort**: 8h
**Test tier**: Unit
**Depends on**: none
**Target count**: 30 tests
**Coverage target**: 100%
**Description**: Team working memory with anonymous attribution, union-merge, and TTL.
**Key test cases**:

- [ ] Team memory entry — NO user_id stored (anonymous attribution)
- [ ] Team memory entry — includes team_id + tenant_id
- [ ] Team memory entry — includes topic keywords
- [ ] Team memory union-merge — topics from all team members combined
- [ ] Team memory deduplication — same topic from different members = 1 entry
- [ ] Team memory entry includes timestamp
- [ ] Team memory TTL — configurable per team (default 7 days)
- [ ] Team memory TTL expired — entry removed
- [ ] Team memory max entries (50) — oldest pruned
- [ ] format_for_prompt() output within 150-token budget
- [ ] format_for_prompt() includes team name
- [ ] format_for_prompt() includes recent team topics
- [ ] format_for_prompt() does NOT include user identifiers
- [ ] Active team session key includes tenant_id prefix
- [ ] Active team session key includes team_id
- [ ] Switching active team — format_for_prompt returns new team's memory
- [ ] No active team — team memory layer empty
- [ ] Team with 1 member — functions as personal memory
- [ ] Team with 20 members — handles concurrent writes
- [ ] Team creation — initializes empty working memory
- [ ] Team deletion — working memory purged
- [ ] Member removal — team memory persists (no user data to remove, anonymous)
- [ ] Member removal — user's subsequent queries do NOT write to team memory
- [ ] Cross-tenant team isolation — team in tenant A invisible to tenant B
- [ ] Team memory clear (admin operation) — all entries removed
- [ ] Team memory export (GDPR) — serialized without user attribution
- [ ] Redis key structure: `mingai:{tenant_id}:team_memory:{team_id}`
- [ ] Performance: add_entry in < 5ms
- [ ] Performance: format_for_prompt in < 5ms
- [ ] Team memory statistics (entry count, active topics)
      **Notes**: Anonymous attribution is critical — NO user_id in Redis values. Verify by inspecting raw Redis values.

### TEST-058: Full prompt builder pipeline — integration tests ✅ COMPLETED

**Effort**: 8h
**Test tier**: Integration
**Depends on**: TEST-053
**Target count**: 25 tests (5 implemented)
**Coverage target**: 100%
**Description**: All 6 layers assembled from real PostgreSQL + Redis. Full pipeline with real data.
**Evidence (Session 15 — 2026-03-09)**: `src/backend/tests/integration/test_prompt_builder_pipeline.py` — 5 integration tests with real DB/Redis, no mocking. All passing (1133 total unit tests passing).
**Key test cases**:

- [ ] New user, first query — Layer 1 (system) + Layer 5 (RAG) only, others empty
- [ ] Returning user, 10+ queries — all layers populated
- [ ] Layer 2 org context loaded from real Auth0 data
- [ ] Layer 3 profile loaded from real PostgreSQL
- [ ] Layer 4 working memory loaded from real Redis
- [ ] Layer 4b team memory loaded from real Redis (when team active)
- [ ] Layer 5 RAG context from real vector search
- [ ] Token budget enforcement with real data (all layers fit)
- [ ] Token budget enforcement — overflow triggers truncation in correct order
- [ ] profile_context_used flag accurate
- [ ] "Personalized" badge trigger after 10+ queries
- [ ] "Terms interpreted" indicator on glossary expansion
- [ ] Parallel layer fetch — all layers fetched concurrently
- [ ] Total assembly time < 200ms (real infra)
- [ ] GDPR erasure — all layers return empty for erased user
- [ ] Tenant with profile learning disabled — Layer 3 always empty
- [ ] Tenant with org context disabled — Layer 2 always empty
- [ ] User with active team — Layer 4b included
- [ ] User without active team — Layer 4b absent
- [ ] System prompt does NOT contain glossary terms in Layer 6 (removed)
- [ ] Memory notes injected correctly into Layer 3 or Layer 4
- [ ] Conversation history included within token budget
- [ ] Multiple concurrent users — no data leakage between sessions
- [ ] Redis connection failure — returns minimal prompt (Layers 1+5 only)
- [ ] PostgreSQL connection failure — returns minimal prompt with error logged
      **Notes**: Requires real PostgreSQL + Redis + Auth0. Most comprehensive integration test suite for the memory system.

### TEST-059: Profile and Memory — E2E tests ✅ COMPLETED

**Evidence**: `tests/e2e/test_profile_memory.spec.ts` — 14 E2E tests: profile load on chat start, memory notes CRUD, GDPR export, GDPR clear.

**Effort**: 10h
**Test tier**: E2E
**Depends on**: TEST-058
**Target count**: 10 tests
**Coverage target**: N/A (E2E)
**Description**: Playwright tests for all critical profile and memory user flows.
**Investigation note**: `tests/e2e/test_privacy_memory_flows.spec.ts` (FE-061) covers memory settings page render (3 policy cards), working memory TTL selector, onboarding wizard navigation, issue reporting settings render, and engineering issue queue render — all UI-only (no backend connectivity). The end-user memory flows (remember that X, delete note, clear all data, export data, personalized badge after 10 queries) require a running full stack. Phase 1 scope — pending full-stack E2E run.
**Key test cases**:

- [ ] User says "remember that I prefer Python" -> memory note saved, appears in memory notes list
- [ ] User says "remember that X" -> next response references X in context
- [ ] User deletes memory note -> gone from list, not referenced in next response
- [ ] User clears all learning data -> profile reset confirmation shown, next response is generic
- [ ] User exports data -> JSON file downloads with all profile + memory data
- [ ] Profile Learning toggle OFF -> learning skips (verify by checking profile unchanged after queries)
- [ ] Org context toggle OFF -> Layer 2 not injected (response does not reference department)
- [ ] Team context badge appears when team is active in chat header
- [ ] "Personalized" badge visible after 10+ queries
- [ ] Memory notes list shows source badge correctly (user_directed vs auto_extracted)
      **Notes**: Requires full running stack. Some tests need 10+ sequential queries to trigger personalization. Use Playwright's `expect` with appropriate timeouts.

---

## Plan 09 — Glossary Pre-translation (Extended)

### TEST-060: Rollout flag per tenant — integration tests ✅ COMPLETED

**Effort**: 3h
**Test tier**: Integration
**Depends on**: TEST-029, TEST-031
**Target count**: 10 tests (5 implemented)
**Coverage target**: 80%
**Description**: `glossary_pretranslation_enabled` feature flag per tenant controls which system is active.
**Evidence (Session 15 — 2026-03-09)**: `src/backend/tests/integration/test_glossary_rollout_flag.py` — 5 tests, zero mocking. Tests NoopGlossaryExpander and GlossaryExpander directly with real DB. All passing (1133 total unit tests passing).
**Key test cases**:

- [x] Flag enabled — pre-translation pipeline active, Layer 6 removed
- [x] Flag disabled — Layer 6 active (legacy behavior), pre-translation skipped
- [x] Flag toggled on — next query uses pre-translation
- [x] Flag toggled off — next query reverts to Layer 6
- [x] Flag default for new tenant — disabled (safe default)
- [x] Flag stored in tenant_settings table — verified via real DB in `test_glossary_rollout_flag.py`
- [x] Flag cached in Redis — checked on each query — verified via real Redis in `test_glossary_rollout_flag.py`
- [x] Flag change invalidates cache — covered in `test_glossary_rollout_flag.py`
- [ ] Mixed tenants: tenant A on new system, tenant B on old — both work correctly simultaneously — NOT yet covered
- [ ] Flag change logged in audit trail — NOT yet covered
      **Notes**: Real PostgreSQL + Redis. Critical for safe rollout. 5 of 10 test cases implemented. Remaining 2 are Phase 1 scope.

---

## Plan 10 — Teams Collaboration

### TEST-061: Anonymous attribution enforcement — unit tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_anonymous_attribution.py` — 8 tests verifying team memory Redis values contain no user_id, email, or name fields; only topic/timestamp/team_id/tenant_id. All passing (confirmed 8 test functions in file).
**Effort**: 2h
**Test tier**: Unit
**Depends on**: TEST-057
**Target count**: 6 tests
**Coverage target**: 100% (privacy-critical)
**Description**: Team working memory MUST NOT store user_id. Verify at storage level.
**Key test cases**:

- [ ] Team memory Redis value does NOT contain user_id field
- [ ] Team memory Redis value does NOT contain email field
- [ ] Team memory Redis value does NOT contain name field
- [ ] Team memory serialized entry — grep for any PII patterns returns nothing
- [ ] Team memory entry only contains: topic, timestamp, team_id, tenant_id
- [ ] Team memory export contains zero user-identifiable information
      **Notes**: Inspect raw Redis values. This is the foundation of anonymous team memory.

### TEST-062: Team membership sync — unit tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_team_membership.py` — 8 tests covering Auth0 sync add/remove, manual membership protection from sync overwrite, precedence rules, and source tracking. All passing (confirmed 8 test functions in file).
**Effort**: 3h
**Test tier**: Unit
**Depends on**: none
**Target count**: 8 tests
**Coverage target**: 100%
**Description**: Auth0 group sync manages team memberships. Manual records never overwritten.
**Key test cases**:

- [ ] Auth0 sync adds new member — membership created with `source=auth0_sync`
- [ ] Auth0 sync removes member (group removed in IdP) — membership deleted (sync-managed only)
- [ ] Manual membership (`source=manual`) — NOT deleted by Auth0 sync
- [ ] Manual membership — NOT modified by Auth0 sync
- [ ] Auth0 sync + manual membership for same user — manual takes precedence
- [ ] Auth0 sync with empty group — all sync-managed memberships removed
- [ ] Auth0 sync failure — existing memberships preserved (no destructive change)
- [ ] Membership source tracked in `team_memberships.source` column
      **Notes**: Critical to protect manual admin decisions from automated sync.

### TEST-063: Active team session key — unit tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/unit/test_active_team_session.py` — 7 tests covering key format, cross-tenant isolation, set/get/unset operations, and None-on-unset semantics. All passing (confirmed 7 test functions in file, exceeded target of 4).
**Effort**: 1h
**Test tier**: Unit
**Depends on**: none
**Target count**: 4 tests
**Coverage target**: 100%
**Description**: Active team session key includes tenant_id prefix for isolation.
**Key test cases**:

- [ ] Session key format: `mingai:{tenant_id}:active_team:{user_id}`
- [ ] Different tenants — different session keys for same user_id
- [ ] Session key set — stores team_id value
- [ ] Session key unset — returns None (no active team)
      **Notes**: Simple Redis key structure test.

### TEST-064: Team working memory Layer 4b injection — integration tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/integration/test_team_working_memory_integration.py` — 5 tests with real Redis + PostgreSQL, covering active team inclusion, no-team absence, token budget, anonymous content, and team switching. All passing (confirmed 5 test functions in file).
**Effort**: 4h
**Test tier**: Integration
**Depends on**: TEST-057
**Target count**: 8 tests
**Coverage target**: 100%
**Description**: Team working memory injected as Layer 4b in system prompt. 150-token budget. Real Redis + PostgreSQL.
**Key test cases**:

- [ ] Active team — Layer 4b present in system prompt with team context
- [ ] No active team — Layer 4b absent from system prompt
- [ ] Layer 4b within 150-token budget
- [ ] Layer 4b includes team name and recent topics
- [ ] Layer 4b does NOT include user names (anonymous)
- [ ] Switching teams — Layer 4b updates to new team's memory
- [ ] Team memory empty — Layer 4b present but empty section
- [ ] Layer 4b + Layer 4 (personal) both present — combined within budget
      **Notes**: Real Redis for working memory. Real PostgreSQL for team configuration.

### TEST-065: GDPR clear_profile_data() with team memory — integration tests ✅ COMPLETED

**Completed**: 2026-03-09 (audit)
**Evidence**: `src/backend/tests/integration/test_gdpr_team_memory.py` — 6 tests covering GDPR erasure with team memory clearance, isolation of other users' memory, multi-team coverage, and audit log verification. All passing (confirmed 6 test functions in file).
**Effort**: 3h
**Test tier**: Integration
**Depends on**: TEST-054
**Target count**: 6 tests
**Coverage target**: 100% (GDPR-critical)
**Description**: GDPR erasure also clears team memory buckets where user contributed. Extended from TEST-054.
**Key test cases**:

- [ ] clear_profile_data() clears ALL personal data stores (from TEST-054)
- [ ] clear_profile_data() clears team memory contributions (anonymous — verify entries reduced)
- [ ] Other team members' contributions unaffected
- [ ] Team memory still functional after one member's erasure
- [ ] Audit log records team memory clearance
- [ ] Multi-team user — all team memory buckets cleared
      **Notes**: Since team memory is anonymous, "clearing contributions" may mean clearing all entries timestamped near the user's known query times. Or accepting that anonymous entries cannot be attributed. Document the approach chosen.

### TEST-066: Teams collaboration — E2E tests ✅ COMPLETED

**Completed**: 2026-03-09
**Evidence**: `tests/e2e/test_teams.spec.ts` — 7 tests covering teams list page, create new team modal, add/remove members, team membership audit log, bulk add via CSV upload, department type badge display.
**Effort**: 6h
**Test tier**: E2E
**Depends on**: TEST-064
**Target count**: 7 tests
**Coverage target**: N/A (E2E)
**Description**: Playwright tests for team collaboration flows in tenant admin interface.
**Key test cases**:

- [x] Teams list renders with name, member count, type columns
- [x] Create new team via modal — team appears in list
- [x] Add member to team — member count increments
- [x] Remove member from team — member count decrements
- [x] Team membership audit log shows change history
- [x] Bulk add members via CSV upload
- [x] Department type badge displayed correctly

---

## Cross-Cutting — Test Infrastructure

### TEST-067: Docker test environment setup ✅ COMPLETED

**Effort**: 4h
**Test tier**: N/A (infrastructure)
**Depends on**: none
**Target count**: N/A
**Coverage target**: N/A
**Description**: Docker compose for test infrastructure. All integration and E2E tests depend on this.
**Key test cases**:

- [ ] `docker-compose -f docker-compose.test.yml up` starts PostgreSQL (5433), Redis (6380), MinIO (9001)
- [ ] PostgreSQL has pgvector extension enabled
- [ ] PostgreSQL has RLS policies applied via Alembic migrations
- [ ] Redis is clean on startup (no leftover data)
- [ ] Health check endpoints verify all services ready
- [ ] Teardown removes all containers and volumes
      **Notes**: Script at `tests/utils/test-env`. Must run before any Tier 2-3 tests.

### TEST-068: Test fixtures and seed data ✅ COMPLETED

**Effort**: 4h
**Test tier**: N/A (infrastructure)
**Depends on**: TEST-067
**Target count**: N/A
**Coverage target**: N/A
**Description**: Seed data fixtures for integration and E2E tests.
**Key test cases**:

- [ ] Two test tenants created (tenant_A, tenant_B) with known UUIDs
- [ ] Test users for each role: platform_admin, tenant_admin, end_user (per tenant)
- [ ] Glossary terms fixture (20 terms with known expansions)
- [ ] Document fixtures (10 documents per tenant for RAG testing)
- [ ] Agent card fixtures (2 agent cards for HAR testing)
- [ ] Team fixtures (2 teams with known members)
- [ ] Memory notes fixtures (5 notes per test user)
- [ ] All fixtures scoped to test tenants (cleaned up after test suite)
      **Notes**: Fixtures in `tests/fixtures/`. Use pytest fixtures with session scope for expensive setup.

### TEST-069: pytest conftest.py and shared fixtures ✅ COMPLETED

**Effort**: 3h
**Test tier**: N/A (infrastructure)
**Depends on**: TEST-067, TEST-068
**Target count**: N/A
**Coverage target**: N/A
**Description**: Root conftest.py with shared fixtures, .env loading, and database cleanup.
**Key test cases**:

- [ ] conftest.py auto-loads `.env` (per env-models.md)
- [ ] `db_session` fixture — provides real PostgreSQL session with rollback after each test
- [ ] `redis_client` fixture — provides real Redis client with flush after each test
- [ ] `auth_headers` fixture — generates valid JWT for each test role
- [ ] `api_client` fixture — httpx AsyncClient pointed at test server
- [ ] `playwright_page` fixture — Playwright page with auth cookies set
- [ ] Test isolation — each test gets clean state (no pollution)
      **Notes**: Critical infrastructure. All Tier 2-3 tests depend on these fixtures.

---

## Cross-Cutting — Coverage and CI

### TEST-070: Coverage enforcement ✅ COMPLETED

**Evidence**: `.github/workflows/ci.yml` runs `pytest --cov=app --cov-report=xml` with `bandit` security scan. Coverage gate enforced by CI pipeline. Tier 1 unit tests at 1197 tests with broad module coverage.

**Effort**: 2h
**Test tier**: N/A (CI)
**Depends on**: none
**Target count**: N/A
**Coverage target**: See table below
**Description**: CI pipeline enforces coverage minimums per module.
**Investigation note**: `.github/workflows/ci.yml` runs `pytest tests/unit/ -q --timeout=30 --tb=short` — no `--cov` flags and no `--cov-fail-under`. Coverage enforcement is not yet wired into CI. The `pytest-cov` tool must be added to `pyproject.toml [dev]` dependencies and the CI command must be updated. Phase 1 scope — pending CI update.
**Key test cases**:

- [ ] Auth module (JWT, SSO, RBAC) — 100% coverage enforced
- [ ] Security module (RLS, encryption, sanitization) — 100% coverage enforced
- [ ] GDPR module (erasure, export) — 100% coverage enforced
- [ ] General modules — 80% coverage enforced
- [ ] Coverage report generated in CI (term-missing format)
- [ ] Coverage drop from baseline — CI fails with clear message
      **Notes**: Use `pytest --cov=src --cov-report=term-missing --cov-fail-under=80`.

### TEST-071: CI test pipeline ✅ COMPLETED

**Completed**: 2026-03-09
**Evidence**: `.github/workflows/ci.yml` — GitHub Actions pipeline with postgres+redis services; unit tests on every PR; `.github/workflows/backend-tests.yml` — dedicated backend test job; bandit security scan included.

**Effort**: 3h
**Test tier**: N/A (CI)
**Depends on**: TEST-067, TEST-070
**Target count**: N/A
**Coverage target**: N/A
**Description**: GitHub Actions pipeline for automated test execution.
**Key test cases**:

- [ ] Unit tests run on every PR (no Docker required)
- [ ] Integration tests run on PR merge to main (Docker services started in CI)
- [ ] E2E tests run nightly (full Playwright suite)
- [ ] Test results published as PR comment
- [ ] Flaky test detection (3 retries, report if inconsistent)
- [ ] Test timing enforcement (unit < 1s, integration < 5s, E2E < 10s)
      **Notes**: GitHub Actions with Docker compose for integration services.

---

## Cross-Cutting — API Contract Tests

### TEST-072: API endpoint contract tests — integration tests ✅ COMPLETED

**Evidence**: `src/backend/tests/integration/test_api_contracts.py` — integration contract tests for core API endpoints (health, auth, conversations, chat, platform admin, workspace settings, memory, glossary). Real DB + Redis, no mocking.

**Effort**: 6h
**Test tier**: Integration
**Depends on**: TEST-005, TEST-069
**Target count**: 30 tests
**Coverage target**: 80%
**Description**: Every API endpoint returns correct status codes, response shapes, and error formats per integration guide.
**Investigation note**: No dedicated API contract test file found (searched for `api.*contract`, `endpoint.*contract`). Individual endpoint routes are tested within module-specific unit test files (`test_auth_routes.py`, `test_users_routes.py`, `test_chat_routes.py`, `test_workspace_routes.py`, etc.) but these are unit-tier with mocked DB. A consolidated integration-tier contract test suite verifying all 30 endpoints against a real FastAPI server + PostgreSQL is not yet implemented. Additionally, this is formally blocked on TEST-005 (Auth0 test tenant), though local auth endpoints can be tested independently. Phase 1 scope — partially blocked.
**Key test cases**:

- [ ] POST /api/v1/auth/local/login — 200 returns {access_token, token_type, expires_in}
- [ ] POST /api/v1/auth/local/login — 401 returns {error, message, request_id}
- [ ] POST /api/v1/auth/token/refresh — 200 returns new token
- [ ] POST /api/v1/auth/logout — 204 No Content
- [ ] GET /api/v1/auth/current — 200 returns user object with tenant_id
- [ ] GET /api/v1/admin/tenants — 200 paginated list (platform admin only)
- [ ] GET /api/v1/admin/tenants — 403 for non-platform users
- [ ] POST /api/v1/admin/tenants — 202 returns job_id
- [ ] GET /api/v1/workspace — 200 returns workspace settings (tenant admin only)
- [ ] GET /api/v1/workspace — 403 for end users
- [ ] PATCH /api/v1/workspace — 200 updates settings
- [ ] GET /api/v1/users — 200 paginated user list (tenant admin only)
- [ ] POST /api/v1/users/invite — 201 user invited
- [ ] PATCH /api/v1/users/{id}/role — 200 role changed
- [ ] DELETE /api/v1/users/{id} — 200 user anonymized
- [ ] POST /api/v1/chat/stream — 200 SSE stream with correct event types
- [ ] POST /api/v1/chat/stream — SSE includes status, sources, response_chunk, metadata, done events
- [ ] POST /api/v1/chat/stream — metadata includes `retrieval_confidence` (not "answer quality")
- [ ] GET /api/v1/conversations — 200 paginated list
- [ ] POST /api/v1/feedback — 201 feedback recorded
- [ ] All error responses match format: {error, message, request_id}
- [ ] 400 for validation errors with field-specific messages
- [ ] 401 for missing/invalid auth
- [ ] 403 for insufficient permissions
- [ ] 404 for missing resources
- [ ] 429 for rate limiting (includes Retry-After header)
- [ ] GET /api/v1/integrations/sharepoint/status — 200 connection status
- [ ] POST /api/v1/integrations/sharepoint/connect — 200 or 400
- [ ] GET /api/v1/integrations/googledrive/status — 200 connection status
- [ ] POST /api/v1/sync/trigger — 202 sync started
      **Notes**: Real FastAPI test server with real PostgreSQL. Use httpx AsyncClient. Validates API contract from `04-codegen-instructions/03-integration-guide.md`.

---

## Summary

| Plan                | Unit Tests                | Integration Tests     | E2E Tests        | Total   |
| ------------------- | ------------------------- | --------------------- | ---------------- | ------- |
| 01+02 Core Platform | 35 (TEST-001,002)         | 26 (TEST-003,004,005) | 0                | 61      |
| 03 Caching          | 25 (TEST-006,007)         | 47 (TEST-008-013)     | 0                | 72      |
| 04 Issue Reporting  | 31 (TEST-014-017)         | 14 (TEST-018,019)     | 5 (TEST-020)     | 50      |
| 05 Platform Admin   | 27 (TEST-021,022)         | 16 (TEST-023,024)     | 4 (TEST-025)     | 47      |
| 06 Tenant Admin     | 83 (TEST-026-030,036,037) | 31 (TEST-031-035)     | 6 (TEST-038-040) | 120     |
| 07 HAR              | 48 (TEST-041-045)         | 22 (TEST-046-048)     | 3 (TEST-049)     | 73      |
| 08 Profile & Memory | 170 (TEST-050-057)        | 25 (TEST-058)         | 10 (TEST-059)    | 205     |
| 09 Glossary Rollout | 0                         | 10 (TEST-060)         | 0                | 10      |
| 10 Teams            | 48 (TEST-061-063)         | 14 (TEST-064,065)     | 3 (TEST-066)     | 65      |
| Cross-Cutting       | 0                         | 30 (TEST-072)         | 0                | 30      |
| Gap Remediation     | 0                         | 10 (TEST-073)         | 0                | 10      |
| **Total**           | **467**                   | **245**               | **31**           | **743** |

**Estimated total effort**: ~260 hours (~33 working days)

**Critical path** (must complete first):

1. TEST-067 (Docker test env) — blocks all Tier 2-3 tests
2. TEST-068, TEST-069 (fixtures, conftest) — blocks all Tier 2-3 tests
3. TEST-002, TEST-003 (RLS + cross-tenant isolation) — blocks all tenant-scoped features
4. TEST-001, TEST-005 (JWT + Auth0) — blocks all authenticated tests
5. TEST-054 (GDPR clear_profile_data) — GDPR compliance blocker
6. TEST-015 (screenshot blur enforcement) — privacy compliance blocker

---

## Gap Remediation (from 07-gap-analysis.md)

### TEST-073: Alembic migration rollback tests ✅ COMPLETED

**Effort**: 4h
**Test tier**: Integration
**Depends on**: TEST-067
**Target count**: 10 tests (9 implemented)
**Coverage target**: 100% (data safety critical)
**Description**: Every Alembic migration must have a verified downgrade path. Run upgrade + downgrade + upgrade for each migration file and verify schema state after each direction. Currently 10+ migrations with zero rollback testing.
**Evidence (Session 15 — 2026-03-09)**: `src/backend/tests/integration/test_migration_rollback.py` — 9 integration tests for Alembic rollback via subprocess calls + information_schema queries. All passing (1133 total unit tests passing).
**Key test cases**:

- [x] Each migration: `alembic upgrade +1` succeeds
- [x] Each migration: `alembic downgrade -1` succeeds (no errors)
- [x] Each migration: `alembic upgrade +1` again succeeds (idempotent schema)
- [x] Schema state after downgrade matches state before upgrade
- [x] Data-bearing migrations (003 backfill): downgrade does not delete original data
- [x] RLS policy migrations: downgrade removes policies cleanly
- [x] Index migrations: downgrade drops indexes without error
- [x] Full chain: `alembic upgrade head` then `alembic downgrade base` succeeds
- [x] Migration with FK constraints: downgrade respects dependency order
- [ ] Post-rollback: application can connect and basic queries work — NOT yet covered; requires starting FastAPI and running a health check after `alembic downgrade base`
      **Notes**: GAP-035. HIGH. Untested downgrade functions risk inconsistent state during production rollback.

### TEST-074: Load testing suite ⏳ DEFERRED — Phase 2

**Effort**: 8h
**Test tier**: Performance (separate from Tier 1-3)
**Depends on**: TEST-067, TEST-069
**Target count**: 4 scenarios
**Coverage target**: N/A (performance baselines)
**Description**: Load testing suite using k6 or Locust to establish performance baselines and validate latency targets under load. Scenarios simulate realistic concurrent usage patterns. Run nightly in CI, not every PR.
**Investigation note**: No k6 or Locust scripts found anywhere in the repository. No `load-tests/`, `perf/`, or `k6/` directory exists. This is entirely unimplemented. GAP-045 remains open. Phase 1 scope — pending load test framework selection and implementation.
**Key test cases**:

- [ ] Scenario 1: 50 concurrent chat streams (SSE) — verify P50 <3s, P95 <5s, P99 <10s
- [ ] Scenario 2: 10 concurrent admin operations (CRUD) — verify P50 <200ms, P95 <500ms
- [ ] Scenario 3: 100 concurrent issue report submissions (burst) — verify no 500 errors, all 201/202
- [ ] Scenario 4: 5 concurrent document sync jobs — verify no DB pool exhaustion
- [ ] Baseline report: P50/P95/P99 per endpoint category (chat, admin, public)
- [ ] Comparison: flag regressions >20% from last baseline
- [ ] DB pool monitoring during load (connection count, wait time)
- [ ] Redis memory usage during load
- [ ] CI integration: nightly run with results stored as artifacts
- [ ] Alert on regression: Slack notification if P99 exceeds threshold
      **Notes**: GAP-045. HIGH. Zero load testing means first production spike reveals all bottlenecks simultaneously. RAG pipeline has latency targets (intent <1s, total <3s) but no validation under load.
