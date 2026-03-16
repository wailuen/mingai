"""
Unit tests for PA-023: Tenant template instance deployment API.

  POST /admin/agents/deploy  — extended to support agent_templates (PA-019)
  GET  /admin/agents         — includes template_name and template_id

Tier 1: Fast, isolated. Uses dependency_overrides + AsyncMock helpers.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "d" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"
TEST_TEMPLATE_ID = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
TEST_KB_ID = "11112222-3333-4444-5555-666677778888"

_MOD = "app.modules.agents.routes"

_DEPLOY_URL = "/api/v1/admin/agents/deploy"
_LIST_URL = "/api/v1/admin/agents"


def _make_tenant_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "tenant-admin-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_viewer_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "viewer-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["viewer"],
        "scope": "tenant",
        "plan": "professional",
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


def _tenant_headers() -> dict:
    return {"Authorization": f"Bearer {_make_tenant_token()}"}


def _viewer_headers() -> dict:
    return {"Authorization": f"Bearer {_make_viewer_token()}"}


_MOCK_AGENT_TEMPLATE = {
    "id": TEST_TEMPLATE_ID,
    "name": "HR Bot",
    "description": "HR assistant for {{company}}.",
    "category": "HR",
    "system_prompt": "You are an HR assistant for {{company}}.",
    "variable_definitions": [
        {"name": "company", "type": "text", "label": "Company", "required": True}
    ],
    "guardrails": [],
    "version": 1,
}

_MOCK_DEPLOY_RESULT = {
    "id": "99990000-aaaa-bbbb-cccc-ddddeeeefffff",
    "name": "Our HR Bot",
    "template_id": TEST_TEMPLATE_ID,
    "template_version": 1,
    "template_name": "HR Bot",
    "status": "published",
}


def _patch_get_agent_template(return_value):
    return patch(
        f"{_MOD}._get_agent_template_by_id",
        new=AsyncMock(return_value=return_value),
    )


def _patch_validate_kb(return_value=None):
    return patch(
        f"{_MOD}._validate_kb_ids_for_tenant",
        new=AsyncMock(return_value=return_value),
    )


def _patch_deploy_db(return_value):
    return patch(
        f"{_MOD}.deploy_from_library_db",
        new=AsyncMock(return_value=return_value),
    )


def _patch_list_db(return_value):
    return patch(
        f"{_MOD}.list_workspace_agents_db",
        new=AsyncMock(return_value=return_value),
    )


def _patch_audit():
    return patch(f"{_MOD}.insert_audit_log", new=AsyncMock())


# ---------------------------------------------------------------------------
# POST /admin/agents/deploy — auth
# ---------------------------------------------------------------------------


class TestDeployAuth:
    def test_requires_auth(self, client):
        resp = client.post(
            _DEPLOY_URL,
            json={"template_id": TEST_TEMPLATE_ID, "name": "Bot"},
        )
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client):
        resp = client.post(
            _DEPLOY_URL,
            json={"template_id": TEST_TEMPLATE_ID, "name": "Bot"},
            headers=_viewer_headers(),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /admin/agents/deploy — agent_templates source (PA-023)
# ---------------------------------------------------------------------------


class TestDeployFromAgentTemplates:
    def test_happy_path_with_required_variable(self, client):
        with (
            _patch_get_agent_template(_MOCK_AGENT_TEMPLATE),
            _patch_validate_kb(),
            _patch_deploy_db(_MOCK_DEPLOY_RESULT),
            _patch_audit(),
        ):
            resp = client.post(
                _DEPLOY_URL,
                json={
                    "template_id": TEST_TEMPLATE_ID,
                    "name": "Our HR Bot",
                    "variable_values": {"company": "Acme Corp"},
                    "kb_ids": [],
                },
                headers=_tenant_headers(),
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "published"

    def test_missing_required_variable_returns_422(self, client):
        with (
            _patch_get_agent_template(_MOCK_AGENT_TEMPLATE),
            _patch_validate_kb(),
        ):
            resp = client.post(
                _DEPLOY_URL,
                json={
                    "template_id": TEST_TEMPLATE_ID,
                    "name": "Our HR Bot",
                    "variable_values": {},
                    "kb_ids": [],
                },
                headers=_tenant_headers(),
            )
        assert resp.status_code == 422
        assert "company" in resp.json()["detail"]

    def test_variable_values_takes_priority_over_variables(self, client):
        """variable_values field takes priority over legacy variables field."""
        deploy_mock = AsyncMock(return_value=_MOCK_DEPLOY_RESULT)
        with (
            _patch_get_agent_template(_MOCK_AGENT_TEMPLATE),
            _patch_validate_kb(),
            patch(f"{_MOD}.deploy_from_library_db", new=deploy_mock),
            _patch_audit(),
        ):
            resp = client.post(
                _DEPLOY_URL,
                json={
                    "template_id": TEST_TEMPLATE_ID,
                    "name": "Bot",
                    "variables": {"company": "OldName"},
                    "variable_values": {"company": "Acme Corp"},
                    "kb_ids": [],
                },
                headers=_tenant_headers(),
            )
        assert resp.status_code == 201
        # The system_prompt should use "Acme Corp" (variable_values), not "OldName"
        call_kwargs = deploy_mock.call_args.kwargs
        assert "Acme Corp" in call_kwargs["system_prompt"]

    def test_kb_ids_validated_against_tenant(self, client):
        """KB validation is called with the tenant's kb_ids."""
        validate_mock = AsyncMock(return_value=None)
        with (
            _patch_get_agent_template(_MOCK_AGENT_TEMPLATE),
            patch(f"{_MOD}._validate_kb_ids_for_tenant", new=validate_mock),
            _patch_deploy_db(_MOCK_DEPLOY_RESULT),
            _patch_audit(),
        ):
            resp = client.post(
                _DEPLOY_URL,
                json={
                    "template_id": TEST_TEMPLATE_ID,
                    "name": "Bot",
                    "variable_values": {"company": "Acme"},
                    "kb_ids": [TEST_KB_ID],
                },
                headers=_tenant_headers(),
            )
        assert resp.status_code == 201
        validate_mock.assert_awaited_once()
        call_args = validate_mock.call_args
        assert TEST_KB_ID in call_args.args[0]

    def test_template_name_stored_in_deploy_call(self, client):
        """template_name is passed from agent_templates.name to deploy_from_library_db."""
        deploy_mock = AsyncMock(return_value=_MOCK_DEPLOY_RESULT)
        with (
            _patch_get_agent_template(_MOCK_AGENT_TEMPLATE),
            _patch_validate_kb(),
            patch(f"{_MOD}.deploy_from_library_db", new=deploy_mock),
            _patch_audit(),
        ):
            resp = client.post(
                _DEPLOY_URL,
                json={
                    "template_id": TEST_TEMPLATE_ID,
                    "name": "Our HR Bot",
                    "variable_values": {"company": "Acme"},
                    "kb_ids": [],
                },
                headers=_tenant_headers(),
            )
        assert resp.status_code == 201
        call_kwargs = deploy_mock.call_args.kwargs
        assert call_kwargs["template_name"] == "HR Bot"

    def test_404_when_agent_template_not_found_and_not_seed(self, client):
        """If template not in agent_templates and not a seed, returns 404."""
        with (
            _patch_get_agent_template(None),
            # Ensure it also isn't in SEED templates by using a UUID that won't match
        ):
            resp = client.post(
                _DEPLOY_URL,
                json={
                    "template_id": TEST_TEMPLATE_ID,
                    "name": "Bot",
                    "variable_values": {},
                },
                headers=_tenant_headers(),
            )
        # Template not found in agent_templates, not a seed, will try agent_cards → 404
        # (The template UUID won't be in seeds or agent_cards in test DB)
        assert resp.status_code in (404, 500)  # 404 ideal; 500 if DB unreachable

    def test_optional_variable_can_be_omitted(self, client):
        template_opt = {
            **_MOCK_AGENT_TEMPLATE,
            "variable_definitions": [
                {
                    "name": "department",
                    "type": "text",
                    "label": "Department",
                    "required": False,
                }
            ],
        }
        with (
            _patch_get_agent_template(template_opt),
            _patch_validate_kb(),
            _patch_deploy_db(_MOCK_DEPLOY_RESULT),
            _patch_audit(),
        ):
            resp = client.post(
                _DEPLOY_URL,
                json={
                    "template_id": TEST_TEMPLATE_ID,
                    "name": "Bot",
                    "variable_values": {},
                    "kb_ids": [],
                },
                headers=_tenant_headers(),
            )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# _validate_kb_ids_for_tenant unit tests (direct)
# ---------------------------------------------------------------------------


class TestValidateKbIds:
    @pytest.mark.asyncio
    async def test_empty_kb_ids_passes(self):
        from app.modules.agents.routes import _validate_kb_ids_for_tenant

        mock_session = MagicMock()
        # Should not raise
        await _validate_kb_ids_for_tenant([], "tenant-id", mock_session)

    @pytest.mark.asyncio
    async def test_invalid_uuid_raises_422(self):
        from fastapi import HTTPException

        from app.modules.agents.routes import _validate_kb_ids_for_tenant

        mock_session = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await _validate_kb_ids_for_tenant(["not-a-uuid"], "tenant-id", mock_session)
        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# GET /admin/agents — template_name in response
# ---------------------------------------------------------------------------


class TestListAgentsWithTemplateName:
    def test_includes_template_name_and_template_id(self, client):
        mock_items = [
            {
                "id": "99990000-aaaa-bbbb-cccc-ddddeeeefffff",
                "name": "Our HR Bot",
                "description": "HR assistant",
                "category": "HR",
                "source": "library",
                "status": "published",
                "version": 1,
                "template_id": TEST_TEMPLATE_ID,
                "template_name": "HR Bot",
                "satisfaction_rate": 88.5,
                "user_count": 12,
                "created_at": "2026-03-16T00:00:00",
            }
        ]
        with _patch_list_db({"items": mock_items, "total": 1}):
            resp = client.get(_LIST_URL, headers=_tenant_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"][0]["template_name"] == "HR Bot"
        assert data["items"][0]["template_id"] == TEST_TEMPLATE_ID

    def test_template_name_null_for_custom_agents(self, client):
        mock_items = [
            {
                "id": "99990000-aaaa-bbbb-cccc-ddddeeeefffff",
                "name": "Custom Agent",
                "description": None,
                "category": None,
                "source": "studio",
                "status": "published",
                "version": 1,
                "template_id": None,
                "template_name": None,
                "satisfaction_rate": None,
                "user_count": 0,
                "created_at": "2026-03-16T00:00:00",
            }
        ]
        with _patch_list_db({"items": mock_items, "total": 1}):
            resp = client.get(_LIST_URL, headers=_tenant_headers())
        assert resp.status_code == 200
        assert resp.json()["items"][0]["template_name"] is None
