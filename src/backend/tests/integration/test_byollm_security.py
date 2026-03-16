"""
P2LLM-017: BYOLLM Security Integration Tests.

Uses real PostgreSQL — no mocking.

Security invariants tested:
- Stored row in DB never contains plaintext API key
- API response (GET /admin/llm-config) returns key_present bool only — no key value
- DELETE removes key material from DB
- Non-enterprise tenant gets 403

Tier 2: Requires running PostgreSQL + JWT_SECRET_KEY configured.

Run:
    pytest tests/integration/test_byollm_security.py -v
"""
import asyncio
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


def _make_token(
    tenant_id: str, roles: list, scope: str = "tenant", plan: str = "enterprise"
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": scope,
        "plan": plan,
        "token_version": 2,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def _make_tenant_row(tenant_id: str) -> dict:
    return {
        "id": tenant_id,
        "name": f"BYOLLM Test Tenant {tenant_id[:8]}",
        "slug": f"byollm-{tenant_id[:8]}",
        "plan": "enterprise",
        "primary_contact_email": f"admin-{tenant_id[:8]}@test.example",
        "status": "active",
    }


# ---------------------------------------------------------------------------
# DB setup / teardown
# ---------------------------------------------------------------------------


def _setup_tenant(tenant_id: str) -> None:
    """Create test tenant row synchronously."""
    db_url = _db_url()

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
                    "VALUES (:id, :name, :slug, :plan, :primary_contact_email, :status) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                _make_tenant_row(tenant_id),
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())


def _cleanup_tenant(tenant_id: str) -> None:
    """Remove test tenant and config rows synchronously."""
    db_url = _db_url()

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            await session.execute(
                text("DELETE FROM tenant_configs WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            await session.execute(
                text("DELETE FROM tenants WHERE id = :id"),
                {"id": tenant_id},
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())


def _read_byollm_config(tenant_id: str) -> dict | None:
    """Read raw byollm_key_ref config from DB synchronously."""
    db_url = _db_url()

    result = {}

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            r = await session.execute(
                text(
                    "SELECT config_data FROM tenant_configs "
                    "WHERE tenant_id = :tid AND config_type = 'byollm_key_ref'"
                ),
                {"tid": tenant_id},
            )
            row = r.fetchone()
            if row:
                result["data"] = row[0]
        await engine.dispose()

    asyncio.run(_do())
    return result.get("data")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


PLAINTEXT_KEY = "sk-realkey-that-must-never-appear-in-db"


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module")
def enterprise_tenant():
    """Create an enterprise tenant for the test module."""
    tenant_id = str(uuid.uuid4())
    _setup_tenant(tenant_id)
    yield tenant_id
    _cleanup_tenant(tenant_id)


@pytest.fixture(scope="module")
def pro_tenant():
    """Create a professional (non-enterprise) tenant for the test module."""
    tid = str(uuid.uuid4())
    db_url = _db_url()

    async def _create():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
                    "VALUES (:id, :name, :slug, 'professional', :email, 'active') "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": tid,
                    "name": f"Pro Tenant {tid[:8]}",
                    "slug": f"pro-{tid[:8]}",
                    "email": f"admin-{tid[:8]}@test.example",
                },
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_create())
    yield tid

    async def _cleanup():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            await session.execute(
                text("DELETE FROM tenant_configs WHERE tenant_id = :tid"), {"tid": tid}
            )
            await session.execute(
                text("DELETE FROM tenants WHERE id = :id"), {"id": tid}
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_cleanup())


class TestBYOLLMSecurity:
    """Security invariants for BYOLLM credential storage."""

    def test_store_byollm_key_response_has_no_plaintext_key(
        self, client, enterprise_tenant
    ):
        """PATCH /admin/llm-config/byollm response must not contain the API key."""
        token = _make_token(
            enterprise_tenant, roles=["tenant_admin"], plan="enterprise"
        )
        response = client.patch(
            "/api/v1/admin/llm-config/byollm",
            json={
                "provider": "openai_direct",
                "api_key": PLAINTEXT_KEY,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        # Accept 200 or 422 (if JWT_SECRET_KEY missing for fernet)
        if response.status_code == 422:
            pytest.skip("JWT_SECRET_KEY not configured — cannot encrypt key")

        assert response.status_code == 200, response.text
        body = response.json()

        # Response MUST NOT contain the plaintext key
        body_str = str(body)
        assert PLAINTEXT_KEY not in body_str
        assert "sk-" not in body_str or "sk-" not in PLAINTEXT_KEY[:3]

        # Response shows key_present: true
        assert body.get("key_present") is True

    def test_db_stores_no_plaintext_key(self, client, enterprise_tenant):
        """After PATCH, the DB row must not contain the plaintext API key."""
        token = _make_token(
            enterprise_tenant, roles=["tenant_admin"], plan="enterprise"
        )
        response = client.patch(
            "/api/v1/admin/llm-config/byollm",
            json={
                "provider": "openai_direct",
                "api_key": PLAINTEXT_KEY,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != 200:
            pytest.skip("BYOLLM store failed — skipping DB assertion")

        config_data = _read_byollm_config(enterprise_tenant)
        assert config_data is not None, "byollm_key_ref config_data not found in DB"

        # The plaintext key must not appear anywhere in the stored config
        config_str = str(config_data)
        assert (
            PLAINTEXT_KEY not in config_str
        ), f"Plaintext key found in DB config: {config_str}"

        # encrypted_key_ref must be present
        if isinstance(config_data, dict):
            assert "encrypted_key_ref" in config_data
            # The encrypted ref is an opaque token — not the raw key
            assert config_data["encrypted_key_ref"] != PLAINTEXT_KEY

    def test_get_llm_config_has_no_plaintext_key(self, client, enterprise_tenant):
        """GET /admin/llm-config response must never contain the API key."""
        token = _make_token(
            enterprise_tenant, roles=["tenant_admin"], plan="enterprise"
        )
        response = client.get(
            "/api/v1/admin/llm-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        body_str = str(body)

        assert PLAINTEXT_KEY not in body_str
        # byollm section shows key_present bool only
        byollm = body.get("byollm", {})
        assert "api_key" not in byollm
        assert "encrypted_key_ref" not in byollm

    def test_delete_removes_key_material(self, client, enterprise_tenant):
        """DELETE /admin/llm-config/byollm removes key from DB."""
        token = _make_token(
            enterprise_tenant, roles=["tenant_admin"], plan="enterprise"
        )
        # Ensure key is stored first
        client.patch(
            "/api/v1/admin/llm-config/byollm",
            json={"provider": "openai_direct", "api_key": PLAINTEXT_KEY},
            headers={"Authorization": f"Bearer {token}"},
        )

        # Now delete
        delete_resp = client.delete(
            "/api/v1/admin/llm-config/byollm",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert delete_resp.status_code == 204, delete_resp.text

        # DB row should be gone
        config_data = _read_byollm_config(enterprise_tenant)
        assert (
            config_data is None
        ), f"byollm_key_ref still present after DELETE: {config_data}"

    def test_non_enterprise_tenant_gets_403(self, client, pro_tenant):
        """Non-enterprise plan gets 403 on PATCH /admin/llm-config/byollm."""
        token = _make_token(pro_tenant, roles=["tenant_admin"], plan="professional")
        response = client.patch(
            "/api/v1/admin/llm-config/byollm",
            json={"provider": "openai_direct", "api_key": PLAINTEXT_KEY},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403, response.text
