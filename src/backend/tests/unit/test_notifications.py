"""
Unit tests for notification SSE stream (API-012).

Tests publisher logic, notification schema, and SSE endpoint auth.
Tier 1: Fast, isolated, uses mocking for Redis.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

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


class TestPublishNotification:
    """Test publish_notification helper publishes to correct Redis channel."""

    @pytest.mark.asyncio
    async def test_publish_notification_publishes_to_correct_channel(self):
        """publish_notification must PUBLISH to mingai:{tenant_id}:notifications:{user_id}."""
        mock_redis = AsyncMock()

        from app.modules.notifications.publisher import publish_notification

        await publish_notification(
            user_id="user-42",
            tenant_id="tenant-abc",
            notification_type="document_ready",
            title="Doc processed",
            body="Your document has been indexed.",
            redis=mock_redis,
        )

        expected_channel = "mingai:tenant-abc:notifications:user-42"
        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == expected_channel

        # Verify the published data is valid JSON
        published_json = call_args[0][1]
        data = json.loads(published_json)
        assert data["type"] == "document_ready"
        assert data["title"] == "Doc processed"
        assert data["body"] == "Your document has been indexed."

    @pytest.mark.asyncio
    async def test_notification_has_required_fields(self):
        """Published notification must include id, type, title, body, read, created_at."""
        mock_redis = AsyncMock()

        from app.modules.notifications.publisher import publish_notification

        await publish_notification(
            user_id="user-1",
            tenant_id="tenant-1",
            notification_type="alert",
            title="Test Alert",
            body="Something happened",
            redis=mock_redis,
        )

        call_args = mock_redis.publish.call_args
        published_json = call_args[0][1]
        data = json.loads(published_json)

        # All required fields must be present
        assert "id" in data, "Notification must have 'id' field"
        assert "type" in data, "Notification must have 'type' field"
        assert "title" in data, "Notification must have 'title' field"
        assert "body" in data, "Notification must have 'body' field"
        assert "read" in data, "Notification must have 'read' field"
        assert "created_at" in data, "Notification must have 'created_at' field"

        # id must be a valid UUID
        UUID(data["id"])  # Raises ValueError if invalid

        # read must default to False
        assert data["read"] is False

        # created_at must be ISO-8601 parseable
        datetime.fromisoformat(data["created_at"])

    @pytest.mark.asyncio
    async def test_publish_notification_with_link(self):
        """When link is provided, it must appear in the published payload."""
        mock_redis = AsyncMock()

        from app.modules.notifications.publisher import publish_notification

        await publish_notification(
            user_id="user-1",
            tenant_id="tenant-1",
            notification_type="nav",
            title="Go here",
            body="Check this out",
            link="/documents/123",
            redis=mock_redis,
        )

        call_args = mock_redis.publish.call_args
        data = json.loads(call_args[0][1])
        assert data["link"] == "/documents/123"

    @pytest.mark.asyncio
    async def test_publish_notification_link_defaults_to_null(self):
        """When link is not provided, it must be null in the payload."""
        mock_redis = AsyncMock()

        from app.modules.notifications.publisher import publish_notification

        await publish_notification(
            user_id="user-1",
            tenant_id="tenant-1",
            notification_type="info",
            title="Heads up",
            body="FYI",
            redis=mock_redis,
        )

        call_args = mock_redis.publish.call_args
        data = json.loads(call_args[0][1])
        assert data["link"] is None

    @pytest.mark.asyncio
    async def test_publish_notification_uses_build_redis_key(self):
        """Channel must be built using build_redis_key for namespace safety."""
        mock_redis = AsyncMock()

        from app.modules.notifications.publisher import publish_notification

        # Colon in tenant_id must be rejected by build_redis_key
        with pytest.raises(ValueError, match="invalid characters"):
            await publish_notification(
                user_id="user-1",
                tenant_id="tenant:evil",
                notification_type="info",
                title="Test",
                body="Test",
                redis=mock_redis,
            )


class TestSSEEndpointAuth:
    """Test that SSE stream endpoint requires authentication."""

    def test_sse_endpoint_requires_auth(self, client):
        """GET /api/v1/notifications/stream without token must return 401."""
        resp = client.get("/api/v1/notifications/stream")
        assert resp.status_code == 401

    def test_sse_endpoint_rejects_invalid_token(self, client):
        """GET /api/v1/notifications/stream with bad token must return 401."""
        resp = client.get(
            "/api/v1/notifications/stream",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401

    def test_sse_endpoint_returns_event_stream_content_type(self, client, user_headers):
        """Successful SSE connection must have text/event-stream content type."""
        # Mock Redis pubsub to avoid real connection
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()
        # Return None to trigger keepalive, then raise CancelledError to end stream
        call_count = 0

        async def _get_message(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise GeneratorExit()
            return None

        mock_pubsub.get_message = _get_message

        mock_redis = AsyncMock()
        mock_redis.pubsub.return_value = mock_pubsub

        with patch(
            "app.modules.notifications.routes.get_redis", return_value=mock_redis
        ):
            # TestClient uses synchronous requests; streaming response returns headers
            with client.stream(
                "GET", "/api/v1/notifications/stream", headers=user_headers
            ) as resp:
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers.get("content-type", "")
                assert resp.headers.get("cache-control") == "no-cache"
                assert resp.headers.get("x-accel-buffering") == "no"

    def test_sse_endpoint_subscribes_to_correct_channel(self, client, user_headers):
        """SSE must subscribe to mingai:{tenant_id}:notifications:{user_id}."""
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()

        call_count = 0

        async def _get_message(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise GeneratorExit()
            return None

        mock_pubsub.get_message = _get_message

        mock_redis = AsyncMock()
        mock_redis.pubsub.return_value = mock_pubsub

        expected_channel = f"mingai:{TEST_TENANT_ID}:notifications:{TEST_USER_ID}"

        with patch(
            "app.modules.notifications.routes.get_redis", return_value=mock_redis
        ):
            with client.stream(
                "GET", "/api/v1/notifications/stream", headers=user_headers
            ) as resp:
                assert resp.status_code == 200
                # Assert inside context while connection is still open to avoid
                # timing race between async generator teardown and mock inspection
                mock_pubsub.subscribe.assert_called_once_with(expected_channel)
