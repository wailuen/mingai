"""
Unit tests for team membership operations (TEST-062).

Tests add member, remove member, list members, and authorization guards
via the teams routes API.

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
TEST_MEMBER_ID = "user-002"
TEST_TEAM_ID = "team-001"


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
def admin_headers():
    return {"Authorization": f"Bearer {_make_token(roles=['tenant_admin'])}"}


@pytest.fixture
def user_headers():
    return {"Authorization": f"Bearer {_make_token()}"}


# ---------------------------------------------------------------------------
# Add member — authorization
# ---------------------------------------------------------------------------


class TestAddMemberAuthorization:
    """POST /api/v1/teams/{id}/members — authorization checks."""

    def test_add_member_succeeds_for_tenant_admin(self, client, admin_headers):
        """Tenant admin can add a member to a team."""
        with patch(
            "app.modules.teams.routes.add_team_member_db",
            new_callable=AsyncMock,
        ) as mock_add:
            mock_add.return_value = {
                "team_id": TEST_TEAM_ID,
                "user_id": TEST_MEMBER_ID,
            }
            resp = client.post(
                f"/api/v1/teams/{TEST_TEAM_ID}/members",
                json={"user_id": TEST_MEMBER_ID},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["team_id"] == TEST_TEAM_ID
        assert data["user_id"] == TEST_MEMBER_ID

    def test_add_member_fails_403_for_end_user(self, client, user_headers):
        """Regular end_user cannot add members to a team (403)."""
        resp = client.post(
            f"/api/v1/teams/{TEST_TEAM_ID}/members",
            json={"user_id": TEST_MEMBER_ID},
            headers=user_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Remove member — authorization
# ---------------------------------------------------------------------------


class TestRemoveMemberAuthorization:
    """DELETE /api/v1/teams/{id}/members/{uid} — authorization checks."""

    def test_remove_member_succeeds_for_tenant_admin(self, client, admin_headers):
        """Tenant admin can remove a member from a team."""
        with patch(
            "app.modules.teams.routes.remove_team_member_db",
            new_callable=AsyncMock,
        ) as mock_remove:
            mock_remove.return_value = True
            resp = client.delete(
                f"/api/v1/teams/{TEST_TEAM_ID}/members/{TEST_MEMBER_ID}",
                headers=admin_headers,
            )
        assert resp.status_code == 204

    def test_remove_member_fails_403_for_end_user(self, client, user_headers):
        """Regular end_user cannot remove members from a team (403)."""
        resp = client.delete(
            f"/api/v1/teams/{TEST_TEAM_ID}/members/{TEST_MEMBER_ID}",
            headers=user_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# List teams — returns team data
# ---------------------------------------------------------------------------


class TestListTeamMembers:
    """GET /api/v1/teams — listing teams returns member counts."""

    def test_list_teams_returns_member_counts(self, client, admin_headers):
        """List teams returns data with member_count for each team."""
        with patch(
            "app.modules.teams.routes.list_teams_db",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = [
                {
                    "id": TEST_TEAM_ID,
                    "name": "Finance Team",
                    "description": "Finance department",
                    "member_count": 3,
                    "created_at": "2026-03-08T00:00:00+00:00",
                },
            ]
            resp = client.get("/api/v1/teams", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["member_count"] == 3


# ---------------------------------------------------------------------------
# Edge cases — idempotency, 404s
# ---------------------------------------------------------------------------


class TestAddMemberIdempotent:
    """POST /api/v1/teams/{id}/members — adding existing member is idempotent."""

    def test_add_already_member_returns_200(self, client, admin_headers):
        """Adding a user who is already a member returns 200 (ON CONFLICT DO NOTHING)."""
        with patch(
            "app.modules.teams.routes.add_team_member_db",
            new_callable=AsyncMock,
        ) as mock_add:
            # The DB helper uses ON CONFLICT DO NOTHING and returns the membership
            mock_add.return_value = {
                "team_id": TEST_TEAM_ID,
                "user_id": TEST_MEMBER_ID,
            }
            resp = client.post(
                f"/api/v1/teams/{TEST_TEAM_ID}/members",
                json={"user_id": TEST_MEMBER_ID},
                headers=admin_headers,
            )
        assert resp.status_code == 200


class TestAddMemberNonExistentTeam:
    """POST /api/v1/teams/{id}/members — adding to non-existent team returns 404."""

    def test_add_member_to_nonexistent_team_returns_404(self, client, admin_headers):
        """Adding a member to a team that does not exist returns 404."""
        with patch(
            "app.modules.teams.routes.add_team_member_db",
            new_callable=AsyncMock,
        ) as mock_add:
            # The DB helper returns empty dict when team not found
            mock_add.return_value = {}
            resp = client.post(
                "/api/v1/teams/nonexistent-team/members",
                json={"user_id": TEST_MEMBER_ID},
                headers=admin_headers,
            )
        assert resp.status_code == 404


class TestRemoveNonMember:
    """DELETE /api/v1/teams/{id}/members/{uid} — removing non-member returns 404."""

    def test_remove_nonmember_returns_404(self, client, admin_headers):
        """Removing a user who is not a member returns 404."""
        with patch(
            "app.modules.teams.routes.remove_team_member_db",
            new_callable=AsyncMock,
        ) as mock_remove:
            mock_remove.return_value = False
            resp = client.delete(
                f"/api/v1/teams/{TEST_TEAM_ID}/members/nonexistent-user",
                headers=admin_headers,
            )
        assert resp.status_code == 404
