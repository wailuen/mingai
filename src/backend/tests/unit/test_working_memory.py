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

        mock_redis.delete.assert_called_once_with("mingai:t1:working_memory:u1:a1")

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


class TestExtractTopic:
    """Test _extract_topic() static method."""

    def test_extract_topic_removes_how_do_i_prefix(self):
        """'How do I configure VPN?' => 'configure vpn?'."""
        from app.modules.memory.working_memory import WorkingMemoryService

        result = WorkingMemoryService._extract_topic("How do I configure VPN?")
        assert result is not None
        assert "how" not in result
        assert "configure" in result.lower()

    def test_extract_topic_removes_what_is_prefix(self):
        """'What is the expense policy?' => topic without 'what is'."""
        from app.modules.memory.working_memory import WorkingMemoryService

        result = WorkingMemoryService._extract_topic("What is the expense policy?")
        assert result is not None
        assert "what" not in result

    def test_extract_topic_removes_tell_me_about_prefix(self):
        """'Tell me about security policies' => topic without prefix."""
        from app.modules.memory.working_memory import WorkingMemoryService

        result = WorkingMemoryService._extract_topic("Tell me about security policies")
        assert result is not None
        assert "tell" not in result

    def test_extract_topic_removes_explain_prefix(self):
        """'Explain the leave policy' => topic without 'explain'."""
        from app.modules.memory.working_memory import WorkingMemoryService

        result = WorkingMemoryService._extract_topic("Explain the leave policy")
        assert result is not None
        assert "explain" not in result

    def test_extract_topic_removes_show_me_prefix(self):
        """'Show me the dashboard' => topic without 'show me'."""
        from app.modules.memory.working_memory import WorkingMemoryService

        result = WorkingMemoryService._extract_topic("Show me the dashboard")
        assert result is not None
        assert "show" not in result

    def test_extract_topic_removes_can_you_prefix(self):
        """'Can you help with onboarding?' => topic without 'can you'."""
        from app.modules.memory.working_memory import WorkingMemoryService

        result = WorkingMemoryService._extract_topic("Can you help with onboarding?")
        assert result is not None
        assert "can" not in result

    def test_extract_topic_removes_please_prefix(self):
        """'Please show the report' => topic without 'please'."""
        from app.modules.memory.working_memory import WorkingMemoryService

        result = WorkingMemoryService._extract_topic("Please show the report")
        assert result is not None
        assert "please" not in result

    def test_extract_topic_removes_how_to_prefix(self):
        """'How to reset password' => topic without 'how to'."""
        from app.modules.memory.working_memory import WorkingMemoryService

        result = WorkingMemoryService._extract_topic("How to reset password")
        assert result is not None
        assert "how" not in result

    def test_extract_topic_removes_what_are_prefix(self):
        """'What are the holidays?' => topic without 'what are'."""
        from app.modules.memory.working_memory import WorkingMemoryService

        result = WorkingMemoryService._extract_topic("What are the holidays?")
        assert result is not None
        assert "what" not in result

    def test_extract_topic_empty_string_returns_none(self):
        """Empty query returns None."""
        from app.modules.memory.working_memory import WorkingMemoryService

        assert WorkingMemoryService._extract_topic("") is None

    def test_extract_topic_none_returns_none(self):
        """None query returns None."""
        from app.modules.memory.working_memory import WorkingMemoryService

        assert WorkingMemoryService._extract_topic(None) is None

    def test_extract_topic_whitespace_only_returns_none(self):
        """Whitespace-only query returns None."""
        from app.modules.memory.working_memory import WorkingMemoryService

        assert WorkingMemoryService._extract_topic("   ") is None

    def test_extract_topic_strips_trailing_punctuation(self):
        """Topic has trailing ?, ., ! stripped."""
        from app.modules.memory.working_memory import WorkingMemoryService

        result = WorkingMemoryService._extract_topic("What is VPN?")
        assert result is not None
        assert not result.endswith("?")

    def test_extract_topic_max_4_words(self):
        """Topic is limited to first 4 significant words."""
        from app.modules.memory.working_memory import WorkingMemoryService

        result = WorkingMemoryService._extract_topic(
            "security policy configuration management overview details"
        )
        assert result is not None
        words = result.split()
        assert len(words) <= 4

    def test_extract_topic_returns_lowercase(self):
        """Topics are lowercased."""
        from app.modules.memory.working_memory import WorkingMemoryService

        result = WorkingMemoryService._extract_topic("VPN Configuration Guide")
        assert result is not None
        assert result == result.lower()

    def test_extract_topic_single_char_word_after_prefix_removal(self):
        """Single-char result (len <= 2) returns None."""
        from app.modules.memory.working_memory import WorkingMemoryService

        # After removing "what is", left with "a" which is <= 2 chars
        result = WorkingMemoryService._extract_topic("What is a")
        # "a" is only 1 char, should return None (len <= 2 filter)
        assert result is None

    def test_extract_topic_unicode_content(self):
        """Unicode characters are preserved in topics."""
        from app.modules.memory.working_memory import WorkingMemoryService

        result = WorkingMemoryService._extract_topic(
            "How do I configure résumé templates?"
        )
        assert result is not None
        # Should contain the unicode word
        assert "résumé" in result

    def test_extract_topic_long_query_takes_first_4_words(self):
        """Long query (many words) => only first 4 significant words."""
        from app.modules.memory.working_memory import WorkingMemoryService

        long_query = " ".join([f"word{i}" for i in range(100)])
        result = WorkingMemoryService._extract_topic(long_query)
        assert result is not None
        assert len(result.split()) <= 4


class TestWorkingMemoryUpdateAdvanced:
    """Additional update() tests for edge cases."""

    @pytest.mark.asyncio
    async def test_duplicate_topic_not_added(self):
        """Same topic extracted twice is not duplicated."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        existing = {"topics": ["configure vpn"], "queries": []}

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(existing))
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update("u1", "t1", "a1", "How do I configure VPN?", "r")

        stored = json.loads(mock_redis.setex.call_args[0][2])
        # Topic "configure vpn" should appear only once
        assert stored["topics"].count("configure vpn") == 1

    @pytest.mark.asyncio
    async def test_empty_query_no_topic_added(self):
        """Empty query should not add a topic."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update("u1", "t1", "a1", "", "r")

        stored = json.loads(mock_redis.setex.call_args[0][2])
        assert stored["topics"] == []

    @pytest.mark.asyncio
    async def test_query_stored_as_truncated_snippet(self):
        """Query longer than 100 chars stored as first 100 chars."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        query = "a" * 50 + "b" * 50 + "c" * 100  # 200 chars total

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update("u1", "t1", "a1", query, "r")

        stored = json.loads(mock_redis.setex.call_args[0][2])
        assert len(stored["queries"][0]) == 100
        assert stored["queries"][0] == query[:100]

    @pytest.mark.asyncio
    async def test_exactly_100_char_query_not_truncated(self):
        """Query of exactly 100 chars is stored as-is."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        query = "x" * 100

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update("u1", "t1", "a1", query, "r")

        stored = json.loads(mock_redis.setex.call_args[0][2])
        assert stored["queries"][0] == query
        assert len(stored["queries"][0]) == 100

    @pytest.mark.asyncio
    async def test_topics_pruned_keeps_newest(self):
        """When 6 topics exist, oldest (first) is dropped, newest kept."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        existing = {
            "topics": ["oldest", "second", "third", "fourth", "fifth"],
            "queries": [],
        }

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(existing))
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update("u1", "t1", "a1", "newest topic here", "r")

        stored = json.loads(mock_redis.setex.call_args[0][2])
        assert len(stored["topics"]) == 5
        assert "oldest" not in stored["topics"]
        assert "newest topic here" in stored["topics"]

    @pytest.mark.asyncio
    async def test_queries_pruned_keeps_newest(self):
        """When 4th query added, oldest (1st) is dropped."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        existing = {
            "topics": [],
            "queries": ["first", "second", "third"],
        }

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(existing))
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update("u1", "t1", "a1", "fourth query", "r")

        stored = json.loads(mock_redis.setex.call_args[0][2])
        assert len(stored["queries"]) == 3
        assert "first" not in stored["queries"]
        assert "fourth query" in stored["queries"]

    @pytest.mark.asyncio
    async def test_unicode_query_stored_correctly(self):
        """Unicode queries are stored and retrieved correctly."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        query = "Comment configurer le réseau WiFi?"

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update("u1", "t1", "a1", query, "r")

        stored = json.loads(mock_redis.setex.call_args[0][2])
        assert query in stored["queries"]

    @pytest.mark.asyncio
    async def test_setex_called_with_json_string(self):
        """Data stored in Redis is valid JSON."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update("u1", "t1", "a1", "test query", "r")

        stored_raw = mock_redis.setex.call_args[0][2]
        parsed = json.loads(stored_raw)  # Should not raise
        assert "topics" in parsed
        assert "queries" in parsed

    @pytest.mark.asyncio
    async def test_new_memory_initialized_with_empty_lists(self):
        """First query ever: memory initialized with empty topics/queries then populated."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update("u1", "t1", "a1", "first question ever", "r")

        stored = json.loads(mock_redis.setex.call_args[0][2])
        assert isinstance(stored["topics"], list)
        assert isinstance(stored["queries"], list)
        # Should have 1 query from the call
        assert len(stored["queries"]) == 1


class TestGetForPromptAdvanced:
    """Additional get_for_prompt() tests."""

    @pytest.mark.asyncio
    async def test_returns_dict_with_topics_and_queries(self):
        """get_for_prompt returns dict containing both topics and queries."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        memory = {"topics": ["vpn", "security"], "queries": ["How to VPN?"]}

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(memory))

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            result = await service.get_for_prompt("u1", "t1", "a1")

        assert result["topics"] == ["vpn", "security"]
        assert result["queries"] == ["How to VPN?"]

    @pytest.mark.asyncio
    async def test_empty_memory_returns_empty_lists(self):
        """get_for_prompt with empty topics/queries returns empty lists."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        memory = {"topics": [], "queries": []}

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(memory))

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            result = await service.get_for_prompt("u1", "t1", "a1")

        assert result == {"topics": [], "queries": []}

    @pytest.mark.asyncio
    async def test_get_for_prompt_uses_correct_key(self):
        """get_for_prompt uses correct Redis key pattern."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.get_for_prompt("user-x", "tenant-y", "agent-z")

        mock_redis.get.assert_called_once_with(
            "mingai:tenant-y:working_memory:user-x:agent-z"
        )


class TestClearMemoryAdvanced:
    """Additional clear_memory() tests."""

    @pytest.mark.asyncio
    async def test_clear_with_agent_id_does_not_scan(self):
        """clear_memory with specific agent_id uses delete, not scan."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.clear_memory("u1", "t1", agent_id="a1")

        mock_redis.delete.assert_called_once_with("mingai:t1:working_memory:u1:a1")

    @pytest.mark.asyncio
    async def test_clear_without_agent_deletes_all_found_keys(self):
        """GDPR clear deletes each key found by scan."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.scan_iter = lambda pattern: _async_iter(
            [
                "mingai:t1:working_memory:u1:a1",
                "mingai:t1:working_memory:u1:a2",
                "mingai:t1:working_memory:u1:a3",
            ]
        )
        mock_redis.delete = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.clear_memory("u1", "t1", agent_id=None)

        assert mock_redis.delete.call_count == 3

    @pytest.mark.asyncio
    async def test_clear_gdpr_no_keys_found(self):
        """GDPR clear with no matching keys: no delete calls, no error."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        mock_redis = AsyncMock()
        mock_redis.scan_iter = lambda pattern: _async_iter([])
        mock_redis.delete = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.clear_memory("u1", "t1", agent_id=None)

        mock_redis.delete.assert_not_called()


class TestPerAgentIsolation:
    """Test that different agents have separate memory."""

    @pytest.mark.asyncio
    async def test_different_agents_different_keys(self):
        """Same user with different agents gets different Redis keys."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        keys_accessed = []

        mock_redis = AsyncMock()

        async def track_get(key):
            keys_accessed.append(key)
            return None

        mock_redis.get = track_get
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update("u1", "t1", "agent-a", "q1", "r")
            await service.update("u1", "t1", "agent-b", "q2", "r")

        assert keys_accessed[0] != keys_accessed[1]
        assert "agent-a" in keys_accessed[0]
        assert "agent-b" in keys_accessed[1]

    @pytest.mark.asyncio
    async def test_agent_a_memory_independent_of_agent_b(self):
        """Agent A update does not affect agent B memory."""
        from app.modules.memory.working_memory import WorkingMemoryService

        service = WorkingMemoryService.__new__(WorkingMemoryService)

        agent_a_data = {"topics": ["finance"], "queries": ["budget?"]}
        agent_b_data = {"topics": ["hr"], "queries": ["leave?"]}

        call_count = 0

        mock_redis = AsyncMock()

        async def selective_get(key):
            if "agent-a" in key:
                return json.dumps(agent_a_data)
            return json.dumps(agent_b_data)

        mock_redis.get = selective_get
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis,
        ):
            await service.update("u1", "t1", "agent-a", "new finance query", "r")

        # setex should have been called with agent-a key
        stored_key = mock_redis.setex.call_args[0][0]
        assert "agent-a" in stored_key


class TestBuildKey:
    """Test _build_key() helper function."""

    def test_build_key_format(self):
        """Key format: mingai:{tenant_id}:working_memory:{user_id}:{agent_id}."""
        from app.modules.memory.working_memory import _build_key

        key = _build_key("tenant-1", "user-1", "agent-1")
        assert key == "mingai:tenant-1:working_memory:user-1:agent-1"

    def test_build_key_with_special_chars(self):
        """Key with UUIDs works correctly."""
        from app.modules.memory.working_memory import _build_key

        key = _build_key(
            "550e8400-e29b-41d4-a716-446655440000",
            "user-abc-123",
            "agent-xyz-789",
        )
        assert key.startswith("mingai:")
        assert "working_memory" in key

    def test_build_key_includes_all_components(self):
        """All three IDs appear in the key."""
        from app.modules.memory.working_memory import _build_key

        key = _build_key("t-id", "u-id", "a-id")
        assert "t-id" in key
        assert "u-id" in key
        assert "a-id" in key


class TestConstants:
    """Test module-level constants are correct."""

    def test_max_topics_is_5(self):
        from app.modules.memory.working_memory import MAX_TOPICS

        assert MAX_TOPICS == 5

    def test_max_queries_is_3(self):
        from app.modules.memory.working_memory import MAX_QUERIES

        assert MAX_QUERIES == 3

    def test_max_query_length_is_100(self):
        from app.modules.memory.working_memory import MAX_QUERY_LENGTH

        assert MAX_QUERY_LENGTH == 100

    def test_ttl_is_7_days_in_seconds(self):
        from app.modules.memory.working_memory import WORKING_MEMORY_TTL_SECONDS

        assert WORKING_MEMORY_TTL_SECONDS == 7 * 24 * 60 * 60


async def _async_iter(items):
    """Helper to create an async iterator from a list."""
    for item in items:
        yield item
