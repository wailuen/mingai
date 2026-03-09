"""
TEST-047: Audit Log Tamper-Evidence Integration Tests

Tests that the HAR signed event chain detects tampering:
1. Valid chain verifies clean
2. Altering middle event breaks chain from that point
3. Deleting middle event breaks chain
4. Altering genesis event breaks entire chain
5. Appending event keeps chain valid
6. Verification is read-only (no side effects)

Tier 2: Real PostgreSQL + Redis, NO MOCKING.

Architecture:
  Uses the existing session-scoped TestClient from conftest.py.
  Direct DB manipulation via asyncio.run() with fresh async engines
  to simulate tampering (UPDATE/DELETE on har_transaction_events).

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_audit_tamper_evidence.py -v --timeout=60
"""
import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured -- skipping integration tests")
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


async def _fetch_one(sql: str, params: dict = None):
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            return result.fetchone()
    finally:
        await engine.dispose()


async def _fetch_scalar(sql: str, params: dict = None):
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            return result.scalar()
    finally:
        await engine.dispose()


async def _create_test_tenant() -> str:
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'enterprise', :email, 'active')",
        {
            "id": tid,
            "name": f"Tamper Test {tid[:8]}",
            "slug": f"tamper-test-{tid[:8]}",
            "email": f"admin-{tid[:8]}@tamper-test.test",
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
            "email": f"admin-{uid[:8]}@tamper-test.test",
            "name": f"Tamper Test Admin {uid[:8]}",
        },
    )
    return uid


async def _create_test_agent(
    tid: str, uid: str, pub_key: str, priv_key_enc: str
) -> str:
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
            "name": f"Tamper Agent {agent_id[:8]}",
            "desc": "Test agent for tamper evidence",
            "prompt": "You are a test agent.",
            "uid": uid,
            "pub_key": pub_key,
            "priv_key_enc": priv_key_enc,
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
# HAR module imports
# ---------------------------------------------------------------------------


def _import_har():
    try:
        from app.modules.har.crypto import generate_agent_keypair
        from app.modules.har.signing import (
            create_signed_event,
            verify_event_chain,
        )

        return {
            "generate_agent_keypair": generate_agent_keypair,
            "create_signed_event": create_signed_event,
            "verify_event_chain": verify_event_chain,
        }
    except ImportError as e:
        pytest.skip(f"HAR modules not yet available: {e}")


# ---------------------------------------------------------------------------
# Helper: create a chain of N signed events for a transaction
# ---------------------------------------------------------------------------


async def _create_event_chain(har, tid, agent_id, priv_key, txn_id, count):
    """Create `count` signed events chained together. Returns list of event dicts."""
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    events = []
    try:
        async with factory() as db:
            prev_hash = None
            for i in range(count):
                event = await har["create_signed_event"](
                    transaction_id=txn_id,
                    event_type="state_transition",
                    actor_agent_id=agent_id,
                    payload={"step": i + 1},
                    actor_private_key_enc=priv_key,
                    prev_event_hash=prev_hash,
                    tenant_id=tid,
                    db=db,
                )
                events.append(event)
                prev_hash = event["event_hash"]
    finally:
        await engine.dispose()
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAuditTamperEvidence:
    """TEST-047: Verify tamper-evidence of signed event chain."""

    def test_write_10_events_chain_verifies(self):
        """Write 10 events via signing module, verify_event_chain() returns True."""
        har = _import_har()

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                pub, priv = har["generate_agent_keypair"]()
                agent_id = await _create_test_agent(tid, uid, pub, priv)

                txn_id = str(uuid.uuid4())
                await _run_sql(
                    "INSERT INTO har_transactions "
                    "(id, tenant_id, initiator_agent_id, counterparty_agent_id, state) "
                    "VALUES (:id, :tid, :agent, :agent, 'OPEN')",
                    {"id": txn_id, "tid": tid, "agent": agent_id},
                )

                await _create_event_chain(har, tid, agent_id, priv, txn_id, 10)

                # Verify chain integrity
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                try:
                    async with factory() as db:
                        chain_valid = await har["verify_event_chain"](txn_id, db)
                        assert chain_valid is True, "10-event chain must verify cleanly"
                finally:
                    await engine.dispose()
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_alter_middle_event_breaks_chain(self):
        """Write 5 events, tamper with event 3's event_hash, chain should break."""
        har = _import_har()

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                pub, priv = har["generate_agent_keypair"]()
                agent_id = await _create_test_agent(tid, uid, pub, priv)

                txn_id = str(uuid.uuid4())
                await _run_sql(
                    "INSERT INTO har_transactions "
                    "(id, tenant_id, initiator_agent_id, counterparty_agent_id, state) "
                    "VALUES (:id, :tid, :agent, :agent, 'OPEN')",
                    {"id": txn_id, "tid": tid, "agent": agent_id},
                )

                events = await _create_event_chain(har, tid, agent_id, priv, txn_id, 5)

                # Tamper: alter event 3's event_hash directly in DB
                tampered_hash = "deadbeef" * 8  # 64-char fake hash
                await _run_sql(
                    "UPDATE har_transaction_events SET event_hash = :fake_hash "
                    "WHERE id = :eid",
                    {"fake_hash": tampered_hash, "eid": events[2]["id"]},
                )

                # Verify chain -- should detect tampering
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                try:
                    async with factory() as db:
                        chain_valid = await har["verify_event_chain"](txn_id, db)
                        assert (
                            chain_valid is False
                        ), "Chain must break when middle event hash is tampered"
                finally:
                    await engine.dispose()
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_delete_middle_event_breaks_chain(self):
        """Write 5 events, DELETE event 3, chain should break at the gap."""
        har = _import_har()

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                pub, priv = har["generate_agent_keypair"]()
                agent_id = await _create_test_agent(tid, uid, pub, priv)

                txn_id = str(uuid.uuid4())
                await _run_sql(
                    "INSERT INTO har_transactions "
                    "(id, tenant_id, initiator_agent_id, counterparty_agent_id, state) "
                    "VALUES (:id, :tid, :agent, :agent, 'OPEN')",
                    {"id": txn_id, "tid": tid, "agent": agent_id},
                )

                events = await _create_event_chain(har, tid, agent_id, priv, txn_id, 5)

                # Delete event 3 (index 2) directly from DB
                await _run_sql(
                    "DELETE FROM har_transaction_events WHERE id = :eid",
                    {"eid": events[2]["id"]},
                )

                # Verify chain -- should detect the gap
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                try:
                    async with factory() as db:
                        chain_valid = await har["verify_event_chain"](txn_id, db)
                        assert (
                            chain_valid is False
                        ), "Chain must break when an event is deleted from the middle"
                finally:
                    await engine.dispose()
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_alter_genesis_event_breaks_entire_chain(self):
        """Write 5 events, tamper with event 1's event_hash, entire chain fails."""
        har = _import_har()

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                pub, priv = har["generate_agent_keypair"]()
                agent_id = await _create_test_agent(tid, uid, pub, priv)

                txn_id = str(uuid.uuid4())
                await _run_sql(
                    "INSERT INTO har_transactions "
                    "(id, tenant_id, initiator_agent_id, counterparty_agent_id, state) "
                    "VALUES (:id, :tid, :agent, :agent, 'OPEN')",
                    {"id": txn_id, "tid": tid, "agent": agent_id},
                )

                events = await _create_event_chain(har, tid, agent_id, priv, txn_id, 5)

                # Tamper: alter genesis event (index 0) event_hash
                tampered_hash = "abcdef01" * 8
                await _run_sql(
                    "UPDATE har_transaction_events SET event_hash = :fake_hash "
                    "WHERE id = :eid",
                    {"fake_hash": tampered_hash, "eid": events[0]["id"]},
                )

                # Verify chain -- event 2 expects event 1's original hash as prev_event_hash
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                try:
                    async with factory() as db:
                        chain_valid = await har["verify_event_chain"](txn_id, db)
                        assert (
                            chain_valid is False
                        ), "Altering genesis event must break entire chain"
                finally:
                    await engine.dispose()
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_append_event_keeps_chain_valid(self):
        """Write 3 events (valid chain), add 4th via normal signing, chain still valid."""
        har = _import_har()

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                pub, priv = har["generate_agent_keypair"]()
                agent_id = await _create_test_agent(tid, uid, pub, priv)

                txn_id = str(uuid.uuid4())
                await _run_sql(
                    "INSERT INTO har_transactions "
                    "(id, tenant_id, initiator_agent_id, counterparty_agent_id, state) "
                    "VALUES (:id, :tid, :agent, :agent, 'OPEN')",
                    {"id": txn_id, "tid": tid, "agent": agent_id},
                )

                events = await _create_event_chain(har, tid, agent_id, priv, txn_id, 3)

                # Verify 3-event chain is valid
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                try:
                    async with factory() as db:
                        assert await har["verify_event_chain"](txn_id, db) is True
                finally:
                    await engine.dispose()

                # Append 4th event via normal signing (chained to last event)
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                try:
                    async with factory() as db:
                        await har["create_signed_event"](
                            transaction_id=txn_id,
                            event_type="state_transition",
                            actor_agent_id=agent_id,
                            payload={"step": 4},
                            actor_private_key_enc=priv,
                            prev_event_hash=events[-1]["event_hash"],
                            tenant_id=tid,
                            db=db,
                        )
                finally:
                    await engine.dispose()

                # Verify 4-event chain is still valid
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                try:
                    async with factory() as db:
                        chain_valid = await har["verify_event_chain"](txn_id, db)
                        assert (
                            chain_valid is True
                        ), "Appending a properly chained event must keep chain valid"
                finally:
                    await engine.dispose()
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_verification_does_not_modify_data(self):
        """Verify that verify_event_chain() is read-only -- row count unchanged."""
        har = _import_har()

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            try:
                pub, priv = har["generate_agent_keypair"]()
                agent_id = await _create_test_agent(tid, uid, pub, priv)

                txn_id = str(uuid.uuid4())
                await _run_sql(
                    "INSERT INTO har_transactions "
                    "(id, tenant_id, initiator_agent_id, counterparty_agent_id, state) "
                    "VALUES (:id, :tid, :agent, :agent, 'OPEN')",
                    {"id": txn_id, "tid": tid, "agent": agent_id},
                )

                await _create_event_chain(har, tid, agent_id, priv, txn_id, 5)

                # Count rows before verification
                count_before = await _fetch_scalar(
                    "SELECT COUNT(*) FROM har_transaction_events "
                    "WHERE transaction_id = :txn_id",
                    {"txn_id": txn_id},
                )

                # Run verification
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                try:
                    async with factory() as db:
                        await har["verify_event_chain"](txn_id, db)
                finally:
                    await engine.dispose()

                # Count rows after verification
                count_after = await _fetch_scalar(
                    "SELECT COUNT(*) FROM har_transaction_events "
                    "WHERE transaction_id = :txn_id",
                    {"txn_id": txn_id},
                )

                assert count_before == count_after, (
                    f"verify_event_chain must be read-only: "
                    f"before={count_before}, after={count_after}"
                )
                assert count_before == 5
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())
