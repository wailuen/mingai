"""
Notification SSE stream (API-012).

Endpoint: GET /api/v1/notifications/stream
Auth: end_user

Delivers real-time notifications via Server-Sent Events.
Backend publishes notifications to Redis Pub/Sub per-user channel:
  mingai:{tenant_id}:notifications:{user_id}

Message format (published via publisher.publish_notification):
  PUBLISH mingai:{tenant_id}:notifications:{user_id} '{"id": "...", "type": "...", ...}'
"""
import asyncio
import inspect

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.dependencies import CurrentUser, get_current_user
from app.core.redis_client import build_redis_key, get_redis

logger = structlog.get_logger()

router = APIRouter(tags=["notifications"])

# Keepalive interval in seconds - SSE connections drop if idle too long
KEEPALIVE_INTERVAL_SECONDS = 30


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
