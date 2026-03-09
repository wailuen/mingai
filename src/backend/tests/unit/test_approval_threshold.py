"""
Unit tests for human approval threshold logic (TEST-045).

Tests the approval threshold in two code paths:
1. check_requires_approval() in har/state_machine.py (default $5000 threshold)
2. Registry route inline logic (RFQ always requires approval, amount > $5000)

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

AGENT_A = str(uuid.uuid4())
AGENT_B = str(uuid.uuid4())


def _make_token(
    user_id: str = TEST_USER_ID,
    tenant_id: str = TEST_TENANT_ID,
    roles: list[str] | None = None,
    scope: str = "tenant",
) -> str:
    if roles is None:
        roles = ["tenant_admin"]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": scope,
        "plan": "professional",
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
    return {"Authorization": f"Bearer {_make_token()}"}


def _make_txn_dict(**overrides) -> dict:
    """Build a transaction dict for mock returns."""
    base = {
        "id": str(uuid.uuid4()),
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
# check_requires_approval() — direct unit tests on the state machine function
# ---------------------------------------------------------------------------


class TestCheckRequiresApprovalFunction:
    """Unit tests for har.state_machine.check_requires_approval()."""

    @pytest.mark.asyncio
    async def test_amount_below_threshold_no_approval(self):
        """Amount $4,999 does NOT require approval (below $5,000 default)."""
        from app.modules.har.state_machine import check_requires_approval

        mock_db = AsyncMock()
        result = await check_requires_approval(4999.0, TEST_TENANT_ID, mock_db)
        assert result is False

    @pytest.mark.asyncio
    async def test_amount_at_threshold_requires_approval(self):
        """Amount $5,000 requires approval (at threshold)."""
        from app.modules.har.state_machine import check_requires_approval

        mock_db = AsyncMock()
        result = await check_requires_approval(5000.0, TEST_TENANT_ID, mock_db)
        assert result is True

    @pytest.mark.asyncio
    async def test_amount_above_threshold_requires_approval(self):
        """Amount $5,001 requires approval (above threshold)."""
        from app.modules.har.state_machine import check_requires_approval

        mock_db = AsyncMock()
        result = await check_requires_approval(5001.0, TEST_TENANT_ID, mock_db)
        assert result is True

    @pytest.mark.asyncio
    async def test_none_amount_no_approval(self):
        """None amount does not require approval (no financial commitment)."""
        from app.modules.har.state_machine import check_requires_approval

        mock_db = AsyncMock()
        result = await check_requires_approval(None, TEST_TENANT_ID, mock_db)
        assert result is False

    @pytest.mark.asyncio
    async def test_zero_amount_no_approval(self):
        """Amount $0 does NOT require approval (below threshold)."""
        from app.modules.har.state_machine import check_requires_approval

        mock_db = AsyncMock()
        result = await check_requires_approval(0.0, TEST_TENANT_ID, mock_db)
        assert result is False


# ---------------------------------------------------------------------------
# POST /har/transactions — approval flag propagation via route
# ---------------------------------------------------------------------------


class TestApprovalThresholdViaHarRoute:
    """POST /api/v1/har/transactions — approval flag set correctly."""

    def test_below_threshold_no_approval_flag(self, client, admin_headers):
        """$4,999 transaction should NOT have requires_human_approval=True."""
        with patch(
            "app.modules.har.routes.create_transaction_db",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = _make_txn_dict(
                amount=4999.0, requires_human_approval=False
            )
            resp = client.post(
                "/api/v1/har/transactions",
                json={
                    "initiator_agent_id": AGENT_A,
                    "counterparty_agent_id": AGENT_B,
                    "amount": 4999.0,
                    "currency": "USD",
                },
                headers=admin_headers,
            )
        assert resp.status_code == 201
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["requires_human_approval"] is False
        assert call_kwargs["approval_deadline"] is None

    def test_at_threshold_sets_approval_flag(self, client, admin_headers):
        """$5,000 transaction should have requires_human_approval=True and deadline."""
        with patch(
            "app.modules.har.routes.create_transaction_db",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = _make_txn_dict(
                amount=5000.0,
                requires_human_approval=True,
                approval_deadline="2026-03-10T00:00:00+00:00",
            )
            resp = client.post(
                "/api/v1/har/transactions",
                json={
                    "initiator_agent_id": AGENT_A,
                    "counterparty_agent_id": AGENT_B,
                    "amount": 5000.0,
                    "currency": "USD",
                },
                headers=admin_headers,
            )
        assert resp.status_code == 201
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["requires_human_approval"] is True
        assert call_kwargs["approval_deadline"] is not None


# ---------------------------------------------------------------------------
# Registry route — RFQ always requires approval, CAPABILITY_QUERY does not
# ---------------------------------------------------------------------------


class TestRegistryApprovalLogic:
    """POST /api/v1/registry/transactions — registry-specific approval rules."""

    def test_rfq_always_requires_approval(self, client, admin_headers):
        """message_type=RFQ always requires approval regardless of amount."""
        with (
            patch(
                "app.modules.registry.routes.get_agent_card_by_tenant_db",
                new_callable=AsyncMock,
            ) as mock_tenant_agent,
            patch(
                "app.modules.registry.routes.get_agent_card_db",
                new_callable=AsyncMock,
            ) as mock_public_agent,
            patch(
                "app.modules.registry.routes.create_registry_transaction_db",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_tenant_agent.return_value = {"id": AGENT_A, "name": "Agent A"}
            mock_public_agent.return_value = {
                "id": AGENT_B,
                "name": "Agent B",
                "is_public": True,
            }
            mock_create.return_value = {
                "txn_id": "HAR-20260308-123456",
                "internal_id": str(uuid.uuid4()),
                "status": "OPEN",
                "message_id": str(uuid.uuid4()),
            }
            resp = client.post(
                "/api/v1/registry/transactions",
                json={
                    "from_agent_id": AGENT_A,
                    "to_agent_id": AGENT_B,
                    "message_type": "RFQ",
                    "payload": {},
                },
                headers=admin_headers,
            )
        assert resp.status_code == 201
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["requires_human_approval"] is True

    def test_capability_query_without_large_amount_no_approval(
        self, client, admin_headers
    ):
        """CAPABILITY_QUERY without large amount does not require approval."""
        with (
            patch(
                "app.modules.registry.routes.get_agent_card_by_tenant_db",
                new_callable=AsyncMock,
            ) as mock_tenant_agent,
            patch(
                "app.modules.registry.routes.get_agent_card_db",
                new_callable=AsyncMock,
            ) as mock_public_agent,
            patch(
                "app.modules.registry.routes.create_registry_transaction_db",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_tenant_agent.return_value = {"id": AGENT_A, "name": "Agent A"}
            mock_public_agent.return_value = {
                "id": AGENT_B,
                "name": "Agent B",
                "is_public": True,
            }
            mock_create.return_value = {
                "txn_id": "HAR-20260308-654321",
                "internal_id": str(uuid.uuid4()),
                "status": "OPEN",
                "message_id": str(uuid.uuid4()),
            }
            resp = client.post(
                "/api/v1/registry/transactions",
                json={
                    "from_agent_id": AGENT_A,
                    "to_agent_id": AGENT_B,
                    "message_type": "CAPABILITY_QUERY",
                    "payload": {},
                },
                headers=admin_headers,
            )
        assert resp.status_code == 201
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["requires_human_approval"] is False
