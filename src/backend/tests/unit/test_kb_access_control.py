"""
Unit tests for KB access control enforcement (TEST-036).

Tests that agent creation and update correctly handle kb_ids in the
capabilities JSON, and that access control is enforced at the agent
configuration level.

The current implementation stores kb_ids in agent_cards.capabilities
as a JSON array. Full KB query-time enforcement is pending schema migration
(documented in the agent deploy route warning log).

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
TEST_USER_ID = "user-admin-001"
TEST_AGENT_ID = str(uuid.uuid4())


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
        "email": "admin@test.com",
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


@pytest.fixture
def user_headers():
    return {"Authorization": f"Bearer {_make_token(roles=['end_user'])}"}


def _agent_create_body(**overrides) -> dict:
    """Build a valid agent creation request body."""
    base = {
        "name": "Test Agent",
        "description": "A test agent",
        "system_prompt": "You are a helpful assistant.",
        "kb_ids": [],
        "kb_mode": "grounded",
        "tool_ids": [],
        "guardrails": {
            "blocked_topics": [],
            "confidence_threshold": 0.5,
            "max_response_length": 2000,
        },
        "access_mode": "workspace_wide",
        "status": "draft",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Agent with empty kb_ids — unrestricted access
# ---------------------------------------------------------------------------


from unittest.mock import MagicMock


def _make_mock_session():
    """Create a mock async session that handles execute() calls."""
    mock_mappings = MagicMock()
    mock_mappings.first.return_value = {"created_at": "2026-03-08T00:00:00+00:00"}
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    return mock_session


@pytest.fixture
def mock_session_client(env_vars):
    """TestClient with session dependency overridden to a mock."""
    from app.main import app
    from app.core.session import get_async_session

    mock_session = _make_mock_session()

    async def override_session():
        return mock_session

    app.dependency_overrides[get_async_session] = override_session
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.pop(get_async_session, None)


class TestAgentEmptyKbIds:
    """Agent with kb_ids=[] should be created with unrestricted KB access."""

    def test_agent_with_empty_kb_ids_created(self, mock_session_client, admin_headers):
        """Agent with kb_ids=[] is created successfully."""
        with (
            patch(
                "app.modules.agents.routes.create_agent_studio_db",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "app.modules.agents.routes.insert_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            mock_create.return_value = {
                "id": TEST_AGENT_ID,
                "name": "Test Agent",
                "status": "draft",
            }
            resp = mock_session_client.post(
                "/api/v1/admin/agents",
                json=_agent_create_body(kb_ids=[]),
                headers=admin_headers,
            )
        assert resp.status_code == 201
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["capabilities"]["kb_ids"] == []


# ---------------------------------------------------------------------------
# Agent with specific kb_ids — restricted access
# ---------------------------------------------------------------------------


class TestAgentWithSpecificKbIds:
    """Agent with specific kb_ids restricts which KBs the agent can access."""

    def test_agent_with_kb_ids_created(self, mock_session_client, admin_headers):
        """Agent with kb_ids=['kb-1'] is created with those restrictions."""
        with (
            patch(
                "app.modules.agents.routes.create_agent_studio_db",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "app.modules.agents.routes.insert_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            mock_create.return_value = {
                "id": TEST_AGENT_ID,
                "name": "Restricted Agent",
                "status": "draft",
            }
            resp = mock_session_client.post(
                "/api/v1/admin/agents",
                json=_agent_create_body(kb_ids=["kb-1"]),
                headers=admin_headers,
            )
        assert resp.status_code == 201
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["capabilities"]["kb_ids"] == ["kb-1"]


# ---------------------------------------------------------------------------
# Update agent — KB restriction change persisted
# ---------------------------------------------------------------------------


class TestUpdateAgentKbRestriction:
    """PUT /api/v1/admin/agents/{id} — KB restriction changes are persisted."""

    def test_update_agent_sets_kb_restriction(self, mock_session_client, admin_headers):
        """Updating an agent with new kb_ids persists the restriction."""
        with (
            patch(
                "app.modules.agents.routes.update_agent_studio_db",
                new_callable=AsyncMock,
            ) as mock_update,
            patch(
                "app.modules.agents.routes.insert_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            mock_update.return_value = {
                "id": TEST_AGENT_ID,
                "name": "Updated Agent",
                "status": "draft",
                "version": 2,
                "updated_at": "2026-03-08T00:00:00+00:00",
            }
            resp = mock_session_client.put(
                f"/api/v1/admin/agents/{TEST_AGENT_ID}",
                json=_agent_create_body(
                    name="Updated Agent",
                    kb_ids=["kb-1", "kb-2"],
                ),
                headers=admin_headers,
            )
        assert resp.status_code == 200
        call_kwargs = mock_update.call_args[1]
        assert call_kwargs["capabilities"]["kb_ids"] == ["kb-1", "kb-2"]

    def test_remove_kb_restriction_sets_empty(self, mock_session_client, admin_headers):
        """Removing KB restriction sets kb_ids=[] (unrestricted)."""
        with (
            patch(
                "app.modules.agents.routes.update_agent_studio_db",
                new_callable=AsyncMock,
            ) as mock_update,
            patch(
                "app.modules.agents.routes.insert_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            mock_update.return_value = {
                "id": TEST_AGENT_ID,
                "name": "Unrestricted Agent",
                "status": "draft",
                "version": 2,
                "updated_at": "2026-03-08T00:00:00+00:00",
            }
            resp = mock_session_client.put(
                f"/api/v1/admin/agents/{TEST_AGENT_ID}",
                json=_agent_create_body(
                    name="Unrestricted Agent",
                    kb_ids=[],
                ),
                headers=admin_headers,
            )
        assert resp.status_code == 200
        call_kwargs = mock_update.call_args[1]
        assert call_kwargs["capabilities"]["kb_ids"] == []


# ---------------------------------------------------------------------------
# Auth guard — only tenant admin can configure KB access
# ---------------------------------------------------------------------------


class TestKbConfigRequiresAdmin:
    """Only tenant admins can create/update agent KB configuration."""

    def test_end_user_cannot_create_agent_with_kb_ids(self, client, user_headers):
        """End user cannot create agents (403)."""
        resp = client.post(
            "/api/v1/admin/agents",
            json=_agent_create_body(kb_ids=["kb-1"]),
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_end_user_cannot_update_agent_kb_ids(self, client, user_headers):
        """End user cannot update agent KB restrictions (403)."""
        resp = client.put(
            f"/api/v1/admin/agents/{TEST_AGENT_ID}",
            json=_agent_create_body(kb_ids=["kb-1"]),
            headers=user_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Multiple KB IDs in capabilities
# ---------------------------------------------------------------------------


class TestMultipleKbIds:
    """Agent with multiple kb_ids has all of them stored in capabilities."""

    def test_multiple_kb_ids_stored_in_capabilities(
        self, mock_session_client, admin_headers
    ):
        """Multiple kb_ids are all persisted in the capabilities JSON."""
        with (
            patch(
                "app.modules.agents.routes.create_agent_studio_db",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "app.modules.agents.routes.insert_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            mock_create.return_value = {
                "id": TEST_AGENT_ID,
                "name": "Multi-KB Agent",
                "status": "draft",
            }
            kb_list = ["kb-sharepoint", "kb-gdrive", "kb-confluence"]
            resp = mock_session_client.post(
                "/api/v1/admin/agents",
                json=_agent_create_body(kb_ids=kb_list),
                headers=admin_headers,
            )
        assert resp.status_code == 201
        call_kwargs = mock_create.call_args[1]
        stored_kb_ids = call_kwargs["capabilities"]["kb_ids"]
        assert stored_kb_ids == kb_list
        assert len(stored_kb_ids) == 3


# ---------------------------------------------------------------------------
# KB mode — grounded vs extended
# ---------------------------------------------------------------------------


class TestKbModeConfig:
    """Agent kb_mode (grounded/extended) is persisted alongside kb_ids."""

    def test_kb_mode_grounded_persisted(self, mock_session_client, admin_headers):
        """kb_mode=grounded is stored in capabilities."""
        with (
            patch(
                "app.modules.agents.routes.create_agent_studio_db",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "app.modules.agents.routes.insert_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            mock_create.return_value = {
                "id": TEST_AGENT_ID,
                "name": "Grounded Agent",
                "status": "draft",
            }
            resp = mock_session_client.post(
                "/api/v1/admin/agents",
                json=_agent_create_body(kb_ids=["kb-1"], kb_mode="grounded"),
                headers=admin_headers,
            )
        assert resp.status_code == 201
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["capabilities"]["kb_mode"] == "grounded"
        assert call_kwargs["capabilities"]["kb_ids"] == ["kb-1"]
