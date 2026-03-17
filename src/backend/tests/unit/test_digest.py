"""
Unit tests for PA-034: Platform daily digest email.

  PATCH /platform/digest/config
  GET   /platform/digest/config
  POST  /platform/digest/preview

Tier 1: Fast, isolated.
"""
import contextlib
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"

_CONFIG_URL = "/api/v1/platform/digest/config"
_PREVIEW_URL = "/api/v1/platform/digest/preview"


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
        "sub": "tenant-user-001",
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


def _mock_prefs(prefs_store: dict):
    """Patch _get_platform_prefs and _save_platform_prefs to use in-memory store."""

    async def _get(user_id: str) -> dict:
        return dict(prefs_store)

    async def _save(user_id: str, prefs: dict) -> None:
        prefs_store.clear()
        prefs_store.update(prefs)

    return (
        patch("app.modules.platform.routes._get_platform_prefs", side_effect=_get),
        patch("app.modules.platform.routes._save_platform_prefs", side_effect=_save),
    )


def _patch_db_preview(
    new_issues=3,
    now_at_risk=2,
    prev_at_risk=1,
    yesterday_cost=150.0,
    week_avg=100.0,
    open_alerts=1,
):
    """Patch DB for POST /platform/digest/preview.

    Call order:
      1. set_config scope
      2. set_config tenant_id
      3. new issues COUNT scalar
      4. at-risk query fetchone → (now_at_risk, prev_at_risk)
      5. cost query fetchone → (yesterday_cost, week_avg)
      6. open alerts COUNT scalar
    """
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()
    call_count = 0

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count <= 2:
            mock_result.scalar.return_value = None
            mock_result.fetchone.return_value = None
        elif call_count == 3:
            mock_result.scalar.return_value = new_issues
        elif call_count == 4:
            mock_result.fetchone.return_value = (now_at_risk, prev_at_risk)
        elif call_count == 5:
            mock_result.fetchone.return_value = (yesterday_cost, week_avg)
        elif call_count == 6:
            mock_result.scalar.return_value = open_alerts
        else:
            mock_result.scalar.return_value = None
            mock_result.fetchone.return_value = None
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


class TestDigestConfigAuth:
    def test_patch_requires_auth(self, client):
        resp = client.patch(_CONFIG_URL, json={"enabled": True})
        assert resp.status_code == 401

    def test_patch_requires_platform_admin(self, client):
        resp = client.patch(
            _CONFIG_URL, json={"enabled": True}, headers=_tenant_headers()
        )
        assert resp.status_code == 403

    def test_preview_requires_auth(self, client):
        resp = client.post(_PREVIEW_URL)
        assert resp.status_code == 401


class TestDigestConfig:
    def test_patch_updates_config(self, client):
        store = {}
        p1, p2 = _mock_prefs(store)
        with p1, p2:
            resp = client.patch(
                _CONFIG_URL,
                json={"enabled": True, "time": "07:00", "recipients": ["a@b.com"]},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["time"] == "07:00"
        assert "a@b.com" in data["recipients"]

    def test_invalid_time_format_returns_422(self, client):
        store = {}
        p1, p2 = _mock_prefs(store)
        with p1, p2:
            resp = client.patch(
                _CONFIG_URL,
                json={"time": "25:99"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 422

    def test_get_returns_defaults_when_not_set(self, client):
        store = {}
        p1, p2 = _mock_prefs(store)
        with p1, p2:
            resp = client.get(_CONFIG_URL, headers=_platform_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "time" in data


class TestDigestPreview:
    def test_preview_returns_content_and_text(self, client):
        with _patch_db_preview():
            resp = client.post(_PREVIEW_URL, headers=_platform_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "content" in data
        assert "text_preview" in data

    def test_preview_content_structure(self, client):
        with _patch_db_preview(
            new_issues=5,
            now_at_risk=3,
            prev_at_risk=2,
            yesterday_cost=200.0,
            week_avg=100.0,
            open_alerts=2,
        ):
            resp = client.post(_PREVIEW_URL, headers=_platform_headers())
        content = resp.json()["content"]
        assert content["new_issues_24h"] == 5
        assert content["at_risk_tenants"] == 3
        assert content["at_risk_change"] == 1  # 3 - 2
        assert content["cost_variance_pct"] == 100.0  # (200-100)/100*100
        assert content["open_template_alerts"] == 2

    def test_preview_text_includes_key_metrics(self, client):
        with _patch_db_preview(new_issues=3):
            resp = client.post(_PREVIEW_URL, headers=_platform_headers())
        text = resp.json()["text_preview"]
        assert "New Issues" in text
        assert "mingai Platform Daily Digest" in text

    def test_cost_variance_zero_when_no_history(self, client):
        """Zero week_avg should not cause ZeroDivisionError."""
        with _patch_db_preview(yesterday_cost=0.0, week_avg=0.0):
            resp = client.post(_PREVIEW_URL, headers=_platform_headers())
        assert resp.status_code == 200
        assert resp.json()["content"]["cost_variance_pct"] == 0.0
