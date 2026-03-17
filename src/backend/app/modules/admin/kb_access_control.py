"""
KB access control API (TA-007).

Endpoints:
- GET  /admin/knowledge-base/{id}/access  -- get access config for a KB index
- PATCH /admin/knowledge-base/{id}/access -- upsert access config for a KB index

Uses kb_access_control table (migration v027).
Default (no row): workspace_wide — all tenant users can search.
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin-kb-access"])

_VALID_VISIBILITY_MODES = frozenset(
    {"workspace_wide", "role_restricted", "user_specific", "agent_only"}
)
_VALID_ROLES = frozenset({"viewer", "editor", "admin"})


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class KBAccessResponse(BaseModel):
    index_id: str
    visibility_mode: str
    allowed_roles: list[str]
    allowed_user_ids: list[str]


class PatchKBAccessRequest(BaseModel):
    visibility_mode: str = Field(
        ...,
        description="workspace_wide | role_restricted | user_specific | agent_only",
    )
    allowed_roles: Optional[list[str]] = Field(default_factory=list)
    allowed_user_ids: Optional[list[str]] = Field(default_factory=list)

    @field_validator("visibility_mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in _VALID_VISIBILITY_MODES:
            raise ValueError(
                f"visibility_mode must be one of: {sorted(_VALID_VISIBILITY_MODES)}"
            )
        return v

    @field_validator("allowed_roles")
    @classmethod
    def validate_roles(cls, v: Optional[list[str]]) -> list[str]:
        if not v:
            return []
        invalid = [r for r in v if r not in _VALID_ROLES]
        if invalid:
            raise ValueError(
                f"Invalid roles: {invalid}. Must be from: {sorted(_VALID_ROLES)}"
            )
        return v

    @field_validator("allowed_user_ids")
    @classmethod
    def validate_user_ids(cls, v: Optional[list[str]]) -> list[str]:
        if not v:
            return []
        for uid in v:
            try:
                uuid.UUID(uid)
            except ValueError:
                raise ValueError(f"Invalid UUID in allowed_user_ids: {uid!r}")
        return v


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def verify_kb_belongs_to_tenant(
    index_id: str, tenant_id: str, db: AsyncSession
) -> bool:
    """
    Return True if the KB index is accessible by the tenant.

    Gold Standard #13: verify via UNION ALL on integrations.config->>'kb_id'
    AND kb_access_control.index_id — no knowledge_bases table exists.
    """
    result = await db.execute(
        text(
            "SELECT 1 FROM ("
            "  SELECT config->>'kb_id' AS idx "
            "  FROM integrations "
            "  WHERE tenant_id = :tenant_id AND config->>'kb_id' = :index_id "
            "  UNION ALL "
            "  SELECT index_id "
            "  FROM kb_access_control "
            "  WHERE tenant_id = :tenant_id AND index_id = :index_id "
            ") sub LIMIT 1"
        ),
        {"tenant_id": tenant_id, "index_id": index_id},
    )
    return result.fetchone() is not None


async def get_kb_access_db(
    index_id: str, tenant_id: str, db: AsyncSession
) -> Optional[dict]:
    """Return the kb_access_control row or None (workspace_wide default)."""
    result = await db.execute(
        text(
            "SELECT visibility_mode, allowed_roles, allowed_user_ids "
            "FROM kb_access_control "
            "WHERE tenant_id = :tenant_id AND index_id = :index_id"
        ),
        {"tenant_id": tenant_id, "index_id": index_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "visibility_mode": row[0],
        "allowed_roles": list(row[1] or []),
        "allowed_user_ids": [str(u) for u in (row[2] or [])],
    }


async def upsert_kb_access_db(
    index_id: str,
    tenant_id: str,
    visibility_mode: str,
    allowed_roles: list[str],
    allowed_user_ids: list[str],
    db: AsyncSession,
) -> None:
    """INSERT or UPDATE kb_access_control row for a KB index."""
    await db.execute(
        text(
            "INSERT INTO kb_access_control "
            "  (tenant_id, index_id, visibility_mode, allowed_roles, allowed_user_ids) "
            "VALUES (:tenant_id, :index_id, :mode, :roles, CAST(:user_ids AS uuid[])) "
            "ON CONFLICT (tenant_id, index_id) DO UPDATE SET "
            "  visibility_mode    = EXCLUDED.visibility_mode, "
            "  allowed_roles      = EXCLUDED.allowed_roles, "
            "  allowed_user_ids   = EXCLUDED.allowed_user_ids, "
            "  updated_at         = NOW()"
        ),
        {
            "tenant_id": tenant_id,
            "index_id": index_id,
            "mode": visibility_mode,
            "roles": allowed_roles,
            "user_ids": [str(u) for u in allowed_user_ids],
        },
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# Canonical path: /access-control (with hyphen) — matches frontend hook convention.
# /access (without hyphen) is retained as an alias for backward compatibility.
@router.get(
    "/knowledge-base/{index_id}/access-control", response_model=KBAccessResponse
)
@router.get(
    "/knowledge-base/{index_id}/access",
    response_model=KBAccessResponse,
    include_in_schema=False,
)
async def get_kb_access(
    index_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> KBAccessResponse:
    """
    Get access control config for a KB index.

    Canonical path: /admin/knowledge-base/{index_id}/access-control
    Alias (backward-compat): /admin/knowledge-base/{index_id}/access

    Returns 404 if the KB does not belong to the calling tenant.
    Returns workspace_wide default if no access-control row exists yet.
    """
    # Validate UUID format
    try:
        uuid.UUID(index_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="index_id must be a valid UUID")

    # Return 404 (not 403) for KB indices that don't belong to this tenant.
    owned = await verify_kb_belongs_to_tenant(index_id, current_user.tenant_id, db)
    if not owned:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    row = await get_kb_access_db(index_id, current_user.tenant_id, db)
    if row is None:
        # Default: workspace_wide
        return KBAccessResponse(
            index_id=index_id,
            visibility_mode="workspace_wide",
            allowed_roles=[],
            allowed_user_ids=[],
        )
    return KBAccessResponse(
        index_id=index_id,
        visibility_mode=row["visibility_mode"],
        allowed_roles=row["allowed_roles"],
        allowed_user_ids=row["allowed_user_ids"],
    )


@router.patch(
    "/knowledge-base/{index_id}/access-control", response_model=KBAccessResponse
)
@router.patch(
    "/knowledge-base/{index_id}/access",
    response_model=KBAccessResponse,
    include_in_schema=False,
)
async def patch_kb_access(
    index_id: str,
    body: PatchKBAccessRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> KBAccessResponse:
    """
    Upsert access control config for a KB index.

    Canonical path: /admin/knowledge-base/{index_id}/access-control
    Alias (backward-compat): /admin/knowledge-base/{index_id}/access

    Returns 404 if the KB does not belong to the calling tenant.
    """
    try:
        uuid.UUID(index_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="index_id must be a valid UUID")

    # Return 404 (not 403) for KB indices that don't belong to this tenant.
    owned = await verify_kb_belongs_to_tenant(index_id, current_user.tenant_id, db)
    if not owned:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    # For role_restricted: at least one role required
    if body.visibility_mode == "role_restricted" and not body.allowed_roles:
        raise HTTPException(
            status_code=422,
            detail="allowed_roles is required for role_restricted visibility",
        )

    # For user_specific: at least one user required
    if body.visibility_mode == "user_specific" and not body.allowed_user_ids:
        raise HTTPException(
            status_code=422,
            detail="allowed_user_ids is required for user_specific visibility",
        )

    # Validate user_ids belong to tenant
    if body.allowed_user_ids:
        result = await db.execute(
            text(
                "SELECT COUNT(*) FROM users "
                "WHERE id = ANY(CAST(:user_ids AS uuid[])) AND tenant_id = :tenant_id"
            ),
            {
                "user_ids": [str(u) for u in body.allowed_user_ids],
                "tenant_id": current_user.tenant_id,
            },
        )
        found_count = result.scalar() or 0
        if found_count != len(body.allowed_user_ids):
            raise HTTPException(
                status_code=422,
                detail="One or more allowed_user_ids are not valid users in this tenant",
            )

    await upsert_kb_access_db(
        index_id=index_id,
        tenant_id=current_user.tenant_id,
        visibility_mode=body.visibility_mode,
        allowed_roles=body.allowed_roles or [],
        allowed_user_ids=body.allowed_user_ids or [],
        db=db,
    )

    logger.info(
        "kb_access_updated",
        index_id=index_id,
        tenant_id=current_user.tenant_id,
        visibility_mode=body.visibility_mode,
    )

    return KBAccessResponse(
        index_id=index_id,
        visibility_mode=body.visibility_mode,
        allowed_roles=body.allowed_roles or [],
        allowed_user_ids=body.allowed_user_ids or [],
    )
