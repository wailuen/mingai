"""
GAP-011: SSE Last-Event-ID Resume Support.

Manages the Redis-backed event buffer that enables clients to resume dropped
SSE connections without restarting the entire query.

Buffer key:  mingai:{tenant_id}:sse_buffer:{conversation_id}
TTL:         300 seconds (5 minutes)
Buffer size: up to SSE_BUFFER_MAX_EVENTS events (default 500)

Protocol:
  - Each SSE event is assigned a sequential numeric id starting at 1.
  - The completed event sequence is serialised as a JSON list and stored in
    Redis when the stream finishes (event type == "done").
  - On reconnect the client sends `Last-Event-ID: N` as a request header.
  - The buffer is replayed from event id N+1 onward.
  - If the buffer has expired (Redis miss), the stream restarts from scratch.
"""
import json
from typing import AsyncGenerator

import structlog

from app.core.redis_client import build_redis_key

logger = structlog.get_logger()

# Maximum number of events kept in the replay buffer per stream.
SSE_BUFFER_MAX_EVENTS = 500

# TTL for the replay buffer (seconds).  Matches cache.py DEFAULT_TTL["sse_buffer"].
SSE_BUFFER_TTL_SECONDS = 300


class SSEBufferService:
    """
    Redis-backed SSE event buffer with Last-Event-ID replay.

    All public methods are non-raising: Redis errors are logged and silently
    swallowed so that a Redis outage never breaks a live stream.
    """

    def __init__(self, *, redis_client=None):
        """
        Args:
            redis_client: Async Redis client. If None, uses get_redis() lazily.
        """
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Buffer storage
    # ------------------------------------------------------------------

    async def store_events(
        self,
        tenant_id: str,
        conversation_id: str,
        events: list[dict],
    ) -> None:
        """
        Persist the complete event list for a finished stream.

        The ``events`` list should contain dicts with at least ``event``
        and ``data`` keys.  Each entry is tagged with an ``id`` (1-based)
        if not already present.

        Args:
            tenant_id:        Tenant namespace.
            conversation_id:  Conversation (stream) identifier.
            events:           Ordered list of SSE event dicts.
        """
        tagged = _tag_events(events)
        if not tagged:
            return
        # Enforce cap
        if len(tagged) > SSE_BUFFER_MAX_EVENTS:
            tagged = tagged[-SSE_BUFFER_MAX_EVENTS:]
        try:
            redis = self._get_redis()
            key = build_redis_key(tenant_id, "sse_buffer", conversation_id)
            payload = json.dumps(tagged)
            await redis.setex(key, SSE_BUFFER_TTL_SECONDS, payload)
            logger.info(
                "sse_buffer_stored",
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                event_count=len(tagged),
            )
        except Exception as exc:
            logger.warning(
                "sse_buffer_store_error",
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                error=str(exc),
            )

    async def get_events_from(
        self,
        tenant_id: str,
        conversation_id: str,
        last_event_id: int,
    ) -> list[dict] | None:
        """
        Retrieve buffered events with id > last_event_id.

        Returns:
            List of event dicts (may be empty if client is already up-to-date),
            or None if the buffer has expired / does not exist.
        """
        try:
            redis = self._get_redis()
            key = build_redis_key(tenant_id, "sse_buffer", conversation_id)
            raw = await redis.get(key)
            if raw is None:
                logger.info(
                    "sse_buffer_miss",
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    last_event_id=last_event_id,
                )
                return None
            all_events: list[dict] = json.loads(raw)
            replay = [e for e in all_events if e.get("id", 0) > last_event_id]
            logger.info(
                "sse_buffer_replay",
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                last_event_id=last_event_id,
                replay_count=len(replay),
            )
            return replay
        except Exception as exc:
            logger.warning(
                "sse_buffer_get_error",
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                error=str(exc),
            )
            return None

    # ------------------------------------------------------------------
    # SSE serialisation helpers
    # ------------------------------------------------------------------

    def _get_redis(self):
        if self._redis is not None:
            return self._redis
        from app.core.redis_client import get_redis

        return get_redis()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _tag_events(events: list[dict]) -> list[dict]:
    """
    Return a copy of events with sequential ``id`` fields (1-based).

    Existing ``id`` values are overwritten to guarantee a contiguous
    sequence that matches the client's Last-Event-ID header expectations.
    """
    tagged = []
    for idx, event in enumerate(events, start=1):
        entry = dict(event)
        entry["id"] = idx
        tagged.append(entry)
    return tagged


def format_sse_event(event: dict) -> str:
    """
    Serialise a tagged event dict to SSE wire format.

    Includes the ``id:`` line required for Last-Event-ID tracking:

        id: 1
        event: status
        data: {"stage": "glossary_expansion"}

    Args:
        event: Dict with keys ``id``, ``event``, ``data``.

    Returns:
        Multi-line SSE string terminated by double newline.
    """
    event_id = event.get("id", "")
    event_type = event.get("event", "message")
    data = event.get("data", {})
    data_str = json.dumps(data)
    return f"id: {event_id}\nevent: {event_type}\ndata: {data_str}\n\n"


async def stream_with_buffer(
    *,
    tenant_id: str,
    conversation_id: str | None,
    last_event_id: int | None,
    orchestrator_gen: AsyncGenerator[dict, None],
    buffer_service: SSEBufferService,
) -> AsyncGenerator[str, None]:
    """
    Wrap an orchestrator generator with SSE id tagging and buffer storage.

    On a fresh stream (last_event_id is None or conversation_id is None):
      - Assign sequential ids to each event
      - Yield formatted SSE strings
      - Store all events in Redis when the stream is done

    On a resume (last_event_id is an int and conversation_id is set):
      - Attempt to replay from the buffer
      - If the buffer is available: yield buffered events from last_event_id+1
      - If the buffer has expired: fall through to orchestrator_gen for a
        fresh stream (transparent restart, no error to the client)

    Args:
        tenant_id:          For Redis key namespacing.
        conversation_id:    Identifies the stream buffer in Redis.
        last_event_id:      Value from the client's Last-Event-ID header, or None.
        orchestrator_gen:   The async generator from orchestrator.stream_response().
        buffer_service:     SSEBufferService instance.

    Yields:
        SSE-formatted strings (id + event + data lines).
    """
    # Attempt buffer replay when client provides Last-Event-ID
    if last_event_id is not None and conversation_id:
        buffered = await buffer_service.get_events_from(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            last_event_id=last_event_id,
        )
        if buffered is not None:
            # Buffer hit — replay and stop (no fresh LLM call)
            for event in buffered:
                yield format_sse_event(event)
            return
        # Buffer miss (expired) — fall through to fresh stream below

    # Fresh stream: collect all events, tag them, yield and buffer
    collected: list[dict] = []
    event_counter = 0

    async for raw_event in orchestrator_gen:
        event_counter += 1
        tagged_event = dict(raw_event)
        tagged_event["id"] = event_counter
        collected.append(tagged_event)
        yield format_sse_event(tagged_event)

    # Store buffer after the stream completes (uses conversation_id from
    # the "done" event if the caller did not know it upfront)
    effective_conv_id = conversation_id
    if effective_conv_id is None and collected:
        # Extract conversation_id from the done event
        done_events = [e for e in collected if e.get("event") == "done"]
        if done_events:
            effective_conv_id = done_events[-1].get("data", {}).get("conversation_id")

    if effective_conv_id and collected:
        await buffer_service.store_events(
            tenant_id=tenant_id,
            conversation_id=effective_conv_id,
            events=collected,
        )
