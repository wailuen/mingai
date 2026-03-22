"""
LLM Library health monitoring background job (TODO-38).

Periodically tests published llm_library entries to detect connectivity
or credential issues before they affect tenants.

Behaviour:
  - Runs every _CHECK_INTERVAL_SECONDS (default: 900s / 15 min)
  - Distributed lock prevents thundering herd across pods
  - Per-entry jitter (0–15s) spreads load
  - One entry failure does NOT abort others
  - Results written to llm_library_health_log (if table exists) or logged only
  - Skips entries without api_key_encrypted (library entries with external credentials)
  - Bedrock entries require endpoint_url; if absent, skip and log

Structured log fields per entry:
  llm_library_health_check — entry_id, provider, model_name, success, latency_ms, error
"""
import asyncio
import os
import random
import time
from typing import Optional

import structlog

from app.core.scheduler import DistributedJobLock, job_run_context
from app.core.session import async_session_factory

logger = structlog.get_logger()

_CHECK_INTERVAL_SECONDS = 900   # 15 minutes
_LOCK_TTL_SECONDS = 1050        # interval + jitter (900 + 15*10 headroom)
_JITTER_MAX_SECONDS = 15
_TEST_PROMPT = "Respond with 'ok' and nothing else."
_MAX_ENTRIES_PER_RUN = 50       # safety cap — don't overload providers


async def run_llm_health_check_job() -> dict:
    """
    One-shot health check for all published llm_library entries that have
    api_key_encrypted set.

    For each entry:
      1. Jitter (0–15s)
      2. Decrypt API key
      3. Send minimal test prompt
      4. Record result in structlog
      5. Clear decrypted key immediately in finally block

    Returns summary dict: {checked, healthy, error, skipped}
    """
    from sqlalchemy import text

    from app.core.llm.provider_service import ProviderService

    svc = ProviderService()
    checked = 0
    healthy = 0
    error_count = 0
    skipped = 0

    # Fetch published entries with encrypted keys
    async with async_session_factory() as db:
        # llm_library is platform-scoped — no tenant RLS needed
        result = await db.execute(
            text(
                "SELECT id, provider, model_name, endpoint_url, "
                "api_key_encrypted, api_version "
                "FROM llm_library "
                "WHERE status = 'published' "
                "AND api_key_encrypted IS NOT NULL "
                "ORDER BY updated_at ASC "
                "LIMIT :limit"
            ),
            {"limit": _MAX_ENTRIES_PER_RUN},
        )
        rows = result.fetchall()

    entries = [
        {
            "id": str(row[0]),
            "provider": row[1],
            "model_name": row[2],
            "endpoint_url": row[3],
            "api_key_encrypted": bytes(row[4]) if row[4] else b"",
            "api_version": row[5],
        }
        for row in rows
    ]

    for entry in entries:
        entry_id = entry["id"]
        provider = entry["provider"]
        model_name = entry["model_name"]

        # Skip Bedrock entries without endpoint_url (before jitter to avoid unnecessary wait)
        if provider == "bedrock" and not entry.get("endpoint_url"):
            logger.warning(
                "llm_library_health_check_skipped",
                entry_id=entry_id,
                provider=provider,
                reason="bedrock_missing_endpoint_url",
            )
            skipped += 1
            continue

        jitter = random.uniform(0, _JITTER_MAX_SECONDS)
        await asyncio.sleep(jitter)

        decrypted_key = ""
        # Initialise start before try so that the except block always has a valid value
        start = time.time()
        success = False
        error_msg = ""
        try:
            decrypted_key = svc.decrypt_api_key(entry["api_key_encrypted"])
            start = time.time()   # reset after decryption — only measure LLM round-trip
            await _test_entry(entry, decrypted_key)
            latency_ms = int((time.time() - start) * 1000)
            success = True

            logger.info(
                "llm_library_health_check",
                entry_id=entry_id,
                provider=provider,
                model_name=model_name,
                success=True,
                latency_ms=latency_ms,
            )
            healthy += 1
            checked += 1

        except Exception as exc:
            latency_ms = int((time.time() - start) * 1000)
            error_msg = str(exc)
            logger.warning(
                "llm_library_health_check",
                entry_id=entry_id,
                provider=provider,
                model_name=model_name,
                success=False,
                latency_ms=latency_ms,
                error=error_msg,
            )
            error_count += 1
            checked += 1

        finally:
            decrypted_key = ""  # Always clear sensitive material

        # Persist health status back to llm_library so API responses show current state
        async with async_session_factory() as db:
            try:
                await db.execute(
                    text(
                        "UPDATE llm_library "
                        "SET health_status = :status, health_checked_at = NOW(), "
                        "health_error = :error "
                        "WHERE id = :id"
                    ),
                    {
                        "status": "healthy" if success else "error",
                        "error": error_msg if not success else None,
                        "id": entry_id,
                    },
                )
                await db.commit()
            except Exception as db_exc:
                logger.debug(
                    "llm_health_check_db_update_failed",
                    entry_id=entry_id,
                    error=str(db_exc),
                )

    summary = {
        "checked": checked,
        "healthy": healthy,
        "error": error_count,
        "skipped": skipped,
    }
    logger.info("llm_library_health_check_summary", **summary)
    return summary


async def _test_entry(entry: dict, api_key: str) -> None:
    """Send a minimal test prompt to verify the entry is functional.

    Raises on any failure (HTTP error, timeout, auth error, etc.).
    Key is cleared by the caller in a finally block.
    """
    provider = entry["provider"]
    model_name = entry["model_name"]
    deployment_name = entry.get("deployment_name") or model_name
    endpoint_url = entry.get("endpoint_url") or ""
    api_version = entry.get("api_version") or os.environ.get(
        "AZURE_PLATFORM_OPENAI_API_VERSION", "2024-02-01"
    )

    messages = [{"role": "user", "content": _TEST_PROMPT}]

    if provider == "azure_openai":
        from openai import AsyncAzureOpenAI

        client = AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint_url,
            api_version=api_version,
        )
        await client.chat.completions.create(
            model=deployment_name,
            messages=messages,
            max_tokens=5,
        )

    elif provider in ("openai_direct", "openai"):
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        await client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=5,
        )

    elif provider == "anthropic":
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)
        await client.messages.create(
            model=model_name,
            max_tokens=5,
            messages=messages,
        )

    elif provider == "bedrock":
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=f"{endpoint_url.rstrip('/')}/v1",
        )
        await client.chat.completions.create(
            model=deployment_name,
            messages=messages,
            max_tokens=5,
        )

    else:
        raise ValueError(f"Unknown provider: {provider!r}")


async def run_llm_health_scheduler() -> None:
    """
    Long-running scheduler loop. Called from app lifespan startup.

    Uses a distributed lock to ensure only one pod runs the check per cycle.
    Runs indefinitely — cancelled on app shutdown.
    """
    lock = DistributedJobLock(
        job_name="llm_library_health_check",
        ttl=_LOCK_TTL_SECONDS,
    )

    while True:
        try:
            async with job_run_context("llm_library_health_check"):
                async with lock:
                    await run_llm_health_check_job()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "llm_library_health_scheduler_error",
                error=str(exc),
            )

        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
