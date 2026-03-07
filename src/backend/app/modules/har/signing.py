"""
HAR A2A Message Signing — create, verify, and chain signed events (AI-041, AI-042).

All signed events form an append-only hash chain per transaction.
Nonce replay protection uses Redis SETNX with TTL.
"""
import hashlib
import json
import secrets
from datetime import datetime, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.har.crypto import sign_payload, verify_signature

logger = structlog.get_logger()


async def create_signed_event(
    transaction_id: str,
    event_type: str,
    actor_agent_id: str,
    payload: dict,
    actor_private_key_enc: str,
    prev_event_hash: str | None,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """
    Create a signed event and insert it into har_transaction_events.

    Steps:
    1. Generate nonce (secrets.token_hex(32) → 64 hex chars)
    2. Build canonical payload bytes (JSON, sorted keys)
    3. Sign with Ed25519 via crypto.sign_payload()
    4. Compute event_hash: sha256(canonical_bytes + signature.encode())
    5. INSERT into har_transaction_events
    6. Return the inserted event dict

    Args:
        transaction_id: UUID of the HAR transaction
        event_type: Type of event (e.g. PROPOSE, ACCEPT, REJECT)
        actor_agent_id: UUID of the agent performing the action
        payload: Event-specific data
        actor_private_key_enc: Fernet-encrypted Ed25519 private key
        prev_event_hash: Hash of the previous event in the chain (None for first event)
        tenant_id: UUID of the tenant
        db: Async database session

    Returns:
        Dict with all event fields including id, nonce, signature, event_hash
    """
    if not transaction_id:
        raise ValueError("transaction_id is required for create_signed_event")
    if not event_type:
        raise ValueError("event_type is required for create_signed_event")
    if not actor_agent_id:
        raise ValueError("actor_agent_id is required for create_signed_event")
    if not tenant_id:
        raise ValueError("tenant_id is required for create_signed_event")

    # Step 1: Generate nonce and check for replay via Redis SETNX
    nonce = secrets.token_hex(32)  # 64 hex characters
    try:
        from app.core.redis_client import get_redis

        redis = get_redis()
        is_fresh = await check_nonce_replay(nonce, tenant_id, redis)
        if not is_fresh:
            # Collision of a 256-bit random nonce is astronomically unlikely;
            # if it happens, it is almost certainly a replay attack.
            raise ValueError(
                f"Nonce collision detected for tenant {tenant_id} — possible replay attack"
            )
    except ValueError:
        raise
    except Exception as exc:
        # Redis unavailable: log and continue — do not block signing on Redis outage.
        # The nonce is still unique by cryptographic randomness; Redis is defence-in-depth.
        logger.warning(
            "har_nonce_replay_check_unavailable",
            tenant_id=tenant_id,
            error_type=type(exc).__name__,
        )

    # Step 2: Build canonical payload
    now = datetime.now(timezone.utc)
    timestamp_iso = now.isoformat()  # String for canonical payload (deterministic)
    canonical_dict = {
        "transaction_id": transaction_id,
        "event_type": event_type,
        "actor_agent_id": actor_agent_id,
        "payload": payload,
        "nonce": nonce,
        "timestamp": timestamp_iso,
    }
    canonical_bytes = json.dumps(canonical_dict, sort_keys=True).encode()

    # Step 3: Sign
    signature = sign_payload(actor_private_key_enc, canonical_bytes)

    # Step 4: Compute event_hash
    event_hash = hashlib.sha256(canonical_bytes + signature.encode()).hexdigest()

    # Step 5: INSERT into har_transaction_events
    payload_json = json.dumps(payload)
    result = await db.execute(
        text(
            "INSERT INTO har_transaction_events "
            "(tenant_id, transaction_id, event_type, actor_agent_id, "
            "payload, signature, nonce, prev_event_hash, event_hash, created_at) "
            "VALUES (:tenant_id, :transaction_id, :event_type, :actor_agent_id, "
            "CAST(:payload AS jsonb), :signature, :nonce, :prev_event_hash, :event_hash, :created_at) "
            "RETURNING id, tenant_id, transaction_id, event_type, actor_agent_id, "
            "payload, signature, nonce, prev_event_hash, event_hash, created_at"
        ),
        {
            "tenant_id": tenant_id,
            "transaction_id": transaction_id,
            "event_type": event_type,
            "actor_agent_id": actor_agent_id,
            "payload": payload_json,
            "signature": signature,
            "nonce": nonce,
            "prev_event_hash": prev_event_hash,
            "event_hash": event_hash,
            "created_at": now,  # datetime object, not string — asyncpg requires this
        },
    )
    await db.commit()

    row = result.mappings().first()
    if row is None:
        raise RuntimeError(
            f"INSERT into har_transaction_events returned no row. "
            f"transaction_id={transaction_id}, event_type={event_type}"
        )

    event_id = str(row["id"])

    logger.info(
        "har_signed_event_created",
        event_id=event_id,
        transaction_id=transaction_id,
        event_type=event_type,
        actor_agent_id=actor_agent_id,
        tenant_id=tenant_id,
    )

    # Return computed values for crypto fields (nonce, signature, event_hash)
    # rather than DB RETURNING values — guarantees correct 64-char nonce and
    # actual signature bytes regardless of how the DB returns them.
    return {
        "id": event_id,
        "tenant_id": tenant_id,
        "transaction_id": transaction_id,
        "event_type": event_type,
        "actor_agent_id": actor_agent_id,
        "payload": payload,
        "signature": signature,
        "nonce": nonce,
        "prev_event_hash": prev_event_hash,
        "event_hash": event_hash,
        "created_at": timestamp_iso,
    }


async def verify_event_signature(event_id: str, db: AsyncSession) -> bool:
    """
    Verify the Ed25519 signature of a stored event.

    Fetches event from DB, fetches agent's public key from agent_cards,
    reconstructs the canonical payload, and verifies the signature.

    Returns True if valid, False if event not found or signature invalid.
    """
    if not event_id:
        logger.warning("verify_event_signature_empty_event_id")
        return False

    # Fetch event
    result = await db.execute(
        text(
            "SELECT id, transaction_id, event_type, actor_agent_id, "
            "payload, nonce, signature, event_hash, created_at "
            "FROM har_transaction_events WHERE id = :event_id"
        ),
        {"event_id": event_id},
    )
    event = result.mappings().first()
    if event is None:
        logger.warning("verify_event_signature_event_not_found", event_id=event_id)
        return False

    # Fetch agent's public key
    agent_result = await db.execute(
        text("SELECT public_key FROM agent_cards WHERE id = :agent_id"),
        {"agent_id": str(event["actor_agent_id"])},
    )
    agent = agent_result.mappings().first()
    if agent is None or not agent["public_key"]:
        logger.warning(
            "verify_event_signature_agent_key_not_found",
            event_id=event_id,
            actor_agent_id=str(event["actor_agent_id"]),
        )
        return False

    # Reconstruct canonical payload
    event_payload = event["payload"]
    if isinstance(event_payload, str):
        event_payload = json.loads(event_payload)

    # Reconstruct timestamp in the same format used when signing:
    # created_at is a datetime object from DB; use isoformat() to match
    # the format used by create_signed_event() when building canonical_dict.
    created_at = event["created_at"]
    if hasattr(created_at, "isoformat"):
        timestamp_str = created_at.isoformat()
    else:
        timestamp_str = str(created_at)

    canonical_dict = {
        "transaction_id": str(event["transaction_id"]),
        "event_type": event["event_type"],
        "actor_agent_id": str(event["actor_agent_id"]),
        "payload": event_payload if event_payload else {},
        "nonce": event["nonce"],
        "timestamp": timestamp_str,
    }
    canonical_bytes = json.dumps(canonical_dict, sort_keys=True).encode()

    # Verify signature
    is_valid = verify_signature(
        agent["public_key"],
        canonical_bytes,
        event["signature"],
    )

    if not is_valid:
        logger.warning(
            "verify_event_signature_invalid",
            event_id=event_id,
            actor_agent_id=str(event["actor_agent_id"]),
        )

    return is_valid


async def check_nonce_replay(nonce: str, tenant_id: str, redis_client) -> bool:
    """
    Check if a nonce has been used before using Redis SETNX with TTL.

    Uses key format: {tenant_id}:nonce:{nonce}
    TTL: 600 seconds (10 minutes)

    Returns True if nonce is fresh (not replayed), False if replayed.
    """
    if not nonce:
        raise ValueError("nonce is required for replay check")
    if not tenant_id:
        raise ValueError("tenant_id is required for replay check")

    key = f"{tenant_id}:nonce:{nonce}"
    # SETNX with TTL: returns True if key was set (fresh), False if already exists (replay)
    was_set = await redis_client.set(key, "1", nx=True, ex=600)

    if not was_set:
        logger.warning(
            "har_nonce_replay_detected",
            tenant_id=tenant_id,
            nonce_prefix=nonce[:8],
        )

    return bool(was_set)


async def verify_event_chain(transaction_id: str, db: AsyncSession) -> bool:
    """
    Verify the hash chain integrity for all events in a transaction.

    Fetches all events ordered by created_at, checks that each event's
    prev_event_hash matches the previous event's event_hash.

    Returns True if chain is intact (or empty), False if broken.
    """
    if not transaction_id:
        raise ValueError("transaction_id is required for chain verification")

    result = await db.execute(
        text(
            "SELECT id, prev_event_hash, event_hash "
            "FROM har_transaction_events "
            "WHERE transaction_id = :transaction_id "
            "ORDER BY created_at ASC"
        ),
        {"transaction_id": transaction_id},
    )
    events = result.mappings().all()

    if not events:
        return True  # Vacuously valid

    # First event must have prev_event_hash = None
    if events[0]["prev_event_hash"] is not None:
        logger.warning(
            "har_event_chain_broken_first_event",
            transaction_id=transaction_id,
            event_id=str(events[0]["id"]),
            prev_event_hash=events[0]["prev_event_hash"],
        )
        return False

    # Check linkage for subsequent events
    for i in range(1, len(events)):
        expected_prev = events[i - 1]["event_hash"]
        actual_prev = events[i]["prev_event_hash"]
        if actual_prev != expected_prev:
            logger.warning(
                "har_event_chain_broken",
                transaction_id=transaction_id,
                event_id=str(events[i]["id"]),
                expected_prev_hash=expected_prev,
                actual_prev_hash=actual_prev,
            )
            return False

    return True
