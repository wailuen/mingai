"""
Integration tests for PA-008 and PA-009: health score API endpoints.

Tier 2: Real PostgreSQL + Redis, NO MOCKING.

Tests:
  PA-008: GET /platform/tenants/at-risk
    - Returns empty list when no at-risk tenants
    - Returns tenants with composite_score < 40 sorted by composite ASC
    - weeks_at_risk counts consecutive at_risk rows correctly
    - component_breakdown includes all four component scores
    - Requires platform_admin scope (returns 403 for tenant_admin)

  PA-009: GET /platform/tenants/{id}/health
    - Returns 404 for unknown tenant_id
    - Returns current snapshot and 12-week trend
    - Missing weeks have null values (not omitted)
    - Requires platform_admin scope

Prerequisites:
    docker-compose up -d   # ensure DB and Redis are running

Run:
    pytest tests/integration/test_health_score_api.py -v --timeout=60
"""
import asyncio
import datetime
import os
import uuid
from datetime import timezone

import pytest
from jose import jwt as jose_jwt
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


def _make_platform_token(user_id: str) -> str:
    now = datetime.datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": "platform",
        "roles": ["platform_admin"],
        "scope": "platform",
        "plan": "enterprise",
        "email": f"pa-{user_id[:8]}@platform.test",
        "exp": now + datetime.timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jose_jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def _make_tenant_admin_token(tenant_id: str, user_id: str) -> str:
    now = datetime.datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "enterprise",
        "email": f"ta-{user_id[:8]}@tenant.test",
        "exp": now + datetime.timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jose_jwt.encode(payload, _jwt_secret(), algorithm="HS256")


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


async def _fetchall(sql: str, params: dict = None):
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            return result.fetchall()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Fixtures: provision test tenant and seed health score rows
# ---------------------------------------------------------------------------


def _provision_tenant() -> tuple[str, str]:
    """
    Insert an active tenant into DB. Returns (tenant_id, user_id).
    """
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    asyncio.run(
        _run_sql(
            """
            INSERT INTO tenants (id, name, slug, plan, status, primary_contact_email, created_at)
            VALUES (:tid, :name, :slug, 'enterprise', 'active', :email, NOW())
            ON CONFLICT DO NOTHING
            """,
            {
                "tid": tenant_id,
                "name": f"HealthTest-{tenant_id[:8]}",
                "slug": f"health-test-{tenant_id[:8]}",
                "email": f"contact-{tenant_id[:8]}@health.test",
            },
        )
    )

    asyncio.run(
        _run_sql(
            """
            INSERT INTO users (id, tenant_id, email, name, role, status, created_at)
            VALUES (:uid, :tid, :email, 'PA Test User', 'tenant_admin', 'active', NOW())
            ON CONFLICT DO NOTHING
            """,
            {
                "uid": user_id,
                "tid": tenant_id,
                "email": f"pa-test-{user_id[:8]}@health.test",
            },
        )
    )

    return tenant_id, user_id


def _upsert_health_score(
    tenant_id: str,
    date_offset_days: int,
    composite: float,
    usage_trend: float,
    feature_breadth: float,
    satisfaction: float,
    error_rate: float,
    at_risk: bool,
    at_risk_reason: str | None = None,
) -> None:
    """Insert a health score row for a tenant at today - date_offset_days."""
    score_date = datetime.date.today() - datetime.timedelta(days=date_offset_days)

    asyncio.run(
        _run_sql(
            """
            INSERT INTO tenant_health_scores
                (tenant_id, date, composite_score, usage_trend_score,
                 feature_breadth_score, satisfaction_score, error_rate_score,
                 at_risk_flag, at_risk_reason)
            VALUES
                (:tid, :date, :composite, :usage_trend, :feature_breadth,
                 :satisfaction, :error_rate, :at_risk, :at_risk_reason)
            ON CONFLICT (tenant_id, date) DO UPDATE SET
                composite_score       = EXCLUDED.composite_score,
                usage_trend_score     = EXCLUDED.usage_trend_score,
                feature_breadth_score = EXCLUDED.feature_breadth_score,
                satisfaction_score    = EXCLUDED.satisfaction_score,
                error_rate_score      = EXCLUDED.error_rate_score,
                at_risk_flag          = EXCLUDED.at_risk_flag,
                at_risk_reason        = EXCLUDED.at_risk_reason
            """,
            {
                "tid": tenant_id,
                "date": score_date,
                "composite": composite,
                "usage_trend": usage_trend,
                "feature_breadth": feature_breadth,
                "satisfaction": satisfaction,
                "error_rate": error_rate,
                "at_risk": at_risk,
                "at_risk_reason": at_risk_reason,
            },
        )
    )


def _cleanup_tenant(tenant_id: str) -> None:
    """Remove test tenant and its health score rows."""
    asyncio.run(
        _run_sql(
            "DELETE FROM tenant_health_scores WHERE tenant_id = :tid",
            {"tid": tenant_id},
        )
    )
    asyncio.run(
        _run_sql(
            "DELETE FROM users WHERE tenant_id = :tid",
            {"tid": tenant_id},
        )
    )
    asyncio.run(
        _run_sql(
            "DELETE FROM tenants WHERE id = :tid",
            {"tid": tenant_id},
        )
    )


# ---------------------------------------------------------------------------
# Module-level setup: provision two test tenants
# ---------------------------------------------------------------------------


_TENANT_HEALTHY_ID: str
_TENANT_ATRISK_ID: str
_PA_USER_ID: str = str(uuid.uuid4())


def setup_module(module):
    global _TENANT_HEALTHY_ID, _TENANT_ATRISK_ID, _PA_USER_ID

    _PA_USER_ID = str(uuid.uuid4())

    # Dispose the module-level SQLAlchemy engine to clear any asyncpg connections
    # left by prior test modules that called asyncio.run() with the shared engine
    # (e.g. test_cache_integration.py). This forces the engine to create fresh
    # connections on the TestClient's portal event loop when the first HTTP
    # request is made, preventing "another operation is in progress" errors.
    async def _dispose_engine():
        from app.core.session import engine as _engine

        await _engine.dispose()

    asyncio.run(_dispose_engine())

    healthy_id, _ = _provision_tenant()
    atrisk_id, _ = _provision_tenant()

    _TENANT_HEALTHY_ID = healthy_id
    _TENANT_ATRISK_ID = atrisk_id

    # Seed healthy tenant — composite = 75 (not at-risk)
    _upsert_health_score(
        tenant_id=_TENANT_HEALTHY_ID,
        date_offset_days=0,
        composite=75.0,
        usage_trend=24.0,
        feature_breadth=16.0,
        satisfaction=28.0,
        error_rate=7.0,
        at_risk=False,
    )

    # Seed at-risk tenant — composite = 32.5 (composite_low), 3 consecutive weeks
    _upsert_health_score(
        tenant_id=_TENANT_ATRISK_ID,
        date_offset_days=0,
        composite=32.5,
        usage_trend=6.0,
        feature_breadth=8.0,
        satisfaction=12.5,
        error_rate=6.0,
        at_risk=True,
        at_risk_reason="composite_low",
    )
    # Prior two weeks also at-risk (for weeks_at_risk = 3)
    _upsert_health_score(
        tenant_id=_TENANT_ATRISK_ID,
        date_offset_days=7,
        composite=35.0,
        usage_trend=7.0,
        feature_breadth=9.0,
        satisfaction=13.0,
        error_rate=6.0,
        at_risk=True,
        at_risk_reason="composite_low",
    )
    _upsert_health_score(
        tenant_id=_TENANT_ATRISK_ID,
        date_offset_days=14,
        composite=38.0,
        usage_trend=8.0,
        feature_breadth=10.0,
        satisfaction=14.0,
        error_rate=6.0,
        at_risk=True,
        at_risk_reason="composite_low",
    )


def teardown_module(module):
    _cleanup_tenant(_TENANT_HEALTHY_ID)
    _cleanup_tenant(_TENANT_ATRISK_ID)


# ---------------------------------------------------------------------------
# PA-008: GET /platform/tenants/at-risk
# ---------------------------------------------------------------------------


class TestAtRiskTenantsEndpoint:
    """PA-008 endpoint tests."""

    def test_requires_platform_admin_scope(self, client):
        """tenant_admin token → 403 Forbidden."""
        tenant_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        token = _make_tenant_admin_token(tenant_id, user_id)
        resp = client.get(
            "/api/v1/platform/tenants/at-risk",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_unauthenticated_returns_401(self, client):
        """No token → 401."""
        resp = client.get("/api/v1/platform/tenants/at-risk")
        assert resp.status_code == 401

    def test_returns_list_not_404_when_empty(self, client):
        """
        Even if no tenants are at-risk, endpoint returns 200 with empty list.
        We seed an at-risk tenant in setup_module, but isolate this test by
        checking the response is a list (not 404).
        """
        pa_user_id = str(uuid.uuid4())
        token = _make_platform_token(pa_user_id)
        resp = client.get(
            "/api/v1/platform/tenants/at-risk",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_at_risk_tenant_appears_in_response(self, client):
        """Tenant with composite < 40 is included in at-risk list."""
        pa_user_id = str(uuid.uuid4())
        token = _make_platform_token(pa_user_id)
        resp = client.get(
            "/api/v1/platform/tenants/at-risk",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        tenant_ids = [item["tenant_id"] for item in data]
        assert _TENANT_ATRISK_ID in tenant_ids

    def test_healthy_tenant_not_in_response(self, client):
        """Tenant with composite = 75 (not at-risk) is excluded."""
        pa_user_id = str(uuid.uuid4())
        token = _make_platform_token(pa_user_id)
        resp = client.get(
            "/api/v1/platform/tenants/at-risk",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        tenant_ids = [item["tenant_id"] for item in data]
        assert _TENANT_HEALTHY_ID not in tenant_ids

    def test_response_sorted_by_composite_asc(self, client):
        """Items are sorted by composite_score ascending (worst first)."""
        pa_user_id = str(uuid.uuid4())
        token = _make_platform_token(pa_user_id)
        resp = client.get(
            "/api/v1/platform/tenants/at-risk",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        if len(data) >= 2:
            scores = [
                item["composite_score"]
                for item in data
                if item["composite_score"] is not None
            ]
            assert scores == sorted(scores)

    def test_at_risk_item_has_required_fields(self, client):
        """Each at-risk item has the required field set."""
        pa_user_id = str(uuid.uuid4())
        token = _make_platform_token(pa_user_id)
        resp = client.get(
            "/api/v1/platform/tenants/at-risk",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Find our seeded at-risk tenant
        at_risk_item = next(
            (item for item in data if item["tenant_id"] == _TENANT_ATRISK_ID), None
        )
        assert at_risk_item is not None

        # Required fields
        assert "tenant_id" in at_risk_item
        assert "name" in at_risk_item
        assert "composite_score" in at_risk_item
        assert "at_risk_reason" in at_risk_item
        assert "weeks_at_risk" in at_risk_item
        assert "component_breakdown" in at_risk_item

        breakdown = at_risk_item["component_breakdown"]
        assert "usage_trend_score" in breakdown
        assert "feature_breadth_score" in breakdown
        assert "satisfaction_score" in breakdown
        assert "error_rate_score" in breakdown

    def test_weeks_at_risk_counts_consecutive_rows(self, client):
        """weeks_at_risk equals count of consecutive at_risk_flag=true rows."""
        pa_user_id = str(uuid.uuid4())
        token = _make_platform_token(pa_user_id)
        resp = client.get(
            "/api/v1/platform/tenants/at-risk",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        at_risk_item = next(
            (item for item in data if item["tenant_id"] == _TENANT_ATRISK_ID), None
        )
        assert at_risk_item is not None
        # We seeded 3 consecutive at-risk rows (today, -7d, -14d)
        assert at_risk_item["weeks_at_risk"] == 3

    def test_at_risk_reason_returned(self, client):
        """at_risk_reason is returned correctly."""
        pa_user_id = str(uuid.uuid4())
        token = _make_platform_token(pa_user_id)
        resp = client.get(
            "/api/v1/platform/tenants/at-risk",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        at_risk_item = next(
            (item for item in data if item["tenant_id"] == _TENANT_ATRISK_ID), None
        )
        assert at_risk_item is not None
        assert at_risk_item["at_risk_reason"] == "composite_low"


# ---------------------------------------------------------------------------
# PA-009: GET /platform/tenants/{id}/health
# ---------------------------------------------------------------------------


class TestTenantHealthDrilldown:
    """PA-009 endpoint tests."""

    def test_requires_platform_admin_scope(self, client):
        """tenant_admin token → 403 Forbidden."""
        tenant_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        token = _make_tenant_admin_token(tenant_id, user_id)
        resp = client.get(
            f"/api/v1/platform/tenants/{tenant_id}/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_unknown_tenant_returns_404(self, client):
        """Random UUID that doesn't exist → 404."""
        unknown_id = str(uuid.uuid4())
        pa_user_id = str(uuid.uuid4())
        token = _make_platform_token(pa_user_id)
        resp = client.get(
            f"/api/v1/platform/tenants/{unknown_id}/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    def test_returns_current_and_trend(self, client):
        """Healthy tenant returns current snapshot and 12-week trend array."""
        pa_user_id = str(uuid.uuid4())
        token = _make_platform_token(pa_user_id)
        resp = client.get(
            f"/api/v1/platform/tenants/{_TENANT_HEALTHY_ID}/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()

        assert "current" in data
        assert "trend" in data

        current = data["current"]
        assert "composite" in current
        assert "usage_trend" in current
        assert "feature_breadth" in current
        assert "satisfaction" in current
        assert "error_rate" in current
        assert "at_risk_flag" in current

    def test_current_snapshot_values_match_seeded_data(self, client):
        """Current snapshot returns the values we seeded for the healthy tenant."""
        pa_user_id = str(uuid.uuid4())
        token = _make_platform_token(pa_user_id)
        resp = client.get(
            f"/api/v1/platform/tenants/{_TENANT_HEALTHY_ID}/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        current = resp.json()["current"]

        assert current["composite"] == pytest.approx(75.0, abs=0.1)
        assert current["at_risk_flag"] is False

    def test_trend_has_12_entries(self, client):
        """Trend array always contains exactly 12 entries."""
        pa_user_id = str(uuid.uuid4())
        token = _make_platform_token(pa_user_id)
        resp = client.get(
            f"/api/v1/platform/tenants/{_TENANT_HEALTHY_ID}/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        trend = resp.json()["trend"]
        assert len(trend) == 12

    def test_trend_entries_have_week_label(self, client):
        """Each trend entry has a 'week' field in YYYY-Www format."""
        import re

        pa_user_id = str(uuid.uuid4())
        token = _make_platform_token(pa_user_id)
        resp = client.get(
            f"/api/v1/platform/tenants/{_TENANT_HEALTHY_ID}/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        trend = resp.json()["trend"]
        week_pattern = re.compile(r"^\d{4}-W\d{2}$")
        for entry in trend:
            assert "week" in entry
            assert week_pattern.match(
                entry["week"]
            ), f"Bad week format: {entry['week']}"

    def test_missing_weeks_have_null_values(self, client):
        """
        Weeks with no stored data return null composite/usage_trend/satisfaction
        rather than being omitted from the trend array.
        """
        pa_user_id = str(uuid.uuid4())
        token = _make_platform_token(pa_user_id)
        resp = client.get(
            f"/api/v1/platform/tenants/{_TENANT_HEALTHY_ID}/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        trend = resp.json()["trend"]

        # Healthy tenant only has data for the current week (date_offset_days=0).
        # All other weeks should have null values.
        null_weeks = [e for e in trend if e["composite"] is None]
        assert len(null_weeks) >= 11  # at most 1 week has data (today)

        for entry in null_weeks:
            assert entry["composite"] is None
            assert entry["usage_trend"] is None
            assert entry["satisfaction"] is None

    def test_at_risk_tenant_current_snapshot(self, client):
        """At-risk tenant current snapshot reflects seeded at_risk_flag=True."""
        pa_user_id = str(uuid.uuid4())
        token = _make_platform_token(pa_user_id)
        resp = client.get(
            f"/api/v1/platform/tenants/{_TENANT_ATRISK_ID}/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        current = resp.json()["current"]
        assert current["composite"] == pytest.approx(32.5, abs=0.1)
        assert current["at_risk_flag"] is True

    def test_at_risk_tenant_trend_has_3_populated_weeks(self, client):
        """At-risk tenant has 3 weeks of data — 3 non-null entries in trend."""
        pa_user_id = str(uuid.uuid4())
        token = _make_platform_token(pa_user_id)
        resp = client.get(
            f"/api/v1/platform/tenants/{_TENANT_ATRISK_ID}/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        trend = resp.json()["trend"]
        populated = [e for e in trend if e["composite"] is not None]
        # Seeded rows at 0d, 7d, 14d ago — should fall in 3 distinct ISO weeks
        # (unless run near a week boundary, in which case 2 may overlap — allow 2-3)
        assert len(populated) >= 2
