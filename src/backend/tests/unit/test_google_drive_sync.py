"""
Unit tests for DEF-010: Google Drive sync worker.

Tier 1: Fast, isolated — all DB and Drive API calls are mocked.

Coverage:
- Webhook validates channel token before processing (security)
- Incremental sync creates a sync_job entry for changed files
- Inaccessible file (any exception during reembed) is logged and skipped
- Duplicate webhook delivery within 5-second window is idempotent
- Initial 'sync' ping from Google is acknowledged without creating a job
- Missing X-Goog-Channel-Token header is rejected gracefully
- POST /documents/google-drive/{id}/watch requires tenant_admin
- POST /webhooks/google-drive/changes is unauthenticated (token in header)
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

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

TEST_JWT_SECRET = "b" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = str(uuid.uuid4())
TEST_INTEGRATION_ID = str(uuid.uuid4())
TEST_CHANNEL_TOKEN = "test-channel-token-secure-32-chars-xz"
TEST_CHANNEL_ID = str(uuid.uuid4())
TEST_RESOURCE_ID = "drive-resource-abc123"


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def _make_token(role: str = "tenant_admin", plan: str = "professional") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "admin-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": [role],
        "scope": "tenant",
        "plan": plan,
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_make_token()}"}


def _viewer_headers() -> dict:
    return {"Authorization": f"Bearer {_make_token(role='viewer')}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Mock DB session builders
# ---------------------------------------------------------------------------


def _mock_session_for_watch(integration_found: bool = True):
    """Return a mock DB session for the /watch endpoint."""
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()

    async def _execute(stmt, params=None, **kwargs):
        mock_result = MagicMock()
        sql = str(stmt)

        if "FROM integrations" in sql and "SELECT" in sql.upper():
            if integration_found:
                if "config FROM integrations" in sql:
                    # SELECT config FROM integrations (upsert_watch_channel_db)
                    mock_result.fetchone.return_value = (
                        json.dumps(
                            {
                                "name": "My Drive",
                                "folder_id": "root123",
                                "credential_ref": "vault:mingai/t1/gd/i1",
                            }
                        ),
                    )
                else:
                    # get_gd_integration_for_tenant
                    mapping = MagicMock()
                    mapping.__getitem__ = lambda self, key: {
                        "id": uuid.UUID(TEST_INTEGRATION_ID),
                        "tenant_id": uuid.UUID(TEST_TENANT_ID),
                        "status": "active",
                        "config": json.dumps(
                            {
                                "name": "My Drive",
                                "folder_id": "root123",
                                "credential_ref": "vault:mingai/t1/gd/i1",
                            }
                        ),
                    }[key]
                    mock_result.mappings.return_value.first.return_value = mapping
            else:
                mock_result.mappings.return_value.first.return_value = None
                mock_result.fetchone.return_value = None
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


def _mock_session_for_webhook(
    token_found: bool = True,
    is_duplicate: bool = False,
):
    """Return a mock DB session for the webhook endpoint."""
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()

    async def _execute(stmt, params=None, **kwargs):
        mock_result = MagicMock()
        sql = str(stmt)

        if "channel_token" in sql and "FROM integrations" in sql:
            # get_gd_integration_by_channel_token
            if token_found:
                mapping = MagicMock()
                mapping.__getitem__ = lambda self, key: {
                    "id": uuid.UUID(TEST_INTEGRATION_ID),
                    "tenant_id": uuid.UUID(TEST_TENANT_ID),
                    "status": "active",
                    "config": json.dumps(
                        {
                            "channel_token": TEST_CHANNEL_TOKEN,
                            "channel_id": TEST_CHANNEL_ID,
                        }
                    ),
                }[key]
                mock_result.mappings.return_value.first.return_value = mapping
            else:
                mock_result.mappings.return_value.first.return_value = None

        elif "COUNT(*) FROM sync_jobs" in sql:
            # check_duplicate_webhook_db
            mock_result.scalar.return_value = 5 if is_duplicate else 0

        elif "INSERT INTO sync_jobs" in sql:
            mock_result.rowcount = 1

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
# POST /documents/google-drive/{id}/watch
# ---------------------------------------------------------------------------


class TestGoogleDriveWatchEndpoint:
    _URL = f"/api/v1/documents/google-drive/{TEST_INTEGRATION_ID}/watch"

    def test_requires_auth(self, client):
        resp = client.post(self._URL)
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client):
        resp = client.post(self._URL, headers=_viewer_headers())
        assert resp.status_code == 403

    def test_not_found_returns_404(self, client):
        with _mock_session_for_watch(integration_found=False):
            resp = client.post(self._URL, headers=_admin_headers())
        assert resp.status_code == 404

    def test_valid_request_returns_201(self, client):
        with _mock_session_for_watch():
            resp = client.post(self._URL, headers=_admin_headers())
        assert resp.status_code == 201

    def test_response_has_channel_id(self, client):
        with _mock_session_for_watch():
            resp = client.post(self._URL, headers=_admin_headers())
        data = resp.json()
        assert "channel_id" in data
        assert data["status"] == "watching"

    def test_response_has_expiration(self, client):
        with _mock_session_for_watch():
            resp = client.post(self._URL, headers=_admin_headers())
        data = resp.json()
        assert "expiration_ms" in data
        assert isinstance(data["expiration_ms"], int)
        assert data["expiration_ms"] > 0

    def test_channel_token_not_in_response(self, client):
        """The channel_token must never be returned to the caller."""
        with _mock_session_for_watch():
            resp = client.post(self._URL, headers=_admin_headers())
        data = resp.json()
        assert "channel_token" not in data


# ---------------------------------------------------------------------------
# POST /webhooks/google-drive/changes
# ---------------------------------------------------------------------------

_WEBHOOK_URL = "/api/v1/webhooks/google-drive/changes"

_VALID_WEBHOOK_HEADERS = {
    "X-Goog-Channel-ID": TEST_CHANNEL_ID,
    "X-Goog-Channel-Token": TEST_CHANNEL_TOKEN,
    "X-Goog-Resource-ID": TEST_RESOURCE_ID,
    "X-Goog-Resource-State": "update",
}


class TestGoogleDriveWebhookSecurity:
    """Security: channel token must be validated before any processing."""

    def test_missing_token_returns_200_ok(self, client):
        """
        Missing token returns 200 {"status": "ok"} — generic response to prevent
        information disclosure about whether the channel token is valid/expected.
        Drive stops retrying on non-5xx responses regardless.
        """
        headers = {
            "X-Goog-Channel-ID": TEST_CHANNEL_ID,
            "X-Goog-Resource-State": "update",
        }
        with _mock_session_for_webhook(token_found=False):
            resp = client.post(_WEBHOOK_URL, headers=headers)
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_invalid_token_returns_200_ok(self, client):
        """Invalid token (no matching integration) returns generic 200 {"status": "ok"}
        to avoid disclosing whether the token is expected."""
        headers = {**_VALID_WEBHOOK_HEADERS, "X-Goog-Channel-Token": "bad-token"}
        with _mock_session_for_webhook(token_found=False):
            resp = client.post(_WEBHOOK_URL, headers=headers)
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_valid_token_is_accepted(self, client):
        """Valid channel token results in status=ok."""
        with _mock_session_for_webhook(token_found=True):
            resp = client.post(_WEBHOOK_URL, headers=_VALID_WEBHOOK_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_no_auth_header_required(self, client):
        """Webhook endpoint has no Bearer token requirement."""
        with _mock_session_for_webhook(token_found=True):
            resp = client.post(_WEBHOOK_URL, headers=_VALID_WEBHOOK_HEADERS)
        # Should succeed (200) without Authorization header
        assert resp.status_code == 200


class TestGoogleDriveWebhookSyncPing:
    """Initial 'sync' ping from Google should be acknowledged without creating a job."""

    def test_sync_ping_returns_ok(self, client):
        headers = {**_VALID_WEBHOOK_HEADERS, "X-Goog-Resource-State": "sync"}
        with _mock_session_for_webhook(token_found=True):
            resp = client.post(_WEBHOOK_URL, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["event"] == "sync_ping"

    def test_sync_ping_does_not_create_job(self, client):
        """The 'sync' ping must not insert a sync_jobs row."""
        headers = {**_VALID_WEBHOOK_HEADERS, "X-Goog-Resource-State": "sync"}
        with _mock_session_for_webhook(token_found=True) as mock_session:
            client.post(_WEBHOOK_URL, headers=headers)
        # Check that no INSERT INTO sync_jobs was called
        insert_calls = [
            call
            for call in mock_session.execute.call_args_list
            if "INSERT INTO sync_jobs" in str(call.args[0] if call.args else "")
        ]
        assert len(insert_calls) == 0


class TestGoogleDriveWebhookChangeEvent:
    """Change events should create a sync_job entry."""

    def test_change_event_creates_sync_job(self, client):
        with _mock_session_for_webhook(token_found=True):
            resp = client.post(_WEBHOOK_URL, headers=_VALID_WEBHOOK_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "job_id" in data

    def test_change_event_job_id_is_uuid(self, client):
        with _mock_session_for_webhook(token_found=True):
            resp = client.post(_WEBHOOK_URL, headers=_VALID_WEBHOOK_HEADERS)
        job_id = resp.json()["job_id"]
        # Must be a valid UUID string
        uuid.UUID(job_id)

    def test_change_event_inserts_sync_job_row(self, client):
        """Verify the INSERT INTO sync_jobs SQL was executed."""
        with _mock_session_for_webhook(token_found=True) as mock_session:
            resp = client.post(_WEBHOOK_URL, headers=_VALID_WEBHOOK_HEADERS)
        assert resp.status_code == 200
        insert_calls = [
            call
            for call in mock_session.execute.call_args_list
            if "INSERT INTO sync_jobs" in str(call.args[0] if call.args else "")
        ]
        assert len(insert_calls) >= 1


class TestGoogleDriveWebhookIdempotency:
    """Duplicate webhook delivery within 5-second window should be skipped."""

    def test_duplicate_delivery_returns_ok(self, client):
        with _mock_session_for_webhook(token_found=True, is_duplicate=True):
            resp = client.post(_WEBHOOK_URL, headers=_VALID_WEBHOOK_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["event"] == "duplicate_skipped"

    def test_duplicate_delivery_skips_sync_job_insert(self, client):
        """A duplicate delivery must NOT insert an additional sync_jobs row."""
        with _mock_session_for_webhook(
            token_found=True, is_duplicate=True
        ) as mock_session:
            client.post(_WEBHOOK_URL, headers=_VALID_WEBHOOK_HEADERS)
        insert_calls = [
            call
            for call in mock_session.execute.call_args_list
            if "INSERT INTO sync_jobs" in str(call.args[0] if call.args else "")
        ]
        assert len(insert_calls) == 0


# ---------------------------------------------------------------------------
# run_incremental_sync unit tests (pure function logic, no HTTP)
# ---------------------------------------------------------------------------


class TestRunIncrementalSync:
    """Unit tests for the run_incremental_sync() orchestration function."""

    @pytest.mark.asyncio
    async def test_integration_not_found_returns_skipped(self):
        from app.modules.documents.google_drive.sync_worker import run_incremental_sync

        mock_db = AsyncMock()

        with patch(
            "app.modules.documents.google_drive.sync_worker.get_gd_integration_for_tenant",
            new=AsyncMock(return_value=None),
        ):
            result = await run_incremental_sync(
                integration_id=TEST_INTEGRATION_ID,
                tenant_id=TEST_TENANT_ID,
                trigger="webhook",
                db=mock_db,
            )

        assert result["status"] == "skipped"
        assert result["reason"] == "integration_not_found"

    @pytest.mark.asyncio
    async def test_no_page_token_saves_start_token(self):
        """First run: fetches and stores startPageToken, returns 'initialised'."""
        from app.modules.documents.google_drive.sync_worker import run_incremental_sync

        mock_db = AsyncMock()
        fake_service = MagicMock()
        fake_service.changes.return_value.getStartPageToken.return_value.execute.return_value = {
            "startPageToken": "token-001"
        }

        with (
            patch(
                "app.modules.documents.google_drive.sync_worker.get_gd_integration_for_tenant",
                new=AsyncMock(
                    return_value={
                        "id": TEST_INTEGRATION_ID,
                        "tenant_id": TEST_TENANT_ID,
                        "status": "active",
                        "config": {"credential_ref": "vault:ref"},
                    }
                ),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker._build_drive_service",
                return_value=fake_service,
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker.get_page_token_db",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker._get_start_page_token",
                new=AsyncMock(return_value="token-001"),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker.save_page_token_db",
                new=AsyncMock(),
            ),
        ):
            result = await run_incremental_sync(
                integration_id=TEST_INTEGRATION_ID,
                tenant_id=TEST_TENANT_ID,
                trigger="webhook",
                db=mock_db,
            )

        assert result["status"] == "initialised"
        assert result["page_token_saved"] is True

    @pytest.mark.asyncio
    async def test_changed_file_is_queued(self):
        """A valid changed file triggers _queue_file_reembed and creates a sync_job."""
        from app.modules.documents.google_drive.sync_worker import run_incremental_sync

        mock_db = AsyncMock()
        fake_changes_response = {
            "newStartPageToken": "token-002",
            "changes": [
                {
                    "fileId": "file-abc",
                    "removed": False,
                    "file": {
                        "id": "file-abc",
                        "name": "report.pdf",
                        "mimeType": "application/pdf",
                        "trashed": False,
                        "modifiedTime": "2026-03-17T10:00:00Z",
                    },
                }
            ],
        }

        queued_files = []

        async def _fake_queue(service, file_id, file_name, **kwargs):
            queued_files.append(file_id)

        with (
            patch(
                "app.modules.documents.google_drive.sync_worker.get_gd_integration_for_tenant",
                new=AsyncMock(
                    return_value={
                        "id": TEST_INTEGRATION_ID,
                        "tenant_id": TEST_TENANT_ID,
                        "status": "active",
                        "config": {"credential_ref": "vault:ref"},
                    }
                ),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker._build_drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker.get_page_token_db",
                new=AsyncMock(return_value="token-001"),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker._list_changes",
                new=AsyncMock(return_value=fake_changes_response),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker._queue_file_reembed",
                new=AsyncMock(side_effect=_fake_queue),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker.save_page_token_db",
                new=AsyncMock(),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker.create_incremental_sync_job_db",
                new=AsyncMock(return_value=str(uuid.uuid4())),
            ),
        ):
            result = await run_incremental_sync(
                integration_id=TEST_INTEGRATION_ID,
                tenant_id=TEST_TENANT_ID,
                trigger="webhook",
                db=mock_db,
            )

        assert result["status"] == "completed"
        assert result["files_queued"] == 1
        assert "file-abc" in queued_files

    @pytest.mark.asyncio
    async def test_inaccessible_file_is_skipped(self):
        """
        A file that raises an exception during _queue_file_reembed must be
        logged and skipped — the sync must NOT crash.
        """
        from app.modules.documents.google_drive.sync_worker import run_incremental_sync

        mock_db = AsyncMock()
        fake_changes_response = {
            "newStartPageToken": "token-002",
            "changes": [
                {
                    "fileId": "file-403",
                    "removed": False,
                    "file": {
                        "id": "file-403",
                        "name": "secret.pdf",
                        "mimeType": "application/pdf",
                        "trashed": False,
                    },
                }
            ],
        }

        async def _failing_queue(service, file_id, **kwargs):
            raise PermissionError(f"403 Access denied to file {file_id}")

        with (
            patch(
                "app.modules.documents.google_drive.sync_worker.get_gd_integration_for_tenant",
                new=AsyncMock(
                    return_value={
                        "id": TEST_INTEGRATION_ID,
                        "tenant_id": TEST_TENANT_ID,
                        "status": "active",
                        "config": {"credential_ref": "vault:ref"},
                    }
                ),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker._build_drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker.get_page_token_db",
                new=AsyncMock(return_value="token-001"),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker._list_changes",
                new=AsyncMock(return_value=fake_changes_response),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker._queue_file_reembed",
                new=AsyncMock(side_effect=_failing_queue),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker.save_page_token_db",
                new=AsyncMock(),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker.create_incremental_sync_job_db",
                new=AsyncMock(return_value=str(uuid.uuid4())),
            ),
        ):
            result = await run_incremental_sync(
                integration_id=TEST_INTEGRATION_ID,
                tenant_id=TEST_TENANT_ID,
                trigger="webhook",
                db=mock_db,
            )

        # Sync must complete successfully despite the per-file error
        assert result["status"] == "completed"
        assert result["files_queued"] == 0
        assert result["files_skipped"] == 1

    @pytest.mark.asyncio
    async def test_trashed_file_is_skipped(self):
        """Files with trashed=True are skipped without queuing for reembed."""
        from app.modules.documents.google_drive.sync_worker import run_incremental_sync

        mock_db = AsyncMock()
        fake_changes_response = {
            "newStartPageToken": "token-002",
            "changes": [
                {
                    "fileId": "file-trash",
                    "removed": False,
                    "file": {
                        "id": "file-trash",
                        "name": "deleted.pdf",
                        "mimeType": "application/pdf",
                        "trashed": True,
                    },
                }
            ],
        }
        queue_calls = []

        async def _track_queue(service, file_id, **kwargs):
            queue_calls.append(file_id)

        with (
            patch(
                "app.modules.documents.google_drive.sync_worker.get_gd_integration_for_tenant",
                new=AsyncMock(
                    return_value={
                        "id": TEST_INTEGRATION_ID,
                        "tenant_id": TEST_TENANT_ID,
                        "status": "active",
                        "config": {"credential_ref": "vault:ref"},
                    }
                ),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker._build_drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker.get_page_token_db",
                new=AsyncMock(return_value="token-001"),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker._list_changes",
                new=AsyncMock(return_value=fake_changes_response),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker._queue_file_reembed",
                new=AsyncMock(side_effect=_track_queue),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker.save_page_token_db",
                new=AsyncMock(),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker.create_incremental_sync_job_db",
                new=AsyncMock(return_value=str(uuid.uuid4())),
            ),
        ):
            result = await run_incremental_sync(
                integration_id=TEST_INTEGRATION_ID,
                tenant_id=TEST_TENANT_ID,
                trigger="webhook",
                db=mock_db,
            )

        assert result["files_queued"] == 0
        assert result["files_skipped"] == 1
        assert len(queue_calls) == 0

    @pytest.mark.asyncio
    async def test_unsupported_mime_type_is_skipped(self):
        """Files with non-indexable MIME types are skipped silently."""
        from app.modules.documents.google_drive.sync_worker import run_incremental_sync

        mock_db = AsyncMock()
        fake_changes_response = {
            "newStartPageToken": "token-002",
            "changes": [
                {
                    "fileId": "file-vid",
                    "removed": False,
                    "file": {
                        "id": "file-vid",
                        "name": "video.mp4",
                        "mimeType": "video/mp4",
                        "trashed": False,
                    },
                }
            ],
        }

        with (
            patch(
                "app.modules.documents.google_drive.sync_worker.get_gd_integration_for_tenant",
                new=AsyncMock(
                    return_value={
                        "id": TEST_INTEGRATION_ID,
                        "tenant_id": TEST_TENANT_ID,
                        "status": "active",
                        "config": {"credential_ref": "vault:ref"},
                    }
                ),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker._build_drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker.get_page_token_db",
                new=AsyncMock(return_value="token-001"),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker._list_changes",
                new=AsyncMock(return_value=fake_changes_response),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker.save_page_token_db",
                new=AsyncMock(),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker.create_incremental_sync_job_db",
                new=AsyncMock(return_value=str(uuid.uuid4())),
            ),
        ):
            result = await run_incremental_sync(
                integration_id=TEST_INTEGRATION_ID,
                tenant_id=TEST_TENANT_ID,
                trigger="webhook",
                db=mock_db,
            )

        assert result["files_queued"] == 0
        assert result["files_skipped"] == 1

    @pytest.mark.asyncio
    async def test_service_build_failure_returns_error(self):
        """If Drive service cannot be built, return error status (no crash)."""
        from app.modules.documents.google_drive.sync_worker import run_incremental_sync

        mock_db = AsyncMock()

        with (
            patch(
                "app.modules.documents.google_drive.sync_worker.get_gd_integration_for_tenant",
                new=AsyncMock(
                    return_value={
                        "id": TEST_INTEGRATION_ID,
                        "tenant_id": TEST_TENANT_ID,
                        "status": "active",
                        "config": {"credential_ref": "vault:ref"},
                    }
                ),
            ),
            patch(
                "app.modules.documents.google_drive.sync_worker._build_drive_service",
                side_effect=RuntimeError("Vault unreachable"),
            ),
        ):
            result = await run_incremental_sync(
                integration_id=TEST_INTEGRATION_ID,
                tenant_id=TEST_TENANT_ID,
                trigger="webhook",
                db=mock_db,
            )

        assert result["status"] == "error"
        assert result["reason"] == "service_build_failed"


# ---------------------------------------------------------------------------
# DB helper unit tests (pure logic, no HTTP)
# ---------------------------------------------------------------------------


class TestGetGdIntegrationByChannelToken:
    """Unit tests for the channel-token lookup used in webhook auth."""

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        from app.modules.documents.google_drive.sync_worker import (
            get_gd_integration_by_channel_token,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_gd_integration_by_channel_token("bad-token", mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_dict_when_found(self):
        from app.modules.documents.google_drive.sync_worker import (
            get_gd_integration_by_channel_token,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mapping = MagicMock()
        mapping.__getitem__ = lambda self, key: {
            "id": uuid.UUID(TEST_INTEGRATION_ID),
            "tenant_id": uuid.UUID(TEST_TENANT_ID),
            "status": "active",
            "config": json.dumps({"channel_token": TEST_CHANNEL_TOKEN}),
        }[key]
        mock_result.mappings.return_value.first.return_value = mapping
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_gd_integration_by_channel_token(TEST_CHANNEL_TOKEN, mock_db)
        assert result is not None
        assert result["id"] == TEST_INTEGRATION_ID
        assert result["tenant_id"] == TEST_TENANT_ID

    @pytest.mark.asyncio
    async def test_sql_uses_parameterized_token(self):
        """The channel_token must be passed as a bind parameter, never interpolated."""
        from app.modules.documents.google_drive.sync_worker import (
            get_gd_integration_by_channel_token,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        token = "'; DROP TABLE integrations; --"
        await get_gd_integration_by_channel_token(token, mock_db)

        call_args = mock_db.execute.call_args
        # The SQL string must NOT contain the injection payload
        sql_str = str(call_args.args[0])
        assert "DROP TABLE" not in sql_str
        # The token must appear in the params dict
        params = call_args.args[1]
        assert params.get("channel_token") == token
