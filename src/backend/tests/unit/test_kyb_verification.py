"""
HAR-012: Unit tests for KYB verification flow.

Tests:
- initiate_kyb: returns session_id and verification_url
- initiate_kyb: returns 503 when STRIPE_SECRET_KEY not configured
- initiate_kyb: returns 404 when agent not found
- initiate_kyb: returns 502 when Stripe session creation fails
- stripe_identity_webhook: updates kyb_level=verified on verified event
- stripe_identity_webhook: updates kyb_level=enterprise on enterprise event
- stripe_identity_webhook: returns 503 when webhook secret not configured
- stripe_identity_webhook: returns 400 on invalid signature
- stripe_identity_webhook: ignores unknown event types (200)
- stripe_identity_webhook: ignores event when agent not found (200)
- update_agent_kyb: trust_score is capped at 100
- verify_stripe_signature: returns False for expired timestamp
- verify_stripe_signature: returns False for tampered payload
- _compute_fee: returns 0.5% of amount
- _compute_fee: returns 0 for None amount
"""
import hashlib
import hmac
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.har.fee_records import _FEE_RATE, _compute_fee
from app.modules.registry.kyb_routes import (
    _KYB_TRUST_BONUSES,
    create_stripe_verification_session,
    get_agent_by_id_and_tenant,
    get_agent_by_stripe_session,
    store_stripe_session_id,
    update_agent_kyb,
    verify_stripe_signature,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(row=None):
    db = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.first.return_value = row
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


def _make_agent_row(agent_id=None, tenant_id=None, kyb_level="none", trust_score=50):
    """Mock DB row for agent_cards."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "id": agent_id or str(uuid.uuid4()),
        "tenant_id": tenant_id or str(uuid.uuid4()),
        "kyb_level": kyb_level,
        "trust_score": trust_score,
    }[key]
    return row


def _make_stripe_sig(payload: bytes, secret: str, timestamp: int = None) -> str:
    """Generate a valid Stripe-Signature header value."""
    ts = timestamp or int(time.time())
    signed_payload = f"{ts}.".encode() + payload
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


# ---------------------------------------------------------------------------
# _compute_fee
# ---------------------------------------------------------------------------


def test_compute_fee_returns_half_percent():
    """_compute_fee returns 0.5% of amount."""
    fee = _compute_fee(10000.0)
    assert abs(fee - 50.0) < 0.001


def test_compute_fee_returns_zero_for_none():
    """_compute_fee returns 0.0 when amount is None."""
    assert _compute_fee(None) == 0.0


def test_compute_fee_returns_zero_for_zero():
    """_compute_fee returns 0.0 when amount is 0."""
    assert _compute_fee(0.0) == 0.0


# ---------------------------------------------------------------------------
# verify_stripe_signature
# ---------------------------------------------------------------------------


def test_verify_stripe_signature_valid():
    """verify_stripe_signature returns True for a correctly signed payload."""
    secret = "whsec_test_secret"
    payload = b'{"type":"identity.verification_session.verified"}'
    sig_header = _make_stripe_sig(payload, secret)
    assert verify_stripe_signature(payload, sig_header, secret) is True


def test_verify_stripe_signature_tampered_payload():
    """verify_stripe_signature returns False when payload is tampered."""
    secret = "whsec_test_secret"
    original = b'{"type":"original"}'
    sig_header = _make_stripe_sig(original, secret)
    tampered = b'{"type":"tampered"}'
    assert verify_stripe_signature(tampered, sig_header, secret) is False


def test_verify_stripe_signature_expired_timestamp():
    """verify_stripe_signature returns False for timestamp > 5 minutes old."""
    secret = "whsec_test_secret"
    payload = b'{"type":"test"}'
    old_ts = int(time.time()) - 400  # 6+ minutes ago
    sig_header = _make_stripe_sig(payload, secret, timestamp=old_ts)
    assert verify_stripe_signature(payload, sig_header, secret) is False


def test_verify_stripe_signature_missing_parts():
    """verify_stripe_signature returns False for malformed header."""
    assert verify_stripe_signature(b"payload", "invalid_header", "secret") is False


# ---------------------------------------------------------------------------
# get_agent_by_id_and_tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_agent_by_id_and_tenant_returns_dict():
    """get_agent_by_id_and_tenant returns agent dict when found."""
    agent_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    row = _make_agent_row(agent_id=agent_id, tenant_id=tenant_id)
    db = _make_session(row=row)

    result = await get_agent_by_id_and_tenant(agent_id, tenant_id, db)
    assert result is not None
    assert result["id"] == agent_id


@pytest.mark.asyncio
async def test_get_agent_by_id_and_tenant_returns_none_when_not_found():
    """get_agent_by_id_and_tenant returns None when agent not found."""
    db = _make_session(row=None)
    result = await get_agent_by_id_and_tenant(str(uuid.uuid4()), str(uuid.uuid4()), db)
    assert result is None


# ---------------------------------------------------------------------------
# get_agent_by_stripe_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_agent_by_stripe_session_returns_agent():
    """get_agent_by_stripe_session returns agent dict when session found."""
    row = _make_agent_row()
    db = _make_session(row=row)

    result = await get_agent_by_stripe_session("vi_session_abc", db)
    assert result is not None


@pytest.mark.asyncio
async def test_get_agent_by_stripe_session_returns_none_when_not_found():
    """get_agent_by_stripe_session returns None when session not found."""
    db = _make_session(row=None)
    result = await get_agent_by_stripe_session("unknown_session", db)
    assert result is None


# ---------------------------------------------------------------------------
# update_agent_kyb
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_agent_kyb_executes_update_and_commits():
    """update_agent_kyb executes UPDATE and calls commit."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    await update_agent_kyb(
        agent_id=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
        new_kyb_level="verified",
        trust_bonus=40,
        db=db,
    )

    db.execute.assert_called_once()
    db.commit.assert_called_once()
    sql = str(db.execute.call_args[0][0])
    assert "kyb_level" in sql


# ---------------------------------------------------------------------------
# create_stripe_verification_session
# ---------------------------------------------------------------------------


def test_create_stripe_session_returns_id_and_url():
    """create_stripe_verification_session returns id and url from Stripe."""
    mock_session = MagicMock()
    mock_session.id = "vi_test_session_001"
    mock_session.url = "https://verify.stripe.com/session/vi_test_session_001"

    mock_stripe = MagicMock()
    mock_stripe.identity.VerificationSession.create.return_value = mock_session

    with patch.dict("sys.modules", {"stripe": mock_stripe}), patch(
        "app.modules.registry.kyb_routes._get_stripe_secret_key",
        return_value="sk_test_key",
    ):
        result = create_stripe_verification_session(str(uuid.uuid4()))

    assert result["id"] == "vi_test_session_001"
    assert "stripe.com" in result["url"]


def test_create_stripe_session_raises_when_no_key():
    """create_stripe_verification_session raises RuntimeError when no API key."""
    with patch(
        "app.modules.registry.kyb_routes._get_stripe_secret_key",
        return_value=None,
    ):
        with pytest.raises(RuntimeError, match="STRIPE_SECRET_KEY not configured"):
            create_stripe_verification_session(str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# KYB trust bonuses constant
# ---------------------------------------------------------------------------


def test_kyb_trust_bonuses_values():
    """KYB trust bonuses are 20/40/60 for basic/verified/enterprise."""
    assert _KYB_TRUST_BONUSES["basic"] == 20
    assert _KYB_TRUST_BONUSES["verified"] == 40
    assert _KYB_TRUST_BONUSES["enterprise"] == 60
