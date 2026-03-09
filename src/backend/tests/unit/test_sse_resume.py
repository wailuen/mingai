"""
Unit tests for GAP-011 — SSE Last-Event-ID Resume Support.

Coverage:
- SSE events emitted by stream_with_buffer carry sequential ``id:`` fields
- Buffer is stored in Redis after stream completes
- Reconnect with Last-Event-ID replays from the correct position
- Expired buffer (Redis miss) triggers fresh stream, no error
- Buffer key follows correct tenant namespace
- format_sse_event produces compliant SSE wire format
- store_events respects max buffer size
- get_events_from returns empty list when client is fully caught up
- Redis error during store is swallowed (non-fatal)
- Redis error during get returns None (triggers fresh stream)
"""
import json
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.modules.chat.sse_buffer import (
    SSEBufferService,
    SSE_BUFFER_MAX_EVENTS,
    SSE_BUFFER_TTL_SECONDS,
    _tag_events,
    format_sse_event,
    stream_with_buffer,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_redis_mock(stored_payload: str | None = None):
    """Build a minimal async Redis mock for sse_buffer tests."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=stored_payload)
    mock.setex = AsyncMock(return_value=True)
    return mock


def _sample_events(n: int = 5) -> list[dict]:
    """Generate n sample orchestrator events (without id)."""
    events = []
    for i in range(n):
        if i < n - 1:
            events.append({"event": "response_chunk", "data": {"chunk": f"chunk_{i}"}})
        else:
            events.append(
                {
                    "event": "done",
                    "data": {"conversation_id": "conv-abc", "message_id": f"msg-{i}"},
                }
            )
    return events


async def _gen_from_list(events: list[dict]):
    """Async generator that yields each event from a list."""
    for event in events:
        yield event


# ---------------------------------------------------------------------------
# format_sse_event tests
# ---------------------------------------------------------------------------


class TestFormatSSEEvent:
    """SSE wire format conformance."""

    def test_id_field_present(self):
        """Formatted event includes id: line."""
        event = {"id": 3, "event": "status", "data": {"stage": "embedding"}}
        output = format_sse_event(event)
        assert "id: 3" in output

    def test_event_type_field_present(self):
        """Formatted event includes event: line."""
        event = {"id": 1, "event": "response_chunk", "data": {"chunk": "hello"}}
        output = format_sse_event(event)
        assert "event: response_chunk" in output

    def test_data_field_is_json(self):
        """Data line contains valid JSON."""
        data = {"stage": "glossary_expansion"}
        event = {"id": 2, "event": "status", "data": data}
        output = format_sse_event(event)
        # Extract the data line
        for line in output.split("\n"):
            if line.startswith("data:"):
                parsed = json.loads(line[len("data:") :].strip())
                assert parsed == data
                return
        pytest.fail("No data: line found in SSE output")

    def test_double_newline_terminator(self):
        """SSE event is terminated with \\n\\n."""
        event = {"id": 1, "event": "done", "data": {"conversation_id": "c1"}}
        output = format_sse_event(event)
        assert output.endswith("\n\n")


# ---------------------------------------------------------------------------
# _tag_events tests
# ---------------------------------------------------------------------------


class TestTagEvents:
    """Sequential id assignment."""

    def test_ids_are_sequential_from_one(self):
        """Events receive ids starting at 1."""
        events = [{"event": "status", "data": {}} for _ in range(3)]
        tagged = _tag_events(events)
        assert [e["id"] for e in tagged] == [1, 2, 3]

    def test_existing_ids_are_overwritten(self):
        """Pre-existing id values are replaced with sequential ids."""
        events = [{"event": "done", "data": {}, "id": 999}]
        tagged = _tag_events(events)
        assert tagged[0]["id"] == 1

    def test_empty_list_returns_empty(self):
        tagged = _tag_events([])
        assert tagged == []


# ---------------------------------------------------------------------------
# stream_with_buffer — fresh stream tests
# ---------------------------------------------------------------------------


class TestStreamWithBufferFresh:
    """Fresh stream (no Last-Event-ID): events tagged and buffered."""

    @pytest.mark.asyncio
    async def test_events_carry_sequential_ids(self):
        """Each yielded SSE string contains an incrementing id:."""
        redis_mock = _make_redis_mock()
        buffer_svc = SSEBufferService(redis_client=redis_mock)
        events = _sample_events(3)

        lines = []
        async for sse_line in stream_with_buffer(
            tenant_id="tenant-1",
            conversation_id="conv-1",
            last_event_id=None,
            orchestrator_gen=_gen_from_list(events),
            buffer_service=buffer_svc,
        ):
            lines.append(sse_line)

        # Extract all id: values from the output
        ids = []
        for chunk in lines:
            for part in chunk.split("\n"):
                if part.startswith("id:"):
                    ids.append(int(part.split(":")[1].strip()))

        assert ids == list(range(1, len(events) + 1))

    @pytest.mark.asyncio
    async def test_buffer_stored_after_stream_completes(self):
        """Redis setex is called once after the stream finishes."""
        redis_mock = _make_redis_mock()
        buffer_svc = SSEBufferService(redis_client=redis_mock)
        events = _sample_events(4)

        async for _ in stream_with_buffer(
            tenant_id="tenant-1",
            conversation_id="conv-store-test",
            last_event_id=None,
            orchestrator_gen=_gen_from_list(events),
            buffer_service=buffer_svc,
        ):
            pass

        redis_mock.setex.assert_called_once()
        # Key should include the conversation_id
        key_arg = redis_mock.setex.call_args[0][0]
        assert "conv-store-test" in key_arg

    @pytest.mark.asyncio
    async def test_buffer_ttl_is_five_minutes(self):
        """Buffer is stored with 300-second TTL."""
        redis_mock = _make_redis_mock()
        buffer_svc = SSEBufferService(redis_client=redis_mock)
        events = _sample_events(2)

        async for _ in stream_with_buffer(
            tenant_id="tenant-1",
            conversation_id="conv-ttl",
            last_event_id=None,
            orchestrator_gen=_gen_from_list(events),
            buffer_service=buffer_svc,
        ):
            pass

        ttl_arg = redis_mock.setex.call_args[0][1]
        assert ttl_arg == SSE_BUFFER_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_buffer_key_uses_tenant_namespace(self):
        """Buffer key is mingai:{tenant_id}:sse_buffer:{conversation_id}."""
        redis_mock = _make_redis_mock()
        buffer_svc = SSEBufferService(redis_client=redis_mock)
        events = _sample_events(2)

        async for _ in stream_with_buffer(
            tenant_id="acme-corp",
            conversation_id="conv-ns-test",
            last_event_id=None,
            orchestrator_gen=_gen_from_list(events),
            buffer_service=buffer_svc,
        ):
            pass

        key_arg = redis_mock.setex.call_args[0][0]
        assert key_arg == "mingai:acme-corp:sse_buffer:conv-ns-test"

    @pytest.mark.asyncio
    async def test_conversation_id_inferred_from_done_event(self):
        """When conversation_id is None, it is extracted from the done event."""
        redis_mock = _make_redis_mock()
        buffer_svc = SSEBufferService(redis_client=redis_mock)
        events = [
            {"event": "status", "data": {"stage": "glossary_expansion"}},
            {
                "event": "done",
                "data": {"conversation_id": "inferred-conv", "message_id": "m1"},
            },
        ]

        async for _ in stream_with_buffer(
            tenant_id="tenant-x",
            conversation_id=None,  # not known up front
            last_event_id=None,
            orchestrator_gen=_gen_from_list(events),
            buffer_service=buffer_svc,
        ):
            pass

        # setex called because conversation_id was inferred from done event
        redis_mock.setex.assert_called_once()
        key_arg = redis_mock.setex.call_args[0][0]
        assert "inferred-conv" in key_arg


# ---------------------------------------------------------------------------
# stream_with_buffer — resume tests
# ---------------------------------------------------------------------------


class TestStreamWithBufferResume:
    """Resume path: Last-Event-ID replays from buffer."""

    @pytest.mark.asyncio
    async def test_replay_from_correct_position(self):
        """Last-Event-ID=2 replays events 3 onwards."""
        # Store 5 tagged events in the mock buffer
        stored_events = _tag_events(_sample_events(5))
        stored_payload = json.dumps(stored_events)
        redis_mock = _make_redis_mock(stored_payload=stored_payload)
        buffer_svc = SSEBufferService(redis_client=redis_mock)

        replayed_ids = []
        async for sse_line in stream_with_buffer(
            tenant_id="tenant-1",
            conversation_id="conv-resume",
            last_event_id=2,  # want events 3, 4, 5
            orchestrator_gen=_gen_from_list([]),  # not called
            buffer_service=buffer_svc,
        ):
            for part in sse_line.split("\n"):
                if part.startswith("id:"):
                    replayed_ids.append(int(part.split(":")[1].strip()))

        assert replayed_ids == [3, 4, 5]

    @pytest.mark.asyncio
    async def test_expired_buffer_triggers_fresh_stream(self):
        """Redis miss (expired buffer) falls through to orchestrator_gen."""
        # Redis returns None → buffer miss
        redis_mock = _make_redis_mock(stored_payload=None)
        buffer_svc = SSEBufferService(redis_client=redis_mock)

        # The fresh orchestrator gen yields 2 events
        fresh_events = [
            {"event": "response_chunk", "data": {"chunk": "fresh"}},
            {
                "event": "done",
                "data": {"conversation_id": "conv-fresh", "message_id": "m"},
            },
        ]

        yielded_lines = []
        async for sse_line in stream_with_buffer(
            tenant_id="tenant-1",
            conversation_id="conv-expired",
            last_event_id=3,
            orchestrator_gen=_gen_from_list(fresh_events),
            buffer_service=buffer_svc,
        ):
            yielded_lines.append(sse_line)

        # Should have gotten 2 SSE lines from the fresh stream
        assert len(yielded_lines) == 2
        # The stream should NOT raise — no error event
        for line in yielded_lines:
            assert "error" not in line

    @pytest.mark.asyncio
    async def test_up_to_date_client_gets_empty_replay(self):
        """Last-Event-ID equal to last stored event → empty replay, no error."""
        stored_events = _tag_events(_sample_events(3))
        stored_payload = json.dumps(stored_events)
        redis_mock = _make_redis_mock(stored_payload=stored_payload)
        buffer_svc = SSEBufferService(redis_client=redis_mock)

        yielded_lines = []
        async for sse_line in stream_with_buffer(
            tenant_id="tenant-1",
            conversation_id="conv-uptodate",
            last_event_id=3,  # last event id in the buffer
            orchestrator_gen=_gen_from_list([]),
            buffer_service=buffer_svc,
        ):
            yielded_lines.append(sse_line)

        assert yielded_lines == []


# ---------------------------------------------------------------------------
# SSEBufferService direct tests
# ---------------------------------------------------------------------------


class TestSSEBufferService:
    """Direct tests of store_events and get_events_from."""

    @pytest.mark.asyncio
    async def test_store_events_caps_at_max(self):
        """Events list is capped at SSE_BUFFER_MAX_EVENTS before storing."""
        redis_mock = _make_redis_mock()
        svc = SSEBufferService(redis_client=redis_mock)

        # Create more events than the cap
        oversized = [
            {"event": "chunk", "data": {}} for _ in range(SSE_BUFFER_MAX_EVENTS + 100)
        ]
        await svc.store_events(
            tenant_id="tenant-1",
            conversation_id="conv-cap",
            events=oversized,
        )

        # The payload stored should contain at most SSE_BUFFER_MAX_EVENTS entries
        stored_payload = redis_mock.setex.call_args[0][2]
        stored = json.loads(stored_payload)
        assert len(stored) == SSE_BUFFER_MAX_EVENTS

    @pytest.mark.asyncio
    async def test_store_empty_events_does_not_call_setex(self):
        """Storing an empty events list is a no-op."""
        redis_mock = _make_redis_mock()
        svc = SSEBufferService(redis_client=redis_mock)

        await svc.store_events(
            tenant_id="tenant-1",
            conversation_id="conv-empty",
            events=[],
        )

        redis_mock.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_events_from_returns_none_on_redis_miss(self):
        """get_events_from returns None when key does not exist."""
        redis_mock = _make_redis_mock(stored_payload=None)
        svc = SSEBufferService(redis_client=redis_mock)

        result = await svc.get_events_from(
            tenant_id="tenant-1",
            conversation_id="conv-miss",
            last_event_id=0,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_store_redis_error_is_swallowed(self):
        """Redis error during store is caught and logged; does not raise."""
        redis_mock = AsyncMock()
        redis_mock.setex = AsyncMock(side_effect=ConnectionError("Redis down"))
        svc = SSEBufferService(redis_client=redis_mock)

        # Should NOT raise
        await svc.store_events(
            tenant_id="tenant-1",
            conversation_id="conv-err",
            events=_sample_events(2),
        )

    @pytest.mark.asyncio
    async def test_get_redis_error_returns_none(self):
        """Redis error during get is caught; returns None (triggers fresh stream)."""
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        svc = SSEBufferService(redis_client=redis_mock)

        result = await svc.get_events_from(
            tenant_id="tenant-1",
            conversation_id="conv-err",
            last_event_id=1,
        )
        assert result is None
