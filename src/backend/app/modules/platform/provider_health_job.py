"""
PVDR-007: Platform LLM Provider health check background job.

Checks connectivity for all enabled providers every 600 seconds.
Per-provider jitter (0–30s) prevents thundering herd. One failure
does not abort others.

Structured logs per provider at key:
    provider_health_check — fields: provider_id, provider_type, success, latency_ms

Mirrors the pattern from tool_health_job.py (APScheduler + AsyncIOScheduler).
"""
import asyncio
import random

import structlog

logger = structlog.get_logger()

_CHECK_INTERVAL_SECONDS = 600  # 10 minutes
_JITTER_MAX_SECONDS = 30


async def run_provider_health_job() -> dict:
    """
    One-shot health check for all enabled providers.

    For each provider:
      1. Jitter (0–30s random sleep)
      2. Fetch provider row including api_key_encrypted
      3. Decrypt key, run connectivity test, clear key immediately
      4. Update provider_status, last_health_check_at, health_error in DB

    Returns summary: {checked, healthy, error, skipped}
    """
    from sqlalchemy import text

    from app.core.llm.provider_service import ProviderService, _set_platform_scope_sql
    from app.core.session import async_session_factory

    svc = ProviderService()
    checked = 0
    healthy = 0
    error_count = 0
    skipped = 0

    # Fetch all enabled provider IDs first — we'll handle each with its own session
    async with async_session_factory() as db:
        await db.execute(text(_set_platform_scope_sql()))
        result = await db.execute(
            text("SELECT id, provider_type FROM llm_providers WHERE is_enabled = true")
        )
        rows = result.fetchall()
        provider_ids = [(str(row[0]), row[1]) for row in rows]

    for provider_id, provider_type in provider_ids:
        # Per-provider jitter
        await asyncio.sleep(random.randint(0, _JITTER_MAX_SECONDS))

        try:
            async with async_session_factory() as db:
                await db.execute(text(_set_platform_scope_sql()))
                # Fetch with encrypted key
                key_result = await db.execute(
                    text(
                        "SELECT provider_type, endpoint, models, options, api_key_encrypted "
                        "FROM llm_providers WHERE id = :id AND is_enabled = true"
                    ),
                    {"id": provider_id},
                )
                row = key_result.fetchone()

            if row is None:
                skipped += 1
                continue

            p_type, endpoint, models_dict, options_dict, encrypted_bytes = row
            if isinstance(models_dict, str):
                import json

                models_dict = json.loads(models_dict) if models_dict else {}
            if isinstance(options_dict, str):
                import json

                options_dict = json.loads(options_dict) if options_dict else {}

            encrypted_bytes = bytes(encrypted_bytes) if encrypted_bytes else b""

            # Build provider_row dict for connectivity test
            provider_row = {
                "id": provider_id,
                "provider_type": p_type,
                "endpoint": endpoint,
                "models": models_dict,
                "options": options_dict,
            }

            success, error_msg = await svc.test_connectivity(provider_row)
            checked += 1

            new_status = "healthy" if success else "error"
            if success:
                healthy += 1
            else:
                error_count += 1

            # Write status back
            async with async_session_factory() as db:
                await db.execute(text(_set_platform_scope_sql()))
                await db.execute(
                    text(
                        "UPDATE llm_providers SET "
                        "provider_status = :status, "
                        "last_health_check_at = NOW(), "
                        "health_error = :health_error, "
                        "updated_at = NOW() "
                        "WHERE id = :id"
                    ),
                    {
                        "status": new_status,
                        "health_error": error_msg,
                        "id": provider_id,
                    },
                )
                await db.commit()

            logger.info(
                "provider_health_check",
                provider_id=provider_id,
                provider_type=provider_type,
                success=success,
                new_status=new_status,
            )

        except Exception as exc:
            skipped += 1
            logger.error(
                "provider_health_check_error",
                provider_id=provider_id,
                provider_type=provider_type,
                error=str(exc),
            )

    return {
        "checked": checked,
        "healthy": healthy,
        "error": error_count,
        "skipped": skipped,
    }


def start_provider_health_scheduler(app) -> None:
    """
    Register the provider health monitoring job with APScheduler.

    Called from app lifespan on startup. Schedules run_provider_health_job
    every 600 seconds.
    """
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        scheduler = AsyncIOScheduler()

        async def _job_wrapper():
            try:
                summary = await run_provider_health_job()
                logger.info("provider_health_job_complete", **summary)
            except Exception as exc:
                logger.error("provider_health_job_failed", error=str(exc))

        scheduler.add_job(
            _job_wrapper,
            trigger=IntervalTrigger(seconds=_CHECK_INTERVAL_SECONDS),
            id="provider_health_monitor",
            replace_existing=True,
            misfire_grace_time=60,
        )
        scheduler.start()
        logger.info(
            "provider_health_scheduler_started",
            interval_seconds=_CHECK_INTERVAL_SECONDS,
        )

        if hasattr(app, "state"):
            app.state.provider_health_scheduler = scheduler

    except ImportError:
        logger.warning(
            "provider_health_scheduler_skipped",
            reason="apscheduler not installed — provider health monitoring disabled",
        )
    except Exception as exc:
        logger.error("provider_health_scheduler_start_failed", error=str(exc))
