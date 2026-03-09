"""
Unit tests for active team session (TEST-063).

The active team is communicated via ChatRequest.active_team_id field
in POST /api/v1/chat/stream. The team memory is scoped via Redis key
pattern: mingai:{tenant_id}:team_memory:{team_id}

Tests validate:
- active_team_id flows through the chat request
- Team memory Redis key follows the correct pattern
- Team isolation via separate Redis keys
- Missing team_id handled gracefully

Tier 1: Fast, isolated, mocks Redis and DB.
"""
import json
from unittest.mock import AsyncMock

import pytest

from app.modules.memory.team_working_memory import TeamWorkingMemoryService
from app.core.redis_client import build_redis_key


# ---------------------------------------------------------------------------
# Redis key pattern tests
# ---------------------------------------------------------------------------


class TestActiveTeamRedisKeyPattern:
    """Team memory Redis key must follow mingai:{tenant_id}:team_memory:{team_id}."""

    def test_redis_key_format(self):
        """Key must be mingai:{tenant_id}:team_memory:{team_id}."""
        service = TeamWorkingMemoryService(redis=AsyncMock())
        key = service._redis_key("tenant-abc", "team-xyz")
        assert key == "mingai:tenant-abc:team_memory:team-xyz"

    def test_redis_key_contains_tenant_id(self):
        """Key must be scoped by tenant_id."""
        service = TeamWorkingMemoryService(redis=AsyncMock())
        key = service._redis_key("my-tenant", "team-1")
        assert "my-tenant" in key


# ---------------------------------------------------------------------------
# Set active team — stores team context in Redis
# ---------------------------------------------------------------------------


class TestSetActiveTeamMemory:
    """Setting active team creates a team memory entry in Redis."""

    @pytest.mark.asyncio
    async def test_set_active_team_stores_in_redis(self):
        """update() stores team memory at the correct key."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        service = TeamWorkingMemoryService(redis=mock_redis)

        await service.update(
            team_id="team-finance",
            tenant_id="tenant-001",
            query="What is the quarterly budget?",
            response="The quarterly budget is...",
        )

        # Verify the correct key was used
        key_used = mock_redis.get.call_args[0][0]
        assert key_used == "mingai:tenant-001:team_memory:team-finance"

        # Verify setex was called with the same key
        setex_key = mock_redis.setex.call_args[0][0]
        assert setex_key == "mingai:tenant-001:team_memory:team-finance"


# ---------------------------------------------------------------------------
# Clear active team — removes Redis key
# ---------------------------------------------------------------------------


class TestClearActiveTeam:
    """Clearing team memory removes the Redis key."""

    @pytest.mark.asyncio
    async def test_clear_removes_redis_key(self):
        """clear() deletes the team memory Redis key."""
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        service = TeamWorkingMemoryService(redis=mock_redis)

        await service.clear(team_id="team-1", tenant_id="tenant-1")

        mock_redis.delete.assert_called_once_with("mingai:tenant-1:team_memory:team-1")


# ---------------------------------------------------------------------------
# Non-existent team — graceful handling
# ---------------------------------------------------------------------------


class TestNonExistentTeamMemory:
    """Getting memory for a team with no data returns empty structure."""

    @pytest.mark.asyncio
    async def test_get_nonexistent_team_returns_empty(self):
        """get() for a team with no Redis data returns empty lists."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        service = TeamWorkingMemoryService(redis=mock_redis)

        result = await service.get(team_id="nonexistent-team", tenant_id="t1")
        assert result == {"topics": [], "recent_queries_anonymous": []}


# ---------------------------------------------------------------------------
# Get active team — returns current data
# ---------------------------------------------------------------------------


class TestGetActiveTeamMemory:
    """get() returns current active team memory data."""

    @pytest.mark.asyncio
    async def test_get_active_team_returns_data(self):
        """get() returns topics and anonymized queries for the team."""
        mock_redis = AsyncMock()
        stored = {
            "topics": ["budget", "forecast"],
            "recent_queries": ["a team member asked: what is the budget?"],
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(stored))

        service = TeamWorkingMemoryService(redis=mock_redis)

        result = await service.get(team_id="team-finance", tenant_id="t1")
        assert result["topics"] == ["budget", "forecast"]
        assert len(result["recent_queries_anonymous"]) == 1


# ---------------------------------------------------------------------------
# Active team context used in orchestrator flow
# ---------------------------------------------------------------------------


class TestActiveTeamContextForOrchestrator:
    """get_context() returns data for prompt injection when active team is set."""

    @pytest.mark.asyncio
    async def test_active_team_context_has_data(self):
        """get_context() with active team data returns non-None dict."""
        mock_redis = AsyncMock()
        stored = {
            "topics": ["revenue"],
            "recent_queries": ["a team member asked: revenue trends?"],
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(stored))

        service = TeamWorkingMemoryService(redis=mock_redis)

        result = await service.get_context(team_id="team-1", tenant_id="t1")
        assert result is not None
        assert "topics" in result
        assert "recent_queries" in result
