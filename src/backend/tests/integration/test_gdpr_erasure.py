"""
TEST-054: GDPR Erasure Integration Tests

Tests that POST /api/v1/users/me/gdpr/erase clears ALL user data:
1. PostgreSQL user_profiles row is deleted/anonymized
2. Redis working memory keys are cleared
3. Redis profile cache keys are cleared

Tier 2: Real PostgreSQL + Redis, NO MOCKING.

Architecture note:
    Uses sync TestClient (session-scoped from conftest) + asyncio.run() for
    DB/Redis setup and teardown. This avoids event loop conflicts with the
    module-level SQLAlchemy engine in session.py.

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_gdpr_erasure.py -v -m integration
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        pytest.skip("JWT_SECRET_KEY not configured — skipping integration tests")
    return secret


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL", "")
    if not url:
        pytest.skip("REDIS_URL not configured — skipping integration tests")
    return url


def _make_user_token(tenant_id: str, user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": ["end_user"],
        "scope": "tenant",
        "plan": "professional",
        "email": f"gdpr-test@{tenant_id[:8]}.test",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


async def _run_sql(sql: str, params: dict | None = None):
    """Execute SQL against real DB using a fresh async engine."""
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _fetch_one(sql: str, params: dict | None = None):
    """Fetch a single row from real DB."""
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            return result.fetchone()
    finally:
        await engine.dispose()


async def _get_redis_client():
    """Create a direct redis.asyncio client for test verification."""
    import redis.asyncio as aioredis

    return aioredis.from_url(
        _redis_url(),
        max_connections=5,
        socket_timeout=5,
        decode_responses=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_USER_ID = str(uuid.uuid4())
TEST_TENANT_ID = str(uuid.uuid4())


@pytest.fixture(scope="module")
def tenant_and_user():
    """Provision a real test tenant + user once per module, clean up after."""
    tid = TEST_TENANT_ID
    uid = TEST_USER_ID

    async def _setup():
        # Create tenant
        await _run_sql(
            "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
            "VALUES (:id, :name, :slug, :plan, :email, 'active')",
            {
                "id": tid,
                "name": f"GDPR Erasure Test {tid[:8]}",
                "slug": f"gdpr-test-{tid[:8]}",
                "plan": "professional",
                "email": f"test-{tid[:8]}@gdpr-test.test",
            },
        )
        # Create user
        await _run_sql(
            "INSERT INTO users (id, tenant_id, email, name, role, status) "
            "VALUES (:id, :tid, :email, :name, :role, 'active')",
            {
                "id": uid,
                "tid": tid,
                "email": f"gdpr-test@{tid[:8]}.test",
                "name": "GDPR Test User",
                "role": "end_user",
            },
        )

    async def _teardown():
        # Clean up in reverse dependency order
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

        # Clean up any leftover Redis keys
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
    yield {"tenant_id": tid, "user_id": uid}
    asyncio.run(_teardown())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGDPREraseAuth:
    """Auth enforcement on GDPR erase endpoint."""

    def test_gdpr_erase_requires_auth(self, client):
        """No token returns 401."""
        resp = client.post("/api/v1/users/me/gdpr/erase")
        assert resp.status_code == 401


class TestGDPREraseProfile:
    """Verify PostgreSQL user_profiles row is deleted."""

    def test_gdpr_erase_clears_profile(self, client, tenant_and_user):
        """Create user_profiles row, call erase, verify row gone from DB."""
        tid = tenant_and_user["tenant_id"]
        uid = tenant_and_user["user_id"]

        # Insert a user_profiles row
        asyncio.run(
            _run_sql(
                "INSERT INTO user_profiles (user_id, tenant_id, technical_level) "
                "VALUES (:uid, :tid, 'advanced') "
                "ON CONFLICT (tenant_id, user_id) DO UPDATE SET technical_level = 'advanced'",
                {"uid": uid, "tid": tid},
            )
        )

        # Verify profile exists before erase
        row = asyncio.run(
            _fetch_one(
                "SELECT user_id FROM user_profiles "
                "WHERE user_id = :uid AND tenant_id = :tid",
                {"uid": uid, "tid": tid},
            )
        )
        assert row is not None, "user_profiles row must exist before erase"

        # Call GDPR erase
        token = _make_user_token(tid, uid)
        resp = client.post(
            "/api/v1/users/me/gdpr/erase",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["erased"] is True
        assert "postgresql" in data["stores_cleared"]

        # Verify profile row is deleted
        row_after = asyncio.run(
            _fetch_one(
                "SELECT user_id FROM user_profiles "
                "WHERE user_id = :uid AND tenant_id = :tid",
                {"uid": uid, "tid": tid},
            )
        )
        assert row_after is None, "user_profiles row must be deleted after GDPR erase"


class TestGDPREraseRedisWorkingMemory:
    """Verify Redis working memory keys are cleared."""

    def test_gdpr_erase_clears_working_memory_redis(self, client, tenant_and_user):
        """Write a working memory Redis key, call erase, verify key gone."""
        tid = tenant_and_user["tenant_id"]
        uid = tenant_and_user["user_id"]
        wm_key = f"mingai:{tid}:working_memory:{uid}:test-agent"

        async def _setup_wm():
            redis = await _get_redis_client()
            try:
                await redis.set(wm_key, "test-working-memory-data")
                val = await redis.get(wm_key)
                assert val is not None, "Working memory key must exist before erase"
            finally:
                await redis.close()

        asyncio.run(_setup_wm())

        # Call GDPR erase
        token = _make_user_token(tid, uid)
        resp = client.post(
            "/api/v1/users/me/gdpr/erase",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "working_memory" in resp.json()["stores_cleared"]

        # Verify working memory key is deleted
        async def _verify_wm():
            redis = await _get_redis_client()
            try:
                val = await redis.get(wm_key)
                return val
            finally:
                await redis.close()

        val_after = asyncio.run(_verify_wm())
        assert (
            val_after is None
        ), f"Working memory key {wm_key} must be deleted after GDPR erase"


class TestGDPREraseRedisProfileCache:
    """Verify Redis profile cache keys are cleared."""

    def test_gdpr_erase_clears_profile_cache_redis(self, client, tenant_and_user):
        """Write a profile cache Redis key, call erase, verify key gone."""
        tid = tenant_and_user["tenant_id"]
        uid = tenant_and_user["user_id"]
        l2_key = f"mingai:{tid}:profile_learning:profile:{uid}"

        async def _setup_cache():
            redis = await _get_redis_client()
            try:
                await redis.set(l2_key, '{"cached": true}')
                val = await redis.get(l2_key)
                assert val is not None, "Profile cache key must exist before erase"
            finally:
                await redis.close()

        asyncio.run(_setup_cache())

        # Call GDPR erase
        token = _make_user_token(tid, uid)
        resp = client.post(
            "/api/v1/users/me/gdpr/erase",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "redis_l2" in resp.json()["stores_cleared"]

        # Verify profile cache key is deleted
        async def _verify_cache():
            redis = await _get_redis_client()
            try:
                val = await redis.get(l2_key)
                return val
            finally:
                await redis.close()

        val_after = asyncio.run(_verify_cache())
        assert (
            val_after is None
        ), f"Profile cache key {l2_key} must be deleted after GDPR erase"


class TestGDPREraseIdempotent:
    """Verify GDPR erase is idempotent."""

    def test_gdpr_erase_is_idempotent(self, client, tenant_and_user):
        """Calling erase twice returns 200 both times (not 404 or 500)."""
        tid = tenant_and_user["tenant_id"]
        uid = tenant_and_user["user_id"]
        token = _make_user_token(tid, uid)
        headers = {"Authorization": f"Bearer {token}"}

        # First erase
        resp1 = client.post("/api/v1/users/me/gdpr/erase", headers=headers)
        assert resp1.status_code == 200
        assert resp1.json()["erased"] is True

        # Second erase (idempotent -- no data left but should still succeed)
        resp2 = client.post("/api/v1/users/me/gdpr/erase", headers=headers)
        assert resp2.status_code == 200
        assert resp2.json()["erased"] is True
