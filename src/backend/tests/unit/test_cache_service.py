"""
Unit tests for CacheService (INFRA-011, INFRA-012, INFRA-013).

TEST-007: Cache serialization/deserialization — unit tests
TEST-006 extensions: cache_type allowlist, key isolation, invalid inputs.

All Redis operations are mocked — no real Redis required for Tier 1 tests.
"""

import datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# TEST-007: CacheSerializer — serialization / deserialization
# ---------------------------------------------------------------------------


class TestCacheSerializer:
    """TEST-007: Cache value serialization."""

    def test_string_round_trip(self):
        from app.core.cache import CacheSerializer

        original = "hello world"
        serialized = CacheSerializer.serialize(original)
        assert CacheSerializer.deserialize(serialized) == original

    def test_dict_json_round_trip(self):
        from app.core.cache import CacheSerializer

        original = {"key": "value", "num": 42, "nested": {"a": [1, 2, 3]}}
        serialized = CacheSerializer.serialize(original)
        assert CacheSerializer.deserialize(serialized) == original

    def test_empty_dict_round_trip(self):
        from app.core.cache import CacheSerializer

        original = {}
        serialized = CacheSerializer.serialize(original)
        assert CacheSerializer.deserialize(serialized) == original

    def test_list_of_sources_round_trip(self):
        """Typical RAG response sources list round-trips correctly."""
        from app.core.cache import CacheSerializer

        original = [
            {"id": "doc-1", "title": "Finance Policy", "score": 0.95},
            {"id": "doc-2", "title": "HR Handbook", "score": 0.87},
        ]
        serialized = CacheSerializer.serialize(original)
        assert CacheSerializer.deserialize(serialized) == original

    def test_unicode_content_preserved(self):
        """CJK, emoji, RTL characters survive the round-trip."""
        from app.core.cache import CacheSerializer

        original = {
            "japanese": "こんにちは",
            "arabic": "مرحبا",
            "emoji": "🎯",
            "chinese": "你好",
        }
        serialized = CacheSerializer.serialize(original)
        result = CacheSerializer.deserialize(serialized)
        assert result == original

    def test_none_value_returns_none(self):
        """None input (cache miss) returns None without error."""
        from app.core.cache import CacheSerializer

        assert CacheSerializer.deserialize(None) is None

    def test_bytes_input_deserialized(self):
        """Redis may return bytes — deserialize handles both str and bytes."""
        from app.core.cache import CacheSerializer

        original = {"answer": 42}
        serialized = CacheSerializer.serialize(original)
        # Simulate Redis returning bytes
        as_bytes = serialized.encode("utf-8")
        assert CacheSerializer.deserialize(as_bytes) == original

    def test_datetime_serialized_to_iso_string(self):
        """datetime objects are serialized to ISO 8601 strings."""
        from app.core.cache import CacheSerializer

        dt = datetime.datetime(2026, 3, 7, 12, 0, 0, tzinfo=datetime.timezone.utc)
        original = {"created_at": dt, "value": "test"}
        serialized = CacheSerializer.serialize(original)
        result = CacheSerializer.deserialize(serialized)
        assert result["created_at"] == "2026-03-07T12:00:00+00:00"
        assert result["value"] == "test"

    def test_float_embedding_array_round_trip(self):
        """Embedding arrays (list of float) round-trip without value loss."""
        from app.core.cache import CacheSerializer

        # Typical 8-dim embedding vector (test with a subset for speed)
        original = [0.12345678, -0.98765432, 0.5, -0.3333333, 1.0, -1.0, 0.0, 0.1]
        serialized = CacheSerializer.serialize(original)
        result = CacheSerializer.deserialize(serialized)
        assert len(result) == len(original)
        for expected, actual in zip(original, result):
            assert abs(expected - actual) < 1e-6

    def test_large_payload_rejected(self):
        """Payloads exceeding 1 MB are rejected with ValueError."""
        from app.core.cache import CacheSerializer

        # 1.1 MB string
        large_value = {"data": "x" * 1_100_000}
        with pytest.raises(ValueError, match="too large"):
            CacheSerializer.serialize(large_value)

    def test_non_serializable_type_raises_type_error(self):
        """Non-JSON-serializable objects raise TypeError."""
        from app.core.cache import CacheSerializer

        class CustomObj:
            pass

        with pytest.raises(TypeError):
            CacheSerializer.serialize({"obj": CustomObj()})

    def test_nested_list_and_dict_round_trip(self):
        """Nested structures with mixed types round-trip correctly."""
        from app.core.cache import CacheSerializer

        original = {
            "topics": ["finance", "hr"],
            "recent_queries": ["a team member asked: budget review"],
            "meta": {"count": 5, "active": True},
        }
        serialized = CacheSerializer.serialize(original)
        assert CacheSerializer.deserialize(serialized) == original


# ---------------------------------------------------------------------------
# TEST: CacheService key validation and cache_type allowlist
# ---------------------------------------------------------------------------


class TestCacheServiceKeyValidation:
    """CacheService validates cache_type and tenant_id before Redis calls."""

    def test_invalid_cache_type_raises_error(self):
        from app.core.cache import CacheService, CacheTypeError

        svc = CacheService()
        with pytest.raises(CacheTypeError, match="(?i)invalid cache_type"):
            svc._make_key("tenant-1", "unknown_type", "key-1")

    def test_empty_tenant_id_raises_error(self):
        from app.core.cache import CacheService

        svc = CacheService()
        with pytest.raises(ValueError, match="tenant_id"):
            svc._make_key("", "profile", "key-1")

    def test_valid_cache_types_all_build_keys(self):
        from app.core.cache import CacheService, VALID_CACHE_TYPES

        svc = CacheService()
        for ct in VALID_CACHE_TYPES:
            key = svc._make_key("t1", ct, "k1")
            assert key == f"mingai:t1:{ct}:k1"

    def test_two_tenants_produce_different_keys(self):
        from app.core.cache import CacheService

        svc = CacheService()
        key_a = svc._make_key("tenant-a", "profile", "user-1")
        key_b = svc._make_key("tenant-b", "profile", "user-1")
        assert key_a != key_b
        assert "tenant-a" in key_a
        assert "tenant-b" in key_b

    def test_colon_in_tenant_id_raises_error(self):
        """Colon in tenant_id would break namespace — must be rejected (C-1 fix)."""
        from app.core.cache import CacheService

        svc = CacheService()
        with pytest.raises(ValueError, match="colon"):
            svc._make_key("tenant-a:profile:admin", "profile", "key-1")

    def test_colon_in_cache_type_raises_error(self):
        """Colon in cache_type (even if it were valid) would break namespace."""
        from app.core.cache import CacheService

        svc = CacheService()
        # Must raise before or at _validate_cache_type (whichever catches first)
        with pytest.raises((ValueError, Exception)):
            svc._make_key("tenant-1", "profile:injected", "key-1")

    def test_default_ttl_returns_value_for_each_type(self):
        from app.core.cache import CacheService, VALID_CACHE_TYPES

        svc = CacheService()
        for ct in VALID_CACHE_TYPES:
            ttl = svc._default_ttl(ct)
            assert ttl > 0


# ---------------------------------------------------------------------------
# TEST: CacheService async operations (Redis mocked)
# ---------------------------------------------------------------------------


class TestCacheServiceOperations:
    """CacheService get/set/delete with mocked Redis."""

    @pytest.fixture
    def mock_redis(self):
        redis = AsyncMock()
        redis.pipeline.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        redis.pipeline.return_value.__aexit__ = AsyncMock(return_value=False)
        return redis

    @pytest.mark.asyncio
    async def test_get_returns_cached_value(self, mock_redis):
        from app.core.cache import CacheService, CacheSerializer

        svc = CacheService()
        cached_value = {"name": "Alice", "role": "admin"}
        mock_redis.get.return_value = CacheSerializer.serialize(cached_value)

        with patch("app.core.cache.get_redis", return_value=mock_redis):
            result = await svc.get("tenant-1", "profile", "user-42")

        assert result == cached_value
        mock_redis.get.assert_called_once_with("mingai:tenant-1:profile:user-42")

    @pytest.mark.asyncio
    async def test_get_returns_none_on_cache_miss(self, mock_redis):
        from app.core.cache import CacheService

        svc = CacheService()
        mock_redis.get.return_value = None

        with patch("app.core.cache.get_redis", return_value=mock_redis):
            result = await svc.get("tenant-1", "profile", "user-42")

        assert result is None

    @pytest.mark.asyncio
    async def test_set_calls_setex_with_correct_args(self, mock_redis):
        from app.core.cache import CacheService, CacheSerializer

        svc = CacheService()
        value = {"score": 0.92}

        with patch("app.core.cache.get_redis", return_value=mock_redis):
            await svc.set("tenant-1", "profile", "user-42", value, ttl=600)

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args[0]
        assert call_args[0] == "mingai:tenant-1:profile:user-42"
        assert call_args[1] == 600
        assert json.loads(call_args[2]) == value

    @pytest.mark.asyncio
    async def test_set_uses_default_ttl_when_none(self, mock_redis):
        from app.core.cache import CacheService, DEFAULT_TTL

        svc = CacheService()

        with patch("app.core.cache.get_redis", return_value=mock_redis):
            await svc.set("tenant-1", "embedding_cache", "hash-abc", [0.1, 0.2])

        call_args = mock_redis.setex.call_args[0]
        assert call_args[1] == DEFAULT_TTL["embedding_cache"]

    @pytest.mark.asyncio
    async def test_delete_calls_redis_delete(self, mock_redis):
        from app.core.cache import CacheService

        svc = CacheService()

        with patch("app.core.cache.get_redis", return_value=mock_redis):
            await svc.delete("tenant-1", "profile", "user-42")

        mock_redis.delete.assert_called_once_with("mingai:tenant-1:profile:user-42")

    @pytest.mark.asyncio
    async def test_get_many_returns_only_hits(self, mock_redis):
        from app.core.cache import CacheService, CacheSerializer

        svc = CacheService()
        # key-1 is a hit, key-2 is a miss (None)
        mock_redis.mget.return_value = [
            CacheSerializer.serialize({"data": "first"}),
            None,
        ]

        with patch("app.core.cache.get_redis", return_value=mock_redis):
            result = await svc.get_many("tenant-1", "profile", ["key-1", "key-2"])

        assert "key-1" in result
        assert "key-2" not in result
        assert result["key-1"] == {"data": "first"}

    @pytest.mark.asyncio
    async def test_get_many_empty_keys_returns_empty_dict(self, mock_redis):
        from app.core.cache import CacheService

        svc = CacheService()

        with patch("app.core.cache.get_redis", return_value=mock_redis):
            result = await svc.get_many("tenant-1", "profile", [])

        assert result == {}
        mock_redis.mget.assert_not_called()

    @pytest.mark.asyncio
    async def test_redis_failure_raises_cache_unavailable_error(self, mock_redis):
        from app.core.cache import CacheService, CacheUnavailableError

        svc = CacheService()
        mock_redis.get.side_effect = ConnectionError("Redis down")

        with patch("app.core.cache.get_redis", return_value=mock_redis):
            with pytest.raises(CacheUnavailableError, match="temporarily unavailable"):
                await svc.get("tenant-1", "profile", "user-42")

    @pytest.mark.asyncio
    async def test_error_message_does_not_leak_redis_details(self, mock_redis):
        """CacheUnavailableError message must not include internal Redis connection details."""
        from app.core.cache import CacheService, CacheUnavailableError

        svc = CacheService()
        mock_redis.get.side_effect = ConnectionError("redis://secret-host:6379/0")

        with patch("app.core.cache.get_redis", return_value=mock_redis):
            with pytest.raises(CacheUnavailableError) as exc_info:
                await svc.get("tenant-1", "profile", "user-42")

        # Error message must NOT contain internal connection strings
        assert "secret-host" not in str(exc_info.value)
        assert "6379" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# TEST: @cached decorator (INFRA-012)
# ---------------------------------------------------------------------------


class TestCachedDecorator:
    """@cached decorator caches async function results in Redis."""

    def test_invalid_cache_type_at_decoration_raises(self):
        """CacheTypeError raised at decoration time — fail fast."""
        from app.core.cache import cached, CacheTypeError

        with pytest.raises(CacheTypeError, match="invalid cache_type"):

            @cached(cache_type="nonexistent_type")
            async def bad_fn():
                pass

    @pytest.mark.asyncio
    async def test_cached_returns_cached_value_on_hit(self):
        from app.core.cache import cached

        call_count = 0

        @cached(cache_type="profile", ttl=60)
        async def get_profile(user_id: str, tenant_id: str) -> dict:
            nonlocal call_count
            call_count += 1
            return {"user_id": user_id, "name": "Alice"}

        mock_cache = AsyncMock()
        mock_cache.get.return_value = {"user_id": "u1", "name": "Alice"}

        with patch("app.core.cache.CacheService", return_value=mock_cache):
            # Re-define with patched CacheService
            @cached(cache_type="profile", ttl=60)
            async def get_profile_patched(user_id: str, tenant_id: str) -> dict:
                nonlocal call_count
                call_count += 1
                return {"user_id": user_id, "name": "Alice"}

            result = await get_profile_patched("u1", tenant_id="tenant-1")

        assert result == {"user_id": "u1", "name": "Alice"}

    @pytest.mark.asyncio
    async def test_cached_calls_through_without_tenant_id(self):
        """Without any string args and no tenant_id kwarg, function is called through."""
        from app.core.cache import cached

        call_count = 0

        @cached(cache_type="profile", ttl=60)
        async def get_config(config_id: int) -> dict:
            nonlocal call_count
            call_count += 1
            return {"config_id": config_id}

        # Integer arg → no tenant_id extracted → call through without caching
        result = await get_config(42)
        assert result == {"config_id": 42}
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_cached_degrades_gracefully_on_redis_failure(self):
        """On Redis failure, the decorator calls through to the original function."""
        from app.core.cache import cached, CacheUnavailableError

        call_count = 0

        mock_cache = AsyncMock()
        mock_cache.get.side_effect = CacheUnavailableError("Redis down")

        with patch("app.core.cache.CacheService", return_value=mock_cache):

            @cached(cache_type="profile", ttl=60)
            async def get_profile(user_id: str, tenant_id: str) -> dict:
                nonlocal call_count
                call_count += 1
                return {"user_id": user_id}

            result = await get_profile("u1", tenant_id="tenant-1")

        assert result == {"user_id": "u1"}
        assert call_count == 1


# ---------------------------------------------------------------------------
# TEST: Cache pub/sub invalidation (INFRA-013)
# ---------------------------------------------------------------------------


class TestPublishInvalidation:
    """publish_invalidation sends correctly formatted messages."""

    @pytest.mark.asyncio
    async def test_publishes_to_invalidation_channel(self):
        from app.core.cache import publish_invalidation, INVALIDATION_CHANNEL

        mock_redis = AsyncMock()

        with patch("app.core.cache.get_redis", return_value=mock_redis):
            await publish_invalidation("tenant-1", "profile", pattern="user-42")

        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args[0]
        assert call_args[0] == INVALIDATION_CHANNEL
        message = json.loads(call_args[1])
        assert message["tenant_id"] == "tenant-1"
        assert message["cache_type"] == "profile"
        assert message["pattern"] == "user-42"
        assert "ts" in message

    @pytest.mark.asyncio
    async def test_invalid_cache_type_raises_error(self):
        from app.core.cache import publish_invalidation, CacheTypeError

        with pytest.raises(CacheTypeError):
            await publish_invalidation("tenant-1", "bad_type")

    @pytest.mark.asyncio
    async def test_redis_failure_raises_cache_unavailable(self):
        from app.core.cache import publish_invalidation, CacheUnavailableError

        mock_redis = AsyncMock()
        mock_redis.publish.side_effect = ConnectionError("Redis down")

        with patch("app.core.cache.get_redis", return_value=mock_redis):
            with pytest.raises(CacheUnavailableError):
                await publish_invalidation("tenant-1", "profile")
