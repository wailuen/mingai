"""
AI-057: IntentDetectionService — classifies user queries by intent.

Uses the tenant's configured INTENT_MODEL (from env) to classify queries.
Supports fast path for memory queries to avoid LLM call.

Intents:
  rag_query     — standard question requiring knowledge retrieval
  greeting      — hello, hi, good morning, etc.
  clarification — follow-up on previous response
  remember      — "remember that...", "save this...", "note that..."
  feedback      — thumbs up/down, "that was helpful"

Redis cache key:  mingai:{tenant_id}:intent:{sha256(normalize_query(query))}
Cache TTL:        86400 seconds (24 hours)
LLM timeout:      200ms — falls back to rag_query on timeout
"""
import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Valid intent labels — allowlist for output validation
_VALID_INTENTS = frozenset(
    {"rag_query", "greeting", "clarification", "remember", "feedback"}
)

# Default fallback intent used when LLM call fails or times out
_FALLBACK_INTENT = "rag_query"

# Redis TTL for cached intent results (seconds) — CACHE-001: 24h
_INTENT_CACHE_TTL_SECONDS = 86400

# LLM call timeout in seconds (200ms)
_INTENT_DETECTION_TIMEOUT = 0.2

# Memory command patterns — exact copy of orchestrator's patterns for fast path
# Each pattern uses ^ to match only at the start of the query.
_MEMORY_COMMAND_PATTERNS = [
    re.compile(r"^remember\s+that\s+", re.IGNORECASE),
    re.compile(r"^remember\s*:\s*", re.IGNORECASE),
    re.compile(r"^please\s+remember\s+", re.IGNORECASE),
    re.compile(r"^note\s+that\s+", re.IGNORECASE),
    re.compile(r"^save\s+this\s*:\s*", re.IGNORECASE),
]

# Greeting patterns — cheap regex fast path (no LLM call)
_GREETING_PATTERNS = [
    re.compile(
        r"^\s*(hello|hi|hey|greetings?|good\s+(morning|afternoon|evening|day))\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*howdy\b", re.IGNORECASE),
    re.compile(r"^\s*sup\b", re.IGNORECASE),
]

# Feedback patterns — cheap regex fast path (no LLM call)
_FEEDBACK_PATTERNS = [
    re.compile(
        r"^\s*(thumbs\s+(up|down)|that\s+was\s+(helpful|great|good|terrible|wrong|bad|incorrect))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(great\s+(answer|response)|wrong\s+answer|bad\s+response)\b",
        re.IGNORECASE,
    ),
]

# System prompt for intent classification LLM call
_INTENT_SYSTEM_PROMPT = (
    "You are an intent classifier. Given a user query, classify its intent as exactly one of:\n"
    "- rag_query: a question or request requiring knowledge retrieval\n"
    "- greeting: a greeting or pleasantry\n"
    "- clarification: a follow-up requesting clarification of a previous AI response\n"
    "- remember: a request to save or remember information\n"
    "- feedback: feedback about a previous AI response (positive or negative)\n\n"
    "Respond with ONLY valid JSON in this format: "
    '{"intent": "<intent>", "confidence": <0.0-1.0>}\n'
    "Do not include any other text."
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class IntentResult:
    """Result of intent classification."""

    intent: str
    confidence: float
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# IntentDetectionService
# ---------------------------------------------------------------------------


class IntentDetectionService:
    """
    AI-057: Classifies user query intent before the RAG pipeline.

    Classification order:
    1. Fast path regex checks (memory, greeting, feedback) — no LLM call
    2. Redis cache lookup (5-minute TTL)
    3. LLM call with 200ms timeout
    4. Fallback to rag_query on timeout/error

    All LLM calls use INTENT_MODEL env var (falls back to ROUTER_MODEL then
    PRIMARY_MODEL). Model names MUST come from env — never hardcoded.
    """

    def __init__(self, *, redis_client=None, llm_client=None, instrumented_client=None):
        """
        Args:
            redis_client:        Async Redis client. If None, uses get_redis() at call time.
            llm_client:          Injected async OpenAI-compatible client (for testing).
                                 If None, builds from env at call time.
            instrumented_client: Optional InstrumentedLLMClient (Phase 2).
                                 When provided, LLM calls route through it for usage
                                 tracking. Falls back to direct API when None.
        """
        self._redis = redis_client
        self._llm_client = llm_client
        self._instrumented_client = instrumented_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def classify(
        self,
        query: str,
        conversation_history: list,
        tenant_id: str,
    ) -> IntentResult:
        """
        Classify the intent of a user query.

        Args:
            query:                The user's query text.
            conversation_history: Prior messages in the conversation (list of dicts).
            tenant_id:            Tenant ID for cache namespace isolation.

        Returns:
            IntentResult with intent, confidence, and optional metadata.
        """
        if not query or not query.strip():
            return IntentResult(intent=_FALLBACK_INTENT, confidence=1.0)

        # Step 1: fast-path regex checks (no LLM, no cache)
        fast_result = self._fast_path_classify(query)
        if fast_result is not None:
            logger.info(
                "intent_fast_path",
                intent=fast_result.intent,
                tenant_id=tenant_id,
            )
            return fast_result

        # Step 2: Redis cache lookup
        cache_key = self._build_cache_key(query, tenant_id)
        cached = await self._cache_get(tenant_id, cache_key)
        if cached is not None:
            logger.info(
                "intent_cache_hit",
                intent=cached.intent,
                tenant_id=tenant_id,
            )
            return cached

        # Step 3: LLM call with timeout
        result = await self._llm_classify(query, conversation_history, tenant_id)

        # Step 4: Cache the result
        await self._cache_set(tenant_id, cache_key, result)

        logger.info(
            "intent_classified",
            intent=result.intent,
            confidence=result.confidence,
            tenant_id=tenant_id,
        )
        return result

    # ------------------------------------------------------------------
    # Fast path
    # ------------------------------------------------------------------

    def _fast_path_classify(self, query: str) -> IntentResult | None:
        """
        Check cheap regex patterns before touching the LLM or cache.

        Returns an IntentResult if the query matches a fast-path pattern,
        or None if LLM classification is needed.
        """
        # Memory command check
        for pattern in _MEMORY_COMMAND_PATTERNS:
            if pattern.search(query):
                return IntentResult(
                    intent="remember",
                    confidence=1.0,
                    metadata={"fast_path": True, "method": "regex"},
                )

        # Greeting check
        for pattern in _GREETING_PATTERNS:
            if pattern.search(query):
                return IntentResult(
                    intent="greeting",
                    confidence=0.95,
                    metadata={"fast_path": True, "method": "regex"},
                )

        # Feedback check
        for pattern in _FEEDBACK_PATTERNS:
            if pattern.search(query):
                return IntentResult(
                    intent="feedback",
                    confidence=0.95,
                    metadata={"fast_path": True, "method": "regex"},
                )

        return None

    # ------------------------------------------------------------------
    # LLM classification
    # ------------------------------------------------------------------

    async def _llm_classify(
        self,
        query: str,
        conversation_history: list,
        tenant_id: str,
    ) -> IntentResult:
        """
        Call the INTENT_MODEL with a 200ms timeout to classify the query.

        Falls back to IntentResult(intent="rag_query", confidence=0.5) on
        timeout or any error. Never raises to the caller.
        """
        try:
            result = await asyncio.wait_for(
                self._call_llm(query, conversation_history, tenant_id),
                timeout=_INTENT_DETECTION_TIMEOUT,
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(
                "intent_llm_timeout",
                tenant_id=tenant_id,
                timeout_seconds=_INTENT_DETECTION_TIMEOUT,
            )
            return IntentResult(
                intent=_FALLBACK_INTENT,
                confidence=0.5,
                metadata={"fallback": True, "reason": "timeout"},
            )
        except Exception as exc:
            logger.warning(
                "intent_llm_error",
                tenant_id=tenant_id,
                error=str(exc),
            )
            return IntentResult(
                intent=_FALLBACK_INTENT,
                confidence=0.5,
                metadata={"fallback": True, "reason": "llm_error"},
            )

    async def _call_llm(
        self,
        query: str,
        conversation_history: list,
        tenant_id: str,
    ) -> IntentResult:
        """
        Perform the actual LLM API call.

        Uses INTENT_MODEL → ROUTER_MODEL → PRIMARY_MODEL (first non-empty wins).
        Cloud provider determined by CLOUD_PROVIDER env var.
        """
        client = self._get_llm_client()

        model = (
            os.environ.get("INTENT_MODEL", "").strip()
            or os.environ.get("ROUTER_MODEL", "").strip()
            or os.environ.get("PRIMARY_MODEL", "").strip()
        )
        if not model:
            raise ValueError(
                "No intent model configured. Set INTENT_MODEL, ROUTER_MODEL, or "
                "PRIMARY_MODEL in .env."
            )

        # Build a compact history excerpt (last 3 turns) for context
        history_excerpt = conversation_history[-3:] if conversation_history else []
        messages = [{"role": "system", "content": _INTENT_SYSTEM_PROMPT}]
        for turn in history_excerpt:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": query})

        # Route through InstrumentedLLMClient when available
        if self._instrumented_client is not None:
            try:
                completion = await self._instrumented_client.complete(
                    tenant_id=tenant_id,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=64,
                    response_format={"type": "json_object"},
                )
                return self._parse_llm_response(completion.content)
            except Exception as exc:
                logger.warning(
                    "intent_instrumented_client_failed",
                    tenant_id=tenant_id,
                    error=str(exc),
                )
                # Fall through to direct client

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=64,
            response_format={"type": "json_object"},
        )

        raw_content = response.choices[0].message.content or "{}"
        return self._parse_llm_response(raw_content)

    def _get_llm_client(self):
        """Return the injected client or build one from env vars."""
        if self._llm_client is not None:
            return self._llm_client

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
            return AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=endpoint,
                api_version="2024-02-01",
            )

        from openai import AsyncOpenAI

        return AsyncOpenAI()

    @staticmethod
    def _parse_llm_response(raw: str) -> IntentResult:
        """
        Parse the LLM JSON response into an IntentResult.

        Falls back to rag_query if the JSON is malformed or the intent is
        not in _VALID_INTENTS.
        """
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("intent_parse_error", raw_length=len(raw))
            return IntentResult(
                intent=_FALLBACK_INTENT,
                confidence=0.5,
                metadata={"fallback": True, "reason": "json_parse_error"},
            )

        intent = str(data.get("intent", "")).strip()
        if intent not in _VALID_INTENTS:
            logger.warning("intent_invalid_label", intent=intent)
            intent = _FALLBACK_INTENT

        try:
            confidence = float(data.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.5

        return IntentResult(intent=intent, confidence=confidence)

    # ------------------------------------------------------------------
    # Redis cache helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_cache_key(query: str, tenant_id: str) -> str:
        """
        Build a stable, collision-resistant cache key for a query.

        CACHE-001: Uses SHA-256 of normalize_query(query) only (NOT tenant-prefixed
        here — the tenant namespace is enforced by the Redis key prefix in
        build_redis_key(tenant_id, 'intent', cache_key)).

        The key is a hex digest (no colons) — safe for Redis key construction.
        """
        from app.core.cache_utils import normalize_query

        normalized = normalize_query(query)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return digest

    async def _cache_get(self, tenant_id: str, cache_key: str) -> IntentResult | None:
        """Retrieve a cached IntentResult. Returns None on miss or Redis error."""
        try:
            from app.core.redis_client import build_redis_key

            redis = self._get_redis()
            # CACHE-001: key type changed from intent_cache to intent
            key = build_redis_key(tenant_id, "intent", cache_key)
            raw = await redis.get(key)
            if raw is None:
                return None
            data = json.loads(raw)
            return IntentResult(
                intent=data["intent"],
                confidence=data["confidence"],
                metadata=data.get("metadata", {}),
            )
        except Exception as exc:
            logger.warning(
                "intent_cache_get_error",
                tenant_id=tenant_id,
                error=str(exc),
            )
            return None

    async def _cache_set(
        self, tenant_id: str, cache_key: str, result: IntentResult
    ) -> None:
        """Store an IntentResult in Redis. Silently ignores Redis errors."""
        try:
            from app.core.redis_client import build_redis_key

            redis = self._get_redis()
            # CACHE-001: key type changed from intent_cache to intent
            key = build_redis_key(tenant_id, "intent", cache_key)
            payload = json.dumps(
                {
                    "intent": result.intent,
                    "confidence": result.confidence,
                    "metadata": result.metadata,
                }
            )
            await redis.setex(key, _INTENT_CACHE_TTL_SECONDS, payload)
        except Exception as exc:
            logger.warning(
                "intent_cache_set_error",
                tenant_id=tenant_id,
                error=str(exc),
            )

    def _get_redis(self):
        """Return injected Redis client or the global pool."""
        if self._redis is not None:
            return self._redis
        from app.core.redis_client import get_redis

        return get_redis()
