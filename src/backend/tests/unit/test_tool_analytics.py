"""
Unit tests for PA-033: Tool usage analytics API.

  GET /platform/tools/{id}/analytics

Tier 1: Fast, isolated. Uses dependency_overrides + AsyncMock.
"""
import contextlib
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"
TEST_TOOL_ID = str(uuid.uuid4())

_BASE_URL = f"/api/v1/platform/tools/{TEST_TOOL_ID}/analytics"


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


def _patch_db_analytics(tool_row, daily_rows):
    """Patch get_async_session for tool analytics endpoint.

    Call order:
      1. set_config scope
      2. set_config tenant_id
      3. SELECT tool exists → fetchone → tool_row
      4. SELECT daily analytics → fetchall → daily_rows
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
            mock_result.fetchone.return_value = None
            mock_result.fetchall.return_value = []
        elif call_count == 3:
            mock_result.fetchone.return_value = tool_row
            mock_result.fetchall.return_value = []
        else:
            mock_result.fetchall.return_value = daily_rows
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


def _make_tool_row():
    return (uuid.UUID(TEST_TOOL_ID), "test-tool")


def _make_daily_row(day, invocations=10, errors=1, p50=50.0, p95=200.0):
    return (day, invocations, errors, p50, p95)


class TestToolAnalyticsAuth:
    def test_requires_auth(self, client):
        resp = client.get(_BASE_URL)
        assert resp.status_code == 401

    def test_requires_platform_admin(self, client):
        resp = client.get(_BASE_URL, headers=_tenant_headers())
        assert resp.status_code == 403


class TestToolAnalyticsHappyPath:
    def test_returns_expected_structure(self, client):
        rows = [_make_daily_row(date(2026, 3, 15))]
        with _patch_db_analytics(_make_tool_row(), rows):
            resp = client.get(_BASE_URL, headers=_platform_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool_id"] == TEST_TOOL_ID
        assert data["tool_name"] == "test-tool"
        assert "daily" in data
        assert "total_invocations" in data
        assert "overall_error_rate" in data

    def test_daily_row_structure(self, client):
        rows = [
            _make_daily_row(
                date(2026, 3, 15), invocations=20, errors=2, p50=45.0, p95=180.0
            )
        ]
        with _patch_db_analytics(_make_tool_row(), rows):
            resp = client.get(_BASE_URL, headers=_platform_headers())
        day = resp.json()["daily"][0]
        assert day["date"] == "2026-03-15"
        assert day["invocations"] == 20
        assert day["error_rate"] == 0.1  # 2/20
        assert day["p50_latency_ms"] == 45.0
        assert day["p95_latency_ms"] == 180.0

    def test_zero_invocations_no_division_error(self, client):
        rows = [
            _make_daily_row(
                date(2026, 3, 15), invocations=0, errors=0, p50=None, p95=None
            )
        ]
        with _patch_db_analytics(_make_tool_row(), rows):
            resp = client.get(_BASE_URL, headers=_platform_headers())
        assert resp.status_code == 200
        day = resp.json()["daily"][0]
        assert day["error_rate"] == 0.0

    def test_missing_tool_returns_404(self, client):
        # tool_row = None (tool not found)
        from app.core.session import get_async_session
        from app.main import app

        mock_session = MagicMock()
        call_count = 0

        async def _execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            mock_result.fetchone.return_value = None
            mock_result.fetchall.return_value = []
            return mock_result

        mock_session.execute = AsyncMock(side_effect=_execute)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock()

        async def _override():
            yield mock_session

        app.dependency_overrides[get_async_session] = _override
        try:
            resp = client.get(_BASE_URL, headers=_platform_headers())
        finally:
            app.dependency_overrides.pop(get_async_session, None)

        assert resp.status_code == 404

    def test_empty_daily_data(self, client):
        with _patch_db_analytics(_make_tool_row(), []):
            resp = client.get(_BASE_URL, headers=_platform_headers())
        assert resp.status_code == 200
        assert resp.json()["daily"] == []
        assert resp.json()["total_invocations"] == 0
        assert resp.json()["overall_error_rate"] == 0.0

    def test_days_param_respected(self, client):
        with _patch_db_analytics(_make_tool_row(), []):
            resp = client.get(_BASE_URL + "?days=7", headers=_platform_headers())
        assert resp.status_code == 200
        assert resp.json()["days"] == 7
