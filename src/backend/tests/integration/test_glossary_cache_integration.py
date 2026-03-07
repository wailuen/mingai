"""
TEST-031: Glossary Redis Cache Integration Tests

Tests GlossaryExpander Redis caching behaviour using real Redis and PostgreSQL.
Tier 2: No mocking — requires running Docker infrastructure (Redis + PostgreSQL).

Architecture note:
    Uses asyncio.run() with fresh async engines for DB setup/teardown,
    matching the pattern from test_glossary_crud.py. GlossaryExpander._get_terms()
    is tested directly with real DB sessions and real Redis.

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_glossary_cache_integration.py -v --timeout=5
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
from app.modules.glossary.expander import GLOSSARY_CACHE_TTL_SECONDS, GlossaryExpander
from app.modules.glossary.routes import _invalidate_glossary_cache


def _reset_redis_pool():
    """
    Reset the module-level Redis pool singleton so that each asyncio.run()
    gets a fresh pool bound to its own event loop.

    This is necessary because asyncio.run() creates a new event loop each
    time, but the singleton pool retains connections from the prior loop,
    causing "Future attached to a different loop" errors.
    """
    _redis_mod._redis_pool = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL", "")
    if not url:
        pytest.skip("REDIS_URL not configured — skipping integration tests")
    return url


async def _run_sql(sql: str, params: dict = None):
    """Execute SQL against real DB using a fresh async engine."""
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _run_sql_fetch(sql: str, params: dict = None) -> list:
    """Execute SQL and return rows."""
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            return result.fetchall()
    finally:
        await engine.dispose()


async def _get_terms_with_fresh_session(tenant_id: str) -> list[dict]:
    """
    Call GlossaryExpander._get_terms() with a real async DB session.

    Creates a fresh engine + session to avoid event loop conflicts
    with the module-level engine in session.py.
    """
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            expander = GlossaryExpander(db=session)
            return await expander._get_terms(tenant_id)
    finally:
        await engine.dispose()


async def _create_tenant(tid: str):
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, :plan, :email, 'active')",
        {
            "id": tid,
            "name": f"Cache Test {tid[:8]}",
            "slug": f"cache-test-{tid[:8]}",
            "plan": "professional",
            "email": f"test-{tid[:8]}@cache-int.test",
        },
    )


async def _cleanup_tenant(tid: str):
    await _run_sql("DELETE FROM glossary_terms WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})


async def _cleanup_redis_key(tenant_id: str):
    cache_key = f"mingai:{tenant_id}:glossary_terms"
    redis = get_redis()
    await redis.delete(cache_key)


async def _insert_glossary_term(
    tenant_id: str, term: str, full_form: str, aliases: list | None = None
):
    term_id = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO glossary_terms (id, tenant_id, term, full_form, aliases) "
        "VALUES (:id, :tenant_id, :term, :full_form, CAST(:aliases AS jsonb))",
        {
            "id": term_id,
            "tenant_id": tenant_id,
            "term": term,
            "full_form": full_form,
            "aliases": json.dumps(aliases or []),
        },
    )
    return term_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def cache_tenant_id():
    """
    Provision a real test tenant once per test class, clean up after.
    Each class gets its own tenant to prevent cross-test interference.
    """
    tid = str(uuid.uuid4())
    asyncio.run(_create_tenant(tid))
    yield tid
    _reset_redis_pool()
    asyncio.run(_cleanup_redis_key(tid))
    _reset_redis_pool()
    asyncio.run(_cleanup_tenant(tid))


# ---------------------------------------------------------------------------
# Tests: Glossary Redis Cache
# ---------------------------------------------------------------------------


class TestGlossaryRedisCache:
    """
    Integration tests for GlossaryExpander Redis caching layer.

    Tests verify cache population, cache hits, invalidation, TTL,
    and empty-list caching — all against real Redis and PostgreSQL.
    """

    def test_glossary_terms_cached_in_redis_after_first_query(self, cache_tenant_id):
        """
        After calling _get_terms(), the cache key mingai:{tenant_id}:glossary_terms
        must exist in Redis with the correct data.
        """
        tenant_id = cache_tenant_id
        cache_key = f"mingai:{tenant_id}:glossary_terms"

        async def _run():
            _reset_redis_pool()
            # Ensure clean state
            redis = get_redis()
            await redis.delete(cache_key)

            # Insert a glossary term into the real DB
            await _insert_glossary_term(
                tenant_id, "HR", "Human Resources", ["human-res"]
            )

            # Call _get_terms — should query DB and populate Redis cache
            terms = await _get_terms_with_fresh_session(tenant_id)

            # Verify terms returned from the call
            assert len(terms) >= 1
            assert any(t["term"] == "HR" for t in terms)

            # Verify the cache key exists in Redis
            cached_raw = await redis.get(cache_key)
            assert (
                cached_raw is not None
            ), f"Cache key {cache_key} should exist in Redis after _get_terms()"

            # Verify cached data matches
            cached_terms = json.loads(cached_raw)
            assert any(t["term"] == "HR" for t in cached_terms)
            assert any(t["full_form"] == "Human Resources" for t in cached_terms)

        asyncio.run(_run())

    def test_glossary_cache_hit_skips_db(self, cache_tenant_id):
        """
        When Redis cache is pre-populated, _get_terms() returns cached data
        without querying the database.

        Verified by placing DIFFERENT data in Redis vs DB — if the result
        matches the Redis data, the DB was not consulted.
        """
        tenant_id = cache_tenant_id
        cache_key = f"mingai:{tenant_id}:glossary_terms"

        async def _run():
            _reset_redis_pool()
            # Place synthetic data in Redis that does NOT exist in DB
            synthetic_terms = [
                {
                    "term": "CACHEONLY",
                    "full_form": "This Exists Only In Cache",
                    "aliases": [],
                }
            ]
            redis = get_redis()
            await redis.setex(
                cache_key,
                GLOSSARY_CACHE_TTL_SECONDS,
                json.dumps(synthetic_terms),
            )

            # Call _get_terms — should return cache data, not DB data
            terms = await _get_terms_with_fresh_session(tenant_id)

            # If cache was hit, we get the synthetic term back
            assert (
                len(terms) == 1
            ), f"Expected 1 cached term, got {len(terms)} — cache was bypassed"
            assert terms[0]["term"] == "CACHEONLY"
            assert terms[0]["full_form"] == "This Exists Only In Cache"

        asyncio.run(_run())

    def test_cache_invalidation_deletes_key(self, cache_tenant_id):
        """
        After calling _invalidate_glossary_cache(tenant_id), the Redis key
        mingai:{tenant_id}:glossary_terms must no longer exist.
        """
        tenant_id = cache_tenant_id
        cache_key = f"mingai:{tenant_id}:glossary_terms"

        async def _run():
            _reset_redis_pool()
            # Pre-populate Redis cache
            redis = get_redis()
            await redis.setex(
                cache_key,
                GLOSSARY_CACHE_TTL_SECONDS,
                json.dumps([{"term": "DEL", "full_form": "Delete Me", "aliases": []}]),
            )

            # Confirm key exists
            assert await redis.exists(cache_key), "Pre-condition: key should exist"

            # Invalidate
            await _invalidate_glossary_cache(tenant_id)

            # Verify key is gone
            exists = await redis.exists(cache_key)
            assert (
                not exists
            ), f"Cache key {cache_key} should be deleted after invalidation"

        asyncio.run(_run())

    def test_fresh_db_query_after_invalidation(self, cache_tenant_id):
        """
        After cache invalidation, calling _get_terms() should query the DB
        afresh and re-populate the Redis cache with current DB data.
        """
        tenant_id = cache_tenant_id
        cache_key = f"mingai:{tenant_id}:glossary_terms"

        async def _run():
            _reset_redis_pool()
            # Place stale data in Redis
            redis = get_redis()
            stale_terms = [{"term": "STALE", "full_form": "Stale Data", "aliases": []}]
            await redis.setex(
                cache_key,
                GLOSSARY_CACHE_TTL_SECONDS,
                json.dumps(stale_terms),
            )

            # Invalidate the cache
            await _invalidate_glossary_cache(tenant_id)

            # Confirm key is gone
            assert not await redis.exists(cache_key)

            # Call _get_terms — should hit DB and re-cache
            terms = await _get_terms_with_fresh_session(tenant_id)

            # The result should come from DB (HR term inserted in test 1),
            # NOT the stale "STALE" term
            term_names = [t["term"] for t in terms]
            assert (
                "STALE" not in term_names
            ), "Stale cached data should not appear after invalidation"

            # Verify the cache was re-populated in Redis
            cached_raw = await redis.get(cache_key)
            assert (
                cached_raw is not None
            ), "Cache should be re-populated after _get_terms() post-invalidation"
            cached_terms = json.loads(cached_raw)
            # cached_terms should match what the DB returned
            cached_names = [t["term"] for t in cached_terms]
            assert cached_names == term_names

        asyncio.run(_run())

    def test_glossary_cache_ttl_is_3600(self, cache_tenant_id):
        """
        After caching, the Redis TTL on the glossary key must be between
        3500 and 3600 seconds (allowing for slight timing variance).
        """
        tenant_id = cache_tenant_id
        cache_key = f"mingai:{tenant_id}:glossary_terms"

        async def _run():
            from app.core.redis_client import close_redis

            _reset_redis_pool()
            redis = get_redis()
            try:
                # Clear cache so _get_terms triggers a fresh DB query + cache store
                await redis.delete(cache_key)

                # Call _get_terms to populate cache
                await _get_terms_with_fresh_session(tenant_id)

                # Check TTL
                ttl = await redis.ttl(cache_key)
                assert 3500 <= ttl <= 3600, f"Expected TTL between 3500-3600, got {ttl}"
            finally:
                # Close pool explicitly before the event loop is destroyed
                await close_redis()

        asyncio.run(_run())

    def test_empty_tenant_glossary_cached_as_empty_list(self):
        """
        For a tenant with no glossary terms in DB, _get_terms() caches
        an empty list [] — not None and not a missing key.
        """
        # Use a completely fresh tenant with zero glossary terms
        empty_tenant_id = str(uuid.uuid4())
        cache_key = f"mingai:{empty_tenant_id}:glossary_terms"

        async def _run():
            _reset_redis_pool()
            redis = get_redis()
            # Ensure clean state
            await redis.delete(cache_key)

            # Create tenant with no glossary terms
            await _create_tenant(empty_tenant_id)
            try:
                # Call _get_terms
                terms = await _get_terms_with_fresh_session(empty_tenant_id)

                # Should return empty list
                assert terms == [], f"Expected [], got {terms}"

                # Cache key should exist with value "[]"
                cached_raw = await redis.get(cache_key)
                assert (
                    cached_raw is not None
                ), "Empty glossary should still be cached (not missing key)"
                cached_terms = json.loads(cached_raw)
                assert (
                    cached_terms == []
                ), f"Cached value should be [], got {cached_terms}"
            finally:
                # Cleanup
                await redis.delete(cache_key)
                await _cleanup_tenant(empty_tenant_id)

        asyncio.run(_run())
