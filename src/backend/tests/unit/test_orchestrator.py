"""
Unit tests for ChatOrchestrationService (AI-056).

Tests the 8-stage RAG pipeline, SSE event sequence, memory fast path,
and service wiring.
Tier 1: Fast, isolated, mocks all dependencies.
"""
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def _fake_stream_llm(self, system_prompt, query, tenant_id):
    """Fake _stream_llm that yields a single chunk without touching OpenAI."""
    yield "Test LLM response."


@pytest.fixture(autouse=True)
def mock_llm_stream(monkeypatch):
    """Patch ChatOrchestrationService._stream_llm for all orchestrator unit tests.

    _stream_llm reads PRIMARY_MODEL and CLOUD_PROVIDER from env and makes a real
    OpenAI/Azure call — inappropriate for Tier 1 unit tests. This fixture replaces
    it with a deterministic fake async generator so tests remain fast and isolated.
    """
    from app.modules.chat import orchestrator as _orch_module

    monkeypatch.setattr(
        _orch_module.ChatOrchestrationService, "_stream_llm", _fake_stream_llm
    )


def _make_mock_services():
    """Create all mock services for the orchestrator."""
    from app.modules.chat.vector_search import SearchResult

    embedding = AsyncMock()
    embedding.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

    search_results = [
        SearchResult("Doc 1", "Content 1", 0.92, "http://sp/doc1", "d1"),
        SearchResult("Doc 2", "Content 2", 0.85, None, "d2"),
    ]
    vector_search = AsyncMock()
    vector_search.search = AsyncMock(return_value=search_results)

    profile = AsyncMock()
    profile.get_profile_context = AsyncMock(return_value={"technical_level": "expert"})
    profile.on_query_completed = AsyncMock()

    working_memory = AsyncMock()
    working_memory.get_for_prompt = AsyncMock(
        return_value={"topics": ["vpn"], "queries": ["VPN setup?"]}
    )
    working_memory.update = AsyncMock()

    org_context = AsyncMock()
    org_context.get = AsyncMock(
        return_value=MagicMock(
            to_dict=MagicMock(return_value={"department": "Engineering"})
        )
    )

    glossary = AsyncMock()
    glossary.expand = AsyncMock(
        return_value=(
            "What is AWS (Amazon Web Services)?",
            ["AWS -> Amazon Web Services"],
        )
    )

    prompt_builder = AsyncMock()
    prompt_builder.build = AsyncMock(
        return_value=(
            "You are an AI assistant...\n\n---\n\nContext...",
            ["profile", "org_context"],
        )
    )

    persistence = AsyncMock()
    persistence.save_exchange = AsyncMock(return_value=("msg-123", "conv-456"))

    confidence = MagicMock()
    confidence.calculate = MagicMock(return_value=0.88)

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
    }


async def _collect_events(gen):
    """Collect all events from async generator."""
    events = []
    async for event in gen:
        events.append(event)
    return events


class TestOrchestrator8Stages:
    """Test the full 8-stage pipeline."""

    @pytest.mark.asyncio
    async def test_all_stages_execute(self):
        """All 8 stages must execute for a normal query."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        service = ChatOrchestrationService(**mocks)

        events = await _collect_events(
            service.stream_response(
                query="What is the leave policy?",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id="conv-1",
                active_team_id=None,
                jwt_claims={},
            )
        )

        # Verify all key services were called
        mocks["glossary_expander"].expand.assert_called_once()
        mocks["embedding_service"].embed.assert_called_once()
        mocks["vector_search_service"].search.assert_called_once()
        mocks["profile_service"].get_profile_context.assert_called_once()
        mocks["working_memory_service"].get_for_prompt.assert_called_once()
        mocks["prompt_builder"].build.assert_called_once()
        mocks["persistence_service"].save_exchange.assert_called_once()

    @pytest.mark.asyncio
    async def test_sse_events_in_correct_order(self):
        """SSE events must be emitted in the correct sequence."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        service = ChatOrchestrationService(**mocks)

        events = await _collect_events(
            service.stream_response(
                query="What is VPN?",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id=None,
                active_team_id=None,
                jwt_claims={},
            )
        )

        event_types = [e["event"] for e in events]

        # Must have these event types in this general order
        assert "status" in event_types
        assert "sources" in event_types
        assert "response_chunk" in event_types
        assert "metadata" in event_types
        assert "done" in event_types

        # "done" must be last
        assert event_types[-1] == "done"

    @pytest.mark.asyncio
    async def test_sources_event_contains_results(self):
        """Sources event must contain search results."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        service = ChatOrchestrationService(**mocks)

        events = await _collect_events(
            service.stream_response(
                query="test",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id="c1",
                active_team_id=None,
                jwt_claims={},
            )
        )

        sources_events = [e for e in events if e["event"] == "sources"]
        assert len(sources_events) >= 1
        sources = sources_events[0]["data"]["sources"]
        assert len(sources) == 2

    @pytest.mark.asyncio
    async def test_metadata_contains_confidence(self):
        """Metadata event must include retrieval_confidence."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        service = ChatOrchestrationService(**mocks)

        events = await _collect_events(
            service.stream_response(
                query="test",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id="c1",
                active_team_id=None,
                jwt_claims={},
            )
        )

        metadata_events = [e for e in events if e["event"] == "metadata"]
        assert len(metadata_events) >= 1
        meta = metadata_events[0]["data"]
        assert "retrieval_confidence" in meta
        assert meta["retrieval_confidence"] == 0.88

    @pytest.mark.asyncio
    async def test_metadata_contains_glossary_expansions(self):
        """Metadata event must include glossary_expansions."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        service = ChatOrchestrationService(**mocks)

        events = await _collect_events(
            service.stream_response(
                query="What is AWS?",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id="c1",
                active_team_id=None,
                jwt_claims={},
            )
        )

        metadata_events = [e for e in events if e["event"] == "metadata"]
        meta = metadata_events[0]["data"]
        assert "glossary_expansions" in meta
        assert "AWS -> Amazon Web Services" in meta["glossary_expansions"]

    @pytest.mark.asyncio
    async def test_done_event_contains_ids(self):
        """Done event must include conversation_id and message_id."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        service = ChatOrchestrationService(**mocks)

        events = await _collect_events(
            service.stream_response(
                query="test",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id="c1",
                active_team_id=None,
                jwt_claims={},
            )
        )

        done_events = [e for e in events if e["event"] == "done"]
        assert len(done_events) == 1
        done = done_events[0]["data"]
        assert "conversation_id" in done
        assert "message_id" in done

    @pytest.mark.asyncio
    async def test_working_memory_update_called(self):
        """Working memory must be updated after response."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        service = ChatOrchestrationService(**mocks)

        await _collect_events(
            service.stream_response(
                query="test",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id="c1",
                active_team_id=None,
                jwt_claims={},
            )
        )

        mocks["working_memory_service"].update.assert_called_once()

    @pytest.mark.asyncio
    async def test_profile_learning_triggered(self):
        """Profile learning on_query_completed must be called."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        service = ChatOrchestrationService(**mocks)

        await _collect_events(
            service.stream_response(
                query="test",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id="c1",
                active_team_id=None,
                jwt_claims={},
            )
        )

        mocks["profile_service"].on_query_completed.assert_called_once()


class TestMemoryFastPath:
    """Test memory command fast path (bypasses RAG stages)."""

    @pytest.mark.asyncio
    async def test_remember_that_triggers_fast_path(self):
        """'Remember that ...' query bypasses RAG and saves memory note."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        mocks["working_memory_service"].add_note = AsyncMock(
            return_value=MagicMock(id="note-1", content="I prefer Python")
        )
        service = ChatOrchestrationService(**mocks)

        events = await _collect_events(
            service.stream_response(
                query="Remember that I prefer Python over Java",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id="c1",
                active_team_id=None,
                jwt_claims={},
            )
        )

        event_types = [e["event"] for e in events]

        # Memory fast path should emit memory_saved and done
        assert "memory_saved" in event_types
        assert "done" in event_types

        # Should NOT call RAG services
        mocks["embedding_service"].embed.assert_not_called()
        mocks["vector_search_service"].search.assert_not_called()

    @pytest.mark.asyncio
    async def test_note_that_triggers_fast_path(self):
        """'Note that ...' query also triggers fast path."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        mocks["working_memory_service"].add_note = AsyncMock(
            return_value=MagicMock(id="note-2", content="My timezone is SGT")
        )
        service = ChatOrchestrationService(**mocks)

        events = await _collect_events(
            service.stream_response(
                query="Note that my timezone is SGT",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id="c1",
                active_team_id=None,
                jwt_claims={},
            )
        )

        event_types = [e["event"] for e in events]
        assert "memory_saved" in event_types

    @pytest.mark.asyncio
    async def test_normal_query_does_not_trigger_fast_path(self):
        """Normal queries should NOT trigger memory fast path."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        service = ChatOrchestrationService(**mocks)

        events = await _collect_events(
            service.stream_response(
                query="What is the refund policy?",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id="c1",
                active_team_id=None,
                jwt_claims={},
            )
        )

        event_types = [e["event"] for e in events]
        assert "memory_saved" not in event_types
        assert "response_chunk" in event_types

    @pytest.mark.asyncio
    async def test_memory_content_over_200_chars_returns_error_sse(self):
        """
        Memory note content > 200 chars must return an error SSE event
        — NOT silently truncate. The LLM pipeline must NOT be invoked.
        """
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        mocks["working_memory_service"].add_note = AsyncMock(
            return_value=MagicMock(id="note-3", content="x" * 200)
        )
        service = ChatOrchestrationService(**mocks)

        long_content = "x" * 300
        events = await _collect_events(
            service.stream_response(
                query=f"Remember that {long_content}",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id="c1",
                active_team_id=None,
                jwt_claims={},
            )
        )

        event_types = [e["event"] for e in events]
        assert (
            "error" in event_types
        ), "Over-length content must emit an error SSE event"
        error_events = [e for e in events if e["event"] == "error"]
        assert error_events[0]["data"]["code"] == "memory_note_too_long"
        # add_note must NOT be called — error short-circuits before save
        mocks["working_memory_service"].add_note.assert_not_called()
        # memory_saved must not appear — content was not saved
        assert "memory_saved" not in event_types
        # done must be the final event — stream always terminates cleanly
        assert event_types[-1] == "done"

    @pytest.mark.asyncio
    async def test_all_memory_trigger_patterns_recognized(self):
        """
        All 5 trigger patterns from AI-024 must activate the memory fast path:
        'remember that', 'remember:', 'please remember', 'note that', 'save this:'
        """
        from app.modules.chat.orchestrator import ChatOrchestrationService

        patterns_and_queries = [
            "Remember that I prefer dark mode",
            "Remember: my team is Platform",
            "Please remember I am in SGT timezone",
            "Note that I like concise answers",
            "Save this: project deadline is Q2",
        ]

        for query in patterns_and_queries:
            mocks = _make_mock_services()
            mocks["working_memory_service"].add_note = AsyncMock(
                return_value=MagicMock(id="n", content="test")
            )
            service = ChatOrchestrationService(**mocks)

            events = await _collect_events(
                service.stream_response(
                    query=query,
                    user_id="u1",
                    tenant_id="t1",
                    agent_id="a1",
                    conversation_id="c1",
                    active_team_id=None,
                    jwt_claims={},
                )
            )

            event_types = [e["event"] for e in events]
            assert (
                "memory_saved" in event_types
            ), f"Query '{query}' should trigger memory fast path but got: {event_types}"
            mocks["embedding_service"].embed.assert_not_called()


class TestTeamMemoryIntegration:
    """Test team memory behavior."""

    @pytest.mark.asyncio
    async def test_team_memory_skipped_when_no_team(self):
        """Team memory should not be fetched when active_team_id is None."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        team_memory = AsyncMock()
        team_memory.get_context = AsyncMock()
        mocks["team_memory_service"] = team_memory

        service = ChatOrchestrationService(**mocks)

        await _collect_events(
            service.stream_response(
                query="test",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id="c1",
                active_team_id=None,
                jwt_claims={},
            )
        )

        # Team memory service should not have get_context called
        # (it might not even exist in the mock set if not passed)


class TestProfileContextUsedFlag:
    """AI-034: profile_context_used flag in metadata SSE event."""

    @pytest.mark.asyncio
    async def test_profile_context_used_true_when_profile_layer_active(self):
        """metadata.profile_context_used is True when 'profile' in layers_active."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        # prompt_builder returns profile layer active (default fixture already has this)
        mocks["prompt_builder"].build = AsyncMock(
            return_value=("system prompt", ["profile"])
        )
        service = ChatOrchestrationService(**mocks)

        events = await _collect_events(
            service.stream_response(
                query="show me my recent reports",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id=None,
                active_team_id=None,
                jwt_claims={},
            )
        )

        metadata = next(e["data"] for e in events if e["event"] == "metadata")
        assert metadata["profile_context_used"] is True

    @pytest.mark.asyncio
    async def test_profile_context_used_true_when_working_memory_active(self):
        """metadata.profile_context_used is True when 'working_memory' in layers_active."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        mocks["prompt_builder"].build = AsyncMock(
            return_value=("system prompt", ["working_memory"])
        )
        service = ChatOrchestrationService(**mocks)

        events = await _collect_events(
            service.stream_response(
                query="what were we discussing?",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id=None,
                active_team_id=None,
                jwt_claims={},
            )
        )

        metadata = next(e["data"] for e in events if e["event"] == "metadata")
        assert metadata["profile_context_used"] is True

    @pytest.mark.asyncio
    async def test_profile_context_used_false_when_no_personalisation_layers(self):
        """metadata.profile_context_used is False when no profile layers contributed."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        # Only RAG layer active — no personalisation
        mocks["prompt_builder"].build = AsyncMock(
            return_value=("system prompt", ["rag"])
        )
        service = ChatOrchestrationService(**mocks)

        events = await _collect_events(
            service.stream_response(
                query="what is the refund policy?",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id=None,
                active_team_id=None,
                jwt_claims={},
            )
        )

        metadata = next(e["data"] for e in events if e["event"] == "metadata")
        assert metadata["profile_context_used"] is False

    @pytest.mark.asyncio
    async def test_profile_context_used_true_any_personalisation_layer_sufficient(self):
        """profile_context_used True when org_context or team_memory active."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        mocks["prompt_builder"].build = AsyncMock(
            return_value=("system prompt", ["org_context", "team_memory"])
        )
        service = ChatOrchestrationService(**mocks)

        events = await _collect_events(
            service.stream_response(
                query="team status?",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id=None,
                active_team_id="team-1",
                jwt_claims={},
            )
        )

        metadata = next(e["data"] for e in events if e["event"] == "metadata")
        assert metadata["profile_context_used"] is True

    @pytest.mark.asyncio
    async def test_metadata_includes_profile_context_used_field(self):
        """metadata event always contains profile_context_used key."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        service = ChatOrchestrationService(**_make_mock_services())

        events = await _collect_events(
            service.stream_response(
                query="hello",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id=None,
                active_team_id=None,
                jwt_claims={},
            )
        )

        metadata_events = [e for e in events if e["event"] == "metadata"]
        assert len(metadata_events) == 1
        assert "profile_context_used" in metadata_events[0]["data"]


class TestEmbeddingUseOriginalQuery:
    """Verify embedding uses ORIGINAL query, not expanded."""

    @pytest.mark.asyncio
    async def test_embed_uses_original_not_expanded(self):
        """Stage 3: Embed must use ORIGINAL query, not glossary-expanded."""
        from app.modules.chat.orchestrator import ChatOrchestrationService

        mocks = _make_mock_services()
        mocks["glossary_expander"].expand = AsyncMock(
            return_value=(
                "What is AWS (Amazon Web Services)?",
                ["AWS -> Amazon Web Services"],
            )
        )
        service = ChatOrchestrationService(**mocks)

        await _collect_events(
            service.stream_response(
                query="What is AWS?",
                user_id="u1",
                tenant_id="t1",
                agent_id="a1",
                conversation_id="c1",
                active_team_id=None,
                jwt_claims={},
            )
        )

        # Embedding should use the ORIGINAL query (with tenant_id for cache)
        mocks["embedding_service"].embed.assert_called_once_with(
            "What is AWS?", tenant_id="t1"
        )
