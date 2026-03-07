"""
Redis Stream producer for issue reports triage pipeline (INFRA-017).

Stream: issue_reports:incoming
Consumer group: issue_triage_workers
Max length: 10,000 (oldest trimmed)
"""
from datetime import datetime, timezone
from typing import Optional

import structlog
from redis.exceptions import ResponseError

logger = structlog.get_logger()

# Stream constants — referenced by both producer (this module) and consumer (worker.py)
STREAM_KEY = "issue_reports:incoming"
CONSUMER_GROUP = "issue_triage_workers"
STREAM_MAX_LEN = 10_000


async def ensure_stream_group(redis) -> None:
    """
    Create the consumer group for the issue triage stream (idempotent).

    Uses XGROUP CREATE with MKSTREAM so the stream is auto-created if it
    does not exist. Swallows the BUSYGROUP error that Redis returns when the
    group already exists, but re-raises any other error.
    """
    try:
        await redis.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
        logger.info(
            "stream_group_created",
            stream=STREAM_KEY,
            group=CONSUMER_GROUP,
        )
    except ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            logger.debug(
                "stream_group_already_exists",
                stream=STREAM_KEY,
                group=CONSUMER_GROUP,
            )
        else:
            raise


async def publish_issue_to_stream(
    report_id: str,
    tenant_id: str,
    issue_type: str,
    severity_hint: Optional[str],
    redis,
) -> str:
    """
    Publish an issue report to the Redis Stream for triage.

    Message schema:
        report_id   — UUID of the issue report row in PostgreSQL
        tenant_id   — tenant that owns the report
        issue_type  — initial classification hint (e.g. "bug", "feature")
        severity_hint — optional severity hint from the submitter
        timestamp   — ISO-8601 publish time

    Returns the stream entry ID assigned by Redis.
    """
    if not report_id:
        raise ValueError(
            "report_id is required to publish to the issue triage stream. "
            "Received empty or None value."
        )
    if not tenant_id:
        raise ValueError(
            "tenant_id is required to publish to the issue triage stream. "
            "Received empty or None value."
        )
    if not issue_type:
        raise ValueError(
            "issue_type is required to publish to the issue triage stream. "
            "Received empty or None value."
        )

    fields = {
        "report_id": report_id,
        "tenant_id": tenant_id,
        "issue_type": issue_type,
        "severity_hint": severity_hint or "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    entry_id = await redis.xadd(
        STREAM_KEY,
        fields,
        maxlen=STREAM_MAX_LEN,
    )

    logger.info(
        "issue_published_to_stream",
        entry_id=entry_id,
        report_id=report_id,
        tenant_id=tenant_id,
        issue_type=issue_type,
    )

    return str(entry_id)
