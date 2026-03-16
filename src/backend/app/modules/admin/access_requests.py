"""
Access request workflow API (TA-010).

End users who hit a 403 on KB or agent access can request access.

Endpoints:
- POST /access-requests          -- end user submits access request
- GET  /admin/access-requests    -- tenant admin lists requests
- PATCH /admin/access-requests/{id} -- tenant admin approves/denies

On approval: user_id appended to allowed_user_ids in the relevant
kb_access_control or agent_access_control row (upsert).
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

# Two routers: one for end-user, one for tenant admin
router = APIRouter(tags=["access-requests"])
admin_router = APIRouter(prefix="/admin", tags=["admin-access-requests"])

_VALID_RESOURCE_TYPES = frozenset({"kb", "agent"})
_VALID_STATUSES = frozenset({"pending", "approved", "denied"})


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateAccessRequest(BaseModel):
    resource_type: str = Field(..., description="'kb' or 'agent'")
    resource_id: str = Field(..., description="UUID of the KB index or agent")
    justification: str = Field(..., min_length=1, max_length=1000)

    @field_validator("resource_type")
    @classmethod
    def validate_resource_type(cls, v: str) -> str:
        if v not in _VALID_RESOURCE_TYPES:
            raise ValueError(f"resource_type must be 'kb' or 'agent'")
        return v

    @field_validator("resource_id")
    @classmethod
    def validate_resource_id(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("resource_id must be a valid UUID")
        return v


class AccessRequestResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    resource_type: str
    resource_id: str
    justification: str
    status: str
    admin_note: Optional[str]
    created_at: str


class PatchAccessRequest(BaseModel):
    status: str = Field(..., description="'approved' or 'denied'")
    note: Optional[str] = Field(None, max_length=2000)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in {"approved", "denied"}:
            raise ValueError("status must be 'approved' or 'denied'")
        return v


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _insert_notification(
    db: AsyncSession,
    tenant_id: str,
    user_id: str,
    notif_type: str,
    title: str,
    body: str,
) -> None:
    """Insert an in-app notification. Errors are logged but not raised."""
    try:
        await db.execute(
            text(
                "INSERT INTO notifications "
                "(id, tenant_id, user_id, type, title, body, read) "
                "VALUES (:id, :tenant_id, :user_id, :type, :title, :body, false)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "user_id": user_id,
                "type": notif_type,
                "title": title,
                "body": body,
            },
        )
    except Exception as exc:
        logger.warning(
            "access_request_notification_failed",
            user_id=user_id,
            tenant_id=tenant_id,
            error=str(exc),
        )


async def _get_tenant_admins(tenant_id: str, db: AsyncSession) -> list[str]:
    """Return user IDs of all active tenant_admin users in the tenant."""
    result = await db.execute(
        text(
            "SELECT id FROM users "
            "WHERE tenant_id = :tenant_id AND role = 'tenant_admin' AND status = 'active'"
        ),
        {"tenant_id": tenant_id},
    )
    return [str(row[0]) for row in result.fetchall()]


async def _append_user_to_access_control(
    db: AsyncSession,
    tenant_id: str,
    resource_type: str,
    resource_id: str,
    user_id: str,
) -> None:
    """
    Add user_id to allowed_user_ids in the correct access control table.

    If no row exists, inserts user_specific row.
    If a row exists with user_specific mode, appends user_id (deduplicates).
    For workspace_wide: no change needed (user already has access).
    For role_restricted/agent_only: switches to user_specific with this user.
    """
    table = "kb_access_control" if resource_type == "kb" else "agent_access_control"
    id_col = "index_id" if resource_type == "kb" else "agent_id"

    await db.execute(
        text(
            f"INSERT INTO {table} "
            f"  (tenant_id, {id_col}, visibility_mode, allowed_roles, allowed_user_ids) "
            f"VALUES (:tenant_id, :resource_id, 'user_specific', '{{}}', ARRAY[:user_id]::uuid[]) "
            f"ON CONFLICT (tenant_id, {id_col}) DO UPDATE SET "
            f"  visibility_mode    = 'user_specific', "
            f"  allowed_user_ids   = ARRAY(SELECT DISTINCT unnest("
            f"    {table}.allowed_user_ids || ARRAY[:user_id]::uuid[]"
            f"  ))"
        ),
        {
            "tenant_id": tenant_id,
            "resource_id": resource_id,
            "user_id": uuid.UUID(user_id),
        },
    )


# ---------------------------------------------------------------------------
# End-user endpoint
# ---------------------------------------------------------------------------


@router.post("/access-requests", status_code=201, response_model=AccessRequestResponse)
async def create_access_request(
    body: CreateAccessRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> AccessRequestResponse:
    """
    Submit an access request for a KB or agent.

    Accessible to all authenticated tenant users (viewer+).
    A user can only have one pending request per resource.
    """
    request_id = str(uuid.uuid4())

    try:
        result = await db.execute(
            text(
                "INSERT INTO access_requests "
                "  (id, tenant_id, user_id, resource_type, resource_id, justification, status) "
                "VALUES (:id, :tenant_id, :user_id, :resource_type, :resource_id, :justification, 'pending') "
                "RETURNING id, tenant_id, user_id, resource_type, resource_id, "
                "  justification, status, admin_note, created_at"
            ),
            {
                "id": request_id,
                "tenant_id": current_user.tenant_id,
                "user_id": current_user.id,
                "resource_type": body.resource_type,
                "resource_id": body.resource_id,
                "justification": body.justification,
            },
        )
    except Exception as exc:
        err_str = str(exc)
        if "unique" in err_str.lower() or "duplicate" in err_str.lower():
            raise HTTPException(
                status_code=409,
                detail="A pending access request for this resource already exists",
            )
        raise

    row = result.fetchone()
    await db.commit()

    # Notify all tenant admins
    admin_ids = await _get_tenant_admins(current_user.tenant_id, db)
    for admin_id in admin_ids:
        await _insert_notification(
            db=db,
            tenant_id=current_user.tenant_id,
            user_id=admin_id,
            notif_type="access_request",
            title="New access request",
            body=f"User {current_user.email or current_user.id} requested access to "
            f"{body.resource_type} {body.resource_id}",
        )
    if admin_ids:
        await db.commit()

    return AccessRequestResponse(
        id=str(row[0]),
        tenant_id=str(row[1]),
        user_id=str(row[2]),
        resource_type=row[3],
        resource_id=str(row[4]),
        justification=row[5],
        status=row[6],
        admin_note=row[7],
        created_at=row[8].isoformat(),
    )


# ---------------------------------------------------------------------------
# Tenant admin endpoints
# ---------------------------------------------------------------------------


@admin_router.get("/access-requests")
async def list_access_requests(
    status: Optional[str] = Query(None, description="pending|approved|denied"),
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """List access requests for the tenant, optionally filtered by status."""
    if status and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {sorted(_VALID_STATUSES)}",
        )

    conditions = ["ar.tenant_id = :tenant_id"]
    params: dict = {"tenant_id": current_user.tenant_id}

    if status:
        conditions.append("ar.status = :status")
        params["status"] = status

    where = " AND ".join(conditions)
    result = await db.execute(
        text(
            "SELECT ar.id, ar.tenant_id, ar.user_id, ar.resource_type, ar.resource_id, "
            "  ar.justification, ar.status, ar.admin_note, ar.created_at, "
            "  u.email AS requester_email "
            "FROM access_requests ar "
            "LEFT JOIN users u ON u.id = ar.user_id "
            f"WHERE {where} "
            "ORDER BY ar.created_at DESC"
        ),
        params,
    )
    rows = result.fetchall()
    items = [
        {
            "id": str(r[0]),
            "tenant_id": str(r[1]),
            "user_id": str(r[2]),
            "resource_type": r[3],
            "resource_id": str(r[4]),
            "justification": r[5],
            "status": r[6],
            "admin_note": r[7],
            "created_at": r[8].isoformat() if r[8] else None,
            "requester_email": r[9],
        }
        for r in rows
    ]
    return {"items": items, "total": len(items)}


@admin_router.patch("/access-requests/{request_id}")
async def decide_access_request(
    request_id: str,
    body: PatchAccessRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """
    Approve or deny an access request.

    On approval: user_id is added to allowed_user_ids in the relevant
    access control table.

    On denial: only the status and admin_note are updated.
    """
    try:
        uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="request_id must be a valid UUID")

    # Fetch the request (RLS ensures tenant isolation)
    result = await db.execute(
        text(
            "SELECT id, tenant_id, user_id, resource_type, resource_id, status "
            "FROM access_requests "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": request_id, "tenant_id": current_user.tenant_id},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Access request not found")

    req_id, tenant_id, user_id, resource_type, resource_id, current_status = (
        str(row[0]),
        str(row[1]),
        str(row[2]),
        row[3],
        str(row[4]),
        row[5],
    )

    if current_status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Access request has already been {current_status}",
        )

    # Update the request record
    await db.execute(
        text(
            "UPDATE access_requests "
            "SET status = :status, admin_note = :note "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {
            "status": body.status,
            "note": body.note,
            "id": request_id,
            "tenant_id": current_user.tenant_id,
        },
    )

    if body.status == "approved":
        await _append_user_to_access_control(
            db=db,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
        )

    await db.commit()

    # Notify the requesting user
    action_label = "approved" if body.status == "approved" else "denied"
    note_suffix = f" Note: {body.note}" if body.note else ""
    await _insert_notification(
        db=db,
        tenant_id=tenant_id,
        user_id=user_id,
        notif_type="access_request_decision",
        title=f"Access request {action_label}",
        body=f"Your request for {resource_type} access was {action_label}.{note_suffix}",
    )
    await db.commit()

    logger.info(
        "access_request_decided",
        request_id=request_id,
        status=body.status,
        admin_id=current_user.id,
        tenant_id=tenant_id,
    )

    return {
        "id": req_id,
        "status": body.status,
        "admin_note": body.note,
    }
