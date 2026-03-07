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
