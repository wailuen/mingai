"""
Unit tests for PA-032: Tool health monitoring job.

Tests the core state-machine logic: healthy → degraded → unavailable → healthy.
P1 issue creation and auto-close on state transitions.

Tier 1: Fast, isolated. AsyncMock + direct function calls (no HTTP server).
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.platform.tool_health_job import (
    _DEGRADED_THRESHOLD,
    _UNAVAILABLE_THRESHOLD,
    _failure_counts,
    _handle_tool_result,
    run_tool_health_job,
)

TOOL_ID = str(uuid.uuid4())
TOOL_NAME = "test-tool"


def _make_db(call_responses: list):
    """Build a mock AsyncSession where each execute() call returns the next item.

    Each item in call_responses is either:
      - None → fetchone/fetchall/scalar all return None/[]
      - a single row tuple → fetchone() returns it, fetchall() returns [it]
      - a list of rows → fetchall() returns it, fetchone() returns rows[0] or None
    """
    mock_session = MagicMock()
    call_index = 0

    async def _execute(*args, **kwargs):
        nonlocal call_index
        idx = call_index
        call_index += 1
        mock_result = MagicMock()
        if idx >= len(call_responses):
            mock_result.fetchone.return_value = None
            mock_result.fetchall.return_value = []
            mock_result.scalar.return_value = None
            return mock_result
        response = call_responses[idx]
        if response is None:
            mock_result.fetchone.return_value = None
            mock_result.fetchall.return_value = []
            mock_result.scalar.return_value = None
        elif isinstance(response, list):
            mock_result.fetchall.return_value = response
            mock_result.fetchone.return_value = response[0] if response else None
        else:
            mock_result.fetchone.return_value = response
            mock_result.fetchall.return_value = [response]
        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()
    return mock_session


@pytest.fixture(autouse=True)
def reset_failure_counts():
    """Reset global failure counter before each test."""
    _failure_counts.clear()
    yield
    _failure_counts.clear()


class TestHandleToolResult:
    """Unit tests for _handle_tool_result directly."""

    @pytest.mark.asyncio
    async def test_success_resets_counter(self):
        _failure_counts[TOOL_ID] = 5
        db = _make_db([None, None, None])  # UPDATE, open_issue check, audit_log
        new_status = await _handle_tool_result(
            db, TOOL_ID, TOOL_NAME, "degraded", is_healthy=True
        )
        assert new_status == "healthy"
        assert _failure_counts[TOOL_ID] == 0

    @pytest.mark.asyncio
    async def test_success_when_already_healthy_returns_none(self):
        _failure_counts[TOOL_ID] = 0
        db = _make_db([])
        new_status = await _handle_tool_result(
            db, TOOL_ID, TOOL_NAME, "healthy", is_healthy=True
        )
        assert new_status is None
        assert _failure_counts[TOOL_ID] == 0

    @pytest.mark.asyncio
    async def test_degraded_after_3_consecutive_failures(self):
        _failure_counts[TOOL_ID] = _DEGRADED_THRESHOLD - 1
        # On exactly the 3rd failure: UPDATE + audit_log
        db = _make_db([None, None])
        new_status = await _handle_tool_result(
            db, TOOL_ID, TOOL_NAME, "healthy", is_healthy=False
        )
        assert new_status == "degraded"
        assert _failure_counts[TOOL_ID] == _DEGRADED_THRESHOLD

    @pytest.mark.asyncio
    async def test_no_state_change_before_degraded_threshold(self):
        """2 failures should not trigger degraded."""
        _failure_counts[TOOL_ID] = _DEGRADED_THRESHOLD - 2
        db = _make_db([])
        new_status = await _handle_tool_result(
            db, TOOL_ID, TOOL_NAME, "healthy", is_healthy=False
        )
        assert new_status is None
        assert _failure_counts[TOOL_ID] == _DEGRADED_THRESHOLD - 1

    @pytest.mark.asyncio
    async def test_unavailable_after_10_consecutive_failures(self):
        _failure_counts[TOOL_ID] = _UNAVAILABLE_THRESHOLD - 1
        # On exactly 10th: UPDATE + open_issue_check + CREATE_P1_ISSUE + audit_log
        # open issue check returns None (no existing)
        db = _make_db([None, None, None, None])
        new_status = await _handle_tool_result(
            db, TOOL_ID, TOOL_NAME, "degraded", is_healthy=False
        )
        assert new_status == "unavailable"
        assert _failure_counts[TOOL_ID] == _UNAVAILABLE_THRESHOLD

    @pytest.mark.asyncio
    async def test_no_duplicate_p1_when_issue_already_open(self):
        """If a P1 issue already exists, do NOT create another."""
        _failure_counts[TOOL_ID] = _UNAVAILABLE_THRESHOLD - 1
        existing_issue = (uuid.uuid4(),)
        # UPDATE + open_issue_check (returns existing) + audit_log
        # CREATE_P1_ISSUE should NOT be called
        db = _make_db([None, existing_issue, None])
        new_status = await _handle_tool_result(
            db, TOOL_ID, TOOL_NAME, "degraded", is_healthy=False
        )
        assert new_status == "unavailable"
        # execute was called 3 times (UPDATE + check + audit), not 4 (no INSERT)
        assert db.execute.call_count == 3

    @pytest.mark.asyncio
    async def test_recovery_closes_open_p1_issue(self):
        """When tool recovers, open P1 issue should be auto-closed."""
        _failure_counts[TOOL_ID] = 15
        existing_issue = (uuid.uuid4(),)
        # UPDATE (healthy) + open_issue_check (returns existing) + CLOSE + audit_log
        db = _make_db([None, existing_issue, None, None])
        new_status = await _handle_tool_result(
            db, TOOL_ID, TOOL_NAME, "unavailable", is_healthy=True
        )
        assert new_status == "healthy"
        assert _failure_counts[TOOL_ID] == 0


class TestRunToolHealthJob:
    """Unit tests for the full job function."""

    @pytest.mark.asyncio
    async def test_empty_catalog_returns_zero_checked(self):
        db = _make_db(
            [
                None,  # set_config scope
                None,  # set_config tenant_id
                [],  # LIST_TOOLS (empty)
            ]
        )
        summary = await run_tool_health_job(db)
        assert summary["checked"] == 0
        assert summary["errors"] == 0

    @pytest.mark.asyncio
    async def test_healthy_tool_no_status_change(self):
        tool_row = (uuid.UUID(TOOL_ID), TOOL_NAME, "healthy", "https://tool.io/health")
        db = _make_db(
            [
                None,  # set_config scope
                None,  # set_config tenant_id
                [tool_row],  # LIST_TOOLS
            ]
        )
        with patch(
            "app.modules.platform.tool_health_job._ping_tool",
            new=AsyncMock(return_value=True),
        ):
            summary = await run_tool_health_job(db)
        assert summary["checked"] == 1
        assert summary["degraded"] == 0
        assert summary["recovered"] == 0

    @pytest.mark.asyncio
    async def test_failing_tool_after_3_failures_becomes_degraded(self):
        _failure_counts[TOOL_ID] = _DEGRADED_THRESHOLD - 1
        tool_row = (uuid.UUID(TOOL_ID), TOOL_NAME, "healthy", "https://tool.io/health")
        # set_config ×2, LIST_TOOLS, UPDATE (degraded), audit_log
        db = _make_db([None, None, [tool_row], None, None])
        with patch(
            "app.modules.platform.tool_health_job._ping_tool",
            new=AsyncMock(return_value=False),
        ):
            summary = await run_tool_health_job(db)
        assert summary["checked"] == 1
        assert summary["degraded"] == 1

    @pytest.mark.asyncio
    async def test_error_in_one_tool_does_not_abort_others(self):
        tool1 = (uuid.UUID(TOOL_ID), "tool-a", "healthy", "https://a.io/health")
        tool2_id = str(uuid.uuid4())
        tool2 = (uuid.UUID(tool2_id), "tool-b", "healthy", "https://b.io/health")
        db = _make_db([None, None, [tool1, tool2]])

        async def _flaky_ping(url: str) -> bool:
            if "a.io" in url:
                raise ConnectionError("network down")
            return True  # tool-b succeeds

        with patch(
            "app.modules.platform.tool_health_job._ping_tool",
            new=_flaky_ping,
        ):
            summary = await run_tool_health_job(db)
        assert summary["errors"] == 1
        assert summary["checked"] == 1  # tool-b counted

    @pytest.mark.asyncio
    async def test_recovered_tool_counted(self):
        _failure_counts[TOOL_ID] = 5
        tool_row = (uuid.UUID(TOOL_ID), TOOL_NAME, "degraded", "https://tool.io/health")
        # set_config ×2, LIST_TOOLS, UPDATE, open_issue_check (None), audit_log
        db = _make_db([None, None, [tool_row], None, None, None])
        with patch(
            "app.modules.platform.tool_health_job._ping_tool",
            new=AsyncMock(return_value=True),
        ):
            summary = await run_tool_health_job(db)
        assert summary["checked"] == 1
        assert summary["recovered"] == 1
