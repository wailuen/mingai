"""
EmbeddingService (AI-054) - Query embedding generation with Redis caching.

Model from EMBEDDING_MODEL env var - NEVER hardcoded.
Cache TTL: 24 hours. Cache key: mingai:{tenant_id}:embedding_cache:{hash}.
"""
import hashlib
import json
import os

import structlog
from openai import AsyncOpenAI

from app.core.redis_client import get_redis

logger = structlog.get_logger()

# Cache TTL: 24 hours
EMBEDDING_CACHE_TTL_SECONDS = 86400


class EmbeddingService:
    """
    Generates query embeddings using OpenAI API with Redis caching.

    Model is read from EMBEDDING_MODEL environment variable.
    When tenant_id is provided, embeddings are cached in Redis with
    the key format: mingai:{tenant_id}:embedding_cache:{sha256_hash[:16]}.
    """

    def __init__(self):
        model = os.environ.get("EMBEDDING_MODEL", "").strip()
        if not model:
            raise ValueError(
                "EMBEDDING_MODEL environment variable is required. "
                "Set it in .env to the embedding model name "
                "(e.g., 'text-embedding-3-small')."
            )
        self._model = model
        self._client = AsyncOpenAI()  # Reads API key from env

    async def embed(self, text: str, tenant_id: str | None = None) -> list[float]:
        """
        Generate an embedding vector for the given text.

        Args:
            text: The text to embed. Must not be empty.
            tenant_id: If provided, cache the result in Redis.

        Returns:
            List of floats representing the embedding vector.

        Raises:
            ValueError: If text is empty or None.
        """
        if text is None:
            raise ValueError(
                "Text for embedding must not be None. "
                "Provide a non-empty string to embed."
            )
        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                "Text for embedding must not be empty or blank. "
                "Provide a non-empty string to embed."
            )

        # Check Redis cache if tenant_id is provided
        if tenant_id:
            cache_key = self._build_cache_key(tenant_id, text)
            redis = get_redis()
            cached = await redis.get(cache_key)
            if cached:
                logger.debug(
                    "embedding_cache_hit",
                    tenant_id=tenant_id,
                    text_hash=cache_key.split(":")[-1],
                )
                return json.loads(cached)

        # Call OpenAI API
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
        )
        vector = response.data[0].embedding

        # Store in Redis cache if tenant_id is provided
        if tenant_id:
            await redis.setex(
                cache_key,
                EMBEDDING_CACHE_TTL_SECONDS,
                json.dumps(vector),
            )
            logger.debug(
                "embedding_cached",
                tenant_id=tenant_id,
                text_hash=cache_key.split(":")[-1],
                vector_dim=len(vector),
            )

        return vector

    @staticmethod
    def _build_cache_key(tenant_id: str, text: str) -> str:
        """
        Build a Redis cache key for an embedding.

        Format: mingai:{tenant_id}:embedding_cache:{sha256_hash[:16]}
        """
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        return f"mingai:{tenant_id}:embedding_cache:{text_hash}"
