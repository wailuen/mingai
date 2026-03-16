"""
Unit tests for SharePoint integration routes (API-050 to API-055).

Tests SharePoint connect, test connection, trigger sync, and sync status.
Tier 1: Fast, isolated, uses mocking for DB helpers.
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
TEST_INTEGRATION_ID = "00000001-0001-0001-0001-000000000001"


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


# ---------------------------------------------------------------------------
# API-050: POST /documents/sharepoint/connect
# ---------------------------------------------------------------------------


class TestSharePointConnect:
    """POST /api/v1/documents/sharepoint/connect"""

    def test_connect_requires_auth(self, client):
        resp = client.post(
            "/api/v1/documents/sharepoint/connect",
            json={
                "name": "Marketing SP",
                "site_url": "https://company.sharepoint.com/sites/marketing",
                "library_name": "Documents",
                "client_id": "fake-client-id",
                "client_secret": "fake-client-secret",
            },
        )
        assert resp.status_code == 401

    def test_connect_creates_integration(self, client, admin_headers):
        with patch(
            "app.modules.documents.sharepoint.insert_integration_db",
            new_callable=AsyncMock,
        ) as mock_insert:
            mock_insert.return_value = {
                "id": TEST_INTEGRATION_ID,
                "status": "pending",
                "name": "Marketing SP",
            }
            resp = client.post(
                "/api/v1/documents/sharepoint/connect",
                json={
                    "name": "Marketing SP",
                    "site_url": "https://company.sharepoint.com/sites/marketing",
                    "library_name": "Documents",
                    "client_id": "fake-client-id",
                    "client_secret": "fake-client-secret",
                },
                headers=admin_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["status"] == "pending"
        assert data["name"] == "Marketing SP"
        # Verify credentials were NOT passed to DB insert
        call_kwargs = mock_insert.call_args
        config_arg = call_kwargs[1].get("config") or call_kwargs[0][2]
        assert "client_id" not in str(config_arg)
        assert "client_secret" not in str(config_arg)

    def test_connect_rejects_missing_site_url(self, client, admin_headers):
        resp = client.post(
            "/api/v1/documents/sharepoint/connect",
            json={
                "name": "Marketing SP",
                "library_name": "Documents",
                "client_id": "cid",
                "client_secret": "csec",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_connect_rejects_http_url(self, client, admin_headers):
        resp = client.post(
            "/api/v1/documents/sharepoint/connect",
            json={
                "name": "Marketing SP",
                "site_url": "http://company.sharepoint.com/sites/marketing",
                "library_name": "Documents",
                "client_id": "cid",
                "client_secret": "csec",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# API-051: POST /documents/sharepoint/{integration_id}/test
# ---------------------------------------------------------------------------


class TestSharePointTest:
    """POST /api/v1/documents/sharepoint/{integration_id}/test"""

    def test_test_requires_auth(self, client):
        resp = client.post(f"/api/v1/documents/sharepoint/{TEST_INTEGRATION_ID}/test")
        assert resp.status_code == 401

    def test_test_returns_ok_for_valid_url(self, client, admin_headers):
        with patch(
            "app.modules.documents.sharepoint.get_integration_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = {
                "id": TEST_INTEGRATION_ID,
                "tenant_id": TEST_TENANT_ID,
                "type": "sharepoint",
                "name": "Marketing SP",
                "status": "pending",
                "config": {
                    "site_url": "https://company.sharepoint.com/sites/marketing",
                    "library_name": "Documents",
                    "credential_ref": f"vault:mingai/{TEST_TENANT_ID}/sharepoint/{TEST_INTEGRATION_ID}",
                },
            }
            resp = client.post(
                f"/api/v1/documents/sharepoint/{TEST_INTEGRATION_ID}/test",
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "latency_ms" in data

    def test_test_returns_404_for_missing_integration(self, client, admin_headers):
        with patch(
            "app.modules.documents.sharepoint.get_integration_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None
            resp = client.post(
                "/api/v1/documents/sharepoint/nonexistent-id/test",
                headers=admin_headers,
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API-054: POST /documents/sharepoint/{integration_id}/sync
# ---------------------------------------------------------------------------


class TestSharePointSync:
    """POST /api/v1/documents/sharepoint/{integration_id}/sync"""

    def test_sync_requires_auth(self, client):
        resp = client.post(f"/api/v1/documents/sharepoint/{TEST_INTEGRATION_ID}/sync")
        assert resp.status_code == 401

    def test_sync_creates_job(self, client, admin_headers):
        with (
            patch(
                "app.modules.documents.sharepoint.get_integration_db",
                new_callable=AsyncMock,
            ) as mock_get,
            patch(
                "app.modules.documents.sharepoint.create_sync_job_db",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_get.return_value = {
                "id": TEST_INTEGRATION_ID,
                "tenant_id": TEST_TENANT_ID,
                "type": "sharepoint",
                "name": "Marketing SP",
                "status": "pending",
                "config": {
                    "site_url": "https://company.sharepoint.com/sites/marketing",
                    "library_name": "Documents",
                    "credential_ref": f"vault:mingai/{TEST_TENANT_ID}/sharepoint/{TEST_INTEGRATION_ID}",
                },
            }
            mock_create.return_value = {
                "job_id": "job-0001",
                "status": "queued",
            }
            resp = client.post(
                f"/api/v1/documents/sharepoint/{TEST_INTEGRATION_ID}/sync",
                headers=admin_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["job_id"] == "job-0001"
        assert data["status"] == "queued"

    def test_sync_returns_404_for_missing_integration(self, client, admin_headers):
        with patch(
            "app.modules.documents.sharepoint.get_integration_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None
            resp = client.post(
                "/api/v1/documents/sharepoint/nonexistent-id/sync",
                headers=admin_headers,
            )
        assert resp.status_code == 404

    def test_sync_rejects_disabled_integration(self, client, admin_headers):
        with patch(
            "app.modules.documents.sharepoint.get_integration_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = {
                "id": TEST_INTEGRATION_ID,
                "tenant_id": TEST_TENANT_ID,
                "type": "sharepoint",
                "name": "Marketing SP",
                "status": "disabled",
                "config": {},
            }
            resp = client.post(
                f"/api/v1/documents/sharepoint/{TEST_INTEGRATION_ID}/sync",
                headers=admin_headers,
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# API-055: GET /documents/sharepoint/{integration_id}/sync
# ---------------------------------------------------------------------------


class TestSharePointSyncStatus:
    """GET /api/v1/documents/sharepoint/{integration_id}/sync"""

    def test_status_requires_auth(self, client):
        resp = client.get(f"/api/v1/documents/sharepoint/{TEST_INTEGRATION_ID}/sync")
        assert resp.status_code == 401

    def test_status_returns_jobs_list(self, client, admin_headers):
        with (
            patch(
                "app.modules.documents.sharepoint.get_integration_db",
                new_callable=AsyncMock,
            ) as mock_get,
            patch(
                "app.modules.documents.sharepoint.list_sync_jobs_db",
                new_callable=AsyncMock,
            ) as mock_list,
        ):
            mock_get.return_value = {
                "id": TEST_INTEGRATION_ID,
                "tenant_id": TEST_TENANT_ID,
                "type": "sharepoint",
                "name": "Marketing SP",
                "status": "pending",
                "config": {},
            }
            mock_list.return_value = {
                "jobs": [
                    {
                        "id": "job-0001",
                        "status": "queued",
                        "created_at": "2026-03-07T00:00:00Z",
                    }
                ],
                "total": 1,
            }
            resp = client.get(
                f"/api/v1/documents/sharepoint/{TEST_INTEGRATION_ID}/sync",
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        assert "total" in data
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["id"] == "job-0001"


# ---------------------------------------------------------------------------
# API-056: GET /admin/sync/failures
# ---------------------------------------------------------------------------


class TestListSyncFailures:
    """GET /api/v1/admin/sync/failures — unit tests (mocked DB)."""

    def test_list_sync_failures_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.get("/api/v1/admin/sync/failures")
        assert resp.status_code == 401

    def test_list_sync_failures_requires_tenant_admin(self, client, user_headers):
        """End-user (non-admin) request is rejected."""
        with patch(
            "app.modules.documents.sharepoint.list_sync_failures_db",
            new_callable=AsyncMock,
        ):
            resp = client.get("/api/v1/admin/sync/failures", headers=user_headers)
        assert resp.status_code == 403

    def test_list_sync_failures_empty(self, client, admin_headers):
        """Returns empty list when no failed sync jobs exist."""
        with patch(
            "app.modules.documents.sharepoint.list_sync_failures_db",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = {
                "items": [],
                "total": 0,
                "page": 1,
                "page_size": 20,
            }
            resp = client.get("/api/v1/admin/sync/failures", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["page_size"] == 20

    def test_list_sync_failures_with_results(self, client, admin_headers):
        """Returns failure items with expected fields."""
        mock_item = {
            "file_name": "annual_report.pdf",
            "file_path": "/Sites/Finance/Docs/annual_report.pdf",
            "error_type": "permission_denied",
            "diagnosis": "Access denied to this file or folder",
            "fix_suggestion": "Check SharePoint permissions for the integration service account",
            "first_failed_at": "2026-03-08T00:00:00+00:00",
            "retry_count": 2,
        }
        with patch(
            "app.modules.documents.sharepoint.list_sync_failures_db",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = {
                "items": [mock_item],
                "total": 1,
                "page": 1,
                "page_size": 20,
            }
            resp = client.get("/api/v1/admin/sync/failures", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["file_name"] == "annual_report.pdf"
        assert item["error_type"] == "permission_denied"
        assert "diagnosis" in item
        assert "fix_suggestion" in item
        assert "first_failed_at" in item
        assert "retry_count" in item

    def test_list_sync_failures_filtered_by_source(self, client, admin_headers):
        """source_id query param is passed to the DB helper."""
        with patch(
            "app.modules.documents.sharepoint.list_sync_failures_db",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = {
                "items": [],
                "total": 0,
                "page": 1,
                "page_size": 20,
            }
            resp = client.get(
                f"/api/v1/admin/sync/failures?source_id={TEST_INTEGRATION_ID}",
                headers=admin_headers,
            )
        assert resp.status_code == 200
        call_kwargs = mock_list.call_args
        # Verify source_id was passed to DB helper
        passed_source_id = call_kwargs.kwargs.get("source_id") or (
            call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
        )
        assert passed_source_id == TEST_INTEGRATION_ID
