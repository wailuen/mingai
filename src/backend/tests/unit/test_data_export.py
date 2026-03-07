"""
Unit tests for API-104: GET /me/data-export — GDPR profile data export.

Tier 1: Fast, isolated, uses mocking for DB layer.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"
TEST_USER_ID = "user-001"

DATA_EXPORT_URL = "/api/v1/me/data-export"


def _make_token(
    user_id: str = TEST_USER_ID,
    tenant_id: str = TEST_TENANT_ID,
    roles: list[str] | None = None,
    scope: str = "tenant",
    plan: str = "professional",
) -> str:
    if roles is None:
        roles = ["end_user"]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": scope,
        "plan": plan,
        "email": "user@test.com",
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


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {_make_token()}"}


class TestDataExportAuth:
    """Auth gating for GDPR data export."""

    def test_data_export_requires_auth(self, client):
        """No auth header should get 401."""
        resp = client.get(DATA_EXPORT_URL)
        assert resp.status_code == 401


class TestDataExportResponse:
    """Response structure and content for GDPR data export."""

    def test_data_export_returns_all_sections(self, client, auth_headers):
        """Response must include profile, memory_notes, working_memory, org_context, exported_at."""
        with patch(
            "app.modules.users.routes.export_user_data_db",
            new_callable=AsyncMock,
        ) as mock_export:
            mock_export.return_value = {
                "profile": {
                    "id": TEST_USER_ID,
                    "email": "user@test.com",
                    "name": "Test User",
                },
                "memory_notes": [{"id": "note-1", "content": "Remember to call Bob"}],
                "working_memory": {"topics": ["finance"], "recent_queries": []},
                "org_context": {},
                "exported_at": "2026-03-07T12:00:00+00:00",
            }
            resp = client.get(DATA_EXPORT_URL, headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "profile" in data
        assert "memory_notes" in data
        assert "working_memory" in data
        assert "org_context" in data
        assert "exported_at" in data

    def test_data_export_scoped_to_current_user(self, client, auth_headers):
        """The export helper must be called with the current user's ID and tenant."""
        with patch(
            "app.modules.users.routes.export_user_data_db",
            new_callable=AsyncMock,
        ) as mock_export:
            mock_export.return_value = {
                "profile": {},
                "memory_notes": [],
                "working_memory": {},
                "org_context": {},
                "exported_at": "2026-03-07T12:00:00+00:00",
            }
            resp = client.get(DATA_EXPORT_URL, headers=auth_headers)

        assert resp.status_code == 200
        mock_export.assert_called_once()
        call_kwargs = mock_export.call_args[1]
        assert call_kwargs["user_id"] == TEST_USER_ID
        assert call_kwargs["tenant_id"] == TEST_TENANT_ID

    def test_data_export_exported_at_is_iso8601(self, client, auth_headers):
        """exported_at field must be a valid ISO 8601 timestamp."""
        with patch(
            "app.modules.users.routes.export_user_data_db",
            new_callable=AsyncMock,
        ) as mock_export:
            mock_export.return_value = {
                "profile": {},
                "memory_notes": [],
                "working_memory": {},
                "org_context": {},
                "exported_at": "2026-03-07T12:00:00+00:00",
            }
            resp = client.get(DATA_EXPORT_URL, headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        # Verify it parses as ISO 8601
        exported_at = data["exported_at"]
        parsed = datetime.fromisoformat(exported_at)
        assert parsed is not None
        assert isinstance(parsed, datetime)
