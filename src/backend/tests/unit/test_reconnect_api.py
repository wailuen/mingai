"""
Unit tests for TA-018: Reconnect wizard API.

POST /documents/sharepoint/{id}/reconnect

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
        "email": "admin@test.com",
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


_RECONNECT_URL = f"/api/v1/documents/sharepoint/{TEST_INTEGRATION_ID}/reconnect"

_VALID_BODY = {
    "site_url": "https://contoso.sharepoint.com",
    "library_name": "Documents",
    "client_id": "client-id-123",
    "client_secret": "secret-xyz",
}

_MOCK_CONFIG = '{"site_url": "https://contoso.sharepoint.com", "library_name": "Docs"}'


def _patch_db(integration_found: bool = True, update_rowcount: int = 1):
    """Patch DB session for reconnect tests."""
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()

    async def _execute(*args, **kwargs):
        mock_result = MagicMock()
        sql = str(args[0]) if args else ""

        if "FROM integrations" in sql and "config" in sql and "SELECT" in sql.upper():
            # reconnect_integration_db inner SELECT
            if integration_found:
                mock_result.fetchone.return_value = (_MOCK_CONFIG,)
            else:
                mock_result.fetchone.return_value = None
        elif "FROM integrations" in sql and "SELECT" in sql.upper():
            # get_integration_db via mappings().first()
            if integration_found:
                mapping = MagicMock()
                mapping.__getitem__ = lambda self, key: {
                    "id": uuid.UUID(TEST_INTEGRATION_ID),
                    "tenant_id": uuid.UUID(TEST_TENANT_ID),
                    "provider": "sharepoint",
                    "status": "active",
                    "config": _MOCK_CONFIG,
                }[key]
                mock_result.mappings.return_value.first.return_value = mapping
            else:
                mock_result.mappings.return_value.first.return_value = None
        elif "UPDATE integrations" in sql:
            mock_result.rowcount = update_rowcount
        elif "INSERT INTO sync_jobs" in sql:
            mock_result.rowcount = 1
        elif "INSERT INTO audit_log" in sql:
            mock_result.rowcount = 1
        else:
            mock_result.fetchone.return_value = None
            mock_result.mappings.return_value.first.return_value = None
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
# Auth tests
# ---------------------------------------------------------------------------


class TestReconnectAuth:
    def test_requires_auth(self, client):
        resp = client.post(_RECONNECT_URL, json=_VALID_BODY)
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client):
        resp = client.post(_RECONNECT_URL, json=_VALID_BODY, headers=_viewer_headers())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestReconnectValidation:
    def test_site_url_must_be_https(self, client):
        body = {**_VALID_BODY, "site_url": "http://contoso.sharepoint.com"}
        with _patch_db():
            resp = client.post(_RECONNECT_URL, json=body, headers=_admin_headers())
        assert resp.status_code == 422

    def test_missing_client_id_returns_422(self, client):
        body = {k: v for k, v in _VALID_BODY.items() if k != "client_id"}
        with _patch_db():
            resp = client.post(_RECONNECT_URL, json=body, headers=_admin_headers())
        assert resp.status_code == 422

    def test_missing_client_secret_returns_422(self, client):
        body = {k: v for k, v in _VALID_BODY.items() if k != "client_secret"}
        with _patch_db():
            resp = client.post(_RECONNECT_URL, json=body, headers=_admin_headers())
        assert resp.status_code == 422

    def test_integration_not_found_returns_404(self, client):
        with _patch_db(integration_found=False):
            resp = client.post(
                _RECONNECT_URL, json=_VALID_BODY, headers=_admin_headers()
            )
        assert resp.status_code == 404

    def test_invalid_sharepoint_url_returns_422(self, client):
        """Test fails if site_url is not a sharepoint.com domain."""
        body = {**_VALID_BODY, "site_url": "https://contoso.example.com"}
        with _patch_db():
            resp = client.post(_RECONNECT_URL, json=body, headers=_admin_headers())
        assert resp.status_code == 422
        assert "test failed" in resp.json()["detail"].lower()

    def test_credentials_not_updated_on_test_failure(self, client):
        """No DB UPDATE should happen when the test fails."""
        body = {**_VALID_BODY, "site_url": "https://contoso.example.com"}
        with _patch_db() as mock_session:
            resp = client.post(_RECONNECT_URL, json=body, headers=_admin_headers())
        assert resp.status_code == 422
        # Verify no UPDATE was executed
        for call in mock_session.execute.call_args_list:
            sql = str(call.args[0]) if call.args else ""
            assert (
                "UPDATE integrations" not in sql
            ), "Credentials must not be updated when test fails"


# ---------------------------------------------------------------------------
# Success tests
# ---------------------------------------------------------------------------


class TestReconnectSuccess:
    def test_successful_reconnect_returns_200(self, client):
        with _patch_db():
            resp = client.post(
                _RECONNECT_URL, json=_VALID_BODY, headers=_admin_headers()
            )
        assert resp.status_code == 200

    def test_response_structure(self, client):
        with _patch_db():
            resp = client.post(
                _RECONNECT_URL, json=_VALID_BODY, headers=_admin_headers()
            )
        data = resp.json()
        assert data["status"] == "reconnected"
        assert data["test_result"] == "success"
        assert "next_sync_at" in data
        assert "integration_id" in data
        assert data["integration_id"] == TEST_INTEGRATION_ID

    def test_next_sync_at_is_in_future(self, client):
        with _patch_db():
            resp = client.post(
                _RECONNECT_URL, json=_VALID_BODY, headers=_admin_headers()
            )
        next_sync_at = datetime.fromisoformat(resp.json()["next_sync_at"])
        assert next_sync_at > datetime.now(timezone.utc)

    def test_audit_log_written(self, client):
        """Reconnect must log to audit_log."""
        with _patch_db() as mock_session:
            resp = client.post(
                _RECONNECT_URL, json=_VALID_BODY, headers=_admin_headers()
            )
        assert resp.status_code == 200
        # Check that audit_log INSERT was called
        audit_calls = [
            call
            for call in mock_session.execute.call_args_list
            if "INSERT INTO audit_log" in str(call.args[0] if call.args else "")
        ]
        assert len(audit_calls) >= 1, "audit_log INSERT not found"

    def test_sync_job_created(self, client):
        """A new sync_job should be created on successful reconnect."""
        with _patch_db() as mock_session:
            resp = client.post(
                _RECONNECT_URL, json=_VALID_BODY, headers=_admin_headers()
            )
        assert resp.status_code == 200
        sync_calls = [
            call
            for call in mock_session.execute.call_args_list
            if "INSERT INTO sync_jobs" in str(call.args[0] if call.args else "")
        ]
        assert len(sync_calls) >= 1, "sync_job INSERT not found"


# ---------------------------------------------------------------------------
# ReconnectRequest schema tests
# ---------------------------------------------------------------------------


class TestReconnectRequestSchema:
    def test_empty_site_url_fails(self):
        from pydantic import ValidationError
        from app.modules.documents.sharepoint import ReconnectRequest

        with pytest.raises(ValidationError):
            ReconnectRequest(
                site_url="",
                library_name="Docs",
                client_id="x",
                client_secret="y",
            )

    def test_http_site_url_fails(self):
        from pydantic import ValidationError
        from app.modules.documents.sharepoint import ReconnectRequest

        with pytest.raises(ValidationError):
            ReconnectRequest(
                site_url="http://site.sharepoint.com",
                library_name="Docs",
                client_id="x",
                client_secret="y",
            )

    def test_valid_request(self):
        from app.modules.documents.sharepoint import ReconnectRequest

        r = ReconnectRequest(
            site_url="https://site.sharepoint.com",
            library_name="Documents",
            client_id="cid",
            client_secret="sec",
        )
        assert r.site_url.startswith("https://")
