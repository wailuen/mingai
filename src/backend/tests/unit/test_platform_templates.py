"""
Unit tests for platform agent template and tool catalog endpoints.

API-038: POST /platform/agent-templates — publish template
API-040: PATCH /platform/agent-templates/{id} — update/version template
API-041: GET /platform/tool-catalog — list tools
API-042: POST /platform/tool-catalog — register tool

Tier 1: Fast, isolated, mocked DB helpers.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"


def _make_platform_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "platform-admin-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["platform_admin"],
        "scope": "platform",
        "plan": "enterprise",
        "email": "platform@mingai.io",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_tenant_token(plan: str = "professional") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "tenant-admin-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": plan,
        "email": "admin@tenant.com",
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
        "PLATFORM_TENANT_ID": "platform",
    }
    with patch.dict(os.environ, env):
        yield


@pytest.fixture
def client(env_vars):
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def platform_headers():
    return {"Authorization": f"Bearer {_make_platform_token()}"}


@pytest.fixture
def tenant_headers():
    return {"Authorization": f"Bearer {_make_tenant_token()}"}


# ---------------------------------------------------------------------------
# POST /platform/agent-templates — API-038
# ---------------------------------------------------------------------------


class TestPublishAgentTemplate:
    """POST /api/v1/platform/agent-templates"""

    _valid_body = {
        "name": "Finance Assistant",
        "category": "Finance",
        "description": "Answers finance queries.",
        "system_prompt": "You are a finance assistant.",
        "variables": [],
        "guardrails": {
            "blocked_topics": [],
            "confidence_threshold": 0.7,
            "max_response_length": 2000,
        },
        "plan_tiers": ["professional", "enterprise"],
    }

    def test_requires_platform_admin(self, client, tenant_headers):
        resp = client.post(
            "/api/v1/platform/agent-templates",
            json=self._valid_body,
            headers=tenant_headers,
        )
        assert resp.status_code == 403

    def test_requires_auth(self, client):
        resp = client.post(
            "/api/v1/platform/agent-templates",
            json=self._valid_body,
        )
        assert resp.status_code == 401

    def test_publish_template_validation_empty_name(self, client, platform_headers):
        """Empty name should be rejected with 422."""
        body = dict(self._valid_body)
        body["name"] = ""
        resp = client.post(
            "/api/v1/platform/agent-templates",
            json=body,
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_publish_template_validation_empty_system_prompt(
        self, client, platform_headers
    ):
        """Empty system_prompt should be rejected with 422."""
        body = dict(self._valid_body)
        body["system_prompt"] = ""
        resp = client.post(
            "/api/v1/platform/agent-templates",
            json=body,
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_publish_template_missing_plan_tiers(self, client, platform_headers):
        """Missing plan_tiers should be rejected with 422."""
        body = dict(self._valid_body)
        body["plan_tiers"] = []
        resp = client.post(
            "/api/v1/platform/agent-templates",
            json=body,
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_publish_template_invalid_plan_tier(self, client, platform_headers):
        """Unknown plan tier should be rejected with 422."""
        body = dict(self._valid_body)
        body["plan_tiers"] = ["premium"]
        resp = client.post(
            "/api/v1/platform/agent-templates",
            json=body,
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_publish_template_reserved_variable_name(self, client, platform_headers):
        """Variable using reserved name should be rejected with 422."""
        body = dict(self._valid_body)
        body["variables"] = [
            {
                "name": "company_name",
                "type": "string",
                "description": "The company",
                "required": True,
                "example": "Acme",
            }
        ]
        resp = client.post(
            "/api/v1/platform/agent-templates",
            json=body,
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_publish_template_success(self, client, platform_headers):
        """Valid request should call DB helper and return 201 with id/name/version/status."""
        with patch(
            "app.modules.platform.routes.publish_agent_template_db",
            new_callable=AsyncMock,
        ) as mock_db:
            mock_db.return_value = {
                "id": "tpl-001",
                "name": "Finance Assistant",
                "version": 1,
                "status": "draft",
            }
            resp = client.post(
                "/api/v1/platform/agent-templates",
                json=self._valid_body,
                headers=platform_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "tpl-001"
        assert data["name"] == "Finance Assistant"
        assert data["version"] == 1
        assert data["status"] == "draft"


# ---------------------------------------------------------------------------
# PATCH /platform/agent-templates/{id} — API-040
# ---------------------------------------------------------------------------


class TestUpdateAgentTemplate:
    """PATCH /api/v1/platform/agent-templates/{template_id}"""

    def test_requires_platform_admin(self, client, tenant_headers):
        resp = client.patch(
            "/api/v1/platform/agent-templates/some-id",
            json={"status": "published"},
            headers=tenant_headers,
        )
        assert resp.status_code == 403

    def test_returns_404_for_missing_template(self, client, platform_headers):
        with patch(
            "app.modules.platform.routes.get_platform_template_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None
            resp = client.patch(
                "/api/v1/platform/agent-templates/nonexistent",
                json={"status": "published"},
                headers=platform_headers,
            )
        assert resp.status_code == 404

    def test_update_status_to_published_success(self, client, platform_headers):
        existing = {
            "id": "tpl-001",
            "name": "Finance",
            "description": "Finance assistant",
            "system_prompt": "You are a finance assistant.",
            "capabilities": {
                "plan_tiers": ["professional"],
                "variables": [],
                "guardrails": {},
            },
            "status": "draft",
            "version": 1,
            "updated_at": datetime.now(timezone.utc),
        }
        updated = dict(existing)
        updated["status"] = "published"
        updated["updated_at"] = datetime.now(timezone.utc)

        with (
            patch(
                "app.modules.platform.routes.get_platform_template_db",
                new_callable=AsyncMock,
            ) as mock_get,
            patch(
                "app.modules.platform.routes.update_platform_template_db",
                new_callable=AsyncMock,
            ) as mock_update,
        ):
            mock_get.return_value = existing
            mock_update.return_value = updated
            resp = client.patch(
                "/api/v1/platform/agent-templates/tpl-001",
                json={"status": "published"},
                headers=platform_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "published"
        assert "updated_at" in data

    def test_update_to_published_fails_without_plan_tiers(
        self, client, platform_headers
    ):
        """Transition to published must fail if no plan_tiers in capabilities."""
        existing = {
            "id": "tpl-002",
            "name": "Empty",
            "description": "",
            "system_prompt": "You are an assistant.",
            "capabilities": {"plan_tiers": [], "variables": []},
            "status": "draft",
            "version": 1,
            "updated_at": datetime.now(timezone.utc),
        }
        with patch(
            "app.modules.platform.routes.get_platform_template_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = existing
            resp = client.patch(
                "/api/v1/platform/agent-templates/tpl-002",
                json={"status": "published"},
                headers=platform_headers,
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /platform/tool-catalog — API-041
# ---------------------------------------------------------------------------


class TestListToolCatalog:
    """GET /api/v1/platform/tool-catalog"""

    def test_requires_auth(self, client):
        resp = client.get("/api/v1/platform/tool-catalog")
        assert resp.status_code == 401

    def test_end_user_forbidden(self, client, env_vars):
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "user-001",
            "tenant_id": TEST_TENANT_ID,
            "roles": ["end_user"],
            "scope": "tenant",
            "plan": "professional",
            "exp": now + timedelta(hours=1),
            "iat": now,
            "token_version": 2,
        }
        token = jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)
        resp = client.get(
            "/api/v1/platform/tool-catalog",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_platform_admin_sees_all(self, client, platform_headers):
        with patch(
            "app.modules.platform.routes.list_tools_db",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = {
                "items": [
                    {
                        "id": "tool-001",
                        "name": "Jira",
                        "provider": "Atlassian",
                        "description": "Issue tracker",
                        "safety_class": "write",
                        "status": "healthy",
                        "health_check_last": None,
                        "plan_tiers": ["professional", "enterprise"],
                    }
                ],
                "total": 1,
                "page": 1,
                "page_size": 20,
            }
            resp = client.get(
                "/api/v1/platform/tool-catalog",
                headers=platform_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Jira"

    def test_invalid_safety_class_rejected(self, client, platform_headers):
        resp = client.get(
            "/api/v1/platform/tool-catalog?safety_class=unknown",
            headers=platform_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /platform/tool-catalog — API-042
# ---------------------------------------------------------------------------


class TestRegisterTool:
    """POST /api/v1/platform/tool-catalog"""

    _valid_body = {
        "name": "Jira",
        "provider": "Atlassian",
        "description": "Issue tracker integration",
        "endpoint_url": "https://api.atlassian.com/jira",
        "auth_type": "oauth2",
        "capabilities": ["create_issue", "list_issues"],
        "safety_class": "write",
        "plan_tiers": ["professional", "enterprise"],
    }

    def test_requires_platform_admin(self, client, tenant_headers):
        resp = client.post(
            "/api/v1/platform/tool-catalog",
            json=self._valid_body,
            headers=tenant_headers,
        )
        assert resp.status_code == 403

    def test_register_tool_rejects_http_endpoint(self, client, platform_headers):
        """HTTP endpoint URL must be rejected — only HTTPS is allowed."""
        body = dict(self._valid_body)
        body["endpoint_url"] = "http://api.atlassian.com/jira"
        resp = client.post(
            "/api/v1/platform/tool-catalog",
            json=body,
            headers=platform_headers,
        )
        assert resp.status_code == 422
        assert "https" in resp.json()["detail"].lower()

    def test_register_tool_rejects_invalid_auth_type(self, client, platform_headers):
        body = dict(self._valid_body)
        body["auth_type"] = "basic_auth"
        resp = client.post(
            "/api/v1/platform/tool-catalog",
            json=body,
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_register_tool_rejects_invalid_safety_class(self, client, platform_headers):
        body = dict(self._valid_body)
        body["safety_class"] = "extremely_dangerous"
        resp = client.post(
            "/api/v1/platform/tool-catalog",
            json=body,
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_register_tool_success(self, client, platform_headers):
        with patch(
            "app.modules.platform.routes.register_tool_db",
            new_callable=AsyncMock,
        ) as mock_db:
            mock_db.return_value = {
                "id": "tool-001",
                "name": "Jira",
                "status": "pending_health_check",
                "created_at": "2026-03-08T00:00:00+00:00",
            }
            resp = client.post(
                "/api/v1/platform/tool-catalog",
                json=self._valid_body,
                headers=platform_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "tool-001"
        assert data["status"] == "pending_health_check"
        assert "created_at" in data
