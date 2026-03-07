"""
Unit tests for WorkingMemoryService (AI-011 to AI-020).

Tests topic accumulation, pruning, query truncation, GDPR clear,
and tenant isolation.
Tier 1: Fast, isolated, mocks Redis.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest


class TestWorkingMemoryUpdate:
    """Test update() method for topic and query accumulation."""

    @pytest.mark.asyncio
    async def test_update_stores_topic(self):
        """update() stores extracted topics in Redis."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update(
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                query="How do I configure VPN?",
                response="To configure VPN, follow these steps...",
            )

        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_accumulates_queries(self):
        """update() adds query to recent queries list."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        existing = {"topics": ["vpn"], "queries": ["How to set up VPN?"]}

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(existing))
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update(
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                query="What are the VPN requirements?",
                response="You need...",
            )

        stored_data = json.loads(mock_redis.setex.call_args[0][2])
        assert len(stored_data["queries"]) == 2

    @pytest.mark.asyncio
    async def test_max_5_topics_prunes_oldest(self):
        """Topics are pruned to max 5, dropping oldest."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        existing = {
            "topics": ["topic1", "topic2", "topic3", "topic4", "topic5"],
            "queries": [],
        }

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(existing))
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update(
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                query="Tell me about topic6",
                response="Topic6 is about...",
            )

        stored_data = json.loads(mock_redis.setex.call_args[0][2])
        assert len(stored_data["topics"]) <= 5

    @pytest.mark.asyncio
    async def test_max_3_queries_prunes_oldest(self):
        """Queries are pruned to max 3, dropping oldest."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        existing = {
            "topics": [],
            "queries": ["query1", "query2", "query3"],
        }

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(existing))
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update(
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                query="query4 is the new question",
                response="Answer...",
            )

        stored_data = json.loads(mock_redis.setex.call_args[0][2])
        assert len(stored_data["queries"]) <= 3
        # Oldest query should be dropped
        assert "query1" not in stored_data["queries"]

    @pytest.mark.asyncio
    async def test_query_truncated_to_100_chars(self):
        """Queries longer than 100 chars are truncated."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        long_query = "x" * 200

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update(
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                query=long_query,
                response="Answer",
            )

        stored_data = json.loads(mock_redis.setex.call_args[0][2])
        for q in stored_data["queries"]:
            assert len(q) <= 100

    @pytest.mark.asyncio
    async def test_redis_key_pattern(self):
        """Redis key must be mingai:{tenant_id}:working_memory:{user_id}:{agent_id}."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update(
                user_id="my-user",
                tenant_id="my-tenant",
                agent_id="my-agent",
                query="test",
                response="answer",
            )

        key = mock_redis.get.call_args[0][0]
        assert key == "mingai:my-tenant:working_memory:my-user:my-agent"

    @pytest.mark.asyncio
    async def test_ttl_is_7_days(self):
        """Working memory TTL must be 7 days (604800 seconds)."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update("u1", "t1", "a1", "q", "r")

        ttl = mock_redis.setex.call_args[0][1]
        assert ttl == 604800


class TestGetForPrompt:
    """Test get_for_prompt() formatting."""

    @pytest.mark.asyncio
    async def test_returns_formatted_string(self):
        """get_for_prompt returns a formatted string."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        memory_data = {"topics": ["vpn", "security"], "queries": ["How to VPN?"]}

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(memory_data))

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            result = await service.get_for_prompt("u1", "t1", "a1")

        assert isinstance(result, dict)
        assert "topics" in result

    @pytest.mark.asyncio
    async def test_returns_none_when_no_memory(self):
        """Returns None when no working memory exists."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            result = await service.get_for_prompt("u1", "t1", "a1")

        assert result is None


class TestClearMemory:
    """Test clear_memory() for GDPR compliance."""

    @pytest.mark.asyncio
    async def test_clear_with_agent_id_deletes_specific_key(self):
        """clear_memory with agent_id deletes only that agent's key."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.clear_memory("u1", "t1", agent_id="a1")

        mock_redis.delete.assert_called_once_with(
            "mingai:t1:working_memory:u1:a1"
        )

    @pytest.mark.asyncio
    async def test_clear_without_agent_id_scans_all_keys(self):
        """clear_memory without agent_id scans and deletes ALL user keys (GDPR)."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        # Simulate scan returning multiple keys
        mock_redis.scan_iter = lambda pattern: _async_iter(
            [
                "mingai:t1:working_memory:u1:agent-a",
                "mingai:t1:working_memory:u1:agent-b",
            ]
        )
        mock_redis.delete = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.clear_memory("u1", "t1", agent_id=None)

        assert mock_redis.delete.call_count == 2

    @pytest.mark.asyncio
    async def test_clear_uses_correct_scan_pattern(self):
        """GDPR scan pattern must be mingai:{tenant_id}:working_memory:{user_id}:*."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        scan_patterns = []

        async def mock_scan(pattern):
            scan_patterns.append(pattern)
            return
            yield  # noqa: make it async generator

        mock_redis = AsyncMock()
        mock_redis.scan_iter = mock_scan
        mock_redis.delete = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.clear_memory("gdpr-user", "gdpr-tenant", agent_id=None)

        assert "mingai:gdpr-tenant:working_memory:gdpr-user:*" in scan_patterns


class TestTenantIsolation:
    """Test working memory tenant isolation."""

    @pytest.mark.asyncio
    async def test_different_tenants_different_keys(self):
        """Same user in different tenants gets different memory keys."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        keys_accessed = []

        mock_redis = AsyncMock()

        original_get = AsyncMock(return_value=None)

        async def track_get(key):
            keys_accessed.append(key)
            return None

        mock_redis.get = track_get
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update("user1", "tenant-a", "a1", "q", "r")
            await service.update("user1", "tenant-b", "a1", "q", "r")

        assert keys_accessed[0] != keys_accessed[1]
        assert "tenant-a" in keys_accessed[0]
        assert "tenant-b" in keys_accessed[1]


async def _async_iter(items):
    """Helper to create an async iterator from a list."""
    for item in items:
        yield item
