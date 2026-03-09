"""
Unit tests for anonymous attribution enforcement in TeamWorkingMemoryService (TEST-061).

Validates that team memory entries NEVER store user_id and always maintain
team-level anonymization. Tests the privacy boundary that protects individual
contributors within a team context.

Tier 1: Fast, isolated, mocks Redis.
"""
import json
from unittest.mock import AsyncMock

import pytest

from app.modules.memory.team_working_memory import TeamWorkingMemoryService


class TestAddEntryNoUserId:
    """update() must NOT include user_id in Redis value."""

    @pytest.mark.asyncio
    async def test_add_entry_does_not_include_user_id(self):
        """The stored Redis value must not contain any user_id field."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        service = TeamWorkingMemoryService(redis=mock_redis)

        await service.update(
            team_id="team-1",
            tenant_id="t1",
            query="What is the quarterly revenue?",
            response="The quarterly revenue is...",
        )

        stored_json = mock_redis.setex.call_args[0][2]
        stored_data = json.loads(stored_json)

        assert (
            "user_id" not in stored_data
        ), "team memory schema must not contain a user_id field"
        assert (
            "user" not in stored_data
        ), "team memory schema must not contain a 'user' field"


class TestAddEntryIncludesTeamId:
    """update() must include team_id in the Redis key."""

    @pytest.mark.asyncio
    async def test_add_entry_includes_team_id_in_key(self):
        """The Redis key must contain the team_id for proper scoping."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        service = TeamWorkingMemoryService(redis=mock_redis)

        await service.update(
            team_id="team-alpha",
            tenant_id="tenant-1",
            query="What is the budget forecast?",
            response="The budget forecast is...",
        )

        redis_key = mock_redis.get.call_args[0][0]
        assert (
            "team-alpha" in redis_key
        ), f"Redis key must contain team_id but got: {redis_key}"


class TestAddEntryIncludesTenantId:
    """update() must include tenant_id in the Redis key for isolation."""

    @pytest.mark.asyncio
    async def test_add_entry_includes_tenant_id_in_key(self):
        """The Redis key must contain the tenant_id for multi-tenant isolation."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        service = TeamWorkingMemoryService(redis=mock_redis)

        await service.update(
            team_id="team-1",
            tenant_id="tenant-xyz",
            query="What are the compliance requirements?",
            response="The compliance requirements are...",
        )

        redis_key = mock_redis.get.call_args[0][0]
        assert (
            "tenant-xyz" in redis_key
        ), f"Redis key must contain tenant_id but got: {redis_key}"


class TestAddEntryIncludesTopics:
    """update() must include topic keywords extracted from the query."""

    @pytest.mark.asyncio
    async def test_add_entry_includes_topic_keywords(self):
        """Stored data must include topics extracted from the query."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        service = TeamWorkingMemoryService(redis=mock_redis)

        await service.update(
            team_id="team-1",
            tenant_id="t1",
            query="What is the refund policy for enterprise customers?",
            response="The refund policy is...",
        )

        stored_data = json.loads(mock_redis.setex.call_args[0][2])
        assert "topics" in stored_data, "Stored data must contain 'topics' key"
        assert len(stored_data["topics"]) > 0, "Topics list must not be empty"


class TestGetTeamMemoryNoUserId:
    """get() must return entries without user_id field."""

    @pytest.mark.asyncio
    async def test_get_team_memory_returns_no_user_id(self):
        """The returned memory dict must not contain user_id anywhere."""
        mock_redis = AsyncMock()
        stored = {
            "topics": ["budget", "forecast"],
            "recent_queries": [
                "a team member asked: what is the budget?",
                "a team member asked: forecast for Q2?",
            ],
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(stored))

        service = TeamWorkingMemoryService(redis=mock_redis)
        result = await service.get(team_id="team-1", tenant_id="t1")

        assert "user_id" not in result, "get() return must not contain user_id"
        result_json = json.dumps(result)
        assert (
            "user-" not in result_json
        ), "get() return must not contain any user identifier pattern"


class TestMultipleUsersContributeMerged:
    """Multiple users contributing to the same team should have entries merged
    without any user attribution."""

    @pytest.mark.asyncio
    async def test_multiple_users_merged_without_attribution(self):
        """Two updates (simulating two users) merge into one anonymous pool."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        service = TeamWorkingMemoryService(redis=mock_redis)

        # First "user" contributes
        await service.update(
            team_id="team-1",
            tenant_id="t1",
            query="What is the refund policy?",
            response="The refund policy is...",
        )

        # Capture first write and feed it back as existing data
        first_stored = json.loads(mock_redis.setex.call_args[0][2])
        mock_redis.get = AsyncMock(return_value=json.dumps(first_stored))

        # Second "user" contributes
        await service.update(
            team_id="team-1",
            tenant_id="t1",
            query="What are the pricing tiers?",
            response="The pricing tiers are...",
        )

        second_stored = json.loads(mock_redis.setex.call_args[0][2])

        # Both queries should be anonymized and merged
        assert len(second_stored["recent_queries"]) == 2
        for q in second_stored["recent_queries"]:
            assert q.startswith(
                "a team member asked:"
            ), f"Query must be anonymized: {q}"
            assert "user-" not in q, "Query must not contain user identifier"


class TestTwoDifferentTeamsIsolated:
    """Two different teams must have isolated Redis keys."""

    @pytest.mark.asyncio
    async def test_two_teams_isolated_entries(self):
        """Entries for team-1 and team-2 use different Redis keys."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        service = TeamWorkingMemoryService(redis=mock_redis)

        await service.update(
            team_id="team-1",
            tenant_id="t1",
            query="Team one query about finance",
            response="response",
        )
        key_team_1 = mock_redis.get.call_args[0][0]

        await service.update(
            team_id="team-2",
            tenant_id="t1",
            query="Team two query about marketing",
            response="response",
        )
        key_team_2 = mock_redis.get.call_args[0][0]

        assert key_team_1 != key_team_2, "Different teams must use different Redis keys"
        assert "team-1" in key_team_1
        assert "team-2" in key_team_2


class TestEntryContentHasTimestampTopicsNoUser:
    """Stored entry must have topics and anonymized queries but NO user identifier."""

    @pytest.mark.asyncio
    async def test_entry_has_topics_and_queries_no_user(self):
        """Entry content has topics and recent_queries but no user_id or name."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        service = TeamWorkingMemoryService(redis=mock_redis)

        await service.update(
            team_id="team-1",
            tenant_id="t1",
            query="What are the contract renewal terms?",
            response="The contract renewal terms are...",
        )

        stored_data = json.loads(mock_redis.setex.call_args[0][2])

        # Must have topics
        assert "topics" in stored_data
        # Must have recent_queries
        assert "recent_queries" in stored_data
        assert len(stored_data["recent_queries"]) > 0

        # Must NOT have any user-identifying fields
        forbidden_keys = {"user_id", "user", "name", "email", "display_name"}
        actual_keys = set(stored_data.keys())
        intersection = actual_keys & forbidden_keys
        assert (
            not intersection
        ), f"Stored data must not contain user-identifying keys: {intersection}"
