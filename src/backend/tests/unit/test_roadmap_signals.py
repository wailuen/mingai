"""
Unit tests for PA-028: Roadmap signal board API.

  GET /platform/roadmap-signals

Tier 1: Fast, isolated. Uses dependency_overrides + AsyncMock.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"

_SIGNALS_URL = "/api/v1/platform/roadmap-signals"


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


def _patch_db_signals(signal_rows):
    """Patch get_async_session for roadmap-signals endpoint.

    Call order:
      1. set_config scope
      2. set_config tenant_id clear
      3. signals query → signal_rows
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
            mock_result.fetchall.return_value = []
        else:
            mock_result.fetchall.return_value = signal_rows
        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    import contextlib

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


class TestRoadmapSignalsAuth:
    def test_requires_auth(self, client):
        resp = client.get(_SIGNALS_URL)
        assert resp.status_code == 401

    def test_requires_platform_admin(self, client):
        resp = client.get(_SIGNALS_URL, headers=_tenant_headers())
        assert resp.status_code == 403


class TestRoadmapSignalsHappyPath:
    def test_returns_signals_and_total(self, client):
        rows = [
            ("add sso integration", 5, 13, 2, 2, 1),
            ("bulk export", 3, 7, 1, 2, 0),
        ]
        with _patch_db_signals(rows):
            resp = client.get(_SIGNALS_URL, headers=_platform_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "signals" in data
        assert "total" in data
        assert data["total"] == 2

    def test_signal_structure(self, client):
        rows = [
            ("add sso integration", 5, 13, 2, 2, 1),
        ]
        with _patch_db_signals(rows):
            resp = client.get(_SIGNALS_URL, headers=_platform_headers())
        signal = resp.json()["signals"][0]
        assert signal["signal"] == "add sso integration"
        assert signal["count"] == 5
        assert signal["weighted_score"] == 13
        assert signal["plan_breakdown"]["enterprise"] == 2
        assert signal["plan_breakdown"]["professional"] == 2
        assert signal["plan_breakdown"]["starter"] == 1

    def test_empty_signals_returns_empty_list(self, client):
        with _patch_db_signals([]):
            resp = client.get(_SIGNALS_URL, headers=_platform_headers())
        assert resp.status_code == 200
        assert resp.json()["signals"] == []
        assert resp.json()["total"] == 0

    def test_limit_clamped_to_200(self, client):
        """limit > 200 should be clamped to 200 (no error)."""
        with _patch_db_signals([]):
            resp = client.get(_SIGNALS_URL + "?limit=9999", headers=_platform_headers())
        assert resp.status_code == 200
