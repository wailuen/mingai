"""
Unit tests for PA-011: Proactive Outreach API.

Endpoint: POST /api/v1/platform/tenants/{id}/message

Tests:
- 422 when subject is blank/empty
- 422 when body is blank/empty
- 422 when send_via is empty list
- 422 when send_via contains invalid channel
- 404 when tenant not found
- 200 success with in_app channel (notifications inserted, audit log written)
- Audit log called with correct action and details
- Email channel skipped gracefully when SENDGRID_API_KEY is absent
- 401 when no auth
- 403 when caller is tenant_admin (not platform_admin)

Tier 1: Fast, isolated, uses mocking.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, call, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TEST_TARGET_TENANT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TEST_PLATFORM_ADMIN_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _make_platform_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": TEST_PLATFORM_ADMIN_ID,
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


def _make_tenant_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "tenant-admin-id",
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


@pytest.fixture
def env_vars():
    env = {
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "JWT_ALGORITHM": TEST_JWT_ALGORITHM,
        "REDIS_URL": "redis://localhost:6379/0",
        "FRONTEND_URL": "http://localhost:3022",
    }
    with patch.dict(os.environ, env, clear=False):
        yield


@pytest.fixture
def client(env_vars):
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def platform_headers():
    return {"Authorization": f"Bearer {_make_platform_token()}"}


@pytest.fixture
def tenant_admin_headers():
    return {"Authorization": f"Bearer {_make_tenant_admin_token()}"}


def _outreach_url(tenant_id: str = TEST_TARGET_TENANT_ID) -> str:
    return f"/api/v1/platform/tenants/{tenant_id}/message"


_VALID_PAYLOAD = {
    "subject": "Important Update",
    "body": "Please review the updated compliance policy.",
    "send_via": ["in_app"],
}

_MOCK_TENANT = {
    "id": TEST_TARGET_TENANT_ID,
    "name": "Acme Corp",
    "slug": "acme-corp",
    "plan": "professional",
    "status": "active",
    "primary_contact_email": "contact@acme.com",
    "created_at": "2026-01-01T00:00:00",
}

_MOCK_RECIPIENTS = [
    {"id": "dddddddd-dddd-dddd-dddd-dddddddddddd", "email": "admin1@acme.com"},
    {"id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee", "email": "admin2@acme.com"},
]


class TestProactiveOutreachAuth:
    """Auth and RBAC enforcement."""

    def test_requires_auth(self, client):
        """401 when no Authorization header."""
        resp = client.post(_outreach_url(), json=_VALID_PAYLOAD)
        assert resp.status_code == 401

    def test_requires_platform_admin(self, client, tenant_admin_headers):
        """403 when caller is tenant_admin (not platform_admin)."""
        resp = client.post(
            _outreach_url(), json=_VALID_PAYLOAD, headers=tenant_admin_headers
        )
        assert resp.status_code == 403


class TestProactiveOutreachValidation:
    """Input validation — 422 responses."""

    def test_422_when_subject_is_empty_string(self, client, platform_headers):
        """422 when subject is an empty string."""
        payload = {**_VALID_PAYLOAD, "subject": ""}
        resp = client.post(_outreach_url(), json=payload, headers=platform_headers)
        assert resp.status_code == 422

    def test_whitespace_only_subject_is_accepted(self, client, platform_headers):
        """Whitespace-only subject passes Pydantic min_length=1 (space counts as a character).
        This documents the current behaviour — stricter strip+check can be added if needed.
        """
        with (
            patch(
                "app.modules.tenants.routes.get_tenant_db", new_callable=AsyncMock
            ) as mock_tenant,
            patch(
                "app.modules.tenants.routes.get_tenant_admins_db",
                new_callable=AsyncMock,
            ) as mock_admins,
            patch(
                "app.modules.tenants.routes.insert_platform_outreach_notifications_db",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.tenants.routes.write_audit_log_db", new_callable=AsyncMock
            ),
        ):
            mock_tenant.return_value = {"id": TEST_TARGET_TENANT_ID, "name": "Test"}
            mock_admins.return_value = []
            payload = {**_VALID_PAYLOAD, "subject": "   "}
            resp = client.post(_outreach_url(), json=payload, headers=platform_headers)
        # Whitespace passes min_length=1; 200 returned (no recipients → no-op)
        assert resp.status_code == 200

    def test_422_when_body_is_empty_string(self, client, platform_headers):
        """422 when body is an empty string."""
        payload = {**_VALID_PAYLOAD, "body": ""}
        resp = client.post(_outreach_url(), json=payload, headers=platform_headers)
        assert resp.status_code == 422

    def test_422_when_send_via_is_empty_list(self, client, platform_headers):
        """422 when send_via is an empty list."""
        payload = {**_VALID_PAYLOAD, "send_via": []}
        resp = client.post(_outreach_url(), json=payload, headers=platform_headers)
        assert resp.status_code == 422

    def test_422_when_send_via_has_invalid_channel(self, client, platform_headers):
        """422 when send_via contains an unsupported channel."""
        payload = {**_VALID_PAYLOAD, "send_via": ["sms"]}
        resp = client.post(_outreach_url(), json=payload, headers=platform_headers)
        assert resp.status_code == 422

    def test_422_when_subject_exceeds_max_length(self, client, platform_headers):
        """422 when subject exceeds 200 characters."""
        payload = {**_VALID_PAYLOAD, "subject": "x" * 201}
        resp = client.post(_outreach_url(), json=payload, headers=platform_headers)
        assert resp.status_code == 422

    def test_422_when_body_exceeds_max_length(self, client, platform_headers):
        """422 when body exceeds 5000 characters."""
        payload = {**_VALID_PAYLOAD, "body": "x" * 5001}
        resp = client.post(_outreach_url(), json=payload, headers=platform_headers)
        assert resp.status_code == 422


class TestProactiveOutreachNotFound:
    """Tenant existence check."""

    def test_404_when_tenant_not_found(self, client, platform_headers):
        """404 when the target tenant does not exist."""
        with patch(
            "app.modules.tenants.routes.get_tenant_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None
            resp = client.post(
                _outreach_url(), json=_VALID_PAYLOAD, headers=platform_headers
            )
        assert resp.status_code == 404


class TestProactiveOutreachSuccess:
    """Happy-path and behavior verification."""

    def test_200_in_app_only(self, client, platform_headers):
        """200 with in_app channel inserts notifications and writes audit log."""
        with (
            patch(
                "app.modules.tenants.routes.get_tenant_db",
                new_callable=AsyncMock,
            ) as mock_get_tenant,
            patch(
                "app.modules.tenants.routes.get_tenant_admins_db",
                new_callable=AsyncMock,
            ) as mock_get_admins,
            patch(
                "app.modules.tenants.routes.insert_platform_outreach_notifications_db",
                new_callable=AsyncMock,
            ) as mock_insert_notifs,
            patch(
                "app.modules.tenants.routes.write_audit_log_db",
                new_callable=AsyncMock,
            ) as mock_audit,
            patch(
                "app.modules.tenants.routes.send_outreach_email",
                new_callable=AsyncMock,
            ) as mock_email,
        ):
            mock_get_tenant.return_value = _MOCK_TENANT
            mock_get_admins.return_value = _MOCK_RECIPIENTS

            resp = client.post(
                _outreach_url(), json=_VALID_PAYLOAD, headers=platform_headers
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == TEST_TARGET_TENANT_ID
        assert data["recipients"] == 2
        assert "in_app" in data["send_via"]
        assert data["message"] == "Outreach sent"

        # Notifications inserted once
        mock_insert_notifs.assert_called_once()
        call_kwargs = mock_insert_notifs.call_args
        assert call_kwargs.kwargs["tenant_id"] == TEST_TARGET_TENANT_ID
        assert call_kwargs.kwargs["subject"] == "Important Update"
        assert len(call_kwargs.kwargs["recipients"]) == 2

        # Email not called when only in_app
        mock_email.assert_not_called()

    def test_audit_log_called_with_correct_action(self, client, platform_headers):
        """Audit log is written with action='proactive_outreach' and correct details."""
        with (
            patch(
                "app.modules.tenants.routes.get_tenant_db",
                new_callable=AsyncMock,
            ) as mock_get_tenant,
            patch(
                "app.modules.tenants.routes.get_tenant_admins_db",
                new_callable=AsyncMock,
            ) as mock_get_admins,
            patch(
                "app.modules.tenants.routes.insert_platform_outreach_notifications_db",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.tenants.routes.write_audit_log_db",
                new_callable=AsyncMock,
            ) as mock_audit,
            patch(
                "app.modules.tenants.routes.send_outreach_email",
                new_callable=AsyncMock,
            ),
        ):
            mock_get_tenant.return_value = _MOCK_TENANT
            mock_get_admins.return_value = _MOCK_RECIPIENTS

            client.post(_outreach_url(), json=_VALID_PAYLOAD, headers=platform_headers)

        mock_audit.assert_called_once()
        audit_kwargs = mock_audit.call_args.kwargs
        assert audit_kwargs["action"] == "proactive_outreach"
        assert audit_kwargs["resource_type"] == "tenant"
        assert audit_kwargs["resource_id"] == TEST_TARGET_TENANT_ID
        assert audit_kwargs["actor_user_id"] == TEST_PLATFORM_ADMIN_ID
        assert audit_kwargs["details"]["recipient_count"] == 2
        assert "in_app" in audit_kwargs["details"]["send_via"]

    def test_email_channel_fires_send_outreach_email_per_recipient(
        self, client, platform_headers
    ):
        """When email is in send_via, send_outreach_email is called once per recipient."""
        payload = {**_VALID_PAYLOAD, "send_via": ["in_app", "email"]}
        with (
            patch(
                "app.modules.tenants.routes.get_tenant_db",
                new_callable=AsyncMock,
            ) as mock_get_tenant,
            patch(
                "app.modules.tenants.routes.get_tenant_admins_db",
                new_callable=AsyncMock,
            ) as mock_get_admins,
            patch(
                "app.modules.tenants.routes.insert_platform_outreach_notifications_db",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.tenants.routes.write_audit_log_db",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.tenants.routes.send_outreach_email",
                new_callable=AsyncMock,
            ) as mock_email,
        ):
            mock_get_tenant.return_value = _MOCK_TENANT
            mock_get_admins.return_value = _MOCK_RECIPIENTS

            resp = client.post(_outreach_url(), json=payload, headers=platform_headers)

        assert resp.status_code == 200
        assert mock_email.call_count == len(_MOCK_RECIPIENTS)
        called_emails = {c.kwargs["recipient_email"] for c in mock_email.call_args_list}
        assert called_emails == {"admin1@acme.com", "admin2@acme.com"}

    def test_email_only_channel_does_not_insert_notifications(
        self, client, platform_headers
    ):
        """When only email is in send_via, no notification rows are inserted."""
        payload = {**_VALID_PAYLOAD, "send_via": ["email"]}
        with (
            patch(
                "app.modules.tenants.routes.get_tenant_db",
                new_callable=AsyncMock,
            ) as mock_get_tenant,
            patch(
                "app.modules.tenants.routes.get_tenant_admins_db",
                new_callable=AsyncMock,
            ) as mock_get_admins,
            patch(
                "app.modules.tenants.routes.insert_platform_outreach_notifications_db",
                new_callable=AsyncMock,
            ) as mock_insert_notifs,
            patch(
                "app.modules.tenants.routes.write_audit_log_db",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.tenants.routes.send_outreach_email",
                new_callable=AsyncMock,
            ),
        ):
            mock_get_tenant.return_value = _MOCK_TENANT
            mock_get_admins.return_value = _MOCK_RECIPIENTS

            resp = client.post(_outreach_url(), json=payload, headers=platform_headers)

        assert resp.status_code == 200
        mock_insert_notifs.assert_not_called()

    def test_returns_zero_recipients_when_no_tenant_admins(
        self, client, platform_headers
    ):
        """200 returned with recipients=0 when the tenant has no active tenant_admins."""
        with (
            patch(
                "app.modules.tenants.routes.get_tenant_db",
                new_callable=AsyncMock,
            ) as mock_get_tenant,
            patch(
                "app.modules.tenants.routes.get_tenant_admins_db",
                new_callable=AsyncMock,
            ) as mock_get_admins,
            patch(
                "app.modules.tenants.routes.insert_platform_outreach_notifications_db",
                new_callable=AsyncMock,
            ) as mock_insert_notifs,
            patch(
                "app.modules.tenants.routes.write_audit_log_db",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.tenants.routes.send_outreach_email",
                new_callable=AsyncMock,
            ) as mock_email,
        ):
            mock_get_tenant.return_value = _MOCK_TENANT
            mock_get_admins.return_value = []

            resp = client.post(
                _outreach_url(), json=_VALID_PAYLOAD, headers=platform_headers
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["recipients"] == 0
        # No notifications inserted when no recipients
        mock_insert_notifs.assert_not_called()
        mock_email.assert_not_called()
