"""
Unit tests for TA-010: Access request workflow.

  POST /access-requests
  GET  /admin/access-requests
  PATCH /admin/access-requests/{id}

Tier 1: Fast, isolated.
"""
import contextlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = str(uuid.uuid4())
TEST_USER_ID = str(uuid.uuid4())
TEST_ADMIN_ID = str(uuid.uuid4())
TEST_AGENT_ID = str(uuid.uuid4())
TEST_KB_ID = str(uuid.uuid4())
TEST_REQUEST_ID = str(uuid.uuid4())


def _make_viewer_token(user_id: str = TEST_USER_ID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": TEST_TENANT_ID,
        "roles": ["viewer"],
        "scope": "tenant",
        "plan": "professional",
        "email": "viewer@test.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_admin_token(user_id: str = TEST_ADMIN_ID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": "admin@test.com",
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


def _viewer_headers() -> dict:
    return {"Authorization": f"Bearer {_make_viewer_token()}"}


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_make_admin_token()}"}


_NOW_ISO = "2026-03-16T10:00:00+00:00"


def _make_request_row(status: str = "pending"):
    """Build a mock access_request DB row tuple."""
    return (
        uuid.UUID(TEST_REQUEST_ID),  # id
        uuid.UUID(TEST_TENANT_ID),  # tenant_id
        uuid.UUID(TEST_USER_ID),  # user_id
        "agent",  # resource_type
        uuid.UUID(TEST_AGENT_ID),  # resource_id
        "I need access for project X",  # justification
        status,  # status
        None,  # admin_note
        datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc),  # created_at
    )


def _patch_db(
    insert_row=None,
    get_request_row=None,
    list_rows=None,
    admin_ids: list[str] | None = None,
    duplicate=False,
):
    """Patch DB session for access request tests.

    For POST /access-requests:
      1. INSERT RETURNING → fetchone()
      2. commit
      3. SELECT users (admins) → fetchall()
      4. INSERT notifications (per admin)
      5. commit

    For GET /admin/access-requests:
      1. SELECT access_requests JOIN users → fetchall()

    For PATCH /admin/access-requests/{id}:
      1. SELECT to fetch request → fetchone()
      2. UPDATE access_requests
      3. _append_user_to_access_control (INSERT/ON CONFLICT)
      4. commit
      5. INSERT notification
      6. commit
    """
    from app.core.session import get_async_session
    from app.main import app

    if admin_ids is None:
        admin_ids = [TEST_ADMIN_ID]

    if insert_row is None:
        insert_row = _make_request_row()

    # list_rows for GET endpoint
    if list_rows is None:
        row = _make_request_row()
        list_rows = [row + ("viewer@test.com",)]

    mock_session = MagicMock()
    call_count = 0

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        sql = str(args[0]) if args else ""

        if "INSERT INTO access_requests" in sql:
            if duplicate:
                raise Exception("duplicate key value violates unique constraint")
            mock_result.fetchone.return_value = insert_row
        elif (
            "SELECT" in sql.upper()
            and "access_requests" in sql
            and "INSERT" not in sql.upper()
            and "UPDATE" not in sql.upper()
        ):
            # SELECT on access_requests (list or single fetch)
            if get_request_row is not None:
                mock_result.fetchone.return_value = get_request_row
            mock_result.fetchall.return_value = list_rows
        elif "users" in sql and "tenant_admin" in sql:
            # get tenant admins
            mock_result.fetchall.return_value = [(uuid.UUID(aid),) for aid in admin_ids]
        elif "INSERT INTO notifications" in sql:
            mock_result.fetchone.return_value = None
        elif "UPDATE access_requests" in sql:
            mock_result.rowcount = 1
        else:
            mock_result.fetchone.return_value = None
            mock_result.fetchall.return_value = []
            mock_result.scalar.return_value = None
        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    async def _override():
        yield mock_session

    app.dependency_overrides[get_async_session] = _override

    @contextlib.contextmanager
    def _ctx():
        try:
            yield mock_session
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    return _ctx()


class TestCreateAccessRequestAuth:
    def test_requires_auth(self, client):
        resp = client.post(
            "/api/v1/access-requests",
            json={
                "resource_type": "agent",
                "resource_id": TEST_AGENT_ID,
                "justification": "I need access",
            },
        )
        assert resp.status_code == 401


class TestCreateAccessRequestValidation:
    def test_invalid_resource_type_returns_422(self, client):
        resp = client.post(
            "/api/v1/access-requests",
            json={
                "resource_type": "database",
                "resource_id": TEST_AGENT_ID,
                "justification": "I need access",
            },
            headers=_viewer_headers(),
        )
        assert resp.status_code == 422

    def test_invalid_resource_id_returns_422(self, client):
        resp = client.post(
            "/api/v1/access-requests",
            json={
                "resource_type": "agent",
                "resource_id": "not-a-uuid",
                "justification": "I need access",
            },
            headers=_viewer_headers(),
        )
        assert resp.status_code == 422

    def test_empty_justification_returns_422(self, client):
        resp = client.post(
            "/api/v1/access-requests",
            json={
                "resource_type": "agent",
                "resource_id": TEST_AGENT_ID,
                "justification": "",
            },
            headers=_viewer_headers(),
        )
        assert resp.status_code == 422

    def test_duplicate_pending_request_returns_409(self, client):
        with _patch_db(duplicate=True):
            resp = client.post(
                "/api/v1/access-requests",
                json={
                    "resource_type": "agent",
                    "resource_id": TEST_AGENT_ID,
                    "justification": "Need access",
                },
                headers=_viewer_headers(),
            )
        assert resp.status_code == 409


class TestCreateAccessRequestSuccess:
    def test_creates_request_returns_201(self, client):
        with _patch_db():
            resp = client.post(
                "/api/v1/access-requests",
                json={
                    "resource_type": "agent",
                    "resource_id": TEST_AGENT_ID,
                    "justification": "Need access for project work",
                },
                headers=_viewer_headers(),
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert data["resource_type"] == "agent"
        assert data["resource_id"] == TEST_AGENT_ID

    def test_kb_request_accepted(self, client):
        row = (
            uuid.UUID(TEST_REQUEST_ID),
            uuid.UUID(TEST_TENANT_ID),
            uuid.UUID(TEST_USER_ID),
            "kb",
            uuid.UUID(TEST_KB_ID),
            "Research purposes",
            "pending",
            None,
            datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc),
        )
        with _patch_db(insert_row=row):
            resp = client.post(
                "/api/v1/access-requests",
                json={
                    "resource_type": "kb",
                    "resource_id": TEST_KB_ID,
                    "justification": "Research purposes",
                },
                headers=_viewer_headers(),
            )
        assert resp.status_code == 201
        assert resp.json()["resource_type"] == "kb"

    def test_response_structure(self, client):
        with _patch_db():
            resp = client.post(
                "/api/v1/access-requests",
                json={
                    "resource_type": "agent",
                    "resource_id": TEST_AGENT_ID,
                    "justification": "Need access",
                },
                headers=_viewer_headers(),
            )
        assert resp.status_code == 201
        data = resp.json()
        assert set(data.keys()) >= {
            "id",
            "tenant_id",
            "user_id",
            "resource_type",
            "resource_id",
            "justification",
            "status",
            "created_at",
        }


class TestListAccessRequestsAuth:
    def test_requires_auth(self, client):
        resp = client.get("/api/v1/admin/access-requests")
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client):
        resp = client.get("/api/v1/admin/access-requests", headers=_viewer_headers())
        assert resp.status_code == 403


class TestListAccessRequests:
    def test_returns_items_and_total(self, client):
        with _patch_db():
            resp = client.get("/api/v1/admin/access-requests", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_status_filter_invalid_returns_422(self, client):
        with _patch_db():
            resp = client.get(
                "/api/v1/admin/access-requests?status=unknown",
                headers=_admin_headers(),
            )
        assert resp.status_code == 422

    def test_status_filter_pending_valid(self, client):
        with _patch_db():
            resp = client.get(
                "/api/v1/admin/access-requests?status=pending",
                headers=_admin_headers(),
            )
        assert resp.status_code == 200

    def test_item_structure(self, client):
        with _patch_db():
            resp = client.get("/api/v1/admin/access-requests", headers=_admin_headers())
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        item = items[0]
        assert set(item.keys()) >= {
            "id",
            "tenant_id",
            "user_id",
            "resource_type",
            "resource_id",
            "status",
            "created_at",
        }


class TestDecideAccessRequestAuth:
    def test_requires_auth(self, client):
        resp = client.patch(
            f"/api/v1/admin/access-requests/{TEST_REQUEST_ID}",
            json={"status": "approved"},
        )
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client):
        resp = client.patch(
            f"/api/v1/admin/access-requests/{TEST_REQUEST_ID}",
            json={"status": "approved"},
            headers=_viewer_headers(),
        )
        assert resp.status_code == 403


class TestDecideAccessRequestValidation:
    def test_invalid_status_returns_422(self, client):
        resp = client.patch(
            f"/api/v1/admin/access-requests/{TEST_REQUEST_ID}",
            json={"status": "pending"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_invalid_request_id_returns_422(self, client):
        resp = client.patch(
            "/api/v1/admin/access-requests/not-a-uuid",
            json={"status": "approved"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_request_not_found_returns_404(self, client):
        with _patch_db(get_request_row=None, list_rows=[]):
            with patch(
                "app.modules.admin.access_requests._patch_db",
                create=True,
            ):
                # Override the GET to return None
                from app.core.session import get_async_session
                from app.main import app

                mock_session = MagicMock()

                async def _execute(*args, **kwargs):
                    mock_result = MagicMock()
                    mock_result.fetchone.return_value = None
                    return mock_result

                mock_session.execute = AsyncMock(side_effect=_execute)
                mock_session.commit = AsyncMock()
                mock_session.rollback = AsyncMock()

                async def _override():
                    yield mock_session

                app.dependency_overrides[get_async_session] = _override
                try:
                    resp = client.patch(
                        f"/api/v1/admin/access-requests/{TEST_REQUEST_ID}",
                        json={"status": "approved"},
                        headers=_admin_headers(),
                    )
                finally:
                    app.dependency_overrides.pop(get_async_session, None)
        assert resp.status_code == 404

    def test_already_decided_returns_409(self, client):
        """Cannot approve/deny an already-decided request."""
        approved_row = _make_request_row(status="approved")

        from app.core.session import get_async_session
        from app.main import app

        mock_session = MagicMock()

        async def _execute(*args, **kwargs):
            mock_result = MagicMock()
            sql = str(args[0]) if args else ""
            if "SELECT" in sql.upper() and "access_requests" in sql:
                mock_result.fetchone.return_value = approved_row
            else:
                mock_result.fetchone.return_value = None
            return mock_result

        mock_session.execute = AsyncMock(side_effect=_execute)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        async def _override():
            yield mock_session

        app.dependency_overrides[get_async_session] = _override
        try:
            resp = client.patch(
                f"/api/v1/admin/access-requests/{TEST_REQUEST_ID}",
                json={"status": "denied"},
                headers=_admin_headers(),
            )
        finally:
            app.dependency_overrides.pop(get_async_session, None)

        assert resp.status_code == 409


class TestDecideAccessRequestSuccess:
    def _patch_decide_db(self, decision: str = "approved"):
        """Patch for PATCH /admin/access-requests/{id}."""
        from app.core.session import get_async_session
        from app.main import app

        mock_session = MagicMock()
        # Matches the 6-column SELECT in decide_access_request:
        # SELECT id, tenant_id, user_id, resource_type, resource_id, status
        request_row = (
            uuid.UUID(TEST_REQUEST_ID),  # 0: id
            uuid.UUID(TEST_TENANT_ID),  # 1: tenant_id
            uuid.UUID(TEST_USER_ID),  # 2: user_id
            "agent",  # 3: resource_type
            uuid.UUID(TEST_AGENT_ID),  # 4: resource_id
            "pending",  # 5: status
        )

        async def _execute(*args, **kwargs):
            mock_result = MagicMock()
            sql = str(args[0]) if args else ""
            if (
                "SELECT" in sql.upper()
                and "access_requests" in sql
                and "UPDATE" not in sql.upper()
            ):
                mock_result.fetchone.return_value = request_row
            elif "users" in sql and "tenant_admin" in sql:
                mock_result.fetchall.return_value = []
            else:
                mock_result.fetchone.return_value = None
                mock_result.fetchall.return_value = []
                mock_result.rowcount = 1
            return mock_result

        mock_session.execute = AsyncMock(side_effect=_execute)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        async def _override():
            yield mock_session

        app.dependency_overrides[get_async_session] = _override

        @contextlib.contextmanager
        def _ctx():
            try:
                yield mock_session
            finally:
                app.dependency_overrides.pop(get_async_session, None)

        return _ctx()

    def test_approve_returns_approved_status(self, client):
        with self._patch_decide_db("approved"):
            resp = client.patch(
                f"/api/v1/admin/access-requests/{TEST_REQUEST_ID}",
                json={"status": "approved", "note": "Welcome aboard"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["admin_note"] == "Welcome aboard"

    def test_deny_returns_denied_status(self, client):
        with self._patch_decide_db("denied"):
            resp = client.patch(
                f"/api/v1/admin/access-requests/{TEST_REQUEST_ID}",
                json={"status": "denied", "note": "Not approved per policy"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "denied"

    def test_approve_without_note(self, client):
        with self._patch_decide_db("approved"):
            resp = client.patch(
                f"/api/v1/admin/access-requests/{TEST_REQUEST_ID}",
                json={"status": "approved"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
