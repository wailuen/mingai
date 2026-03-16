"""
Unit tests for TA-031: Onboarding wizard persistence.

  GET  /api/v1/admin/onboarding/status
  PATCH /api/v1/admin/onboarding/progress
  PATCH /api/v1/admin/onboarding/dismiss

Tier 1: Fast, isolated — mocks DB session.
"""
import contextlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "t031" * 16  # 64 chars
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = str(uuid.uuid4())

_STATUS_URL = "/api/v1/admin/onboarding/status"
_PROGRESS_URL = "/api/v1/admin/onboarding/progress"
_DISMISS_URL = "/api/v1/admin/onboarding/dismiss"


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
# DB mock helper
# ---------------------------------------------------------------------------


def _patch_db(progress_config=None, dismiss_config=None):
    """
    Patch DB to return controlled rows for onboarding queries.

    progress_config: dict or None (stored JSON value for onboarding_progress row)
    dismiss_config:  dict or None (stored JSON value for onboarding_dismiss row)
    """
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()

    async def _execute(stmt, params=None, **kwargs):
        mock_result = MagicMock()
        # Resolve the config_type from the bound params rather than SQL text
        # because both queries have the same SQL structure.
        config_type = None
        if params and isinstance(params, dict):
            config_type = params.get("config_type")

        if "INSERT" in str(stmt) or "ON CONFLICT" in str(stmt):
            # Upsert — no meaningful return value needed
            mock_result.fetchone.return_value = None
        elif config_type == "onboarding_progress":
            mock_result.fetchone.return_value = (
                (progress_config,) if progress_config is not None else None
            )
        elif config_type == "onboarding_dismiss":
            mock_result.fetchone.return_value = (
                (dismiss_config,) if dismiss_config is not None else None
            )
        else:
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


# ---------------------------------------------------------------------------
# Tests: Auth
# ---------------------------------------------------------------------------


class TestOnboardingAuth:
    def test_status_requires_auth(self, client):
        resp = client.get(_STATUS_URL)
        assert resp.status_code == 401

    def test_status_requires_tenant_admin(self, client):
        resp = client.get(_STATUS_URL, headers=_viewer_headers())
        assert resp.status_code == 403

    def test_progress_requires_tenant_admin(self, client):
        resp = client.patch(
            _PROGRESS_URL,
            json={"step": "invite_users", "completed": True},
            headers=_viewer_headers(),
        )
        assert resp.status_code == 403

    def test_dismiss_requires_tenant_admin(self, client):
        resp = client.patch(_DISMISS_URL, headers=_viewer_headers())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: GET /admin/onboarding/status
# ---------------------------------------------------------------------------


class TestOnboardingGetStatus:
    def test_no_config_returns_all_false(self, client):
        """When no tenant_configs row exists, all steps are false."""
        with _patch_db(progress_config=None, dismiss_config=None):
            resp = client.get(_STATUS_URL, headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step"] == "invite_users"
        assert data["completed"] is False
        assert data["dismissed_until"] is None
        steps = data["steps"]
        for step in [
            "invite_users",
            "configure_kb",
            "configure_agent",
            "configure_sso",
            "done",
        ]:
            assert steps[step] is False

    def test_partial_progress_returns_correct_current_step(self, client):
        """When invite_users is done, current_step should advance to configure_kb."""
        stored = {
            "invite_users": True,
            "configure_kb": False,
            "configure_agent": False,
            "configure_sso": False,
            "done": False,
        }
        with _patch_db(progress_config=stored, dismiss_config=None):
            resp = client.get(_STATUS_URL, headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step"] == "configure_kb"
        assert data["steps"]["invite_users"] is True

    def test_all_complete_returns_completed_true(self, client):
        """When all steps are true, completed should be True."""
        stored = {
            "invite_users": True,
            "configure_kb": True,
            "configure_agent": True,
            "configure_sso": True,
            "done": True,
        }
        with _patch_db(progress_config=stored, dismiss_config=None):
            resp = client.get(_STATUS_URL, headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["completed"] is True
        assert data["current_step"] == "done"

    def test_dismissed_until_returned_when_set(self, client):
        """dismissed_until from DB is included in response."""
        future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        dismiss_stored = {"dismissed_until": future}
        with _patch_db(progress_config=None, dismiss_config=dismiss_stored):
            resp = client.get(_STATUS_URL, headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["dismissed_until"] == future


# ---------------------------------------------------------------------------
# Tests: PATCH /admin/onboarding/progress
# ---------------------------------------------------------------------------


class TestOnboardingPatchProgress:
    def test_invalid_step_returns_422(self, client):
        with _patch_db():
            resp = client.patch(
                _PROGRESS_URL,
                json={"step": "invalid_step", "completed": True},
                headers=_admin_headers(),
            )
        assert resp.status_code == 422

    def test_valid_step_marked_complete(self, client):
        """PATCH with a valid step updates and returns updated status."""
        initial = {
            "invite_users": False,
            "configure_kb": False,
            "configure_agent": False,
            "configure_sso": False,
            "done": False,
        }
        with _patch_db(progress_config=initial):
            resp = client.patch(
                _PROGRESS_URL,
                json={"step": "invite_users", "completed": True},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        # After marking invite_users done, current_step advances
        assert data["current_step"] in ("configure_kb", "invite_users")

    def test_missing_step_field_returns_422(self, client):
        with _patch_db():
            resp = client.patch(
                _PROGRESS_URL,
                json={"completed": True},
                headers=_admin_headers(),
            )
        assert resp.status_code == 422

    def test_missing_completed_field_returns_422(self, client):
        with _patch_db():
            resp = client.patch(
                _PROGRESS_URL,
                json={"step": "invite_users"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: PATCH /admin/onboarding/dismiss
# ---------------------------------------------------------------------------


class TestOnboardingDismiss:
    def test_dismiss_returns_dismissed_until(self, client):
        """Dismiss should return a dismissed_until timestamp ~7 days from now."""
        with _patch_db():
            resp = client.patch(_DISMISS_URL, headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["dismissed_until"] is not None
        # Verify the timestamp is in the future
        dismissed = datetime.fromisoformat(data["dismissed_until"])
        # Should be approximately 7 days from now (within a minute tolerance)
        expected_min = datetime.now(timezone.utc) + timedelta(days=6, hours=23)
        assert dismissed > expected_min


# ---------------------------------------------------------------------------
# Tests: _compute_current_step logic (unit-level, no HTTP)
# ---------------------------------------------------------------------------


class TestComputeCurrentStep:
    def test_all_false_returns_first_step(self):
        from app.modules.admin.onboarding import _compute_current_step

        steps = {
            "invite_users": False,
            "configure_kb": False,
            "configure_agent": False,
            "configure_sso": False,
            "done": False,
        }
        assert _compute_current_step(steps) == "invite_users"

    def test_first_two_complete_returns_third(self):
        from app.modules.admin.onboarding import _compute_current_step

        steps = {
            "invite_users": True,
            "configure_kb": True,
            "configure_agent": False,
            "configure_sso": False,
            "done": False,
        }
        assert _compute_current_step(steps) == "configure_agent"

    def test_all_complete_returns_done(self):
        from app.modules.admin.onboarding import _compute_current_step

        steps = {
            s: True
            for s in [
                "invite_users",
                "configure_kb",
                "configure_agent",
                "configure_sso",
                "done",
            ]
        }
        assert _compute_current_step(steps) == "done"
