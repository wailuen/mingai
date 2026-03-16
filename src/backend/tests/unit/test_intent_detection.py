"""
Unit tests for AI-057 — IntentDetectionService.

Coverage:
- Fast path: memory patterns bypass LLM (regex only)
- Fast path: greeting patterns bypass LLM
- Fast path: feedback patterns bypass LLM
- LLM path: valid JSON response parsed correctly
- LLM path: invalid/unknown intent falls back to rag_query
- LLM path: timeout falls back to rag_query
- Redis cache hit returns cached result without LLM call
- Redis cache miss triggers LLM and stores result
- Empty query returns rag_query fallback
- Confidence is clamped to [0.0, 1.0]
- Model fallback chain: INTENT_MODEL > ROUTER_MODEL > PRIMARY_MODEL
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.chat.intent_detection import (
    IntentDetectionService,
    IntentResult,
    _FALLBACK_INTENT,
    _INTENT_CACHE_TTL_SECONDS,
    _INTENT_DETECTION_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_redis_mock(cached_raw: str | None = None):
    """Build a minimal async Redis mock for intent cache tests."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=cached_raw)
    mock.setex = AsyncMock(return_value=True)
    return mock


def _make_llm_response(intent: str, confidence: float = 0.9):
    """Build a minimal OpenAI-compatible completion mock."""
    choice = MagicMock()
    choice.message.content = json.dumps({"intent": intent, "confidence": confidence})
    completion = MagicMock()
    completion.choices = [choice]
    return completion


# ---------------------------------------------------------------------------
# Fast-path tests (no LLM, no cache)
# ---------------------------------------------------------------------------


class TestIntentFastPath:
    """Memory, greeting and feedback patterns skip LLM entirely."""

    @pytest.mark.asyncio
    async def test_remember_that_returns_remember_no_llm(self):
        """'remember that my name is Alice' → remember intent via regex."""
        svc = IntentDetectionService(redis_client=_make_redis_mock())
        result = await svc.classify(
            query="remember that my name is Alice",
            conversation_history=[],
            tenant_id="tenant-1",
        )
        assert result.intent == "remember"
        assert result.confidence == 1.0
        assert result.metadata.get("fast_path") is True

    @pytest.mark.asyncio
    async def test_remember_colon_returns_remember_no_llm(self):
        """'remember: buy milk' → remember intent."""
        svc = IntentDetectionService(redis_client=_make_redis_mock())
        result = await svc.classify(
            query="remember: buy milk",
            conversation_history=[],
            tenant_id="tenant-1",
        )
        assert result.intent == "remember"
        assert result.metadata.get("fast_path") is True

    @pytest.mark.asyncio
    async def test_note_that_returns_remember_no_llm(self):
        """'note that the deadline is Friday' → remember intent."""
        svc = IntentDetectionService(redis_client=_make_redis_mock())
        result = await svc.classify(
            query="Note that the deadline is Friday",
            conversation_history=[],
            tenant_id="tenant-1",
        )
        assert result.intent == "remember"

    @pytest.mark.asyncio
    async def test_save_this_returns_remember_no_llm(self):
        """'save this: project code is X42' → remember intent."""
        svc = IntentDetectionService(redis_client=_make_redis_mock())
        result = await svc.classify(
            query="Save this: project code is X42",
            conversation_history=[],
            tenant_id="tenant-1",
        )
        assert result.intent == "remember"

    @pytest.mark.asyncio
    async def test_hello_returns_greeting(self):
        """'hello there' → greeting intent via regex."""
        svc = IntentDetectionService(redis_client=_make_redis_mock())
        result = await svc.classify(
            query="hello there",
            conversation_history=[],
            tenant_id="tenant-1",
        )
        assert result.intent == "greeting"
        assert result.metadata.get("fast_path") is True

    @pytest.mark.asyncio
    async def test_good_morning_returns_greeting(self):
        """'Good morning!' → greeting intent."""
        svc = IntentDetectionService(redis_client=_make_redis_mock())
        result = await svc.classify(
            query="Good morning!",
            conversation_history=[],
            tenant_id="tenant-1",
        )
        assert result.intent == "greeting"

    @pytest.mark.asyncio
    async def test_thumbs_up_returns_feedback(self):
        """'thumbs up' → feedback intent via regex."""
        svc = IntentDetectionService(redis_client=_make_redis_mock())
        result = await svc.classify(
            query="thumbs up",
            conversation_history=[],
            tenant_id="tenant-1",
        )
        assert result.intent == "feedback"
        assert result.metadata.get("fast_path") is True

    @pytest.mark.asyncio
    async def test_that_was_helpful_returns_feedback(self):
        """'that was helpful' → feedback intent."""
        svc = IntentDetectionService(redis_client=_make_redis_mock())
        result = await svc.classify(
            query="That was helpful",
            conversation_history=[],
            tenant_id="tenant-1",
        )
        assert result.intent == "feedback"


# ---------------------------------------------------------------------------
# LLM path tests
# ---------------------------------------------------------------------------


class TestIntentLLMPath:
    """LLM is called when no fast path matches and cache misses."""

    @pytest.mark.asyncio
    async def test_valid_llm_response_rag_query(self):
        """LLM returns rag_query → result has correct intent and confidence."""
        llm_mock = AsyncMock()
        llm_mock.chat.completions.create = AsyncMock(
            return_value=_make_llm_response("rag_query", 0.95)
        )
        redis_mock = _make_redis_mock(cached_raw=None)

        with patch.dict("os.environ", {"INTENT_MODEL": "test-model"}):
            svc = IntentDetectionService(redis_client=redis_mock, llm_client=llm_mock)
            result = await svc.classify(
                query="What is our refund policy?",
                conversation_history=[],
                tenant_id="tenant-1",
            )

        assert result.intent == "rag_query"
        assert result.confidence == 0.95
        llm_mock.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_valid_llm_response_clarification(self):
        """LLM returns clarification → intent is clarification."""
        llm_mock = AsyncMock()
        llm_mock.chat.completions.create = AsyncMock(
            return_value=_make_llm_response("clarification", 0.88)
        )
        redis_mock = _make_redis_mock(cached_raw=None)

        with patch.dict("os.environ", {"INTENT_MODEL": "test-model"}):
            svc = IntentDetectionService(redis_client=redis_mock, llm_client=llm_mock)
            result = await svc.classify(
                query="Can you clarify what you said about paragraph 3?",
                conversation_history=[],
                tenant_id="tenant-1",
            )

        assert result.intent == "clarification"
        assert result.confidence == 0.88

    @pytest.mark.asyncio
    async def test_invalid_intent_label_falls_back(self):
        """LLM returns unknown intent → falls back to rag_query."""
        choice = MagicMock()
        choice.message.content = json.dumps(
            {"intent": "NOT_A_VALID_INTENT", "confidence": 0.8}
        )
        completion = MagicMock()
        completion.choices = [choice]

        llm_mock = AsyncMock()
        llm_mock.chat.completions.create = AsyncMock(return_value=completion)
        redis_mock = _make_redis_mock(cached_raw=None)

        with patch.dict("os.environ", {"INTENT_MODEL": "test-model"}):
            svc = IntentDetectionService(redis_client=redis_mock, llm_client=llm_mock)
            result = await svc.classify(
                query="Something weird",
                conversation_history=[],
                tenant_id="tenant-1",
            )

        assert result.intent == _FALLBACK_INTENT

    @pytest.mark.asyncio
    async def test_malformed_json_falls_back(self):
        """LLM returns malformed JSON → falls back to rag_query."""
        choice = MagicMock()
        choice.message.content = "not json at all"
        completion = MagicMock()
        completion.choices = [choice]

        llm_mock = AsyncMock()
        llm_mock.chat.completions.create = AsyncMock(return_value=completion)
        redis_mock = _make_redis_mock(cached_raw=None)

        with patch.dict("os.environ", {"INTENT_MODEL": "test-model"}):
            svc = IntentDetectionService(redis_client=redis_mock, llm_client=llm_mock)
            result = await svc.classify(
                query="Something that returns bad JSON",
                conversation_history=[],
                tenant_id="tenant-1",
            )

        assert result.intent == _FALLBACK_INTENT
        assert result.metadata.get("fallback") is True

    @pytest.mark.asyncio
    async def test_timeout_falls_back_to_rag_query(self):
        """LLM call exceeds 200ms timeout → falls back to rag_query."""

        async def slow_llm(*args, **kwargs):
            await asyncio.sleep(10)  # much longer than 200ms timeout
            return _make_llm_response("greeting")

        llm_mock = AsyncMock()
        llm_mock.chat.completions.create = slow_llm
        redis_mock = _make_redis_mock(cached_raw=None)

        with patch.dict("os.environ", {"INTENT_MODEL": "test-model"}):
            svc = IntentDetectionService(redis_client=redis_mock, llm_client=llm_mock)
            # Patch timeout to a very small value to keep tests fast
            with patch(
                "app.modules.chat.intent_detection._INTENT_DETECTION_TIMEOUT",
                0.01,
            ):
                result = await svc.classify(
                    query="What is the company mission?",
                    conversation_history=[],
                    tenant_id="tenant-1",
                )

        assert result.intent == _FALLBACK_INTENT
        assert result.metadata.get("reason") == "timeout"

    @pytest.mark.asyncio
    async def test_llm_exception_falls_back_to_rag_query(self):
        """LLM raises an exception → falls back to rag_query."""
        llm_mock = AsyncMock()
        llm_mock.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("LLM unavailable")
        )
        redis_mock = _make_redis_mock(cached_raw=None)

        with patch.dict("os.environ", {"INTENT_MODEL": "test-model"}):
            svc = IntentDetectionService(redis_client=redis_mock, llm_client=llm_mock)
            result = await svc.classify(
                query="What is our overtime policy?",
                conversation_history=[],
                tenant_id="tenant-1",
            )

        assert result.intent == _FALLBACK_INTENT
        assert result.metadata.get("fallback") is True


# ---------------------------------------------------------------------------
# Redis cache tests
# ---------------------------------------------------------------------------


class TestIntentCache:
    """Cache hit returns stored result; miss triggers LLM and stores result."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_result_no_llm(self):
        """A warm cache entry is returned without calling the LLM."""
        cached_payload = json.dumps(
            {"intent": "clarification", "confidence": 0.92, "metadata": {}}
        )
        redis_mock = _make_redis_mock(cached_raw=cached_payload)

        llm_mock = AsyncMock()
        llm_mock.chat.completions.create = AsyncMock()  # should NOT be called

        with patch.dict("os.environ", {"INTENT_MODEL": "test-model"}):
            svc = IntentDetectionService(redis_client=redis_mock, llm_client=llm_mock)
            result = await svc.classify(
                query="Can you explain that again?",
                conversation_history=[],
                tenant_id="tenant-1",
            )

        assert result.intent == "clarification"
        assert result.confidence == 0.92
        llm_mock.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_calls_llm_and_stores(self):
        """Cache miss triggers LLM call and result is stored via setex."""
        redis_mock = _make_redis_mock(cached_raw=None)

        llm_mock = AsyncMock()
        llm_mock.chat.completions.create = AsyncMock(
            return_value=_make_llm_response("rag_query", 0.9)
        )

        with patch.dict("os.environ", {"INTENT_MODEL": "test-model"}):
            svc = IntentDetectionService(redis_client=redis_mock, llm_client=llm_mock)
            result = await svc.classify(
                query="What is our holiday schedule?",
                conversation_history=[],
                tenant_id="tenant-1",
            )

        assert result.intent == "rag_query"
        # Verify setex was called to persist the result
        redis_mock.setex.assert_called_once()
        call_args = redis_mock.setex.call_args
        # First positional arg is the key, second is TTL
        assert call_args[0][1] == _INTENT_CACHE_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_cache_key_includes_tenant_namespace(self):
        """CACHE-001: Cache key follows mingai:{tenant_id}:intent:{sha256} pattern."""
        redis_mock = _make_redis_mock(cached_raw=None)
        llm_mock = AsyncMock()
        llm_mock.chat.completions.create = AsyncMock(
            return_value=_make_llm_response("rag_query", 0.8)
        )

        with patch.dict("os.environ", {"INTENT_MODEL": "test-model"}):
            svc = IntentDetectionService(redis_client=redis_mock, llm_client=llm_mock)
            await svc.classify(
                query="What are the leave policies?",
                conversation_history=[],
                tenant_id="tenant-abc",
            )

        # CACHE-001: key type changed from intent_cache to intent
        get_call_key = redis_mock.get.call_args[0][0]
        assert get_call_key.startswith("mingai:tenant-abc:intent:")

    @pytest.mark.asyncio
    async def test_redis_error_during_get_falls_through_to_llm(self):
        """Redis GET failure is swallowed; LLM is called as fallback."""
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        redis_mock.setex = AsyncMock()

        llm_mock = AsyncMock()
        llm_mock.chat.completions.create = AsyncMock(
            return_value=_make_llm_response("rag_query", 0.85)
        )

        with patch.dict("os.environ", {"INTENT_MODEL": "test-model"}):
            svc = IntentDetectionService(redis_client=redis_mock, llm_client=llm_mock)
            result = await svc.classify(
                query="Describe the onboarding process",
                conversation_history=[],
                tenant_id="tenant-1",
            )

        assert result.intent == "rag_query"
        llm_mock.chat.completions.create.assert_called_once()


# ---------------------------------------------------------------------------
# Edge-case tests
# ---------------------------------------------------------------------------


class TestIntentEdgeCases:
    """Empty queries, confidence clamping, model env fallback."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_rag_query(self):
        """Empty/whitespace-only query → rag_query without touching cache or LLM."""
        svc = IntentDetectionService(redis_client=_make_redis_mock())
        result = await svc.classify(
            query="   ",
            conversation_history=[],
            tenant_id="tenant-1",
        )
        assert result.intent == _FALLBACK_INTENT
        assert result.confidence == 1.0

    def test_confidence_clamped_above_one(self):
        """Confidence > 1.0 from LLM is clamped to 1.0."""
        result = IntentDetectionService._parse_llm_response(
            json.dumps({"intent": "rag_query", "confidence": 1.5})
        )
        assert result.confidence == 1.0

    def test_confidence_clamped_below_zero(self):
        """Confidence < 0.0 from LLM is clamped to 0.0."""
        result = IntentDetectionService._parse_llm_response(
            json.dumps({"intent": "greeting", "confidence": -0.3})
        )
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_model_fallback_uses_router_model_when_intent_model_absent(self):
        """Falls back to ROUTER_MODEL when INTENT_MODEL not set."""
        llm_mock = AsyncMock()
        captured_calls = []

        async def capture_create(**kwargs):
            captured_calls.append(kwargs.get("model"))
            return _make_llm_response("rag_query", 0.9)

        llm_mock.chat.completions.create = capture_create
        redis_mock = _make_redis_mock(cached_raw=None)

        env = {"ROUTER_MODEL": "router-deployment", "PRIMARY_MODEL": "primary-model"}
        # INTENT_MODEL intentionally absent
        with patch.dict("os.environ", env, clear=False):
            # Remove INTENT_MODEL if it happens to be set
            import os

            os.environ.pop("INTENT_MODEL", None)
            svc = IntentDetectionService(redis_client=redis_mock, llm_client=llm_mock)
            await svc.classify(
                query="What is the HR policy?",
                conversation_history=[],
                tenant_id="tenant-1",
            )

        assert len(captured_calls) == 1
        assert captured_calls[0] == "router-deployment"

    @pytest.mark.asyncio
    async def test_no_model_configured_raises_falls_back(self):
        """No model env vars at all → LLM error → falls back to rag_query."""
        llm_mock = AsyncMock()
        redis_mock = _make_redis_mock(cached_raw=None)

        with patch.dict("os.environ", {}, clear=True):
            # Ensure model vars are absent
            import os

            for var in ("INTENT_MODEL", "ROUTER_MODEL", "PRIMARY_MODEL"):
                os.environ.pop(var, None)

            svc = IntentDetectionService(redis_client=redis_mock, llm_client=llm_mock)
            result = await svc.classify(
                query="What is the expense policy?",
                conversation_history=[],
                tenant_id="tenant-1",
            )

        # Without any model configured the _call_llm raises ValueError,
        # which is caught and falls back to rag_query
        assert result.intent == _FALLBACK_INTENT
