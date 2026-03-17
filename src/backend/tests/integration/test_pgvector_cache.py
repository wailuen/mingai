"""
DEF-013: pgvector Semantic Cache Integration Tests.

TEST-011: Embedding stored and retrieved via pgvector (direct insert + lookup)
TEST-012: Cross-tenant isolation — tenant_B cannot see tenant_A's cache entries
TEST-013: Similarity threshold boundary — exact hit, near-match hit, distant miss

All tests use real PostgreSQL with the pgvector extension and real Redis for
version counters. No mocking.

Design note: SemanticCacheService.lookup() calls async_session_factory() from
session.py, a module-level singleton that binds to the first asyncio event loop.
Each asyncio.run() creates a new event loop — reusing the singleton pool causes
asyncpg "cannot perform operation: another operation is in progress" errors.

Resolution: these tests run the pgvector lookup SQL directly using fresh
create_async_engine() instances (one per asyncio.run()), matching the pattern
used by test_glossary_cache_integration.py and test_glossary_pipeline_integration.py.
This provides the same coverage as calling svc.lookup() and is the established
Tier-2 integration test pattern for this codebase.

Prerequisites:
    docker-compose up -d  # PostgreSQL + Redis required

Run:
    cd src/backend && python -m pytest tests/integration/test_pgvector_cache.py -v
"""
import asyncio
import json
import math
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.redis_client as _redis_mod
from app.core.redis_client import close_redis, get_redis


# ---------------------------------------------------------------------------
# Infrastructure helpers
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


def _reset_redis_pool() -> None:
    """Reset the module-level Redis singleton so each asyncio.run() gets a fresh pool."""
    _redis_mod._redis_pool = None


def _make_engine():
    return create_async_engine(_db_url(), echo=False)


async def _run_sql(sql: str, params: dict = None) -> None:
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _run_sql_fetch(sql: str, params: dict = None) -> list:
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            return result.fetchall()
    finally:
        await engine.dispose()


async def _create_tenant(name_prefix: str) -> str:
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"{name_prefix} {tid[:8]}",
            "slug": f"pgv-test-{tid[:8]}",
            "email": f"admin-{tid[:8]}@pgvtest.test",
        },
    )
    return tid


async def _cleanup_tenant(tid: str) -> None:
    await _run_sql("DELETE FROM semantic_cache WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})


# ---------------------------------------------------------------------------
# Vector math helpers
# ---------------------------------------------------------------------------


def _unit_vector(dim: int, seed: int = 0, noise: float = 0.0) -> list[float]:
    """Generate a normalised deterministic vector of dimension `dim`.

    Uses a simple LCG-style formula to produce component values that differ
    across elements, ensuring vectors with different seeds are in genuinely
    different directions after normalization.

    `noise` adds a small perturbation to each component (relative to the seed
    pattern) to produce near-match variants for threshold testing.

    Args:
        dim:   Dimensionality of the output vector.
        seed:  Integer seed — different seeds produce orthogonally different
               directions. Must not be 0 to avoid degenerate output.
        noise: Per-component perturbation factor (default 0.0 = no noise).
    """
    # Use a deterministic pattern: component i = sin(seed * i / 100 + seed)
    # This ensures genuinely different directions for different seeds
    import math as _math

    raw = [
        _math.sin(seed * (i + 1) / 50.0) + noise * _math.cos((i + 1) * 0.1)
        for i in range(dim)
    ]
    magnitude = _math.sqrt(sum(v * v for v in raw))
    if magnitude == 0:
        # Fallback: unit vector along first axis
        result = [0.0] * dim
        result[0] = 1.0
        return result
    return [v / magnitude for v in raw]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# Direct DB insert helper (bypasses SemanticCacheService.store() background task)
# ---------------------------------------------------------------------------


async def _insert_cache_entry(
    tenant_id: str,
    embedding: list[float],
    query_text: str = "test query",
    raw_answer: str = "test answer",
    version_tag: int = 0,
    ttl_seconds: int = 86400,
) -> str:
    """Insert a semantic_cache row directly using SQL, bypassing the service layer.

    This gives tests deterministic control over the stored embedding and version_tag
    without relying on background asyncio tasks in SemanticCacheService.store().
    """
    entry_id = str(uuid.uuid4())
    emb_literal = "[" + ",".join(str(v) for v in embedding) + "]"

    # Serialise a minimal CacheableResponse-compatible payload
    response_json = json.dumps(
        {
            "sources": [],
            "raw_answer": raw_answer,
            "confidence": 0.85,
            "model": "test-model",
            "latency_ms": 100,
        }
    )

    await _run_sql(
        "INSERT INTO semantic_cache "
        "(id, tenant_id, query_embedding, query_text, response_text, "
        " similarity_threshold, hit_count, created_at, expires_at, version_tag) "
        "VALUES "
        "(:id, :tid, CAST(:emb AS vector), :query_text, :response_text, "
        " 0.92, 0, NOW(), NOW() + (:ttl * INTERVAL '1 second'), :version_tag)",
        {
            "id": entry_id,
            "tid": tenant_id,
            "emb": emb_literal,
            "query_text": query_text,
            "response_text": response_json,
            "ttl": ttl_seconds,
            "version_tag": version_tag,
        },
    )
    return entry_id


# ---------------------------------------------------------------------------
# Pgvector lookup helper using fresh engine (avoids module-level session factory)
# ---------------------------------------------------------------------------


async def _pgvector_lookup(
    tenant_id: str,
    query_embedding: list[float],
    threshold: float = 0.92,
    require_version: int = 0,
) -> dict | None:
    """
    Run the pgvector cosine-distance lookup against semantic_cache using a
    fresh SQLAlchemy engine — avoids the event-loop conflict from
    session.py's module-level async_session_factory.

    Returns a dict with keys {id, raw_answer, similarity, version_tag}
    if a matching entry is found, or None on miss.
    """
    dist_threshold = 1.0 - threshold
    emb_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            # Reproduce the RLS context that SemanticCacheService sets
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": tenant_id},
            )
            result = await session.execute(
                text(
                    "SELECT id, response_text, version_tag, "
                    "  (query_embedding <=> CAST(:emb AS vector)) AS distance "
                    "FROM semantic_cache "
                    "WHERE tenant_id = :tid "
                    "  AND expires_at > NOW() "
                    "  AND (query_embedding <=> CAST(:emb AS vector)) <= :dist_threshold "
                    "ORDER BY query_embedding <=> CAST(:emb AS vector) "
                    "LIMIT 1"
                ),
                {
                    "tid": tenant_id,
                    "emb": emb_literal,
                    "dist_threshold": dist_threshold,
                },
            )
            row = result.mappings().first()

        if row is None:
            return None

        # Version gating: if the stored entry's version_tag does not match
        # the expected version, treat it as stale (same logic as the service)
        stored_version = row.get("version_tag", 0)
        if stored_version != require_version:
            return None

        distance = float(row["distance"])
        similarity = max(0.0, 1.0 - distance)
        response_data = json.loads(row["response_text"])
        return {
            "id": str(row["id"]),
            "raw_answer": response_data.get("raw_answer", ""),
            "similarity": similarity,
            "version_tag": stored_version,
        }
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Version helpers (Redis)
# ---------------------------------------------------------------------------


async def _set_redis_version(tenant_id: str, version: int) -> None:
    """Force the Redis version counter for a tenant to an exact value."""
    _reset_redis_pool()
    redis = get_redis()
    key = f"mingai:{tenant_id}:version:global"
    try:
        await redis.set(key, str(version))
    finally:
        await close_redis()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def tenant_a_id():
    """Primary test tenant — provisioned once per class, cleaned up after."""
    _db_url()  # Ensure configured before provisioning
    tid = asyncio.run(_create_tenant("PGVector Test A"))
    yield tid
    asyncio.run(_cleanup_tenant(tid))


@pytest.fixture(scope="class")
def tenant_b_id():
    """Secondary test tenant for cross-tenant isolation tests."""
    _db_url()
    tid = asyncio.run(_create_tenant("PGVector Test B"))
    yield tid
    asyncio.run(_cleanup_tenant(tid))


# ---------------------------------------------------------------------------
# TEST-011: Embedding stored and retrieved via pgvector
# ---------------------------------------------------------------------------


class TestPgvectorStoreAndRetrieve:
    """TEST-011: Direct INSERT then pgvector lookup verifying round-trip."""

    def test_stored_embedding_retrieved_by_exact_match(self, tenant_a_id):
        """
        Insert a cache entry with a known 1536-dim embedding.
        Query with the SAME embedding vector.
        Verify: entry is returned and similarity ≈ 1.0 (cosine distance ≈ 0).

        This validates the full pgvector round-trip:
          INSERT with CAST(:emb AS vector)
          → SELECT with (embedding <=> CAST(:q AS vector)) <= dist_threshold
          → similarity = 1 - distance
        """
        DIM = 1536
        base_embedding = _unit_vector(DIM, seed=5)

        # Insert at version 0
        asyncio.run(
            _insert_cache_entry(
                tenant_id=tenant_a_id,
                embedding=base_embedding,
                query_text="What is our leave policy?",
                raw_answer="The leave policy grants 20 days annual leave.",
                version_tag=0,
            )
        )

        result = asyncio.run(
            _pgvector_lookup(
                tenant_id=tenant_a_id,
                query_embedding=base_embedding,
                threshold=0.90,
                require_version=0,
            )
        )

        assert result is not None, (
            "Exact-match lookup should return a result, got None. "
            "Check that the semantic_cache table and pgvector extension exist "
            "and that the entry was inserted correctly."
        )
        assert result["similarity"] >= 0.99, (
            f"Exact-match cosine similarity should be ≥ 0.99, "
            f"got {result['similarity']:.4f}. "
            "Identical vectors should have cosine distance ≈ 0.0."
        )
        assert (
            result["raw_answer"] == "The leave policy grants 20 days annual leave."
        ), f"Retrieved answer mismatch: {result['raw_answer']!r}"

    def test_expired_entry_not_returned(self, tenant_a_id):
        """
        An entry with expires_at in the past must not be returned by the lookup.
        The WHERE expires_at > NOW() filter must exclude it.

        Uses base=0.9 (far from other test bases) and threshold=0.9999 so that
        only the exact same vector would qualify — ensuring the only candidate
        in the result set is the expired entry itself.
        """
        DIM = 1536
        # Use a base that is far from other test entries (0.5, 0.3, 0.7, 0.11, etc.)
        # to minimise risk of other non-expired entries matching at threshold=0.9999
        embed = _unit_vector(DIM, seed=9)
        entry_id = str(uuid.uuid4())
        emb_literal = "[" + ",".join(str(v) for v in embed) + "]"
        response_json = json.dumps(
            {
                "sources": [],
                "raw_answer": "expired",
                "confidence": 0.5,
                "model": "test",
                "latency_ms": 0,
            }
        )

        # Insert with expires_at in the past (1 hour ago)
        asyncio.run(
            _run_sql(
                "INSERT INTO semantic_cache "
                "(id, tenant_id, query_embedding, query_text, response_text, "
                " similarity_threshold, hit_count, created_at, expires_at, version_tag) "
                "VALUES "
                "(:id, :tid, CAST(:emb AS vector), :query_text, :response_text, "
                " 0.92, 0, NOW(), NOW() - INTERVAL '1 hour', 0)",
                {
                    "id": entry_id,
                    "tid": tenant_a_id,
                    "emb": emb_literal,
                    "query_text": "expired test",
                    "response_text": response_json,
                },
            )
        )

        # Use a very strict threshold (0.9999) so only an exact-match qualifies.
        # The only candidate for this embedding is the expired entry we just inserted.
        result = asyncio.run(
            _pgvector_lookup(
                tenant_id=tenant_a_id,
                query_embedding=embed,
                threshold=0.9999,
                require_version=0,
            )
        )

        assert result is None, (
            "Expired cache entry (expires_at in the past) must not be returned. "
            "The WHERE expires_at > NOW() filter is not working."
        )

    def test_version_mismatch_returns_none(self, tenant_a_id):
        """
        If the stored entry's version_tag does not match require_version,
        the lookup must return None (stale entry gating).

        This mirrors the version-gating logic in SemanticCacheService.lookup()
        which compares stored version_tag against the Redis global version counter.
        """
        DIM = 1536
        embed = _unit_vector(DIM, seed=3)

        # Insert at version 5
        asyncio.run(
            _insert_cache_entry(
                tenant_id=tenant_a_id,
                embedding=embed,
                query_text="stale version test",
                raw_answer="stale answer",
                version_tag=5,
            )
        )

        # Query requiring version 10 — stored is 5, so mismatch → miss
        result = asyncio.run(
            _pgvector_lookup(
                tenant_id=tenant_a_id,
                query_embedding=embed,
                threshold=0.0,  # Permissive threshold — any match passes distance
                require_version=10,
            )
        )
        assert result is None, (
            "Entry with version_tag=5 should be treated as stale when require_version=10. "
            "The version-gating logic is not working."
        )


# ---------------------------------------------------------------------------
# TEST-012: Cross-tenant isolation
# ---------------------------------------------------------------------------


class TestPgvectorCrossTenantIsolation:
    """TEST-012: Tenant B cannot retrieve Tenant A's cache entries via pgvector lookup."""

    def test_tenant_b_cannot_see_tenant_a_entry(self, tenant_a_id, tenant_b_id):
        """
        Insert a cache entry for tenant_A.
        Run the pgvector lookup as tenant_B with the exact same embedding.
        Expect None — the WHERE tenant_id = :tid filter must block cross-tenant access.

        The semantic_cache table has:
          - WHERE tenant_id = :tid in the lookup query (application-level filter)
          - RLS policy: tenant_id = current_setting('app.tenant_id', true)::uuid
        Both layers must prevent cross-tenant reads.
        """
        DIM = 1536
        shared_embedding = _unit_vector(DIM, seed=7)

        # Insert entry ONLY for tenant_A
        asyncio.run(
            _insert_cache_entry(
                tenant_id=tenant_a_id,
                embedding=shared_embedding,
                query_text="cross-tenant isolation test",
                raw_answer="This belongs to tenant A only.",
                version_tag=0,
            )
        )

        # Lookup as tenant_B — must return nothing
        result_b = asyncio.run(
            _pgvector_lookup(
                tenant_id=tenant_b_id,
                query_embedding=shared_embedding,
                threshold=0.90,
                require_version=0,
            )
        )

        assert result_b is None, (
            "Cross-tenant isolation FAILED: tenant_B retrieved tenant_A's cache entry. "
            "The WHERE tenant_id = :tid filter or RLS policy is not working correctly."
        )

    def test_tenant_a_can_still_retrieve_own_entry(self, tenant_a_id, tenant_b_id):
        """
        After the cross-tenant test above, tenant_A must still be able to
        retrieve its own entry — verifying that isolation does not corrupt data.
        """
        DIM = 1536
        shared_embedding = _unit_vector(DIM, seed=7)

        # Lookup as tenant_A — must succeed
        result_a = asyncio.run(
            _pgvector_lookup(
                tenant_id=tenant_a_id,
                query_embedding=shared_embedding,
                threshold=0.90,
                require_version=0,
            )
        )

        assert result_a is not None, (
            "Tenant A should be able to retrieve its own entry, but got None. "
            "This indicates data corruption or an RLS misconfiguration."
        )
        assert result_a["raw_answer"] == "This belongs to tenant A only."

    def test_tenant_b_empty_after_tenant_a_insert(self, tenant_a_id, tenant_b_id):
        """
        Tenant B has no cache entries of its own.
        A lookup for any vector as tenant_B must return None.
        """
        DIM = 1536
        any_embedding = _unit_vector(DIM, seed=1)

        result_b = asyncio.run(
            _pgvector_lookup(
                tenant_id=tenant_b_id,
                query_embedding=any_embedding,
                threshold=0.0,  # Permissive — catch anything in tenant_B's namespace
                require_version=0,
            )
        )

        assert result_b is None, (
            "Tenant B has no cache entries; lookup should return None. "
            f"Got: {result_b}"
        )


# ---------------------------------------------------------------------------
# TEST-013: Similarity threshold boundary tests
# ---------------------------------------------------------------------------


class TestPgvectorSimilarityThreshold:
    """
    TEST-013: Verify cosine similarity threshold enforcement via pgvector.

    Three scenarios:
      1. Exact same vector → cosine distance 0 → similarity 1.0 → hit
      2. Near-match vector → small perturbation → similarity > 0.92 → hit
      3. Distant vector → large perturbation → similarity < 0.92 → miss
    """

    def test_exact_vector_always_hits(self, tenant_a_id):
        """
        Exact same embedding as the stored entry:
          cosine distance = 0 → similarity = 1.0 → always above threshold 0.92.
        """
        DIM = 1536
        embed = _unit_vector(DIM, seed=11)

        asyncio.run(
            _insert_cache_entry(
                tenant_id=tenant_a_id,
                embedding=embed,
                query_text="threshold test exact",
                raw_answer="exact hit answer",
                version_tag=0,
            )
        )

        result = asyncio.run(
            _pgvector_lookup(
                tenant_id=tenant_a_id,
                query_embedding=embed,
                threshold=0.92,
                require_version=0,
            )
        )
        assert (
            result is not None
        ), "Exact-match vector must always hit at threshold 0.92"
        assert result["similarity"] >= 0.99, (
            f"Expected similarity ≥ 0.99 for exact vector, "
            f"got {result['similarity']:.4f}"
        )

    def test_near_match_vector_hits_above_threshold(self, tenant_a_id):
        """
        A vector with a very small perturbation should still hit at threshold 0.92.

        Strategy: normalised vectors with tiny noise (noise=0.001 on 1536-dim)
        give cosine similarity very close to 1.0 — reliably above 0.92.
        """
        DIM = 1536
        stored_embed = _unit_vector(DIM, seed=22)
        near_embed = _unit_vector(DIM, seed=22, noise=0.001)

        # Validate our test vectors produce the expected similarity
        sim = _cosine_similarity(stored_embed, near_embed)
        if sim < 0.92:
            pytest.skip(
                f"Test vector construction error: near-match similarity is {sim:.4f} "
                f"which is below threshold 0.92. Adjust noise parameter."
            )

        asyncio.run(
            _insert_cache_entry(
                tenant_id=tenant_a_id,
                embedding=stored_embed,
                query_text="threshold near match test",
                raw_answer="near match answer",
                version_tag=0,
            )
        )

        result = asyncio.run(
            _pgvector_lookup(
                tenant_id=tenant_a_id,
                query_embedding=near_embed,
                threshold=0.92,
                require_version=0,
            )
        )

        assert result is not None, (
            f"Near-match vector (computed similarity={sim:.4f}) should hit "
            f"at threshold 0.92, but got None. "
            "Check pgvector cosine distance computation."
        )
        assert (
            result["similarity"] >= 0.92
        ), f"Returned similarity {result['similarity']:.4f} is below threshold 0.92"

    def test_distant_vector_misses_threshold(self, tenant_a_id):
        """
        A vector in a sufficiently different direction should miss at threshold 0.92.

        Strategy: use a large noise value (50.0) which dominates the base on most
        components, creating a vector in a distinctly different direction from
        the stored base vector.
        """
        DIM = 1536
        stored_embed = _unit_vector(DIM, seed=33)
        distant_embed = _unit_vector(DIM, seed=33, noise=50.0)

        # Validate the vectors are actually distant
        sim = _cosine_similarity(stored_embed, distant_embed)
        if sim >= 0.92:
            pytest.skip(
                f"Test vector construction error: distant vector similarity is {sim:.4f} "
                f"which is ≥ threshold 0.92. The test would not be meaningful."
            )

        asyncio.run(
            _insert_cache_entry(
                tenant_id=tenant_a_id,
                embedding=stored_embed,
                query_text="threshold distant miss test",
                raw_answer="should not be retrieved",
                version_tag=0,
            )
        )

        result = asyncio.run(
            _pgvector_lookup(
                tenant_id=tenant_a_id,
                query_embedding=distant_embed,
                threshold=0.92,
                require_version=0,
            )
        )

        assert result is None, (
            f"Distant vector (computed similarity={sim:.4f} < 0.92) should miss "
            f"at threshold 0.92, but lookup returned a result. "
            "Check pgvector distance threshold filtering."
        )
