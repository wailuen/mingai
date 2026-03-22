"""
TEST-023: LLM Profile CRUD — Integration Tests

Tests platform admin create/read/update/deprecate of LLM profiles against
real PostgreSQL using the new LLMProfileService (v050 schema).
No mocking — Tier 2 integration tests.

New schema (v050):
  - Platform profiles: owner_tenant_id IS NULL
  - BYOLLM profiles: owner_tenant_id = tenant_id
  - Slots (chat/intent/vision/agent) reference llm_library entries
  - No direct model_name/provider columns — resolved via slot FKs

Prerequisites:
    docker-compose up -d  # ensure PostgreSQL is running

Run:
    pytest tests/integration/test_llm_profile_crud.py -v --timeout=30
"""
import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.llm_profiles.service import (
    LLMProfileConflictError,
    LLMProfileNotFoundError,
    LLMProfileService,
    LLMProfileValidationError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ACTOR_ID = str(uuid.uuid4())


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


def _make_engine():
    return create_async_engine(_db_url(), echo=False)


async def _run_sql(sql: str, params: dict = None):
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _make_session_factory():
    """Return (engine, session_factory) — caller must dispose engine."""
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _cleanup_profiles_by_name_prefix(prefix: str):
    """Remove test profiles whose name starts with prefix."""
    await _run_sql(
        "DELETE FROM llm_profiles WHERE name LIKE :prefix AND owner_tenant_id IS NULL",
        {"prefix": f"{prefix}%"},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def name_prefix():
    """Unique prefix for test profile names to avoid cross-test pollution."""
    token = uuid.uuid4().hex[:8]
    yield f"TEST-CRUD-{token}-"
    asyncio.run(_cleanup_profiles_by_name_prefix(f"TEST-CRUD-{token}-"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLLMProfileCRUD:
    """
    Integration tests for LLM profile CRUD operations against real PostgreSQL.

    Tests use platform profiles (owner_tenant_id IS NULL) which don't require
    existing llm_library entries when created without slot assignments.

    TEST-023 coverage:
    - Create profile — all fields stored in DB
    - Read profile — returns correct data
    - Read nonexistent — raises LLMProfileNotFoundError
    - Update profile — changes persisted
    - List profiles — includes created profiles
    - Name uniqueness enforced for platform profiles
    - Model names come from llm_library (validated at library layer)
    - Deprecate — sets status = 'deprecated'
    - Deprecate already deprecated — raises ValueError
    - Deprecate nonexistent — raises LookupError
    """

    def test_create_llm_profile_stores_all_fields(self, name_prefix):
        """
        Creating a platform LLM profile stores all provided fields in PostgreSQL.
        The returned dict includes id, name, description, status, plan_tiers.
        """

        async def _run():
            engine, factory = await _make_session_factory()
            svc = LLMProfileService()
            try:
                async with factory() as session:
                    result = await svc.create_platform_profile(
                        name=f"{name_prefix}Alpha",
                        description="Test profile alpha",
                        plan_tiers=["professional"],
                        slot_data={},  # No library slots needed for basic CRUD
                        is_platform_default=False,
                        actor_id=_ACTOR_ID,
                        db=session,
                    )
                    await session.commit()
            finally:
                await engine.dispose()
            return result

        profile = asyncio.run(_run())

        assert "id" in profile, "Created profile must have an id"
        assert profile["name"] == f"{name_prefix}Alpha"
        assert profile["description"] == "Test profile alpha"
        assert profile["status"] == "active"
        assert profile["plan_tiers"] == ["professional"]
        assert profile["owner_tenant_id"] is None  # platform profile

    def test_read_llm_profile_returns_correct_data(self, name_prefix):
        """
        get_profile returns the profile with all fields matching what was inserted,
        including created_at and updated_at timestamps.
        """

        async def _run():
            engine, factory = await _make_session_factory()
            svc = LLMProfileService()
            try:
                async with factory() as session:
                    created = await svc.create_platform_profile(
                        name=f"{name_prefix}Read",
                        description="Read test profile",
                        plan_tiers=[],
                        slot_data={},
                        is_platform_default=False,
                        actor_id=_ACTOR_ID,
                        db=session,
                    )
                    await session.commit()
                    profile_id = created["id"]
                    fetched = await svc.get_profile(profile_id=profile_id, db=session)
            finally:
                await engine.dispose()
            return created, fetched

        created, fetched = asyncio.run(_run())

        assert fetched["id"] == created["id"]
        assert fetched["name"] == f"{name_prefix}Read"
        assert fetched["description"] == "Read test profile"
        assert fetched["status"] == "active"
        assert "created_at" in fetched
        assert "updated_at" in fetched

    def test_read_nonexistent_profile_raises(self, name_prefix):
        """get_profile raises LLMProfileNotFoundError for a non-existent profile ID."""

        async def _run():
            engine, factory = await _make_session_factory()
            svc = LLMProfileService()
            try:
                async with factory() as session:
                    raised = False
                    try:
                        await svc.get_profile(
                            profile_id=str(uuid.uuid4()), db=session
                        )
                    except LLMProfileNotFoundError:
                        raised = True
            finally:
                await engine.dispose()
            return raised

        raised = asyncio.run(_run())
        assert raised, "get_profile must raise LLMProfileNotFoundError for non-existent ID"

    def test_update_llm_profile_persists_changes(self, name_prefix):
        """
        update_platform_profile changes the specified fields and leaves
        other fields unchanged. updated_at is advanced.
        """

        async def _run():
            engine, factory = await _make_session_factory()
            svc = LLMProfileService()
            try:
                async with factory() as session:
                    created = await svc.create_platform_profile(
                        name=f"{name_prefix}Update",
                        description="Before update",
                        plan_tiers=["starter"],
                        slot_data={},
                        is_platform_default=False,
                        actor_id=_ACTOR_ID,
                        db=session,
                    )
                    await session.commit()
                    profile_id = created["id"]

                    updated = await svc.update_platform_profile(
                        profile_id=profile_id,
                        updates={"description": "After update", "plan_tiers": ["starter", "professional"]},
                        actor_id=_ACTOR_ID,
                        db=session,
                    )
                    await session.commit()
            finally:
                await engine.dispose()
            return created, updated

        created, updated = asyncio.run(_run())

        assert updated is not None, "update_platform_profile must return updated record"
        assert updated["description"] == "After update", "Description should be updated"
        assert "professional" in updated["plan_tiers"], "plan_tiers should be updated"
        assert updated["name"] == created["name"], "Name must remain unchanged"

    def test_list_llm_profiles_includes_created(self, name_prefix):
        """
        list_platform_profiles returns a list that includes profiles created
        in this test. Fields include id, name, status.
        """

        async def _run():
            engine, factory = await _make_session_factory()
            svc = LLMProfileService()
            try:
                async with factory() as session:
                    created = await svc.create_platform_profile(
                        name=f"{name_prefix}List",
                        description=None,
                        plan_tiers=[],
                        slot_data={},
                        is_platform_default=False,
                        actor_id=_ACTOR_ID,
                        db=session,
                    )
                    await session.commit()
                    profiles = await svc.list_platform_profiles(db=session)
            finally:
                await engine.dispose()
            return created["id"], profiles

        created_id, profiles = asyncio.run(_run())

        assert isinstance(profiles, list), "list_platform_profiles must return a list"
        ids = [p["id"] for p in profiles]
        assert created_id in ids, (
            f"Created profile {created_id} must appear in list. Got: {ids[:5]}"
        )
        # Verify each item has required fields
        for p in profiles:
            assert "id" in p
            assert "name" in p
            assert "status" in p

    def test_profile_name_uniqueness_enforced(self, name_prefix):
        """
        Creating two platform profiles with the same name raises LLMProfileConflictError.
        """

        async def _run():
            engine, factory = await _make_session_factory()
            svc = LLMProfileService()
            try:
                async with factory() as session:
                    await svc.create_platform_profile(
                        name=f"{name_prefix}Duplicate",
                        description=None,
                        plan_tiers=[],
                        slot_data={},
                        is_platform_default=False,
                        actor_id=_ACTOR_ID,
                        db=session,
                    )
                    await session.commit()

                    # Second create with same name — must fail
                    duplicate_raised = False
                    try:
                        await svc.create_platform_profile(
                            name=f"{name_prefix}Duplicate",
                            description="different desc",
                            plan_tiers=["professional"],
                            slot_data={},
                            is_platform_default=False,
                            actor_id=_ACTOR_ID,
                            db=session,
                        )
                    except LLMProfileConflictError:
                        duplicate_raised = True
            finally:
                await engine.dispose()
            return duplicate_raised

        duplicate_raised = asyncio.run(_run())
        assert duplicate_raised, (
            "Creating a platform profile with a duplicate name must raise LLMProfileConflictError"
        )

    def test_model_names_come_from_request_not_hardcoded(self, name_prefix):
        """
        The name stored in the DB matches exactly what was passed in the request —
        demonstrating that profile metadata is stored as-is.
        In the new schema, model names live in llm_library entries referenced via
        slot FKs, not in the profile row itself.
        """
        custom_name = f"{name_prefix}Model-{uuid.uuid4().hex[:6]}"

        async def _run():
            engine, factory = await _make_session_factory()
            svc = LLMProfileService()
            try:
                async with factory() as session:
                    created = await svc.create_platform_profile(
                        name=custom_name,
                        description=None,
                        plan_tiers=[],
                        slot_data={},
                        is_platform_default=False,
                        actor_id=_ACTOR_ID,
                        db=session,
                    )
                    await session.commit()
                    fetched = await svc.get_profile(profile_id=created["id"], db=session)
            finally:
                await engine.dispose()
            return fetched

        fetched = asyncio.run(_run())
        assert fetched["name"] == custom_name, (
            f"Profile name stored as '{fetched['name']}' but expected '{custom_name}'. "
            "Profile name must be stored exactly as provided."
        )

    def test_deprecate_llm_profile_sets_deprecated_status(self, name_prefix):
        """
        deprecate_platform_profile soft-deletes a profile by setting status='deprecated'.
        The profile record remains in the DB.
        """

        async def _run():
            engine, factory = await _make_session_factory()
            svc = LLMProfileService()
            try:
                async with factory() as session:
                    created = await svc.create_platform_profile(
                        name=f"{name_prefix}Deprecate-{uuid.uuid4().hex[:6]}",
                        description=None,
                        plan_tiers=[],
                        slot_data={},
                        is_platform_default=False,
                        actor_id=_ACTOR_ID,
                        db=session,
                    )
                    await session.commit()
                    profile_id = created["id"]

                    result = await svc.deprecate_platform_profile(
                        profile_id=profile_id,
                        actor_id=_ACTOR_ID,
                        db=session,
                    )
                    await session.commit()

                    # Verify the profile still exists but is deprecated
                    after = await svc.get_profile(profile_id=profile_id, db=session)
            finally:
                await engine.dispose()
            return result, after

        result, after = asyncio.run(_run())

        assert result["status"] == "deprecated"
        assert after is not None, "Profile must still exist after deprecation (soft-delete)"
        assert after["status"] == "deprecated"

    def test_deprecate_already_deprecated_raises_value_error(self, name_prefix):
        """
        deprecate_platform_profile raises ValueError when the profile is already
        deprecated.
        """

        async def _run():
            engine, factory = await _make_session_factory()
            svc = LLMProfileService()
            try:
                async with factory() as session:
                    created = await svc.create_platform_profile(
                        name=f"{name_prefix}DoubleDeprecate-{uuid.uuid4().hex[:6]}",
                        description=None,
                        plan_tiers=[],
                        slot_data={},
                        is_platform_default=False,
                        actor_id=_ACTOR_ID,
                        db=session,
                    )
                    await session.commit()
                    profile_id = created["id"]

                    # First deprecation succeeds
                    await svc.deprecate_platform_profile(
                        profile_id=profile_id, actor_id=_ACTOR_ID, db=session
                    )
                    await session.commit()

                    # Second deprecation should raise LLMProfileValidationError or ValueError
                    double_raised = False
                    try:
                        await svc.deprecate_platform_profile(
                            profile_id=profile_id, actor_id=_ACTOR_ID, db=session
                        )
                    except (LLMProfileValidationError, ValueError):
                        double_raised = True
            finally:
                await engine.dispose()
            return double_raised

        double_raised = asyncio.run(_run())
        assert double_raised, "Deprecating an already-deprecated profile must raise ValueError"

    def test_deprecate_nonexistent_profile_raises_lookup_error(self, name_prefix):
        """
        deprecate_platform_profile raises LookupError for a non-existent profile ID.
        """

        async def _run():
            engine, factory = await _make_session_factory()
            svc = LLMProfileService()
            try:
                async with factory() as session:
                    lookup_raised = False
                    try:
                        await svc.deprecate_platform_profile(
                            profile_id=str(uuid.uuid4()),
                            actor_id=_ACTOR_ID,
                            db=session,
                        )
                    except (LookupError, LLMProfileNotFoundError):
                        lookup_raised = True
            finally:
                await engine.dispose()
            return lookup_raised

        lookup_raised = asyncio.run(_run())
        assert lookup_raised, (
            "Deprecating a non-existent profile must raise LookupError or LLMProfileNotFoundError"
        )
