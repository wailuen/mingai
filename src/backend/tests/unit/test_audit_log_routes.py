"""
Unit tests for audit log API endpoints (API-087).

Tests auth, RBAC, and response structure for:
- GET /api/v1/admin/audit-log

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


def _make_tenant_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "tenant-admin-user",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": "admin@tenant.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_end_user_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "end-user",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["end_user"],
        "scope": "tenant",
        "plan": "professional",
        "email": "user@tenant.com",
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
def admin_headers():
    return {"Authorization": f"Bearer {_make_tenant_admin_token()}"}


@pytest.fixture
def user_headers():
    return {"Authorization": f"Bearer {_make_end_user_token()}"}


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_AUDIT_ITEMS = [
    {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "actor_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "actor_email": "admin@tenant.com",
        "action": "user.invite",
        "resource_type": "user",
        "resource_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "metadata": {"count": 3},
        "created_at": "2026-03-07T10:00:00+00:00",
    },
    {
        "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "actor_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "actor_email": "admin@tenant.com",
        "action": "settings.update",
        "resource_type": "workspace",
        "resource_id": None,
        "metadata": {},
        "created_at": "2026-03-06T15:30:00+00:00",
    },
]


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestAuditLogAuth:
    """GET /admin/audit-log - auth and RBAC."""

    def test_requires_auth(self, client):
        """401 when no Authorization header."""
        resp = client.get("/api/v1/admin/audit-log")
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client, user_headers):
        """403 when end_user tries to access."""
        resp = client.get("/api/v1/admin/audit-log", headers=user_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Response structure tests
# ---------------------------------------------------------------------------


class TestAuditLogEmpty:
    """Behavior when audit log has no entries."""

    def test_audit_log_empty_returns_empty_items(self, client, admin_headers):
        """Returns empty items list and total=0 when no entries."""
        with patch(
            "app.modules.admin.audit_log.get_audit_log_db",
            new_callable=AsyncMock,
        ) as mock_db:
            mock_db.return_value = ([], 0)
            resp = client.get("/api/v1/admin/audit-log", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["page_size"] == 20

    def test_audit_log_empty_has_pagination_fields(self, client, admin_headers):
        """Response always includes page and page_size even when empty."""
        with patch(
            "app.modules.admin.audit_log.get_audit_log_db",
            new_callable=AsyncMock,
        ) as mock_db:
            mock_db.return_value = ([], 0)
            resp = client.get(
                "/api/v1/admin/audit-log?page=2&page_size=10", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["page_size"] == 10


class TestAuditLogEntries:
    """Behavior when audit log has entries."""

    def test_audit_log_returns_entries(self, client, admin_headers):
        """Returns items list with correct structure when entries exist."""
        with patch(
            "app.modules.admin.audit_log.get_audit_log_db",
            new_callable=AsyncMock,
        ) as mock_db:
            mock_db.return_value = (SAMPLE_AUDIT_ITEMS, 2)
            resp = client.get("/api/v1/admin/audit-log", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

        item = data["items"][0]
        assert "id" in item
        assert "actor_id" in item
        assert "actor_email" in item
        assert "action" in item
        assert "resource_type" in item
        assert "resource_id" in item
        assert "metadata" in item
        assert "created_at" in item

    def test_audit_log_item_fields_types(self, client, admin_headers):
        """Each item has the correct types for all fields."""
        with patch(
            "app.modules.admin.audit_log.get_audit_log_db",
            new_callable=AsyncMock,
        ) as mock_db:
            mock_db.return_value = (SAMPLE_AUDIT_ITEMS, 2)
            resp = client.get("/api/v1/admin/audit-log", headers=admin_headers)
        data = resp.json()
        item = data["items"][0]
        assert isinstance(item["id"], str)
        assert isinstance(item["action"], str)
        assert isinstance(item["actor_email"], str)
        assert isinstance(item["metadata"], dict)


class TestAuditLogFilters:
    """Filter parameter handling."""

    def test_audit_log_filter_by_action_passes_to_db(self, client, admin_headers):
        """action filter is passed through to the DB layer."""
        with patch(
            "app.modules.admin.audit_log.get_audit_log_db",
            new_callable=AsyncMock,
        ) as mock_db:
            mock_db.return_value = ([], 0)
            resp = client.get(
                "/api/v1/admin/audit-log?action=user.invite", headers=admin_headers
            )
        assert resp.status_code == 200
        call_kwargs = mock_db.call_args.kwargs
        assert call_kwargs.get("action") == "user.invite"

    def test_audit_log_filter_by_actor_passes_to_db(self, client, admin_headers):
        """actor_id filter is passed through to the DB layer."""
        actor = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        with patch(
            "app.modules.admin.audit_log.get_audit_log_db",
            new_callable=AsyncMock,
        ) as mock_db:
            mock_db.return_value = ([], 0)
            resp = client.get(
                f"/api/v1/admin/audit-log?actor_id={actor}", headers=admin_headers
            )
        assert resp.status_code == 200
        call_kwargs = mock_db.call_args.kwargs
        assert call_kwargs.get("actor_id") == actor

    def test_audit_log_filter_by_resource_type_passes_to_db(
        self, client, admin_headers
    ):
        """resource_type filter is passed through to the DB layer."""
        with patch(
            "app.modules.admin.audit_log.get_audit_log_db",
            new_callable=AsyncMock,
        ) as mock_db:
            mock_db.return_value = ([], 0)
            resp = client.get(
                "/api/v1/admin/audit-log?resource_type=user", headers=admin_headers
            )
        assert resp.status_code == 200
        call_kwargs = mock_db.call_args.kwargs
        assert call_kwargs.get("resource_type") == "user"

    def test_audit_log_search_passes_to_db(self, client, admin_headers):
        """search filter is passed through to the DB layer."""
        with patch(
            "app.modules.admin.audit_log.get_audit_log_db",
            new_callable=AsyncMock,
        ) as mock_db:
            mock_db.return_value = ([], 0)
            resp = client.get(
                "/api/v1/admin/audit-log?search=invite", headers=admin_headers
            )
        assert resp.status_code == 200
        call_kwargs = mock_db.call_args.kwargs
        assert call_kwargs.get("search") == "invite"

    def test_audit_log_page_size_max_100(self, client, admin_headers):
        """page_size above 100 returns 422 validation error."""
        resp = client.get(
            "/api/v1/admin/audit-log?page_size=200", headers=admin_headers
        )
        assert resp.status_code == 422

    def test_audit_log_page_size_accepted(self, client, admin_headers):
        """page_size within bounds is accepted."""
        with patch(
            "app.modules.admin.audit_log.get_audit_log_db",
            new_callable=AsyncMock,
        ) as mock_db:
            mock_db.return_value = ([], 0)
            resp = client.get(
                "/api/v1/admin/audit-log?page_size=50", headers=admin_headers
            )
        assert resp.status_code == 200
        call_kwargs = mock_db.call_args.kwargs
        assert call_kwargs.get("page_size") == 50
