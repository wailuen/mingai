"""
ATA-034: Integration tests for MCPToolResolver Redis caching.

Tier 2: No mocking — requires real PostgreSQL + Redis.
Skip automatically when DATABASE_URL or REDIS_URL is not set.

Tests:
1. Cache miss path: first call queries DB, result cached with 300s TTL
2. Cache hit path: second call within TTL returns cached value (no DB query)
3. Non-existent tool: DB miss → json.dumps(None) cached, function returns None
4. invalidate_mcp_tool_cache: after invalidation, next call hits DB again
5. Redis key format: key matches mingai:{tenant_id}:mcp_tool:{tool_id}

Architecture note:
    Uses asyncio.run() + fresh async engines for DB setup/teardown.
    Resets the Redis pool singleton between runs to avoid event loop conflicts.
"""
import asyncio
import json
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.redis_client as _redis_mod
from app.core.redis_client import get_redis


# ---------------------------------------------------------------------------
# Infrastructure guards
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — skipping MCP resolver integration test")
    return url


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL", "")
    if not url:
        pytest.skip("REDIS_URL not set — skipping MCP resolver integration test")
    return url


def _reset_redis_pool():
    """
    Reset module-level Redis pool singleton so each asyncio.run() gets
    a fresh pool bound to its new event loop.
    """
    _redis_mod._redis_pool = None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _run_sql(sql: str, params: dict = None):
    """Execute SQL against the real DB using a fresh async engine."""
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _create_tenant(tid: str):
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, :plan, :email, 'active')",
        {
            "id": tid,
            "name": f"MCP Resolver Test {tid[:8]}",
            "slug": f"mcp-resolver-{tid[:8]}",
            "plan": "professional",
            "email": f"test-{tid[:8]}@mcp-resolver.test",
        },
    )


async def _cleanup_tenant(tid: str):
    await _run_sql("DELETE FROM mcp_servers WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})


async def _insert_mcp_server(
    tenant_id: str,
    name: str = "Test MCP Server",
    endpoint: str = "https://mcp.example.com",
    status: str = "active",
) -> str:
    server_id = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO mcp_servers (id, tenant_id, name, endpoint, auth_type, status) "
        "VALUES (:id, :tid, :name, :endpoint, 'none', :status)",
        {
            "id": server_id,
            "tid": tenant_id,
            "name": name,
            "endpoint": endpoint,
            "status": status,
        },
    )
    return server_id


async def _call_get_mcp_tool_config(
    tool_id: str, tenant_id: str
) -> tuple[object, object]:
    """
    Call get_mcp_tool_config() with a fresh DB session and real Redis.

    Returns (result, db_execute_call_count).
    Uses a fresh engine to avoid loop conflicts with the module-level engine.
    """
    from app.modules.chat.mcp_resolver import get_mcp_tool_config

    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    redis = get_redis()
    try:
        async with factory() as session:
            result = await get_mcp_tool_config(tool_id, tenant_id, redis, session)
    finally:
        await engine.dispose()
    return result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def mcp_resolver_tenant():
    """
    Provision a real tenant + MCP server once per test class.
    Cleans up after all tests in the class complete.
    """
    _db_url()   # trigger skip if not configured
    _redis_url()  # trigger skip if not configured

    tid = str(uuid.uuid4())
    asyncio.run(_create_tenant(tid))
    yield tid
    _reset_redis_pool()
    asyncio.run(_cleanup_tenant(tid))


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


class TestMCPResolverIntegration:
    """
    Integration tests for get_mcp_tool_config() and invalidate_mcp_tool_cache().
    Requires real PostgreSQL and real Redis — see module docstring.
    """

    def test_cache_miss_queries_db_and_populates_cache(self, mcp_resolver_tenant):
        """
        First call: cache miss → DB queried → result stored in Redis with 300s TTL.
        The key mingai:{tenant_id}:mcp_tool:{tool_id} must exist after the call.
        """
        tenant_id = mcp_resolver_tenant

        async def _run():
            _reset_redis_pool()
            tool_id = await _insert_mcp_server(tenant_id, name="DB Query Server")
            cache_key = f"mingai:{tenant_id}:mcp_tool:{tool_id}"
            redis = get_redis()

            # Ensure clean state
            await redis.delete(cache_key)

            result = await _call_get_mcp_tool_config(tool_id, tenant_id)

            # Correct result returned
            assert result is not None
            assert result["id"] == tool_id
            assert result["name"] == "DB Query Server"
            assert result["endpoint"] == "https://mcp.example.com"
            assert result["auth_type"] == "none"

            # Cache key must now exist
            cached_raw = await redis.get(cache_key)
            assert cached_raw is not None, f"Cache key {cache_key} should exist after call"

            # TTL must be close to 300
            ttl = await redis.ttl(cache_key)
            assert 270 <= ttl <= 300, f"Expected TTL ~300s, got {ttl}"

            # Cached data matches result
            cached = json.loads(cached_raw)
            assert cached["id"] == tool_id
            assert cached["name"] == "DB Query Server"

        asyncio.run(_run())

    def test_cache_hit_returns_cached_value(self, mcp_resolver_tenant):
        """
        Second call within TTL returns cached value.
        Verified by placing synthetic data in Redis before the call — if the
        function returns the synthetic data, the DB was not consulted.
        """
        tenant_id = mcp_resolver_tenant

        async def _run():
            _reset_redis_pool()
            tool_id = str(uuid.uuid4())  # Does not need to exist in DB
            cache_key = f"mingai:{tenant_id}:mcp_tool:{tool_id}"
            redis = get_redis()

            synthetic = {
                "id": tool_id,
                "name": "CACHED_ONLY",
                "endpoint": "https://cache-only.example.com",
                "auth_type": "none",
                "auth_config": None,
            }
            await redis.setex(cache_key, 300, json.dumps(synthetic))

            result = await _call_get_mcp_tool_config(tool_id, tenant_id)

            assert result is not None
            assert result["name"] == "CACHED_ONLY", (
                "Expected cache hit to return synthetic data — DB was queried instead"
            )
            assert result["endpoint"] == "https://cache-only.example.com"

            # Cleanup
            await redis.delete(cache_key)

        asyncio.run(_run())

    def test_non_existent_tool_caches_none_sentinel(self, mcp_resolver_tenant):
        """
        When the tool_id does not exist in DB, None is returned AND
        json.dumps(None) is written to Redis to prevent repeated DB queries.
        """
        tenant_id = mcp_resolver_tenant

        async def _run():
            _reset_redis_pool()
            bogus_tool_id = str(uuid.uuid4())
            cache_key = f"mingai:{tenant_id}:mcp_tool:{bogus_tool_id}"
            redis = get_redis()

            # Ensure clean state
            await redis.delete(cache_key)

            result = await _call_get_mcp_tool_config(bogus_tool_id, tenant_id)

            assert result is None, "Non-existent tool should return None"

            # Redis key must exist with json.dumps(None)
            cached_raw = await redis.get(cache_key)
            assert cached_raw is not None, (
                "None sentinel should be cached to prevent repeated DB queries"
            )
            assert json.loads(cached_raw) is None, (
                f"Cached value should be JSON null, got {cached_raw!r}"
            )

            # Cleanup
            await redis.delete(cache_key)

        asyncio.run(_run())

    def test_invalidate_clears_cache_and_next_call_hits_db(self, mcp_resolver_tenant):
        """
        After invalidate_mcp_tool_cache(), the cache key is deleted and
        the next call to get_mcp_tool_config() queries the DB afresh and
        re-populates the cache.
        """
        tenant_id = mcp_resolver_tenant

        async def _run():
            from app.modules.chat.mcp_resolver import invalidate_mcp_tool_cache

            _reset_redis_pool()
            tool_id = await _insert_mcp_server(tenant_id, name="Invalidation Server")
            cache_key = f"mingai:{tenant_id}:mcp_tool:{tool_id}"
            redis = get_redis()

            # Pre-populate cache with stale data
            stale = {"id": tool_id, "name": "STALE", "endpoint": "https://stale.example.com",
                     "auth_type": "none", "auth_config": None}
            await redis.setex(cache_key, 300, json.dumps(stale))
            assert await redis.exists(cache_key), "Pre-condition: cache key must exist"

            # Invalidate
            await invalidate_mcp_tool_cache(tenant_id, tool_id, redis)
            assert not await redis.exists(cache_key), "Cache key must be deleted after invalidation"

            # Next call must hit DB and return fresh data
            result = await _call_get_mcp_tool_config(tool_id, tenant_id)
            assert result is not None
            assert result["name"] == "Invalidation Server", (
                "Expected fresh DB data, got stale cached value"
            )

            # Cache must be repopulated
            cached_raw = await redis.get(cache_key)
            assert cached_raw is not None, "Cache should be repopulated after miss"
            cached = json.loads(cached_raw)
            assert cached["name"] == "Invalidation Server"

        asyncio.run(_run())

    def test_redis_key_format(self, mcp_resolver_tenant):
        """
        Verify the Redis key written by get_mcp_tool_config() matches the
        expected namespace pattern: mingai:{tenant_id}:mcp_tool:{tool_id}.
        """
        tenant_id = mcp_resolver_tenant

        async def _run():
            _reset_redis_pool()
            tool_id = await _insert_mcp_server(tenant_id, name="Key Format Server")
            expected_key = f"mingai:{tenant_id}:mcp_tool:{tool_id}"
            redis = get_redis()

            # Clear any prior cache entry
            await redis.delete(expected_key)

            await _call_get_mcp_tool_config(tool_id, tenant_id)

            # The exact key must exist in Redis
            assert await redis.exists(expected_key), (
                f"Expected key {expected_key!r} to exist in Redis after call"
            )
            assert not await redis.exists(f"mcp_tool:{tool_id}"), (
                "Unscoped key must NOT exist — namespace required"
            )

            # Cleanup
            await redis.delete(expected_key)

        asyncio.run(_run())
