"""
Unit tests for Agent Templates routes (API-110 to API-115).

Tests agent template listing, detail, and deploy endpoints.
Tier 1: Fast, isolated, uses mocking for DB helpers.
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
def user_headers():
    return {"Authorization": f"Bearer {_make_token()}"}


@pytest.fixture
def admin_headers():
    return {
        "Authorization": f"Bearer {_make_token(roles=['tenant_admin'], scope='tenant')}"
    }


# ---------------------------------------------------------------------------
# GET /agents/templates — List templates
# ---------------------------------------------------------------------------


class TestListAgentTemplates:
    """GET /api/v1/agents/templates"""

    def test_list_requires_auth(self, client):
        resp = client.get("/api/v1/agents/templates")
        assert resp.status_code == 401

    def test_list_requires_tenant_admin(self, client, user_headers):
        resp = client.get("/api/v1/agents/templates", headers=user_headers)
        assert resp.status_code == 403

    def test_list_returns_seed_templates_with_empty_db(self, client, admin_headers):
        """Seed templates should always be returned even when DB has no agent_cards."""
        with patch(
            "app.modules.agents.routes.list_agent_templates_db",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = {"items": [], "total": 0}
            resp = client.get("/api/v1/agents/templates", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        # Should have at least the 4 seed templates
        seed_items = [i for i in data["items"] if i.get("is_seed") is True]
        assert len(seed_items) == 4
        seed_ids = {i["id"] for i in seed_items}
        assert seed_ids == {"seed-hr", "seed-it", "seed-procurement", "seed-onboarding"}

    def test_list_merges_db_and_seed_templates(self, client, admin_headers):
        """DB results should be merged with seed templates."""
        db_agent = {
            "id": "db-agent-001",
            "name": "Custom Agent",
            "description": "A custom agent",
            "system_prompt": "You are a custom agent.",
            "capabilities": ["custom"],
            "status": "published",
            "version": 1,
            "is_seed": False,
            "created_at": "2026-03-07T00:00:00+00:00",
        }
        with patch(
            "app.modules.agents.routes.list_agent_templates_db",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = {"items": [db_agent], "total": 1}
            resp = client.get("/api/v1/agents/templates", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        # 4 seed + 1 DB = 5 items
        assert len(data["items"]) == 5
        assert data["total"] == 5

    def test_list_category_filter_works_on_seed(self, client, admin_headers):
        """Category filter should filter seed templates too."""
        with patch(
            "app.modules.agents.routes.list_agent_templates_db",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = {"items": [], "total": 0}
            resp = client.get(
                "/api/v1/agents/templates?category=HR", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        # Only the HR seed template should match
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "seed-hr"
        assert data["items"][0]["category"] == "HR"

    def test_list_category_filter_case_insensitive(self, client, admin_headers):
        """Category filter should be case-insensitive."""
        with patch(
            "app.modules.agents.routes.list_agent_templates_db",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = {"items": [], "total": 0}
            resp = client.get(
                "/api/v1/agents/templates?category=it", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "seed-it"

    def test_list_pagination_validation(self, client, admin_headers):
        resp = client.get("/api/v1/agents/templates?page=0", headers=admin_headers)
        assert resp.status_code == 422

    def test_list_page_size_max(self, client, admin_headers):
        resp = client.get(
            "/api/v1/agents/templates?page_size=51", headers=admin_headers
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /agents/templates/{template_id} — Get template detail
# ---------------------------------------------------------------------------


class TestGetAgentTemplate:
    """GET /api/v1/agents/templates/{template_id}"""

    def test_get_requires_auth(self, client):
        resp = client.get("/api/v1/agents/templates/seed-hr")
        assert resp.status_code == 401

    def test_get_seed_template(self, client, admin_headers):
        """Should return seed template by id without DB call."""
        resp = client.get("/api/v1/agents/templates/seed-hr", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "seed-hr"
        assert data["name"] == "HR Policy Assistant"
        assert data["is_seed"] is True

    def test_get_db_template(self, client, admin_headers):
        """Should return DB template for non-seed id."""
        with patch(
            "app.modules.agents.routes.get_agent_template_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = {
                "id": "db-agent-001",
                "name": "Custom Agent",
                "description": "A custom agent",
                "system_prompt": "Custom prompt",
                "capabilities": [],
                "status": "published",
                "version": 1,
                "is_seed": False,
                "created_at": "2026-03-07T00:00:00+00:00",
            }
            resp = client.get(
                "/api/v1/agents/templates/db-agent-001", headers=admin_headers
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == "db-agent-001"

    def test_get_returns_404_for_unknown(self, client, admin_headers):
        """Should return 404 for unknown template id."""
        with patch(
            "app.modules.agents.routes.get_agent_template_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None
            resp = client.get(
                "/api/v1/agents/templates/nonexistent", headers=admin_headers
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /agents/templates/{template_id}/deploy — Deploy template
# ---------------------------------------------------------------------------


class TestDeployAgentTemplate:
    """POST /api/v1/agents/templates/{template_id}/deploy"""

    def test_deploy_requires_auth(self, client):
        resp = client.post(
            "/api/v1/agents/templates/seed-hr/deploy",
            json={"name": "My HR Bot", "access_control": "workspace", "kb_ids": []},
        )
        assert resp.status_code == 401

    def test_deploy_requires_tenant_admin(self, client, user_headers):
        resp = client.post(
            "/api/v1/agents/templates/seed-hr/deploy",
            json={"name": "My HR Bot", "access_control": "workspace", "kb_ids": []},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_deploy_seed_template(self, client, admin_headers):
        """Deploy a seed template should create a new agent_cards row."""
        with patch(
            "app.modules.agents.routes.deploy_agent_template_db",
            new_callable=AsyncMock,
        ) as mock_deploy:
            mock_deploy.return_value = {
                "id": "new-agent-001",
                "name": "My HR Bot",
                "status": "published",
            }
            resp = client.post(
                "/api/v1/agents/templates/seed-hr/deploy",
                json={
                    "name": "My HR Bot",
                    "access_control": "workspace",
                    "kb_ids": [],
                },
                headers=admin_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "new-agent-001"
        assert data["name"] == "My HR Bot"
        assert data["status"] == "published"
        # Verify deploy_agent_template_db was called with correct system_prompt from seed
        call_kwargs = mock_deploy.call_args[1]
        assert "HR Policy Assistant" in call_kwargs.get(
            "system_prompt", ""
        ) or "hr_policies" in str(mock_deploy.call_args)

    def test_deploy_db_template(self, client, admin_headers):
        """Deploy a DB template should fetch from DB first then create new row."""
        with (
            patch(
                "app.modules.agents.routes.get_agent_template_db",
                new_callable=AsyncMock,
            ) as mock_get,
            patch(
                "app.modules.agents.routes.deploy_agent_template_db",
                new_callable=AsyncMock,
            ) as mock_deploy,
        ):
            mock_get.return_value = {
                "id": "db-template-001",
                "name": "Custom Template",
                "description": "Custom",
                "system_prompt": "You are custom.",
                "capabilities": [],
                "status": "draft",
                "version": 1,
                "is_seed": False,
            }
            mock_deploy.return_value = {
                "id": "deployed-001",
                "name": "My Custom Agent",
                "status": "published",
            }
            resp = client.post(
                "/api/v1/agents/templates/db-template-001/deploy",
                json={
                    "name": "My Custom Agent",
                    "access_control": "workspace",
                    "kb_ids": [],
                },
                headers=admin_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My Custom Agent"
        assert data["status"] == "published"

    def test_deploy_returns_404_for_unknown_template(self, client, admin_headers):
        """Deploy unknown template should return 404."""
        with patch(
            "app.modules.agents.routes.get_agent_template_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None
            resp = client.post(
                "/api/v1/agents/templates/nonexistent/deploy",
                json={
                    "name": "My Agent",
                    "access_control": "workspace",
                    "kb_ids": [],
                },
                headers=admin_headers,
            )
        assert resp.status_code == 404

    def test_deploy_requires_name(self, client, admin_headers):
        """Deploy without name should return 422."""
        resp = client.post(
            "/api/v1/agents/templates/seed-hr/deploy",
            json={"access_control": "workspace", "kb_ids": []},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_deploy_validates_access_control(self, client, admin_headers):
        """Deploy with invalid access_control should return 422."""
        resp = client.post(
            "/api/v1/agents/templates/seed-hr/deploy",
            json={
                "name": "My Agent",
                "access_control": "invalid_value",
                "kb_ids": [],
            },
            headers=admin_headers,
        )
        assert resp.status_code == 422
