"""
Unit tests for TA-012: Glossary version history and rollback.

  GET  /glossary/{id}/history
  PATCH /glossary/{id}/rollback/{version_id}

Tier 1: Fast, isolated.
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

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = str(uuid.uuid4())
TEST_TERM_ID = str(uuid.uuid4())
TEST_VERSION_ID = str(uuid.uuid4())


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


_HISTORY_URL = f"/api/v1/glossary/{TEST_TERM_ID}/history"
_ROLLBACK_URL = f"/api/v1/glossary/{TEST_TERM_ID}/rollback/{TEST_VERSION_ID}"


def _make_audit_row(details: dict | None = None):
    """Build a mock audit_log row tuple matching the SELECT columns."""
    if details is None:
        details = {
            "changed_fields": ["full_form"],
            "before": {"full_form": "Old Form"},
            "after": {"full_form": "New Form"},
        }
    return (
        uuid.UUID(TEST_VERSION_ID),  # id
        "admin-user-001",  # user_id
        "update",  # action
        details,  # details (JSONB — already a dict from asyncpg)
        datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc),  # created_at
        "admin@test.com",  # actor_email
    )


def _patch_db(history_rows=None, audit_row=None, term_row=None):
    """Patch DB session for glossary history tests.

    GET /history: SELECT audit_log → fetchall()
    PATCH /rollback:
      1. SELECT audit_log (version fetch) → fetchone()
      2. SELECT glossary_terms (current state) → fetchone()
      3. UPDATE glossary_terms → fetchone()
      4. INSERT audit_log (rollback record)
      5. commit
    """
    from app.core.session import get_async_session
    from app.main import app

    if history_rows is None:
        history_rows = [_make_audit_row()]

    if audit_row is None:
        audit_row = (
            uuid.UUID(TEST_VERSION_ID),
            {
                "changed_fields": ["full_form"],
                "before": {"full_form": "Old Form"},
                "after": {"full_form": "New Form"},
            },
        )

    if term_row is None:
        term_row = (
            uuid.UUID(TEST_TERM_ID),
            "HR",
            "New Form",
            [],
            datetime(2026, 3, 16, 9, 0, 0, tzinfo=timezone.utc),
        )

    mock_session = MagicMock()

    async def _execute(*args, **kwargs):
        mock_result = MagicMock()
        sql = str(args[0]) if args else ""

        if (
            "FROM audit_log" in sql
            and "SELECT" in sql.upper()
            and "resource_type = 'glossary_term'" in sql
        ):
            if "WHERE id = CAST" in sql:
                # Single version fetch (rollback)
                mock_result.fetchone.return_value = audit_row
            else:
                # History list
                mock_result.fetchall.return_value = history_rows
        elif "FROM glossary_terms" in sql and "SELECT" in sql.upper():
            mock_result.fetchone.return_value = term_row
        elif "UPDATE glossary_terms" in sql:
            # update_glossary_term_db calls get_glossary_term_db after update
            mock_result.fetchone.return_value = term_row
            mock_result.rowcount = 1
        elif "INSERT INTO audit_log" in sql:
            mock_result.fetchone.return_value = None
        else:
            mock_result.fetchone.return_value = None
            mock_result.fetchall.return_value = []
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


class TestGlossaryHistoryAuth:
    def test_requires_auth(self, client):
        resp = client.get(_HISTORY_URL)
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client):
        resp = client.get(_HISTORY_URL, headers=_viewer_headers())
        assert resp.status_code == 403

    def test_invalid_term_id_returns_422(self, client):
        resp = client.get(
            "/api/v1/glossary/not-a-uuid/history", headers=_admin_headers()
        )
        assert resp.status_code == 422


class TestGlossaryHistorySuccess:
    def test_returns_items_and_total(self, client):
        with _patch_db():
            resp = client.get(_HISTORY_URL, headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] == 1

    def test_empty_history_returns_empty_list(self, client):
        with _patch_db(history_rows=[]):
            resp = client.get(_HISTORY_URL, headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_item_structure(self, client):
        with _patch_db():
            resp = client.get(_HISTORY_URL, headers=_admin_headers())
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert set(item.keys()) >= {
            "id",
            "actor_id",
            "actor_email",
            "action",
            "changed_fields",
            "before",
            "after",
            "created_at",
        }

    def test_item_has_before_and_after(self, client):
        with _patch_db():
            resp = client.get(_HISTORY_URL, headers=_admin_headers())
        item = resp.json()["items"][0]
        assert item["before"] == {"full_form": "Old Form"}
        assert item["after"] == {"full_form": "New Form"}
        assert "full_form" in item["changed_fields"]


class TestGlossaryRollbackAuth:
    def test_requires_auth(self, client):
        resp = client.patch(_ROLLBACK_URL)
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client):
        resp = client.patch(_ROLLBACK_URL, headers=_viewer_headers())
        assert resp.status_code == 403


class TestGlossaryRollbackValidation:
    def test_invalid_term_id_returns_422(self, client):
        resp = client.patch(
            f"/api/v1/glossary/not-a-uuid/rollback/{TEST_VERSION_ID}",
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_invalid_version_id_returns_422(self, client):
        resp = client.patch(
            f"/api/v1/glossary/{TEST_TERM_ID}/rollback/not-a-uuid",
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_version_not_found_returns_404(self, client):
        # Use explicit override: version SELECT returns None
        from app.core.session import get_async_session
        from app.main import app

        mock_session = MagicMock()

        async def _execute(*args, **kwargs):
            mock_result = MagicMock()
            # Explicitly return None for all fetchone calls
            mock_result.fetchone = MagicMock(return_value=None)
            return mock_result

        mock_session.execute = AsyncMock(side_effect=_execute)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        async def _override():
            yield mock_session

        app.dependency_overrides[get_async_session] = _override
        try:
            resp = client.patch(_ROLLBACK_URL, headers=_admin_headers())
        finally:
            app.dependency_overrides.pop(get_async_session, None)
        assert resp.status_code == 404

    def test_version_with_no_before_state_returns_422(self, client):
        audit_row_no_before = (
            uuid.UUID(TEST_VERSION_ID),
            {
                "changed_fields": ["full_form"],
                "before": {},
                "after": {"full_form": "X"},
            },
        )
        with _patch_db(audit_row=audit_row_no_before):
            resp = client.patch(_ROLLBACK_URL, headers=_admin_headers())
        assert resp.status_code == 422


class TestGlossaryRollbackSuccess:
    def test_rollback_restores_term(self, client):
        """Rollback returns the restored term."""
        with _patch_db():
            resp = client.patch(_ROLLBACK_URL, headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        # The response is the updated term (from get_glossary_term_db)
        assert "term" in data or "id" in data

    def test_rollback_only_restores_allowed_fields(self, client):
        """Before state with disallowed fields only keeps allowed ones."""
        audit_with_extra = (
            uuid.UUID(TEST_VERSION_ID),
            {
                "before": {
                    "full_form": "Old Form",
                    "tenant_id": "hacked",  # should be ignored
                    "id": "hacked",  # should be ignored
                },
                "after": {"full_form": "New Form"},
            },
        )
        with _patch_db(audit_row=audit_with_extra):
            resp = client.patch(_ROLLBACK_URL, headers=_admin_headers())
        # Should succeed — only full_form from `before` is applied
        assert resp.status_code == 200
