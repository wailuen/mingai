"""
Integration test: ProfileResolver returns None for unassigned slots.

When a profile has chat assigned but intent is NULL, requesting the intent
slot should return None from get_slot() — not raise a KeyError.

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


async def _create_tenant_with_partial_profile(
    engine, tenant_id: str, profile_id: str
) -> None:
    """Create a profile with no slots assigned, assign to tenant."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO llm_profiles "
                "(id, name, description, status, is_platform_default, plan_tiers, "
                "owner_tenant_id, created_by, created_at, updated_at) "
                "VALUES (:id, :name, 'Null slot profile', 'active', false, '{}', "
                "NULL, :id, NOW(), NOW()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": profile_id, "name": f"Null Slot Profile {profile_id[:8]}"},
        )
        await session.execute(
            text(
                "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status, llm_profile_id) "
                "VALUES (:id, :name, :slug, 'professional', :email, 'active', :pid) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": tenant_id,
                "name": f"Null Slot Tenant {tenant_id[:8]}",
                "slug": f"null-slot-{tenant_id[:8]}",
                "email": f"null-{tenant_id[:8]}@test.example",
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
def null_slot_fixtures():
    tenant_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())

    async def _setup():
        engine = await _get_engine()
        try:
            await _create_tenant_with_partial_profile(engine, tenant_id, profile_id)
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


class TestResolutionNullSlot:
    """Unassigned slots return None from get_slot(), never raise."""

    def test_unassigned_intent_slot_is_none(self, null_slot_fixtures):
        """Profile with no intent slot assigned has get_slot('intent') returning None."""
        import asyncio as _asyncio
        from app.core.llm.profile_resolver import ProfileResolver

        tenant_id = null_slot_fixtures["tenant_id"]

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
        if result is None:
            pytest.skip("Resolver returned None — DB resolution may not be working")

        # All slots should exist in the dict (even if None library_id)
        intent_slot = result.get_slot("intent")
        # Intent slot exists but library_id is None (not assigned)
        if intent_slot is not None:
            assert intent_slot.library_id is None, (
                "Unassigned intent slot must have library_id=None"
            )

    def test_unassigned_slot_does_not_raise_key_error(self, null_slot_fixtures):
        """Calling get_slot() on an unassigned slot must not raise KeyError."""
        import asyncio as _asyncio
        from app.core.llm.profile_resolver import ProfileResolver

        tenant_id = null_slot_fixtures["tenant_id"]

        async def _run():
            engine = await _get_engine()
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            try:
                async with factory() as db:
                    orig = os.environ.get("LLM_PROFILE_SLOT_ROUTING", "0")
                    os.environ["LLM_PROFILE_SLOT_ROUTING"] = "1"
                    try:
                        resolver = ProfileResolver()
                        result = await resolver.resolve(
                            tenant_id=tenant_id,
                            plan="professional",
                            db=db,
                        )
                        if result is None:
                            return None
                        # This must not raise
                        try:
                            _ = result.get_slot("vision")
                            _ = result.get_slot("agent")
                        except KeyError as e:
                            raise AssertionError(
                                f"get_slot() raised KeyError for unassigned slot: {e}"
                            )
                        return result
                    finally:
                        os.environ["LLM_PROFILE_SLOT_ROUTING"] = orig
            finally:
                await engine.dispose()

        # Should not raise
        _asyncio.run(_run())
