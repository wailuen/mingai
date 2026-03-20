"""
SCHED-035: H-07 regression test — run_tool_health_scheduler is wired in main.py.

H-07 was the bug where tool_health_job.py used an in-process dict for failure
counters, which was reset on every pod restart.  The fix (SCHED-008) replaced
the in-process dict with Redis counters AND introduced run_tool_health_scheduler()
as the asyncio-native entry point (replacing APScheduler).

This test verifies that main.py:
  1. Imports run_tool_health_scheduler from the correct module
  2. Calls asyncio.create_task() with it during app startup
  3. Cancels the task cleanly during shutdown

These assurances guarantee that:
  - No APScheduler remnant is used for tool health
  - The scheduler IS started on every pod launch (H-07 cannot regress silently)
"""
from __future__ import annotations

import ast
import inspect
import importlib
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Static analysis: verify the import and wiring exist in main.py source
# ---------------------------------------------------------------------------

MAIN_PY = Path(__file__).parent.parent.parent / "app" / "main.py"


def _main_py_source() -> str:
    return MAIN_PY.read_text()


def test_main_imports_run_tool_health_scheduler():
    """main.py must import run_tool_health_scheduler from tool_health_job."""
    src = _main_py_source()
    assert "run_tool_health_scheduler" in src, (
        "run_tool_health_scheduler not found in main.py — H-07 regression: "
        "tool health scheduler would not be started on pod launch."
    )
    assert "tool_health_job" in src, (
        "tool_health_job import not found in main.py."
    )


def test_main_creates_task_for_tool_health():
    """main.py must call asyncio.create_task() with run_tool_health_scheduler."""
    src = _main_py_source()
    # Must see create_task called with the scheduler function
    assert "create_task(run_tool_health_scheduler())" in src, (
        "asyncio.create_task(run_tool_health_scheduler()) not found in main.py — "
        "the tool health job would not run."
    )


def test_main_cancels_tool_health_task_on_shutdown():
    """main.py must cancel _tool_health_task in the shutdown block."""
    src = _main_py_source()
    assert "_tool_health_task" in src, (
        "_tool_health_task variable not found in main.py."
    )
    # Both cancel() and the task variable should appear together
    assert "_tool_health_task.cancel()" in src, (
        "_tool_health_task.cancel() not found in main.py — "
        "tool health task would leak on shutdown."
    )


def test_no_apscheduler_import_in_tool_health_job():
    """
    tool_health_job.py must not import APScheduler.
    APScheduler was the root cause of H-07 (in-process state + wrong lifecycle).
    Comments referencing APScheduler for historical context are fine;
    actual import statements are not.
    """
    tool_health_path = MAIN_PY.parent / "modules" / "platform" / "tool_health_job.py"
    src = tool_health_path.read_text()
    # Filter out comment and docstring lines before checking for apscheduler imports
    non_comment_lines = [
        line for line in src.splitlines()
        if not line.lstrip().startswith("#") and '"""' not in line and "'''" not in line
    ]
    non_comment_src = "\n".join(non_comment_lines)
    assert "import apscheduler" not in non_comment_src.lower(), (
        "APScheduler import statement found in tool_health_job.py — "
        "H-07 regression: job would use in-process scheduler."
    )
    assert "from apscheduler" not in non_comment_src.lower(), (
        "APScheduler import statement found in tool_health_job.py — "
        "H-07 regression: job would use in-process scheduler."
    )


def test_run_tool_health_scheduler_is_async():
    """run_tool_health_scheduler must be an async function (asyncio-native)."""
    from app.modules.platform.tool_health_job import run_tool_health_scheduler
    assert inspect.iscoroutinefunction(run_tool_health_scheduler), (
        "run_tool_health_scheduler is not async — "
        "it cannot be used with asyncio.create_task()."
    )


def test_no_apscheduler_in_pyproject():
    """APScheduler must not appear in pyproject.toml dependencies."""
    pyproject = MAIN_PY.parent.parent.parent.parent / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text().lower()
        assert "apscheduler" not in content, (
            "APScheduler still listed in pyproject.toml — "
            "dependency not fully removed (SCHED-021)."
        )
