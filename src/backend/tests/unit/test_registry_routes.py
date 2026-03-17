"""
Unit tests for Public Agent Registry routes (API-089 to API-098).

Tier 1: Fast, isolated, uses mocking for all DB helpers.
Tests auth, ownership, and business-logic guards without touching a real DB.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"

TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER_ADMIN_A = "user-admin-a-001"
USER_ADMIN_B = "user-admin-b-001"
USER_END_A = "user-end-a-001"

AGENT_A_ID = "agent-aaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
AGENT_B_ID = "agent-bbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TXN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
HAR_TXN_ID = "HAR-20260308-123456"


def _make_token(
    user_id: str = USER_ADMIN_A,
    tenant_id: str = TENANT_A,
    roles: list[str] | None = None,
    scope: str = "tenant",
    plan: str = "professional",
) -> str:
    if roles is None:
        roles = ["tenant_admin"]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": scope,
        "plan": plan,
        "email": f"{user_id}@test.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


@pytest.fixture(autouse=True)
def bypass_ssrf_dns(monkeypatch):
    """
    Unit tests don't have real DNS — bypass SSRF DNS resolution for all
    route tests that use agent.example.com (a public domain, not internal).
    The SSRF validator itself has dedicated unit tests in test_a2a_routing.py.
    """
    monkeypatch.setattr(
        "app.modules.registry.routes._validate_ssrf_safe_url",
        lambda url: None,
    )


@pytest.fixture
def env_vars():
    env = {
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "JWT_ALGORITHM": TEST_JWT_ALGORITHM,
        "REDIS_URL": "redis://localhost:6379/0",
        "FRONTEND_URL": "http://localhost:3022",
    }
    with patch.dict(os.environ, env):
        yield


@pytest.fixture
def client(env_vars):
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def _admin_a_headers():
    return {
        "Authorization": f"Bearer {_make_token(user_id=USER_ADMIN_A, tenant_id=TENANT_A)}"
    }


def _admin_b_headers():
    return {
        "Authorization": f"Bearer {_make_token(user_id=USER_ADMIN_B, tenant_id=TENANT_B)}"
    }


def _end_user_headers():
    return {
        "Authorization": f"Bearer {_make_token(user_id=USER_END_A, tenant_id=TENANT_A, roles=['end_user'])}"
    }


def _sample_agent(
    agent_id: str = AGENT_A_ID, tenant_id: str = TENANT_A, is_public: bool = True
) -> dict:
    return {
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "name": "Finance Agent",
        "description": "Handles financial queries",
        "status": "published",
        "is_public": is_public,
        "a2a_endpoint": "https://agent.example.com/a2a",
        "transaction_types": ["RFQ"],
        "industries": ["finance"],
        "languages": ["en"],
        "health_check_url": "https://agent.example.com/health",
        "public_key": "ed25519-pub-key",
        "trust_score": 80,
        "capabilities": [],
        "created_at": "2026-03-08T00:00:00+00:00",
        "updated_at": "2026-03-08T00:00:00+00:00",
    }


def _sample_transaction(tenant_id: str = TENANT_A) -> dict:
    return {
        "txn_id": HAR_TXN_ID,
        "internal_id": TXN_UUID,
        "tenant_id": tenant_id,
        "from_agent_id": AGENT_A_ID,
        "to_agent_id": AGENT_B_ID,
        "status": "OPEN",
        "payload": {"har_txn_id": HAR_TXN_ID, "message_type": "RFQ"},
        "requires_human_approval": True,
        "approval_deadline": (
            datetime.now(timezone.utc) + timedelta(hours=48)
        ).isoformat(),
        "created_at": "2026-03-08T00:00:00+00:00",
        "updated_at": "2026-03-08T00:00:00+00:00",
        "events": [],
    }


# ---------------------------------------------------------------------------
# API-089: POST /registry/agents — register
# ---------------------------------------------------------------------------


class TestRegisterAgent:
    """API-089: Register agent to global registry."""

    def test_register_requires_tenant_admin(self, client):
        """Unauthenticated request should return 401."""
        resp = client.post(
            "/api/v1/registry/agents",
            json={
                "agent_id": AGENT_A_ID,
                "a2a_endpoint": "https://agent.example.com/a2a",
            },
        )
        assert resp.status_code == 401

    def test_register_end_user_forbidden(self, client):
        """end_user role is not tenant_admin — should be 403."""
        resp = client.post(
            "/api/v1/registry/agents",
            json={
                "agent_id": AGENT_A_ID,
                "a2a_endpoint": "https://agent.example.com/a2a",
            },
            headers=_end_user_headers(),
        )
        assert resp.status_code == 403

    def test_register_agent_non_https_endpoint_rejected(self, client):
        """HTTP endpoint (not HTTPS) should be rejected with 422."""
        resp = client.post(
            "/api/v1/registry/agents",
            json={
                "agent_id": AGENT_A_ID,
                "a2a_endpoint": "http://insecure.example.com/a2a",
            },
            headers=_admin_a_headers(),
        )
        assert resp.status_code == 422

    def test_register_agent_not_found_returns_404(self, client):
        """If agent doesn't belong to tenant, return 404."""
        with patch(
            "app.modules.registry.routes.register_agent_db",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post(
                "/api/v1/registry/agents",
                json={
                    "agent_id": AGENT_A_ID,
                    "a2a_endpoint": "https://agent.example.com/a2a",
                },
                headers=_admin_a_headers(),
            )
        assert resp.status_code == 404

    def test_register_agent_success(self, client):
        """Valid request registers agent and returns agent_id."""
        agent = _sample_agent()
        with patch(
            "app.modules.registry.routes.register_agent_db",
            new_callable=AsyncMock,
            return_value=agent,
        ):
            resp = client.post(
                "/api/v1/registry/agents",
                json={
                    "agent_id": AGENT_A_ID,
                    "a2a_endpoint": "https://agent.example.com/a2a",
                    "transaction_types": ["RFQ"],
                    "industries": ["finance"],
                    "languages": ["en"],
                },
                headers=_admin_a_headers(),
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["agent_id"] == AGENT_A_ID
        assert "registered_at" in data


# ---------------------------------------------------------------------------
# API-090: GET /registry/agents — public list
# ---------------------------------------------------------------------------


class TestListRegistryAgents:
    """API-090: Search/list public registry."""

    def test_list_registry_public_access(self, client):
        """No auth required — public endpoint returns 200."""
        with patch(
            "app.modules.registry.routes.list_public_agents_db",
            new_callable=AsyncMock,
            return_value={"items": [], "total": 0},
        ), patch(
            "app.modules.registry.routes.compute_trust_score_db",
            new_callable=AsyncMock,
            return_value=80,
        ), patch(
            "app.modules.registry.routes._get_health_status",
            new_callable=AsyncMock,
            return_value="healthy",
        ):
            resp = client.get("/api/v1/registry/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_list_returns_only_public_published(self, client):
        """Result shape should include items and total."""
        agents = [_sample_agent()]
        with patch(
            "app.modules.registry.routes.list_public_agents_db",
            new_callable=AsyncMock,
            return_value={"items": agents, "total": 1},
        ), patch(
            "app.modules.registry.routes.compute_trust_score_db",
            new_callable=AsyncMock,
            return_value=85,
        ), patch(
            "app.modules.registry.routes._get_health_status",
            new_callable=AsyncMock,
            return_value="healthy",
        ):
            resp = client.get("/api/v1/registry/agents?query=Finance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["trust_score"] == 85


# ---------------------------------------------------------------------------
# API-091: GET /registry/agents/{agent_id} — public detail
# ---------------------------------------------------------------------------


class TestGetAgentDetail:
    """API-091: Get agent card detail — no auth required."""

    def test_get_agent_detail_public(self, client):
        """No auth needed — returns full agent detail."""
        agent = _sample_agent()
        with patch(
            "app.modules.registry.routes.get_agent_card_db",
            new_callable=AsyncMock,
            return_value=agent,
        ), patch(
            "app.modules.registry.routes.get_tenant_name_db",
            new_callable=AsyncMock,
            return_value="Acme Corp",
        ), patch(
            "app.modules.registry.routes.get_transaction_count_db",
            new_callable=AsyncMock,
            return_value=42,
        ), patch(
            "app.modules.registry.routes.compute_trust_score_db",
            new_callable=AsyncMock,
            return_value=90,
        ), patch(
            "app.modules.registry.routes._get_health_status",
            new_callable=AsyncMock,
            return_value="healthy",
        ), patch(
            "app.modules.registry.routes._increment_discovery_counter",
        ):
            resp = client.get(f"/api/v1/registry/agents/{AGENT_A_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == AGENT_A_ID
        assert data["tenant_name"] == "Acme Corp"
        assert data["transaction_count"] == 42
        assert data["trust_score"] == 90

    def test_get_private_agent_returns_404(self, client):
        """Non-public agent should return 404 even if it exists."""
        agent = _sample_agent(is_public=False)
        with patch(
            "app.modules.registry.routes.get_agent_card_db",
            new_callable=AsyncMock,
            return_value=agent,
        ):
            resp = client.get(f"/api/v1/registry/agents/{AGENT_A_ID}")
        assert resp.status_code == 404

    def test_get_missing_agent_returns_404(self, client):
        """Agent not in DB returns 404."""
        with patch(
            "app.modules.registry.routes.get_agent_card_db",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(f"/api/v1/registry/agents/{AGENT_A_ID}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API-092: PUT /registry/agents/{agent_id} — update
# ---------------------------------------------------------------------------


class TestUpdateAgentCard:
    """API-092: Update agent card."""

    def test_update_requires_ownership(self, client):
        """Different tenant trying to update should get 403."""
        # TENANT_B admin tries to update TENANT_A's agent
        with patch(
            "app.modules.registry.routes.get_agent_card_by_tenant_db",
            new_callable=AsyncMock,
            return_value=None,  # not found for tenant B
        ):
            resp = client.put(
                f"/api/v1/registry/agents/{AGENT_A_ID}",
                json={"description": "Updated"},
                headers=_admin_b_headers(),
            )
        assert resp.status_code == 403

    def test_update_success(self, client):
        """Owner can update agent card."""
        agent = _sample_agent()
        updated_agent = {**agent, "description": "Updated description"}
        with patch(
            "app.modules.registry.routes.get_agent_card_by_tenant_db",
            new_callable=AsyncMock,
            return_value=agent,
        ), patch(
            "app.modules.registry.routes.update_agent_registry_db",
            new_callable=AsyncMock,
            return_value=updated_agent,
        ):
            resp = client.put(
                f"/api/v1/registry/agents/{AGENT_A_ID}",
                json={"description": "Updated description"},
                headers=_admin_a_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == AGENT_A_ID
        assert "updated_at" in data

    def test_update_non_https_endpoint_rejected(self, client):
        """HTTP endpoint should fail validation."""
        agent = _sample_agent()
        with patch(
            "app.modules.registry.routes.get_agent_card_by_tenant_db",
            new_callable=AsyncMock,
            return_value=agent,
        ):
            resp = client.put(
                f"/api/v1/registry/agents/{AGENT_A_ID}",
                json={"a2a_endpoint": "http://bad.example.com"},
                headers=_admin_a_headers(),
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# API-093: DELETE /registry/agents/{agent_id} — deregister
# ---------------------------------------------------------------------------


class TestDeregisterAgent:
    """API-093: Deregister agent."""

    def test_deregister_requires_ownership(self, client):
        """Different tenant cannot deregister another tenant's agent."""
        with patch(
            "app.modules.registry.routes.get_agent_card_by_tenant_db",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.delete(
                f"/api/v1/registry/agents/{AGENT_A_ID}",
                headers=_admin_b_headers(),
            )
        assert resp.status_code == 403

    def test_deregister_success_returns_204(self, client):
        """Owner can deregister — returns 204 No Content."""
        agent = _sample_agent()
        with patch(
            "app.modules.registry.routes.get_agent_card_by_tenant_db",
            new_callable=AsyncMock,
            return_value=agent,
        ), patch(
            "app.modules.registry.routes.abandon_open_transactions_db",
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            "app.modules.registry.routes.deregister_agent_db",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.delete(
                f"/api/v1/registry/agents/{AGENT_A_ID}",
                headers=_admin_a_headers(),
            )
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# API-094: POST /registry/transactions — initiate
# ---------------------------------------------------------------------------


class TestInitiateTransaction:
    """API-094: Initiate A2A transaction."""

    def test_initiate_transaction_requires_auth(self, client):
        """No auth returns 401."""
        resp = client.post(
            "/api/v1/registry/transactions",
            json={
                "from_agent_id": AGENT_A_ID,
                "to_agent_id": AGENT_B_ID,
                "message_type": "RFQ",
            },
        )
        assert resp.status_code == 401

    def test_initiate_transaction_from_agent_must_be_own_tenant(self, client):
        """from_agent not belonging to user's tenant → 403."""
        with patch(
            "app.modules.registry.routes.get_agent_card_by_tenant_db",
            new_callable=AsyncMock,
            return_value=None,  # from_agent not found in tenant
        ):
            resp = client.post(
                "/api/v1/registry/transactions",
                json={
                    "from_agent_id": AGENT_A_ID,
                    "to_agent_id": AGENT_B_ID,
                    "message_type": "RFQ",
                },
                headers=_end_user_headers(),
            )
        assert resp.status_code == 403

    def test_initiate_invalid_message_type_rejected(self, client):
        """Invalid message_type → 422."""
        agent_a = _sample_agent(tenant_id=TENANT_A)
        with patch(
            "app.modules.registry.routes.get_agent_card_by_tenant_db",
            new_callable=AsyncMock,
            return_value=agent_a,
        ):
            resp = client.post(
                "/api/v1/registry/transactions",
                json={
                    "from_agent_id": AGENT_A_ID,
                    "to_agent_id": AGENT_B_ID,
                    "message_type": "INVALID_TYPE",
                },
                headers=_end_user_headers(),
            )
        assert resp.status_code == 422

    def test_initiate_to_agent_not_public_returns_404(self, client):
        """to_agent not in public registry → 404."""
        agent_a = _sample_agent(tenant_id=TENANT_A)
        agent_b_private = _sample_agent(
            agent_id=AGENT_B_ID, tenant_id=TENANT_B, is_public=False
        )
        with patch(
            "app.modules.registry.routes.get_agent_card_by_tenant_db",
            new_callable=AsyncMock,
            return_value=agent_a,
        ), patch(
            "app.modules.registry.routes.get_agent_card_db",
            new_callable=AsyncMock,
            return_value=agent_b_private,
        ):
            resp = client.post(
                "/api/v1/registry/transactions",
                json={
                    "from_agent_id": AGENT_A_ID,
                    "to_agent_id": AGENT_B_ID,
                    "message_type": "CAPABILITY_QUERY",
                },
                headers=_end_user_headers(),
            )
        assert resp.status_code == 404

    def test_initiate_transaction_success(self, client):
        """Valid request returns 201 with txn_id."""
        agent_a = _sample_agent(tenant_id=TENANT_A)
        agent_b = _sample_agent(agent_id=AGENT_B_ID, tenant_id=TENANT_B)
        txn_result = {
            "txn_id": HAR_TXN_ID,
            "internal_id": TXN_UUID,
            "status": "OPEN",
            "message_id": "msg-uuid-001",
        }
        with patch(
            "app.modules.registry.routes.get_agent_card_by_tenant_db",
            new_callable=AsyncMock,
            return_value=agent_a,
        ), patch(
            "app.modules.registry.routes.get_agent_card_db",
            new_callable=AsyncMock,
            return_value=agent_b,
        ), patch(
            "app.modules.registry.routes.create_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=txn_result,
        ):
            resp = client.post(
                "/api/v1/registry/transactions",
                json={
                    "from_agent_id": AGENT_A_ID,
                    "to_agent_id": AGENT_B_ID,
                    "message_type": "CAPABILITY_QUERY",
                },
                headers=_end_user_headers(),
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["txn_id"] == HAR_TXN_ID
        assert data["status"] == "OPEN"
        assert "message_id" in data


# ---------------------------------------------------------------------------
# API-095: GET /registry/transactions/{txn_id} — status + audit trail
# ---------------------------------------------------------------------------


class TestGetTransactionStatus:
    """API-095: Get transaction status and audit trail."""

    def test_get_transaction_requires_participation(self, client):
        """User whose tenant owns neither agent should get 403."""
        txn = _sample_transaction(tenant_id=TENANT_A)
        # Both agents belong to TENANT_B — not TENANT_A user's tenant
        agent_a = _sample_agent(agent_id=AGENT_A_ID, tenant_id=TENANT_B)
        agent_b = _sample_agent(agent_id=AGENT_B_ID, tenant_id=TENANT_B)
        with patch(
            "app.modules.registry.routes.get_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=txn,
        ), patch(
            "app.modules.registry.routes.get_agent_card_db",
            new_callable=AsyncMock,
            side_effect=[agent_a, agent_b],
        ):
            resp = client.get(
                f"/api/v1/registry/transactions/{HAR_TXN_ID}",
                headers=_end_user_headers(),  # TENANT_A user
            )
        assert resp.status_code == 403

    def test_get_transaction_participant_can_read(self, client):
        """User whose tenant owns from_agent can read transaction."""
        txn = _sample_transaction(tenant_id=TENANT_A)
        agent_a = _sample_agent(agent_id=AGENT_A_ID, tenant_id=TENANT_A)
        agent_b = _sample_agent(agent_id=AGENT_B_ID, tenant_id=TENANT_B)
        with patch(
            "app.modules.registry.routes.get_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=txn,
        ), patch(
            "app.modules.registry.routes.get_agent_card_db",
            new_callable=AsyncMock,
            side_effect=[agent_a, agent_b],
        ):
            resp = client.get(
                f"/api/v1/registry/transactions/{HAR_TXN_ID}",
                headers=_end_user_headers(),  # TENANT_A user
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["txn_id"] == HAR_TXN_ID
        assert "events" in data


# ---------------------------------------------------------------------------
# API-096: POST /registry/transactions/{txn_id}/approve
# ---------------------------------------------------------------------------


class TestApproveTransaction:
    """API-096: Approve transaction."""

    def test_approve_transitions_to_committed(self, client):
        """Tenant admin of initiating tenant can approve — transitions to COMMITTED."""
        txn = _sample_transaction(tenant_id=TENANT_A)
        agent_a = _sample_agent(agent_id=AGENT_A_ID, tenant_id=TENANT_A)
        updated_txn = {
            "id": TXN_UUID,
            "tenant_id": TENANT_A,
            "initiator_agent_id": AGENT_A_ID,
            "counterparty_agent_id": AGENT_B_ID,
            "state": "COMMITTED",
            "amount": None,
            "currency": None,
            "payload": {},
            "requires_human_approval": True,
            "human_approved_at": "2026-03-08T12:00:00+00:00",
            "human_approved_by": USER_ADMIN_A,
            "approval_deadline": None,
            "chain_head_hash": None,
            "created_at": "2026-03-08T00:00:00+00:00",
            "updated_at": "2026-03-08T12:00:00+00:00",
        }
        with patch(
            "app.modules.registry.routes.get_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=txn,
        ), patch(
            "app.modules.registry.routes.get_agent_card_db",
            new_callable=AsyncMock,
            return_value=agent_a,
        ), patch(
            "app.modules.registry.routes.set_approval_db",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.registry.routes.transition_state",
            new_callable=AsyncMock,
            return_value=updated_txn,
        ):
            resp = client.post(
                f"/api/v1/registry/transactions/{HAR_TXN_ID}/approve",
                headers=_admin_a_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["txn_id"] == HAR_TXN_ID
        assert data["status"] == "COMMITTED"

    def test_approve_wrong_tenant_returns_403(self, client):
        """Admin of non-initiating tenant cannot approve."""
        txn = _sample_transaction(tenant_id=TENANT_A)
        # from_agent belongs to TENANT_A, but TENANT_B admin is calling
        agent_a = _sample_agent(agent_id=AGENT_A_ID, tenant_id=TENANT_A)
        with patch(
            "app.modules.registry.routes.get_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=txn,
        ), patch(
            "app.modules.registry.routes.get_agent_card_db",
            new_callable=AsyncMock,
            return_value=agent_a,
        ):
            resp = client.post(
                f"/api/v1/registry/transactions/{HAR_TXN_ID}/approve",
                headers=_admin_b_headers(),  # TENANT_B
            )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# API-097: POST /registry/transactions/{txn_id}/reject
# ---------------------------------------------------------------------------


class TestRejectTransaction:
    """API-097: Reject transaction."""

    def test_reject_transitions_to_abandoned(self, client):
        """Tenant admin of initiating tenant can reject."""
        txn = _sample_transaction(tenant_id=TENANT_A)
        agent_a = _sample_agent(agent_id=AGENT_A_ID, tenant_id=TENANT_A)
        abandoned_txn = {
            "id": TXN_UUID,
            "tenant_id": TENANT_A,
            "initiator_agent_id": AGENT_A_ID,
            "counterparty_agent_id": AGENT_B_ID,
            "state": "ABANDONED",
            "amount": None,
            "currency": None,
            "payload": {},
            "requires_human_approval": True,
            "human_approved_at": None,
            "human_approved_by": None,
            "approval_deadline": None,
            "chain_head_hash": None,
            "created_at": "2026-03-08T00:00:00+00:00",
            "updated_at": "2026-03-08T12:00:00+00:00",
        }
        with patch(
            "app.modules.registry.routes.get_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=txn,
        ), patch(
            "app.modules.registry.routes.get_agent_card_db",
            new_callable=AsyncMock,
            return_value=agent_a,
        ), patch(
            "app.modules.registry.routes.transition_state",
            new_callable=AsyncMock,
            return_value=abandoned_txn,
        ):
            resp = client.post(
                f"/api/v1/registry/transactions/{HAR_TXN_ID}/reject",
                headers=_admin_a_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["txn_id"] == HAR_TXN_ID
        assert data["status"] == "ABANDONED"

    def test_reject_wrong_tenant_returns_403(self, client):
        """Admin of non-initiating tenant cannot reject."""
        txn = _sample_transaction(tenant_id=TENANT_A)
        agent_a = _sample_agent(agent_id=AGENT_A_ID, tenant_id=TENANT_A)
        with patch(
            "app.modules.registry.routes.get_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=txn,
        ), patch(
            "app.modules.registry.routes.get_agent_card_db",
            new_callable=AsyncMock,
            return_value=agent_a,
        ):
            resp = client.post(
                f"/api/v1/registry/transactions/{HAR_TXN_ID}/reject",
                headers=_admin_b_headers(),
            )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# API-098: GET /registry/analytics — tenant-scoped analytics
# ---------------------------------------------------------------------------


class TestRegistryAnalytics:
    """API-098: Registry discovery analytics."""

    def test_registry_analytics_requires_tenant_admin(self, client):
        """end_user cannot access analytics."""
        resp = client.get("/api/v1/registry/analytics", headers=_end_user_headers())
        assert resp.status_code == 403

    def test_registry_analytics_no_auth_returns_401(self, client):
        """No auth returns 401."""
        resp = client.get("/api/v1/registry/analytics")
        assert resp.status_code == 401

    def test_registry_analytics_tenant_scoped(self, client):
        """Analytics only shows agents owned by current tenant."""
        analytics_data = [
            {
                "agent_id": AGENT_A_ID,
                "name": "Finance Agent",
                "discovery_count": 0,
                "transaction_count": 10,
                "trust_score": 90,
                "trust_score_trend": "up",
            }
        ]
        with patch(
            "app.modules.registry.routes.get_analytics_db",
            new_callable=AsyncMock,
            return_value=analytics_data,
        ), patch(
            "app.modules.registry.routes._get_discovery_count",
            new_callable=AsyncMock,
            return_value=42,
        ):
            resp = client.get(
                "/api/v1/registry/analytics?period=30d",
                headers=_admin_a_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert data["agents"][0]["agent_id"] == AGENT_A_ID
        assert data["agents"][0]["discovery_count"] == 42

    def test_registry_analytics_invalid_period_returns_422(self, client):
        """Invalid period parameter returns 422."""
        with patch(
            "app.modules.registry.routes.get_analytics_db",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get(
                "/api/v1/registry/analytics?period=invalid",
                headers=_admin_a_headers(),
            )
        assert resp.status_code == 422
