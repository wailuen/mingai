"""
HAR-010: Approval timeout background job.

Runs hourly (with ±60s jitter). Queries har_transactions where:
  - state = 'PENDING_APPROVAL'
  - approval_deadline < NOW()

For each timed-out transaction:
  1. Sets state = 'TIMED_OUT' (terminal)
  2. Records a transition event (unsigned, system-initiated)
  3. Creates an in-app notification for all tenant_admin users

The job never raises — all errors are logged and processing continues
to the next transaction.

Background task lifecycle:
    run_approval_timeout_scheduler()   — infinite loop, call via asyncio.create_task()
    run_approval_timeout_job()         — single sweep, called by scheduler
"""
from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text

from app.core.scheduler import DistributedJobLock, job_run_context

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_INTERVAL_SECONDS = 3600  # 1 hour
_JITTER_SECONDS = 60
_BATCH_SIZE = 100  # max transactions to process per sweep


# ---------------------------------------------------------------------------
# Interval helper
# ---------------------------------------------------------------------------


def _jitter_interval() -> float:
    """Return base interval ± random jitter, minimum 1 second."""
    return max(
        1.0, _BASE_INTERVAL_SECONDS + random.uniform(-_JITTER_SECONDS, _JITTER_SECONDS)
    )


# ---------------------------------------------------------------------------
# Core sweep
# ---------------------------------------------------------------------------


async def get_timed_out_transactions(db: Any) -> list[dict]:
    """
    Return har_transactions that are in PENDING_APPROVAL state
    and whose approval_deadline has passed.
    """
    result = await db.execute(
        text(
            "SELECT id, tenant_id, amount, currency "
            "FROM har_transactions "
            "WHERE state = 'PENDING_APPROVAL' "
            "AND approval_deadline < NOW() "
            "ORDER BY approval_deadline ASC "
            "LIMIT :limit"
        ),
        {"limit": _BATCH_SIZE},
    )
    rows = result.mappings().all()
    return [
        {
            "id": str(r["id"]),
            "tenant_id": str(r["tenant_id"]),
            "amount": float(r["amount"]) if r["amount"] is not None else None,
            "currency": r["currency"] or "USD",
        }
        for r in rows
    ]


async def mark_transaction_timed_out(
    transaction_id: str, tenant_id: str, db: Any
) -> None:
    """
    Set har_transactions.state = 'TIMED_OUT' for a single transaction.

    Also records an unsigned system-initiated transition event.
    """
    # Update state
    await db.execute(
        text(
            "UPDATE har_transactions "
            "SET state = 'TIMED_OUT', updated_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id "
            "AND state = 'PENDING_APPROVAL'"
        ),
        {"id": transaction_id, "tenant_id": tenant_id},
    )

    # Record transition event — unsigned, system-initiated
    import json
    import hashlib

    event_id = str(uuid.uuid4())
    event_payload = {
        "from": "PENDING_APPROVAL",
        "to": "TIMED_OUT",
        "reason": "approval_timeout",
    }
    event_payload_json = json.dumps(event_payload, sort_keys=True)

    # Compute simple hash for chain integrity
    hash_input = json.dumps(
        {
            "event_id": event_id,
            "event_type": "state_transition",
            "payload": event_payload,
            "prev_event_hash": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        sort_keys=True,
    )
    import hashlib as _hashlib

    event_hash = _hashlib.sha256(hash_input.encode()).hexdigest()

    await db.execute(
        text(
            "INSERT INTO har_transaction_events "
            "(id, tenant_id, transaction_id, event_type, actor_agent_id, actor_user_id, "
            "payload, signature, nonce, prev_event_hash, event_hash) "
            "VALUES (:id, :tenant_id, :transaction_id, 'state_transition', "
            "NULL, NULL, CAST(:payload AS jsonb), NULL, NULL, NULL, :event_hash)"
        ),
        {
            "id": event_id,
            "tenant_id": tenant_id,
            "transaction_id": transaction_id,
            "payload": event_payload_json,
            "event_hash": event_hash,
        },
    )
    await db.commit()


async def notify_timeout_to_admins(
    transaction_id: str,
    tenant_id: str,
    db: Any,
) -> None:
    """
    Send in-app notifications to all active tenant_admin users for a timed-out transaction.
    Errors are swallowed — notification failure must not abort the timeout sweep.
    """
    try:
        result = await db.execute(
            text(
                "SELECT id FROM users "
                "WHERE tenant_id = :tenant_id "
                "AND role = 'tenant_admin' "
                "AND status = 'active'"
            ),
            {"tenant_id": tenant_id},
        )
        rows = result.mappings().all()
        user_ids = [str(r["id"]) for r in rows]

        if not user_ids:
            logger.warning(
                "har_timeout_no_tenant_admins",
                transaction_id=transaction_id,
                tenant_id=tenant_id,
            )
            return

        from app.modules.notifications.publisher import publish_notification

        for user_id in user_ids:
            try:
                await publish_notification(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    notification_type="har_approval_timeout",
                    title="HAR Transaction Timed Out",
                    body=(
                        f"Transaction {transaction_id} approval deadline has passed. "
                        "The transaction has been marked as TIMED_OUT."
                    ),
                    link=f"/har/transactions/{transaction_id}",
                )
            except Exception as exc:
                logger.error(
                    "har_timeout_notification_failed",
                    transaction_id=transaction_id,
                    user_id=user_id,
                    error_type=type(exc).__name__,
                )
    except Exception as exc:
        logger.error(
            "har_timeout_admin_lookup_failed",
            transaction_id=transaction_id,
            tenant_id=tenant_id,
            error_type=type(exc).__name__,
        )


async def process_timed_out_transaction(
    transaction: dict,
    db: Any,
) -> None:
    """
    Process a single timed-out transaction.
    Marks it TIMED_OUT and sends notifications.
    Errors are caught and logged — other transactions continue to process.
    """
    transaction_id = transaction["id"]
    tenant_id = transaction["tenant_id"]

    try:
        await mark_transaction_timed_out(transaction_id, tenant_id, db)
        logger.info(
            "har_transaction_timed_out",
            transaction_id=transaction_id,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.error(
            "har_timeout_mark_failed",
            transaction_id=transaction_id,
            tenant_id=tenant_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return

    await notify_timeout_to_admins(transaction_id, tenant_id, db)


async def run_approval_timeout_job(db: Any) -> int:
    """
    Single sweep: find and process all timed-out PENDING_APPROVAL transactions.

    Returns the count of transactions processed.
    """
    try:
        transactions = await get_timed_out_transactions(db)
    except Exception as exc:
        logger.error(
            "har_timeout_job_query_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return 0

    if not transactions:
        logger.debug("har_timeout_job_no_timed_out_transactions")
        return 0

    logger.info(
        "har_timeout_job_processing",
        count=len(transactions),
    )

    for txn in transactions:
        await process_timed_out_transaction(txn, db)

    return len(transactions)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


async def run_approval_timeout_scheduler() -> None:
    """
    Long-running background task. Runs run_approval_timeout_job() hourly
    (with ±60s jitter).

    Handles CancelledError cleanly on shutdown.
    """
    from app.core.session import async_session_factory

    logger.info("har_approval_timeout_scheduler_started")
    while True:
        try:
            async with DistributedJobLock("har_approval_timeout", ttl=600) as acquired:
                if not acquired:
                    logger.debug(
                        "har_approval_timeout_job_skipped",
                        reason="lock_held_by_another_pod",
                    )
                else:
                    async with async_session_factory() as db:
                        async with job_run_context("har_approval_timeout") as ctx:
                            count = await run_approval_timeout_job(db)
                            ctx.records_processed = count
        except asyncio.CancelledError:
            logger.info("har_approval_timeout_scheduler_cancelled")
            raise
        except Exception as exc:
            logger.error(
                "har_approval_timeout_scheduler_error",
                error_type=type(exc).__name__,
                error=str(exc),
            )

        interval = _jitter_interval()
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("har_approval_timeout_scheduler_cancelled")
            raise
