"""
Unit tests for app/modules/chat/mcp_resolver.py (ATA-032).

Tests cover:
1. Cache hit path: returns cached value, no DB call
2. Cache miss path: queries DB, writes result to cache
3. Non-existent tool (DB miss): None cached, None returned
4. invalidate_mcp_tool_cache: calls redis.delete with correct key
5. Cache key format: uses correct build_redis_key pattern

All Redis and DB dependencies are mocked — no infrastructure required.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_redis(cached_value=None):
    """Return a mock Redis client. cached_value is what redis.get() returns."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=cached_value)
    redis.setex = AsyncMock()
    redis.delete = AsyncMock()
    return redis


def _make_db(row=None):
    """Return a mock AsyncSession whose execute() returns the given row."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = row
    db.execute = AsyncMock(return_value=mock_result)
    return db


_TENANT_ID = "tenant-abc-123"
_TOOL_ID = "tool-uuid-456"
_EXPECTED_CACHE_KEY = f"mingai:{_TENANT_ID}:mcp_tool:{_TOOL_ID}"


# ---------------------------------------------------------------------------
# get_mcp_tool_config — cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_returns_cached_value_and_skips_db():
    """
    When Redis returns a cached value, the function returns it and never
    calls db.execute().
    """
    from app.modules.chat.mcp_resolver import get_mcp_tool_config

    config = {"id": _TOOL_ID, "name": "My Tool", "endpoint": "https://tool.example.com",
               "auth_type": "none", "auth_config": None}
    redis = _make_redis(cached_value=json.dumps(config))
    db = _make_db()

    result = await get_mcp_tool_config(_TOOL_ID, _TENANT_ID, redis, db)

    assert result == config
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_cache_hit_none_sentinel_returns_none_and_skips_db():
    """
    When Redis has json.dumps(None) cached (sentinel for non-existent tool),
    the function returns None and never calls db.execute().
    """
    from app.modules.chat.mcp_resolver import get_mcp_tool_config

    redis = _make_redis(cached_value=json.dumps(None))
    db = _make_db()

    result = await get_mcp_tool_config(_TOOL_ID, _TENANT_ID, redis, db)

    assert result is None
    db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# get_mcp_tool_config — cache miss, DB hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_miss_queries_db_and_caches_result():
    """
    On cache miss, the function queries DB and writes the config dict to
    Redis with TTL=300.
    """
    from app.modules.chat.mcp_resolver import get_mcp_tool_config

    db_row = (_TOOL_ID, "My Tool", "https://tool.example.com", "none", None)
    redis = _make_redis(cached_value=None)
    db = _make_db(row=db_row)

    result = await get_mcp_tool_config(_TOOL_ID, _TENANT_ID, redis, db)

    # Correct dict returned
    assert result is not None
    assert result["id"] == _TOOL_ID
    assert result["name"] == "My Tool"
    assert result["endpoint"] == "https://tool.example.com"
    assert result["auth_type"] == "none"
    assert result["auth_config"] is None

    # DB was queried
    db.execute.assert_called_once()

    # Redis.setex called with correct key and TTL
    redis.setex.assert_called_once()
    call_args = redis.setex.call_args[0]
    assert call_args[0] == _EXPECTED_CACHE_KEY
    assert call_args[1] == 300  # TTL
    assert json.loads(call_args[2]) == result


# ---------------------------------------------------------------------------
# get_mcp_tool_config — cache miss, DB miss (non-existent tool)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_existent_tool_caches_none_sentinel_and_returns_none():
    """
    When the tool is not found in DB (or inactive), None is cached as a JSON
    sentinel and None is returned — prevents repeated DB hits.
    """
    from app.modules.chat.mcp_resolver import get_mcp_tool_config

    redis = _make_redis(cached_value=None)
    db = _make_db(row=None)  # DB returns no row

    result = await get_mcp_tool_config(_TOOL_ID, _TENANT_ID, redis, db)

    assert result is None

    # DB was still queried
    db.execute.assert_called_once()

    # Redis.setex called with json.dumps(None) as value
    redis.setex.assert_called_once()
    call_args = redis.setex.call_args[0]
    assert call_args[0] == _EXPECTED_CACHE_KEY
    assert call_args[1] == 300
    assert json.loads(call_args[2]) is None


# ---------------------------------------------------------------------------
# get_mcp_tool_config — Redis ConnectionError fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_connection_error_falls_through_to_db():
    """
    When Redis raises ConnectionError on get(), the function falls through to
    the DB and returns the config — Redis failure must never break tool resolution.
    """
    import redis as redis_lib
    from app.modules.chat.mcp_resolver import get_mcp_tool_config

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=redis_lib.exceptions.ConnectionError("Redis unreachable"))
    redis.setex = AsyncMock()  # write may also fail; that's handled separately

    db_row = (_TOOL_ID, "My Tool", "https://tool.example.com", "none", None)
    db = _make_db(row=db_row)

    result = await get_mcp_tool_config(_TOOL_ID, _TENANT_ID, redis, db)

    # DB fallback succeeds — result is correct despite Redis being down
    assert result is not None
    assert result["id"] == _TOOL_ID
    db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_redis_connection_error_on_write_still_returns_config():
    """
    When Redis raises ConnectionError on setex() (cache write), the function
    still returns the config from DB — Redis write failure must not suppress result.
    """
    import redis as redis_lib
    from app.modules.chat.mcp_resolver import get_mcp_tool_config

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)  # cache miss
    redis.setex = AsyncMock(
        side_effect=redis_lib.exceptions.ConnectionError("Redis unreachable")
    )

    db_row = (_TOOL_ID, "Slack", "https://slack.example.com", "oauth2", None)
    db = _make_db(row=db_row)

    result = await get_mcp_tool_config(_TOOL_ID, _TENANT_ID, redis, db)

    assert result is not None
    assert result["name"] == "Slack"


# ---------------------------------------------------------------------------
# invalidate_mcp_tool_cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalidate_mcp_tool_cache_calls_redis_delete_with_correct_key():
    """invalidate_mcp_tool_cache deletes the correct namespaced Redis key."""
    from app.modules.chat.mcp_resolver import invalidate_mcp_tool_cache

    redis = AsyncMock()
    redis.delete = AsyncMock()

    await invalidate_mcp_tool_cache(_TENANT_ID, _TOOL_ID, redis)

    redis.delete.assert_called_once_with(_EXPECTED_CACHE_KEY)


# ---------------------------------------------------------------------------
# Cache key format
# ---------------------------------------------------------------------------


def test_cache_key_format_matches_namespace_pattern():
    """
    Verify that build_redis_key(tenant_id, "mcp_tool", tool_id) produces the
    expected key pattern: mingai:{tenant_id}:mcp_tool:{tool_id}.
    """
    from app.core.redis_client import build_redis_key

    key = build_redis_key(_TENANT_ID, "mcp_tool", _TOOL_ID)
    assert key == _EXPECTED_CACHE_KEY
    assert key.startswith("mingai:")
    assert ":mcp_tool:" in key


def test_cache_key_rejects_colon_in_tool_id():
    """build_redis_key raises ValueError if tool_id contains a colon."""
    from app.core.redis_client import build_redis_key

    with pytest.raises(ValueError, match="colon"):
        build_redis_key(_TENANT_ID, "mcp_tool", "bad:tool:id")


# ---------------------------------------------------------------------------
# ATA-033: cache invalidation wired into mcp_servers CRUD routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_mcp_server_calls_invalidate_after_commit():
    """
    POST /admin/mcp-servers must call invalidate_mcp_tool_cache after db.commit().
    Verified by patching the invalidation function and asserting it was called.
    """
    from unittest.mock import patch
    from datetime import datetime, timezone

    from app.modules.admin.mcp_servers import create_mcp_server, CreateMCPServerRequest

    _NOW = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = (
        "new-server-id",
        "test-srv",
        "https://host.example.com",
        "none",
        "active",
        None,
        _NOW,
    )
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()

    from app.core.dependencies import CurrentUser
    user = CurrentUser(
        id="admin-1",
        tenant_id=_TENANT_ID,
        roles=["tenant_admin"],
        scope="tenant",
        plan="enterprise",
    )
    body = CreateMCPServerRequest(name="test-srv", endpoint="https://host.example.com")

    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()

    with patch(
        "app.modules.admin.mcp_servers.get_redis", return_value=mock_redis
    ), patch(
        "app.modules.admin.mcp_servers.invalidate_mcp_tool_cache", new_callable=AsyncMock
    ) as mock_invalidate:
        await create_mcp_server(body=body, current_user=user, db=db)

    # invalidate_mcp_tool_cache must have been called once
    mock_invalidate.assert_called_once()
    call_kwargs = mock_invalidate.call_args
    # First positional arg is tenant_id
    assert call_kwargs[0][0] == _TENANT_ID


@pytest.mark.asyncio
async def test_delete_mcp_server_calls_invalidate_after_commit():
    """
    DELETE /admin/mcp-servers/{id} must call invalidate_mcp_tool_cache after
    db.commit().
    """
    from unittest.mock import patch

    from app.modules.admin.mcp_servers import delete_mcp_server

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 1
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()

    from app.core.dependencies import CurrentUser
    user = CurrentUser(
        id="admin-1",
        tenant_id=_TENANT_ID,
        roles=["tenant_admin"],
        scope="tenant",
        plan="enterprise",
    )

    server_id = "11111111-1111-1111-1111-111111111111"
    mock_redis = AsyncMock()

    with patch(
        "app.modules.admin.mcp_servers.get_redis", return_value=mock_redis
    ), patch(
        "app.modules.admin.mcp_servers.invalidate_mcp_tool_cache", new_callable=AsyncMock
    ) as mock_invalidate:
        await delete_mcp_server(server_id=server_id, current_user=user, db=db)

    mock_invalidate.assert_called_once()
    call_args = mock_invalidate.call_args[0]
    assert call_args[0] == _TENANT_ID
    assert call_args[1] == server_id
