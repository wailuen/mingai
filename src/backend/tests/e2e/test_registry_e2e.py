"""
DEF-017: Registry E2E Tests

End-to-end tests for the public agent registry workflow:
1. Agent registration (POST /registry/agents) returns 201
2. Agent search/browse (GET /registry/agents) returns paginated results
3. Trust score is numeric in [0, 100]
4. Health status check via GET /registry/agents/{id} returns valid status
5. HAR transaction initiation (POST /registry/transactions)
6. Multi-tenant isolation: agents registered by tenant A not modifiable by tenant B

Tier 3: E2E, NO mocking, <10s timeout, requires Docker infrastructure.

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/e2e/test_registry_e2e.py -v --timeout=10
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
# Infrastructure helpers
# ---------------------------------------------------------------------------


def _jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        pytest.skip("JWT_SECRET_KEY not configured -- skipping E2E tests")
    return secret


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured -- skipping E2E tests")
    return url


def _make_engine():
    return create_async_engine(_db_url(), echo=False)


async def _run_sql(sql: str, params: dict | None = None):
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            await session.commit()
            return result
    finally:
        await engine.dispose()


async def _run_sql_fetch(sql: str, params: dict | None = None) -> list:
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            return result.fetchall()
    finally:
        await engine.dispose()


def _make_token(
    user_id: str,
    tenant_id: str,
    roles: list[str],
    scope: str = "tenant",
    plan: str = "professional",
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": scope,
        "plan": plan,
        "email": f"e2e-{user_id[:8]}@registry-e2e.test",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


async def _create_tenant(name_prefix: str = "Registry E2E") -> str:
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"{name_prefix} {tid[:8]}",
            "slug": f"reg-e2e-{tid[:8]}",
            "email": f"admin@reg-e2e-{tid[:8]}.test",
        },
    )
    return tid


async def _create_user(tid: str, role: str = "admin") -> str:
    uid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO users (id, tenant_id, email, name, role, status) "
        "VALUES (:id, :tid, :email, :name, :role, 'active')",
        {
            "id": uid,
            "tid": tid,
            "email": f"{role}-{uid[:8]}@reg-e2e.test",
            "name": f"E2E {role.title()} {uid[:8]}",
            "role": role,
        },
    )
    return uid


async def _create_agent(
    tid: str, uid: str, name: str = "E2E Agent", agent_status: str = "published"
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
            "desc": f"E2E test agent: {name}",
            "prompt": "You are a test agent for E2E registry tests.",
            "status": agent_status,
            "uid": uid,
        },
    )
    return agent_id


async def _cleanup_tenant(tid: str):
    """Clean up all tenant data in dependency order.

    har_transactions has FKs to agent_cards for both initiator and counterparty,
    which may span tenants. Delete transactions where either the initiator or
    counterparty agent belongs to this tenant before deleting agent_cards.
    """
    # Delete transaction events referencing transactions from this tenant
    await _run_sql(
        "DELETE FROM har_transaction_events WHERE transaction_id IN "
        "(SELECT id FROM har_transactions WHERE tenant_id = :tid)",
        {"tid": tid},
    )
    # Delete transactions owned by this tenant
    await _run_sql(
        "DELETE FROM har_transactions WHERE tenant_id = :tid", {"tid": tid}
    )
    # Delete transactions where counterparty agent belongs to this tenant
    await _run_sql(
        "DELETE FROM har_transaction_events WHERE transaction_id IN "
        "(SELECT t.id FROM har_transactions t "
        "JOIN agent_cards a ON t.counterparty_agent_id = a.id "
        "WHERE a.tenant_id = :tid)",
        {"tid": tid},
    )
    await _run_sql(
        "DELETE FROM har_transactions WHERE counterparty_agent_id IN "
        "(SELECT id FROM agent_cards WHERE tenant_id = :tid)",
        {"tid": tid},
    )
    await _run_sql(
        "DELETE FROM audit_log WHERE tenant_id = :tid", {"tid": tid}
    )
    await _run_sql(
        "DELETE FROM agent_cards WHERE tenant_id = :tid", {"tid": tid}
    )
    await _run_sql(
        "DELETE FROM users WHERE tenant_id = :tid", {"tid": tid}
    )
    await _run_sql(
        "DELETE FROM tenants WHERE id = :tid", {"tid": tid}
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tenant_a():
    """Provision tenant A for E2E registry tests."""
    async def _setup():
        tid = await _create_tenant("Registry E2E A")
        uid = await _create_user(tid, "admin")
        return tid, uid
    tid, uid = asyncio.run(_setup())
    yield {"tid": tid, "uid": uid}
    asyncio.run(_cleanup_tenant(tid))


@pytest.fixture(scope="module")
def tenant_b():
    """Provision tenant B for E2E multi-tenant isolation tests."""
    async def _setup():
        tid = await _create_tenant("Registry E2E B")
        uid = await _create_user(tid, "admin")
        return tid, uid
    tid, uid = asyncio.run(_setup())
    yield {"tid": tid, "uid": uid}
    asyncio.run(_cleanup_tenant(tid))


@pytest.fixture(scope="module")
def admin_a_headers(tenant_a):
    token = _make_token(tenant_a["uid"], tenant_a["tid"], roles=["tenant_admin"])
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def admin_b_headers(tenant_b):
    token = _make_token(tenant_b["uid"], tenant_b["tid"], roles=["tenant_admin"])
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def user_a_headers(tenant_a):
    uid = str(uuid.uuid4())
    token = _make_token(uid, tenant_a["tid"], roles=["end_user"])
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# E2E Test: Agent Registration
# ---------------------------------------------------------------------------


class TestAgentRegistration:
    """DEF-017: Agent registration via POST /registry/agents returns 201."""

    def test_register_agent_returns_201(self, client, tenant_a, admin_a_headers):
        """Register a published agent to the public registry."""
        agent_id = asyncio.run(
            _create_agent(tenant_a["tid"], tenant_a["uid"], "Registration E2E Bot")
        )

        resp = client.post(
            "/api/v1/registry/agents",
            json={
                "agent_id": agent_id,
                "a2a_endpoint": "https://example.com/a2a/reg-e2e-bot",
                "transaction_types": ["RFQ", "CAPABILITY_QUERY"],
                "industries": ["technology"],
                "languages": ["en"],
            },
            headers=admin_a_headers,
        )
        assert resp.status_code == 201, f"Register failed: {resp.text}"
        data = resp.json()
        assert data["agent_id"] == agent_id
        assert data["name"] == "Registration E2E Bot"
        assert "registered_at" in data

    def test_register_nonexistent_agent_returns_404(self, client, admin_a_headers):
        """Registering a non-existent agent_id returns 404."""
        fake_id = str(uuid.uuid4())
        resp = client.post(
            "/api/v1/registry/agents",
            json={
                "agent_id": fake_id,
                "a2a_endpoint": "https://example.com/a2a/nonexistent",
            },
            headers=admin_a_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# E2E Test: Agent Search/Browse
# ---------------------------------------------------------------------------


class TestAgentSearchBrowse:
    """DEF-017: GET /registry/agents returns paginated results."""

    def test_list_agents_returns_paginated_results(self, client, tenant_a, admin_a_headers):
        """Register an agent then verify it appears in public search."""
        agent_id = asyncio.run(
            _create_agent(tenant_a["tid"], tenant_a["uid"], "Browse E2E Bot")
        )

        # Register
        reg_resp = client.post(
            "/api/v1/registry/agents",
            json={
                "agent_id": agent_id,
                "a2a_endpoint": "https://example.com/a2a/browse-e2e-bot",
                "industries": ["healthcare"],
            },
            headers=admin_a_headers,
        )
        assert reg_resp.status_code == 201

        # Search by name
        list_resp = client.get("/api/v1/registry/agents?query=Browse+E2E+Bot")
        assert list_resp.status_code == 200, f"List failed: {list_resp.text}"
        data = list_resp.json()

        # Verify pagination structure
        assert "items" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert isinstance(data["items"], list)
        assert data["total"] >= 1

        # Verify our agent is in the results
        found_ids = [item["agent_id"] for item in data["items"]]
        assert agent_id in found_ids, (
            f"Agent {agent_id} not found in search results. "
            f"Found: {found_ids}"
        )


# ---------------------------------------------------------------------------
# E2E Test: Trust Score Validation
# ---------------------------------------------------------------------------


class TestTrustScoreValidation:
    """DEF-017: Trust score is numeric in [0, 100]."""

    def test_trust_score_in_valid_range(self, client, tenant_a, admin_a_headers):
        """Agent detail returns a trust_score that is numeric and in [0, 100]."""
        agent_id = asyncio.run(
            _create_agent(tenant_a["tid"], tenant_a["uid"], "Trust Score E2E Bot")
        )

        # Register
        client.post(
            "/api/v1/registry/agents",
            json={
                "agent_id": agent_id,
                "a2a_endpoint": "https://example.com/a2a/trust-e2e-bot",
            },
            headers=admin_a_headers,
        )

        # Get agent detail (public endpoint — no auth required)
        detail_resp = client.get(f"/api/v1/registry/agents/{agent_id}")
        assert detail_resp.status_code == 200, f"Detail failed: {detail_resp.text}"
        data = detail_resp.json()

        assert "trust_score" in data, "Agent detail must include trust_score"
        trust_score = data["trust_score"]
        assert isinstance(trust_score, (int, float)), (
            f"trust_score must be numeric, got {type(trust_score).__name__}"
        )
        assert 0 <= trust_score <= 100, (
            f"trust_score must be in [0, 100], got {trust_score}"
        )

    def test_trust_score_in_list_results(self, client, tenant_a, admin_a_headers):
        """Trust score is present and valid in list/search results too."""
        agent_id = asyncio.run(
            _create_agent(tenant_a["tid"], tenant_a["uid"], "Trust List E2E Bot")
        )
        client.post(
            "/api/v1/registry/agents",
            json={
                "agent_id": agent_id,
                "a2a_endpoint": "https://example.com/a2a/trust-list-e2e-bot",
            },
            headers=admin_a_headers,
        )

        list_resp = client.get("/api/v1/registry/agents?query=Trust+List+E2E+Bot")
        assert list_resp.status_code == 200
        items = list_resp.json()["items"]
        our_agent = next((a for a in items if a["agent_id"] == agent_id), None)
        assert our_agent is not None
        assert 0 <= our_agent["trust_score"] <= 100


# ---------------------------------------------------------------------------
# E2E Test: Health Status
# ---------------------------------------------------------------------------


class TestHealthStatus:
    """
    DEF-017: Health status check via GET /registry/agents/{id}.

    Note: The API does not expose a PATCH health endpoint. Health status is
    read from Redis by the GET detail endpoint. A newly registered agent
    with no Redis health key defaults to 'healthy'.
    """

    def test_agent_detail_includes_health_status(self, client, tenant_a, admin_a_headers):
        """GET /registry/agents/{id} returns a health_status field."""
        agent_id = asyncio.run(
            _create_agent(tenant_a["tid"], tenant_a["uid"], "Health E2E Bot")
        )

        client.post(
            "/api/v1/registry/agents",
            json={
                "agent_id": agent_id,
                "a2a_endpoint": "https://example.com/a2a/health-e2e-bot",
                "health_check_url": "https://example.com/health/health-e2e-bot",
            },
            headers=admin_a_headers,
        )

        detail_resp = client.get(f"/api/v1/registry/agents/{agent_id}")
        assert detail_resp.status_code == 200
        data = detail_resp.json()

        assert "health_status" in data, "Agent detail must include health_status"
        assert isinstance(data["health_status"], str), "health_status must be a string"
        # Default is 'healthy' for newly registered agents
        assert data["health_status"] in ("healthy", "unhealthy", "unknown"), (
            f"Unexpected health_status: {data['health_status']}"
        )


# ---------------------------------------------------------------------------
# E2E Test: Transaction Initiation
# ---------------------------------------------------------------------------


class TestTransactionInitiation:
    """DEF-017: POST /registry/transactions initiates a HAR transaction."""

    def test_initiate_capability_query_transaction(
        self, client, tenant_a, tenant_b, admin_a_headers, admin_b_headers, user_a_headers
    ):
        """
        Tenant A initiates a CAPABILITY_QUERY transaction to tenant B's agent.
        Verifies 201 response with txn_id and OPEN status.
        """
        # Create agents for both tenants
        agent_a_id = asyncio.run(
            _create_agent(tenant_a["tid"], tenant_a["uid"], "Initiator E2E Bot")
        )
        agent_b_id = asyncio.run(
            _create_agent(tenant_b["tid"], tenant_b["uid"], "Counterparty E2E Bot")
        )

        # Register counterparty agent to public registry
        client.post(
            "/api/v1/registry/agents",
            json={
                "agent_id": agent_b_id,
                "a2a_endpoint": "https://example.com/a2a/counterparty-e2e",
            },
            headers=admin_b_headers,
        )

        # Initiate transaction as tenant A user
        init_resp = client.post(
            "/api/v1/registry/transactions",
            json={
                "from_agent_id": agent_a_id,
                "to_agent_id": agent_b_id,
                "message_type": "CAPABILITY_QUERY",
                "payload": {"query": "What capabilities do you support?"},
            },
            headers=user_a_headers,
        )
        assert init_resp.status_code == 201, f"Initiate failed: {init_resp.text}"
        data = init_resp.json()

        assert "txn_id" in data, "Response must include txn_id"
        assert data["status"] == "OPEN", f"Expected OPEN status, got {data['status']}"

        # Verify transaction can be fetched
        get_resp = client.get(
            f"/api/v1/registry/transactions/{data['txn_id']}",
            headers=user_a_headers,
        )
        assert get_resp.status_code == 200
        txn_data = get_resp.json()
        assert txn_data["txn_id"] == data["txn_id"]
        assert txn_data["status"] == "OPEN"
        assert "events" in txn_data

    def test_invalid_message_type_rejected(self, client, user_a_headers):
        """Transaction with invalid message_type is rejected with 422."""
        resp = client.post(
            "/api/v1/registry/transactions",
            json={
                "from_agent_id": str(uuid.uuid4()),
                "to_agent_id": str(uuid.uuid4()),
                "message_type": "INVALID_TYPE",
                "payload": {},
            },
            headers=user_a_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# E2E Test: Multi-Tenant Isolation
# ---------------------------------------------------------------------------


class TestRegistryMultiTenantIsolation:
    """
    DEF-017: Agents registered by tenant A are not modifiable by tenant B.
    All operations use real DB, no mocking.
    """

    def test_tenant_b_cannot_modify_tenant_a_agent(
        self, client, tenant_a, tenant_b, admin_a_headers, admin_b_headers
    ):
        """
        Tenant A registers an agent. Tenant B cannot update or deregister it.
        """
        agent_id = asyncio.run(
            _create_agent(tenant_a["tid"], tenant_a["uid"], "Isolation E2E Bot")
        )

        # Tenant A registers
        reg_resp = client.post(
            "/api/v1/registry/agents",
            json={
                "agent_id": agent_id,
                "a2a_endpoint": "https://example.com/a2a/isolation-e2e",
                "industries": ["finance"],
            },
            headers=admin_a_headers,
        )
        assert reg_resp.status_code == 201

        # Tenant B cannot UPDATE tenant A's agent (403)
        update_resp = client.put(
            f"/api/v1/registry/agents/{agent_id}",
            json={"description": "Hijacked by tenant B"},
            headers=admin_b_headers,
        )
        assert update_resp.status_code == 403, (
            f"Tenant B should get 403 on update, got {update_resp.status_code}: {update_resp.text}"
        )

        # Tenant B cannot DELETE (deregister) tenant A's agent (403)
        del_resp = client.delete(
            f"/api/v1/registry/agents/{agent_id}",
            headers=admin_b_headers,
        )
        assert del_resp.status_code == 403, (
            f"Tenant B should get 403 on deregister, got {del_resp.status_code}: {del_resp.text}"
        )

        # Verify agent is still intact via public GET
        detail_resp = client.get(f"/api/v1/registry/agents/{agent_id}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["name"] == "Isolation E2E Bot"

    def test_tenant_b_can_read_but_not_own_tenant_a_agent(
        self, client, tenant_a, tenant_b, admin_a_headers, admin_b_headers
    ):
        """
        Public registry is readable by anyone, but ownership operations
        (update, deregister) require tenant match.
        """
        agent_id = asyncio.run(
            _create_agent(tenant_a["tid"], tenant_a["uid"], "ReadOnly E2E Bot")
        )

        # Register as tenant A
        client.post(
            "/api/v1/registry/agents",
            json={
                "agent_id": agent_id,
                "a2a_endpoint": "https://example.com/a2a/readonly-e2e",
            },
            headers=admin_a_headers,
        )

        # Tenant B CAN read (public endpoint, no auth required)
        detail_resp = client.get(f"/api/v1/registry/agents/{agent_id}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["agent_id"] == agent_id

        # Tenant B CAN search and find it (public endpoint)
        list_resp = client.get("/api/v1/registry/agents?query=ReadOnly+E2E+Bot")
        assert list_resp.status_code == 200
        found_ids = [item["agent_id"] for item in list_resp.json()["items"]]
        assert agent_id in found_ids

        # But tenant B CANNOT modify
        update_resp = client.put(
            f"/api/v1/registry/agents/{agent_id}",
            json={"description": "Attempted hijack"},
            headers=admin_b_headers,
        )
        assert update_resp.status_code == 403
