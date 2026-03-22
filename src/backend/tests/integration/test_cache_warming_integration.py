"""
TEST-013: Cache warming background job integration tests (Tier 2).

Tests the warm_embedding_cache() job against real PostgreSQL and Redis.
The LLM API client is the ONLY thing mocked (Tier 1 boundary mocking
of external API). The integration points under test are:

  1. SQL queries against real PostgreSQL (tenants, messages tables)
  2. Redis cache writes via real Redis
  3. Per-tenant isolation and error handling

NO internal mocking of EmbeddingService internals, Redis, or DB.

Requires: PostgreSQL (DATABASE_URL) and Redis (REDIS_URL) from .env.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.redis_client as redis_client_module
import app.core.session as session_module
import app.modules.chat.cache_warming as cache_warming_module
from app.core.redis_client import get_redis
from app.modules.chat.embedding import EmbeddingService


def _unique_id() -> str:
    return str(uuid.uuid4())


def _unique_slug() -> str:
    return f"test-slug-{uuid.uuid4().hex[:8]}"


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured -- skipping integration tests")
    return url


def _make_embedding_response(vector: list[float]):
    """Build a fake OpenAI embeddings.create() response object."""
    embedding_obj = SimpleNamespace(embedding=vector)
    return SimpleNamespace(data=[embedding_obj])


_DEFAULT_VECTOR = [0.1] * 8


def _get_session_factory():
    """Get the current session factory (after reset)."""
    return session_module.async_session_factory


@pytest.fixture(autouse=True)
async def _reset_pools():
    """
    Reset module-level SQLAlchemy engine and Redis pool before each test.
    Avoids asyncpg event loop binding conflicts across test functions.
    """
    redis_client_module._redis_pool = None
    await session_module.engine.dispose()
    session_module.engine = create_async_engine(
        _db_url(), echo=False, pool_size=5, max_overflow=10
    )
    session_module.async_session_factory = async_sessionmaker(
        session_module.engine, class_=AsyncSession, expire_on_commit=False
    )
    # Also patch cache_warming module's direct import of async_session_factory
    cache_warming_module.async_session_factory = session_module.async_session_factory
    yield
    await session_module.engine.dispose()
    if redis_client_module._redis_pool is not None:
        await redis_client_module._redis_pool.aclose()
        redis_client_module._redis_pool = None


@pytest.fixture
async def seed_tenant():
    """
    Create an active tenant with messages for cache warming tests.
    Returns (tenant_id, query_texts) and cleans up afterwards.
    """
    created_tenants: list[str] = []
    created_conversations: list[str] = []
    created_users: list[str] = []

    async def _create(
        *,
        status: str = "active",
        queries: list[str] | None = None,
        recent: bool = True,
    ) -> tuple[str, list[str]]:
        tenant_id = _unique_id()
        slug = _unique_slug()
        created_tenants.append(tenant_id)

        async with _get_session_factory()() as session:
            # Create tenant
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, plan, status, primary_contact_email) "
                    "VALUES (:id, :name, :slug, 'starter', :status, :email)"
                ),
                {
                    "id": tenant_id,
                    "name": f"Warming Test {tenant_id[:8]}",
                    "slug": slug,
                    "status": status,
                    "email": "warming@test.test",
                },
            )

            query_texts = (
                queries
                if queries is not None
                else [
                    "How do I reset my password?",
                    "What is the refund policy?",
                ]
            )

            if query_texts:
                # Create a user (required FK for conversations)
                user_id = _unique_id()
                created_users.append(user_id)
                await session.execute(
                    text(
                        "INSERT INTO users (id, tenant_id, email, name) "
                        "VALUES (:id, :tid, :email, 'Test User')"
                    ),
                    {
                        "id": user_id,
                        "tid": tenant_id,
                        "email": f"test-{user_id[:8]}@warming.test",
                    },
                )

                # Create a conversation for messages
                conv_id = _unique_id()
                created_conversations.append(conv_id)
                await session.execute(
                    text(
                        "INSERT INTO conversations (id, tenant_id, user_id, title) "
                        "VALUES (:id, :tid, :uid, 'test')"
                    ),
                    {"id": conv_id, "tid": tenant_id, "uid": user_id},
                )

                # Insert messages -- if recent=True, use NOW(); otherwise 30 days ago
                for q in query_texts:
                    msg_id = _unique_id()
                    if recent:
                        await session.execute(
                            text(
                                "INSERT INTO messages (id, conversation_id, tenant_id, role, content, created_at) "
                                "VALUES (:id, :cid, :tid, 'user', :content, NOW())"
                            ),
                            {
                                "id": msg_id,
                                "cid": conv_id,
                                "tid": tenant_id,
                                "content": q,
                            },
                        )
                    else:
                        await session.execute(
                            text(
                                "INSERT INTO messages (id, conversation_id, tenant_id, role, content, created_at) "
                                "VALUES (:id, :cid, :tid, 'user', :content, NOW() - INTERVAL '60 days')"
                            ),
                            {
                                "id": msg_id,
                                "cid": conv_id,
                                "tid": tenant_id,
                                "content": q,
                            },
                        )

            await session.commit()

        return tenant_id, query_texts

    yield _create

    # Cleanup (reverse FK order: messages -> conversations -> users -> tenants)
    async with _get_session_factory()() as session:
        for cid in created_conversations:
            await session.execute(
                text("DELETE FROM messages WHERE conversation_id = :cid"),
                {"cid": cid},
            )
            await session.execute(
                text("DELETE FROM conversations WHERE id = :cid"),
                {"cid": cid},
            )
        for uid in created_users:
            await session.execute(
                text("DELETE FROM users WHERE id = :uid"),
                {"uid": uid},
            )
        for tid in created_tenants:
            await session.execute(
                text("DELETE FROM tenants WHERE id = :tid"),
                {"tid": tid},
            )
        await session.commit()

    # Clean up Redis embedding cache keys
    redis = get_redis()
    for tid in created_tenants:
        # Scan and delete any embedding cache keys for test tenants
        cursor = 0
        while True:
            cursor, keys = await redis.scan(
                cursor, match=f"mingai:{tid}:embedding_cache:*", count=100
            )
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break


def _patch_embedding_service(
    call_tracker: list | None = None, fail_on: str | None = None
):
    """
    Return a patched EmbeddingService whose _client is mocked.
    Optionally tracks calls and can fail on a specific text.
    """
    mock_client = AsyncMock()

    async def _embed_side_effect(**kwargs):
        input_text = kwargs.get("input", "")
        if call_tracker is not None:
            call_tracker.append(input_text)
        if fail_on and input_text == fail_on:
            raise RuntimeError(f"Simulated embedding failure for: {input_text}")
        return _make_embedding_response(_DEFAULT_VECTOR)

    mock_client.embeddings.create = AsyncMock(side_effect=_embed_side_effect)
    return mock_client


# =========================================================================
# TEST-013-01: Warming job creates cache entries
# =========================================================================


async def test_warming_job_creates_cache_entries(seed_tenant):
    """After running the warming job, Redis keys exist for top queries."""
    tenant_id, queries = await seed_tenant(queries=["refund policy", "shipping info"])

    call_tracker: list[str] = []
    mock_client = _patch_embedding_service(call_tracker=call_tracker)

    with patch.dict(
        os.environ,
        {
            "CLOUD_PROVIDER": "local",
            "EMBEDDING_MODEL": "text-embedding-3-small",
            "OPENAI_API_KEY": "sk-test-not-real-key-for-integration-tests",
        },
    ):
        from app.modules.chat.cache_warming import warm_embedding_cache

        # Patch EmbeddingService to use our mock client
        original_init = EmbeddingService.__init__

        def _patched_init(self):
            original_init(self)
            self._client = mock_client

        with patch.object(EmbeddingService, "__init__", _patched_init):
            await warm_embedding_cache()

    # Verify Redis keys exist for each query
    from app.modules.chat.embedding import _deserialize_float16

    redis = get_redis()
    for q in queries:
        cache_key = EmbeddingService._build_cache_key(tenant_id, q, "text-embedding-3-small")
        cached = await redis.get(cache_key)
        assert cached is not None, f"Cache key should exist for query: {q}"
        # Cache is stored as float16 binary (not JSON); deserialize and compare approximately
        # get_redis() uses decode_responses=True so binary data comes back as str; re-encode
        raw = cached.encode("latin-1") if isinstance(cached, str) else cached
        vector = _deserialize_float16(raw)
        assert len(vector) == len(_DEFAULT_VECTOR), f"Vector length mismatch: {len(vector)} != {len(_DEFAULT_VECTOR)}"
        for actual, expected in zip(vector, _DEFAULT_VECTOR):
            assert abs(actual - expected) < 0.01, f"Vector value mismatch: {actual} != {expected}"

    # Verify the LLM was called for each query
    assert len(call_tracker) >= len(
        queries
    ), f"Expected at least {len(queries)} LLM calls, got {len(call_tracker)}"


# =========================================================================
# TEST-013-02: Tenant isolation
# =========================================================================


async def test_warming_job_tenant_isolation(seed_tenant):
    """Warming job only creates cache entries for the specified tenant's queries."""
    tenant_a_id, queries_a = await seed_tenant(queries=["tenant A question"])
    tenant_b_id, queries_b = await seed_tenant(queries=["tenant B question"])

    call_tracker: list[str] = []
    mock_client = _patch_embedding_service(call_tracker=call_tracker)

    with patch.dict(
        os.environ,
        {
            "CLOUD_PROVIDER": "local",
            "EMBEDDING_MODEL": "text-embedding-3-small",
            "OPENAI_API_KEY": "sk-test-not-real-key-for-integration-tests",
        },
    ):
        from app.modules.chat.cache_warming import warm_embedding_cache

        original_init = EmbeddingService.__init__

        def _patched_init(self):
            original_init(self)
            self._client = mock_client

        with patch.object(EmbeddingService, "__init__", _patched_init):
            await warm_embedding_cache()

    redis = get_redis()

    # Tenant A's query should be cached under tenant A's key
    key_a = EmbeddingService._build_cache_key(tenant_a_id, "tenant A question", "text-embedding-3-small")
    cached_a = await redis.get(key_a)
    assert cached_a is not None, "Tenant A query should be cached"

    # Tenant B's query should be cached under tenant B's key
    key_b = EmbeddingService._build_cache_key(tenant_b_id, "tenant B question", "text-embedding-3-small")
    cached_b = await redis.get(key_b)
    assert cached_b is not None, "Tenant B query should be cached"

    # Cross-tenant: tenant A's key namespace should NOT have tenant B's query
    cross_key = EmbeddingService._build_cache_key(tenant_a_id, "tenant B question", "text-embedding-3-small")
    cross_cached = await redis.get(cross_key)
    assert cross_cached is None, "Tenant A should not have tenant B's query cached"


# =========================================================================
# TEST-013-03: Idempotency -- running twice refreshes, doesn't duplicate
# =========================================================================


async def test_warming_job_idempotent(seed_tenant):
    """Running the warming job twice refreshes TTL but does not create duplicates."""
    tenant_id, queries = await seed_tenant(queries=["idempotent test query"])

    call_tracker: list[str] = []
    mock_client = _patch_embedding_service(call_tracker=call_tracker)

    with patch.dict(
        os.environ,
        {
            "CLOUD_PROVIDER": "local",
            "EMBEDDING_MODEL": "text-embedding-3-small",
            "OPENAI_API_KEY": "sk-test-not-real-key-for-integration-tests",
        },
    ):
        from app.modules.chat.cache_warming import warm_embedding_cache

        original_init = EmbeddingService.__init__

        def _patched_init(self):
            original_init(self)
            self._client = mock_client

        with patch.object(EmbeddingService, "__init__", _patched_init):
            # First run
            await warm_embedding_cache()

            redis = get_redis()
            cache_key = EmbeddingService._build_cache_key(
                tenant_id, "idempotent test query", "text-embedding-3-small"
            )
            ttl_after_first = await redis.ttl(cache_key)
            assert ttl_after_first > 0, "TTL should be set after first run"

            # Note: on cache hit, EmbeddingService.embed() returns from cache
            # without calling LLM again. The TTL is only set on cache miss.
            # So the second run should be a cache hit (no new LLM call).
            first_run_calls = len(call_tracker)

            # Second run
            await warm_embedding_cache()

            # On second run, the embedding is already cached, so the LLM
            # should NOT be called again (cache hit path in EmbeddingService)
            second_run_new_calls = len(call_tracker) - first_run_calls
            assert (
                second_run_new_calls == 0
            ), f"Second warming run should hit cache, got {second_run_new_calls} new LLM calls"

            # The cached value should still be valid
            cached = await redis.get(cache_key)
            assert cached is not None, "Cache entry should still exist after second run"


# =========================================================================
# TEST-013-04: Error handling -- one document failure doesn't crash job
# =========================================================================


async def test_warming_job_continues_on_embed_failure(seed_tenant):
    """If one document fails embedding, the job continues to the next."""
    tenant_id, _ = await seed_tenant(
        queries=["good query one", "bad query fails", "good query two"]
    )

    call_tracker: list[str] = []
    # Configure mock to fail on "bad query fails"
    mock_client = _patch_embedding_service(
        call_tracker=call_tracker, fail_on="bad query fails"
    )

    with patch.dict(
        os.environ,
        {
            "CLOUD_PROVIDER": "local",
            "EMBEDDING_MODEL": "text-embedding-3-small",
            "OPENAI_API_KEY": "sk-test-not-real-key-for-integration-tests",
        },
    ):
        from app.modules.chat.cache_warming import warm_embedding_cache

        original_init = EmbeddingService.__init__

        def _patched_init(self):
            original_init(self)
            self._client = mock_client

        with patch.object(EmbeddingService, "__init__", _patched_init):
            # Should not raise despite one query failing
            await warm_embedding_cache()

    # Verify the good queries were still cached
    redis = get_redis()
    key_good1 = EmbeddingService._build_cache_key(tenant_id, "good query one", "text-embedding-3-small")
    key_good2 = EmbeddingService._build_cache_key(tenant_id, "good query two", "text-embedding-3-small")
    key_bad = EmbeddingService._build_cache_key(tenant_id, "bad query fails", "text-embedding-3-small")

    assert await redis.get(key_good1) is not None, "First good query should be cached"
    assert await redis.get(key_good2) is not None, "Second good query should be cached"
    assert await redis.get(key_bad) is None, "Failed query should not be cached"


# =========================================================================
# TEST-013-05: Empty document set -- graceful handling
# =========================================================================


async def test_warming_job_handles_empty_document_set(seed_tenant):
    """Job handles tenants with no documents (no messages) gracefully."""
    # Create a tenant with no messages (empty queries list)
    tenant_id, _ = await seed_tenant(queries=[])

    mock_client = _patch_embedding_service()

    with patch.dict(
        os.environ,
        {
            "CLOUD_PROVIDER": "local",
            "EMBEDDING_MODEL": "text-embedding-3-small",
            "OPENAI_API_KEY": "sk-test-not-real-key-for-integration-tests",
        },
    ):
        from app.modules.chat.cache_warming import warm_embedding_cache

        original_init = EmbeddingService.__init__

        def _patched_init(self):
            original_init(self)
            self._client = mock_client

        with patch.object(EmbeddingService, "__init__", _patched_init):
            # Should not raise
            await warm_embedding_cache()

    # No cache entries should be created for this tenant
    redis = get_redis()
    cursor = 0
    keys_found = []
    while True:
        cursor, keys = await redis.scan(
            cursor, match=f"mingai:{tenant_id}:embedding_cache:*", count=100
        )
        keys_found.extend(keys)
        if cursor == 0:
            break

    assert (
        len(keys_found) == 0
    ), f"No cache entries should exist for tenant with no messages, found {len(keys_found)}"
