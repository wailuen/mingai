"""
Unit tests for app/core/cache_utils.py and float16 serialization.

Tests:
- normalize_query: canonical form derivation
- Float16 roundtrip: _serialize_float16 / _deserialize_float16
- Intent cache key format: SHA256 of normalize_query (not tenant-prefixed)
- Search cache key format
"""
import hashlib
import struct

import pytest


# ---------------------------------------------------------------------------
# normalize_query
# ---------------------------------------------------------------------------


def test_normalize_query_lowercase():
    from app.core.cache_utils import normalize_query

    assert normalize_query("Hello World") == "hello world"


def test_normalize_query_strip():
    from app.core.cache_utils import normalize_query

    assert normalize_query("  hello  ") == "hello"


def test_normalize_query_collapse_whitespace():
    from app.core.cache_utils import normalize_query

    assert normalize_query("what   is    this") == "what is this"


def test_normalize_query_strips_punctuation():
    from app.core.cache_utils import normalize_query

    # Commas, question marks, exclamation marks removed
    assert normalize_query("what is this?") == "what is this"
    assert normalize_query("hello, world!") == "hello world"


def test_normalize_query_preserves_apostrophes():
    from app.core.cache_utils import normalize_query

    # Per spec: apostrophes are preserved (all other punctuation is stripped)
    assert normalize_query("don't") == "don't"
    assert normalize_query("it's here") == "it's here"


def test_normalize_query_empty():
    from app.core.cache_utils import normalize_query

    assert normalize_query("") == ""
    assert normalize_query("   ") == ""


def test_normalize_query_none():
    from app.core.cache_utils import normalize_query

    assert normalize_query(None) == ""  # type: ignore[arg-type]


def test_normalize_query_unicode():
    from app.core.cache_utils import normalize_query

    # CJK characters should pass through (they are \w in Python Unicode)
    result = normalize_query("什么是 AI?")
    assert "什么是" in result
    assert "?" not in result


# ---------------------------------------------------------------------------
# Float16 roundtrip
# ---------------------------------------------------------------------------


def test_serialize_float16_bytes_length():
    from app.modules.chat.embedding import _serialize_float16

    vec = [0.1, 0.2, 0.3, -0.5, 1.0]
    b = _serialize_float16(vec)
    # float16 = 2 bytes each
    assert len(b) == len(vec) * 2


def test_float16_roundtrip_precision():
    from app.modules.chat.embedding import _deserialize_float16, _serialize_float16

    vec = [0.1, 0.2, 0.3, -0.5, 1.0, 0.0, -1.0]
    b = _serialize_float16(vec)
    recovered = _deserialize_float16(b)

    assert len(recovered) == len(vec)
    for original, recovered_val in zip(vec, recovered):
        # Float16 has ~3 significant decimal digits; allow 0.01 tolerance
        assert (
            abs(original - recovered_val) < 0.01
        ), f"Float16 precision error: {original} -> {recovered_val}"


def test_float16_roundtrip_zero_vector():
    from app.modules.chat.embedding import _deserialize_float16, _serialize_float16

    vec = [0.0] * 10
    recovered = _deserialize_float16(_serialize_float16(vec))
    assert all(v == 0.0 for v in recovered)


def test_float16_roundtrip_1536_dims():
    """Roundtrip test for a typical embedding dimension."""
    from app.modules.chat.embedding import _deserialize_float16, _serialize_float16

    vec = [0.001 * i for i in range(1536)]
    b = _serialize_float16(vec)
    recovered = _deserialize_float16(b)
    assert len(recovered) == 1536
    # Spot check a few values
    assert abs(recovered[0] - 0.0) < 0.001
    assert abs(recovered[100] - 0.1) < 0.01


# ---------------------------------------------------------------------------
# Intent cache key format (CACHE-001)
# ---------------------------------------------------------------------------


def test_intent_cache_key_is_sha256_of_normalized():
    from app.core.cache_utils import normalize_query
    from app.modules.chat.intent_detection import IntentDetectionService

    query = "What is the policy for remote work?"
    tenant_id = "some-tenant-id"
    key = IntentDetectionService._build_cache_key(query, tenant_id)

    # Should be SHA256 of normalize_query(query) — NOT tenant-prefixed
    normalized = normalize_query(query)
    expected = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    assert key == expected


def test_intent_cache_key_no_colons():
    from app.modules.chat.intent_detection import IntentDetectionService

    key = IntentDetectionService._build_cache_key("hello there", "tenant-123")
    assert ":" not in key


def test_intent_cache_key_same_query_different_tenants():
    """Same query from different tenants should produce same SHA256 hash.
    Tenant isolation is enforced by the Redis key prefix, not the hash."""
    from app.modules.chat.intent_detection import IntentDetectionService

    key1 = IntentDetectionService._build_cache_key("what is RAG", "tenant-aaa")
    key2 = IntentDetectionService._build_cache_key("what is RAG", "tenant-bbb")
    # Same query, same hash — tenant namespace enforced by Redis key prefix
    assert key1 == key2


# ---------------------------------------------------------------------------
# Embedding cache key format (CACHE-002)
# ---------------------------------------------------------------------------


def test_embedding_cache_key_includes_model_id():
    from app.modules.chat.embedding import EmbeddingService

    key = EmbeddingService._build_cache_key(
        "tenant-1", "hello world", "text-embedding-3-small"
    )
    # Should contain model_id segment
    assert (
        "text-embedding-3-small" in key
        or "text-embedding-3-small".replace("-", "_") in key
    )
    # Should have correct prefix
    assert key.startswith("mingai:tenant-1:emb:")


def test_embedding_cache_key_no_colons_in_model_id():
    from app.modules.chat.embedding import EmbeddingService

    # Model IDs may contain hyphens and dots but not colons
    key = EmbeddingService._build_cache_key("tenant-1", "text", "my-model.v2")
    # No extra colons beyond the 4 structural separators
    parts = key.split(":")
    # mingai : tenant : emb : model : hash => 5 parts
    assert len(parts) == 5


def test_embedding_cache_key_hash_is_full_sha256():
    from app.modules.chat.embedding import EmbeddingService

    key = EmbeddingService._build_cache_key("tenant-1", "test text", "model-v1")
    # Last segment should be full SHA256 (64 chars)
    hash_part = key.split(":")[-1]
    assert len(hash_part) == 64
    assert all(c in "0123456789abcdef" for c in hash_part)


# ---------------------------------------------------------------------------
# Search cache key format (CACHE-003)
# ---------------------------------------------------------------------------


def test_search_cache_key_prefix():
    from app.core.cache_search import SearchCacheService

    embedding = [0.1] * 10
    key = SearchCacheService._build_key(
        "tenant-abc", "index-1", embedding, {"top_k": 10}
    )
    assert key.startswith("mingai:tenant-abc:search:index-1:")


def test_search_cache_key_length():
    from app.core.cache_search import SearchCacheService

    embedding = [0.1] * 5
    key = SearchCacheService._build_key("t", "idx", embedding, {})
    parts = key.split(":")
    # mingai : t : search : idx : emb_hash16 : params_hash8
    assert len(parts) == 6


def test_search_cache_key_different_embeddings():
    from app.core.cache_search import SearchCacheService

    params = {"top_k": 10}
    key1 = SearchCacheService._build_key("t", "idx", [0.1, 0.2], params)
    key2 = SearchCacheService._build_key("t", "idx", [0.9, 0.8], params)
    assert key1 != key2


def test_search_cache_key_different_params():
    from app.core.cache_search import SearchCacheService

    emb = [0.1, 0.2]
    key1 = SearchCacheService._build_key("t", "idx", emb, {"top_k": 5})
    key2 = SearchCacheService._build_key("t", "idx", emb, {"top_k": 10})
    assert key1 != key2


def test_search_cache_key_tenant_isolation():
    from app.core.cache_search import SearchCacheService

    emb = [0.1, 0.2]
    key1 = SearchCacheService._build_key("tenant-a", "idx", emb, {})
    key2 = SearchCacheService._build_key("tenant-b", "idx", emb, {})
    assert key1 != key2


def test_search_cache_key_colon_in_tenant_id_raises():
    from app.core.cache_search import SearchCacheService

    with pytest.raises(ValueError, match="colons"):
        SearchCacheService._build_key("tenant:bad", "idx", [0.1], {})


# ---------------------------------------------------------------------------
# Index version counter (CACHE-004) — sync tests only (no Redis needed)
# ---------------------------------------------------------------------------


def test_version_key_colon_in_tenant_raises():
    """Test that invalid tenant_id raises ValueError synchronously."""
    import asyncio
    from app.core.cache_utils import increment_index_version

    with pytest.raises(ValueError, match="colons"):
        asyncio.run(increment_index_version("bad:tenant", "idx"))


def test_version_key_colon_in_index_raises():
    import asyncio
    from app.core.cache_utils import increment_index_version

    with pytest.raises(ValueError, match="colons"):
        asyncio.run(increment_index_version("tenant", "bad:index"))
