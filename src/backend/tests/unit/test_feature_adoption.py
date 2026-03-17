"""
Unit tests for PA-029: Feature adoption API.

  GET /platform/feature-adoption

Tier 1: Fast, isolated. Uses dependency_overrides + AsyncMock.
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from datetime import datetime, timedelta, timezone

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"

_ADOPTION_URL = "/api/v1/platform/feature-adoption"


def _make_platform_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "platform-admin-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["platform_admin"],
        "scope": "platform",
        "plan": "enterprise",
        "email": "platform@mingai.io",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_tenant_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "tenant-admin-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


@pytest.fixture
def env_vars():
    env = {
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "JWT_ALGORITHM": TEST_JWT_ALGORITHM,
        "REDIS_URL": "redis://localhost:6379/0",
        "FRONTEND_URL": "http://localhost:3022",
    }
    with patch.dict(os.environ, env):
        yield


@pytest.fixture
def client(env_vars):
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def _platform_headers() -> dict:
    return {"Authorization": f"Bearer {_make_platform_token()}"}


def _tenant_headers() -> dict:
    return {"Authorization": f"Bearer {_make_tenant_token()}"}


def _patch_db_adoption(total_active: int, adoption_rows: list):
    """Patch get_async_session for feature-adoption endpoint.

    Call order:
      1. set_config scope
      2. set_config tenant_id
      3. COUNT(*) active tenants → scalar → total_active
      4. analytics_events per-feature query → adoption_rows
    """
    from app.core.session import get_async_session
    from app.main import app

    import contextlib

    mock_session = MagicMock()
    call_count = 0

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count <= 2:
            # set_config calls — result not used
            mock_result.fetchall.return_value = []
            mock_result.fetchone.return_value = None
            mock_result.scalar.return_value = None
        elif call_count == 3:
            # COUNT(*) active tenants
            mock_result.scalar.return_value = total_active
            mock_result.fetchall.return_value = []
            mock_result.fetchone.return_value = (total_active,)
        else:
            # analytics_events adoption query
            mock_result.fetchall.return_value = adoption_rows
        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    async def _override():
        yield mock_session

    app.dependency_overrides[get_async_session] = _override

    @contextlib.contextmanager
    def _ctx():
        try:
            yield
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    return _ctx()


class TestFeatureAdoptionAuth:
    def test_requires_auth(self, client):
        resp = client.get(_ADOPTION_URL)
        assert resp.status_code == 401

    def test_requires_platform_admin(self, client):
        resp = client.get(_ADOPTION_URL, headers=_tenant_headers())
        assert resp.status_code == 403


class TestFeatureAdoptionHappyPath:
    def test_returns_features_and_total(self, client):
        rows = [
            ("chat", 8, 240, 4),
            ("glossary", 5, 100, 2),
        ]
        with _patch_db_adoption(10, rows):
            resp = client.get(_ADOPTION_URL, headers=_platform_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "features" in data
        assert "total_active_tenants" in data
        assert data["total_active_tenants"] == 10

    def test_all_seven_features_always_present(self, client):
        """Even with zero analytics data, all 7 features must appear."""
        with _patch_db_adoption(5, []):
            resp = client.get(_ADOPTION_URL, headers=_platform_headers())
        assert resp.status_code == 200
        feature_names = [f["feature"] for f in resp.json()["features"]]
        for expected in [
            "chat",
            "glossary",
            "agent_templates",
            "knowledge_base",
            "sso",
            "cost_analytics",
            "cache_analytics",
        ]:
            assert expected in feature_names

    def test_zero_active_tenants_returns_zero_pct(self, client):
        """When total_active_tenants == 0 adoption_pct must be 0.0, not ZeroDivisionError."""
        rows = [("chat", 0, 0, 0)]
        with _patch_db_adoption(0, rows):
            resp = client.get(_ADOPTION_URL, headers=_platform_headers())
        assert resp.status_code == 200
        chat = next(f for f in resp.json()["features"] if f["feature"] == "chat")
        assert chat["adoption_pct"] == 0.0

    def test_feature_structure(self, client):
        """Each feature dict must have the required keys with correct types."""
        rows = [
            ("chat", 4, 80, 2),
        ]
        with _patch_db_adoption(10, rows):
            resp = client.get(_ADOPTION_URL, headers=_platform_headers())
        data = resp.json()
        chat = next(f for f in data["features"] if f["feature"] == "chat")
        assert chat["adopted_tenant_count"] == 4
        assert chat["total_active_tenants"] == 10
        assert chat["adoption_pct"] == 40.0
        # avg_sessions_per_week_per_tenant = 80 events / 2 weeks / 4 tenants = 10.0
        assert chat["avg_sessions_per_week_per_tenant"] == 10.0

    def test_untracked_feature_has_zero_stats(self, client):
        """Features not in analytics_events rows get zeroed-out stats."""
        # Only 'chat' has data — all others should be zero
        rows = [("chat", 3, 30, 1)]
        with _patch_db_adoption(10, rows):
            resp = client.get(_ADOPTION_URL, headers=_platform_headers())
        sso = next(f for f in resp.json()["features"] if f["feature"] == "sso")
        assert sso["adopted_tenant_count"] == 0
        assert sso["adoption_pct"] == 0.0
        assert sso["avg_sessions_per_week_per_tenant"] == 0.0

    def test_days_param_clamped_to_365(self, client):
        """days > 365 is clamped to 365 (no error)."""
        with _patch_db_adoption(5, []):
            resp = client.get(_ADOPTION_URL + "?days=9999", headers=_platform_headers())
        assert resp.status_code == 200

    def test_days_param_clamped_minimum_1(self, client):
        """days < 1 is clamped to 1 (no error)."""
        with _patch_db_adoption(5, []):
            resp = client.get(_ADOPTION_URL + "?days=0", headers=_platform_headers())
        assert resp.status_code == 200
