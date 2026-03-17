"""
Auth0 Management API client (P3AUTH-021).

Handles automatic token refresh via Client Credentials grant.
Token cached in Redis: key = "mingai:platform:auth0_mgmt_token:token"
TTL = expires_in - 60 seconds (guards against clock skew at token boundary).

Usage::

    token = await get_management_api_token()
    result = await management_api_request("GET", "users/auth0|xxx")
"""
import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

# Redis key for the cached management API token.
# Uses "platform" as the tenant_id segment since this is platform-scoped,
# not tenant-scoped. build_redis_key validates that no segment contains colons.
_MGMT_TOKEN_REDIS_KEY = "mingai:platform:auth0_mgmt_token:token"


async def get_management_api_token() -> str:
    """
    Return a valid Auth0 Management API token.

    Lookup order:
    1. Redis cache (key: mingai:platform:auth0_mgmt_token:token)
    2. Auth0 Client Credentials grant (POST /oauth/token)

    Redis is treated as best-effort: if unavailable the function still returns
    a fresh token fetched from Auth0 (graceful degradation).

    Raises:
        RuntimeError: If AUTH0_DOMAIN, AUTH0_MANAGEMENT_CLIENT_ID, or
                      AUTH0_MANAGEMENT_CLIENT_SECRET are not set.
        httpx.HTTPStatusError: If the Auth0 token request fails.
    """
    auth0_domain = os.environ.get("AUTH0_DOMAIN", "")
    client_id = os.environ.get("AUTH0_MANAGEMENT_CLIENT_ID", "")
    client_secret = os.environ.get("AUTH0_MANAGEMENT_CLIENT_SECRET", "")

    if not auth0_domain:
        raise RuntimeError(
            "AUTH0_DOMAIN is not set. Configure it in .env before using the "
            "Auth0 Management API."
        )
    if not client_id:
        raise RuntimeError(
            "AUTH0_MANAGEMENT_CLIENT_ID is not set. Configure it in .env "
            "before using the Auth0 Management API."
        )
    if not client_secret:
        raise RuntimeError(
            "AUTH0_MANAGEMENT_CLIENT_SECRET is not set. Configure it in .env "
            "before using the Auth0 Management API."
        )

    # Tier 1: Redis cache — best-effort, never crashes the caller.
    try:
        from app.core.redis_client import get_redis

        redis = get_redis()
        cached = await redis.get(_MGMT_TOKEN_REDIS_KEY)
        if cached:
            logger.debug("auth0_mgmt_token_cache_hit")
            return cached
    except Exception as exc:
        logger.warning(
            "auth0_mgmt_token_redis_get_failed",
            error=str(exc),
        )

    # Tier 2: Fetch from Auth0.
    audience = f"https://{auth0_domain}/api/v2/"
    token_url = f"https://{auth0_domain}/oauth/token"

    async with httpx.AsyncClient(timeout=10.0) as http:
        response = await http.post(
            token_url,
            json={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "audience": audience,
            },
        )

    if response.status_code != 200:
        logger.error(
            "auth0_mgmt_token_fetch_failed",
            status=response.status_code,
            body=response.text[:200],
        )
        raise RuntimeError(
            f"Auth0 Management API token request failed "
            f"(HTTP {response.status_code}): {response.text[:200]}"
        )

    payload = response.json()
    token: str = payload["access_token"]
    expires_in: int = int(payload.get("expires_in", 86400))

    # Cache with TTL = expires_in - 60 to avoid using a token right at
    # the expiry boundary.
    cache_ttl = max(expires_in - 60, 60)

    try:
        from app.core.redis_client import get_redis

        redis = get_redis()
        await redis.setex(_MGMT_TOKEN_REDIS_KEY, cache_ttl, token)
        logger.debug("auth0_mgmt_token_cached", ttl_seconds=cache_ttl)
    except Exception as exc:
        # Redis unavailable — still return the token; next call will re-fetch.
        logger.warning(
            "auth0_mgmt_token_redis_cache_failed",
            error=str(exc),
        )

    logger.info("auth0_mgmt_token_fetched", expires_in=expires_in)
    return token


async def management_api_request(
    method: str,
    path: str,
    body: Any = None,
) -> dict:
    """
    Make an authenticated request to the Auth0 Management API v2.

    Args:
        method:  HTTP method ("GET", "POST", "PATCH", "DELETE").
        path:    API path relative to /api/v2/ (e.g. "users/auth0|xxx").
        body:    Optional JSON-serialisable request body (for POST/PATCH).

    Returns:
        Parsed JSON response body as a dict.

    Raises:
        RuntimeError: If the request fails or returns a non-200 status.
    """
    auth0_domain = os.environ.get("AUTH0_DOMAIN", "")
    if not auth0_domain:
        raise RuntimeError(
            "AUTH0_DOMAIN is not set. Configure it in .env before using the "
            "Auth0 Management API."
        )

    token = await get_management_api_token()
    url = f"https://{auth0_domain}/api/v2/{path}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as http:
        response = await http.request(
            method=method.upper(),
            url=url,
            headers=headers,
            json=body,
        )

    if response.status_code not in (200, 201, 204):
        logger.error(
            "auth0_management_api_request_failed",
            method=method.upper(),
            path=path,
            status=response.status_code,
            body=response.text[:200],
        )
        raise RuntimeError(
            f"Auth0 Management API {method.upper()} {path} failed "
            f"(HTTP {response.status_code}): {response.text[:200]}"
        )

    if response.status_code == 204 or not response.content:
        return {}

    return response.json()
