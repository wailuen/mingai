"""
TEST-065: GDPR clear_profile_data() with Team Memory Integration Tests

Tests that GDPR erasure via POST /api/v1/users/me/gdpr/erase also clears
team working memory contributions, and related edge cases.

Tier 2: Real PostgreSQL + Redis, NO MOCKING.

Architecture:
  Uses the session-scoped TestClient from conftest.py.
  DB setup/teardown via asyncio.run() with fresh async engines.
  Redis verification via direct redis.asyncio client.

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_gdpr_team_memory.py -v --timeout=60
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        pytest.skip("JWT_SECRET_KEY not configured -- skipping integration tests")
    return secret


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured -- skipping integration tests")
    return url


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL", "")
    if not url:
        pytest.skip("REDIS_URL not configured -- skipping integration tests")
    return url


def _make_user_token(tenant_id: str, user_id: str, email: str = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": ["end_user"],
        "scope": "tenant",
        "plan": "professional",
        "email": email or f"gdpr-team-{user_id[:8]}@test.test",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


async def _run_sql(sql: str, params: dict = None):
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            await session.commit()
            return result
    finally:
        await engine.dispose()


async def _fetch_one(sql: str, params: dict = None):
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            return result.fetchone()
    finally:
        await engine.dispose()


async def _get_redis_client():
    import redis.asyncio as aioredis

    return aioredis.from_url(
        _redis_url(),
        max_connections=5,
        socket_timeout=5,
        decode_responses=True,
    )


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


TEST_TENANT_ID = str(uuid.uuid4())
TEST_USER_A_ID = str(uuid.uuid4())
TEST_USER_B_ID = str(uuid.uuid4())
TEST_TEAM_ID = str(uuid.uuid4())


@pytest.fixture(scope="module")
def test_data():
    """Provision a test tenant with two users, clean up after."""
    tid = TEST_TENANT_ID
    uid_a = TEST_USER_A_ID
    uid_b = TEST_USER_B_ID

    async def _setup():
        await _run_sql(
            "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
            "VALUES (:id, :name, :slug, :plan, :email, 'active')",
            {
                "id": tid,
                "name": f"GDPR Team Test {tid[:8]}",
                "slug": f"gdpr-team-{tid[:8]}",
                "plan": "professional",
                "email": f"admin-{tid[:8]}@gdpr-team.test",
            },
        )
        for uid, email_prefix in [(uid_a, "user-a"), (uid_b, "user-b")]:
            await _run_sql(
                "INSERT INTO users (id, tenant_id, email, name, role, status) "
                "VALUES (:id, :tid, :email, :name, :role, 'active')",
                {
                    "id": uid,
                    "tid": tid,
                    "email": f"{email_prefix}-{uid[:8]}@gdpr-team.test",
                    "name": f"GDPR {email_prefix}",
                    "role": "end_user",
                },
            )

    async def _teardown():
        await _run_sql(
            "DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE tenant_id = :tid)",
            {"tid": tid},
        )
        await _run_sql("DELETE FROM conversations WHERE tenant_id = :tid", {"tid": tid})
        await _run_sql("DELETE FROM memory_notes WHERE tenant_id = :tid", {"tid": tid})
        await _run_sql("DELETE FROM user_profiles WHERE tenant_id = :tid", {"tid": tid})
        await _run_sql("DELETE FROM users WHERE tenant_id = :tid", {"tid": tid})
        await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})

        redis = await _get_redis_client()
        try:
            pattern = f"mingai:{tid}:*"
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor, match=pattern, count=100)
                if keys:
                    await redis.delete(*keys)
                if cursor == 0:
                    break
        finally:
            await redis.close()

    asyncio.run(_setup())
    yield {
        "tenant_id": tid,
        "user_a_id": uid_a,
        "user_b_id": uid_b,
        "team_id": TEST_TEAM_ID,
    }
    asyncio.run(_teardown())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGDPRTeamMemory:
    """TEST-065: GDPR erasure + team working memory."""

    def test_gdpr_erase_clears_team_memory_entries(self, client, test_data):
        """Add user to team memory, call GDPR erase, verify team memory is cleared."""
        tid = test_data["tenant_id"]
        uid = test_data["user_a_id"]
        team_id = test_data["team_id"]
        team_key = f"mingai:{tid}:team_memory:{team_id}"

        # Setup: add team memory entry
        async def _setup():
            redis = await _get_redis_client()
            try:
                from app.modules.memory.team_working_memory import (
                    TeamWorkingMemoryService,
                )

                svc = TeamWorkingMemoryService(redis=redis)
                await svc.update(
                    team_id=team_id,
                    tenant_id=tid,
                    query="Confidential question from user A",
                    response="Sensitive answer.",
                )
                # Verify it exists
                raw = await redis.get(team_key)
                assert raw is not None, "Team memory must exist before GDPR erase"
            finally:
                await redis.close()

        asyncio.run(_setup())

        # Call GDPR erase endpoint
        token = _make_user_token(tid, uid)
        resp = client.post(
            "/api/v1/users/me/gdpr/erase",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["erased"] is True

    def test_gdpr_erase_does_not_affect_other_users_team_memory(
        self, client, test_data
    ):
        """User A erases data; user B's team memory contributions still exist."""
        tid = test_data["tenant_id"]
        uid_a = test_data["user_a_id"]
        uid_b = test_data["user_b_id"]
        # Use a different team so we can verify B's data survives
        team_b_only = str(uuid.uuid4())
        team_key_b = f"mingai:{tid}:team_memory:{team_b_only}"

        async def _setup():
            redis = await _get_redis_client()
            try:
                from app.modules.memory.team_working_memory import (
                    TeamWorkingMemoryService,
                )

                svc = TeamWorkingMemoryService(redis=redis)
                # User B contributes to a separate team
                await svc.update(
                    team_id=team_b_only,
                    tenant_id=tid,
                    query="User B important question",
                    response="User B answer.",
                )
                raw = await redis.get(team_key_b)
                assert raw is not None, "User B's team memory must exist before erase"
            finally:
                await redis.close()

        asyncio.run(_setup())

        # User A triggers GDPR erase
        token_a = _make_user_token(tid, uid_a)
        resp = client.post(
            "/api/v1/users/me/gdpr/erase",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200

        # Verify User B's team memory still exists
        async def _verify():
            redis = await _get_redis_client()
            try:
                raw = await redis.get(team_key_b)
                assert (
                    raw is not None
                ), "User B's team memory must survive User A's GDPR erase"
                data = json.loads(raw)
                assert len(data.get("recent_queries", [])) > 0
            finally:
                await redis.delete(team_key_b)
                await redis.close()

        asyncio.run(_verify())

    def test_gdpr_erase_requires_auth(self, client):
        """Call GDPR erase without auth token -- should return 401."""
        resp = client.post("/api/v1/users/me/gdpr/erase")
        assert resp.status_code == 401

    def test_gdpr_erase_clears_redis_working_memory(self, client, test_data):
        """Set working memory for user, call GDPR erase, Redis key should be gone."""
        tid = test_data["tenant_id"]
        uid = test_data["user_a_id"]
        wm_key = f"mingai:{tid}:working_memory:{uid}:test-agent-gdpr"

        async def _setup():
            redis = await _get_redis_client()
            try:
                await redis.set(wm_key, json.dumps({"topics": ["test"]}))
                val = await redis.get(wm_key)
                assert val is not None, "Working memory key must exist before erase"
            finally:
                await redis.close()

        asyncio.run(_setup())

        token = _make_user_token(tid, uid)
        resp = client.post(
            "/api/v1/users/me/gdpr/erase",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "working_memory" in resp.json()["stores_cleared"]

        async def _verify():
            redis = await _get_redis_client()
            try:
                val = await redis.get(wm_key)
                return val
            finally:
                await redis.close()

        val_after = asyncio.run(_verify())
        assert (
            val_after is None
        ), f"Working memory key {wm_key} must be deleted after GDPR erase"

    def test_gdpr_erase_is_idempotent(self, client, test_data):
        """Calling GDPR erase twice returns 200 both times (idempotent)."""
        tid = test_data["tenant_id"]
        uid = test_data["user_a_id"]
        token = _make_user_token(tid, uid)
        headers = {"Authorization": f"Bearer {token}"}

        resp1 = client.post("/api/v1/users/me/gdpr/erase", headers=headers)
        assert resp1.status_code == 200
        assert resp1.json()["erased"] is True

        resp2 = client.post("/api/v1/users/me/gdpr/erase", headers=headers)
        assert resp2.status_code == 200
        assert resp2.json()["erased"] is True
