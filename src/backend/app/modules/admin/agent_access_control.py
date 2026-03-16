"""
Agent access control API (TA-009).

Endpoints:
- GET  /admin/agents/{id}/access  -- get access config for a deployed agent
- PATCH /admin/agents/{id}/access -- upsert access config for a deployed agent

Uses agent_access_control table (migration v028).
Default (no row): workspace_wide — all tenant users can invoke.
Note: agent_only mode does NOT apply to agents (only to KBs).
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

router = APIRouter(prefix="/admin", tags=["admin-agent-access"])

_VALID_VISIBILITY_MODES = frozenset(
    {"workspace_wide", "role_restricted", "user_specific"}
)
_VALID_ROLES = frozenset({"viewer", "editor", "admin"})


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AgentAccessResponse(BaseModel):
    agent_id: str
    visibility_mode: str
    allowed_roles: list[str]
    allowed_user_ids: list[str]


class PatchAgentAccessRequest(BaseModel):
    visibility_mode: str = Field(
        ...,
        description="workspace_wide | role_restricted | user_specific",
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


async def get_agent_access_db(
    agent_id: str, tenant_id: str, db: AsyncSession
) -> Optional[dict]:
    """Return the agent_access_control row or None (workspace_wide default)."""
    result = await db.execute(
        text(
            "SELECT visibility_mode, allowed_roles, allowed_user_ids "
            "FROM agent_access_control "
            "WHERE tenant_id = :tenant_id AND agent_id = :agent_id"
        ),
        {"tenant_id": tenant_id, "agent_id": agent_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "visibility_mode": row[0],
        "allowed_roles": list(row[1] or []),
        "allowed_user_ids": [str(u) for u in (row[2] or [])],
    }


async def upsert_agent_access_db(
    agent_id: str,
    tenant_id: str,
    visibility_mode: str,
    allowed_roles: list[str],
    allowed_user_ids: list[str],
    db: AsyncSession,
) -> None:
    """INSERT or UPDATE agent_access_control row for an agent."""
    await db.execute(
        text(
            "INSERT INTO agent_access_control "
            "  (tenant_id, agent_id, visibility_mode, allowed_roles, allowed_user_ids) "
            "VALUES (:tenant_id, :agent_id, :mode, :roles, CAST(:user_ids AS uuid[])) "
            "ON CONFLICT (tenant_id, agent_id) DO UPDATE SET "
            "  visibility_mode    = EXCLUDED.visibility_mode, "
            "  allowed_roles      = EXCLUDED.allowed_roles, "
            "  allowed_user_ids   = EXCLUDED.allowed_user_ids"
        ),
        {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "mode": visibility_mode,
            "roles": allowed_roles,
            "user_ids": [str(u) for u in allowed_user_ids],
        },
    )
    await db.commit()


def check_agent_access(
    visibility_mode: str,
    allowed_roles: list[str],
    allowed_user_ids: list[str],
    user_id: str,
    user_roles: list[str],
) -> bool:
    """
    Return True if the user is allowed to invoke the agent.

    Called by the chat/agent invocation pipeline before processing.
    workspace_wide (default): always allowed.
    role_restricted: user must have at least one of the allowed roles.
    user_specific: user_id must be in allowed_user_ids.
    """
    if visibility_mode == "workspace_wide":
        return True
    if visibility_mode == "role_restricted":
        return bool(set(user_roles) & set(allowed_roles))
    if visibility_mode == "user_specific":
        return user_id in allowed_user_ids
    # Unknown mode — deny by default
    return False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}/access", response_model=AgentAccessResponse)
async def get_agent_access(
    agent_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> AgentAccessResponse:
    """Get access control config for an agent. Returns workspace_wide default if no row exists."""
    try:
        uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="agent_id must be a valid UUID")

    row = await get_agent_access_db(agent_id, current_user.tenant_id, db)
    if row is None:
        return AgentAccessResponse(
            agent_id=agent_id,
            visibility_mode="workspace_wide",
            allowed_roles=[],
            allowed_user_ids=[],
        )
    return AgentAccessResponse(
        agent_id=agent_id,
        visibility_mode=row["visibility_mode"],
        allowed_roles=row["allowed_roles"],
        allowed_user_ids=row["allowed_user_ids"],
    )


@router.patch("/agents/{agent_id}/access", response_model=AgentAccessResponse)
async def patch_agent_access(
    agent_id: str,
    body: PatchAgentAccessRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> AgentAccessResponse:
    """Upsert access control config for an agent. Requires tenant_admin."""
    try:
        uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="agent_id must be a valid UUID")

    # Verify agent exists in this tenant
    result = await db.execute(
        text(
            "SELECT id FROM agent_cards "
            "WHERE id = :agent_id AND tenant_id = :tenant_id"
        ),
        {"agent_id": agent_id, "tenant_id": current_user.tenant_id},
    )
    if result.fetchone() is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    if body.visibility_mode == "role_restricted" and not body.allowed_roles:
        raise HTTPException(
            status_code=422,
            detail="allowed_roles is required for role_restricted visibility",
        )

    if body.visibility_mode == "user_specific" and not body.allowed_user_ids:
        raise HTTPException(
            status_code=422,
            detail="allowed_user_ids is required for user_specific visibility",
        )

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

    await upsert_agent_access_db(
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        visibility_mode=body.visibility_mode,
        allowed_roles=body.allowed_roles or [],
        allowed_user_ids=body.allowed_user_ids or [],
        db=db,
    )

    logger.info(
        "agent_access_updated",
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        visibility_mode=body.visibility_mode,
    )

    return AgentAccessResponse(
        agent_id=agent_id,
        visibility_mode=body.visibility_mode,
        allowed_roles=body.allowed_roles or [],
        allowed_user_ids=body.allowed_user_ids or [],
    )
