"""
Teams API routes (API-051 to API-060).

Endpoints:
- GET    /teams                   — List teams for the tenant
- POST   /teams                   — Create team (tenant admin only)
- GET    /teams/{id}              — Get team details
- PATCH  /teams/{id}              — Update team (tenant admin only)
- DELETE /teams/{id}              — Delete team (tenant admin only)
- POST   /teams/{id}/members      — Add member (tenant admin only)
- DELETE /teams/{id}/members/{uid} — Remove member (tenant admin only)
- GET    /teams/{id}/memory       — Get team working memory

Note: /teams/{id}/memory and /teams/{id}/members routes must be
registered BEFORE /{id} routes to avoid path collision.
"""
import re
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/teams", tags=["teams"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateTeamRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)


class UpdateTeamRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)


class AddMemberRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=200)


class BulkAddMembersRequest(BaseModel):
    user_ids: list[str] = Field(..., min_length=1)


class MemoryConfigUpdateRequest(BaseModel):
    enabled: bool
    ttl_days: int = Field(..., ge=1, le=365)


# ---------------------------------------------------------------------------
# DB / service helper functions (mockable in unit tests)
# ---------------------------------------------------------------------------


_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _is_valid_uuid(value: str) -> bool:
    """Return True if value is a standard lowercase UUID."""
    return bool(_UUID_RE.match(value))


async def list_teams_db(tenant_id: str, db) -> list:
    """List all teams for the tenant.

    Returns an empty list for non-UUID tenant identifiers (e.g. the platform
    admin sentinel value "default") rather than propagating an asyncpg type
    error, since platform admins do not belong to a real tenant.
    """
    if not _is_valid_uuid(tenant_id):
        return []
    result = await db.execute(
        text(
            "SELECT t.id, t.name, t.description, COUNT(m.user_id) as member_count, t.created_at "
            "FROM tenant_teams t "
            "LEFT JOIN team_memberships m ON m.team_id = t.id "
            "WHERE t.tenant_id = :tenant_id "
            "GROUP BY t.id, t.name, t.description, t.created_at "
            "ORDER BY t.name ASC"
        ),
        {"tenant_id": tenant_id},
    )
    return [
        {
            "id": str(r[0]),
            "name": r[1],
            "description": r[2],
            "member_count": r[3],
            "created_at": str(r[4]),
        }
        for r in result.fetchall()
    ]


async def create_team_db(
    tenant_id: str, name: str, description: Optional[str], db
) -> dict:
    """Create a new team."""
    team_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO tenant_teams (id, tenant_id, name, description) "
            "VALUES (:id, :tenant_id, :name, :description)"
        ),
        {
            "id": team_id,
            "tenant_id": tenant_id,
            "name": name,
            "description": description,
        },
    )
    await db.commit()
    logger.info("team_created", team_id=team_id, name=name, tenant_id=tenant_id)
    return {
        "id": team_id,
        "name": name,
        "description": description,
        "tenant_id": tenant_id,
    }


async def get_team_db(team_id: str, tenant_id: str, db) -> Optional[dict]:
    """Get team details with member count."""
    result = await db.execute(
        text(
            "SELECT t.id, t.name, t.description, COUNT(m.user_id) as member_count, t.created_at "
            "FROM tenant_teams t "
            "LEFT JOIN team_memberships m ON m.team_id = t.id "
            "WHERE t.id = :id AND t.tenant_id = :tenant_id "
            "GROUP BY t.id, t.name, t.description, t.created_at"
        ),
        {"id": team_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "name": row[1],
        "description": row[2],
        "member_count": row[3],
        "created_at": str(row[4]),
    }


_TEAM_UPDATE_ALLOWLIST = {"name", "description"}


async def update_team_db(
    team_id: str, tenant_id: str, updates: dict, db
) -> Optional[dict]:
    """Update team fields."""
    invalid = set(updates) - _TEAM_UPDATE_ALLOWLIST
    if invalid:
        raise ValueError(f"Invalid team update fields: {invalid}")
    set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
    params = {"id": team_id, "tenant_id": tenant_id, **updates}
    result = await db.execute(
        text(
            f"UPDATE tenant_teams SET {set_clauses} WHERE id = :id AND tenant_id = :tenant_id"
        ),
        params,
    )
    await db.commit()
    if (result.rowcount or 0) == 0:
        return None
    return await get_team_db(team_id, tenant_id, db)


async def delete_team_db(team_id: str, tenant_id: str, db) -> bool:
    """Delete a team and its memberships."""
    await db.execute(
        text("DELETE FROM team_memberships WHERE team_id = :team_id"),
        {"team_id": team_id},
    )
    result = await db.execute(
        text("DELETE FROM tenant_teams WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": team_id, "tenant_id": tenant_id},
    )
    await db.commit()
    return (result.rowcount or 0) > 0


async def add_team_member_db(
    team_id: str,
    user_id: str,
    tenant_id: str,
    db,
    actor_id: str | None = None,
) -> dict:
    """Add a user to a team (scoped to caller's tenant)."""
    # Verify team belongs to caller's tenant before inserting membership
    team = await get_team_db(team_id, tenant_id, db)
    if team is None:
        return {}  # Route layer raises 404 on empty result

    result = await db.execute(
        text(
            "INSERT INTO team_memberships (team_id, user_id, tenant_id, source) "
            "VALUES (:team_id, :user_id, :tenant_id, 'manual') "
            "ON CONFLICT (team_id, user_id) DO NOTHING"
        ),
        {
            "team_id": team_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
        },
    )
    if (result.rowcount or 0) > 0:
        # Write audit log entry only when a row was actually inserted
        await db.execute(
            text(
                "INSERT INTO team_membership_audit "
                "(tenant_id, team_id, user_id, action, actor_id, source) "
                "VALUES (:tenant_id, :team_id, :user_id, 'added', :actor_id, 'manual')"
            ),
            {
                "tenant_id": tenant_id,
                "team_id": team_id,
                "user_id": user_id,
                "actor_id": actor_id,
            },
        )
    await db.commit()
    logger.info(
        "team_member_added", team_id=team_id, user_id=user_id
    )
    return {"team_id": team_id, "user_id": user_id}


async def remove_team_member_db(
    team_id: str,
    user_id: str,
    tenant_id: str,
    db,
    actor_id: str | None = None,
) -> bool:
    """Remove a user from a team (scoped to caller's tenant)."""
    result = await db.execute(
        text(
            "DELETE FROM team_memberships "
            "WHERE team_id = :team_id AND user_id = :user_id "
            "AND team_id IN ("
            "  SELECT id FROM tenant_teams WHERE id = :team_id AND tenant_id = :tenant_id"
            ")"
        ),
        {"team_id": team_id, "user_id": user_id, "tenant_id": tenant_id},
    )
    removed = (result.rowcount or 0) > 0
    if removed:
        await db.execute(
            text(
                "INSERT INTO team_membership_audit "
                "(tenant_id, team_id, user_id, action, actor_id, source) "
                "VALUES (:tenant_id, :team_id, :user_id, 'removed', :actor_id, 'manual')"
            ),
            {
                "tenant_id": tenant_id,
                "team_id": team_id,
                "user_id": user_id,
                "actor_id": actor_id,
            },
        )
        logger.info("team_member_removed", team_id=team_id, user_id=user_id)
    await db.commit()
    return removed


async def get_team_memory_data(team_id: str, tenant_id: str, db) -> dict:
    """Get team working memory from Redis."""
    from app.core.redis_client import get_redis
    import json

    redis = get_redis()
    key = f"mingai:{tenant_id}:working_memory:team:{team_id}"
    raw = await redis.get(key)
    if raw:
        data = json.loads(raw)
    else:
        data = {"topics": [], "queries": []}

    return {
        "team_id": team_id,
        "topics": data.get("topics", []),
        "recent_queries": data.get("queries", []),
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/")
async def list_teams(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-051: List all teams in the tenant."""
    result = await list_teams_db(
        tenant_id=current_user.tenant_id,
        db=session,
    )
    return result


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_team(
    request: CreateTeamRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-052: Create a new team (tenant admin only)."""
    result = await create_team_db(
        tenant_id=current_user.tenant_id,
        name=request.name,
        description=request.description,
        db=session,
    )
    return result


@router.get("/{team_id}/audit-log")
async def get_team_audit_log(
    team_id: str,
    page: int = 1,
    limit: int = 20,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """GET /teams/{id}/audit-log — Membership audit log for a team."""
    try:
        team_uuid = uuid.UUID(team_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid team ID")
    tenant_uuid = uuid.UUID(current_user.tenant_id)
    offset = (page - 1) * limit

    total_res = await session.execute(
        text(
            "SELECT COUNT(*) FROM team_membership_audit "
            "WHERE team_id = :team_id AND tenant_id = :tenant_id"
        ),
        {"team_id": team_uuid, "tenant_id": tenant_uuid},
    )
    total = total_res.scalar() or 0

    rows_res = await session.execute(
        text(
            "SELECT a.id, a.action, a.source, a.created_at, "
            "u.email AS member_email, u.name AS member_name, "
            "actor.email AS actor_email "
            "FROM team_membership_audit a "
            "JOIN users u ON u.id = a.user_id "
            "LEFT JOIN users actor ON actor.id = a.actor_id "
            "WHERE a.team_id = :team_id AND a.tenant_id = :tenant_id "
            "ORDER BY a.created_at DESC "
            "LIMIT :limit OFFSET :offset"
        ),
        {"team_id": team_uuid, "tenant_id": tenant_uuid, "limit": limit, "offset": offset},
    )
    rows = rows_res.fetchall()
    items = [
        {
            "id": str(r[0]),
            "action": r[1],
            "source": r[2],
            "created_at": r[3].isoformat() if r[3] else None,
            "member_email": r[4],
            "member_name": r[5],
            "actor_email": r[6],
        }
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": limit}


@router.get("/{team_id}/memory")
async def get_team_memory(
    team_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-060: Get team working memory."""
    result = await get_team_memory_data(
        team_id=team_id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    return result


@router.post("/{team_id}/members")
async def add_team_member(
    team_id: str,
    request: AddMemberRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-056: Add a user to a team (tenant admin only)."""
    result = await add_team_member_db(
        team_id=team_id,
        user_id=request.user_id,
        tenant_id=current_user.tenant_id,
        db=session,
        actor_id=current_user.id,
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team '{team_id}' not found",
        )
    return result


@router.post("/{team_id}/members/bulk")
async def bulk_add_team_members(
    team_id: str,
    request: BulkAddMembersRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Bulk add users to a team (tenant admin only)."""
    team = await get_team_db(team_id, current_user.tenant_id, session)
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team '{team_id}' not found",
        )
    added = 0
    for user_id in request.user_ids:
        result = await add_team_member_db(
            team_id=team_id,
            user_id=user_id,
            tenant_id=current_user.tenant_id,
            db=session,
            actor_id=current_user.id,
        )
        if result:
            added += 1
    return {"team_id": team_id, "added": added}


@router.get("/{team_id}/memory-config")
async def get_team_memory_config(
    team_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Get team memory configuration."""
    team = await get_team_db(team_id, current_user.tenant_id, session)
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team '{team_id}' not found",
        )
    return {"enabled": True, "ttl_days": 7, "entry_count": 0, "size_bytes": 0}


@router.patch("/{team_id}/memory-config")
async def update_team_memory_config(
    team_id: str,
    request: MemoryConfigUpdateRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Update team memory configuration."""
    team = await get_team_db(team_id, current_user.tenant_id, session)
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team '{team_id}' not found",
        )
    return {"enabled": request.enabled, "ttl_days": request.ttl_days, "entry_count": 0, "size_bytes": 0}


@router.delete("/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team_member(
    team_id: str,
    user_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-057: Remove a user from a team (tenant admin only)."""
    removed = await remove_team_member_db(
        team_id=team_id,
        user_id=user_id,
        tenant_id=current_user.tenant_id,
        db=session,
        actor_id=current_user.id,
    )
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found in team '{team_id}'",
        )
    return None


@router.get("/{team_id}")
async def get_team(
    team_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-053: Get team details."""
    result = await get_team_db(
        team_id=team_id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team '{team_id}' not found",
        )
    return result


@router.patch("/{team_id}")
async def update_team(
    team_id: str,
    request: UpdateTeamRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-054: Update team name or description (tenant admin only)."""
    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )
    result = await update_team_db(
        team_id=team_id,
        tenant_id=current_user.tenant_id,
        updates=updates,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team '{team_id}' not found",
        )
    return result


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-055: Delete a team and all memberships (tenant admin only)."""
    deleted = await delete_team_db(
        team_id=team_id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team '{team_id}' not found",
        )
    return None
