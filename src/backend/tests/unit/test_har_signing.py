"""
Unit tests for HAR A2A message signing module (AI-041, AI-042).

Tests signed event creation, nonce replay detection, and event chain verification.
Tier 1: Fast, isolated, uses mocks for DB and Redis.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

TEST_JWT_SECRET = "a" * 64
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"
TEST_AGENT_ID = "aaaaaaaa-1111-2222-3333-444444444444"
TEST_TRANSACTION_ID = "bbbbbbbb-1111-2222-3333-444444444444"


@pytest.fixture(autouse=True)
def env_vars():
    """Set JWT_SECRET_KEY for all tests in this module."""
    with patch.dict(os.environ, {"JWT_SECRET_KEY": TEST_JWT_SECRET}):
        yield


@pytest.fixture
def mock_db():
    """Create a mock AsyncSession for unit tests."""
    db = AsyncMock()
    return db


@pytest.fixture
def mock_redis():
    """Create a mock Redis client for unit tests."""
    redis = AsyncMock()
    return redis


@pytest.fixture
def agent_keypair():
    """Generate a fresh keypair for test use."""
    from app.modules.har.crypto import generate_agent_keypair

    return generate_agent_keypair()


class TestCreateSignedEvent:
    """Test create_signed_event() produces well-formed signed events."""

    @pytest.mark.asyncio
    async def test_signed_event_has_all_fields(self, mock_db, agent_keypair):
        """Created event must have nonce, signature, event_hash, prev_event_hash."""
        from app.modules.har.signing import create_signed_event

        _, private_key_enc = agent_keypair

        # Mock the DB execute to return a mock result with the inserted row
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = {
            "id": str(uuid.uuid4()),
            "tenant_id": TEST_TENANT_ID,
            "transaction_id": TEST_TRANSACTION_ID,
            "event_type": "PROPOSE",
            "actor_agent_id": TEST_AGENT_ID,
            "payload": {"amount": 100},
            "signature": "sig_placeholder",
            "nonce": "nonce_placeholder",
            "prev_event_hash": None,
            "event_hash": "hash_placeholder",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        mock_db.execute = AsyncMock(return_value=mock_result)

        event = await create_signed_event(
            transaction_id=TEST_TRANSACTION_ID,
            event_type="PROPOSE",
            actor_agent_id=TEST_AGENT_ID,
            payload={"amount": 100},
            actor_private_key_enc=private_key_enc,
            prev_event_hash=None,
            tenant_id=TEST_TENANT_ID,
            db=mock_db,
        )

        # Must have all required fields
        assert "nonce" in event, "Event must contain nonce"
        assert "signature" in event, "Event must contain signature"
        assert "event_hash" in event, "Event must contain event_hash"
        assert "prev_event_hash" in event, "Event must contain prev_event_hash"
        assert "event_type" in event, "Event must contain event_type"
        assert "transaction_id" in event, "Event must contain transaction_id"
        assert "actor_agent_id" in event, "Event must contain actor_agent_id"

        # Nonce must be 64 hex chars (32 bytes)
        assert (
            len(event["nonce"]) == 64
        ), f"Nonce must be 64 hex chars, got {len(event['nonce'])}"

        # Signature must be non-empty base64url string
        assert len(event["signature"]) > 0, "Signature must be non-empty"

        # event_hash must be a hex sha256 (64 chars)
        assert (
            len(event["event_hash"]) == 64
        ), f"event_hash must be 64 hex chars (sha256), got {len(event['event_hash'])}"

    @pytest.mark.asyncio
    async def test_signed_event_with_prev_hash(self, mock_db, agent_keypair):
        """Created event should carry prev_event_hash when provided."""
        from app.modules.har.signing import create_signed_event

        _, private_key_enc = agent_keypair
        prev_hash = "a" * 64

        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = {
            "id": str(uuid.uuid4()),
            "tenant_id": TEST_TENANT_ID,
            "transaction_id": TEST_TRANSACTION_ID,
            "event_type": "ACCEPT",
            "actor_agent_id": TEST_AGENT_ID,
            "payload": {},
            "signature": "sig",
            "nonce": "n" * 64,
            "prev_event_hash": prev_hash,
            "event_hash": "h" * 64,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        mock_db.execute = AsyncMock(return_value=mock_result)

        event = await create_signed_event(
            transaction_id=TEST_TRANSACTION_ID,
            event_type="ACCEPT",
            actor_agent_id=TEST_AGENT_ID,
            payload={},
            actor_private_key_enc=private_key_enc,
            prev_event_hash=prev_hash,
            tenant_id=TEST_TENANT_ID,
            db=mock_db,
        )

        assert event["prev_event_hash"] == prev_hash

    @pytest.mark.asyncio
    async def test_signed_event_calls_db_insert(self, mock_db, agent_keypair):
        """create_signed_event must INSERT into har_transaction_events."""
        from app.modules.har.signing import create_signed_event

        _, private_key_enc = agent_keypair

        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = {
            "id": str(uuid.uuid4()),
            "tenant_id": TEST_TENANT_ID,
            "transaction_id": TEST_TRANSACTION_ID,
            "event_type": "PROPOSE",
            "actor_agent_id": TEST_AGENT_ID,
            "payload": {},
            "signature": "sig",
            "nonce": "n" * 64,
            "prev_event_hash": None,
            "event_hash": "h" * 64,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        mock_db.execute = AsyncMock(return_value=mock_result)

        await create_signed_event(
            transaction_id=TEST_TRANSACTION_ID,
            event_type="PROPOSE",
            actor_agent_id=TEST_AGENT_ID,
            payload={},
            actor_private_key_enc=private_key_enc,
            prev_event_hash=None,
            tenant_id=TEST_TENANT_ID,
            db=mock_db,
        )

        # DB execute must have been called (INSERT INTO har_transaction_events)
        assert (
            mock_db.execute.call_count >= 1
        ), "DB execute must be called at least once"
        assert mock_db.commit.call_count >= 1, "DB commit must be called after INSERT"

        # Verify the INSERT was for har_transaction_events with tenant_id scoping.
        # TextClause exposes SQL via .text attribute; params are the second positional arg.
        insert_found = False
        tenant_scoped = False
        for call in mock_db.execute.call_args_list:
            sql_arg = call.args[0] if call.args else None
            params_arg = call.args[1] if len(call.args) > 1 else (call.kwargs or {})
            sql_text = getattr(sql_arg, "text", str(sql_arg))
            if "INSERT INTO har_transaction_events" in sql_text:
                insert_found = True
                if TEST_TENANT_ID in str(params_arg):
                    tenant_scoped = True
        assert insert_found, "Must INSERT into har_transaction_events"
        assert tenant_scoped, "INSERT params must include tenant_id for isolation"


class TestNonceReplay:
    """Test check_nonce_replay() for replay attack detection."""

    @pytest.mark.asyncio
    async def test_nonce_replay_fresh_nonce_returns_true(self, mock_redis):
        """First use of a nonce should return True (fresh)."""
        from app.modules.har.signing import check_nonce_replay

        # SETNX returns True when key didn't exist (fresh nonce)
        mock_redis.set = AsyncMock(return_value=True)

        result = await check_nonce_replay("abc123", TEST_TENANT_ID, mock_redis)
        assert result is True

    @pytest.mark.asyncio
    async def test_nonce_replay_rejected(self, mock_redis):
        """Second call with same nonce must return False (replayed)."""
        from app.modules.har.signing import check_nonce_replay

        # First call: fresh
        mock_redis.set = AsyncMock(return_value=True)
        result1 = await check_nonce_replay("nonce1", TEST_TENANT_ID, mock_redis)
        assert result1 is True

        # Second call: replayed (SETNX returns False)
        mock_redis.set = AsyncMock(return_value=False)
        result2 = await check_nonce_replay("nonce1", TEST_TENANT_ID, mock_redis)
        assert result2 is False

    @pytest.mark.asyncio
    async def test_nonce_replay_sets_ttl(self, mock_redis):
        """Nonce key must have a TTL of 600 seconds."""
        from app.modules.har.signing import check_nonce_replay

        mock_redis.set = AsyncMock(return_value=True)

        await check_nonce_replay("nonce_ttl", TEST_TENANT_ID, mock_redis)

        # Verify set was called with nx=True and ex=600
        mock_redis.set.assert_called_once()
        call_kwargs = mock_redis.set.call_args
        # Check the key format includes tenant_id and nonce
        key = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("name", "")
        assert TEST_TENANT_ID in key, "Redis key must include tenant_id"
        assert "nonce_ttl" in key, "Redis key must include the nonce value"
        # Verify TTL and SETNX semantics are enforced
        assert (
            call_kwargs.kwargs.get("nx") is True
        ), "Must use nx=True for SETNX semantics"
        assert call_kwargs.kwargs.get("ex") == 600, "TTL must be 600 seconds"


class TestVerifyEventChain:
    """Test verify_event_chain() for hash chain integrity."""

    @pytest.mark.asyncio
    async def test_verify_event_chain_empty_transaction(self, mock_db):
        """No events for a transaction → True (vacuously valid)."""
        from app.modules.har.signing import verify_event_chain

        # Return empty result set
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await verify_event_chain(TEST_TRANSACTION_ID, mock_db)
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_event_chain_single_event(self, mock_db):
        """Single event with prev_event_hash=None → True."""
        from app.modules.har.signing import verify_event_chain

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [
            {
                "id": str(uuid.uuid4()),
                "prev_event_hash": None,
                "event_hash": "a" * 64,
            }
        ]
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await verify_event_chain(TEST_TRANSACTION_ID, mock_db)
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_event_chain_valid_two_events(self, mock_db):
        """Two events with correct prev_event_hash linkage → True."""
        from app.modules.har.signing import verify_event_chain

        hash_1 = "a" * 64
        hash_2 = "b" * 64

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [
            {
                "id": str(uuid.uuid4()),
                "prev_event_hash": None,
                "event_hash": hash_1,
            },
            {
                "id": str(uuid.uuid4()),
                "prev_event_hash": hash_1,
                "event_hash": hash_2,
            },
        ]
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await verify_event_chain(TEST_TRANSACTION_ID, mock_db)
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_event_chain_broken_linkage(self, mock_db):
        """Events with incorrect prev_event_hash → False."""
        from app.modules.har.signing import verify_event_chain

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [
            {
                "id": str(uuid.uuid4()),
                "prev_event_hash": None,
                "event_hash": "a" * 64,
            },
            {
                "id": str(uuid.uuid4()),
                "prev_event_hash": "wrong_hash",  # should be "a" * 64
                "event_hash": "b" * 64,
            },
        ]
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await verify_event_chain(TEST_TRANSACTION_ID, mock_db)
        assert result is False


class TestVerifyEventSignature:
    """Test verify_event_signature() fetches event + agent and verifies."""

    @pytest.mark.asyncio
    async def test_verify_event_signature_valid(self, mock_db, agent_keypair):
        """Valid event signature should verify True."""
        from app.modules.har.crypto import sign_payload
        from app.modules.har.signing import verify_event_signature

        public_key_b64, private_key_enc = agent_keypair

        # Build the canonical payload that would have been signed
        import hashlib
        import json as json_mod

        canonical_dict = {
            "transaction_id": TEST_TRANSACTION_ID,
            "event_type": "PROPOSE",
            "actor_agent_id": TEST_AGENT_ID,
            "payload": {"amount": 100},
            "nonce": "n" * 64,
            "timestamp": "2026-03-08T00:00:00+00:00",
        }
        canonical_bytes = json_mod.dumps(canonical_dict, sort_keys=True).encode()
        signature = sign_payload(private_key_enc, canonical_bytes)
        event_hash = hashlib.sha256(canonical_bytes + signature.encode()).hexdigest()

        event_id = str(uuid.uuid4())

        # Mock: first call returns event, second call returns agent public key
        event_row = {
            "id": event_id,
            "transaction_id": TEST_TRANSACTION_ID,
            "event_type": "PROPOSE",
            "actor_agent_id": TEST_AGENT_ID,
            "payload": {"amount": 100},
            "nonce": "n" * 64,
            "signature": signature,
            "event_hash": event_hash,
            "created_at": "2026-03-08T00:00:00+00:00",
        }
        agent_row = {"public_key": public_key_b64}

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.mappings.return_value.first.return_value = event_row
            else:
                result.mappings.return_value.first.return_value = agent_row
            return result

        mock_db.execute = mock_execute

        result = await verify_event_signature(event_id, mock_db)
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_event_signature_missing_event(self, mock_db):
        """Event not found in DB should return False."""
        from app.modules.har.signing import verify_event_signature

        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await verify_event_signature("nonexistent-id", mock_db)
        assert result is False
