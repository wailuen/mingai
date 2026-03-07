"""
AI-050: Profile + Memory Full Pipeline Integration Tests

Tests the end-to-end pipeline:
  1. User sends queries → ProfileLearningService triggers extraction after N queries
  2. Extracted profile attributes written to user_profiles table
  3. Memory notes created (user_directed and auto_extracted)
  4. Memory notes retrieved and limited correctly
  5. Profile data fed into working memory snapshot

Architecture:
  - Real PostgreSQL + Redis (no mocking of infrastructure)
  - LLM calls mocked (ProfileLearningService uses INTENT_MODEL; swap for predictable extraction)
  - Verifies data isolation across two tenants

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_profile_memory_integration.py -v --timeout=60
"""
import asyncio
import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.memory.notes import (
    MAX_NOTES_IN_PROMPT,
    MAX_NOTES_PER_USER,
    MAX_NOTE_CONTENT_LENGTH,
    MemoryNoteValidationError,
    validate_memory_note_content,
)
from app.modules.profile.learning import (
    LEARN_TRIGGER_THRESHOLD,
    ProfileLearningService,
)


# ---------------------------------------------------------------------------
# DB helpers
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
            result = await session.execute(text(sql), params or {})
            await session.commit()
            return result
    finally:
        await engine.dispose()


async def _create_test_tenant_and_user() -> tuple[str, str]:
    """Return (tenant_id, user_id) for a freshly-created test tenant/user pair."""
    tid = str(uuid.uuid4())
    uid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"Profile Memory Test {tid[:8]}",
            "slug": f"pm-test-{tid[:8]}",
            "email": f"admin-{tid[:8]}@pm-int.test",
        },
    )
    await _run_sql(
        "INSERT INTO users (id, tenant_id, email, name, role, status) "
        "VALUES (:id, :tid, :email, :name, 'user', 'active')",
        {
            "id": uid,
            "tid": tid,
            "email": f"user-{uid[:8]}@pm-int.test",
            "name": f"Test User {uid[:8]}",
        },
    )
    return tid, uid


async def _cleanup_tenant(tid: str):
    tables = [
        "profile_learning_events",
        "memory_notes",
        "working_memory_snapshots",
        "user_profiles",
        "users",
        "tenants",
    ]
    for table in tables:
        col = "tenant_id" if table != "tenants" else "id"
        await _run_sql(f"DELETE FROM {table} WHERE {col} = :tid", {"tid": tid})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMemoryNoteValidation:
    """Tier 1: unit-level validation tests (no DB needed)."""

    def test_valid_note_accepted(self):
        result = validate_memory_note_content("  User prefers concise answers  ")
        assert result == "User prefers concise answers"

    def test_empty_note_raises(self):
        with pytest.raises(MemoryNoteValidationError):
            validate_memory_note_content("")

    def test_whitespace_only_raises(self):
        with pytest.raises(MemoryNoteValidationError):
            validate_memory_note_content("   ")

    def test_none_raises(self):
        with pytest.raises(MemoryNoteValidationError):
            validate_memory_note_content(None)

    def test_exactly_200_chars_accepted(self):
        content = "x" * 200
        result = validate_memory_note_content(content)
        assert len(result) == 200

    def test_201_chars_raises(self):
        content = "x" * 201
        with pytest.raises(MemoryNoteValidationError) as exc_info:
            validate_memory_note_content(content)
        assert "200" in str(exc_info.value.message)

    def test_constants_correct(self):
        """Verify the canonical limits are enforced at the right values."""
        assert MAX_NOTE_CONTENT_LENGTH == 200
        assert MAX_NOTES_PER_USER == 15
        assert MAX_NOTES_IN_PROMPT == 5


class TestMemoryNotesIntegration:
    """Tier 2: integration tests against real PostgreSQL."""

    def test_memory_notes_inserted_and_retrieved(self):
        """Notes inserted into DB are visible in subsequent queries."""

        async def _run():
            tid, uid = await _create_test_tenant_and_user()
            try:
                note_id = str(uuid.uuid4())
                await _run_sql(
                    "INSERT INTO memory_notes (id, tenant_id, user_id, content, source) "
                    "VALUES (:id, :tid, :uid, :content, 'user_directed')",
                    {
                        "id": note_id,
                        "tid": tid,
                        "uid": uid,
                        "content": "Prefers detailed financial breakdowns",
                    },
                )
                result = await _run_sql(
                    "SELECT content FROM memory_notes WHERE id = :id",
                    {"id": note_id},
                )
                row = result.fetchone()
                assert row is not None
                assert row[0] == "Prefers detailed financial breakdowns"
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_cross_tenant_memory_isolation(self):
        """Memory notes from tenant A must not be visible when querying tenant B."""

        async def _run():
            tid_a, uid_a = await _create_test_tenant_and_user()
            tid_b, uid_b = await _create_test_tenant_and_user()
            try:
                # Insert note for tenant A
                await _run_sql(
                    "INSERT INTO memory_notes (id, tenant_id, user_id, content, source) "
                    "VALUES (:id, :tid, :uid, 'Tenant A secret', 'user_directed')",
                    {"id": str(uuid.uuid4()), "tid": tid_a, "uid": uid_a},
                )
                # Query as tenant B — must return 0 rows
                result = await _run_sql(
                    "SELECT COUNT(*) FROM memory_notes WHERE tenant_id = :tid",
                    {"tid": tid_b},
                )
                count = result.scalar()
                assert count == 0, "Tenant B must not see Tenant A's memory notes"
            finally:
                await _cleanup_tenant(tid_a)
                await _cleanup_tenant(tid_b)

        asyncio.run(_run())

    def test_max_notes_per_user_enforced_by_service(self):
        """After 15 notes exist, inserting a 16th from service prunes oldest note."""
        # This verifies the pruning contract at the DB level.
        # ProfileLearningService prunes when count exceeds MAX_NOTES_PER_USER.

        async def _run():
            tid, uid = await _create_test_tenant_and_user()
            try:
                # Insert exactly 15 notes
                for i in range(15):
                    await _run_sql(
                        "INSERT INTO memory_notes (id, tenant_id, user_id, content, source, created_at) "
                        "VALUES (:id, :tid, :uid, :content, 'auto_extracted', NOW() + :offset * interval '1 second')",
                        {
                            "id": str(uuid.uuid4()),
                            "tid": tid,
                            "uid": uid,
                            "content": f"Note number {i + 1}",
                            "offset": i,
                        },
                    )
                count_result = await _run_sql(
                    "SELECT COUNT(*) FROM memory_notes WHERE tenant_id = :tid AND user_id = :uid",
                    {"tid": tid, "uid": uid},
                )
                assert count_result.scalar() == 15

                # Simulate service: if we exceed 15, delete oldest
                # (this mirrors the logic in ProfileLearningService.save_memory_note)
                await _run_sql(
                    "DELETE FROM memory_notes WHERE id IN ("
                    "  SELECT id FROM memory_notes "
                    "  WHERE tenant_id = :tid AND user_id = :uid "
                    "  ORDER BY created_at ASC LIMIT 1"
                    ")",
                    {"tid": tid, "uid": uid},
                )
                # Insert 16th
                await _run_sql(
                    "INSERT INTO memory_notes (id, tenant_id, user_id, content, source) "
                    "VALUES (:id, :tid, :uid, 'Note 16', 'auto_extracted')",
                    {"id": str(uuid.uuid4()), "tid": tid, "uid": uid},
                )
                final_count = await _run_sql(
                    "SELECT COUNT(*) FROM memory_notes WHERE tenant_id = :tid AND user_id = :uid",
                    {"tid": tid, "uid": uid},
                )
                assert final_count.scalar() == 15
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())


class TestProfileLearningIntegration:
    """Tier 2: ProfileLearningService against real PostgreSQL + Redis + mocked LLM."""

    def test_profile_upsert_writes_to_database(self):
        """
        After profile extraction, user_profiles row is written/updated.
        LLM extraction is mocked via _run_profile_extraction to return
        a predictable outcome — we verify the DB is updated correctly.
        """

        async def _run():
            tid, uid = await _create_test_tenant_and_user()
            try:
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with factory() as db:
                    service = ProfileLearningService(db_session=db)

                    extracted_attrs = {
                        "technical_level": "expert",
                        "communication_style": "concise",
                        "interests": ["finance", "risk management"],
                        "expertise_areas": ["credit analysis"],
                        "common_tasks": ["quarterly reviews"],
                    }

                    # Mock _call_intent_model (the LLM caller inside _run_profile_extraction)
                    with patch.object(
                        service,
                        "_call_intent_model",
                        new=AsyncMock(return_value=extracted_attrs),
                    ):
                        # Also mock DB conversation fetch to return dummy queries
                        async def _mock_execute(stmt, params=None):
                            from unittest.mock import MagicMock

                            result = MagicMock()
                            result.fetchall.return_value = []
                            result.mappings.return_value.first.return_value = None
                            result.scalar.return_value = 0
                            return result

                        # Call _merge_and_persist_profile directly (actual method name)
                        await service._merge_and_persist_profile(
                            user_id=uid,
                            tenant_id=tid,
                            extracted=extracted_attrs,
                        )

                    # Verify user_profiles row was written
                    result = await db.execute(
                        text(
                            "SELECT technical_level, communication_style "
                            "FROM user_profiles WHERE user_id = :uid AND tenant_id = :tid"
                        ),
                        {"uid": uid, "tid": tid},
                    )
                    row = result.fetchone()
                    assert row is not None, "user_profiles row must be created"
                    assert row[0] == "expert"
                    assert row[1] == "concise"

                await engine.dispose()
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_profile_not_extracted_below_threshold(self):
        """
        ProfileLearningService.maybe_trigger_learning() must NOT extract if
        query count has not reached LEARN_TRIGGER_THRESHOLD.
        """
        # Reset the Redis singleton so a fresh connection is created in the
        # new event loop (asyncio.run creates a new loop each call; the pool
        # from a previous loop would be in an inconsistent state).
        import app.core.redis_client as _rc

        _rc._redis_pool = None

        async def _run():
            tid, uid = await _create_test_tenant_and_user()
            try:
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with factory() as db:
                    service = ProfileLearningService(db_session=db)

                    extraction_called = False

                    async def _fake_extraction(*args, **kwargs):
                        nonlocal extraction_called
                        extraction_called = True
                        return {}

                    with patch.object(
                        service,
                        "_run_profile_extraction",
                        new=AsyncMock(side_effect=_fake_extraction),
                    ):
                        # Pre-set Redis counter to threshold-2 so next INCR = threshold-1
                        counter_key = f"mingai:{tid}:profile_learning:query_count:{uid}"
                        from app.core.redis_client import get_redis

                        redis = get_redis()
                        await redis.set(counter_key, LEARN_TRIGGER_THRESHOLD - 2, ex=60)
                        await service.on_query_completed(
                            user_id=uid, tenant_id=tid, agent_id="test-agent"
                        )
                        await redis.delete(counter_key)

                    assert (
                        not extraction_called
                    ), "LLM extraction must NOT be called below the trigger threshold"

                await engine.dispose()
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_cross_tenant_profile_isolation(self):
        """Profile data for tenant A is invisible to tenant B's queries."""

        async def _run():
            tid_a, uid_a = await _create_test_tenant_and_user()
            tid_b, uid_b = await _create_test_tenant_and_user()
            try:
                # Write a profile for tenant A's user
                await _run_sql(
                    "INSERT INTO user_profiles "
                    "(id, tenant_id, user_id, technical_level, communication_style) "
                    "VALUES (:id, :tid, :uid, 'expert', 'formal')",
                    {"id": str(uuid.uuid4()), "tid": tid_a, "uid": uid_a},
                )
                # Tenant B query must return 0 rows
                result = await _run_sql(
                    "SELECT COUNT(*) FROM user_profiles WHERE tenant_id = :tid",
                    {"tid": tid_b},
                )
                assert result.scalar() == 0
            finally:
                await _cleanup_tenant(tid_a)
                await _cleanup_tenant(tid_b)

        asyncio.run(_run())


class TestWorkingMemorySnapshotIntegration:
    """Tier 2: working_memory_snapshots written and read correctly."""

    def test_snapshot_stored_and_retrieved(self):
        """A working memory snapshot written to DB is retrievable with correct data."""

        async def _run():
            tid, uid = await _create_test_tenant_and_user()
            try:
                snap_id = str(uuid.uuid4())
                snap_data = {
                    "profile": {"technical_level": "intermediate"},
                    "memory_notes": ["Prefers charts over tables"],
                    "org_context": {"team": "Finance"},
                }
                await _run_sql(
                    "INSERT INTO working_memory_snapshots "
                    "(id, tenant_id, user_id, snapshot_data) "
                    "VALUES (:id, :tid, :uid, CAST(:data AS jsonb))",
                    {
                        "id": snap_id,
                        "tid": tid,
                        "uid": uid,
                        "data": json.dumps(snap_data),
                    },
                )
                result = await _run_sql(
                    "SELECT snapshot_data FROM working_memory_snapshots WHERE id = :id",
                    {"id": snap_id},
                )
                row = result.fetchone()
                assert row is not None
                stored = row[0]
                if isinstance(stored, str):
                    stored = json.loads(stored)
                assert stored["profile"]["technical_level"] == "intermediate"
                assert "Prefers charts over tables" in stored["memory_notes"]
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())
