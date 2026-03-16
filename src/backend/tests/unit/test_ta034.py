"""
Unit tests for TA-034: Multiple document source management.

  GET    /api/v1/admin/knowledge-base/{kb_id}/sources
  GET    /api/v1/admin/knowledge-base/{kb_id}/documents?search=
  DELETE /api/v1/admin/knowledge-base/{kb_id}/sources/{integration_id}

Tier 1: Fast, isolated — mocks DB session.
"""
import contextlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "t034" * 16
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = str(uuid.uuid4())

_KB_ID = str(uuid.uuid4())
_INT_ID = str(uuid.uuid4())
_INT_ID_2 = str(uuid.uuid4())

_SOURCES_URL = f"/api/v1/admin/knowledge-base/{_KB_ID}/sources"
_DOCUMENTS_URL = f"/api/v1/admin/knowledge-base/{_KB_ID}/documents"
_DELETE_SOURCE_URL = f"/api/v1/admin/knowledge-base/{_KB_ID}/sources/{_INT_ID}"


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def _make_admin_token() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": "admin-001",
            "tenant_id": TEST_TENANT_ID,
            "roles": ["tenant_admin"],
            "scope": "tenant",
            "plan": "professional",
            "exp": now + timedelta(hours=1),
            "iat": now,
            "token_version": 2,
        },
        TEST_JWT_SECRET,
        algorithm=TEST_JWT_ALGORITHM,
    )


def _make_viewer_token() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": "viewer-001",
            "tenant_id": TEST_TENANT_ID,
            "roles": ["viewer"],
            "scope": "tenant",
            "plan": "professional",
            "exp": now + timedelta(hours=1),
            "iat": now,
            "token_version": 2,
        },
        TEST_JWT_SECRET,
        algorithm=TEST_JWT_ALGORITHM,
    )


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_make_admin_token()}"}


def _viewer_headers() -> dict:
    return {"Authorization": f"Bearer {_make_viewer_token()}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def env_vars():
    env = {
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "JWT_ALGORITHM": TEST_JWT_ALGORITHM,
        "REDIS_URL": "redis://localhost:6379/0",
        "FRONTEND_URL": "http://localhost:3022",
    }
    with patch.dict(os.environ, env):
        yield


@pytest.fixture(scope="module")
def client(env_vars):
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------


def _make_integration_mapping(
    int_id: str,
    provider: str = "sharepoint",
    int_status: str = "active",
    config: dict = None,
    last_sync_at=None,
    last_sync_status: str = "completed",
):
    """Build a MagicMock mapping row for an integration."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "id": int_id,
        "provider": provider,
        "status": int_status,
        "config": json.dumps(config or {"name": "Test SP", "kb_id": _KB_ID}),
        "last_sync_at": last_sync_at,
        "last_sync_status": last_sync_status,
    }.get(key)
    row.get = lambda key, default=None: {
        "id": int_id,
        "provider": provider,
        "status": int_status,
        "config": json.dumps(config or {"name": "Test SP", "kb_id": _KB_ID}),
        "last_sync_at": last_sync_at,
        "last_sync_status": last_sync_status,
    }.get(key, default)
    # Make subscript work for mappings()
    row._data = {
        "id": int_id,
        "provider": provider,
        "status": int_status,
        "config": json.dumps(config or {"name": "Test SP", "kb_id": _KB_ID}),
        "last_sync_at": last_sync_at,
        "last_sync_status": last_sync_status,
    }
    return row


def _patch_db_sources(integration_rows):
    """Patch DB for GET sources endpoint."""
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()

    async def _execute(stmt, params=None, **kwargs):
        mock_result = MagicMock()
        sql = str(stmt)

        if "FROM integrations" in sql and "LATERAL" in sql:
            mock_result.mappings.return_value = integration_rows
        else:
            mock_result.mappings.return_value = []
            mock_result.fetchall.return_value = []
            mock_result.fetchone.return_value = None

        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

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


def _patch_db_documents(integration_rows, job_rows=None):
    """Patch DB for GET documents endpoint."""
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()

    async def _execute(stmt, params=None, **kwargs):
        mock_result = MagicMock()
        sql = str(stmt)

        if (
            "FROM integrations" in sql
            and "config->>'kb_id'" in sql
            and "sync_jobs" not in sql
        ):
            # Returns integration rows for the "get integration IDs" query
            mock_result.fetchall.return_value = integration_rows
        elif "FROM sync_jobs" in sql:
            mock_result.fetchall.return_value = job_rows or []
        else:
            mock_result.fetchall.return_value = []

        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

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


def _patch_db_delete(found_row=None, update_rowcount=1):
    """Patch DB for DELETE source endpoint."""
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()

    async def _execute(stmt, params=None, **kwargs):
        mock_result = MagicMock()
        sql = str(stmt)

        if "SELECT id, config FROM integrations" in sql:
            mock_result.fetchone.return_value = found_row
        elif "UPDATE integrations SET config" in sql:
            mock_result.rowcount = update_rowcount
        else:
            mock_result.fetchone.return_value = None
            mock_result.rowcount = 0

        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

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


# ---------------------------------------------------------------------------
# Tests: Auth
# ---------------------------------------------------------------------------


class TestKBSourcesAuth:
    def test_sources_requires_auth(self, client):
        resp = client.get(_SOURCES_URL)
        assert resp.status_code == 401

    def test_sources_requires_tenant_admin(self, client):
        resp = client.get(_SOURCES_URL, headers=_viewer_headers())
        assert resp.status_code == 403

    def test_documents_requires_auth(self, client):
        resp = client.get(_DOCUMENTS_URL)
        assert resp.status_code == 401

    def test_delete_source_requires_tenant_admin(self, client):
        resp = client.delete(_DELETE_SOURCE_URL, headers=_viewer_headers())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: GET /admin/knowledge-base/{kb_id}/sources
# ---------------------------------------------------------------------------


class TestListKBSources:
    def test_invalid_kb_id_returns_422(self, client):
        resp = client.get(
            "/api/v1/admin/knowledge-base/not-a-uuid/sources",
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_empty_sources_returns_list(self, client):
        with _patch_db_sources([]):
            resp = client.get(_SOURCES_URL, headers=_admin_headers())
        assert resp.status_code == 200
        assert resp.json() == []

    def test_active_recent_sync_is_healthy(self, client):
        """An active integration with a recent sync should be 'healthy'."""
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        row = _make_integration_mapping(
            _INT_ID,
            int_status="active",
            last_sync_at=recent,
            last_sync_status="completed",
        )
        with _patch_db_sources([row]):
            resp = client.get(_SOURCES_URL, headers=_admin_headers())
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["health_indicator"] == "healthy"
        assert items[0]["integration_id"] == _INT_ID

    def test_disabled_integration_is_unhealthy(self, client):
        row = _make_integration_mapping(
            _INT_ID,
            int_status="disabled",
            last_sync_at=None,
        )
        with _patch_db_sources([row]):
            resp = client.get(_SOURCES_URL, headers=_admin_headers())
        assert resp.status_code == 200
        items = resp.json()
        assert items[0]["health_indicator"] == "unhealthy"

    def test_pending_integration_is_pending(self, client):
        row = _make_integration_mapping(
            _INT_ID,
            int_status="pending",
            last_sync_at=None,
        )
        with _patch_db_sources([row]):
            resp = client.get(_SOURCES_URL, headers=_admin_headers())
        assert resp.status_code == 200
        items = resp.json()
        assert items[0]["health_indicator"] == "pending"


# ---------------------------------------------------------------------------
# Tests: GET /admin/knowledge-base/{kb_id}/documents
# ---------------------------------------------------------------------------


class TestListKBDocuments:
    def test_invalid_kb_id_returns_422(self, client):
        resp = client.get(
            "/api/v1/admin/knowledge-base/bad-id/documents",
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_no_integrations_returns_empty(self, client):
        with _patch_db_documents(integration_rows=[], job_rows=[]):
            resp = client.get(_DOCUMENTS_URL, headers=_admin_headers())
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_list_of_documents(self, client):
        int_row = (_INT_ID, "sharepoint", json.dumps({"name": "SP1", "kb_id": _KB_ID}))
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        job_row = (
            job_id,
            _INT_ID,
            now,
            json.dumps({"title": "Doc 1", "document_count": 5}),
        )

        with _patch_db_documents(integration_rows=[int_row], job_rows=[job_row]):
            resp = client.get(_DOCUMENTS_URL, headers=_admin_headers())
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["title"] == "Doc 1"
        assert items[0]["integration_id"] == _INT_ID


# ---------------------------------------------------------------------------
# Tests: DELETE /admin/knowledge-base/{kb_id}/sources/{integration_id}
# ---------------------------------------------------------------------------


class TestDeleteKBSource:
    def test_invalid_kb_id_returns_422(self, client):
        resp = client.delete(
            f"/api/v1/admin/knowledge-base/bad-id/sources/{_INT_ID}",
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_invalid_integration_id_returns_422(self, client):
        resp = client.delete(
            f"/api/v1/admin/knowledge-base/{_KB_ID}/sources/bad-id",
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_not_found_returns_404(self, client):
        with _patch_db_delete(found_row=None):
            resp = client.delete(_DELETE_SOURCE_URL, headers=_admin_headers())
        assert resp.status_code == 404

    def test_success_returns_204(self, client):
        existing_config = json.dumps({"name": "SP1", "kb_id": _KB_ID})
        found_row = (_INT_ID, existing_config)
        with _patch_db_delete(found_row=found_row, update_rowcount=1):
            resp = client.delete(_DELETE_SOURCE_URL, headers=_admin_headers())
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Tests: _compute_health logic (unit-level)
# ---------------------------------------------------------------------------


class TestComputeHealth:
    def test_disabled_is_unhealthy(self):
        from app.modules.admin.kb_sources import _compute_health

        assert _compute_health("disabled", None) == "unhealthy"

    def test_error_is_unhealthy(self):
        from app.modules.admin.kb_sources import _compute_health

        assert _compute_health("error", datetime.now(timezone.utc)) == "unhealthy"

    def test_pending_is_pending(self):
        from app.modules.admin.kb_sources import _compute_health

        assert _compute_health("pending", None) == "pending"

    def test_active_no_sync_is_stale(self):
        from app.modules.admin.kb_sources import _compute_health

        assert _compute_health("active", None) == "stale"

    def test_active_old_sync_is_stale(self):
        from app.modules.admin.kb_sources import _compute_health

        old = datetime.now(timezone.utc) - timedelta(hours=48)
        assert _compute_health("active", old) == "stale"

    def test_active_recent_sync_is_healthy(self):
        from app.modules.admin.kb_sources import _compute_health

        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        assert _compute_health("active", recent) == "healthy"
