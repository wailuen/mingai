"""
VectorSearchService (AI-055) - Cloud-agnostic vector search.

Delegates to the appropriate search backend based on CLOUD_PROVIDER env var.
Index naming: {tenant_id}-{agent_id} (isolated per tenant per agent).
"""
import os
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class SearchResult:
    """A single search result from vector search."""

    title: str
    content: str
    score: float
    source_url: str | None
    document_id: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "title": self.title,
            "content": self.content,
            "score": self.score,
            "source_url": self.source_url,
            "document_id": self.document_id,
        }


class LocalSearchClient:
    """
    Local/development search client using pgvector.

    Used when CLOUD_PROVIDER=local.
    In production, replaced by Azure AI Search, OpenSearch, etc.
    """

    async def knn_search(
        self,
        *,
        index: str,
        vector: list[float],
        top_k: int = 10,
    ) -> list[dict]:
        """
        Perform k-nearest-neighbor search.

        Returns list of dicts with: title, content, score, source_url, id.
        """
        logger.info(
            "local_knn_search",
            index=index,
            top_k=top_k,
            vector_dim=len(vector),
        )
        # In local mode, this would query pgvector
        # Real implementation connects to PostgreSQL with pgvector extension
        return []


def get_search_client(cloud_provider: str | None = None):
    """
    Get the appropriate search client based on CLOUD_PROVIDER.

    Returns a client with an async knn_search() method.
    """
    provider = cloud_provider or os.environ.get("CLOUD_PROVIDER", "local")

    if provider == "local":
        return LocalSearchClient()
    elif provider == "azure":
        logger.info("search_client_init", provider="azure_ai_search")
        return LocalSearchClient()  # Placeholder - Azure AI Search in Phase 2
    elif provider == "aws":
        logger.info("search_client_init", provider="opensearch")
        return LocalSearchClient()  # Placeholder - OpenSearch in Phase 2
    elif provider == "gcp":
        logger.info("search_client_init", provider="vertex_ai")
        return LocalSearchClient()  # Placeholder - Vertex AI Search in Phase 2
    else:
        raise ValueError(
            f"Unknown CLOUD_PROVIDER: '{provider}'. "
            f"Must be one of: local, azure, aws, gcp."
        )


class VectorSearchService:
    """
    Cloud-agnostic vector search service.

    Delegates to the appropriate search backend (pgvector, Azure AI Search,
    OpenSearch, Vertex AI) based on CLOUD_PROVIDER.
    Index naming: {tenant_id}-{agent_id} (isolated per tenant per agent).
    """

    def __init__(self, cloud_provider: str | None = None):
        self._client = get_search_client(cloud_provider)

    async def search(
        self,
        query_vector: list[float],
        tenant_id: str,
        agent_id: str,
        top_k: int = 10,
    ) -> list[SearchResult]:
        """
        Search tenant's document index for this agent.

        Args:
            query_vector: Embedding vector of the query.
            tenant_id: Tenant identifier for index isolation.
            agent_id: Agent identifier for index scoping.
            top_k: Maximum number of results to return.

        Returns:
            List of SearchResult objects sorted by relevance.

        Raises:
            ValueError: If tenant_id or agent_id is empty.
        """
        if not tenant_id:
            raise ValueError(
                "tenant_id is required for vector search. "
                "Search indexes are tenant-scoped."
            )
        if not agent_id:
            raise ValueError(
                "agent_id is required for vector search. "
                "Search indexes are scoped per tenant per agent."
            )

        index_name = f"{tenant_id}-{agent_id}"

        raw_results = await self._client.knn_search(
            index=index_name,
            vector=query_vector,
            top_k=top_k,
        )

        results = [
            SearchResult(
                title=r["title"],
                content=r["content"],
                score=r["score"],
                source_url=r.get("source_url"),
                document_id=r["id"],
            )
            for r in raw_results
        ]

        logger.info(
            "vector_search_completed",
            tenant_id=tenant_id,
            agent_id=agent_id,
            index=index_name,
            result_count=len(results),
            top_score=results[0].score if results else 0.0,
        )

        return results


class RetrievalConfidenceCalculator:
    """
    Calculates a confidence score for search results.

    Uses a weighted average of top result scores, with emphasis
    on the top result and result count.
    """

    def calculate(self, results: list[SearchResult]) -> float:
        """
        Calculate retrieval confidence from search results.

        Returns a float between 0.0 and 1.0.
        0.0 = no results or very poor matches.
        1.0 = multiple high-confidence matches.
        """
        if not results:
            return 0.0

        scores = [r.score for r in results]

        # Top score weighted heavily (50%), average of rest (30%),
        # result count factor (20%)
        top_score = max(scores)
        avg_score = sum(scores) / len(scores)
        count_factor = min(len(scores) / 5.0, 1.0)  # Max out at 5 results

        confidence = (top_score * 0.5) + (avg_score * 0.3) + (count_factor * 0.2)

        # Clamp to [0.0, 1.0]
        return max(0.0, min(1.0, confidence))
