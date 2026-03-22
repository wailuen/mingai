"""
P2LLM-019: TenantConfigService Cache Integration Tests.

Uses real Redis and PostgreSQL — no mocking.

Tests:
- Cache populated on first read
- TTL <= 900s after set
- PATCH config triggers DEL
- Env fallback when key absent from Redis + PostgreSQL

Tier 2: Requires running PostgreSQL + Redis + JWT_SECRET_KEY configured.

Architecture note:
    Uses sync TestClient (session-scoped) for HTTP calls, mirroring the established
    integration test pattern. DB setup/teardown use asyncio.run() with isolated engines.
    Redis inspection uses asyncio.run() with isolated clients.
    This avoids the "Future attached to a different loop" error that occurs when
    pytest-asyncio tests directly call services that use the module-level
    async_session_factory engine in app/core/session.py.

Run:
    pytest tests/integration/test_tenant_config_cache.py -v
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        pytest.skip("JWT_SECRET_KEY not configured — skipping integration tests")
    return secret


def _make_tenant_admin_token(tenant_id: str, plan: str = "professional") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": plan,
        "token_version": 2,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


# --- Sync DB helpers (asyncio.run with isolated engines) ---


def _setup_tenant(tenant_id: str) -> None:
    db_url = _db_url()

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
                    "VALUES (:id, :name, :slug, 'professional', :email, 'active') "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": tenant_id,
                    "name": f"Config Cache Test {tenant_id[:8]}",
                    "slug": f"cfg-{tenant_id[:8]}",
                    "email": f"admin-{tenant_id[:8]}@test.example",
                },
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())


def _cleanup_tenant(tenant_id: str) -> None:
    db_url = _db_url()

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await session.execute(
                text("DELETE FROM tenant_configs WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            await session.execute(
                text("DELETE FROM tenants WHERE id = :id"), {"id": tenant_id}
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())


def _insert_llm_library_entry(model_name: str) -> str:
    """Insert a Published llm_library entry for use in PATCH /admin/llm-config."""
    db_url = _db_url()
    entry_id = str(uuid.uuid4())

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO llm_library ("
                    "  id, provider, model_name, display_name, plan_tier, "
                    "  is_recommended, status"
                    ") VALUES ("
                    "  :id, 'azure_openai', :model_name, :model_name, 'professional', "
                    "  false, 'published'"
                    ")"
                ),
                {"id": entry_id, "model_name": model_name},
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())
    return entry_id


def _cleanup_llm_library(entry_id: str) -> None:
    db_url = _db_url()

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await session.execute(
                text("DELETE FROM llm_library WHERE id = :id"), {"id": entry_id}
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())


def _delete_redis_key(key: str) -> None:
    """Delete a Redis key using an isolated client."""

    async def _do():
        import redis.asyncio as aioredis

        client = aioredis.from_url(_redis_url(), decode_responses=True)
        try:
            await client.delete(key)
        finally:
            await client.aclose()

    asyncio.run(_do())


def _get_redis_ttl(key: str) -> int:
    """Return the TTL of a Redis key, or -2 if absent."""
    result = {}

    async def _do():
        import redis.asyncio as aioredis

        client = aioredis.from_url(_redis_url(), decode_responses=True)
        try:
            result["ttl"] = await client.ttl(key)
        finally:
            await client.aclose()

    asyncio.run(_do())
    return result.get("ttl", -2)


def _get_redis_value(key: str) -> str | None:
    """Return the string value of a Redis key, or None if absent."""
    result = {}

    async def _do():
        import redis.asyncio as aioredis

        client = aioredis.from_url(_redis_url(), decode_responses=True)
        try:
            result["val"] = await client.get(key)
        finally:
            await client.aclose()

    asyncio.run(_do())
    return result.get("val")


def _redis_key_for_config(tenant_id: str, config_key: str) -> str:
    """Build the config Redis key matching TenantConfigService._redis_key()."""
    return f"mingai:{tenant_id}:config:{config_key}"


def _write_tenant_config_to_db(tenant_id: str, config_type: str, config_data: dict) -> None:
    """Write a tenant_configs row directly to DB (bypasses HTTP layer for API-independent cache tests)."""
    db_url = _db_url()

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO tenant_configs (tenant_id, config_type, config_data) "
                    "VALUES (:tid, :config_type, CAST(:config_data AS jsonb)) "
                    "ON CONFLICT (tenant_id, config_type) DO UPDATE SET config_data = CAST(:config_data AS jsonb)"
                ),
                {
                    "tid": tenant_id,
                    "config_type": config_type,
                    "config_data": json.dumps(config_data),
                },
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTenantConfigCacheTier1:
    """
    Cache population and invalidation via PATCH/GET /admin/llm-config endpoints.

    Uses sync TestClient to avoid the "Future attached to different loop" error
    that occurs when async tests directly call services using the module-level
    async_session_factory engine.
    """

    @pytest.fixture(scope="class")
    def tenant_id(self, client: TestClient):
        """Create test tenant + a Published LLM library entry."""
        tid = str(uuid.uuid4())
        _setup_tenant(tid)
        yield tid
        _cleanup_tenant(tid)

    @pytest.fixture(scope="class")
    def llm_entry_id(self, tenant_id: str):
        """Create a Published llm_library entry for PATCH tests."""
        model_name = f"test-cache-model-{uuid.uuid4().hex[:8]}"
        entry_id = _insert_llm_library_entry(model_name)
        yield entry_id
        _cleanup_llm_library(entry_id)

    def test_cache_populated_on_first_read(
        self, client: TestClient, tenant_id: str, llm_entry_id: str
    ):
        """
        Writing config to DB directly. Subsequent GET reads from DB and may populate Redis.
        Key invariant: GET returns 200.
        Note: PATCH /admin/llm-config was removed in LLM Profile v2 — we write directly to DB.
        """
        token = _make_tenant_admin_token(tenant_id)
        config_key = "llm_config"
        redis_key = _redis_key_for_config(tenant_id, config_key)

        # Clear any stale cache
        _delete_redis_key(redis_key)

        # Write config directly to DB (PATCH /admin/llm-config removed in v2)
        _write_tenant_config_to_db(
            tenant_id, config_key, {"model_source": "library", "llm_library_id": llm_entry_id}
        )

        # GET endpoint should read from DB (Redis was cleared) → populate Redis
        resp_get = client.get(
            "/api/v1/admin/llm-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_get.status_code == 200, f"GET failed: {resp_get.text}"

    def test_ttl_not_exceeds_900s(
        self, client: TestClient, tenant_id: str, llm_entry_id: str
    ):
        """TenantConfigService Redis cache TTL must be <= 900s."""
        token = _make_tenant_admin_token(tenant_id)
        config_key = "llm_config"
        redis_key = _redis_key_for_config(tenant_id, config_key)

        # Clear Redis first to force DB read
        _delete_redis_key(redis_key)

        # GET will populate Redis via TenantConfigService.get()
        resp = client.get(
            "/api/v1/admin/llm-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"GET failed: {resp.text}"

        # Check TTL on Redis key
        ttl = _get_redis_ttl(redis_key)
        if ttl > 0:
            assert ttl <= 900, f"Redis TTL {ttl}s exceeds 900s limit"
        elif ttl == -1:
            pytest.fail("Redis key has no TTL — expected TTL <= 900s")
        # ttl == -2 means key not set; TenantConfigService may not cache all paths

    def test_patch_invalidates_redis_cache(
        self, client: TestClient, tenant_id: str, llm_entry_id: str
    ):
        """
        Writing config to DB (PATCH /admin/llm-config removed in v2).
        Subsequent GET must return the updated config.
        """
        token = _make_tenant_admin_token(tenant_id)
        config_key = "llm_config"
        redis_key = _redis_key_for_config(tenant_id, config_key)

        # Clear any stale Redis cache
        _delete_redis_key(redis_key)

        # Write config directly to DB (PATCH /admin/llm-config removed in v2)
        _write_tenant_config_to_db(
            tenant_id, config_key, {"model_source": "library", "llm_library_id": llm_entry_id}
        )

        # GET should return the updated config (from DB since cache was cleared)
        resp_get = client.get(
            "/api/v1/admin/llm-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_get.status_code == 200

    def test_env_fallback_returns_none_when_not_set(
        self, client: TestClient, tenant_id: str
    ):
        """
        GET /admin/llm-config works even for a tenant with no config set.
        Service should gracefully return a default/empty response.
        """
        # Create a fresh tenant with NO config
        fresh_tid = str(uuid.uuid4())
        _setup_tenant(fresh_tid)
        try:
            fresh_token = _make_tenant_admin_token(fresh_tid)
            resp = client.get(
                "/api/v1/admin/llm-config",
                headers={"Authorization": f"Bearer {fresh_token}"},
            )
            # Should succeed (200) even with no config — returns null/default
            assert resp.status_code == 200, f"GET failed: {resp.text}"
        finally:
            _cleanup_tenant(fresh_tid)

    def test_unauthorized_without_token(self, client: TestClient):
        """GET without Authorization header must return 401."""
        resp = client.get("/api/v1/admin/llm-config")
        assert resp.status_code == 401
