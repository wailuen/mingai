"""
TEST-042: Memory Policy API Integration Tests (API-076/077)

Tests GET and PATCH /admin/memory-policy endpoints against real PostgreSQL.
No mocking — Tier 2 integration tests.

Architecture note:
    Uses session-scoped TestClient from conftest.py (shared across all
    integration tests to avoid asyncpg event loop conflicts).

Prerequisites:
    docker-compose up -d  # ensure PostgreSQL and Redis are running

Run:
    pytest tests/integration/test_memory_policy.py -v
"""
import asyncio
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
        pytest.skip("JWT_SECRET_KEY not configured — skipping integration tests")
    return secret


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


def _make_admin_token(tenant_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": f"admin@{tenant_id[:8]}.test",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def _make_user_token(tenant_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "roles": ["end_user"],
        "scope": "tenant",
        "plan": "professional",
        "email": f"user@{tenant_id[:8]}.test",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


async def _run_sql(sql: str, params: dict = None):
    """Execute SQL against real DB using a fresh async engine."""
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _create_tenant(tid: str):
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, :plan, :email, 'active')",
        {
            "id": tid,
            "name": f"Memory Policy Test {tid[:8]}",
            "slug": f"mp-int-{tid[:8]}",
            "plan": "professional",
            "email": f"test-{tid[:8]}@mp-int.test",
        },
    )


async def _cleanup_tenant(tid: str):
    await _run_sql("DELETE FROM tenant_configs WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mp_tenant_id():
    """Provision a real test tenant once per module, clean up after."""
    tid = str(uuid.uuid4())
    asyncio.run(_create_tenant(tid))
    yield tid
    asyncio.run(_cleanup_tenant(tid))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetMemoryPolicyDefaults:
    """GET /api/v1/admin/memory-policy returns defaults when no config exists."""

    def test_get_memory_policy_defaults(self, client, mp_tenant_id):
        """
        API-076: GET returns all default values when no policy has been set.

        Verifies response schema and default values for all 8 fields.
        """
        token = _make_admin_token(mp_tenant_id)
        resp = client.get(
            "/api/v1/admin/memory-policy",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Verify all required fields are present
        assert "profile_learning_enabled" in data
        assert "profile_learning_trigger_interval" in data
        assert "working_memory_enabled" in data
        assert "working_memory_ttl_days" in data
        assert "memory_notes_enabled" in data
        assert "memory_notes_max_per_user" in data
        assert "org_context_enabled" in data
        assert "org_context_source" in data

        # Verify defaults
        assert data["profile_learning_enabled"] is True
        assert data["profile_learning_trigger_interval"] == 10
        assert data["working_memory_enabled"] is True
        assert data["working_memory_ttl_days"] == 7
        assert data["memory_notes_enabled"] is True
        assert data["memory_notes_max_per_user"] == 20
        assert data["org_context_enabled"] is False
        assert data["org_context_source"] == "none"

    def test_get_requires_tenant_admin(self, client, mp_tenant_id):
        """End-user role is rejected with 403."""
        token = _make_user_token(mp_tenant_id)
        resp = client.get(
            "/api/v1/admin/memory-policy",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_get_requires_auth(self, client, mp_tenant_id):
        """Unauthenticated request returns 401."""
        resp = client.get("/api/v1/admin/memory-policy")
        assert resp.status_code == 401


class TestUpdateMemoryPolicy:
    """PATCH /api/v1/admin/memory-policy persists and returns updated policy."""

    def test_update_memory_policy(self, client, mp_tenant_id):
        """
        API-077: PATCH updates specified fields and returns merged policy.

        Verifies: changed fields are updated, unchanged fields retain defaults.
        """
        token = _make_admin_token(mp_tenant_id)

        # Update a subset of fields
        resp = client.patch(
            "/api/v1/admin/memory-policy",
            json={
                "working_memory_ttl_days": 14,
                "memory_notes_max_per_user": 50,
                "org_context_enabled": True,
                "org_context_source": "azure_ad",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Updated fields
        assert data["working_memory_ttl_days"] == 14
        assert data["memory_notes_max_per_user"] == 50
        assert data["org_context_enabled"] is True
        assert data["org_context_source"] == "azure_ad"

        # Unchanged fields retain defaults
        assert data["profile_learning_enabled"] is True
        assert data["profile_learning_trigger_interval"] == 10

        # GET should now return the updated values
        get_resp = client.get(
            "/api/v1/admin/memory-policy",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data["working_memory_ttl_days"] == 14
        assert get_data["org_context_source"] == "azure_ad"

    def test_update_requires_tenant_admin(self, client, mp_tenant_id):
        """End-user role is rejected with 403."""
        token = _make_user_token(mp_tenant_id)
        resp = client.patch(
            "/api/v1/admin/memory-policy",
            json={"working_memory_ttl_days": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_update_empty_body_returns_422(self, client, mp_tenant_id):
        """PATCH with no fields returns 422 Unprocessable Entity."""
        token = _make_admin_token(mp_tenant_id)
        resp = client.patch(
            "/api/v1/admin/memory-policy",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422


class TestMemoryPolicyValidation:
    """Validation rules for PATCH /api/v1/admin/memory-policy."""

    def test_memory_policy_validation_trigger_interval_too_low(
        self, client, mp_tenant_id
    ):
        """profile_learning_trigger_interval below 5 returns 422."""
        token = _make_admin_token(mp_tenant_id)
        resp = client.patch(
            "/api/v1/admin/memory-policy",
            json={"profile_learning_trigger_interval": 4},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_memory_policy_validation_ttl_too_high(self, client, mp_tenant_id):
        """working_memory_ttl_days above 30 returns 422."""
        token = _make_admin_token(mp_tenant_id)
        resp = client.patch(
            "/api/v1/admin/memory-policy",
            json={"working_memory_ttl_days": 31},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_memory_policy_validation_max_notes_too_high(self, client, mp_tenant_id):
        """memory_notes_max_per_user above 100 returns 422."""
        token = _make_admin_token(mp_tenant_id)
        resp = client.patch(
            "/api/v1/admin/memory-policy",
            json={"memory_notes_max_per_user": 101},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_memory_policy_validation_invalid_org_source(self, client, mp_tenant_id):
        """Invalid org_context_source returns 422."""
        token = _make_admin_token(mp_tenant_id)
        resp = client.patch(
            "/api/v1/admin/memory-policy",
            json={"org_context_source": "invalid_provider"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_memory_policy_validation_valid_org_sources(self, client, mp_tenant_id):
        """All valid org_context_source values are accepted."""
        token = _make_admin_token(mp_tenant_id)
        for source in ("azure_ad", "okta", "saml", "none"):
            resp = client.patch(
                "/api/v1/admin/memory-policy",
                json={"org_context_source": source},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert (
                resp.status_code == 200
            ), f"Expected 200 for org_context_source='{source}', got {resp.status_code}"
