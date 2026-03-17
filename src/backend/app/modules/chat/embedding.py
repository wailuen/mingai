"""
EmbeddingService (AI-054) - Query embedding generation with Redis caching.

CACHE-002 updates:
- Cache key includes model_id: mingai:{tenant_id}:emb:{model_id}:{sha256(text)}
- Serialization: float16 binary (struct.pack) instead of JSON
- TTL: 604800s (7 days) instead of 86400s (24h)

Model from EMBEDDING_MODEL env var - NEVER hardcoded.
Cache key type: emb (registered in VALID_CACHE_TYPES).
"""
import hashlib
import os
import struct

import structlog

from app.core.redis_client import get_redis_binary

logger = structlog.get_logger()

# CACHE-002: 7-day TTL for embedding cache
EMBEDDING_CACHE_TTL_SECONDS = 604800


class EmbeddingService:
    """
    Generates query embeddings using OpenAI API with Redis caching.

    Model is read from EMBEDDING_MODEL environment variable.
    When tenant_id is provided, embeddings are cached in Redis with
    the key format: mingai:{tenant_id}:emb:{model_id}:{sha256(text)}.

    Serialization uses float16 binary (struct.pack 'e' format) for
    ~50% storage reduction versus JSON. Deserialization converts back
    to float32 list transparently.

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
            api_version = os.environ.get(
                "AZURE_PLATFORM_OPENAI_API_VERSION", "2024-02-01"
            ).strip()
            self._client = AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=endpoint,
                api_version=api_version,
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
            cache_key = self._build_cache_key(tenant_id, text, self._model)
            redis = get_redis_binary()
            # CACHE-002: value is binary float16 bytes — must use binary pool
            cached_raw = await redis.get(cache_key)
            if cached_raw:
                logger.debug(
                    "embedding_cache_hit",
                    tenant_id=tenant_id,
                    model_id=self._model,
                )
                return _deserialize_float16(cached_raw)

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
            # CACHE-002: serialize as float16 binary bytes for compact storage
            binary_payload = _serialize_float16(vector)
            redis = get_redis_binary()
            await redis.setex(cache_key, EMBEDDING_CACHE_TTL_SECONDS, binary_payload)
            logger.debug(
                "embedding_cached",
                tenant_id=tenant_id,
                model_id=self._model,
                vector_dim=len(vector),
                bytes_stored=len(binary_payload),
            )

        return vector

    @staticmethod
    def _build_cache_key(tenant_id: str, text: str, model_id: str) -> str:
        """
        Build a Redis cache key for an embedding.

        CACHE-002 format: mingai:{tenant_id}:emb:{model_id}:{sha256(text)}

        The model_id is sanitized (replace special chars with underscore) to
        ensure it is safe for the Redis key namespace. The key type 'emb' is
        registered in VALID_CACHE_TYPES.

        Note: We build the key directly (not via build_redis_key) because
        model_id may contain hyphens/dots which are allowed by the safe-segment
        regex but we include it as a namespace segment, not a suffix part.
        """
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        # Sanitize model_id: keep only alphanumeric, hyphens, dots, underscores
        safe_model_id = _sanitize_model_id(model_id)
        return f"mingai:{tenant_id}:emb:{safe_model_id}:{text_hash}"


# ---------------------------------------------------------------------------
# Float16 binary serialization helpers (CACHE-002)
# ---------------------------------------------------------------------------


def _serialize_float16(vector: list[float]) -> bytes:
    """
    Serialize a float32 embedding vector as packed float16 bytes.

    Uses struct.pack with 'e' (16-bit float) format.
    Reduces storage by ~50% compared to JSON.

    Args:
        vector: List of float values (float32 precision).

    Returns:
        Bytes object, length = len(vector) * 2.
    """
    n = len(vector)
    return struct.pack(f"{n}e", *vector)


def _deserialize_float16(raw: bytes) -> list[float]:
    """
    Deserialize packed float16 bytes back to a list of floats.

    The returned values are float32 precision (Python float).

    Args:
        raw: Bytes from Redis binary pool (decode_responses=False).
             Length must be even.

    Returns:
        List of float values.
    """
    n = len(raw) // 2
    return list(struct.unpack(f"{n}e", raw))


def _sanitize_model_id(model_id: str) -> str:
    """
    Sanitize a model deployment name for use in a Redis key segment.

    Replaces characters that are not alphanumeric, hyphens, dots, or
    underscores with underscores.
    """
    import re

    return re.sub(r"[^A-Za-z0-9._-]", "_", model_id)
