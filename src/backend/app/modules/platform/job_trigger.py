"""
TODO-13C: Platform Admin manual job trigger endpoint.

POST /api/v1/platform/jobs/{job_name}/trigger
Platform Admin scope only.

Validates job_name against KNOWN_JOB_NAMES, checks for an already-running
instance in job_run_log, then fires the job in a background asyncio.Task.
Returns 202 immediately — the caller must poll job history to see the outcome.
"""
import asyncio
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.core.dependencies import CurrentUser, require_platform_admin
from app.core.redis_client import get_redis
from app.core.scheduler import DistributedJobLock, job_run_context
from app.core.session import async_session_factory, get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/platform/jobs", tags=["platform"])

# All schedulable job names — must match the job names used in job_run_context calls.
KNOWN_JOB_NAMES: frozenset[str] = frozenset(
    {
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
)

# Module-level set that holds references to background tasks to prevent GC.
_background_tasks: set[asyncio.Task] = set()


# ---------------------------------------------------------------------------
# Per-job async wrappers
# ---------------------------------------------------------------------------


async def _run_health_score() -> None:
    from app.modules.platform.health_score_job import run_health_score_job

    async with job_run_context("health_score"):
        await run_health_score_job()


async def _run_cost_summary() -> None:
    from app.modules.platform.cost_summary_job import run_cost_summary_job

    async with job_run_context("cost_summary"):
        await run_cost_summary_job()


async def _run_azure_cost() -> None:
    from app.modules.platform.azure_cost_job import run_azure_cost_job

    async with job_run_context("azure_cost"):
        await run_azure_cost_job()


async def _run_cost_alert() -> None:
    from app.modules.platform.cost_alert_job import run_cost_alert_job

    async with job_run_context("cost_alert"):
        await run_cost_alert_job()


async def _run_miss_signals() -> None:
    from app.modules.glossary.miss_signals_job import run_miss_signals_job

    async with job_run_context("miss_signals"):
        await run_miss_signals_job()


async def _run_credential_expiry() -> None:
    from app.modules.documents.credential_expiry_job import run_credential_expiry_job

    async with job_run_context("credential_expiry"):
        await run_credential_expiry_job()


async def _run_query_warming() -> None:
    from app.modules.cache.query_warming import run_query_warming_job

    async with job_run_context("query_warming"):
        await run_query_warming_job()


async def _run_semantic_cache_cleanup() -> None:
    from app.core.cache.cleanup_job import _run_cleanup

    async with job_run_context("semantic_cache_cleanup") as ctx:
        deleted = await _run_cleanup()
        ctx.records_processed = deleted


async def _run_provider_health() -> None:
    from app.modules.platform.provider_health_job import run_provider_health_job

    async with job_run_context("provider_health"):
        await run_provider_health_job()


async def _run_tool_health() -> None:
    from app.modules.platform.tool_health_job import run_tool_health_job

    async with async_session_factory() as db:
        try:
            async with job_run_context("tool_health"):
                await run_tool_health_job(db)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def _run_url_health_monitor() -> None:
    from app.modules.registry.url_health_monitor import run_url_health_monitor

    async with job_run_context("url_health_monitor"):
        await run_url_health_monitor()


async def _run_approval_timeout() -> None:
    from app.modules.har.approval_timeout_job import run_approval_timeout_job

    async with async_session_factory() as db:
        try:
            async with job_run_context("har_approval_timeout"):
                await run_approval_timeout_job(db)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def _run_agent_health() -> None:
    from app.modules.har.health_monitor import AgentHealthMonitor

    async with async_session_factory() as db:
        try:
            async with job_run_context("agent_health") as ctx:
                result = await AgentHealthMonitor().run_once(db)
                ctx.records_processed = result.get("agents_checked")
            await db.commit()
        except Exception:
            await db.rollback()
            raise


# Dispatch map: job_name → zero-arg async callable
_JOB_DISPATCH: dict[str, object] = {
    "health_score": _run_health_score,
    "cost_summary": _run_cost_summary,
    "azure_cost": _run_azure_cost,
    "cost_alert": _run_cost_alert,
    "miss_signals": _run_miss_signals,
    "credential_expiry": _run_credential_expiry,
    "query_warming": _run_query_warming,
    "semantic_cache_cleanup": _run_semantic_cache_cleanup,
    "provider_health": _run_provider_health,
    "tool_health": _run_tool_health,
    "url_health_monitor": _run_url_health_monitor,
    "har_approval_timeout": _run_approval_timeout,
    "agent_health": _run_agent_health,
}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


class TriggerResponse(BaseModel):
    job_name: str
    run_id: Optional[str]
    status: str


@router.post("/{job_name}/trigger", response_model=TriggerResponse, status_code=202)
async def trigger_job(
    job_name: str,
    current_user: CurrentUser = Depends(require_platform_admin),
) -> TriggerResponse:
    """
    Manually trigger a named background job.

    - 404 if job_name is not in KNOWN_JOB_NAMES.
    - 409 if a row with status='running' already exists for that job in job_run_log.
    - 202 on success — job runs asynchronously.

    The caller should poll GET /platform/jobs/history?job_name=<name> to track
    the outcome.
    """
    if job_name not in KNOWN_JOB_NAMES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown job '{job_name}'. Known jobs: {', '.join(sorted(KNOWN_JOB_NAMES))}",
        )

    # Check for an already-running instance
    async with async_session_factory() as db:
        running_result = await db.execute(
            text(
                "SELECT id FROM job_run_log "
                "WHERE job_name = :job_name AND status = 'running' "
                "LIMIT 1"
            ),
            {"job_name": job_name},
        )
        running_row = running_result.fetchone()

    if running_row is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_name}' is already running.",
        )

    # Atomic dispatch gate: prevent concurrent requests from both passing the
    # SELECT check before either background task writes its 'running' row.
    # TTL of 10 s is ample time for job_run_context to INSERT the running row.
    _DISPATCH_KEY = f"mingai:trigger:dispatching:{job_name}"
    redis = get_redis()
    dispatched = await redis.set(_DISPATCH_KEY, "1", nx=True, ex=60)
    if not dispatched:
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_name}' is already running.",
        )

    fn = _JOB_DISPATCH[job_name]

    task = asyncio.create_task(fn())  # type: ignore[operator]
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    logger.info(
        "job_triggered_manually",
        job_name=job_name,
        triggered_by=str(current_user.id),
    )

    return TriggerResponse(job_name=job_name, run_id=None, status="triggered")
