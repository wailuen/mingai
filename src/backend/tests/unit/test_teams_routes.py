"""
Unit tests for teams routes (API-051 to API-060).

Tests team CRUD, member management, and team memory endpoints.
Tier 1: Fast, isolated, uses mocking.
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
    roles: list[str] | None = None,
    scope: str = "tenant",
) -> str:
    if roles is None:
        roles = ["end_user"]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": TEST_TENANT_ID,
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
def user_headers():
    return {"Authorization": f"Bearer {_make_token()}"}


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {_make_token(roles=['tenant_admin'])}"}


class TestListTeams:
    """GET /api/v1/teams"""

    def test_list_teams_requires_auth(self, client):
        resp = client.get("/api/v1/teams")
        assert resp.status_code == 401

    def test_list_teams_returns_list(self, client, user_headers):
        with patch(
            "app.modules.teams.routes.list_teams_db", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = []
            resp = client.get("/api/v1/teams", headers=user_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestCreateTeam:
    """POST /api/v1/teams - tenant admin only."""

    def test_create_team_requires_auth(self, client):
        resp = client.post("/api/v1/teams", json={"name": "Finance Team"})
        assert resp.status_code == 401

    def test_create_team_requires_tenant_admin(self, client, user_headers):
        resp = client.post(
            "/api/v1/teams",
            json={"name": "Finance Team"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_create_team_returns_created(self, client, admin_headers):
        with patch(
            "app.modules.teams.routes.create_team_db", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = {"id": "team-1", "name": "Finance Team"}
            resp = client.post(
                "/api/v1/teams",
                json={"name": "Finance Team"},
                headers=admin_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data

    def test_create_team_rejects_empty_name(self, client, admin_headers):
        resp = client.post(
            "/api/v1/teams",
            json={"name": ""},
            headers=admin_headers,
        )
        assert resp.status_code == 422


class TestGetTeam:
    """GET /api/v1/teams/{id}"""

    def test_get_team_requires_auth(self, client):
        resp = client.get("/api/v1/teams/team-1")
        assert resp.status_code == 401

    def test_get_team_returns_data(self, client, user_headers):
        with patch(
            "app.modules.teams.routes.get_team_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "id": "team-1",
                "name": "Finance Team",
                "member_count": 5,
            }
            resp = client.get("/api/v1/teams/team-1", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == "team-1"

    def test_get_team_returns_404(self, client, user_headers):
        with patch(
            "app.modules.teams.routes.get_team_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None
            resp = client.get("/api/v1/teams/nonexistent", headers=user_headers)
        assert resp.status_code == 404


class TestUpdateTeam:
    """PATCH /api/v1/teams/{id}"""

    def test_update_team_requires_tenant_admin(self, client, user_headers):
        resp = client.patch(
            "/api/v1/teams/team-1",
            json={"name": "Updated Team"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_update_team_returns_updated(self, client, admin_headers):
        with patch(
            "app.modules.teams.routes.update_team_db", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = {"id": "team-1", "name": "Updated Team"}
            resp = client.patch(
                "/api/v1/teams/team-1",
                json={"name": "Updated Team"},
                headers=admin_headers,
            )
        assert resp.status_code == 200


class TestDeleteTeam:
    """DELETE /api/v1/teams/{id}"""

    def test_delete_team_requires_tenant_admin(self, client, user_headers):
        resp = client.delete("/api/v1/teams/team-1", headers=user_headers)
        assert resp.status_code == 403

    def test_delete_team_returns_204(self, client, admin_headers):
        with patch(
            "app.modules.teams.routes.delete_team_db", new_callable=AsyncMock
        ) as mock_del:
            mock_del.return_value = True
            resp = client.delete("/api/v1/teams/team-1", headers=admin_headers)
        assert resp.status_code == 204

    def test_delete_team_returns_404(self, client, admin_headers):
        with patch(
            "app.modules.teams.routes.delete_team_db", new_callable=AsyncMock
        ) as mock_del:
            mock_del.return_value = False
            resp = client.delete("/api/v1/teams/nonexistent", headers=admin_headers)
        assert resp.status_code == 404


class TestTeamMembers:
    """POST and DELETE /api/v1/teams/{id}/members/{user_id}"""

    def test_add_member_requires_auth(self, client):
        resp = client.post("/api/v1/teams/team-1/members", json={"user_id": "user-002"})
        assert resp.status_code == 401

    def test_add_member_requires_tenant_admin(self, client, user_headers):
        resp = client.post(
            "/api/v1/teams/team-1/members",
            json={"user_id": "user-002"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_add_member_returns_200(self, client, admin_headers):
        with patch(
            "app.modules.teams.routes.add_team_member_db", new_callable=AsyncMock
        ) as mock_add:
            mock_add.return_value = {"team_id": "team-1", "user_id": "user-002"}
            resp = client.post(
                "/api/v1/teams/team-1/members",
                json={"user_id": "user-002"},
                headers=admin_headers,
            )
        assert resp.status_code == 200

    def test_remove_member_requires_tenant_admin(self, client, user_headers):
        resp = client.delete(
            "/api/v1/teams/team-1/members/user-002",
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_remove_member_returns_204(self, client, admin_headers):
        with patch(
            "app.modules.teams.routes.remove_team_member_db", new_callable=AsyncMock
        ) as mock_remove:
            mock_remove.return_value = True
            resp = client.delete(
                "/api/v1/teams/team-1/members/user-002",
                headers=admin_headers,
            )
        assert resp.status_code == 204


class TestTeamMemory:
    """GET /api/v1/teams/{id}/memory"""

    def test_get_team_memory_requires_auth(self, client):
        resp = client.get("/api/v1/teams/team-1/memory")
        assert resp.status_code == 401

    def test_get_team_memory_returns_data(self, client, user_headers):
        with patch(
            "app.modules.teams.routes.get_team_memory_data", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "team_id": "team-1",
                "topics": ["quarterly review", "budget"],
                "recent_queries": [],
            }
            resp = client.get("/api/v1/teams/team-1/memory", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "team_id" in data
