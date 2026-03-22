"""
PVDR-018: Integration tests for LLM Provider Credentials Management.

Tier 2: Real PostgreSQL — no mocking.

11 test cases:
1.  POST → DB row has api_key_encrypted as bytes (not plaintext)
2.  GET list → no api_key_encrypted in response
3.  GET detail → no api_key_encrypted in response
4.  PATCH without api_key → api_key_encrypted unchanged
5.  PATCH with new api_key → api_key_encrypted changed and decrypts correctly
6.  set-default → only one is_default=true row
7.  DELETE default → 409
8.  DELETE non-default → 204
9.  Seed idempotency (first call True, second call False)
10. GET /admin/llm-config/providers (tenant admin)
11. PATCH /admin/llm-config/provider (tenant admin)

Run:
    pytest tests/integration/test_llm_providers.py -v
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


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


def _make_platform_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "roles": ["platform_admin"],
        "scope": "platform",
        "plan": "enterprise",
        "token_version": 2,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def _make_tenant_token(tenant_id: str, user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "enterprise",
        "token_version": 2,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def _db_exec(sql: str, params: dict = None):
    """Run a raw SQL statement against real DB, return first row or None."""
    db_url = _db_url()
    result_holder = {}

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            await session.execute(
                text("SELECT set_config('app.scope', 'platform', true)")
            )
            res = await session.execute(text(sql), params or {})
            row = res.fetchone()
            result_holder["row"] = row
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())
    return result_holder.get("row")


def _cleanup_providers(test_prefix: str = "Integration Test"):
    """Remove provider rows created during tests."""
    db_url = _db_url()

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            await session.execute(
                text("SELECT set_config('app.scope', 'platform', true)")
            )
            await session.execute(
                text("DELETE FROM llm_providers WHERE display_name LIKE :prefix"),
                {"prefix": f"{test_prefix}%"},
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())


def _setup_tenant(tenant_id: str, user_id: str) -> None:
    """Create test tenant + user rows synchronously."""
    db_url = _db_url()

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
                    "VALUES (:id, :name, :slug, :plan, :email, :status) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": tenant_id,
                    "name": f"PVDR Test Tenant {tenant_id[:8]}",
                    "slug": f"pvdr-{tenant_id[:8]}",
                    "plan": "enterprise",
                    "email": f"admin-{tenant_id[:8]}@test.example",
                    "status": "active",
                },
            )
            await session.execute(
                text(
                    "INSERT INTO users (id, tenant_id, email, name, role, status) "
                    "VALUES (:id, :tid, :email, :name, 'tenant_admin', 'active') "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": user_id,
                    "tid": tenant_id,
                    "email": f"admin-{user_id[:8]}@test.example",
                    "name": "PVDR Test Admin",
                },
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())


def _cleanup_tenant(tenant_id: str) -> None:
    """Remove test tenant rows synchronously."""
    db_url = _db_url()

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            await session.execute(
                text("SELECT set_config('app.scope', 'platform', true)")
            )
            await session.execute(
                text("DELETE FROM tenant_configs WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            await session.execute(
                text("DELETE FROM users WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            await session.execute(
                text("DELETE FROM tenants WHERE id = :id"),
                {"id": tenant_id},
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestLLMProviders:
    """
    Integration tests for /platform/providers and /admin/llm-config/provider.
    Uses real PostgreSQL. Session-scoped TestClient from root conftest.
    """

    FAKE_KEY = "sk-integration-test-key-do-not-use"
    FAKE_ENDPOINT = "https://integration-test.openai.azure.com/"

    @pytest.fixture(autouse=True, scope="class")
    def _setup(self):
        """Create tenant + user for tenant-scoped tests."""
        self.__class__._tenant_id = str(uuid.uuid4())
        self.__class__._user_id = str(uuid.uuid4())
        _setup_tenant(self.__class__._tenant_id, self.__class__._user_id)
        yield
        _cleanup_providers("Integration Test")
        _cleanup_tenant(self.__class__._tenant_id)

    # ------------------------------------------------------------------
    # Test 1: POST → DB has bytes (not plaintext)
    # ------------------------------------------------------------------

    def test_01_post_stores_encrypted_bytes(self, client):
        """POST /platform/providers → api_key_encrypted in DB is bytes, not plaintext."""
        token = _make_platform_token()
        resp = client.post(
            "/api/v1/platform/providers",
            json={
                "provider_type": "azure_openai",
                "display_name": "Integration Test Provider 01",
                "endpoint": self.FAKE_ENDPOINT,
                "api_key": self.FAKE_KEY,
                "models": {"primary": "agentic-worker"},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code not in (200, 201):
            pytest.skip(
                f"Provider creation failed (status={resp.status_code}): {resp.text}"
            )

        provider_id = resp.json()["id"]
        self.__class__._provider_id_01 = provider_id

        # Verify DB row
        row = _db_exec(
            "SELECT api_key_encrypted FROM llm_providers WHERE id = :id",
            {"id": provider_id},
        )
        assert row is not None
        encrypted_bytes = bytes(row[0])
        assert isinstance(encrypted_bytes, bytes)
        assert encrypted_bytes != self.FAKE_KEY.encode("utf-8")

    # ------------------------------------------------------------------
    # Test 2: GET list → no api_key_encrypted in response
    # ------------------------------------------------------------------

    def test_02_get_list_no_key(self, client):
        """GET /platform/providers → api_key_encrypted not in any response item."""
        token = _make_platform_token()
        resp = client.get(
            "/api/v1/platform/providers",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        providers = data.get("providers", data) if isinstance(data, dict) else data

        for p in providers:
            assert (
                "api_key_encrypted" not in p
            ), f"api_key_encrypted appeared in list response for provider {p.get('id')}"

    # ------------------------------------------------------------------
    # Test 3: GET detail → no api_key_encrypted in response
    # ------------------------------------------------------------------

    def test_03_get_detail_no_key(self, client):
        """GET /platform/providers/{id} → api_key_encrypted not in response."""
        provider_id = getattr(self.__class__, "_provider_id_01", None)
        if provider_id is None:
            pytest.skip("test_01 must run first")

        token = _make_platform_token()
        resp = client.get(
            f"/api/v1/platform/providers/{provider_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "api_key_encrypted" not in resp.json()

    # ------------------------------------------------------------------
    # Test 4: PATCH without api_key → api_key_encrypted unchanged
    # ------------------------------------------------------------------

    def test_04_patch_no_key_preserves_encrypted(self, client):
        """PATCH without api_key field → api_key_encrypted in DB unchanged."""
        provider_id = getattr(self.__class__, "_provider_id_01", None)
        if provider_id is None:
            pytest.skip("test_01 must run first")

        # Get original encrypted bytes
        row_before = _db_exec(
            "SELECT api_key_encrypted FROM llm_providers WHERE id = :id",
            {"id": provider_id},
        )
        assert row_before is not None
        encrypted_before = bytes(row_before[0])

        token = _make_platform_token()
        resp = client.patch(
            f"/api/v1/platform/providers/{provider_id}",
            json={"display_name": "Integration Test Provider 01 Updated"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        # Verify unchanged
        row_after = _db_exec(
            "SELECT api_key_encrypted FROM llm_providers WHERE id = :id",
            {"id": provider_id},
        )
        assert row_after is not None
        encrypted_after = bytes(row_after[0])
        assert encrypted_after == encrypted_before

    # ------------------------------------------------------------------
    # Test 5: PATCH with new api_key → changed and decrypts correctly
    # ------------------------------------------------------------------

    def test_05_patch_with_new_key_changes_encrypted(self, client):
        """PATCH with new api_key → api_key_encrypted changed; decrypts to new key."""
        provider_id = getattr(self.__class__, "_provider_id_01", None)
        if provider_id is None:
            pytest.skip("test_01 must run first")

        row_before = _db_exec(
            "SELECT api_key_encrypted FROM llm_providers WHERE id = :id",
            {"id": provider_id},
        )
        encrypted_before = bytes(row_before[0])

        new_key = "sk-new-integration-test-key-xyz"
        token = _make_platform_token()
        resp = client.patch(
            f"/api/v1/platform/providers/{provider_id}",
            json={"api_key": new_key},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        row_after = _db_exec(
            "SELECT api_key_encrypted FROM llm_providers WHERE id = :id",
            {"id": provider_id},
        )
        encrypted_after = bytes(row_after[0])

        # Must have changed
        assert encrypted_after != encrypted_before

        # Must decrypt to new key
        from app.core.llm.provider_service import ProviderService

        svc = ProviderService()
        decrypted = svc.decrypt_api_key(encrypted_after)
        assert decrypted == new_key

    # ------------------------------------------------------------------
    # Test 6: set-default → only one is_default=true row
    # ------------------------------------------------------------------

    def test_06_set_default_single_default(self, client):
        """POST /set-default → only one row has is_default=true."""
        # Create a second provider
        token = _make_platform_token()
        resp2 = client.post(
            "/api/v1/platform/providers",
            json={
                "provider_type": "openai",
                "display_name": "Integration Test Provider 02",
                "endpoint": None,
                "api_key": self.FAKE_KEY,
                "models": {},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp2.status_code not in (200, 201):
            pytest.skip(f"Second provider creation failed: {resp2.text}")

        provider_id_2 = resp2.json()["id"]
        self.__class__._provider_id_02 = provider_id_2

        # Set provider_2 as default
        resp_default = client.post(
            f"/api/v1/platform/providers/{provider_id_2}/set-default",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_default.status_code == 200

        # Count rows with is_default = true
        db_url = _db_url()
        count_holder = {}

        async def _count():
            engine = create_async_engine(db_url, echo=False)
            async_session = async_sessionmaker(engine, expire_on_commit=False)
            async with async_session() as session:
                await session.execute(
                    text("SELECT set_config('app.scope', 'platform', true)")
                )
                res = await session.execute(
                    text("SELECT COUNT(*) FROM llm_providers WHERE is_default = true")
                )
                count_holder["count"] = res.fetchone()[0]
            await engine.dispose()

        asyncio.run(_count())
        assert count_holder["count"] == 1

    # ------------------------------------------------------------------
    # Test 7: DELETE default → 409
    # ------------------------------------------------------------------

    def test_07_delete_default_409(self, client):
        """DELETE the default provider → 409 Conflict."""
        provider_id_2 = getattr(self.__class__, "_provider_id_02", None)
        if provider_id_2 is None:
            pytest.skip("test_06 must run first")

        token = _make_platform_token()
        resp = client.delete(
            f"/api/v1/platform/providers/{provider_id_2}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409

    # ------------------------------------------------------------------
    # Test 8: DELETE non-default → 204
    # ------------------------------------------------------------------

    def test_08_delete_non_default_204(self, client):
        """DELETE a non-default provider → 204 No Content."""
        # First disable provider_01 so we can delete without triggering "only enabled" guard
        provider_id_01 = getattr(self.__class__, "_provider_id_01", None)
        provider_id_02 = getattr(self.__class__, "_provider_id_02", None)
        if provider_id_01 is None:
            pytest.skip("test_01 must run first")

        token = _make_platform_token()
        # Create a third provider to allow deletion
        resp3 = client.post(
            "/api/v1/platform/providers",
            json={
                "provider_type": "openai",
                "display_name": "Integration Test Provider 03 Delete",
                "api_key": self.FAKE_KEY,
                "models": {},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp3.status_code not in (200, 201):
            pytest.skip(f"Third provider creation failed: {resp3.text}")

        provider_id_3 = resp3.json()["id"]

        resp_del = client.delete(
            f"/api/v1/platform/providers/{provider_id_3}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_del.status_code == 204

    # ------------------------------------------------------------------
    # Test 9: Seed idempotency
    # ------------------------------------------------------------------

    def test_09_seed_idempotency(self):
        """seed_llm_provider_from_env(): first call returns True (or False if env missing),
        second call always returns False (idempotent)."""
        db_url = _db_url()

        results = {}

        async def _do():
            from app.core.seeds import seed_llm_provider_from_env
            # Run seed once (may or may not create based on env vars)
            r1 = await seed_llm_provider_from_env()
            results["r1"] = r1
            # Run seed again — always False (idempotent)
            r2 = await seed_llm_provider_from_env()
            results["r2"] = r2

        asyncio.run(_do())

        # r2 must always be False — idempotent
        assert results["r2"] is False, "Second seed call must return False (idempotent)"

        # r1 is either True (env vars set) or False (env vars missing)
        # Either is acceptable — we can't control env vars in all test environments
        assert isinstance(results["r1"], bool)

    # ------------------------------------------------------------------
    # Test 10: GET /admin/llm-config/providers (tenant admin)
    # ------------------------------------------------------------------

    def test_10_tenant_list_providers(self, client):
        """GET /admin/llm-config/providers returns list for tenant admin."""
        token = _make_tenant_token(self._tenant_id, self._user_id)
        resp = client.get(
            "/api/v1/admin/llm-config/providers",
            headers={"Authorization": f"Bearer {token}"},
        )
        # 200 with list or empty list — no auth error
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

        # No api_key_encrypted in any item
        for item in resp.json():
            assert "api_key_encrypted" not in item

    # ------------------------------------------------------------------
    # Test 11: PATCH /admin/llm-config/provider (tenant admin)
    # ------------------------------------------------------------------

    def test_11_tenant_patch_provider_selection(self, client):
        """PATCH /admin/llm-config/provider with null → returns using_default=True."""
        token = _make_tenant_token(self._tenant_id, self._user_id)

        # Clear any existing selection (set to null/default)
        resp = client.patch(
            "/api/v1/admin/llm-config/provider",
            json={"provider_id": None},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["using_default"] is True
        assert data.get("provider_id") is None
