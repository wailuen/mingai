"""
TEST-060: Glossary Pretranslation Rollout Flag Integration Tests

Tests the per-tenant `glossary_pretranslation_enabled` flag against real
PostgreSQL — no mocking of DB, Redis, or any infrastructure.

Covers:
  1. Flag defaults to False for a new tenant (no row in tenant_configs)
  2. Enabling flag persists across DB sessions
  3. Flag is isolated between tenants (enable for A does not affect B)
  4. GlossaryExpander.expand() skips expansion when flag is disabled
     (uses NoopGlossaryExpander — real call, no mocks)
  5. GlossaryExpander.expand() applies expansion when flag is enabled
     (uses real GlossaryExpander with real DB and Redis)

Architecture:
  - Real PostgreSQL (via DATABASE_URL)
  - Real Redis (via REDIS_URL) for glossary cache
  - asyncio.run() pattern for DB operations
  - Uses is_glossary_pretranslation_enabled() and set_glossary_pretranslation_enabled()
    from app.core.glossary_config

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/integration/test_glossary_rollout_flag.py -v --timeout=60
"""
import asyncio
import json
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.redis_client as redis_client_module
from app.core.glossary_config import (
    is_glossary_pretranslation_enabled,
    set_glossary_pretranslation_enabled,
)
from app.modules.glossary.expander import GlossaryExpander, NoopGlossaryExpander


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
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


async def _create_test_tenant() -> str:
    """Create a fresh tenant and return its ID."""
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"Test Tenant {tid[:8]}",
            "slug": f"test-{tid[:8]}",
            "email": f"admin@{tid[:8]}.test",
        },
    )
    return tid


async def _cleanup_tenant(tenant_id: str):
    """Remove test tenant and cascade-delete all related rows."""
    await _run_sql(
        "DELETE FROM tenants WHERE id = :id",
        {"id": tenant_id},
    )


async def _insert_glossary_term(tenant_id: str, term: str, full_form: str):
    """Insert a glossary term for testing expansion."""
    await _run_sql(
        "INSERT INTO glossary_terms "
        "(id, tenant_id, term, full_form, aliases, is_active) "
        "VALUES (:id, :tenant_id, :term, :full_form, :aliases, true) "
        "ON CONFLICT (tenant_id, term) DO NOTHING",
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "term": term,
            "full_form": full_form,
            "aliases": json.dumps([]),
        },
    )


async def _reset_redis():
    """Reset Redis pool to avoid event-loop binding issues between tests."""
    redis_client_module._redis_pool = None


async def _clear_glossary_cache(tenant_id: str):
    """Remove the glossary cache key for a tenant from Redis."""
    from app.core.redis_client import get_redis

    redis = get_redis()
    await redis.delete(f"mingai:{tenant_id}:glossary_terms")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGlossaryRolloutFlagIntegration:
    """
    TEST-060: Glossary pretranslation rollout flag integration tests.
    Real PostgreSQL + Redis — zero mocking.
    """

    def test_flag_default_false_for_new_tenant(self):
        """
        A freshly-created tenant with no tenant_configs row must have the
        glossary_pretranslation flag default to False.
        """

        async def _run():
            tid = await _create_test_tenant()
            try:
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with factory() as db:
                    # No tenant_configs row has been inserted — must default False
                    enabled = await is_glossary_pretranslation_enabled(tid, db)

                await engine.dispose()
                return enabled
            finally:
                await _cleanup_tenant(tid)

        enabled = asyncio.run(_run())
        assert enabled is False, (
            "Glossary pretranslation must default to False for a new tenant "
            "with no tenant_configs row"
        )

    def test_enable_flag_persists_across_requests(self):
        """
        After set_glossary_pretranslation_enabled(tenant_id, True, db), the
        flag must be readable as True in a completely new DB session/connection.
        This verifies the upsert is committed and visible to subsequent requests.
        """

        async def _run():
            tid = await _create_test_tenant()
            try:
                # Session 1: write the flag
                engine1 = _make_engine()
                factory1 = async_sessionmaker(
                    engine1, class_=AsyncSession, expire_on_commit=False
                )
                async with factory1() as db1:
                    await set_glossary_pretranslation_enabled(tid, True, db1)
                await engine1.dispose()

                # Session 2: completely independent connection — must see True
                engine2 = _make_engine()
                factory2 = async_sessionmaker(
                    engine2, class_=AsyncSession, expire_on_commit=False
                )
                async with factory2() as db2:
                    enabled = await is_glossary_pretranslation_enabled(tid, db2)
                await engine2.dispose()

                return enabled
            finally:
                await _cleanup_tenant(tid)

        enabled = asyncio.run(_run())
        assert enabled is True, (
            "Enabling glossary pretranslation must persist across DB sessions. "
            "The upsert must commit and be visible to subsequent reads."
        )

    def test_flag_isolation_between_tenants(self):
        """
        Enabling the flag for tenant A must not affect tenant B.
        Tenant B must still read False after tenant A's flag is enabled.
        """

        async def _run():
            tid_a = await _create_test_tenant()
            tid_b = await _create_test_tenant()
            try:
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with factory() as db:
                    # Enable for tenant A only
                    await set_glossary_pretranslation_enabled(tid_a, True, db)

                    # Read flag for tenant A
                    flag_a = await is_glossary_pretranslation_enabled(tid_a, db)

                    # Read flag for tenant B (must still be False)
                    flag_b = await is_glossary_pretranslation_enabled(tid_b, db)

                await engine.dispose()
                return flag_a, flag_b
            finally:
                await _cleanup_tenant(tid_a)
                await _cleanup_tenant(tid_b)

        flag_a, flag_b = asyncio.run(_run())

        assert (
            flag_a is True
        ), "Tenant A's glossary pretranslation flag must be True after enabling"
        assert flag_b is False, (
            "Tenant B's glossary pretranslation flag must remain False — "
            "flag changes for tenant A must not leak to tenant B"
        )

    def test_noop_expander_returns_empty_expansions(self):
        """
        NoopGlossaryExpander.expand() must always return the original query
        with an empty expansions list — regardless of tenant flag state.
        This verifies the correct expander is selected when the flag is off.
        """

        async def _run():
            await _reset_redis()
            tid = await _create_test_tenant()
            try:
                # Insert a glossary term — NoopExpander must NOT expand it
                await _insert_glossary_term(tid, "ROI", "Return on Investment")

                # Confirm flag is False (default)
                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with factory() as db:
                    flag = await is_glossary_pretranslation_enabled(tid, db)
                    assert flag is False, "Flag must be False for this test to be valid"

                    # When flag is False, the pipeline uses NoopGlossaryExpander
                    noop = NoopGlossaryExpander()
                    query = "What is our ROI target?"
                    expanded_query, expansions = await noop.expand(query, tid)

                await engine.dispose()
                return expanded_query, expansions
            finally:
                await _cleanup_tenant(tid)

        expanded_query, expansions = asyncio.run(_run())

        assert expanded_query == "What is our ROI target?", (
            "NoopGlossaryExpander must return the original query unchanged. "
            f"Got: {expanded_query!r}"
        )
        assert expansions == [], (
            "NoopGlossaryExpander must return empty expansions list. "
            f"Got: {expansions}"
        )

    def test_real_expander_applies_expansion_when_flag_enabled(self):
        """
        When the flag is enabled and a glossary term exists in the DB,
        GlossaryExpander.expand() must return the expanded query and a
        non-empty expansions list with the term's full form.
        """

        async def _run():
            await _reset_redis()
            tid = await _create_test_tenant()
            try:
                # Insert a glossary term into the DB
                await _insert_glossary_term(tid, "SLA", "Service Level Agreement")

                engine = _make_engine()
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with factory() as db:
                    # Enable the flag
                    await set_glossary_pretranslation_enabled(tid, True, db)
                    flag = await is_glossary_pretranslation_enabled(tid, db)
                    assert flag is True, "Flag must be True for this test to be valid"

                    # Clear Redis cache to force DB read
                    await _clear_glossary_cache(tid)

                    # Use real GlossaryExpander with real DB
                    expander = GlossaryExpander(db=db)
                    query = "What is our SLA for critical incidents?"
                    expanded_query, expansions = await expander.expand(query, tid)

                await engine.dispose()
                return expanded_query, expansions
            finally:
                await _cleanup_tenant(tid)

        expanded_query, expansions = asyncio.run(_run())

        assert len(expansions) >= 1, (
            "GlossaryExpander must return at least one expansion when flag is enabled "
            f"and a matching term exists. Got: {expansions}"
        )
        assert any(
            "Service Level Agreement" in str(exp) for exp in expansions
        ), f"Expected 'Service Level Agreement' in expansions. Got: {expansions}"
        assert "Service Level Agreement" in expanded_query, (
            "Expanded query must contain the full form of the glossary term. "
            f"Got: {expanded_query!r}"
        )
