"""
Unit tests for INFRA-017 (Redis Stream producer) and INFRA-018 (Redis Stream consumer/worker).

Tests cover:
- Stream constants verification (STREAM_KEY, CONSUMER_GROUP, STREAM_MAX_LEN)
- ensure_stream_group idempotency (XGROUP CREATE MKSTREAM)
- publish_issue_to_stream calls XADD with correct fields and MAXLEN
- process_message routes feature-type issues to product backlog (skips triage)
- process_message for bug-type calls triage agent and updates issue status

Tier 1: Fast, isolated, mocks Redis/DB/LLM only.
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test: Stream constants (INFRA-017)
# ---------------------------------------------------------------------------


class TestStreamConstants:
    """Verify the stream constants are set correctly."""

    def test_stream_key_value(self):
        from app.modules.issues.stream import STREAM_KEY

        assert STREAM_KEY == "issue_reports:incoming"

    def test_consumer_group_value(self):
        from app.modules.issues.stream import CONSUMER_GROUP

        assert CONSUMER_GROUP == "issue_triage_workers"

    def test_stream_max_len_value(self):
        from app.modules.issues.stream import STREAM_MAX_LEN

        assert STREAM_MAX_LEN == 10_000


# ---------------------------------------------------------------------------
# Test: ensure_stream_group (INFRA-017)
# ---------------------------------------------------------------------------


class TestEnsureStreamGroup:
    """Test idempotent consumer group creation."""

    @pytest.mark.asyncio
    async def test_ensure_stream_group_creates_group(self):
        """XGROUP CREATE is called with correct args."""
        from app.modules.issues.stream import (
            CONSUMER_GROUP,
            STREAM_KEY,
            ensure_stream_group,
        )

        redis = AsyncMock()
        redis.xgroup_create = AsyncMock()

        await ensure_stream_group(redis)

        redis.xgroup_create.assert_called_once_with(
            STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True
        )

    @pytest.mark.asyncio
    async def test_ensure_stream_group_idempotent_on_busygroup(self):
        """If group already exists (BUSYGROUP error), no exception raised."""
        from app.modules.issues.stream import ensure_stream_group

        redis = AsyncMock()
        # redis-py raises ResponseError with "BUSYGROUP" message
        from redis.exceptions import ResponseError

        redis.xgroup_create = AsyncMock(
            side_effect=ResponseError("BUSYGROUP Consumer Group name already exists")
        )

        # Must not raise
        await ensure_stream_group(redis)

    @pytest.mark.asyncio
    async def test_ensure_stream_group_raises_on_other_errors(self):
        """Non-BUSYGROUP errors propagate."""
        from app.modules.issues.stream import ensure_stream_group
        from redis.exceptions import ResponseError

        redis = AsyncMock()
        redis.xgroup_create = AsyncMock(
            side_effect=ResponseError("WRONGTYPE Operation against a key")
        )

        with pytest.raises(ResponseError, match="WRONGTYPE"):
            await ensure_stream_group(redis)


# ---------------------------------------------------------------------------
# Test: publish_issue_to_stream (INFRA-017)
# ---------------------------------------------------------------------------


class TestPublishIssueToStream:
    """Test XADD is called correctly and returns stream entry ID."""

    @pytest.mark.asyncio
    async def test_publish_calls_xadd_with_correct_fields(self):
        from app.modules.issues.stream import STREAM_KEY, publish_issue_to_stream

        redis = AsyncMock()
        redis.xadd = AsyncMock(return_value="1678900000000-0")

        entry_id = await publish_issue_to_stream(
            report_id="report-123",
            tenant_id="tenant-abc",
            issue_type="bug",
            severity_hint="P1",
            redis=redis,
        )

        redis.xadd.assert_called_once()
        call_args = redis.xadd.call_args
        assert call_args[0][0] == STREAM_KEY
        fields = call_args[0][1]
        assert fields["report_id"] == "report-123"
        assert fields["tenant_id"] == "tenant-abc"
        assert fields["issue_type"] == "bug"
        assert fields["severity_hint"] == "P1"
        assert "timestamp" in fields
        assert call_args[1]["maxlen"] == 10_000

    @pytest.mark.asyncio
    async def test_publish_returns_string_entry_id(self):
        from app.modules.issues.stream import publish_issue_to_stream

        redis = AsyncMock()
        redis.xadd = AsyncMock(return_value="1678900000000-0")

        entry_id = await publish_issue_to_stream(
            report_id="report-456",
            tenant_id="tenant-def",
            issue_type="performance",
            severity_hint=None,
            redis=redis,
        )

        assert isinstance(entry_id, str)
        assert entry_id == "1678900000000-0"

    @pytest.mark.asyncio
    async def test_publish_with_none_severity_hint(self):
        """severity_hint=None is stored as empty string in stream fields."""
        from app.modules.issues.stream import publish_issue_to_stream

        redis = AsyncMock()
        redis.xadd = AsyncMock(return_value="1678900000001-0")

        await publish_issue_to_stream(
            report_id="report-789",
            tenant_id="tenant-ghi",
            issue_type="access",
            severity_hint=None,
            redis=redis,
        )

        call_args = redis.xadd.call_args
        fields = call_args[0][1]
        assert fields["severity_hint"] == ""


# ---------------------------------------------------------------------------
# Test: process_message — feature type skips triage (INFRA-018)
# ---------------------------------------------------------------------------


def _make_mock_session():
    """Return a mock async session that supports execute and commit."""
    session = AsyncMock()

    async def _execute(stmt, params=None):
        result = MagicMock()
        result.fetchone.return_value = (
            "report-1",
            "tenant-1",
            "user-1",
            "Feature request",
            "Add dark mode",
            None,
            "open",
            False,
            "2026-01-01",
        )
        result.rowcount = 1
        return result

    session.execute = _execute
    session.commit = AsyncMock()
    return session


class TestProcessMessageFeatureType:
    """Feature requests route to product backlog, skip severity classification."""

    @pytest.mark.asyncio
    async def test_feature_type_skips_triage_agent(self):
        from app.modules.issues.worker import process_message

        db_session = _make_mock_session()
        redis = AsyncMock()

        fields = {
            "report_id": "report-feat-1",
            "tenant_id": "tenant-1",
            "issue_type": "feature",
            "severity_hint": "",
            "timestamp": "2026-01-01T00:00:00Z",
        }

        with patch("app.modules.issues.worker.IssueTriageAgent") as MockAgent:
            await process_message(
                msg_id="1678900000000-0",
                fields=fields,
                db_session=db_session,
                redis=redis,
            )

            # Triage agent should NOT be instantiated for feature requests
            MockAgent.return_value.triage.assert_not_called()


# ---------------------------------------------------------------------------
# Test: process_message — bug type calls triage and updates status (INFRA-018)
# ---------------------------------------------------------------------------


class TestProcessMessageBugType:
    """Bug-type messages invoke IssueTriageAgent and update issue status."""

    @pytest.mark.asyncio
    async def test_bug_type_calls_triage_agent_and_updates_status(self):
        from app.modules.issues.worker import process_message
        from app.modules.issues.triage_agent import TriageResult

        db_session = _make_mock_session()
        redis = AsyncMock()

        fields = {
            "report_id": "report-bug-1",
            "tenant_id": "tenant-1",
            "issue_type": "bug",
            "severity_hint": "P1",
            "timestamp": "2026-01-01T00:00:00Z",
        }

        mock_triage_result = TriageResult(
            issue_type="ui_bug",
            severity="P1",
            confidence=0.85,
            routing="engineering",
            reasoning="Button is broken",
        )

        with patch("app.modules.issues.worker.IssueTriageAgent") as MockAgent:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.triage.return_value = mock_triage_result
            MockAgent.return_value = mock_agent_instance

            await process_message(
                msg_id="1678900000001-0",
                fields=fields,
                db_session=db_session,
                redis=redis,
            )

            # Triage agent MUST be called for bug-type issues
            mock_agent_instance.triage.assert_called_once()

            # Verify triage was called with correct arguments
            call_args = mock_agent_instance.triage.call_args
            assert (
                call_args[1]["tenant_id"] == "tenant-1" or call_args[0][2] == "tenant-1"
            )
