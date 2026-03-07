"""
Integration tests for analytics endpoints (API-074, API-075).

Tests against real PostgreSQL — no mocking of DB layer.

Prerequisites:
    docker-compose up -d  # ensure PostgreSQL + Redis are running

Run:
    pytest tests/integration/test_analytics_routes.py -v --timeout=30
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


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
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _create_test_tenant() -> str:
    tid = str(uuid.uuid4())
    slug = f"analytics-test-{tid[:8]}"
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"Analytics Test {tid[:8]}",
            "slug": slug,
            "email": f"admin-{tid[:8]}@analytics-int.test",
        },
    )
    return tid


async def _create_test_user(tenant_id: str) -> str:
    uid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO users (id, tenant_id, email, name, role, status) "
        "VALUES (:id, :tenant_id, :email, :name, 'admin', 'active')",
        {
            "id": uid,
            "tenant_id": tenant_id,
            "email": f"user-{uid[:8]}@analytics-int.test",
            "name": "Analytics Test User",
        },
    )
    return uid


async def _cleanup_tenant(tid: str):
    await _run_sql("DELETE FROM user_feedback WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM messages WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM conversations WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM users WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM tenants WHERE id = :tid", {"tid": tid})


# ---------------------------------------------------------------------------
# JWT helpers for test tokens
# ---------------------------------------------------------------------------


def _make_tenant_admin_token(tenant_id: str) -> str:
    from datetime import timedelta

    from jose import jwt

    secret = os.environ.get("JWT_SECRET_KEY", "test-secret-" + "a" * 50)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": f"admin-{tenant_id[:8]}",
        "tenant_id": tenant_id,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": f"admin-{tenant_id[:8]}@test.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSatisfactionAnalyticsPeriodFilter:
    """GET /admin/analytics/satisfaction — period filter integration."""

    def test_satisfaction_analytics_period_filter(self, client):
        """30d and 7d periods both return valid structure with period field."""
        tid = asyncio.run(_create_test_tenant())
        try:
            token = _make_tenant_admin_token(tid)
            headers = {"Authorization": f"Bearer {token}"}

            for period in ("30d", "7d"):
                resp = client.get(
                    f"/api/v1/admin/analytics/satisfaction?period={period}",
                    headers=headers,
                )
                assert resp.status_code == 200, f"period={period} failed: {resp.text}"
                data = resp.json()
                assert data["period"] == period
                assert "overall_rate" in data
                assert "total_ratings" in data
                assert "per_agent" in data
                assert "daily_trend" in data
                assert "not_enough_data" in data
        finally:
            asyncio.run(_cleanup_tenant(tid))

    def test_satisfaction_analytics_empty_returns_not_enough_data(self, client):
        """Tenant with no feedback has not_enough_data=True."""
        tid = asyncio.run(_create_test_tenant())
        try:
            token = _make_tenant_admin_token(tid)
            headers = {"Authorization": f"Bearer {token}"}

            resp = client.get(
                "/api/v1/admin/analytics/satisfaction",
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["not_enough_data"] is True
            assert data["total_ratings"] == 0
            assert data["overall_rate"] == 0.0
            assert data["per_agent"] == []
        finally:
            asyncio.run(_cleanup_tenant(tid))


class TestEngagementAnalytics:
    """GET /admin/analytics/engagement — integration."""

    def test_engagement_analytics_returns_structure(self, client):
        """Returns valid engagement structure with all required fields."""
        tid = asyncio.run(_create_test_tenant())
        try:
            token = _make_tenant_admin_token(tid)
            headers = {"Authorization": f"Bearer {token}"}

            resp = client.get(
                "/api/v1/admin/analytics/engagement",
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()

            assert "dau" in data
            assert "wau" in data
            assert "mau" in data
            assert "period" in data
            assert "per_agent" in data
            assert "inactive_users" in data
            assert "feature_adoption" in data

            assert data["period"] == "30d"
            assert isinstance(data["dau"], int)
            assert isinstance(data["wau"], int)
            assert isinstance(data["mau"], int)
            assert isinstance(data["per_agent"], list)

            inactive = data["inactive_users"]
            assert "count" in inactive
            assert "pct" in inactive

            adoption = data["feature_adoption"]
            assert "memory_notes" in adoption
            assert "glossary_queries" in adoption
            assert "feedback" in adoption

            # All values should be 0 for a fresh tenant with no data
            assert data["dau"] == 0
            assert data["wau"] == 0
            assert data["mau"] == 0
        finally:
            asyncio.run(_cleanup_tenant(tid))
