"""
AI-051: HAR A2A Full Transaction Integration Test

Tests the end-to-end HAR A2A flow:
  1. Two agents are registered with Ed25519 keypairs
  2. Initiator creates a transaction (DRAFT → OPEN)
  3. Negotiation event created with valid Ed25519 signature
  4. Nonce replay is rejected
  5. Transaction committed, human approval gate triggered for large amounts
  6. Signature chain verified end-to-end
  7. State machine rejects invalid transitions

Architecture:
  - Real PostgreSQL (no mocking of DB)
  - Real Redis (nonce replay detection)
  - Ed25519 crypto uses real cryptography library
  - No LLM calls in this test suite

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_har_a2a_integration.py -v --timeout=60
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


def _make_engine():
    return create_async_engine(_db_url(), echo=False)


async def _run_sql(sql: str, params: dict = None):
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            await session.commit()
            return result
    finally:
        await engine.dispose()


async def _create_test_tenant() -> str:
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'enterprise', :email, 'active')",
        {
            "id": tid,
            "name": f"HAR Test {tid[:8]}",
            "slug": f"har-test-{tid[:8]}",
            "email": f"admin-{tid[:8]}@har-int.test",
        },
    )
    return tid


async def _create_test_user(tid: str) -> str:
    uid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO users (id, tenant_id, email, name, role, status) "
        "VALUES (:id, :tid, :email, :name, 'admin', 'active')",
        {
            "id": uid,
            "tid": tid,
            "email": f"admin-{uid[:8]}@har-int.test",
            "name": f"Test Admin {uid[:8]}",
        },
    )
    return uid


async def _create_test_agent(
    tid: str, uid: str, public_key: str, private_key_enc: str
) -> str:
    """Insert an agent_cards row with real Ed25519 keypair stored."""
    agent_id = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO agent_cards "
        "(id, tenant_id, name, description, system_prompt, status, version, created_by, "
        "public_key, private_key_enc, trust_score, kyb_level) "
        "VALUES (:id, :tid, :name, :desc, :prompt, 'published', 1, :uid, "
        ":pub_key, :priv_key_enc, 50, 2)",
        {
            "id": agent_id,
            "tid": tid,
            "name": f"HAR Agent {agent_id[:8]}",
            "desc": "Test agent for HAR integration",
            "prompt": "You are a test agent for HAR protocol verification.",
            "uid": uid,
            "pub_key": public_key,
            "priv_key_enc": private_key_enc,
        },
    )
    return agent_id


async def _cleanup_tenant(tid: str):
    tables = [
        "har_transaction_events",
        "har_transactions",
        "agent_cards",
        "users",
        "tenants",
    ]
    for table in tables:
        col = "tenant_id" if table != "tenants" else "id"
        await _run_sql(f"DELETE FROM {table} WHERE {col} = :tid", {"tid": tid})


# ---------------------------------------------------------------------------
# Skip if har module not yet available (agents still building it)
# ---------------------------------------------------------------------------


def _import_har_modules():
    """Import HAR modules, skip if not yet implemented."""
    try:
        from app.modules.har.crypto import (
            generate_agent_keypair,
            sign_payload,
            verify_signature,
        )
        from app.modules.har.signing import (
            check_nonce_replay,
            create_signed_event,
            verify_event_chain,
            verify_event_signature,
        )
        from app.modules.har.state_machine import (
            VALID_TRANSITIONS,
            get_transaction,
            transition_state,
        )

        return {
            "generate_agent_keypair": generate_agent_keypair,
            "sign_payload": sign_payload,
            "verify_signature": verify_signature,
            "check_nonce_replay": check_nonce_replay,
            "create_signed_event": create_signed_event,
            "verify_event_chain": verify_event_chain,
            "verify_event_signature": verify_event_signature,
            "VALID_TRANSITIONS": VALID_TRANSITIONS,
            "get_transaction": get_transaction,
            "transition_state": transition_state,
        }
    except ImportError as e:
        pytest.skip(f"HAR modules not yet available: {e}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHARCryptoIntegration:
    """Verify Ed25519 crypto with real keypairs stored in PostgreSQL."""

    def test_keypair_generation_and_storage(self):
        """Generate a keypair and store/retrieve from agent_cards table."""
        har = _import_har_modules()
        generate_agent_keypair = har["generate_agent_keypair"]
        verify_signature = har["verify_signature"]
        sign_payload = har["sign_payload"]

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                pub_key, priv_key_enc = generate_agent_keypair()
                agent_id = await _create_test_agent(tid, uid, pub_key, priv_key_enc)

                # Retrieve keys from DB
                result = await _run_sql(
                    "SELECT public_key, private_key_enc FROM agent_cards WHERE id = :id",
                    {"id": agent_id},
                )
                row = result.fetchone()
                assert row is not None
                stored_pub = row[0]
                stored_priv_enc = row[1]

                # Sign a payload and verify using stored keys
                payload = b"test payload for HAR A2A"
                signature = sign_payload(stored_priv_enc, payload)
                assert verify_signature(stored_pub, payload, signature) is True
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_signature_with_tampered_payload_fails(self):
        """Signature valid for original payload must fail against tampered payload."""
        har = _import_har_modules()
        generate_agent_keypair = har["generate_agent_keypair"]
        sign_payload = har["sign_payload"]
        verify_signature = har["verify_signature"]

        pub_key, priv_key_enc = generate_agent_keypair()
        original = b"original transaction payload"
        signature = sign_payload(priv_key_enc, original)
        tampered = b"tampered transaction payload"
        assert verify_signature(pub_key, tampered, signature) is False


class TestHARStateMachineIntegration:
    """Verify state transitions persist to har_transactions table."""

    def test_transaction_lifecycle_draft_to_completed(self):
        """
        Full lifecycle: DRAFT → OPEN → NEGOTIATING → COMMITTED → EXECUTING → COMPLETED.
        Each state is persisted and verifiable in DB.
        """
        har = _import_har_modules()
        transition_state = har["transition_state"]
        get_transaction = har["get_transaction"]

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                pub, priv = har["generate_agent_keypair"]()
                initiator_id = await _create_test_agent(tid, uid, pub, priv)
                pub2, priv2 = har["generate_agent_keypair"]()
                counterparty_id = await _create_test_agent(tid, uid, pub2, priv2)

                # Create transaction in DRAFT state
                txn_id = str(uuid.uuid4())
                await _run_sql(
                    "INSERT INTO har_transactions "
                    "(id, tenant_id, initiator_agent_id, counterparty_agent_id, state, amount, currency) "
                    "VALUES (:id, :tid, :init, :cp, 'DRAFT', 100.00, 'USD')",
                    {
                        "id": txn_id,
                        "tid": tid,
                        "init": initiator_id,
                        "cp": counterparty_id,
                    },
                )

                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )

                path = ["OPEN", "NEGOTIATING", "COMMITTED", "EXECUTING", "COMPLETED"]
                try:
                    async with factory() as db:
                        for new_state in path:
                            result = await transition_state(
                                transaction_id=txn_id,
                                new_state=new_state,
                                actor_agent_id=initiator_id,
                                actor_user_id=None,
                                tenant_id=tid,
                                db=db,
                            )
                            assert (
                                result["state"] == new_state
                            ), f"Expected state {new_state}, got {result['state']}"

                        # Verify final state in DB
                        final = await get_transaction(
                            transaction_id=txn_id, tenant_id=tid, db=db
                        )
                        assert final is not None
                        assert final["state"] == "COMPLETED"
                finally:
                    await engine.dispose()

            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_invalid_transition_rejected(self):
        """DRAFT → COMPLETED must raise HTTPException(400)."""
        har = _import_har_modules()
        transition_state = har["transition_state"]
        from fastapi import HTTPException

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                pub, priv = har["generate_agent_keypair"]()
                initiator_id = await _create_test_agent(tid, uid, pub, priv)
                pub2, priv2 = har["generate_agent_keypair"]()
                counterparty_id = await _create_test_agent(tid, uid, pub2, priv2)

                txn_id = str(uuid.uuid4())
                await _run_sql(
                    "INSERT INTO har_transactions "
                    "(id, tenant_id, initiator_agent_id, counterparty_agent_id, state) "
                    "VALUES (:id, :tid, :init, :cp, 'DRAFT')",
                    {
                        "id": txn_id,
                        "tid": tid,
                        "init": initiator_id,
                        "cp": counterparty_id,
                    },
                )

                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                try:
                    async with factory() as db:
                        with pytest.raises(HTTPException) as exc_info:
                            await transition_state(
                                transaction_id=txn_id,
                                new_state="COMPLETED",
                                actor_agent_id=initiator_id,
                                actor_user_id=None,
                                tenant_id=tid,
                                db=db,
                            )
                        assert exc_info.value.status_code == 400
                finally:
                    await engine.dispose()
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())


class TestHARSignatureChainIntegration:
    """Verify signature chain integrity with real DB and crypto."""

    def test_event_signature_verified_from_db(self):
        """
        Create a signed event, store it, then verify signature retrieves
        public key from agent_cards and verifies successfully.
        """
        har = _import_har_modules()
        create_signed_event = har["create_signed_event"]
        verify_event_signature = har["verify_event_signature"]
        verify_event_chain = har["verify_event_chain"]

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                pub, priv = har["generate_agent_keypair"]()
                initiator_id = await _create_test_agent(tid, uid, pub, priv)
                pub2, priv2 = har["generate_agent_keypair"]()
                counterparty_id = await _create_test_agent(tid, uid, pub2, priv2)

                txn_id = str(uuid.uuid4())
                await _run_sql(
                    "INSERT INTO har_transactions "
                    "(id, tenant_id, initiator_agent_id, counterparty_agent_id, state) "
                    "VALUES (:id, :tid, :init, :cp, 'OPEN')",
                    {
                        "id": txn_id,
                        "tid": tid,
                        "init": initiator_id,
                        "cp": counterparty_id,
                    },
                )

                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                try:
                    async with factory() as db:
                        # Create first signed event
                        event1 = await create_signed_event(
                            transaction_id=txn_id,
                            event_type="state_transition",
                            actor_agent_id=initiator_id,
                            payload={"from": "DRAFT", "to": "OPEN"},
                            actor_private_key_enc=priv,
                            prev_event_hash=None,
                            tenant_id=tid,
                            db=db,
                        )
                        assert "event_hash" in event1
                        assert event1["signature"] is not None

                        # Verify event signature via DB lookup
                        valid = await verify_event_signature(event1["id"], db)
                        assert (
                            valid is True
                        ), "Event signature must verify against stored public key"

                        # Create second chained event
                        event2 = await create_signed_event(
                            transaction_id=txn_id,
                            event_type="state_transition",
                            actor_agent_id=counterparty_id,
                            payload={"from": "OPEN", "to": "NEGOTIATING"},
                            actor_private_key_enc=priv2,
                            prev_event_hash=event1["event_hash"],
                            tenant_id=tid,
                            db=db,
                        )
                        assert event2["prev_event_hash"] == event1["event_hash"]

                        # Verify the full chain
                        chain_valid = await verify_event_chain(txn_id, db)
                        assert chain_valid is True, "Signature chain must be intact"
                finally:
                    await engine.dispose()
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_nonce_replay_rejected_with_real_redis(self):
        """Same nonce must be rejected on second use (real Redis check)."""
        har = _import_har_modules()
        check_nonce_replay = har["check_nonce_replay"]
        import app.core.redis_client as _redis_mod
        from app.core.redis_client import close_redis, get_redis

        async def _run():
            # Reset redis pool for clean state
            _redis_mod._redis_pool = None
            redis = get_redis()
            tid = str(uuid.uuid4())
            nonce = f"test-nonce-{uuid.uuid4().hex}"
            try:
                is_fresh = await check_nonce_replay(nonce, tid, redis)
                assert is_fresh is True, "First use of nonce must be accepted"

                is_replay = await check_nonce_replay(nonce, tid, redis)
                assert is_replay is False, "Replay of same nonce must be rejected"
            finally:
                await redis.delete(f"{tid}:nonce:{nonce}")
                await close_redis()

        asyncio.run(_run())


class TestHARHumanApprovalGate:
    """Verify human approval gate for large transactions."""

    def test_large_amount_sets_requires_approval(self):
        """Amount >= 5000 must set requires_human_approval=True."""
        har = _import_har_modules()
        # We test this via the check_requires_approval function
        from app.modules.har.state_machine import check_requires_approval

        async def _run():
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            tid = await _create_test_tenant()
            try:
                async with factory() as db:
                    # Below threshold
                    result_low = await check_requires_approval(4999.99, tid, db)
                    assert result_low is False

                    # At threshold
                    result_at = await check_requires_approval(5000.0, tid, db)
                    assert result_at is True

                    # Above threshold
                    result_high = await check_requires_approval(100000.0, tid, db)
                    assert result_high is True

                    # No amount (optional field)
                    result_none = await check_requires_approval(None, tid, db)
                    assert result_none is False
            finally:
                await _cleanup_tenant(tid)
                await engine.dispose()

        asyncio.run(_run())
