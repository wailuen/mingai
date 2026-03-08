"""
Notification routes (API-012, API-117, API-118, API-119, API-120).

Endpoints:
- GET  /notifications/stream           — SSE real-time stream (API-012)
- GET  /notifications                  — List persisted notifications (API-120)
- PATCH /notifications/{id}            — Mark notification read (API-119)
- GET  /me/notification-preferences   — Get notification preferences (API-118)
- PATCH /me/notification-preferences  — Update notification preferences (API-118)
"""
import asyncio
import inspect
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.core.redis_client import build_redis_key, get_redis
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(tags=["notifications"])
me_notifications_router = APIRouter(prefix="/me", tags=["me"])

# Keepalive interval in seconds - SSE connections drop if idle too long
KEEPALIVE_INTERVAL_SECONDS = 30

# Allowlist: notification preference keys stored in tenant_configs
_VALID_PREF_KEYS = {"in_app", "email", "issue_updates", "access_requests"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class NotificationItem(BaseModel):
    id: str
    type: str
    title: str
    body: str
    link: Optional[str] = None
    read: bool
    created_at: str


class NotificationListResponse(BaseModel):
    items: List[NotificationItem]
    total: int
    unread_count: int


class MarkReadRequest(BaseModel):
    read: bool


class MarkReadResponse(BaseModel):
    id: str
    read: bool


class NotificationPreferences(BaseModel):
    in_app: Optional[bool] = None
    email: Optional[bool] = None
    issue_updates: Optional[bool] = None
    access_requests: Optional[bool] = None


class NotificationPreferencesResponse(BaseModel):
    in_app: bool
    email: bool
    issue_updates: bool
    access_requests: bool


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

_DEFAULT_PREFS: dict = {
    "in_app": True,
    "email": True,
    "issue_updates": True,
    "access_requests": True,
}


async def _get_notification_prefs(
    db: AsyncSession, tenant_id: str, user_id: str
) -> dict:
    """Fetch notification preferences from tenant_configs. Returns defaults if not set."""
    config_key = f"notification_preferences:{user_id}"
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tenant_id AND config_type = :config_key"
        ),
        {"tenant_id": tenant_id, "config_key": config_key},
    )
    row = result.fetchone()
    if row is None:
        return dict(_DEFAULT_PREFS)
    data = row[0]
    if isinstance(data, str):
        data = json.loads(data)
    # Merge with defaults so new keys always appear
    merged = dict(_DEFAULT_PREFS)
    merged.update(data)
    return merged


async def _upsert_notification_prefs(
    db: AsyncSession, tenant_id: str, user_id: str, prefs: dict
) -> None:
    """Upsert notification preferences into tenant_configs."""
    config_key = f"notification_preferences:{user_id}"
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    await db.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (:id, :tenant_id, :config_key, CAST(:data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) "
            "DO UPDATE SET config_data = CAST(:data AS jsonb), updated_at = NOW()"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "config_key": config_key,
            "data": json.dumps(prefs),
        },
    )
    await db.commit()


# ---------------------------------------------------------------------------
# SSE stream (API-012) — existing endpoint preserved exactly
# ---------------------------------------------------------------------------


async def _event_generator(user_id: str, tenant_id: str) -> bytes:
    """
    Async generator that subscribes to a user's Redis Pub/Sub channel
    and yields SSE-formatted events.

    Sends keepalive comments every 30 seconds to prevent proxy/LB timeouts.
    Handles client disconnect via CancelledError / GeneratorExit.
    """
    channel = build_redis_key(tenant_id, "notifications", user_id)
    redis = get_redis()
    pubsub_result = redis.pubsub()
    # redis-py's pubsub() is synchronous, but handle awaitable for safety
    pubsub = (
        (await pubsub_result) if inspect.isawaitable(pubsub_result) else pubsub_result
    )

    await pubsub.subscribe(channel)
    logger.info(
        "sse_stream_started",
        user_id=user_id,
        tenant_id=tenant_id,
        channel=channel,
    )

    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=KEEPALIVE_INTERVAL_SECONDS,
                    ),
                    timeout=KEEPALIVE_INTERVAL_SECONDS + 1,
                )
            except asyncio.TimeoutError:
                # No message within keepalive window - send keepalive comment
                yield ": keepalive\n\n"
                continue

            if message and message["type"] == "message":
                data = message["data"]
                # redis-py with decode_responses=True returns str, otherwise bytes
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                yield f"data: {data}\n\n"
            else:
                # No message received (None or subscribe/unsubscribe confirmation)
                yield ": keepalive\n\n"

    except (asyncio.CancelledError, GeneratorExit):
        logger.info(
            "sse_stream_client_disconnected",
            user_id=user_id,
            tenant_id=tenant_id,
        )
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        logger.info(
            "sse_stream_closed",
            user_id=user_id,
            tenant_id=tenant_id,
            channel=channel,
        )


@router.get("/notifications/stream")
async def notification_stream(
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    SSE stream for real-time notification delivery (API-012).

    Maintains a persistent connection per authenticated user.
    Notifications are delivered within 2 seconds of the Redis PUBLISH event.
    Only delivers notifications for the current user (enforced via JWT).

    Headers:
    - Content-Type: text/event-stream
    - Cache-Control: no-cache (prevent proxy caching)
    - X-Accel-Buffering: no (prevent nginx buffering)

    SSE event format:
        data: {"id": "uuid", "type": "string", "title": "string", "body": "string",
               "link": "string|null", "read": false, "created_at": "ISO-8601"}
    """
    from fastapi.responses import StreamingResponse

    generator = _event_generator(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# API-120: List notifications
# ---------------------------------------------------------------------------


@router.get("/notifications", response_model=NotificationListResponse)
async def list_notifications(
    read: Optional[bool] = Query(None, description="Filter by read status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """
    List persisted notifications for the current user (API-120).

    Newest first. Supports optional read/unread filter and pagination.
    """
    tenant_id = current_user.tenant_id
    user_id = current_user.id
    offset = (page - 1) * page_size

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    # Build WHERE clause from hardcoded fragments only
    where_fragments = [
        "tenant_id = :tenant_id",
        "user_id = :user_id",
    ]
    params: dict = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "limit": page_size,
        "offset": offset,
    }

    if read is not None:
        where_fragments.append("read = :read_filter")
        params["read_filter"] = read

    where_clause = " AND ".join(where_fragments)

    # Total count
    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM notifications WHERE {where_clause}"),
        params,
    )
    total = count_result.scalar() or 0

    # Unread count (always scoped to this user regardless of filter)
    unread_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM notifications "
            "WHERE tenant_id = :tenant_id AND user_id = :user_id AND read = false"
        ),
        {"tenant_id": tenant_id, "user_id": user_id},
    )
    unread_count = unread_result.scalar() or 0

    # Fetch page
    rows_result = await db.execute(
        text(
            f"SELECT id, type, title, body, link, read, created_at "
            f"FROM notifications "
            f"WHERE {where_clause} "
            f"ORDER BY created_at DESC "
            f"LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    rows = rows_result.fetchall()

    items = [
        NotificationItem(
            id=str(row[0]),
            type=row[1],
            title=row[2],
            body=row[3] or "",
            link=row[4],
            read=bool(row[5]),
            created_at=row[6].isoformat() if row[6] else "",
        )
        for row in rows
    ]

    logger.info(
        "notifications_listed",
        user_id=user_id,
        total=total,
        page=page,
    )
    return NotificationListResponse(items=items, total=total, unread_count=unread_count)


# ---------------------------------------------------------------------------
# API-119: Mark notification as read
# ---------------------------------------------------------------------------


@router.patch("/notifications/{notification_id}", response_model=MarkReadResponse)
async def mark_notification_read(
    notification_id: str,
    request: MarkReadRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Mark a notification as read or unread (API-119).

    Only the owning user may update their own notifications (403 otherwise).
    """
    tenant_id = current_user.tenant_id
    user_id = current_user.id

    # Validate UUID format
    try:
        notif_uuid = uuid.UUID(notification_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Notification not found")

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    # Fetch to verify ownership
    fetch_result = await db.execute(
        text(
            "SELECT id, user_id FROM notifications "
            "WHERE id = :notif_id AND tenant_id = :tenant_id"
        ),
        {"notif_id": str(notif_uuid), "tenant_id": tenant_id},
    )
    row = fetch_result.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")

    # Ownership check — must be caller's own notification
    if str(row[1]) != user_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied",
        )

    await db.execute(
        text(
            "UPDATE notifications SET read = :read_val "
            "WHERE id = :notif_id AND tenant_id = :tenant_id"
        ),
        {
            "read_val": request.read,
            "notif_id": str(notif_uuid),
            "tenant_id": tenant_id,
        },
    )
    await db.commit()

    logger.info(
        "notification_marked",
        user_id=user_id,
        notification_id=notification_id,
        read=request.read,
    )
    return MarkReadResponse(id=notification_id, read=request.read)


# ---------------------------------------------------------------------------
# API-118: Notification preferences (registered on me_notifications_router)
# These are mounted under /me by router.py via me_notifications_router.
# ---------------------------------------------------------------------------


@me_notifications_router.get(
    "/notification-preferences",
    response_model=NotificationPreferencesResponse,
)
async def get_notification_preferences(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get current user's notification preferences (API-118).

    Returns defaults (all enabled) if preferences have not been explicitly set.
    """
    prefs = await _get_notification_prefs(db, current_user.tenant_id, current_user.id)
    return NotificationPreferencesResponse(**prefs)


@me_notifications_router.patch(
    "/notification-preferences",
    response_model=NotificationPreferencesResponse,
)
async def update_notification_preferences(
    request: NotificationPreferences,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Update current user's notification preferences (API-118).

    Validates that at least one channel (in_app or email) remains enabled.
    Only provided fields are updated; omitted fields keep their current values.
    """
    current_prefs = await _get_notification_prefs(
        db, current_user.tenant_id, current_user.id
    )

    # Apply partial updates — only fields explicitly provided in the request body
    update_data = request.model_dump(exclude_none=True)
    for key, value in update_data.items():
        if key in _VALID_PREF_KEYS:
            current_prefs[key] = value

    # At least one delivery channel must be enabled
    if not current_prefs.get("in_app") and not current_prefs.get("email"):
        raise HTTPException(
            status_code=422,
            detail="At least one notification channel (in_app or email) must remain enabled",
        )

    await _upsert_notification_prefs(
        db, current_user.tenant_id, current_user.id, current_prefs
    )

    logger.info(
        "notification_preferences_updated",
        user_id=current_user.id,
    )
    return NotificationPreferencesResponse(**current_prefs)
