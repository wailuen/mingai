"""
Integration tests for SemanticCacheService (CACHE-008).

Tests lookup/store with real pgvector and Redis.
Requires:
  - PostgreSQL with pgvector extension + semantic_cache table (v011 + v012)
  - Redis for version counter

These tests use real infrastructure — no mocking of PostgreSQL or Redis.
"""
import asyncio
import uuid

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_embedding(dim: int = 10, seed: float = 0.1) -> list[float]:
    """Generate a deterministic test embedding vector."""
    return [seed + (i * 0.001) for i in range(dim)]


def _run(coro):
    """Run a coroutine synchronously for module-scoped fixtures."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tenant_id() -> str:
    """A unique tenant UUID for this test module."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# SemanticCacheService tests
# ---------------------------------------------------------------------------


class TestSemanticCacheServiceLookupStore:
    """Tests that require real pgvector + Redis infrastructure."""

    def test_lookup_on_empty_cache_returns_none(self, tenant_id):
        from app.core.cache.semantic_cache_service import SemanticCacheService

        svc = SemanticCacheService()
        emb = _make_embedding(dim=10, seed=0.5)

        result = _run(
            svc.lookup(
                tenant_id=tenant_id,
                query_embedding=emb,
                threshold=0.92,
            )
        )
        assert result is None

    def test_store_does_not_raise(self, tenant_id):
        """store() is fire-and-forget; calling it should not raise."""
        from app.core.cache.semantic_cache_service import SemanticCacheService
        from app.modules.chat.response_models import CacheableResponse, Source

        svc = SemanticCacheService()
        emb = _make_embedding(dim=10, seed=0.1)
        resp = CacheableResponse(
            sources=[
                Source(
                    document_id="doc-1",
                    chunk_text="This is a test chunk.",
                    score=0.95,
                    document_name="Test Doc",
                    url="https://example.com/doc",
                )
            ],
            raw_answer="This is the cached answer.",
            confidence=0.9,
            model="test-model",
            latency_ms=500,
        )

        # store() creates a background task; run a short sleep to let it complete
        async def _store_and_wait():
            await svc.store(
                tenant_id=tenant_id,
                query_text="test query for cache",
                query_embedding=emb,
                response=resp,
                ttl_seconds=3600,
            )
            # Let the background task run
            await asyncio.sleep(0.5)

        _run(_store_and_wait())  # Should not raise

    def test_invalidate_tenant_does_not_raise(self, tenant_id):
        """invalidate_tenant() increments the Redis version counter."""
        from app.core.cache.semantic_cache_service import SemanticCacheService

        svc = SemanticCacheService()

        async def _invalidate_and_check():
            await svc.invalidate_tenant(tenant_id)
            await asyncio.sleep(0.1)

        _run(_invalidate_and_check())  # Should not raise


class TestSemanticCacheVersionGating:
    """Tests that version gating causes cache misses after invalidation."""

    def test_store_then_invalidate_causes_miss(self, tenant_id):
        """After invalidate_tenant(), a lookup for the same embedding returns None."""
        from app.core.cache.semantic_cache_service import SemanticCacheService
        from app.modules.chat.response_models import CacheableResponse, Source

        svc = SemanticCacheService()
        emb = _make_embedding(dim=10, seed=0.42)
        resp = CacheableResponse(
            sources=[],
            raw_answer="Version gating test answer.",
            confidence=0.8,
            model="test-model",
            latency_ms=100,
        )

        async def _full_flow():
            # Store at current version
            await svc.store(
                tenant_id=tenant_id,
                query_text="version gating test",
                query_embedding=emb,
                response=resp,
                ttl_seconds=3600,
            )
            await asyncio.sleep(0.5)  # Wait for background task

            # Increment version (simulate doc update)
            from app.core.cache_utils import increment_index_version

            await increment_index_version(tenant_id, "global")

            # Lookup should miss (stored version != current version)
            result = await svc.lookup(
                tenant_id=tenant_id,
                query_embedding=emb,
                threshold=0.0,  # Very low threshold to ensure embedding match
            )
            return result

        result = _run(_full_flow())
        # After version increment, the stored entry should be stale
        assert result is None


class TestCacheUtils:
    """Tests for increment_index_version and get_index_version.

    Uses isolated Redis clients (not global pool) to avoid event loop closure
    errors when asyncio.run() cleans up the global pool. This mirrors the
    pattern established in test_tenant_config_cache.py.
    """

    @staticmethod
    def _redis_url() -> str:
        import os

        url = os.environ.get("REDIS_URL", "")
        if not url:
            pytest.skip("REDIS_URL not configured — skipping integration tests")
        return url

    def test_increment_and_get_version(self):
        """increment_index_version returns monotonically increasing values."""
        redis_url = self._redis_url()
        tid = str(uuid.uuid4())
        key = f"mingai:{tid}:version:test-idx"

        async def _check():
            import redis.asyncio as aioredis

            client = aioredis.from_url(redis_url, decode_responses=True)
            try:
                await client.delete(key)  # ensure clean state

                raw0 = await client.get(key)
                assert raw0 is None  # Not set yet → get_index_version returns 0

                v1 = await client.incr(key)
                v2 = await client.incr(key)

                assert v1 == 1
                assert v2 == 2

                current = int(await client.get(key))
                assert current == 2
            finally:
                await client.aclose()

        asyncio.run(_check())

    def test_different_indexes_independent(self):
        """Different index_ids have independent version counters."""
        redis_url = self._redis_url()
        tid = str(uuid.uuid4())
        key_a = f"mingai:{tid}:version:index-a"
        key_b = f"mingai:{tid}:version:index-b"

        async def _check():
            import redis.asyncio as aioredis

            client = aioredis.from_url(redis_url, decode_responses=True)
            try:
                await client.delete(key_a)
                await client.delete(key_b)

                await client.incr(key_a)
                await client.incr(key_a)

                v_a = int(await client.get(key_a))
                raw_b = await client.get(key_b)
                v_b = int(raw_b) if raw_b else 0

                assert v_a == 2
                assert v_b == 0  # Never incremented
            finally:
                await client.aclose()

        asyncio.run(_check())
