# Semantic Caching Analysis: LLM Response Reuse at Scale

**Date**: March 4, 2026
**Focus**: Eliminating redundant LLM calls via semantic similarity matching
**Status**: Research Phase

---

## 1. The Core Problem

### Why Exact-Match Caching is Insufficient

Enterprise RAG systems face a fundamental challenge: identical meaning expressed in different words.

| User A (9 AM)                     | User B (11 AM)                        | Semantically Identical?                |
| --------------------------------- | ------------------------------------- | -------------------------------------- |
| "What's our PTO policy?"          | "How many vacation days do I get?"    | YES (0.96 similarity)                  |
| "Q3 revenue results"              | "Third quarter financial performance" | YES (0.94 similarity)                  |
| "Who do I contact for IT issues?" | "IT helpdesk contact information"     | YES (0.97 similarity)                  |
| "How to expense a flight?"        | "Travel reimbursement process"        | YES (0.91 similarity)                  |
| "Azure subscription cost"         | "AWS pricing for our account"         | NO (0.63 similarity — different cloud) |

In a typical enterprise deployment:

- **20-35% of queries are semantic duplicates** within a 24-hour window
- **40-60% of queries are semantic duplicates** within a 7-day window
- Policy and FAQ queries (highest volume) have the highest semantic repetition rates

At $0.010-0.016 per LLM query:

- 1,000 queries/day/tenant × 30% cache hit rate = 300 LLM calls eliminated
- 300 × $0.013 = **$3.90/day/tenant in savings**
- At 50 tenants: **$195/day = $71,175/year** in LLM cost elimination

---

## 2. Semantic Cache Architecture

### Design Overview

```
User Query (text)
      │
      ▼
Generate Query Embedding
(text-embedding-3-large, 3072 dims)
      │
      ▼
Search Semantic Cache Index
(pgvector / Redis with HNSW index)
      │
      ├── Similarity >= 0.95 ──────────────► Return Cached Response
      │                                       (+ cache_hit metadata, adapted)
      │
      └── Similarity < 0.95 ──────────────► Proceed with RAG Pipeline
                                             │
                                             ▼
                                         Store (embedding, response)
                                         in Semantic Cache
```

### Key Design Decisions

| Decision                 | Options                               | Recommended                       | Rationale                                                 |
| ------------------------ | ------------------------------------- | --------------------------------- | --------------------------------------------------------- |
| **Similarity Storage**   | pgvector, Redis VSS, Qdrant, Weaviate | pgvector (on same PostgreSQL RDS) | Reuses existing infra, full SQL control, no extra service |
| **Similarity Metric**    | Cosine, Euclidean, Dot Product        | Cosine similarity                 | Normalized for text embeddings; model-independent scale   |
| **Similarity Threshold** | 0.85, 0.90, 0.95, 0.98                | 0.95 (configurable per tenant)    | 0.95 balances precision vs recall; tunable                |
| **Index Algorithm**      | HNSW, IVFFlat, Exact                  | HNSW (pgvector)                   | Sub-linear search time; suitable for millions of entries  |
| **Cache Scope**          | Global, Per-tenant, Per-user          | Per-tenant                        | No cross-tenant data; user context embedded in response   |
| **TTL Management**       | Time-based, Version-based             | Both                              | Time TTL for data freshness; version for document updates |

---

## 3. Similarity Threshold Analysis

### Threshold Trade-offs

| Threshold | Precision     | Recall         | Risk                            | Behavior                                       |
| --------- | ------------- | -------------- | ------------------------------- | ---------------------------------------------- |
| 0.85      | MEDIUM        | HIGH           | Medium — may serve wrong answer | Catches more queries, but more false positives |
| 0.90      | HIGH          | MEDIUM         | Low-Medium                      | Good balance for general queries               |
| **0.95**  | **VERY HIGH** | **MEDIUM-LOW** | **Very Low**                    | **Recommended default**                        |
| 0.98      | NEAR-PERFECT  | LOW            | Near-Zero                       | Over-restrictive; few hits                     |

**Why 0.95 is the sweet spot**:

- At 0.95, queries are semantically equivalent in enterprise contexts (same intent, same expected answer)
- Accounts for grammatical paraphrasing, synonym use, word order variation
- Does NOT conflate queries that differ on key details ("Q3 revenue" vs "Q4 revenue" — similarity ~0.82)

### Context-Adjusted Thresholds

Not all query types should use the same threshold:

| Query Category          | Recommended Threshold     | Rationale                                               |
| ----------------------- | ------------------------- | ------------------------------------------------------- |
| Policy/FAQ queries      | 0.93                      | High paraphrasing; answers rarely need personalization  |
| Factual lookups         | 0.95                      | Moderate precision needed                               |
| Analytical queries      | 0.97                      | Financial/analytical questions differ on subtle details |
| Personal queries ("my") | Do NOT cache semantically | User-specific; always unique                            |
| Real-time data queries  | Do NOT cache semantically | Freshness is critical                                   |
| MCP-backed queries      | Separate TTL policy       | Freshness from MCP source governs                       |

---

## 4. Cache Key and Storage Design

### Database Schema (pgvector)

```sql
-- Semantic cache table (per-tenant, partitioned by tenant_id)
CREATE TABLE semantic_cache (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id       UUID NOT NULL,
    query_embedding VECTOR(3072) NOT NULL,   -- text-embedding-3-large
    query_text      TEXT NOT NULL,           -- original query (for audit/debug)
    response_json   JSONB NOT NULL,          -- full response object
    indexes_used    TEXT[] NOT NULL,         -- which indexes produced this response
    intent_category TEXT,                    -- from intent detection
    version_tags    JSONB,                   -- {index_id: version_counter} for invalidation
    hit_count       INTEGER DEFAULT 0,       -- tracks popularity
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,    -- TTL
    CONSTRAINT valid_ttl CHECK (expires_at > created_at)
) PARTITION BY LIST (tenant_id);

-- HNSW index for fast approximate nearest neighbor search
CREATE INDEX semantic_cache_embedding_idx
    ON semantic_cache
    USING hnsw (query_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Index for tenant + expiry filtering
CREATE INDEX semantic_cache_tenant_expires_idx
    ON semantic_cache (tenant_id, expires_at);
```

### Search Query

```python
async def semantic_cache_lookup(
    tenant_id: str,
    query_embedding: list[float],
    threshold: float = 0.95,
    intent_category: str = None
) -> dict | None:
    """
    Find cached response with cosine similarity >= threshold.
    Returns None on cache miss.
    """
    # Filter conditions
    filters = ["tenant_id = $1", "expires_at > NOW()"]
    params = [tenant_id, query_embedding, threshold]

    # Optional: filter by intent category for higher precision
    if intent_category:
        filters.append("intent_category = $4")
        params.append(intent_category)

    # HNSW approximate nearest neighbor query
    result = await db.fetchrow(f"""
        SELECT
            response_json,
            query_text,
            hit_count,
            1 - (query_embedding <=> $2::vector) AS similarity
        FROM semantic_cache
        WHERE {' AND '.join(filters)}
            AND 1 - (query_embedding <=> $2::vector) >= $3
        ORDER BY query_embedding <=> $2::vector ASC
        LIMIT 1
    """, *params)

    if result:
        # Update hit count asynchronously (fire and forget)
        asyncio.create_task(
            db.execute(
                "UPDATE semantic_cache SET hit_count = hit_count + 1 WHERE id = $1",
                result["id"]
            )
        )
        return {
            "response": result["response_json"],
            "similarity": result["similarity"],
            "cache_hit": True,
            "original_query": result["query_text"]
        }

    return None
```

### Cache Write

```python
async def semantic_cache_store(
    tenant_id: str,
    query_text: str,
    query_embedding: list[float],
    response: dict,
    indexes_used: list[str],
    intent_category: str,
    version_tags: dict,
    ttl_seconds: int = 86400
) -> None:
    """Store a response in the semantic cache."""

    # Don't cache responses that are user-specific or real-time
    if response.get("requires_personalization") or response.get("real_time_data"):
        return

    # Don't cache if confidence is too low
    if response.get("confidence", {}).get("overall", 0) < 0.7:
        return

    await db.execute("""
        INSERT INTO semantic_cache
            (tenant_id, query_embedding, query_text, response_json,
             indexes_used, intent_category, version_tags, expires_at)
        VALUES
            ($1, $2::vector, $3, $4, $5, $6, $7, NOW() + INTERVAL '1 second' * $8)
        ON CONFLICT DO NOTHING
    """,
        tenant_id, query_embedding, query_text, json.dumps(response),
        indexes_used, intent_category, json.dumps(version_tags), ttl_seconds
    )
```

---

## 5. Response Adaptation for Semantic Cache Hits

### The Personalization Problem

When User B asks "How many vacation days do I get?", the cached response for User A's "PTO policy?" may say "As an analyst in Finance, you have 20 days...". This personalization must be stripped or adapted.

**Solution: Two-tier response model**

```python
@dataclass
class CacheableResponse:
    """Components stored in semantic cache — GENERIC, non-personalized"""
    source_chunks: list[dict]    # Retrieved documents
    raw_answer: str              # Policy content, factual answer
    confidence: dict             # Confidence breakdown
    citations: list[str]         # Source URLs

@dataclass
class PersonalizedResponse:
    """Final response including user context — NOT cached"""
    cacheable: CacheableResponse
    user_greeting: str           # "As an analyst in your team..."
    follow_up_questions: list[str]  # Tailored to user role
    adaptation_note: str         # "Based on similar question..."
```

On semantic cache hit:

1. Retrieve `CacheableResponse` from cache
2. Run lightweight personalization layer (no LLM call needed — rule-based adaptation)
3. Add adaptation note: "Based on a similar question..."
4. Return adapted response with cache hit metadata

**User transparency**: Always surface to user when a cached response is served:

```
🔵 Cache-assisted response (saved 2.3s)
   Similar query answered 4 hours ago. [View original query]
```

---

## 6. Cache Invalidation for Semantic Responses

### Version Tag System

Each semantic cache entry stores which index versions it was generated from:

```json
{
  "version_tags": {
    "hr-policies": 42, // version counter for HR index
    "public-kb": 17 // version counter for public knowledge base
  }
}
```

When a document is updated in an index, the version counter is incremented. On the next semantic cache lookup:

1. Check `version_tags[index_id]` against current version counter
2. If stale → cache miss, regenerate response, store with new version tags

```python
async def is_cache_valid(entry: dict, current_versions: dict) -> bool:
    """Check if cached entry is still valid given current index versions."""
    stored_versions = entry["version_tags"]
    for index_id, stored_version in stored_versions.items():
        current = current_versions.get(index_id, 0)
        if current > stored_version:
            return False  # Index was updated; cache entry is stale
    return True
```

This is more efficient than mass invalidation: only entries that used updated indexes are stale.

### Batch Cleanup

```sql
-- Periodic job: remove expired and stale entries
DELETE FROM semantic_cache
WHERE expires_at < NOW()
   OR (
       -- Entry used hr-policies but version is outdated
       'hr-policies' = ANY(indexes_used)
       AND (version_tags->>'hr-policies')::int < $1  -- current_version
   );
```

---

## 7. Performance Characteristics

### Lookup Latency (HNSW on pgvector)

| Cache Size   | P50 Latency | P99 Latency |
| ------------ | ----------- | ----------- |
| 10K entries  | 2ms         | 5ms         |
| 100K entries | 5ms         | 15ms        |
| 1M entries   | 12ms        | 40ms        |

**At expected scale**: 1M entries total (50 tenants × 500 queries/day × 40 days) → P50 12ms lookup.

This is 60-100x faster than an LLM call (600-2000ms).

### Embedding Generation Cost (Required for Lookup)

The query embedding must always be generated to perform semantic lookup:

- Cost: ~$0.00013 per 1K tokens (~$0.000065 per query at avg 500 tokens)
- Latency: 100-200ms (mitigated by CACHE-7: query embedding cache)
- On cache hit: saves $0.013 LLM call — embedding cost is negligible (0.5% of savings)
- On cache miss: embedding is reused for vector search; no additional cost

---

## 8. Alternative Implementations

### Option A: GPTCache Library

**GPTCache** (open source) provides out-of-the-box semantic caching for LLM calls.

**Pros**: Ready to deploy; supports multiple similarity backends; active community
**Cons**: Additional dependency; not multi-tenant by default; customization required
**Verdict**: Viable for MVP validation; likely needs replacement for enterprise-grade multi-tenancy

### Option B: Redis with Vector Similarity Search (Redis VSS)

Redis Stack includes built-in vector search (HNSW).

**Pros**: Single infrastructure (Redis already deployed); sub-millisecond lookup
**Cons**: Embedding storage is expensive in Redis memory; no SQL-level version tagging; limited query capabilities
**Verdict**: Good for small-scale (<10K entries); pgvector preferred for enterprise scale

### Option C: pgvector (Recommended)

PostgreSQL with pgvector extension on the existing RDS Aurora instance.

**Pros**: Reuses existing PostgreSQL; ACID transactions; SQL-level control; scales well; native partitioning by tenant_id
**Cons**: Requires pgvector extension on RDS; HNSW index must be tuned
**Verdict**: **Recommended for production** — lowest operational overhead, best control

### Option D: Dedicated Vector Database (Qdrant/Weaviate/Pinecone)

**Pros**: Purpose-built; best performance at billion-scale
**Cons**: New service dependency; overkill for <10M entries; additional cost; operational overhead
**Verdict**: Consider only at 100+ tenant scale with millions of cached responses

---

## 9. Cache Hit Rate Projections

### Enterprise Knowledge Worker Pattern

Based on typical enterprise Q&A patterns:

| Query Category      | % of Volume | Semantic Repeat Rate     | Expected Cache Hit Rate |
| ------------------- | ----------- | ------------------------ | ----------------------- |
| HR/Policy questions | 35%         | 60% (7-day window)       | 40% (with 4h TTL)       |
| Financial/Analytics | 25%         | 30% (same day)           | 20%                     |
| IT/Technical        | 20%         | 45%                      | 30%                     |
| Project-specific    | 15%         | 15% (unique per project) | 5%                      |
| Real-time/Personal  | 5%          | N/A (not cached)         | 0%                      |

**Blended hit rate**: ~28% of queries served from semantic cache
**Effective hit rate** (excluding non-cacheable): ~30%

### Revenue Impact per Tenant

Assumptions:

- 500 queries/day per tenant
- $0.013 average LLM call cost
- 30% semantic cache hit rate

```
Daily LLM calls eliminated: 500 × 0.30 = 150
Daily savings: 150 × $0.013 = $1.95/tenant/day
Annual savings: $1.95 × 365 = $711.75/tenant/year
At 50 tenants: $35,587.50/year in LLM cost elimination
At 200 tenants: $142,350/year
```

---

## 10. Integration with Existing Pipeline

### Modified RAG Pipeline with Semantic Cache

```python
async def process_chat_query(
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    query: str
) -> AsyncIterator[str]:  # SSE stream

    # Stage 0: Generate query embedding (CACHE-7 — embedding cache)
    query_embedding = await get_cached_embedding(tenant_id, query)

    # Stage 0b: Semantic cache lookup (CACHE-B — NEW)
    if not is_personal_query(query) and not requires_real_time(query):
        semantic_hit = await semantic_cache_lookup(
            tenant_id=tenant_id,
            query_embedding=query_embedding,
            threshold=await get_tenant_cache_threshold(tenant_id)
        )
        if semantic_hit:
            # Adapt cached response for this user
            adapted = adapt_for_user(
                semantic_hit["response"],
                user_context=await get_user_context(tenant_id, user_id)
            )
            # Stream adapted response
            yield sse_event("cache_hit", {"similarity": semantic_hit["similarity"]})
            async for chunk in stream_response(adapted):
                yield sse_event("response_chunk", chunk)
            return

    # Stage 1: Intent Detection (CACHE-6)
    intent = await get_cached_intent(tenant_id, query)

    # Stage 2: Vector Search (CACHE-8)
    sources = await parallel_search_with_cache(tenant_id, query_embedding, intent)

    # Stage 3: Context Building (CACHE-4, CACHE-5, glossary cache)
    context = await build_context_with_cache(tenant_id, user_id, conversation_id)

    # Stage 4: LLM Synthesis
    async for chunk in llm_synthesize_stream(query, sources, context):
        yield sse_event("response_chunk", chunk)

    # Stage 5: Store in semantic cache (async, non-blocking)
    asyncio.create_task(
        semantic_cache_store(
            tenant_id=tenant_id,
            query_text=query,
            query_embedding=query_embedding,
            response=assembled_response,
            indexes_used=[s["index_id"] for s in sources],
            intent_category=intent["intent"],
            version_tags=await get_current_versions(tenant_id, sources),
            ttl_seconds=await get_tenant_cache_ttl(tenant_id)
        )
    )
```

---

## 11. Risks and Mitigations

| Risk                                       | Probability | Impact   | Mitigation                                                             |
| ------------------------------------------ | ----------- | -------- | ---------------------------------------------------------------------- |
| Stale cached response after doc update     | MEDIUM      | HIGH     | Version tag invalidation (Section 6)                                   |
| False positive match (wrong answer served) | LOW         | HIGH     | 0.95 threshold + user feedback to trigger invalidation                 |
| Personalized response leaked to other user | LOW         | CRITICAL | Two-tier response model (Section 5); never cache user-specific content |
| Cache poisoning via adversarial query      | VERY LOW    | HIGH     | Confidence threshold (>0.7); only store high-quality responses         |
| Memory bloat (3072-dim vectors)            | MEDIUM      | MEDIUM   | pgvector with compression; periodic cleanup; tiered TTLs               |

---

**Document Version**: 1.0
**Depends On**: `14-caching-architecture-overview.md`
**See Also**: `16-embedding-search-cache.md`, `17-multi-tenant-cache-isolation.md`
