"""
SCHED-038: Per-tenant concurrency throttle for background jobs.

Provides a semaphore-based throttle so jobs that fan out across all active
tenants (e.g. query_warming) do not saturate the embedding API or database
pool when the tenant count grows.

Configuration
─────────────
Set the environment variable SCHEDULER_MAX_CONCURRENT_TENANTS to control how
many tenants are processed simultaneously.  Defaults to 5.

    SCHEDULER_MAX_CONCURRENT_TENANTS=10  # allow 10 in-flight tenant tasks

Usage
─────
    from app.core.scheduler.tenant_throttle import run_tenants_throttled

    results = await run_tenants_throttled(
        tenant_ids,
        coro_factory=lambda tid: process_tenant(tid, extra_arg),
    )

Each element of the returned list is either the value returned by
coro_factory(tenant_id) or an Exception if that tenant's coroutine raised.
Callers inspect the list and decide how to handle per-tenant failures.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger()


def _max_concurrent() -> int:
    """Read SCHEDULER_MAX_CONCURRENT_TENANTS from env, default 5, min 1."""
    raw = os.environ.get("SCHEDULER_MAX_CONCURRENT_TENANTS", "5")
    try:
        val = int(raw)
        return max(1, val)
    except (TypeError, ValueError):
        logger.warning(
            "scheduler_max_concurrent_tenants_invalid",
            raw_value=raw,
            fallback=5,
        )
        return 5


async def run_tenants_throttled(
    tenant_ids: list[str],
    coro_factory: Callable[[str], Awaitable[Any]],
    max_concurrent: int | None = None,
) -> list[Any]:
    """
    Run coro_factory(tenant_id) for each tenant_id concurrently, but no more
    than max_concurrent tenants at a time.

    Args:
        tenant_ids:     List of tenant ID strings to process.
        coro_factory:   Async callable that accepts a tenant_id and returns a
                        coroutine.  Will be called once per tenant.
        max_concurrent: Semaphore limit.  Reads SCHEDULER_MAX_CONCURRENT_TENANTS
                        from env if None.

    Returns:
        List aligned with tenant_ids.  Each element is either the return value
        of coro_factory(tenant_id) or an Exception instance if it raised.
        Never raises itself.
    """
    limit = max_concurrent if max_concurrent is not None else _max_concurrent()
    semaphore = asyncio.Semaphore(limit)

    async def _guarded(tid: str) -> Any:
        async with semaphore:
            try:
                return await coro_factory(tid)
            except Exception as exc:
                logger.error(
                    "tenant_throttle_task_failed",
                    tenant_id=tid,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                return exc

    tasks = [asyncio.create_task(_guarded(tid)) for tid in tenant_ids]
    return list(await asyncio.gather(*tasks))
