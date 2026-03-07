"""
Unit tests for VectorSearchService (AI-055).

Tests vector search, result formatting, and cloud provider abstraction.
Tier 1: Fast, isolated, mocks search backend.
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSearchResult:
    """Test SearchResult data class."""

    def test_search_result_has_required_fields(self):
        """SearchResult must have title, content, score, source_url, document_id."""
        from app.modules.chat.vector_search import SearchResult

        result = SearchResult(
            title="Test Document",
            content="Some content here",
            score=0.95,
            source_url="https://sharepoint.com/doc1",
            document_id="doc-123",
        )
        assert result.title == "Test Document"
        assert result.content == "Some content here"
        assert result.score == 0.95
        assert result.source_url == "https://sharepoint.com/doc1"
        assert result.document_id == "doc-123"

    def test_search_result_to_dict(self):
        """SearchResult.to_dict() returns all fields as a dictionary."""
        from app.modules.chat.vector_search import SearchResult

        result = SearchResult(
            title="Doc",
            content="Content",
            score=0.8,
            source_url=None,
            document_id="doc-1",
        )
        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["title"] == "Doc"
        assert d["content"] == "Content"
        assert d["score"] == 0.8
        assert d["document_id"] == "doc-1"

    def test_search_result_source_url_optional(self):
        """source_url can be None."""
        from app.modules.chat.vector_search import SearchResult

        result = SearchResult(
            title="Doc",
            content="Content",
            score=0.8,
            source_url=None,
            document_id="doc-1",
        )
        assert result.source_url is None


class TestVectorSearchService:
    """Test VectorSearchService methods."""

    @pytest.mark.asyncio
    async def test_search_returns_list_of_search_results(self):
        """search() returns a list of SearchResult objects."""
        from app.modules.chat.vector_search import SearchResult, VectorSearchService

        service = VectorSearchService.__new__(VectorSearchService)

        mock_raw_results = [
            {
                "title": "HR Policy v2",
                "content": "Leave policy details...",
                "score": 0.92,
                "source_url": "https://sp.com/hr",
                "id": "doc-1",
            },
            {
                "title": "Benefits Guide",
                "content": "Health benefits...",
                "score": 0.85,
                "source_url": None,
                "id": "doc-2",
            },
        ]

        service._client = AsyncMock()
        service._client.knn_search = AsyncMock(return_value=mock_raw_results)

        results = await service.search(
            query_vector=[0.1, 0.2, 0.3],
            tenant_id="tenant-abc",
            agent_id="agent-1",
            top_k=10,
        )

        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)
        assert results[0].title == "HR Policy v2"
        assert results[0].score == 0.92
        assert results[1].document_id == "doc-2"

    @pytest.mark.asyncio
    async def test_search_uses_tenant_agent_index_name(self):
        """Search index name must be {tenant_id}-{agent_id}."""
        from app.modules.chat.vector_search import VectorSearchService

        service = VectorSearchService.__new__(VectorSearchService)
        service._client = AsyncMock()
        service._client.knn_search = AsyncMock(return_value=[])

        await service.search(
            query_vector=[0.1],
            tenant_id="acme-corp",
            agent_id="hr-bot",
            top_k=5,
        )

        service._client.knn_search.assert_called_once()
        call_kwargs = service._client.knn_search.call_args
        assert call_kwargs.kwargs.get("index") == "acme-corp-hr-bot" or (
            len(call_kwargs.args) > 0 and call_kwargs.args[0] == "acme-corp-hr-bot"
        )

    @pytest.mark.asyncio
    async def test_search_passes_top_k(self):
        """top_k parameter is forwarded to the search client."""
        from app.modules.chat.vector_search import VectorSearchService

        service = VectorSearchService.__new__(VectorSearchService)
        service._client = AsyncMock()
        service._client.knn_search = AsyncMock(return_value=[])

        await service.search(
            query_vector=[0.1],
            tenant_id="t1",
            agent_id="a1",
            top_k=20,
        )

        call_kwargs = service._client.knn_search.call_args
        assert call_kwargs.kwargs.get("top_k") == 20

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        """search() returns empty list when no results found."""
        from app.modules.chat.vector_search import VectorSearchService

        service = VectorSearchService.__new__(VectorSearchService)
        service._client = AsyncMock()
        service._client.knn_search = AsyncMock(return_value=[])

        results = await service.search(
            query_vector=[0.1],
            tenant_id="t1",
            agent_id="a1",
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_search_default_top_k_is_10(self):
        """Default top_k should be 10."""
        from app.modules.chat.vector_search import VectorSearchService

        service = VectorSearchService.__new__(VectorSearchService)
        service._client = AsyncMock()
        service._client.knn_search = AsyncMock(return_value=[])

        await service.search(
            query_vector=[0.1],
            tenant_id="t1",
            agent_id="a1",
        )

        call_kwargs = service._client.knn_search.call_args
        assert call_kwargs.kwargs.get("top_k") == 10

    @pytest.mark.asyncio
    async def test_search_validates_tenant_id(self):
        """search() raises ValueError if tenant_id is empty."""
        from app.modules.chat.vector_search import VectorSearchService

        service = VectorSearchService.__new__(VectorSearchService)
        service._client = AsyncMock()

        with pytest.raises(ValueError, match="tenant_id"):
            await service.search(
                query_vector=[0.1],
                tenant_id="",
                agent_id="a1",
            )

    @pytest.mark.asyncio
    async def test_search_validates_agent_id(self):
        """search() raises ValueError if agent_id is empty."""
        from app.modules.chat.vector_search import VectorSearchService

        service = VectorSearchService.__new__(VectorSearchService)
        service._client = AsyncMock()

        with pytest.raises(ValueError, match="agent_id"):
            await service.search(
                query_vector=[0.1],
                tenant_id="t1",
                agent_id="",
            )


class TestRetrievalConfidenceCalculator:
    """Test confidence scoring for search results."""

    def test_high_scores_produce_high_confidence(self):
        """Multiple high-scoring results should yield high confidence."""
        from app.modules.chat.vector_search import (
            RetrievalConfidenceCalculator,
            SearchResult,
        )

        calc = RetrievalConfidenceCalculator()
        results = [
            SearchResult("A", "Content", 0.95, None, "1"),
            SearchResult("B", "Content", 0.90, None, "2"),
            SearchResult("C", "Content", 0.88, None, "3"),
        ]
        confidence = calc.calculate(results)
        assert confidence >= 0.8

    def test_low_scores_produce_low_confidence(self):
        """Low-scoring results should yield low confidence."""
        from app.modules.chat.vector_search import (
            RetrievalConfidenceCalculator,
            SearchResult,
        )

        calc = RetrievalConfidenceCalculator()
        results = [
            SearchResult("A", "Content", 0.3, None, "1"),
            SearchResult("B", "Content", 0.25, None, "2"),
        ]
        confidence = calc.calculate(results)
        assert confidence < 0.5

    def test_no_results_returns_zero_confidence(self):
        """No results should return 0.0 confidence."""
        from app.modules.chat.vector_search import RetrievalConfidenceCalculator

        calc = RetrievalConfidenceCalculator()
        confidence = calc.calculate([])
        assert confidence == 0.0

    def test_confidence_between_0_and_1(self):
        """Confidence score must always be between 0.0 and 1.0."""
        from app.modules.chat.vector_search import (
            RetrievalConfidenceCalculator,
            SearchResult,
        )

        calc = RetrievalConfidenceCalculator()
        results = [
            SearchResult("A", "Content", 0.5, None, "1"),
        ]
        confidence = calc.calculate(results)
        assert 0.0 <= confidence <= 1.0
