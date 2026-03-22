"""
TEST-046: A2A Transaction Flow Integration Tests

Tests the HAR A2A transaction lifecycle via the API routes and state machine
with real PostgreSQL and Redis. Complements the existing test_har_a2a_integration.py
which tests lower-level crypto and state machine functions directly.

Tier 2: Real PostgreSQL + Redis, NO MOCKING.

Architecture:
  Uses the session-scoped TestClient from conftest.py.
  DB setup/teardown via asyncio.run() with fresh async engines.
  JWT tokens for authenticated API calls.

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_a2a_transaction_flow.py -v --timeout=60
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# DB / auth helpers
# ---------------------------------------------------------------------------


def _jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        pytest.skip("JWT_SECRET_KEY not configured -- skipping integration tests")
    return secret


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured -- skipping integration tests")
    return url


def _make_admin_token(tenant_id: str, user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "enterprise",
        "email": f"admin-{user_id[:8]}@a2a-test.test",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


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


# ---------------------------------------------------------------------------
# Module-scoped fixture: test tenant + user + agents
# ---------------------------------------------------------------------------

TEST_TENANT_ID = str(uuid.uuid4())
TEST_USER_ID = str(uuid.uuid4())
TEST_AGENT_A_ID = str(uuid.uuid4())
TEST_AGENT_B_ID = str(uuid.uuid4())


@pytest.fixture(scope="module")
def test_env():
    """Provision tenant, user, and two agent_cards for the test suite."""
    tid = TEST_TENANT_ID
    uid = TEST_USER_ID
    agent_a = TEST_AGENT_A_ID
    agent_b = TEST_AGENT_B_ID

    async def _setup():
        await _run_sql(
            "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
            "VALUES (:id, :name, :slug, 'enterprise', :email, 'active')",
            {
                "id": tid,
                "name": f"A2A Flow Test {tid[:8]}",
                "slug": f"a2a-flow-{tid[:8]}",
                "email": f"admin-{tid[:8]}@a2a-test.test",
            },
        )
        await _run_sql(
            "INSERT INTO users (id, tenant_id, email, name, role, status) "
            "VALUES (:id, :tid, :email, :name, 'admin', 'active')",
            {
                "id": uid,
                "tid": tid,
                "email": f"admin-{uid[:8]}@a2a-test.test",
                "name": f"A2A Admin {uid[:8]}",
            },
        )
        # Create two agent_cards (no crypto keys needed for route-level tests)
        for aid, suffix in [(agent_a, "initiator"), (agent_b, "counterparty")]:
            await _run_sql(
                "INSERT INTO agent_cards "
                "(id, tenant_id, name, description, system_prompt, status, version, "
                "created_by, trust_score, kyb_level) "
                "VALUES (:id, :tid, :name, :desc, :prompt, 'published', 1, :uid, 50, 'none')",
                {
                    "id": aid,
                    "tid": tid,
                    "name": f"A2A Agent {suffix}",
                    "desc": f"Test {suffix} agent",
                    "prompt": f"You are a test {suffix} agent.",
                    "uid": uid,
                },
            )

    async def _teardown():
        for table in [
            "har_transaction_events",
            "har_transactions",
            "agent_cards",
            "users",
            "tenants",
        ]:
            col = "tenant_id" if table != "tenants" else "id"
            await _run_sql(f"DELETE FROM {table} WHERE {col} = :tid", {"tid": tid})

    asyncio.run(_setup())
    yield {
        "tenant_id": tid,
        "user_id": uid,
        "agent_a_id": agent_a,
        "agent_b_id": agent_b,
    }
    asyncio.run(_teardown())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestA2ATransactionFlow:
    """TEST-046: A2A transaction flow via API routes."""

    def test_create_transaction_draft_state(self, client, test_env):
        """Create HAR transaction via API, verify initial state is DRAFT."""
        tid = test_env["tenant_id"]
        uid = test_env["user_id"]
        token = _make_admin_token(tid, uid)

        resp = client.post(
            "/api/v1/har/transactions",
            json={
                "initiator_agent_id": test_env["agent_a_id"],
                "counterparty_agent_id": test_env["agent_b_id"],
                "amount": 100.0,
                "currency": "USD",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert (
            resp.status_code == 201
        ), f"Expected 201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["state"] == "DRAFT"
        assert data["initiator_agent_id"] == test_env["agent_a_id"]
        assert data["counterparty_agent_id"] == test_env["agent_b_id"]
        assert data["amount"] == 100.0

    def test_transaction_state_machine_valid_transitions(self, client, test_env):
        """DRAFT -> OPEN -> NEGOTIATING -> COMMITTED -> EXECUTING -> COMPLETED."""
        tid = test_env["tenant_id"]
        uid = test_env["user_id"]
        token = _make_admin_token(tid, uid)
        headers = {"Authorization": f"Bearer {token}"}

        # Create transaction
        resp = client.post(
            "/api/v1/har/transactions",
            json={
                "initiator_agent_id": test_env["agent_a_id"],
                "counterparty_agent_id": test_env["agent_b_id"],
                "amount": 50.0,
                "currency": "USD",
            },
            headers=headers,
        )
        assert resp.status_code == 201
        txn_id = resp.json()["id"]

        # Walk through valid transitions
        transitions = ["OPEN", "NEGOTIATING", "COMMITTED", "EXECUTING", "COMPLETED"]
        for new_state in transitions:
            resp = client.post(
                f"/api/v1/har/transactions/{txn_id}/transition",
                json={"new_state": new_state},
                headers=headers,
            )
            assert (
                resp.status_code == 200
            ), f"Transition to {new_state} failed: {resp.status_code} {resp.text}"
            assert resp.json()["state"] == new_state

        # Verify final state
        resp = client.get(
            f"/api/v1/har/transactions/{txn_id}",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "COMPLETED"

    def test_transaction_invalid_transition_rejected(self, client, test_env):
        """Try DRAFT -> COMPLETED (skipping intermediate states) -- should fail."""
        tid = test_env["tenant_id"]
        uid = test_env["user_id"]
        token = _make_admin_token(tid, uid)
        headers = {"Authorization": f"Bearer {token}"}

        # Create transaction in DRAFT
        resp = client.post(
            "/api/v1/har/transactions",
            json={
                "initiator_agent_id": test_env["agent_a_id"],
                "counterparty_agent_id": test_env["agent_b_id"],
            },
            headers=headers,
        )
        assert resp.status_code == 201
        txn_id = resp.json()["id"]

        # Try invalid transition DRAFT -> COMPLETED
        resp = client.post(
            f"/api/v1/har/transactions/{txn_id}/transition",
            json={"new_state": "COMPLETED"},
            headers=headers,
        )
        assert (
            resp.status_code == 400
        ), f"Expected 400 for invalid transition, got {resp.status_code}"

    def test_transaction_requires_human_approval_above_threshold(
        self, client, test_env
    ):
        """Create transaction with amount=6000, verify requires_human_approval=True."""
        tid = test_env["tenant_id"]
        uid = test_env["user_id"]
        token = _make_admin_token(tid, uid)

        resp = client.post(
            "/api/v1/har/transactions",
            json={
                "initiator_agent_id": test_env["agent_a_id"],
                "counterparty_agent_id": test_env["agent_b_id"],
                "amount": 6000.0,
                "currency": "USD",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert (
            data["requires_human_approval"] is True
        ), "Amount >= 5000 must set requires_human_approval=True"
        assert data["approval_deadline"] is not None

    def test_approve_transaction_transitions_to_committed(self, client, test_env):
        """Create transaction, move to NEGOTIATING, POST approve, verify COMMITTED."""
        tid = test_env["tenant_id"]
        uid = test_env["user_id"]
        token = _make_admin_token(tid, uid)
        headers = {"Authorization": f"Bearer {token}"}

        # Create and advance to NEGOTIATING
        resp = client.post(
            "/api/v1/har/transactions",
            json={
                "initiator_agent_id": test_env["agent_a_id"],
                "counterparty_agent_id": test_env["agent_b_id"],
                "amount": 7000.0,
                "currency": "USD",
            },
            headers=headers,
        )
        assert resp.status_code == 201
        txn_id = resp.json()["id"]

        # Transition DRAFT -> OPEN -> NEGOTIATING
        for state in ["OPEN", "NEGOTIATING"]:
            resp = client.post(
                f"/api/v1/har/transactions/{txn_id}/transition",
                json={"new_state": state},
                headers=headers,
            )
            assert resp.status_code == 200

        # Approve
        resp = client.post(
            f"/api/v1/har/transactions/{txn_id}/approve",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "COMMITTED"
        assert data["human_approved_by"] == uid

    def test_concurrent_transactions_isolated(self, client, test_env):
        """Create 2 transactions simultaneously -- they should not interfere."""
        tid = test_env["tenant_id"]
        uid = test_env["user_id"]
        token = _make_admin_token(tid, uid)
        headers = {"Authorization": f"Bearer {token}"}

        # Create two transactions
        txn_ids = []
        for amount in [100.0, 200.0]:
            resp = client.post(
                "/api/v1/har/transactions",
                json={
                    "initiator_agent_id": test_env["agent_a_id"],
                    "counterparty_agent_id": test_env["agent_b_id"],
                    "amount": amount,
                    "currency": "USD",
                },
                headers=headers,
            )
            assert resp.status_code == 201
            txn_ids.append(resp.json()["id"])

        assert txn_ids[0] != txn_ids[1], "Transaction IDs must be unique"

        # Advance transaction 1 to OPEN, leave transaction 2 in DRAFT
        resp = client.post(
            f"/api/v1/har/transactions/{txn_ids[0]}/transition",
            json={"new_state": "OPEN"},
            headers=headers,
        )
        assert resp.status_code == 200

        # Verify states are independent
        resp1 = client.get(
            f"/api/v1/har/transactions/{txn_ids[0]}",
            headers=headers,
        )
        resp2 = client.get(
            f"/api/v1/har/transactions/{txn_ids[1]}",
            headers=headers,
        )
        assert resp1.json()["state"] == "OPEN"
        assert resp2.json()["state"] == "DRAFT"
        assert resp1.json()["amount"] == 100.0
        assert resp2.json()["amount"] == 200.0
