"""
Bulk user operations API (TA-032).

Endpoint:
- POST /admin/users/bulk-action

Supported actions: suspend, role_change, kb_assignment

All user_ids are processed in a single transaction with per-user
succeeded/failed breakdown returned to caller.
"""
import json
import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/admin/users", tags=["admin-users"])

_VALID_ACTIONS = frozenset({"suspend", "role_change", "kb_assignment"})
_VALID_BULK_ROLES = frozenset({"viewer", "tenant_admin"})
_VALID_KB_SCOPES = frozenset(
    {"workspace_wide", "role_restricted", "user_specific", "agent_only"}
)
_MAX_USER_IDS = 100


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class BulkActionPayload(BaseModel):
    role: Optional[str] = Field(None, description="Required for role_change action")
    kb_id: Optional[str] = Field(None, description="Required for kb_assignment action")
    scope: Optional[str] = Field(
        "workspace_wide", description="KB visibility scope for kb_assignment"
    )

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_BULK_ROLES:
            raise ValueError(
                f"role must be one of: {', '.join(sorted(_VALID_BULK_ROLES))}"
            )
        return v

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_KB_SCOPES:
            raise ValueError(
                f"scope must be one of: {', '.join(sorted(_VALID_KB_SCOPES))}"
            )
        return v


class BulkActionRequest(BaseModel):
    user_ids: list[str] = Field(..., description="List of user UUIDs to act on")
    action: str = Field(..., description="suspend | role_change | kb_assignment")
    payload: Optional[BulkActionPayload] = None

    @field_validator("user_ids")
    @classmethod
    def validate_user_ids(cls, v: list[str]) -> list[str]:
        if len(v) == 0:
            raise ValueError("user_ids must not be empty")
        if len(v) > _MAX_USER_IDS:
            raise ValueError(f"user_ids may not exceed {_MAX_USER_IDS} entries")
        for uid in v:
            try:
                uuid.UUID(uid)
            except ValueError:
                raise ValueError(f"Invalid UUID in user_ids: {uid!r}")
        return v

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in _VALID_ACTIONS:
            raise ValueError(
                f"action must be one of: {', '.join(sorted(_VALID_ACTIONS))}"
            )
        return v


class FailedUser(BaseModel):
    user_id: str
    reason: str


class BulkActionResponse(BaseModel):
    succeeded: list[str]
    failed: list[FailedUser]


# ---------------------------------------------------------------------------
# DB helpers (mockable in unit tests)
# ---------------------------------------------------------------------------


async def bulk_suspend_db(
    user_ids: list[str],
    tenant_id: str,
    acting_user_id: str,
    db,
) -> tuple[list[str], list[FailedUser]]:
    """
    Suspend a list of users belonging to this tenant.

    Returns (succeeded_ids, failed_items).
    Uses ANY(:ids) for the in-tenant check, then updates row-by-row to
    produce per-user results without leaking cross-tenant info.
    The acting user cannot suspend themselves (self-lockout prevention).
    """
    # Fetch which user_ids actually belong to this tenant
    exists_result = await db.execute(
        text(
            "SELECT id FROM users "
            "WHERE tenant_id = :tenant_id AND id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"tenant_id": tenant_id, "ids": user_ids},
    )
    found_ids = {str(row[0]) for row in exists_result.fetchall()}

    succeeded: list[str] = []
    failed: list[FailedUser] = []

    for uid in user_ids:
        if uid == acting_user_id:
            failed.append(
                FailedUser(user_id=uid, reason="cannot suspend your own account")
            )
            continue
        if uid not in found_ids:
            failed.append(FailedUser(user_id=uid, reason="user not found"))
            continue

        update_result = await db.execute(
            text(
                "UPDATE users SET status = 'suspended' "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {"id": uid, "tenant_id": tenant_id},
        )
        if (update_result.rowcount or 0) == 0:
            failed.append(FailedUser(user_id=uid, reason="update failed"))
        else:
            succeeded.append(uid)
            logger.info("user_suspended", user_id=uid, tenant_id=tenant_id)

    await db.commit()
    return succeeded, failed


async def bulk_role_change_db(
    user_ids: list[str],
    tenant_id: str,
    role: str,
    acting_user_id: str,
    db,
) -> tuple[list[str], list[FailedUser]]:
    """
    Change role for a list of users belonging to this tenant.

    Writes an audit_log entry per successfully changed user.
    The acting user cannot change their own role (self-lockout prevention).
    """
    # Fetch which user_ids belong to this tenant
    exists_result = await db.execute(
        text(
            "SELECT id FROM users "
            "WHERE tenant_id = :tenant_id AND id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"tenant_id": tenant_id, "ids": user_ids},
    )
    found_ids = {str(row[0]) for row in exists_result.fetchall()}

    succeeded: list[str] = []
    failed: list[FailedUser] = []

    for uid in user_ids:
        if uid == acting_user_id:
            failed.append(FailedUser(user_id=uid, reason="cannot change your own role"))
            continue
        if uid not in found_ids:
            failed.append(FailedUser(user_id=uid, reason="user not found"))
            continue

        update_result = await db.execute(
            text(
                "UPDATE users SET role = :role "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {"role": role, "id": uid, "tenant_id": tenant_id},
        )
        if (update_result.rowcount or 0) == 0:
            failed.append(FailedUser(user_id=uid, reason="update failed"))
            continue

        succeeded.append(uid)

        # Audit log entry per user
        await db.execute(
            text(
                "INSERT INTO audit_log (id, tenant_id, user_id, action, resource_type, resource_id, details) "
                "VALUES (:id, :tenant_id, :user_id, 'role_change', 'user', :resource_id, CAST(:details AS jsonb))"
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "user_id": acting_user_id,
                "resource_id": uid,
                "details": json.dumps({"new_role": role}),
            },
        )
        logger.info(
            "user_role_changed",
            user_id=uid,
            new_role=role,
            actor_id=acting_user_id,
            tenant_id=tenant_id,
        )

    await db.commit()
    return succeeded, failed


async def bulk_kb_assignment_db(
    user_ids: list[str],
    tenant_id: str,
    kb_id: str,
    scope: str,
    db,
) -> tuple[list[str], list[FailedUser]]:
    """
    Upsert kb_access_control allowed_user_ids for a list of users.

    Validates that each user_id belongs to this tenant, then adds them
    to the kb_access_control row (or creates it with user_specific visibility).
    No self-exclusion guard — assigning a KB to oneself is a valid operation.
    """
    # Validate kb_id is a valid UUID
    try:
        uuid.UUID(kb_id)
    except ValueError:
        # All fail — invalid kb_id
        return [], [
            FailedUser(user_id=uid, reason="invalid kb_id UUID") for uid in user_ids
        ]

    # Verify the KB belongs to this tenant
    kb_check = await db.execute(
        text(
            "SELECT index_id FROM kb_access_control "
            "WHERE index_id = CAST(:kb_id AS uuid) AND tenant_id = :tenant_id "
            "UNION ALL "
            "SELECT id FROM knowledge_bases "
            "WHERE id = CAST(:kb_id AS uuid) AND tenant_id = :tenant_id "
            "LIMIT 1"
        ),
        {"kb_id": kb_id, "tenant_id": tenant_id},
    )
    if kb_check.fetchone() is None:
        return [], [
            FailedUser(user_id=uid, reason="knowledge base not found")
            for uid in user_ids
        ]

    # Fetch which user_ids belong to this tenant
    exists_result = await db.execute(
        text(
            "SELECT id FROM users "
            "WHERE tenant_id = :tenant_id AND id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"tenant_id": tenant_id, "ids": user_ids},
    )
    found_ids = {str(row[0]) for row in exists_result.fetchall()}

    succeeded: list[str] = []
    failed: list[FailedUser] = []

    # Only process users that exist in this tenant
    valid_user_ids = [uid for uid in user_ids if uid in found_ids]
    for uid in user_ids:
        if uid not in found_ids:
            failed.append(FailedUser(user_id=uid, reason="user not found"))

    if not valid_user_ids:
        return succeeded, failed

    # Upsert kb_access_control — add new users to allowed_user_ids
    await db.execute(
        text(
            "INSERT INTO kb_access_control "
            "  (tenant_id, index_id, visibility_mode, allowed_roles, allowed_user_ids) "
            "VALUES (:tenant_id, :index_id, :mode, ARRAY[]::text[], CAST(:user_ids AS uuid[])) "
            "ON CONFLICT (tenant_id, index_id) DO UPDATE SET "
            "  visibility_mode   = :mode, "
            "  allowed_user_ids  = ARRAY(SELECT DISTINCT unnest("
            "      kb_access_control.allowed_user_ids || CAST(:user_ids AS uuid[]))), "
            "  updated_at        = NOW()"
        ),
        {
            "tenant_id": tenant_id,
            "index_id": kb_id,
            "mode": scope,
            "user_ids": valid_user_ids,
        },
    )
    await db.commit()

    succeeded = valid_user_ids
    logger.info(
        "bulk_kb_assignment",
        tenant_id=tenant_id,
        kb_id=kb_id,
        user_count=len(succeeded),
    )
    return succeeded, failed


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


@router.post(
    "/bulk-action", response_model=BulkActionResponse, status_code=status.HTTP_200_OK
)
async def bulk_user_action(
    request: BulkActionRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> BulkActionResponse:
    """TA-032: Perform a bulk action on a list of users."""
    payload = request.payload or BulkActionPayload()

    if request.action == "suspend":
        succeeded, failed = await bulk_suspend_db(
            user_ids=request.user_ids,
            tenant_id=current_user.tenant_id,
            acting_user_id=current_user.id,
            db=db,
        )

    elif request.action == "role_change":
        if not payload.role:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="payload.role is required for role_change action",
            )
        succeeded, failed = await bulk_role_change_db(
            user_ids=request.user_ids,
            tenant_id=current_user.tenant_id,
            role=payload.role,
            acting_user_id=current_user.id,
            db=db,
        )

    elif request.action == "kb_assignment":
        if not payload.kb_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="payload.kb_id is required for kb_assignment action",
            )
        succeeded, failed = await bulk_kb_assignment_db(
            user_ids=request.user_ids,
            tenant_id=current_user.tenant_id,
            kb_id=payload.kb_id,
            scope=payload.scope or "workspace_wide",
            db=db,
        )

    else:
        # Should not reach here — Pydantic validator catches invalid actions
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown action: {request.action!r}",
        )

    logger.info(
        "bulk_user_action_completed",
        action=request.action,
        tenant_id=current_user.tenant_id,
        succeeded_count=len(succeeded),
        failed_count=len(failed),
    )

    return BulkActionResponse(succeeded=succeeded, failed=failed)
