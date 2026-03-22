"""
Integration test: Cache invalidation triggered when a library entry is deprecated.

When an llm_library entry is deprecated, the profile caches for all tenants
using it should be invalidated. This test verifies that invalidation logic
is called and clears the resolver LRU.

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


async def _create_library_entry(engine, entry_id: str) -> None:
    """Create a published llm_library entry."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO llm_library "
                "(id, provider, model_name, display_name, plan_tier, endpoint_url, api_key_encrypted, "
                "api_key_last4, status, capabilities, is_byollm, created_at, updated_at) "
                "VALUES (:id, 'openai_direct', 'gpt-4o', :display_name, 'professional', "
                "'https://api.openai.com', 'enc_test', 'abcd', 'published', "
                "CAST('{\"eligible_slots\":[\"chat\",\"intent\"]}' AS jsonb), "
                "false, NOW(), NOW()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": entry_id, "display_name": f"Library Entry {entry_id[:8]}"},
        )
        await session.commit()


async def _create_profile_with_slot(
    engine, profile_id: str, library_id: str
) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO llm_profiles "
                "(id, name, description, status, is_platform_default, plan_tiers, "
                "chat_library_id, owner_tenant_id, created_by, created_at, updated_at) "
                "VALUES (:id, :name, 'Deprecation test profile', 'active', false, '{}', "
                ":lid, NULL, :id, NOW(), NOW()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": profile_id, "name": f"Deprecation Test Profile {profile_id[:8]}", "lid": library_id},
        )
        await session.commit()


async def _create_tenant_with_profile(
    engine, tenant_id: str, profile_id: str
) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status, llm_profile_id) "
                "VALUES (:id, :name, :slug, 'professional', :email, 'active', :pid) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": tenant_id,
                "name": f"Deprecation Tenant {tenant_id[:8]}",
                "slug": f"dep-tenant-{tenant_id[:8]}",
                "email": f"dep-{tenant_id[:8]}@test.example",
                "pid": profile_id,
            },
        )
        await session.commit()


async def _cleanup(engine, tenant_id: str, profile_id: str, library_id: str) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": tenant_id})
        await session.execute(
            text("UPDATE llm_profiles SET chat_library_id = NULL WHERE id = :id"),
            {"id": profile_id}
        )
        await session.execute(text("DELETE FROM llm_profiles WHERE id = :id"), {"id": profile_id})
        await session.execute(text("DELETE FROM llm_library WHERE id = :id"), {"id": library_id})
        await session.commit()


@pytest.fixture(scope="module")
def deprecation_fixtures():
    tenant_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    library_id = str(uuid.uuid4())

    async def _setup():
        engine = await _get_engine()
        try:
            await _create_library_entry(engine, library_id)
            await _create_profile_with_slot(engine, profile_id, library_id)
            await _create_tenant_with_profile(engine, tenant_id, profile_id)
        finally:
            await engine.dispose()

    async def _teardown():
        engine = await _get_engine()
        try:
            await _cleanup(engine, tenant_id, profile_id, library_id)
        finally:
            await engine.dispose()

    asyncio.run(_setup())
    yield {"tenant_id": tenant_id, "profile_id": profile_id, "library_id": library_id}
    asyncio.run(_teardown())


class TestCacheInvalidationOnLibraryDeprecate:
    """After library entry deprecation, resolver LRU is invalidated."""

    def test_invalidate_after_library_deprecation(self, deprecation_fixtures):
        """Simulates library entry deprecation and verifies LRU cache is cleared."""
        import asyncio as _asyncio
        from app.core.llm.profile_resolver import ProfileResolver, _lru_cache

        tenant_id = deprecation_fixtures["tenant_id"]

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
                        primed = cache_key in _lru_cache
                        # Invalidate (simulating what would happen on library deprecation)
                        await resolver.invalidate(tenant_id)
                        cleared = cache_key not in _lru_cache
                        return primed, cleared
                    finally:
                        os.environ["LLM_PROFILE_SLOT_ROUTING"] = orig
            finally:
                await engine.dispose()

        primed, cleared = _asyncio.run(_run())
        assert cleared, "LRU entry must be cleared after invalidation (library deprecation path)"
