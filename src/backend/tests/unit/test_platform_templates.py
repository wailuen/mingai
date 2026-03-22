"""
Unit tests for platform agent template and tool catalog endpoints.

PA-020: POST /platform/agent-templates — create Draft
PA-020: GET  /platform/agent-templates — list templates
PA-020: GET  /platform/agent-templates/{id} — detail
PA-020: PATCH /platform/agent-templates/{id} — partial update

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
TEST_TEMPLATE_ID = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"

_MOD = "app.modules.platform.routes"


def _make_platform_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "00000000-0000-0000-0000-000000000001",
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
        "sub": "00000000-0000-0000-0000-000000000002",
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
# POST /platform/agent-templates — PA-020
# ---------------------------------------------------------------------------

_VALID_CREATE_BODY = {
    "name": "Finance Assistant",
    "category": "Finance",
    "description": "Answers finance queries.",
    "system_prompt": "You are a finance assistant.",
    "variable_definitions": [],
    "guardrails": [],
}

_MOCK_TEMPLATE = {
    "id": TEST_TEMPLATE_ID,
    "name": "Finance Assistant",
    "description": "Answers finance queries.",
    "category": "Finance",
    "system_prompt": "You are a finance assistant.",
    "variable_definitions": [],
    "guardrails": [],
    "confidence_threshold": None,
    "version": 1,
    "status": "Draft",
    "changelog": None,
    "created_by": "00000000-0000-0000-0000-000000000001",
    "created_at": "2026-03-16T00:00:00+00:00",
    "updated_at": "2026-03-16T00:00:00+00:00",
}


class TestCreateAgentTemplate:
    """POST /api/v1/platform/agent-templates"""

    def test_requires_platform_admin(self, client, tenant_headers):
        resp = client.post(
            "/api/v1/platform/agent-templates",
            json=_VALID_CREATE_BODY,
            headers=tenant_headers,
        )
        assert resp.status_code == 403

    def test_requires_auth(self, client):
        resp = client.post(
            "/api/v1/platform/agent-templates",
            json=_VALID_CREATE_BODY,
        )
        assert resp.status_code == 401

    def test_rejects_empty_name(self, client, platform_headers):
        body = {**_VALID_CREATE_BODY, "name": ""}
        resp = client.post(
            "/api/v1/platform/agent-templates",
            json=body,
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_allows_empty_system_prompt_for_draft(self, client, platform_headers):
        """TODO-20: Empty system_prompt is valid for draft saves; validation runs at publish time."""
        body = {**_VALID_CREATE_BODY, "system_prompt": ""}
        resp = client.post(
            "/api/v1/platform/agent-templates",
            json=body,
            headers=platform_headers,
        )
        assert resp.status_code == 201

    def test_rejects_reserved_variable_name(self, client, platform_headers):
        body = {
            **_VALID_CREATE_BODY,
            "variable_definitions": [
                {
                    "name": "company_name",
                    "type": "text",
                    "label": "Company",
                    "required": True,
                }
            ],
        }
        resp = client.post(
            "/api/v1/platform/agent-templates",
            json=body,
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_rejects_invalid_variable_type(self, client, platform_headers):
        body = {
            **_VALID_CREATE_BODY,
            "variable_definitions": [
                {"name": "role", "type": "string", "label": "Role", "required": False}
            ],
        }
        resp = client.post(
            "/api/v1/platform/agent-templates",
            json=body,
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_rejects_variable_without_label(self, client, platform_headers):
        body = {
            **_VALID_CREATE_BODY,
            "variable_definitions": [
                {"name": "role", "type": "text", "required": False}
                # missing "label"
            ],
        }
        resp = client.post(
            "/api/v1/platform/agent-templates",
            json=body,
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_create_success_returns_201_with_full_row(self, client, platform_headers):
        with patch(
            f"{_MOD}._create_agent_template_db",
            new_callable=AsyncMock,
        ) as mock_db:
            mock_db.return_value = _MOCK_TEMPLATE
            resp = client.post(
                "/api/v1/platform/agent-templates",
                json=_VALID_CREATE_BODY,
                headers=platform_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == TEST_TEMPLATE_ID
        assert data["status"] == "Draft"
        assert data["version"] == 1
        # Full row shape — created_at and system_prompt must be present
        assert "created_at" in data
        assert "system_prompt" in data

    def test_confidence_threshold_validated(self, client, platform_headers):
        """confidence_threshold must be 0.00–1.00."""
        body = {**_VALID_CREATE_BODY, "confidence_threshold": 1.5}
        resp = client.post(
            "/api/v1/platform/agent-templates",
            json=body,
            headers=platform_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /platform/agent-templates — PA-020
# ---------------------------------------------------------------------------


class TestListAgentTemplates:
    """GET /api/v1/platform/agent-templates"""

    def test_requires_auth(self, client):
        resp = client.get("/api/v1/platform/agent-templates")
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
            "/api/v1/platform/agent-templates",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_platform_admin_sees_all_statuses(self, client, platform_headers):
        """Platform admin list endpoint returns items+total+page."""
        # Uses real DB session mock via dependency_overrides
        from app.core.session import get_async_session
        from app.main import app
        from unittest.mock import MagicMock

        session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=0)
        rows_result = MagicMock()
        rows_result.fetchall = MagicMock(return_value=[])
        session.execute = AsyncMock(side_effect=[count_result, rows_result])

        async def _dep():
            yield session

        app.dependency_overrides[get_async_session] = _dep
        try:
            resp = client.get(
                "/api/v1/platform/agent-templates",
                headers=platform_headers,
            )
        finally:
            app.dependency_overrides.pop(get_async_session, None)

        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_rejects_invalid_status_filter(self, client, platform_headers):
        resp = client.get(
            "/api/v1/platform/agent-templates?status=Active",
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_tenant_admin_cannot_filter_by_status(self, client, tenant_headers):
        """Tenant admins may not use ?status= filter — returns 422."""
        resp = client.get(
            "/api/v1/platform/agent-templates?status=Published",
            headers=tenant_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /platform/agent-templates/{id} — PA-020
# ---------------------------------------------------------------------------


class TestGetAgentTemplate:
    """GET /api/v1/platform/agent-templates/{id}"""

    def test_returns_404_for_missing_template(self, client, platform_headers):
        with patch(
            f"{_MOD}._get_agent_template_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None
            resp = client.get(
                f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}",
                headers=platform_headers,
            )
        assert resp.status_code == 404

    def test_returns_template_for_platform_admin(self, client, platform_headers):
        with patch(
            f"{_MOD}._get_agent_template_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = _MOCK_TEMPLATE
            resp = client.get(
                f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}",
                headers=platform_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == TEST_TEMPLATE_ID

    def test_tenant_admin_cannot_see_draft(self, client, tenant_headers):
        """Tenant admins only see Published/seed templates."""
        draft_template = {**_MOCK_TEMPLATE, "status": "Draft"}
        with patch(
            f"{_MOD}._get_agent_template_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = draft_template
            resp = client.get(
                f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}",
                headers=tenant_headers,
            )
        assert resp.status_code == 404

    def test_tenant_admin_can_see_published(self, client, tenant_headers):
        published_template = {**_MOCK_TEMPLATE, "status": "Published"}
        with patch(
            f"{_MOD}._get_agent_template_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = published_template
            resp = client.get(
                f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}",
                headers=tenant_headers,
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# PATCH /platform/agent-templates/{id} — PA-020
# ---------------------------------------------------------------------------


class TestPatchAgentTemplate:
    """PATCH /api/v1/platform/agent-templates/{template_id}"""

    def test_requires_platform_admin(self, client, tenant_headers):
        resp = client.patch(
            f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}",
            json={"status": "Published"},
            headers=tenant_headers,
        )
        assert resp.status_code == 403

    def test_returns_404_for_missing_template(self, client, platform_headers):
        with patch(
            f"{_MOD}._get_agent_template_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None
            resp = client.patch(
                f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}",
                json={"status": "Published"},
                headers=platform_headers,
            )
        assert resp.status_code == 404

    def test_publish_requires_changelog(self, client, platform_headers):
        """Transitioning to Published without changelog returns 422."""
        draft = {**_MOCK_TEMPLATE, "status": "Draft"}
        with patch(
            f"{_MOD}._get_agent_template_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = draft
            resp = client.patch(
                f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}",
                json={"status": "Published"},  # no changelog
                headers=platform_headers,
            )
        assert resp.status_code == 422
        assert "changelog" in resp.json()["detail"].lower()

    def test_published_system_prompt_immutable(self, client, platform_headers):
        """PATCH system_prompt on Published template returns 409."""
        published = {**_MOCK_TEMPLATE, "status": "Published"}
        with patch(
            f"{_MOD}._get_agent_template_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = published
            resp = client.patch(
                f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}",
                json={"system_prompt": "new prompt"},
                headers=platform_headers,
            )
        assert resp.status_code == 409
        assert "immutable" in resp.json()["detail"].lower()

    def test_deprecated_cannot_change_status(self, client, platform_headers):
        deprecated = {**_MOCK_TEMPLATE, "status": "Deprecated"}
        with patch(
            f"{_MOD}._get_agent_template_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = deprecated
            resp = client.patch(
                f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}",
                json={"status": "Published"},
                headers=platform_headers,
            )
        assert resp.status_code == 422

    def test_patch_status_rejects_seed(self, client, platform_headers):
        """'seed' status cannot be set via API."""
        draft = {**_MOCK_TEMPLATE, "status": "Draft"}
        with patch(
            f"{_MOD}._get_agent_template_db",
            new_callable=AsyncMock,
        ):
            resp = client.patch(
                f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}",
                json={"status": "seed"},
                headers=platform_headers,
            )
        # Pydantic pattern validation blocks 'seed'
        assert resp.status_code == 422

    def test_patch_draft_name_success(self, client, platform_headers):
        draft = {**_MOCK_TEMPLATE, "status": "Draft"}
        updated = {**_MOCK_TEMPLATE, "name": "Updated Name"}
        with (
            patch(
                f"{_MOD}._get_agent_template_db",
                new_callable=AsyncMock,
            ) as mock_get,
            patch(
                f"{_MOD}._patch_agent_template_db",
                new_callable=AsyncMock,
            ) as mock_patch,
        ):
            mock_get.return_value = draft
            mock_patch.return_value = updated
            resp = client.patch(
                f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}",
                json={"name": "Updated Name"},
                headers=platform_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    def test_publish_with_changelog_success(self, client, platform_headers):
        draft = {**_MOCK_TEMPLATE, "status": "Draft"}
        published = {
            **_MOCK_TEMPLATE,
            "status": "Published",
            "changelog": "Initial release.",
        }
        with (
            patch(
                f"{_MOD}._get_agent_template_db",
                new_callable=AsyncMock,
            ) as mock_get,
            patch(
                f"{_MOD}._patch_agent_template_db",
                new_callable=AsyncMock,
            ) as mock_patch,
        ):
            mock_get.return_value = draft
            mock_patch.return_value = published
            resp = client.patch(
                f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}",
                json={"status": "Published", "changelog": "Initial release."},
                headers=platform_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "Published"


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
