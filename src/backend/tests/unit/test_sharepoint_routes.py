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
TEST_INTEGRATION_ID = "integ-0001-0001-0001-000000000001"


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
