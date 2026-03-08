"""
Unit tests for API-124 and API-125 — Transaction Dispute endpoints (GAP-036).

- POST /registry/transactions/{transaction_id}/dispute     — file dispute
- POST /registry/transactions/{transaction_id}/dispute/resolve — resolve dispute

Tier 1: Fast, isolated, all DB helpers mocked.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"

TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TENANT_C = "cccccccc-cccc-cccc-cccc-cccccccccccc"

USER_ADMIN_A = "user-admin-a-001"
USER_ADMIN_B = "user-admin-b-001"
USER_PLATFORM = "user-platform-001"

AGENT_A_ID = "agent-aaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
AGENT_B_ID = "agent-bbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TXN_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
HAR_TXN_ID = "HAR-20260308-999999"
DISPUTE_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"


def _make_token(
    user_id: str = USER_ADMIN_A,
    tenant_id: str = TENANT_A,
    roles: list[str] | None = None,
    scope: str = "tenant",
) -> str:
    if roles is None:
        roles = ["tenant_admin"]
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user_id,
            "tenant_id": tenant_id,
            "roles": roles,
            "scope": scope,
            "plan": "professional",
            "email": f"{user_id}@test.com",
            "exp": now + timedelta(hours=1),
            "iat": now,
            "token_version": 2,
        },
        TEST_JWT_SECRET,
        algorithm=TEST_JWT_ALGORITHM,
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


def _platform_admin_headers():
    return {
        "Authorization": f"Bearer {_make_token(user_id=USER_PLATFORM, tenant_id=TENANT_C, roles=['platform_admin'], scope='platform')}"
    }


def _end_user_headers():
    return {
        "Authorization": f"Bearer {_make_token(user_id='end-user-001', tenant_id=TENANT_A, roles=['end_user'])}"
    }


def _sample_txn(state: str = "EXECUTING") -> dict:
    return {
        "txn_id": HAR_TXN_ID,
        "internal_id": TXN_UUID,
        "tenant_id": TENANT_A,
        "from_agent_id": AGENT_A_ID,
        "to_agent_id": AGENT_B_ID,
        "status": state,
        "payload": {"har_txn_id": HAR_TXN_ID, "message_type": "RFQ"},
        "requires_human_approval": False,
        "approval_deadline": None,
        "created_at": "2026-03-08T00:00:00+00:00",
        "updated_at": "2026-03-08T00:00:00+00:00",
        "events": [],
    }


def _sample_agent(agent_id: str, tenant_id: str) -> dict:
    return {
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "name": "Test Agent",
        "description": "desc",
        "status": "published",
        "is_public": True,
        "a2a_endpoint": "https://agent.example.com/a2a",
        "transaction_types": ["RFQ"],
        "industries": ["finance"],
        "languages": ["en"],
        "health_check_url": None,
        "public_key": None,
        "trust_score": 80,
        "capabilities": [],
        "created_at": "2026-03-08T00:00:00+00:00",
        "updated_at": "2026-03-08T00:00:00+00:00",
    }


def _sample_dispute() -> dict:
    return {
        "dispute_id": DISPUTE_ID,
        "transaction_id": TXN_UUID,
        "filed_by_tenant_id": TENANT_A,
        "status": "open",
        "filed_at": "2026-03-08T12:00:00+00:00",
    }


def _valid_dispute_body() -> dict:
    return {
        "reason": "The delivered output was completely wrong and unusable.",
        "category": "quality",
        "evidence_urls": ["https://evidence.example.com/screenshot1.png"],
        "desired_resolution": "Full refund and redelivery of correct output.",
    }


def _valid_resolve_body() -> dict:
    return {
        "resolution": "buyer_favor",
        "resolution_notes": "Evidence clearly shows output did not meet contract specification.",
        "action_taken": "Reversed charges and notified both parties.",
    }


# ---------------------------------------------------------------------------
# API-124: POST /registry/transactions/{txn_id}/dispute
# ---------------------------------------------------------------------------


class TestFileDispute:
    """API-124: File a dispute on a registry transaction."""

    def test_dispute_requires_tenant_admin(self, client):
        """End user (non-admin) cannot file a dispute — returns 403."""
        resp = client.post(
            f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute",
            json=_valid_dispute_body(),
            headers=_end_user_headers(),
        )
        assert resp.status_code == 403

    def test_dispute_no_auth_returns_401(self, client):
        """Unauthenticated request returns 401."""
        resp = client.post(
            f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute",
            json=_valid_dispute_body(),
        )
        assert resp.status_code == 401

    def test_dispute_transaction_not_found_returns_404(self, client):
        """Non-existent transaction returns 404."""
        with patch(
            "app.modules.registry.routes.get_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post(
                f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute",
                json=_valid_dispute_body(),
                headers=_admin_a_headers(),
            )
        assert resp.status_code == 404

    def test_dispute_wrong_tenant_returns_403(self, client):
        """Admin of a tenant that is not a party to the transaction returns 403."""
        txn = _sample_txn(state="EXECUTING")
        # Both agents belong to TENANT_A/TENANT_B, not TENANT_C
        agent_a = _sample_agent(AGENT_A_ID, TENANT_A)
        agent_b = _sample_agent(AGENT_B_ID, TENANT_B)
        # TENANT_C admin calls — not a party
        with patch(
            "app.modules.registry.routes.get_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=txn,
        ), patch(
            "app.modules.registry.routes.get_agent_card_db",
            new_callable=AsyncMock,
            side_effect=[agent_a, agent_b],
        ):
            token = _make_token(
                user_id="admin-c", tenant_id=TENANT_C, roles=["tenant_admin"]
            )
            resp = client.post(
                f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute",
                json=_valid_dispute_body(),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403

    def test_dispute_already_disputed_returns_409(self, client):
        """Cannot dispute a transaction already in DISPUTED state."""
        txn = _sample_txn(state="DISPUTED")
        with patch(
            "app.modules.registry.routes.get_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=txn,
        ):
            resp = client.post(
                f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute",
                json=_valid_dispute_body(),
                headers=_admin_a_headers(),
            )
        assert resp.status_code == 409

    def test_dispute_creates_dispute_record_and_returns_201(self, client):
        """Valid dispute returns 201 with dispute_id, transaction_id, status, filed_at."""
        txn = _sample_txn(state="EXECUTING")
        agent_a = _sample_agent(AGENT_A_ID, TENANT_A)
        agent_b = _sample_agent(AGENT_B_ID, TENANT_B)
        dispute = {
            "dispute_id": DISPUTE_ID,
            "transaction_id": TXN_UUID,
            "status": "open",
            "filed_at": "2026-03-08T12:00:00+00:00",
        }
        updated_txn = {**txn, "state": "DISPUTED"}
        with patch(
            "app.modules.registry.routes.get_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=txn,
        ), patch(
            "app.modules.registry.routes.get_agent_card_db",
            new_callable=AsyncMock,
            side_effect=[agent_a, agent_b],
        ), patch(
            "app.modules.registry.routes.create_dispute_db",
            new_callable=AsyncMock,
            return_value=dispute,
        ), patch(
            "app.modules.registry.routes.transition_state",
            new_callable=AsyncMock,
            return_value=updated_txn,
        ), patch(
            "app.modules.registry.routes.log_dispute_audit_event_db",
            new_callable=AsyncMock,
        ):
            resp = client.post(
                f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute",
                json=_valid_dispute_body(),
                headers=_admin_a_headers(),
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["dispute_id"] == DISPUTE_ID
        assert data["transaction_id"] == TXN_UUID
        assert data["status"] == "open"
        assert "filed_at" in data

    def test_dispute_invalid_category_returns_422(self, client):
        """Invalid category value triggers 422 validation error."""
        body = {**_valid_dispute_body(), "category": "unknown_category"}
        resp = client.post(
            f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute",
            json=body,
            headers=_admin_a_headers(),
        )
        assert resp.status_code == 422

    def test_dispute_reason_too_short_returns_422(self, client):
        """Reason shorter than 10 chars triggers 422."""
        body = {**_valid_dispute_body(), "reason": "Too short"}
        resp = client.post(
            f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute",
            json=body,
            headers=_admin_a_headers(),
        )
        assert resp.status_code == 422

    def test_dispute_abandoned_transaction_returns_409(self, client):
        """ABANDONED transaction cannot be disputed."""
        txn = _sample_txn(state="ABANDONED")
        with patch(
            "app.modules.registry.routes.get_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=txn,
        ):
            resp = client.post(
                f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute",
                json=_valid_dispute_body(),
                headers=_admin_a_headers(),
            )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# API-125: POST /registry/transactions/{txn_id}/dispute/resolve
# ---------------------------------------------------------------------------


class TestResolveDispute:
    """API-125: Resolve a transaction dispute — platform_admin only."""

    def test_resolve_requires_platform_admin(self, client):
        """Tenant admin cannot resolve disputes — returns 403."""
        resp = client.post(
            f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute/resolve",
            json=_valid_resolve_body(),
            headers=_admin_a_headers(),
        )
        assert resp.status_code == 403

    def test_resolve_no_auth_returns_401(self, client):
        """Unauthenticated request returns 401."""
        resp = client.post(
            f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute/resolve",
            json=_valid_resolve_body(),
        )
        assert resp.status_code == 401

    def test_resolve_transaction_not_found_returns_404(self, client):
        """Non-existent transaction returns 404."""
        with patch(
            "app.modules.registry.routes.get_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post(
                f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute/resolve",
                json=_valid_resolve_body(),
                headers=_platform_admin_headers(),
            )
        assert resp.status_code == 404

    def test_resolve_non_disputed_transaction_returns_409(self, client):
        """Transaction in EXECUTING state (not DISPUTED) returns 409."""
        txn = _sample_txn(state="EXECUTING")
        with patch(
            "app.modules.registry.routes.get_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=txn,
        ):
            resp = client.post(
                f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute/resolve",
                json=_valid_resolve_body(),
                headers=_platform_admin_headers(),
            )
        assert resp.status_code == 409

    def test_resolve_no_open_dispute_record_returns_404(self, client):
        """DISPUTED transaction with no open dispute record returns 404."""
        txn = _sample_txn(state="DISPUTED")
        with patch(
            "app.modules.registry.routes.get_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=txn,
        ), patch(
            "app.modules.registry.routes.get_open_dispute_db",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post(
                f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute/resolve",
                json=_valid_resolve_body(),
                headers=_platform_admin_headers(),
            )
        assert resp.status_code == 404

    def test_resolve_dispute_updates_state_and_returns_200(self, client):
        """Valid resolve returns 200 with dispute_id, resolution, resolved_at, resolved_by."""
        txn = _sample_txn(state="DISPUTED")
        dispute = _sample_dispute()
        resolved = {
            "dispute_id": DISPUTE_ID,
            "resolution": "buyer_favor",
            "resolved_at": "2026-03-08T14:00:00+00:00",
            "resolved_by": USER_PLATFORM,
        }
        resolved_txn = {**txn, "state": "RESOLVED"}
        with patch(
            "app.modules.registry.routes.get_registry_transaction_db",
            new_callable=AsyncMock,
            return_value=txn,
        ), patch(
            "app.modules.registry.routes.get_open_dispute_db",
            new_callable=AsyncMock,
            return_value=dispute,
        ), patch(
            "app.modules.registry.routes.resolve_dispute_db",
            new_callable=AsyncMock,
            return_value=resolved,
        ), patch(
            "app.modules.registry.routes.transition_state",
            new_callable=AsyncMock,
            return_value=resolved_txn,
        ), patch(
            "app.modules.registry.routes.log_dispute_audit_event_db",
            new_callable=AsyncMock,
        ):
            resp = client.post(
                f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute/resolve",
                json=_valid_resolve_body(),
                headers=_platform_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dispute_id"] == DISPUTE_ID
        assert data["resolution"] == "buyer_favor"
        assert "resolved_at" in data
        assert "resolved_by" in data

    def test_resolve_invalid_resolution_returns_422(self, client):
        """Invalid resolution value triggers 422."""
        body = {**_valid_resolve_body(), "resolution": "invalid_resolution"}
        resp = client.post(
            f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute/resolve",
            json=body,
            headers=_platform_admin_headers(),
        )
        assert resp.status_code == 422

    def test_resolve_notes_too_short_returns_422(self, client):
        """resolution_notes shorter than 10 chars triggers 422."""
        body = {**_valid_resolve_body(), "resolution_notes": "Too short"}
        resp = client.post(
            f"/api/v1/registry/transactions/{HAR_TXN_ID}/dispute/resolve",
            json=body,
            headers=_platform_admin_headers(),
        )
        assert resp.status_code == 422
