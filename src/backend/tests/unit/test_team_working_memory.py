"""
Unit tests for TeamWorkingMemoryService (AI-013).

Tests anonymization, capping, deduplication, privacy, and Redis interactions.
Tier 1: Fast, isolated, mocks Redis.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest


class TestUpdateAnonymizesQuery:
    """update() must anonymize queries before storing."""

    @pytest.mark.asyncio
    async def test_update_anonymizes_query(self):
        """Stored query must match anonymized format: 'a team member asked: ...'."""
        from app.modules.memory.team_working_memory import TeamWorkingMemoryService

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        service = TeamWorkingMemoryService(redis=mock_redis)

        await service.update(
            team_id="team-1",
            tenant_id="t1",
            query="What is the refund policy?",
            response="The refund policy is...",
        )

        mock_redis.setex.assert_called_once()
        stored_data = json.loads(mock_redis.setex.call_args[0][2])
        for q in stored_data["recent_queries"]:
            assert q.startswith(
                "a team member asked: "
            ), f"Query must be anonymized but got: {q}"


class TestUpdateCapsQueries:
    """update() must cap queries at 5 most recent."""

    @pytest.mark.asyncio
    async def test_update_caps_queries_at_5(self):
        """After 6 updates, only 5 queries should be stored."""
        from app.modules.memory.team_working_memory import TeamWorkingMemoryService

        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        existing = {
            "topics": [],
            "recent_queries": [
                "a team member asked: q1",
                "a team member asked: q2",
                "a team member asked: q3",
                "a team member asked: q4",
                "a team member asked: q5",
            ],
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(existing))

        service = TeamWorkingMemoryService(redis=mock_redis)

        await service.update(
            team_id="team-1",
            tenant_id="t1",
            query="query number six",
            response="response",
        )

        stored_data = json.loads(mock_redis.setex.call_args[0][2])
        assert len(stored_data["recent_queries"]) == 5
        # Oldest query should be dropped
        assert "a team member asked: q1" not in stored_data["recent_queries"]
        assert stored_data["recent_queries"][-1].startswith(
            "a team member asked: query number six"
        )


class TestUpdateCapsTopics:
    """update() must cap topics at 10."""

    @pytest.mark.asyncio
    async def test_update_caps_topics_at_10(self):
        """After many updates with unique topics, max 10 topics should be stored."""
        from app.modules.memory.team_working_memory import TeamWorkingMemoryService

        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        existing = {
            "topics": [f"topic{i}" for i in range(10)],
            "recent_queries": [],
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(existing))

        service = TeamWorkingMemoryService(redis=mock_redis)

        await service.update(
            team_id="team-1",
            tenant_id="t1",
            query="Tell me about brandnewtopic",
            response="response",
        )

        stored_data = json.loads(mock_redis.setex.call_args[0][2])
        assert len(stored_data["topics"]) <= 10


class TestUpdateDeduplicatesTopics:
    """update() must deduplicate topics."""

    @pytest.mark.asyncio
    async def test_update_deduplicates_topics(self):
        """Same topic added twice should only appear once."""
        from app.modules.memory.team_working_memory import TeamWorkingMemoryService

        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        existing = {
            "topics": ["refund"],
            "recent_queries": [],
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(existing))

        service = TeamWorkingMemoryService(redis=mock_redis)

        # Query that would extract "refund" as a topic
        await service.update(
            team_id="team-1",
            tenant_id="t1",
            query="What is the refund policy for enterprise?",
            response="response",
        )

        stored_data = json.loads(mock_redis.setex.call_args[0][2])
        topic_counts = {}
        for t in stored_data["topics"]:
            topic_counts[t] = topic_counts.get(t, 0) + 1
        for t, count in topic_counts.items():
            assert (
                count == 1
            ), f"Topic '{t}' appears {count} times, expected exactly once"


class TestUpdateNeverStoresUserId:
    """update() must NEVER store user_id in team memory."""

    @pytest.mark.asyncio
    async def test_update_never_stores_user_id(self):
        """user_id must not appear anywhere in the stored Redis value."""
        from app.modules.memory.team_working_memory import TeamWorkingMemoryService

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        service = TeamWorkingMemoryService(redis=mock_redis)

        user_id = "user-secret-id-12345"
        # The service interface does not accept user_id at all.
        # This test validates the stored data does not contain user identifiers.
        await service.update(
            team_id="team-1",
            tenant_id="t1",
            query="What is the refund policy?",
            response="The refund policy is...",
        )

        stored_json = mock_redis.setex.call_args[0][2]
        assert (
            user_id not in stored_json
        ), "user_id must never appear in team memory data"
        # Also ensure no 'user_id' key exists in the stored data
        stored_data = json.loads(stored_json)
        assert (
            "user_id" not in stored_data
        ), "team memory schema must not contain a user_id field"


class TestGetReturnsEmptyWhenNoData:
    """get() must return empty structure when no data exists."""

    @pytest.mark.asyncio
    async def test_get_returns_empty_when_no_data(self):
        """Returns {'topics': [], 'recent_queries_anonymous': []} when empty."""
        from app.modules.memory.team_working_memory import TeamWorkingMemoryService

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        service = TeamWorkingMemoryService(redis=mock_redis)

        result = await service.get(team_id="team-1", tenant_id="t1")
        assert result == {"topics": [], "recent_queries_anonymous": []}


class TestGetForPromptReturnsNoneWhenEmpty:
    """get_for_prompt() returns None when memory is empty."""

    @pytest.mark.asyncio
    async def test_get_for_prompt_returns_none_when_empty(self):
        """Empty memory (no data or empty lists) returns None."""
        from app.modules.memory.team_working_memory import TeamWorkingMemoryService

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        service = TeamWorkingMemoryService(redis=mock_redis)

        result = await service.get_for_prompt(team_id="team-1", tenant_id="t1")
        assert result is None


class TestClearDeletesRedisKey:
    """clear() must delete the Redis key."""

    @pytest.mark.asyncio
    async def test_clear_deletes_redis_key(self):
        """Redis delete must be called with the correct key."""
        from app.modules.memory.team_working_memory import TeamWorkingMemoryService

        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        service = TeamWorkingMemoryService(redis=mock_redis)

        await service.clear(team_id="team-1", tenant_id="t1")

        mock_redis.delete.assert_called_once_with("mingai:t1:team_memory:team-1")


class TestRedisKeyPattern:
    """Redis key must follow mingai:{tenant_id}:team_memory:{team_id} pattern."""

    @pytest.mark.asyncio
    async def test_redis_key_pattern(self):
        """Key pattern must be mingai:{tenant_id}:team_memory:{team_id}."""
        from app.modules.memory.team_working_memory import TeamWorkingMemoryService

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        service = TeamWorkingMemoryService(redis=mock_redis)

        await service.update(
            team_id="my-team",
            tenant_id="my-tenant",
            query="test query words here",
            response="response",
        )

        key = mock_redis.get.call_args[0][0]
        assert key == "mingai:my-tenant:team_memory:my-team"


class TestTTLIs7Days:
    """TTL must be 604800 seconds (7 days)."""

    @pytest.mark.asyncio
    async def test_ttl_is_7_days(self):
        """setex TTL must be 604800."""
        from app.modules.memory.team_working_memory import TeamWorkingMemoryService

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        service = TeamWorkingMemoryService(redis=mock_redis)

        await service.update(
            team_id="team-1",
            tenant_id="t1",
            query="test query words here",
            response="response",
        )

        ttl = mock_redis.setex.call_args[0][1]
        assert ttl == 604800


class TestGetContextAlias:
    """get_context() must work as alias for orchestrator integration."""

    @pytest.mark.asyncio
    async def test_get_context_returns_data(self):
        """get_context() returns team memory dict for orchestrator."""
        from app.modules.memory.team_working_memory import TeamWorkingMemoryService

        mock_redis = AsyncMock()
        memory_data = {
            "topics": ["refund", "policy"],
            "recent_queries": ["a team member asked: what is refund policy"],
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(memory_data))

        service = TeamWorkingMemoryService(redis=mock_redis)

        result = await service.get_context(team_id="team-1", tenant_id="t1")
        assert result is not None
        assert "topics" in result

    @pytest.mark.asyncio
    async def test_get_context_returns_none_when_empty(self):
        """get_context() returns None when no data (same as get_for_prompt)."""
        from app.modules.memory.team_working_memory import TeamWorkingMemoryService

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        service = TeamWorkingMemoryService(redis=mock_redis)

        result = await service.get_context(team_id="team-1", tenant_id="t1")
        assert result is None


class TestQueryTruncation:
    """Queries must be truncated to 100 characters before anonymizing."""

    @pytest.mark.asyncio
    async def test_long_query_truncated(self):
        """Query longer than 100 chars must be truncated."""
        from app.modules.memory.team_working_memory import TeamWorkingMemoryService

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        service = TeamWorkingMemoryService(redis=mock_redis)

        long_query = "x" * 200
        await service.update(
            team_id="team-1",
            tenant_id="t1",
            query=long_query,
            response="response",
        )

        stored_data = json.loads(mock_redis.setex.call_args[0][2])
        anon_query = stored_data["recent_queries"][0]
        # "a team member asked: " is 21 chars + 100 chars max = 121 chars max
        assert (
            len(anon_query) <= 121
        ), f"Anonymized query too long: {len(anon_query)} chars"
