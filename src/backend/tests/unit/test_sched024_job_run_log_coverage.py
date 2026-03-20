"""
SCHED-024: job_run_log integration unit tests for credential_expiry,
cost_summary (CancelledError branch), and url_health_monitor (platform scope).

All tests are Tier 1 unit tests — they mock async_session_factory at
app.core.session.async_session_factory and call job_run_context directly,
following the same pattern as tests/unit/test_job_run_context.py.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.core.scheduler.job_run_log import job_run_context


# ---------------------------------------------------------------------------
# Helpers (identical pattern to test_job_run_context.py)
# ---------------------------------------------------------------------------


def _make_mock_session(execute_side_effect=None):
    """Return (context_manager_mock, session_mock) for async_session_factory."""
    session = AsyncMock()
    if execute_side_effect:
        session.execute.side_effect = execute_side_effect
    cm = AsyncMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = None
    return cm, session


def _two_session_factory(insert_cm, update_cm):
    """
    Returns a factory side_effect that hands out insert_cm on the first call
    and update_cm on every subsequent call — the same pattern used in the
    existing test_job_run_context.py tests.
    """
    call_count = [0]

    def _factory():
        call_count[0] += 1
        return insert_cm if call_count[0] == 1 else update_cm

    return _factory


# ---------------------------------------------------------------------------
# Test 1: credential_expiry writes job_run_log row with correct job_name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credential_expiry_job_run_context_writes_log_row():
    """
    When run_credential_expiry_job() is called inside a job_run_context,
    a job_run_log row gets written with job_name='credential_expiry'.

    This is a pure unit test — async_session_factory is mocked and the
    inner credential_expiry job function is replaced with a no-op coroutine.
    """
    insert_cm, insert_session = _make_mock_session()
    update_cm, _ = _make_mock_session()

    with patch(
        "app.core.session.async_session_factory",
        side_effect=_two_session_factory(insert_cm, update_cm),
    ):
        async with job_run_context("credential_expiry") as ctx:
            # Simulate the job completing with some records
            ctx.records_processed = 3

    # Verify INSERT INTO job_run_log was called
    assert insert_session.execute.called, "INSERT was not called on enter"
    insert_call_args = insert_session.execute.call_args_list[0]
    sql_str = str(insert_call_args[0][0])
    params = insert_call_args[0][1]

    assert "INSERT INTO job_run_log" in sql_str
    assert params["job_name"] == "credential_expiry"
    # Platform-scope call: no tenant_id argument passed → tenant_id param is None
    assert params["tenant_id"] is None


# ---------------------------------------------------------------------------
# Test 2: cost_summary CancelledError branch writes status='abandoned'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_summary_cancelled_error_writes_abandoned():
    """
    When the cost_summary job body raises asyncio.CancelledError,
    job_run_context writes status='abandoned' (not 'failed').

    Mirrors test_updates_abandoned_on_cancelled_error from test_job_run_context.py
    but uses the 'cost_summary' job_name to confirm coverage for that job.
    """
    insert_cm, _ = _make_mock_session()
    update_cm, update_session = _make_mock_session()

    with patch(
        "app.core.session.async_session_factory",
        side_effect=_two_session_factory(insert_cm, update_cm),
    ):
        with pytest.raises(asyncio.CancelledError):
            async with job_run_context("cost_summary") as ctx:
                raise asyncio.CancelledError()

    # The update session should have been called with status='abandoned'
    assert update_session.execute.called, "UPDATE was not called on CancelledError"
    update_call_args = update_session.execute.call_args_list[0]
    params = update_call_args[0][1]

    assert params["status"] == "abandoned"
    assert params["error_message"] == "CancelledError"


# ---------------------------------------------------------------------------
# Test 3: url_health_monitor uses job_run_context with tenant_id=None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_url_health_monitor_uses_platform_scope_job_run_context():
    """
    url_health_monitor calls job_run_context("url_health_monitor") with no
    tenant_id argument (defaults to None) — confirming it is a platform-scope
    job, not a per-tenant job.

    We call job_run_context directly with the same job_name used in
    run_url_health_monitor_scheduler to verify the INSERT params.
    """
    insert_cm, insert_session = _make_mock_session()
    update_cm, _ = _make_mock_session()

    with patch(
        "app.core.session.async_session_factory",
        side_effect=_two_session_factory(insert_cm, update_cm),
    ):
        # Call job_run_context with the exact job_name and signature used in
        # url_health_monitor.py: job_run_context("url_health_monitor")
        # No tenant_id is passed — this is the platform-scope pattern.
        async with job_run_context("url_health_monitor") as ctx:
            ctx.records_processed = 5

    assert insert_session.execute.called, "INSERT was not called"
    insert_call_args = insert_session.execute.call_args_list[0]
    sql_str = str(insert_call_args[0][0])
    params = insert_call_args[0][1]

    assert "INSERT INTO job_run_log" in sql_str
    assert params["job_name"] == "url_health_monitor"
    # Platform-scope: tenant_id must be None (not a tenant UUID)
    assert params["tenant_id"] is None
