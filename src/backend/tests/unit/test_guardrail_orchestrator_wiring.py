"""
Unit tests for guardrail wiring in ChatOrchestrationService (ATA-019/020/021).

Tests:
  1. Guardrail-enabled agent buffers chunks — no SSE yield until Stage 7b completes
  2. Blocked response: SSE emits guardrail_triggered event + canned message, NOT original
  3. Blocked response: save_exchange is NOT called
  4. Redacted response: save_exchange IS called with filtered_text
  5. Default agent (no guardrails): chunks yield live, Stage 7b not invoked
  6. Stage 4.5: low retrieval confidence + threshold set -> canned response, LLM NOT called
  7. Stage 4.5: threshold=0 -> LLM called regardless of confidence

Tier 1: Fast, isolated, mocks all dependencies.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _collect_events(gen):
    """Collect all events from an async generator."""
    events = []
    async for event in gen:
        events.append(event)
    return events


def _make_base_mocks(guardrail_config=None, retrieval_confidence=0.88):
    """
    Build the full mock services dict required by ChatOrchestrationService.

    guardrail_config: dict merged into capabilities["guardrails"] for the agent.
    """
    from app.modules.chat.vector_search import SearchResult

    capabilities = {}
    if guardrail_config is not None:
        capabilities["guardrails"] = guardrail_config

    embedding = AsyncMock()
    embedding.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

    search_results = [
        SearchResult("Doc 1", "Content 1", 0.92, "http://sp/doc1", "d1"),
    ]
    vector_search = AsyncMock()
    vector_search.search = AsyncMock(return_value=search_results)
    vector_search.search_conversation_index = AsyncMock(return_value=[])

    profile = AsyncMock()
    profile.get_profile_context = AsyncMock(return_value={"technical_level": "expert"})
    profile.on_query_completed = AsyncMock()

    working_memory = AsyncMock()
    working_memory.get_for_prompt = AsyncMock(return_value={})
    working_memory.update = AsyncMock()

    org_context = AsyncMock()
    org_context.get = AsyncMock(
        return_value=MagicMock(to_dict=MagicMock(return_value={}))
    )

    glossary = AsyncMock()
    glossary.expand = AsyncMock(return_value=("expanded query", []))

    prompt_builder = AsyncMock()
    prompt_builder.build = AsyncMock(
        return_value=("You are an assistant.", ["profile"])
    )
    prompt_builder._get_agent_prompt = AsyncMock(
        return_value=("Agent prompt.", capabilities, [], [])
    )

    persistence = AsyncMock()
    persistence.save_exchange = AsyncMock(return_value=("msg-123", "conv-456"))

    confidence = MagicMock()
    confidence.calculate = MagicMock(return_value=retrieval_confidence)

    db_session = AsyncMock()
    db_session.execute = AsyncMock()
    db_session.commit = AsyncMock()

    return {
        "embedding_service": embedding,
        "vector_search_service": vector_search,
        "profile_service": profile,
        "working_memory_service": working_memory,
        "org_context_service": org_context,
        "glossary_expander": glossary,
        "prompt_builder": prompt_builder,
        "persistence_service": persistence,
        "confidence_calculator": confidence,
        "db_session": db_session,
    }


def _make_service(mocks):
    """Instantiate ChatOrchestrationService with mock services."""
    from app.modules.chat.orchestrator import ChatOrchestrationService
    return ChatOrchestrationService(**mocks)


def _standard_call_kwargs(
    query="What is the leave policy?",
    agent_id="agent-1",
    conversation_id="conv-1",
):
    return dict(
        query=query,
        user_id="user-1",
        tenant_id="tenant-1",
        agent_id=agent_id,
        conversation_id=conversation_id,
        active_team_id=None,
        jwt_claims={},
    )


# ---------------------------------------------------------------------------
# Fixtures: patch away infrastructure that hits external I/O
# ---------------------------------------------------------------------------

async def _fake_stream_llm(self, system_prompt, query, tenant_id):
    """Deterministic fake _stream_llm — yields tokens without touching OpenAI."""
    yield "chunk1 "
    yield "chunk2"


@pytest.fixture(autouse=True)
def patch_llm_stream(monkeypatch):
    from app.modules.chat import orchestrator as _mod
    monkeypatch.setattr(_mod.ChatOrchestrationService, "_stream_llm", _fake_stream_llm)


@pytest.fixture(autouse=True)
def patch_semantic_cache(monkeypatch):
    """Disable semantic cache to avoid Redis calls in unit tests."""
    from app.modules.chat import orchestrator as _mod

    original = _mod.ChatOrchestrationService.stream_response

    async def _patched_stream(self, **kwargs):
        # Patch the internal cache lookup to always miss
        with patch("app.core.cache.semantic_cache_service.SemanticCacheService") as _sc:
            _sc.return_value.lookup = AsyncMock(return_value=None)
            _sc.return_value.store = AsyncMock()
            with patch("app.core.tenant_config_service.TenantConfigService") as _tc:
                _tc.return_value.get = AsyncMock(return_value={})
                async for event in original(self, **kwargs):
                    yield event

    monkeypatch.setattr(_mod.ChatOrchestrationService, "stream_response", _patched_stream)


@pytest.fixture(autouse=True)
def patch_token_budget(monkeypatch):
    """Patch get_tenant_token_budget to avoid DB calls."""
    monkeypatch.setattr(
        "app.modules.chat.prompt_builder.get_tenant_token_budget",
        AsyncMock(return_value=4096),
    )


# ---------------------------------------------------------------------------
# Test 1: Guardrail-enabled agent buffers chunks
# ---------------------------------------------------------------------------

class TestGuardrailBuffering:
    """Stage 7 must buffer chunks when guardrails are active — no token SSE until 7b."""

    @pytest.mark.asyncio
    async def test_buffered_chunks_yield_single_response_chunk_after_check(self):
        """
        When guardrails are enabled, chunks must NOT flow live to SSE.
        Stage 7b must run first; the buffered text is emitted as a single
        response_chunk event after the check passes.
        """
        guardrail_config = {
            "blocked_topics": ["competitor"],  # active guardrail
        }
        mocks = _make_base_mocks(guardrail_config=guardrail_config)
        service = _make_service(mocks)

        events = await _collect_events(service.stream_response(**_standard_call_kwargs()))

        response_chunk_events = [e for e in events if e["event"] == "response_chunk"]
        # Guardrail-enabled path yields exactly one response_chunk (the full buffered text)
        assert len(response_chunk_events) == 1, (
            "Buffered path must yield exactly one response_chunk after guardrail check"
        )
        # The chunk must contain the full concatenated LLM output
        assert response_chunk_events[0]["data"]["chunk"] == "chunk1 chunk2"

    @pytest.mark.asyncio
    async def test_no_token_events_before_guardrail_check_on_buffered_path(self):
        """
        No 'token' events should appear when guardrails buffer the response
        (the spec uses 'token' only on blocked path; normal path uses response_chunk).
        """
        guardrail_config = {"max_response_length": 9999}
        mocks = _make_base_mocks(guardrail_config=guardrail_config)
        service = _make_service(mocks)

        events = await _collect_events(service.stream_response(**_standard_call_kwargs()))

        token_events = [e for e in events if e["event"] == "token"]
        assert len(token_events) == 0, "No 'token' events on buffered+pass path"


# ---------------------------------------------------------------------------
# Test 2: Blocked response SSE events
# ---------------------------------------------------------------------------

class TestBlockedResponse:
    """Blocked response must emit guardrail_triggered + canned token, not original."""

    @pytest.mark.asyncio
    async def test_blocked_emits_guardrail_triggered_event(self):
        guardrail_config = {"blocked_topics": ["chunk1"]}  # matches fake LLM output
        mocks = _make_base_mocks(guardrail_config=guardrail_config)
        service = _make_service(mocks)

        events = await _collect_events(service.stream_response(**_standard_call_kwargs()))

        gt_events = [e for e in events if e["event"] == "guardrail_triggered"]
        assert len(gt_events) == 1
        data = gt_events[0]["data"]
        assert data["action"] == "block"
        assert data["agent_id"] == "agent-1"

    @pytest.mark.asyncio
    async def test_blocked_emits_canned_token_not_original_text(self):
        """The canned message must be in the token event, never the original text."""
        from app.modules.chat.guardrails import _CANNED_BLOCK_RESPONSE

        guardrail_config = {"blocked_topics": ["chunk1"]}
        mocks = _make_base_mocks(guardrail_config=guardrail_config)
        service = _make_service(mocks)

        events = await _collect_events(service.stream_response(**_standard_call_kwargs()))

        token_events = [e for e in events if e["event"] == "token"]
        assert len(token_events) >= 1
        all_token_text = "".join(e["data"]["text"] for e in token_events)
        # Original LLM text must NOT appear
        assert "chunk1" not in all_token_text
        assert "chunk2" not in all_token_text
        # Canned message must appear
        assert _CANNED_BLOCK_RESPONSE in all_token_text

    @pytest.mark.asyncio
    async def test_blocked_response_chunk_not_in_any_event(self):
        """Original LLM text must be absent from all SSE events on block."""
        guardrail_config = {"blocked_topics": ["chunk2"]}
        mocks = _make_base_mocks(guardrail_config=guardrail_config)
        service = _make_service(mocks)

        events = await _collect_events(service.stream_response(**_standard_call_kwargs()))

        all_text = str(events)
        assert "chunk2" not in all_text

    @pytest.mark.asyncio
    async def test_blocked_ends_with_done_event(self):
        guardrail_config = {"blocked_topics": ["chunk1"]}
        mocks = _make_base_mocks(guardrail_config=guardrail_config)
        service = _make_service(mocks)

        events = await _collect_events(service.stream_response(**_standard_call_kwargs()))

        assert events[-1]["event"] == "done"


# ---------------------------------------------------------------------------
# Test 3: Blocked response — save_exchange NOT called
# ---------------------------------------------------------------------------

class TestBlockedSaveExchange:
    """save_exchange must NOT be called when the guardrail blocks the response."""

    @pytest.mark.asyncio
    async def test_save_exchange_not_called_on_block(self):
        guardrail_config = {"blocked_topics": ["chunk1"]}
        mocks = _make_base_mocks(guardrail_config=guardrail_config)
        service = _make_service(mocks)

        await _collect_events(service.stream_response(**_standard_call_kwargs()))

        mocks["persistence_service"].save_exchange.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4: Redacted response — save_exchange IS called with filtered_text
# ---------------------------------------------------------------------------

class TestRedactedResponse:
    """Redacted response must be saved; save_exchange receives filtered text."""

    @pytest.mark.asyncio
    async def test_save_exchange_called_with_redacted_text(self):
        guardrail_config = {
            "rules": [
                {
                    "rule_id": "redact-chunk1",
                    "rule_type": "keyword_block",
                    "patterns": ["chunk1"],
                    "on_violation": "redact",
                    "replacement": "[REDACTED]",
                }
            ]
        }
        mocks = _make_base_mocks(guardrail_config=guardrail_config)
        service = _make_service(mocks)

        await _collect_events(service.stream_response(**_standard_call_kwargs()))

        mocks["persistence_service"].save_exchange.assert_called_once()
        call_kwargs = mocks["persistence_service"].save_exchange.call_args
        # response arg must contain the replacement, not the original
        response_arg = call_kwargs.kwargs.get("response", call_kwargs.args[4] if len(call_kwargs.args) > 4 else None)
        assert response_arg is not None
        assert "[REDACTED]" in response_arg
        assert "chunk1" not in response_arg

    @pytest.mark.asyncio
    async def test_save_exchange_called_with_guardrail_violations_on_redact(self):
        """save_exchange receives guardrail_violations kwarg when redact fires."""
        guardrail_config = {
            "rules": [
                {
                    "rule_id": "redact-rule",
                    "rule_type": "keyword_block",
                    "patterns": ["chunk2"],
                    "on_violation": "redact",
                    "replacement": "[REMOVED]",
                }
            ]
        }
        mocks = _make_base_mocks(guardrail_config=guardrail_config)
        service = _make_service(mocks)

        await _collect_events(service.stream_response(**_standard_call_kwargs()))

        call_kwargs = mocks["persistence_service"].save_exchange.call_args.kwargs
        violations = call_kwargs.get("guardrail_violations", [])
        assert isinstance(violations, list)
        assert len(violations) >= 1


# ---------------------------------------------------------------------------
# Test 5: Default agent — no guardrails, live streaming
# ---------------------------------------------------------------------------

class TestNoGuardrails:
    """When no guardrails are active, chunks stream live and Stage 7b is not invoked."""

    @pytest.mark.asyncio
    async def test_live_streaming_with_no_guardrails(self):
        """Default path yields multiple response_chunk events (one per LLM chunk)."""
        mocks = _make_base_mocks(guardrail_config=None)
        service = _make_service(mocks)

        events = await _collect_events(service.stream_response(**_standard_call_kwargs()))

        response_chunk_events = [e for e in events if e["event"] == "response_chunk"]
        # _fake_stream_llm yields 2 chunks, so 2 response_chunk events expected
        assert len(response_chunk_events) == 2

    @pytest.mark.asyncio
    async def test_no_guardrail_triggered_event_without_guardrails(self):
        mocks = _make_base_mocks(guardrail_config=None)
        service = _make_service(mocks)

        events = await _collect_events(service.stream_response(**_standard_call_kwargs()))

        gt_events = [e for e in events if e["event"] == "guardrail_triggered"]
        assert len(gt_events) == 0

    @pytest.mark.asyncio
    async def test_save_exchange_called_on_no_guardrails(self):
        mocks = _make_base_mocks(guardrail_config=None)
        service = _make_service(mocks)

        await _collect_events(service.stream_response(**_standard_call_kwargs()))

        mocks["persistence_service"].save_exchange.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_exchange_guardrail_violations_empty_without_guardrails(self):
        """save_exchange must receive empty guardrail_violations on normal path."""
        mocks = _make_base_mocks(guardrail_config=None)
        service = _make_service(mocks)

        await _collect_events(service.stream_response(**_standard_call_kwargs()))

        call_kwargs = mocks["persistence_service"].save_exchange.call_args.kwargs
        violations = call_kwargs.get("guardrail_violations", [])
        assert violations == []


# ---------------------------------------------------------------------------
# Test 6: Stage 4.5 — low confidence + threshold set → canned response
# ---------------------------------------------------------------------------

class TestConfidenceGate:
    """Stage 4.5 pre-LLM confidence gate (ATA-020)."""

    @pytest.mark.asyncio
    async def test_low_confidence_yields_canned_response(self):
        """When retrieval_confidence < threshold, canned response is yielded."""
        from app.modules.chat.guardrails import _CANNED_LOW_CONFIDENCE

        guardrail_config = {"confidence_threshold": 0.9}
        # retrieval_confidence=0.5 < threshold=0.9
        mocks = _make_base_mocks(guardrail_config=guardrail_config, retrieval_confidence=0.5)
        service = _make_service(mocks)

        events = await _collect_events(service.stream_response(**_standard_call_kwargs()))

        token_events = [e for e in events if e["event"] == "token"]
        assert len(token_events) >= 1
        token_text = "".join(e["data"]["text"] for e in token_events)
        assert _CANNED_LOW_CONFIDENCE in token_text

    @pytest.mark.asyncio
    async def test_low_confidence_llm_not_called(self):
        """LLM must NOT be called when the confidence gate short-circuits."""
        guardrail_config = {"confidence_threshold": 0.9}
        mocks = _make_base_mocks(guardrail_config=guardrail_config, retrieval_confidence=0.3)

        llm_called = []

        async def _tracking_stream(self, system_prompt, query, tenant_id):
            llm_called.append(True)
            yield "should not appear"

        from app.modules.chat import orchestrator as _mod
        original = _mod.ChatOrchestrationService._stream_llm
        _mod.ChatOrchestrationService._stream_llm = _tracking_stream

        try:
            service = _make_service(mocks)
            await _collect_events(service.stream_response(**_standard_call_kwargs()))
        finally:
            _mod.ChatOrchestrationService._stream_llm = original

        assert llm_called == [], "LLM must NOT be called when confidence gate triggers"

    @pytest.mark.asyncio
    async def test_low_confidence_save_exchange_called(self):
        """
        Stage 4.5 DOES call save_exchange (unlike a block) — the canned response
        is valid conversation history.
        """
        guardrail_config = {"confidence_threshold": 0.9}
        mocks = _make_base_mocks(guardrail_config=guardrail_config, retrieval_confidence=0.4)
        service = _make_service(mocks)

        await _collect_events(service.stream_response(**_standard_call_kwargs()))

        mocks["persistence_service"].save_exchange.assert_called_once()

    @pytest.mark.asyncio
    async def test_low_confidence_ends_with_done(self):
        guardrail_config = {"confidence_threshold": 0.9}
        mocks = _make_base_mocks(guardrail_config=guardrail_config, retrieval_confidence=0.2)
        service = _make_service(mocks)

        events = await _collect_events(service.stream_response(**_standard_call_kwargs()))

        assert events[-1]["event"] == "done"


# ---------------------------------------------------------------------------
# Test 7: Stage 4.5 — threshold=0 → LLM called regardless
# ---------------------------------------------------------------------------

class TestConfidenceGateDisabled:
    """When confidence_threshold is 0 (or absent), the gate must not trigger."""

    @pytest.mark.asyncio
    async def test_zero_threshold_llm_called(self):
        """threshold=0 means no gate — LLM must be called even on low confidence."""
        guardrail_config = {"confidence_threshold": 0.0}
        # Very low retrieval confidence
        mocks = _make_base_mocks(guardrail_config=guardrail_config, retrieval_confidence=0.01)
        service = _make_service(mocks)

        events = await _collect_events(service.stream_response(**_standard_call_kwargs()))

        # LLM response chunks must appear (guardrail passes, no block)
        response_chunk_events = [e for e in events if e["event"] == "response_chunk"]
        assert len(response_chunk_events) >= 1, (
            "LLM must be called when threshold=0"
        )

    @pytest.mark.asyncio
    async def test_no_threshold_key_llm_called(self):
        """No confidence_threshold key in config — gate must not trigger."""
        guardrail_config = {"blocked_topics": []}  # inactive
        mocks = _make_base_mocks(guardrail_config=guardrail_config, retrieval_confidence=0.01)
        service = _make_service(mocks)

        events = await _collect_events(service.stream_response(**_standard_call_kwargs()))

        # Normal flow — LLM executes, response_chunk events appear
        all_event_types = [e["event"] for e in events]
        assert "response_chunk" in all_event_types or "token" in all_event_types

    @pytest.mark.asyncio
    async def test_high_confidence_above_threshold_llm_called(self):
        """When retrieval_confidence > threshold, gate must not trigger."""
        guardrail_config = {"confidence_threshold": 0.7}
        mocks = _make_base_mocks(guardrail_config=guardrail_config, retrieval_confidence=0.95)
        service = _make_service(mocks)

        events = await _collect_events(service.stream_response(**_standard_call_kwargs()))

        # response_chunk expected (guardrail enabled, but check passes)
        response_chunk_events = [e for e in events if e["event"] == "response_chunk"]
        assert len(response_chunk_events) == 1  # buffered path, single chunk


# ---------------------------------------------------------------------------
# Additional: persistence.save_exchange guardrail_violations stored in metadata
# ---------------------------------------------------------------------------

class TestPersistenceGuardrailViolations:
    """ATA-021: guardrail_violations stored in conversation_messages.metadata."""

    def test_save_exchange_merges_violations_into_metadata(self):
        """
        save_exchange must include guardrail_violations in the assistant message
        metadata JSON when the list is non-empty.
        """
        import json
        from unittest.mock import AsyncMock, MagicMock
        from app.modules.chat.persistence import ConversationPersistenceService

        captured_params = {}

        async def _fake_execute(sql_or_text, params=None):
            if params:
                captured_params.update(params)
            result = MagicMock()
            result.scalar_one = MagicMock(return_value="id-1")
            return result

        db = MagicMock()
        db.execute = _fake_execute
        db.commit = AsyncMock()

        import asyncio
        svc = ConversationPersistenceService(db)

        violations = [{"rule_id": "blocked_topics", "action": "block"}]

        asyncio.run(svc.save_exchange(
            user_id="u1",
            tenant_id="t1",
            conversation_id="conv-1",
            query="test query",
            response="test response",
            sources=[],
            guardrail_violations=violations,
        ))

        # The last metadata param captured should contain guardrail_violations
        assert "metadata" in captured_params
        stored = json.loads(captured_params["metadata"])
        assert "guardrail_violations" in stored
        assert stored["guardrail_violations"] == violations

    def test_save_exchange_no_violations_metadata_has_no_key(self):
        """
        When guardrail_violations is empty/None, the metadata must NOT include
        the key (clean baseline, backward compatible).
        """
        import json
        from unittest.mock import AsyncMock, MagicMock
        from app.modules.chat.persistence import ConversationPersistenceService

        captured_params = {}

        async def _fake_execute(sql_or_text, params=None):
            if params:
                captured_params.update(params)
            result = MagicMock()
            result.scalar_one = MagicMock(return_value="id-1")
            return result

        db = MagicMock()
        db.execute = _fake_execute
        db.commit = AsyncMock()

        import asyncio
        svc = ConversationPersistenceService(db)

        asyncio.run(svc.save_exchange(
            user_id="u1",
            tenant_id="t1",
            conversation_id="conv-1",
            query="test query",
            response="test response",
            sources=[],
            guardrail_violations=[],
        ))

        assert "metadata" in captured_params
        stored = json.loads(captured_params["metadata"])
        assert "guardrail_violations" not in stored
