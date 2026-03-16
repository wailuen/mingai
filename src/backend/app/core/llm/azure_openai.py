"""
Azure OpenAI LLM and Embedding Provider adapters (P2LLM-002).

Reads credentials from environment variables:
    AZURE_PLATFORM_OPENAI_API_KEY
    AZURE_PLATFORM_OPENAI_ENDPOINT
    AZURE_PLATFORM_OPENAI_API_VERSION  (default: "2024-02-01")

API keys are NEVER exposed in __repr__, logs, or exception messages.
"""
import os
import time

import structlog

from app.core.llm.base import CompletionResponse, EmbeddingProvider, LLMProvider

logger = structlog.get_logger()


def _get_azure_client():
    """
    Build and return an AsyncAzureOpenAI client from environment variables.

    Raises ValueError if required credentials are missing.
    API key is never logged or repr'd.
    """
    from openai import AsyncAzureOpenAI

    api_key = os.environ.get("AZURE_PLATFORM_OPENAI_API_KEY", "").strip()
    endpoint = os.environ.get("AZURE_PLATFORM_OPENAI_ENDPOINT", "").strip()
    api_version = os.environ.get(
        "AZURE_PLATFORM_OPENAI_API_VERSION", "2024-02-01"
    ).strip()

    if not api_key:
        raise ValueError(
            "AZURE_PLATFORM_OPENAI_API_KEY is required for AzureOpenAI provider. "
            "Set it in .env."
        )
    if not endpoint:
        raise ValueError(
            "AZURE_PLATFORM_OPENAI_ENDPOINT is required for AzureOpenAI provider. "
            "Set it in .env."
        )

    return AsyncAzureOpenAI(
        api_key=api_key,
        azure_endpoint=endpoint,
        api_version=api_version,
    )


class AzureOpenAIProvider(LLMProvider):
    """
    Azure OpenAI chat completion adapter.

    Credentials are read from environment variables at construction time.
    The API key is stored privately and never appears in repr or exceptions.
    """

    def __init__(self) -> None:
        self._client = _get_azure_client()

    def __repr__(self) -> str:
        endpoint = os.environ.get("AZURE_PLATFORM_OPENAI_ENDPOINT", "<not set>")
        return f"AzureOpenAIProvider(endpoint={endpoint!r})"

    async def complete(
        self,
        messages: list[dict],
        model: str,
        **kwargs,
    ) -> CompletionResponse:
        """
        Execute a chat completion against Azure OpenAI.

        Args:
            messages: OpenAI-compatible messages list.
            model:    Azure deployment name.
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
            "azure_openai_completion",
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
            provider="azure_openai",
            latency_ms=latency_ms,
        )


class AzureOpenAIEmbeddingProvider(EmbeddingProvider):
    """
    Azure OpenAI embedding adapter.

    Credentials are read from environment variables at construction time.
    """

    def __init__(self) -> None:
        self._client = _get_azure_client()

    def __repr__(self) -> str:
        endpoint = os.environ.get("AZURE_PLATFORM_OPENAI_ENDPOINT", "<not set>")
        return f"AzureOpenAIEmbeddingProvider(endpoint={endpoint!r})"

    async def embed(
        self,
        texts: list[str],
        model: str,
    ) -> list[list[float]]:
        """
        Generate embedding vectors via Azure OpenAI.

        Args:
            texts: Non-empty list of strings to embed.
            model: Azure deployment name (e.g. 'text-embedding-3-small').

        Returns:
            List of float vectors, one per input text.
        """
        if not texts:
            return []

        response = await self._client.embeddings.create(
            model=model,
            input=texts,
        )

        # API returns embeddings in the same order as inputs
        vectors = [item.embedding for item in response.data]

        logger.debug(
            "azure_openai_embedding",
            model=model,
            batch_size=len(texts),
            vector_dim=len(vectors[0]) if vectors else 0,
        )

        return vectors
