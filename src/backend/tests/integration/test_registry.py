"""
Public Agent Registry Integration Tests (API-089 to API-098).

Tests:
- API-089/090: Register agent then list/find it in the public registry
- API-089/093: Register then deregister (soft-delete)
- API-094/095: Initiate transaction and get its status
- API-094/096: Approve transaction workflow
- API-098: Registry analytics for tenant's agents

Architecture:
  - Real PostgreSQL (no mocking of DB helpers)
  - No Redis or LLM calls in this suite
  - Isolated test tenants — cleaned up after each test

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_registry.py -v --timeout=60
"""
import asyncio
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
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"Registry Test {tid[:8]}",
            "slug": f"registry-test-{tid[:8]}",
            "email": f"admin-{tid[:8]}@registry-int.test",
        },
    )
    return tid


async def _create_test_user(tid: str, role: str = "admin") -> str:
    uid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO users (id, tenant_id, email, name, role, status) "
        "VALUES (:id, :tid, :email, :name, :role, 'active')",
        {
            "id": uid,
            "tid": tid,
            "email": f"{role}-{uid[:8]}@registry-int.test",
            "name": f"Test {role.title()} {uid[:8]}",
            "role": role,
        },
    )
    return uid


async def _create_test_agent(
    tid: str, uid: str, name: str = "Test Agent", agent_status: str = "published"
) -> str:
    agent_id = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO agent_cards "
        "(id, tenant_id, name, description, system_prompt, status, version, source, created_by) "
        "VALUES (:id, :tid, :name, :desc, :prompt, :status, 1, 'custom', :uid)",
        {
            "id": agent_id,
            "tid": tid,
            "name": name,
            "desc": "Test agent for registry integration tests",
            "prompt": "You are a test agent.",
            "status": agent_status,
            "uid": uid,
        },
    )
    return agent_id


async def _cleanup_tenant(tid: str):
    """Clean up all tenant data in dependency order."""
    tables_and_cols = [
        ("har_transaction_events", "tenant_id"),
        ("har_transactions", "tenant_id"),
        ("audit_log", "tenant_id"),
        ("agent_cards", "tenant_id"),
        ("users", "tenant_id"),
        ("tenants", "id"),
    ]
    for table, col in tables_and_cols:
        await _run_sql(f"DELETE FROM {table} WHERE {col} = :tid", {"tid": tid})


# ---------------------------------------------------------------------------
# JWT token helper
# ---------------------------------------------------------------------------


def _make_admin_token(tenant_id: str, user_id: str) -> str:
    from datetime import timedelta

    from jose import jwt

    secret = os.environ.get("JWT_SECRET_KEY", "a" * 64)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": f"admin-{user_id[:8]}@test.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _make_user_token(tenant_id: str, user_id: str) -> str:
    from datetime import timedelta

    from jose import jwt

    secret = os.environ.get("JWT_SECRET_KEY", "a" * 64)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": ["end_user"],
        "scope": "tenant",
        "plan": "professional",
        "email": f"user-{user_id[:8]}@test.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRegisterAndListAgent:
    """API-089 + API-090: Register agent then find it in the public registry."""

    def test_register_and_list_agent(self, client):
        """Register an agent, then verify it appears in the public list."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            agent_id = await _create_test_agent(tid, uid, "Finance Bot", "published")
            try:
                token = _make_admin_token(tid, uid)

                # Register to public registry
                resp = client.post(
                    "/api/v1/registry/agents",
                    json={
                        "agent_id": agent_id,
                        "a2a_endpoint": "https://finance-bot.example.com/a2a",
                        "transaction_types": ["RFQ"],
                        "industries": ["finance"],
                        "languages": ["en"],
                        "health_check_url": "https://finance-bot.example.com/health",
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert resp.status_code == 201, f"Register failed: {resp.text}"
                data = resp.json()
                assert data["agent_id"] == agent_id
                assert data["name"] == "Finance Bot"
                assert "registered_at" in data

                # Should appear in public list
                list_resp = client.get("/api/v1/registry/agents?query=Finance+Bot")
                assert list_resp.status_code == 200, f"List failed: {list_resp.text}"
                list_data = list_resp.json()
                assert list_data["total"] >= 1
                found_ids = [item["agent_id"] for item in list_data["items"]]
                assert agent_id in found_ids

            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())


class TestRegisterAndDeregisterAgent:
    """API-089 + API-093: Register agent then deregister it."""

    def test_register_and_deregister(self, client):
        """Register then deregister — agent should disappear from public list."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            agent_id = await _create_test_agent(tid, uid, "Support Bot", "published")
            try:
                token = _make_admin_token(tid, uid)

                # Register
                reg_resp = client.post(
                    "/api/v1/registry/agents",
                    json={
                        "agent_id": agent_id,
                        "a2a_endpoint": "https://support-bot.example.com/a2a",
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert reg_resp.status_code == 201, f"Register failed: {reg_resp.text}"

                # Verify detail is accessible
                detail_resp = client.get(f"/api/v1/registry/agents/{agent_id}")
                assert detail_resp.status_code == 200

                # Deregister
                dereg_resp = client.delete(
                    f"/api/v1/registry/agents/{agent_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert (
                    dereg_resp.status_code == 204
                ), f"Deregister failed: {dereg_resp.text}"

                # Agent should no longer be accessible via public detail
                gone_resp = client.get(f"/api/v1/registry/agents/{agent_id}")
                assert gone_resp.status_code == 404

            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())


class TestInitiateAndGetTransaction:
    """API-094 + API-095: Initiate transaction and read its status."""

    def test_initiate_and_get_transaction(self, client):
        """Initiate a CAPABILITY_QUERY transaction and verify it can be fetched."""

        async def _run():
            tid_a = await _create_test_tenant()
            tid_b = await _create_test_tenant()
            uid_a = await _create_test_user(tid_a)
            uid_b = await _create_test_user(tid_b)
            agent_a_id = await _create_test_agent(
                tid_a, uid_a, "Initiator Agent", "published"
            )
            agent_b_id = await _create_test_agent(
                tid_b, uid_b, "Counterparty Agent", "published"
            )

            # Register agent_b to public registry
            token_b = _make_admin_token(tid_b, uid_b)
            client.post(
                "/api/v1/registry/agents",
                json={
                    "agent_id": agent_b_id,
                    "a2a_endpoint": "https://counterparty.example.com/a2a",
                },
                headers={"Authorization": f"Bearer {token_b}"},
            )

            try:
                # Initiate as end_user of TENANT_A
                user_token_a = _make_user_token(tid_a, uid_a)
                init_resp = client.post(
                    "/api/v1/registry/transactions",
                    json={
                        "from_agent_id": agent_a_id,
                        "to_agent_id": agent_b_id,
                        "message_type": "CAPABILITY_QUERY",
                        "payload": {"query": "What capabilities do you support?"},
                    },
                    headers={"Authorization": f"Bearer {user_token_a}"},
                )
                assert (
                    init_resp.status_code == 201
                ), f"Initiate failed: {init_resp.text}"
                init_data = init_resp.json()
                assert "txn_id" in init_data
                assert init_data["status"] == "OPEN"
                txn_id = init_data["txn_id"]

                # Fetch transaction status as participant
                get_resp = client.get(
                    f"/api/v1/registry/transactions/{txn_id}",
                    headers={"Authorization": f"Bearer {user_token_a}"},
                )
                assert get_resp.status_code == 200, f"Get txn failed: {get_resp.text}"
                get_data = get_resp.json()
                assert get_data["txn_id"] == txn_id
                assert get_data["status"] == "OPEN"
                assert "events" in get_data
                assert "approval_required" in get_data

            finally:
                await _cleanup_tenant(tid_a)
                await _cleanup_tenant(tid_b)

        asyncio.run(_run())


class TestApproveTransactionWorkflow:
    """API-094 + API-096: Initiate RFQ then approve it."""

    def test_approve_transaction_workflow(self, client):
        """RFQ triggers approval required; tenant admin can approve → COMMITTED."""

        async def _run():
            tid_a = await _create_test_tenant()
            tid_b = await _create_test_tenant()
            uid_a = await _create_test_user(tid_a)
            uid_b = await _create_test_user(tid_b)
            agent_a_id = await _create_test_agent(
                tid_a, uid_a, "Buyer Agent", "published"
            )
            agent_b_id = await _create_test_agent(
                tid_b, uid_b, "Seller Agent", "published"
            )

            # Register seller agent to public registry
            token_b = _make_admin_token(tid_b, uid_b)
            client.post(
                "/api/v1/registry/agents",
                json={
                    "agent_id": agent_b_id,
                    "a2a_endpoint": "https://seller.example.com/a2a",
                    "transaction_types": ["RFQ"],
                },
                headers={"Authorization": f"Bearer {token_b}"},
            )

            try:
                # Initiate RFQ as TENANT_A user — will require approval
                token_a = _make_admin_token(tid_a, uid_a)
                init_resp = client.post(
                    "/api/v1/registry/transactions",
                    json={
                        "from_agent_id": agent_a_id,
                        "to_agent_id": agent_b_id,
                        "message_type": "RFQ",
                        "payload": {"items": ["widget-001"], "quantity": 100},
                    },
                    headers={"Authorization": f"Bearer {token_a}"},
                )
                assert (
                    init_resp.status_code == 201
                ), f"Initiate failed: {init_resp.text}"
                txn_id = init_resp.json()["txn_id"]
                assert init_resp.json().get("status") == "OPEN"

                # Approve as TENANT_A admin
                approve_resp = client.post(
                    f"/api/v1/registry/transactions/{txn_id}/approve",
                    headers={"Authorization": f"Bearer {token_a}"},
                )
                assert (
                    approve_resp.status_code == 200
                ), f"Approve failed: {approve_resp.text}"
                approve_data = approve_resp.json()
                assert approve_data["status"] == "COMMITTED"
                assert approve_data["txn_id"] == txn_id
                assert "approved_at" in approve_data

            finally:
                await _cleanup_tenant(tid_a)
                await _cleanup_tenant(tid_b)

        asyncio.run(_run())


class TestRegistryAnalytics:
    """API-098: Registry discovery analytics."""

    def test_registry_analytics(self, client):
        """Tenant admin sees analytics for their own registered agents."""

        async def _run():
            tid = await _create_test_tenant()
            uid = await _create_test_user(tid)
            agent_id = await _create_test_agent(
                tid, uid, "Analytics Agent", "published"
            )
            try:
                token = _make_admin_token(tid, uid)

                # Register agent first
                client.post(
                    "/api/v1/registry/agents",
                    json={
                        "agent_id": agent_id,
                        "a2a_endpoint": "https://analytics-agent.example.com/a2a",
                        "industries": ["analytics"],
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )

                # Fetch analytics
                analytics_resp = client.get(
                    "/api/v1/registry/analytics?period=30d",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert (
                    analytics_resp.status_code == 200
                ), f"Analytics failed: {analytics_resp.text}"
                analytics_data = analytics_resp.json()
                assert "agents" in analytics_data

                # Our agent should appear in analytics
                agent_ids = [a["agent_id"] for a in analytics_data["agents"]]
                assert agent_id in agent_ids

                # Verify analytics structure
                our_agent = next(
                    a for a in analytics_data["agents"] if a["agent_id"] == agent_id
                )
                assert "transaction_count" in our_agent
                assert "trust_score" in our_agent
                assert "trust_score_trend" in our_agent
                assert our_agent["trust_score_trend"] in ("up", "down", "stable")

            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())
