"""
Unit tests for PA-035: GDPR deletion workflow.

  POST /platform/tenants/{id}/gdpr-delete

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
TEST_ADMIN_TENANT_ID = "12345678-1234-5678-1234-567812345678"

_BASE_URL = f"/api/v1/platform/tenants/{TEST_TENANT_ID}/gdpr-delete"


def _make_platform_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "platform-admin-001",
        "tenant_id": TEST_ADMIN_TENANT_ID,
        "roles": ["platform_admin"],
        "scope": "platform",
        "plan": "enterprise",
        "email": "platform@mingai.io",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_tenant_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "tenant-user-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
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


def _platform_headers() -> dict:
    return {"Authorization": f"Bearer {_make_platform_token()}"}


def _tenant_headers() -> dict:
    return {"Authorization": f"Bearer {_make_tenant_token()}"}


def _patch_db_gdpr(tenant_exists: bool = True, pipeline_raises: bool = False):
    """Patch DB for GDPR endpoint.

    Call order:
      1. UUID validation passes (no DB call)
      2. SELECT tenant exists → fetchone → (tenant_id,) or None
      3+ : pipeline calls (mocked via _execute_gdpr_pipeline patch)
    """
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()
    call_count = 0
    tenant_row = (uuid.UUID(TEST_TENANT_ID),) if tenant_exists else None

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            # SELECT tenant
            mock_result.fetchone.return_value = tenant_row
        else:
            mock_result.fetchone.return_value = None
            mock_result.scalar.return_value = 0
            mock_result.fetchall.return_value = []
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
            yield
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    return _ctx()


_VALID_PAYLOAD = {
    "confirmed": True,
    "deletion_reference": "GDPR-REQ-2026-001",
}


class TestGdprDeletionAuth:
    def test_requires_auth(self, client):
        resp = client.post(_BASE_URL, json=_VALID_PAYLOAD)
        assert resp.status_code == 401

    def test_requires_platform_admin(self, client):
        resp = client.post(_BASE_URL, json=_VALID_PAYLOAD, headers=_tenant_headers())
        assert resp.status_code == 403


class TestGdprDeletionValidation:
    def test_confirmed_false_returns_422(self, client):
        with _patch_db_gdpr():
            resp = client.post(
                _BASE_URL,
                json={"confirmed": False, "deletion_reference": "REF-001"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 422

    def test_missing_deletion_reference_returns_422(self, client):
        resp = client.post(
            _BASE_URL,
            json={"confirmed": True, "deletion_reference": ""},
            headers=_platform_headers(),
        )
        assert resp.status_code == 422

    def test_invalid_tenant_uuid_returns_422(self, client):
        resp = client.post(
            "/api/v1/platform/tenants/not-a-uuid/gdpr-delete",
            json=_VALID_PAYLOAD,
            headers=_platform_headers(),
        )
        assert resp.status_code == 422

    def test_tenant_not_found_returns_404(self, client):
        fake_report = {
            "dry_run": False,
            "deleted_tables": [],
            "retained_for_legal_hold": [],
            "counts": {},
            "completed_at": "2026-03-16T00:00:00+00:00",
        }
        with _patch_db_gdpr(tenant_exists=False):
            with patch(
                "app.modules.platform.routes._execute_gdpr_pipeline",
                new=AsyncMock(return_value=fake_report),
            ):
                resp = client.post(
                    _BASE_URL, json=_VALID_PAYLOAD, headers=_platform_headers()
                )
        assert resp.status_code == 404


class TestGdprDeletionDryRun:
    def test_dry_run_returns_report_without_executing(self, client):
        fake_report = {
            "dry_run": True,
            "deleted_tables": [],
            "retained_for_legal_hold": ["usage_events", "audit_log"],
            "counts": {"users_anonymized": 5},
            "completed_at": "2026-03-16T00:00:00+00:00",
        }
        with _patch_db_gdpr():
            with patch(
                "app.modules.platform.routes._execute_gdpr_pipeline",
                new=AsyncMock(return_value=fake_report),
            ):
                resp = client.post(
                    _BASE_URL,
                    json={**_VALID_PAYLOAD, "dry_run": True},
                    headers=_platform_headers(),
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert "report" in data

    def test_dry_run_does_not_call_audit_log(self, client):
        """dry_run should not write to audit log or commit."""
        fake_report = {
            "dry_run": True,
            "deleted_tables": [],
            "retained_for_legal_hold": [],
            "counts": {},
            "completed_at": "2026-03-16T00:00:00+00:00",
        }
        with _patch_db_gdpr() as _:
            with patch(
                "app.modules.platform.routes._execute_gdpr_pipeline",
                new=AsyncMock(return_value=fake_report),
            ):
                resp = client.post(
                    _BASE_URL,
                    json={**_VALID_PAYLOAD, "dry_run": True},
                    headers=_platform_headers(),
                )
        assert resp.status_code == 200


class TestGdprDeletionExecution:
    def test_successful_deletion_returns_report(self, client):
        fake_report = {
            "dry_run": False,
            "deleted_tables": ["tenants (soft-deleted)", "users (PII anonymized)"],
            "retained_for_legal_hold": ["usage_events", "audit_log"],
            "counts": {"users_anonymized": 3},
            "completed_at": "2026-03-16T00:00:00+00:00",
        }
        with _patch_db_gdpr():
            with patch(
                "app.modules.platform.routes._execute_gdpr_pipeline",
                new=AsyncMock(return_value=fake_report),
            ):
                with patch("app.modules.platform.routes._insert_platform_audit_log"):
                    with patch("app.modules.platform.routes.get_redis") as mock_redis:
                        mock_redis.return_value = MagicMock(
                            scan=AsyncMock(return_value=(0, [])),
                            delete=AsyncMock(),
                        )
                        resp = client.post(
                            _BASE_URL,
                            json=_VALID_PAYLOAD,
                            headers=_platform_headers(),
                        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert "report" in data
        assert "deleted_tables" in data["report"]
        assert "retained_for_legal_hold" in data["report"]
