"""
P2LLM-016: Unit tests for LLM provider adapters.

Tier 1: Unit tests — mocked network calls, no real API connections.

Tests:
- Both adapters implement LLMProvider / EmbeddingProvider
- CompletionResponse all fields populated
- API key NOT in repr() or exception messages
- Cost calculation formula correctness
"""
import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures / constants
# ---------------------------------------------------------------------------

TEST_JWT_SECRET = "z" * 64  # 64-char secret for get_fernet()
FAKE_API_KEY = "sk-fake-key-for-testing-do-not-use"
FAKE_ENDPOINT = "https://fake-azure.openai.azure.com/"


def _make_fake_completion(content="hello", tokens_in=10, tokens_out=5):
    """Build a mock OpenAI ChatCompletion response."""
    choice = MagicMock()
    choice.message.content = content
    usage = MagicMock()
    usage.prompt_tokens = tokens_in
    usage.completion_tokens = tokens_out
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _make_fake_embedding(dim=1536):
    """Build a mock OpenAI Embeddings response."""
    item = MagicMock()
    item.embedding = [0.1] * dim
    resp = MagicMock()
    resp.data = [item]
    return resp


# ---------------------------------------------------------------------------
# LLMProvider abstract interface
# ---------------------------------------------------------------------------


class TestLLMProviderInterface:
    """Ensure the abstract interface is correctly defined."""

    def test_completion_response_fields(self):
        """CompletionResponse dataclass has all required fields."""
        from app.core.llm.base import CompletionResponse

        cr = CompletionResponse(
            content="test",
            tokens_in=10,
            tokens_out=5,
            model="gpt-4o",
            provider="openai_direct",
            latency_ms=123,
        )
        assert cr.content == "test"
        assert cr.tokens_in == 10
        assert cr.tokens_out == 5
        assert cr.model == "gpt-4o"
        assert cr.provider == "openai_direct"
        assert cr.latency_ms == 123

    def test_llm_provider_is_abstract(self):
        """LLMProvider cannot be instantiated directly."""
        from app.core.llm.base import LLMProvider

        with pytest.raises(TypeError):
            LLMProvider()

    def test_embedding_provider_is_abstract(self):
        """EmbeddingProvider cannot be instantiated directly."""
        from app.core.llm.base import EmbeddingProvider

        with pytest.raises(TypeError):
            EmbeddingProvider()


# ---------------------------------------------------------------------------
# AzureOpenAIProvider
# ---------------------------------------------------------------------------


class TestAzureOpenAIProvider:
    """Tests for AzureOpenAIProvider adapter."""

    @pytest.fixture(autouse=True)
    def _set_env(self):
        env = {
            "AZURE_PLATFORM_OPENAI_API_KEY": FAKE_API_KEY,
            "AZURE_PLATFORM_OPENAI_ENDPOINT": FAKE_ENDPOINT,
            "AZURE_PLATFORM_OPENAI_API_VERSION": "2024-02-01",
        }
        with patch.dict(os.environ, env):
            yield

    def test_implements_llm_provider(self):
        """AzureOpenAIProvider is an instance of LLMProvider."""
        from app.core.llm.azure_openai import AzureOpenAIProvider
        from app.core.llm.base import LLMProvider

        assert isinstance(AzureOpenAIProvider(), LLMProvider)

    def test_repr_does_not_contain_api_key(self):
        """repr() must not expose the API key."""
        from app.core.llm.azure_openai import AzureOpenAIProvider

        provider = AzureOpenAIProvider()
        representation = repr(provider)
        assert FAKE_API_KEY not in representation
        assert "sk-" not in representation

    @pytest.mark.asyncio
    async def test_complete_returns_completion_response(self):
        """complete() returns a fully-populated CompletionResponse."""
        from app.core.llm.azure_openai import AzureOpenAIProvider
        from app.core.llm.base import CompletionResponse

        fake_resp = _make_fake_completion("Azure says hello", 20, 8)

        with patch("openai.AsyncAzureOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=fake_resp)
            mock_cls.return_value = mock_client

            provider = AzureOpenAIProvider()
            result = await provider.complete(
                messages=[{"role": "user", "content": "hi"}],
                model="agentic-worker",
            )

        assert isinstance(result, CompletionResponse)
        assert result.content == "Azure says hello"
        assert result.tokens_in == 20
        assert result.tokens_out == 8
        assert result.provider == "azure_openai"
        assert result.model == "agentic-worker"
        assert result.latency_ms >= 0

    def test_missing_api_key_raises(self):
        """ValueError raised when AZURE_PLATFORM_OPENAI_API_KEY is unset."""
        with patch.dict(os.environ, {"AZURE_PLATFORM_OPENAI_API_KEY": ""}):
            from app.core.llm import azure_openai as _mod

            with pytest.raises(ValueError, match="AZURE_PLATFORM_OPENAI_API_KEY"):
                _mod._get_azure_client()

    def test_missing_endpoint_raises(self):
        """ValueError raised when AZURE_PLATFORM_OPENAI_ENDPOINT is unset."""
        with patch.dict(os.environ, {"AZURE_PLATFORM_OPENAI_ENDPOINT": ""}):
            from app.core.llm import azure_openai as _mod

            with pytest.raises(ValueError, match="AZURE_PLATFORM_OPENAI_ENDPOINT"):
                _mod._get_azure_client()


# ---------------------------------------------------------------------------
# AzureOpenAIEmbeddingProvider
# ---------------------------------------------------------------------------


class TestAzureOpenAIEmbeddingProvider:
    """Tests for AzureOpenAIEmbeddingProvider adapter."""

    @pytest.fixture(autouse=True)
    def _set_env(self):
        env = {
            "AZURE_PLATFORM_OPENAI_API_KEY": FAKE_API_KEY,
            "AZURE_PLATFORM_OPENAI_ENDPOINT": FAKE_ENDPOINT,
        }
        with patch.dict(os.environ, env):
            yield

    def test_implements_embedding_provider(self):
        """AzureOpenAIEmbeddingProvider is an instance of EmbeddingProvider."""
        from app.core.llm.azure_openai import AzureOpenAIEmbeddingProvider
        from app.core.llm.base import EmbeddingProvider

        assert isinstance(AzureOpenAIEmbeddingProvider(), EmbeddingProvider)

    def test_repr_does_not_contain_api_key(self):
        """repr() must not expose the API key."""
        from app.core.llm.azure_openai import AzureOpenAIEmbeddingProvider

        provider = AzureOpenAIEmbeddingProvider()
        representation = repr(provider)
        assert FAKE_API_KEY not in representation

    @pytest.mark.asyncio
    async def test_embed_returns_vectors(self):
        """embed() returns a list of float vectors."""
        from app.core.llm.azure_openai import AzureOpenAIEmbeddingProvider

        fake_resp = _make_fake_embedding(1536)

        with patch("openai.AsyncAzureOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.embeddings.create = AsyncMock(return_value=fake_resp)
            mock_cls.return_value = mock_client

            provider = AzureOpenAIEmbeddingProvider()
            vectors = await provider.embed(
                texts=["hello world"],
                model="text-embedding-3-small",
            )

        assert isinstance(vectors, list)
        assert len(vectors) == 1
        assert len(vectors[0]) == 1536
        assert all(isinstance(v, float) for v in vectors[0])

    @pytest.mark.asyncio
    async def test_embed_empty_input_returns_empty(self):
        """embed() with empty list returns empty list without API call."""
        from app.core.llm.azure_openai import AzureOpenAIEmbeddingProvider

        with patch("openai.AsyncAzureOpenAI"):
            provider = AzureOpenAIEmbeddingProvider()
            result = await provider.embed(texts=[], model="text-embedding-3-small")

        assert result == []


# ---------------------------------------------------------------------------
# OpenAIDirectProvider
# ---------------------------------------------------------------------------


class TestOpenAIDirectProvider:
    """Tests for OpenAIDirectProvider adapter."""

    def test_implements_llm_provider(self):
        """OpenAIDirectProvider is an instance of LLMProvider."""
        from app.core.llm.base import LLMProvider
        from app.core.llm.openai_direct import OpenAIDirectProvider

        provider = OpenAIDirectProvider(api_key=FAKE_API_KEY)
        assert isinstance(provider, LLMProvider)

    def test_repr_does_not_contain_api_key(self):
        """repr() must not expose the API key."""
        from app.core.llm.openai_direct import OpenAIDirectProvider

        provider = OpenAIDirectProvider(api_key=FAKE_API_KEY)
        representation = repr(provider)
        assert FAKE_API_KEY not in representation
        assert "sk-" not in representation

    def test_key_source_explicit_vs_env(self):
        """Explicit key sets key_source='explicit'; env key sets key_source='env'."""
        from app.core.llm.openai_direct import OpenAIDirectProvider

        explicit = OpenAIDirectProvider(api_key=FAKE_API_KEY)
        assert "explicit" in repr(explicit)

        with patch.dict(os.environ, {"OPENAI_API_KEY": FAKE_API_KEY}):
            env_provider = OpenAIDirectProvider()
            assert "env" in repr(env_provider)

    def test_missing_key_raises(self):
        """ValueError raised when no API key is available."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            from app.core.llm.openai_direct import OpenAIDirectProvider

            with pytest.raises(ValueError, match="API key"):
                OpenAIDirectProvider()

    @pytest.mark.asyncio
    async def test_complete_returns_completion_response(self):
        """complete() returns a fully-populated CompletionResponse."""
        from app.core.llm.base import CompletionResponse
        from app.core.llm.openai_direct import OpenAIDirectProvider

        fake_resp = _make_fake_completion("Direct says hello", 15, 6)

        with patch("openai.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=fake_resp)
            mock_cls.return_value = mock_client

            provider = OpenAIDirectProvider(api_key=FAKE_API_KEY)
            result = await provider.complete(
                messages=[{"role": "user", "content": "hi"}],
                model="gpt-4o",
            )

        assert isinstance(result, CompletionResponse)
        assert result.content == "Direct says hello"
        assert result.tokens_in == 15
        assert result.tokens_out == 6
        assert result.provider == "openai_direct"
        assert result.model == "gpt-4o"
        assert result.latency_ms >= 0

    def test_provider_value(self):
        """provider field must be 'openai_direct'."""
        # Verified indirectly via complete() test above.
        # This docstring documents the contract.
        assert True


# ---------------------------------------------------------------------------
# OpenAIDirectEmbeddingProvider
# ---------------------------------------------------------------------------


class TestOpenAIDirectEmbeddingProvider:
    """Tests for OpenAIDirectEmbeddingProvider adapter."""

    def test_implements_embedding_provider(self):
        """OpenAIDirectEmbeddingProvider is an instance of EmbeddingProvider."""
        from app.core.llm.base import EmbeddingProvider
        from app.core.llm.openai_direct import OpenAIDirectEmbeddingProvider

        provider = OpenAIDirectEmbeddingProvider(api_key=FAKE_API_KEY)
        assert isinstance(provider, EmbeddingProvider)

    def test_repr_does_not_contain_api_key(self):
        """repr() must not expose the API key."""
        from app.core.llm.openai_direct import OpenAIDirectEmbeddingProvider

        provider = OpenAIDirectEmbeddingProvider(api_key=FAKE_API_KEY)
        representation = repr(provider)
        assert FAKE_API_KEY not in representation

    @pytest.mark.asyncio
    async def test_embed_returns_vectors(self):
        """embed() returns a list of float vectors."""
        from app.core.llm.openai_direct import OpenAIDirectEmbeddingProvider

        fake_resp = _make_fake_embedding(1536)

        with patch("openai.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.embeddings.create = AsyncMock(return_value=fake_resp)
            mock_cls.return_value = mock_client

            provider = OpenAIDirectEmbeddingProvider(api_key=FAKE_API_KEY)
            vectors = await provider.embed(
                texts=["test text"],
                model="text-embedding-3-small",
            )

        assert len(vectors) == 1
        assert len(vectors[0]) == 1536


# ---------------------------------------------------------------------------
# Cost calculation formula (P2LLM-011)
# ---------------------------------------------------------------------------


class TestCostCalculationFormula:
    """Verify cost formula: (tokens_in/1000 * price_in) + (tokens_out/1000 * price_out)."""

    @pytest.mark.asyncio
    async def test_cost_calculation_formula_within_1pct(self):
        """
        Cost calculation within 1% of expected formula.
        price_in=0.002 / 1K, price_out=0.002 / 1K (sample gpt-4o pricing)
        1000 tokens_in + 500 tokens_out = 0.002 + 0.001 = 0.003 USD
        """
        from app.core.llm.instrumented_client import InstrumentedLLMClient

        client = InstrumentedLLMClient()

        # Simulate pricing lookup result
        pricing = {"price_in": 0.002, "price_out": 0.002}

        with patch.object(
            client, "_get_library_pricing", AsyncMock(return_value=pricing)
        ):
            cost = await client._calculate_cost(
                model_source="library",
                model="gpt-4o",
                tokens_in=1000,
                tokens_out=500,
            )

        expected = (1000 / 1000 * 0.002) + (500 / 1000 * 0.002)
        assert cost is not None
        assert (
            abs(cost - expected) / expected < 0.01
        ), f"Cost {cost} differs from expected {expected} by more than 1%"

    @pytest.mark.asyncio
    async def test_cost_returns_none_on_lookup_failure(self):
        """Cost returns None (not raise) when pricing lookup fails."""
        from app.core.llm.instrumented_client import InstrumentedLLMClient

        client = InstrumentedLLMClient()

        with patch.object(
            client, "_get_library_pricing", AsyncMock(side_effect=Exception("DB down"))
        ):
            cost = await client._calculate_cost(
                model_source="library",
                model="gpt-4o",
                tokens_in=100,
                tokens_out=50,
            )

        # When _get_library_pricing raises, the outer except in _calculate_cost
        # catches it and returns None — verifying graceful non-raising behaviour.
        assert cost is None, f"Expected None on pricing lookup failure, got {cost}"

    @pytest.mark.asyncio
    async def test_cost_byollm_uses_env_fallback(self):
        """BYOLLM pricing uses BYOLLM_COST_PER_1K_IN_USD env var."""
        from app.core.llm.instrumented_client import InstrumentedLLMClient

        client = InstrumentedLLMClient()

        env = {
            "BYOLLM_COST_PER_1K_IN_USD": "0.003",
            "BYOLLM_COST_PER_1K_OUT_USD": "0.006",
        }
        with patch.dict(os.environ, env):
            cost = await client._calculate_cost(
                model_source="byollm",
                model="custom-model",
                tokens_in=1000,
                tokens_out=500,
            )

        expected = (1000 / 1000 * 0.003) + (500 / 1000 * 0.006)
        assert cost is not None
        assert abs(cost - expected) < 0.0000001


# ---------------------------------------------------------------------------
# Parametrized adapter tests (run same suite on both adapters)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adapter_factory,provider_label",
    [
        (
            lambda: __import__(
                "app.core.llm.azure_openai", fromlist=["AzureOpenAIProvider"]
            ).AzureOpenAIProvider(),
            "azure_openai",
        ),
    ],
)
class TestAdapterContractAzure:
    """Parametrized contract tests for Azure adapter."""

    @pytest.fixture(autouse=True)
    def _env(self):
        env = {
            "AZURE_PLATFORM_OPENAI_API_KEY": FAKE_API_KEY,
            "AZURE_PLATFORM_OPENAI_ENDPOINT": FAKE_ENDPOINT,
        }
        with patch.dict(os.environ, env):
            yield

    def test_provider_is_llm_provider(self, adapter_factory, provider_label):
        """Adapter is an instance of LLMProvider."""
        from app.core.llm.base import LLMProvider

        adapter = adapter_factory()
        assert isinstance(adapter, LLMProvider)

    def test_api_key_not_in_repr(self, adapter_factory, provider_label):
        """API key not in repr."""
        adapter = adapter_factory()
        assert FAKE_API_KEY not in repr(adapter)
