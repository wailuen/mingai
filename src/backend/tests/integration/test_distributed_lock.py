"""
Integration tests for DistributedJobLock with real Redis (Tier 2).

SCHED-034: DistributedJobLock correctness under concurrent access.

Tests:
1. test_two_concurrent_coroutines_only_one_acquires
2. test_second_coroutine_acquires_after_ttl_expiry
3. test_heartbeat_prevents_ttl_expiry
4. test_release_clears_key
5. test_skipped_lock_does_not_write_key

NO MOCKING — all tests use real Redis via get_redis().
"""

import asyncio
from uuid import uuid4

import pytest

import app.core.redis_client as redis_client_module
from app.core.redis_client import get_redis
from app.core.scheduler.job_lock import DistributedJobLock, _LOCK_KEY_PREFIX


def _unique_job_name() -> str:
    """Generate a unique job name per test invocation to prevent key collisions."""
    return f"test_{uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
async def _reset_redis_pool():
    """
    Reset the global Redis connection pool before and after each test.

    pytest-asyncio in auto mode assigns each test its own event loop at
    function scope. The global _redis_pool singleton in redis_client binds to
    the first loop that creates it. Without this reset, later tests fail with
    'Future attached to a different loop'.
    """
    redis_client_module._redis_pool = None
    yield
    if redis_client_module._redis_pool is not None:
        await redis_client_module._redis_pool.aclose()
        redis_client_module._redis_pool = None


# =============================================================================
# Test 1 — mutual exclusion: exactly one of two concurrent acquirers wins
# =============================================================================


async def test_two_concurrent_coroutines_only_one_acquires():
    """
    Two coroutines race to acquire the same lock simultaneously.
    Exactly one must succeed (acquired=True); the other must be skipped
    (acquired=False).
    """
    job_name = _unique_job_name()
    lock_key = f"{_LOCK_KEY_PREFIX}{job_name}"
    redis = get_redis()

    results: list[bool] = []

    async def try_acquire() -> None:
        async with DistributedJobLock(job_name, ttl=30) as acquired:
            results.append(acquired)
            if acquired:
                # Hold briefly so the race is deterministic
                await asyncio.sleep(0.1)

    try:
        await asyncio.gather(try_acquire(), try_acquire())

        assert len(results) == 2, "Both coroutines must complete"
        acquired_count = sum(1 for r in results if r is True)
        skipped_count = sum(1 for r in results if r is False)
        assert acquired_count == 1, (
            f"Exactly one coroutine should have acquired the lock, got {acquired_count}"
        )
        assert skipped_count == 1, (
            f"Exactly one coroutine should have been skipped, got {skipped_count}"
        )
    finally:
        await redis.delete(lock_key)


# =============================================================================
# Test 2 — TTL expiry: a second acquire succeeds after the first lock expires
# =============================================================================


async def test_second_coroutine_acquires_after_ttl_expiry():
    """
    Acquire a lock with TTL=2s, then wait 3s for it to expire naturally.
    A subsequent acquire attempt on the same key must succeed (acquired=True).
    """
    job_name = _unique_job_name()
    lock_key = f"{_LOCK_KEY_PREFIX}{job_name}"
    redis = get_redis()

    try:
        # First acquire — exits immediately, but the key lives for ttl=2s
        # because the Lua release runs at context exit (it deletes the key).
        # To test TTL expiry we need the key to persist, so we acquire and
        # then delete the key manually to simulate the lock BEING held without
        # a Lua release.  Instead, we simply set the key directly with a 2s TTL
        # to simulate a lock that was acquired and never released (crashed pod).
        import uuid as _uuid_mod

        orphan_token = str(_uuid_mod.uuid4())
        await redis.set(lock_key, orphan_token, nx=True, ex=2)

        # Immediately, a new acquire attempt should fail (key exists).
        second_result: bool | None = None

        async with DistributedJobLock(job_name, ttl=10) as acquired:
            second_result = acquired

        assert second_result is False, (
            "Lock should still be held by the orphan token immediately after set"
        )

        # Wait for the orphan lock to expire (TTL=2s + 1s buffer).
        await asyncio.sleep(3)

        # Now a third acquire attempt should succeed.
        third_result: bool | None = None

        async with DistributedJobLock(job_name, ttl=10) as acquired:
            third_result = acquired

        assert third_result is True, (
            "Lock should be acquirable after the original TTL has expired"
        )
    finally:
        await redis.delete(lock_key)


# =============================================================================
# Test 3 — heartbeat keeps the lock alive beyond one TTL interval
# =============================================================================


async def test_heartbeat_prevents_ttl_expiry():
    """
    Acquire a lock with TTL=4s. The heartbeat fires every TTL//2 = 2s and
    renews EXPIRE. Hold the lock for 6 seconds. Assert the key still exists
    in Redis before the context exits (i.e. heartbeat extended the TTL).
    """
    job_name = _unique_job_name()
    lock_key = f"{_LOCK_KEY_PREFIX}{job_name}"
    redis = get_redis()

    try:
        key_exists_at_6s: bool = False

        async with DistributedJobLock(job_name, ttl=4) as acquired:
            assert acquired is True, "Lock must be acquired for this test to be valid"

            # Wait 6 seconds — without a heartbeat the key would expire after 4s.
            await asyncio.sleep(6)

            # Check while still inside the context (heartbeat still running).
            key_exists_at_6s = await redis.exists(lock_key) == 1

        assert key_exists_at_6s is True, (
            "Lock key should still exist at 6s because the heartbeat renewed the TTL"
        )
    finally:
        await redis.delete(lock_key)


# =============================================================================
# Test 4 — release: context exit atomically deletes the lock key
# =============================================================================


async def test_release_clears_key():
    """
    After the DistributedJobLock context manager exits normally,
    the lock key must no longer exist in Redis.
    """
    job_name = _unique_job_name()
    lock_key = f"{_LOCK_KEY_PREFIX}{job_name}"
    redis = get_redis()

    try:
        async with DistributedJobLock(job_name, ttl=30) as acquired:
            assert acquired is True, "Lock must be acquired for this test to be valid"
            key_exists_inside = await redis.exists(lock_key) == 1
            assert key_exists_inside, "Key must exist while lock is held"

        # Context has exited — Lua script should have deleted the key.
        key_exists_after = await redis.exists(lock_key) == 1
        assert key_exists_after is False, (
            "Lock key must be deleted after the context manager exits"
        )
    finally:
        # Defensive cleanup in case the assertion above fires before release.
        await redis.delete(lock_key)


# =============================================================================
# Test 5 — skipped acquirer writes no extra key
# =============================================================================


async def test_skipped_lock_does_not_write_key():
    """
    When a second coroutine fails to acquire the lock, it must not write any
    additional Redis key. The only key present should be the one from the
    first (successful) acquirer.
    """
    job_name = _unique_job_name()
    lock_key = f"{_LOCK_KEY_PREFIX}{job_name}"
    redis = get_redis()

    try:
        # Acquire the lock and hold it.
        first_acquired: bool = False
        second_acquired: bool | None = None
        key_count_while_held: int = 0

        async with DistributedJobLock(job_name, ttl=30) as acquired:
            first_acquired = acquired
            assert first_acquired is True

            # Second acquire attempt while first is still holding.
            async with DistributedJobLock(job_name, ttl=30) as acquired2:
                second_acquired = acquired2

            # Count keys matching this lock prefix — should be exactly 1.
            # KEYS is O(N) but acceptable in integration tests against a
            # dedicated test Redis instance.
            matching_keys = await redis.keys(f"{_LOCK_KEY_PREFIX}{job_name}*")
            key_count_while_held = len(matching_keys)

        assert second_acquired is False, (
            "Second coroutine must not acquire the lock while first holds it"
        )
        assert key_count_while_held == 1, (
            f"Exactly one lock key should exist, found {key_count_while_held}: "
            f"{matching_keys if key_count_while_held != 1 else ''}"
        )
    finally:
        await redis.delete(lock_key)
