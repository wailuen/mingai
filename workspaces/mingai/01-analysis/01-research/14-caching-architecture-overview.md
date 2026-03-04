# Caching Architecture Overview: End-to-End Pipeline Analysis

**Date**: March 4, 2026
**Scope**: Complete caching strategy from user query receipt to response delivery
**Status**: Research Phase

---

## 1. Executive Summary

The mingai RAG pipeline has **10 distinct stages** where caching can be applied. Current Redis usage covers only 2 of 10 stages (JWT validation, rate limiting), leaving significant latency and cost reduction on the table.

**Impact Potential**:

- Latency reduction: 40-70% for cache-hit queries (from ~2.5s to <0.5s)
- LLM cost reduction: 25-45% by eliminating redundant embedding and synthesis calls
- Cosmos DB read reduction: 80-90% for user context, glossary, and index metadata
- Overall cost reduction: 30-50% for high-volume tenants

**Priority Ranking** (impact × feasibility):

| Rank | Cache Target                | Impact   | Complexity | Est. Savings                  |
| ---- | --------------------------- | -------- | ---------- | ----------------------------- |
| 1    | LLM Semantic Response Cache | CRITICAL | HIGH       | 25-40% LLM cost               |
| 2    | Query Embedding Cache       | HIGH     | LOW        | 100% embed cost on cache hit  |
| 3    | Search Result Cache         | HIGH     | MEDIUM     | 50-80% search latency         |
| 4    | User Context / RBAC Cache   | MEDIUM   | LOW        | 80% Cosmos reads              |
| 5    | Intent Detection Cache      | MEDIUM   | LOW        | <1s intent latency eliminated |
| 6    | Glossary Cache              | MEDIUM   | VERY LOW   | DB reads eliminated           |
| 7    | Conversation History Cache  | MEDIUM   | LOW        | Cosmos reads on each turn     |
| 8    | Index Metadata Cache        | LOW      | VERY LOW   | DB reads eliminated           |
| 9    | A2A Agent Response Cache    | VARIABLE | MEDIUM     | Depends on data freshness     |
| 10   | Frontend / TanStack Query   | LOW      | VERY LOW   | Already partially implemented |

---

## 2. Full Pipeline Cache Map

```
Browser
  │
  ├─ [CACHE-10] TanStack Query (stale-while-revalidate)
  │   └─ Conversation list, index list, user profile
  │
  ▼
API Gateway (FastAPI)
  │
  ├─ [CACHE-1] JWT Validation Cache ✅ IMPLEMENTED
  │   └─ Redis: mingai:{tenant_id}:auth:jwt:{token_hash}
  │   └─ TTL: JWT expiry (8h)
  │
  ├─ [CACHE-2] Rate Limit Counters ✅ IMPLEMENTED
  │   └─ Redis: sliding window + fixed window
  │
  ├─ [CACHE-3] RBAC / Permission Cache ⚠️ PARTIAL
  │   └─ Redis: mingai:{tenant_id}:rbac:{user_id}
  │   └─ TTL: 5-15 minutes, invalidated on role change
  │
  ▼
Chat Router
  │
  ├─ [CACHE-4] User Context Cache ❌ MISSING
  │   └─ Redis: mingai:{tenant_id}:user:{user_id}:profile
  │   └─ TTL: 10 minutes
  │   └─ Invalidated: on profile update webhook
  │
  ├─ [CACHE-5] Conversation History Cache ❌ MISSING
  │   └─ Redis: mingai:{tenant_id}:conv:{conv_id}:history
  │   └─ TTL: 30 minutes (warm during active session)
  │   └─ Warm on conversation open, evict on close
  │
  ▼
Intent Detection (GPT-5 Mini)
  │
  ├─ [CACHE-6] Intent Result Cache ❌ MISSING
  │   └─ Redis: mingai:{tenant_id}:intent:{query_hash}
  │   └─ TTL: 24 hours (exact match only)
  │   └─ Win: Eliminates GPT-5 Mini call entirely
  │
  ▼
Embedding Generation (text-embedding-3-large)
  │
  ├─ [CACHE-7] Query Embedding Cache ⚠️ PARTIAL (mentioned in code)
  │   └─ Redis: mingai:{tenant_id}:emb:{query_hash}
  │   └─ TTL: 7 days (deterministic — same query = same embedding)
  │   └─ Win: 100% cost + latency saving on cache hit
  │
  ▼
Vector Search (Azure AI Search)
  │
  ├─ [CACHE-8] Search Result Cache ❌ MISSING
  │   └─ Redis: mingai:{tenant_id}:search:{index_id}:{emb_hash}
  │   └─ TTL: 15min-4h (configurable per index, by data freshness)
  │   └─ Invalidated: when documents are added/modified to index
  │
  ├─ [CACHE-9] Index Metadata Cache ❌ MISSING
  │   └─ Redis: mingai:{tenant_id}:idx:{index_id}:meta
  │   └─ TTL: 10 minutes
  │
  ▼
Context Building
  │
  ├─ Glossary Cache (part of CACHE-4 strategy)
  │   └─ Redis: mingai:{tenant_id}:glossary:{term_hash}
  │   └─ TTL: 1 hour (terms rarely change)
  │
  ▼
LLM Synthesis (GPT-5.2-chat)
  │
  ├─ [CACHE-A] Exact Response Cache ❌ MISSING
  │   └─ Redis: mingai:{tenant_id}:llm:exact:{prompt_hash}
  │   └─ TTL: 1-24h (configurable per tenant)
  │
  ├─ [CACHE-B] Semantic Response Cache ❌ MISSING (KEY DIFFERENTIATOR)
  │   └─ pgvector or Redis: semantic similarity search
  │   └─ Threshold: cosine similarity > 0.95
  │   └─ TTL: 4-24h (policy-driven)
  │   └─ Win: Eliminates LLM call for "same question, different phrasing"
  │
  ▼
A2A Agent Calls (External Data)
  │
  ├─ [CACHE-C] A2A Agent Response Cache ❌ MISSING
  │   └─ Redis: mingai:{tenant_id}:a2a:{agent_id}:{sha256(task_description)}
  │   └─ TTL: Per-agent policy (real-time: 15s, semi-static: 4h)
  │
  ▼
Response (SSE Stream)
```

---

## 3. Cache Layer Inventory

### Layer 1: Client-Side Caching (Browser)

**Current**: TanStack Query (React Query) with default stale-while-revalidate.

**Assessment**: Already implemented but not optimally configured.

**Gaps**:

- Conversation list: should have 30s stale time, 5min cache time
- Index list: should have 5min stale time (rarely changes)
- User profile: should persist across sessions in localStorage
- No offline support for read-only content

**Actions Required**: Configure TanStack Query staleTime and cacheTime per query type. Add `localStorage` persistence for user preferences.

---

### Layer 2: CDN / Edge Caching

**Current**: None for API responses (they are dynamic, authenticated).

**Assessment**: Limited applicability for authenticated API responses. However:

- Static frontend assets (Next.js): CDN caching via Vercel/CloudFront — already standard
- Public knowledge base previews: could be edge-cached if ever exposed publicly
- API responses: NOT cache-able at CDN layer due to authentication + user-specific content

**Actions Required**: Ensure Next.js static assets use CDN. No API edge caching feasible without architecture change.

---

### Layer 3: API Gateway (FastAPI) — In-Process Memory Cache

**Current**: No in-process cache; all state goes to Redis.

**Assessment**: For single-instance deployments, an in-memory LRU cache (via `cachetools` or `functools.lru_cache`) for hot paths reduces Redis round-trips.

**Candidates**:

- System role definitions (platform-level, never change between deployments)
- Index schema metadata (per-tenant, 10 min TTL)
- Tenant configuration (per-tenant, 5 min TTL)

**Caution**: In multi-instance deployments, in-process cache creates inconsistency risk. Only appropriate for truly immutable or near-immutable data.

**Actions Required**: Add `@lru_cache(maxsize=1000)` for system role definitions. Use Redis for tenant-specific data.

---

### Layer 4: Redis Distributed Cache (Primary Cache Layer)

**Current State**: Redis is deployed and used for:

- JWT session caching
- Rate limiting counters
- Key prefix: `aihub2:` (migrating to `mingai:` in Phase 1)

**Required Expansion**: 8 additional cache types (see full pipeline map above).

**Architecture Considerations**:

- Multi-tenant key namespace: `mingai:{tenant_id}:{type}:{key}`
- TTL policy: per cache type, configurable per tenant
- Eviction policy: `allkeys-lru` (recommended for cache workloads)
- Memory sizing: 2-4GB for typical deployment (see sizing calculations in Section 5)
- Redis Cluster vs Sentinel: Sentinel for single-region HA; Cluster for multi-region

---

### Layer 5: Semantic Cache (Vector Similarity)

**Current**: Does not exist.

**Assessment**: THE highest-impact caching opportunity. Enterprise users frequently ask semantically equivalent questions with different phrasing:

- "What is the PTO policy?" ≈ "How many vacation days do employees get?"
- "Q3 revenue?" ≈ "What was our revenue in the third quarter?"
- "Who is the HR contact?" ≈ "HR department email?"

**Implementation**: See file `15-semantic-caching-analysis.md` for full design.

**Impact**: Eliminate 25-40% of LLM calls; 40-70% latency reduction for cache hits.

---

## 4. Caching Decision Matrix

For each pipeline stage, the key decisions are: **What to cache**, **Cache key design**, **TTL policy**, and **Invalidation strategy**.

### 4.1 JWT Validation Cache (CACHE-1) ✅

| Attribute        | Value                                                             |
| ---------------- | ----------------------------------------------------------------- |
| **What**         | JWT decode result + permission set                                |
| **Cache Key**    | `mingai:{tenant_id}:auth:jwt:{sha256(token)}`                     |
| **TTL**          | `min(jwt_exp - now, 300s)` — expires with token, max 5min         |
| **Invalidation** | Token blacklist on logout; user role change event                 |
| **Redis Type**   | STRING (serialized user object)                                   |
| **Risk**         | Low — token is cryptographically verified before cache population |

### 4.2 User Context Cache (CACHE-4) ❌

| Attribute        | Value                                                      |
| ---------------- | ---------------------------------------------------------- |
| **What**         | User profile + resolved permissions + accessible indexes   |
| **Cache Key**    | `mingai:{tenant_id}:ctx:{user_id}`                         |
| **TTL**          | 600s (10 minutes)                                          |
| **Invalidation** | Role change event → pub/sub invalidation via Redis         |
| **Redis Type**   | HASH (field-level updates without full rewrite)            |
| **Risk**         | Medium — stale permissions for 10min max; mitigated by TTL |
| **Impact**       | Eliminates 3-5 Cosmos DB reads per chat turn               |

### 4.3 Conversation History Cache (CACHE-5) ❌

| Attribute        | Value                                        |
| ---------------- | -------------------------------------------- |
| **What**         | Last 10 messages of active conversation      |
| **Cache Key**    | `mingai:{tenant_id}:conv:{conv_id}:history`  |
| **TTL**          | 1800s (30 minutes) — refresh on each message |
| **Invalidation** | Write-through: update cache on new message   |
| **Redis Type**   | LIST (LPUSH new messages, LTRIM to 10 items) |
| **Risk**         | Low — always written with new messages       |
| **Impact**       | Eliminates 1 Cosmos DB query per chat turn   |

### 4.4 Intent Detection Cache (CACHE-6) ❌

| Attribute        | Value                                                                          |
| ---------------- | ------------------------------------------------------------------------------ |
| **What**         | Intent classification result + selected indexes                                |
| **Cache Key**    | `mingai:{tenant_id}:intent:{sha256(normalized_query)}`                         |
| **TTL**          | 86400s (24 hours) — intent of a query doesn't change                           |
| **Invalidation** | None needed (query hash is deterministic)                                      |
| **Redis Type**   | STRING (JSON-serialized intent object)                                         |
| **Risk**         | Very Low — same query always has same intent                                   |
| **Impact**       | Eliminates GPT-5 Mini LLM call (saves ~$0.0002, more importantly saves <500ms) |
| **Note**         | Normalize query before hashing: lowercase, strip extra whitespace              |

### 4.5 Query Embedding Cache (CACHE-7) ⚠️

| Attribute        | Value                                                                          |
| ---------------- | ------------------------------------------------------------------------------ |
| **What**         | 3072-dimension embedding vector for query text                                 |
| **Cache Key**    | `mingai:{tenant_id}:emb:{model_id}:{sha256(query)}`                            |
| **TTL**          | 604800s (7 days) — embeddings are deterministic                                |
| **Invalidation** | On model upgrade (flush by model_id prefix)                                    |
| **Redis Type**   | STRING (base64-encoded float32 array or msgpack)                               |
| **Risk**         | Very Low — deterministic function                                              |
| **Impact**       | Eliminates embedding API call (~$0.00013/1K tokens), reduces latency 100-300ms |
| **Note**         | Include model_id in cache key for version safety                               |

### 4.6 Search Result Cache (CACHE-8) ❌

| Attribute        | Value                                                                  |
| ---------------- | ---------------------------------------------------------------------- |
| **What**         | Top-K search results for (query embedding, index) pair                 |
| **Cache Key**    | `mingai:{tenant_id}:search:{index_id}:{emb_hash_prefix_16}`            |
| **TTL**          | Configurable per index: 900s-14400s (15min-4h)                         |
| **Invalidation** | Document update in index → invalidate all search caches for that index |
| **Redis Type**   | STRING (JSON-serialized result list)                                   |
| **Risk**         | Medium — stale results if documents updated during TTL window          |
| **Impact**       | Eliminates Azure Search call, reduces latency 200-800ms                |
| **Config**       | Freshness vs. performance tradeoff exposed to tenant admin             |

### 4.7 Glossary Cache ❌

| Attribute        | Value                                                               |
| ---------------- | ------------------------------------------------------------------- |
| **What**         | Glossary term definitions for extracted query terms                 |
| **Cache Key**    | `mingai:{tenant_id}:glossary:{scope}:{term_normalized}`             |
| **TTL**          | 3600s (1 hour)                                                      |
| **Invalidation** | Glossary update event → flush prefix `mingai:{tenant_id}:glossary:` |
| **Redis Type**   | HASH                                                                |
| **Risk**         | Low — glossary terms change rarely                                  |
| **Impact**       | Eliminates 1-5 Cosmos DB reads per query                            |

### 4.8 Index Metadata Cache (CACHE-9) ❌

| Attribute        | Value                                                            |
| ---------------- | ---------------------------------------------------------------- |
| **What**         | Index configuration (search_config, credentials, access control) |
| **Cache Key**    | `mingai:{tenant_id}:idx:{index_id}:meta`                         |
| **TTL**          | 600s (10 minutes)                                                |
| **Invalidation** | Index update event → direct key invalidation                     |
| **Redis Type**   | STRING (JSON-serialized index object)                            |
| **Risk**         | Low — index config changes rarely                                |
| **Impact**       | Eliminates Cosmos DB read on every search call                   |

### 4.9 LLM Response Cache — Exact (CACHE-A) ❌

| Attribute        | Value                                                          |
| ---------------- | -------------------------------------------------------------- |
| **What**         | Full LLM response for identical prompts                        |
| **Cache Key**    | `mingai:{tenant_id}:llm:exact:{sha256(full_prompt)}`           |
| **TTL**          | Configurable: 3600s-86400s (1h-24h)                            |
| **Invalidation** | Document update → flush by affected index namespace            |
| **Redis Type**   | STRING (full response JSON)                                    |
| **Risk**         | Medium — exact match rate low (~5-10%), but zero-risk on match |
| **Impact**       | When hit: eliminates most expensive call in pipeline           |

### 4.10 LLM Response Cache — Semantic (CACHE-B) ❌

See `15-semantic-caching-analysis.md` for complete design.

### 4.11 A2A Agent Response Cache (CACHE-C) ❌

| Attribute        | Value                                                                |
| ---------------- | -------------------------------------------------------------------- |
| **What**         | A2A Artifact (agent synthesized response to a natural language task) |
| **Cache Key**    | `mingai:{tenant_id}:a2a:{agent_id}:{sha256(task_description)}`       |
| **TTL**          | Per-agent policy (see table below)                                   |
| **Invalidation** | Time-based only (agent responses reflect point-in-time analysis)     |
| **Redis Type**   | STRING (JSON-serialized A2A Artifact)                                |

**A2A Agent Response TTL Policy**:

| A2A Agent              | Data Freshness          | Recommended TTL |
| ---------------------- | ----------------------- | --------------- |
| Bloomberg Intelligence | Real-time market prices | 15-60 seconds   |
| CapIQ Intelligence     | Company financials      | 4-12 hours      |
| Perplexity Web Search  | News and web content    | 1-4 hours       |
| Oracle Fusion          | ERP operational records | 15-60 minutes   |
| AlphaGeo               | Geospatial data         | 24 hours        |
| Teamworks              | Project status          | 5-15 minutes    |
| PitchBook Intelligence | M&A data                | 4-24 hours      |
| Azure AD Directory     | User/group membership   | 5-15 minutes    |
| iLevel Portfolio       | Investment records      | 30-60 minutes   |

---

## 5. Memory Sizing Estimates

### Per-Tenant Calculations (100 active users, 500 queries/day)

| Cache Type            | Entries          | Avg Size        | Memory |
| --------------------- | ---------------- | --------------- | ------ |
| JWT tokens            | 200 active       | 2KB             | 400KB  |
| User context          | 100 users        | 5KB             | 500KB  |
| Conversation history  | 50 active        | 10KB            | 500KB  |
| Intent cache          | 500/day, 24h TTL | 500B            | 250KB  |
| Embedding cache       | 500/day, 7d TTL  | 25KB (3072 dim) | 87MB   |
| Search results        | 500/day, 2h TTL  | 20KB            | 10MB   |
| Glossary              | 200 terms        | 1KB             | 200KB  |
| Index metadata        | 10 indexes       | 5KB             | 50KB   |
| LLM responses (exact) | 500/day, 4h TTL  | 5KB             | 2.5MB  |

**Per-tenant baseline**: ~100MB (dominated by embedding cache)
**Embedding optimization**: Compress float32 vectors → float16 (50% size reduction) = ~50MB per tenant
**At 50 tenants**: 2.5-5GB Redis memory needed

**Recommendation**: 8GB Redis instance with LRU eviction; embedding vectors stored in separate slot or compressed.

---

## 6. Cache Invalidation Architecture

### Event-Driven Invalidation

The core challenge: when source data changes, cached derivatives must be purged.

```
Event Source          Event Type              Cache Targets Invalidated
─────────────────     ─────────────────       ──────────────────────────────────
Document update       document.updated        search:{index_id}:*
                                              llm:exact:{index_id}:* (tagged)
                                              semantic cache entries (index tagged)

Role change           role.changed            ctx:{user_id}
                                              auth:jwt:{user_id}:* (all tokens)

Index update          index.updated           idx:{index_id}:meta
                                              search:{index_id}:*

Glossary update       glossary.updated        glossary:{tenant_id}:*

User profile update   user.updated            ctx:{user_id}
```

### Implementation: Redis Pub/Sub + Tag-Based Invalidation

```python
# When a document is updated in an index:
async def on_document_updated(tenant_id: str, index_id: str):
    # 1. Invalidate search result caches for this index
    pattern = f"mingai:{tenant_id}:search:{index_id}:*"
    await redis.eval(
        "local keys = redis.call('KEYS', ARGV[1]) "
        "for i=1,#keys do redis.call('DEL', keys[i]) end",
        0, pattern
    )

    # 2. Publish invalidation event for LLM response cache
    # (LLM responses tagged with index_id at write time)
    await redis.publish(
        f"mingai:invalidation:{tenant_id}",
        json.dumps({"type": "index_updated", "index_id": index_id})
    )

    # 3. Increment version counter for semantic cache
    await redis.incr(f"mingai:{tenant_id}:version:{index_id}")
```

### Invalidation Safety Contract

- **Over-invalidation is safe** (performance penalty); **under-invalidation is dangerous** (stale data)
- Default strategy: invalidate aggressively on writes, cache conservatively
- TTLs serve as the final safety net (maximum staleness = TTL)

---

## 7. Cache Warming Strategy

### What to Warm

1. **System-level**: Platform configuration, system roles — warm at startup
2. **Tenant-level**: Index metadata, common glossary terms — warm at tenant provisioning
3. **Usage-based**: Top-50 queries by tenant (from analytics) — warm daily at off-peak

### Warming Implementation

```python
async def warm_tenant_cache(tenant_id: str):
    """Run at tenant provisioning and daily at 2 AM tenant-local time"""

    # 1. Warm index metadata
    indexes = await cosmos_db.indexes.query("SELECT * FROM c WHERE c.tenant_id = @tid")
    for index in indexes:
        await cache.set(f"mingai:{tenant_id}:idx:{index.id}:meta", index, ttl=600)

    # 2. Warm glossary (top 200 terms)
    terms = await cosmos_db.glossary.query("SELECT TOP 200 * FROM c ...")
    for term in terms:
        await cache.set(f"mingai:{tenant_id}:glossary:enterprise:{term.term}", term, ttl=3600)

    # 3. Warm embeddings for top queries (from analytics)
    top_queries = await analytics.get_top_queries(tenant_id, limit=50, days=7)
    for query in top_queries:
        embedding = await azure_openai.embeddings.create(query.text)
        await cache.set(f"mingai:{tenant_id}:emb:text-embedding-3-large:{sha256(query.text)}",
                       embedding, ttl=604800)
```

---

## 8. Multi-Tenant Cache Isolation

**Critical requirement**: No tenant must ever see another tenant's cached data.

### Key Namespace Design

```
mingai:{tenant_id}:{cache_type}:{discriminator}
```

- `tenant_id` is always the second component
- Never use wildcard operations across tenant boundaries
- All cache reads MUST include tenant_id from JWT (not from user input)

### Tenant Eviction Policy

Problem: A large tenant's search result cache could evict a small tenant's entries.

**Solution**: Use Redis `maxmemory-policy allkeys-lru` with memory limits OR allocate separate Redis databases per tenant tier:

- Starter plan: Shared Redis DB, strict memory limits via Redis Streams
- Professional: Shared Redis DB, priority eviction metadata
- Enterprise: Dedicated Redis DB or Redis Cluster shard

---

## 9. Observability Requirements

Every cache operation must emit metrics:

```
cache_hit{tenant_id, cache_type, stage}
cache_miss{tenant_id, cache_type, stage}
cache_latency_ms{tenant_id, cache_type, operation}
cache_eviction{tenant_id, cache_type}
cache_memory_bytes{tenant_id}
```

**Dashboard Requirements**:

- Per-tenant cache hit rates by stage
- Cost savings from cache hits (LLM calls avoided × cost per call)
- Cache memory usage by tenant
- Invalidation event frequency

This directly feeds the **Cost Analytics** USP: tenants can see actual dollar savings from caching.

---

**Document Version**: 1.0
**Next**: See `15-semantic-caching-analysis.md` for semantic cache design
**See Also**: `16-embedding-search-cache.md`, `17-multi-tenant-cache-isolation.md`
