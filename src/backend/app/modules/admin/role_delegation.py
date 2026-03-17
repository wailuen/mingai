"""
Tenant admin role delegation API (TA-035).

Endpoints:
- POST   /admin/users/{user_id}/delegate-admin
- DELETE /admin/users/{user_id}/delegations/{delegation_id}
- GET    /admin/users/{user_id}/delegations

Delegations are stored in the user_delegations table (v038).
Each grant/revoke is written to audit_log.
require_tenant_admin is enforced on all endpoints.

Scoped admin middleware dependencies (require_kb_admin, require_agent_admin)
are defined in app.core.dependencies and imported from there.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(tags=["admin-role-delegation"])

_VALID_DELEGATED_SCOPES = frozenset({"kb_admin", "agent_admin", "user_admin"})
# Scopes that require a resource_id
_RESOURCE_REQUIRED_SCOPES = frozenset({"kb_admin", "agent_admin"})


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DelegateAdminRequest(BaseModel):
    delegated_scope: str = Field(..., description="kb_admin | agent_admin | user_admin")
    resource_id: Optional[str] = Field(
        None,
        description="Required for kb_admin/agent_admin; must be null for user_admin",
    )
    expires_at: Optional[str] = Field(
        None, description="ISO 8601 datetime (UTC) when the delegation expires, or null"
    )

    @field_validator("delegated_scope")
    @classmethod
    def validate_scope(cls, v: str) -> str:
        if v not in _VALID_DELEGATED_SCOPES:
            raise ValueError(
                f"delegated_scope must be one of: {', '.join(sorted(_VALID_DELEGATED_SCOPES))}"
            )
        return v

    @field_validator("resource_id")
    @classmethod
    def validate_resource_id_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                uuid.UUID(v)
            except ValueError:
                raise ValueError(f"resource_id must be a valid UUID, got: {v!r}")
        return v


class DelegationResponse(BaseModel):
    id: str
    user_id: str
    delegated_scope: str
    resource_id: Optional[str]
    granted_by: str
    expires_at: Optional[str]
    created_at: str


class DelegationListResponse(BaseModel):
    delegations: list[DelegationResponse]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def create_delegation_db(
    user_id: str,
    tenant_id: str,
    delegated_scope: str,
    resource_id: Optional[str],
    granted_by: str,
    expires_at: Optional[datetime],
    db: AsyncSession,
) -> dict:
    """Insert a new user_delegations row. Returns the created row as a dict."""
    new_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO user_delegations "
            "(id, tenant_id, user_id, delegated_scope, resource_id, granted_by, expires_at) "
            "VALUES (:id, :tenant_id, :user_id, :delegated_scope, "
            "CAST(:resource_id AS uuid), :granted_by, :expires_at)"
        ),
        {
            "id": new_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "delegated_scope": delegated_scope,
            "resource_id": resource_id,
            "granted_by": granted_by,
            "expires_at": expires_at,
        },
    )
    return {
        "id": new_id,
        "user_id": user_id,
        "delegated_scope": delegated_scope,
        "resource_id": resource_id,
        "granted_by": granted_by,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


async def delete_delegation_db(
    delegation_id: str,
    user_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> bool:
    """
    Delete a delegation by id scoped to user_id and tenant_id.

    Returns True if a row was deleted, False if not found (or not owned).
    """
    result = await db.execute(
        text(
            "DELETE FROM user_delegations "
            "WHERE id = :id AND user_id = :user_id AND tenant_id = :tenant_id"
        ),
        {"id": delegation_id, "user_id": user_id, "tenant_id": tenant_id},
    )
    return (result.rowcount or 0) > 0


async def list_delegations_db(
    user_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """Return all delegations for the given user within the tenant."""
    result = await db.execute(
        text(
            "SELECT id, user_id, delegated_scope, resource_id, granted_by, "
            "expires_at, created_at "
            "FROM user_delegations "
            "WHERE user_id = :user_id AND tenant_id = :tenant_id "
            "ORDER BY created_at DESC"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    rows = result.fetchall()
    return [
        {
            "id": str(row[0]),
            "user_id": str(row[1]),
            "delegated_scope": row[2],
            "resource_id": str(row[3]) if row[3] else None,
            "granted_by": str(row[4]),
            "expires_at": row[5].isoformat() if row[5] else None,
            "created_at": row[6].isoformat() if row[6] else None,
        }
        for row in rows
    ]


async def log_delegation_audit(
    actor_id: str,
    tenant_id: str,
    action: str,
    target_user_id: str,
    delegation_id: str,
    delegated_scope: str,
    resource_id: Optional[str],
    db: AsyncSession,
) -> None:
    """Write an audit_log entry for delegation.granted or delegation.revoked."""
    await db.execute(
        text(
            "INSERT INTO audit_log "
            "(id, tenant_id, user_id, action, resource_type, resource_id, details) "
            "VALUES (:id, :tenant_id, :user_id, :action, 'user_delegation', "
            ":resource_id, CAST(:details AS jsonb))"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "user_id": actor_id,
            "action": action,
            "resource_id": target_user_id,
            "details": json.dumps(
                {
                    "delegation_id": delegation_id,
                    "target_user_id": target_user_id,
                    "delegated_scope": delegated_scope,
                    "resource_id": resource_id,
                }
            ),
        },
    )


def _assert_user_exists_in_tenant(user_id: str) -> None:
    """Validate that user_id is a well-formed UUID (content validated by DB)."""
    try:
        uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"user_id is not a valid UUID: {user_id!r}",
        )


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post(
    "/admin/users/{user_id}/delegate-admin",
    response_model=DelegationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def delegate_admin(
    user_id: str,
    request: DelegateAdminRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> DelegationResponse:
    """
    TA-035: Grant a scoped admin delegation to a user.

    - kb_admin / agent_admin: resource_id is required (422 if missing)
    - user_admin: resource_id must be null (422 if provided)
    """
    _assert_user_exists_in_tenant(user_id)

    scope = request.delegated_scope

    # Validate resource_id requirements per scope
    if scope in _RESOURCE_REQUIRED_SCOPES and not request.resource_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"resource_id is required for {scope} delegations",
        )
    if scope == "user_admin" and request.resource_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="resource_id must be null for user_admin delegations",
        )

    # Parse expires_at if provided
    expires_dt: Optional[datetime] = None
    if request.expires_at:
        try:
            expires_dt = datetime.fromisoformat(request.expires_at)
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="expires_at must be a valid ISO 8601 datetime",
            )

    # Verify that the target user belongs to this tenant
    user_check = await db.execute(
        text(
            "SELECT id FROM users WHERE id = :user_id AND tenant_id = :tenant_id LIMIT 1"
        ),
        {"user_id": user_id, "tenant_id": current_user.tenant_id},
    )
    if user_check.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    row = await create_delegation_db(
        user_id=user_id,
        tenant_id=current_user.tenant_id,
        delegated_scope=scope,
        resource_id=request.resource_id,
        granted_by=current_user.id,
        expires_at=expires_dt,
        db=db,
    )

    await log_delegation_audit(
        actor_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="delegation.granted",
        target_user_id=user_id,
        delegation_id=row["id"],
        delegated_scope=scope,
        resource_id=request.resource_id,
        db=db,
    )

    await db.commit()

    logger.info(
        "delegation_granted",
        delegation_id=row["id"],
        target_user_id=user_id,
        scope=scope,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
    )

    # Fetch created_at from DB for accurate response
    created_result = await db.execute(
        text("SELECT created_at FROM user_delegations WHERE id = :id"),
        {"id": row["id"]},
    )
    created_row = created_result.fetchone()
    created_at_str = created_row[0].isoformat() if created_row else None

    return DelegationResponse(
        id=row["id"],
        user_id=row["user_id"],
        delegated_scope=row["delegated_scope"],
        resource_id=row["resource_id"],
        granted_by=row["granted_by"],
        expires_at=row["expires_at"],
        created_at=created_at_str or "",
    )


@router.delete(
    "/admin/users/{user_id}/delegations/{delegation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_delegation(
    user_id: str,
    delegation_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> None:
    """TA-035: Revoke a scoped admin delegation."""
    _assert_user_exists_in_tenant(user_id)

    try:
        uuid.UUID(delegation_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"delegation_id is not a valid UUID: {delegation_id!r}",
        )

    # Fetch delegation details before deletion (for audit log)
    detail_result = await db.execute(
        text(
            "SELECT delegated_scope, resource_id FROM user_delegations "
            "WHERE id = :id AND user_id = :user_id AND tenant_id = :tenant_id"
        ),
        {
            "id": delegation_id,
            "user_id": user_id,
            "tenant_id": current_user.tenant_id,
        },
    )
    detail_row = detail_result.fetchone()
    if detail_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delegation not found",
        )

    delegated_scope = detail_row[0]
    resource_id = str(detail_row[1]) if detail_row[1] else None

    deleted = await delete_delegation_db(
        delegation_id=delegation_id,
        user_id=user_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delegation not found",
        )

    await log_delegation_audit(
        actor_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="delegation.revoked",
        target_user_id=user_id,
        delegation_id=delegation_id,
        delegated_scope=delegated_scope,
        resource_id=resource_id,
        db=db,
    )

    await db.commit()

    logger.info(
        "delegation_revoked",
        delegation_id=delegation_id,
        target_user_id=user_id,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
    )


@router.get(
    "/admin/users/{user_id}/delegations",
    response_model=DelegationListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_user_delegations(
    user_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> DelegationListResponse:
    """TA-035: List active delegations for a user."""
    _assert_user_exists_in_tenant(user_id)

    delegations = await list_delegations_db(
        user_id=user_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )

    return DelegationListResponse(
        delegations=[DelegationResponse(**d) for d in delegations]
    )
