"""
Unit tests for API-044: POST /admin/users/bulk-invite — CSV bulk user invite.

Tier 1: Fast, isolated, uses mocking for DB layer.
"""
import io
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

BULK_INVITE_URL = "/api/v1/admin/users/bulk-invite"


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
def user_headers():
    return {"Authorization": f"Bearer {_make_token()}"}


@pytest.fixture
def admin_headers():
    return {
        "Authorization": f"Bearer {_make_token(roles=['tenant_admin'], scope='tenant')}"
    }


def _csv_file(content: str, filename: str = "users.csv"):
    """Create a file-like tuple for multipart upload."""
    return {"file": (filename, io.BytesIO(content.encode("utf-8")), "text/csv")}


class TestBulkInviteAuth:
    """Auth and role gating for bulk invite."""

    def test_bulk_invite_requires_tenant_admin(self, client, user_headers):
        """End users (non-admin) should get 403."""
        csv_content = "email,name,role\nalice@acme.com,Alice Smith,end_user\n"
        resp = client.post(
            BULK_INVITE_URL,
            files=_csv_file(csv_content),
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_bulk_invite_requires_auth(self, client):
        """No auth header should get 401."""
        csv_content = "email,name,role\nalice@acme.com,Alice Smith,end_user\n"
        resp = client.post(
            BULK_INVITE_URL,
            files=_csv_file(csv_content),
        )
        assert resp.status_code == 401


class TestBulkInviteValidation:
    """CSV validation before any invites are sent."""

    def test_bulk_invite_rejects_non_csv(self, client, admin_headers):
        """Non-CSV file extension should be rejected with 422."""
        files = {
            "file": (
                "users.xlsx",
                io.BytesIO(b"not csv content"),
                "application/vnd.ms-excel",
            )
        }
        resp = client.post(
            BULK_INVITE_URL,
            files=files,
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_bulk_invite_rejects_invalid_email(self, client, admin_headers):
        """Rows with bad emails should appear in errors."""
        csv_content = "email,name,role\nnot-an-email,Bad User,end_user\n"
        with patch(
            "app.modules.users.routes.bulk_invite_check_quota",
            new_callable=AsyncMock,
            return_value=500,
        ), patch(
            "app.modules.users.routes.bulk_invite_check_existing",
            new_callable=AsyncMock,
            return_value=set(),
        ):
            resp = client.post(
                BULK_INVITE_URL,
                files=_csv_file(csv_content),
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed"] == 1
        assert data["successful"] == 0
        assert len(data["errors"]) == 1
        assert "email" in data["errors"][0]["reason"].lower()

    def test_bulk_invite_rejects_invalid_role(self, client, admin_headers):
        """Rows with invalid roles should appear in errors."""
        csv_content = "email,name,role\nalice@acme.com,Alice,superadmin\n"
        with patch(
            "app.modules.users.routes.bulk_invite_check_quota",
            new_callable=AsyncMock,
            return_value=500,
        ), patch(
            "app.modules.users.routes.bulk_invite_check_existing",
            new_callable=AsyncMock,
            return_value=set(),
        ):
            resp = client.post(
                BULK_INVITE_URL,
                files=_csv_file(csv_content),
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed"] == 1
        assert len(data["errors"]) == 1
        assert "role" in data["errors"][0]["reason"].lower()

    def test_bulk_invite_max_500_rows_enforced(self, client, admin_headers):
        """CSV with more than 500 data rows should be rejected with 422."""
        header = "email,name,role\n"
        rows = "".join(f"user{i}@acme.com,User {i},end_user\n" for i in range(501))
        resp = client.post(
            BULK_INVITE_URL,
            files=_csv_file(header + rows),
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_bulk_invite_reports_duplicate_emails(self, client, admin_headers):
        """Duplicate emails within the CSV should be reported as errors."""
        csv_content = (
            "email,name,role\n"
            "alice@acme.com,Alice,end_user\n"
            "alice@acme.com,Alice Dup,tenant_admin\n"
        )
        with patch(
            "app.modules.users.routes.bulk_invite_check_quota",
            new_callable=AsyncMock,
            return_value=500,
        ), patch(
            "app.modules.users.routes.bulk_invite_check_existing",
            new_callable=AsyncMock,
            return_value=set(),
        ), patch(
            "app.modules.users.routes.bulk_invite_insert_db",
            new_callable=AsyncMock,
            return_value=1,
        ):
            resp = client.post(
                BULK_INVITE_URL,
                files=_csv_file(csv_content),
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed"] >= 1
        dup_errors = [e for e in data["errors"] if "duplicate" in e["reason"].lower()]
        assert len(dup_errors) >= 1

    def test_bulk_invite_validates_all_before_sending(self, client, admin_headers):
        """All rows should be validated before any invite is inserted."""
        csv_content = (
            "email,name,role\n"
            "valid@acme.com,Valid User,end_user\n"
            "bad-email,Bad User,end_user\n"
        )
        with patch(
            "app.modules.users.routes.bulk_invite_check_quota",
            new_callable=AsyncMock,
            return_value=500,
        ), patch(
            "app.modules.users.routes.bulk_invite_check_existing",
            new_callable=AsyncMock,
            return_value=set(),
        ), patch(
            "app.modules.users.routes.bulk_invite_insert_db",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_insert:
            resp = client.post(
                BULK_INVITE_URL,
                files=_csv_file(csv_content),
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        # Only valid rows are inserted; bad rows are errors
        assert data["successful"] == 1
        assert data["failed"] == 1
        # insert_db called only for valid rows
        assert mock_insert.call_count == 1


class TestBulkInviteSuccess:
    """Successful bulk invite returns summary."""

    def test_bulk_invite_returns_summary(self, client, admin_headers):
        """200 with total/successful/failed/errors on valid CSV."""
        csv_content = (
            "email,name,role\n"
            "alice@acme.com,Alice Smith,end_user\n"
            "bob@acme.com,Bob Jones,tenant_admin\n"
        )
        with patch(
            "app.modules.users.routes.bulk_invite_check_quota",
            new_callable=AsyncMock,
            return_value=500,
        ), patch(
            "app.modules.users.routes.bulk_invite_check_existing",
            new_callable=AsyncMock,
            return_value=set(),
        ), patch(
            "app.modules.users.routes.bulk_invite_insert_db",
            new_callable=AsyncMock,
            return_value=1,
        ):
            resp = client.post(
                BULK_INVITE_URL,
                files=_csv_file(csv_content),
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["successful"] == 2
        assert data["failed"] == 0
        assert data["errors"] == []
