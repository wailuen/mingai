"""
Integration tests for CacheService with real Redis (Tier 2).

TEST-008: CacheService CRUD operations (6 tests)
TEST-009: Cross-tenant cache key isolation (3 tests)
TEST-010: Cache invalidation pub/sub (3 tests)

CACHE-019: SemanticCacheService integration tests (6 scenarios):
  1. test_semantic_cache_hit_returns_response
  2. test_semantic_cache_miss_runs_pipeline
  3. test_cross_tenant_isolation
  4. test_version_invalidation_causes_miss
  5. test_threshold_boundary
  6. test_cleanup_removes_expired

NO MOCKING — all tests hit real Redis and PostgreSQL/pgvector instances.
"""

import asyncio
import os
import uuid

import pytest

import app.core.redis_client as redis_client_module
from app.core.cache import (
    VALID_CACHE_TYPES,
    CacheService,
    CacheTypeError,
    publish_invalidation,
    subscribe_invalidation,
)
from app.core.redis_client import build_redis_key, get_redis

# Use a valid cache_type from the allowlist for all tests
CACHE_TYPE = "query_cache"


def _unique_tenant() -> str:
    """Generate a unique tenant_id per test to avoid cross-test key collision."""
    return f"test-tenant-{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
async def _reset_redis_pool():
    """
    Reset the global Redis connection pool before each test.

    Each async test gets its own event loop (pytest-asyncio function scope).
    The global _redis_pool singleton in redis_client binds to the first loop
    that creates it. Without this reset, subsequent tests fail with
    'Future attached to a different loop'.
    """
    redis_client_module._redis_pool = None
    yield
    # Close the pool created during the test and reset for the next test
    if redis_client_module._redis_pool is not None:
        await redis_client_module._redis_pool.aclose()
        redis_client_module._redis_pool = None


@pytest.fixture
async def cache():
    """Provide a CacheService instance."""
    return CacheService()


# =========================================================================
# TEST-008: CacheService CRUD (6 tests)
# =========================================================================


async def test_cache_set_and_get(cache: CacheService):
    """Set a value then get it back — values must match."""
    tenant = _unique_tenant()
    key = "user-profile-42"
    value = {"name": "Alice", "score": 99.5}

    await cache.set(tenant, CACHE_TYPE, key, value, ttl=30)
    result = await cache.get(tenant, CACHE_TYPE, key)

    assert result == value
    assert result["name"] == "Alice"
    assert result["score"] == 99.5

    # Cleanup
    await cache.delete(tenant, CACHE_TYPE, key)


async def test_cache_get_missing_key_returns_none(cache: CacheService):
    """Getting a non-existent key returns None (cache miss)."""
    tenant = _unique_tenant()
    result = await cache.get(tenant, CACHE_TYPE, "nonexistent-key-xyz")

    assert result is None


async def test_cache_delete_removes_key(cache: CacheService):
    """Set a key, delete it, then get returns None."""
    tenant = _unique_tenant()
    key = "to-be-deleted"

    await cache.set(tenant, CACHE_TYPE, key, {"data": True}, ttl=30)

    # Verify it exists first
    assert await cache.get(tenant, CACHE_TYPE, key) is not None

    # Delete and verify it is gone
    await cache.delete(tenant, CACHE_TYPE, key)
    result = await cache.get(tenant, CACHE_TYPE, key)

    assert result is None


async def test_cache_ttl_expires_key(cache: CacheService):
    """Set a key with TTL=1 second, wait 2 seconds, get returns None."""
    tenant = _unique_tenant()
    key = "ttl-test"

    await cache.set(tenant, CACHE_TYPE, key, "ephemeral", ttl=1)

    # Confirm it exists immediately
    assert await cache.get(tenant, CACHE_TYPE, key) == "ephemeral"

    # Wait for TTL to expire
    await asyncio.sleep(2.0)

    result = await cache.get(tenant, CACHE_TYPE, key)
    assert result is None


async def test_cache_get_many_returns_all_keys(cache: CacheService):
    """Set 3 keys individually, get_many returns all 3."""
    tenant = _unique_tenant()
    keys_values = {
        "k1": "value-one",
        "k2": {"nested": True},
        "k3": [1, 2, 3],
    }

    for k, v in keys_values.items():
        await cache.set(tenant, CACHE_TYPE, k, v, ttl=30)

    result = await cache.get_many(tenant, CACHE_TYPE, list(keys_values.keys()))

    assert result == keys_values

    # Cleanup
    for k in keys_values:
        await cache.delete(tenant, CACHE_TYPE, k)


async def test_cache_set_many_writes_all(cache: CacheService):
    """set_many writes 3 keys, each individual get returns the correct value."""
    tenant = _unique_tenant()
    mapping = {
        "sm-a": "alpha",
        "sm-b": 42,
        "sm-c": {"deep": [1, 2]},
    }

    await cache.set_many(tenant, CACHE_TYPE, mapping, ttl=30)

    for k, expected in mapping.items():
        result = await cache.get(tenant, CACHE_TYPE, k)
        assert result == expected, f"Key {k}: expected {expected}, got {result}"

    # Cleanup
    for k in mapping:
        await cache.delete(tenant, CACHE_TYPE, k)


# =========================================================================
# TEST-009: Cross-tenant cache key isolation (3 tests)
# =========================================================================


async def test_tenant_a_key_not_visible_to_tenant_b(cache: CacheService):
    """Tenant A sets a key; tenant B's get for the same logical key returns None."""
    tenant_a = _unique_tenant()
    tenant_b = _unique_tenant()
    key = "shared-logical-key"

    await cache.set(tenant_a, CACHE_TYPE, key, "tenant-a-data", ttl=30)

    result_b = await cache.get(tenant_b, CACHE_TYPE, key)
    assert result_b is None, "Tenant B should not see tenant A's data"

    result_a = await cache.get(tenant_a, CACHE_TYPE, key)
    assert result_a == "tenant-a-data"

    # Cleanup
    await cache.delete(tenant_a, CACHE_TYPE, key)


async def test_tenant_a_delete_does_not_affect_tenant_b(cache: CacheService):
    """Tenant A deletes a key; tenant B's value for the same logical key is unaffected."""
    tenant_a = _unique_tenant()
    tenant_b = _unique_tenant()
    key = "isolation-delete-test"

    await cache.set(tenant_a, CACHE_TYPE, key, "a-value", ttl=30)
    await cache.set(tenant_b, CACHE_TYPE, key, "b-value", ttl=30)

    # Tenant A deletes
    await cache.delete(tenant_a, CACHE_TYPE, key)

    # Tenant B's value is still there
    result_b = await cache.get(tenant_b, CACHE_TYPE, key)
    assert result_b == "b-value", "Tenant B's data must survive tenant A's delete"

    # Tenant A's is gone
    result_a = await cache.get(tenant_a, CACHE_TYPE, key)
    assert result_a is None

    # Cleanup
    await cache.delete(tenant_b, CACHE_TYPE, key)


async def test_invalidate_pattern_scoped_to_tenant(cache: CacheService):
    """invalidate_pattern for tenant A only removes tenant A keys, not tenant B."""
    tenant_a = _unique_tenant()
    tenant_b = _unique_tenant()

    # Set keys for both tenants
    await cache.set(tenant_a, CACHE_TYPE, "pat-1", "a1", ttl=30)
    await cache.set(tenant_a, CACHE_TYPE, "pat-2", "a2", ttl=30)
    await cache.set(tenant_b, CACHE_TYPE, "pat-1", "b1", ttl=30)
    await cache.set(tenant_b, CACHE_TYPE, "pat-2", "b2", ttl=30)

    # Invalidate all of tenant A's query_cache keys
    deleted = await cache.invalidate_pattern(tenant_a, CACHE_TYPE, "*")
    assert deleted == 2

    # Tenant A keys are gone
    assert await cache.get(tenant_a, CACHE_TYPE, "pat-1") is None
    assert await cache.get(tenant_a, CACHE_TYPE, "pat-2") is None

    # Tenant B keys are still present
    assert await cache.get(tenant_b, CACHE_TYPE, "pat-1") == "b1"
    assert await cache.get(tenant_b, CACHE_TYPE, "pat-2") == "b2"

    # Cleanup
    await cache.delete(tenant_b, CACHE_TYPE, "pat-1")
    await cache.delete(tenant_b, CACHE_TYPE, "pat-2")


# =========================================================================
# TEST-010: Cache invalidation pub/sub (3 tests)
# =========================================================================


async def test_publish_invalidation_sends_message():
    """publish_invalidation publishes a message to the invalidation channel."""
    tenant = _unique_tenant()

    # Subscribe first to verify the message arrives
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe("mingai:cache_invalidation")

    # Consume the subscription confirmation message
    msg = await pubsub.get_message(timeout=2.0)
    assert msg is not None and msg["type"] == "subscribe"

    # Publish
    await publish_invalidation(tenant, CACHE_TYPE, "some-pattern-*")

    # Receive the published message
    msg = await pubsub.get_message(timeout=3.0)
    assert msg is not None, "Expected to receive published invalidation message"
    assert msg["type"] == "message"

    import json

    event = json.loads(msg["data"])
    assert event["tenant_id"] == tenant
    assert event["cache_type"] == CACHE_TYPE
    assert event["pattern"] == "some-pattern-*"
    assert "ts" in event

    await pubsub.unsubscribe("mingai:cache_invalidation")
    await pubsub.aclose()


async def test_subscribe_invalidation_receives_published_message():
    """subscribe_invalidation yields the correct event after publish_invalidation."""
    tenant = _unique_tenant()
    received_events: list[dict] = []

    async def subscriber_task():
        async for event in subscribe_invalidation():
            received_events.append(event)
            break  # Only need the first event

    # Start subscriber in background
    task = asyncio.create_task(subscriber_task())

    # Give the subscriber time to connect and subscribe
    await asyncio.sleep(0.5)

    # Publish an invalidation event
    await publish_invalidation(tenant, CACHE_TYPE, "sub-test-*")

    # Wait for the subscriber to receive (with timeout)
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except asyncio.TimeoutError:
        task.cancel()
        pytest.fail("Subscriber did not receive the message within 5 seconds")

    assert len(received_events) == 1
    event = received_events[0]
    assert event["tenant_id"] == tenant
    assert event["cache_type"] == CACHE_TYPE
    assert event["pattern"] == "sub-test-*"


async def test_invalid_cache_type_not_forwarded():
    """Publishing with invalid cache_type raises CacheTypeError; subscriber never yields."""
    tenant = _unique_tenant()
    received_events: list[dict] = []

    async def subscriber_task():
        async for event in subscribe_invalidation():
            received_events.append(event)
            break

    # Start subscriber
    task = asyncio.create_task(subscriber_task())
    await asyncio.sleep(0.5)

    # Attempt to publish with an invalid cache_type — should raise
    with pytest.raises(CacheTypeError):
        await publish_invalidation(tenant, "totally_bogus_type", "*")

    # Also manually publish a raw message with invalid cache_type to the channel
    # to verify the subscriber filters it out
    import json
    import time

    redis = get_redis()
    bad_message = json.dumps(
        {
            "tenant_id": tenant,
            "cache_type": "totally_bogus_type",
            "pattern": "*",
            "ts": time.time(),
        }
    )
    await redis.publish("mingai:cache_invalidation", bad_message)

    # Give subscriber a moment to (not) process it
    await asyncio.sleep(1.0)

    # Subscriber should have filtered the invalid cache_type
    assert (
        len(received_events) == 0
    ), "Subscriber should not yield events with invalid cache_type"

    # Clean up the subscriber task
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# =========================================================================
# CACHE-019: SemanticCacheService integration tests (6 scenarios)
# =========================================================================
#
# These tests use asyncio.run() (synchronous test methods inside class bodies)
# to match the pattern established in test_semantic_cache.py. This avoids
# event loop conflicts with the module-level SQLAlchemy engine.
# =========================================================================


def _run_sync(coro):
    """
    Run an async coroutine synchronously for use in sync test methods.

    After running the coroutine, disposes the SQLAlchemy engine's connection
    pool so that asyncpg connections from this event loop are not held open
    when the next test creates a new event loop. Without this, the module-level
    engine's asyncpg connections straddle two event loops, causing the
    'another operation in progress' InterfaceError on subsequent tests.

    This matches the pattern used by app/main.py lifespan shutdown.
    """

    async def _run_and_dispose():
        # Dispose engine BEFORE running coro so any asyncpg connections left
        # open by previous asyncio.run() calls (e.g. test_semantic_cache.py)
        # do not straddle event loops and cause InterfaceError / _cancel warnings.
        from app.core.session import engine as _engine

        await _engine.dispose()

        result = await coro
        # Dispose again AFTER so connections created during this run are
        # released before the next test's event loop starts.
        await _engine.dispose()
        # Also close the global Redis pool so _reset_redis_pool teardown finds
        # nothing to close — prevents 'Event loop is closed' RuntimeError
        # when _reset_redis_pool runs aclose() in a different event loop.
        import app.core.redis_client as _rc

        if _rc._redis_pool is not None:
            try:
                await _rc._redis_pool.aclose()
            except Exception:
                pass
            _rc._redis_pool = None
        return result

    return asyncio.run(_run_and_dispose())


def _make_embedding_1536(seed: float = 0.1) -> list[float]:
    """
    Generate a deterministic 1536-dimensional embedding vector.

    Must be exactly 1536 dimensions to match the pgvector VECTOR(1536) column.
    """
    return [seed + (i * 0.0001) for i in range(1536)]


def _make_cacheable_response(
    answer: str = "cached answer",
) -> "CacheableResponse":  # noqa: F821
    """Build a CacheableResponse for semantic cache tests."""
    from app.modules.chat.response_models import CacheableResponse, Source

    return CacheableResponse(
        sources=[
            Source(
                document_id="doc-cache019-1",
                chunk_text="CACHE-019 integration test chunk.",
                score=0.95,
                document_name="CACHE-019 Test Doc",
                url="https://example.com/cache019",
            )
        ],
        raw_answer=answer,
        confidence=0.88,
        model="test-model",
        latency_ms=250,
    )


# ---------------------------------------------------------------------------
# CACHE-019 Scenario 1: Semantic cache hit returns response
# ---------------------------------------------------------------------------


class TestCache019SemanticCacheHit:
    """Store a response, lookup with same embedding → cache hit."""

    def test_semantic_cache_hit_returns_response(self):
        if not os.environ.get("REDIS_URL") or not os.environ.get("DATABASE_URL"):
            pytest.skip("REDIS_URL or DATABASE_URL not configured")

        from app.core.cache.semantic_cache_service import SemanticCacheService

        svc = SemanticCacheService()
        tenant = str(uuid.uuid4())
        emb = _make_embedding_1536(seed=0.2)
        resp = _make_cacheable_response("CACHE-019 cache hit answer")

        async def _flow():
            await svc.store(
                tenant_id=tenant,
                query_text="cache019 hit test query",
                query_embedding=emb,
                response=resp,
                ttl_seconds=3600,
            )
            await asyncio.sleep(0.6)

            result = await svc.lookup(
                tenant_id=tenant,
                query_embedding=emb,
                threshold=0.0,
            )
            return result

        result = _run_sync(_flow())
        assert result is not None, "Expected semantic cache hit but got None"
        assert result.response.raw_answer == "CACHE-019 cache hit answer"
        assert result.similarity >= 0.0
        assert result.age_seconds >= 0


# ---------------------------------------------------------------------------
# CACHE-019 Scenario 2: Semantic cache miss when no entry stored
# ---------------------------------------------------------------------------


class TestCache019SemanticCacheMiss:
    """Fresh tenant with no stored entries — lookup must return None."""

    def test_semantic_cache_miss_runs_pipeline(self):
        if not os.environ.get("REDIS_URL") or not os.environ.get("DATABASE_URL"):
            pytest.skip("REDIS_URL or DATABASE_URL not configured")

        from app.core.cache.semantic_cache_service import SemanticCacheService

        svc = SemanticCacheService()
        fresh_tenant = str(uuid.uuid4())
        emb = _make_embedding_1536(seed=0.7)

        result = _run_sync(
            svc.lookup(
                tenant_id=fresh_tenant,
                query_embedding=emb,
                threshold=0.0,
            )
        )
        assert result is None, "Expected None on empty cache but got a result"


# ---------------------------------------------------------------------------
# CACHE-019 Scenario 3: Cross-tenant isolation
# ---------------------------------------------------------------------------


class TestCache019CrossTenantIsolation:
    """Store entry for tenant A; lookup as tenant B must return None."""

    def test_cross_tenant_isolation(self):
        if not os.environ.get("REDIS_URL") or not os.environ.get("DATABASE_URL"):
            pytest.skip("REDIS_URL or DATABASE_URL not configured")

        from app.core.cache.semantic_cache_service import SemanticCacheService

        svc = SemanticCacheService()
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        emb = _make_embedding_1536(seed=0.33)
        resp = _make_cacheable_response("CACHE-019 cross-tenant isolation answer")

        async def _flow():
            await svc.store(
                tenant_id=tenant_a,
                query_text="cache019 cross-tenant isolation query",
                query_embedding=emb,
                response=resp,
                ttl_seconds=3600,
            )
            await asyncio.sleep(0.6)

            result = await svc.lookup(
                tenant_id=tenant_b,
                query_embedding=emb,
                threshold=0.0,
            )
            return result

        result = _run_sync(_flow())
        assert (
            result is None
        ), "Tenant B must not see tenant A's semantic cache entry — RLS isolation violated"


# ---------------------------------------------------------------------------
# CACHE-019 Scenario 4: Version invalidation causes miss
# ---------------------------------------------------------------------------


class TestCache019VersionInvalidation:
    """Store with version N, increment version → lookup misses."""

    def test_version_invalidation_causes_miss(self):
        if not os.environ.get("REDIS_URL") or not os.environ.get("DATABASE_URL"):
            pytest.skip("REDIS_URL or DATABASE_URL not configured")

        from app.core.cache.semantic_cache_service import SemanticCacheService
        from app.core.cache_utils import increment_index_version

        svc = SemanticCacheService()
        tenant = str(uuid.uuid4())
        emb = _make_embedding_1536(seed=0.55)
        resp = _make_cacheable_response("CACHE-019 version invalidation answer")

        async def _flow():
            await svc.store(
                tenant_id=tenant,
                query_text="cache019 version invalidation query",
                query_embedding=emb,
                response=resp,
                ttl_seconds=3600,
            )
            await asyncio.sleep(0.6)

            # Confirm it is a hit before invalidation
            hit = await svc.lookup(
                tenant_id=tenant,
                query_embedding=emb,
                threshold=0.0,
            )

            # Increment global index version (simulate document update)
            await increment_index_version(tenant, "global")

            # Stored entry version_tag is now stale → should miss
            miss = await svc.lookup(
                tenant_id=tenant,
                query_embedding=emb,
                threshold=0.0,
            )
            return hit, miss

        hit, miss = _run_sync(_flow())
        assert hit is not None, "Expected cache hit before version increment"
        assert miss is None, "Expected cache miss after version increment"


# ---------------------------------------------------------------------------
# CACHE-019 Scenario 5: Threshold boundary
# ---------------------------------------------------------------------------


class TestCache019ThresholdBoundary:
    """
    Validate cosine similarity threshold enforcement.

    A very close vector (near-identical) hits above threshold=0.95.
    An orthogonal vector (low cosine similarity) misses above threshold=0.95.
    """

    def test_threshold_boundary_above_hits_below_misses(self):
        if not os.environ.get("REDIS_URL") or not os.environ.get("DATABASE_URL"):
            pytest.skip("REDIS_URL or DATABASE_URL not configured")

        from app.core.cache.semantic_cache_service import SemanticCacheService

        svc = SemanticCacheService()
        tenant = str(uuid.uuid4())

        # Base vector: uniform 0.1 values
        base_emb = [0.1] * 1536
        resp = _make_cacheable_response("CACHE-019 threshold boundary answer")

        # Near-identical vector: tiny perturbation, cosine similarity ≈ 1.0
        near_emb = [0.1 + (i * 0.000001) for i in range(1536)]

        # Orthogonal-ish vector: alternating +/- values, low cosine similarity
        # with a uniform-positive base vector
        far_emb = [0.1 if i % 2 == 0 else -0.1 for i in range(1536)]

        async def _flow():
            await svc.store(
                tenant_id=tenant,
                query_text="cache019 threshold boundary query",
                query_embedding=base_emb,
                response=resp,
                ttl_seconds=3600,
            )
            await asyncio.sleep(0.6)

            # Near-identical should hit at threshold=0.95
            hit = await svc.lookup(
                tenant_id=tenant,
                query_embedding=near_emb,
                threshold=0.95,
            )

            # Orthogonal should miss at threshold=0.95
            miss = await svc.lookup(
                tenant_id=tenant,
                query_embedding=far_emb,
                threshold=0.95,
            )
            return hit, miss

        hit, miss = _run_sync(_flow())
        assert hit is not None, "Near-identical vector should hit at threshold=0.95"
        assert miss is None, "Orthogonal vector should miss at threshold=0.95"


# ---------------------------------------------------------------------------
# CACHE-019 Scenario 6: Cleanup removes expired entries
# ---------------------------------------------------------------------------


class TestCache019CleanupRemovesExpired:
    """Insert an already-expired entry, run the cleanup job → row deleted."""

    def test_cleanup_removes_expired(self):
        if not os.environ.get("REDIS_URL") or not os.environ.get("DATABASE_URL"):
            pytest.skip("REDIS_URL or DATABASE_URL not configured")

        tenant = str(uuid.uuid4())

        async def _flow():
            import json as _json
            import uuid as _uuid

            from sqlalchemy import text
            from app.core.session import async_session_factory
            from app.core.cache.cleanup_job import _run_cleanup

            entry_id = str(_uuid.uuid4())
            emb_literal = "[" + ",".join(["0.1"] * 1536) + "]"
            response_json = _json.dumps(
                {
                    "sources": [],
                    "raw_answer": "CACHE-019 expired entry",
                    "confidence": 0.5,
                    "model": "test",
                    "latency_ms": 0,
                }
            )

            # Insert a row with expires_at already in the past
            async with async_session_factory() as session:
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tenant},
                )
                await session.execute(
                    text(
                        "INSERT INTO semantic_cache "
                        "(id, tenant_id, query_embedding, query_text, response_text, "
                        " similarity_threshold, hit_count, created_at, expires_at, version_tag) "
                        "VALUES (:id, :tid, CAST(:emb AS vector), :query_text, :response_text, "
                        " 0.92, 0, NOW() - INTERVAL '2 hours', "
                        " NOW() - INTERVAL '1 hour', 0)"
                    ),
                    {
                        "id": entry_id,
                        "tid": tenant,
                        "emb": emb_literal,
                        "query_text": "cache019 expired entry query",
                        "response_text": response_json,
                    },
                )
                await session.commit()

            # Confirm row exists before cleanup
            async with async_session_factory() as session:
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tenant},
                )
                count_result = await session.execute(
                    text(
                        "SELECT COUNT(*) FROM semantic_cache "
                        "WHERE id = :id AND tenant_id = :tid"
                    ),
                    {"id": entry_id, "tid": tenant},
                )
                before_count = count_result.scalar() or 0

            # Run cleanup job
            await _run_cleanup()

            # Confirm expired row is gone
            async with async_session_factory() as session:
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tenant},
                )
                count_result = await session.execute(
                    text(
                        "SELECT COUNT(*) FROM semantic_cache "
                        "WHERE id = :id AND tenant_id = :tid"
                    ),
                    {"id": entry_id, "tid": tenant},
                )
                after_count = count_result.scalar() or 0

            return before_count, after_count

        before, after = _run_sync(_flow())
        assert before == 1, f"Expected 1 expired row before cleanup, got {before}"
        assert after == 0, f"Expected 0 rows after cleanup, got {after}"
