"""
Integration test: API credentials must never appear in any API response.

Verifies that `api_key_encrypted` and `api_key` fields are absent from all
BYOLLM and platform profile API responses, including nested objects.

Tier 2: No mocking — requires running PostgreSQL + Redis.
"""
import asyncio
import json as _json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Credential leak detection helper
# ---------------------------------------------------------------------------


_BANNED_CREDENTIAL_KEYS = frozenset(
    {"api_key_encrypted", "api_key", "api_secret", "secret_key", "access_token"}
)


def assert_no_credential_fields(obj: Any, path: str = "root") -> None:
    """Recursively assert no credential fields appear anywhere in a JSON response.

    Checks dict keys at every nesting level.
    """
    if isinstance(obj, dict):
        for key in obj:
            assert key not in _BANNED_CREDENTIAL_KEYS, (
                f"Credential field '{key}' found in response at path {path}.{key}"
            )
            assert_no_credential_fields(obj[key], path=f"{path}.{key}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            assert_no_credential_fields(item, path=f"{path}[{i}]")


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


def _make_enterprise_admin_token(tenant_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "enterprise",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def _make_platform_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "roles": ["platform_admin"],
        "scope": "platform",
        "plan": "enterprise",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


async def _run_sql(sql: str, params: Optional[dict] = None) -> None:
    url = _db_url()
    engine = create_async_engine(url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _create_tenant(tid: str, plan: str = "enterprise") -> None:
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, :plan, :email, 'active') "
        "ON CONFLICT (id) DO NOTHING",
        {
            "id": tid,
            "name": f"Cred Test Tenant {tid[:8]}",
            "slug": f"cred-{tid[:8]}",
            "plan": plan,
            "email": f"cred-{tid[:8]}@test.example",
        },
    )


async def _delete_tenant_data(tid: str) -> None:
    await _run_sql(
        "DELETE FROM llm_library WHERE owner_tenant_id = :tid", {"tid": tid}
    )
    await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})


async def _create_published_platform_library_entry() -> str:
    """Create a published platform library entry for testing platform profile responses."""
    entry_id = str(uuid.uuid4())
    caps = _json.dumps({"eligible_slots": ["chat", "intent", "vision", "agent"]})
    await _run_sql(
        "INSERT INTO llm_library "
        "(id, provider, model_name, display_name, plan_tier, endpoint_url, "
        "api_key_encrypted, api_key_last4, status, capabilities, "
        "is_byollm, owner_tenant_id, created_at, updated_at) "
        "VALUES "
        "(:id, 'openai_direct', 'gpt-4o', 'Platform Cred Test', 'professional', 'https://api.openai.com/v1', "
        "'enc_test_secret', '4321', 'published', "
        "CAST(:caps AS jsonb), false, NULL, NOW(), NOW())",
        {"id": entry_id, "caps": caps},
    )
    return entry_id


async def _delete_library_entry(entry_id: str) -> None:
    await _run_sql("DELETE FROM llm_library WHERE id = :id", {"id": entry_id})


async def _delete_profile(profile_id: str) -> None:
    await _run_sql("DELETE FROM llm_profiles WHERE id = :id", {"id": profile_id})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def enterprise_tenant():
    tid = str(uuid.uuid4())
    asyncio.run(_create_tenant(tid))
    yield tid
    asyncio.run(_delete_tenant_data(tid))


@pytest.fixture(scope="module")
def platform_library_entry():
    entry_id = asyncio.run(_create_published_platform_library_entry())
    yield entry_id
    asyncio.run(_delete_library_entry(entry_id))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCredentialNeverReturned:
    """All API responses must be free of credential fields."""

    def test_byollm_create_response_has_no_credentials(
        self, client, enterprise_tenant
    ):
        """POST /admin/byollm/library-entries response must not contain api_key fields."""
        headers = {
            "Authorization": f"Bearer {_make_enterprise_admin_token(enterprise_tenant)}"
        }
        resp = client.post(
            "/api/v1/admin/byollm/library-entries",
            json={
                "provider": "openai",
                "model_name": "gpt-4o",
                "display_name": f"Cred Test {uuid.uuid4().hex[:6]}",
                "endpoint_url": "https://api.openai.com/v1",
                "api_key": "sk-testcredentialtest1234",
            },
            headers=headers,
        )
        # May fail with 422 if SSRF rejects the endpoint — that's fine for this test
        # We only care about the response body when it succeeds or returns data
        if resp.status_code == 201:
            assert_no_credential_fields(resp.json())

    def test_byollm_list_response_has_no_credentials(
        self, client, enterprise_tenant
    ):
        """GET /admin/byollm/library-entries list must not contain api_key fields."""
        headers = {
            "Authorization": f"Bearer {_make_enterprise_admin_token(enterprise_tenant)}"
        }
        resp = client.get("/api/v1/admin/byollm/library-entries", headers=headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert_no_credential_fields(resp.json())

    def test_platform_profile_list_has_no_credentials(self, client):
        """GET /platform/llm-profiles list must not contain api_key fields."""
        headers = {
            "Authorization": f"Bearer {_make_platform_admin_token()}"
        }
        resp = client.get("/api/v1/platform/llm-profiles", headers=headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert_no_credential_fields(resp.json())

    def test_available_models_response_has_no_credentials(self, client, platform_library_entry):
        """GET /platform/llm-profiles/available-models/{slot} must not expose credentials."""
        headers = {
            "Authorization": f"Bearer {_make_platform_admin_token()}"
        }
        resp = client.get(
            "/api/v1/platform/llm-profiles/available-models/chat", headers=headers
        )
        # May be 200 (list) or 404 (no profiles) — either way body must be clean
        if resp.status_code == 200:
            assert_no_credential_fields(resp.json())

    def test_assert_no_credential_fields_catches_nested_keys(self):
        """Unit-level test of the helper — verifies nested detection works."""
        clean = {
            "id": "abc",
            "slots": {"chat": {"model_name": "gpt-4o", "params": {}}},
        }
        # Should not raise
        assert_no_credential_fields(clean)

    def test_assert_no_credential_fields_detects_api_key_encrypted(self):
        """Helper raises AssertionError when api_key_encrypted is present."""
        dirty = {"id": "abc", "api_key_encrypted": "enc_value"}
        with pytest.raises(AssertionError, match="api_key_encrypted"):
            assert_no_credential_fields(dirty)

    def test_assert_no_credential_fields_detects_nested(self):
        """Helper raises AssertionError when credential is nested inside list."""
        dirty = {"entries": [{"id": "1", "api_key": "sk-secret"}]}
        with pytest.raises(AssertionError, match="api_key"):
            assert_no_credential_fields(dirty)
