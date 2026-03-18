"""
Unit tests for VectorSearchService conversation methods.
Tier 1 — pure Python, no DB.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestUpsertConversationChunks:
    async def test_uses_conv_prefix_index_id(self):
        """upsert_conversation_chunks() uses index_id = f'conv-{tenant_id}-{conv_id}'."""
        from app.modules.chat.vector_search import VectorSearchService

        mock_client = MagicMock()
        mock_client.upsert_chunks = AsyncMock(return_value=2)

        service = VectorSearchService.__new__(VectorSearchService)
        service._client = mock_client

        await service.upsert_conversation_chunks(
            tenant_id="tenant-123",
            conversation_id="conv-456",
            user_id="user-789",
            file_name="report.pdf",
            chunks=[
                {"text": "chunk one", "embedding": [0.1] * 1536},
                {"text": "chunk two", "embedding": [0.2] * 1536},
            ],
        )

        assert mock_client.upsert_chunks.call_count == 1
        called_chunks = mock_client.upsert_chunks.call_args[1]["chunks"]
        assert len(called_chunks) == 2
        assert called_chunks[0]["index_id"] == "conv-tenant-123-conv-456"
        assert called_chunks[0]["source_type"] == "conversation"
        assert called_chunks[0]["conversation_id"] == "conv-456"
        assert called_chunks[0]["user_id"] == "user-789"

    async def test_single_db_call_for_multiple_chunks(self):
        """All chunks are upserted in a single call (not per-chunk)."""
        from app.modules.chat.vector_search import VectorSearchService

        mock_client = MagicMock()
        mock_client.upsert_chunks = AsyncMock(return_value=3)

        service = VectorSearchService.__new__(VectorSearchService)
        service._client = mock_client

        await service.upsert_conversation_chunks(
            tenant_id="t",
            conversation_id="c",
            user_id="u",
            file_name="doc.txt",
            chunks=[
                {"text": f"chunk {i}", "embedding": [0.1] * 1536} for i in range(3)
            ],
        )

        # Exactly 1 upsert_chunks call regardless of chunk count
        assert mock_client.upsert_chunks.call_count == 1

    async def test_source_file_id_includes_conv_prefix(self):
        """source_file_id is prefixed with conv_{conv_id}_ for unique identification."""
        from app.modules.chat.vector_search import VectorSearchService

        mock_client = MagicMock()
        mock_client.upsert_chunks = AsyncMock(return_value=1)

        service = VectorSearchService.__new__(VectorSearchService)
        service._client = mock_client

        await service.upsert_conversation_chunks(
            tenant_id="t",
            conversation_id="myconv",
            user_id="u",
            file_name="report.pdf",
            chunks=[{"text": "text", "embedding": [0.1] * 1536}],
        )

        called_chunks = mock_client.upsert_chunks.call_args[1]["chunks"]
        assert called_chunks[0]["source_file_id"].startswith("conv_myconv_")


class TestSearchConversationIndex:
    async def test_uses_conv_prefix_index_id(self):
        """search_conversation_index() builds index_id = f'conv-{tenant_id}-{conv_id}'."""
        from app.modules.chat.vector_search import VectorSearchService, SearchResult

        mock_client = MagicMock()
        mock_client.knn_search = AsyncMock(return_value=[])

        service = VectorSearchService.__new__(VectorSearchService)
        service._client = mock_client

        results = await service.search_conversation_index(
            query_vector=[0.1] * 1536,
            tenant_id="tenant-abc",
            conversation_id="conv-xyz",
            query_text="revenue",
        )

        mock_client.knn_search.assert_called_once()
        call_kwargs = mock_client.knn_search.call_args[1]
        assert call_kwargs["index_id"] == "conv-tenant-abc-conv-xyz"
        assert results == []

    async def test_raises_on_missing_tenant_id(self):
        """search_conversation_index() raises ValueError if tenant_id is empty."""
        from app.modules.chat.vector_search import VectorSearchService

        service = VectorSearchService.__new__(VectorSearchService)
        service._client = MagicMock()

        with pytest.raises(ValueError, match="tenant_id"):
            await service.search_conversation_index(
                query_vector=[0.1] * 1536,
                tenant_id="",
                conversation_id="conv-xyz",
            )
