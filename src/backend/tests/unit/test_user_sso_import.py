"""
Unit tests for TA-033: User import from SSO.

All Auth0 Management API calls and DB helpers are mocked so these tests run
without network access or a real database.
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.modules.admin.sso_import import (
    ImportFromSSORequest,
    ImportFromSSOResponse,
    _MAX_IMPORT_BATCH,
    create_imported_user,
    find_existing_users_by_auth0_ids,
    import_users_from_sso,
    list_sso_directory_users,
    log_sso_import_audit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT_ID = str(uuid.uuid4())
ACTOR_ID = str(uuid.uuid4())


def _make_user(roles=None, scope="tenant"):
    user = MagicMock()
    user.id = ACTOR_ID
    user.tenant_id = TENANT_ID
    user.roles = roles or ["tenant_admin"]
    user.scope = scope
    return user


def _make_db(fetchone_return=None, fetchall_return=None):
    db = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = fetchone_return
    result.fetchall.return_value = fetchall_return or []
    db.execute.return_value = result
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# find_existing_users_by_auth0_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_existing_returns_matching_ids():
    existing_id = "auth0|existing"
    db = _make_db(fetchall_return=[(existing_id,), ("auth0|other",)])
    result = await find_existing_users_by_auth0_ids(
        ["auth0|existing", "auth0|new", "auth0|other"],
        TENANT_ID,
        db,
    )
    assert result == {"auth0|existing", "auth0|other"}


@pytest.mark.asyncio
async def test_find_existing_empty_input():
    db = _make_db()
    result = await find_existing_users_by_auth0_ids([], TENANT_ID, db)
    assert result == set()
    db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# create_imported_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_imported_user_success():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    result = await create_imported_user(
        auth0_user_id="auth0|abc",
        email="alice@example.com",
        name="Alice",
        tenant_id=TENANT_ID,
        db=db,
    )
    assert result is not None
    assert len(result) == 36  # UUID string
    call_kwargs = db.execute.call_args
    assert call_kwargs is not None


@pytest.mark.asyncio
async def test_create_imported_user_unique_violation_returns_none():
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=IntegrityError(
            None, None, Exception("duplicate key unique constraint")
        )
    )
    result = await create_imported_user(
        auth0_user_id="auth0|dup",
        email="dup@example.com",
        name=None,
        tenant_id=TENANT_ID,
        db=db,
    )
    assert result is None


@pytest.mark.asyncio
async def test_create_imported_user_other_exception_propagates():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=Exception("connection lost"))
    with pytest.raises(Exception, match="connection lost"):
        await create_imported_user(
            auth0_user_id="auth0|err",
            email="err@example.com",
            name=None,
            tenant_id=TENANT_ID,
            db=db,
        )


# ---------------------------------------------------------------------------
# log_sso_import_audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_sso_import_audit_writes_correct_action():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    await log_sso_import_audit(
        actor_id=ACTOR_ID,
        tenant_id=TENANT_ID,
        created_count=3,
        skipped_count=1,
        failed_count=0,
        db=db,
    )
    db.execute.assert_called_once()
    call_args = db.execute.call_args
    # The action value is embedded as a literal in the SQL string, not a bind param.
    # Verify the SQL clause contains the correct action string.
    sql_text = str(call_args.args[0])
    assert "sso_import" in sql_text
    # Verify bound params include the details JSON with expected counts.
    params = call_args.args[1]
    details = json.loads(params["details"])
    assert details["created"] == 3
    assert details["skipped"] == 1
    assert details["failed"] == 0


# ---------------------------------------------------------------------------
# ImportFromSSORequest — Pydantic validation
# ---------------------------------------------------------------------------


def test_import_request_max_batch_enforced():
    with pytest.raises(ValueError, match="50"):
        ImportFromSSORequest(auth0_user_ids=["auth0|x"] * 51)


def test_import_request_empty_list_rejected():
    with pytest.raises(ValueError):
        ImportFromSSORequest(auth0_user_ids=[])


def test_import_request_valid():
    req = ImportFromSSORequest(auth0_user_ids=["auth0|abc", "auth0|def"])
    assert len(req.auth0_user_ids) == 2


def test_import_request_at_max_boundary():
    req = ImportFromSSORequest(
        auth0_user_ids=[f"auth0|{i}" for i in range(_MAX_IMPORT_BATCH)]
    )
    assert len(req.auth0_user_ids) == _MAX_IMPORT_BATCH


# ---------------------------------------------------------------------------
# import_users_from_sso — route handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_creates_new_users():
    """Users not already present are fetched from Auth0 and inserted."""
    auth0_uid = "auth0|newuser"
    current_user = _make_user()
    db = _make_db(fetchall_return=[])  # no existing users

    # Mock find_existing_users_by_auth0_ids — returns empty set
    # Mock create_imported_user — returns a new UUID
    new_uid = str(uuid.uuid4())

    profile_data = {"email": "new@example.com", "name": "New User"}

    with (
        patch(
            "app.modules.admin.sso_import.find_existing_users_by_auth0_ids",
            new_callable=AsyncMock,
            return_value=set(),
        ),
        patch(
            "app.modules.admin.sso_import.management_api_request",
            new_callable=AsyncMock,
            return_value=profile_data,
        ),
        patch(
            "app.modules.admin.sso_import.create_imported_user",
            new_callable=AsyncMock,
            return_value=new_uid,
        ),
        patch(
            "app.modules.admin.sso_import.log_sso_import_audit",
            new_callable=AsyncMock,
        ),
    ):
        request = ImportFromSSORequest(auth0_user_ids=[auth0_uid])
        result = await import_users_from_sso(request, current_user, db)

    assert result.created == 1
    assert result.skipped == 0
    assert result.failed == []


@pytest.mark.asyncio
async def test_import_skips_duplicate_users():
    """Users already in DB are counted as skipped, not created."""
    auth0_uid = "auth0|existing"
    current_user = _make_user()
    db = _make_db()

    with (
        patch(
            "app.modules.admin.sso_import.find_existing_users_by_auth0_ids",
            new_callable=AsyncMock,
            return_value={auth0_uid},
        ),
        patch(
            "app.modules.admin.sso_import.log_sso_import_audit",
            new_callable=AsyncMock,
        ),
    ):
        request = ImportFromSSORequest(auth0_user_ids=[auth0_uid])
        result = await import_users_from_sso(request, current_user, db)

    assert result.created == 0
    assert result.skipped == 1
    assert result.failed == []


@pytest.mark.asyncio
async def test_import_logged_to_audit_log():
    """Audit log is written regardless of outcome."""
    current_user = _make_user()
    db = _make_db()

    audit_mock = AsyncMock()

    with (
        patch(
            "app.modules.admin.sso_import.find_existing_users_by_auth0_ids",
            new_callable=AsyncMock,
            return_value={"auth0|a"},
        ),
        patch(
            "app.modules.admin.sso_import.log_sso_import_audit",
            audit_mock,
        ),
    ):
        request = ImportFromSSORequest(auth0_user_ids=["auth0|a"])
        await import_users_from_sso(request, current_user, db)

    audit_mock.assert_called_once()


@pytest.mark.asyncio
async def test_import_auth0_profile_fetch_failure_goes_to_failed():
    """If Auth0 profile fetch fails the user appears in the failed list."""
    auth0_uid = "auth0|broken"
    current_user = _make_user()
    db = _make_db()

    with (
        patch(
            "app.modules.admin.sso_import.find_existing_users_by_auth0_ids",
            new_callable=AsyncMock,
            return_value=set(),
        ),
        patch(
            "app.modules.admin.sso_import.management_api_request",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Auth0 error"),
        ),
        patch(
            "app.modules.admin.sso_import.log_sso_import_audit",
            new_callable=AsyncMock,
        ),
    ):
        request = ImportFromSSORequest(auth0_user_ids=[auth0_uid])
        result = await import_users_from_sso(request, current_user, db)

    assert result.created == 0
    assert len(result.failed) == 1
    assert result.failed[0].auth0_user_id == auth0_uid


@pytest.mark.asyncio
async def test_import_email_conflict_counts_as_skipped():
    """If insert fails on email uniqueness the user is counted as skipped."""
    auth0_uid = "auth0|conflict"
    current_user = _make_user()
    db = _make_db()

    with (
        patch(
            "app.modules.admin.sso_import.find_existing_users_by_auth0_ids",
            new_callable=AsyncMock,
            return_value=set(),
        ),
        patch(
            "app.modules.admin.sso_import.management_api_request",
            new_callable=AsyncMock,
            return_value={"email": "x@x.com", "name": "X"},
        ),
        patch(
            "app.modules.admin.sso_import.create_imported_user",
            new_callable=AsyncMock,
            return_value=None,  # email conflict
        ),
        patch(
            "app.modules.admin.sso_import.log_sso_import_audit",
            new_callable=AsyncMock,
        ),
    ):
        request = ImportFromSSORequest(auth0_user_ids=[auth0_uid])
        result = await import_users_from_sso(request, current_user, db)

    assert result.created == 0
    assert result.skipped == 1


# ---------------------------------------------------------------------------
# list_sso_directory_users — route handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sso_directory_users_returns_users():
    """Happy path: org_id configured, Auth0 returns members."""
    current_user = _make_user()
    db = _make_db()

    members = [
        {"user_id": "auth0|a", "email": "a@ex.com", "name": "A"},
        {"user_id": "auth0|b", "email": "b@ex.com", "name": "B"},
    ]

    with (
        patch.dict("os.environ", {"AUTH0_DOMAIN": "mingai-dev.jp.auth0.com"}),
        patch(
            "app.modules.admin.sso_import.get_tenant_auth0_org_id",
            new_callable=AsyncMock,
            return_value="org_abc123",
        ),
        patch(
            "app.modules.admin.sso_import.management_api_request",
            new_callable=AsyncMock,
            return_value=members,
        ),
    ):
        result = await list_sso_directory_users(current_user, db)

    assert result.total == 2
    assert result.users[0].auth0_user_id == "auth0|a"
    assert result.users[1].email == "b@ex.com"


@pytest.mark.asyncio
async def test_list_sso_directory_users_missing_org_id_returns_404():
    current_user = _make_user()
    db = _make_db()

    with (
        patch.dict("os.environ", {"AUTH0_DOMAIN": "mingai-dev.jp.auth0.com"}),
        patch(
            "app.modules.admin.sso_import.get_tenant_auth0_org_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await list_sso_directory_users(current_user, db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_sso_directory_users_no_auth0_domain_returns_422():
    current_user = _make_user()
    db = _make_db()

    with patch.dict("os.environ", {}, clear=True):
        # Ensure AUTH0_DOMAIN is absent
        import os

        os.environ.pop("AUTH0_DOMAIN", None)
        with pytest.raises(HTTPException) as exc_info:
            await list_sso_directory_users(current_user, db)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_list_sso_directory_users_auth0_error_returns_502():
    current_user = _make_user()
    db = _make_db()

    with (
        patch.dict("os.environ", {"AUTH0_DOMAIN": "mingai-dev.jp.auth0.com"}),
        patch(
            "app.modules.admin.sso_import.get_tenant_auth0_org_id",
            new_callable=AsyncMock,
            return_value="org_abc",
        ),
        patch(
            "app.modules.admin.sso_import.management_api_request",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Auth0 unreachable"),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await list_sso_directory_users(current_user, db)

    assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# Auth enforcement — require_tenant_admin (403 for viewer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_viewer_role_is_rejected_by_dependency():
    """The require_tenant_admin dependency must block non-admins.

    We test the dependency itself rather than the full route stack since unit
    tests don't run a real FastAPI test client.
    """
    from app.core.dependencies import require_tenant_admin

    viewer = _make_user(roles=["viewer"])

    with pytest.raises(HTTPException) as exc_info:
        await require_tenant_admin(viewer)

    assert exc_info.value.status_code == 403
