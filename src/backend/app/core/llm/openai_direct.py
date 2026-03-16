"""
OpenAI Direct LLM and Embedding Provider adapters (P2LLM-003).

Reads credentials from environment variables:
    OPENAI_API_KEY  (or passed explicitly at construction)

API keys are NEVER exposed in __repr__, logs, or exception messages.
"""
import os
import time

import structlog

from app.core.llm.base import CompletionResponse, EmbeddingProvider, LLMProvider

logger = structlog.get_logger()


class OpenAIDirectProvider(LLMProvider):
    """
    OpenAI Direct chat completion adapter (non-Azure).

    Accepts an optional api_key at construction; if None, reads OPENAI_API_KEY
    from environment. The key is stored privately and never appears in repr
    or exception messages.
    """

    def __init__(self, api_key: str | None = None) -> None:
        from openai import AsyncOpenAI

        resolved_key = api_key or os.environ.get("OPENAI_API_KEY", "").strip()
        if not resolved_key:
            raise ValueError(
                "OpenAI API key is required for OpenAIDirectProvider. "
                "Pass api_key= or set OPENAI_API_KEY in .env."
            )
        # Store key privately — never in public attributes
        self._client = AsyncOpenAI(api_key=resolved_key)
        # Keep a flag for repr without exposing the key
        self._key_source = "explicit" if api_key else "env"

    def __repr__(self) -> str:
        return f"OpenAIDirectProvider(key_source={self._key_source!r})"

    async def complete(
        self,
        messages: list[dict],
        model: str,
        **kwargs,
    ) -> CompletionResponse:
        """
        Execute a chat completion against the OpenAI API.

        Args:
            messages: OpenAI-compatible messages list.
            model:    Model name (e.g. 'gpt-4o').
            **kwargs: Forwarded to the API (temperature, max_tokens, etc.).

        Returns:
            CompletionResponse with all fields populated.
        """
        start = time.time()
        response = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs,
        )
        latency_ms = int((time.time() - start) * 1000)

        content = response.choices[0].message.content or ""
        tokens_in = response.usage.prompt_tokens if response.usage else 0
        tokens_out = response.usage.completion_tokens if response.usage else 0

        logger.debug(
            "openai_direct_completion",
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
        )

        return CompletionResponse(
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model,
            provider="openai_direct",
            latency_ms=latency_ms,
        )


class OpenAIDirectEmbeddingProvider(EmbeddingProvider):
    """
    OpenAI Direct embedding adapter.

    Accepts an optional api_key at construction; if None, reads OPENAI_API_KEY
    from environment. The key is stored privately and never appears in repr
    or exception messages.
    """

    def __init__(self, api_key: str | None = None) -> None:
        from openai import AsyncOpenAI

        resolved_key = api_key or os.environ.get("OPENAI_API_KEY", "").strip()
        if not resolved_key:
            raise ValueError(
                "OpenAI API key is required for OpenAIDirectEmbeddingProvider. "
                "Pass api_key= or set OPENAI_API_KEY in .env."
            )
        self._client = AsyncOpenAI(api_key=resolved_key)
        self._key_source = "explicit" if api_key else "env"

    def __repr__(self) -> str:
        return f"OpenAIDirectEmbeddingProvider(key_source={self._key_source!r})"

    async def embed(
        self,
        texts: list[str],
        model: str,
    ) -> list[list[float]]:
        """
        Generate embedding vectors via OpenAI API.

        Args:
            texts: Non-empty list of strings to embed.
            model: Model name (e.g. 'text-embedding-3-small').

        Returns:
            List of float vectors, one per input text.
        """
        if not texts:
            return []

        response = await self._client.embeddings.create(
            model=model,
            input=texts,
        )

        vectors = [item.embedding for item in response.data]

        logger.debug(
            "openai_direct_embedding",
            model=model,
            batch_size=len(texts),
            vector_dim=len(vectors[0]) if vectors else 0,
        )

        return vectors
