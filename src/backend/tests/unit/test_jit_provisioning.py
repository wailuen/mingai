"""
Unit tests for JIT provisioning (P3AUTH-008) and group-to-role sync (P3AUTH-009).

Tests:
  POST /internal/users/jit-provision
  POST /internal/users/sync-roles

Tier 1: mocked DB + mocked Redis — fast, no real infrastructure required.

Coverage:
JIT Provisioning:
1. First login creates user with role=viewer, status=active
2. Repeat login (same auth0_user_id) updates last_login_at — no duplicate
3. user.created audit event emitted only on first login
4. Missing INTERNAL_SECRET_KEY env var → 401
5. Wrong X-Internal-Secret header → 401

Group Sync (P3AUTH-009):
6. No mapping configured → noop (no DB write)
7. Single group maps to viewer → role set to viewer, audit logged
8. Multiple groups, highest wins (admin > editor > viewer)
9. No matching group → role unchanged (no_change)
10. User not found → 404
11. Wrong secret → 401
"""
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.auth.jit_provisioning import internal_router

# ---------------------------------------------------------------------------
# Test app fixture — mount ONLY the internal router, skip the full app stack
# ---------------------------------------------------------------------------


def _make_test_app() -> FastAPI:
    """Create a minimal FastAPI app with only the internal router under /internal."""
    app = FastAPI()
    app.include_router(internal_router, prefix="/internal")
    return app


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_SECRET = "test-internal-secret-abc123"
_TENANT_ID = "a0000000-0000-0000-0000-000000000001"
_AUTH0_ID = "auth0|test123"
_EMAIL = "test@example.com"
_NAME = "Test User"

_VALID_BODY = {
    "auth0_user_id": _AUTH0_ID,
    "email": _EMAIL,
    "name": _NAME,
    "tenant_id": _TENANT_ID,
    "groups": [],
}


def _make_mock_session(fetchone_return=None, rowcount=1):
    """Build a mock AsyncSession with configurable fetchone result."""
    session = AsyncMock()
    # Simulate execute returning an object with fetchone()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = fetchone_return
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Helpers for dependency overrides
# ---------------------------------------------------------------------------


def _override_session(session):
    """Return a FastAPI dependency override that yields *session*."""

    async def _get_session():
        yield session

    return _get_session


# ---------------------------------------------------------------------------
# Test 4: Missing INTERNAL_SECRET_KEY env var → 401
# ---------------------------------------------------------------------------


def test_missing_internal_secret_key_returns_401():
    """If INTERNAL_SECRET_KEY is not configured, JIT endpoint must return 401."""
    app = _make_test_app()
    client = TestClient(app, raise_server_exceptions=False)

    # Ensure the env var is absent
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("INTERNAL_SECRET_KEY", None)
        response = client.post(
            "/internal/users/jit-provision",
            json=_VALID_BODY,
            headers={"X-Internal-Secret": "any-value"},
        )

    assert response.status_code == 401
    assert "not configured" in response.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# Test 5: Wrong X-Internal-Secret header → 401
# ---------------------------------------------------------------------------


def test_wrong_internal_secret_returns_401():
    """A mismatched X-Internal-Secret header must return 401."""
    app = _make_test_app()
    client = TestClient(app, raise_server_exceptions=False)

    with patch.dict(os.environ, {"INTERNAL_SECRET_KEY": _VALID_SECRET}):
        response = client.post(
            "/internal/users/jit-provision",
            json=_VALID_BODY,
            headers={"X-Internal-Secret": "wrong-secret"},
        )

    assert response.status_code == 401


def test_missing_internal_secret_header_returns_401():
    """A request without X-Internal-Secret header must return 401."""
    app = _make_test_app()
    client = TestClient(app, raise_server_exceptions=False)

    with patch.dict(os.environ, {"INTERNAL_SECRET_KEY": _VALID_SECRET}):
        response = client.post(
            "/internal/users/jit-provision",
            json=_VALID_BODY,
            # No X-Internal-Secret header
        )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test 1: First login creates user with role=viewer, status=active
# ---------------------------------------------------------------------------


def test_first_login_creates_user():
    """
    On first login (no existing user), JIT endpoint creates a new user row
    with role=viewer and status=active, and returns action='created'.
    """
    app = _make_test_app()

    # fetchone returns None (no existing user)
    mock_session = _make_mock_session(fetchone_return=None)

    from app.core.session import get_async_session

    app.dependency_overrides[get_async_session] = _override_session(mock_session)

    client = TestClient(app)

    with patch.dict(os.environ, {"INTERNAL_SECRET_KEY": _VALID_SECRET}):
        response = client.post(
            "/internal/users/jit-provision",
            json=_VALID_BODY,
            headers={"X-Internal-Secret": _VALID_SECRET},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "created"
    assert "user_id" in body
    # Verify user_id is a valid UUID
    uuid.UUID(body["user_id"])

    # DB execute must have been called: bypass_rls + jit_default_role lookup + lookup + INSERT users + INSERT audit_log
    assert mock_session.execute.call_count >= 3
    mock_session.commit.assert_called_once()

    # Check that INSERT INTO users was called with role=viewer (via :role param) and status=active
    all_calls = mock_session.execute.call_args_list
    insert_user_call = next(
        (c for c in all_calls if "INSERT INTO users" in str(c.args[0])), None
    )
    assert insert_user_call is not None
    assert "'active'" in str(insert_user_call.args[0])
    # role is now parameterized — check via params dict
    if len(insert_user_call.args) > 1 and isinstance(insert_user_call.args[1], dict):
        assert insert_user_call.args[1].get("role") == "viewer"


# ---------------------------------------------------------------------------
# Test 2: Repeat login updates last_login_at, does NOT create duplicate
# ---------------------------------------------------------------------------


def test_repeat_login_updates_last_login_not_duplicate():
    """
    On repeat login (user already exists), JIT endpoint updates last_login_at
    and returns action='updated'. No new INSERT INTO users must occur.
    """
    app = _make_test_app()

    existing_user_id = str(uuid.uuid4())

    # fetchone returns an existing user row: (id, tenant_id, status)
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, i: [
        existing_user_id,
        _TENANT_ID,
        "active",
    ][i]
    # Use a tuple-like object that the code does str(row[0]), str(row[1]), str(row[2])
    mock_fetchone = (existing_user_id, _TENANT_ID, "active")

    mock_session = _make_mock_session(fetchone_return=mock_fetchone)

    from app.core.session import get_async_session

    app.dependency_overrides[get_async_session] = _override_session(mock_session)

    client = TestClient(app)

    with patch.dict(os.environ, {"INTERNAL_SECRET_KEY": _VALID_SECRET}):
        response = client.post(
            "/internal/users/jit-provision",
            json=_VALID_BODY,
            headers={"X-Internal-Secret": _VALID_SECRET},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "updated"
    assert body["user_id"] == existing_user_id

    # Verify UPDATE was called
    all_sql_calls = [str(call.args[0]) for call in mock_session.execute.call_args_list]
    update_call = next((sql for sql in all_sql_calls if "UPDATE users" in sql), None)
    assert update_call is not None

    # No INSERT INTO users should have been called
    insert_user_call = next(
        (sql for sql in all_sql_calls if "INSERT INTO users" in sql), None
    )
    assert insert_user_call is None

    mock_session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Test 3: user.created audit event emitted only on first login
# ---------------------------------------------------------------------------


def test_audit_event_emitted_on_first_login_only():
    """
    The audit_log INSERT with action='user.created' must occur on first login.
    On repeat login, no audit_log INSERT must occur.
    """
    app = _make_test_app()

    # --- First login (no existing user) ---
    mock_session_first = _make_mock_session(fetchone_return=None)

    from app.core.session import get_async_session

    app.dependency_overrides[get_async_session] = _override_session(mock_session_first)
    client = TestClient(app)

    with patch.dict(os.environ, {"INTERNAL_SECRET_KEY": _VALID_SECRET}):
        resp1 = client.post(
            "/internal/users/jit-provision",
            json=_VALID_BODY,
            headers={"X-Internal-Secret": _VALID_SECRET},
        )

    assert resp1.status_code == 200
    assert resp1.json()["action"] == "created"

    # Check audit_log INSERT was called
    all_sql_first = [
        str(call.args[0]) for call in mock_session_first.execute.call_args_list
    ]
    audit_insert = next(
        (sql for sql in all_sql_first if "audit_log" in sql and "INSERT" in sql), None
    )
    assert audit_insert is not None, "Expected INSERT INTO audit_log on first login"
    assert "user.created" in audit_insert

    # --- Repeat login (user exists) ---
    existing_user_id = str(uuid.uuid4())
    mock_fetchone = (existing_user_id, _TENANT_ID, "active")
    mock_session_repeat = _make_mock_session(fetchone_return=mock_fetchone)
    app.dependency_overrides[get_async_session] = _override_session(mock_session_repeat)

    with patch.dict(os.environ, {"INTERNAL_SECRET_KEY": _VALID_SECRET}):
        resp2 = client.post(
            "/internal/users/jit-provision",
            json=_VALID_BODY,
            headers={"X-Internal-Secret": _VALID_SECRET},
        )

    assert resp2.status_code == 200
    assert resp2.json()["action"] == "updated"

    # No audit_log INSERT on repeat login
    all_sql_repeat = [
        str(call.args[0]) for call in mock_session_repeat.execute.call_args_list
    ]
    audit_on_repeat = next(
        (sql for sql in all_sql_repeat if "audit_log" in sql and "INSERT" in sql), None
    )
    assert audit_on_repeat is None, "Must NOT insert audit_log on repeat login"


# ---------------------------------------------------------------------------
# Additional: name falls back to email prefix when name is None
# ---------------------------------------------------------------------------


def test_first_login_uses_email_prefix_when_name_is_none():
    """When name is None, user should be created with email prefix as name."""
    app = _make_test_app()
    mock_session = _make_mock_session(fetchone_return=None)

    from app.core.session import get_async_session

    app.dependency_overrides[get_async_session] = _override_session(mock_session)
    client = TestClient(app)

    body_no_name = dict(_VALID_BODY)
    body_no_name["name"] = None

    with patch.dict(os.environ, {"INTERNAL_SECRET_KEY": _VALID_SECRET}):
        response = client.post(
            "/internal/users/jit-provision",
            json=body_no_name,
            headers={"X-Internal-Secret": _VALID_SECRET},
        )

    assert response.status_code == 200
    assert response.json()["action"] == "created"

    # Verify the INSERT includes email prefix as name
    all_sql_calls = [str(call.args[0]) for call in mock_session.execute.call_args_list]
    insert_user_call = next(
        (sql for sql in all_sql_calls if "INSERT INTO users" in sql), None
    )
    assert insert_user_call is not None
    # The params should have name = "test" (prefix of "test@example.com")
    insert_params = [
        call.args[1]
        for call in mock_session.execute.call_args_list
        if len(call.args) > 1
        and isinstance(call.args[1], dict)
        and "name" in call.args[1]
    ]
    assert insert_params, "Expected INSERT params with name field"
    assert insert_params[0]["name"] == "test"


# ===========================================================================
# P3AUTH-009: Group-to-role sync — POST /internal/users/sync-roles
# ===========================================================================

_SYNC_ROLES_URL = "/internal/users/sync-roles"

_VALID_SYNC_BODY = {
    "auth0_user_id": _AUTH0_ID,
    "groups": ["finance-team"],
    "tenant_id": _TENANT_ID,
}


def _make_sync_roles_session(
    user_row=None,
    group_sync_config_row=None,
):
    """
    Build a mock AsyncSession for sync-roles tests.

    execute() returns:
    - First call (bypass_rls): result with fetchone → None
    - Second call (lookup user): result with fetchone → user_row
    - Third call (get group_sync config): result with fetchone → group_sync_config_row
    - Fourth+ calls (UPDATE / audit INSERT): rowcount=1
    """
    session = AsyncMock()

    results = []

    # bypass_rls result
    bypass_result = MagicMock()
    bypass_result.fetchone.return_value = None
    results.append(bypass_result)

    # user lookup result
    user_result = MagicMock()
    user_result.fetchone.return_value = user_row
    results.append(user_result)

    # group sync config result
    config_result = MagicMock()
    config_result.fetchone.return_value = group_sync_config_row
    results.append(config_result)

    # Any further calls (UPDATE users, INSERT audit_log) return generic result
    generic_result = MagicMock()
    generic_result.fetchone.return_value = None
    generic_result.rowcount = 1

    call_count = [0]

    async def _execute(sql, params=None):
        idx = call_count[0]
        call_count[0] += 1
        if idx < len(results):
            return results[idx]
        return generic_result

    session.execute = _execute
    session.commit = AsyncMock()
    return session


def _make_group_sync_config_row(allowlist: list, mapping: dict):
    """Build a mock row for group sync config."""
    import json

    config = {
        "auth0_group_allowlist": allowlist,
        "auth0_group_role_mapping": mapping,
    }
    row = MagicMock()
    row.__getitem__ = lambda self, i: json.dumps(config) if i == 0 else None
    # Make row[0] work as attribute access too
    return (json.dumps(config),)


# ---------------------------------------------------------------------------
# Test 6: No mapping configured → noop
# ---------------------------------------------------------------------------


def test_sync_roles_no_mapping_returns_noop():
    """When no sso_group_sync config is stored, sync-roles returns noop."""
    app = _make_test_app()
    # No group_sync_config_row (simulates missing tenant_configs entry)
    mock_session = _make_sync_roles_session(
        user_row=(_AUTH0_ID[:8], _TENANT_ID, "viewer"),
        group_sync_config_row=None,
    )

    from app.core.session import get_async_session

    app.dependency_overrides[get_async_session] = _override_session(mock_session)
    client = TestClient(app)

    with patch.dict(os.environ, {"INTERNAL_SECRET_KEY": _VALID_SECRET}):
        response = client.post(
            _SYNC_ROLES_URL,
            json=_VALID_SYNC_BODY,
            headers={"X-Internal-Secret": _VALID_SECRET},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "noop"
    assert body["reason"] == "no_mapping_configured"
    # commit must NOT have been called (no DB writes for noop)
    mock_session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Test 7: Single group maps to viewer → role synced, audit logged
# ---------------------------------------------------------------------------


def test_sync_roles_single_group_maps_to_viewer():
    """When one group maps to viewer and user is currently a different role, role is synced."""
    import json

    app = _make_test_app()

    config_data = json.dumps(
        {
            "auth0_group_allowlist": ["finance-team"],
            "auth0_group_role_mapping": {"finance-team": "viewer"},
        }
    )

    mock_session = _make_sync_roles_session(
        user_row=("user-uuid-001", _TENANT_ID, "editor"),
        group_sync_config_row=(config_data,),
    )

    from app.core.session import get_async_session

    app.dependency_overrides[get_async_session] = _override_session(mock_session)
    client = TestClient(app)

    with patch.dict(os.environ, {"INTERNAL_SECRET_KEY": _VALID_SECRET}):
        response = client.post(
            _SYNC_ROLES_URL,
            json={
                "auth0_user_id": _AUTH0_ID,
                "groups": ["finance-team"],
                "tenant_id": _TENANT_ID,
            },
            headers={"X-Internal-Secret": _VALID_SECRET},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "role_synced"
    assert body["new_role"] == "viewer"
    mock_session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Test 8: Multiple groups, highest wins (admin > editor > viewer)
# ---------------------------------------------------------------------------


def test_sync_roles_multiple_groups_highest_wins():
    """When multiple groups match, the highest-privilege role wins."""
    import json

    app = _make_test_app()

    config_data = json.dumps(
        {
            "auth0_group_allowlist": [],  # empty allowlist = accept any
            "auth0_group_role_mapping": {
                "viewers-group": "viewer",
                "editors-group": "editor",
                "admins-group": "admin",
            },
        }
    )

    mock_session = _make_sync_roles_session(
        user_row=("user-uuid-002", _TENANT_ID, "viewer"),
        group_sync_config_row=(config_data,),
    )

    from app.core.session import get_async_session

    app.dependency_overrides[get_async_session] = _override_session(mock_session)
    client = TestClient(app)

    with patch.dict(os.environ, {"INTERNAL_SECRET_KEY": _VALID_SECRET}):
        response = client.post(
            _SYNC_ROLES_URL,
            json={
                "auth0_user_id": _AUTH0_ID,
                # User is in all three groups — admin wins
                "groups": ["viewers-group", "editors-group", "admins-group"],
                "tenant_id": _TENANT_ID,
            },
            headers={"X-Internal-Secret": _VALID_SECRET},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "role_synced"
    assert body["new_role"] == "admin"
    mock_session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Test 9: No matching group → role unchanged
# ---------------------------------------------------------------------------


def test_sync_roles_no_matching_group_returns_no_change():
    """When no group matches the mapping, role is left unchanged."""
    import json

    app = _make_test_app()

    config_data = json.dumps(
        {
            "auth0_group_allowlist": [],
            "auth0_group_role_mapping": {"known-group": "editor"},
        }
    )

    mock_session = _make_sync_roles_session(
        user_row=("user-uuid-003", _TENANT_ID, "viewer"),
        group_sync_config_row=(config_data,),
    )

    from app.core.session import get_async_session

    app.dependency_overrides[get_async_session] = _override_session(mock_session)
    client = TestClient(app)

    with patch.dict(os.environ, {"INTERNAL_SECRET_KEY": _VALID_SECRET}):
        response = client.post(
            _SYNC_ROLES_URL,
            json={
                "auth0_user_id": _AUTH0_ID,
                "groups": ["unknown-group"],  # not in mapping
                "tenant_id": _TENANT_ID,
            },
            headers={"X-Internal-Secret": _VALID_SECRET},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "no_change"
    # DEF-008: commit IS called even on no_change because team membership sync
    # runs on every sync-roles invocation to keep memberships current.
    mock_session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Test 10: User not found → 404
# ---------------------------------------------------------------------------


def test_sync_roles_user_not_found_returns_404():
    """When user is not found by auth0_user_id, sync-roles returns 404."""
    app = _make_test_app()

    mock_session = _make_sync_roles_session(
        user_row=None,  # no user found
        group_sync_config_row=None,
    )

    from app.core.session import get_async_session

    app.dependency_overrides[get_async_session] = _override_session(mock_session)
    client = TestClient(app, raise_server_exceptions=False)

    with patch.dict(os.environ, {"INTERNAL_SECRET_KEY": _VALID_SECRET}):
        response = client.post(
            _SYNC_ROLES_URL,
            json=_VALID_SYNC_BODY,
            headers={"X-Internal-Secret": _VALID_SECRET},
        )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Test 11: Wrong secret → 401
# ---------------------------------------------------------------------------


def test_sync_roles_wrong_secret_returns_401():
    """A request with a wrong X-Internal-Secret returns 401."""
    app = _make_test_app()
    client = TestClient(app, raise_server_exceptions=False)

    with patch.dict(os.environ, {"INTERNAL_SECRET_KEY": _VALID_SECRET}):
        response = client.post(
            _SYNC_ROLES_URL,
            json=_VALID_SYNC_BODY,
            headers={"X-Internal-Secret": "wrong-secret"},
        )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test 12: _highest_role utility
# ---------------------------------------------------------------------------


def test_highest_role_priority():
    """_highest_role selects the most privileged role from a list."""
    from app.modules.auth.jit_provisioning import _highest_role

    assert _highest_role(["viewer", "editor", "admin"]) == "admin"
    assert _highest_role(["viewer", "editor"]) == "editor"
    assert _highest_role(["viewer"]) == "viewer"
    assert _highest_role([]) is None
