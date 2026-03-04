# Caching Implementation Plan: Phased Rollout

**Date**: March 4, 2026
**Depends On**: `01-analysis/01-research/14-17`, `01-analysis/06-caching-product/01-02`
**Integration With**: Phase 1 (Foundation) of Implementation Roadmap

---

## Overview

The caching implementation is structured in **4 phases** aligned with the existing 6-phase product roadmap. Each phase delivers independent value and can ship incrementally.

| Phase | Name               | Duration | Primary Deliverable                           | Dependencies                |
| ----- | ------------------ | -------- | --------------------------------------------- | --------------------------- |
| C1    | Foundation Caches  | 2 weeks  | User context, glossary, index metadata caches | Phase 1 (tenant_id in keys) |
| C2    | Pipeline Caches    | 2 weeks  | Embedding, intent, search result caches       | C1 complete                 |
| C3    | Semantic Cache     | 4 weeks  | pgvector semantic response cache              | C2 + PostgreSQL RDS         |
| C4    | Cache Analytics UI | 2 weeks  | Admin dashboard: hit rates, cost savings      | C3 + analytics pipeline     |

**Total estimated duration**: 10 weeks (can run parallel to product roadmap phases)

---

## Phase C1: Foundation Caches (Weeks 1-2)

### Goal

Eliminate all redundant database reads that occur on every chat turn. Zero LLM impact — pure infrastructure improvement.

### Deliverables

1. **Cache service abstraction layer** — `app/core/cache.py`
   - `build_cache_key(tenant_id, cache_type, *parts)` with validation
   - `CacheService` class wrapping `aioredis` with metrics instrumentation
   - `@cached(ttl, cache_type)` decorator for easy application
   - Invalidation event publisher/subscriber via Redis Pub/Sub

2. **User context cache** (CACHE-4)
   - Cache: user profile + resolved permissions + accessible index list
   - TTL: 600s
   - Invalidation: on role change event

3. **Conversation history cache** (CACHE-5)
   - Cache: last 10 messages per conversation
   - Write-through: update cache on every new message
   - TTL: 1800s, refreshed on each message

4. **Glossary cache**
   - Cache: all active glossary terms per tenant
   - TTL: 3600s
   - Invalidation: on glossary update event

5. **Index metadata cache** (CACHE-9)
   - Cache: index configuration per index_id
   - TTL: 600s
   - Invalidation: on index update event

6. **Redis key namespace migration**
   - Migrate from `aihub2:` prefix to `mingai:{tenant_id}:` per Phase 1 requirement

### Technical Specification

```python
# app/core/cache.py — Core cache service

import hashlib
import json
import re
from typing import Optional, Any
import aioredis
from app.core.config import settings
from app.core.metrics import metrics

VALID_CACHE_TYPES = frozenset({
    "auth", "ctx", "conv", "intent", "emb",
    "search", "idx", "glossary", "llm", "mcp",
    "rate", "version"
})

UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
)

class CacheService:
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    def build_key(self, tenant_id: str, cache_type: str, *parts: str) -> str:
        if not UUID_PATTERN.match(tenant_id):
            raise ValueError(f"Invalid tenant_id: {tenant_id!r}")
        if cache_type not in VALID_CACHE_TYPES:
            raise ValueError(f"Invalid cache_type: {cache_type!r}")
        for part in parts:
            if not re.match(r'^[a-zA-Z0-9\-_:\.]+$', str(part)):
                raise ValueError(f"Invalid key component: {part!r}")
        return f"mingai:{tenant_id}:{cache_type}:{':'.join(str(p) for p in parts)}"

    async def get(self, key: str) -> Optional[Any]:
        data = await self.redis.get(key)
        if data:
            metrics.increment("cache.hit", tags={"key_prefix": key.split(":")[2]})
            return json.loads(data)
        metrics.increment("cache.miss", tags={"key_prefix": key.split(":")[2]})
        return None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        await self.redis.setex(key, ttl, json.dumps(value))

    async def delete(self, key: str) -> None:
        await self.redis.delete(key)

    async def publish_invalidation(self, tenant_id: str, event: dict) -> None:
        await self.redis.publish(
            f"mingai:invalidation:{tenant_id}",
            json.dumps(event)
        )
```

### Tests Required

- Unit: key validation (invalid tenant_id, invalid cache_type, injection attempt)
- Integration: get/set/delete/invalidation with real Redis
- Security: cross-tenant key isolation (test vectors in `17-multi-tenant-cache-isolation.md`)

### Success Metrics

- Cosmos DB / PostgreSQL read count reduced by 80% per chat turn
- P99 response latency for context-building phase: <20ms (down from 80-120ms)
- Zero cross-tenant cache violations in security test suite

---

## Phase C2: Pipeline Caches (Weeks 3-4)

### Goal

Eliminate redundant LLM calls for intent detection and redundant API calls for embeddings. Introduce search result caching with configurable TTL.

### Deliverables

1. **Intent detection cache** (CACHE-6)
   - Key: `mingai:{tenant_id}:intent:{sha256(normalized_query)}`
   - TTL: 86400s (24h)
   - Query normalization: lowercase, strip whitespace, remove punctuation

2. **Query embedding cache** (CACHE-7)
   - Key: `mingai:{tenant_id}:emb:{model_id}:{sha256(query)}`
   - Storage: float16-compressed binary (50% size reduction)
   - TTL: 604800s (7 days)
   - Model upgrade path: include model_id in key

3. **Search result cache** (CACHE-8)
   - Key: `mingai:{tenant_id}:search:{index_id}:{emb_hash_prefix_16}:{params_hash_8}`
   - TTL: per-index configuration (default 3600s)
   - Invalidation: index version counter comparison
   - Index version counter: `INCR mingai:{tenant_id}:version:{index_id}` on document update

4. **Index cache TTL configuration** — tenant admin UI addition
   - Admin can set per-index cache TTL: 0 (disabled), 15min, 30min, 1h, 4h, 8h, 24h
   - Default: 1 hour for all indexes
   - UI: Index management page → cache settings section

5. **Cache warming background job**
   - Scheduled daily at 3 AM (tenant-local timezone)
   - Pre-generates embeddings for top-100 queries from past 30 days
   - Pre-warms intent cache for top queries

### Technical Specification

```python
# app/services/embedding_service.py — Embedding with cache

import hashlib
import numpy as np
from app.core.cache import CacheService

async def get_query_embedding(
    tenant_id: str,
    query: str,
    cache: CacheService,
    openai_client,
    model_id: str = "text-embedding-3-large"
) -> list[float]:
    """Get embedding from cache or generate it."""
    query_hash = hashlib.sha256(query.lower().strip().encode()).hexdigest()[:32]
    key = cache.build_key(tenant_id, "emb", model_id, query_hash)

    cached = await cache.redis.get(key)
    if cached:
        arr = np.frombuffer(cached, dtype=np.float16).astype(np.float32)
        return arr.tolist()

    response = await openai_client.embeddings.create(
        input=query, model=model_id, dimensions=3072
    )
    embedding = response.data[0].embedding

    # Store compressed (float32 → float16)
    compressed = np.array(embedding, dtype=np.float32).astype(np.float16).tobytes()
    await cache.redis.setex(key, 604800, compressed)

    return embedding
```

### Success Metrics

- Intent detection: 40-60% cache hit rate after week 1 (common queries)
- Embedding generation API calls: 80-90% reduction for active tenants
- Search result cache hit rate: 50-70% within configurable TTL window
- P50 pipeline latency (excluding LLM synthesis): <100ms (down from 600-1200ms)

---

## Phase C3: Semantic Response Cache (Weeks 5-8)

### Goal

Eliminate redundant LLM synthesis calls for semantically equivalent queries. Largest single impact on cost and latency.

### Deliverables

1. **pgvector schema setup**
   - `semantic_cache` table with HNSW index (see schema in `15-semantic-caching-analysis.md`)
   - Partition by `tenant_id`
   - Alembic migration (part of Phase 1 database migrations)

2. **Semantic cache service** — `app/services/semantic_cache.py`
   - `lookup(tenant_id, query_embedding, threshold)` → cached response or None
   - `store(tenant_id, query, embedding, response, metadata)` — async, non-blocking
   - Version tag management for invalidation
   - Configurable threshold per tenant

3. **Response model split** (two-tier)
   - `CacheableResponse`: generic content (sources, raw answer, confidence)
   - `PersonalizedResponse`: user-specific wrapper (greeting, follow-ups)
   - Cache stores only `CacheableResponse`

4. **Semantic cache integration in chat router**
   - Check semantic cache BEFORE intent detection (with query embedding)
   - On hit: adapt response + stream immediately (no LLM call)
   - On miss: run full pipeline, store result in semantic cache async

5. **Cache invalidation on document update**
   - Version counter increment on document sync
   - Semantic cache lookup validates version tags before returning

6. **User-visible cache state in SSE stream**
   - New SSE event: `cache_state` with hit/miss, similarity score, response age
   - UI: visual indicator of response source

7. **Semantic cache configuration in admin UI**
   - Per-tenant threshold: 0.85-0.99 slider
   - Per-tenant TTL: 1h, 4h, 8h, 24h, disabled
   - Real-time hit rate display per index

8. **Cleanup job** — runs hourly
   - Delete expired entries (expires_at < NOW())
   - Delete stale entries (version tag outdated)

### Integration Code Sketch

```python
# app/modules/chat/service.py — Modified to use semantic cache

async def process_chat(tenant_id, user_id, conv_id, query, index_ids):
    # Step 0: Get query embedding (cached)
    embedding = await embedding_service.get_query_embedding(tenant_id, query, cache, openai)

    # Step 0b: Semantic cache check
    tenant_config = await get_tenant_cache_config(tenant_id)
    if not is_personal_query(query) and not needs_real_time(query):
        hit = await semantic_cache.lookup(
            tenant_id=tenant_id,
            query_embedding=embedding,
            threshold=tenant_config.semantic_threshold,
            index_ids=index_ids
        )
        if hit:
            user_ctx = await get_user_context(tenant_id, user_id)
            return adapt_and_stream(hit, user_ctx, cache_metadata={
                "similarity": hit.similarity,
                "age_seconds": hit.age_seconds,
                "source": "semantic_cache"
            })

    # Full pipeline if cache miss
    intent = await intent_service.detect(tenant_id, query, cache, openai)
    sources = await search_service.parallel_search(tenant_id, embedding, intent.selected_indexes, cache)
    context = await context_builder.build(tenant_id, user_id, conv_id, cache)
    response = await llm_service.synthesize(query, sources, context, stream=True)

    # Store in semantic cache (async)
    asyncio.create_task(semantic_cache.store(
        tenant_id=tenant_id,
        query_text=query,
        query_embedding=embedding,
        response=response.cacheable_portion,
        indexes_used=intent.selected_indexes,
        intent_category=intent.intent,
        version_tags=await get_current_versions(tenant_id, intent.selected_indexes),
        ttl_seconds=tenant_config.semantic_ttl
    ))

    return response
```

### Success Metrics

- Semantic cache hit rate: 25-35% at steady state (month 1)
- LLM synthesis calls eliminated: 25-35%
- Average response time for cache hit queries: <200ms (vs 2500ms baseline)
- Cost per query (blended): 25-35% reduction
- Zero incorrect cache hits (verified via user feedback + manual spot-check)

---

## Phase C4: Cache Analytics Dashboard (Weeks 9-10)

### Goal

Make cache performance visible to tenant admins. Close the loop between cache optimization and cost management (USP #4: Comprehensive Cost Analytics).

### Deliverables

1. **Cache metrics collection** — extend existing analytics pipeline
   - Event: `cache_hit | cache_miss | cache_eviction | cache_invalidation`
   - Attributes: tenant_id, cache_type, stage, latency_ms, cost_saved
   - Storage: analytics events table (existing)

2. **Cache analytics API endpoints**

   ```
   GET /api/v1/admin/analytics/cache/summary
       → Total hit rate, cost saved, queries served from cache
   GET /api/v1/admin/analytics/cache/by-index
       → Per-index hit rate, avg TTL efficiency, invalidation frequency
   GET /api/v1/admin/analytics/cache/top-cached-queries
       → Most frequently cached queries (anonymized content)
   GET /api/v1/admin/analytics/cache/cost-savings
       → Dollar savings breakdown: LLM calls avoided × cost/call
   ```

3. **Admin dashboard UI** — Cache Performance panel
   - Overall cache hit rate (gauge: current week)
   - Cost saved this month ($X in LLM calls eliminated)
   - Hit rate by pipeline stage (embedding, search, semantic)
   - Top cached query categories (pie chart)
   - Cache memory usage by type (bar chart)
   - Configurable settings link → cache configuration page

4. **Per-user transparency** — Chat response metadata
   - Existing metadata event in SSE: extend with `cache_state`
   - UI chip on response: "⚡ Fast response" (cache hit) vs "🟢 Live response" (LLM)
   - Hover tooltip: "Response from cache (3.2 hours ago) · [Refresh]"

5. **Monthly cost report** — PDF/email
   - Include cache savings breakdown
   - "Your AI platform saved $X this month through intelligent caching"
   - Trend line: cost per query over time (should decrease as cache warms)

### Success Metrics

- Tenant admins actively review cache dashboard weekly
- Cost savings visible and verifiable: within 5% of actual cost reduction
- User satisfaction: cache transparency increases trust (measured via feedback)

---

## Risk Register

| Risk                                                   | Probability | Impact   | Mitigation                                                |
| ------------------------------------------------------ | ----------- | -------- | --------------------------------------------------------- |
| pgvector extension unavailable on RDS                  | LOW         | HIGH     | Confirm with AWS team pre-Phase C3; fallback to Redis VSS |
| Semantic cache false positives (wrong answers served)  | LOW         | HIGH     | 0.95 threshold + feedback-driven invalidation             |
| Redis memory pressure at scale                         | MEDIUM      | MEDIUM   | Memory quotas per tenant; float16 compression             |
| Cache warming job interferes with peak traffic         | LOW         | LOW      | Schedule at off-peak hours; rate-limit warming            |
| Multi-tenant key isolation failure                     | VERY LOW    | CRITICAL | Security test suite in Phase C1; pre-merge required       |
| Version tag drift (stale responses after index update) | LOW         | HIGH     | Automated version increment on every doc sync             |

---

## Dependencies on Other Phases

| Phase C | Depends On                    | Why                                                         |
| ------- | ----------------------------- | ----------------------------------------------------------- |
| C1      | Phase 1 (tenant_id in JWT)    | Cannot build tenant-namespaced keys without tenant_id       |
| C2      | Phase C1                      | Cache service abstraction must exist                        |
| C3      | Phase C2 + PostgreSQL RDS     | Semantic cache needs embedding cache; needs pgvector on RDS |
| C4      | Phase C3 + Analytics pipeline | Dashboard needs cache metrics data                          |

---

**Document Version**: 1.0
**Estimated Engineering Effort**: ~30 person-days (6 weeks at 5 days/week, 1 engineer)
**Risk Level**: MEDIUM (C1-C2 low risk; C3 semantic cache requires careful testing)
