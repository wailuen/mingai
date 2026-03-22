"""
Integration test: Plan tier bypass — starter plan.

Verifies that starter plan tenants are blocked from:
  - POST /admin/llm-config/select-profile (requires professional+)
  - All BYOLLM endpoints (requires enterprise)

Tier 2: No mocking — requires running PostgreSQL + Redis.
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


def _make_admin_token(tenant_id: str, plan: str = "starter") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": plan,
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


async def _create_tenant(tid: str, plan: str) -> None:
    url = _db_url()
    engine = create_async_engine(url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
                    "VALUES (:id, :name, :slug, :plan, :email, 'active') "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": tid,
                    "name": f"Tier Test {plan} {tid[:8]}",
                    "slug": f"tier-{plan}-{tid[:8]}",
                    "plan": plan,
                    "email": f"tier-{tid[:8]}@test.example",
                },
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _delete_tenant(tid: str) -> None:
    url = _db_url()
    engine = create_async_engine(url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(
                text("DELETE FROM tenants WHERE id = :id"), {"id": tid}
            )
            await session.commit()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def starter_tenant():
    tid = str(uuid.uuid4())
    asyncio.run(_create_tenant(tid, "starter"))
    yield tid
    asyncio.run(_delete_tenant(tid))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStarterPlanBlocked:
    """Starter plan tenants cannot access professional+ or enterprise endpoints."""

    def test_select_profile_returns_403_for_starter(self, client, starter_tenant):
        """POST /admin/llm-config/select-profile requires professional+."""
        headers = {"Authorization": f"Bearer {_make_admin_token(starter_tenant, 'starter')}"}
        resp = client.post(
            "/api/v1/admin/llm-config/select-profile",
            json={"profile_id": str(uuid.uuid4())},
            headers=headers,
        )
        assert resp.status_code == 403, (
            f"Expected 403 for starter plan on select-profile, got {resp.status_code}: {resp.text}"
        )

    def test_byollm_list_library_returns_403_for_starter(self, client, starter_tenant):
        """GET /admin/byollm/library-entries requires enterprise plan."""
        headers = {"Authorization": f"Bearer {_make_admin_token(starter_tenant, 'starter')}"}
        resp = client.get("/api/v1/admin/byollm/library-entries", headers=headers)
        assert resp.status_code == 403, (
            f"Expected 403 for starter plan on BYOLLM list, got {resp.status_code}: {resp.text}"
        )

    def test_byollm_create_library_returns_403_for_starter(self, client, starter_tenant):
        """POST /admin/byollm/library-entries requires enterprise plan."""
        headers = {"Authorization": f"Bearer {_make_admin_token(starter_tenant, 'starter')}"}
        resp = client.post(
            "/api/v1/admin/byollm/library-entries",
            json={
                "provider": "openai",
                "model_name": "gpt-4o",
                "display_name": "Test",
                "endpoint_url": "https://api.openai.com/v1",
                "api_key": "sk-test1234",
            },
            headers=headers,
        )
        assert resp.status_code == 403, (
            f"Expected 403 for starter plan on BYOLLM create, got {resp.status_code}: {resp.text}"
        )

    def test_byollm_list_profiles_returns_403_for_starter(self, client, starter_tenant):
        """GET /admin/byollm/profiles requires enterprise plan."""
        headers = {"Authorization": f"Bearer {_make_admin_token(starter_tenant, 'starter')}"}
        resp = client.get("/api/v1/admin/byollm/profiles", headers=headers)
        assert resp.status_code == 403, (
            f"Expected 403 for starter plan on BYOLLM profiles list, got {resp.status_code}: {resp.text}"
        )

    def test_403_response_body_does_not_disclose_plan_details(self, client, starter_tenant):
        """403 error body must not reveal the caller's plan or required plan (security rule)."""
        headers = {"Authorization": f"Bearer {_make_admin_token(starter_tenant, 'starter')}"}
        resp = client.post(
            "/api/v1/admin/llm-config/select-profile",
            json={"profile_id": str(uuid.uuid4())},
            headers=headers,
        )
        assert resp.status_code == 403
        body = resp.json()
        detail = str(body.get("detail", "")).lower()
        # Must not disclose caller's plan tier in error
        assert "starter" not in detail, "403 body must not disclose caller plan tier"
        # May use generic terms — just must not be plan-specific leakage
