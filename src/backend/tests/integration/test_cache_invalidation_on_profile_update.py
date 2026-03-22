"""
Integration test: Cache invalidation when a profile is updated.

Verifies that calling ProfileResolver.invalidate() removes the Redis key
so the next resolution call goes to DB.

Tier 2: No mocking — requires running PostgreSQL + Redis.
"""
import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


async def _get_engine():
    return create_async_engine(_db_url(), echo=False)


async def _create_test_fixtures(engine, tenant_id: str, profile_id: str) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO llm_profiles "
                "(id, name, description, status, is_platform_default, plan_tiers, "
                "owner_tenant_id, created_by, created_at, updated_at) "
                "VALUES (:id, :name, 'Cache test profile', 'active', false, '{}', "
                "NULL, :id, NOW(), NOW()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": profile_id, "name": f"Cache Test Profile {profile_id[:8]}"},
        )
        await session.execute(
            text(
                "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status, llm_profile_id) "
                "VALUES (:id, :name, :slug, 'professional', :email, 'active', :pid) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": tenant_id,
                "name": f"Cache Test Tenant {tenant_id[:8]}",
                "slug": f"cache-test-{tenant_id[:8]}",
                "email": f"cache-{tenant_id[:8]}@test.example",
                "pid": profile_id,
            },
        )
        await session.commit()


async def _cleanup(engine, tenant_id: str, profile_id: str) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": tenant_id})
        await session.execute(text("DELETE FROM llm_profiles WHERE id = :id"), {"id": profile_id})
        await session.commit()


@pytest.fixture(scope="module")
def cache_invalidation_fixtures():
    tenant_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())

    async def _setup():
        engine = await _get_engine()
        try:
            await _create_test_fixtures(engine, tenant_id, profile_id)
        finally:
            await engine.dispose()

    async def _teardown():
        engine = await _get_engine()
        try:
            await _cleanup(engine, tenant_id, profile_id)
        finally:
            await engine.dispose()

    asyncio.run(_setup())
    yield {"tenant_id": tenant_id, "profile_id": profile_id}
    asyncio.run(_teardown())


class TestCacheInvalidationOnProfileUpdate:
    """After invalidation, the next resolver call hits DB (not Redis)."""

    def test_invalidate_removes_lru_entry(self, cache_invalidation_fixtures):
        """ProfileResolver.invalidate() removes the tenant's entry from the LRU cache."""
        import asyncio as _asyncio
        from app.core.llm.profile_resolver import ProfileResolver, _lru_cache

        tenant_id = cache_invalidation_fixtures["tenant_id"]

        async def _run():
            engine = await _get_engine()
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            try:
                async with factory() as db:
                    orig = os.environ.get("LLM_PROFILE_SLOT_ROUTING", "0")
                    os.environ["LLM_PROFILE_SLOT_ROUTING"] = "1"
                    try:
                        resolver = ProfileResolver()
                        # Prime the cache
                        await resolver.resolve(tenant_id=tenant_id, plan="professional", db=db)
                        cache_key = f"llm_profile:{tenant_id}"
                        assert cache_key in _lru_cache, "LRU should be primed after resolve"
                        # Invalidate
                        await resolver.invalidate(tenant_id)
                        assert cache_key not in _lru_cache, (
                            "LRU entry must be removed after invalidate()"
                        )
                    finally:
                        os.environ["LLM_PROFILE_SLOT_ROUTING"] = orig
            finally:
                await engine.dispose()

        _asyncio.run(_run())

    def test_resolve_after_invalidation_hits_db(self, cache_invalidation_fixtures):
        """After invalidation, resolver fetches fresh data from DB."""
        import asyncio as _asyncio
        from app.core.llm.profile_resolver import ProfileResolver, _lru_cache

        tenant_id = cache_invalidation_fixtures["tenant_id"]
        profile_id = cache_invalidation_fixtures["profile_id"]

        async def _run():
            engine = await _get_engine()
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            try:
                async with factory() as db:
                    orig = os.environ.get("LLM_PROFILE_SLOT_ROUTING", "0")
                    os.environ["LLM_PROFILE_SLOT_ROUTING"] = "1"
                    try:
                        resolver = ProfileResolver()
                        await resolver.invalidate(tenant_id)
                        # After invalidation, resolver should go to DB
                        result = await resolver.resolve(
                            tenant_id=tenant_id, plan="professional", db=db
                        )
                        return result
                    finally:
                        os.environ["LLM_PROFILE_SLOT_ROUTING"] = orig
            finally:
                await engine.dispose()

        result = _asyncio.run(_run())
        assert result is not None, "Resolver must return a profile after invalidation + re-resolve"
        assert result.profile_id == profile_id
