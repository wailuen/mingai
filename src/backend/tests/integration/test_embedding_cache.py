"""
TEST-011: Embedding cache float16 compression integration tests (Tier 2).

Tests the Redis caching layer of EmbeddingService. The LLM API client
(AsyncOpenAI / AsyncAzureOpenAI) is the ONLY thing mocked -- this is
Tier 1 boundary mocking of an external API, not internal mocking. The
integration point under test is the Redis caching behavior.

NO internal mocking of EmbeddingService, Redis, or any SDK component.

Requires: Redis (REDIS_URL from .env).
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import os
import re
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import app.core.redis_client as redis_client_module
from app.core.redis_client import get_redis_binary
from app.modules.chat.embedding import (
    EMBEDDING_CACHE_TTL_SECONDS,
    EmbeddingService,
    _deserialize_float16,
)

# Model used in the embedding_service fixture
_FIXTURE_MODEL = "text-embedding-3-small"


def _unique_tenant() -> str:
    return f"test-tenant-{uuid.uuid4().hex[:12]}"


# A known 8-dimensional vector for deterministic testing
_KNOWN_VECTOR = [
    0.123456789,
    -0.987654321,
    0.555555555,
    0.111111111,
    -0.333333333,
    0.777777777,
    -0.222222222,
    0.444444444,
]


def _make_embedding_response(vector: list[float]):
    """Build a fake OpenAI embeddings.create() response object."""
    embedding_obj = SimpleNamespace(embedding=vector)
    return SimpleNamespace(data=[embedding_obj])


def _approx_equal(a: list[float], b: list[float], tol: float = 0.01) -> bool:
    """Compare two float vectors approximately (needed for float16 precision)."""
    if len(a) != len(b):
        return False
    return all(abs(x - y) < tol for x, y in zip(a, b))


@pytest.fixture(autouse=True)
async def _reset_redis_pool():
    """Reset Redis pool per test to avoid event loop binding issues."""
    redis_client_module._redis_pool = None
    redis_client_module._redis_binary_pool = None
    yield
    if redis_client_module._redis_pool is not None:
        await redis_client_module._redis_pool.aclose()
        redis_client_module._redis_pool = None
    if redis_client_module._redis_binary_pool is not None:
        await redis_client_module._redis_binary_pool.aclose()
        redis_client_module._redis_binary_pool = None


@pytest.fixture
def mock_openai_client():
    """
    Provide a mock AsyncOpenAI client that returns a known vector.
    This is Tier 1 boundary mocking -- only the external LLM API is mocked.
    """
    client = AsyncMock()
    client.embeddings.create = AsyncMock(
        return_value=_make_embedding_response(_KNOWN_VECTOR)
    )
    return client


@pytest.fixture
def embedding_service(mock_openai_client):
    """
    Create an EmbeddingService with the mocked OpenAI client injected.
    EMBEDDING_MODEL must be set in env (loaded by conftest from .env).
    """
    with patch.dict(
        os.environ,
        {
            "CLOUD_PROVIDER": "local",
            "EMBEDDING_MODEL": _FIXTURE_MODEL,
            "OPENAI_API_KEY": "sk-test-not-real-key-for-integration-tests",
        },
    ):
        svc = EmbeddingService()
        svc._client = mock_openai_client
    return svc


# =========================================================================
# TEST-011-01: Cache miss -> cache set
# =========================================================================


async def test_cache_miss_stores_result_in_redis(embedding_service, mock_openai_client):
    """First call for text stores the embedding in Redis at the correct key."""
    tenant_id = _unique_tenant()
    text_input = "What is the refund policy?"

    result = await embedding_service.embed(text_input, tenant_id=tenant_id)

    # LLM was called exactly once
    mock_openai_client.embeddings.create.assert_called_once()

    # Result matches our known vector (approximately — float16 precision loss)
    assert _approx_equal(result, _KNOWN_VECTOR), (
        f"Result vector should approximately match known vector"
    )

    # Verify Redis has the cached value (binary pool — cache uses float16 bytes)
    redis = get_redis_binary()
    cache_key = EmbeddingService._build_cache_key(
        tenant_id, text_input, embedding_service._model
    )
    cached_raw = await redis.get(cache_key)
    assert cached_raw is not None, "Embedding should be cached in Redis after first call"

    # Cache is stored as float16 binary — deserialize and compare approximately
    cached_vector = _deserialize_float16(cached_raw)
    assert _approx_equal(cached_vector, _KNOWN_VECTOR), (
        "Cached vector should approximately match known vector"
    )

    # Cleanup
    await redis.delete(cache_key)


# =========================================================================
# TEST-011-02: Cache hit -> no LLM call
# =========================================================================


async def test_cache_hit_returns_from_redis_no_llm_call(
    embedding_service, mock_openai_client
):
    """Second call for same text returns from Redis; LLM is not called again."""
    tenant_id = _unique_tenant()
    text_input = "How do I reset my password?"

    # First call -- cache miss, LLM called
    result1 = await embedding_service.embed(text_input, tenant_id=tenant_id)
    assert mock_openai_client.embeddings.create.call_count == 1

    # Second call -- cache hit, LLM NOT called
    result2 = await embedding_service.embed(text_input, tenant_id=tenant_id)
    assert (
        mock_openai_client.embeddings.create.call_count == 1
    ), "LLM should not be called on cache hit"

    assert _approx_equal(result1, result2), "Both calls should return same vector"

    # Cleanup
    redis = get_redis_binary()
    cache_key = EmbeddingService._build_cache_key(
        tenant_id, text_input, embedding_service._model
    )
    await redis.delete(cache_key)


# =========================================================================
# TEST-011-03: Cache key includes tenant isolation
# =========================================================================


async def test_cache_key_includes_tenant_isolation(
    embedding_service, mock_openai_client
):
    """Same text with different tenant_ids produces different Redis keys."""
    tenant_a = _unique_tenant()
    tenant_b = _unique_tenant()
    text_input = "Shared query across tenants"

    # Embed for tenant A
    await embedding_service.embed(text_input, tenant_id=tenant_a)

    # Embed for tenant B -- should also call LLM (different cache key)
    await embedding_service.embed(text_input, tenant_id=tenant_b)

    assert (
        mock_openai_client.embeddings.create.call_count == 2
    ), "LLM should be called once per tenant (different cache keys)"

    # Verify different Redis keys
    model = embedding_service._model
    key_a = EmbeddingService._build_cache_key(tenant_a, text_input, model)
    key_b = EmbeddingService._build_cache_key(tenant_b, text_input, model)
    assert key_a != key_b, "Cache keys for different tenants must differ"

    redis = get_redis_binary()
    assert await redis.get(key_a) is not None
    assert await redis.get(key_b) is not None

    # Cleanup
    await redis.delete(key_a, key_b)


# =========================================================================
# TEST-011-04: Cache key structure validation
# =========================================================================


async def test_cache_key_includes_model_in_hash(embedding_service):
    """
    The cache key format is: mingai:{tenant_id}:emb:{safe_model_id}:{sha256(text)}
    Verify that the key structure is deterministic and contains the model.
    """
    tenant_id = _unique_tenant()
    text_input = "What are the pricing tiers?"
    model = embedding_service._model  # "text-embedding-3-small"

    key = EmbeddingService._build_cache_key(tenant_id, text_input, model)

    # Key format: mingai:{tenant_id}:emb:{safe_model_id}:{sha256_hex}
    expected_hash = hashlib.sha256(text_input.encode()).hexdigest()
    # The model is sanitized: hyphens/dots stay, other special chars become _
    assert key.startswith(f"mingai:{tenant_id}:emb:")
    assert key.endswith(f":{expected_hash}")
    assert "text-embedding-3-small" in key or "text_embedding_3_small" in key

    # Different text -> different key
    key2 = EmbeddingService._build_cache_key(tenant_id, "Different text entirely", model)
    assert key != key2, "Different texts must produce different cache keys"

    # Different model -> different key
    key3 = EmbeddingService._build_cache_key(tenant_id, text_input, "other-model")
    assert key != key3, "Different models must produce different cache keys"


# =========================================================================
# TEST-011-05: 7-day TTL set (CACHE-002: changed from 24h to 7 days)
# =========================================================================


async def test_24_hour_ttl_set_after_cache_write(embedding_service, mock_openai_client):
    """After caching an embedding, Redis TTL is approximately EMBEDDING_CACHE_TTL_SECONDS."""
    tenant_id = _unique_tenant()
    text_input = "TTL verification query"

    await embedding_service.embed(text_input, tenant_id=tenant_id)

    redis = get_redis_binary()
    cache_key = EmbeddingService._build_cache_key(
        tenant_id, text_input, embedding_service._model
    )
    ttl = await redis.ttl(cache_key)

    # TTL should be close to EMBEDDING_CACHE_TTL_SECONDS (allow 10s tolerance)
    assert ttl > 0, "TTL should be positive"
    assert (
        abs(ttl - EMBEDDING_CACHE_TTL_SECONDS) < 10
    ), f"TTL should be ~{EMBEDDING_CACHE_TTL_SECONDS}s, got {ttl}s"

    # Cleanup
    await redis.delete(cache_key)


# =========================================================================
# TEST-011-06: Float16 round-trip precision
# =========================================================================


async def test_float16_roundtrip_precision(embedding_service, mock_openai_client):
    """
    Store a known float32 vector via the embedding service, retrieve it
    from Redis cache, and verify cosine distance from original is < 0.001.

    Note: the EmbeddingService stores vectors as float16 binary, so there is
    some precision loss. The round-trip cosine distance should still be < 0.001.
    """
    tenant_id = _unique_tenant()
    text_input = "Precision test query"

    # Use a more realistic 16-dim vector with varied magnitudes
    original_vector = [
        0.0234375,
        -0.98765432,
        0.12345678,
        0.55555556,
        -0.33333333,
        0.77777778,
        -0.22222222,
        0.44444444,
        0.99999999,
        -0.00000001,
        0.50000000,
        -0.50000000,
        0.11111111,
        -0.88888889,
        0.66666667,
        -0.66666667,
    ]
    mock_openai_client.embeddings.create.return_value = _make_embedding_response(
        original_vector
    )

    # First call: cache miss -> stores in Redis
    result1 = await embedding_service.embed(text_input, tenant_id=tenant_id)

    # Second call: cache hit -> retrieves from Redis
    result2 = await embedding_service.embed(text_input, tenant_id=tenant_id)

    # Compute cosine distance between original and cache-retrieved vectors
    def _cosine_distance(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 1.0
        similarity = dot / (norm_a * norm_b)
        return 1.0 - similarity

    distance = _cosine_distance(original_vector, result2)
    assert (
        distance < 0.001
    ), f"Cosine distance after round-trip should be < 0.001, got {distance}"

    # Cleanup
    redis = get_redis_binary()
    cache_key = EmbeddingService._build_cache_key(
        tenant_id, text_input, embedding_service._model
    )
    await redis.delete(cache_key)


# =========================================================================
# TEST-011-07: Cache expiry
# =========================================================================


async def test_cache_expiry_returns_miss(embedding_service, mock_openai_client):
    """Set embedding with very short TTL, wait for expiry, verify cache miss."""
    tenant_id = _unique_tenant()
    text_input = "Expiry test query"

    # First call caches with default TTL
    await embedding_service.embed(text_input, tenant_id=tenant_id)
    assert mock_openai_client.embeddings.create.call_count == 1

    # Manually override the TTL to 1 second
    redis = get_redis_binary()
    cache_key = EmbeddingService._build_cache_key(
        tenant_id, text_input, embedding_service._model
    )
    await redis.expire(cache_key, 1)

    # Wait for expiry
    await asyncio.sleep(2.0)

    # Verify cache miss -- key should be gone
    cached = await redis.get(cache_key)
    assert cached is None, "Cache entry should have expired"

    # Next embed call should hit LLM again
    await embedding_service.embed(text_input, tenant_id=tenant_id)
    assert (
        mock_openai_client.embeddings.create.call_count == 2
    ), "LLM should be called again after cache expiry"

    # Cleanup
    await redis.delete(cache_key)


# =========================================================================
# TEST-011-08: Batch embedding -- each text cached individually
# =========================================================================


async def test_batch_embedding_caches_individually(
    embedding_service, mock_openai_client
):
    """Embed multiple texts; verify each is cached as a separate Redis key."""
    tenant_id = _unique_tenant()
    texts = [
        "What is the return policy?",
        "How do I contact support?",
        "Where is my order?",
    ]

    # Generate unique vectors per text (so we can verify correct retrieval)
    vectors = {
        texts[0]: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
        texts[1]: [0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1],
        texts[2]: [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
    }

    # Configure mock to return the right vector for each call
    call_index = 0

    async def _side_effect(**kwargs):
        nonlocal call_index
        input_text = kwargs.get("input", "")
        vec = vectors.get(input_text, _KNOWN_VECTOR)
        call_index += 1
        return _make_embedding_response(vec)

    mock_openai_client.embeddings.create.side_effect = _side_effect

    # Embed all texts
    results = {}
    for t in texts:
        results[t] = await embedding_service.embed(t, tenant_id=tenant_id)

    # LLM called once per text
    assert call_index == 3

    # Verify each is cached individually in Redis
    redis = get_redis_binary()
    model = embedding_service._model
    for t in texts:
        cache_key = EmbeddingService._build_cache_key(tenant_id, t, model)
        cached_raw = await redis.get(cache_key)
        assert cached_raw is not None, f"Text '{t}' should be cached"
        # Deserialize float16 binary and compare approximately
        cached_vector = _deserialize_float16(cached_raw)
        assert _approx_equal(cached_vector, vectors[t]), (
            f"Cached vector for '{t}' should approximately match the original"
        )

    # Verify cache hits on second pass
    mock_openai_client.embeddings.create.side_effect = None
    mock_openai_client.embeddings.create.reset_mock()

    for t in texts:
        result = await embedding_service.embed(t, tenant_id=tenant_id)
        assert _approx_equal(result, vectors[t]), (
            f"Cache hit for '{t}' should return approximately correct vector"
        )

    mock_openai_client.embeddings.create.assert_not_called()

    # Cleanup
    for t in texts:
        cache_key = EmbeddingService._build_cache_key(tenant_id, t, model)
        await redis.delete(cache_key)
