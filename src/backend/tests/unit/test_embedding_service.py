"""
Unit tests for EmbeddingService (AI-054).

Tests embedding generation, Redis caching, and model configuration.
Tier 1: Fast, isolated, mocks OpenAI API calls.
"""
import hashlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestEmbeddingServiceInit:
    """Test EmbeddingService initialization and configuration."""

    def test_embedding_model_from_env(self):
        """Embedding model must come from EMBEDDING_MODEL env var."""
        with patch.dict(os.environ, {"EMBEDDING_MODEL": "text-embedding-3-small"}):
            from app.modules.chat.embedding import EmbeddingService

            service = EmbeddingService.__new__(EmbeddingService)
            # The model should be read from env, not hardcoded
            assert os.environ["EMBEDDING_MODEL"] == "text-embedding-3-small"

    def test_embedding_model_raises_if_empty(self):
        """Embedding service must raise if EMBEDDING_MODEL is not set."""
        from app.modules.chat.embedding import EmbeddingService

        with patch.dict(os.environ, {"EMBEDDING_MODEL": ""}, clear=False):
            with pytest.raises((ValueError, RuntimeError)):
                EmbeddingService()


class TestEmbedMethod:
    """Test the embed() method."""

    @pytest.mark.asyncio
    async def test_embed_returns_float_list(self):
        """embed() returns a list of floats (the embedding vector)."""
        from app.modules.chat.embedding import EmbeddingService

        mock_vector = [0.1, 0.2, 0.3, 0.4, 0.5]

        service = EmbeddingService.__new__(EmbeddingService)
        service._model = "test-model"

        # Mock the OpenAI client
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=mock_vector)]
        service._client = AsyncMock()
        service._client.embeddings.create = AsyncMock(return_value=mock_response)

        result = await service.embed("test query")
        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)
        assert result == mock_vector

    @pytest.mark.asyncio
    async def test_embed_uses_configured_model(self):
        """embed() passes the configured model to OpenAI API."""
        from app.modules.chat.embedding import EmbeddingService

        service = EmbeddingService.__new__(EmbeddingService)
        service._model = "custom-embedding-model"

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1])]
        service._client = AsyncMock()
        service._client.embeddings.create = AsyncMock(return_value=mock_response)

        await service.embed("test query")

        service._client.embeddings.create.assert_called_once_with(
            model="custom-embedding-model",
            input="test query",
        )

    @pytest.mark.asyncio
    async def test_embed_empty_text_raises(self):
        """embed() raises ValueError for empty text input."""
        from app.modules.chat.embedding import EmbeddingService

        service = EmbeddingService.__new__(EmbeddingService)
        service._model = "test-model"
        service._client = AsyncMock()

        with pytest.raises(ValueError, match="[Ee]mpty|[Bb]lank|[Tt]ext"):
            await service.embed("")

    @pytest.mark.asyncio
    async def test_embed_none_text_raises(self):
        """embed() raises ValueError for None text input."""
        from app.modules.chat.embedding import EmbeddingService

        service = EmbeddingService.__new__(EmbeddingService)
        service._model = "test-model"
        service._client = AsyncMock()

        with pytest.raises((ValueError, TypeError)):
            await service.embed(None)


class TestEmbeddingCaching:
    """Test Redis caching for embeddings (CACHE-002: float16 binary, 7-day TTL)."""

    @pytest.mark.asyncio
    async def test_cached_result_returned_without_api_call(self):
        """If Redis has a cached embedding (float16 bytes), do not call OpenAI API."""
        import struct

        from app.modules.chat.embedding import EmbeddingService, _serialize_float16

        cached_vector = [0.5, 0.6, 0.7]
        # CACHE-002: stored as float16 binary bytes, not JSON
        cached_bytes = _serialize_float16(cached_vector)

        service = EmbeddingService.__new__(EmbeddingService)
        service._model = "test-model"
        service._client = AsyncMock()
        service._instrumented_client = None

        mock_redis = AsyncMock()
        # get() returns bytes (float16 binary)
        mock_redis.get = AsyncMock(return_value=cached_bytes)

        with patch("app.modules.chat.embedding.get_redis_binary", return_value=mock_redis):
            result = await service.embed("test query", tenant_id="tenant-abc")

        # Result should be float32 list recovered from float16
        assert len(result) == len(cached_vector)
        for orig, rec in zip(cached_vector, result):
            assert abs(orig - rec) < 0.01, f"float16 precision error: {orig} vs {rec}"
        service._client.embeddings.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_calls_api_and_stores(self):
        """On cache miss, call OpenAI API and store result via _set_binary."""
        from app.modules.chat.embedding import EmbeddingService

        new_vector = [0.1, 0.2, 0.3]

        service = EmbeddingService.__new__(EmbeddingService)
        service._model = "test-model"
        service._instrumented_client = None

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=new_vector)]
        service._client = AsyncMock()
        service._client.embeddings.create = AsyncMock(return_value=mock_response)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # Cache miss
        mock_redis.setex = AsyncMock()

        # CACHE-002: storage via redis.setex on cache miss
        with patch(
            "app.modules.chat.embedding.get_redis_binary", return_value=mock_redis
        ):
            result = await service.embed("test query", tenant_id="tenant-abc")

        assert result == new_vector
        service._client.embeddings.create.assert_called_once()
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_key_uses_emb_prefix(self):
        """CACHE-002: Cache key format is mingai:{tenant_id}:emb:{model_id}:{hash}."""
        from app.modules.chat.embedding import EmbeddingService

        service = EmbeddingService.__new__(EmbeddingService)
        service._model = "test-model"
        service._instrumented_client = None

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1])]
        service._client = AsyncMock()
        service._client.embeddings.create = AsyncMock(return_value=mock_response)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.chat.embedding.get_redis_binary", return_value=mock_redis
        ):
            await service.embed("test query", tenant_id="my-tenant")

        cache_key = mock_redis.get.call_args[0][0]
        # CACHE-002: key is mingai:{tenant}:emb:{model}:{hash}
        assert cache_key.startswith("mingai:my-tenant:emb:")
        assert "test-model" in cache_key

    @pytest.mark.asyncio
    async def test_cache_ttl_is_7_days(self):
        """CACHE-002: Embedding cache TTL must be 604800 seconds (7 days)."""
        from app.modules.chat.embedding import (
            EmbeddingService,
            EMBEDDING_CACHE_TTL_SECONDS,
        )

        assert EMBEDDING_CACHE_TTL_SECONDS == 604800

        service = EmbeddingService.__new__(EmbeddingService)
        service._model = "test-model"
        service._instrumented_client = None

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1])]
        service._client = AsyncMock()
        service._client.embeddings.create = AsyncMock(return_value=mock_response)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.chat.embedding.get_redis_binary", return_value=mock_redis
        ):
            await service.embed("query", tenant_id="t1")

        # redis.setex(key, ttl, value) — TTL is arg index 1 (0-based)
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args[0]
        assert call_args[1] == 604800

    @pytest.mark.asyncio
    async def test_no_caching_without_tenant_id(self):
        """Without tenant_id, no Redis caching (direct API call only)."""
        from app.modules.chat.embedding import EmbeddingService

        service = EmbeddingService.__new__(EmbeddingService)
        service._model = "test-model"

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1])]
        service._client = AsyncMock()
        service._client.embeddings.create = AsyncMock(return_value=mock_response)

        # No Redis mock needed - should not be called
        result = await service.embed("query")  # No tenant_id

        assert result == [0.1]
        service._client.embeddings.create.assert_called_once()
