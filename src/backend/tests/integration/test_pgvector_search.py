"""
Integration tests for pgvector hybrid search.

All tests use real PostgreSQL with pgvector extension.
No mocking -- per gold standards.
"""
import hashlib
import uuid

import pytest
from sqlalchemy import text

from app.core.session import async_session_factory
from app.modules.chat.vector_search import (
    PgVectorSearchClient,
    VectorSearchService,
)
from tests.fixtures.vector_search_fixtures import make_chunk, make_embedding


@pytest.fixture
def tenant_id():
    return str(uuid.uuid4())


@pytest.fixture
def index_id(tenant_id):
    return f"{tenant_id}-agent"


@pytest.fixture(autouse=True)
async def setup_and_cleanup(tenant_id):
    """Create tenant row before test; clean up all test data after."""
    slug = f"int-{tenant_id[:8]}"
    async with async_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO tenants (id, name, slug, plan, status, primary_contact_email) "
                "VALUES (CAST(:tid AS uuid), :name, :slug, 'starter', 'active', 'int@test.test') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"tid": tenant_id, "name": f"Int Test {tenant_id[:8]}", "slug": slug},
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


class TestHybridSearch:
    async def test_hybrid_search_returns_relevant_chunks(self, tenant_id, index_id):
        """FTS + vector hybrid finds chunks containing the search keyword."""
        client = PgVectorSearchClient()
        keyword = "quarterly_revenue_unique_term_xyz"
        matching_emb = make_embedding(seed=1)

        chunks = [
            make_chunk(
                tenant_id,
                index_id,
                chunk_key="matching",
                content=f"This document covers {keyword} analysis.",
                embedding=matching_emb,
                content_hash=hashlib.sha256(
                    f"This document covers {keyword} analysis.".encode()
                ).hexdigest(),
            ),
            make_chunk(
                tenant_id,
                index_id,
                chunk_key="irrelevant",
                content="Unrelated content about weather.",
                embedding=make_embedding(seed=2),
                content_hash=hashlib.sha256(
                    b"Unrelated content about weather."
                ).hexdigest(),
            ),
        ]
        await client.upsert_chunks(chunks)

        results = await client.knn_search(
            index_id=index_id,
            vector=matching_emb,
            top_k=5,
            query_text=keyword,
            tenant_id=tenant_id,
        )
        assert len(results) >= 1
        # The chunk with the keyword should score highly and appear in results
        content_values = [r["content"] for r in results]
        assert any(
            keyword in c for c in content_values
        ), f"Expected chunk with '{keyword}' in results, got: {content_values}"

    async def test_cross_tenant_isolation(self, index_id):
        """Chunks from Tenant A are invisible to Tenant B searches."""
        client = PgVectorSearchClient()
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        index_a = f"{tenant_a}-agent"
        index_b = f"{tenant_b}-agent"
        emb = make_embedding(seed=7)

        # Create tenant rows for FK satisfaction
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

        await client.upsert_chunks(
            [make_chunk(tenant_a, index_a, embedding=emb, chunk_key="a_chunk")]
        )

        results = await client.knn_search(
            index_id=index_b,
            vector=emb,
            top_k=5,
            query_text=None,
            tenant_id=tenant_b,
        )
        assert results == [], f"Tenant B should see zero results, got {results}"

        # Cleanup
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

    async def test_per_user_conversation_isolation(self, tenant_id, index_id):
        """User A's conversation docs are invisible to User B's search."""
        client = PgVectorSearchClient()
        user_a = str(uuid.uuid4())
        user_b = str(uuid.uuid4())
        conv_id = str(uuid.uuid4())

        # Create user rows for FK satisfaction
        async with async_session_factory() as session:
            for uid, email in ((user_a, "ua@test.test"), (user_b, "ub@test.test")):
                await session.execute(
                    text(
                        "INSERT INTO users (id, tenant_id, email, role, status) "
                        "VALUES (CAST(:uid AS uuid), CAST(:tid AS uuid), :email, 'viewer', 'active') "
                        "ON CONFLICT (id) DO NOTHING"
                    ),
                    {"uid": uid, "tid": tenant_id, "email": email},
                )
            await session.commit()

        emb = make_embedding(seed=3)
        await client.upsert_chunks(
            [
                make_chunk(
                    tenant_id,
                    index_id,
                    chunk_key="user_a_doc",
                    source_type="conversation",
                    user_id=user_a,
                    conversation_id=conv_id,
                    embedding=emb,
                )
            ]
        )

        # User B queries -- should see nothing
        results = await client.knn_search(
            index_id=index_id,
            vector=emb,
            top_k=5,
            query_text=None,
            tenant_id=tenant_id,
            user_id=user_b,
        )
        assert results == [], f"User B should see zero conversation docs, got {results}"

        # Cleanup users
        async with async_session_factory() as session:
            for uid in (user_a, user_b):
                await session.execute(
                    text("DELETE FROM users WHERE id = CAST(:uid AS uuid)"),
                    {"uid": uid},
                )
            await session.commit()


class TestRegistryCounts:
    async def test_chunk_count_updated_after_upsert(self, tenant_id, index_id):
        """search_index_registry.chunk_count matches actual chunk count after upsert."""
        client = PgVectorSearchClient()
        chunks = [
            make_chunk(tenant_id, index_id, chunk_key=f"reg_{i}") for i in range(5)
        ]
        await client.upsert_chunks(chunks)

        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT chunk_count FROM search_index_registry "
                    "WHERE tenant_id=:tid AND index_id=:iid"
                ),
                {"tid": tenant_id, "iid": index_id},
            )
            row = result.fetchone()
            assert row is not None, "Registry row should exist after upsert"
            assert row[0] == 5

    async def test_doc_count_counts_distinct_files(self, tenant_id, index_id):
        """doc_count reflects distinct source_file_id values, not chunk count."""
        client = PgVectorSearchClient()
        chunks = [
            make_chunk(
                tenant_id, index_id, chunk_key="f1c0", source_file_id="file1.txt"
            ),
            make_chunk(
                tenant_id, index_id, chunk_key="f1c1", source_file_id="file1.txt"
            ),
            make_chunk(
                tenant_id, index_id, chunk_key="f2c0", source_file_id="file2.txt"
            ),
        ]
        await client.upsert_chunks(chunks)

        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT doc_count, chunk_count FROM search_index_registry "
                    "WHERE tenant_id=:tid AND index_id=:iid"
                ),
                {"tid": tenant_id, "iid": index_id},
            )
            row = result.fetchone()
            assert row is not None
            assert (
                row[0] == 2
            ), f"Expected doc_count=2, got {row[0]}"  # 2 distinct files
            assert row[1] == 3, f"Expected chunk_count=3, got {row[1]}"  # 3 chunks

    async def test_delete_updates_registry(self, tenant_id, index_id):
        """After delete_by_source_file, registry counts reflect the deletion."""
        client = PgVectorSearchClient()
        chunks = [
            make_chunk(tenant_id, index_id, chunk_key="fa_c0", source_file_id="a.txt"),
            make_chunk(tenant_id, index_id, chunk_key="fa_c1", source_file_id="a.txt"),
            make_chunk(tenant_id, index_id, chunk_key="fb_c0", source_file_id="b.txt"),
        ]
        await client.upsert_chunks(chunks)

        await client.delete_by_source_file(tenant_id, index_id, "a.txt")

        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT chunk_count FROM search_index_registry "
                    "WHERE tenant_id=:tid AND index_id=:iid"
                ),
                {"tid": tenant_id, "iid": index_id},
            )
            row = result.fetchone()
            assert row is not None
            assert (
                row[0] == 1
            ), f"Expected chunk_count=1 after deleting a.txt chunks, got {row[0]}"

    async def test_search_empty_index_no_exception(self, tenant_id, index_id):
        """Searching an empty index returns [] without exceptions."""
        client = PgVectorSearchClient()
        results = await client.knn_search(
            index_id=index_id,
            vector=make_embedding(),
            top_k=5,
            query_text=None,
            tenant_id=tenant_id,
        )
        assert results == []
