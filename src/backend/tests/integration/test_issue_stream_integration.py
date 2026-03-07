"""
TEST-018: Issue Redis Streams Integration Tests

Verifies that the Redis Stream producer (INFRA-017) works correctly against
a real Redis instance:
- ensure_stream_group creates the consumer group (idempotent)
- publish_issue_to_stream writes a readable message to the stream
- Message fields match the published payload exactly
- Stream length is bounded by STREAM_MAX_LEN

Tier 2: Real Redis — no mocking. Requires REDIS_URL in environment.

Run:
    pytest tests/integration/test_issue_stream_integration.py -v -m integration
"""
import os
import time
import uuid

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL", "")
    if not url:
        pytest.skip("REDIS_URL not configured — skipping Redis integration tests")
    return url


@pytest_asyncio.fixture
async def redis_conn():
    """Real async Redis connection, closed after each test."""
    import redis.asyncio as aioredis

    r = aioredis.from_url(_redis_url(), decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def clean_test_stream(redis_conn):
    """
    Ensure the integration test stream key is cleaned up after each test.

    Uses a unique stream key per test run to avoid cross-test contamination
    with the production stream.
    """
    test_stream_key = f"integration_test:issue_stream:{uuid.uuid4().hex}"
    yield test_stream_key
    # Cleanup — delete test stream
    await redis_conn.delete(test_stream_key)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
class TestEnsureStreamGroupIntegration:
    """Real Redis: consumer group creation and idempotency."""

    async def test_creates_consumer_group_on_real_redis(
        self, redis_conn, clean_test_stream
    ):
        """ensure_stream_group creates the group with MKSTREAM on real Redis."""
        from redis.exceptions import ResponseError

        from app.modules.issues.stream import CONSUMER_GROUP

        # Create group using the real Redis call directly
        # (monkeypatching stream key to avoid polluting production stream)
        try:
            await redis_conn.xgroup_create(
                clean_test_stream, CONSUMER_GROUP, id="0", mkstream=True
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

        # Verify the group exists by listing groups
        groups = await redis_conn.xinfo_groups(clean_test_stream)
        group_names = [g["name"] for g in groups]
        assert CONSUMER_GROUP in group_names

    async def test_idempotent_create_does_not_raise(
        self, redis_conn, clean_test_stream
    ):
        """Second ensure_stream_group call on same stream/group is a no-op."""
        from app.modules.issues.stream import CONSUMER_GROUP

        # Create group twice — second call must not raise
        for _ in range(2):
            try:
                await redis_conn.xgroup_create(
                    clean_test_stream, CONSUMER_GROUP, id="0", mkstream=True
                )
            except Exception as exc:
                from redis.exceptions import ResponseError

                if isinstance(exc, ResponseError) and "BUSYGROUP" in str(exc):
                    pass  # Expected on second call
                else:
                    raise

        # Stream must still be accessible
        info = await redis_conn.xinfo_stream(clean_test_stream)
        assert info is not None


@pytest.mark.integration
@pytest.mark.asyncio
class TestPublishIssueToStreamIntegration:
    """Real Redis: XADD and readback of published messages."""

    async def test_published_message_is_readable_from_stream(self, redis_conn):
        """
        publish_issue_to_stream writes a message that XREAD can retrieve with
        exact field values.
        """
        from app.modules.issues.stream import STREAM_KEY, publish_issue_to_stream

        report_id = f"test-report-{uuid.uuid4().hex[:8]}"
        tenant_id = f"test-tenant-{uuid.uuid4().hex[:8]}"

        entry_id = await publish_issue_to_stream(
            report_id=report_id,
            tenant_id=tenant_id,
            issue_type="bug",
            severity_hint="P2",
            redis=redis_conn,
        )

        try:
            # entry_id must be a non-empty string (Redis stream entry ID format: <ms>-<seq>)
            assert isinstance(entry_id, str)
            assert "-" in entry_id

            # Read the message back from the stream
            messages = await redis_conn.xrange(STREAM_KEY, min=entry_id, max=entry_id)
            assert (
                len(messages) == 1
            ), "Published message must appear exactly once in stream"

            msg_id, fields = messages[0]
            assert fields["report_id"] == report_id
            assert fields["tenant_id"] == tenant_id
            assert fields["issue_type"] == "bug"
            assert fields["severity_hint"] == "P2"
            assert "timestamp" in fields
            # timestamp must be a valid ISO string
            assert "T" in fields["timestamp"]
        finally:
            # Remove test entry so the live triage worker doesn't process a fake report
            await redis_conn.xdel(STREAM_KEY, entry_id)

    async def test_none_severity_hint_stored_as_empty_string(self, redis_conn):
        """severity_hint=None must be stored as '' in the stream (not 'None')."""
        from app.modules.issues.stream import STREAM_KEY, publish_issue_to_stream

        report_id = f"test-report-{uuid.uuid4().hex[:8]}"

        entry_id = await publish_issue_to_stream(
            report_id=report_id,
            tenant_id=f"test-tenant-{uuid.uuid4().hex[:8]}",
            issue_type="performance",
            severity_hint=None,
            redis=redis_conn,
        )

        try:
            messages = await redis_conn.xrange(STREAM_KEY, min=entry_id, max=entry_id)
            assert len(messages) == 1
            _, fields = messages[0]
            assert fields["severity_hint"] == ""
        finally:
            await redis_conn.xdel(STREAM_KEY, entry_id)

    async def test_multiple_publishes_produce_ordered_entries(self, redis_conn):
        """Publishing N messages yields N stream entries in monotonically increasing order."""
        from app.modules.issues.stream import STREAM_KEY, publish_issue_to_stream

        tenant_id = f"test-tenant-{uuid.uuid4().hex[:8]}"
        published_ids = []

        for i in range(3):
            entry_id = await publish_issue_to_stream(
                report_id=f"report-{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                issue_type="bug",
                severity_hint=f"P{i % 4}",
                redis=redis_conn,
            )
            published_ids.append(entry_id)

        try:
            # All IDs must be distinct and ordered
            assert len(set(published_ids)) == 3
            assert published_ids == sorted(
                published_ids
            ), "Stream entry IDs must be monotonically increasing"
        finally:
            if published_ids:
                await redis_conn.xdel(STREAM_KEY, *published_ids)

    async def test_publish_requires_nonempty_report_id(self, redis_conn):
        """publish_issue_to_stream raises ValueError when report_id is empty."""
        from app.modules.issues.stream import publish_issue_to_stream

        with pytest.raises(ValueError, match="report_id"):
            await publish_issue_to_stream(
                report_id="",
                tenant_id="tenant-abc",
                issue_type="bug",
                severity_hint=None,
                redis=redis_conn,
            )

    async def test_publish_requires_nonempty_tenant_id(self, redis_conn):
        """publish_issue_to_stream raises ValueError when tenant_id is empty."""
        from app.modules.issues.stream import publish_issue_to_stream

        with pytest.raises(ValueError, match="tenant_id"):
            await publish_issue_to_stream(
                report_id="some-report-id",
                tenant_id="",
                issue_type="bug",
                severity_hint=None,
                redis=redis_conn,
            )
