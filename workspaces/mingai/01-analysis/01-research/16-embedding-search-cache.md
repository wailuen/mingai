# Embedding and Search Result Cache: Deep Dive

**Date**: March 4, 2026
**Focus**: Query embedding caching and vector search result caching
**Status**: Research Phase

---

## 1. Embedding Cache (CACHE-7)

### Why Embeddings are Ideal Cache Targets

Query embeddings are **purely deterministic functions**: identical input text + identical model = bit-for-bit identical output vector. This makes them the safest possible cache target with zero risk of serving wrong data.

Current pipeline generates embeddings on EVERY query, even repeated ones. With 500 queries/day per tenant and ~15% exact query repetition, this is 75 unnecessary API calls per day per tenant.

### Embedding Storage Format

A `text-embedding-3-large` vector has 3072 float32 dimensions:

- Raw float32: `3072 × 4 bytes = 12,288 bytes = 12KB`
- float16 compressed: `3072 × 2 bytes = 6,144 bytes = 6KB`
- Base64 encoded float32: ~16KB (for JSON-friendly storage)
- msgpack binary: ~12.3KB

**Recommended**: float16 compression in Redis → 6KB per cached embedding.

Memory per tenant (500 queries/day, 7-day TTL, 15% unique queries):

- Unique queries/week: `500 × 7 × 0.85 = 2,975 unique embeddings`
- Memory: `2,975 × 6KB = ~17.5MB per tenant`
- At 50 tenants: `875MB total` — acceptable in Redis

### Implementation

```python
import struct
import hashlib
import numpy as np
from typing import Optional

EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMS = 3072

def embedding_cache_key(tenant_id: str, query: str, model_id: str) -> str:
    """
    Cache key for query embeddings.
    Includes model_id to safely handle model version upgrades.
    """
    query_normalized = query.lower().strip()
    query_hash = hashlib.sha256(query_normalized.encode()).hexdigest()[:32]
    return f"mingai:{tenant_id}:emb:{model_id}:{query_hash}"

def serialize_embedding(embedding: list[float]) -> bytes:
    """Compress float32 to float16 for storage efficiency (50% size reduction)."""
    arr = np.array(embedding, dtype=np.float32)
    compressed = arr.astype(np.float16)
    return compressed.tobytes()

def deserialize_embedding(data: bytes) -> list[float]:
    """Decompress float16 back to float32."""
    arr = np.frombuffer(data, dtype=np.float16)
    return arr.astype(np.float32).tolist()

async def get_cached_embedding(
    tenant_id: str,
    query: str,
    model_id: str = EMBEDDING_MODEL
) -> Optional[list[float]]:
    """Return cached embedding or None."""
    key = embedding_cache_key(tenant_id, query, model_id)
    data = await redis.get(key)
    if data:
        return deserialize_embedding(data)
    return None

async def cache_embedding(
    tenant_id: str,
    query: str,
    embedding: list[float],
    model_id: str = EMBEDDING_MODEL,
    ttl: int = 604800  # 7 days
) -> None:
    """Store embedding in Redis with 7-day TTL."""
    key = embedding_cache_key(tenant_id, query, model_id)
    data = serialize_embedding(embedding)
    await redis.setex(key, ttl, data)

async def get_or_create_embedding(
    tenant_id: str,
    query: str,
    azure_openai_client,
    model_id: str = EMBEDDING_MODEL
) -> list[float]:
    """Get embedding from cache or generate and cache it."""
    # Try cache first
    cached = await get_cached_embedding(tenant_id, query, model_id)
    if cached is not None:
        metrics.increment("embedding_cache_hit", tags={"tenant_id": tenant_id})
        return cached

    # Generate embedding
    metrics.increment("embedding_cache_miss", tags={"tenant_id": tenant_id})
    response = await azure_openai_client.embeddings.create(
        input=query,
        model=model_id,
        dimensions=EMBEDDING_DIMS
    )
    embedding = response.data[0].embedding

    # Cache it (non-blocking)
    asyncio.create_task(
        cache_embedding(tenant_id, query, embedding, model_id)
    )

    return embedding
```

### Model Upgrade Strategy

When upgrading from `text-embedding-3-large` to a future model:

1. New model produces different vectors → incompatible with existing semantic cache
2. Cache key includes `model_id` → old entries automatically become unreachable
3. New model ID → fresh cache population begins
4. Old entries expire naturally via TTL (7 days)
5. During transition: embedding cache hit rate temporarily drops; gradually recovers

```python
# Migration helper: pre-warm cache with new model
async def migrate_embeddings(tenant_id: str, new_model_id: str):
    """Pre-warm embedding cache when upgrading models."""
    top_queries = await analytics.get_top_queries(tenant_id, limit=200, days=30)
    for query in top_queries:
        await get_or_create_embedding(tenant_id, query.text, azure_client, new_model_id)
    logger.info(f"Migrated {len(top_queries)} embeddings for tenant {tenant_id}")
```

---

## 2. Search Result Cache (CACHE-8)

### The Data Freshness vs. Latency Trade-off

Search result caching is the most complex decision because it involves a fundamental trade-off:

```
High TTL → Better cache hit rates → Higher latency savings → Risk of stale results
Low TTL  → Lower cache hit rates → Less savings → Fresh results always
```

The right TTL depends entirely on **how frequently knowledge base documents are updated**.

### Index Update Frequency Classification

| Index Type                            | Update Frequency  | Recommended Cache TTL |
| ------------------------------------- | ----------------- | --------------------- |
| Policy documents (HR, Legal, Finance) | Monthly/quarterly | 4-8 hours             |
| Product documentation                 | Weekly            | 1-2 hours             |
| Project wikis                         | Daily             | 15-30 minutes         |
| Real-time reports                     | Hourly            | Not cached            |
| News/external content                 | Minutes           | Not cached            |

**Tenant admin configuration**: Each knowledge base index should have a configurable TTL, set by the tenant admin who knows their update patterns. This becomes a UI feature.

### Cache Key Design

The search result cache key must encode:

1. Tenant context (isolation)
2. Which index was searched
3. What the query was (embedding-based, not text-based — same meaning = same key)
4. Search parameters (top_k, min_score, filters)

```python
import hashlib
import json

def search_cache_key(
    tenant_id: str,
    index_id: str,
    embedding: list[float],
    search_params: dict
) -> str:
    """
    Cache key for search results.
    Uses first 16 hex chars of embedding hash (sufficient for collision avoidance).
    Full SHA256 of embedding would be overkill and expensive to compute.
    """
    # Use quantized embedding for key (avoid float precision issues)
    emb_normalized = [round(x, 4) for x in embedding[:32]]  # First 32 dims + precision
    emb_key = hashlib.sha256(
        json.dumps(emb_normalized, sort_keys=True).encode()
    ).hexdigest()[:16]

    # Include search params (top_k, filters affect results)
    params_hash = hashlib.sha256(
        json.dumps(search_params, sort_keys=True).encode()
    ).hexdigest()[:8]

    return f"mingai:{tenant_id}:search:{index_id}:{emb_key}:{params_hash}"
```

### Implementation

```python
@dataclass
class SearchResultCacheEntry:
    results: list[dict]
    timestamp: float
    index_id: str
    tenant_id: str
    query_text: str  # Stored for audit/debug only

async def get_cached_search_results(
    tenant_id: str,
    index_id: str,
    embedding: list[float],
    search_params: dict
) -> Optional[list[dict]]:
    """Return cached search results or None."""
    # Check index TTL policy
    ttl_config = await get_index_cache_config(tenant_id, index_id)
    if ttl_config.ttl_seconds == 0:
        return None  # Caching disabled for this index

    key = search_cache_key(tenant_id, index_id, embedding, search_params)
    data = await redis.get(key)

    if data:
        entry = SearchResultCacheEntry(**json.loads(data))

        # Validate against version counter
        current_version = await get_index_version(tenant_id, index_id)
        if entry.get("index_version", 0) < current_version:
            await redis.delete(key)  # Stale — invalidate
            return None

        metrics.increment("search_cache_hit", tags={"tenant_id": tenant_id, "index_id": index_id})
        return entry.results

    return None

async def cache_search_results(
    tenant_id: str,
    index_id: str,
    embedding: list[float],
    search_params: dict,
    results: list[dict],
    query_text: str
) -> None:
    """Store search results in Redis."""
    ttl_config = await get_index_cache_config(tenant_id, index_id)
    if ttl_config.ttl_seconds == 0:
        return  # Caching disabled for this index

    key = search_cache_key(tenant_id, index_id, embedding, search_params)
    current_version = await get_index_version(tenant_id, index_id)

    entry = {
        "results": results,
        "timestamp": time.time(),
        "index_id": index_id,
        "tenant_id": tenant_id,
        "query_text": query_text[:200],  # Truncate for storage
        "index_version": current_version
    }

    await redis.setex(key, ttl_config.ttl_seconds, json.dumps(entry))
    metrics.increment("search_cache_store", tags={"tenant_id": tenant_id, "index_id": index_id})
```

### Document Update → Cache Invalidation Flow

When a document is updated/added/deleted in a knowledge base:

```
SharePoint Sync Worker
  │ Document changed
  ▼
Update Azure AI Search index
  │
  ▼
Increment index_version counter
  │ Redis: INCR mingai:{tenant_id}:version:{index_id}
  ▼
Publish invalidation event
  │ Redis PUBLISH mingai:invalidation:{tenant_id}
  │   {"type": "index_updated", "index_id": "hr-policies", "new_version": 43}
  ▼
(Optional) Batch delete stale keys
  │ DEL mingai:{tenant_id}:search:hr-policies:*
  │ Note: KEYS + DEL is blocking; use Lua script or SCAN for production
  ▼
Next search query: cache_key lookup → version mismatch → cache miss → fresh search
```

### Parallel Search with Cache

The existing pipeline searches indexes in parallel. Cache lookup should also be parallel:

```python
async def parallel_search_with_cache(
    tenant_id: str,
    query_embedding: list[float],
    selected_indexes: list[str],
    query_text: str
) -> list[dict]:
    """Search all selected indexes in parallel, using cache where available."""

    async def search_single_index(index_id: str) -> list[dict]:
        search_params = {
            "top_k": 5,
            "min_score": 0.6
        }

        # Try cache first
        cached = await get_cached_search_results(
            tenant_id, index_id, query_embedding, search_params
        )
        if cached is not None:
            return cached

        # Cache miss: execute search
        index_meta = await get_cached_index_metadata(tenant_id, index_id)
        results = await azure_search.search(
            index_name=index_meta.search_config.index_name,
            vector_queries=[...],
            **search_params
        )

        # Cache results asynchronously
        asyncio.create_task(
            cache_search_results(
                tenant_id, index_id, query_embedding,
                search_params, results, query_text
            )
        )

        return results

    # Execute all index searches concurrently
    results = await asyncio.gather(*[
        search_single_index(index_id)
        for index_id in selected_indexes
    ])

    # Flatten and deduplicate
    all_results = [r for sublist in results for r in sublist]
    return deduplicate_and_rank(all_results)
```

---

## 3. Index Metadata Cache (CACHE-9)

### What to Cache

The index metadata (stored in Cosmos DB / PostgreSQL) is read on every search operation:

- Index ID and name
- Azure AI Search index name, endpoint, API key
- Search configuration (top_k, min_score, semantic_config)
- Access control (which roles can query this index)
- Document count, last sync time

This data changes rarely (when admin updates index configuration) and reading it from the database on every query adds latency and cost.

### Implementation

```python
async def get_cached_index_metadata(tenant_id: str, index_id: str) -> IndexConfig:
    """Get index metadata from cache or database."""
    key = f"mingai:{tenant_id}:idx:{index_id}:meta"
    data = await redis.get(key)

    if data:
        return IndexConfig(**json.loads(data))

    # Cache miss: load from database
    index = await db.indexes.get(tenant_id=tenant_id, index_id=index_id)
    if not index:
        raise IndexNotFoundError(index_id)

    # Cache for 10 minutes
    await redis.setex(key, 600, json.dumps(index.dict()))
    return index

async def invalidate_index_metadata_cache(tenant_id: str, index_id: str) -> None:
    """Called when admin updates index configuration."""
    key = f"mingai:{tenant_id}:idx:{index_id}:meta"
    await redis.delete(key)

    # Also invalidate all indexes list cache
    list_key = f"mingai:{tenant_id}:idx:list"
    await redis.delete(list_key)
```

---

## 4. Combined Latency Improvement

### Before Caching (Baseline)

```
Operation                          Latency    Cost
─────────────────────────────────  ─────────  ──────────────
JWT validation (DB read)           5-10ms     ~$0.000001
User context (Cosmos DB)           10-30ms    ~$0.0001
Conversation history (Cosmos DB)   10-30ms    ~$0.0001
Intent detection (GPT-5 Mini)      300-800ms  ~$0.0002
Embedding generation               150-300ms  ~$0.00007
Index metadata (Cosmos DB ×N)      10-30ms×N  ~$0.0001×N
Vector search (Azure Search ×N)    200-600ms  ~$0.001×N
Glossary lookup (Cosmos DB)        10-30ms    ~$0.0001
LLM synthesis (GPT-5.2-chat)       1000-2000ms $0.010-0.016
────────────────────────────────────────────────────────────
TOTAL (2 indexes)                  ~2500ms    ~$0.012-0.018
```

### After Full Caching (Cache Hit Scenario)

```
Operation                          Latency    Cost
─────────────────────────────────  ─────────  ──────────────
JWT validation (Redis cache)       <1ms       ~$0
User context (Redis)               2-5ms      ~$0
Conversation history (Redis)       2-5ms      ~$0
Intent detection (Redis)           2-5ms      ~$0
Embedding generation (Redis)       2-5ms      ~$0
Index metadata (Redis ×N)          1-2ms×N    ~$0
Vector search (Redis)              2-5ms      ~$0
Glossary lookup (Redis)            2-5ms      ~$0
Semantic cache lookup (pgvector)   12-40ms    ~$0
LLM synthesis: CACHE HIT           0ms        $0
────────────────────────────────────────────────────────────
TOTAL (full cache hit)             ~40-80ms   ~$0
```

**Result**: 30-60× latency improvement, 100% cost elimination for cache-hit queries.

### After Partial Caching (Cache Miss — LLM needed)

```
Operation                          Latency    Cost
─────────────────────────────────  ─────────  ──────────────
JWT validation (Redis cache)       <1ms       ~$0
User context (Redis)               2-5ms      ~$0
Conversation history (Redis)       2-5ms      ~$0
Intent detection (Redis or LLM)    5ms-800ms  $0 or $0.0002
Embedding generation (Redis)       2-5ms      ~$0
Index metadata (Redis)             1-2ms      ~$0
Vector search (Redis)              2-5ms      ~$0
Glossary lookup (Redis)            2-5ms      ~$0
LLM synthesis (unavoidable)        1000-2000ms $0.010-0.016
────────────────────────────────────────────────────────────
TOTAL (semantic cache miss)        ~1050-2100ms $0.010-0.016
```

Overhead removed: 500-1000ms of non-LLM pipeline steps eliminated via caching.

---

## 5. Cache Warming for Embeddings

Pre-warming embedding cache for top queries dramatically improves initial hit rates.

```python
# Scheduled job: runs daily at 3 AM (off-peak)
async def warm_embedding_cache(tenant_id: str):
    """Pre-generate and cache embeddings for frequently-asked queries."""

    # Get top 100 queries from past 30 days
    top_queries = await analytics.get_top_queries(
        tenant_id=tenant_id,
        limit=100,
        days=30,
        min_count=3  # Only queries asked 3+ times
    )

    # Check which are already cached
    uncached = []
    for query in top_queries:
        if not await get_cached_embedding(tenant_id, query.text):
            uncached.append(query.text)

    # Batch generate embeddings (max 20 concurrent to avoid rate limits)
    semaphore = asyncio.Semaphore(20)
    async def warm_single(query_text: str):
        async with semaphore:
            await get_or_create_embedding(tenant_id, query_text, azure_client)

    await asyncio.gather(*[warm_single(q) for q in uncached])
    logger.info(f"Warmed {len(uncached)} embeddings for tenant {tenant_id}")
```

---

**Document Version**: 1.0
**Depends On**: `14-caching-architecture-overview.md`, `15-semantic-caching-analysis.md`
