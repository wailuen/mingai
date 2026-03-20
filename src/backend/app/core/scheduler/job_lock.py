"""
SCHED-002: Distributed job lock for multi-instance (Kubernetes) deployments.

Only one pod should execute each scheduled job per cycle.  This is enforced
via a Redis SET NX EX lock.  A heartbeat task renews the EXPIRE every TTL/2
seconds so the lock survives long-running jobs.  If Redis evicts the lock
token while the job is running (e.g. due to AOF loss) the heartbeat detects
the mismatch and cancels the job task to prevent zombie work.

Atomic release is handled by a Lua script that checks the token before DEL,
preventing a pod from releasing a lock it no longer owns.

Usage:
    async with DistributedJobLock("provider_health", ttl=700) as acquired:
        if not acquired:
            return  # another pod has the lock — skip this cycle
        # ... do the work ...

Token is stored as a plain str (UUID4) because the standard Redis pool uses
decode_responses=True, so GET always returns str.  Storing bytes would cause
the heartbeat comparison to fail (str != bytes) on every check.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog

logger = structlog.get_logger()

# Lua script: DELETE the key only if its current value matches our token.
# Returns 1 if deleted, 0 if the key no longer exists or belongs to another pod.
# Registered once at module level; redis.register_script() is synchronous and
# only wraps the script text — the SHA is cached per connection by redis-py.
_LUA_RELEASE_SCRIPT_TEXT = """
local val = redis.call('GET', KEYS[1])
if val == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""

_LOCK_KEY_PREFIX = "mingai:scheduler:lock:"


@asynccontextmanager
async def DistributedJobLock(
    job_name: str,
    *,
    ttl: int = 700,
) -> AsyncIterator[bool]:
    """
    Async context manager that acquires a distributed Redis lock.

    Yields:
        True   — this pod acquired the lock; caller should run the job.
        False  — another pod holds the lock; caller should skip this cycle.

    Args:
        job_name: Unique identifier for the job (used as part of the Redis key).
        ttl:      Lock TTL in seconds.  Should exceed max expected job runtime.
                  Default 700s gives ~100s headroom over a 600s provider health run.
                  Heartbeat renews EXPIRE every TTL//2 seconds.

    The `current_task` captured inside this context manager is the task that
    called `async with DistributedJobLock(...)`.  If the heartbeat detects token
    theft it cancels that task — the scheduler loop — not any inner coroutine.
    This is intentional: the scheduler loop handles CancelledError by re-raising,
    which bubbles up to lifespan and stops the job cleanly.
    """
    from app.core.redis_client import get_redis

    redis = get_redis()
    lock_key = f"{_LOCK_KEY_PREFIX}{job_name}"
    # Plain str token — pool uses decode_responses=True so GET returns str.
    token: str = str(uuid.uuid4())
    heartbeat_task: asyncio.Task | None = None
    acquired = False

    # Register Lua script once per redis pool instance (synchronous, no network call).
    lua_release = redis.register_script(_LUA_RELEASE_SCRIPT_TEXT)

    try:
        # Attempt to acquire lock with NX (set only if not exists) and EX (expire).
        result = await redis.set(lock_key, token, nx=True, ex=ttl)
        acquired = result is True

        if not acquired:
            yield False
            return

        # We own the lock.  Start heartbeat to renew EXPIRE every TTL//2 seconds.
        # The heartbeat also guards against token theft: if the stored value no
        # longer matches our token, it cancels `current_task` (the caller's asyncio
        # Task — i.e. the scheduler loop) and returns.
        current_task = asyncio.current_task()

        async def _heartbeat() -> None:
            interval = max(1, ttl // 2)
            while True:
                await asyncio.sleep(interval)
                try:
                    # Read current token to detect theft before extending.
                    # Both sides are str because decode_responses=True.
                    current_val: str | None = await redis.get(lock_key)
                    if current_val != token:
                        logger.error(
                            "scheduler_lock_token_mismatch",
                            job_name=job_name,
                            expected=token,
                            actual=current_val,
                            action="cancelling_job_task",
                        )
                        if current_task is not None and not current_task.done():
                            current_task.cancel()
                        return
                    # Token matches — renew TTL.
                    await redis.expire(lock_key, ttl)
                    logger.debug(
                        "scheduler_lock_heartbeat",
                        job_name=job_name,
                        ttl_renewed=ttl,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "scheduler_lock_heartbeat_error",
                        job_name=job_name,
                        error=str(exc),
                    )

        heartbeat_task = asyncio.create_task(_heartbeat())

        yield True

    finally:
        # Cancel heartbeat first so it stops renewing the key before release.
        if heartbeat_task is not None and not heartbeat_task.done():
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        # Release the lock atomically only if we own it.
        if acquired:
            try:
                released = await lua_release(keys=[lock_key], args=[token])
                if released:
                    logger.debug("scheduler_lock_released", job_name=job_name)
                else:
                    logger.warning(
                        "scheduler_lock_release_skipped",
                        job_name=job_name,
                        reason="token_mismatch_or_expired",
                    )
            except Exception as exc:
                logger.warning(
                    "scheduler_lock_release_error",
                    job_name=job_name,
                    error=str(exc),
                )
