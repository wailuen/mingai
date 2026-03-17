"""
HAR-012: KYB (Know Your Business) verification flow via Stripe Identity.

Endpoints:
- POST /registry/agents/{agent_id}/kyb/initiate  — Start a Stripe Identity verification session
- POST /webhooks/stripe/identity                  — Stripe webhook: update kyb_level + trust_score

The initiate endpoint returns a Stripe-hosted verification URL and session_id.
The webhook endpoint validates Stripe-Signature HMAC, then updates the
agent_cards row with the appropriate kyb_level and adds a trust_score bonus.

KYB level and trust score bonuses:
  basic      → +20 trust_score
  verified   → +40 trust_score
  enterprise → +60 trust_score

Environment variables:
  STRIPE_SECRET_KEY            — Stripe API secret key
  STRIPE_IDENTITY_WEBHOOK_SECRET — Stripe webhook signing secret

Endpoint is fail-closed: returns 503 when STRIPE_SECRET_KEY is absent.
Webhook returns 503 when STRIPE_IDENTITY_WEBHOOK_SECRET is absent.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(tags=["kyb"])

# ---------------------------------------------------------------------------
# KYB trust score bonuses
# ---------------------------------------------------------------------------

_KYB_TRUST_BONUSES: dict[str, int] = {
    "basic": 20,
    "verified": 40,
    "enterprise": 60,
}

# ---------------------------------------------------------------------------
# Stripe client helper (isolated for testability)
# ---------------------------------------------------------------------------


def _get_stripe_secret_key() -> Optional[str]:
    return os.environ.get("STRIPE_SECRET_KEY")


def _get_webhook_secret() -> Optional[str]:
    return os.environ.get("STRIPE_IDENTITY_WEBHOOK_SECRET")


def create_stripe_verification_session(agent_id: str) -> dict:
    """
    Create a Stripe Identity verification session for the agent.

    Returns dict with keys: id, url
    Raises RuntimeError on Stripe API errors.
    """
    secret_key = _get_stripe_secret_key()
    if not secret_key:
        raise RuntimeError("STRIPE_SECRET_KEY not configured")

    try:
        import stripe  # type: ignore[import-not-found]

        stripe.api_key = secret_key
        session = stripe.identity.VerificationSession.create(
            type="document",
            metadata={"agent_id": agent_id},
            options={
                "document": {
                    "allowed_types": ["driving_license", "id_card", "passport"],
                    "require_live_capture": True,
                    "require_matching_selfie": True,
                },
            },
        )
        return {"id": session.id, "url": session.url}
    except Exception as exc:
        raise RuntimeError(
            f"Stripe verification session creation failed: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def get_agent_by_id_and_tenant(
    agent_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[dict]:
    """Fetch minimal agent card fields needed for KYB operations."""
    result = await db.execute(
        text(
            "SELECT id, tenant_id, kyb_level, trust_score "
            "FROM agent_cards "
            "WHERE id = :id AND tenant_id = :tenant_id AND status != 'deregistered'"
        ),
        {"id": agent_id, "tenant_id": tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "kyb_level": row["kyb_level"] or "none",
        "trust_score": float(row["trust_score"])
        if row["trust_score"] is not None
        else 0.0,
    }


async def get_agent_by_stripe_session(
    stripe_session_id: str,
    db: AsyncSession,
) -> Optional[dict]:
    """Find an agent card by its stored Stripe verification session ID."""
    result = await db.execute(
        text(
            "SELECT id, tenant_id, kyb_level, trust_score "
            "FROM agent_cards "
            "WHERE kyb_stripe_session_id = :session_id"
        ),
        {"session_id": stripe_session_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "kyb_level": row["kyb_level"] or "none",
        "trust_score": float(row["trust_score"])
        if row["trust_score"] is not None
        else 0.0,
    }


async def update_agent_kyb(
    agent_id: str,
    tenant_id: str,
    new_kyb_level: str,
    trust_bonus: int,
    db: AsyncSession,
) -> None:
    """
    Update agent_cards with new kyb_level and incremented trust_score.
    trust_score is capped at 100.
    """
    await db.execute(
        text(
            "UPDATE agent_cards "
            "SET kyb_level = :kyb_level, "
            "trust_score = LEAST(trust_score + :bonus, 100), "
            "updated_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {
            "kyb_level": new_kyb_level,
            "bonus": trust_bonus,
            "id": agent_id,
            "tenant_id": tenant_id,
        },
    )
    await db.commit()


async def store_stripe_session_id(
    agent_id: str,
    tenant_id: str,
    stripe_session_id: str,
    db: AsyncSession,
) -> None:
    """Persist the Stripe verification session ID on the agent card."""
    await db.execute(
        text(
            "UPDATE agent_cards "
            "SET kyb_stripe_session_id = :session_id, updated_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"session_id": stripe_session_id, "id": agent_id, "tenant_id": tenant_id},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Stripe webhook signature validation
# ---------------------------------------------------------------------------


def verify_stripe_signature(
    payload: bytes,
    stripe_signature: str,
    webhook_secret: str,
) -> bool:
    """
    Validate a Stripe webhook signature.

    Stripe-Signature format: t=<timestamp>,v1=<signature>[,v1=<sig2>...]
    Returns True if ANY of the v1 signatures match (Stripe may send multiple).
    """
    try:
        # Parse all parts without using dict() to preserve duplicate v1 keys
        timestamp: Optional[str] = None
        v1_signatures: list[str] = []
        for item in stripe_signature.split(","):
            if not item:
                continue
            key, _, val = item.partition("=")
            if key == "t":
                timestamp = val
            elif key == "v1":
                v1_signatures.append(val)

        if not timestamp or not v1_signatures:
            return False

        # Reject signatures older than 5 minutes
        if abs(time.time() - int(timestamp)) > 300:
            return False

        signed_payload = f"{timestamp}.".encode() + payload
        expected = hmac.new(
            webhook_secret.encode(),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        # Accept if ANY of the provided v1 signatures match (Stripe rotation pattern)
        return any(hmac.compare_digest(expected, sig) for sig in v1_signatures)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Route: initiate KYB
# ---------------------------------------------------------------------------


@router.post("/registry/agents/{agent_id}/kyb/initiate", status_code=status.HTTP_200_OK)
async def initiate_kyb(
    agent_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    HAR-012: Initiate a Stripe Identity KYB verification session for an agent.

    Returns: { "session_id": "...", "verification_url": "..." }
    """
    secret_key = _get_stripe_secret_key()
    if not secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="KYB verification service is not configured",
        )

    agent = await get_agent_by_id_and_tenant(agent_id, current_user.tenant_id, session)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    try:
        stripe_session = create_stripe_verification_session(agent_id)
    except RuntimeError as exc:
        logger.error(
            "kyb_stripe_session_creation_failed",
            agent_id=agent_id,
            tenant_id=current_user.tenant_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to create verification session",
        )

    await store_stripe_session_id(
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        stripe_session_id=stripe_session["id"],
        db=session,
    )

    logger.info(
        "kyb_session_initiated",
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        stripe_session_id=stripe_session["id"],
    )

    return {
        "session_id": stripe_session["id"],
        "verification_url": stripe_session["url"],
    }


# ---------------------------------------------------------------------------
# Route: Stripe Identity webhook
# ---------------------------------------------------------------------------


@router.post("/webhooks/stripe/identity", status_code=status.HTTP_200_OK)
async def stripe_identity_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
    session: AsyncSession = Depends(get_async_session),
):
    """
    HAR-012: Stripe Identity webhook endpoint.

    Validates Stripe-Signature HMAC, then updates agent kyb_level and trust_score
    based on the verification result.

    Supported events:
      identity.verification_session.verified   → 'verified'
      identity.verification_session.requires_input (with metadata.kyb_tier=enterprise) → 'enterprise'

    Returns 503 if STRIPE_IDENTITY_WEBHOOK_SECRET is not configured (fail-closed).
    Returns 400 if signature validation fails.
    Returns 200 for all processed events (including unknown event types — idempotent).
    """
    webhook_secret = _get_webhook_secret()
    if not webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook processing is not configured",
        )

    if not stripe_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe-Signature header",
        )

    raw_body = await request.body()

    if not verify_stripe_signature(raw_body, stripe_signature, webhook_secret):
        logger.warning(
            "stripe_identity_webhook_invalid_signature",
            stripe_signature=stripe_signature[:20] if stripe_signature else None,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature",
        )

    import json

    try:
        event = json.loads(raw_body)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    event_type = event.get("type", "")
    event_data = event.get("data", {}).get("object", {})
    stripe_session_id = event_data.get("id")
    metadata = event_data.get("metadata", {})

    if not stripe_session_id:
        # Unrecognised event shape — acknowledge without processing
        return {"received": True}

    # Determine new KYB level from event type
    if event_type == "identity.verification_session.verified":
        new_kyb_level = "verified"
    elif (
        event_type == "identity.verification_session.requires_input"
        and metadata.get("kyb_tier") == "enterprise"
    ):
        new_kyb_level = "enterprise"
    else:
        # Unhandled event type — acknowledge without processing
        logger.info(
            "stripe_identity_webhook_ignored",
            event_type=event_type,
            stripe_session_id=stripe_session_id,
        )
        return {"received": True}

    # Look up agent by Stripe session ID
    agent = await get_agent_by_stripe_session(stripe_session_id, session)
    if agent is None:
        logger.warning(
            "stripe_identity_webhook_agent_not_found",
            stripe_session_id=stripe_session_id,
        )
        return {"received": True}

    trust_bonus = _KYB_TRUST_BONUSES.get(new_kyb_level, 0)
    await update_agent_kyb(
        agent_id=agent["id"],
        tenant_id=agent["tenant_id"],
        new_kyb_level=new_kyb_level,
        trust_bonus=trust_bonus,
        db=session,
    )

    logger.info(
        "kyb_updated_from_webhook",
        agent_id=agent["id"],
        tenant_id=agent["tenant_id"],
        new_kyb_level=new_kyb_level,
        trust_bonus=trust_bonus,
        stripe_session_id=stripe_session_id,
    )

    return {"received": True}
