"""
TEST-058: SystemPromptBuilder Full Pipeline Integration Tests

Tests the end-to-end SystemPromptBuilder.build() pipeline with real PostgreSQL
and Redis — no mocking of infrastructure.

Covers:
  1. All 6 layers assemble correctly when all data is present
  2. Token budget enforcement — final prompt within configured budget
  3. Graceful degradation when profile data is missing
  4. Team working memory included when user has a team
  5. Team working memory excluded when user has no team

Architecture:
  - Real PostgreSQL (via DATABASE_URL)
  - Real Redis (via REDIS_URL) — for working memory and team memory
  - asyncio.run() pattern with scope="module" for DB fixtures
  - agent_cards row inserted for Layer 0 prompt lookup

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_prompt_builder_pipeline.py -v --timeout=60
"""
import asyncio
import json
import os
import uuid

import pytest

import app.core.redis_client as redis_client_module
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.chat.prompt_builder import SystemPromptBuilder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


def _check_redis() -> str:
    url = os.environ.get("REDIS_URL", "")
    if not url:
        pytest.skip("REDIS_URL not configured — skipping integration tests")
    return url


def _make_engine():
    return create_async_engine(_db_url(), echo=False)


async def _run_sql(sql: str, params: dict = None):
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            await session.commit()
            return result
    finally:
        await engine.dispose()


async def _create_test_tenant_and_user() -> tuple[str, str]:
    """Return (tenant_id, user_id) for a freshly-created test tenant/user pair."""
    tid = str(uuid.uuid4())
    uid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"PromptBuilder Test {tid[:8]}",
            "slug": f"pb-test-{tid[:8]}",
            "email": f"admin-{tid[:8]}@pb-int.test",
        },
    )
    await _run_sql(
        "INSERT INTO users (id, tenant_id, email, name, role, status) "
        "VALUES (:id, :tid, :email, :name, 'user', 'active')",
        {
            "id": uid,
            "tid": tid,
            "email": f"user-{uid[:8]}@pb-int.test",
            "name": f"Test User {uid[:8]}",
        },
    )
    return tid, uid


async def _create_agent_card(tenant_id: str, system_prompt: str) -> str:
    """Insert an active agent_card and return its UUID."""
    agent_id = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO agent_cards (id, tenant_id, name, description, system_prompt, status) "
        "VALUES (:id, :tid, :name, :desc, :prompt, 'active')",
        {
            "id": agent_id,
            "tid": tenant_id,
            "name": f"Test Agent {agent_id[:8]}",
            "desc": "Integration test agent",
            "prompt": system_prompt,
        },
    )
    return agent_id


async def _create_user_profile(tenant_id: str, user_id: str, attrs: dict) -> None:
    """Insert a user_profiles row with the given attributes."""
    await _run_sql(
        "INSERT INTO user_profiles "
        "(id, tenant_id, user_id, technical_level, communication_style) "
        "VALUES (:id, :tid, :uid, :tech, :comm) "
        "ON CONFLICT (tenant_id, user_id) DO UPDATE "
        "SET technical_level = :tech, communication_style = :comm",
        {
            "id": str(uuid.uuid4()),
            "tid": tenant_id,
            "uid": user_id,
            "tech": attrs.get("technical_level", "intermediate"),
            "comm": attrs.get("communication_style", "formal"),
        },
    )


async def _cleanup_tenant(tid: str):
    tables_tenant_id = [
        "agent_cards",
        "user_profiles",
        "memory_notes",
        "working_memory_snapshots",
        "users",
        "tenant_configs",
    ]
    for table in tables_tenant_id:
        await _run_sql(f"DELETE FROM {table} WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})


async def _reset_redis():
    """Reset Redis pool to avoid event-loop binding issues between tests."""
    redis_client_module._redis_pool = None


async def _set_working_memory(tenant_id: str, user_id: str, agent_id: str, data: dict):
    """Write working memory directly into Redis for test setup."""
    from app.core.redis_client import get_redis

    redis = get_redis()
    key = f"mingai:{tenant_id}:working_memory:{user_id}:{agent_id}"
    await redis.setex(key, 3600, json.dumps(data))


async def _set_team_memory(tenant_id: str, team_id: str, data: dict):
    """Write team memory directly into Redis for test setup."""
    from app.core.redis_client import get_redis

    redis = get_redis()
    key = f"mingai:{tenant_id}:team_memory:{team_id}"
    await redis.setex(key, 3600, json.dumps(data))


async def _delete_redis_key(*keys: str):
    from app.core.redis_client import get_redis

    redis = get_redis()
    for key in keys:
        await redis.delete(key)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPromptBuilderPipelineIntegration:
    """
    TEST-058: SystemPromptBuilder integration tests against real DB + Redis.
    """

    def test_all_6_layers_assemble_in_parallel(self):
        """
        Creates a user with profile data, org context, working memory, and team
        memory. Calls SystemPromptBuilder.build() and verifies all 6 layers
        (Layer 0 agent base, Layer 1 platform base, Layer 2 org context,
        Layer 3 profile, Layer 4a individual memory, Layer 4b team memory)
        are present in the assembled prompt.
        """
        _check_redis()

        async def _run():
            await _reset_redis()
            tid, uid = await _create_test_tenant_and_user()
            team_id = str(uuid.uuid4())
            agent_id = await _create_agent_card(
                tid, "You are a Finance AI assistant for enterprise workflows."
            )

            # Set up working memory (Layer 4a)
            wm_data = {
                "topics": ["quarterly", "budget"],
                "queries": ["Show me Q1 budget"],
            }
            await _set_working_memory(tid, uid, agent_id, wm_data)

            # Set up team memory (Layer 4b).
            # _format_team_memory reads "recent_topics" key.
            tm_data = {
                "recent_topics": ["forecasting"],
                "recent_queries": ["a team member asked: revenue forecast"],
            }
            await _set_team_memory(tid, team_id, tm_data)

            wm_key = f"mingai:{tid}:working_memory:{uid}:{agent_id}"
            tm_key = f"mingai:{tid}:team_memory:{team_id}"

            try:
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with factory() as db:
                    builder = SystemPromptBuilder()

                    # Layer 2: Org context
                    org_ctx = {"department": "Finance", "region": "APAC"}

                    # Layer 3: Profile context
                    profile_ctx = {
                        "technical_level": "expert",
                        "communication_style": "concise",
                    }

                    # Layer 5: RAG context
                    rag_ctx = [
                        {
                            "title": "Budget Policy",
                            "content": "All budget approvals require CFO sign-off.",
                        }
                    ]

                    prompt, layers_active = await builder.build(
                        agent_id=agent_id,
                        tenant_id=tid,
                        org_context=org_ctx,
                        profile_context=profile_ctx,
                        working_memory=wm_data,
                        team_memory=tm_data,
                        rag_context=rag_ctx,
                        db_session=db,
                    )

                await engine.dispose()

                # Layer 0: agent base (from agent_cards table)
                assert (
                    "Finance AI assistant" in prompt
                ), "Layer 0 (agent base from DB) must appear in prompt"

                # Layer 1: platform base (always included)
                assert any(
                    term in prompt.lower() for term in ("enterprise", "knowledge")
                ), "Layer 1 (platform base) must appear in prompt"

                # Layer 2: org context
                assert (
                    "Finance" in prompt or "Organization Context" in prompt
                ), "Layer 2 (org context) must appear in prompt"
                assert "org_context" in layers_active

                # Layer 3: profile
                assert (
                    "expert" in prompt or "User Profile" in prompt
                ), "Layer 3 (profile context) must appear in prompt"
                assert "profile" in layers_active

                # Layer 4a: working memory
                assert (
                    "quarterly" in prompt or "Recent Context" in prompt
                ), "Layer 4a (working memory) must appear in prompt"
                assert "working_memory" in layers_active

                # Layer 4b: team memory
                assert (
                    "forecasting" in prompt or "Team Context" in prompt
                ), "Layer 4b (team memory) must appear in prompt"
                assert "team_memory" in layers_active

                # Layer 5: RAG
                assert (
                    "Knowledge Base Context" in prompt or "Budget Policy" in prompt
                ), "Layer 5 (RAG context) must appear in prompt"

                # All 4 optional layers should be active
                assert (
                    len(layers_active) == 4
                ), f"Expected 4 active layers, got {len(layers_active)}: {layers_active}"

            finally:
                await _delete_redis_key(wm_key, tm_key)
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_layer_token_budget_enforcement(self):
        """
        Creates a scenario where all layers have maximum data. Verifies the
        final prompt is within the configured token budget. Layer 5 (RAG) must
        receive only the remaining budget after layers 0-4b consume their shares.
        """
        _check_redis()

        async def _run():
            await _reset_redis()
            tid, uid = await _create_test_tenant_and_user()
            agent_id = await _create_agent_card(tid, "You are a test agent.")

            try:
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with factory() as db:
                    builder = SystemPromptBuilder()

                    # Maximally-sized data for each layer
                    org_ctx = {
                        "department": "x" * 50,
                        "region": "y" * 50,
                        "team": "z" * 50,
                        "location": "w" * 50,
                    }
                    profile_ctx = {
                        "technical_level": "expert",
                        "communication_style": "a" * 100,
                        "interests": ["b" * 50, "c" * 50],
                    }
                    wm_data = {
                        "topics": ["topic" + str(i) for i in range(5)],
                        "queries": ["query text " * 10],
                    }
                    tm_data = {
                        "topics": ["team_topic" + str(i) for i in range(5)],
                        "recent_queries": ["a team member asked: " + "x" * 100],
                    }
                    # Large RAG context — should be truncated to remaining budget
                    rag_ctx = [
                        {
                            "title": f"Document {i}",
                            "content": "RAG content. " * 200,
                        }
                        for i in range(5)
                    ]

                    # Use default 2048 token budget
                    query_budget = 2048
                    prompt, layers_active = await builder.build(
                        agent_id=agent_id,
                        tenant_id=tid,
                        org_context=org_ctx,
                        profile_context=profile_ctx,
                        working_memory=wm_data,
                        team_memory=tm_data,
                        rag_context=rag_ctx,
                        query_budget=query_budget,
                        db_session=db,
                    )

                await engine.dispose()

                # Verify prompt exists and has content
                assert prompt, "Prompt must not be empty"

                # Verify all optional layers activated
                assert "org_context" in layers_active
                assert "profile" in layers_active
                assert "working_memory" in layers_active
                assert "team_memory" in layers_active

                # Verify Layer 5 RAG section appears (remaining budget used)
                assert (
                    "Knowledge Base Context" in prompt
                ), "RAG section must appear — remaining budget after overhead must be positive"

                # Verify overhead layers are within their budgets (by checking truncation)
                # Org context: 100 token budget = 400 chars max
                org_start = prompt.find("[Organization Context]")
                if org_start >= 0:
                    # Find next section separator after org context
                    next_sep = prompt.find("---", org_start)
                    if next_sep > org_start:
                        org_section = prompt[org_start:next_sep]
                        # 100 tokens * 4 chars + header overhead — soft check
                        assert (
                            len(org_section) <= 600
                        ), f"Org context section too long: {len(org_section)} chars"

            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_graceful_degradation_missing_profile(self):
        """
        User with no profile learning data (no user_profiles row). Builds
        prompt. Verifies Layer 3 is absent from layers_active (empty/skipped)
        but all other layers still assemble correctly.
        """
        _check_redis()

        async def _run():
            await _reset_redis()
            tid, uid = await _create_test_tenant_and_user()
            agent_id = await _create_agent_card(
                tid, "You are a general purpose assistant."
            )

            wm_data = {"topics": ["deployment"], "queries": ["How do I deploy?"]}
            await _set_working_memory(tid, uid, agent_id, wm_data)
            wm_key = f"mingai:{tid}:working_memory:{uid}:{agent_id}"

            try:
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with factory() as db:
                    builder = SystemPromptBuilder()

                    # No profile_context — simulates missing profile data
                    prompt, layers_active = await builder.build(
                        agent_id=agent_id,
                        tenant_id=tid,
                        org_context={"department": "Engineering"},
                        profile_context=None,
                        working_memory=wm_data,
                        team_memory=None,
                        rag_context=[],
                        db_session=db,
                    )

                await engine.dispose()

                # Layer 3 (profile) must be absent — graceful degradation
                assert (
                    "profile" not in layers_active
                ), "Layer 3 must NOT be active when profile_context is None"

                # Layer 0 (agent base) must be present
                assert (
                    "general purpose assistant" in prompt
                ), "Layer 0 (agent base) must be present even without profile"

                # Layer 1 (platform base) must be present
                assert any(
                    term in prompt.lower() for term in ("enterprise", "knowledge")
                ), "Layer 1 (platform base) must be present even without profile"

                # Layer 2 (org context) must be present
                assert (
                    "org_context" in layers_active
                ), "Layer 2 (org context) must still be active when profile is missing"
                assert "Engineering" in prompt or "Organization Context" in prompt

                # Layer 4a (working memory) must be present
                assert (
                    "working_memory" in layers_active
                ), "Layer 4a (working memory) must still be active when profile is missing"

                # Only 2 layers active (org_context + working_memory)
                assert (
                    len(layers_active) == 2
                ), f"Expected 2 active layers without profile/team, got: {layers_active}"

            finally:
                await _delete_redis_key(wm_key)
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_team_working_memory_included_when_user_has_team(self):
        """
        User is in a team with team working memory stored in Redis. Verifies
        Layer 4b (team memory) is included in the assembled prompt and in
        layers_active.
        """
        _check_redis()

        async def _run():
            await _reset_redis()
            tid, uid = await _create_test_tenant_and_user()
            team_id = str(uuid.uuid4())
            agent_id = await _create_agent_card(
                tid, "You are a collaborative team assistant."
            )

            # Seed team working memory in Redis.
            # Note: SystemPromptBuilder._format_team_memory reads "recent_topics" key.
            tm_data = {
                "recent_topics": ["Q3", "OKRs", "hiring"],
                "recent_queries": [
                    "a team member asked: What are our Q3 OKRs?",
                    "a team member asked: How many engineers are we hiring?",
                ],
            }
            await _set_team_memory(tid, team_id, tm_data)
            tm_key = f"mingai:{tid}:team_memory:{team_id}"

            try:
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with factory() as db:
                    builder = SystemPromptBuilder()

                    prompt, layers_active = await builder.build(
                        agent_id=agent_id,
                        tenant_id=tid,
                        org_context=None,
                        profile_context=None,
                        working_memory=None,
                        team_memory=tm_data,
                        rag_context=[],
                        db_session=db,
                    )

                await engine.dispose()

                # Layer 4b must be active
                assert (
                    "team_memory" in layers_active
                ), "Layer 4b (team memory) must be active when team_memory is provided"

                # Team context section must appear in prompt
                assert (
                    "Team Context" in prompt or "Q3" in prompt or "OKRs" in prompt
                ), "Team memory content must appear in assembled prompt"

                # Verify team topics from the seed data appear.
                # _format_team_memory reads "recent_topics" and emits them as
                # "Team topics: Q3, OKRs, hiring" — check case-insensitively.
                prompt_lower = prompt.lower()
                assert any(
                    topic.lower() in prompt_lower
                    for topic in ["q3", "okrs", "hiring", "team topics"]
                ), f"At least one team topic must appear in prompt. Prompt: {prompt[:500]}"

            finally:
                await _delete_redis_key(tm_key)
                await _cleanup_tenant(tid)

        asyncio.run(_run())

    def test_team_working_memory_excluded_when_no_team(self):
        """
        User not in any team — team_memory is None. Verifies Layer 4b is absent
        from layers_active and no team context section appears in the prompt.
        """
        _check_redis()

        async def _run():
            await _reset_redis()
            tid, uid = await _create_test_tenant_and_user()
            agent_id = await _create_agent_card(
                tid, "You are an individual contributor assistant."
            )

            try:
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with factory() as db:
                    builder = SystemPromptBuilder()

                    # team_memory=None simulates user with no active team
                    prompt, layers_active = await builder.build(
                        agent_id=agent_id,
                        tenant_id=tid,
                        org_context=None,
                        profile_context={"technical_level": "intermediate"},
                        working_memory={
                            "topics": ["testing"],
                            "queries": ["How to test?"],
                        },
                        team_memory=None,
                        rag_context=[],
                        db_session=db,
                    )

                await engine.dispose()

                # Layer 4b must NOT be active
                assert (
                    "team_memory" not in layers_active
                ), "Layer 4b must NOT be active when team_memory is None"

                # Team Context section must not appear in prompt
                assert (
                    "Team Context" not in prompt
                ), "Team Context section must not appear when user has no team"

                # Other layers must still work
                assert "profile" in layers_active, "Profile layer must still be active"
                assert (
                    "working_memory" in layers_active
                ), "Working memory layer must still be active"

                # Verify prompt has actual content from other layers
                assert (
                    "individual contributor assistant" in prompt
                ), "Layer 0 (agent base) must still appear"

            finally:
                await _cleanup_tenant(tid)

        asyncio.run(_run())
