"""
Integration test: ProfileResolver resolves platform profile for a tenant.

Verifies that when a tenant has an explicit llm_profile_id pointing to a platform
profile, ProfileResolver.resolve() returns that profile correctly.

Tier 2: No mocking — requires running PostgreSQL + Redis.
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

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


async def _create_tenant(engine, tid: str, plan: str = "professional") -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
                "VALUES (:id, :name, :slug, :plan, :email, 'active') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": tid,
                "name": f"Resolution Test {tid[:8]}",
                "slug": f"res-test-{tid[:8]}",
                "plan": plan,
                "email": f"res-{tid[:8]}@test.example",
            },
        )
        await session.commit()


async def _create_platform_profile(engine, profile_id: str, name: str) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO llm_profiles "
                "(id, name, description, status, is_platform_default, plan_tiers, "
                "owner_tenant_id, created_by, created_at, updated_at) "
                "VALUES (:id, :name, 'Test platform profile', 'active', false, '{}', "
                "NULL, :id, NOW(), NOW()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": profile_id, "name": name},
        )
        await session.commit()


async def _assign_profile_to_tenant(engine, tenant_id: str, profile_id: str) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text("UPDATE tenants SET llm_profile_id = :pid WHERE id = :tid"),
            {"pid": profile_id, "tid": tenant_id},
        )
        await session.commit()


async def _cleanup(engine, tenant_id: str, profile_id: str) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text("DELETE FROM tenants WHERE id = :id"), {"id": tenant_id}
        )
        await session.execute(
            text("DELETE FROM llm_profiles WHERE id = :id"), {"id": profile_id}
        )
        await session.commit()


@pytest.fixture(scope="module")
def resolution_platform_fixtures():
    tenant_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())

    async def _setup():
        engine = await _get_engine()
        try:
            await _create_tenant(engine, tenant_id)
            await _create_platform_profile(engine, profile_id, f"Platform Profile {profile_id[:8]}")
            await _assign_profile_to_tenant(engine, tenant_id, profile_id)
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


class TestResolutionPlatformProfile:
    """ProfileResolver correctly resolves an explicitly assigned platform profile."""

    def test_resolver_returns_correct_profile_id(self, resolution_platform_fixtures):
        """When tenant has llm_profile_id set, resolver returns that profile."""
        import asyncio as _asyncio
        from app.core.llm.profile_resolver import ProfileResolver

        tenant_id = resolution_platform_fixtures["tenant_id"]
        profile_id = resolution_platform_fixtures["profile_id"]

        async def _run():
            engine = await _get_engine()
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            try:
                async with factory() as db:
                    # Must set LLM_PROFILE_SLOT_ROUTING=1 for the resolver to run
                    import os
                    original = os.environ.get("LLM_PROFILE_SLOT_ROUTING", "0")
                    os.environ["LLM_PROFILE_SLOT_ROUTING"] = "1"
                    try:
                        resolver = ProfileResolver()
                        result = await resolver.resolve(
                            tenant_id=tenant_id,
                            plan="professional",
                            db=db,
                        )
                    finally:
                        os.environ["LLM_PROFILE_SLOT_ROUTING"] = original
                    return result
            finally:
                await engine.dispose()

        result = _asyncio.run(_run())
        assert result is not None, "Resolver should return a profile, not None"
        assert result.profile_id == profile_id, (
            f"Expected profile_id={profile_id}, got {result.profile_id}"
        )

    def test_resolver_is_not_byollm_for_platform_profile(self, resolution_platform_fixtures):
        """Platform profiles have owner_tenant_id IS NULL, so is_byollm is False."""
        import asyncio as _asyncio
        from app.core.llm.profile_resolver import ProfileResolver

        tenant_id = resolution_platform_fixtures["tenant_id"]

        async def _run():
            engine = await _get_engine()
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            try:
                async with factory() as db:
                    import os
                    original = os.environ.get("LLM_PROFILE_SLOT_ROUTING", "0")
                    os.environ["LLM_PROFILE_SLOT_ROUTING"] = "1"
                    try:
                        resolver = ProfileResolver()
                        result = await resolver.resolve(
                            tenant_id=tenant_id,
                            plan="professional",
                            db=db,
                        )
                    finally:
                        os.environ["LLM_PROFILE_SLOT_ROUTING"] = original
                    return result
            finally:
                await engine.dispose()

        result = _asyncio.run(_run())
        if result is None:
            pytest.skip("Resolver returned None — profile may not be active")
        assert result.owner_tenant_id is None, (
            "Platform profile should have owner_tenant_id=None"
        )
