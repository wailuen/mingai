"""
Unit tests for RetrievalConfidenceCalculator and VectorSearchService input validation.

Tier 1: Pure Python — no database, no external infrastructure required.
DB-touching tests (PgVectorSearchClient, upsert, search) live in
tests/integration/test_pgvector_client.py.
"""
import pytest

from app.modules.chat.vector_search import (
    RetrievalConfidenceCalculator,
    SearchResult,
    VectorSearchService,
)
from tests.fixtures.vector_search_fixtures import make_embedding


# ---------------------------------------------------------------------------
# RetrievalConfidenceCalculator — pure Python, no DB
# ---------------------------------------------------------------------------


class TestRetrievalConfidenceCalculator:
    def _result(self, score: float) -> SearchResult:
        return SearchResult(
            title="t", content="c", score=score, source_url=None, document_id="d"
        )

    def test_empty_results_returns_zero(self):
        calc = RetrievalConfidenceCalculator()
        assert calc.calculate([]) == 0.0

    def test_single_low_score_below_half(self):
        """Single low-score result produces confidence < 0.5."""
        calc = RetrievalConfidenceCalculator()
        # score=0.3: top*0.5 + avg*0.3 + count*0.2 = 0.15 + 0.09 + 0.04 = 0.28
        result = calc.calculate([self._result(0.3)])
        assert result < 0.5, f"Expected < 0.5, got {result}"

    def test_single_perfect_score(self):
        """Single score=1.0 result: 0.5 + 0.3 + 0.04 = 0.84."""
        calc = RetrievalConfidenceCalculator()
        result = calc.calculate([self._result(1.0)])
        assert abs(result - 0.84) < 0.01, f"Expected ~0.84, got {result}"

    def test_five_perfect_scores_returns_one(self):
        """5 results all score=1.0 -> confidence = 1.0 (clamped)."""
        calc = RetrievalConfidenceCalculator()
        results = [self._result(1.0) for _ in range(5)]
        assert calc.calculate(results) == 1.0

    def test_confidence_clamped_to_zero_one(self):
        """Confidence is always in [0, 1]."""
        calc = RetrievalConfidenceCalculator()
        for score in [0.0, 0.1, 0.5, 0.99, 1.0]:
            result = calc.calculate([self._result(score)])
            assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# VectorSearchService input validation — no DB call (raises before reaching DB)
# ---------------------------------------------------------------------------


class TestVectorSearchServiceValidation:
    async def test_raises_on_empty_tenant_id(self):
        """VectorSearchService.search() raises ValueError for empty tenant_id."""
        service = VectorSearchService()
        with pytest.raises(ValueError, match="tenant_id"):
            await service.search(
                query_vector=make_embedding(),
                tenant_id="",
                agent_id="agent",
            )

    async def test_raises_on_empty_agent_id(self):
        """VectorSearchService.search() raises ValueError for empty agent_id."""
        service = VectorSearchService()
        with pytest.raises(ValueError, match="agent_id"):
            await service.search(
                query_vector=make_embedding(),
                tenant_id="some-tenant-id",
                agent_id="",
            )
