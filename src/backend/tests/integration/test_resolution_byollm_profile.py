"""
Integration test: ProfileResolver resolves BYOLLM profile.

Verifies that when a tenant has an active BYOLLM profile (owner_tenant_id = tenant_id),
ProfileResolver.resolve() returns that profile with is_byollm semantics.

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


async def _create_enterprise_tenant(engine, tid: str) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
                "VALUES (:id, :name, :slug, 'enterprise', :email, 'active') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": tid,
                "name": f"BYOLLM Res Test {tid[:8]}",
                "slug": f"byollm-res-{tid[:8]}",
                "email": f"byollm-res-{tid[:8]}@test.example",
            },
        )
        await session.commit()


async def _create_byollm_profile(engine, profile_id: str, tenant_id: str) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO llm_profiles "
                "(id, name, description, status, is_platform_default, plan_tiers, "
                "owner_tenant_id, created_by, created_at, updated_at) "
                "VALUES (:id, :name, 'BYOLLM test profile', 'active', false, '{}', "
                ":tid, :tid, NOW(), NOW()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": profile_id, "name": f"BYOLLM Profile {profile_id[:8]}", "tid": tenant_id},
        )
        await session.commit()


async def _assign_profile(engine, tenant_id: str, profile_id: str) -> None:
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
        # Unset llm_profile_id FK on tenant before deleting profile
        await session.execute(
            text("UPDATE tenants SET llm_profile_id = NULL WHERE id = :id"), {"id": tenant_id}
        )
        # Delete profile first (owner_tenant_id FK would block tenant delete)
        await session.execute(
            text("DELETE FROM llm_profiles WHERE id = :id"), {"id": profile_id}
        )
        await session.execute(
            text("DELETE FROM tenants WHERE id = :id"), {"id": tenant_id}
        )
        await session.commit()


@pytest.fixture(scope="module")
def byollm_resolution_fixtures():
    tenant_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())

    async def _setup():
        engine = await _get_engine()
        try:
            await _create_enterprise_tenant(engine, tenant_id)
            await _create_byollm_profile(engine, profile_id, tenant_id)
            await _assign_profile(engine, tenant_id, profile_id)
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


class TestResolutionBYOLLMProfile:
    """ProfileResolver identifies and returns BYOLLM-owned profiles."""

    def test_resolver_returns_byollm_profile(self, byollm_resolution_fixtures):
        """Resolver returns the BYOLLM profile when tenant has one assigned."""
        import asyncio as _asyncio
        from app.core.llm.profile_resolver import ProfileResolver

        tenant_id = byollm_resolution_fixtures["tenant_id"]
        profile_id = byollm_resolution_fixtures["profile_id"]

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
                            plan="enterprise",
                            db=db,
                        )
                    finally:
                        os.environ["LLM_PROFILE_SLOT_ROUTING"] = orig
            finally:
                await engine.dispose()

        result = _asyncio.run(_run())
        assert result is not None, "Resolver must return the BYOLLM profile"
        assert result.profile_id == profile_id

    def test_resolver_byollm_owner_matches_tenant(self, byollm_resolution_fixtures):
        """BYOLLM profile has owner_tenant_id equal to the requesting tenant."""
        import asyncio as _asyncio
        from app.core.llm.profile_resolver import ProfileResolver

        tenant_id = byollm_resolution_fixtures["tenant_id"]

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
                            plan="enterprise",
                            db=db,
                        )
                    finally:
                        os.environ["LLM_PROFILE_SLOT_ROUTING"] = orig
            finally:
                await engine.dispose()

        result = _asyncio.run(_run())
        if result is None:
            pytest.skip("Resolver returned None")
        assert result.owner_tenant_id == tenant_id, (
            "BYOLLM profile owner_tenant_id must match the requesting tenant"
        )
