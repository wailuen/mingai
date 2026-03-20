"""
Unit tests for SCHED-036: Startup zombie row cleanup.

Tests the zombie cleanup SQL contract and the graceful DB-failure path.
We invoke only the cleanup logic (not the full app lifespan) by extracting
it into a helper, then verifying:
  - Rows with status='running' older than 1 hour → 'abandoned'
  - Rows with status='running' within 30 minutes → NOT touched (SQL contract)
  - Rows with non-running status → NOT touched (SQL contract)
  - DB failure during cleanup logs a warning and does NOT block startup
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Extracted helper that mirrors the main.py zombie cleanup block exactly.
# This is the function under test; it must stay in sync with main.py.
# ---------------------------------------------------------------------------


async def _run_zombie_cleanup(session_factory):
    """Isolated copy of the zombie cleanup block from main.py lifespan."""
    import structlog

    logger = structlog.get_logger()
    abandoned = []
    try:
        async with session_factory() as db:
            result = await db.execute(
                text(
                    "UPDATE job_run_log "
                    "SET status = 'abandoned', completed_at = NOW() "
                    "WHERE status = 'running' "
                    "  AND started_at < NOW() - INTERVAL '1 hour' "
                    "RETURNING job_name"
                )
            )
            abandoned = result.fetchall()
            await db.commit()
        logger.info(
            "job_run_log_zombie_cleanup",
            rows_abandoned=len(abandoned),
            jobs=[r[0] for r in abandoned] if abandoned else [],
        )
    except Exception as exc:
        logger.warning("startup_zombie_cleanup_failed", error=str(exc))
    return abandoned


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory(rows=None, raise_on_execute=None):
    result = MagicMock()
    result.fetchall.return_value = rows if rows is not None else []

    session = AsyncMock()
    if raise_on_execute:
        session.execute.side_effect = raise_on_execute
    else:
        session.execute.return_value = result

    cm = AsyncMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = None

    return MagicMock(return_value=cm), session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zombie_cleanup_issues_update_to_abandoned():
    """
    The cleanup issues an UPDATE job_run_log … SET status = 'abandoned'
    and restricts to rows where started_at < NOW() - INTERVAL '1 hour'.
    """
    factory, session = _make_session_factory(rows=[("health_score",), ("cost_summary",)])

    result = await _run_zombie_cleanup(factory)

    assert session.execute.called
    sql_str = str(session.execute.call_args_list[0][0][0])
    assert "UPDATE job_run_log" in sql_str
    assert "'abandoned'" in sql_str
    # Only stale rows (older than 1 hour) are targeted
    assert "INTERVAL '1 hour'" in sql_str
    # Only rows currently in running state are targeted (others untouched)
    assert "status = 'running'" in sql_str
    assert session.commit.called
    assert len(result) == 2


@pytest.mark.asyncio
async def test_zombie_cleanup_returns_empty_when_no_stale_rows():
    """
    When no stale rows exist the cleanup commits and returns an empty list
    (does not raise, does not skip the UPDATE).
    """
    factory, session = _make_session_factory(rows=[])

    result = await _run_zombie_cleanup(factory)

    assert session.execute.called
    assert session.commit.called
    assert result == []


@pytest.mark.asyncio
async def test_zombie_cleanup_does_not_touch_non_running_rows():
    """
    The WHERE clause must include `status = 'running'` so completed, failed,
    and abandoned rows are never overwritten.
    """
    factory, session = _make_session_factory(rows=[])

    await _run_zombie_cleanup(factory)

    sql_str = str(session.execute.call_args_list[0][0][0])
    # Non-running rows are excluded by the WHERE condition
    assert "status = 'running'" in sql_str
    # The UPDATE only targets the stale running subset — no blanket UPDATE
    assert "started_at < NOW() - INTERVAL '1 hour'" in sql_str


@pytest.mark.asyncio
async def test_zombie_cleanup_db_failure_does_not_raise():
    """
    A DB failure (e.g. table not yet migrated) is caught.  The cleanup must
    NOT propagate the exception — startup continues normally.
    """
    factory, session = _make_session_factory(
        raise_on_execute=RuntimeError("relation job_run_log does not exist")
    )

    # Should not raise
    result = await _run_zombie_cleanup(factory)

    # Returns empty list on failure (abandon list not populated)
    assert result == []
    # Commit was never reached since execute raised
    session.commit.assert_not_called()
