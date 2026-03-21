"""ATA-005/006 unit tests: VectorSearchService._search_single_index and fan-out."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.modules.chat.vector_search import VectorSearchService, SearchResult


def _make_results(count: int, base_score: float = 0.9) -> list[SearchResult]:
    return [
        SearchResult(
            title=f"Doc {i}",
            content=f"Content {i}",
            score=base_score - i * 0.1,
            source_url=None,
            document_id=f"doc-{i}",
        )
        for i in range(count)
    ]


@pytest.mark.asyncio
async def test_search_single_index_calls_client():
    """_search_single_index passes correct params to knn_search."""
    mock_client = AsyncMock()
    mock_client.knn_search = AsyncMock(
        return_value=[
            {"title": "t", "content": "c", "score": 0.9, "chunk_key": "k"}
        ]
    )
    svc = VectorSearchService.__new__(VectorSearchService)
    svc._client = mock_client
    results = await svc._search_single_index(
        index_id="tenant-agent",
        query_vector=[0.1, 0.2],
        top_k=5,
        tenant_id="tenant",
        query_text="test",
    )
    assert len(results) == 1
    mock_client.knn_search.assert_called_once()


@pytest.mark.asyncio
async def test_search_no_kb_ids_uses_agent_index():
    """search() with no kb_ids queries only agent's own index."""
    mock_client = AsyncMock()
    mock_client.knn_search = AsyncMock(return_value=[])
    svc = VectorSearchService.__new__(VectorSearchService)
    svc._client = mock_client
    await svc.search(
        query_vector=[0.1],
        tenant_id="t1",
        agent_id="a1",
        top_k=5,
    )
    call_args = mock_client.knn_search.call_args
    assert call_args.kwargs["index_id"] == "t1-a1"


@pytest.mark.asyncio
async def test_search_with_kb_ids_fans_out():
    """search() with kb_ids queries agent index + each KB index."""
    call_count = 0

    async def fake_knn_search(**kwargs):
        nonlocal call_count
        call_count += 1
        return [
            {
                "title": f"Doc {call_count}",
                "content": "",
                "score": 0.8,
                "chunk_key": f"k{call_count}",
            }
        ]

    mock_client = MagicMock()
    mock_client.knn_search = fake_knn_search
    svc = VectorSearchService.__new__(VectorSearchService)
    svc._client = mock_client
    results = await svc.search(
        query_vector=[0.1],
        tenant_id="t1",
        agent_id="a1",
        top_k=10,
        kb_ids=["kb-1", "kb-2"],
    )
    assert call_count == 3  # agent index + 2 KB indexes
    assert len(results) == 3


@pytest.mark.asyncio
async def test_search_fan_out_skips_failed_index():
    """Failed KB index is logged and skipped, not raised."""
    call_count = 0

    async def fake_knn_search(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("Index not found")
        return [{"title": "t", "content": "", "score": 0.9, "chunk_key": "k"}]

    mock_client = MagicMock()
    mock_client.knn_search = fake_knn_search
    svc = VectorSearchService.__new__(VectorSearchService)
    svc._client = mock_client
    results = await svc.search(
        query_vector=[0.1],
        tenant_id="t1",
        agent_id="a1",
        kb_ids=["kb-1"],
    )
    # call_count==2: agent index (call 1, ok) + kb-1 (call 2, failed)
    # Only the agent index result survives — kb-1 is skipped
    assert call_count == 2
    assert len(results) == 1


@pytest.mark.asyncio
async def test_search_deduplicates_kb_ids():
    """Duplicate kb_id matching agent index is not searched twice."""
    call_count = 0

    async def fake_knn_search(**kwargs):
        nonlocal call_count
        call_count += 1
        return []

    mock_client = MagicMock()
    mock_client.knn_search = fake_knn_search
    svc = VectorSearchService.__new__(VectorSearchService)
    svc._client = mock_client
    await svc.search(
        query_vector=[0.1],
        tenant_id="t1",
        agent_id="a1",
        kb_ids=["t1-a1"],  # Same as agent's own index
    )
    # Deduplication: t1-a1 appears once in indexes_to_search
    assert call_count == 1


@pytest.mark.asyncio
async def test_search_results_sorted_by_score_on_fan_out():
    """Fan-out results are merged and re-sorted by score descending."""
    scores_returned = [0.3, 0.9, 0.6]  # out of order
    call_num = 0

    async def fake_knn_search(**kwargs):
        nonlocal call_num
        score = scores_returned[call_num]
        call_num += 1
        return [{"title": "t", "content": "", "score": score, "chunk_key": f"k{call_num}"}]

    mock_client = MagicMock()
    mock_client.knn_search = fake_knn_search
    svc = VectorSearchService.__new__(VectorSearchService)
    svc._client = mock_client
    results = await svc.search(
        query_vector=[0.1],
        tenant_id="t1",
        agent_id="a1",
        top_k=10,
        kb_ids=["kb-1", "kb-2"],
    )
    assert results[0].score == 0.9
    assert results[1].score == 0.6
    assert results[2].score == 0.3
