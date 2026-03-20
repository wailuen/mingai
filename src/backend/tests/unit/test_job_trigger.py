"""
Unit tests for TODO-13C: POST /api/v1/platform/jobs/{job_name}/trigger.

Tier 1: Fast, isolated. DB, auth, and job functions are mocked.

6 scenarios:
  1. Happy path — known job, not running → 202 triggered.
  2. Unknown job name → 404.
  3. Job already running in job_run_log → 409.
  4. KNOWN_JOB_NAMES contains all 13 expected names.
  5. Background task is added to _background_tasks set (GC prevention).
  6. Done callback removes task from _background_tasks set.
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.platform.job_trigger import (
    KNOWN_JOB_NAMES,
    TriggerResponse,
    _background_tasks,
    trigger_job,
)

PLATFORM_ADMIN_USER_ID = str(uuid.uuid4())


def _make_platform_user():
    user = MagicMock()
    user.id = PLATFORM_ADMIN_USER_ID
    return user


def _make_db_no_running():
    """Mock session that returns no running rows."""
    db = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = None

    async def _execute(*args, **kwargs):
        return result

    db.execute = _execute

    async def _aenter(*args, **kwargs):
        return db

    async def _aexit(*args, **kwargs):
        pass

    cm = MagicMock()
    cm.__aenter__ = _aenter
    cm.__aexit__ = _aexit
    return cm


def _make_db_with_running():
    """Mock session that returns a running row."""
    db = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = (str(uuid.uuid4()),)

    async def _execute(*args, **kwargs):
        return result

    db.execute = _execute

    async def _aenter(*args, **kwargs):
        return db

    async def _aexit(*args, **kwargs):
        pass

    cm = MagicMock()
    cm.__aenter__ = _aenter
    cm.__aexit__ = _aexit
    return cm


# ---------------------------------------------------------------------------
# Scenario 1: Happy path — known job, not running → 202 triggered
# ---------------------------------------------------------------------------


def _make_redis_no_lock():
    """Mock Redis that allows lock acquisition (SETNX returns True)."""
    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    return redis


@pytest.mark.asyncio
async def test_trigger_job_happy_path():
    user = _make_platform_user()
    cm = _make_db_no_running()

    # Patch async_session_factory, get_redis, and asyncio.create_task so the
    # actual job function and infrastructure are never called.
    with patch(
        "app.modules.platform.job_trigger.async_session_factory", return_value=cm
    ):
        with patch(
            "app.modules.platform.job_trigger.get_redis",
            return_value=_make_redis_no_lock(),
        ):
            mock_task = MagicMock(spec=asyncio.Task)
            mock_task.add_done_callback = MagicMock()
            with patch("asyncio.create_task", return_value=mock_task):
                response = await trigger_job(job_name="health_score", current_user=user)

    assert isinstance(response, TriggerResponse)
    assert response.job_name == "health_score"
    assert response.status == "triggered"
    assert response.run_id is None


# ---------------------------------------------------------------------------
# Scenario 2: Unknown job name → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_job_unknown_name():
    from fastapi import HTTPException

    user = _make_platform_user()

    with pytest.raises(HTTPException) as exc_info:
        await trigger_job(job_name="nonexistent_job", current_user=user)

    assert exc_info.value.status_code == 404
    assert "nonexistent_job" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Scenario 3: Job already running → 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_job_already_running():
    from fastapi import HTTPException

    user = _make_platform_user()
    cm = _make_db_with_running()

    with patch(
        "app.modules.platform.job_trigger.async_session_factory", return_value=cm
    ):
        with pytest.raises(HTTPException) as exc_info:
            await trigger_job(job_name="health_score", current_user=user)

    assert exc_info.value.status_code == 409
    assert "already running" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Scenario 3b: Redis dispatch gate blocks concurrent duplicate triggers → 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_job_redis_gate_blocks_concurrent():
    from fastapi import HTTPException

    user = _make_platform_user()
    cm = _make_db_no_running()

    # SETNX returns None (falsy) — another request holds the dispatch key.
    locked_redis = MagicMock()
    locked_redis.set = AsyncMock(return_value=None)

    with patch(
        "app.modules.platform.job_trigger.async_session_factory", return_value=cm
    ):
        with patch(
            "app.modules.platform.job_trigger.get_redis", return_value=locked_redis
        ):
            with pytest.raises(HTTPException) as exc_info:
                await trigger_job(job_name="health_score", current_user=user)

    assert exc_info.value.status_code == 409
    assert "already running" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Scenario 4: KNOWN_JOB_NAMES contains all 13 expected names
# ---------------------------------------------------------------------------


def test_known_job_names_complete():
    expected = {
        "health_score",
        "cost_summary",
        "azure_cost",
        "cost_alert",
        "miss_signals",
        "credential_expiry",
        "query_warming",
        "semantic_cache_cleanup",
        "provider_health",
        "tool_health",
        "url_health_monitor",
        "har_approval_timeout",
        "agent_health",
    }
    assert KNOWN_JOB_NAMES == expected


# ---------------------------------------------------------------------------
# Scenario 5: Background task is added to _background_tasks set (GC prevention)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_job_task_added_to_background_set():
    user = _make_platform_user()
    cm = _make_db_no_running()

    captured_callbacks = []

    def _fake_add_done_callback(cb):
        captured_callbacks.append(cb)

    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.add_done_callback = _fake_add_done_callback

    with patch(
        "app.modules.platform.job_trigger.async_session_factory", return_value=cm
    ):
        with patch(
            "app.modules.platform.job_trigger.get_redis",
            return_value=_make_redis_no_lock(),
        ):
            with patch("asyncio.create_task", return_value=mock_task):
                # Snapshot the set size before
                size_before = len(_background_tasks)
                await trigger_job(job_name="cost_summary", current_user=user)
                size_after = len(_background_tasks)

    # Task was added
    assert size_after == size_before + 1
    assert mock_task in _background_tasks

    # Cleanup: simulate done callback removing it
    _background_tasks.discard(mock_task)


# ---------------------------------------------------------------------------
# Scenario 6: Done callback removes task from _background_tasks set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_job_done_callback_removes_task():
    user = _make_platform_user()
    cm = _make_db_no_running()

    stored_callback = None

    def _fake_add_done_callback(cb):
        nonlocal stored_callback
        stored_callback = cb

    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.add_done_callback = _fake_add_done_callback

    with patch(
        "app.modules.platform.job_trigger.async_session_factory", return_value=cm
    ):
        with patch(
            "app.modules.platform.job_trigger.get_redis",
            return_value=_make_redis_no_lock(),
        ):
            with patch("asyncio.create_task", return_value=mock_task):
                await trigger_job(job_name="query_warming", current_user=user)

    assert mock_task in _background_tasks
    assert stored_callback is not None

    # Simulate task completion — callback should remove it from the set
    stored_callback(mock_task)
    assert mock_task not in _background_tasks
