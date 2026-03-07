"""
Issue triage background worker (INFRA-018).

Reads from Redis Stream `issue_reports:incoming` using XREADGROUP.
For each message:
1. Load full issue report from PostgreSQL
2. Invoke IssueTriageAgent for classification
3. Update issue status to 'triaging' then 'triaged' with result
4. Create GitHub issue via env-configured integration if warranted
5. XCLAIM abandoned messages after 5-minute visibility timeout
6. XACK after success

Consumer ID: derived from worker instance hostname + pid.
Feature requests (type=feature) route to product backlog, skip severity classification.
"""
import asyncio
import os
import platform
from typing import Optional

import httpx
import structlog
from sqlalchemy import text

from app.modules.issues.stream import CONSUMER_GROUP, STREAM_KEY
from app.modules.issues.triage_agent import IssueTriageAgent

logger = structlog.get_logger()

# Visibility timeout for abandoned message reclaim (5 minutes in milliseconds)
_VISIBILITY_TIMEOUT_MS = 5 * 60 * 1000

# Exponential backoff config for LLM failures
_MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 2


async def create_github_issue(
    title: str, body: str, labels: list[str]
) -> Optional[str]:
    """
    Create a GitHub issue if GITHUB_TOKEN and GITHUB_REPO are configured.

    Returns the HTML URL of the created issue, or None if GitHub is not
    configured or the API call fails.
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPO", "")
    if not token or not repo:
        logger.debug(
            "github_integration_skipped",
            reason="GITHUB_TOKEN or GITHUB_REPO not set",
        )
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.github.com/repos/{repo}/issues",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            },
            json={"title": title, "body": body, "labels": labels},
            timeout=30.0,
        )
        if resp.status_code == 201:
            url = resp.json()["html_url"]
            logger.info("github_issue_created", url=url, title=title)
            return url

        logger.warning(
            "github_issue_creation_failed",
            status_code=resp.status_code,
            response_body=resp.text[:500],
        )
    return None


async def process_message(
    msg_id: str,
    fields: dict,
    db_session,
    redis,
) -> None:
    """
    Handle a single issue triage message from the Redis Stream.

    1. Load the issue report from PostgreSQL by report_id.
    2. If issue_type == "feature", route to product backlog (skip triage agent).
    3. Otherwise, invoke IssueTriageAgent for classification.
    4. Update the issue report status and persist triage result.
    5. Optionally create a GitHub issue for high-severity items.
    """
    report_id = fields.get("report_id", "")
    tenant_id = fields.get("tenant_id", "")
    issue_type = fields.get("issue_type", "")

    if not report_id:
        logger.error("process_message_missing_report_id", msg_id=msg_id, fields=fields)
        return

    logger.info(
        "processing_issue_message",
        msg_id=msg_id,
        report_id=report_id,
        tenant_id=tenant_id,
        issue_type=issue_type,
    )

    # Load full issue report from PostgreSQL
    result = await db_session.execute(
        text(
            "SELECT id, tenant_id, user_id, title, description, screenshot_url, "
            "status, blur_acknowledged, created_at "
            "FROM issue_reports WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": report_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        logger.warning(
            "issue_report_not_found",
            report_id=report_id,
            tenant_id=tenant_id,
            msg_id=msg_id,
        )
        return

    title = row[3]
    description = row[4]

    # Feature requests route to product backlog, skip severity classification
    if issue_type == "feature":
        await db_session.execute(
            text(
                "UPDATE issue_reports SET status = :status "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {"status": "product_backlog", "id": report_id, "tenant_id": tenant_id},
        )
        await db_session.commit()
        logger.info(
            "feature_routed_to_product_backlog",
            report_id=report_id,
            tenant_id=tenant_id,
        )
        return

    # Set status to 'triaging' while the agent works
    await db_session.execute(
        text(
            "UPDATE issue_reports SET status = :status "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"status": "triaging", "id": report_id, "tenant_id": tenant_id},
    )
    await db_session.commit()

    # Invoke IssueTriageAgent with exponential backoff on LLM failure
    triage_result = None
    last_error = None
    for attempt in range(_MAX_RETRIES):
        try:
            agent = IssueTriageAgent()
            triage_result = await agent.triage(
                title=title,
                description=description,
                tenant_id=tenant_id,
            )
            break
        except Exception as exc:
            last_error = exc
            wait_time = _BASE_BACKOFF_SECONDS * (2**attempt)
            logger.warning(
                "triage_agent_retry",
                attempt=attempt + 1,
                max_retries=_MAX_RETRIES,
                wait_seconds=wait_time,
                error=str(exc),
                report_id=report_id,
            )
            await asyncio.sleep(wait_time)

    if triage_result is None:
        # All retries exhausted -- mark with error status to prevent indefinite retry
        logger.error(
            "triage_agent_failed_all_retries",
            report_id=report_id,
            tenant_id=tenant_id,
            error=str(last_error),
        )
        await db_session.execute(
            text(
                "UPDATE issue_reports SET status = :status "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {"status": "triage_error", "id": report_id, "tenant_id": tenant_id},
        )
        await db_session.commit()
        return

    # Update issue with triage results
    await db_session.execute(
        text(
            "UPDATE issue_reports SET status = :status "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"status": "triaged", "id": report_id, "tenant_id": tenant_id},
    )
    await db_session.commit()

    logger.info(
        "issue_triaged_successfully",
        report_id=report_id,
        issue_type=triage_result.issue_type,
        severity=triage_result.severity,
        confidence=triage_result.confidence,
        routing=triage_result.routing,
    )

    # Create GitHub issue for P0/P1 severity if GitHub integration is configured
    if triage_result.severity in ("P0", "P1"):
        severity_label = triage_result.severity.lower()
        labels = [severity_label, triage_result.issue_type, triage_result.routing]
        gh_body = (
            f"**Severity**: {triage_result.severity}\n"
            f"**Type**: {triage_result.issue_type}\n"
            f"**Routing**: {triage_result.routing}\n"
            f"**Confidence**: {triage_result.confidence:.2f}\n"
            f"**Reasoning**: {triage_result.reasoning}\n\n"
            f"---\n\n"
            f"**Description**:\n{description[:2000]}\n\n"
            f"*Auto-created by mingai issue triage pipeline (INFRA-018)*"
        )
        await create_github_issue(
            title=f"[{triage_result.severity}] {title[:150]}",
            body=gh_body,
            labels=labels,
        )


async def reclaim_abandoned_messages(
    consumer_id: str,
    redis,
    db_session,
) -> int:
    """
    XCLAIM messages that have been pending for longer than the visibility timeout.

    Scans the pending entries list (PEL) for the consumer group and claims any
    messages idle for more than 5 minutes. Each reclaimed message is then
    processed and acknowledged.

    Returns the number of messages reclaimed and processed.
    """
    reclaimed_count = 0

    try:
        # XPENDING with detail: get up to 100 pending messages
        pending = await redis.xpending_range(
            STREAM_KEY,
            CONSUMER_GROUP,
            min="-",
            max="+",
            count=100,
        )

        stale_ids = [
            entry["message_id"]
            for entry in pending
            if entry.get("time_since_delivered", 0) >= _VISIBILITY_TIMEOUT_MS
        ]

        if not stale_ids:
            return 0

        # XCLAIM the stale messages
        claimed = await redis.xclaim(
            STREAM_KEY,
            CONSUMER_GROUP,
            consumer_id,
            min_idle_time=_VISIBILITY_TIMEOUT_MS,
            message_ids=stale_ids,
        )

        for msg_id, fields in claimed:
            try:
                await process_message(
                    msg_id=msg_id,
                    fields=fields,
                    db_session=db_session,
                    redis=redis,
                )
                await redis.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)
                reclaimed_count += 1
                logger.info(
                    "reclaimed_message_processed",
                    msg_id=msg_id,
                    consumer_id=consumer_id,
                )
            except Exception as exc:
                logger.error(
                    "reclaimed_message_processing_failed",
                    msg_id=msg_id,
                    consumer_id=consumer_id,
                    error=str(exc),
                )

    except Exception as exc:
        logger.error(
            "reclaim_abandoned_messages_failed",
            consumer_id=consumer_id,
            error=str(exc),
        )

    return reclaimed_count


async def run_triage_worker(worker_id: str = "worker-1") -> None:
    """
    Main worker loop: read from the issue triage Redis Stream and process messages.

    Consumer ID is derived from the worker_id parameter (typically hostname + pid).
    Runs indefinitely, reading new messages via XREADGROUP and periodically
    reclaiming abandoned messages.
    """
    from app.core.redis_client import get_redis
    from app.core.session import async_session_factory
    from app.modules.issues.stream import ensure_stream_group

    consumer_id = f"{worker_id}-{platform.node()}-{os.getpid()}"

    redis = get_redis()
    await ensure_stream_group(redis)

    logger.info(
        "triage_worker_started",
        consumer_id=consumer_id,
        stream=STREAM_KEY,
        group=CONSUMER_GROUP,
    )

    reclaim_counter = 0

    while True:
        try:
            # Read new messages (block for up to 5 seconds)
            messages = await redis.xreadgroup(
                CONSUMER_GROUP,
                consumer_id,
                {STREAM_KEY: ">"},
                count=10,
                block=5000,
            )

            if messages:
                for stream_name, stream_messages in messages:
                    for msg_id, fields in stream_messages:
                        async with async_session_factory() as db_session:
                            try:
                                await process_message(
                                    msg_id=msg_id,
                                    fields=fields,
                                    db_session=db_session,
                                    redis=redis,
                                )
                                await redis.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)
                            except Exception as exc:
                                logger.error(
                                    "message_processing_failed",
                                    msg_id=msg_id,
                                    error=str(exc),
                                    consumer_id=consumer_id,
                                )

            # Reclaim abandoned messages every 10 iterations (~50 seconds)
            reclaim_counter += 1
            if reclaim_counter >= 10:
                reclaim_counter = 0
                async with async_session_factory() as db_session:
                    reclaimed = await reclaim_abandoned_messages(
                        consumer_id=consumer_id,
                        redis=redis,
                        db_session=db_session,
                    )
                    if reclaimed > 0:
                        logger.info(
                            "reclaim_cycle_completed",
                            reclaimed_count=reclaimed,
                            consumer_id=consumer_id,
                        )

        except asyncio.CancelledError:
            logger.info("triage_worker_shutdown", consumer_id=consumer_id)
            break
        except Exception as exc:
            logger.error(
                "triage_worker_loop_error",
                error=str(exc),
                consumer_id=consumer_id,
            )
            await asyncio.sleep(5)
