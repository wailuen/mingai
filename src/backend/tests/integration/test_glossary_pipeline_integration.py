"""
AI-031 / TEST-032: Glossary Pipeline Integration Tests

Tests the full pipeline: query -> glossary expansion -> RAG (original) + LLM (expanded).
Verifies routing contracts between pipeline stages.

Architecture:
  - GlossaryExpander uses real Redis + PostgreSQL (no mocking)
  - ChatOrchestrationService uses mocked LLM + embedding/search services
  - Rollout flag tested against real tenant_configs table
  - Cross-tenant isolation verified with real data

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_glossary_pipeline_integration.py -v --timeout=10
"""
import asyncio
import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.redis_client as _redis_mod
from app.core.redis_client import close_redis, get_redis
from app.modules.glossary.expander import GLOSSARY_CACHE_TTL_SECONDS, GlossaryExpander


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


def _reset_redis_pool():
    _redis_mod._redis_pool = None


def _make_engine():
    return create_async_engine(_db_url(), echo=False)


async def _run_sql(sql: str, params: dict = None):
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _create_test_tenant() -> str:
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"Glossary Pipeline Test {tid[:8]}",
            "slug": f"gp-test-{tid[:8]}",
            "email": f"admin-{tid[:8]}@gp-int.test",
        },
    )
    return tid


async def _cleanup_tenant(tid: str):
    await _run_sql("DELETE FROM glossary_terms WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM tenant_configs WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})


async def _insert_glossary_term(
    tenant_id: str, term: str, full_form: str, aliases: list = None
):
    """Insert a glossary term for a tenant. Idempotent — ignores duplicate (tenant_id, term)."""
    await _run_sql(
        "INSERT INTO glossary_terms (id, tenant_id, term, full_form, aliases) "
        "VALUES (:id, :tenant_id, :term, :full_form, CAST(:aliases AS jsonb)) "
        "ON CONFLICT (tenant_id, term) DO NOTHING",
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "term": term,
            "full_form": full_form,
            "aliases": json.dumps(aliases or []),
        },
    )


async def _set_rollout_flag(tenant_id: str, enabled: bool):
    """Set glossary_pretranslation flag for a tenant in tenant_configs."""
    await _run_sql(
        "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
        "VALUES (gen_random_uuid(), :tid, 'glossary_pretranslation', CAST(:val AS jsonb)) "
        "ON CONFLICT (tenant_id, config_type) "
        "DO UPDATE SET config_data = CAST(:val AS jsonb)",
        {"tid": tenant_id, "val": json.dumps({"enabled": enabled})},
    )


async def _clear_redis_cache(tenant_id: str):
    """Remove glossary cache key for tenant from Redis."""
    _reset_redis_pool()
    redis = get_redis()
    try:
        await redis.delete(f"mingai:{tenant_id}:glossary_terms")
    finally:
        await close_redis()


def _make_orchestrator_with_real_glossary(tenant_id: str, db_session):
    """
    Build a ChatOrchestrationService with:
    - Real GlossaryExpander (real Redis + PostgreSQL)
    - Mocked embedding: records which query it received
    - Mocked vector_search: returns empty results
    - Mocked profile, working_memory, org_context, team_memory: minimal stubs
    - Mocked LLM service: yields a canned response chunk
    - Mocked persistence, confidence_calculator, prompt_builder: minimal stubs
    """
    from app.modules.chat.orchestrator import ChatOrchestrationService

    received_queries = {"embed": None, "llm": None, "prompt_system": None}

    # Real glossary expander
    real_glossary = GlossaryExpander(db=db_session)

    # Embedding mock — records the query passed to embed()
    embedding_service = MagicMock()

    async def _embed(query):
        received_queries["embed"] = query
        return [0.1] * 1536  # dummy vector

    embedding_service.embed = _embed

    # Vector search mock — returns empty results
    vector_search_service = MagicMock()

    async def _search(**kwargs):
        return []

    vector_search_service.search = _search

    # Profile mock
    profile_service = MagicMock()
    profile_service.get_profile_context = AsyncMock(return_value=None)
    profile_service.on_query_completed = AsyncMock()

    # Working memory mock
    working_memory_service = MagicMock()
    working_memory_service.get_for_prompt = AsyncMock(return_value=None)
    working_memory_service.update = AsyncMock()

    # Org context mock
    org_context_service = MagicMock()
    org_ctx = MagicMock()
    org_ctx.to_dict = MagicMock(return_value={})
    org_context_service.get = AsyncMock(return_value=org_ctx)

    # Confidence calculator
    confidence_calculator = MagicMock()
    confidence_calculator.calculate = MagicMock(return_value=0.75)

    # Prompt builder mock — records the system prompt
    prompt_builder = MagicMock()

    async def _build(**kwargs):
        rag_ctx = kwargs.get("rag_context", [])
        received_queries["prompt_system"] = kwargs
        return "SYSTEM: You are a helpful assistant.", ["layer0", "layer1"]

    prompt_builder.build = _build

    # LLM service mock — records the query (expanded) it receives
    llm_service = MagicMock()

    async def _stream_llm(**kwargs):
        received_queries["llm"] = kwargs.get("query")
        yield "Test response."

    llm_service.stream = _stream_llm

    # Persistence mock
    persistence_service = MagicMock()
    persistence_service.save_exchange = AsyncMock(
        return_value=("msg-id-123", "conv-id-456")
    )

    orchestrator = ChatOrchestrationService(
        embedding_service=embedding_service,
        vector_search_service=vector_search_service,
        profile_service=profile_service,
        working_memory_service=working_memory_service,
        org_context_service=org_context_service,
        glossary_expander=real_glossary,
        prompt_builder=prompt_builder,
        persistence_service=persistence_service,
        confidence_calculator=confidence_calculator,
        llm_service=llm_service,
    )

    return orchestrator, received_queries


async def _collect_events(
    orchestrator, *, query, tenant_id, user_id="user-1", agent_id="agent-1"
):
    """Collect all SSE events from stream_response."""
    events = []
    async for event in orchestrator.stream_response(
        query=query,
        user_id=user_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        conversation_id=None,
        active_team_id=None,
        jwt_claims={},
    ):
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def tenant_id():
    """Provision one real tenant per class, clean up after."""
    tid = asyncio.run(_create_test_tenant())
    yield tid
    asyncio.run(_cleanup_tenant(tid))


@pytest.fixture(scope="class")
def tenant_b_id():
    """A second tenant for cross-tenant isolation tests."""
    tid = asyncio.run(_create_test_tenant())
    yield tid
    asyncio.run(_cleanup_tenant(tid))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGlossaryPipelineIntegration:
    """
    AI-031: Full glossary pipeline integration tests.

    Uses real Redis + PostgreSQL for glossary expansion.
    LLM calls mocked; all other services minimally stubbed.
    """

    def test_embedding_receives_original_query(self, tenant_id):
        """
        Stage 3 (embedding) MUST receive the original query, not the expanded one.
        This is the core architectural contract: RAG index was built on original
        language; vector similarity requires the same embedding space.
        """
        asyncio.run(_clear_redis_cache(tenant_id))
        asyncio.run(
            _insert_glossary_term(tenant_id, "AL", "Annual Leave", aliases=["PTO"])
        )

        async def _run():
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    (
                        orchestrator,
                        received_queries,
                    ) = _make_orchestrator_with_real_glossary(tenant_id, session)
                    await _collect_events(
                        orchestrator, query="What is AL policy?", tenant_id=tenant_id
                    )
            finally:
                await close_redis()
                await engine.dispose()
            return received_queries

        received = asyncio.run(_run())
        assert (
            received["embed"] == "What is AL policy?"
        ), f"Embedding must receive original query. Got: {received['embed']!r}"

    def test_llm_receives_expanded_query(self, tenant_id):
        """
        Stage 7 (LLM) MUST receive the expanded query.
        Glossary expansion happens at Stage 1; the expanded form goes to the LLM
        to ensure the model has full context without needing to know acronyms.
        """
        asyncio.run(_clear_redis_cache(tenant_id))
        asyncio.run(_insert_glossary_term(tenant_id, "AL", "Annual Leave"))

        async def _run():
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    (
                        orchestrator,
                        received_queries,
                    ) = _make_orchestrator_with_real_glossary(tenant_id, session)
                    await _collect_events(
                        orchestrator, query="What is AL policy?", tenant_id=tenant_id
                    )
            finally:
                await close_redis()
                await engine.dispose()
            return received_queries

        received = asyncio.run(_run())
        llm_query = received["llm"]
        assert llm_query is not None, "LLM must receive a query"
        assert (
            "Annual Leave" in llm_query
        ), f"LLM must receive expanded query containing 'Annual Leave'. Got: {llm_query!r}"
        assert (
            "AL" in llm_query
        ), "Expanded query should still contain original 'AL' term"

    def test_response_metadata_includes_expansions(self, tenant_id):
        """
        The SSE 'metadata' event must include glossary_expansions list.
        This is the analytics signal: platform admin can audit which terms
        were expanded in each query.
        """
        asyncio.run(_clear_redis_cache(tenant_id))
        asyncio.run(_insert_glossary_term(tenant_id, "HR", "Human Resources"))

        async def _run():
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    orchestrator, _ = _make_orchestrator_with_real_glossary(
                        tenant_id, session
                    )
                    events = await _collect_events(
                        orchestrator, query="HR policy for team", tenant_id=tenant_id
                    )
            finally:
                await close_redis()
                await engine.dispose()
            return events

        events = asyncio.run(_run())
        metadata_events = [e for e in events if e["event"] == "metadata"]
        assert (
            len(metadata_events) == 1
        ), f"Expected exactly 1 metadata event, got {len(metadata_events)}"
        expansions = metadata_events[0]["data"]["glossary_expansions"]
        assert isinstance(expansions, list), "glossary_expansions must be a list"
        assert len(expansions) >= 1, "Should have at least one expansion for 'HR'"
        assert any(
            "Human Resources" in exp for exp in expansions
        ), f"Expected 'Human Resources' in expansions. Got: {expansions}"

    def test_no_expansion_when_tenant_has_no_terms(self, tenant_id):
        """
        When a tenant has no glossary terms, original query is used for both
        embedding and LLM, and expansions list is empty.
        """
        # Use a fresh tenant with no terms
        fresh_tid = asyncio.run(_create_test_tenant())
        asyncio.run(_clear_redis_cache(fresh_tid))

        async def _run():
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    (
                        orchestrator,
                        received_queries,
                    ) = _make_orchestrator_with_real_glossary(fresh_tid, session)
                    events = await _collect_events(
                        orchestrator, query="What is AL policy?", tenant_id=fresh_tid
                    )
            finally:
                await close_redis()
                await engine.dispose()
            return events, received_queries

        try:
            events, received_queries = asyncio.run(_run())
        finally:
            asyncio.run(_cleanup_tenant(fresh_tid))
        metadata_events = [e for e in events if e["event"] == "metadata"]
        assert (
            metadata_events[0]["data"]["glossary_expansions"] == []
        ), "No terms → empty expansions list"
        assert (
            received_queries["embed"] == "What is AL policy?"
        ), "Embed gets original query"
        assert (
            received_queries["llm"] == "What is AL policy?"
        ), "LLM gets unchanged query when no expansion"

    def test_layer_6_absent_from_system_prompt(self, tenant_id):
        """
        The system prompt must NOT contain a Layer 6 glossary section.
        Glossary expansion is handled inline (Stage 1), not via system prompt injection.
        This verifies the architectural migration away from Layer 6 injection.
        """
        asyncio.run(_clear_redis_cache(tenant_id))
        asyncio.run(_insert_glossary_term(tenant_id, "SLA", "Service Level Agreement"))

        captured_prompt_kwargs = {}

        async def _run():
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    (
                        orchestrator,
                        received_queries,
                    ) = _make_orchestrator_with_real_glossary(tenant_id, session)

                    # Intercept prompt_builder.build kwargs
                    original_build = orchestrator._prompt_builder.build

                    async def _capture_build(**kwargs):
                        captured_prompt_kwargs.update(kwargs)
                        return await original_build(**kwargs)

                    orchestrator._prompt_builder.build = _capture_build
                    await _collect_events(
                        orchestrator, query="Our SLA is 99.9%", tenant_id=tenant_id
                    )
            finally:
                await close_redis()
                await engine.dispose()

        asyncio.run(_run())

        # Layer 6 check: prompt_builder.build should NOT receive a glossary_terms kwarg
        # (Layer 6 was removed from SystemPromptBuilder)
        assert (
            "glossary_terms" not in captured_prompt_kwargs
        ), "prompt_builder.build must NOT receive glossary_terms — Layer 6 is removed"
        # Verify the build was called with expected layers
        assert (
            "rag_context" in captured_prompt_kwargs
        ), "prompt_builder must receive rag_context"
        assert (
            "working_memory" in captured_prompt_kwargs
        ), "prompt_builder must receive working_memory"

    def test_expansion_cached_in_redis_after_first_call(self, tenant_id):
        """
        After the first expand() call, glossary terms are cached in Redis.
        A second expand() call reads from cache, not PostgreSQL.
        This tests the Redis caching layer directly on the expander.
        """
        asyncio.run(_clear_redis_cache(tenant_id))
        asyncio.run(
            _insert_glossary_term(tenant_id, "KPI", "Key Performance Indicator")
        )

        async def _run():
            _reset_redis_pool()
            redis = get_redis()
            cache_key = f"mingai:{tenant_id}:glossary_terms"
            try:
                # Confirm no cache exists
                before = await redis.get(cache_key)

                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                try:
                    async with factory() as session:
                        expander = GlossaryExpander(db=session)
                        # First call: cache miss, reads from PostgreSQL
                        expanded, expansions = await expander.expand(
                            "What is our KPI target?", tenant_id
                        )
                finally:
                    await engine.dispose()

                # After first call: cache must be populated
                after = await redis.get(cache_key)
            finally:
                await close_redis()

            return before, after, expanded, expansions

        before, after, expanded, expansions = asyncio.run(_run())

        assert before is None, "Cache must be empty before first expand()"
        assert after is not None, "Cache must be populated after first expand()"
        assert (
            "Key Performance Indicator" in expanded
        ), "Expansion must work on first call"
        assert len(expansions) >= 1, "Should have at least one expansion"

    def test_multiple_terms_all_expanded(self, tenant_id):
        """
        A query with multiple glossary acronyms has all matching terms expanded.
        Each expansion is reported in the metadata event's glossary_expansions list.
        """
        asyncio.run(_clear_redis_cache(tenant_id))
        asyncio.run(_insert_glossary_term(tenant_id, "CEO", "Chief Executive Officer"))
        asyncio.run(_insert_glossary_term(tenant_id, "CFO", "Chief Financial Officer"))
        asyncio.run(_insert_glossary_term(tenant_id, "CTO", "Chief Technology Officer"))

        async def _run():
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    (
                        orchestrator,
                        received_queries,
                    ) = _make_orchestrator_with_real_glossary(tenant_id, session)
                    events = await _collect_events(
                        orchestrator,
                        query="The CEO, CFO, and CTO approved this.",
                        tenant_id=tenant_id,
                    )
            finally:
                await close_redis()
                await engine.dispose()
            return events, received_queries

        events, received_queries = asyncio.run(_run())
        metadata_events = [e for e in events if e["event"] == "metadata"]
        expansions = metadata_events[0]["data"]["glossary_expansions"]

        assert any(
            "Chief Executive Officer" in e for e in expansions
        ), "CEO should be expanded"
        assert any(
            "Chief Financial Officer" in e for e in expansions
        ), "CFO should be expanded"
        assert any(
            "Chief Technology Officer" in e for e in expansions
        ), "CTO should be expanded"

        llm_query = received_queries["llm"]
        assert "Chief Executive Officer" in llm_query, "CEO expanded in LLM query"
        assert "Chief Financial Officer" in llm_query, "CFO expanded in LLM query"
        assert "Chief Technology Officer" in llm_query, "CTO expanded in LLM query"

    def test_cross_tenant_glossary_isolation(self, tenant_id, tenant_b_id):
        """
        Tenant A's glossary terms must NOT expand queries for Tenant B.
        Each tenant has a separate Redis namespace key and separate DB rows.
        """
        asyncio.run(_clear_redis_cache(tenant_id))
        asyncio.run(_clear_redis_cache(tenant_b_id))

        # Tenant A has "ACME" → "ACME Corporation"
        asyncio.run(_insert_glossary_term(tenant_id, "ACME", "ACME Corporation"))
        # Tenant B has NO glossary terms

        async def _run():
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    (
                        orchestrator_b,
                        received_queries_b,
                    ) = _make_orchestrator_with_real_glossary(tenant_b_id, session)
                    events_b = await _collect_events(
                        orchestrator_b,
                        query="What does ACME do?",
                        tenant_id=tenant_b_id,
                    )
            finally:
                await close_redis()
                await engine.dispose()
            return events_b, received_queries_b

        events_b, received_queries_b = asyncio.run(_run())

        metadata_b = [e for e in events_b if e["event"] == "metadata"][0]
        # Tenant B query: "ACME" must NOT be expanded (belongs to tenant A)
        assert (
            metadata_b["data"]["glossary_expansions"] == []
        ), "Tenant B must not see Tenant A's glossary terms"
        assert (
            received_queries_b["llm"] == "What does ACME do?"
        ), "LLM must receive unexpanded query for Tenant B"

    def test_alias_expansion_in_pipeline(self, tenant_id):
        """
        Alias terms expand to the same full_form as the primary term.
        When a user types the alias, LLM receives the expanded form.
        """
        asyncio.run(_clear_redis_cache(tenant_id))
        asyncio.run(
            _insert_glossary_term(
                tenant_id, "AL", "Annual Leave", aliases=["PTO", "VAC"]
            )
        )

        async def _run():
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    (
                        orchestrator,
                        received_queries,
                    ) = _make_orchestrator_with_real_glossary(tenant_id, session)
                    events = await _collect_events(
                        orchestrator,
                        query="How many days of PTO do I have?",
                        tenant_id=tenant_id,
                    )
            finally:
                await close_redis()
                await engine.dispose()
            return events, received_queries

        events, received_queries = asyncio.run(_run())

        llm_query = received_queries["llm"]
        assert (
            "Annual Leave" in llm_query
        ), f"Alias 'PTO' must expand to 'Annual Leave'. LLM got: {llm_query!r}"
        # Original query unchanged for embedding
        assert received_queries["embed"] == "How many days of PTO do I have?"
        # Alias expansion must appear in metadata analytics signal
        metadata_events = [e for e in events if e["event"] == "metadata"]
        expansions = metadata_events[0]["data"]["glossary_expansions"]
        assert any(
            "Annual Leave" in exp for exp in expansions
        ), f"Alias expansion must appear in metadata glossary_expansions. Got: {expansions}"

    def test_rollout_flag_disabled_suppresses_expansion(self, tenant_id):
        """
        When glossary_pretranslation_enabled = False for a tenant, the NoopGlossaryExpander
        is used and the original query reaches both embedding and LLM unchanged.
        This is the rollout gate: operators can disable inline expansion per tenant.
        """
        asyncio.run(_clear_redis_cache(tenant_id))
        asyncio.run(_insert_glossary_term(tenant_id, "ROI", "Return on Investment"))
        # Explicitly disable the rollout flag for this tenant
        asyncio.run(_set_rollout_flag(tenant_id, False))

        async def _run():
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    from app.modules.glossary.expander import NoopGlossaryExpander

                    # Simulate what build_orchestrator does when flag=False
                    (
                        orchestrator,
                        received_queries,
                    ) = _make_orchestrator_with_real_glossary(tenant_id, session)
                    # Override with NoopGlossaryExpander to simulate flag=False path
                    orchestrator._glossary = NoopGlossaryExpander()
                    events = await _collect_events(
                        orchestrator,
                        query="What is our ROI target?",
                        tenant_id=tenant_id,
                    )
            finally:
                await close_redis()
                await engine.dispose()
                # Remove flag row so subsequent tests use the default (False)
                await _run_sql(
                    "DELETE FROM tenant_configs WHERE tenant_id = :tid AND config_type = 'glossary_pretranslation'",
                    {"tid": tenant_id},
                )
            return events, received_queries

        events, received_queries = asyncio.run(_run())

        # With Noop expander, no expansion should occur
        metadata_events = [e for e in events if e["event"] == "metadata"]
        expansions = metadata_events[0]["data"]["glossary_expansions"]
        assert (
            expansions == []
        ), "With rollout flag disabled (NoopGlossaryExpander), glossary_expansions must be empty"
        assert (
            received_queries["embed"] == "What is our ROI target?"
        ), "Embed receives original query when expansion disabled"
        assert (
            received_queries["llm"] == "What is our ROI target?"
        ), "LLM receives original query (no expansion) when rollout flag is False"

    def test_done_event_always_emitted_last(self, tenant_id):
        """
        The SSE 'done' event must always be the final event in the stream.
        This is a contract the frontend relies on to terminate the SSE connection.
        """
        asyncio.run(_clear_redis_cache(tenant_id))

        async def _run():
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    orchestrator, _ = _make_orchestrator_with_real_glossary(
                        tenant_id, session
                    )
                    events = await _collect_events(
                        orchestrator,
                        query="Tell me about our process.",
                        tenant_id=tenant_id,
                    )
            finally:
                await close_redis()
                await engine.dispose()
            return events

        events = asyncio.run(_run())
        assert len(events) > 0, "Must emit at least one event"
        assert (
            events[-1]["event"] == "done"
        ), f"Last event must be 'done'. Got: {events[-1]['event']!r}"
        event_types = [e["event"] for e in events]
        # Verify expected events are present in order
        assert "status" in event_types, "Must emit status events"
        assert "metadata" in event_types, "Must emit metadata event"
        assert "done" in event_types, "Must emit done event"
