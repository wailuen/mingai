"""
HAR A2A Transaction State Machine (AI-043, AI-044, AI-045).

Valid states: DRAFT | OPEN | NEGOTIATING | COMMITTED | EXECUTING | COMPLETED | ABANDONED | DISPUTED | RESOLVED

Implements:
- VALID_TRANSITIONS: state transition map
- transition_state(): validate and apply state transitions
- get_transaction(): fetch transaction by id + tenant
- record_transition_event(): create signed/unsigned event chain entry
- check_requires_approval(): approval threshold check
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# State transition map (AI-043)
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[str, list[str]] = {
    "DRAFT": ["OPEN"],
    "OPEN": ["NEGOTIATING", "ABANDONED"],
    "NEGOTIATING": ["COMMITTED", "ABANDONED"],
    "COMMITTED": ["EXECUTING", "ABANDONED"],
    "EXECUTING": ["COMPLETED", "DISPUTED"],
    "DISPUTED": ["RESOLVED"],
    # Terminal states
    "COMPLETED": [],
    "ABANDONED": [],
    "RESOLVED": [],
}

ALL_STATES = list(VALID_TRANSITIONS.keys())


# ---------------------------------------------------------------------------
# State transition (AI-043)
# ---------------------------------------------------------------------------


async def transition_state(
    transaction_id: str,
    new_state: str,
    actor_agent_id: str | None,
    actor_user_id: str | None,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """
    Validate and apply a state transition on a HAR transaction.

    Raises HTTPException(400) if the transition is invalid.
    Raises HTTPException(404) if the transaction is not found.
    Returns the updated transaction dict.
    """
    if new_state not in ALL_STATES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid state '{new_state}'. Valid states: {ALL_STATES}",
        )

    # Fetch current state — always filter by tenant_id to prevent cross-tenant access
    result = await db.execute(
        text(
            "SELECT id, tenant_id, initiator_agent_id, counterparty_agent_id, "
            "state, amount, currency, payload, requires_human_approval, "
            "human_approved_at, human_approved_by, approval_deadline, "
            "chain_head_hash, created_at, updated_at "
            "FROM har_transactions WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": transaction_id, "tenant_id": tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Transaction '{transaction_id}' not found",
        )

    current_state = row["state"]
    allowed = VALID_TRANSITIONS.get(current_state, [])
    if new_state not in allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid transition: {current_state} -> {new_state}. "
                f"Allowed transitions from {current_state}: {allowed}"
            ),
        )

    # Apply state transition — scoped to tenant
    await db.execute(
        text(
            "UPDATE har_transactions "
            "SET state = :new_state, updated_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"new_state": new_state, "id": transaction_id, "tenant_id": tenant_id},
    )
    await db.commit()

    # Record transition event (AI-044)
    await record_transition_event(
        transaction_id=transaction_id,
        tenant_id=tenant_id,
        old_state=current_state,
        new_state=new_state,
        actor_agent_id=actor_agent_id,
        actor_user_id=actor_user_id,
        db=db,
    )

    logger.info(
        "har_state_transition",
        transaction_id=transaction_id,
        tenant_id=tenant_id,
        from_state=current_state,
        to_state=new_state,
        actor_agent_id=actor_agent_id,
        actor_user_id=actor_user_id,
    )

    # Re-fetch to return updated row — scoped to tenant
    updated = await db.execute(
        text(
            "SELECT id, tenant_id, initiator_agent_id, counterparty_agent_id, "
            "state, amount, currency, payload, requires_human_approval, "
            "human_approved_at, human_approved_by, approval_deadline, "
            "chain_head_hash, created_at, updated_at "
            "FROM har_transactions WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": transaction_id, "tenant_id": tenant_id},
    )
    updated_row = updated.mappings().first()
    if updated_row is None:
        raise HTTPException(
            status_code=500,
            detail="Transaction disappeared after update - data integrity error",
        )
    result_dict = _row_to_dict(updated_row)

    # HAR-011: Create fee record when transaction reaches COMPLETED state
    if new_state == "COMPLETED":
        try:
            from app.modules.har.fee_records import create_fee_record

            await create_fee_record(
                transaction_id=transaction_id,
                tenant_id=tenant_id,
                amount=result_dict.get("amount"),
                currency=result_dict.get("currency"),
                db=db,
            )
        except Exception as exc:
            logger.error(
                "har_fee_record_creation_failed",
                transaction_id=transaction_id,
                tenant_id=tenant_id,
                error_type=type(exc).__name__,
            )

    return result_dict


# ---------------------------------------------------------------------------
# Get transaction (AI-043)
# ---------------------------------------------------------------------------


async def get_transaction(
    transaction_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict | None:
    """Fetch a full transaction row by id and tenant_id. Returns None if not found."""
    result = await db.execute(
        text(
            "SELECT id, tenant_id, initiator_agent_id, counterparty_agent_id, "
            "state, amount, currency, payload, requires_human_approval, "
            "human_approved_at, human_approved_by, approval_deadline, "
            "chain_head_hash, created_at, updated_at "
            "FROM har_transactions "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": transaction_id, "tenant_id": tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Signature chaining (AI-044)
# ---------------------------------------------------------------------------


async def record_transition_event(
    transaction_id: str,
    tenant_id: str,
    old_state: str,
    new_state: str,
    actor_agent_id: str | None,
    actor_user_id: str | None,
    db: AsyncSession,
) -> None:
    """
    Record a state transition event in the har_transaction_events chain.

    For agent-initiated transitions (actor_agent_id set):
        Fetches the agent's private_key_enc from agent_cards and calls
        signing.create_signed_event() to produce a cryptographically signed event.
        If the agent has no keypair, falls back to an unsigned event with a WARNING log.
    For user-initiated transitions (actor_user_id set, no actor_agent_id):
        Inserts an unsigned event (signature=None, nonce=None).

    Updates har_transactions.chain_head_hash with the new event's event_hash.
    """
    event_payload = {"from": old_state, "to": new_state}
    event_id = str(uuid.uuid4())

    # Get current chain head hash for prev_event_hash linking
    head_result = await db.execute(
        text(
            "SELECT chain_head_hash FROM har_transactions "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": transaction_id, "tenant_id": tenant_id},
    )
    head_row = head_result.mappings().first()
    prev_event_hash = head_row["chain_head_hash"] if head_row else None

    # _event_inserted tracks whether create_signed_event already persisted the
    # event row (signed path). All other paths insert it here.
    _event_inserted = False
    signature = None
    nonce = None

    if actor_agent_id:
        # Agent-initiated: fetch private key and create signed event
        key_result = await db.execute(
            text(
                "SELECT private_key_enc FROM agent_cards "
                "WHERE id = :agent_id AND tenant_id = :tenant_id"
            ),
            {"agent_id": actor_agent_id, "tenant_id": tenant_id},
        )
        key_row = key_result.mappings().first()
        private_key_enc = key_row["private_key_enc"] if key_row else None

        if private_key_enc:
            try:
                from app.modules.har.signing import create_signed_event

                signed = await create_signed_event(
                    transaction_id=transaction_id,
                    event_type="state_transition",
                    actor_agent_id=actor_agent_id,
                    payload=event_payload,
                    actor_private_key_enc=private_key_enc,
                    prev_event_hash=prev_event_hash,
                    tenant_id=tenant_id,
                    db=db,
                )
                # create_signed_event already INSERTed the event — do not insert again.
                event_id = signed.get("id", event_id)
                signature = signed.get("signature")
                nonce = signed.get("nonce")
                event_hash = signed.get("event_hash")
                _event_inserted = True
            except Exception as exc:
                # Signing failed — fall back to unsigned but log clearly (not silently)
                logger.warning(
                    "har_signing_failed_falling_back_to_unsigned",
                    transaction_id=transaction_id,
                    actor_agent_id=actor_agent_id,
                    error_type=type(exc).__name__,
                )
                event_hash = _compute_event_hash(
                    event_id=event_id,
                    event_type="state_transition",
                    payload=event_payload,
                    prev_event_hash=prev_event_hash,
                )
        else:
            # Agent has no keypair — cannot sign; record unsigned with warning
            logger.warning(
                "har_agent_no_keypair_unsigned_event",
                transaction_id=transaction_id,
                actor_agent_id=actor_agent_id,
                tenant_id=tenant_id,
            )
            event_hash = _compute_event_hash(
                event_id=event_id,
                event_type="state_transition",
                payload=event_payload,
                prev_event_hash=prev_event_hash,
            )
    else:
        # User-initiated: unsigned event
        event_hash = _compute_event_hash(
            event_id=event_id,
            event_type="state_transition",
            payload=event_payload,
            prev_event_hash=prev_event_hash,
        )

    if not _event_inserted:
        # Unsigned / fallback: insert event here (signed path already inserted via create_signed_event)
        await db.execute(
            text(
                "INSERT INTO har_transaction_events "
                "(id, tenant_id, transaction_id, event_type, actor_agent_id, actor_user_id, "
                "payload, signature, nonce, prev_event_hash, event_hash) "
                "VALUES (:id, :tenant_id, :transaction_id, :event_type, "
                ":actor_agent_id, :actor_user_id, "
                "CAST(:payload AS jsonb), :signature, :nonce, :prev_event_hash, :event_hash)"
            ),
            {
                "id": event_id,
                "tenant_id": tenant_id,
                "transaction_id": transaction_id,
                "event_type": "state_transition",
                "actor_agent_id": actor_agent_id,
                "actor_user_id": actor_user_id,
                "payload": json.dumps(event_payload),
                "signature": signature,
                "nonce": nonce,
                "prev_event_hash": prev_event_hash,
                "event_hash": event_hash,
            },
        )

    # Update chain head hash — same transaction as the unsigned INSERT above;
    # for signed events this is a separate commit after create_signed_event's commit.
    await db.execute(
        text(
            "UPDATE har_transactions SET chain_head_hash = :hash "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"hash": event_hash, "id": transaction_id, "tenant_id": tenant_id},
    )
    await db.commit()

    logger.info(
        "har_transition_event_recorded",
        transaction_id=transaction_id,
        event_id=event_id,
        event_hash=event_hash,
        signed=signature is not None,
    )


# ---------------------------------------------------------------------------
# Human approval gate (AI-045)
# ---------------------------------------------------------------------------


async def check_requires_approval(
    amount: float | None,
    tenant_id: str,
    db: AsyncSession,
) -> bool:
    """
    Check if a transaction amount requires human approval.

    Default threshold: 5000.0. Returns True if amount >= threshold.
    Returns False if amount is None.

    Logs when approval is required for audit trail.
    """
    if amount is None:
        return False

    threshold = 5000.0

    requires = amount >= threshold
    if requires:
        logger.info(
            "har_approval_required",
            amount=amount,
            threshold=threshold,
            tenant_id=tenant_id,
        )
    return requires


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_event_hash(
    event_id: str,
    event_type: str,
    payload: dict,
    prev_event_hash: str | None,
) -> str:
    """Compute SHA-256 hash for an unsigned event for chain integrity."""
    hash_input = json.dumps(
        {
            "event_id": event_id,
            "event_type": event_type,
            "payload": payload,
            "prev_event_hash": prev_event_hash,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(hash_input.encode()).hexdigest()


def _row_to_dict(row) -> dict:
    """Convert a SQLAlchemy row mapping to a serializable dict."""
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)

    return {
        "id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "initiator_agent_id": str(row["initiator_agent_id"]),
        "counterparty_agent_id": str(row["counterparty_agent_id"]),
        "state": row["state"],
        "amount": float(row["amount"]) if row["amount"] is not None else None,
        "currency": row["currency"],
        "payload": payload or {},
        "requires_human_approval": row["requires_human_approval"],
        "human_approved_at": str(row["human_approved_at"])
        if row["human_approved_at"]
        else None,
        "human_approved_by": str(row["human_approved_by"])
        if row["human_approved_by"]
        else None,
        "approval_deadline": str(row["approval_deadline"])
        if row["approval_deadline"]
        else None,
        "chain_head_hash": row["chain_head_hash"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }
