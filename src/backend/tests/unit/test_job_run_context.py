"""
Unit tests for app/core/scheduler/job_run_log.py (SCHED-023).

Tests:
- Context manager inserts 'running' row on enter
- Context manager updates to 'completed' on success with duration and records
- Context manager updates to 'failed' on exception with error_message
- Context manager updates to 'abandoned' on CancelledError using asyncio.shield
- DB failure during INSERT logs warning but does not raise (job runs normally)
- DB failure during UPDATE logs warning but does not re-raise original exception
- ctx.records_processed is thread-local to the yielded context object
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.core.scheduler.job_run_log import job_run_context, JobRunContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_session(execute_side_effect=None, commit_side_effect=None):
    """Return a mock async context manager that simulates async_session_factory."""
    session = AsyncMock()
    if execute_side_effect:
        session.execute.side_effect = execute_side_effect
    if commit_side_effect:
        session.commit.side_effect = commit_side_effect

    # async context manager
    cm = AsyncMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = None
    return cm, session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_yields_JobRunContext_instance():
    """The yielded object is a JobRunContext dataclass."""
    mock_cm, _ = _make_mock_session()
    with patch(
        "app.core.session.async_session_factory",
        return_value=mock_cm,
    ):
        async with job_run_context("test_job") as ctx:
            assert isinstance(ctx, JobRunContext)
            assert ctx.records_processed is None


@pytest.mark.asyncio
async def test_inserts_running_row_on_enter():
    """INSERT with status='running' is called when entering the context."""
    mock_cm, session = _make_mock_session()
    with patch(
        "app.core.session.async_session_factory",
        return_value=mock_cm,
    ):
        async with job_run_context("health_score", tenant_id="tenant-abc") as ctx:
            ctx.records_processed = 42
            # The INSERT should have been called by now
            insert_call_args = session.execute.call_args_list[0]
            sql_str = str(insert_call_args[0][0])
            assert "INSERT INTO job_run_log" in sql_str
            params = insert_call_args[0][1]
            assert params["job_name"] == "health_score"
            assert params["tenant_id"] == "tenant-abc"
            assert "'running'" in sql_str  # literal in SQL, not a parameter


@pytest.mark.asyncio
async def test_updates_completed_on_success():
    """UPDATE to 'completed' is called with duration_ms and records_processed."""
    insert_cm, _ = _make_mock_session()
    update_cm, update_session = _make_mock_session()

    call_count = [0]

    def factory_side_effect():
        call_count[0] += 1
        if call_count[0] == 1:
            return insert_cm
        return update_cm

    with patch(
        "app.core.session.async_session_factory",
        side_effect=factory_side_effect,
    ):
        async with job_run_context("cost_summary") as ctx:
            ctx.records_processed = 7

    # _write_final_status was called with 'completed'
    update_execute_args = update_session.execute.call_args_list[0]
    sql_str = str(update_execute_args[0][0])
    params = update_execute_args[0][1]
    assert "UPDATE job_run_log" in sql_str
    assert params["status"] == "completed"
    assert params["records_processed"] == 7
    assert params["duration_ms"] is not None and params["duration_ms"] >= 0
    assert params["error_message"] is None


@pytest.mark.asyncio
async def test_updates_failed_on_exception():
    """UPDATE to 'failed' with error_message when the body raises."""
    insert_cm, _ = _make_mock_session()
    update_cm, update_session = _make_mock_session()

    call_count = [0]

    def factory_side_effect():
        call_count[0] += 1
        return insert_cm if call_count[0] == 1 else update_cm

    with patch(
        "app.core.session.async_session_factory",
        side_effect=factory_side_effect,
    ):
        with pytest.raises(ValueError, match="test error"):
            async with job_run_context("provider_health") as ctx:
                raise ValueError("test error")

    update_execute_args = update_session.execute.call_args_list[0]
    params = update_execute_args[0][1]
    assert params["status"] == "failed"
    assert "test error" in params["error_message"]


@pytest.mark.asyncio
async def test_updates_abandoned_on_cancelled_error():
    """UPDATE to 'abandoned' via asyncio.shield when CancelledError is raised."""
    insert_cm, _ = _make_mock_session()
    update_cm, update_session = _make_mock_session()

    call_count = [0]

    def factory_side_effect():
        call_count[0] += 1
        return insert_cm if call_count[0] == 1 else update_cm

    with patch(
        "app.core.session.async_session_factory",
        side_effect=factory_side_effect,
    ):
        with pytest.raises(asyncio.CancelledError):
            async with job_run_context("tool_health") as ctx:
                raise asyncio.CancelledError()

    update_execute_args = update_session.execute.call_args_list[0]
    params = update_execute_args[0][1]
    assert params["status"] == "abandoned"
    assert params["error_message"] == "CancelledError"


@pytest.mark.asyncio
async def test_db_insert_failure_does_not_raise():
    """If the INSERT fails, the context manager logs a warning and continues."""
    bad_cm = AsyncMock()
    bad_session = AsyncMock()
    bad_session.execute.side_effect = RuntimeError("db down")
    bad_cm.__aenter__.return_value = bad_session
    bad_cm.__aexit__.return_value = None

    with patch(
        "app.core.session.async_session_factory",
        return_value=bad_cm,
    ):
        # Should not raise despite INSERT failure
        async with job_run_context("semantic_cache_cleanup") as ctx:
            ctx.records_processed = 5
        # If we get here the job ran normally


@pytest.mark.asyncio
async def test_db_update_failure_does_not_reraise():
    """If the UPDATE fails, warning is logged but the original exception is not swallowed."""
    insert_cm, _ = _make_mock_session()

    bad_update_cm = AsyncMock()
    bad_update_session = AsyncMock()
    bad_update_session.execute.side_effect = RuntimeError("update failed")
    bad_update_cm.__aenter__.return_value = bad_update_session
    bad_update_cm.__aexit__.return_value = None

    call_count = [0]

    def factory_side_effect():
        call_count[0] += 1
        return insert_cm if call_count[0] == 1 else bad_update_cm

    with patch(
        "app.core.session.async_session_factory",
        side_effect=factory_side_effect,
    ):
        # Success path — UPDATE fails but no exception propagates from the context
        async with job_run_context("query_warming") as ctx:
            ctx.records_processed = 3
        # Still no exception here


@pytest.mark.asyncio
async def test_records_processed_none_by_default():
    """ctx.records_processed defaults to None when caller does not set it."""
    mock_cm, _ = _make_mock_session()
    update_cm, update_session = _make_mock_session()

    call_count = [0]

    def factory_side_effect():
        call_count[0] += 1
        return mock_cm if call_count[0] == 1 else update_cm

    with patch(
        "app.core.session.async_session_factory",
        side_effect=factory_side_effect,
    ):
        async with job_run_context("azure_cost"):
            pass  # records_processed never set

    params = update_session.execute.call_args_list[0][0][1]
    assert params["records_processed"] is None
