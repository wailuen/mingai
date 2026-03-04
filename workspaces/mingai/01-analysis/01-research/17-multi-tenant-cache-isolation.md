# Multi-Tenant Cache Isolation: Security and Architecture

**Date**: March 4, 2026
**Focus**: Ensuring cache isolation in multi-tenant deployment
**Status**: Research Phase — Critical for Phase 1

---

## 1. The Isolation Imperative

In a multi-tenant system, a cache failure that leaks data across tenant boundaries is a **catastrophic security incident** — far worse than a cache miss. Every caching decision must be evaluated against two failure modes:

1. **Confidentiality breach**: Tenant A reads cached data belonging to Tenant B
2. **Integrity breach**: Tenant B's cache write corrupts Tenant A's data

**Zero tolerance**: Any caching design that allows either failure mode is unacceptable, regardless of performance benefit.

---

## 2. Key Namespace Design

### Structure

```
mingai:{tenant_id}:{cache_type}:{discriminator}
```

**Components**:

- `mingai:` — global prefix for all mingai Redis keys (namespace isolation from other apps)
- `{tenant_id}` — UUID of the tenant (from JWT, never from user input)
- `{cache_type}` — category of cached data (fixed vocabulary)
- `{discriminator}` — specific cache entry identifier

**Cache type vocabulary** (fixed list, prevents injection):

```python
VALID_CACHE_TYPES = frozenset({
    "auth",    # JWT validation results
    "ctx",     # User context and permissions
    "conv",    # Conversation history
    "intent",  # Intent detection results
    "emb",     # Query embeddings
    "search",  # Search results
    "idx",     # Index metadata
    "glossary", # Glossary terms
    "llm",     # LLM response cache
    "mcp",     # MCP tool responses
    "rate",    # Rate limiting counters
    "version", # Index version counters
})
```

### Validation Layer

```python
import re
import uuid

TENANT_ID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
)

def build_cache_key(tenant_id: str, cache_type: str, *parts: str) -> str:
    """
    Build a validated cache key.
    Raises ValueError if inputs fail validation.
    """
    # Validate tenant_id is a real UUID (prevents injection)
    if not TENANT_ID_PATTERN.match(tenant_id):
        raise ValueError(f"Invalid tenant_id format: {tenant_id!r}")

    # Validate cache_type is from allowed vocabulary
    if cache_type not in VALID_CACHE_TYPES:
        raise ValueError(f"Invalid cache_type: {cache_type!r}")

    # Sanitize parts: only alphanumeric, hyphens, underscores, colons
    sanitized_parts = []
    for part in parts:
        if not re.match(r'^[a-zA-Z0-9\-_:\.]+$', str(part)):
            raise ValueError(f"Invalid cache key component: {part!r}")
        sanitized_parts.append(str(part))

    return f"mingai:{tenant_id}:{cache_type}:{':'.join(sanitized_parts)}"
```

### Source of Truth: tenant_id from JWT

The `tenant_id` used in cache keys MUST come from the validated JWT, never from:

- Request body parameters
- URL path parameters
- Query string parameters
- HTTP headers (other than Authorization)

```python
# CORRECT: tenant_id from decoded, validated JWT
@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    user: AuthenticatedUser = Depends(get_current_user)  # JWT-validated
):
    tenant_id = user.tenant_id  # From JWT — trusted
    cache_key = build_cache_key(tenant_id, "intent", sha256(request.query))
    ...

# WRONG: tenant_id from request body
@router.post("/chat/stream")  # DO NOT DO THIS
async def chat_stream_wrong(
    request: ChatRequestWithTenantId,  # Has tenant_id field — DANGEROUS
):
    tenant_id = request.tenant_id  # User-controlled — NEVER TRUST
    cache_key = f"mingai:{tenant_id}:..."  # Potential injection
```

---

## 3. Cross-Tenant Query Prevention

### Redis Wildcard Operations

Redis `KEYS *` and `SCAN` operations are dangerous in multi-tenant contexts. Strict controls:

```python
# ALLOWED: Pattern scoped to specific tenant
async def invalidate_tenant_search_cache(tenant_id: str, index_id: str):
    """Safely invalidate search cache for one index within one tenant."""
    # Validate before use
    validated_key_prefix = build_cache_key(tenant_id, "search", index_id)

    # Use SCAN (non-blocking) with strict prefix
    cursor = 0
    while True:
        cursor, keys = await redis.scan(
            cursor=cursor,
            match=f"{validated_key_prefix}:*",
            count=100
        )
        if keys:
            await redis.delete(*keys)
        if cursor == 0:
            break

# FORBIDDEN: Cross-tenant wildcard
async def bad_invalidate():  # DO NOT DO THIS
    keys = await redis.keys("mingai:*:search:hr-policies:*")  # Gets ALL tenants!
    await redis.delete(*keys)  # DATA BREACH
```

### Database Query Isolation

All database queries that involve cached data must include tenant_id as a filter:

```python
# CORRECT: All queries scoped to tenant
async def get_user_context(tenant_id: str, user_id: str):
    return await db.fetchrow(
        "SELECT * FROM users WHERE tenant_id = $1 AND id = $2",
        tenant_id, user_id
    )

# Row-Level Security (PostgreSQL RLS) as second defense
# Even if tenant_id is missing from query, RLS enforces it:
# POLICY: USING (tenant_id = current_setting('app.tenant_id')::uuid)
```

---

## 4. Tenant Cache Sizing and Fair-Use

### The Noisy Neighbor Problem

In a shared Redis instance, a large tenant running bulk operations could:

- Flood the cache with embeddings, evicting small tenants' hot data
- Trigger excessive LRU evictions for other tenants
- Increase Redis memory pressure globally

**Solutions by tenant tier**:

| Plan         | Cache Isolation    | Memory Limit          | Eviction Priority |
| ------------ | ------------------ | --------------------- | ----------------- |
| Starter      | Shared Redis DB    | Soft limit (advisory) | Equal             |
| Professional | Shared Redis DB    | Hard limit via Lua    | Elevated          |
| Enterprise   | Dedicated Redis DB | None (dedicated)      | N/A               |

### Memory Quotas via Lua Script

```lua
-- Redis Lua script: set a value only if tenant is within memory quota
local tenant_key = KEYS[1]
local value = ARGV[1]
local ttl = tonumber(ARGV[2])
local quota_key = "mingai:" .. ARGV[3] .. ":mem_usage"
local max_bytes = tonumber(ARGV[4])

-- Get current tenant memory usage (approximation)
local current = tonumber(redis.call("GET", quota_key) or "0")
local value_size = #value

if current + value_size > max_bytes then
    return redis.error_reply("QUOTA_EXCEEDED")
end

-- Store value and update quota
redis.call("SETEX", tenant_key, ttl, value)
redis.call("INCRBY", quota_key, value_size)
redis.call("EXPIRE", quota_key, 3600)  -- Reset quota tracking hourly

return "OK"
```

### Redis Database Separation (Enterprise Tier)

Enterprise tenants get a dedicated Redis database (logical separation within same instance):

- Redis supports up to 16 databases (DB 0-15) per instance
- Alternatively: dedicated Redis instance per enterprise tenant
- Key prefix still maintained for code consistency

```python
# Connection pool with database selection
def get_redis_connection(tenant_id: str) -> Redis:
    tenant_config = tenant_tier_configs[tenant_id]
    if tenant_config.plan == "enterprise":
        # Dedicated Redis DB for enterprise tenants
        return Redis(
            host=redis_host,
            port=redis_port,
            db=tenant_config.redis_db_id  # Enterprise-specific DB
        )
    else:
        # Shared DB for starter/professional
        return Redis(host=redis_host, port=redis_port, db=0)
```

---

## 5. Cache Security Attack Vectors

### 5.1 Cache Key Poisoning

**Attack**: Attacker crafts a query that contains a colon-separated tenant_id in the query text, hoping the cache key generation includes the query text directly.

**Example**:

```
Query: "What is the PTO policy? tenant_id:attacker-tenant-uuid"
```

If the cache key were built as:

```python
key = f"mingai:{tenant_id}:cache:{query}"  # VULNERABLE
```

The attacker could craft keys pointing to another tenant's space.

**Mitigation**: Always hash the query before using in cache key:

```python
key = build_cache_key(tenant_id, "intent", sha256(query))  # SAFE
```

### 5.2 Timing Attacks via Cache Hits

**Attack**: An attacker could infer what questions other users in their tenant have asked by observing response timing (cache hit = fast, cache miss = slow).

**Mitigation**:

- Semantic cache entries are shared within a tenant (intentional — users in same tenant see same policies)
- Cross-tenant: cache is fully isolated; no timing leak across tenants
- Within-tenant timing leakage is acceptable: users in same org can see same policies

### 5.3 Cache Flooding (DoS)

**Attack**: Attacker sends many unique queries to fill the Redis cache, evicting legitimate cached data.

**Mitigation**:

- Rate limiting per user (already implemented)
- Memory quotas per tenant (Section 4)
- Semantic deduplication: many unique queries that are semantically similar won't all be cached (cache key = embedding hash, and similar queries map to similar embeddings → cache slot reuse)

### 5.4 Stale Data Elevation

**Attack**: A user's permissions are reduced (role removed). For up to TTL duration, the old cached permission set may still be used.

**Mitigation**:

- Short TTL for permission cache (10 minutes max)
- Redis Pub/Sub for immediate invalidation on role change:

```python
# On role change event:
async def on_user_role_changed(tenant_id: str, user_id: str):
    # Immediately invalidate context cache
    key = build_cache_key(tenant_id, "ctx", user_id)
    await redis.delete(key)

    # Publish to all instances (cross-instance invalidation)
    await redis.publish(
        "mingai:invalidation:auth",
        json.dumps({"type": "user_role_changed", "tenant_id": tenant_id, "user_id": user_id})
    )
```

```python
# All instances subscribe to invalidation channel
async def start_invalidation_listener():
    pubsub = redis.pubsub()
    await pubsub.subscribe("mingai:invalidation:auth")
    async for message in pubsub.listen():
        if message["type"] == "message":
            event = json.loads(message["data"])
            if event["type"] == "user_role_changed":
                # Clear local in-memory LRU cache if used
                local_cache.clear_user(event["user_id"])
```

---

## 6. Audit and Compliance Requirements

### Cache Access Logging

For compliance-regulated tenants (finance, healthcare), cache operations must be auditable:

```python
async def audited_cache_get(
    tenant_id: str,
    cache_type: str,
    key: str,
    user_id: str
) -> Optional[bytes]:
    """Cache get with compliance audit log."""
    result = await redis.get(key)
    hit = result is not None

    # Log for SOC 2 / audit
    if tenant_config.requires_cache_audit:
        await audit_log.record(
            tenant_id=tenant_id,
            event_type="cache_access",
            cache_type=cache_type,
            cache_hit=hit,
            user_id=user_id,
            timestamp=datetime.utcnow()
        )

    return result
```

### Data Residency

For tenants with data residency requirements (EU GDPR, etc.):

- Redis instance must be in the same region as the tenant's primary data
- Cache key namespace must be region-aware: `mingai:{region}:{tenant_id}:...`
- Multi-region deployments: each region has its own Redis; no cross-region cache sharing

---

## 7. Testing Multi-Tenant Cache Isolation

### Required Test Cases

```python
# Test: Tenant A cannot access Tenant B's cache entries
async def test_cross_tenant_isolation():
    tenant_a = "11111111-1111-1111-1111-111111111111"
    tenant_b = "22222222-2222-2222-2222-222222222222"

    # Store data for tenant A
    key_a = build_cache_key(tenant_a, "ctx", "user-123")
    await redis.setex(key_a, 600, json.dumps({"user": "alice", "roles": ["admin"]}))

    # Attempt to access tenant A's data as tenant B
    key_b_attempt = build_cache_key(tenant_b, "ctx", "user-123")
    result = await redis.get(key_b_attempt)

    # Must return None (different key namespace)
    assert result is None, "CRITICAL: Cross-tenant cache isolation violated"

# Test: tenant_id injection via query text is prevented
async def test_cache_key_injection():
    tenant_id = "11111111-1111-1111-1111-111111111111"
    malicious_query = "policy :22222222-2222-2222-2222-222222222222:ctx:victim-user:"

    # Key must be safely constructed regardless of query content
    key = build_cache_key(tenant_id, "intent", sha256(malicious_query))

    # Key must only contain tenant A's ID
    assert "22222222-2222-2222-2222-222222222222" not in key
    assert key.startswith(f"mingai:{tenant_id}:intent:")

# Test: invalidation does not affect other tenants
async def test_invalidation_isolation():
    tenant_a = "11111111-1111-1111-1111-111111111111"
    tenant_b = "22222222-2222-2222-2222-222222222222"

    # Populate caches for both tenants
    key_a = build_cache_key(tenant_a, "search", "hr-policies", "abc123")
    key_b = build_cache_key(tenant_b, "search", "hr-policies", "abc123")
    await redis.setex(key_a, 600, b"tenant_a_data")
    await redis.setex(key_b, 600, b"tenant_b_data")

    # Invalidate tenant A's search cache
    await invalidate_tenant_search_cache(tenant_a, "hr-policies")

    # Tenant A's cache should be gone
    assert await redis.get(key_a) is None

    # Tenant B's cache should be unaffected
    assert await redis.get(key_b) == b"tenant_b_data"
```

---

## 8. Summary: Non-Negotiable Cache Isolation Rules

1. **All cache keys must include tenant_id** as the second component, derived from JWT
2. **tenant_id must be validated** as a UUID before use in cache keys
3. **Cache type must be from a fixed allowlist** to prevent key injection
4. **All components after cache_type must be hashed** if derived from user input
5. **SCAN/KEYS patterns must be scoped** to a single tenant's prefix
6. **Pub/Sub invalidation messages must include tenant_id** and must be validated on receipt
7. **Enterprise tenants must receive** dedicated Redis database or instance
8. **Role changes must immediately invalidate** user context cache via Pub/Sub
9. **Data residency constraints** must be implemented at the Redis layer

---

**Document Version**: 1.0
**Severity**: CRITICAL — data isolation failures are unacceptable
**Depends On**: `14-caching-architecture-overview.md`
