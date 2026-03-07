"""
Integration tests for CacheService with real Redis (Tier 2).

TEST-008: CacheService CRUD operations (6 tests)
TEST-009: Cross-tenant cache key isolation (3 tests)
TEST-010: Cache invalidation pub/sub (3 tests)

NO MOCKING — all tests hit a real Redis instance (REDIS_URL from .env).
"""

import asyncio
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
