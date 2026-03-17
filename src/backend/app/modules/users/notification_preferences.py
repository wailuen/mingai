"""
Notification preferences API (DEF-003).

Endpoints:
    GET  /me/notification-preferences  — get all 5 preference types for caller
    PATCH /me/notification-preferences — upsert preferences (accepts array)

Missing rows imply default: channel=in_app, enabled=true.
Both endpoints require any authenticated user (get_current_user).
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/me", tags=["me-notification-preferences"])

_VALID_NOTIFICATION_TYPES = frozenset(
    {"issue_update", "sync_failure", "access_request", "platform_message", "digest"}
)
_VALID_CHANNELS = frozenset({"in_app", "email", "both"})

# Default values when no row exists
_DEFAULT_CHANNEL = "in_app"
_DEFAULT_ENABLED = True


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class NotificationPreferenceItem(BaseModel):
    notification_type: str
    channel: str
    enabled: bool


class PatchPreferenceEntry(BaseModel):
    notification_type: str = Field(..., description="One of the 5 notification types")
    channel: Optional[str] = Field(None, description="in_app | email | both")
    enabled: Optional[bool] = Field(None)

    @field_validator("notification_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in _VALID_NOTIFICATION_TYPES:
            raise ValueError(
                f"notification_type must be one of: {sorted(_VALID_NOTIFICATION_TYPES)}"
            )
        return v

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_CHANNELS:
            raise ValueError(f"channel must be one of: {sorted(_VALID_CHANNELS)}")
        return v


class PatchPreferencesRequest(BaseModel):
    preferences: list[PatchPreferenceEntry] = Field(
        ..., min_length=1, description="Array of preference updates"
    )


class NotificationPreferencesResponse(BaseModel):
    preferences: list[NotificationPreferenceItem]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def get_preferences_db(
    user_id: str, tenant_id: str, db: AsyncSession
) -> dict[str, dict]:
    """Return existing preference rows keyed by notification_type."""
    result = await db.execute(
        text(
            "SELECT notification_type, channel, enabled "
            "FROM notification_preferences "
            "WHERE tenant_id = :tid AND user_id = :uid"
        ),
        {"tid": tenant_id, "uid": user_id},
    )
    rows = result.fetchall()
    return {row[0]: {"channel": row[1], "enabled": row[2]} for row in rows}


async def upsert_preference_db(
    user_id: str,
    tenant_id: str,
    notification_type: str,
    channel: str,
    enabled: bool,
    db: AsyncSession,
) -> None:
    """Upsert a single notification preference row."""
    await db.execute(
        text(
            "INSERT INTO notification_preferences "
            "  (id, tenant_id, user_id, notification_type, channel, enabled) "
            "VALUES (:id, :tid, :uid, :ntype, :channel, :enabled) "
            "ON CONFLICT (tenant_id, user_id, notification_type) DO UPDATE SET "
            "  channel    = EXCLUDED.channel, "
            "  enabled    = EXCLUDED.enabled, "
            "  updated_at = NOW()"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": tenant_id,
            "uid": user_id,
            "ntype": notification_type,
            "channel": channel,
            "enabled": enabled,
        },
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/notification-preferences", response_model=NotificationPreferencesResponse)
async def get_notification_preferences(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> NotificationPreferencesResponse:
    """Return all 5 notification preference types with current settings.

    Types with no stored row return the default (channel=in_app, enabled=true).
    """
    existing = await get_preferences_db(current_user.id, current_user.tenant_id, db)

    items = []
    for ntype in sorted(_VALID_NOTIFICATION_TYPES):
        row = existing.get(ntype)
        items.append(
            NotificationPreferenceItem(
                notification_type=ntype,
                channel=row["channel"] if row else _DEFAULT_CHANNEL,
                enabled=row["enabled"] if row else _DEFAULT_ENABLED,
            )
        )
    return NotificationPreferencesResponse(preferences=items)


@router.patch(
    "/notification-preferences", response_model=NotificationPreferencesResponse
)
async def patch_notification_preferences(
    body: PatchPreferencesRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
) -> NotificationPreferencesResponse:
    """Upsert notification preferences. Accepts an array of updates.

    Fields omitted from an entry (channel or enabled) retain their current
    value (or the default if no row exists yet).
    """
    # Fetch current state to merge omitted fields
    existing = await get_preferences_db(current_user.id, current_user.tenant_id, db)

    for entry in body.preferences:
        current = existing.get(entry.notification_type, {})
        channel = (
            entry.channel
            if entry.channel is not None
            else current.get("channel", _DEFAULT_CHANNEL)
        )
        enabled = (
            entry.enabled
            if entry.enabled is not None
            else current.get("enabled", _DEFAULT_ENABLED)
        )
        await upsert_preference_db(
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            notification_type=entry.notification_type,
            channel=channel,
            enabled=enabled,
            db=db,
        )

    await db.commit()

    logger.info(
        "notification_preferences_updated",
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        count=len(body.preferences),
    )

    # Return full updated state
    updated = await get_preferences_db(current_user.id, current_user.tenant_id, db)
    items = []
    for ntype in sorted(_VALID_NOTIFICATION_TYPES):
        row = updated.get(ntype)
        items.append(
            NotificationPreferenceItem(
                notification_type=ntype,
                channel=row["channel"] if row else _DEFAULT_CHANNEL,
                enabled=row["enabled"] if row else _DEFAULT_ENABLED,
            )
        )
    return NotificationPreferencesResponse(preferences=items)
