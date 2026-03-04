# Red Team Critique: Caching Strategy

**Date**: March 4, 2026
**Reviewer**: Red Team Agent
**Documents Reviewed**:

- `01-analysis/01-research/14-caching-architecture-overview.md`
- `01-analysis/01-research/15-semantic-caching-analysis.md`
- `01-analysis/01-research/16-embedding-search-cache.md`
- `01-analysis/01-research/17-multi-tenant-cache-isolation.md`
- `01-analysis/06-caching-product/01-value-proposition.md`
- `01-analysis/06-caching-product/02-competitive-analysis.md`
- `02-plans/03-caching-implementation-plan.md`
- `03-user-flows/05-caching-ux-flows.md`

---

## Critical Gaps (Must Fix Before Implementation)

These are issues that will cause system failures, security breaches, or serve incorrect data to users.

---

### CRIT-1: The `semantic_cache_lookup` function has a broken SQL parameter binding

**File**: `15-semantic-caching-analysis.md`, Section 4, "Search Query"

The function builds a `filters` list and a `params` list separately, but the parameter placeholder indices are hardcoded (`$1`, `$2`, `$3`, `$4`) and do not reflect the conditional addition of `intent_category`. The bug:

```python
params = [tenant_id, query_embedding, threshold]  # $1, $2, $3

if intent_category:
    filters.append("intent_category = $4")  # Hardcoded $4
    params.append(intent_category)           # Now $4 — this is fine
```

The problem is the WHERE clause also uses `$2` for the cosine distance expression twice:

```sql
AND 1 - (query_embedding <=> $2::vector) >= $3
ORDER BY query_embedding <=> $2::vector ASC
```

This is actually valid asyncpg syntax. BUT the larger bug is that the function returns `result["id"]` in the hit_count update:

```python
asyncio.create_task(
    db.execute(
        "UPDATE semantic_cache SET hit_count = hit_count + 1 WHERE id = $1",
        result["id"]   # <-- "id" is NOT selected in the SELECT statement
    )
)
```

The SELECT only fetches `response_json`, `query_text`, `hit_count`, and `similarity`. The `id` column is never selected. This will raise a `KeyError` on every cache hit, causing the background task to log an exception silently. The `id` field must be added to the SELECT list.

**Fix required**: Add `id` to the SELECT columns in `semantic_cache_lookup`.

---

### CRIT-2: Search cache key uses only first 32 embedding dimensions — catastrophic collision risk

**File**: `16-embedding-search-cache.md`, Section 2, "Cache Key Design"

```python
emb_normalized = [round(x, 4) for x in embedding[:32]]  # First 32 dims + precision
```

This uses only 32 of 3072 dimensions (1.04% of the vector) to generate the cache key. Two semantically different queries can easily produce nearly identical first-32 dimensions while being entirely different in the remaining 3040 dimensions. This is not a theoretical concern — in high-dimensional embedding spaces, the discriminative information is distributed across all dimensions, not concentrated in the first 32.

The consequence: different queries map to the same search cache key, and User A gets the search results for User B's query. In a multi-tenant system with topic-specific documents, this is a data correctness failure.

The justification given ("Full SHA256 of embedding would be overkill and expensive to compute") is wrong. SHA256 of the full embedding runs in microseconds on any modern CPU. The correct approach is to hash all 3072 dimensions (or at minimum use the float16-compressed bytes directly as the hash input, which is already being produced for storage).

**Fix required**: Hash the complete embedding vector, not 32 dimensions.

---

### CRIT-3: Race condition on semantic cache write — concurrent users can generate and store duplicate entries

**File**: `15-semantic-caching-analysis.md`, Section 4, "Cache Write"

```sql
ON CONFLICT DO NOTHING
```

The write uses `ON CONFLICT DO NOTHING`, but the `semantic_cache` table has no unique constraint defined (see the schema — the primary key is a UUID `gen_random_uuid()` and there is no unique index on `(tenant_id, query_embedding)`). Therefore `ON CONFLICT DO NOTHING` will never trigger — it conflicts on nothing — and every concurrent writer will successfully insert a duplicate row with a different UUID.

The consequence: at high concurrency, the same query embedding gets stored N times (once per concurrent cache-miss request). This bloats storage, pollutes HNSW index quality with near-duplicate vectors, and makes hit_count tracking meaningless.

Furthermore, `ON CONFLICT DO NOTHING` on a UUID primary key means this statement silently degrades to a plain INSERT with no deduplication. The authors may have intended this to target a `(tenant_id, query_text)` unique constraint, but that constraint does not exist in the schema as written.

**Fix required**: Add a unique index on `(tenant_id, query_embedding)` (using pgvector's equality operator) OR lock at the application layer with Redis SETNX before triggering the write, OR at minimum accept the duplicate writes and implement periodic deduplication.

---

### CRIT-4: The Lua memory quota script is fundamentally broken

**File**: `17-multi-tenant-cache-isolation.md`, Section 4, "Memory Quotas via Lua Script"

```lua
local quota_key = "mingai:" .. ARGV[3] .. ":mem_usage"
local current = tonumber(redis.call("GET", quota_key) or "0")
local value_size = #value
```

The quota is tracked by counting raw bytes of values written. This is not how Redis memory works. Redis memory includes:

1. Key overhead (per-key metadata, expiry data, pointer structures)
2. Encoding overhead (ziplist, listpack, skiplist depending on data type)
3. Memory allocator fragmentation

The actual memory per key is typically 2-4x the raw value size. A tenant that writes 100MB of raw value bytes may actually consume 300-400MB in Redis. This quota system will routinely undercount memory consumption by 2-4x, making the "hard limit" functionally meaningless.

Additionally, the quota counter uses `EXPIRE quota_key 3600` — it resets every hour. This means a tenant can write up to the quota, wait for the hour to reset, and write the quota again. Over a day, a tenant could consume 24x their nominal quota. This is not a quota; it is a rate limiter with a one-hour window.

**Fix required**: Use Redis `MEMORY USAGE key` command to get accurate per-key memory consumption (available since Redis 4.0), or use Redis logical database separation to enforce memory limits at the Redis server level via `maxmemory` per database rather than application-level byte counting.

---

### CRIT-5: Version tag invalidation is a lookup-time check, not a delete — stale entries accumulate indefinitely

**File**: `15-semantic-caching-analysis.md`, Section 6, "Version Tag System"

```python
async def is_cache_valid(entry: dict, current_versions: dict) -> bool:
    stored_versions = entry["version_tags"]
    for index_id, stored_version in stored_versions.items():
        current = current_versions.get(index_id, 0)
        if current > stored_version:
            return False
    return True
```

This function checks validity at lookup time but never deletes the stale entry. The document says "on the next semantic cache lookup: if stale → cache miss, regenerate response." The stale entry remains in the database. After the new response is generated and stored, there are now TWO entries in the semantic cache for semantically similar queries: the stale one and the new one.

The cleanup job is defined as:

```sql
DELETE FROM semantic_cache
WHERE expires_at < NOW()
   OR (
       'hr-policies' = ANY(indexes_used)
       AND (version_tags->>'hr-policies')::int < $1
   );
```

This cleanup SQL is hardcoded to the literal string `'hr-policies'`. This is not parametric — it will only ever clean up entries from the `hr-policies` index. Any other index's stale entries will never be cleaned by this query. The document presents this as a "periodic job" but it is a broken example that would require N separate DELETE statements for N indexes, and there is no mechanism defined to enumerate indexes and generate those statements.

**Fix required**: The cleanup job must query all `distinct(indexes_used)` values and generate per-index cleanup statements, OR rewrite the cleanup as a single query that checks the version tag JSONB against a current-versions lookup table. The stale entry must also be deleted lazily at lookup time (not just skipped).

---

### CRIT-6: `build_cache_key` allows dot (`.`) in key components, enabling namespace traversal

**File**: `17-multi-tenant-cache-isolation.md`, Section 2, and `02-plans/03-caching-implementation-plan.md`, Phase C1

```python
if not re.match(r'^[a-zA-Z0-9\-_:\.]+$', str(part)):
    raise ValueError(f"Invalid cache key component: {part!r}")
```

The allowed pattern includes the colon character (`:`). Since the key format is `mingai:{tenant_id}:{cache_type}:{discriminator}`, and `discriminator` is composed by joining `parts` with `:`, any part containing a colon creates a key with extra segments that can collide with other cache types.

Example: a `search` key discriminator of `hr-policies:emb_hash:extra` would produce:
`mingai:{tenant_id}:search:hr-policies:emb_hash:extra`

This is indistinguishable from a search key with `index_id=hr-policies`, `emb_key=emb_hash`, and `params_hash=extra`. If an attacker can control the `index_id` (e.g., via a crafted API request where the index_id value contains a colon), they could potentially construct keys that collide with other tenants' entries in edge cases, or at minimum pollute the `version:{index_id}` counter namespace.

The document's own example (`5.1 Cache Key Poisoning`) addresses query text injection via hashing — which is correct. But it does not address the case where an index_id or other non-hashed parameter contains colons.

**Fix required**: Remove `:` from the allowed character set for cache key parts, OR enforce that non-hashed parts (like `index_id`) are validated against an allowlist of known index IDs before being used in key construction.

---

### CRIT-7: Semantic cache lookup bypasses per-index RBAC

**File**: `15-semantic-caching-analysis.md`, Section 2, "Key Design Decisions"

The cache scope is "Per-tenant" and the response is stored with `indexes_used`. However, the lookup function (`semantic_cache_lookup`) does not filter by which indexes the requesting user has access to. Consider:

- User A has access to `hr-policies` and `finance-docs`
- User B has access only to `hr-policies`
- User A asks a question → response is generated from both `hr-policies` AND `finance-docs` → stored in semantic cache with `indexes_used = ["hr-policies", "finance-docs"]`
- User B asks a semantically similar question → semantic cache lookup returns the cached response → User B receives content derived from `finance-docs` they do not have access to

The two-tier response model (Section 5) separates personalization but it does not separate access control. The `CacheableResponse` contains `source_chunks` from both indexes. User B can now read finance document content through the semantic cache.

This is a **data access control bypass**, not merely a staleness issue. It directly violates the RBAC model that is listed as one of mingai's genuine differentiators.

**Fix required**: The semantic cache key must incorporate the requesting user's index access set (or at minimum, the set of `index_ids` they are permitted to query). Cache lookup must only return entries where `indexes_used` is a subset of the user's permitted indexes. This significantly reduces cache hit rates but is non-negotiable for compliance.

---

## High Priority Gaps (Fix Before MVP)

---

### HIGH-1: Float16 compression introduces precision loss that breaks semantic cache consistency

**File**: `16-embedding-search-cache.md`, Section 1, "Embedding Storage Format"

The plan is to store embeddings in Redis as float16 (half precision) and then decompress back to float32 for use in vector similarity computation. This is presented as a pure win (50% size reduction, "zero risk").

The problem: when the decompressed float16 embedding is used for the pgvector HNSW similarity search in the semantic cache, the cosine similarity scores will differ from scores computed with the original float32 vector. The error is not trivial: float16 has only ~3 decimal digits of precision versus ~7 for float32.

Consider a query with a semantic cache entry stored at similarity 0.952 (above the 0.95 threshold). The float16-decompressed version of the query embedding produces a slightly different cosine distance, potentially computed as 0.949 (below threshold). The cache hit is missed. Conversely, an entry at 0.948 could be promoted above 0.95.

The documents never establish whether the embedding cached in Redis (float16) and the embedding stored in pgvector's HNSW index are the same compressed form. If Redis returns float16-decompressed-to-float32 and pgvector stores the original float32, they are different vectors. The semantic cache lookup and the Redis embedding cache are on different code paths with different compression states.

**Fix required**: Establish a single canonical embedding representation. Either use float16 everywhere (including pgvector storage, acknowledging precision loss) or use float32 everywhere (accepting the storage cost). Document explicitly that the embedding used for HNSW lookup is the same representation as the one stored in the cache. Do not silently introduce lossy compression that affects similarity thresholds.

---

### HIGH-2: Cache warming can trigger during business hours due to timezone calculation error

**File**: `02-plans/03-caching-implementation-plan.md`, Phase C2; `14-caching-architecture-overview.md`, Section 7

The warming job is described as running "daily at 3 AM (tenant-local timezone)" and "daily at 2 AM tenant-local time." These two documents give different times for the same job (2 AM vs 3 AM). More critically, neither document explains how the scheduler knows the tenant's timezone.

The implementation snippet:

```python
top_queries = await analytics.get_top_queries(tenant_id, limit=50, days=7)
```

There is no timezone configuration model referenced for tenants. If tenant timezone is not stored, the scheduler defaults to UTC. A tenant in UTC-8 (US Pacific) has "3 AM UTC" as 7 PM the previous day — peak business hours. Warming 200 embedding API calls and generating LLM responses during peak hours adds latency spikes and increases Azure OpenAI rate limit pressure exactly when users are actively querying.

Additionally, the warming job makes up to 200 concurrent Azure OpenAI embedding calls (semaphore of 20). At ~$0.00007 per call, this is $0.014/tenant/day for embeddings alone — cheap, but the Azure OpenAI rate limits (requests per minute) are shared with live user traffic. A 20-concurrent burst at 3 AM UTC for a Pacific tenant is hitting the API during their business hours.

**Fix required**: Store tenant timezone in the tenant configuration model. The implementation plan for Phase C1 does not add a timezone field to the tenant schema. This must be added before the warming job can function correctly.

---

### HIGH-3: Redis pub/sub invalidation has no acknowledgment — invalidations can be silently lost

**File**: `17-multi-tenant-cache-isolation.md`, Section 5.4; `14-caching-architecture-overview.md`, Section 6

The invalidation model uses Redis Pub/Sub:

```python
await redis.publish(
    "mingai:invalidation:auth",
    json.dumps({"type": "user_role_changed", "tenant_id": tenant_id, "user_id": user_id})
)
```

Redis Pub/Sub is fire-and-forget with no delivery guarantees. If no subscriber is listening when the message is published (subscriber restarted, network blip, pod rolling deployment), the invalidation message is silently dropped. The subscriber `start_invalidation_listener` is a persistent async loop — if it crashes, it must be restarted manually (or by pod restart). During the restart window, role change events are published but not received.

The result: a user whose role was revoked continues to use cached permissions until the TTL expires (up to 10 minutes). For security-sensitive operations (a user being fired, a role being downgraded due to compliance audit), 10 minutes of continued access via stale cache is unacceptable.

The documents acknowledge TTL as "the final safety net" but this framing is backwards for permission caches. Permission changes are not routine — they are often triggered by security events. The safety net must not be a 10-minute window.

**Fix required**: Use Redis Streams (not Pub/Sub) for invalidation events. Streams provide consumer groups with acknowledged delivery and message persistence. A subscriber restart can replay missed messages from the stream. Alternatively, the permission cache TTL for user context must be reduced to 60 seconds (not 600 seconds) to bound the maximum staleness after an invalidation loss.

---

### HIGH-4: The 30-day engineering estimate (10 weeks, 1 engineer) is wildly optimistic

**File**: `02-plans/03-caching-implementation-plan.md`, footer

"Estimated Engineering Effort: ~30 person-days (6 weeks at 5 days/week, 1 engineer)"

The math is already wrong: 10 weeks at 5 days/week = 50 person-days, not 30. But even 50 days is unrealistic.

Phase C3 alone (semantic cache) requires:

- pgvector on RDS Aurora: provisioning, extension installation, SSL configuration, performance baseline
- HNSW index tuning: `m` and `ef_construction` parameters require empirical benchmarking with actual data volumes
- Partition-by-tenant_id on PostgreSQL: partitioned table management, per-tenant partition creation on tenant provisioning
- Two-tier response model: requires refactoring the existing LLM synthesis output format
- Version tag system: requires changes to the document sync pipeline (SharePoint worker must increment version counters)
- Alembic migration: requires coordinated deployment with the PostgreSQL schema
- Integration with existing SSE streaming: semantic cache hit must interrupt the stream setup path

This is not 4 weeks for 1 engineer. This is a minimum of 6-8 weeks for 1 engineer, not counting testing and bug-fix cycles.

The entire 4-phase plan is scoped assuming zero rework, zero bugs, zero infrastructure delays, and a single engineer who never touches anything else. Real projects run at 60-70% of ideal velocity due to meetings, context switching, and unforeseen issues.

**Fix required**: Revise estimates to 60-80 person-days minimum. Phase C3 should be treated as a 6-week project on its own. Risk register should include "single engineer becomes unavailable" as a scenario.

---

### HIGH-5: "Configurable TTL per index" in Phase C2 requires a schema change not listed as a dependency

**File**: `02-plans/03-caching-implementation-plan.md`, Phase C2

Phase C2 Deliverable 4: "Admin can set per-index cache TTL: 0 (disabled), 15min, 30min, 1h, 4h, 8h, 24h"

The TTL setting must be persisted somewhere. The implementation plan does not mention:

- What database table stores this configuration (`indexes` in Cosmos DB or a new PostgreSQL table?)
- What migration is required to add the TTL field to the index metadata model
- What the default value is for existing indexes (the plan says "Default: 1 hour" but that default must be enforced at the migration layer)
- How `get_index_cache_config()` is implemented (referenced in `16-embedding-search-cache.md` but not defined anywhere)

The `SearchResultCacheEntry` dataclass in `16-embedding-search-cache.md` does not include an `index_version` field, but `get_cached_search_results` references `entry.get("index_version", 0)`. This is an inconsistency between the dataclass definition and the retrieval code.

**Fix required**: Define the complete data model change required for per-index cache configuration. Specify the migration. Implement `get_index_cache_config()` explicitly. Fix the `SearchResultCacheEntry` dataclass to include `index_version`.

---

### HIGH-6: HNSW index on a partitioned table does not work in pgvector

**File**: `15-semantic-caching-analysis.md`, Section 4, "Database Schema"

```sql
CREATE TABLE semantic_cache (
    ...
) PARTITION BY LIST (tenant_id);

CREATE INDEX semantic_cache_embedding_idx
    ON semantic_cache
    USING hnsw (query_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

In PostgreSQL with pgvector, creating an HNSW index on a partitioned parent table requires that each partition has its own index. The `CREATE INDEX ... ON semantic_cache` statement creates an index only on the parent table shell, not on child partitions (this changed in PostgreSQL 16 with `CREATE INDEX ... ON ONLY`). For the index to actually be used, each tenant partition must have its own HNSW index created explicitly at partition creation time.

This means: tenant provisioning must include `CREATE INDEX ON semantic_cache_{tenant_id} USING hnsw (...)`. The implementation plan does not include this step in tenant provisioning flow. New tenants will experience full sequential scans on their semantic cache table until an index is manually created.

Furthermore, HNSW indexes on pgvector require the entire index to fit in memory for optimal performance. A 1M-entry cache with 3072-dimensional vectors requires approximately 12GB of RAM for the HNSW graph structure. The sizing estimates (Section 7 of `15-semantic-caching-analysis.md`) only address the data storage (pgvector rows) and not the in-memory HNSW graph requirements.

**Fix required**: Include `CREATE INDEX` for each tenant partition in the tenant provisioning workflow. Add HNSW memory requirements to the infrastructure sizing section — this is not just a storage problem.

---

## Medium Priority Gaps (Fix Before GA)

---

### MED-1: The 80/15/5 breakdown is asserted, not derived

**File**: `01-analysis/06-caching-product/01-value-proposition.md`, Section 2

The 80/15/5 framework is used to categorize caching components as "100% reusable" (80%), "self-service configurable" (15%), and "custom dev required" (5%). Every component in the "80%" column is labeled "100% reusable" — which means literally everything is in the 80% bucket and nothing is in the 15% or 5% buckets based on the table's own logic.

The 15% column lists 6 items (search TTL, semantic threshold, semantic TTL, MCP TTL, warming schedule, cache disable) and the 5% column lists 4 items (domain-specific threshold, custom warming queries, audit logging extension, regional partitioning). But there is no explanation of why these percentages are 80/15/5 rather than 70/20/10 or 90/8/2. The split is not derived from usage data, customer research, or any quantitative analysis — it is asserted.

**Problem for product positioning**: If an enterprise prospect asks "what percentage of our configuration will be custom work?", the answer "5%" comes from a framework applied without any validation. If reality is 20% custom (very likely for enterprises with unusual data residency or compliance needs), the estimate misleads sales conversations.

---

### MED-2: Competitive claims about Glean, Copilot, and Guru are based on inference, not evidence

**File**: `02-competitive-analysis.md`, throughout

The competitive analysis repeatedly uses the phrase "inferred behavior" and "likely implements." Examples:

- "Glean likely implements basic response caching, but details are not published."
- "No semantic response caching evident from response latency patterns"
- "Microsoft does not document its internal caching architecture for Copilot."
- "Inferred behavior (from public documentation and user reports)"

Every claim about competitors is either unverified inference or acknowledged as unknown. The gap analysis table in Section 3 states "No competitor offers..." for 6 items — but since competitor internals are unknown, these claims cannot be verified.

Using unverified competitive claims in sales materials (which this analysis feeds) creates legal risk (false advertising) and credibility risk if a prospect demonstrates that a competitor already has one of these "unique" features.

Glean in particular has a sophisticated engineering team and has been building enterprise search since 2019. The assumption that they have "zero pipeline transparency" and "no semantic caching" is based on nothing more than the fact that their documentation does not publicly disclose it.

**Fix required**: Tag all competitive claims as "unverified inference" in any external materials. Commission a proper competitive teardown using trial accounts before presenting these as differentiators to enterprise prospects.

---

### MED-3: The "living institutional knowledge base" claim presupposes static enterprise knowledge — it does not hold for most industries

**File**: `01-analysis/06-caching-product/01-value-proposition.md`, Section 4 (Amplify)

"Year 2: Plateau at 60-70% — structural FAQ cache + rotating current-events queries"

This projection assumes enterprise knowledge is mostly stable FAQs that repeat over time. For the specific industries mingai targets (finance, legal, M&A), knowledge is highly dynamic:

- A law firm's knowledge base changes with every new case, regulation, and precedent
- An investment bank's knowledge base changes with every deal, every market move, every regulatory filing
- A startup's policies and processes change monthly

The semantic cache TTL analysis (Section 3 of `15-semantic-caching-analysis.md`) actually acknowledges this: "Project-specific" queries have 15% semantic repeat rate. But the "Amplify" value proposition ignores this and projects a stable 60-70% cache hit rate by Year 2. For legal or finance-focused enterprises, the actual mature cache hit rate may be 25-35%, not 60-70%.

The cache hit rate projections in `15-semantic-caching-analysis.md`, Section 9, show "Project-specific" queries at 5% expected cache hit rate and only 15% of volume. But for a VC firm or law firm, project-specific queries may be 50-60% of volume, collapsing the blended hit rate from 28% to 12-15%.

---

### MED-4: "Offline/degraded mode" is mentioned but never designed

**File**: `01-analysis/06-caching-product/01-value-proposition.md`, Section 5 (Accessibility)

"Offline/degraded mode: read-only cache mode serves stale responses when LLM unavailable"

This feature is mentioned as a capability but there is zero design for it in any of the documents. Questions that are not answered:

- How does the system detect "LLM unavailable" vs "LLM slow"?
- Which cache layer serves stale responses — Redis, pgvector, or both?
- What staleness limit is acceptable in degraded mode?
- How does the user know they are in degraded mode?
- Does degraded mode apply to all tenants or is it configurable?
- What happens when the LLM comes back — does the system re-serve fresh responses for in-flight queries?

If this is to be presented as a product capability to enterprise buyers (especially those with uptime SLAs), it must be fully designed before going to market.

---

### MED-5: The admin "Preview Impact" UI feature (Flow TA-C2) requires a predictive model that doesn't exist

**File**: `03-user-flows/05-caching-ux-flows.md`, Flow TA-C2

```
PREVIEW IMPACT
If you change TTL from 4h → 8h:
Expected hit rate: 64% → 72% (+8%)
Expected savings: +$24.50/month
```

This feature requires the system to predict how changing the TTL will affect the hit rate. This is a non-trivial prediction problem. It requires:

- Historical data on how often cache entries are queried between their age-4h and age-8h window
- A hit rate prediction model that accounts for query volume, query diversity, and document update frequency
- Confidence bounds on the prediction (the "+8%" could easily be +2% or +15% depending on query patterns)

None of the technical documents design this predictive model. This is not an "easy" admin UX feature — it requires a statistical model trained on per-tenant query timing data that does not exist at MVP stage. If implemented naively (just showing "+8%"), it will show wrong numbers that undermine admin trust in the entire analytics dashboard.

**Fix required**: Either descope the "Preview Impact" feature for MVP/GA and show only "Higher TTL = higher hit rate (consult historical data)" guidance, OR design the prediction model explicitly as a separate workstream.

---

### MED-6: Intent cache normalization is under-specified and inconsistent

**File**: `14-caching-architecture-overview.md`, Section 4.4; `02-plans/03-caching-implementation-plan.md`, Phase C2

The overview says: "Normalize query before hashing: lowercase, strip extra whitespace"

The implementation plan says: "Query normalization: lowercase, strip whitespace, remove punctuation"

These are different normalization rules (the plan removes punctuation, the overview does not). If different parts of the codebase implement different normalizations, the same query will produce different hashes. A query normalized by the intent cache code path and the same query normalized by the embedding cache code path will produce different hashes if punctuation handling differs.

Furthermore, "remove punctuation" is too vague. Does "Q3 revenue" become "Q3 revenue" or "q3 revenue"? Does "What's the PTO policy?" become "whats the pto policy" or "what s the pto policy"? What about non-ASCII punctuation used by international employees? These details matter for cache hit rates.

---

### MED-7: Redis Cluster vs. Sentinel choice is deferred without decision criteria

**File**: `14-caching-architecture-overview.md`, Section 3, Layer 4

"Redis Cluster vs Sentinel: Sentinel for single-region HA; Cluster for multi-region"

This is stated as a fact but the system's actual region strategy is not defined. If mingai is targeting EU GDPR compliance with data residency (mentioned in `17-multi-tenant-cache-isolation.md`, Section 6), it must be multi-region by definition. Sentinel is explicitly noted as insufficient for multi-region. Therefore the choice between Sentinel and Cluster is not actually deferred — it is already forced to Cluster for any GDPR-compliant deployment.

The implementation plan does not include Redis Cluster configuration as a Phase C1 deliverable, yet the compliance requirements would require it before onboarding EU tenants. This is a missing dependency.

---

### MED-8: UX flows do not cover the scenario where semantic cache returns wrong answer with high confidence

**File**: `03-user-flows/05-caching-ux-flows.md`

Flow EDGE-C3 covers a similarity of 0.93 (below threshold, correctly rejected). Flow EU-C5 covers thumbs-down on a cached response. But there is no flow for the most dangerous scenario: a semantic cache hit at 0.96 similarity that is factually wrong because the query was subtly different in a way the cosine similarity did not capture.

Example:

- Cached: "What is the PTO policy for employees hired before 2024?" (Answer: 20 days)
- Query: "What is the PTO policy for employees hired in 2024?" (Answer: 15 days, new hire policy)
- Cosine similarity: 0.96 (above threshold)
- Result: User receives wrong answer with "⚡ Fast response" indicator, no warning

The thumbs-down path (EU-C5) handles feedback after the fact, but there is no proactive warning mechanism for subtle-but-critical query distinctions. The "3h ago" timestamp is not sufficient warning — the user cannot know the answer is wrong without already knowing the answer.

The flow also does not cover what happens when 10+ users receive and act on a wrong cached answer before someone submits negative feedback. The documents say "3+ thumbs-down triggers automatic escalation" but there is no notification to users who previously received the wrong answer.

---

## Low Priority Gaps (Backlog)

---

### LOW-1: The model name "GPT-5 Mini" and "GPT-5.2-chat" are hardcoded in the architecture documents

**File**: `14-caching-architecture-overview.md`, Section 2 pipeline diagram

Models referenced: "Intent Detection (GPT-5 Mini)", "LLM Synthesis (GPT-5.2-chat)"

Per the project's own `rules/env-models.md`, model names must never be hardcoded. These are architecture documents (not production code), so this does not violate the rule technically, but it creates a maintenance problem: any time the model changes, every architecture document must be updated. The pipeline diagram should reference model roles (e.g., "Intent LLM", "Synthesis LLM") and note that actual model names come from `.env`.

---

### LOW-2: The cost savings arithmetic in `15-semantic-caching-analysis.md` contains a calculation error

**File**: `15-semantic-caching-analysis.md`, Section 1

Section 1 calculates:

- 50 tenants × $3.90/day = "$195/day = $71,175/year"
- $195 × 365 = $71,175 ✓ (correct)

Section 9 calculates:

- "$711.75/tenant/year" for 500 queries/day, 30% hit rate
- "At 50 tenants: $35,587.50/year"

But Section 1 says "50 tenants × $3.90/day = $195/day = $71,175/year" and Section 9 says "50 tenants = $35,587.50/year."

These are different: $71,175/year (Section 1) vs. $35,587.50/year (Section 9). Section 1 uses 1,000 queries/day/tenant, Section 9 uses 500 queries/day/tenant. The document does not acknowledge this discrepancy — different sections use different query volume assumptions without flagging the inconsistency. A prospect or investor reading both sections will see conflicting savings claims.

---

### LOW-3: The "Enterprise tier gets dedicated Redis DB" solution hits a Redis hard limit

**File**: `17-multi-tenant-cache-isolation.md`, Section 4

"Redis supports up to 16 databases (DB 0-15) per instance"

The document proposes allocating dedicated Redis databases (DB 0-15) to enterprise tenants. With only 16 logical databases available, this caps enterprise tenants at 15 (DB 0 is for shared tenants). Once the 16th enterprise tenant is onboarded, the architecture breaks down and requires a new Redis instance.

This limit is never mentioned in the document. If the product roadmap includes scaling to 50+ enterprise tenants (a reasonable goal for a commercial SaaS), this approach requires multiple Redis instances. The connection pool code (`get_redis_connection`) would need to support multiple Redis hosts, not just multiple DB numbers.

---

### LOW-4: The frontend cache configuration (TanStack Query) is described but not specified

**File**: `14-caching-architecture-overview.md`, Section 3, Layer 1

"Configure TanStack Query staleTime and cacheTime per query type"

The document notes this is "already partially implemented" and suggests specific values (30s stale time for conversation list, 5min for index list) but there is no Phase C1 deliverable for this work. It falls through the gaps — not in C1 (backend focus), not in C2, not in C3, not in C4. If it is "required" (as the document states), it must be in a phase.

---

### LOW-5: "Monthly email report" (Flow TA-C1, Phase C4) introduces email infrastructure complexity not scoped

**File**: `02-plans/03-caching-implementation-plan.md`, Phase C4; `03-user-flows/05-caching-ux-flows.md`, Flow TA-C1

"Monthly cost report — PDF/email"

Generating PDF reports and sending emails requires either an email service (SES, SendGrid) and a PDF generation library. Neither is mentioned in the implementation dependencies, and there is no existing email infrastructure in the architecture documents. This is a non-trivial feature addition that could delay Phase C4 for an unrelated infrastructure reason.

---

## Verified Claims (Good)

The following are well-reasoned and should be retained:

1. **Multi-tenant key namespace design** (`17-multi-tenant-cache-isolation.md`, Section 2): The `mingai:{tenant_id}:{type}:{discriminator}` pattern with UUID validation, cache-type allowlist, and the requirement to derive `tenant_id` from JWT (not user input) is a correct, defensible design. The explicit test cases (Section 7) are a genuine strength.

2. **Float16 compression for embedding storage in Redis** (`16-embedding-search-cache.md`, Section 1): The 50% storage reduction via float16 is technically correct for Redis storage. The concern raised in HIGH-1 is about cross-system consistency, not about the compression itself being wrong.

3. **pgvector over dedicated vector database** (`15-semantic-caching-analysis.md`, Section 8): The recommendation to use pgvector on existing RDS Aurora rather than introducing Qdrant/Pinecone is sound operational reasoning at the scale described (<10M entries). The alternative evaluation is honest about when to reconsider.

4. **Context-adjusted similarity thresholds** (`15-semantic-caching-analysis.md`, Section 3): The distinction between 0.93 for HR/policy queries and 0.97 for analytical/financial queries reflects real differences in semantic density across query types. This is the correct approach.

5. **SCAN instead of KEYS for invalidation** (`17-multi-tenant-cache-isolation.md`, Section 3): Explicitly recommending `SCAN` over `KEYS` for production Redis pattern matching is correct operational guidance.

6. **Not caching personal queries and real-time queries** (`15-semantic-caching-analysis.md`, Section 3): The explicit exclusion of "personal queries" (queries containing "my," "mine," first-person context) and real-time data queries from semantic caching is the correct design decision and the analysis in Section 3 is sound.

7. **Separate `aihub2:` → `mingai:` namespace migration** (`02-plans/03-caching-implementation-plan.md`, Phase C1): Explicitly calling out the prefix migration as a Phase C1 deliverable prevents the namespace confusion that would arise from running both prefixes in production simultaneously.

8. **Cache state transparency in UX** (`03-user-flows/05-caching-ux-flows.md`): The distinction between "⚡ Fast response", "🟢 Live response", and "🟡 Live data" is a clean, non-technical communication of cache state. The absence of jargon ("Cache hit") is intentionally correct.

9. **Moat assessment honesty** (`02-competitive-analysis.md`, Section 5): The risk table correctly assesses that most individual caching features can be copied within 3-6 months. The claim that the moat is in multi-tenant architecture (6-12 months to copy) is the most defensible part of the competitive analysis. This honest assessment should be the basis for all competitive positioning.

---

## Summary: Overall Assessment

The caching strategy documents represent a comprehensive first-draft architectural analysis with genuine depth in some areas (multi-tenant isolation design, cache type inventory, semantic similarity analysis). The UX flows are better than average — the cache-state indicators are thoughtful and the admin flows are practical.

However, the strategy has five categories of fundamental problems that make it unready for implementation without significant revision:

**First, there are implementation bugs in the code samples themselves.** CRIT-1 (missing `id` in SELECT), CRIT-3 (ON CONFLICT targeting the wrong constraint), and CRIT-5 (hardcoded index name in cleanup SQL) are all bugs that would fail at runtime. Code in architecture documents is reviewed less carefully than production code — but these documents are being used as implementation specifications, and shipping buggy specs produces buggy software.

**Second, the RBAC bypass in semantic cache (CRIT-7) is a design-level security flaw.** A cached response generated from index A + index B can be served to a user who only has access to index A. For a system that claims granular RBAC as a genuine differentiator, this is a fundamental contradiction. It must be resolved at the architecture level before a single line of semantic cache code is written.

**Third, the memory sizing analysis is incomplete.** The per-tenant Redis sizing (CRIT-4, HIGH-6) ignores HNSW index memory requirements and uses a broken quota mechanism. Building a multi-tenant cache without accurate memory modeling will produce unexpected OOM evictions that degrade all tenants simultaneously.

**Fourth, the implementation plan timeline is unrealistic.** The 30-person-day estimate for 10 weeks of work contains a basic arithmetic error (30 ≠ 50) and underestimates Phase C3 complexity by at least 2x. Planning based on these estimates will produce a failed sprint.

**Fifth, the product claims exceed what the competitive evidence supports.** Every differentiation claim about competitors (Glean, Copilot, Guru) is inferred from silence — the fact that competitors do not publicly document their cache architecture does not mean they lack one. The competitive analysis is honest about this internally, but the value-proposition document presents the claims as facts.

The correct order of operations: fix CRIT-7 (RBAC bypass) and CRIT-2 (cache key collision) before any implementation begins. Fix CRIT-1, CRIT-3, CRIT-5 before Phase C3 code is written. Revise the implementation timeline with honest estimates. Conduct actual competitive teardowns before using competitor gap analysis in customer-facing materials.

The underlying direction — multi-tier caching with semantic similarity matching, transparent cost attribution, and configurable freshness policies — is sound and genuinely differentiating if executed correctly. The current documents are not ready to hand to an engineer and say "build this."
