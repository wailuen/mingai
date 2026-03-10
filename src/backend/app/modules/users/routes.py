"""
Users API routes (API-041 to API-050), bulk invite (API-044), and GDPR data export (API-104).

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
- POST   /admin/users/bulk-invite — CSV bulk user invite (tenant admin)
- GET    /me/data-export  — GDPR profile data export (any authenticated user)

Note: /me routes must be registered BEFORE /{id} routes to avoid path collision.
"""
import csv
import io
import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/users", tags=["users"])

# Separate routers for /admin/users and /me prefixes
admin_users_router = APIRouter(prefix="/admin/users", tags=["admin-users"])
me_router = APIRouter(prefix="/me", tags=["me"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class InviteUserRequest(BaseModel):
    email: EmailStr = Field(..., description="Valid RFC 5322 email address")
    role: str = Field(..., min_length=1, max_length=50)
    name: Optional[str] = Field(None, max_length=200)

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        allowed = {"viewer", "tenant_admin"}
        if v not in allowed:
            raise ValueError(f"role must be one of: {', '.join(sorted(allowed))}")
        return v


class UpdateUserRequest(BaseModel):
    role: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, max_length=200)
    is_active: Optional[bool] = None

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {"viewer", "tenant_admin"}
        if v not in allowed:
            raise ValueError(f"role must be one of: {', '.join(sorted(allowed))}")
        return v


_PREFERENCES_MAX_BYTES = 65_536  # 64 KB serialized


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    preferences: Optional[dict] = None

    @field_validator("preferences")
    @classmethod
    def preferences_size_limit(cls, v: Optional[dict]) -> Optional[dict]:
        if v is not None and len(json.dumps(v)) > _PREFERENCES_MAX_BYTES:
            raise ValueError(
                f"preferences payload exceeds maximum of {_PREFERENCES_MAX_BYTES} bytes"
            )
        return v


class BulkInviteResult(BaseModel):
    total: int
    successful: int
    failed: int
    errors: list[dict]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_BULK_INVITE_ROLES = {"viewer", "tenant_admin"}
_EMAIL_PATTERN = re.compile(r"^[^@]+@[^@]+\.[^@]+$")
_MAX_BULK_INVITE_ROWS = 500
_MAX_CSV_BYTES = 2 * 1024 * 1024  # 2 MB upload limit


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
    email_domain = email.split("@")[-1] if "@" in email else "unknown"
    logger.info(
        "user_invited", user_id=user_id, email_domain=email_domain, tenant_id=tenant_id
    )
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

# Hardcoded SQL fragments — column names never interpolated from user-controlled data.
# Only these exact fragments can appear in SET clauses; values remain parameterized.
# NOTE: `is_active` is intentionally absent here — the loop below maps it to `status`.
# Any new field added to _USER_UPDATE_ALLOWLIST must have a corresponding entry here
# OR an explicit mapping in the is_active→status block (lines ~196-199).
_DB_COLUMN_SQL: dict[str, str] = {
    "role": "role = :role",
    "name": "name = :name",
    "status": "status = :status",
}


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

    # Column names sourced exclusively from _DB_COLUMN_SQL (static map).
    # Values remain parameterized (`:col`). No user-controlled strings reach SQL.
    set_clauses = ", ".join(
        _DB_COLUMN_SQL[k] for k in db_updates if k in _DB_COLUMN_SQL
    )
    if not set_clauses:
        raise ValueError("No valid update fields after allowlist filtering")
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
    """Update user profile fields (name on users table; preferences on user_profiles)."""
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

    if "preferences" in updates and updates["preferences"]:
        await db.execute(
            text(
                "INSERT INTO user_profiles (user_id, tenant_id, preferences) "
                "VALUES (:user_id, :tenant_id, :prefs::jsonb) "
                "ON CONFLICT (user_id, tenant_id) DO UPDATE "
                "SET preferences = COALESCE(user_profiles.preferences, '{}'::jsonb) || :prefs::jsonb"
            ),
            {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "prefs": json.dumps(updates["preferences"]),
            },
        )

    await db.commit()
    return {"id": user_id, **{k: v for k, v in updates.items() if v is not None}}


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
# Bulk invite DB helpers (API-044)
# ---------------------------------------------------------------------------


async def bulk_invite_check_quota(tenant_id: str, db) -> int:
    """Return the remaining user quota for the tenant (users_max - current count).

    Reads users_max from tenant_configs where config_type='limits'.
    If no limit is configured, returns 500 (default max).
    """
    # Get configured limit
    config_result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tenant_id AND config_type = 'limits'"
        ),
        {"tenant_id": tenant_id},
    )
    config_row = config_result.fetchone()
    users_max = 500  # default max
    if config_row and config_row[0]:
        config_data = config_row[0]
        if isinstance(config_data, dict) and "users_max" in config_data:
            users_max = config_data["users_max"]

    # Count existing users (active + invited)
    count_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM users "
            "WHERE tenant_id = :tenant_id AND status IN ('active', 'invited')"
        ),
        {"tenant_id": tenant_id},
    )
    current_count = count_result.scalar() or 0

    remaining = users_max - current_count
    return max(remaining, 0)


async def bulk_invite_check_existing(tenant_id: str, emails: list[str], db) -> set[str]:
    """Return set of emails that already exist in users or invitations for this tenant."""
    if not emails:
        return set()
    # Use parameterized IN clause via ANY
    result = await db.execute(
        text(
            "SELECT LOWER(email) FROM users "
            "WHERE tenant_id = :tenant_id AND LOWER(email) = ANY(:emails)"
        ),
        {"tenant_id": tenant_id, "emails": [e.lower() for e in emails]},
    )
    return {row[0] for row in result.fetchall()}


async def bulk_invite_insert_db(
    tenant_id: str,
    email: str,
    name: Optional[str],
    role: str,
    invited_by: str,
    db,
) -> int:
    """Insert a single invitation record. Returns 1 on success."""
    invitation_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, tenant_id, email, name, role, status) "
            "VALUES (:id, :tenant_id, :email, :name, :role, 'invited')"
        ),
        {
            "id": invitation_id,
            "tenant_id": tenant_id,
            "email": email.lower().strip(),
            "name": name,
            "role": role,
        },
    )
    await db.commit()
    email_domain = email.split("@")[-1] if "@" in email else "unknown"
    logger.info(
        "bulk_invite_user_created",
        invitation_id=invitation_id,
        email_domain=email_domain,
        tenant_id=tenant_id,
        invited_by=invited_by,
    )
    return 1


# ---------------------------------------------------------------------------
# GDPR data export helper (API-104)
# ---------------------------------------------------------------------------


async def export_user_data_db(user_id: str, tenant_id: str, db) -> dict:
    """Collect all user data for GDPR data export (API-104).

    Queries:
    - user_profiles table for profile data
    - memory_notes table for memory notes
    - working_memory_snapshots table for latest working memory snapshot
    - org_context: empty dict (per-session, not persisted)
    """
    # Profile
    profile_result = await db.execute(
        text(
            "SELECT u.id, u.email, u.name, u.role, u.status, "
            "up.technical_level, up.communication_style, up.interests "
            "FROM users u LEFT JOIN user_profiles up ON up.user_id = u.id "
            "WHERE u.id = :user_id AND u.tenant_id = :tenant_id"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    profile_row = profile_result.fetchone()
    if profile_row:
        profile = {
            "id": str(profile_row[0]),
            "email": profile_row[1],
            "name": profile_row[2],
            "role": profile_row[3],
            "status": profile_row[4],
            "technical_level": profile_row[5],
            "communication_style": profile_row[6],
            "interests": profile_row[7] or [],
        }
    else:
        profile = {"id": user_id}

    # Memory notes
    notes_result = await db.execute(
        text(
            "SELECT id, content, source, created_at FROM memory_notes "
            "WHERE user_id = :user_id AND tenant_id = :tenant_id "
            "ORDER BY created_at DESC"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    memory_notes = [
        {
            "id": str(r[0]),
            "content": r[1],
            "source": r[2],
            "created_at": str(r[3]),
        }
        for r in notes_result.fetchall()
    ]

    # Working memory (latest snapshot)
    wm_result = await db.execute(
        text(
            "SELECT snapshot_data, created_at FROM working_memory_snapshots "
            "WHERE user_id = :user_id AND tenant_id = :tenant_id "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    wm_row = wm_result.fetchone()
    working_memory = wm_row[0] if wm_row else {}

    exported_at = datetime.now(timezone.utc).isoformat()

    logger.info("gdpr_data_export", user_id=user_id, tenant_id=tenant_id)

    return {
        "profile": profile,
        "memory_notes": memory_notes,
        "working_memory": working_memory,
        "org_context": {},
        "exported_at": exported_at,
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
    # Platform-scope users (tenant_id='default') are not in the users table.
    # Return a synthetic profile from JWT claims.
    try:
        uuid.UUID(current_user.tenant_id)
    except (ValueError, AttributeError):
        return {
            "id": current_user.id,
            "email": current_user.email,
            "name": "Platform Admin",
            "role": "platform_admin",
            "status": "active",
            "tenant_id": current_user.tenant_id,
            "scope": current_user.scope,
        }
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


# ---------------------------------------------------------------------------
# Admin users route handlers
# ---------------------------------------------------------------------------


class SingleInviteRequest(BaseModel):
    """POST /admin/users/invite — invite a single user by email."""

    email: str = Field(..., min_length=1, max_length=320)
    role: str = Field("viewer", pattern="^(viewer|tenant_admin)$")
    name: Optional[str] = Field(None, max_length=200)


@admin_users_router.post("/invite", status_code=status.HTTP_201_CREATED)
async def invite_single_user(
    request: SingleInviteRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Invite a single user by email (creates user record with status='invited')."""
    email = request.email.strip().lower()
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid email address",
        )
    existing = await bulk_invite_check_existing(
        current_user.tenant_id, [email], session
    )
    if email in existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User '{email}' already exists in this workspace",
        )
    remaining = await bulk_invite_check_quota(current_user.tenant_id, session)
    if remaining <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="User quota reached. Upgrade your plan to invite more users.",
        )
    await bulk_invite_insert_db(
        tenant_id=current_user.tenant_id,
        email=email,
        name=request.name,
        role=request.role,
        invited_by=current_user.id,
        db=session,
    )
    return {"email": email, "status": "invited"}


@admin_users_router.post("/bulk-invite", status_code=status.HTTP_200_OK)
async def bulk_invite_users(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-044: Bulk invite users via CSV. Validates all rows before any invite is sent."""
    # Validate file type
    filename = file.filename or ""
    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File must be a CSV file (.csv extension required)",
        )

    # Read and parse CSV
    content = await file.read(_MAX_CSV_BYTES + 1)
    if len(content) > _MAX_CSV_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"CSV file exceeds maximum size of {_MAX_CSV_BYTES // 1024 // 1024} MB",
        )
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"CSV file must be UTF-8 encoded: {exc}",
        )

    reader = csv.DictReader(io.StringIO(decoded))

    # Validate CSV has required headers
    if not reader.fieldnames or not {"email", "name", "role"}.issubset(
        set(reader.fieldnames)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CSV must have headers: email, name, role",
        )

    # Read all rows
    rows = []
    for row in reader:
        rows.append(row)
        if len(rows) > _MAX_BULK_INVITE_ROWS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"CSV exceeds maximum of {_MAX_BULK_INVITE_ROWS} rows",
            )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CSV file contains no data rows",
        )

    # Phase 1: Validate all rows before any inserts
    errors: list[dict] = []
    valid_rows: list[dict] = []
    seen_emails: set[str] = set()

    # Check quota
    remaining_quota = await bulk_invite_check_quota(
        tenant_id=current_user.tenant_id, db=session
    )

    # Check existing emails in bulk
    all_emails = [row.get("email", "").strip().lower() for row in rows]
    existing_emails = await bulk_invite_check_existing(
        tenant_id=current_user.tenant_id,
        emails=all_emails,
        db=session,
    )

    for idx, row in enumerate(rows, start=2):  # Row 2 is first data row (after header)
        email = row.get("email", "").strip().lower()
        name = row.get("name", "").strip()
        role = row.get("role", "").strip().lower()

        # Email validation
        if not email or not _EMAIL_PATTERN.match(email):
            errors.append(
                {"row": idx, "email": email, "reason": "Invalid email format"}
            )
            continue

        # Role validation
        if role not in _VALID_BULK_INVITE_ROLES:
            errors.append(
                {
                    "row": idx,
                    "email": email,
                    "reason": f"Invalid role '{role}'. Must be one of: {', '.join(sorted(_VALID_BULK_INVITE_ROLES))}",
                }
            )
            continue

        # Duplicate within CSV
        if email in seen_emails:
            errors.append(
                {"row": idx, "email": email, "reason": "Duplicate email in CSV"}
            )
            continue
        seen_emails.add(email)

        # Already exists in database
        if email in existing_emails:
            errors.append(
                {
                    "row": idx,
                    "email": email,
                    "reason": "Email already exists for this tenant",
                }
            )
            continue

        valid_rows.append({"email": email, "name": name or None, "role": role})

    # Check quota against valid rows
    if len(valid_rows) > remaining_quota:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Insufficient user quota. Remaining: {remaining_quota}, requested: {len(valid_rows)}",
        )

    # Phase 2: Insert valid rows
    successful = 0
    for vrow in valid_rows:
        inserted = await bulk_invite_insert_db(
            tenant_id=current_user.tenant_id,
            email=vrow["email"],
            name=vrow["name"],
            role=vrow["role"],
            invited_by=current_user.id,
            db=session,
        )
        successful += inserted

    logger.info(
        "bulk_invite_completed",
        tenant_id=current_user.tenant_id,
        total=len(rows),
        successful=successful,
        failed=len(errors),
        invited_by=current_user.id,
    )

    return BulkInviteResult(
        total=len(rows),
        successful=successful,
        failed=len(errors),
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Admin users route handlers (API-088 enhanced user directory)
# ---------------------------------------------------------------------------

_VALID_USER_STATUSES = {"active", "invited", "suspended"}
_VALID_USER_ROLES = {"viewer", "tenant_admin"}

# Hardcoded SQL fragments for user WHERE status filter — never from user input
_USER_STATUS_SQL: dict[str, str] = {
    "active": "u.status = 'active'",
    "invited": "u.status = 'invited'",
    "suspended": "u.status = 'suspended'",
}


async def list_users_enhanced_db(
    tenant_id: str,
    page: int,
    page_size: int,
    search: Optional[str],
    role_filter: Optional[str],
    status_filter: Optional[str],
    db,
) -> dict:
    """List users for a tenant with search, role, status filters and last_active_at."""
    offset = (page - 1) * page_size

    # Build WHERE fragments from hardcoded strings — no user input in SQL structure
    where_parts = ["u.tenant_id = :tenant_id"]
    params: dict = {"tenant_id": tenant_id, "limit": page_size, "offset": offset}

    if status_filter and status_filter in _VALID_USER_STATUSES:
        where_parts.append(_USER_STATUS_SQL[status_filter])
    elif not status_filter:
        # Default: show active and invited (not suspended)
        where_parts.append("u.status IN ('active', 'invited', 'suspended')")

    if search:
        # Escape LIKE metacharacters to prevent wildcard injection
        safe_search = (
            search.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        where_parts.append(
            "(LOWER(u.name) LIKE :search ESCAPE '\\\\' OR LOWER(u.email) LIKE :search ESCAPE '\\\\')"
        )
        params["search"] = f"%{safe_search}%"

    if role_filter and role_filter in _VALID_USER_ROLES:
        where_parts.append("u.role = :role")
        params["role"] = role_filter

    where_clause = " AND ".join(where_parts)

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM users u WHERE {where_clause}"),
        params,
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        text(
            f"SELECT u.id, u.email, u.name, u.role, u.status, u.created_at, "
            f"MAX(m.created_at) AS last_active_at "
            f"FROM users u "
            f"LEFT JOIN conversations c ON c.user_id = u.id AND c.tenant_id = u.tenant_id "
            f"LEFT JOIN messages m ON m.conversation_id = c.id "
            f"WHERE {where_clause} "
            f"GROUP BY u.id, u.email, u.name, u.role, u.status, u.created_at "
            f"ORDER BY u.created_at DESC LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    items = []
    for row in rows_result.mappings():
        items.append(
            {
                "id": str(row["id"]),
                "name": row["name"],
                "email": row["email"],
                "role": row["role"],
                "status": row["status"],
                "last_login": str(row["last_active_at"])
                if row["last_active_at"]
                else None,
                "created_at": str(row["created_at"]),
            }
        )
    total_pages = math.ceil(total / page_size) if page_size > 0 else 1
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@admin_users_router.get("")
async def list_admin_users(
    search: Optional[str] = Query(None, description="Search by name or email"),
    role: Optional[str] = Query(None, description="Filter by role"),
    user_status: Optional[str] = Query(
        None,
        alias="status",
        description="Filter by status: active|invited|suspended",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-088: Enhanced user directory list with search, role, status filters."""
    if user_status is not None and user_status not in _VALID_USER_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid status '{user_status}'. "
                f"Must be one of: {', '.join(sorted(_VALID_USER_STATUSES))}"
            ),
        )
    result = await list_users_enhanced_db(
        tenant_id=current_user.tenant_id,
        page=page,
        page_size=page_size,
        search=search,
        role_filter=role,
        status_filter=user_status,
        db=session,
    )
    return result


# ---------------------------------------------------------------------------
# /me route handlers
# ---------------------------------------------------------------------------


@me_router.get("/data-export")
async def gdpr_data_export(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-104: Export all personal data for GDPR compliance (Article 20 data portability)."""
    result = await export_user_data_db(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    return result
