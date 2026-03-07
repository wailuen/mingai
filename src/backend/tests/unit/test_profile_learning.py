"""
Unit tests for ProfileLearningService (AI-001 to AI-010).

Tests L1/L2/L3 caching, query counter, profile extraction trigger,
and tenant isolation.
Tier 1: Fast, isolated, mocks Redis/DB/LLM.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestProfileLRUCache:
    """Test in-process L1 LRU cache."""

    def test_cache_max_size_is_1000(self):
        """L1 cache must have maxsize=1000."""
        from app.modules.profile.learning import _profile_l1_cache

        assert _profile_l1_cache.maxsize == 1000

    def test_cache_set_and_get(self):
        """Can store and retrieve a profile from L1 cache."""
        from app.modules.profile.learning import _profile_l1_cache

        _profile_l1_cache["test-tenant:test-user"] = {"level": "expert"}
        assert _profile_l1_cache["test-tenant:test-user"] == {"level": "expert"}
        # Cleanup
        del _profile_l1_cache["test-tenant:test-user"]

    def test_cache_evicts_at_max_size(self):
        """L1 cache evicts oldest entries when maxsize exceeded."""
        from cachetools import LRUCache

        small_cache = LRUCache(maxsize=3)
        small_cache["a"] = 1
        small_cache["b"] = 2
        small_cache["c"] = 3
        small_cache["d"] = 4  # Should evict "a"
        assert "a" not in small_cache
        assert "d" in small_cache


class TestGetProfile:
    """Test get_profile_context() with L1/L2/L3 fallback."""

    @pytest.mark.asyncio
    async def test_l1_cache_hit_skips_redis_and_db(self):
        """L1 cache hit returns profile without calling Redis or DB."""
        from app.modules.profile.learning import (
            ProfileLearningService,
            _profile_l1_cache,
        )

        _profile_l1_cache["t1:u1"] = {"technical_level": "expert"}

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()

        mock_redis = MagicMock()
        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            result = await service.get_profile_context("u1", "t1")

        assert result == {"technical_level": "expert"}
        mock_redis.get.assert_not_called()
        service._db.execute.assert_not_called()

        # Cleanup
        del _profile_l1_cache["t1:u1"]

    @pytest.mark.asyncio
    async def test_l2_cache_hit_skips_db(self):
        """L2 Redis hit returns profile without calling DB."""
        from app.modules.profile.learning import (
            ProfileLearningService,
            _profile_l1_cache,
        )

        # Ensure L1 miss
        if "t2:u2" in _profile_l1_cache:
            del _profile_l1_cache["t2:u2"]

        cached_profile = {"communication_style": "concise"}

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_profile))

        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            result = await service.get_profile_context("u2", "t2")

        assert result == cached_profile
        service._db.execute.assert_not_called()

        # Cleanup
        if "t2:u2" in _profile_l1_cache:
            del _profile_l1_cache["t2:u2"]

    @pytest.mark.asyncio
    async def test_l2_key_uses_correct_pattern(self):
        """L2 Redis key must be mingai:{tenant_id}:profile_learning:profile:{user_id}."""
        from app.modules.profile.learning import (
            ProfileLearningService,
            _profile_l1_cache,
        )

        if "my-tenant:my-user" in _profile_l1_cache:
            del _profile_l1_cache["my-tenant:my-user"]

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()
        service._load_from_db = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            await service.get_profile_context("my-user", "my-tenant")

        mock_redis.get.assert_called_once_with(
            "mingai:my-tenant:profile_learning:profile:my-user"
        )

    @pytest.mark.asyncio
    async def test_l3_db_fallback_when_cache_misses(self):
        """When L1 and L2 miss, load from PostgreSQL."""
        from app.modules.profile.learning import (
            ProfileLearningService,
            _profile_l1_cache,
        )

        if "t3:u3" in _profile_l1_cache:
            del _profile_l1_cache["t3:u3"]

        db_profile = {"technical_level": "beginner", "interests": ["python"]}

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()
        service._load_from_db = AsyncMock(return_value=db_profile)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            result = await service.get_profile_context("u3", "t3")

        assert result == db_profile
        service._load_from_db.assert_called_once_with("u3", "t3")
        # Should populate L2 cache
        mock_redis.setex.assert_called_once()

        # Cleanup
        if "t3:u3" in _profile_l1_cache:
            del _profile_l1_cache["t3:u3"]

    @pytest.mark.asyncio
    async def test_none_returned_when_no_profile_exists(self):
        """Returns None when profile not found in any cache or DB."""
        from app.modules.profile.learning import (
            ProfileLearningService,
            _profile_l1_cache,
        )

        if "t4:u4" in _profile_l1_cache:
            del _profile_l1_cache["t4:u4"]

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()
        service._load_from_db = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            result = await service.get_profile_context("u4", "t4")

        assert result is None


class TestQueryCounter:
    """Test on_query_completed() and learn trigger."""

    @pytest.mark.asyncio
    async def test_counter_increments_on_query(self):
        """on_query_completed increments the Redis query counter."""
        from app.modules.profile.learning import ProfileLearningService

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()
        service._run_profile_extraction = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            await service.on_query_completed("u1", "t1", "agent-1")

        mock_redis.incr.assert_called_once()

    @pytest.mark.asyncio
    async def test_counter_key_uses_correct_pattern(self):
        """Counter key must be mingai:{tenant_id}:profile_learning:query_count:{user_id}."""
        from app.modules.profile.learning import ProfileLearningService

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()
        service._run_profile_extraction = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            await service.on_query_completed("user-abc", "tenant-xyz", "a1")

        mock_redis.incr.assert_called_once_with(
            "mingai:tenant-xyz:profile_learning:query_count:user-abc"
        )

    @pytest.mark.asyncio
    async def test_learn_triggered_at_10_queries(self):
        """Profile extraction triggered when counter reaches 10."""
        from app.modules.profile.learning import ProfileLearningService

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()
        service._run_profile_extraction = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=10)
        mock_redis.expire = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            await service.on_query_completed("u1", "t1", "a1")

        service._run_profile_extraction.assert_called_once_with("u1", "t1", "a1")

    @pytest.mark.asyncio
    async def test_learn_triggered_at_20_queries(self):
        """Profile extraction also triggers at 20 (every 10)."""
        from app.modules.profile.learning import ProfileLearningService

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()
        service._run_profile_extraction = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=20)
        mock_redis.expire = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            await service.on_query_completed("u1", "t1", "a1")

        service._run_profile_extraction.assert_called_once()

    @pytest.mark.asyncio
    async def test_learn_not_triggered_at_11(self):
        """Profile extraction does NOT trigger at count 11."""
        from app.modules.profile.learning import ProfileLearningService

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()
        service._run_profile_extraction = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=11)
        mock_redis.expire = AsyncMock()

        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            await service.on_query_completed("u1", "t1", "a1")

        service._run_profile_extraction.assert_not_called()

    @pytest.mark.asyncio
    async def test_counter_resets_after_learn(self):
        """Counter resets to 0 after triggering learn."""
        from app.modules.profile.learning import ProfileLearningService

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()
        service._run_profile_extraction = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=10)
        mock_redis.expire = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            await service.on_query_completed("u1", "t1", "a1")

        # Counter should be reset
        counter_key = "mingai:t1:profile_learning:query_count:u1"
        mock_redis.set.assert_called_once_with(counter_key, 0)

    @pytest.mark.asyncio
    async def test_counter_ttl_30_days(self):
        """Query counter TTL must be 30 days (2592000 seconds)."""
        from app.modules.profile.learning import ProfileLearningService

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()
        service._run_profile_extraction = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            await service.on_query_completed("u1", "t1", "a1")

        # 30 days = 30 * 24 * 3600 = 2592000
        mock_redis.expire.assert_called_once()
        ttl_arg = mock_redis.expire.call_args[0][1]
        assert ttl_arg == 2592000


class TestTenantIsolation:
    """Test profile tenant isolation."""

    @pytest.mark.asyncio
    async def test_different_tenants_different_l1_keys(self):
        """L1 cache keys include tenant_id for isolation."""
        from app.modules.profile.learning import (
            ProfileLearningService,
            _profile_l1_cache,
        )

        _profile_l1_cache["tenant-a:user-1"] = {"level": "expert"}
        _profile_l1_cache["tenant-b:user-1"] = {"level": "beginner"}

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()

        mock_redis = MagicMock()
        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            result_a = await service.get_profile_context("user-1", "tenant-a")
            result_b = await service.get_profile_context("user-1", "tenant-b")

        assert result_a["level"] == "expert"
        assert result_b["level"] == "beginner"

        # Cleanup
        del _profile_l1_cache["tenant-a:user-1"]
        del _profile_l1_cache["tenant-b:user-1"]


class TestClearL1Cache:
    """Test GDPR L1 cache clearing."""

    @pytest.mark.asyncio
    async def test_clear_l1_cache_removes_user_entries(self):
        """clear_l1_cache removes all entries for a user across tenants."""
        from app.modules.profile.learning import (
            ProfileLearningService,
            _profile_l1_cache,
        )

        _profile_l1_cache["t1:gdpr-user"] = {"level": "expert"}
        _profile_l1_cache["t2:gdpr-user"] = {"level": "beginner"}
        _profile_l1_cache["t1:other-user"] = {"level": "intermediate"}

        service = ProfileLearningService.__new__(ProfileLearningService)
        await service.clear_l1_cache("gdpr-user")

        assert "t1:gdpr-user" not in _profile_l1_cache
        assert "t2:gdpr-user" not in _profile_l1_cache
        assert "t1:other-user" in _profile_l1_cache

        # Cleanup
        if "t1:other-user" in _profile_l1_cache:
            del _profile_l1_cache["t1:other-user"]


class TestExtractionPrompt:
    """Test profile extraction prompt and constants."""

    def test_extraction_prompt_exists(self):
        """EXTRACTION_PROMPT constant must exist."""
        from app.modules.profile.learning import EXTRACTION_PROMPT

        assert isinstance(EXTRACTION_PROMPT, str)
        assert len(EXTRACTION_PROMPT) > 50

    def test_extraction_prompt_requests_json(self):
        """Extraction prompt must request JSON output."""
        from app.modules.profile.learning import EXTRACTION_PROMPT

        assert "json" in EXTRACTION_PROMPT.lower() or "JSON" in EXTRACTION_PROMPT

    def test_extraction_prompt_mentions_required_fields(self):
        """Extraction prompt must mention all required profile fields."""
        from app.modules.profile.learning import EXTRACTION_PROMPT

        assert "technical_level" in EXTRACTION_PROMPT
        assert "communication_style" in EXTRACTION_PROMPT
        assert "interests" in EXTRACTION_PROMPT
        assert "expertise_areas" in EXTRACTION_PROMPT
        assert "common_tasks" in EXTRACTION_PROMPT

    def test_learn_trigger_threshold_is_10(self):
        """Default learn trigger threshold must be 10 queries."""
        from app.modules.profile.learning import LEARN_TRIGGER_THRESHOLD

        assert LEARN_TRIGGER_THRESHOLD == 10


class TestCounterCheckpoint:
    """Test INFRA-032: Redis counter write-back to PostgreSQL."""

    @pytest.mark.asyncio
    async def test_checkpoint_called_on_trigger(self):
        """When counter reaches threshold (10), _checkpoint_counter_to_db is called."""
        from app.modules.profile.learning import ProfileLearningService

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()
        service._run_profile_extraction = AsyncMock()
        service._checkpoint_counter_to_db = AsyncMock()
        service._seed_counter_from_db = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=10)
        mock_redis.expire = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            await service.on_query_completed("u1", "t1", "a1")

        service._checkpoint_counter_to_db.assert_called_once_with("u1", "t1")

    @pytest.mark.asyncio
    async def test_checkpoint_no_db_session_is_noop(self):
        """When db is None, _checkpoint_counter_to_db is silently skipped."""
        from app.modules.profile.learning import ProfileLearningService

        service = ProfileLearningService(db_session=None)

        # Should not raise — just return silently
        await service._checkpoint_counter_to_db("u1", "t1")

    @pytest.mark.asyncio
    async def test_checkpoint_db_failure_suppressed(self):
        """DB error in _checkpoint_counter_to_db is suppressed (warning logged, no raise)."""
        from app.modules.profile.learning import ProfileLearningService

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("DB connection lost"))

        service = ProfileLearningService(db_session=mock_db)

        # Must not raise
        await service._checkpoint_counter_to_db("u1", "t1")

        # DB execute was attempted
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_checkpoint_upserts_with_threshold_increment(self):
        """Checkpoint upserts query_count by adding LEARN_TRIGGER_THRESHOLD to existing value."""
        from app.modules.profile.learning import (
            LEARN_TRIGGER_THRESHOLD,
            ProfileLearningService,
        )

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        service = ProfileLearningService(db_session=mock_db)

        await service._checkpoint_counter_to_db("user-1", "tenant-1")

        # Verify the SQL was called with parameterized values
        call_args = mock_db.execute.call_args
        sql_params = call_args[0][1]
        assert sql_params["user_id"] == "user-1"
        assert sql_params["tenant_id"] == "tenant-1"
        assert sql_params["threshold"] == LEARN_TRIGGER_THRESHOLD
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_seed_from_db_on_fresh_counter(self):
        """When INCR returns 1, _seed_counter_from_db is called to restore position."""
        from app.modules.profile.learning import ProfileLearningService

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()
        service._run_profile_extraction = AsyncMock()
        service._checkpoint_counter_to_db = AsyncMock()
        service._seed_counter_from_db = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            await service.on_query_completed("u1", "t1", "a1")

        counter_key = "mingai:t1:profile_learning:query_count:u1"
        service._seed_counter_from_db.assert_called_once_with(
            "u1", "t1", mock_redis, counter_key
        )

    @pytest.mark.asyncio
    async def test_seed_not_called_when_count_not_1(self):
        """When INCR returns > 1, _seed_counter_from_db is NOT called."""
        from app.modules.profile.learning import ProfileLearningService

        service = ProfileLearningService.__new__(ProfileLearningService)
        service._db = AsyncMock()
        service._run_profile_extraction = AsyncMock()
        service._checkpoint_counter_to_db = AsyncMock()
        service._seed_counter_from_db = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=5)
        mock_redis.expire = AsyncMock()

        with patch("app.modules.profile.learning.get_redis", return_value=mock_redis):
            await service.on_query_completed("u1", "t1", "a1")

        service._seed_counter_from_db.assert_not_called()

    @pytest.mark.asyncio
    async def test_seed_skips_when_db_is_none(self):
        """When db is None, _seed_counter_from_db is skipped gracefully."""
        from app.modules.profile.learning import ProfileLearningService

        service = ProfileLearningService(db_session=None)
        mock_redis = AsyncMock()

        # Should not raise
        await service._seed_counter_from_db("u1", "t1", mock_redis, "some:key")

        # Redis set should NOT be called (nothing to seed)
        mock_redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_seed_no_checkpoint_is_noop(self):
        """When PostgreSQL has no row for user, seed does nothing to Redis."""
        from app.modules.profile.learning import ProfileLearningService

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ProfileLearningService(db_session=mock_db)
        mock_redis = AsyncMock()

        await service._seed_counter_from_db("u1", "t1", mock_redis, "some:key")

        # No checkpoint found — Redis should NOT be updated
        mock_redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_seed_sets_modular_position(self):
        """When PostgreSQL has checkpoint=23, Redis is set to 23 % 10 = 3."""
        from app.modules.profile.learning import ProfileLearningService

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (23,)
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ProfileLearningService(db_session=mock_db)
        mock_redis = AsyncMock()

        await service._seed_counter_from_db("u1", "t1", mock_redis, "some:counter:key")

        # 23 % 10 = 3 — set Redis counter to 3
        mock_redis.set.assert_called_once_with("some:counter:key", 3)

    @pytest.mark.asyncio
    async def test_seed_zero_modular_position_not_set(self):
        """When PostgreSQL has checkpoint=20, modular position is 0 — no Redis set needed."""
        from app.modules.profile.learning import ProfileLearningService

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (20,)
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ProfileLearningService(db_session=mock_db)
        mock_redis = AsyncMock()

        await service._seed_counter_from_db("u1", "t1", mock_redis, "some:key")

        # 20 % 10 = 0 — no need to set, counter already at correct position
        mock_redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_seed_db_failure_suppressed(self):
        """DB error in _seed_counter_from_db is suppressed (warning logged, no raise)."""
        from app.modules.profile.learning import ProfileLearningService

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("DB timeout"))

        service = ProfileLearningService(db_session=mock_db)
        mock_redis = AsyncMock()

        # Must not raise
        await service._seed_counter_from_db("u1", "t1", mock_redis, "some:key")

        # Redis should NOT be touched on DB failure
        mock_redis.set.assert_not_called()
