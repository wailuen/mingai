"""
Unit tests for memory routes (API-099 to API-105).

Tests memory notes, profile, and working memory endpoints.
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
    tenant_id: str = TEST_TENANT_ID,
    roles: list[str] | None = None,
) -> str:
    if roles is None:
        roles = ["end_user"]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": "tenant",
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
def auth_headers():
    return {"Authorization": f"Bearer {_make_token()}"}


class TestMemoryNotesList:
    """GET /api/v1/memory/notes"""

    def test_list_notes_requires_auth(self, client):
        resp = client.get("/api/v1/memory/notes")
        assert resp.status_code == 401

    def test_list_notes_returns_list(self, client, auth_headers):
        with patch(
            "app.modules.memory.routes.list_notes_db", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = [
                {
                    "id": "note-1",
                    "content": "Remember to call Bob",
                    "source": "user_directed",
                },
            ]
            resp = client.get("/api/v1/memory/notes", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_notes_empty_returns_empty_list(self, client, auth_headers):
        with patch(
            "app.modules.memory.routes.list_notes_db", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = []
            resp = client.get("/api/v1/memory/notes", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []


class TestCreateMemoryNote:
    """POST /api/v1/memory/notes"""

    def test_create_note_requires_auth(self, client):
        resp = client.post("/api/v1/memory/notes", json={"content": "Test note"})
        assert resp.status_code == 401

    def test_create_note_returns_created(self, client, auth_headers):
        with patch(
            "app.modules.memory.routes.create_note_db", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = {
                "id": "note-1",
                "content": "Test note",
                "source": "user_directed",
            }
            resp = client.post(
                "/api/v1/memory/notes",
                json={"content": "Test note"},
                headers=auth_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["content"] == "Test note"

    def test_create_note_rejects_empty_content(self, client, auth_headers):
        resp = client.post(
            "/api/v1/memory/notes",
            json={"content": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_create_note_enforces_200_char_limit(self, client, auth_headers):
        resp = client.post(
            "/api/v1/memory/notes",
            json={"content": "x" * 201},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_create_note_accepts_exactly_200_chars(self, client, auth_headers):
        with patch(
            "app.modules.memory.routes.create_note_db", new_callable=AsyncMock
        ) as mock_create:
            content = "x" * 200
            mock_create.return_value = {
                "id": "note-1",
                "content": content,
                "source": "user_directed",
            }
            resp = client.post(
                "/api/v1/memory/notes",
                json={"content": content},
                headers=auth_headers,
            )
        assert resp.status_code == 201


class TestDeleteMemoryNote:
    """DELETE /api/v1/memory/notes/{id}"""

    def test_delete_note_requires_auth(self, client):
        valid_id = "00000000-0000-0000-0000-000000000001"
        resp = client.delete(f"/api/v1/memory/notes/{valid_id}")
        assert resp.status_code == 401

    def test_delete_note_returns_204(self, client, auth_headers):
        valid_id = "00000000-0000-0000-0000-000000000001"
        with patch(
            "app.modules.memory.routes.delete_note_db", new_callable=AsyncMock
        ) as mock_del:
            mock_del.return_value = True
            resp = client.delete(
                f"/api/v1/memory/notes/{valid_id}", headers=auth_headers
            )
        assert resp.status_code == 204

    def test_delete_note_returns_404_if_not_found(self, client, auth_headers):
        valid_id = "00000000-0000-0000-0000-000000000002"
        with patch(
            "app.modules.memory.routes.delete_note_db", new_callable=AsyncMock
        ) as mock_del:
            mock_del.return_value = False
            resp = client.delete(
                f"/api/v1/memory/notes/{valid_id}", headers=auth_headers
            )
        assert resp.status_code == 404


class TestGetProfile:
    """GET /api/v1/memory/profile"""

    def test_get_profile_requires_auth(self, client):
        resp = client.get("/api/v1/memory/profile")
        assert resp.status_code == 401

    def test_get_profile_returns_data(self, client, auth_headers):
        with patch(
            "app.modules.memory.routes.get_profile_data", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "user_id": TEST_USER_ID,
                "technical_level": "intermediate",
                "communication_style": "concise",
            }
            resp = client.get("/api/v1/memory/profile", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "user_id" in data

    def test_get_profile_returns_empty_if_no_profile(self, client, auth_headers):
        with patch(
            "app.modules.memory.routes.get_profile_data", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"user_id": TEST_USER_ID}
            resp = client.get("/api/v1/memory/profile", headers=auth_headers)
        assert resp.status_code == 200


class TestWorkingMemory:
    """GET and DELETE /api/v1/memory/working"""

    def test_get_working_memory_requires_auth(self, client):
        resp = client.get("/api/v1/memory/working")
        assert resp.status_code == 401

    def test_get_working_memory_returns_summary(self, client, auth_headers):
        with patch(
            "app.modules.memory.routes.get_working_memory_data", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "user_id": TEST_USER_ID,
                "topics": ["finance", "HR"],
                "recent_queries": ["What is vacation policy?"],
            }
            resp = client.get("/api/v1/memory/working", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "topics" in data

    def test_clear_working_memory_requires_auth(self, client):
        resp = client.delete("/api/v1/memory/working")
        assert resp.status_code == 401

    def test_clear_working_memory_returns_204(self, client, auth_headers):
        with patch(
            "app.modules.memory.routes.clear_working_memory_data",
            new_callable=AsyncMock,
        ) as mock_clear:
            mock_clear.return_value = None
            resp = client.delete("/api/v1/memory/working", headers=auth_headers)
        assert resp.status_code == 204


class TestPrivacyEndpoint:
    """PATCH /api/v1/memory/privacy (API-100)"""

    def test_update_privacy_requires_auth(self, client):
        resp = client.patch(
            "/api/v1/memory/privacy",
            json={"profile_learning_enabled": False, "working_memory_enabled": True},
        )
        assert resp.status_code == 401

    def test_update_privacy_sets_preferences(self, client, auth_headers):
        with patch(
            "app.modules.memory.routes.upsert_privacy_settings",
            new_callable=AsyncMock,
        ) as mock_upsert:
            mock_upsert.return_value = {
                "profile_learning_enabled": False,
                "working_memory_enabled": True,
            }
            resp = client.patch(
                "/api/v1/memory/privacy",
                json={
                    "profile_learning_enabled": False,
                    "working_memory_enabled": True,
                },
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_learning_enabled"] is False
        assert data["working_memory_enabled"] is True
        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args
        assert call_kwargs[1]["user_id"] == TEST_USER_ID
        assert call_kwargs[1]["tenant_id"] == TEST_TENANT_ID
        assert call_kwargs[1]["profile_learning_enabled"] is False
        assert call_kwargs[1]["working_memory_enabled"] is True

    def test_update_privacy_partial_update(self, client, auth_headers):
        """Sending only one field should still work (both fields required by schema)."""
        resp = client.patch(
            "/api/v1/memory/privacy",
            json={"profile_learning_enabled": True},
            headers=auth_headers,
        )
        # Schema requires both fields, so partial should be rejected
        assert resp.status_code == 422


class TestClearAllNotes:
    """DELETE /api/v1/memory/notes (API-103)"""

    def test_clear_all_notes_requires_auth(self, client):
        resp = client.delete("/api/v1/memory/notes")
        assert resp.status_code == 401

    def test_clear_all_notes_returns_204(self, client, auth_headers):
        with patch(
            "app.modules.memory.routes.clear_all_notes_db",
            new_callable=AsyncMock,
        ) as mock_clear:
            mock_clear.return_value = None
            resp = client.delete("/api/v1/memory/notes", headers=auth_headers)
        assert resp.status_code == 204
        mock_clear.assert_called_once_with(
            user_id=TEST_USER_ID,
            tenant_id=TEST_TENANT_ID,
            db=mock_clear.call_args[1]["db"],
        )


class TestExportProfile:
    """GET /api/v1/memory/export (API-104)"""

    def test_export_requires_auth(self, client):
        resp = client.get("/api/v1/memory/export")
        assert resp.status_code == 401

    def test_export_returns_profile_data(self, client, auth_headers):
        with (
            patch(
                "app.modules.memory.routes.get_profile_data",
                new_callable=AsyncMock,
            ) as mock_profile,
            patch(
                "app.modules.memory.routes.list_notes_db",
                new_callable=AsyncMock,
            ) as mock_notes,
            patch(
                "app.modules.memory.routes.get_working_memory_data",
                new_callable=AsyncMock,
            ) as mock_wm,
            patch(
                "app.modules.memory.routes.get_privacy_settings",
                new_callable=AsyncMock,
            ) as mock_privacy,
        ):
            mock_profile.return_value = {
                "user_id": TEST_USER_ID,
                "technical_level": "intermediate",
            }
            mock_notes.return_value = [
                {"id": "n1", "content": "Note 1", "source": "user_directed"}
            ]
            mock_wm.return_value = {
                "user_id": TEST_USER_ID,
                "agent_id": "default",
                "topics": ["hr"],
                "recent_queries": [],
            }
            mock_privacy.return_value = {
                "profile_learning_enabled": True,
                "working_memory_enabled": True,
            }
            resp = client.get("/api/v1/memory/export", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "profile" in data
        assert "notes" in data
        assert "working_memory" in data
        assert "privacy_settings" in data
        assert data["profile"]["user_id"] == TEST_USER_ID
        assert len(data["notes"]) == 1


class TestGDPRClear:
    """DELETE /api/v1/memory/profile (API-105)"""

    def test_gdpr_clear_requires_auth(self, client):
        resp = client.delete("/api/v1/memory/profile")
        assert resp.status_code == 401

    def test_gdpr_clear_returns_204(self, client, auth_headers):
        with (
            patch(
                "app.modules.memory.routes.clear_all_notes_db",
                new_callable=AsyncMock,
            ) as mock_notes,
            patch(
                "app.modules.memory.routes.gdpr_clear_working_memory",
                new_callable=AsyncMock,
            ) as mock_wm,
            patch(
                "app.modules.memory.routes.gdpr_clear_profile",
                new_callable=AsyncMock,
            ) as mock_profile,
            patch(
                "app.modules.memory.routes.gdpr_clear_l1_cache",
                new_callable=AsyncMock,
            ) as mock_l1,
            patch(
                "app.modules.memory.routes.gdpr_reset_privacy_settings",
                new_callable=AsyncMock,
            ) as mock_privacy,
        ):
            resp = client.delete("/api/v1/memory/profile", headers=auth_headers)

        assert resp.status_code == 204
        mock_notes.assert_called_once()
        mock_wm.assert_called_once()
        mock_profile.assert_called_once()
        mock_l1.assert_called_once()
        mock_privacy.assert_called_once()

    def test_gdpr_clear_clears_working_memory(self, client, auth_headers):
        """Verify WorkingMemoryService.clear_memory is called (aihub2 bug fix)."""
        with (
            patch(
                "app.modules.memory.routes.clear_all_notes_db",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.memory.routes.gdpr_clear_working_memory",
                new_callable=AsyncMock,
            ) as mock_wm,
            patch(
                "app.modules.memory.routes.gdpr_clear_profile",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.memory.routes.gdpr_clear_l1_cache",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.memory.routes.gdpr_reset_privacy_settings",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.delete("/api/v1/memory/profile", headers=auth_headers)

        assert resp.status_code == 204
        # Confirm working memory clear was called with correct user/tenant
        call_kwargs = mock_wm.call_args[1]
        assert call_kwargs["user_id"] == TEST_USER_ID
        assert call_kwargs["tenant_id"] == TEST_TENANT_ID
