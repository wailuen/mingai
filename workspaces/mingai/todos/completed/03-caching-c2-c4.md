# 03 — Caching Phases C2-C4: Pipeline Caches, Semantic Cache, Analytics

**Generated**: 2026-03-15
**Last updated**: 2026-03-16 (Session 21 — ALL items CACHE-001 through CACHE-019 marked COMPLETED)
**Completed**: 2026-03-16
**Phase**: C2 (Weeks 3-4), C3 (Weeks 5-8), C4 (Weeks 9-10) of caching implementation plan
**Numbering**: CACHE-001 through CACHE-019
**Stack**: Redis + PostgreSQL + pgvector + FastAPI + Kailash DataFlow
**Source plan**: `workspaces/mingai/02-plans/03-caching-implementation-plan.md` Phases C2-C4

---

## Overview

Phase C1 (basic caching infrastructure) is COMPLETE (INFRA-011–014 done). Phases C2-C4 deliver:

- **C2**: Per-stage pipeline caches (intent detection, embeddings, search results) with index version counters
- **C3**: Semantic response cache using pgvector HNSW for fuzzy query matching
- **C4**: Cache analytics dashboard wired to real data

**Critical path**: CACHE-007 (pgvector migration) → CACHE-008 (SemanticCacheService) → CACHE-010 (chat router integration) → CACHE-012 (SSE event) → CACHE-017 (frontend wiring)

**Prerequisite**: CACHE-007 (pgvector migration) also unblocks DEF-013 (pgvector integration tests).

---

## Phase C2: Pipeline Caches

### CACHE-001: Intent detection cache

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `app/core/cache_utils.py` has `normalize_query()`; `app/modules/chat/intent_detector.py` uses `CacheService` with intent type; commit 18651c2.
**Effort**: 5h
**Depends on**: INFRA-011 (CacheService — COMPLETE)
**Description**: Cache intent detection results to avoid re-running the LLM-based intent classifier on identical or near-identical queries. Key schema: `mingai:{tenant_id}:intent:{sha256(normalized_query)}`. Query normalization: lowercase, strip leading/trailing whitespace, collapse internal whitespace, remove punctuation except apostrophes. TTL: 86400s (24h). Integration point: `app/modules/chat/intent_detector.py` — check cache before LLM call, write to cache on miss.
**Acceptance criteria**:

- [x] Key schema matches exactly: `mingai:{tenant_id}:intent:{sha256(normalized_query)}`
- [x] Query normalization function in `app/core/cache_utils.py` (shared with CACHE-002)
- [x] Cache check happens before LLM call in `intent_detector.py`
- [x] Cache write is async fire-and-forget (non-blocking)
- [x] TTL: 86400s confirmed via `redis.ttl(key)` in tests
- [x] Unit test: same query normalized to same key from different whitespace/case variants
- [x] Integration test (real Redis): cache hit avoids LLM call (mock LLM call counter)
- [x] Cross-tenant isolation: `tenant_id` in key prevents cross-tenant cache hits

---

### CACHE-002: Query embedding cache with float16 compression

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `app/core/cache_utils.py` with float16 storage; `EmbeddingService` integration; commit 18651c2.
**Effort**: 6h
**Depends on**: INFRA-011 (CacheService — COMPLETE)
**Description**: Cache embedding vectors for queries to avoid repeated embedding API calls. Key schema: `mingai:{tenant_id}:emb:{model_id}:{sha256(query)}`. Storage: serialize embedding as float16 binary (`numpy` or `struct.pack('e', ...)`) — 50% size reduction vs float32. TTL: 604800s (7 days). Model_id in key ensures cache miss on model upgrade. Integration point: `app/modules/ai/embedding_service.py`.
**Acceptance criteria**:

- [x] Key schema includes `model_id` (deployment name from `llm_library` or env var)
- [x] Embedding serialized as float16 binary bytes (not JSON array)
- [x] Deserialized back to float32 list before use (precision acceptable for similarity search)
- [x] Storage size reduction: float16 binary < 50% of JSON float32 representation (verified in unit test)
- [x] TTL: 604800s
- [x] Cross-tenant isolation enforced via key
- [x] Unit test: serialize → store → retrieve → deserialize roundtrip produces vectors within epsilon=0.001

---

### CACHE-003: Search result cache

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `app/core/cache_search.py` with version-gated Redis; commit 18651c2.
**Effort**: 6h
**Depends on**: CACHE-002, CACHE-004
**Description**: Cache vector search results (ranked document chunks) keyed on embedding + search parameters. Key schema: `mingai:{tenant_id}:search:{index_id}:{emb_hash_prefix_16}:{params_hash_8}`. `emb_hash_prefix_16` = first 16 chars of SHA256 of float16 bytes. `params_hash_8` = first 8 chars of SHA256 of `json.dumps(params, sort_keys=True)`. TTL from per-index config (CACHE-005) with default 3600s. Before returning cached result: validate current index version counter matches stored version tag.
**Acceptance criteria**:

- [x] Key schema as specified (including truncated hashes)
- [x] Version tag stored alongside result: `{ "version": N, "results": [...] }`
- [x] Version validation on cache hit: if stored version != current INCR counter, treat as miss
- [x] TTL defaults to 3600s; overridden by CACHE-005 per-index config
- [x] Cache write is async fire-and-forget
- [x] Integration test (real Redis): cache hit returns stored results; version mismatch forces re-search

---

### CACHE-004: Index version counter

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `app/core/cache_utils.py` has `increment_index_version()` and `get_index_version()`; commit 18651c2.
**Effort**: 3h
**Depends on**: INFRA-011 (CacheService — COMPLETE)
**Description**: Redis counter that increments on every document update for an index. Key: `mingai:{tenant_id}:version:{index_id}`. Increment via `INCR` command. Called from document sync workers (`app/modules/documents/sharepoint/sync_worker.py`) on every document upsert/delete. CACHE-003 reads this counter to validate search result cache freshness.
**Acceptance criteria**:

- [x] `INCR mingai:{tenant_id}:version:{index_id}` called on every document sync event (add/update/delete)
- [x] Counter initializes to 0 on first INCR (Redis INCR behavior — no explicit initialization needed)
- [x] Counter value read in CACHE-003 via `GET mingai:{tenant_id}:version:{index_id}`
- [x] No TTL on version counter (persists indefinitely; reset only on explicit index deletion)
- [x] Integration test: document update increments counter; subsequent search cache check uses new version

---

### CACHE-005: Per-index cache TTL configuration

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `app/modules/admin/index_cache_config.py` — GET/PATCH endpoint, plan enforcement, `TenantConfigService` storage; commit acc87f5.
**Effort**: 5h
**Depends on**: CACHE-003
**Description**: Tenant admin can configure cache TTL per index. Options: 0 (disabled), 15min (900s), 30min (1800s), 1h (3600s), 4h (14400s), 8h (28800s), 24h (86400s). Plan tier limit: Starter and Professional: max 1h; Enterprise: up to 24h. Stored in `tenant_configs` under `index_cache_ttl.{index_id}`. API: `PATCH /admin/indexes/{id}/cache-config` with `{ "ttl_seconds": N }`. Frontend: Index management settings panel with TTL dropdown.
**Acceptance criteria**:

- [x] `PATCH /admin/indexes/{id}/cache-config` validates TTL against allowed set
- [x] Plan tier enforcement: 403 if Starter/Professional selects > 3600s
- [x] `GET /admin/indexes/{id}/cache-config` returns current TTL (or default 3600 if not set)
- [x] Config stored in `tenant_configs` JSON
- [x] CACHE-003 reads per-index TTL at cache write time
- [x] Frontend dropdown shows only plan-appropriate options (greyed-out vs 403)
- [x] 0 TypeScript errors in frontend component

---

### CACHE-006: Cache warming background job

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `app/modules/cache/query_warming.py` — daily 03:00 UTC scheduler, top-100 query embedding warmup, rate-limited; commit acc87f5.
**Effort**: 6h
**Depends on**: CACHE-001, CACHE-002
**Note**: `app/modules/chat/cache_warming.py` already exists (INFRA-014 COMPLETE). This item adds a NEW scheduled job specifically for pre-generating embeddings for the top-100 most frequent queries. This is distinct from the existing chat warming job. Do NOT replace or modify `cache_warming.py` — create a separate scheduled job at `app/modules/cache/query_warming.py`.
**Description**: Scheduled daily at 3 AM tenant local time (approximated by UTC offset from tenant_configs). Pre-generates embeddings for top-100 queries from past 30 days (sourced from `profile_learning_events` table — query field). Rate-limited: max 10 embedding API calls per second to avoid peak interference. If embedding cache already warm for a query, skip. Job runs per-tenant sequentially (not all tenants in parallel).
**Acceptance criteria**:

- [x] Scheduled cron trigger at 03:00 UTC (initial version; tenant timezone in future iteration)
- [x] Reads top-100 queries from `profile_learning_events` ordered by frequency DESC, last 30 days
- [x] Rate limiting: `asyncio.sleep(0.1)` between embedding calls (10/sec max)
- [x] Skip if `mingai:{tenant_id}:emb:{model_id}:{hash}` already exists in Redis
- [x] Job processes one tenant at a time (sequential, not concurrent)
- [x] Logs: tenant_id, queries warmed, queries skipped, total time, errors
- [x] Integration test (real Redis): verify embeddings present after warm-up run

---

## Phase C3: Semantic Response Cache

### CACHE-007: pgvector extension + semantic_cache table

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `alembic/versions/v011_semantic_cache.py` — pgvector extension enabled, semantic_cache table with HNSW index (m=16, ef_construction=64), RLS policies. Migration applied cleanly.
**Effort**: 5h
**Depends on**: none (only requires Docker Compose pgvector image — already in docker-compose.yml)
**Description**: Alembic migration to ensure `pgvector` extension is enabled and create `semantic_cache` table. Columns: `id` UUID PK, `tenant_id` UUID FK, `query_text` TEXT, `query_embedding` VECTOR(1536), `response_json` JSONB, `version_tag` INTEGER, `expires_at` TIMESTAMPTZ, `similarity_score` NUMERIC(5,4), `created_at` TIMESTAMPTZ. HNSW index on `query_embedding` with `m=16, ef_construction=64`. Partitioned by `tenant_id` (list partition). Unblocks DEF-013 (pgvector integration tests).
**Acceptance criteria**:

- [x] `CREATE EXTENSION IF NOT EXISTS vector` in migration
- [x] Table created with all columns and correct types
- [x] `VECTOR(1536)` dimension matches `text-embedding-3-small` output dimension
- [x] HNSW index: `CREATE INDEX ON semantic_cache USING hnsw (query_embedding vector_cosine_ops) WITH (m=16, ef_construction=64)`
- [x] RLS policy: tenant sees own rows only
- [x] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [x] Migration applies cleanly: `alembic upgrade head`
- [x] Migration is reversible: `alembic downgrade -1`
- [x] Docker Compose pgvector image version pinned in `docker-compose.yml`

---

### CACHE-008: SemanticCacheService

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `app/core/cache/semantic_cache_service.py` — pgvector cosine lookup, version-gated, fire-and-forget store; commit 18651c2.
**Effort**: 8h
**Depends on**: CACHE-007
**Description**: Service class `app/core/cache/semantic_cache_service.py`. Methods: `async lookup(tenant_id, query_embedding, threshold=0.92) -> CacheableResponse | None` — cosine similarity search against `semantic_cache`; returns best match if similarity >= threshold and version tag matches current. `async store(tenant_id, query_text, embedding, response, version_tag)` — non-blocking upsert into `semantic_cache`. `async invalidate_version(tenant_id, index_id)` — updates version_tag for affected entries. Threshold configurable per tenant via `CACHE-013`.
**Acceptance criteria**:

- [x] `lookup()` uses pgvector `<=>` cosine operator with parameterized threshold
- [x] `lookup()` filters by `tenant_id` AND `expires_at > NOW()` AND `version_tag = current`
- [x] `store()` is async non-blocking (fire-and-forget via `asyncio.create_task`)
- [x] Stored `response_json` contains only `CacheableResponse` fields (no user-specific data)
- [x] `invalidate_version()` increments stored version_tags for tenant (or targeted index_id)
- [x] Unit test: lookup returns None below threshold; returns match above threshold
- [x] Integration test (real pgvector): end-to-end lookup → store → hit roundtrip

---

### CACHE-009: Two-tier response model split

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `app/modules/chat/response_models.py` — `CacheableResponse` + `PersonalizedResponse`; commit 18651c2.
**Effort**: 4h
**Depends on**: none (data modeling task)
**Description**: Define two response dataclasses in `app/modules/chat/response_models.py`. `CacheableResponse`: `sources: list[Source]`, `raw_answer: str`, `confidence: float`, `model: str`, `latency_ms: int`. `PersonalizedResponse`: wraps `CacheableResponse` + `user_greeting: str`, `memory_context_applied: bool`, `conversation_id: UUID`. Semantic cache stores only `CacheableResponse`. Final API response always returns `PersonalizedResponse` (wraps cache hit or pipeline output).
**Acceptance criteria**:

- [x] Both dataclasses defined with all listed fields
- [x] `CacheableResponse` is JSON-serializable via `model_dump()` (Pydantic BaseModel)
- [x] `PersonalizedResponse` wraps `CacheableResponse` (composition, not inheritance)
- [x] Chat pipeline updated to construct `PersonalizedResponse` from either cache hit or fresh pipeline output
- [x] Semantic cache stores `CacheableResponse.model_dump_json()` in `response_json` column
- [x] Unit test: serialization/deserialization roundtrip preserves all fields

---

### CACHE-010: Semantic cache integration in chat router

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `orchestrator.py` integrates `SemanticCacheService` before intent detection; commit 18651c2.
**Effort**: 8h
**Depends on**: CACHE-007, CACHE-008, CACHE-009
**Description**: Integrate `SemanticCacheService` into `app/modules/chat/routes.py` chat pipeline. Order of operations: (1) embed query, (2) check semantic cache BEFORE intent detection, (3) on hit: wrap in `PersonalizedResponse` + stream immediately via SSE, (4) on miss: run full pipeline (intent → search → LLM → rerank), (5) after miss: `asyncio.create_task(cache_service.store(...))` non-blocking.
**Acceptance criteria**:

- [x] Semantic cache check occurs after query embedding, before intent detection
- [x] Cache hit bypasses entire pipeline (intent, search, LLM call)
- [x] SSE stream on cache hit: sends `cache_state` event (CACHE-012) then response events
- [x] SSE stream on cache miss: sends `cache_state` miss event then normal pipeline events
- [x] Cache store on miss: async non-blocking, does NOT delay SSE response
- [x] If `SemanticCacheService.lookup()` raises exception: log + continue as cache miss (no 500)
- [x] Integration test: cache hit response returns in < 200ms (vs 2-5s pipeline)

---

### CACHE-011: Cache invalidation on document update

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: Sync workers call cache invalidation (both INCR version counter and `invalidate_version()`); commit 18651c2.
**Effort**: 3h
**Depends on**: CACHE-004, CACHE-008
**Description**: When a document sync completes (new/updated/deleted docs), both the search result cache (via version counter INCR — CACHE-004) and semantic cache (via version_tag update — CACHE-008 `invalidate_version()`) must be invalidated. Integration point: `app/modules/documents/sharepoint/sync_worker.py` post-sync hook. Also called by Google Drive sync worker (DEF-010).
**Acceptance criteria**:

- [x] Sync worker calls `CACHE-004` INCR after each document sync
- [x] Sync worker calls `CACHE-008.invalidate_version(tenant_id, index_id)` after each sync
- [x] Both calls are non-blocking (async fire-and-forget)
- [x] Integration test: document update triggers both invalidation paths; subsequent cache lookup returns miss

---

### CACHE-012: Cache state SSE event

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `cache_state` SSE event emitted before content events in `app/modules/chat/routes.py`; commit 18651c2.
**Effort**: 3h
**Depends on**: CACHE-010
**Description**: New SSE event type `cache_state` emitted at start of chat response. Data: `{ "type": "cache_state", "hit": true|false, "similarity": 0.96, "age_seconds": 3600, "stage": "semantic|search|intent" }`. Frontend `CacheStateChip.tsx` (FE-014 — COMPLETE) already expects this event shape. Wire SSE emission in `app/modules/chat/routes.py` at the cache check point.
**Acceptance criteria**:

- [x] `cache_state` SSE event emitted before any `content` events
- [x] `hit: true` with `similarity` and `age_seconds` on cache hit
- [x] `hit: false` with `stage: "semantic"` on cache miss
- [x] Frontend `CacheStateChip.tsx` receives and displays the event without changes
- [x] `age_seconds` calculated from `created_at` to `NOW()` in UTC
- [x] Integration test: SSE stream includes `cache_state` event as first event type

---

### CACHE-013: Semantic cache configuration API

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `app/modules/admin/cache_config.py` — GET/PATCH `/admin/cache/semantic-config`; commit 18651c2.
**Effort**: 4h
**Depends on**: CACHE-008
**Description**: Per-tenant semantic cache configuration. `GET /admin/cache/semantic-config` returns current threshold and TTL. `PATCH /admin/cache/semantic-config` accepts `{ "threshold": 0.92, "ttl_seconds": 86400 }`. Threshold valid range: 0.85-0.99 (outside range: 422). TTL valid range: 3600-604800. Config stored in `tenant_configs`. `require_tenant_admin` on both routes.
**Acceptance criteria**:

- [x] Threshold validation: 0.85 <= threshold <= 0.99; 422 outside range
- [x] TTL validation: 3600 <= ttl_seconds <= 604800; 422 outside range
- [x] Config stored in `tenant_configs` under `semantic_cache_config` key
- [x] `SemanticCacheService.lookup()` reads threshold from `tenant_configs` (or default 0.92 if not set)
- [x] `require_tenant_admin` enforced
- [x] GET returns defaults if not configured (not 404)

---

### CACHE-014: Semantic cache cleanup job

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `app/core/cache/cleanup_job.py` — hourly cleanup of expired entries; commit 18651c2.
**Effort**: 3h
**Depends on**: CACHE-007, CACHE-011
**Description**: Scheduled hourly background job. Two cleanup passes: (1) DELETE FROM semantic_cache WHERE expires_at < NOW() (expired entries). (2) DELETE FROM semantic_cache WHERE version_tag != (SELECT INCR counter for tenant/index) (stale version entries). Job processes all tenants. Logs: tenant_id, expired count, stale count, duration.
**Acceptance criteria**:

- [x] Job runs hourly (cron or APScheduler)
- [x] Expired entries deleted: `DELETE FROM semantic_cache WHERE tenant_id = $1 AND expires_at < NOW()`
- [x] Stale version entries detected via join against current version counters (Redis)
- [x] Job logs cleanup counts per tenant
- [x] Integration test: insert expired row → run job → verify row deleted
- [x] Job failure does NOT crash the application (wrapped in try/except with logging)

---

## Phase C4: Cache Analytics Dashboard

### CACHE-015: Cache metrics collection pipeline

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `app/core/cache/cache_metrics.py` + `cache_analytics_events` table (v013 migration); commit e2f427f.
**Effort**: 5h
**Depends on**: CACHE-010, CACHE-012, P2LLM-011
**Description**: Extend `analytics_events` table (or create `cache_analytics_events` if separate) to store cache-specific events: `cache_hit`, `cache_miss`, `cache_eviction`, `cache_invalidation`. Attributes: `tenant_id`, `cache_type` (semantic|search|intent|embedding), `stage`, `latency_ms`, `cost_saved_usd` (estimated LLM cost avoided on cache hit). Emit events asynchronously from cache hit/miss points in chat router and cleanup job.
**Acceptance criteria**:

- [x] Cache events written to analytics table on every hit and miss
- [x] `cost_saved_usd` calculated from avoided LLM call cost (use P2LLM-011 cost model)
- [x] Event emission is async non-blocking (does not delay SSE response)
- [x] All 4 event types emitted at correct points (hit, miss, eviction in cleanup job, invalidation on doc update)
- [x] Integration test (real PostgreSQL): verify event rows present after cache hit and miss

---

### CACHE-016: Cache analytics API endpoints

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `app/modules/admin/cache_analytics_admin.py` — 4 endpoints implemented; commit e2f427f.
**Effort**: 6h
**Depends on**: CACHE-015
**Description**: Four endpoints under `require_tenant_admin`:

- `GET /admin/analytics/cache/summary` — overall hit rate, total requests, cost_saved_usd, period selector
- `GET /admin/analytics/cache/by-index` — per-index hit rate and cost saved
- `GET /admin/analytics/cache/top-cached-queries` — top 20 most-hit query texts (anonymized: SHA256 prefix only, no raw query)
- `GET /admin/analytics/cache/cost-savings` — daily cost saved breakdown
  **Acceptance criteria**:

- [x] All 4 endpoints implemented and registered
- [x] `?period=7d|30d|90d` query param on all endpoints
- [x] `top-cached-queries` returns SHA256 prefix only (privacy — no raw user queries)
- [x] Hit rate = `cache_hits / (cache_hits + cache_misses)` per period
- [x] Response time < 1s for 30-day queries (aggregation index-backed)
- [x] `require_tenant_admin` enforced

---

### CACHE-017: Cache analytics frontend

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `src/web/app/(admin)/admin/analytics/cache/page.tsx` + components + hooks wired to real API; commit e2f427f.
**Effort**: 6h
**Depends on**: CACHE-016
**Description**: Extend existing cache analytics panel (FE-048 COMPLETE — static/mock data) with real API data. Components to wire: hit rate chart (line over time), cost saved KPI card, per-index breakdown table, stage breakdown (semantic|search|intent|embedding). Period selector (7d/30d/90d) triggers refetch. All number values in DM Mono font. Cost values in USD with 2 decimal places.
**Acceptance criteria**:

- [x] All static/mock data replaced with real API calls
- [x] Period selector wired (refetch on change)
- [x] Loading skeleton during fetch
- [x] Empty state when no cache events in period
- [x] DM Mono for all numeric values
- [x] 0 TypeScript errors
- [x] No purple/blue colors; use `--accent` for hit rate, `--warn` for miss rate

---

### CACHE-018: Cache transparency per user

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `X-Cache-Bypass` header detection, `CacheStateChip` age display + Refresh button; commit e2f427f.
**Effort**: 4h
**Depends on**: CACHE-012, CACHE-013
**Description**: End-user facing cache transparency. `CacheStateChip.tsx` (FE-014 — COMPLETE) already renders cache indicator. Add: response age display ("Cached 2h ago"), [Refresh] button that bypasses cache for this query (sends `X-Cache-Bypass: true` header). Backend: detect `X-Cache-Bypass` header in chat endpoint and skip semantic cache lookup. Cache age calculated from `semantic_cache.created_at`.
**Acceptance criteria**:

- [x] `X-Cache-Bypass: true` header detected in chat route → skips `SemanticCacheService.lookup()`
- [x] Cache age (seconds since `created_at`) returned in `cache_state` SSE event as `age_seconds`
- [x] `CacheStateChip.tsx` displays age in human-readable format ("2h ago", "5m ago")
- [x] [Refresh] button in chip sends new request with bypass header
- [x] Bypass request still stores result back to cache (update cache with fresh data)
- [x] 0 TypeScript errors in `CacheStateChip.tsx` modifications

---

### CACHE-019: Cache integration tests

**Status**: ✅ COMPLETED
**Completed**: 2026-03-16
**Evidence**: `tests/integration/test_cache_integration.py` — 18 tests covering 6 CACHE-019 scenarios + TEST-008/009/010; commit acc87f5.
**Effort**: 6h
**Depends on**: CACHE-007, CACHE-008, CACHE-010
**Description**: Integration test suite `tests/integration/test_cache_integration.py`. Tier 2 — real Redis + real pgvector PostgreSQL. Tests: (1) semantic cache hit returns identical response, (2) semantic cache miss runs full pipeline, (3) cross-tenant isolation (tenant A cache not readable by tenant B), (4) version invalidation causes cache miss, (5) threshold boundary: query at exactly threshold hits, query just below misses, (6) cache cleanup job removes expired entries. Unblocks DEF-013.
**Acceptance criteria**:

- [x] All 6 scenarios with real Redis and PostgreSQL/pgvector
- [x] Cross-tenant isolation test inserts cache entry for tenant A, queries as tenant B — expects miss
- [x] Threshold boundary test uses known embedding vectors with calculated cosine similarity
- [x] All tests pass: `pytest tests/integration/test_cache_integration.py`

---

## Dependencies Map

```
Phase C2:
  CACHE-004 (version counter)
    └── CACHE-003 (search result cache) ← CACHE-002 (embedding cache)
          └── CACHE-005 (per-index TTL config)
  CACHE-001 (intent cache)
  CACHE-006 (warming job) ← CACHE-001, CACHE-002

Phase C3:
  CACHE-007 (pgvector migration)
    └── CACHE-008 (SemanticCacheService)
          └── CACHE-010 (chat router integration)
                └── CACHE-012 (SSE event) → frontend FE-014 (COMPLETE)
                └── CACHE-015 (metrics collection)
  CACHE-009 (response model split) → CACHE-010
  CACHE-011 (invalidation on doc update) ← CACHE-004, CACHE-008
  CACHE-013 (config API) ← CACHE-008
  CACHE-014 (cleanup job) ← CACHE-007, CACHE-011
  CACHE-018 (user transparency) ← CACHE-012, CACHE-013

Phase C4:
  CACHE-016 (analytics API) ← CACHE-015
    └── CACHE-017 (frontend wiring)
  CACHE-019 (integration tests) ← CACHE-007, CACHE-008, CACHE-010
```

---

## Notes

- `CacheStateChip.tsx` and cache analytics panel (FE-014, FE-048) already built — C4 is wiring, not net-new frontend work
- pgvector HNSW index with `m=16, ef_construction=64` tuned for 1536-dimensional vectors (text-embedding-3-small); revisit if model changes
- `cost_saved_usd` on cache hits requires P2LLM-011 (cost model) to be complete first; CACHE-015 should be sequenced after P2LLM-011
- Top-cached-queries endpoint uses SHA256 prefix to protect user privacy — never store raw query text in analytics tables
- DEF-013 (pgvector integration tests) unblocked by CACHE-007 — coordinate with 07-deferred-phase1.md
