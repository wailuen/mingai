"""
LLM abstraction layer — provider-agnostic interface for chat completions and embeddings.

Exports:
    CompletionResponse  — unified response dataclass
    LLMProvider         — abstract base for completion adapters
    EmbeddingProvider   — abstract base for embedding adapters
"""
from app.core.llm.base import CompletionResponse, EmbeddingProvider, LLMProvider

__all__ = ["CompletionResponse", "LLMProvider", "EmbeddingProvider"]
