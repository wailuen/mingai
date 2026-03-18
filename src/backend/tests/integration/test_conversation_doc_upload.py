"""
Integration tests for conversation document upload endpoint (TODO-11).

Tier 2 — real PostgreSQL with pgvector. No DB mocking.
EmbeddingService is mocked (avoid Azure API calls in CI).
"""
import io
import uuid
import pytest
from unittest.mock import AsyncMock, patch

pytestmark = pytest.mark.integration
from sqlalchemy import text

from app.core.session import async_session_factory
from app.modules.chat.vector_search import PgVectorSearchClient
from tests.fixtures.vector_search_fixtures import make_embedding


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tenant_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def user_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def conversation_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture(autouse=True)
async def setup_and_cleanup(tenant_id, user_id, conversation_id):
    """Create tenant, user, and conversation rows; clean up after."""
    slug = f"int-{tenant_id[:8]}"
    async with async_session_factory() as session:
        # Tenant
        await session.execute(
            text(
                "INSERT INTO tenants (id, name, slug, plan, status, primary_contact_email) "
                "VALUES (CAST(:tid AS uuid), :name, :slug, 'starter', 'active', 'test@test.test') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"tid": tenant_id, "name": f"DocUpload Test {tenant_id[:8]}", "slug": slug},
        )
        # User
        await session.execute(
            text(
                "INSERT INTO users (id, tenant_id, email, role, status) "
                "VALUES (CAST(:uid AS uuid), CAST(:tid AS uuid), :email, 'viewer', 'active') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "uid": user_id,
                "tid": tenant_id,
                "email": f"test-{user_id[:8]}@test.test",
            },
        )
        # Conversation
        await session.execute(
            text(
                "INSERT INTO conversations (id, tenant_id, user_id, title) "
                "VALUES (CAST(:cid AS uuid), CAST(:tid AS uuid), CAST(:uid AS uuid), 'Test Conversation') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"cid": conversation_id, "tid": tenant_id, "uid": user_id},
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
            text("DELETE FROM conversations WHERE tenant_id = CAST(:tid AS uuid)"),
            {"tid": tenant_id},
        )
        await session.execute(
            text("DELETE FROM users WHERE tenant_id = CAST(:tid AS uuid)"),
            {"tid": tenant_id},
        )
        await session.execute(
            text("DELETE FROM tenants WHERE id = CAST(:tid AS uuid)"),
            {"tid": tenant_id},
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Pipeline tests (test DocumentIndexingPipeline.process_conversation_file directly)
# ---------------------------------------------------------------------------


class TestProcessConversationFileIntegration:
    async def test_txt_file_indexed_to_pgvector(
        self, tmp_path, tenant_id, user_id, conversation_id
    ):
        """A .txt file is parsed, chunked, and upserted into search_chunks."""
        from app.modules.documents.indexing import DocumentIndexingPipeline

        txt_file = tmp_path / "test.txt"
        txt_file.write_text(
            "This document discusses quarterly revenue performance for 2025. "
            "The sales team exceeded targets by 15 percent in Q3. "
            "Key drivers were enterprise contract renewals and new logo acquisition."
        )

        with patch("app.modules.documents.indexing.EmbeddingService") as MockEmbed:
            MockEmbed.return_value.embed = AsyncMock(
                return_value=make_embedding(seed=42)
            )

            pipeline = DocumentIndexingPipeline()
            result = await pipeline.process_conversation_file(
                file_path=str(txt_file),
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
            )

        assert result["chunks_indexed"] >= 1
        assert result["conversation_id"] == conversation_id
        assert result["index_id"] == f"conv-{tenant_id}-{conversation_id}"
        assert result["file_name"] == "test.txt"

        # Verify chunk is actually in the DB
        async with async_session_factory() as session:
            row = await session.execute(
                text(
                    "SELECT COUNT(*) FROM search_chunks "
                    "WHERE tenant_id = CAST(:tid AS uuid) "
                    "AND conversation_id = CAST(:cid AS uuid) "
                    "AND source_type = 'conversation'"
                ),
                {"tid": tenant_id, "cid": conversation_id},
            )
            count = row.scalar()
        assert count >= 1, f"Expected chunks in DB, got {count}"

    async def test_search_chunks_visible_after_upload(
        self, tmp_path, tenant_id, user_id, conversation_id
    ):
        """After upload, knn_search on the conv index returns the uploaded chunk."""
        from app.modules.documents.indexing import DocumentIndexingPipeline

        query_emb = make_embedding(seed=1)

        txt_file = tmp_path / "revenue.txt"
        txt_file.write_text("This document is about revenue forecasting for 2025.")

        with patch("app.modules.documents.indexing.EmbeddingService") as MockEmbed:
            # Use the same embedding for both doc and query so it definitely matches
            MockEmbed.return_value.embed = AsyncMock(return_value=query_emb)

            pipeline = DocumentIndexingPipeline()
            await pipeline.process_conversation_file(
                file_path=str(txt_file),
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
            )

        client = PgVectorSearchClient()
        results = await client.knn_search(
            index_id=f"conv-{tenant_id}-{conversation_id}",
            vector=query_emb,
            top_k=5,
            query_text=None,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
        )
        assert len(results) >= 1, f"Expected search results, got {results}"

    async def test_delete_conversation_removes_chunks(
        self, tmp_path, tenant_id, user_id, conversation_id
    ):
        """Deleting a conversation also removes its search_chunks (BE-9 fix)."""
        from app.modules.documents.indexing import DocumentIndexingPipeline
        from app.modules.chat.routes import delete_conversation

        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Content that will be deleted with the conversation.")

        with patch("app.modules.documents.indexing.EmbeddingService") as MockEmbed:
            MockEmbed.return_value.embed = AsyncMock(
                return_value=make_embedding(seed=5)
            )

            pipeline = DocumentIndexingPipeline()
            await pipeline.process_conversation_file(
                file_path=str(txt_file),
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
            )

        # Verify chunks exist before deletion
        async with async_session_factory() as session:
            count_before = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM search_chunks "
                        "WHERE conversation_id = CAST(:cid AS uuid)"
                    ),
                    {"cid": conversation_id},
                )
            ).scalar()
        assert count_before >= 1

        # Delete the conversation
        async with async_session_factory() as session:
            deleted = await delete_conversation(
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
                db=session,
            )
        assert deleted is True

        # Verify chunks are gone
        async with async_session_factory() as session:
            count_after = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM search_chunks "
                        "WHERE conversation_id = CAST(:cid AS uuid)"
                    ),
                    {"cid": conversation_id},
                )
            ).scalar()
        assert count_after == 0, f"Expected 0 chunks after delete, got {count_after}"

    async def test_idempotent_upload(
        self, tmp_path, tenant_id, user_id, conversation_id
    ):
        """Uploading the same file twice does not double the chunk count."""
        from app.modules.documents.indexing import DocumentIndexingPipeline

        txt_file = tmp_path / "idempotent.txt"
        txt_file.write_text("This is idempotency test content for pgvector upload.")

        with patch("app.modules.documents.indexing.EmbeddingService") as MockEmbed:
            MockEmbed.return_value.embed = AsyncMock(
                return_value=make_embedding(seed=7)
            )

            pipeline = DocumentIndexingPipeline()
            result1 = await pipeline.process_conversation_file(
                file_path=str(txt_file),
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            result2 = await pipeline.process_conversation_file(
                file_path=str(txt_file),
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
            )

        async with async_session_factory() as session:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM search_chunks "
                        "WHERE tenant_id = CAST(:tid AS uuid) "
                        "AND conversation_id = CAST(:cid AS uuid)"
                    ),
                    {"tid": tenant_id, "cid": conversation_id},
                )
            ).scalar()

        # Chunk count should equal result1["chunks_indexed"] (not doubled)
        assert (
            count == result1["chunks_indexed"]
        ), f"Expected {result1['chunks_indexed']} chunks (no duplication), got {count}"

    async def test_cross_tenant_isolation(
        self, tmp_path, tenant_id, user_id, conversation_id
    ):
        """Conversation chunks are invisible to other tenants' searches."""
        from app.modules.documents.indexing import DocumentIndexingPipeline

        other_tenant = str(uuid.uuid4())
        query_emb = make_embedding(seed=10)

        txt_file = tmp_path / "isolated.txt"
        txt_file.write_text("Secret financial data for tenant A only.")

        with patch("app.modules.documents.indexing.EmbeddingService") as MockEmbed:
            MockEmbed.return_value.embed = AsyncMock(return_value=query_emb)

            pipeline = DocumentIndexingPipeline()
            await pipeline.process_conversation_file(
                file_path=str(txt_file),
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
            )

        # Search as other_tenant — should find nothing
        client = PgVectorSearchClient()
        results = await client.knn_search(
            index_id=f"conv-{tenant_id}-{conversation_id}",
            vector=query_emb,
            top_k=5,
            query_text=None,
            tenant_id=other_tenant,  # different tenant
            conversation_id=conversation_id,
        )
        assert results == [], f"Other tenant should see no results, got {results}"
