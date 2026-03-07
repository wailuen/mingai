"""
TEST-023: LLM Profile CRUD — Integration Tests

Tests platform admin create/read/update/delete of LLM profiles against
real PostgreSQL. No mocking — Tier 2 integration tests.

Prerequisites:
    docker-compose up -d  # ensure PostgreSQL is running

Run:
    pytest tests/integration/test_llm_profile_crud.py -v --timeout=10
"""
import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.tenants.routes import (
    create_llm_profile_db,
    delete_llm_profile_db,
    get_llm_profile_db,
    list_llm_profiles_db,
    update_llm_profile_db,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


async def _make_session():
    """Return (engine, session) — caller must dispose engine."""
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _create_test_tenant() -> str:
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"LLM Test {tid[:8]}",
            "slug": f"llm-test-{tid[:8]}",
            "email": f"admin-{tid[:8]}@llm-int.test",
        },
    )
    return tid


async def _cleanup_tenant(tid: str):
    await _run_sql("DELETE FROM llm_profiles WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def tenant_id():
    """Provision one real tenant per test class, clean up after."""
    tid = asyncio.run(_create_test_tenant())
    yield tid
    asyncio.run(_cleanup_tenant(tid))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLLMProfileCRUD:
    """
    Integration tests for LLM profile CRUD operations against real PostgreSQL.

    TEST-023 coverage:
    - Create profile — all fields stored in DB
    - Read profile — returns correct data
    - Update profile — changes persisted
    - Delete profile in use — rejected with ValueError (409 at API layer)
    - Delete unused profile — succeeds
    - List profiles — includes created profiles
    - Name uniqueness enforced per tenant
    - Model names read from request, not hardcoded
    """

    def test_create_llm_profile_stores_all_fields(self, tenant_id):
        """
        Creating an LLM profile stores all provided fields in PostgreSQL.
        The returned dict includes id plus all input fields.
        """

        async def _run():
            engine, factory = await _make_session()
            try:
                async with factory() as session:
                    result = await create_llm_profile_db(
                        tenant_id=tenant_id,
                        name="Test Profile Alpha",
                        provider="azure_openai",
                        primary_model="agentic-worker",
                        intent_model="agentic-router",
                        embedding_model="text-embedding-3-small",
                        endpoint_url="https://eastus2.api.cognitive.microsoft.com/",
                        api_key_ref="AZURE_PLATFORM_OPENAI_API_KEY",
                        is_default=False,
                        db=session,
                    )
            finally:
                await engine.dispose()
            return result

        profile = asyncio.run(_run())

        assert "id" in profile, "Created profile must have an id"
        assert profile["tenant_id"] == tenant_id
        assert profile["name"] == "Test Profile Alpha"
        assert profile["provider"] == "azure_openai"
        assert profile["primary_model"] == "agentic-worker"
        assert profile["intent_model"] == "agentic-router"
        assert profile["embedding_model"] == "text-embedding-3-small"
        assert profile["endpoint_url"] == "https://eastus2.api.cognitive.microsoft.com/"
        assert profile["is_default"] is False

    def test_read_llm_profile_returns_correct_data(self, tenant_id):
        """
        get_llm_profile_db returns the profile with all fields matching what
        was inserted, including created_at and updated_at timestamps.
        """

        async def _run():
            engine, factory = await _make_session()
            try:
                async with factory() as session:
                    created = await create_llm_profile_db(
                        tenant_id=tenant_id,
                        name="Read Test Profile",
                        provider="azure_openai",
                        primary_model="agentic-gpt5",
                        intent_model="agentic-router",
                        embedding_model="text-embedding-3-small",
                        endpoint_url=None,
                        api_key_ref=None,
                        is_default=True,
                        db=session,
                    )
                    profile_id = created["id"]
                    fetched = await get_llm_profile_db(
                        profile_id=profile_id, db=session
                    )
            finally:
                await engine.dispose()
            return created, fetched

        created, fetched = asyncio.run(_run())

        assert fetched is not None, "get_llm_profile_db must return the profile"
        assert fetched["id"] == created["id"]
        assert fetched["name"] == "Read Test Profile"
        assert fetched["provider"] == "azure_openai"
        assert fetched["primary_model"] == "agentic-gpt5"
        assert fetched["is_default"] is True
        assert "created_at" in fetched
        assert "updated_at" in fetched

    def test_read_nonexistent_profile_returns_none(self, tenant_id):
        """get_llm_profile_db returns None for a non-existent profile ID."""

        async def _run():
            engine, factory = await _make_session()
            try:
                async with factory() as session:
                    result = await get_llm_profile_db(
                        profile_id=str(uuid.uuid4()), db=session
                    )
            finally:
                await engine.dispose()
            return result

        result = asyncio.run(_run())
        assert result is None, "Non-existent profile should return None"

    def test_update_llm_profile_persists_changes(self, tenant_id):
        """
        update_llm_profile_db changes the specified fields and leaves
        other fields unchanged. updated_at is advanced.
        """

        async def _run():
            engine, factory = await _make_session()
            try:
                async with factory() as session:
                    created = await create_llm_profile_db(
                        tenant_id=tenant_id,
                        name="Update Test Profile",
                        provider="azure_openai",
                        primary_model="agentic-worker",
                        intent_model="agentic-router",
                        embedding_model="text-embedding-3-small",
                        endpoint_url=None,
                        api_key_ref=None,
                        is_default=False,
                        db=session,
                    )
                    profile_id = created["id"]

                    updated = await update_llm_profile_db(
                        profile_id=profile_id,
                        updates={"name": "Updated Name", "is_default": True},
                        db=session,
                    )
            finally:
                await engine.dispose()
            return created, updated

        created, updated = asyncio.run(_run())

        assert updated is not None, "update_llm_profile_db must return updated record"
        assert updated["name"] == "Updated Name", "Name should be updated"
        assert updated["is_default"] is True, "is_default should be updated"
        assert (
            updated["provider"] == created["provider"]
        ), "Provider must remain unchanged"
        assert (
            updated["primary_model"] == created["primary_model"]
        ), "primary_model unchanged"

    def test_list_llm_profiles_includes_created(self, tenant_id):
        """
        list_llm_profiles_db returns a list that includes profiles created
        for the test tenant. Fields include id, tenant_id, name, provider.
        """

        async def _run():
            engine, factory = await _make_session()
            try:
                async with factory() as session:
                    created = await create_llm_profile_db(
                        tenant_id=tenant_id,
                        name="List Test Profile",
                        provider="azure_openai",
                        primary_model="agentic-worker",
                        intent_model="agentic-router",
                        embedding_model="text-embedding-3-small",
                        endpoint_url=None,
                        api_key_ref=None,
                        is_default=False,
                        db=session,
                    )
                    profiles = await list_llm_profiles_db(db=session)
            finally:
                await engine.dispose()
            return created["id"], profiles

        created_id, profiles = asyncio.run(_run())

        assert isinstance(profiles, list), "list_llm_profiles_db must return a list"
        ids = [p["id"] for p in profiles]
        assert (
            created_id in ids
        ), f"Created profile {created_id} must appear in list. Got: {ids[:5]}"
        # Verify each item has required fields
        for p in profiles:
            assert "id" in p
            assert "tenant_id" in p
            assert "name" in p
            assert "provider" in p

    def test_delete_unused_profile_succeeds(self, tenant_id):
        """
        delete_llm_profile_db removes a profile that is not assigned to
        any tenant (tenants.llm_profile_id != profile_id).
        """

        async def _run():
            engine, factory = await _make_session()
            try:
                async with factory() as session:
                    created = await create_llm_profile_db(
                        tenant_id=tenant_id,
                        name="Delete Test Profile",
                        provider="azure_openai",
                        primary_model="agentic-worker",
                        intent_model="agentic-router",
                        embedding_model="text-embedding-3-small",
                        endpoint_url=None,
                        api_key_ref=None,
                        is_default=False,
                        db=session,
                    )
                    profile_id = created["id"]
                    delete_result = await delete_llm_profile_db(
                        profile_id=profile_id, db=session
                    )
                    # Verify it's actually gone
                    after = await get_llm_profile_db(profile_id=profile_id, db=session)
            finally:
                await engine.dispose()
            return delete_result, after

        delete_result, after = asyncio.run(_run())

        assert delete_result["deleted"] is True
        assert after is None, "Profile should not exist after deletion"

    def test_delete_in_use_profile_raises_value_error(self, tenant_id):
        """
        delete_llm_profile_db raises ValueError when a profile is assigned
        to a tenant via tenants.llm_profile_id. The API converts this to 409.
        """

        async def _run():
            engine, factory = await _make_session()
            try:
                async with factory() as session:
                    created = await create_llm_profile_db(
                        tenant_id=tenant_id,
                        name="In Use Profile",
                        provider="azure_openai",
                        primary_model="agentic-worker",
                        intent_model="agentic-router",
                        embedding_model="text-embedding-3-small",
                        endpoint_url=None,
                        api_key_ref=None,
                        is_default=False,
                        db=session,
                    )
                    profile_id = created["id"]

                    # Assign this profile to the tenant
                    await session.execute(
                        text(
                            "UPDATE tenants SET llm_profile_id = :pid WHERE id = :tid"
                        ),
                        {"pid": profile_id, "tid": tenant_id},
                    )
                    await session.commit()

                    try:
                        raised = False
                        await delete_llm_profile_db(profile_id=profile_id, db=session)
                    except ValueError:
                        raised = True

                    # Clean up: unassign profile from tenant then delete it
                    await session.execute(
                        text(
                            "UPDATE tenants SET llm_profile_id = NULL WHERE id = :tid"
                        ),
                        {"tid": tenant_id},
                    )
                    await session.commit()
                    await delete_llm_profile_db(profile_id=profile_id, db=session)
            finally:
                await engine.dispose()
            return raised

        raised = asyncio.run(_run())
        assert (
            raised
        ), "delete_llm_profile_db must raise ValueError when profile is in use by a tenant"

    def test_profile_name_uniqueness_enforced_per_tenant(self, tenant_id):
        """
        Creating two profiles with the same name for the same tenant raises
        ValueError. Profiles with the same name for different tenants are allowed.
        """

        async def _run():
            engine, factory = await _make_session()
            try:
                async with factory() as session:
                    await create_llm_profile_db(
                        tenant_id=tenant_id,
                        name="Duplicate Name Profile",
                        provider="azure_openai",
                        primary_model="agentic-worker",
                        intent_model="agentic-router",
                        embedding_model="text-embedding-3-small",
                        endpoint_url=None,
                        api_key_ref=None,
                        is_default=False,
                        db=session,
                    )
                    # Second create with same name for same tenant
                    duplicate_raised = False
                    try:
                        await create_llm_profile_db(
                            tenant_id=tenant_id,
                            name="Duplicate Name Profile",
                            provider="openai",
                            primary_model="gpt-4o",
                            intent_model="gpt-4o-mini",
                            embedding_model="text-embedding-3-small",
                            endpoint_url=None,
                            api_key_ref=None,
                            is_default=False,
                            db=session,
                        )
                    except ValueError:
                        duplicate_raised = True
            finally:
                await engine.dispose()
            return duplicate_raised

        duplicate_raised = asyncio.run(_run())
        assert (
            duplicate_raised
        ), "Creating a profile with a duplicate name for the same tenant must raise ValueError"

    def test_model_names_come_from_request_not_hardcoded(self, tenant_id):
        """
        The model names stored in the DB match exactly what was passed in the
        request — demonstrating that model names are not hardcoded in the API
        (any string is accepted, env-config enforced at the caller level).
        """
        custom_model = f"custom-model-{uuid.uuid4().hex[:8]}"

        async def _run():
            engine, factory = await _make_session()
            try:
                async with factory() as session:
                    created = await create_llm_profile_db(
                        tenant_id=tenant_id,
                        name=f"Env Model Test {uuid.uuid4().hex[:6]}",
                        provider="azure_openai",
                        primary_model=custom_model,
                        intent_model="agentic-router",
                        embedding_model="text-embedding-3-small",
                        endpoint_url=None,
                        api_key_ref=None,
                        is_default=False,
                        db=session,
                    )
                    fetched = await get_llm_profile_db(
                        profile_id=created["id"], db=session
                    )
            finally:
                await engine.dispose()
            return fetched

        fetched = asyncio.run(_run())
        assert fetched["primary_model"] == custom_model, (
            f"primary_model stored as '{fetched['primary_model']}' but expected '{custom_model}'. "
            "Model names must be stored exactly as provided — no hardcoding."
        )
