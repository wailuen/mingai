"""
Integration tests for PgVectorSearchClient and VectorSearchService.

Tier 2: Real PostgreSQL with pgvector extension — no mocking.
Tests upsert accuracy, idempotency, search behavior, isolation, and deletion.

Requires Docker services: PostgreSQL with pgvector (DATABASE_URL).
"""
import hashlib
import uuid

import pytest
from sqlalchemy import text

from app.core.session import async_session_factory
from app.modules.chat.vector_search import (
    PgVectorSearchClient,
    SearchResult,
    VectorSearchService,
)
from tests.fixtures.vector_search_fixtures import make_chunk, make_embedding


@pytest.fixture
def tenant_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def index_id(tenant_id: str) -> str:
    return f"{tenant_id}-test-agent"


@pytest.fixture
def client() -> PgVectorSearchClient:
    return PgVectorSearchClient()


@pytest.fixture(autouse=True)
async def setup_and_cleanup_tenant(tenant_id):
    """Insert a real tenant row before each test; clean up search + tenant rows after."""
    slug = f"test-{tenant_id[:8]}"
    async with async_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO tenants (id, name, slug, plan, status, primary_contact_email) "
                "VALUES (CAST(:tid AS uuid), :name, :slug, 'starter', 'active', 'test@test.test') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"tid": tenant_id, "name": f"Test Tenant {tenant_id[:8]}", "slug": slug},
        )
        await session.commit()

    yield

    async with async_session_factory() as session:
        await session.execute(
            text("DELETE FROM search_chunks WHERE tenant_id = CAST(:tid AS uuid)"),
            {"tid": tenant_id},
        )
        await session.execute(
            text(
                "DELETE FROM search_index_registry WHERE tenant_id = CAST(:tid AS uuid)"
            ),
            {"tid": tenant_id},
        )
        await session.execute(
            text("DELETE FROM tenants WHERE id = CAST(:tid AS uuid)"),
            {"tid": tenant_id},
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Upsert behavior
# ---------------------------------------------------------------------------


class TestPgVectorSearchClientUpsert:
    async def test_upsert_returns_accurate_count(self, client, tenant_id, index_id):
        """Upsert 3 distinct chunks — all 3 should be inserted."""
        chunks = [
            make_chunk(tenant_id, index_id, chunk_key=f"key{i}") for i in range(3)
        ]
        count = await client.upsert_chunks(chunks)
        assert count == 3

    async def test_upsert_idempotent_same_content(self, client, tenant_id, index_id):
        """Upserting same chunk twice with identical content — second upsert returns 0."""
        content = "unique content for idempotency test"
        chunk = make_chunk(
            tenant_id,
            index_id,
            chunk_key="idempotent_key",
            content=content,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
        )
        first = await client.upsert_chunks([chunk])
        second = await client.upsert_chunks([chunk])
        assert first == 1
        assert second == 0  # WHERE content_hash IS DISTINCT FROM prevents re-write

    async def test_upsert_updates_on_content_change(self, client, tenant_id, index_id):
        """Upserting same chunk_key with different content — second upsert returns 1."""
        original = make_chunk(
            tenant_id, index_id, chunk_key="update_key", content="original"
        )
        updated_content = "updated content"
        updated = make_chunk(
            tenant_id,
            index_id,
            chunk_key="update_key",
            content=updated_content,
            content_hash=hashlib.sha256(updated_content.encode()).hexdigest(),
        )
        first = await client.upsert_chunks([original])
        second = await client.upsert_chunks([updated])
        assert first == 1
        assert second == 1  # content changed → update fires

    async def test_upsert_empty_list_returns_zero(self, client):
        """Empty chunks list returns 0 without DB call."""
        count = await client.upsert_chunks([])
        assert count == 0


# ---------------------------------------------------------------------------
# Search behavior
# ---------------------------------------------------------------------------


class TestPgVectorSearchClientSearch:
    async def test_search_returns_matching_chunk(self, client, tenant_id, index_id):
        """After upserting a chunk, searching with its own embedding returns that chunk."""
        emb = make_embedding(seed=42)
        await client.upsert_chunks(
            [
                make_chunk(
                    tenant_id, index_id, embedding=emb, content="searchable document"
                )
            ]
        )

        results = await client.knn_search(
            index_id=index_id,
            vector=emb,
            top_k=5,
            query_text=None,
            tenant_id=tenant_id,
        )
        assert len(results) >= 1
        assert results[0]["content"] == "searchable document"
        assert "score" in results[0]
        assert 0.0 <= results[0]["score"] <= 1.0

    async def test_search_empty_index_returns_empty(self, client, tenant_id, index_id):
        """Search on empty index returns empty list without raising."""
        results = await client.knn_search(
            index_id=index_id,
            vector=make_embedding(),
            top_k=5,
            query_text=None,
            tenant_id=tenant_id,
        )
        assert results == []

    async def test_hybrid_search_returns_keyword_matched_chunk(
        self, client, tenant_id, index_id
    ):
        """Hybrid mode (query_text >= 2 chars) returns the keyword-matching chunk."""
        keyword_content = "quarterly revenue report finance"
        other_content = "employee vacation policy document"

        # Use embeddings that are very different so vector rank won't prefer keyword_content
        emb_keyword = make_embedding(seed=1)
        emb_other = make_embedding(seed=2)
        query_emb = make_embedding(seed=3)  # Closer to neither

        await client.upsert_chunks(
            [
                make_chunk(
                    tenant_id,
                    index_id,
                    chunk_key="kw",
                    content=keyword_content,
                    embedding=emb_keyword,
                ),
                make_chunk(
                    tenant_id,
                    index_id,
                    chunk_key="other",
                    content=other_content,
                    embedding=emb_other,
                ),
            ]
        )

        # "revenue" should be found by FTS leg in hybrid mode
        results = await client.knn_search(
            index_id=index_id,
            vector=query_emb,
            top_k=10,
            query_text="revenue",
            tenant_id=tenant_id,
        )
        contents = [r["content"] for r in results]
        assert (
            keyword_content in contents
        ), f"Hybrid search should surface the keyword-matching chunk. Got: {contents}"

    async def test_vector_only_for_short_query_text(self, client, tenant_id, index_id):
        """query_text with 1 char falls back to vector-only (no FTS error raised)."""
        emb = make_embedding(seed=10)
        await client.upsert_chunks([make_chunk(tenant_id, index_id, embedding=emb)])

        results = await client.knn_search(
            index_id=index_id,
            vector=emb,
            top_k=5,
            query_text="x",  # 1 char — below hybrid threshold of 2
            tenant_id=tenant_id,
        )
        # Should succeed and return the chunk (vector match)
        assert len(results) >= 1

    async def test_rrf_scores_bounded_zero_to_one(self, client, tenant_id, index_id):
        """All returned RRF scores are in [0, 1]."""
        emb = make_embedding(seed=5)
        chunks = [
            make_chunk(
                tenant_id, index_id, chunk_key=f"k{i}", embedding=make_embedding(i)
            )
            for i in range(5)
        ]
        await client.upsert_chunks(chunks)

        results = await client.knn_search(
            index_id=index_id,
            vector=emb,
            top_k=10,
            query_text="test content",
            tenant_id=tenant_id,
        )
        for r in results:
            score = r["score"]
            assert 0.0 <= score <= 1.0, f"Score out of range: {score}"

    async def test_search_cross_tenant_isolation(self, client):
        """Tenant A's chunks are invisible to Tenant B's search."""
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        index_a = f"{tenant_a}-agent"
        index_b = f"{tenant_b}-agent"

        async with async_session_factory() as session:
            for tid in (tenant_a, tenant_b):
                await session.execute(
                    text(
                        "INSERT INTO tenants (id, name, slug, plan, status, primary_contact_email) "
                        "VALUES (CAST(:tid AS uuid), :name, :slug, 'starter', 'active', 'x@test.test') "
                        "ON CONFLICT (id) DO NOTHING"
                    ),
                    {"tid": tid, "name": f"T-{tid[:8]}", "slug": f"t-{tid[:8]}"},
                )
            await session.commit()

        try:
            emb = make_embedding(seed=99)
            await client.upsert_chunks(
                [make_chunk(tenant_a, index_a, embedding=emb, content="secret data")]
            )

            results = await client.knn_search(
                index_id=index_b,
                vector=emb,
                top_k=5,
                query_text=None,
                tenant_id=tenant_b,
            )
            assert (
                results == []
            ), "Tenant B should not see Tenant A's chunks — cross-tenant isolation violated"
        finally:
            async with async_session_factory() as session:
                for tid in (tenant_a, tenant_b):
                    await session.execute(
                        text(
                            "DELETE FROM search_chunks WHERE tenant_id = CAST(:tid AS uuid)"
                        ),
                        {"tid": tid},
                    )
                    await session.execute(
                        text(
                            "DELETE FROM search_index_registry WHERE tenant_id = CAST(:tid AS uuid)"
                        ),
                        {"tid": tid},
                    )
                    await session.execute(
                        text("DELETE FROM tenants WHERE id = CAST(:tid AS uuid)"),
                        {"tid": tid},
                    )
                await session.commit()


# ---------------------------------------------------------------------------
# Delete behavior
# ---------------------------------------------------------------------------


class TestPgVectorSearchClientDelete:
    async def test_delete_by_index_removes_all(self, client, tenant_id, index_id):
        """delete_by_index removes all chunks for that index."""
        chunks = [
            make_chunk(tenant_id, index_id, chunk_key=f"del{i}") for i in range(3)
        ]
        await client.upsert_chunks(chunks)

        deleted = await client.delete_by_index(tenant_id, index_id)
        assert deleted == 3

        results = await client.knn_search(
            index_id=index_id,
            vector=make_embedding(),
            top_k=5,
            query_text=None,
            tenant_id=tenant_id,
        )
        assert results == []

    async def test_delete_by_source_file_scoped(self, client, tenant_id, index_id):
        """delete_by_source_file only removes chunks for that specific file."""
        chunks_file1 = [
            make_chunk(
                tenant_id, index_id, chunk_key=f"f1_c{i}", source_file_id="file1.txt"
            )
            for i in range(2)
        ]
        chunks_file2 = [
            make_chunk(
                tenant_id, index_id, chunk_key=f"f2_c{i}", source_file_id="file2.txt"
            )
            for i in range(2)
        ]
        await client.upsert_chunks(chunks_file1 + chunks_file2)

        deleted = await client.delete_by_source_file(tenant_id, index_id, "file1.txt")
        assert deleted == 2

        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM search_chunks "
                    "WHERE tenant_id=:tid AND index_id=:iid AND source_file_id='file2.txt'"
                ),
                {"tid": tenant_id, "iid": index_id},
            )
            assert (
                result.scalar() == 2
            ), "file2 chunks should remain after file1 deletion"


# ---------------------------------------------------------------------------
# VectorSearchService adapter
# ---------------------------------------------------------------------------


class TestVectorSearchService:
    async def test_service_search_returns_search_result_objects(self, tenant_id):
        """VectorSearchService.search() returns typed SearchResult objects with valid scores."""
        agent_id = "test-agent"
        service = VectorSearchService()
        emb = make_embedding(seed=1)

        client = PgVectorSearchClient()
        index_id = f"{tenant_id}-{agent_id}"
        await client.upsert_chunks([make_chunk(tenant_id, index_id, embedding=emb)])

        results = await service.search(
            query_vector=emb,
            tenant_id=tenant_id,
            agent_id=agent_id,
            query_text="test",
        )
        assert len(results) >= 1, "Should return at least 1 result for an indexed chunk"
        assert isinstance(results[0], SearchResult)
        assert 0.0 <= results[0].score <= 1.0
        assert results[0].content == "test content"

    async def test_service_upsert_chunks_builds_correct_chunk_key(self, tenant_id):
        """VectorSearchService.upsert_chunks() builds chunk_key matching indexing.py pattern."""
        service = VectorSearchService()
        integration_id = str(uuid.uuid4())
        file_path = "/tmp/myfile.txt"
        chunk_text = "some content"

        await service.upsert_chunks(
            tenant_id=tenant_id,
            integration_id=integration_id,
            file_path=file_path,
            chunk_index=0,
            chunk_text=chunk_text,
            embedding=make_embedding(),
        )

        expected_key = f"{integration_id}_myfile.txt_0"
        expected_hash = hashlib.sha256(chunk_text.encode()).hexdigest()

        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT chunk_key, content_hash FROM search_chunks "
                    "WHERE tenant_id=:tid AND chunk_key=:key"
                ),
                {"tid": tenant_id, "key": expected_key},
            )
            row = result.fetchone()
            assert row is not None, f"Chunk with key '{expected_key}' not found in DB"
            assert (
                row[1] == expected_hash
            ), "content_hash should match SHA256 of chunk_text"
