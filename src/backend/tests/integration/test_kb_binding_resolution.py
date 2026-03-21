"""
ATA-014: Integration tests for KB binding resolution.

Tests the full KB binding pipeline:
  1. _get_agent_prompt() extracts kb_ids from agent_cards.capabilities
  2. _get_agent_prompt() returns empty list when no kb_ids in capabilities
  3. VectorSearchService.search() fans out to each KB index + agent index
  4. Failed KB index is skipped — no exception raised (resilient fan-out)
  5. search() with kb_ids=None searches only the agent index
  6. Merged results are sorted by score descending

Architecture:
  Tests 1-2 require real PostgreSQL (via DATABASE_URL) — they call
  _get_agent_prompt() which queries agent_cards.
  Tests 3-6 mock _search_single_index (the external pgvector call) so they
  can run without a live DB. The mock covers only the network/DB boundary;
  all fan-out, merge, and sort logic in VectorSearchService is exercised
  against the real implementation.

Prerequisites:
    docker-compose up -d  # ensure DB is running for tests 1-2

Run:
    pytest tests/integration/test_kb_binding_resolution.py -v --timeout=60
"""
from __future__ import annotations

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.chat.prompt_builder import SystemPromptBuilder
from app.modules.chat.vector_search import SearchResult, VectorSearchService


# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


# ---------------------------------------------------------------------------
# DB helpers (asyncio.run() pattern — avoids event loop conflicts with
# the session-scoped TestClient in conftest.py)
# ---------------------------------------------------------------------------


def _make_engine():
    return create_async_engine(_db_url(), echo=False)


async def _run_sql(sql: str, params: dict | None = None):
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            await session.commit()
            return result
    finally:
        await engine.dispose()


async def _create_test_tenant() -> str:
    """Insert a test tenant and return its UUID string."""
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'starter', :email, 'active')",
        {
            "id": tid,
            "name": f"KB Bind Test {tid[:8]}",
            "slug": f"kb-bind-{tid[:8]}",
            "email": f"admin-{tid[:8]}@kb-int.test",
        },
    )
    return tid


async def _create_agent_card(
    tenant_id: str,
    system_prompt: str,
    capabilities: dict | None = None,
) -> str:
    """Insert an active agent_card with the given capabilities and return its UUID."""
    agent_id = str(uuid.uuid4())
    import json

    caps_json = json.dumps(capabilities or {})
    await _run_sql(
        "INSERT INTO agent_cards "
        "(id, tenant_id, name, description, system_prompt, capabilities, status) "
        "VALUES (:id, :tid, :name, :desc, :prompt, CAST(:caps AS jsonb), 'active')",
        {
            "id": agent_id,
            "tid": tenant_id,
            "name": f"KB Test Agent {agent_id[:8]}",
            "desc": "KB binding integration test agent",
            "prompt": system_prompt,
            "caps": caps_json,
        },
    )
    return agent_id


async def _cleanup_tenant(tid: str) -> None:
    tables = ["agent_cards", "users"]
    for table in tables:
        await _run_sql(f"DELETE FROM {table} WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})


# ---------------------------------------------------------------------------
# Tests 1-2: _get_agent_prompt() — require real DB
# ---------------------------------------------------------------------------


class TestGetAgentPromptKbIds:
    """
    ATA-014 Tests 1-2: _get_agent_prompt() correctly extracts kb_ids from
    agent_cards.capabilities, or returns [] when the key is absent.

    These tests use real PostgreSQL — they are skipped when DATABASE_URL is unset.
    """

    def test_returns_kb_ids_from_capabilities(self):
        """
        Agent card has capabilities = {"kb_ids": ["kb-1", "kb-2"]}.
        _get_agent_prompt() must return kb_ids == ["kb-1", "kb-2"].
        """
        _db_url()  # skip guard

        async def _run():
            tid = await _create_test_tenant()
            try:
                agent_id = await _create_agent_card(
                    tid,
                    system_prompt="You are a test agent with KB bindings.",
                    capabilities={"kb_ids": ["kb-1", "kb-2"]},
                )

                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with factory() as db:
                    builder = SystemPromptBuilder()
                    prompt, capabilities, kb_ids = await builder._get_agent_prompt(
                        agent_id, tid, db
                    )
                await engine.dispose()

                assert kb_ids == [
                    "kb-1",
                    "kb-2",
                ], f"Expected ['kb-1', 'kb-2'], got {kb_ids!r}"
                assert "test agent with KB bindings" in prompt
                assert isinstance(capabilities, dict)
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_returns_empty_list_when_no_kb_ids_in_capabilities(self):
        """
        Agent card has capabilities = {} (no kb_ids key).
        _get_agent_prompt() must return kb_ids == [].
        """
        _db_url()  # skip guard

        async def _run():
            tid = await _create_test_tenant()
            try:
                agent_id = await _create_agent_card(
                    tid,
                    system_prompt="You are a test agent without KB bindings.",
                    capabilities={},
                )

                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with factory() as db:
                    builder = SystemPromptBuilder()
                    prompt, capabilities, kb_ids = await builder._get_agent_prompt(
                        agent_id, tid, db
                    )
                await engine.dispose()

                assert kb_ids == [], f"Expected [], got {kb_ids!r}"
                assert "test agent without KB bindings" in prompt
            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Tests 3-6: VectorSearchService fan-out — mock _search_single_index
# These tests do NOT require a live DB because the pgvector call is mocked.
# The fan-out, merge, and sort logic in VectorSearchService.search() is
# exercised against the real implementation.
# ---------------------------------------------------------------------------


DUMMY_VECTOR = [0.1] * 1536
TENANT_ID = "tenant-test-" + str(uuid.uuid4())[:8]
AGENT_ID = str(uuid.uuid4())
AGENT_INDEX = f"{TENANT_ID}-{AGENT_ID}"


def _make_result(score: float, title: str = "doc") -> SearchResult:
    return SearchResult(
        title=title,
        content=f"content for {title}",
        score=score,
        source_url=None,
        document_id=f"doc-{title}",
    )


class TestVectorSearchFanOut:
    """
    ATA-014 Tests 3-6: VectorSearchService.search() fan-out logic.

    _search_single_index is mocked at the pgvector boundary to avoid requiring
    a live database for these structural/logic tests.
    """

    def test_search_with_kb_ids_calls_search_single_index_for_each_index(self):
        """
        search(kb_ids=["kb-1", "kb-2"]) must call _search_single_index exactly 3
        times: once for the agent's own index and once for each KB index.
        """

        async def _run():
            service = VectorSearchService()
            mock = AsyncMock(return_value=[])

            with patch.object(service, "_search_single_index", mock):
                await service.search(
                    query_vector=DUMMY_VECTOR,
                    tenant_id=TENANT_ID,
                    agent_id=AGENT_ID,
                    top_k=5,
                    kb_ids=["kb-1", "kb-2"],
                )

            assert mock.call_count == 3, (
                f"Expected _search_single_index called 3 times "
                f"(agent + kb-1 + kb-2), got {mock.call_count}"
            )

            # Verify all 3 index IDs were searched
            called_index_ids = {
                call.kwargs.get("index_id") or call.args[0]
                for call in mock.call_args_list
            }
            assert AGENT_INDEX in called_index_ids, (
                f"Agent index {AGENT_INDEX!r} must be searched; got {called_index_ids}"
            )
            assert "kb-1" in called_index_ids, "kb-1 must be searched"
            assert "kb-2" in called_index_ids, "kb-2 must be searched"

        asyncio.run(_run())

    def test_search_with_failed_kb_index_returns_results_from_successful_indexes(self):
        """
        If _search_single_index raises for kb-1 but succeeds for the agent index
        and kb-2, the call must not propagate the exception. Results from
        successful indexes are returned; results from the failed index are absent.
        """
        agent_result = _make_result(0.9, title="agent-doc")
        kb2_result = _make_result(0.7, title="kb2-doc")

        async def _side_effect(index_id: str, **kwargs) -> list[SearchResult]:
            if index_id == "kb-1":
                raise RuntimeError("simulated kb-1 index failure")
            if index_id == AGENT_INDEX:
                return [agent_result]
            if index_id == "kb-2":
                return [kb2_result]
            return []

        async def _run():
            service = VectorSearchService()

            with patch.object(
                service,
                "_search_single_index",
                AsyncMock(side_effect=_side_effect),
            ):
                results = await service.search(
                    query_vector=DUMMY_VECTOR,
                    tenant_id=TENANT_ID,
                    agent_id=AGENT_ID,
                    top_k=10,
                    kb_ids=["kb-1", "kb-2"],
                )

            # No exception raised — resilient fan-out
            assert isinstance(results, list), "search() must return a list"

            result_titles = {r.title for r in results}
            assert "agent-doc" in result_titles, "Agent index result must be present"
            assert "kb2-doc" in result_titles, "kb-2 result must be present"
            # kb-1 failed — its results cannot appear (none were produced)
            # The test verifies no crash and both successful indexes contributed
            assert len(results) == 2, (
                f"Expected 2 results (agent + kb-2), got {len(results)}"
            )

        asyncio.run(_run())

    def test_search_with_kb_ids_none_searches_only_agent_index(self):
        """
        search(kb_ids=None) must call _search_single_index exactly once, with
        the agent's own index (fast path — no gather overhead).
        """

        async def _run():
            service = VectorSearchService()
            mock = AsyncMock(return_value=[_make_result(0.8)])

            with patch.object(service, "_search_single_index", mock):
                results = await service.search(
                    query_vector=DUMMY_VECTOR,
                    tenant_id=TENANT_ID,
                    agent_id=AGENT_ID,
                    top_k=5,
                    kb_ids=None,
                )

            assert mock.call_count == 1, (
                f"Expected _search_single_index called once, got {mock.call_count}"
            )
            called_index_id = (
                mock.call_args.kwargs.get("index_id") or mock.call_args.args[0]
            )
            assert called_index_id == AGENT_INDEX, (
                f"Must search agent index {AGENT_INDEX!r}, got {called_index_id!r}"
            )
            assert len(results) == 1

        asyncio.run(_run())

    def test_search_merges_and_sorts_results_by_score_descending(self):
        """
        Agent index returns scores [0.9, 0.7]; KB index returns score [0.85].
        After merge and sort, order must be: 0.9, 0.85, 0.7.
        """
        agent_results = [
            _make_result(0.9, title="agent-high"),
            _make_result(0.7, title="agent-low"),
        ]
        kb_results = [
            _make_result(0.85, title="kb-mid"),
        ]

        async def _side_effect(index_id: str, **kwargs) -> list[SearchResult]:
            if index_id == AGENT_INDEX:
                return list(agent_results)
            if index_id == "kb-alpha":
                return list(kb_results)
            return []

        async def _run():
            service = VectorSearchService()

            with patch.object(
                service,
                "_search_single_index",
                AsyncMock(side_effect=_side_effect),
            ):
                results = await service.search(
                    query_vector=DUMMY_VECTOR,
                    tenant_id=TENANT_ID,
                    agent_id=AGENT_ID,
                    top_k=10,
                    kb_ids=["kb-alpha"],
                )

            assert len(results) == 3, f"Expected 3 merged results, got {len(results)}"

            scores = [r.score for r in results]
            assert scores == sorted(scores, reverse=True), (
                f"Results must be sorted by score descending, got scores: {scores}"
            )
            assert scores[0] == 0.9, f"Highest score must be 0.9, got {scores[0]}"
            assert scores[1] == 0.85, f"Second score must be 0.85, got {scores[1]}"
            assert scores[2] == 0.7, f"Third score must be 0.7, got {scores[2]}"

        asyncio.run(_run())
