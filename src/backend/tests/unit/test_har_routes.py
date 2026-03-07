"""
Unit tests for HAR A2A routes (AI-043, AI-044, AI-045).

Tests transaction CRUD, state transitions, approval, and rejection endpoints.
Tier 1: Fast, isolated, uses mocking for DB helpers.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"
TEST_USER_ID = "user-001"


def _make_token(
    user_id: str = TEST_USER_ID,
    tenant_id: str = TEST_TENANT_ID,
    roles: list[str] | None = None,
    scope: str = "tenant",
    plan: str = "professional",
) -> str:
    if roles is None:
        roles = ["end_user"]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": scope,
        "plan": plan,
        "email": "user@test.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


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


@pytest.fixture
def admin_headers():
    return {
        "Authorization": f"Bearer {_make_token(roles=['tenant_admin'], scope='tenant')}"
    }


@pytest.fixture
def platform_admin_headers():
    return {
        "Authorization": f"Bearer {_make_token(roles=['tenant_admin'], scope='platform')}"
    }


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

TXN_ID = str(uuid.uuid4())
AGENT_A = str(uuid.uuid4())
AGENT_B = str(uuid.uuid4())


def _make_txn_dict(**overrides) -> dict:
    """Build a transaction dict for mock returns."""
    base = {
        "id": TXN_ID,
        "tenant_id": TEST_TENANT_ID,
        "initiator_agent_id": AGENT_A,
        "counterparty_agent_id": AGENT_B,
        "state": "DRAFT",
        "amount": None,
        "currency": None,
        "payload": {},
        "requires_human_approval": False,
        "human_approved_at": None,
        "human_approved_by": None,
        "approval_deadline": None,
        "chain_head_hash": None,
        "created_at": "2026-03-08T00:00:00+00:00",
        "updated_at": "2026-03-08T00:00:00+00:00",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# POST /har/transactions — Create transaction (AI-043)
# ---------------------------------------------------------------------------


class TestCreateTransaction:
    """POST /api/v1/har/transactions"""

    def test_create_transaction_returns_201(self, client, admin_headers):
        """Creating a transaction should return 201 with transaction data."""
        with patch(
            "app.modules.har.routes.create_transaction_db",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = _make_txn_dict()
            resp = client.post(
                "/api/v1/har/transactions",
                json={
                    "initiator_agent_id": AGENT_A,
                    "counterparty_agent_id": AGENT_B,
                },
                headers=admin_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == TXN_ID
        assert data["state"] == "DRAFT"
        assert data["initiator_agent_id"] == AGENT_A

    def test_create_transaction_large_amount_sets_approval_flag(
        self, client, admin_headers
    ):
        """Amount >= 5000 should set requires_human_approval=True and approval_deadline."""
        with patch(
            "app.modules.har.routes.create_transaction_db",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = _make_txn_dict(
                amount=6000.0,
                currency="USD",
                requires_human_approval=True,
                approval_deadline="2026-03-10T00:00:00+00:00",
            )
            resp = client.post(
                "/api/v1/har/transactions",
                json={
                    "initiator_agent_id": AGENT_A,
                    "counterparty_agent_id": AGENT_B,
                    "amount": 6000.0,
                    "currency": "USD",
                },
                headers=admin_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["requires_human_approval"] is True
        assert data["approval_deadline"] is not None

        # Verify the DB helper was called with approval fields
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["requires_human_approval"] is True
        assert call_kwargs["approval_deadline"] is not None

    def test_create_transaction_requires_auth(self, client):
        resp = client.post(
            "/api/v1/har/transactions",
            json={
                "initiator_agent_id": AGENT_A,
                "counterparty_agent_id": AGENT_B,
            },
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /har/transactions/{txn_id} — Get transaction (AI-043)
# ---------------------------------------------------------------------------


class TestGetTransaction:
    """GET /api/v1/har/transactions/{txn_id}"""

    def test_get_transaction_success(self, client, admin_headers):
        with patch(
            "app.modules.har.routes.get_transaction_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = _make_txn_dict()
            resp = client.get(
                f"/api/v1/har/transactions/{TXN_ID}", headers=admin_headers
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == TXN_ID

    def test_get_transaction_404_wrong_tenant(self, client, admin_headers):
        """Transaction not found for this tenant should return 404."""
        with patch(
            "app.modules.har.routes.get_transaction_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None
            resp = client.get(
                f"/api/v1/har/transactions/{TXN_ID}", headers=admin_headers
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /har/transactions/{txn_id}/transition — State transition (AI-043)
# ---------------------------------------------------------------------------


class TestTransitionEndpoint:
    """POST /api/v1/har/transactions/{txn_id}/transition"""

    def test_transition_state_endpoint(self, client, admin_headers):
        """Valid state transition should succeed and return updated transaction."""
        with patch(
            "app.modules.har.routes.transition_state",
            new_callable=AsyncMock,
        ) as mock_transition:
            mock_transition.return_value = _make_txn_dict(state="OPEN")
            resp = client.post(
                f"/api/v1/har/transactions/{TXN_ID}/transition",
                json={"new_state": "OPEN"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "OPEN"

    def test_transition_requires_auth(self, client):
        resp = client.post(
            f"/api/v1/har/transactions/{TXN_ID}/transition",
            json={"new_state": "OPEN"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /har/transactions/{txn_id}/approve — Approval gate (AI-045)
# ---------------------------------------------------------------------------


class TestApproveEndpoint:
    """POST /api/v1/har/transactions/{txn_id}/approve"""

    def test_approve_endpoint_sets_human_approved_at(self, client, admin_headers):
        """Approving a NEGOTIATING transaction sets human_approved_at and transitions to COMMITTED."""
        with (
            patch(
                "app.modules.har.routes.get_transaction_db",
                new_callable=AsyncMock,
            ) as mock_get,
            patch(
                "app.modules.har.routes.approve_transaction_db",
                new_callable=AsyncMock,
            ) as mock_approve,
            patch(
                "app.modules.har.routes.transition_state",
                new_callable=AsyncMock,
            ) as mock_transition,
        ):
            mock_get.return_value = _make_txn_dict(
                state="NEGOTIATING", requires_human_approval=True
            )
            mock_approve.return_value = None
            mock_transition.return_value = _make_txn_dict(
                state="COMMITTED",
                human_approved_at="2026-03-08T12:00:00+00:00",
                human_approved_by=TEST_USER_ID,
            )
            resp = client.post(
                f"/api/v1/har/transactions/{TXN_ID}/approve",
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "COMMITTED"
        assert data["human_approved_at"] is not None
        assert data["human_approved_by"] == TEST_USER_ID


# ---------------------------------------------------------------------------
# POST /har/transactions/{txn_id}/reject — Rejection gate (AI-045)
# ---------------------------------------------------------------------------


class TestRejectEndpoint:
    """POST /api/v1/har/transactions/{txn_id}/reject"""

    def test_reject_endpoint_transitions_to_abandoned(self, client, admin_headers):
        """Rejecting a transaction transitions it to ABANDONED."""
        with (
            patch(
                "app.modules.har.routes.get_transaction_db",
                new_callable=AsyncMock,
            ) as mock_get,
            patch(
                "app.modules.har.routes.transition_state",
                new_callable=AsyncMock,
            ) as mock_transition,
        ):
            mock_get.return_value = _make_txn_dict(
                state="NEGOTIATING", requires_human_approval=True
            )
            mock_transition.return_value = _make_txn_dict(state="ABANDONED")
            resp = client.post(
                f"/api/v1/har/transactions/{TXN_ID}/reject",
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "ABANDONED"


# ---------------------------------------------------------------------------
# GET /har/transactions — List transactions (AI-043)
# ---------------------------------------------------------------------------


class TestListTransactions:
    """GET /api/v1/har/transactions"""

    def test_list_transactions_success(self, client, admin_headers):
        with patch(
            "app.modules.har.routes.list_transactions_db",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = {
                "items": [_make_txn_dict()],
                "total": 1,
            }
            resp = client.get("/api/v1/har/transactions", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_list_transactions_with_state_filter(self, client, admin_headers):
        with patch(
            "app.modules.har.routes.list_transactions_db",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = {"items": [], "total": 0}
            resp = client.get(
                "/api/v1/har/transactions?state=OPEN", headers=admin_headers
            )
        assert resp.status_code == 200
        # Verify the state filter was passed
        call_kwargs = mock_list.call_args[1]
        assert call_kwargs["state_filter"] == "OPEN"

    def test_list_transactions_pagination(self, client, admin_headers):
        with patch(
            "app.modules.har.routes.list_transactions_db",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = {"items": [], "total": 0}
            resp = client.get(
                "/api/v1/har/transactions?page=2&page_size=10",
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["page_size"] == 10
