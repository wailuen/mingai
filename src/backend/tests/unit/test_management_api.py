"""
Unit tests for Auth0 Management API client (P3AUTH-021).

Covers:
- Token cache hit (no HTTP call made)
- Token cache miss → fetches from Auth0 → caches result
- Redis unavailable → gracefully degrades (still fetches from Auth0)
- Auth0 returns error → raises RuntimeError with descriptive message
- management_api_request success and failure paths

Patch strategy: get_redis is imported lazily inside the function body via
`from app.core.redis_client import get_redis`, so we patch the source at
`app.core.redis_client.get_redis`.  httpx.AsyncClient is patched at
`app.modules.auth.management_api.httpx.AsyncClient` because httpx is imported
at module level there.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_TOKEN = "eyJfake.token.value"
FAKE_DOMAIN = "test-tenant.jp.auth0.com"
FAKE_CLIENT_ID = "test_client_id"
FAKE_CLIENT_SECRET = "test_client_secret"

_AUTH0_ENV = {
    "AUTH0_DOMAIN": FAKE_DOMAIN,
    "AUTH0_MANAGEMENT_CLIENT_ID": FAKE_CLIENT_ID,
    "AUTH0_MANAGEMENT_CLIENT_SECRET": FAKE_CLIENT_SECRET,
}


def _make_token_response(token: str = FAKE_TOKEN, expires_in: int = 86400) -> dict:
    return {"access_token": token, "token_type": "Bearer", "expires_in": expires_in}


def _make_mock_http_client(
    status_code: int = 200,
    json_body: dict | None = None,
    text_body: str = "",
):
    """Build a reusable mock httpx.AsyncClient context manager."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.text = text_body
    if json_body is not None:
        mock_response.json = MagicMock(return_value=json_body)
        mock_response.content = b"body"
    else:
        mock_response.content = b""

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.request = AsyncMock(return_value=mock_response)
    return mock_client


# ---------------------------------------------------------------------------
# get_management_api_token — cache hit
# ---------------------------------------------------------------------------


class TestGetManagementApiTokenCacheHit:
    """When Redis has a cached token, no HTTP request is made."""

    @pytest.mark.asyncio
    async def test_returns_cached_token_without_http_call(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=FAKE_TOKEN)

        mock_http_client = _make_mock_http_client(
            status_code=200, json_body=_make_token_response()
        )

        with (
            patch.dict("os.environ", _AUTH0_ENV),
            patch("app.core.redis_client.get_redis", return_value=mock_redis),
            patch(
                "app.modules.auth.management_api.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            from app.modules.auth.management_api import get_management_api_token

            result = await get_management_api_token()

        assert result == FAKE_TOKEN
        # No HTTP post call should have been made
        mock_http_client.post.assert_not_called()


# ---------------------------------------------------------------------------
# get_management_api_token — cache miss
# ---------------------------------------------------------------------------


class TestGetManagementApiTokenCacheMiss:
    """When Redis has no cached token, fetch from Auth0 and cache the result."""

    @pytest.mark.asyncio
    async def test_fetches_token_and_caches_on_miss(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        mock_http_client = _make_mock_http_client(
            status_code=200,
            json_body=_make_token_response(expires_in=3600),
        )

        with (
            patch.dict("os.environ", _AUTH0_ENV),
            patch("app.core.redis_client.get_redis", return_value=mock_redis),
            patch(
                "app.modules.auth.management_api.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            from app.modules.auth.management_api import get_management_api_token

            result = await get_management_api_token()

        assert result == FAKE_TOKEN

        # Token should have been cached with TTL = expires_in - 60 = 3540
        mock_redis.setex.assert_called_once()
        ttl_arg = mock_redis.setex.call_args[0][1]
        token_arg = mock_redis.setex.call_args[0][2]
        assert ttl_arg == 3540
        assert token_arg == FAKE_TOKEN

    @pytest.mark.asyncio
    async def test_posts_correct_payload_to_auth0(self):
        """Verify the client_credentials payload sent to Auth0."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        mock_http_client = _make_mock_http_client(
            status_code=200, json_body=_make_token_response()
        )

        with (
            patch.dict("os.environ", _AUTH0_ENV),
            patch("app.core.redis_client.get_redis", return_value=mock_redis),
            patch(
                "app.modules.auth.management_api.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            from app.modules.auth.management_api import get_management_api_token

            await get_management_api_token()

        post_call = mock_http_client.post.call_args
        posted_json = post_call.kwargs["json"]
        assert posted_json["grant_type"] == "client_credentials"
        assert posted_json["client_id"] == FAKE_CLIENT_ID
        assert posted_json["client_secret"] == FAKE_CLIENT_SECRET
        assert posted_json["audience"] == f"https://{FAKE_DOMAIN}/api/v2/"

    @pytest.mark.asyncio
    async def test_cache_ttl_is_expires_in_minus_60(self):
        """TTL uses expires_in - 60 second guard window."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        mock_http_client = _make_mock_http_client(
            status_code=200,
            json_body=_make_token_response(expires_in=7200),
        )

        with (
            patch.dict("os.environ", _AUTH0_ENV),
            patch("app.core.redis_client.get_redis", return_value=mock_redis),
            patch(
                "app.modules.auth.management_api.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            from app.modules.auth.management_api import get_management_api_token

            await get_management_api_token()

        ttl_arg = mock_redis.setex.call_args[0][1]
        assert ttl_arg == 7140  # 7200 - 60


# ---------------------------------------------------------------------------
# get_management_api_token — Redis unavailable
# ---------------------------------------------------------------------------


class TestGetManagementApiTokenRedisUnavailable:
    """When Redis is unavailable, gracefully degrade and still fetch the token."""

    @pytest.mark.asyncio
    async def test_redis_get_failure_falls_through_to_auth0(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
        mock_redis.setex = AsyncMock(side_effect=ConnectionError("Redis unavailable"))

        mock_http_client = _make_mock_http_client(
            status_code=200, json_body=_make_token_response()
        )

        with (
            patch.dict("os.environ", _AUTH0_ENV),
            patch("app.core.redis_client.get_redis", return_value=mock_redis),
            patch(
                "app.modules.auth.management_api.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            from app.modules.auth.management_api import get_management_api_token

            # Must not raise — Redis failure is gracefully handled
            result = await get_management_api_token()

        assert result == FAKE_TOKEN

    @pytest.mark.asyncio
    async def test_redis_setex_failure_still_returns_token(self):
        """Even if caching the token fails, the fetched token is returned."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # cache miss
        mock_redis.setex = AsyncMock(side_effect=ConnectionError("Redis write failed"))

        mock_http_client = _make_mock_http_client(
            status_code=200, json_body=_make_token_response()
        )

        with (
            patch.dict("os.environ", _AUTH0_ENV),
            patch("app.core.redis_client.get_redis", return_value=mock_redis),
            patch(
                "app.modules.auth.management_api.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            from app.modules.auth.management_api import get_management_api_token

            result = await get_management_api_token()

        assert result == FAKE_TOKEN

    @pytest.mark.asyncio
    async def test_get_redis_raises_still_fetches_token(self):
        """If get_redis() itself raises (e.g. REDIS_URL not set), still fetch token."""
        mock_http_client = _make_mock_http_client(
            status_code=200, json_body=_make_token_response()
        )

        with (
            patch.dict("os.environ", _AUTH0_ENV),
            patch(
                "app.core.redis_client.get_redis",
                side_effect=ValueError("REDIS_URL is not set"),
            ),
            patch(
                "app.modules.auth.management_api.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            from app.modules.auth.management_api import get_management_api_token

            result = await get_management_api_token()

        assert result == FAKE_TOKEN


# ---------------------------------------------------------------------------
# get_management_api_token — Auth0 returns error
# ---------------------------------------------------------------------------


class TestGetManagementApiTokenAuth0Error:
    """When Auth0 returns a non-200, raise RuntimeError with context."""

    @pytest.mark.asyncio
    async def test_auth0_401_raises_runtime_error(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        mock_http_client = _make_mock_http_client(
            status_code=401, text_body="Unauthorized"
        )

        with (
            patch.dict("os.environ", _AUTH0_ENV),
            patch("app.core.redis_client.get_redis", return_value=mock_redis),
            patch(
                "app.modules.auth.management_api.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            from app.modules.auth.management_api import get_management_api_token

            with pytest.raises(RuntimeError) as exc_info:
                await get_management_api_token()

        assert "401" in str(exc_info.value)
        assert "Unauthorized" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_auth0_500_raises_runtime_error(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        mock_http_client = _make_mock_http_client(
            status_code=500, text_body="Internal Server Error"
        )

        with (
            patch.dict("os.environ", _AUTH0_ENV),
            patch("app.core.redis_client.get_redis", return_value=mock_redis),
            patch(
                "app.modules.auth.management_api.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            from app.modules.auth.management_api import get_management_api_token

            with pytest.raises(RuntimeError) as exc_info:
                await get_management_api_token()

        assert "500" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_error_message_includes_response_body(self):
        """Error message includes a snippet of the Auth0 response body."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        mock_http_client = _make_mock_http_client(
            status_code=403,
            text_body='{"error":"access_denied","description":"insufficient scope"}',
        )

        with (
            patch.dict("os.environ", _AUTH0_ENV),
            patch("app.core.redis_client.get_redis", return_value=mock_redis),
            patch(
                "app.modules.auth.management_api.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            from app.modules.auth.management_api import get_management_api_token

            with pytest.raises(RuntimeError) as exc_info:
                await get_management_api_token()

        error_message = str(exc_info.value)
        assert "403" in error_message
        assert "access_denied" in error_message


# ---------------------------------------------------------------------------
# get_management_api_token — missing env vars
# ---------------------------------------------------------------------------


class TestGetManagementApiTokenMissingEnv:
    """Missing required env vars raise RuntimeError immediately."""

    @pytest.mark.asyncio
    async def test_missing_auth0_domain_raises(self):
        env = {**_AUTH0_ENV, "AUTH0_DOMAIN": ""}
        with patch.dict("os.environ", env):
            from app.modules.auth.management_api import get_management_api_token

            with pytest.raises(RuntimeError, match="AUTH0_DOMAIN"):
                await get_management_api_token()

    @pytest.mark.asyncio
    async def test_missing_client_id_raises(self):
        env = {**_AUTH0_ENV, "AUTH0_MANAGEMENT_CLIENT_ID": ""}
        with patch.dict("os.environ", env):
            from app.modules.auth.management_api import get_management_api_token

            with pytest.raises(RuntimeError, match="AUTH0_MANAGEMENT_CLIENT_ID"):
                await get_management_api_token()

    @pytest.mark.asyncio
    async def test_missing_client_secret_raises(self):
        env = {**_AUTH0_ENV, "AUTH0_MANAGEMENT_CLIENT_SECRET": ""}
        with patch.dict("os.environ", env):
            from app.modules.auth.management_api import get_management_api_token

            with pytest.raises(RuntimeError, match="AUTH0_MANAGEMENT_CLIENT_SECRET"):
                await get_management_api_token()


# ---------------------------------------------------------------------------
# management_api_request
# ---------------------------------------------------------------------------


class TestManagementApiRequest:
    """management_api_request wraps get_management_api_token + HTTP call."""

    @pytest.mark.asyncio
    async def test_successful_get_request(self):
        response_body = {"user_id": "auth0|123", "email": "user@example.com"}

        mock_http_client = _make_mock_http_client(
            status_code=200, json_body=response_body
        )

        with (
            patch.dict("os.environ", _AUTH0_ENV),
            patch(
                "app.modules.auth.management_api.get_management_api_token",
                new_callable=AsyncMock,
                return_value=FAKE_TOKEN,
            ),
            patch(
                "app.modules.auth.management_api.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            from app.modules.auth.management_api import management_api_request

            result = await management_api_request("GET", "users/auth0|123")

        assert result == response_body

        request_call = mock_http_client.request.call_args
        assert request_call.kwargs["method"] == "GET"
        assert "users/auth0|123" in request_call.kwargs["url"]
        assert request_call.kwargs["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"

    @pytest.mark.asyncio
    async def test_non_200_raises_runtime_error(self):
        mock_http_client = _make_mock_http_client(
            status_code=404, text_body="Not found"
        )

        with (
            patch.dict("os.environ", _AUTH0_ENV),
            patch(
                "app.modules.auth.management_api.get_management_api_token",
                new_callable=AsyncMock,
                return_value=FAKE_TOKEN,
            ),
            patch(
                "app.modules.auth.management_api.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            from app.modules.auth.management_api import management_api_request

            with pytest.raises(RuntimeError) as exc_info:
                await management_api_request("GET", "users/nonexistent")

        assert "404" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_204_no_content_returns_empty_dict(self):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.content = b""

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.request = AsyncMock(return_value=mock_response)

        with (
            patch.dict("os.environ", _AUTH0_ENV),
            patch(
                "app.modules.auth.management_api.get_management_api_token",
                new_callable=AsyncMock,
                return_value=FAKE_TOKEN,
            ),
            patch(
                "app.modules.auth.management_api.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            from app.modules.auth.management_api import management_api_request

            result = await management_api_request("DELETE", "connections/con_xxx")

        assert result == {}

    @pytest.mark.asyncio
    async def test_post_request_sends_body(self):
        """POST requests include the body as JSON."""
        response_body = {"id": "new-resource"}
        mock_http_client = _make_mock_http_client(
            status_code=201, json_body=response_body
        )

        request_body = {"name": "My Connection", "strategy": "samlp"}

        with (
            patch.dict("os.environ", _AUTH0_ENV),
            patch(
                "app.modules.auth.management_api.get_management_api_token",
                new_callable=AsyncMock,
                return_value=FAKE_TOKEN,
            ),
            patch(
                "app.modules.auth.management_api.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            from app.modules.auth.management_api import management_api_request

            result = await management_api_request(
                "POST", "connections", body=request_body
            )

        assert result == response_body
        request_call = mock_http_client.request.call_args
        assert request_call.kwargs["json"] == request_body
        assert request_call.kwargs["method"] == "POST"
