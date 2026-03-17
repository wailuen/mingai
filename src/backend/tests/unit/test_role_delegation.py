"""
Unit tests for TA-035: Tenant admin role delegation.

All DB operations are mocked so these tests run without a real database.
"""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.admin.role_delegation import (
    DelegateAdminRequest,
    DelegationListResponse,
    DelegationResponse,
    _RESOURCE_REQUIRED_SCOPES,
    _VALID_DELEGATED_SCOPES,
    create_delegation_db,
    delegate_admin,
    delete_delegation_db,
    list_delegations_db,
    list_user_delegations,
    log_delegation_audit,
    revoke_delegation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT_ID = str(uuid.uuid4())
ACTOR_ID = str(uuid.uuid4())
TARGET_USER_ID = str(uuid.uuid4())
KB_ID = str(uuid.uuid4())
AGENT_ID = str(uuid.uuid4())
DELEGATION_ID = str(uuid.uuid4())


def _make_user(roles=None):
    user = MagicMock()
    user.id = ACTOR_ID
    user.tenant_id = TENANT_ID
    user.roles = roles or ["tenant_admin"]
    user.scope = "tenant"
    return user


def _make_db_with_user_check(user_exists=True, fetchone_return=None):
    """DB mock where first execute() checks user existence."""
    db = AsyncMock()
    user_result = MagicMock()
    user_result.fetchone.return_value = (TARGET_USER_ID,) if user_exists else None
    # By default, subsequent calls return fetchone_return
    later_result = MagicMock()
    later_result.fetchone.return_value = fetchone_return
    later_result.fetchall.return_value = []
    db.execute = AsyncMock(side_effect=[user_result, later_result, MagicMock()])
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# DelegateAdminRequest validation
# ---------------------------------------------------------------------------


def test_valid_kb_admin_scope_with_resource_id():
    req = DelegateAdminRequest(
        delegated_scope="kb_admin",
        resource_id=str(uuid.uuid4()),
    )
    assert req.delegated_scope == "kb_admin"


def test_valid_agent_admin_scope_with_resource_id():
    req = DelegateAdminRequest(
        delegated_scope="agent_admin",
        resource_id=str(uuid.uuid4()),
    )
    assert req.delegated_scope == "agent_admin"


def test_valid_user_admin_scope_no_resource_id():
    req = DelegateAdminRequest(delegated_scope="user_admin")
    assert req.resource_id is None


def test_invalid_scope_rejected():
    with pytest.raises(ValueError, match="delegated_scope must be one of"):
        DelegateAdminRequest(delegated_scope="super_admin")


def test_invalid_resource_id_uuid_rejected():
    with pytest.raises(ValueError, match="valid UUID"):
        DelegateAdminRequest(delegated_scope="kb_admin", resource_id="not-a-uuid")


# ---------------------------------------------------------------------------
# create_delegation_db
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_delegation_db_returns_dict_with_id():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())

    row = await create_delegation_db(
        user_id=TARGET_USER_ID,
        tenant_id=TENANT_ID,
        delegated_scope="kb_admin",
        resource_id=KB_ID,
        granted_by=ACTOR_ID,
        expires_at=None,
        db=db,
    )
    assert "id" in row
    assert row["user_id"] == TARGET_USER_ID
    assert row["delegated_scope"] == "kb_admin"
    assert row["resource_id"] == KB_ID
    assert row["expires_at"] is None


@pytest.mark.asyncio
async def test_create_delegation_db_with_expires_at():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    exp = datetime(2027, 1, 1, tzinfo=timezone.utc)

    row = await create_delegation_db(
        user_id=TARGET_USER_ID,
        tenant_id=TENANT_ID,
        delegated_scope="agent_admin",
        resource_id=AGENT_ID,
        granted_by=ACTOR_ID,
        expires_at=exp,
        db=db,
    )
    assert row["expires_at"] == exp.isoformat()


# ---------------------------------------------------------------------------
# delete_delegation_db
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_delegation_db_returns_true_on_success():
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.rowcount = 1
    db.execute = AsyncMock(return_value=result_mock)

    deleted = await delete_delegation_db(
        delegation_id=DELEGATION_ID,
        user_id=TARGET_USER_ID,
        tenant_id=TENANT_ID,
        db=db,
    )
    assert deleted is True


@pytest.mark.asyncio
async def test_delete_delegation_db_returns_false_when_not_found():
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.rowcount = 0
    db.execute = AsyncMock(return_value=result_mock)

    deleted = await delete_delegation_db(
        delegation_id=DELEGATION_ID,
        user_id=TARGET_USER_ID,
        tenant_id=TENANT_ID,
        db=db,
    )
    assert deleted is False


# ---------------------------------------------------------------------------
# log_delegation_audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_delegation_audit_grant():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())

    await log_delegation_audit(
        actor_id=ACTOR_ID,
        tenant_id=TENANT_ID,
        action="delegation.granted",
        target_user_id=TARGET_USER_ID,
        delegation_id=DELEGATION_ID,
        delegated_scope="kb_admin",
        resource_id=KB_ID,
        db=db,
    )
    db.execute.assert_called_once()
    # db.execute(text(sql), params) — call_args[0] is positional tuple
    params = db.execute.call_args[0][1]
    assert params["action"] == "delegation.granted"
    details = json.loads(params["details"])
    assert details["delegated_scope"] == "kb_admin"
    assert details["resource_id"] == KB_ID


@pytest.mark.asyncio
async def test_log_delegation_audit_revoke():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())

    await log_delegation_audit(
        actor_id=ACTOR_ID,
        tenant_id=TENANT_ID,
        action="delegation.revoked",
        target_user_id=TARGET_USER_ID,
        delegation_id=DELEGATION_ID,
        delegated_scope="user_admin",
        resource_id=None,
        db=db,
    )
    # db.execute(text(sql), params) — call_args[0] is positional tuple
    params = db.execute.call_args[0][1]
    assert params["action"] == "delegation.revoked"


# ---------------------------------------------------------------------------
# delegate_admin route handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delegate_admin_kb_requires_resource_id():
    current_user = _make_user()
    db = AsyncMock()
    db.commit = AsyncMock()

    request = DelegateAdminRequest(delegated_scope="kb_admin")  # no resource_id
    with pytest.raises(HTTPException) as exc_info:
        await delegate_admin(TARGET_USER_ID, request, current_user, db)

    assert exc_info.value.status_code == 422
    assert "resource_id" in exc_info.value.detail


@pytest.mark.asyncio
async def test_delegate_admin_agent_requires_resource_id():
    current_user = _make_user()
    db = AsyncMock()
    db.commit = AsyncMock()

    request = DelegateAdminRequest(delegated_scope="agent_admin")  # no resource_id
    with pytest.raises(HTTPException) as exc_info:
        await delegate_admin(TARGET_USER_ID, request, current_user, db)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_delegate_admin_user_admin_forbids_resource_id():
    current_user = _make_user()
    db = AsyncMock()
    db.commit = AsyncMock()

    request = DelegateAdminRequest(
        delegated_scope="user_admin",
        resource_id=str(uuid.uuid4()),
    )
    with pytest.raises(HTTPException) as exc_info:
        await delegate_admin(TARGET_USER_ID, request, current_user, db)

    assert exc_info.value.status_code == 422
    assert "null" in exc_info.value.detail


@pytest.mark.asyncio
async def test_delegate_admin_user_not_found_raises_404():
    current_user = _make_user()
    # First execute (user existence check) returns None
    db = AsyncMock()
    user_check_result = MagicMock()
    user_check_result.fetchone.return_value = None
    db.execute = AsyncMock(return_value=user_check_result)
    db.commit = AsyncMock()

    request = DelegateAdminRequest(
        delegated_scope="kb_admin",
        resource_id=KB_ID,
    )
    with pytest.raises(HTTPException) as exc_info:
        await delegate_admin(TARGET_USER_ID, request, current_user, db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delegate_admin_creates_delegation_and_logs_audit():
    current_user = _make_user()
    new_delegation_id = str(uuid.uuid4())

    with (
        patch(
            "app.modules.admin.role_delegation.create_delegation_db",
            new_callable=AsyncMock,
            return_value={
                "id": new_delegation_id,
                "user_id": TARGET_USER_ID,
                "delegated_scope": "kb_admin",
                "resource_id": KB_ID,
                "granted_by": ACTOR_ID,
                "expires_at": None,
            },
        ),
        patch(
            "app.modules.admin.role_delegation.log_delegation_audit",
            new_callable=AsyncMock,
        ) as audit_mock,
    ):
        # DB: user existence check returns row; subsequent fetches work
        db = AsyncMock()
        user_result = MagicMock()
        user_result.fetchone.return_value = (TARGET_USER_ID,)
        created_at_result = MagicMock()
        now = datetime(2026, 3, 17, tzinfo=timezone.utc)
        created_at_result.fetchone.return_value = (now,)
        db.execute = AsyncMock(side_effect=[user_result, created_at_result])
        db.commit = AsyncMock()

        request = DelegateAdminRequest(
            delegated_scope="kb_admin",
            resource_id=KB_ID,
        )
        result = await delegate_admin(TARGET_USER_ID, request, current_user, db)

    assert result.id == new_delegation_id
    assert result.delegated_scope == "kb_admin"
    audit_mock.assert_called_once()
    call_kwargs = audit_mock.call_args.kwargs
    assert call_kwargs["action"] == "delegation.granted"


# ---------------------------------------------------------------------------
# revoke_delegation route handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_delegation_not_found_raises_404():
    current_user = _make_user()
    db = AsyncMock()
    not_found_result = MagicMock()
    not_found_result.fetchone.return_value = None
    db.execute = AsyncMock(return_value=not_found_result)
    db.commit = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await revoke_delegation(TARGET_USER_ID, DELEGATION_ID, current_user, db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_revoke_delegation_logs_audit():
    current_user = _make_user()

    with (
        patch(
            "app.modules.admin.role_delegation.delete_delegation_db",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.modules.admin.role_delegation.log_delegation_audit",
            new_callable=AsyncMock,
        ) as audit_mock,
    ):
        db = AsyncMock()
        detail_result = MagicMock()
        detail_result.fetchone.return_value = ("kb_admin", KB_ID)
        db.execute = AsyncMock(return_value=detail_result)
        db.commit = AsyncMock()

        await revoke_delegation(TARGET_USER_ID, DELEGATION_ID, current_user, db)

    audit_mock.assert_called_once()
    call_kwargs = audit_mock.call_args.kwargs
    assert call_kwargs["action"] == "delegation.revoked"


@pytest.mark.asyncio
async def test_revoke_delegation_invalid_delegation_id_uuid():
    current_user = _make_user()
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await revoke_delegation(TARGET_USER_ID, "not-a-uuid", current_user, db)

    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# list_user_delegations route handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_user_delegations_returns_empty_list():
    current_user = _make_user()

    with patch(
        "app.modules.admin.role_delegation.list_delegations_db",
        new_callable=AsyncMock,
        return_value=[],
    ):
        db = AsyncMock()
        result = await list_user_delegations(TARGET_USER_ID, current_user, db)

    assert isinstance(result, DelegationListResponse)
    assert result.delegations == []


@pytest.mark.asyncio
async def test_list_user_delegations_returns_items():
    current_user = _make_user()

    delegations_data = [
        {
            "id": DELEGATION_ID,
            "user_id": TARGET_USER_ID,
            "delegated_scope": "kb_admin",
            "resource_id": KB_ID,
            "granted_by": ACTOR_ID,
            "expires_at": None,
            "created_at": "2026-03-17T00:00:00+00:00",
        }
    ]

    with patch(
        "app.modules.admin.role_delegation.list_delegations_db",
        new_callable=AsyncMock,
        return_value=delegations_data,
    ):
        db = AsyncMock()
        result = await list_user_delegations(TARGET_USER_ID, current_user, db)

    assert len(result.delegations) == 1
    assert result.delegations[0].delegated_scope == "kb_admin"


# ---------------------------------------------------------------------------
# require_kb_admin / require_agent_admin middleware dependencies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_kb_admin_allows_tenant_admin():
    from app.core.dependencies import _check_kb_admin_access

    user = _make_user(roles=["tenant_admin"])
    db = AsyncMock()

    result = await _check_kb_admin_access(KB_ID, user, db)
    assert result is user
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_require_kb_admin_allows_delegation_bearer():
    from app.core.dependencies import _check_kb_admin_access

    user = _make_user(roles=["viewer"])
    db = AsyncMock()
    found_result = MagicMock()
    found_result.fetchone.return_value = (1,)
    db.execute = AsyncMock(return_value=found_result)

    result = await _check_kb_admin_access(KB_ID, user, db)
    assert result is user


@pytest.mark.asyncio
async def test_require_kb_admin_blocks_viewer_without_delegation():
    from app.core.dependencies import _check_kb_admin_access

    user = _make_user(roles=["viewer"])
    db = AsyncMock()
    not_found = MagicMock()
    not_found.fetchone.return_value = None
    db.execute = AsyncMock(return_value=not_found)

    with pytest.raises(HTTPException) as exc_info:
        await _check_kb_admin_access(KB_ID, user, db)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_agent_admin_allows_tenant_admin():
    from app.core.dependencies import _check_agent_admin_access

    user = _make_user(roles=["tenant_admin"])
    db = AsyncMock()

    result = await _check_agent_admin_access(AGENT_ID, user, db)
    assert result is user
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_require_agent_admin_blocks_viewer_without_delegation():
    from app.core.dependencies import _check_agent_admin_access

    user = _make_user(roles=["viewer"])
    db = AsyncMock()
    not_found = MagicMock()
    not_found.fetchone.return_value = None
    db.execute = AsyncMock(return_value=not_found)

    with pytest.raises(HTTPException) as exc_info:
        await _check_agent_admin_access(AGENT_ID, user, db)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_tenant_admin_blocks_viewer():
    from app.core.dependencies import require_tenant_admin

    viewer = _make_user(roles=["viewer"])
    with pytest.raises(HTTPException) as exc_info:
        await require_tenant_admin(viewer)

    assert exc_info.value.status_code == 403
    # Must not disclose scope/roles details
    assert "viewer" not in exc_info.value.detail.lower()
    assert "scope" not in exc_info.value.detail.lower()
