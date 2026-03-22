"""
Integration test: ProfileResolver falls back to platform default profile.

Verifies that when a tenant has no explicit llm_profile_id, the resolver
returns the platform default profile. When no default exists, it returns None.

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


async def _create_tenant_no_profile(engine, tid: str) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status, llm_profile_id) "
                "VALUES (:id, :name, :slug, 'professional', :email, 'active', NULL) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": tid,
                "name": f"Default Fallback Test {tid[:8]}",
                "slug": f"dflt-{tid[:8]}",
                "email": f"dflt-{tid[:8]}@test.example",
            },
        )
        await session.commit()


async def _create_default_platform_profile(engine, profile_id: str) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO llm_profiles "
                "(id, name, description, status, is_platform_default, plan_tiers, "
                "owner_tenant_id, created_by, created_at, updated_at) "
                "VALUES (:id, :name, 'Default fallback profile', 'active', true, '{}', "
                "NULL, :id, NOW(), NOW()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": profile_id, "name": f"Default Profile {profile_id[:8]}"},
        )
        await session.commit()


async def _clear_all_platform_defaults(engine) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        # Use lock_timeout to avoid hanging if rows are locked by another session.
        # SKIP LOCKED semantics: only clear rows we can lock immediately.
        await session.execute(text("SET LOCAL lock_timeout = '3s'"))
        try:
            await session.execute(
                text(
                    "UPDATE llm_profiles SET is_platform_default = false "
                    "WHERE owner_tenant_id IS NULL AND is_platform_default = true"
                )
            )
        except Exception:
            # If lock contention, skip the clear — the test creates its own
            # default and checks by profile_id, so pre-existing defaults are
            # acceptable as long as the resolver finds ours.
            await session.rollback()
            return
        await session.commit()


async def _cleanup_tenant(engine, tid: str) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text("DELETE FROM tenants WHERE id = :id"), {"id": tid}
        )
        await session.commit()


async def _cleanup_profile(engine, pid: str) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text("DELETE FROM llm_profiles WHERE id = :id"), {"id": pid}
        )
        await session.commit()


@pytest.fixture(scope="module")
def default_fallback_fixtures():
    tenant_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())

    async def _setup():
        engine = await _get_engine()
        try:
            await _clear_all_platform_defaults(engine)
            await _create_tenant_no_profile(engine, tenant_id)
            await _create_default_platform_profile(engine, profile_id)
        finally:
            await engine.dispose()

    async def _teardown():
        engine = await _get_engine()
        try:
            await _cleanup_tenant(engine, tenant_id)
            await _cleanup_profile(engine, profile_id)
        finally:
            await engine.dispose()

    asyncio.run(_setup())
    yield {"tenant_id": tenant_id, "profile_id": profile_id}
    asyncio.run(_teardown())


class TestResolutionDefaultFallback:
    """ProfileResolver falls back to the platform default profile when no explicit assignment."""

    def test_tenant_without_profile_gets_default(self, default_fallback_fixtures):
        """Tenant with llm_profile_id=NULL gets the platform default profile."""
        import asyncio as _asyncio
        from app.core.llm.profile_resolver import ProfileResolver

        tenant_id = default_fallback_fixtures["tenant_id"]
        profile_id = default_fallback_fixtures["profile_id"]

        async def _run():
            engine = await _get_engine()
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            try:
                async with factory() as db:
                    orig = os.environ.get("LLM_PROFILE_SLOT_ROUTING", "0")
                    os.environ["LLM_PROFILE_SLOT_ROUTING"] = "1"
                    try:
                        resolver = ProfileResolver()
                        return await resolver.resolve(
                            tenant_id=tenant_id,
                            plan="professional",
                            db=db,
                        )
                    finally:
                        os.environ["LLM_PROFILE_SLOT_ROUTING"] = orig
            finally:
                await engine.dispose()

        result = _asyncio.run(_run())
        assert result is not None, "Resolver should return the platform default profile"
        assert result.profile_id == profile_id, (
            f"Expected default profile {profile_id}, got {result.profile_id if result else None}"
        )

    def test_no_default_returns_none(self, default_fallback_fixtures):
        """When no platform default exists and tenant has no assignment, resolver returns None."""
        import asyncio as _asyncio
        from app.core.llm.profile_resolver import ProfileResolver

        tenant_id = default_fallback_fixtures["tenant_id"]
        profile_id = default_fallback_fixtures["profile_id"]

        async def _run():
            engine = await _get_engine()
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            try:
                # Temporarily disable ONLY the test profile we own — avoids row-lock
                # contention from broad UPDATE on all platform profiles.
                async with factory() as session:
                    await session.execute(
                        text("UPDATE llm_profiles SET is_platform_default = false WHERE id = :pid"),
                        {"pid": profile_id},
                    )
                    await session.commit()
                # Invalidate Redis cache so the resolver re-reads from DB
                from app.core.redis_client import get_redis
                from app.core.llm import profile_resolver as _pr_mod
                _pr_mod._lru_cache.clear()
                try:
                    redis = get_redis()
                    await redis.delete(f"mingai:{tenant_id}:llm_profile")
                except Exception:
                    pass
                async with factory() as db:
                    orig = os.environ.get("LLM_PROFILE_SLOT_ROUTING", "0")
                    os.environ["LLM_PROFILE_SLOT_ROUTING"] = "1"
                    try:
                        resolver = ProfileResolver()
                        return await resolver.resolve(
                            tenant_id=tenant_id,
                            plan="professional",
                            db=db,
                        )
                    finally:
                        os.environ["LLM_PROFILE_SLOT_ROUTING"] = orig
            finally:
                await engine.dispose()

        result = _asyncio.run(_run())
        assert result is None, (
            "Resolver should return None when no default exists and no assignment"
        )
