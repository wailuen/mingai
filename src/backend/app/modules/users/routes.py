"""
Users API routes (API-041 to API-050).

Endpoints:
- GET    /users           — List users (tenant admin only, paginated)
- POST   /users           — Invite user
- GET    /users/me        — Get current user profile
- PATCH  /users/me        — Update current user profile
- GET    /users/{id}      — Get user (tenant admin only)
- PATCH  /users/{id}      — Update user (tenant admin only)
- DELETE /users/{id}      — Deactivate user (tenant admin only)
- POST   /users/me/gdpr/export — Export user data
- POST   /users/me/gdpr/erase  — GDPR erase (clears all 3 stores)

Note: /me routes must be registered BEFORE /{id} routes to avoid path collision.
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/users", tags=["users"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class InviteUserRequest(BaseModel):
    email: EmailStr = Field(..., description="Valid RFC 5322 email address")
    role: str = Field(..., min_length=1, max_length=50)
    name: Optional[str] = Field(None, max_length=200)


class UpdateUserRequest(BaseModel):
    role: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, max_length=200)
    is_active: Optional[bool] = None


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    preferences: Optional[dict] = None


# ---------------------------------------------------------------------------
# DB helper functions (mockable in unit tests)
# ---------------------------------------------------------------------------


async def list_users_db(tenant_id: str, page: int, page_size: int, db) -> dict:
    """List users for a tenant, paginated."""
    offset = (page - 1) * page_size
    count_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM users WHERE tenant_id = :tenant_id AND status = 'active'"
        ),
        {"tenant_id": tenant_id},
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        text(
            "SELECT id, email, name, role, status, created_at FROM users "
            "WHERE tenant_id = :tenant_id AND status = 'active' "
            "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        ),
        {"tenant_id": tenant_id, "limit": page_size, "offset": offset},
    )
    rows = rows_result.fetchall()
    items = [
        {
            "id": str(r[0]),
            "email": r[1],
            "name": r[2],
            "role": r[3],
            "status": r[4],
            "created_at": str(r[5]),
        }
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def invite_user_db(
    tenant_id: str,
    email: str,
    role: str,
    name: Optional[str],
    db,
) -> dict:
    """Insert a new invited user record."""
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, tenant_id, email, name, role, status) "
            "VALUES (:id, :tenant_id, :email, :name, :role, 'invited')"
        ),
        {
            "id": user_id,
            "tenant_id": tenant_id,
            "email": email,
            "name": name,
            "role": role,
        },
    )
    await db.commit()
    logger.info("user_invited", user_id=user_id, email=email, tenant_id=tenant_id)
    return {"id": user_id, "email": email, "status": "invited", "role": role}


async def get_user_db(user_id: str, tenant_id: str, db) -> Optional[dict]:
    """Fetch a single user by ID within the tenant."""
    result = await db.execute(
        text(
            "SELECT id, email, name, role, status, created_at FROM users "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": user_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "email": row[1],
        "name": row[2],
        "role": row[3],
        "status": row[4],
        "created_at": str(row[5]),
    }


_USER_UPDATE_ALLOWLIST = {"role", "name", "is_active"}


async def update_user_db(
    user_id: str,
    tenant_id: str,
    updates: dict,
    db,
) -> Optional[dict]:
    """Update user fields with column allowlist enforcement."""
    invalid = set(updates) - _USER_UPDATE_ALLOWLIST
    if invalid:
        raise ValueError(f"Invalid user update fields: {invalid}")

    # Map is_active boolean to status column value
    db_updates = {}
    for k, v in updates.items():
        if k == "is_active":
            db_updates["status"] = "active" if v else "suspended"
        else:
            db_updates[k] = v

    set_clauses = ", ".join(f"{k} = :{k}" for k in db_updates)
    params = {"id": user_id, "tenant_id": tenant_id, **db_updates}
    result = await db.execute(
        text(
            f"UPDATE users SET {set_clauses} WHERE id = :id AND tenant_id = :tenant_id"
        ),
        params,
    )
    await db.commit()

    if (result.rowcount or 0) == 0:
        return None

    return await get_user_db(user_id, tenant_id, db)


async def deactivate_user_db(user_id: str, tenant_id: str, db) -> bool:
    """Soft-delete user by setting is_active=false."""
    result = await db.execute(
        text(
            "UPDATE users SET status = 'suspended' WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": user_id, "tenant_id": tenant_id},
    )
    await db.commit()
    return (result.rowcount or 0) > 0


async def get_user_profile_db(user_id: str, tenant_id: str, db) -> dict:
    """Get full user profile including preferences."""
    result = await db.execute(
        text(
            "SELECT u.id, u.email, u.name, u.role, u.status, "
            "up.technical_level, up.communication_style, up.interests "
            "FROM users u LEFT JOIN user_profiles up ON up.user_id = u.id "
            "WHERE u.id = :id AND u.tenant_id = :tenant_id"
        ),
        {"id": user_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return {"id": user_id, "tenant_id": tenant_id}
    return {
        "id": str(row[0]),
        "email": row[1],
        "name": row[2],
        "role": row[3],
        "status": row[4],
        "tenant_id": tenant_id,
        "technical_level": row[5],
        "communication_style": row[6],
        "interests": row[7] or [],
    }


async def update_user_profile_db(
    user_id: str, tenant_id: str, updates: dict, db
) -> dict:
    """Update user profile fields."""
    if "name" in updates and updates["name"] is not None:
        await db.execute(
            text(
                "UPDATE users SET name = :name "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {
                "name": updates["name"],
                "id": user_id,
                "tenant_id": tenant_id,
            },
        )
        await db.commit()
    return {"id": user_id, **updates}


async def export_user_data(user_id: str, tenant_id: str, db) -> dict:
    """Collect all user data for GDPR export."""
    user = await get_user_profile_db(user_id, tenant_id, db)

    conv_result = await db.execute(
        text(
            "SELECT id, title, created_at FROM conversations "
            "WHERE user_id = :user_id AND tenant_id = :tenant_id"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    conversations = [
        {"id": str(r[0]), "title": r[1], "created_at": str(r[2])}
        for r in conv_result.fetchall()
    ]

    notes_result = await db.execute(
        text(
            "SELECT id, content, created_at FROM memory_notes "
            "WHERE user_id = :user_id AND tenant_id = :tenant_id"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    notes = [
        {"id": str(r[0]), "content": r[1], "created_at": str(r[2])}
        for r in notes_result.fetchall()
    ]

    logger.info("gdpr_export", user_id=user_id, tenant_id=tenant_id)
    return {
        "user_id": user_id,
        "data": {
            "profile": user,
            "conversations": conversations,
            "memory_notes": notes,
        },
    }


async def erase_user_data(user_id: str, tenant_id: str, db) -> dict:
    """
    GDPR erase: clear all 3 stores.

    1. PostgreSQL: clear profile, notes, conversations
    2. Redis L2: clear profile cache
    3. Working memory: clear all agent working memory keys
    """
    from app.modules.profile.learning import ProfileLearningService

    profile_service = ProfileLearningService(db_session=db)

    # Clear PostgreSQL data
    await db.execute(
        text(
            "DELETE FROM memory_notes WHERE user_id = :user_id AND tenant_id = :tenant_id"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    await db.execute(
        text(
            "DELETE FROM user_profiles WHERE user_id = :user_id AND tenant_id = :tenant_id"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    await db.execute(
        text(
            "UPDATE conversations SET title = '[deleted]' "
            "WHERE user_id = :user_id AND tenant_id = :tenant_id"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    await db.execute(
        text(
            "DELETE FROM messages WHERE conversation_id IN ("
            "SELECT id FROM conversations "
            "WHERE user_id = :user_id AND tenant_id = :tenant_id)"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    await db.commit()

    # Clear L1 in-process cache
    await profile_service.clear_l1_cache(user_id)

    # Clear Redis L2 profile cache
    from app.core.redis_client import get_redis

    redis = get_redis()
    l2_key = f"mingai:{tenant_id}:profile_learning:profile:{user_id}"
    counter_key = f"mingai:{tenant_id}:profile_learning:query_count:{user_id}"
    await redis.delete(l2_key)
    await redis.delete(counter_key)

    # Clear working memory keys (scan pattern)
    wm_pattern = f"mingai:{tenant_id}:working_memory:{user_id}:*"
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=wm_pattern, count=100)
        if keys:
            await redis.delete(*keys)
        if cursor == 0:
            break

    logger.info("gdpr_erase_completed", user_id=user_id, tenant_id=tenant_id)
    return {
        "erased": True,
        "stores_cleared": ["postgresql", "redis_l2", "working_memory"],
    }


# ---------------------------------------------------------------------------
# Route handlers (note: /me routes BEFORE /{id} to avoid path collision)
# ---------------------------------------------------------------------------


@router.get("/me")
async def get_current_user_profile(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-046: Get current user's full profile."""
    result = await get_user_profile_db(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    return result


@router.patch("/me")
async def update_current_user_profile(
    request: UpdateProfileRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-047: Update current user's profile."""
    updates = request.model_dump(exclude_none=True)
    result = await update_user_profile_db(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        updates=updates,
        db=session,
    )
    return result


@router.post("/me/gdpr/export")
async def gdpr_export(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-048: Export all personal data for the current user (GDPR Article 20)."""
    result = await export_user_data(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    return result


@router.post("/me/gdpr/erase")
async def gdpr_erase(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-049: GDPR erase (Right to be Forgotten).

    Clears all 3 stores: PostgreSQL profile/notes/messages, Redis L2 cache,
    and working memory keys.
    """
    result = await erase_user_data(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    return result


@router.get("/")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-041: List all users in the tenant (tenant admin only)."""
    result = await list_users_db(
        tenant_id=current_user.tenant_id,
        page=page,
        page_size=page_size,
        db=session,
    )
    return result


@router.post("/", status_code=status.HTTP_201_CREATED)
async def invite_user(
    request: InviteUserRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-042: Invite a new user to the tenant."""
    # email is validated by Pydantic EmailStr before reaching this handler
    result = await invite_user_db(
        tenant_id=current_user.tenant_id,
        email=str(request.email).lower().strip(),
        role=request.role,
        name=request.name,
        db=session,
    )
    return result


@router.get("/{user_id}")
async def get_user(
    user_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-043: Get a user by ID (tenant admin only)."""
    result = await get_user_db(
        user_id=user_id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found",
        )
    return result


@router.patch("/{user_id}")
async def update_user(
    user_id: str,
    request: UpdateUserRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-044: Update user role or status (tenant admin only)."""
    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )
    result = await update_user_db(
        user_id=user_id,
        tenant_id=current_user.tenant_id,
        updates=updates,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found",
        )
    return result


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-045: Soft-deactivate a user (tenant admin only)."""
    deactivated = await deactivate_user_db(
        user_id=user_id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    if not deactivated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found",
        )
    return None
