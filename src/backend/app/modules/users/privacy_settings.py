"""
User privacy settings API (DEF-004).

Endpoints:
    GET  /me/privacy-settings  — get privacy settings or defaults (all true)
    PATCH /me/privacy-settings — update subset of privacy flags

Both endpoints require any authenticated user (get_current_user).

Service helper:
    _check_privacy_setting(session, tenant_id, user_id, setting_name) -> bool
    Returns True if the setting is enabled or if no row exists yet (default-permissive).
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/me", tags=["me-privacy-settings"])

_PRIVACY_FIELDS = frozenset(
    {"profile_learning_enabled", "working_memory_enabled", "org_context_enabled"}
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PrivacySettingsResponse(BaseModel):
    profile_learning_enabled: bool
    working_memory_enabled: bool
    org_context_enabled: bool


class PatchPrivacySettingsRequest(BaseModel):
    profile_learning_enabled: Optional[bool] = Field(None)
    working_memory_enabled: Optional[bool] = Field(None)
    org_context_enabled: Optional[bool] = Field(None)


# ---------------------------------------------------------------------------
# Service helper
# ---------------------------------------------------------------------------


async def _check_privacy_setting(
    session: AsyncSession,
    tenant_id: str,
    user_id: str,
    setting_name: str,
) -> bool:
    """Return True if the named privacy setting is enabled.

    Returns True (default-permissive) when no row exists for this user.

    Args:
        session: Async SQLAlchemy session.
        tenant_id: Tenant scope for RLS.
        user_id: User whose setting is checked.
        setting_name: One of 'profile_learning_enabled', 'working_memory_enabled',
                      or 'org_context_enabled'.
    """
    if setting_name not in _PRIVACY_FIELDS:
        raise ValueError(f"Unknown privacy setting: {setting_name!r}")

    # Column name is from allowlist — safe to interpolate
    col = setting_name
    result = await session.execute(
        text(
            f"SELECT {col} FROM user_privacy_settings "  # noqa: S608 — col is allowlisted
            "WHERE tenant_id = :tid AND user_id = :uid"
        ),
        {"tid": tenant_id, "uid": user_id},
    )
    row = result.fetchone()
    if row is None:
        return True  # default-permissive: no row means all enabled
    return bool(row[0])


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def get_privacy_settings_db(
    user_id: str, tenant_id: str, db: AsyncSession
) -> Optional[dict]:
    """Return privacy settings row or None."""
    result = await db.execute(
        text(
            "SELECT profile_learning_enabled, working_memory_enabled, "
            "org_context_enabled "
            "FROM user_privacy_settings "
            "WHERE tenant_id = :tid AND user_id = :uid"
        ),
        {"tid": tenant_id, "uid": user_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "profile_learning_enabled": row[0],
        "working_memory_enabled": row[1],
        "org_context_enabled": row[2],
    }


async def upsert_privacy_settings_db(
    user_id: str,
    tenant_id: str,
    profile_learning_enabled: bool,
    working_memory_enabled: bool,
    org_context_enabled: bool,
    db: AsyncSession,
) -> None:
    """Upsert user privacy settings row."""
    await db.execute(
        text(
            "INSERT INTO user_privacy_settings "
            "  (id, tenant_id, user_id, profile_learning_enabled, "
            "   working_memory_enabled, org_context_enabled) "
            "VALUES (:id, :tid, :uid, :ple, :wme, :oce) "
            "ON CONFLICT (tenant_id, user_id) DO UPDATE SET "
            "  profile_learning_enabled = EXCLUDED.profile_learning_enabled, "
            "  working_memory_enabled   = EXCLUDED.working_memory_enabled, "
            "  org_context_enabled      = EXCLUDED.org_context_enabled, "
            "  updated_at               = NOW()"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": tenant_id,
            "uid": user_id,
            "ple": profile_learning_enabled,
            "wme": working_memory_enabled,
            "oce": org_context_enabled,
        },
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/privacy-settings", response_model=PrivacySettingsResponse)
async def get_privacy_settings(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> PrivacySettingsResponse:
    """Return user privacy settings. All fields default to true if no row exists."""
    row = await get_privacy_settings_db(current_user.id, current_user.tenant_id, db)
    if row is None:
        return PrivacySettingsResponse(
            profile_learning_enabled=True,
            working_memory_enabled=True,
            org_context_enabled=True,
        )
    return PrivacySettingsResponse(
        profile_learning_enabled=row["profile_learning_enabled"],
        working_memory_enabled=row["working_memory_enabled"],
        org_context_enabled=row["org_context_enabled"],
    )


@router.patch("/privacy-settings", response_model=PrivacySettingsResponse)
async def patch_privacy_settings(
    body: PatchPrivacySettingsRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> PrivacySettingsResponse:
    """Update privacy settings. Only provided fields are changed; others retain
    current value (or default True if row is new).
    """
    existing = await get_privacy_settings_db(
        current_user.id, current_user.tenant_id, db
    )
    current_vals = existing or {
        "profile_learning_enabled": True,
        "working_memory_enabled": True,
        "org_context_enabled": True,
    }

    ple = (
        body.profile_learning_enabled
        if body.profile_learning_enabled is not None
        else current_vals["profile_learning_enabled"]
    )
    wme = (
        body.working_memory_enabled
        if body.working_memory_enabled is not None
        else current_vals["working_memory_enabled"]
    )
    oce = (
        body.org_context_enabled
        if body.org_context_enabled is not None
        else current_vals["org_context_enabled"]
    )

    await upsert_privacy_settings_db(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        profile_learning_enabled=ple,
        working_memory_enabled=wme,
        org_context_enabled=oce,
        db=db,
    )
    await db.commit()

    logger.info(
        "privacy_settings_updated",
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )

    return PrivacySettingsResponse(
        profile_learning_enabled=ple,
        working_memory_enabled=wme,
        org_context_enabled=oce,
    )
