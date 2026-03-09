"""
TEST-064: Team Working Memory Integration Tests

Tests that TeamWorkingMemoryService correctly stores, retrieves, isolates,
and expires team memory entries in real Redis.

Tier 2: Real Redis, NO MOCKING.

Architecture:
  Uses direct Redis client via get_redis() from app.core.redis_client.
  Each test uses unique tenant_id and team_id to prevent cross-test pollution.
  asyncio.run() wraps async operations.

Prerequisites:
    docker-compose up -d  # ensure Redis is running

Run:
    pytest tests/integration/test_team_working_memory_integration.py -v --timeout=60
"""
import asyncio
import os
import uuid

import pytest

import app.core.redis_client as redis_client_module
from app.core.redis_client import get_redis
from app.modules.memory.team_working_memory import TeamWorkingMemoryService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_redis():
    url = os.environ.get("REDIS_URL", "")
    if not url:
        pytest.skip("REDIS_URL not configured -- skipping integration tests")


def _unique_id() -> str:
    return str(uuid.uuid4())


async def _reset_redis():
    """Reset the global Redis pool to avoid event-loop binding issues."""
    redis_client_module._redis_pool = None


async def _cleanup_key(key: str):
    """Delete a Redis key after test."""
    redis = get_redis()
    await redis.delete(key)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTeamWorkingMemoryRedis:
    """TEST-064: Team working memory integration with real Redis."""

    def test_team_memory_stored_in_redis(self):
        """Add team memory entry, verify it is retrievable with correct key format."""
        _check_redis()

        async def _run():
            await _reset_redis()
            redis = get_redis()
            tenant_id = _unique_id()
            team_id = _unique_id()
            key = f"mingai:{tenant_id}:team_memory:{team_id}"

            try:
                svc = TeamWorkingMemoryService(redis=redis)
                await svc.update(
                    team_id=team_id,
                    tenant_id=tenant_id,
                    query="What is our quarterly revenue target?",
                    response="The Q1 target is $2.5M.",
                )

                # Verify data is stored at the expected Redis key
                raw = await redis.get(key)
                assert (
                    raw is not None
                ), f"Team memory must be stored at Redis key: {key}"

                # Verify data is retrievable via service
                result = await svc.get(team_id=team_id, tenant_id=tenant_id)
                assert "topics" in result
                assert "recent_queries_anonymous" in result
                assert len(result["recent_queries_anonymous"]) == 1
                assert "a team member asked:" in result["recent_queries_anonymous"][0]
            finally:
                await _cleanup_key(key)

        asyncio.run(_run())

    def test_team_memory_retrieved_for_active_team(self):
        """Set active team memory, retrieve it -- should return entries for that team."""
        _check_redis()

        async def _run():
            await _reset_redis()
            redis = get_redis()
            tenant_id = _unique_id()
            team_id = _unique_id()
            key = f"mingai:{tenant_id}:team_memory:{team_id}"

            try:
                svc = TeamWorkingMemoryService(redis=redis)

                # Add multiple queries
                await svc.update(
                    team_id=team_id,
                    tenant_id=tenant_id,
                    query="What are the hiring plans for Q2?",
                    response="We plan to hire 10 engineers.",
                )
                await svc.update(
                    team_id=team_id,
                    tenant_id=tenant_id,
                    query="What is the budget allocation?",
                    response="Budget is $500K for engineering.",
                )

                # Retrieve via get_for_prompt (used for injection)
                result = await svc.get_for_prompt(team_id=team_id, tenant_id=tenant_id)
                assert (
                    result is not None
                ), "get_for_prompt must return data for active team"
                assert "topics" in result
                assert "recent_queries" in result
                assert len(result["recent_queries"]) == 2
            finally:
                await _cleanup_key(key)

        asyncio.run(_run())

    def test_team_memory_isolated_between_teams(self):
        """Team A and Team B have separate memory buckets -- no cross-contamination."""
        _check_redis()

        async def _run():
            await _reset_redis()
            redis = get_redis()
            tenant_id = _unique_id()
            team_a = _unique_id()
            team_b = _unique_id()
            key_a = f"mingai:{tenant_id}:team_memory:{team_a}"
            key_b = f"mingai:{tenant_id}:team_memory:{team_b}"

            try:
                svc = TeamWorkingMemoryService(redis=redis)

                await svc.update(
                    team_id=team_a,
                    tenant_id=tenant_id,
                    query="Team A secret project details",
                    response="Classified.",
                )
                await svc.update(
                    team_id=team_b,
                    tenant_id=tenant_id,
                    query="Team B public roadmap",
                    response="Q2 release.",
                )

                # Team A should only see its own data
                result_a = await svc.get(team_id=team_a, tenant_id=tenant_id)
                assert len(result_a["recent_queries_anonymous"]) == 1
                assert "secret project" in result_a["recent_queries_anonymous"][0]

                # Team B should only see its own data
                result_b = await svc.get(team_id=team_b, tenant_id=tenant_id)
                assert len(result_b["recent_queries_anonymous"]) == 1
                assert "public roadmap" in result_b["recent_queries_anonymous"][0]

                # Verify no cross-contamination
                assert "secret project" not in str(result_b)
                assert "public roadmap" not in str(result_a)
            finally:
                await _cleanup_key(key_a)
                await _cleanup_key(key_b)

        asyncio.run(_run())

    def test_team_memory_ttl_enforced(self):
        """Set entry with short TTL, wait, verify it expires."""
        _check_redis()

        async def _run():
            await _reset_redis()
            redis = get_redis()
            tenant_id = _unique_id()
            team_id = _unique_id()
            key = f"mingai:{tenant_id}:team_memory:{team_id}"

            try:
                svc = TeamWorkingMemoryService(redis=redis)
                await svc.update(
                    team_id=team_id,
                    tenant_id=tenant_id,
                    query="Temporary data for TTL test",
                    response="Will expire.",
                )

                # Confirm data exists
                raw = await redis.get(key)
                assert raw is not None, "Data must exist before TTL expiry"

                # Override TTL to 1 second for test
                await redis.expire(key, 1)

                # Wait for TTL to expire
                await asyncio.sleep(2.0)

                # Verify data is gone
                raw_after = await redis.get(key)
                assert raw_after is None, "Data must be gone after TTL expiry"

                # Service should return empty result
                result = await svc.get(team_id=team_id, tenant_id=tenant_id)
                assert result["topics"] == []
                assert result["recent_queries_anonymous"] == []
            finally:
                await _cleanup_key(key)

        asyncio.run(_run())

    def test_team_memory_empty_for_new_team(self):
        """New team with no history -- get_for_prompt returns None (not error)."""
        _check_redis()

        async def _run():
            await _reset_redis()
            redis = get_redis()
            tenant_id = _unique_id()
            team_id = _unique_id()

            svc = TeamWorkingMemoryService(redis=redis)

            # get_for_prompt returns None for empty team (per implementation)
            result = await svc.get_for_prompt(team_id=team_id, tenant_id=tenant_id)
            assert (
                result is None
            ), "get_for_prompt must return None for new team with no history"

            # get() returns empty lists (not None, not error)
            result_get = await svc.get(team_id=team_id, tenant_id=tenant_id)
            assert result_get["topics"] == []
            assert result_get["recent_queries_anonymous"] == []

        asyncio.run(_run())
