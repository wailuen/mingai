"""
EmbeddingService (AI-054) - Query embedding generation with Redis caching.

Model from EMBEDDING_MODEL env var - NEVER hardcoded.
Cache TTL: 24 hours. Cache key: mingai:{tenant_id}:embedding_cache:{hash}.
"""
import hashlib
import json
import os

import structlog

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

    Phase 2: Optionally accepts an InstrumentedLLMClient at construction.
    When provided AND tenant_id is supplied, routing goes through the
    instrumented client (for usage tracking). Falls back to direct API
    for backwards compatibility when instrumented_client is None.
    """

    def __init__(self, instrumented_client=None):
        """
        Args:
            instrumented_client: Optional InstrumentedLLMClient instance.
                                 When provided and tenant_id is given, embeddings
                                 route through it for usage tracking.
        """
        self._instrumented_client = instrumented_client
        model = os.environ.get("EMBEDDING_MODEL", "").strip()
        if not model:
            raise ValueError(
                "EMBEDDING_MODEL environment variable is required. "
                "Set it in .env to the embedding model name "
                "(e.g., 'text-embedding-3-small')."
            )
        self._model = model

        cloud_provider = os.environ.get("CLOUD_PROVIDER", "local").strip()
        if cloud_provider == "azure":
            from openai import AsyncAzureOpenAI

            api_key = os.environ.get("AZURE_PLATFORM_OPENAI_API_KEY", "").strip()
            endpoint = os.environ.get("AZURE_PLATFORM_OPENAI_ENDPOINT", "").strip()
            if not api_key:
                raise ValueError(
                    "AZURE_PLATFORM_OPENAI_API_KEY is required when CLOUD_PROVIDER=azure."
                )
            if not endpoint:
                raise ValueError(
                    "AZURE_PLATFORM_OPENAI_ENDPOINT is required when CLOUD_PROVIDER=azure."
                )
            self._client = AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=endpoint,
                api_version="2024-02-01",
            )
        else:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI()

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

        # Route through InstrumentedLLMClient when available and tenant_id provided
        if tenant_id and getattr(self, "_instrumented_client", None) is not None:
            try:
                vectors = await self._instrumented_client.embed(
                    tenant_id=tenant_id,
                    texts=[text],
                )
                vector = vectors[0] if vectors else []
            except Exception as exc:
                logger.warning(
                    "embedding_instrumented_client_failed",
                    tenant_id=tenant_id,
                    error=str(exc),
                )
                # Fall back to direct API
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=text,
                )
                vector = response.data[0].embedding
        else:
            # Direct API call (legacy / no tenant_id path)
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
