"""
Unit tests for issue reporting routes (API-013, API-014).

Tests issue CRUD, blur_acknowledged enforcement, RBAC, auth,
and screenshot presign URL generation.
Tier 1: Fast, isolated, uses mocking for DB helpers and storage.
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


def _make_token(
    user_id: str = TEST_USER_ID,
    roles: list[str] | None = None,
    scope: str = "tenant",
) -> str:
    if roles is None:
        roles = ["end_user"]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": TEST_TENANT_ID,
        "roles": roles,
        "scope": scope,
        "plan": "professional",
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
    return {"Authorization": f"Bearer {_make_token(roles=['tenant_admin'])}"}


# ---------------------------------------------------------------------------
# POST /api/v1/issues — Create issue (any authenticated user)
# ---------------------------------------------------------------------------


class TestCreateIssue:
    """POST /api/v1/issues"""

    def test_create_issue_requires_auth(self, client):
        resp = client.post(
            "/api/v1/issues", json={"title": "Bug", "description": "Details"}
        )
        assert resp.status_code == 401

    def test_create_issue_returns_201(self, client, user_headers):
        with patch(
            "app.modules.issues.routes.create_issue_db", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = {
                "id": "issue-1",
                "title": "Bug",
                "description": "Details",
                "status": "open",
            }
            resp = client.post(
                "/api/v1/issues",
                json={"title": "Bug", "description": "Details"},
                headers=user_headers,
            )
        assert resp.status_code == 201
        assert resp.json()["id"] == "issue-1"

    def test_create_issue_rejects_empty_title(self, client, user_headers):
        resp = client.post(
            "/api/v1/issues",
            json={"title": "", "description": "Details"},
            headers=user_headers,
        )
        assert resp.status_code == 422

    def test_create_issue_rejects_screenshot_without_blur_ack(
        self, client, user_headers
    ):
        """INFRA-019: screenshot_url without blur_acknowledged=True must fail with 422."""
        resp = client.post(
            "/api/v1/issues",
            json={
                "title": "Bug with screenshot",
                "description": "Details",
                "screenshot_url": "https://storage.example.com/screenshot.png",
                "blur_acknowledged": False,
            },
            headers=user_headers,
        )
        assert resp.status_code == 422
        assert "blur_acknowledged" in resp.json()["detail"].lower()

    def test_create_issue_accepts_screenshot_with_blur_ack(self, client, user_headers):
        """INFRA-019: screenshot_url with blur_acknowledged=True succeeds."""
        with patch(
            "app.modules.issues.routes.create_issue_db", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = {
                "id": "issue-2",
                "title": "Bug with screenshot",
                "description": "Details",
                "screenshot_url": "https://storage.example.com/screenshot.png",
                "blur_acknowledged": True,
                "status": "open",
            }
            resp = client.post(
                "/api/v1/issues",
                json={
                    "title": "Bug with screenshot",
                    "description": "Details",
                    "screenshot_url": "https://storage.example.com/screenshot.png",
                    "blur_acknowledged": True,
                },
                headers=user_headers,
            )
        assert resp.status_code == 201

    def test_create_issue_no_blur_ack_needed_without_screenshot(
        self, client, user_headers
    ):
        """blur_acknowledged can be False when no screenshot_url is provided."""
        with patch(
            "app.modules.issues.routes.create_issue_db", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = {
                "id": "issue-3",
                "title": "Bug",
                "description": "Details",
                "status": "open",
            }
            resp = client.post(
                "/api/v1/issues",
                json={
                    "title": "Bug",
                    "description": "Details",
                    "blur_acknowledged": False,
                },
                headers=user_headers,
            )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# GET /api/v1/issues — List issues (tenant_admin only)
# ---------------------------------------------------------------------------


class TestListIssues:
    """GET /api/v1/issues"""

    def test_list_issues_requires_auth(self, client):
        resp = client.get("/api/v1/issues")
        assert resp.status_code == 401

    def test_list_issues_requires_tenant_admin(self, client, user_headers):
        resp = client.get("/api/v1/issues", headers=user_headers)
        assert resp.status_code == 403

    def test_list_issues_returns_paginated(self, client, admin_headers):
        with patch(
            "app.modules.issues.routes.list_issues_db", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = {
                "items": [],
                "total": 0,
                "page": 1,
                "page_size": 20,
            }
            resp = client.get("/api/v1/issues", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data


# ---------------------------------------------------------------------------
# GET /api/v1/issues/{issue_id} — Get issue (admin or owner)
# ---------------------------------------------------------------------------


class TestGetIssue:
    """GET /api/v1/issues/{issue_id}"""

    def test_get_issue_requires_auth(self, client):
        resp = client.get("/api/v1/issues/issue-1")
        assert resp.status_code == 401

    def test_get_issue_returns_data(self, client, user_headers):
        with patch(
            "app.modules.issues.routes.get_issue_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "id": "issue-1",
                "title": "Bug",
                "description": "Details",
                "user_id": TEST_USER_ID,
                "status": "open",
            }
            resp = client.get("/api/v1/issues/issue-1", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == "issue-1"

    def test_get_issue_returns_404(self, client, user_headers):
        with patch(
            "app.modules.issues.routes.get_issue_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None
            resp = client.get("/api/v1/issues/nonexistent", headers=user_headers)
        assert resp.status_code == 404

    def test_get_issue_forbidden_for_non_owner_non_admin(self, client):
        """Non-owner, non-admin user cannot see another user's issue."""
        other_user_headers = {
            "Authorization": f"Bearer {_make_token(user_id='user-other')}"
        }
        with patch(
            "app.modules.issues.routes.get_issue_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "id": "issue-1",
                "title": "Bug",
                "description": "Details",
                "user_id": "user-001",  # Different from user-other
                "status": "open",
            }
            resp = client.get("/api/v1/issues/issue-1", headers=other_user_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PATCH /api/v1/issues/{issue_id}/status — Update status (tenant admin only)
# ---------------------------------------------------------------------------


class TestUpdateIssueStatus:
    """PATCH /api/v1/issues/{issue_id}/status"""

    def test_update_status_requires_auth(self, client):
        resp = client.patch(
            "/api/v1/issues/issue-1/status", json={"status": "resolved"}
        )
        assert resp.status_code == 401

    def test_update_status_requires_tenant_admin(self, client, user_headers):
        resp = client.patch(
            "/api/v1/issues/issue-1/status",
            json={"status": "resolved"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_update_status_returns_200(self, client, admin_headers):
        with patch(
            "app.modules.issues.routes.update_issue_status_db", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = {
                "id": "issue-1",
                "title": "Bug",
                "status": "resolved",
            }
            resp = client.patch(
                "/api/v1/issues/issue-1/status",
                json={"status": "resolved"},
                headers=admin_headers,
            )
        assert resp.status_code == 200

    def test_update_status_returns_404(self, client, admin_headers):
        with patch(
            "app.modules.issues.routes.update_issue_status_db", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = None
            resp = client.patch(
                "/api/v1/issues/nonexistent/status",
                json={"status": "resolved"},
                headers=admin_headers,
            )
        assert resp.status_code == 404

    def test_update_status_rejects_invalid_status(self, client, admin_headers):
        resp = client.patch(
            "/api/v1/issues/issue-1/status",
            json={"status": "invalid_status"},
            headers=admin_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/issues/{issue_id}/events — Add event (tenant admin only)
# ---------------------------------------------------------------------------


class TestAddIssueEvent:
    """POST /api/v1/issues/{issue_id}/events"""

    def test_add_event_requires_auth(self, client):
        resp = client.post(
            "/api/v1/issues/issue-1/events",
            json={"content": "Investigating the issue"},
        )
        assert resp.status_code == 401

    def test_add_event_requires_tenant_admin(self, client, user_headers):
        resp = client.post(
            "/api/v1/issues/issue-1/events",
            json={"content": "Investigating the issue"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_add_event_returns_201(self, client, admin_headers):
        with patch(
            "app.modules.issues.routes.add_issue_event_db", new_callable=AsyncMock
        ) as mock_add:
            mock_add.return_value = {
                "id": "event-1",
                "issue_id": "issue-1",
                "content": "Investigating the issue",
            }
            resp = client.post(
                "/api/v1/issues/issue-1/events",
                json={"content": "Investigating the issue"},
                headers=admin_headers,
            )
        assert resp.status_code == 201
        assert resp.json()["id"] == "event-1"


# ---------------------------------------------------------------------------
# GET /api/v1/issue-reports/presign — Presigned upload URL (API-014)
# ---------------------------------------------------------------------------


class TestPresignScreenshotUpload:
    """GET /api/v1/issue-reports/presign (API-014)"""

    def test_presign_requires_auth(self, client):
        """Unauthenticated requests are rejected with 401."""
        resp = client.get(
            "/api/v1/issue-reports/presign",
            params={"filename": "shot.png", "content_type": "image/png"},
        )
        assert resp.status_code == 401

    def test_presign_returns_upload_blob_expires(self, client, user_headers):
        """Happy path: returns upload_url, blob_url, expires_in=300."""
        from app.core.storage import PresignedUpload

        with patch("app.core.storage.generate_presigned_upload") as mock_presign:
            mock_presign.return_value = PresignedUpload(
                upload_url="http://localhost:8022/api/v1/internal/screenshots/tok",
                blob_url="http://localhost:8022/api/v1/internal/screenshots/pay",
                expires_in=300,
            )
            resp = client.get(
                "/api/v1/issue-reports/presign",
                params={"filename": "shot.png", "content_type": "image/png"},
                headers=user_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "upload_url" in data
        assert "blob_url" in data
        assert data["expires_in"] == 300

    def test_presign_rejects_invalid_content_type(self, client, user_headers):
        """Content-type not in {image/png, image/jpeg} returns 422."""
        resp = client.get(
            "/api/v1/issue-reports/presign",
            params={"filename": "shot.gif", "content_type": "image/gif"},
            headers=user_headers,
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "image/jpeg" in detail or "image/png" in detail

    def test_presign_accepts_jpeg(self, client, user_headers):
        """image/jpeg is an allowed content type."""
        from app.core.storage import PresignedUpload

        with patch("app.core.storage.generate_presigned_upload") as mock_presign:
            mock_presign.return_value = PresignedUpload(
                upload_url="http://localhost:8022/api/v1/internal/screenshots/tok",
                blob_url="http://localhost:8022/api/v1/internal/screenshots/pay",
                expires_in=300,
            )
            resp = client.get(
                "/api/v1/issue-reports/presign",
                params={"filename": "photo.jpg", "content_type": "image/jpeg"},
                headers=user_headers,
            )

        assert resp.status_code == 200

    def test_presign_missing_filename_returns_422(self, client, user_headers):
        """filename is required."""
        resp = client.get(
            "/api/v1/issue-reports/presign",
            params={"content_type": "image/png"},
            headers=user_headers,
        )
        assert resp.status_code == 422

    def test_presign_missing_content_type_returns_422(self, client, user_headers):
        """content_type is required."""
        resp = client.get(
            "/api/v1/issue-reports/presign",
            params={"filename": "shot.png"},
            headers=user_headers,
        )
        assert resp.status_code == 422

    def test_presign_scopes_path_to_tenant(self, client, user_headers):
        """Storage key passed to generate_presigned_upload uses caller's tenant_id."""
        from app.core.storage import PresignedUpload

        captured_kwargs = {}

        def capture_call(tenant_id, filename, content_type, **kwargs):
            captured_kwargs["tenant_id"] = tenant_id
            return PresignedUpload(
                upload_url="http://localhost:8022/api/v1/internal/screenshots/tok",
                blob_url="http://localhost:8022/api/v1/internal/screenshots/pay",
                expires_in=300,
            )

        with patch(
            "app.core.storage.generate_presigned_upload",
            side_effect=capture_call,
        ):
            client.get(
                "/api/v1/issue-reports/presign",
                params={"filename": "shot.png", "content_type": "image/png"},
                headers=user_headers,
            )

        assert captured_kwargs["tenant_id"] == TEST_TENANT_ID

    def test_presign_storage_error_returns_500(self, client, user_headers):
        """If generate_presigned_upload raises, returns 500 (not 4xx)."""
        with patch(
            "app.core.storage.generate_presigned_upload",
            side_effect=RuntimeError("S3 connection refused"),
        ):
            resp = client.get(
                "/api/v1/issue-reports/presign",
                params={"filename": "shot.png", "content_type": "image/png"},
                headers=user_headers,
            )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/v1/my-reports — List current user's own reports (API-015)
# ---------------------------------------------------------------------------


class TestListMyReports:
    """GET /api/v1/my-reports (API-015)"""

    def test_list_my_reports_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.get("/api/v1/my-reports")
        assert resp.status_code == 401

    def test_list_my_reports_returns_paginated(self, client, user_headers):
        """Returns paginated list with items/total/page/page_size."""
        with patch(
            "app.modules.issues.routes.list_my_issues_db", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = {
                "items": [
                    {
                        "id": "report-1",
                        "title": "Login broken",
                        "status": "open",
                        "created_at": "2026-01-01T00:00:00",
                        "updated_at": None,
                    }
                ],
                "total": 1,
                "page": 1,
                "page_size": 20,
            }
            resp = client.get("/api/v1/my-reports", headers=user_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] == 1
        assert data["items"][0]["id"] == "report-1"

    def test_list_my_reports_scoped_to_current_user(self, client, user_headers):
        """DB helper is called with the current user's user_id, not someone else's."""
        captured = {}

        async def capture(user_id, tenant_id, page, page_size, status_filter, db):
            captured["user_id"] = user_id
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

        with patch("app.modules.issues.routes.list_my_issues_db", side_effect=capture):
            client.get("/api/v1/my-reports", headers=user_headers)

        assert captured["user_id"] == TEST_USER_ID

    def test_list_my_reports_accepts_status_filter(self, client, user_headers):
        """status=open query param is passed through to DB helper."""
        captured = {}

        async def capture(user_id, tenant_id, page, page_size, status_filter, db):
            captured["status_filter"] = status_filter
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

        with patch("app.modules.issues.routes.list_my_issues_db", side_effect=capture):
            client.get(
                "/api/v1/my-reports",
                params={"status": "open"},
                headers=user_headers,
            )

        assert captured["status_filter"] == "open"

    def test_list_my_reports_invalid_status_returns_422(self, client, user_headers):
        """An unknown status value is rejected by pydantic enum validation."""
        resp = client.get(
            "/api/v1/my-reports",
            params={"status": "invalid_status"},
            headers=user_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/my-reports/{report_id} — Get own report detail (API-016)
# ---------------------------------------------------------------------------


class TestGetMyReport:
    """GET /api/v1/my-reports/{report_id} (API-016)"""

    def test_get_my_report_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.get("/api/v1/my-reports/report-1")
        assert resp.status_code == 401

    def test_get_my_report_returns_detail_with_timeline(self, client, user_headers):
        """200 response includes timeline field listing issue events."""
        with patch(
            "app.modules.issues.routes.get_my_issue_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "id": "report-1",
                "title": "Login broken",
                "description": "Cannot log in after password reset.",
                "screenshot_url": None,
                "status": "investigating",
                "blur_acknowledged": False,
                "created_at": "2026-01-01T00:00:00",
                "timeline": [
                    {
                        "id": "event-1",
                        "event": "Investigation started",
                        "timestamp": "2026-01-02T10:00:00",
                    }
                ],
            }
            resp = client.get("/api/v1/my-reports/report-1", headers=user_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "report-1"
        assert "timeline" in data
        assert len(data["timeline"]) == 1
        assert data["timeline"][0]["event"] == "Investigation started"

    def test_get_my_report_returns_404_when_not_found(self, client, user_headers):
        """Returns 404 when the report does not exist or belongs to another user."""
        with patch(
            "app.modules.issues.routes.get_my_issue_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None
            resp = client.get("/api/v1/my-reports/nonexistent", headers=user_headers)

        assert resp.status_code == 404

    def test_get_my_report_scoped_to_current_user(self, client, user_headers):
        """DB helper is called with the current user's ID — cross-user access not possible."""
        captured = {}

        async def capture(issue_id, user_id, tenant_id, db):
            captured["user_id"] = user_id
            return None  # triggers 404, but we only care about the arg

        with patch("app.modules.issues.routes.get_my_issue_db", side_effect=capture):
            client.get("/api/v1/my-reports/report-1", headers=user_headers)

        assert captured["user_id"] == TEST_USER_ID


# ---------------------------------------------------------------------------
# POST /api/v1/issue-reports/{issue_id}/still-happening — API-017
# ---------------------------------------------------------------------------


class TestStillHappening:
    """POST /api/v1/issue-reports/{issue_id}/still-happening (API-017)"""

    def test_still_happening_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.post(
            "/api/v1/issue-reports/issue-1/still-happening",
            json={},
        )
        assert resp.status_code == 401

    def test_still_happening_returns_201_with_routing(self, client, user_headers):
        """Returns 201 with status, new_report_id, and routing field."""
        with patch(
            "app.modules.issues.routes.record_still_happening_db",
            new_callable=AsyncMock,
        ) as mock_record:
            mock_record.return_value = {
                "status": "regression_reported",
                "new_report_id": "report-new",
                "routing": "auto_escalate",
            }
            resp = client.post(
                "/api/v1/issue-reports/issue-1/still-happening",
                json={"additional_context": "Still broken on mobile too"},
                headers=user_headers,
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "regression_reported"
        assert "new_report_id" in data
        assert "routing" in data

    def test_still_happening_uses_provided_fix_deployment_id(
        self, client, user_headers
    ):
        """fix_deployment_id from request body is passed to the DB helper."""
        captured = {}

        async def capture(
            issue_id, user_id, tenant_id, additional_context, fix_deployment_id, db
        ):
            captured["fix_deployment_id"] = fix_deployment_id
            return {
                "status": "regression_reported",
                "new_report_id": "r",
                "routing": "auto_escalate",
            }

        with patch(
            "app.modules.issues.routes.record_still_happening_db",
            side_effect=capture,
        ):
            client.post(
                "/api/v1/issue-reports/issue-1/still-happening",
                json={"fix_deployment_id": "deploy-v2.3.1"},
                headers=user_headers,
            )

        assert captured["fix_deployment_id"] == "deploy-v2.3.1"

    def test_still_happening_falls_back_fix_deployment_id_when_absent(
        self, client, user_headers
    ):
        """When fix_deployment_id is not provided, falls back to 'fix-for-{issue_id}'."""
        captured = {}

        async def capture(
            issue_id, user_id, tenant_id, additional_context, fix_deployment_id, db
        ):
            captured["fix_deployment_id"] = fix_deployment_id
            return {
                "status": "regression_reported",
                "new_report_id": "r",
                "routing": "auto_escalate",
            }

        with patch(
            "app.modules.issues.routes.record_still_happening_db",
            side_effect=capture,
        ):
            client.post(
                "/api/v1/issue-reports/issue-42/still-happening",
                json={},
                headers=user_headers,
            )

        assert captured["fix_deployment_id"] == "fix-for-issue-42"

    def test_still_happening_original_not_found_returns_404(self, client, user_headers):
        """Returns 404 when the DB helper raises HTTPException(404)."""
        from fastapi import HTTPException as FastAPIHTTPException

        with patch(
            "app.modules.issues.routes.record_still_happening_db",
            new_callable=AsyncMock,
        ) as mock_record:
            mock_record.side_effect = FastAPIHTTPException(
                status_code=404, detail="Issue 'issue-99' not found"
            )
            resp = client.post(
                "/api/v1/issue-reports/issue-99/still-happening",
                json={},
                headers=user_headers,
            )

        assert resp.status_code == 404
