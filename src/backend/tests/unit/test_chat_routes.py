"""
Unit tests for chat routes (API-007 to API-014).

Tests SSE streaming, feedback, conversations, and issues endpoints.
Tier 1: Fast, isolated, uses mocking for services.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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
def auth_headers():
    return {"Authorization": f"Bearer {_make_token()}"}


@pytest.fixture
def admin_headers():
    return {
        "Authorization": f"Bearer {_make_token(roles=['tenant_admin'], scope='tenant')}"
    }


class TestChatStreamAuth:
    """Authentication requirements for SSE chat endpoint."""

    def test_chat_stream_requires_auth(self, client):
        resp = client.post(
            "/api/v1/chat/stream",
            json={"query": "test", "agent_id": "hr_policy"},
        )
        assert resp.status_code == 401

    def test_chat_stream_rejects_bad_token(self, client):
        resp = client.post(
            "/api/v1/chat/stream",
            json={"query": "test", "agent_id": "hr_policy"},
            headers={"Authorization": "Bearer bad-token"},
        )
        assert resp.status_code == 401


class TestChatStreamValidation:
    """Input validation for SSE chat endpoint."""

    def test_chat_stream_rejects_empty_query(self, client, auth_headers):
        resp = client.post(
            "/api/v1/chat/stream",
            json={"query": "", "agent_id": "hr_policy"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_chat_stream_rejects_query_too_long(self, client, auth_headers):
        resp = client.post(
            "/api/v1/chat/stream",
            json={"query": "x" * 10001, "agent_id": "hr_policy"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_chat_stream_rejects_empty_agent_id(self, client, auth_headers):
        resp = client.post(
            "/api/v1/chat/stream",
            json={"query": "hello", "agent_id": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_chat_stream_rejects_missing_agent_id(self, client, auth_headers):
        resp = client.post(
            "/api/v1/chat/stream",
            json={"query": "hello"},
            headers=auth_headers,
        )
        assert resp.status_code == 422


class TestChatStreamSSE:
    """SSE streaming response format."""

    def test_chat_stream_returns_event_stream(self, client, auth_headers):
        async def mock_stream(**kwargs):
            yield {"type": "token", "content": "Hello"}
            yield {
                "type": "done",
                "conversation_id": "conv-1",
                "message_id": "00000000-0000-0000-0000-000000000001",
            }

        from app.main import app
        from app.core.session import get_async_session

        # TA-022: stream_chat does a DB agent-status check before build_orchestrator.
        # Override the session dependency to avoid hitting a real database.
        mock_agent_row = MagicMock()
        mock_agent_row.__getitem__ = lambda self, key: "active"
        mock_execute_result = MagicMock()
        mock_execute_result.mappings.return_value.first.return_value = mock_agent_row
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_execute_result)

        async def _override_session():
            yield mock_session

        app.dependency_overrides[get_async_session] = _override_session

        with patch("app.modules.chat.routes.build_orchestrator") as mock_build:
            mock_orch = MagicMock()
            mock_orch.stream_response = mock_stream
            mock_build.return_value = mock_orch

            try:
                resp = client.post(
                    "/api/v1/chat/stream",
                    json={"query": "hello", "agent_id": "hr_policy"},
                    headers=auth_headers,
                )
            finally:
                app.dependency_overrides.pop(get_async_session, None)

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

    def test_chat_stream_optional_fields(self, client, auth_headers):
        """conversation_id and active_team_id are optional."""

        async def mock_stream(**kwargs):
            yield {"type": "done", "conversation_id": "c1", "message_id": "m1"}

        from app.main import app
        from app.core.session import get_async_session

        mock_agent_row = MagicMock()
        mock_agent_row.__getitem__ = lambda self, key: "active"
        mock_execute_result = MagicMock()
        mock_execute_result.mappings.return_value.first.return_value = mock_agent_row
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_execute_result)

        async def _override_session():
            yield mock_session

        app.dependency_overrides[get_async_session] = _override_session

        with patch("app.modules.chat.routes.build_orchestrator") as mock_build:
            mock_orch = MagicMock()
            mock_orch.stream_response = mock_stream
            mock_build.return_value = mock_orch

            try:
                resp = client.post(
                    "/api/v1/chat/stream",
                    json={
                        "query": "hello",
                        "agent_id": "finance",
                        "conversation_id": "conv-123",
                        "active_team_id": "team-456",
                    },
                    headers=auth_headers,
                )
            finally:
                app.dependency_overrides.pop(get_async_session, None)

        assert resp.status_code == 200


class TestFeedbackEndpoint:
    """POST /api/v1/chat/feedback tests."""

    def test_feedback_requires_auth(self, client):
        resp = client.post(
            "/api/v1/chat/feedback",
            json={"message_id": "00000000-0000-0000-0000-000000000001", "rating": "up"},
        )
        assert resp.status_code == 401

    def test_feedback_thumbs_up(self, client, auth_headers):
        with patch(
            "app.modules.chat.routes.save_feedback", new_callable=AsyncMock
        ) as mock_save:
            mock_save.return_value = {"id": "fb-1"}
            resp = client.post(
                "/api/v1/chat/feedback",
                json={
                    "message_id": "00000000-0000-0000-0000-000000000001",
                    "rating": "up",
                },
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data

    def test_feedback_thumbs_down_with_comment(self, client, auth_headers):
        with patch(
            "app.modules.chat.routes.save_feedback", new_callable=AsyncMock
        ) as mock_save:
            mock_save.return_value = {"id": "fb-2"}
            resp = client.post(
                "/api/v1/chat/feedback",
                json={
                    "message_id": "00000000-0000-0000-0000-000000000001",
                    "rating": "down",
                    "comment": "Not helpful",
                },
                headers=auth_headers,
            )
        assert resp.status_code == 200

    def test_feedback_rejects_invalid_rating(self, client, auth_headers):
        resp = client.post(
            "/api/v1/chat/feedback",
            json={
                "message_id": "00000000-0000-0000-0000-000000000001",
                "rating": "sideways",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_feedback_rejects_missing_message_id(self, client, auth_headers):
        resp = client.post(
            "/api/v1/chat/feedback",
            json={"rating": "up"},
            headers=auth_headers,
        )
        assert resp.status_code == 422


class TestConversationsList:
    """GET /api/v1/conversations tests."""

    def test_list_conversations_requires_auth(self, client):
        resp = client.get("/api/v1/conversations")
        assert resp.status_code == 401

    def test_list_conversations_returns_paginated(self, client, auth_headers):
        with patch(
            "app.modules.chat.routes.list_conversations", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = {
                "items": [],
                "total": 0,
                "page": 1,
                "page_size": 20,
            }
            resp = client.get("/api/v1/conversations", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_list_conversations_pagination_params(self, client, auth_headers):
        with patch(
            "app.modules.chat.routes.list_conversations", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = {
                "items": [],
                "total": 0,
                "page": 2,
                "page_size": 10,
            }
            resp = client.get(
                "/api/v1/conversations?page=2&page_size=10", headers=auth_headers
            )
        assert resp.status_code == 200

    def test_list_conversations_rejects_page_zero(self, client, auth_headers):
        resp = client.get("/api/v1/conversations?page=0", headers=auth_headers)
        assert resp.status_code == 422

    def test_list_conversations_rejects_page_size_over_100(self, client, auth_headers):
        resp = client.get("/api/v1/conversations?page_size=101", headers=auth_headers)
        assert resp.status_code == 422


class TestConversationDetail:
    """GET /api/v1/conversations/{id} and DELETE tests."""

    def test_get_conversation_requires_auth(self, client):
        resp = client.get("/api/v1/conversations/conv-1")
        assert resp.status_code == 401

    def test_get_conversation_returns_data(self, client, auth_headers):
        with patch(
            "app.modules.chat.routes.get_conversation", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "id": "conv-1",
                "title": "Test conversation",
                "created_at": "2026-01-01T00:00:00Z",
                "messages": [],
            }
            resp = client.get("/api/v1/conversations/conv-1", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == "conv-1"

    def test_get_conversation_returns_404_if_not_found(self, client, auth_headers):
        with patch(
            "app.modules.chat.routes.get_conversation", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None
            resp = client.get("/api/v1/conversations/nonexistent", headers=auth_headers)
        assert resp.status_code == 404

    def test_delete_conversation_requires_auth(self, client):
        resp = client.delete("/api/v1/conversations/conv-1")
        assert resp.status_code == 401

    def test_delete_conversation_returns_204(self, client, auth_headers):
        with patch(
            "app.modules.chat.routes.delete_conversation", new_callable=AsyncMock
        ) as mock_del:
            mock_del.return_value = True
            resp = client.delete("/api/v1/conversations/conv-1", headers=auth_headers)
        assert resp.status_code == 204

    def test_delete_conversation_returns_404_if_not_found(self, client, auth_headers):
        with patch(
            "app.modules.chat.routes.delete_conversation", new_callable=AsyncMock
        ) as mock_del:
            mock_del.return_value = False
            resp = client.delete(
                "/api/v1/conversations/nonexistent", headers=auth_headers
            )
        assert resp.status_code == 404


class TestIssuesEndpoints:
    """POST /api/v1/issues and GET /api/v1/issues/{id} tests."""

    def test_submit_issue_requires_auth(self, client):
        resp = client.post(
            "/api/v1/issues",
            json={
                "title": "Problem",
                "description": "Details",
                "message_id": "00000000-0000-0000-0000-000000000001",
            },
        )
        assert resp.status_code == 401

    def test_submit_issue_returns_created(self, client, auth_headers):
        with patch(
            "app.modules.issues.routes.create_issue_db", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = {
                "id": "issue-1",
                "title": "Problem",
                "description": "Details",
                "status": "open",
            }
            resp = client.post(
                "/api/v1/issues",
                json={
                    "title": "Problem",
                    "description": "Details",
                },
                headers=auth_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data

    def test_submit_issue_rejects_empty_title(self, client, auth_headers):
        resp = client.post(
            "/api/v1/issues",
            json={
                "title": "",
                "description": "Details",
                "message_id": "00000000-0000-0000-0000-000000000001",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_get_issue_requires_auth(self, client):
        resp = client.get("/api/v1/issues/issue-1")
        assert resp.status_code == 401

    def test_get_issue_returns_data(self, client, auth_headers):
        with patch(
            "app.modules.issues.routes.get_issue_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "id": "issue-1",
                "reporter_id": TEST_USER_ID,
                "status": "open",
                "title": "Problem",
            }
            resp = client.get("/api/v1/issues/issue-1", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == "issue-1"

    def test_get_issue_returns_404_if_not_found(self, client, auth_headers):
        with patch(
            "app.modules.issues.routes.get_issue_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None
            resp = client.get("/api/v1/issues/nonexistent", headers=auth_headers)
        assert resp.status_code == 404
