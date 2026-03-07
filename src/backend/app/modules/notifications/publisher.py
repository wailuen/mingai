"""
Notification publisher for mingai platform.

Publishes notifications to per-user Redis Pub/Sub channels.
Channel pattern: mingai:{tenant_id}:notifications:{user_id}

Import this module from any backend service that needs to push
real-time notifications to users.
"""
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import structlog

from app.core.redis_client import build_redis_key

logger = structlog.get_logger()


async def publish_notification(
    user_id: str,
    tenant_id: str,
    notification_type: str,
    title: str,
    body: str,
    link: Optional[str] = None,
    redis: Optional[object] = None,
) -> None:
    """
    Publish a notification to a user's Redis Pub/Sub channel.

    Args:
        user_id: Target user ID (from JWT sub claim).
        tenant_id: Tenant ID (from JWT tenant_id claim).
        notification_type: Notification category (e.g. "document_ready", "alert").
        title: Short notification title.
        body: Notification body text.
        link: Optional navigation link for the notification.
        redis: Redis client instance. If not provided, fetches from pool.

    Raises:
        ValueError: If tenant_id or user_id violate namespace constraints.
    """
    if not user_id:
        raise ValueError(
            "user_id is required for notification publishing. "
            "Cannot send notification without a target user."
        )
    if not tenant_id:
        raise ValueError(
            "tenant_id is required for notification publishing. "
            "Cannot send notification without tenant context."
        )
    if not notification_type:
        raise ValueError(
            "notification_type is required. "
            "Specify the category of notification (e.g. 'document_ready', 'alert')."
        )
    if not title:
        raise ValueError(
            "title is required. Notifications must have a human-readable title."
        )
    if not body:
        raise ValueError("body is required. Notifications must have a body message.")

    # build_redis_key validates tenant_id (no colons, non-empty)
    channel = build_redis_key(tenant_id, "notifications", user_id)

    notification = {
        "id": str(uuid4()),
        "type": notification_type,
        "title": title,
        "body": body,
        "link": link,
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    payload = json.dumps(notification)

    if redis is None:
        from app.core.redis_client import get_redis

        redis = get_redis()

    await redis.publish(channel, payload)

    logger.info(
        "notification_published",
        user_id=user_id,
        tenant_id=tenant_id,
        notification_type=notification_type,
        notification_id=notification["id"],
        channel=channel,
    )
