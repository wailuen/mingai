"""
Integration test: Slot assignment validation in LLMProfileService.

Verifies that the service correctly rejects:
- Assigning unpublished library entries (status='draft')
- Assigning deprecated library entries
- Library entries that don't exist

Tier 2: No mocking — requires running PostgreSQL + Redis.
"""
import asyncio
import json
import os
import uuid
from typing import Optional

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.llm_profiles.service import LLMProfileService, LLMProfileValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


async def _run_sql(sql: str, params: Optional[dict] = None) -> None:
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _create_library_entry(
    status: str,
    eligible_slots: Optional[list] = None,
    owner_tenant_id: Optional[str] = None,
) -> str:
    entry_id = str(uuid.uuid4())
    caps = json.dumps({"eligible_slots": eligible_slots or ["chat", "intent"]})
    await _run_sql(
        "INSERT INTO llm_library "
        "(id, provider, model_name, display_name, plan_tier, endpoint_url, "
        "api_key_encrypted, api_key_last4, status, capabilities, "
        "is_byollm, owner_tenant_id, created_at, updated_at) "
        "VALUES "
        "(:id, 'openai_direct', :model, :display, 'professional', 'https://api.openai.com/v1', "
        "'enc_sav_test', '9999', :status, "
        "CAST(:caps AS jsonb), :is_byollm, :owner, NOW(), NOW())",
        {
            "id": entry_id,
            "model": f"model-{status}-{entry_id[:6]}",
            "display": f"SAV Test {status}",
            "status": status,
            "caps": caps,
            "is_byollm": owner_tenant_id is not None,
            "owner": owner_tenant_id,
        },
    )
    return entry_id


async def _create_platform_profile(name: str) -> str:
    profile_id = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO llm_profiles "
        "(id, name, description, status, "
        "chat_library_id, intent_library_id, vision_library_id, agent_library_id, "
        "chat_params, intent_params, vision_params, agent_params, "
        "chat_traffic_split, intent_traffic_split, vision_traffic_split, agent_traffic_split, "
        "is_platform_default, plan_tiers, owner_tenant_id, created_by, created_at, updated_at) "
        "VALUES "
        "(:id, :name, NULL, 'active', "
        "NULL, NULL, NULL, NULL, "
        "'{}', '{}', '{}', '{}', "
        "'[]', '[]', '[]', '[]', "
        "false, '{}', NULL, :actor, NOW(), NOW())",
        {"id": profile_id, "name": name, "actor": str(uuid.uuid4())},
    )
    return profile_id


async def _cleanup_entries(entry_ids: list) -> None:
    for eid in entry_ids:
        await _run_sql("DELETE FROM llm_library WHERE id = :id", {"id": eid})


async def _cleanup_profile(profile_id: str) -> None:
    await _run_sql("DELETE FROM llm_profiles WHERE id = :id", {"id": profile_id})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def slot_validation_setup():
    """
    Creates:
      - One library entry with status='draft' (unpublished)
      - One library entry with status='deprecated'
      - One library entry that is published (for contrast)
      - A platform profile to assign to

    Yields (profile_id, draft_entry_id, deprecated_entry_id, published_entry_id).
    """
    draft_entry = asyncio.run(_create_library_entry("draft"))
    deprecated_entry = asyncio.run(_create_library_entry("deprecated"))
    published_entry = asyncio.run(_create_library_entry("published"))
    profile_id = asyncio.run(
        _create_platform_profile(f"SAV Profile {uuid.uuid4().hex[:6]}")
    )
    yield profile_id, draft_entry, deprecated_entry, published_entry
    asyncio.run(_cleanup_profile(profile_id))
    asyncio.run(_cleanup_entries([draft_entry, deprecated_entry, published_entry]))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSlotAssignmentValidation:
    """Service rejects invalid slot assignments at the validation layer."""

    def test_assigning_draft_entry_raises_validation_error(self, slot_validation_setup):
        """update_platform_profile raises LLMProfileValidationError for draft entry."""
        profile_id, draft_entry, deprecated_entry, published_entry = slot_validation_setup

        engine = create_async_engine(_db_url(), echo=False)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async def _run():
            try:
                async with factory() as db:
                    svc = LLMProfileService()
                    try:
                        await svc.update_platform_profile(
                            profile_id,
                            updates={"chat_library_id": draft_entry},
                            actor_id=str(uuid.uuid4()),
                            db=db,
                        )
                        return None  # No error — test will fail
                    except LLMProfileValidationError as exc:
                        return str(exc)
                    finally:
                        await db.rollback()
            finally:
                await engine.dispose()

        error_msg = asyncio.run(_run())
        assert error_msg is not None, (
            "Expected LLMProfileValidationError for draft entry, no error raised"
        )
        assert draft_entry in error_msg or "not published" in error_msg.lower(), (
            f"Error message should reference the library_id or 'not published': {error_msg}"
        )

    def test_assigning_deprecated_entry_raises_validation_error(self, slot_validation_setup):
        """update_platform_profile raises LLMProfileValidationError for deprecated entry."""
        profile_id, draft_entry, deprecated_entry, published_entry = slot_validation_setup

        engine = create_async_engine(_db_url(), echo=False)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async def _run():
            try:
                async with factory() as db:
                    svc = LLMProfileService()
                    try:
                        await svc.update_platform_profile(
                            profile_id,
                            updates={"intent_library_id": deprecated_entry},
                            actor_id=str(uuid.uuid4()),
                            db=db,
                        )
                        return None
                    except LLMProfileValidationError as exc:
                        return str(exc)
                    finally:
                        await db.rollback()
            finally:
                await engine.dispose()

        error_msg = asyncio.run(_run())
        assert error_msg is not None, (
            "Expected LLMProfileValidationError for deprecated entry, no error raised"
        )
        assert deprecated_entry in error_msg or "not published" in error_msg.lower(), (
            f"Error message should reference the library_id or status: {error_msg}"
        )

    def test_assigning_nonexistent_entry_raises_validation_error(self, slot_validation_setup):
        """update_platform_profile raises LLMProfileValidationError for missing entry."""
        profile_id, draft_entry, deprecated_entry, published_entry = slot_validation_setup
        nonexistent_id = str(uuid.uuid4())

        engine = create_async_engine(_db_url(), echo=False)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async def _run():
            try:
                async with factory() as db:
                    svc = LLMProfileService()
                    try:
                        await svc.update_platform_profile(
                            profile_id,
                            updates={"chat_library_id": nonexistent_id},
                            actor_id=str(uuid.uuid4()),
                            db=db,
                        )
                        return None
                    except LLMProfileValidationError as exc:
                        return str(exc)
                    finally:
                        await db.rollback()
            finally:
                await engine.dispose()

        error_msg = asyncio.run(_run())
        assert error_msg is not None, (
            "Expected LLMProfileValidationError for nonexistent entry, no error raised"
        )
        assert nonexistent_id in error_msg or "not found" in error_msg.lower(), (
            f"Error message should reference the missing library_id: {error_msg}"
        )

    def test_assigning_published_entry_succeeds(self, slot_validation_setup):
        """Assigning a published entry to a slot succeeds without error."""
        profile_id, draft_entry, deprecated_entry, published_entry = slot_validation_setup

        engine = create_async_engine(_db_url(), echo=False)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async def _run():
            try:
                async with factory() as db:
                    svc = LLMProfileService()
                    try:
                        result = await svc.update_platform_profile(
                            profile_id,
                            updates={"chat_library_id": published_entry},
                            actor_id=str(uuid.uuid4()),
                            db=db,
                        )
                        await db.commit()
                        return result
                    except LLMProfileValidationError as exc:
                        return f"ERROR: {exc}"
            finally:
                await engine.dispose()

        result = asyncio.run(_run())
        assert not isinstance(result, str) or not result.startswith("ERROR"), (
            f"Published entry assignment should succeed, got: {result}"
        )
        assert isinstance(result, dict), (
            f"Expected dict response from update, got: {type(result)}"
        )
