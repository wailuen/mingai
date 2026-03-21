"""
HAR-007: Outbound A2A message routing.

Routes signed A2A messages to a target agent's a2a_endpoint via HTTP POST.
Uses Ed25519 signing from app.modules.har.crypto.
Retries 3 times with exponential backoff (1s, 2s, 4s).
On 3 retries exhausted: logs har_transaction_events, updates transaction to FAILED.

Note: HAR state machine does not have a FAILED state in the canonical list
(DRAFT → OPEN → ... → COMPLETED/ABANDONED/RESOLVED). On exhausted retries
the transaction is set to ABANDONED with an event payload indicating routing failure.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import urllib.parse
import uuid
from typing import Optional
from uuid import UUID

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_A2A_TIMEOUT_SECONDS = 30
_MAX_RETRIES = 3
_BACKOFF_SECONDS = [1, 2, 4]
_A2A_CONTENT_TYPE = "application/jose+json"

# SSRF protection — private / reserved IP networks that must never be targeted
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),  # RFC1918 private
    ipaddress.ip_network("172.16.0.0/12"),  # RFC1918 private
    ipaddress.ip_network("192.168.0.0/16"),  # RFC1918 private
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local / cloud metadata
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT shared address space
    ipaddress.ip_network("0.0.0.0/8"),  # This network
]


def _is_private_ip(ip_str: str) -> bool:
    """Return True if the IP address falls within any blocked network range."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in _BLOCKED_NETWORKS)
    except ValueError:
        return True  # Fail closed on unparseable IP


def _validate_ssrf_safe_url(url: str) -> None:
    """RULE A2A-04: DNS resolution must happen on EVERY outbound HTTP call.

    This function MUST be called immediately before every external HTTP request,
    not just at registration time. DNS rebinding attacks work by having the DNS
    record resolve to a safe IP at registration time, then changing the IP to a
    private address before the actual request. Pre-flight DNS checks are NOT
    sufficient — they must be per-request.

    Import from app.modules.registry.a2a_routing — never reimplement inline.
    Reference: CWE-918 (SSRF), OWASP Testing Guide OTG-INPVAL-019.

    Validate that a URL does not target internal/private infrastructure.

    Raises ValueError if the URL is SSRF-unsafe:
    - Hostname resolves to a private/reserved IP range
    - Hostname is localhost or a known metadata endpoint pattern

    This is a defence-in-depth check applied before outbound HTTP requests
    in the A2A routing and health-check pipelines.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        raise ValueError(f"Malformed URL: {exc}") from exc

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname.")

    # Reject explicit IP literals in blocked ranges immediately
    try:
        addr = ipaddress.ip_address(hostname)
        if _is_private_ip(str(addr)):
            raise ValueError(
                f"A2A endpoint hostname '{hostname}' resolves to a "
                "blocked private/reserved IP address."
            )
        return  # Numeric IP that is public — allow
    except ValueError as exc:
        # Re-raise our own SSRF error, not the ip_address() parse error
        if "blocked private" in str(exc):
            raise

    # Reject well-known internal hostnames without DNS resolution
    _blocked_hostnames = {
        "localhost",
        "metadata.google.internal",
        "169.254.169.254",
        "fd00:ec2::254",
    }
    if hostname.lower() in _blocked_hostnames or hostname.startswith("169.254."):
        raise ValueError(
            f"A2A endpoint hostname '{hostname}' targets a blocked internal endpoint."
        )

    # Resolve hostname and validate the resulting IP(s)
    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        # If DNS resolution fails, fail closed
        raise ValueError(f"A2A endpoint hostname '{hostname}' could not be resolved.")

    for _fam, _typ, _proto, _canon, sockaddr in resolved:
        ip_str = sockaddr[0]
        if _is_private_ip(ip_str):
            raise ValueError(
                f"A2A endpoint hostname '{hostname}' resolves to private IP "
                f"'{ip_str}' — SSRF protection blocked this request."
            )


# ---------------------------------------------------------------------------
# Core routing function
# ---------------------------------------------------------------------------


async def route_message(
    session: AsyncSession,
    transaction_id: UUID,
    target_agent_id: UUID,
    message_type: str,
    payload: dict,
) -> dict:
    """
    Route a signed A2A message to target agent's a2a_endpoint.

    Steps:
    1. Fetch a2a_endpoint from agent_cards for target_agent_id.
    2. Validate payload against the JSON schema for message_type.
    3. Sign the payload using the initiator agent's Ed25519 key.
    4. HTTP POST to a2a_endpoint with Content-Type: application/jose+json.
    5. Retry up to 3 times with exponential backoff on failure.
    6. On success: log event to har_transaction_events.
    7. On all retries exhausted: log failure event, set transaction to ABANDONED.

    Args:
        session:          Async DB session.
        transaction_id:   UUID of the HAR transaction.
        target_agent_id:  UUID of the target agent_card.
        message_type:     One of the _VALID_MESSAGE_TYPES.
        payload:          Message body dict.

    Returns:
        dict with keys: status ("sent" | "failed"), response_code, attempt_count.

    Raises:
        ValueError: If target agent has no a2a_endpoint.
    """
    txn_id_str = str(transaction_id)
    agent_id_str = str(target_agent_id)

    # Validate payload schema before sending
    from app.modules.registry.schemas.validator import validate_message_payload

    schema_errors = validate_message_payload(message_type, payload)
    if schema_errors:
        raise ValueError(
            f"Payload validation failed for message_type '{message_type}': {schema_errors}"
        )

    # Fetch target agent's a2a_endpoint
    endpoint = await _get_a2a_endpoint(agent_id_str, session)
    if endpoint is None:
        raise ValueError(
            f"Agent '{agent_id_str}' not found or has no a2a_endpoint configured."
        )

    # SSRF protection: validate endpoint does not target internal infrastructure
    _validate_ssrf_safe_url(endpoint)

    # Fetch transaction row to get initiator_agent_id for signing
    txn_result = await session.execute(
        text(
            "SELECT initiator_agent_id, tenant_id FROM har_transactions "
            "WHERE id = :txn_id"
        ),
        {"txn_id": txn_id_str},
    )
    txn_row = txn_result.mappings().first()
    if txn_row is None:
        raise ValueError(f"Transaction '{txn_id_str}' not found.")

    initiator_agent_id = str(txn_row["initiator_agent_id"])
    tenant_id = str(txn_row["tenant_id"])

    # Build signed envelope
    signed_payload = await _build_signed_envelope(
        transaction_id=txn_id_str,
        message_type=message_type,
        payload=payload,
        initiator_agent_id=initiator_agent_id,
        tenant_id=tenant_id,
        session=session,
    )

    # Send with retry
    last_exc: Optional[Exception] = None
    last_status_code: Optional[int] = None

    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=_A2A_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    endpoint,
                    content=json.dumps(signed_payload),
                    headers={"Content-Type": _A2A_CONTENT_TYPE},
                )
                last_status_code = response.status_code

                if response.status_code < 500:
                    # Success or client error — do not retry
                    await _log_routing_event(
                        transaction_id=txn_id_str,
                        tenant_id=tenant_id,
                        message_type=message_type,
                        target_agent_id=agent_id_str,
                        status_code=response.status_code,
                        attempt=attempt + 1,
                        success=True,
                        session=session,
                    )
                    logger.info(
                        "a2a_message_routed",
                        transaction_id=txn_id_str,
                        target_agent_id=agent_id_str,
                        status_code=response.status_code,
                        attempt=attempt + 1,
                    )
                    return {
                        "status": "sent",
                        "response_code": response.status_code,
                        "attempt_count": attempt + 1,
                        "signed": "signature" in signed_payload,
                    }
                else:
                    logger.warning(
                        "a2a_routing_server_error",
                        transaction_id=txn_id_str,
                        target_agent_id=agent_id_str,
                        status_code=response.status_code,
                        attempt=attempt + 1,
                    )
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "a2a_routing_attempt_failed",
                transaction_id=txn_id_str,
                target_agent_id=agent_id_str,
                attempt=attempt + 1,
                error_type=type(exc).__name__,
                error=str(exc),
            )

        # Wait before next retry (no sleep on last attempt)
        if attempt < _MAX_RETRIES - 1:
            await asyncio.sleep(_BACKOFF_SECONDS[attempt])

    # All retries exhausted — log failure and abandon transaction
    logger.error(
        "a2a_routing_all_retries_exhausted",
        transaction_id=txn_id_str,
        target_agent_id=agent_id_str,
        max_retries=_MAX_RETRIES,
        last_status_code=last_status_code,
        last_error=str(last_exc) if last_exc else None,
    )

    await _log_routing_event(
        transaction_id=txn_id_str,
        tenant_id=tenant_id,
        message_type=message_type,
        target_agent_id=agent_id_str,
        status_code=last_status_code,
        attempt=_MAX_RETRIES,
        success=False,
        session=session,
    )

    await _abandon_transaction(txn_id_str, tenant_id, session)

    return {
        "status": "failed",
        "response_code": last_status_code,
        "attempt_count": _MAX_RETRIES,
        "signed": "signature" in signed_payload,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_a2a_endpoint(agent_id: str, session: AsyncSession) -> Optional[str]:
    """Fetch a2a_endpoint for an agent_card. Returns None if not found."""
    result = await session.execute(
        text("SELECT a2a_endpoint FROM agent_cards WHERE id = :agent_id"),
        {"agent_id": agent_id},
    )
    row = result.mappings().first()
    if row is None or not row["a2a_endpoint"]:
        return None
    return row["a2a_endpoint"]


async def _build_signed_envelope(
    transaction_id: str,
    message_type: str,
    payload: dict,
    initiator_agent_id: str,
    tenant_id: str,
    session: AsyncSession,
) -> dict:
    """
    Build a signed A2A message envelope.

    Fetches the initiator agent's private_key_enc from agent_cards.
    Signs using har.crypto.sign_payload (Ed25519).
    Falls back to unsigned envelope if key not found.
    """
    key_result = await session.execute(
        text(
            "SELECT private_key_enc FROM agent_cards "
            "WHERE id = :agent_id AND tenant_id = :tenant_id"
        ),
        {"agent_id": initiator_agent_id, "tenant_id": tenant_id},
    )
    key_row = key_result.mappings().first()
    private_key_enc = key_row["private_key_enc"] if key_row else None

    envelope: dict = {
        "transaction_id": transaction_id,
        "message_type": message_type,
        "sender_agent_id": initiator_agent_id,
        "payload": payload,
    }

    if private_key_enc:
        try:
            from app.modules.har.crypto import sign_payload

            canonical = json.dumps(envelope, sort_keys=True)
            signature = sign_payload(canonical.encode(), private_key_enc)
            envelope["signature"] = signature
        except Exception as exc:
            logger.warning(
                "a2a_signing_failed_unsigned_envelope",
                transaction_id=transaction_id,
                initiator_agent_id=initiator_agent_id,
                error_type=type(exc).__name__,
            )
    else:
        logger.warning(
            "a2a_no_private_key_unsigned_envelope",
            transaction_id=transaction_id,
            initiator_agent_id=initiator_agent_id,
            tenant_id=tenant_id,
        )

    return envelope


async def _log_routing_event(
    transaction_id: str,
    tenant_id: str,
    message_type: str,
    target_agent_id: str,
    status_code: Optional[int],
    attempt: int,
    success: bool,
    session: AsyncSession,
) -> None:
    """Log a routing event to har_transaction_events."""
    import hashlib

    event_id = str(uuid.uuid4())
    event_type = "a2a_routed" if success else "a2a_routing_failed"
    event_payload = {
        "message_type": message_type,
        "target_agent_id": target_agent_id,
        "status_code": status_code,
        "attempt": attempt,
        "success": success,
    }
    # Simple hash for unsigned events
    hash_input = json.dumps(
        {"event_id": event_id, "event_type": event_type, "payload": event_payload},
        sort_keys=True,
    )
    event_hash = hashlib.sha256(hash_input.encode()).hexdigest()

    try:
        await session.execute(
            text(
                "INSERT INTO har_transaction_events "
                "(id, tenant_id, transaction_id, event_type, actor_agent_id, "
                "payload, event_hash) "
                "VALUES (:id, :tenant_id, :transaction_id, :event_type, "
                ":actor_agent_id, CAST(:payload AS jsonb), :event_hash)"
            ),
            {
                "id": event_id,
                "tenant_id": tenant_id,
                "transaction_id": transaction_id,
                "event_type": event_type,
                "actor_agent_id": target_agent_id,
                "payload": json.dumps(event_payload),
                "event_hash": event_hash,
            },
        )
        await session.commit()
    except Exception as exc:
        logger.error(
            "a2a_routing_event_log_failed",
            transaction_id=transaction_id,
            error_type=type(exc).__name__,
        )


async def _abandon_transaction(
    transaction_id: str,
    tenant_id: str,
    session: AsyncSession,
) -> None:
    """Set a transaction to ABANDONED when all routing retries are exhausted."""
    try:
        await session.execute(
            text(
                "UPDATE har_transactions SET state = 'ABANDONED', updated_at = NOW() "
                "WHERE id = :txn_id AND tenant_id = :tenant_id "
                "AND state NOT IN ('COMPLETED', 'ABANDONED', 'RESOLVED')"
            ),
            {"txn_id": transaction_id, "tenant_id": tenant_id},
        )
        await session.commit()
        logger.info(
            "a2a_transaction_abandoned_routing_failure",
            transaction_id=transaction_id,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.error(
            "a2a_transaction_abandon_failed",
            transaction_id=transaction_id,
            error_type=type(exc).__name__,
        )
