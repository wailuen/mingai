"""
Unit tests for TA-012: Glossary version history and rollback.

Focused on:
  - GET  /glossary/{id}/history     — audit_log entries for a term
  - PATCH /glossary/{id}/rollback/{version_id} — restore before state

See also test_glossary_history.py for HTTP-layer tests.

Tier 1: Fast, isolated.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "c" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = str(uuid.uuid4())
TEST_TERM_ID = str(uuid.uuid4())
TEST_VERSION_ID = str(uuid.uuid4())

_HISTORY_URL = f"/api/v1/glossary/{TEST_TERM_ID}/history"
_ROLLBACK_URL = f"/api/v1/glossary/{TEST_TERM_ID}/rollback/{TEST_VERSION_ID}"


def _make_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "admin-user-001",
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


def _make_viewer_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "viewer-user-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["viewer"],
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


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_make_admin_token()}"}


def _viewer_headers() -> dict:
    return {"Authorization": f"Bearer {_make_viewer_token()}"}


# ---------------------------------------------------------------------------
# Auth / access control
# ---------------------------------------------------------------------------


class TestHistoryAuth:
    def test_history_requires_auth(self, client):
        resp = client.get(_HISTORY_URL)
        assert resp.status_code == 401

    def test_history_viewer_forbidden(self, client):
        resp = client.get(_HISTORY_URL, headers=_viewer_headers())
        assert resp.status_code == 403

    def test_rollback_requires_auth(self, client):
        resp = client.patch(_ROLLBACK_URL)
        assert resp.status_code == 401

    def test_rollback_viewer_forbidden(self, client):
        resp = client.patch(_ROLLBACK_URL, headers=_viewer_headers())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestHistoryValidation:
    def test_non_uuid_term_id_rejected(self, client):
        resp = client.get(
            "/api/v1/glossary/not-a-uuid/history", headers=_admin_headers()
        )
        assert resp.status_code == 422

    def test_non_uuid_version_id_rejected(self, client):
        resp = client.patch(
            f"/api/v1/glossary/{TEST_TERM_ID}/rollback/not-a-uuid",
            headers=_admin_headers(),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Rollback field-allowlist enforcement (pure function test)
# ---------------------------------------------------------------------------


class TestRollbackAllowlist:
    def test_only_allowed_fields_restored(self):
        """
        _GLOSSARY_UPDATABLE_FIELDS must not include tenant_id, id, or created_at.
        Verify that unauthorized field keys are filtered out before applying update.
        """
        from app.modules.glossary.routes import _GLOSSARY_UPDATABLE_FIELDS

        unsafe_fields = {"tenant_id", "id", "created_at", "updated_at"}
        overlap = unsafe_fields & _GLOSSARY_UPDATABLE_FIELDS
        assert overlap == set(), f"Dangerous fields in allowlist: {overlap}"

    def test_updatable_fields_are_correct(self):
        from app.modules.glossary.routes import _GLOSSARY_UPDATABLE_FIELDS

        assert "term" in _GLOSSARY_UPDATABLE_FIELDS
        assert "full_form" in _GLOSSARY_UPDATABLE_FIELDS
        assert "aliases" in _GLOSSARY_UPDATABLE_FIELDS

    def test_before_state_filtering_removes_unknown_keys(self):
        """Simulate the before-state filtering logic from rollback endpoint."""
        from app.modules.glossary.routes import _GLOSSARY_UPDATABLE_FIELDS

        before_state = {
            "term": "HR",
            "full_form": "Human Resources",
            "aliases": [],
            "tenant_id": "hacked",
            "id": "hacked",
        }
        updates = {
            k: v for k, v in before_state.items() if k in _GLOSSARY_UPDATABLE_FIELDS
        }
        assert "tenant_id" not in updates
        assert "id" not in updates
        assert updates["term"] == "HR"
        assert updates["full_form"] == "Human Resources"


# ---------------------------------------------------------------------------
# History response shape
# ---------------------------------------------------------------------------


class TestHistoryResponseShape:
    def test_history_response_has_items_and_total(self, client):
        from app.core.session import get_async_session
        from app.main import app

        audit_row = (
            uuid.UUID(TEST_VERSION_ID),
            "admin-user-001",
            "update",
            {
                "changed_fields": ["full_form"],
                "before": {"full_form": "Old"},
                "after": {"full_form": "New"},
            },
            datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc),
            "admin@test.com",
        )

        mock_session = MagicMock()

        async def _execute(*args, **kwargs):
            mock_result = MagicMock()
            sql = str(args[0]) if args else ""
            if "FROM audit_log" in sql and "glossary_term" in sql:
                mock_result.fetchall.return_value = [audit_row]
            else:
                mock_result.fetchall.return_value = []
                mock_result.fetchone.return_value = None
            return mock_result

        mock_session.execute = AsyncMock(side_effect=_execute)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        async def _override():
            yield mock_session

        app.dependency_overrides[get_async_session] = _override
        try:
            resp = client.get(_HISTORY_URL, headers=_admin_headers())
        finally:
            app.dependency_overrides.pop(get_async_session, None)

        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] == 1

    def test_history_item_has_all_required_keys(self, client):
        from app.core.session import get_async_session
        from app.main import app

        audit_row = (
            uuid.UUID(TEST_VERSION_ID),
            "admin-user-001",
            "update",
            {
                "changed_fields": ["term"],
                "before": {"term": "HR"},
                "after": {"term": "HR2"},
            },
            datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc),
            "admin@test.com",
        )

        mock_session = MagicMock()

        async def _execute(*args, **kwargs):
            mock_result = MagicMock()
            sql = str(args[0]) if args else ""
            if "FROM audit_log" in sql and "glossary_term" in sql:
                mock_result.fetchall.return_value = [audit_row]
            else:
                mock_result.fetchall.return_value = []
                mock_result.fetchone.return_value = None
            return mock_result

        mock_session.execute = AsyncMock(side_effect=_execute)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        async def _override():
            yield mock_session

        app.dependency_overrides[get_async_session] = _override
        try:
            resp = client.get(_HISTORY_URL, headers=_admin_headers())
        finally:
            app.dependency_overrides.pop(get_async_session, None)

        assert resp.status_code == 200
        item = resp.json()["items"][0]
        required_keys = {
            "id",
            "actor_id",
            "actor_email",
            "action",
            "changed_fields",
            "before",
            "after",
            "created_at",
        }
        assert required_keys.issubset(set(item.keys()))
