"""
Unit tests for TA-019: Google Drive API.

- POST /documents/google-drive/connect (updated: accepts service_account_json)
- GET  /documents/google-drive/{id}/folders (new)

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
TEST_INTEGRATION_ID = str(uuid.uuid4())


def _make_token(role: str = "tenant_admin") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "admin-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": [role],
        "scope": "tenant",
        "plan": "professional",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_make_token()}"}


def _viewer_headers() -> dict:
    return {"Authorization": f"Bearer {_make_token(role='viewer')}"}


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


_CONNECT_URL = "/api/v1/documents/google-drive/connect"
_FOLDERS_URL = f"/api/v1/documents/google-drive/{TEST_INTEGRATION_ID}/folders"

_VALID_SA_JSON = {
    "type": "service_account",
    "project_id": "my-project",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\n...",
    "client_email": "svc@my-project.iam.gserviceaccount.com",
    "private_key_id": "key123",
}

_VALID_CONNECT_BODY = {
    "name": "My Drive Integration",
    "folder_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs",
    "service_account_json": _VALID_SA_JSON,
}


def _patch_db_connect():
    """Patch DB session for connect tests."""
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()

    async def _execute(*args, **kwargs):
        mock_result = MagicMock()
        mock_result.rowcount = 1
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


def _patch_db_folders(integration_found: bool = True):
    """Patch DB session for folders tests."""
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()

    async def _execute(*args, **kwargs):
        mock_result = MagicMock()
        sql = str(args[0]) if args else ""
        if "FROM integrations" in sql and "SELECT" in sql.upper():
            if integration_found:
                mapping = MagicMock()
                mapping.__getitem__ = lambda self, key: {
                    "id": uuid.UUID(TEST_INTEGRATION_ID),
                    "tenant_id": uuid.UUID(TEST_TENANT_ID),
                    "provider": "google_drive",
                    "status": "active",
                    "config": '{"folder_id": "rootFolderABC", "name": "My Drive"}',
                }[key]
                mock_result.mappings.return_value.first.return_value = mapping
            else:
                mock_result.mappings.return_value.first.return_value = None
        else:
            mock_result.rowcount = 1
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


# ---------------------------------------------------------------------------
# GoogleDriveConnectRequest schema validation tests
# ---------------------------------------------------------------------------


class TestGoogleDriveConnectSchema:
    def test_valid_service_account_json(self):
        from app.modules.documents.google_drive import GoogleDriveConnectRequest

        req = GoogleDriveConnectRequest(
            name="Test", folder_id="abc", service_account_json=_VALID_SA_JSON
        )
        assert req.name == "Test"

    def test_missing_type_raises(self):
        from pydantic import ValidationError
        from app.modules.documents.google_drive import GoogleDriveConnectRequest

        bad = {k: v for k, v in _VALID_SA_JSON.items() if k != "type"}
        with pytest.raises(ValidationError) as exc_info:
            GoogleDriveConnectRequest(
                name="Test", folder_id="abc", service_account_json=bad
            )
        assert "type" in str(exc_info.value)

    def test_missing_project_id_raises(self):
        from pydantic import ValidationError
        from app.modules.documents.google_drive import GoogleDriveConnectRequest

        bad = {k: v for k, v in _VALID_SA_JSON.items() if k != "project_id"}
        with pytest.raises(ValidationError):
            GoogleDriveConnectRequest(
                name="Test", folder_id="abc", service_account_json=bad
            )

    def test_missing_private_key_raises(self):
        from pydantic import ValidationError
        from app.modules.documents.google_drive import GoogleDriveConnectRequest

        bad = {k: v for k, v in _VALID_SA_JSON.items() if k != "private_key"}
        with pytest.raises(ValidationError):
            GoogleDriveConnectRequest(
                name="Test", folder_id="abc", service_account_json=bad
            )

    def test_missing_client_email_raises(self):
        from pydantic import ValidationError
        from app.modules.documents.google_drive import GoogleDriveConnectRequest

        bad = {k: v for k, v in _VALID_SA_JSON.items() if k != "client_email"}
        with pytest.raises(ValidationError):
            GoogleDriveConnectRequest(
                name="Test", folder_id="abc", service_account_json=bad
            )

    def test_wrong_type_value_raises(self):
        from pydantic import ValidationError
        from app.modules.documents.google_drive import GoogleDriveConnectRequest

        bad = {**_VALID_SA_JSON, "type": "oauth2"}
        with pytest.raises(ValidationError) as exc_info:
            GoogleDriveConnectRequest(
                name="Test", folder_id="abc", service_account_json=bad
            )
        assert "service_account" in str(exc_info.value)


# ---------------------------------------------------------------------------
# POST /documents/google-drive/connect
# ---------------------------------------------------------------------------


class TestGoogleDriveConnect:
    def test_requires_auth(self, client):
        resp = client.post(_CONNECT_URL, json=_VALID_CONNECT_BODY)
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client):
        resp = client.post(
            _CONNECT_URL, json=_VALID_CONNECT_BODY, headers=_viewer_headers()
        )
        assert resp.status_code == 403

    def test_valid_request_returns_201(self, client):
        with _patch_db_connect():
            resp = client.post(
                _CONNECT_URL, json=_VALID_CONNECT_BODY, headers=_admin_headers()
            )
        assert resp.status_code == 201

    def test_missing_type_returns_422(self, client):
        bad = {
            **_VALID_CONNECT_BODY,
            "service_account_json": {
                k: v for k, v in _VALID_SA_JSON.items() if k != "type"
            },
        }
        with _patch_db_connect():
            resp = client.post(_CONNECT_URL, json=bad, headers=_admin_headers())
        assert resp.status_code == 422

    def test_credential_not_stored_directly(self, client):
        """The private_key from service_account_json must NOT appear in the DB INSERT."""
        with _patch_db_connect() as mock_session:
            resp = client.post(
                _CONNECT_URL, json=_VALID_CONNECT_BODY, headers=_admin_headers()
            )
        assert resp.status_code == 201
        # Check that private_key is not in any SQL params
        for call in mock_session.execute.call_args_list:
            if call.args:
                params = call.args[1] if len(call.args) > 1 else {}
                config_str = params.get("config", "")
                assert "BEGIN RSA" not in str(
                    config_str
                ), "private_key must not be stored in DB config"


# ---------------------------------------------------------------------------
# GET /documents/google-drive/{id}/folders
# ---------------------------------------------------------------------------


class TestGoogleDriveFolders:
    def test_requires_auth(self, client):
        resp = client.get(_FOLDERS_URL)
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client):
        resp = client.get(_FOLDERS_URL, headers=_viewer_headers())
        assert resp.status_code == 403

    def test_not_found_returns_404(self, client):
        with _patch_db_folders(integration_found=False):
            resp = client.get(_FOLDERS_URL, headers=_admin_headers())
        assert resp.status_code == 404

    def test_returns_list(self, client):
        with _patch_db_folders():
            resp = client.get(_FOLDERS_URL, headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_folder_node_structure(self, client):
        with _patch_db_folders():
            resp = client.get(_FOLDERS_URL, headers=_admin_headers())
        node = resp.json()[0]
        assert "id" in node
        assert "name" in node
        assert "children" in node
        assert isinstance(node["children"], list)

    def test_root_folder_id_matches_config(self, client):
        with _patch_db_folders():
            resp = client.get(_FOLDERS_URL, headers=_admin_headers())
        node = resp.json()[0]
        assert node["id"] == "rootFolderABC"
        assert node["name"] == "My Drive"
