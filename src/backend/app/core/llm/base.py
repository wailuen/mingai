"""
LLM Provider Abstract Interface (P2LLM-001).

Defines the contract for all LLM provider adapters in mingai.
Providers implement LLMProvider (completions) or EmbeddingProvider (embeddings).

All concrete providers must:
- Read credentials from environment variables — NEVER hardcode
- Populate all fields of CompletionResponse
- Never expose API keys in __repr__ or exception messages
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CompletionResponse:
    """
    Unified completion response shape across all LLM providers.

    Fields:
        content:     The model's text response.
        tokens_in:   Number of prompt tokens consumed.
        tokens_out:  Number of completion tokens generated.
        model:       The model/deployment name used.
        provider:    Provider identifier string (e.g. 'azure_openai', 'openai_direct').
        latency_ms:  Wall-clock latency in milliseconds for the API call.
    """

    content: str
    tokens_in: int
    tokens_out: int
    model: str
    provider: str
    latency_ms: int


class LLMProvider(ABC):
    """
    Abstract base class for chat completion providers.

    Implementations: AzureOpenAIProvider, OpenAIDirectProvider.
    """

    @abstractmethod
    async def complete(
        self,
        messages: list[dict],
        model: str,
        **kwargs,
    ) -> CompletionResponse:
        """
        Execute a chat completion.

        Args:
            messages: OpenAI-compatible message list (role/content dicts).
            model:    Model or deployment name to use.
            **kwargs: Provider-specific overrides (temperature, max_tokens, etc.).

        Returns:
            CompletionResponse with all fields populated.
        """
        ...


class EmbeddingProvider(ABC):
    """
    Abstract base class for embedding providers.

    Implementations: AzureOpenAIEmbeddingProvider, OpenAIDirectEmbeddingProvider.
    """

    @abstractmethod
    async def embed(
        self,
        texts: list[str],
        model: str,
    ) -> list[list[float]]:
        """
        Generate embedding vectors for a batch of texts.

        Args:
            texts: Non-empty list of strings to embed.
            model: Model or deployment name to use.

        Returns:
            List of embedding vectors, one per input text.
        """
        ...
