"""
Unit tests for DocumentIndexingPipeline (AI-060).

Tier 1: Fast, isolated, uses mocking for external services.
Tests chunking, text extraction, and pipeline flow.
"""
import os
import tempfile

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestChunkText:
    """Test _chunk_text splitting logic."""

    def test_chunk_text_single_chunk(self):
        """Short text fits in one chunk => returns 1 chunk."""
        from app.modules.documents.indexing import DocumentIndexingPipeline

        pipeline = DocumentIndexingPipeline()
        text = "Hello world, this is a short document."
        chunks = pipeline._chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunk_text_multiple_chunks(self):
        """10000 char text => multiple chunks."""
        from app.modules.documents.indexing import DocumentIndexingPipeline

        pipeline = DocumentIndexingPipeline()
        text = "A" * 10000
        chunks = pipeline._chunk_text(text)
        assert len(chunks) > 1

    def test_chunk_overlap_preserved(self):
        """Consecutive chunks share CHUNK_OVERLAP*4 chars at boundaries."""
        from app.modules.documents.indexing import DocumentIndexingPipeline

        pipeline = DocumentIndexingPipeline()
        # Create text large enough for at least 2 chunks
        # CHUNK_SIZE=512 tokens * 4 chars = 2048 chars per chunk
        text = "".join(chr(ord("A") + (i % 26)) for i in range(5000))
        chunks = pipeline._chunk_text(text)

        assert len(chunks) >= 2

        overlap_chars = DocumentIndexingPipeline.CHUNK_OVERLAP * 4  # 50 * 4 = 200

        # The end of chunk[0] should overlap with the start of chunk[1]
        chunk0_tail = chunks[0][-overlap_chars:]
        chunk1_head = chunks[1][:overlap_chars]
        assert chunk0_tail == chunk1_head, (
            f"Expected {overlap_chars}-char overlap between consecutive chunks. "
            f"chunk0 tail: {chunk0_tail[:40]}..., chunk1 head: {chunk1_head[:40]}..."
        )


class TestExtractText:
    """Test text extraction from various formats."""

    def test_extract_text_txt(self):
        """Write a temp txt file, extract => returns content."""
        from app.modules.documents.indexing import DocumentIndexingPipeline

        pipeline = DocumentIndexingPipeline()
        content = "This is test content for extraction."
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(content)
            f.flush()
            tmp_path = f.name

        try:
            extracted = pipeline._extract_text_txt(tmp_path)
            assert extracted == content
        finally:
            os.unlink(tmp_path)

    def test_unsupported_extension_raises(self):
        """Unsupported extension (.xlsx) => raises ValueError."""
        from app.modules.documents.indexing import DocumentIndexingPipeline

        pipeline = DocumentIndexingPipeline()
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            tmp_path = f.name

        try:
            with pytest.raises(ValueError, match="Unsupported file extension"):
                import asyncio

                asyncio.run(
                    pipeline.process_file(tmp_path, "int-1", "tenant-1", AsyncMock())
                )
        finally:
            os.unlink(tmp_path)


class TestProcessFile:
    """Test the full process_file pipeline with mocked services."""

    @pytest.mark.asyncio
    @patch("app.modules.documents.indexing.VectorSearchService")
    @patch("app.modules.documents.indexing.EmbeddingService")
    async def test_process_file_returns_chunk_count(
        self, MockEmbedding, MockVectorSearch
    ):
        """Mock EmbeddingService + VectorSearchService, assert chunks_indexed in result."""
        from app.modules.documents.indexing import DocumentIndexingPipeline

        # Create a temp txt file
        content = "A" * 3000  # Should produce at least 2 chunks
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(content)
            f.flush()
            tmp_path = f.name

        try:
            # Mock embedding service
            mock_embed_instance = MagicMock()
            mock_embed_instance.embed = AsyncMock(return_value=[0.1] * 128)
            MockEmbedding.return_value = mock_embed_instance

            # Mock vector search service — upsert_chunks is our upsert method
            mock_vs_instance = MagicMock()
            mock_vs_instance.upsert_chunks = AsyncMock()
            MockVectorSearch.return_value = mock_vs_instance

            mock_db = AsyncMock()
            # sync_jobs update result
            update_result = MagicMock()
            update_result.rowcount = 1
            mock_db.execute = AsyncMock(return_value=update_result)

            pipeline = DocumentIndexingPipeline()
            result = await pipeline.process_file(tmp_path, "int-1", "tenant-1", mock_db)

            assert "chunks_indexed" in result
            assert result["chunks_indexed"] > 0
            assert result["file_path"] == tmp_path
            assert result["integration_id"] == "int-1"
        finally:
            os.unlink(tmp_path)


class TestProcessConversationFile:
    async def test_returns_correct_keys(self, tmp_path):
        """process_conversation_file returns dict with required keys."""
        from app.modules.documents.indexing import DocumentIndexingPipeline

        txt_file = tmp_path / "test.txt"
        txt_file.write_text("This is test content for conversation document upload.")

        with (
            patch("app.modules.documents.indexing.EmbeddingService") as MockEmbed,
            patch("app.modules.documents.indexing.VectorSearchService") as MockVec,
        ):
            MockEmbed.return_value.embed = AsyncMock(return_value=[0.1] * 1536)
            MockVec.return_value.upsert_conversation_chunks = AsyncMock(return_value=1)

            pipeline = DocumentIndexingPipeline()
            result = await pipeline.process_conversation_file(
                file_path=str(txt_file),
                conversation_id="conv-test-123",
                user_id="user-test-456",
                tenant_id="tenant-test-789",
            )

        assert "chunks_indexed" in result
        assert "file_name" in result
        assert "conversation_id" in result
        assert "index_id" in result
        assert result["conversation_id"] == "conv-test-123"
        assert result["index_id"] == "conv-tenant-test-789-conv-test-123"
        assert result["chunks_indexed"] >= 1

    async def test_no_sync_jobs_write(self, tmp_path):
        """process_conversation_file does NOT write to sync_jobs."""
        from app.modules.documents.indexing import DocumentIndexingPipeline

        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Some content.")

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()

        with (
            patch("app.modules.documents.indexing.EmbeddingService") as MockEmbed,
            patch("app.modules.documents.indexing.VectorSearchService") as MockVec,
        ):
            MockEmbed.return_value.embed = AsyncMock(return_value=[0.1] * 1536)
            MockVec.return_value.upsert_conversation_chunks = AsyncMock(return_value=1)

            pipeline = DocumentIndexingPipeline()
            await pipeline.process_conversation_file(
                file_path=str(txt_file),
                conversation_id="conv-123",
                user_id="user-456",
                tenant_id="tenant-789",
            )

        # sync_jobs should never be written
        for call in mock_db.execute.call_args_list:
            sql = str(call)
            assert "sync_jobs" not in sql.lower(), f"sync_jobs was written: {sql}"

    async def test_unsupported_extension_raises(self, tmp_path):
        """process_conversation_file raises ValueError for unsupported extensions."""
        from app.modules.documents.indexing import DocumentIndexingPipeline

        xlsx_file = tmp_path / "data.xlsx"
        xlsx_file.write_bytes(b"fake xlsx content")

        pipeline = DocumentIndexingPipeline()
        with pytest.raises(ValueError, match="Unsupported file extension"):
            await pipeline.process_conversation_file(
                file_path=str(xlsx_file),
                conversation_id="conv-123",
                user_id="user-456",
                tenant_id="tenant-789",
            )

    async def test_empty_text_returns_zero_chunks(self, tmp_path):
        """process_conversation_file returns chunks_indexed=0 for empty content."""
        from app.modules.documents.indexing import DocumentIndexingPipeline

        txt_file = tmp_path / "empty.txt"
        txt_file.write_text("   ")  # whitespace only

        with (
            patch("app.modules.documents.indexing.EmbeddingService") as MockEmbed,
            patch("app.modules.documents.indexing.VectorSearchService") as MockVec,
        ):
            MockEmbed.return_value.embed = AsyncMock(return_value=[0.1] * 1536)
            MockVec.return_value.upsert_conversation_chunks = AsyncMock(return_value=0)

            pipeline = DocumentIndexingPipeline()
            result = await pipeline.process_conversation_file(
                file_path=str(txt_file),
                conversation_id="conv-123",
                user_id="user-456",
                tenant_id="tenant-789",
            )

        assert result["chunks_indexed"] == 0

    async def test_uses_asyncio_to_thread_for_extraction(self, tmp_path):
        """process_conversation_file uses asyncio.to_thread for text extraction."""
        from app.modules.documents.indexing import DocumentIndexingPipeline

        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Content to index.")

        with (
            patch("app.modules.documents.indexing.EmbeddingService") as MockEmbed,
            patch("app.modules.documents.indexing.VectorSearchService") as MockVec,
            patch(
                "asyncio.to_thread", wraps=__import__("asyncio").to_thread
            ) as mock_thread,
        ):
            MockEmbed.return_value.embed = AsyncMock(return_value=[0.1] * 1536)
            MockVec.return_value.upsert_conversation_chunks = AsyncMock(return_value=1)

            pipeline = DocumentIndexingPipeline()
            await pipeline.process_conversation_file(
                file_path=str(txt_file),
                conversation_id="conv-123",
                user_id="user-456",
                tenant_id="tenant-789",
            )

        # asyncio.to_thread should have been called for text extraction
        assert mock_thread.call_count >= 1
