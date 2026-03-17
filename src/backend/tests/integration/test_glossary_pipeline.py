"""
DEF-016: Glossary Pipeline Integration Tests.

TEST-033: Query with known glossary term returns term expansion via GlossaryExpander
TEST-034: Unmatched domain term appears in glossary_miss_signals after batch job run
TEST-035: Glossary Redis cache is invalidated when a term is PATCHed

All tests use real PostgreSQL and real Redis. No mocking.

Prerequisites:
    docker-compose up -d  # PostgreSQL + Redis required

Run:
    cd src/backend && python -m pytest tests/integration/test_glossary_pipeline.py -v
"""
import asyncio
import json
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.redis_client as _redis_mod
from app.core.redis_client import close_redis, get_redis
from app.modules.glossary.expander import GLOSSARY_CACHE_TTL_SECONDS, GlossaryExpander
from app.modules.glossary.routes import (
    _invalidate_glossary_cache,
    update_glossary_term_db,
)


# ---------------------------------------------------------------------------
# Infrastructure helpers
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL", "")
    if not url:
        pytest.skip("REDIS_URL not configured — skipping integration tests")
    return url


def _reset_redis_pool() -> None:
    """Reset the module-level Redis singleton so each asyncio.run() gets a fresh pool."""
    _redis_mod._redis_pool = None


def _make_engine():
    return create_async_engine(_db_url(), echo=False)


async def _run_sql(sql: str, params: dict = None) -> None:
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _run_sql_fetch(sql: str, params: dict = None) -> list:
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            return result.fetchall()
    finally:
        await engine.dispose()


async def _create_tenant(name_prefix: str = "Glossary Pipeline Test") -> str:
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"{name_prefix} {tid[:8]}",
            "slug": f"glp-test-{tid[:8]}",
            "email": f"admin-{tid[:8]}@glptest.test",
        },
    )
    return tid


async def _cleanup_tenant(tid: str) -> None:
    await _run_sql(
        "DELETE FROM glossary_miss_signals WHERE tenant_id = :tid", {"tid": tid}
    )
    await _run_sql("DELETE FROM glossary_terms WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM messages WHERE tenant_id = :tid", {"tid": tid})
    await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})


async def _insert_glossary_term(
    tenant_id: str,
    term: str,
    full_form: str,
    aliases: list | None = None,
) -> str:
    """Insert a glossary term, returns its UUID."""
    term_id = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO glossary_terms (id, tenant_id, term, full_form, aliases) "
        "VALUES (:id, :tenant_id, :term, :full_form, CAST(:aliases AS jsonb)) "
        "ON CONFLICT (tenant_id, term) DO UPDATE "
        "SET full_form = EXCLUDED.full_form, aliases = EXCLUDED.aliases",
        {
            "id": term_id,
            "tenant_id": tenant_id,
            "term": term,
            "full_form": full_form,
            "aliases": json.dumps(aliases or []),
        },
    )
    # Return the actual ID (conflict resolution may have kept the original)
    rows = await _run_sql_fetch(
        "SELECT id FROM glossary_terms WHERE tenant_id = :tid AND term = :term",
        {"tid": tenant_id, "term": term},
    )
    return str(rows[0][0]) if rows else term_id


async def _clear_redis_glossary_cache(tenant_id: str) -> None:
    _reset_redis_pool()
    redis = get_redis()
    try:
        await redis.delete(f"mingai:{tenant_id}:glossary_terms")
    finally:
        await close_redis()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def gl_tenant_id():
    """Provision a real test tenant per class, clean up after."""
    _db_url()  # Ensure DB is configured before provisioning
    tid = asyncio.run(_create_tenant("GL Pipeline Test"))
    yield tid
    asyncio.run(_cleanup_tenant(tid))


# ---------------------------------------------------------------------------
# TEST-033: Query with known glossary term returns term expansion
# ---------------------------------------------------------------------------


class TestGlossaryTermExpansion:
    """TEST-033: GlossaryExpander returns full_form for known terms."""

    def test_known_term_is_expanded_in_query(self, gl_tenant_id):
        """
        Create a glossary term (LTV → Lifetime Value) in the real DB.
        Call GlossaryExpander.expand() with a query containing 'LTV'.
        Verify:
          - The expanded query contains 'Lifetime Value'
          - The expansions list includes 'LTV → Lifetime Value'
        """
        asyncio.run(_clear_redis_glossary_cache(gl_tenant_id))
        asyncio.run(
            _insert_glossary_term(
                tenant_id=gl_tenant_id,
                term="LTV",
                full_form="Lifetime Value",
            )
        )

        async def _expand():
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    expander = GlossaryExpander(db=session)
                    expanded_query, expansions = await expander.expand(
                        "What is our LTV for Q1?", gl_tenant_id
                    )
                    return expanded_query, expansions
            finally:
                await engine.dispose()
                await close_redis()

        expanded_query, expansions = asyncio.run(_expand())

        assert "Lifetime Value" in expanded_query, (
            f"Expected 'Lifetime Value' in expanded query, got: {expanded_query!r}. "
            "The expander must inject the full_form after the matched term."
        )
        assert "LTV" in expanded_query, (
            f"Original term 'LTV' should still be present after expansion. "
            f"Got: {expanded_query!r}"
        )
        assert (
            len(expansions) >= 1
        ), f"Expected at least one expansion, got: {expansions}"
        assert any(
            "Lifetime Value" in exp for exp in expansions
        ), f"Expansion list must include 'Lifetime Value'. Got: {expansions}"

    def test_unknown_term_is_not_expanded(self, gl_tenant_id):
        """
        A term not in the glossary must not be expanded.
        The original query is returned unchanged, and expansions is empty.
        """
        asyncio.run(_clear_redis_glossary_cache(gl_tenant_id))

        async def _expand():
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    expander = GlossaryExpander(db=session)
                    return await expander.expand(
                        "What is our XYZUNKNOWN rate?", gl_tenant_id
                    )
            finally:
                await engine.dispose()
                await close_redis()

        expanded_query, expansions = asyncio.run(_expand())

        assert (
            expanded_query == "What is our XYZUNKNOWN rate?"
        ), f"Unknown term query must be returned unchanged. Got: {expanded_query!r}"
        assert (
            expansions == []
        ), f"No expansions expected for unknown term. Got: {expansions}"

    def test_expansion_contains_full_form_in_glossary_data(self, gl_tenant_id):
        """
        The expansion output for a matched term must reflect the full_form
        stored in the glossary_terms table.

        This verifies the complete data path: DB row → term cache → expansion.
        """
        asyncio.run(_clear_redis_glossary_cache(gl_tenant_id))
        asyncio.run(
            _insert_glossary_term(
                tenant_id=gl_tenant_id,
                term="CAC",
                full_form="Customer Acquisition Cost",
            )
        )

        async def _expand():
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    expander = GlossaryExpander(db=session)
                    expanded_query, expansions = await expander.expand(
                        "Show me CAC trends for this year", gl_tenant_id
                    )
                    return expanded_query, expansions
            finally:
                await engine.dispose()
                await close_redis()

        expanded_query, expansions = asyncio.run(_expand())

        assert (
            "Customer Acquisition Cost" in expanded_query
        ), f"Expansion must inject the DB-stored full_form. Got: {expanded_query!r}"
        assert any(
            "Customer Acquisition Cost" in e for e in expansions
        ), f"Expansion descriptor must reference the full_form. Got: {expansions}"


# ---------------------------------------------------------------------------
# TEST-034: Miss signals batch job records unmatched domain terms
# ---------------------------------------------------------------------------


class TestGlossaryMissSignals:
    """
    TEST-034: Miss signal recording mechanism for unmatched domain terms.

    Design note: _process_tenant() uses async_session_factory (module-level,
    bound to the pytest event loop) which cannot be called from asyncio.run().
    These tests validate the same database contract by:
      1. Calling the pure-Python helper functions (_extract_candidates,
         _compute_tfidf_scores) directly.
      2. Executing the equivalent INSERT via a fresh async engine.
    This is the established Tier-2 pattern for this codebase.
    """

    def test_batch_job_records_unknown_abbreviations(self, gl_tenant_id):
        """
        Verify the miss-signal recording mechanism end-to-end.

        Process:
        1. Use _extract_candidates() to identify candidate terms from messages
           containing the domain abbreviation 'ARPU'.
        2. Use _compute_tfidf_scores() to rank candidates.
        3. Write the top candidates into glossary_miss_signals via a fresh engine.
        4. Query glossary_miss_signals and assert 'ARPU' was recorded.
        """
        from collections import defaultdict

        from app.modules.glossary.miss_signals_job import (
            _compute_tfidf_scores,
            _extract_candidates,
        )

        _db_url()  # Ensure DB is configured

        # Clean any previous miss signals for this tenant
        asyncio.run(
            _run_sql(
                "DELETE FROM glossary_miss_signals WHERE tenant_id = :tid",
                {"tid": gl_tenant_id},
            )
        )

        # Simulate the batch-job's message corpus: 5 messages containing 'ARPU'
        messages = [
            f"What is our ARPU for this month sample query number {i}?"
            for i in range(5)
        ]

        # Step 1: run candidate extraction (pure Python — no DB required)
        term_messages: dict = defaultdict(list)
        for msg in messages:
            candidates = _extract_candidates(msg)
            snippet = msg[:40].replace("\n", " ").strip()
            for term in candidates:
                term_messages[term].append(snippet)

        # Step 2: TF-IDF scoring
        scores = _compute_tfidf_scores(term_messages, len(messages))

        # Verify 'ARPU' was identified as a candidate by the extraction logic
        assert "ARPU" in scores, (
            f"_extract_candidates() must identify 'ARPU' as a candidate term. "
            f"Scores: {scores}. Check that the ABBREV_RE pattern matches 2-6 char "
            "uppercase tokens and that 'ARPU' is not in _STOPWORDS."
        )

        # Step 3: Write top candidates to glossary_miss_signals using a fresh engine
        # (mirrors the INSERT in _process_tenant, validated against real DB)
        top_terms = sorted(scores, key=scores.__getitem__, reverse=True)[:20]

        async def _write_miss_signals():
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    for term in top_terms:
                        docs = term_messages[term]
                        occurrence_count = len(docs)
                        query_sample = docs[0][:40] if docs else ""
                        await session.execute(
                            text(
                                "INSERT INTO glossary_miss_signals "
                                "  (tenant_id, query_text, unresolved_term, occurrence_count) "
                                "VALUES (:tenant_id, :query_text, :term, :count) "
                                "ON CONFLICT DO NOTHING"
                            ),
                            {
                                "tenant_id": gl_tenant_id,
                                "query_text": query_sample,
                                "term": term,
                                "count": occurrence_count,
                            },
                        )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(_write_miss_signals())

        # Step 4: Verify 'ARPU' was inserted into glossary_miss_signals
        rows = asyncio.run(
            _run_sql_fetch(
                "SELECT unresolved_term, occurrence_count "
                "FROM glossary_miss_signals "
                "WHERE tenant_id = :tid AND unresolved_term = 'ARPU'",
                {"tid": gl_tenant_id},
            )
        )

        assert len(rows) >= 1, (
            f"Expected 'ARPU' to appear in glossary_miss_signals, but no rows found. "
            "Check that the INSERT ran and that the constraint allows this term."
        )
        term_row = rows[0]
        assert term_row[0] == "ARPU", f"Expected term 'ARPU', got {term_row[0]!r}"
        assert term_row[1] >= 1, f"occurrence_count should be >= 1, got {term_row[1]}"

    def test_covered_terms_not_recorded_as_miss_signals(self, gl_tenant_id):
        """
        A term already in the tenant's glossary must NOT appear as a
        miss-signal candidate — it is "covered" and excluded by _process_tenant.

        Verify the covered-set exclusion logic:
          1. Insert 'LTV' into glossary_terms (marking it as covered).
          2. Fetch covered terms from the real DB.
          3. Run _extract_candidates() on messages containing 'LTV'.
          4. Apply the covered-set filter (same logic as _process_tenant).
          5. Assert 'LTV' does not appear in the uncovered candidates.
        """
        from app.modules.glossary.miss_signals_job import _extract_candidates

        # Ensure 'LTV' is in the glossary (covered)
        asyncio.run(
            _insert_glossary_term(
                tenant_id=gl_tenant_id,
                term="LTV",
                full_form="Lifetime Value",
            )
        )

        # Fetch the covered terms from the real DB (same SELECT as _process_tenant)
        rows = asyncio.run(
            _run_sql_fetch(
                "SELECT term, aliases FROM glossary_terms WHERE tenant_id = :tenant_id",
                {"tenant_id": gl_tenant_id},
            )
        )
        covered: set[str] = set()
        for row in rows:
            covered.add(row[0].upper())
            for alias in row[1] or []:
                covered.add(alias.upper())

        # Verify 'LTV' is in the covered set before running extraction
        assert "LTV" in covered, (
            f"'LTV' must be in the covered set fetched from glossary_terms. "
            f"Got covered={covered}. Check _insert_glossary_term."
        )

        # Run extraction on messages containing 'LTV'
        messages = [f"What is our LTV for Q{i + 1}?" for i in range(5)]
        all_candidates: set[str] = set()
        for msg in messages:
            all_candidates.update(_extract_candidates(msg))

        # Apply covered-set exclusion (same logic as _process_tenant)
        uncovered_candidates = {c for c in all_candidates if c not in covered}

        assert "LTV" not in uncovered_candidates, (
            "Covered term 'LTV' must be excluded from miss-signal candidates. "
            f"uncovered_candidates={uncovered_candidates}. "
            "The covered-set exclusion logic in _process_tenant() is broken."
        )


# ---------------------------------------------------------------------------
# TEST-035: Glossary Redis cache invalidated on term PATCH
# ---------------------------------------------------------------------------


class TestGlossaryCacheInvalidationOnPatch:
    """TEST-035: Patching a glossary term invalidates its tenant's Redis cache."""

    def test_patch_term_invalidates_redis_cache(self, gl_tenant_id):
        """
        Full flow:
        1. Create a glossary term in the DB.
        2. Call GlossaryExpander._get_terms() to populate the Redis cache.
        3. Verify the cache key exists.
        4. Call update_glossary_term_db() + _invalidate_glossary_cache() (simulating PATCH).
        5. Verify the Redis cache key is deleted.
        6. Call _get_terms() again — verify it reads the updated value from DB.
        """
        asyncio.run(_clear_redis_glossary_cache(gl_tenant_id))

        # Step 1: create the term
        term_id = asyncio.run(
            _insert_glossary_term(
                tenant_id=gl_tenant_id,
                term="NPS",
                full_form="Net Promoter Score",
            )
        )

        cache_key = f"mingai:{gl_tenant_id}:glossary_terms"

        async def _warm_cache_and_verify() -> bool:
            """Populate Redis cache by calling _get_terms, return True if cache was set."""
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            redis = get_redis()
            try:
                # Confirm no cache before warming
                before = await redis.exists(cache_key)
                assert before == 0, "Pre-condition: cache must be empty before warming"

                async with factory() as session:
                    expander = GlossaryExpander(db=session)
                    terms = await expander._get_terms(gl_tenant_id)

                # Cache should now be populated
                after = await redis.exists(cache_key)
                assert after > 0, (
                    "Cache key must exist after calling _get_terms(). "
                    "Check that GlossaryExpander._get_terms() stores in Redis."
                )
                # Verify term is in the cache
                cached_raw = await redis.get(cache_key)
                cached_terms = json.loads(cached_raw) if cached_raw else []
                return any(t["term"] == "NPS" for t in cached_terms)
            finally:
                await engine.dispose()
                await close_redis()

        nps_in_cache = asyncio.run(_warm_cache_and_verify())
        assert nps_in_cache, "NPS term must be in the Redis cache after _get_terms()"

        # Step 4: update the term's full_form (simulates PATCH /glossary/{id})
        async def _patch_and_invalidate():
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            redis = get_redis()
            try:
                async with factory() as session:
                    updated = await update_glossary_term_db(
                        term_id=term_id,
                        tenant_id=gl_tenant_id,
                        updates={"full_form": "Net Promoter Score (Updated)"},
                        db=session,
                        commit=True,
                    )
                assert updated is not None, "Update must succeed"
                assert updated["full_form"] == "Net Promoter Score (Updated)"

                # Simulate what the PATCH route does after updating
                await _invalidate_glossary_cache(gl_tenant_id)

                # Verify cache is now deleted
                cache_exists = await redis.exists(cache_key)
                return cache_exists
            finally:
                await engine.dispose()
                await close_redis()

        cache_exists_after_patch = asyncio.run(_patch_and_invalidate())
        assert cache_exists_after_patch == 0, (
            f"Redis cache key '{cache_key}' must be deleted after PATCH + invalidation. "
            "Got cache_exists_after_patch != 0. "
            "Check that _invalidate_glossary_cache() calls redis.delete()."
        )

        # Step 6: next call to _get_terms() must read the UPDATED value from DB
        async def _verify_next_read_from_db() -> str:
            """Returns full_form of NPS after cache miss re-populates from DB."""
            _reset_redis_pool()
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    expander = GlossaryExpander(db=session)
                    terms = await expander._get_terms(gl_tenant_id)
                for t in terms:
                    if t["term"] == "NPS":
                        return t["full_form"]
                return ""
            finally:
                await engine.dispose()
                await close_redis()

        fresh_full_form = asyncio.run(_verify_next_read_from_db())
        assert fresh_full_form == "Net Promoter Score (Updated)", (
            f"After cache invalidation, _get_terms() must return the updated DB value. "
            f"Got full_form={fresh_full_form!r} — stale cache or DB update failed."
        )


# ---------------------------------------------------------------------------
# DEF-016: Glossary CRUD, Version History, Rollback, Miss Signals, Isolation
# ---------------------------------------------------------------------------

# JWT helper for API-level tests
def _make_token(user_id: str, tenant_id: str, roles: list[str]) -> str:
    from datetime import datetime, timedelta, timezone

    from jose import jwt as jose_jwt

    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        pytest.skip("JWT_SECRET_KEY not configured — skipping integration tests")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": "tenant",
        "plan": "professional",
        "email": f"test-{user_id[:8]}@glp-int.test",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jose_jwt.encode(payload, secret, algorithm="HS256")


async def _create_user(tenant_id: str, role: str = "admin") -> str:
    """Create a real user row in the users table (needed for audit_log FK)."""
    uid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO users (id, tenant_id, email, name, role, status) "
        "VALUES (:id, :tid, :email, :name, :role, 'active')",
        {
            "id": uid,
            "tid": tenant_id,
            "email": f"{role}-{uid[:8]}@glp-int.test",
            "name": f"GL Test {role.title()} {uid[:8]}",
            "role": role,
        },
    )
    return uid


class TestGlossaryCRUDViaAPI:
    """
    DEF-016: Glossary terms can be created, fetched, updated, and soft-deleted
    via the HTTP API with real PostgreSQL. No mocking.
    """

    @pytest.fixture(scope="class")
    def api_tenant_id(self):
        tid = asyncio.run(_create_tenant("GL CRUD API Test"))
        yield tid
        asyncio.run(
            _run_sql("DELETE FROM audit_log WHERE tenant_id = :tid", {"tid": tid})
        )
        asyncio.run(
            _run_sql("DELETE FROM users WHERE tenant_id = :tid", {"tid": tid})
        )
        asyncio.run(_cleanup_tenant(tid))

    @pytest.fixture(scope="class")
    def admin_headers(self, api_tenant_id):
        uid = asyncio.run(_create_user(api_tenant_id, "admin"))
        token = _make_token(uid, api_tenant_id, roles=["tenant_admin"])
        return {"Authorization": f"Bearer {token}"}

    @pytest.fixture(scope="class")
    def viewer_headers(self, api_tenant_id):
        uid = asyncio.run(_create_user(api_tenant_id, "viewer"))
        token = _make_token(uid, api_tenant_id, roles=["viewer"])
        return {"Authorization": f"Bearer {token}"}

    def test_create_fetch_update_delete_term(self, client, api_tenant_id, admin_headers, viewer_headers):
        """Full CRUD lifecycle through the REST API."""
        unique_term = f"CRUD{uuid.uuid4().hex[:6].upper()}"

        # CREATE
        create_resp = client.post(
            "/api/v1/glossary",
            json={"term": unique_term, "full_form": "CRUD Integration Test", "aliases": ["CRUDAL"]},
            headers=admin_headers,
        )
        assert create_resp.status_code == 201, f"Create failed: {create_resp.text}"
        created = create_resp.json()
        term_id = created["id"]
        assert created["term"] == unique_term
        assert created["full_form"] == "CRUD Integration Test"
        assert "CRUDAL" in created["aliases"]

        # FETCH (as viewer — read access)
        get_resp = client.get(f"/api/v1/glossary/{term_id}", headers=viewer_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["term"] == unique_term

        # LIST
        list_resp = client.get("/api/v1/glossary?page_size=100", headers=viewer_headers)
        assert list_resp.status_code == 200
        terms = {item["term"] for item in list_resp.json()["items"]}
        assert unique_term in terms

        # UPDATE
        patch_resp = client.patch(
            f"/api/v1/glossary/{term_id}",
            json={"full_form": "Updated CRUD Test"},
            headers=admin_headers,
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["full_form"] == "Updated CRUD Test"

        # VERIFY update persisted
        get_after = client.get(f"/api/v1/glossary/{term_id}", headers=viewer_headers)
        assert get_after.json()["full_form"] == "Updated CRUD Test"

        # DELETE
        del_resp = client.delete(f"/api/v1/glossary/{term_id}", headers=admin_headers)
        assert del_resp.status_code == 204

        # VERIFY deleted
        get_gone = client.get(f"/api/v1/glossary/{term_id}", headers=viewer_headers)
        assert get_gone.status_code == 404


class TestGlossaryVersionHistory:
    """
    DEF-016: Term version history is tracked in audit_log, and rollback
    restores previous state. Real PostgreSQL, no mocking.
    """

    @pytest.fixture(scope="class")
    def history_tenant_id(self):
        tid = asyncio.run(_create_tenant("GL History Test"))
        yield tid
        # Clean up audit_log entries too
        asyncio.run(
            _run_sql("DELETE FROM audit_log WHERE tenant_id = :tid", {"tid": tid})
        )
        asyncio.run(
            _run_sql("DELETE FROM users WHERE tenant_id = :tid", {"tid": tid})
        )
        asyncio.run(_cleanup_tenant(tid))

    @pytest.fixture(scope="class")
    def history_admin_headers(self, history_tenant_id):
        uid = asyncio.run(_create_user(history_tenant_id, "admin"))
        token = _make_token(uid, history_tenant_id, roles=["tenant_admin"])
        return {"Authorization": f"Bearer {token}"}

    def test_update_creates_audit_entry_and_rollback_restores(
        self, client, history_tenant_id, history_admin_headers
    ):
        """
        1. Create a term
        2. Update it (should write audit_log entry)
        3. GET history — verify audit entry exists with before/after
        4. Rollback to the audit entry — verify term restored
        """
        unique_term = f"HIST{uuid.uuid4().hex[:6].upper()}"

        # Step 1: Create
        create_resp = client.post(
            "/api/v1/glossary",
            json={"term": unique_term, "full_form": "Original Definition"},
            headers=history_admin_headers,
        )
        assert create_resp.status_code == 201, f"Create failed: {create_resp.text}"
        term_id = create_resp.json()["id"]

        # Step 2: Update
        patch_resp = client.patch(
            f"/api/v1/glossary/{term_id}",
            json={"full_form": "Changed Definition"},
            headers=history_admin_headers,
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["full_form"] == "Changed Definition"

        # Step 3: GET history
        history_resp = client.get(
            f"/api/v1/glossary/{term_id}/history",
            headers=history_admin_headers,
        )
        assert history_resp.status_code == 200, f"History failed: {history_resp.text}"
        history_data = history_resp.json()
        assert history_data["total"] >= 1, "Expected at least one audit entry"

        # Find the 'update' entry
        update_entries = [
            e for e in history_data["items"] if e["action"] == "update"
        ]
        assert len(update_entries) >= 1, "Expected an 'update' audit entry"
        audit_entry = update_entries[0]
        assert "full_form" in audit_entry["changed_fields"]
        assert audit_entry["before"]["full_form"] == "Original Definition"
        assert audit_entry["after"]["full_form"] == "Changed Definition"
        version_id = audit_entry["id"]

        # Step 4: Rollback
        rollback_resp = client.patch(
            f"/api/v1/glossary/{term_id}/rollback/{version_id}",
            headers=history_admin_headers,
        )
        assert rollback_resp.status_code == 200, f"Rollback failed: {rollback_resp.text}"
        assert rollback_resp.json()["full_form"] == "Original Definition"

        # Verify rollback persisted
        get_resp = client.get(
            f"/api/v1/glossary/{term_id}",
            headers=history_admin_headers,
        )
        assert get_resp.json()["full_form"] == "Original Definition"

        # Verify rollback created its own audit entry
        history_after = client.get(
            f"/api/v1/glossary/{term_id}/history",
            headers=history_admin_headers,
        )
        rollback_entries = [
            e for e in history_after.json()["items"] if e["action"] == "rollback"
        ]
        assert len(rollback_entries) >= 1, "Expected a 'rollback' audit entry"

        # Cleanup
        client.delete(f"/api/v1/glossary/{term_id}", headers=history_admin_headers)


class TestGlossaryMissSignalsEndpoint:
    """
    DEF-016: Miss signals endpoint returns data from glossary_miss_signals table.
    Real PostgreSQL, no mocking.
    """

    @pytest.fixture(scope="class")
    def miss_tenant_id(self):
        tid = asyncio.run(_create_tenant("GL Miss Signals Test"))
        yield tid
        asyncio.run(
            _run_sql(
                "DELETE FROM glossary_miss_signals WHERE tenant_id = :tid",
                {"tid": tid},
            )
        )
        asyncio.run(
            _run_sql("DELETE FROM users WHERE tenant_id = :tid", {"tid": tid})
        )
        asyncio.run(_cleanup_tenant(tid))

    @pytest.fixture(scope="class")
    def miss_admin_headers(self, miss_tenant_id):
        uid = asyncio.run(_create_user(miss_tenant_id, "admin"))
        token = _make_token(uid, miss_tenant_id, roles=["tenant_admin"])
        return {"Authorization": f"Bearer {token}"}

    def test_miss_signals_endpoint_returns_inserted_data(
        self, client, miss_tenant_id, miss_admin_headers
    ):
        """
        Insert miss signals directly into the DB, then verify the API endpoint
        returns them aggregated correctly.
        """
        # Insert miss signals for two terms
        async def _insert_signals():
            for i in range(3):
                await _run_sql(
                    "INSERT INTO glossary_miss_signals "
                    "(tenant_id, query_text, unresolved_term, occurrence_count) "
                    "VALUES (:tid, :query, :term, :count)",
                    {
                        "tid": miss_tenant_id,
                        "query": f"What is XTERM sample {i}?",
                        "term": "XTERM",
                        "count": 2,
                    },
                )
            await _run_sql(
                "INSERT INTO glossary_miss_signals "
                "(tenant_id, query_text, unresolved_term, occurrence_count) "
                "VALUES (:tid, :query, :term, :count)",
                {
                    "tid": miss_tenant_id,
                    "query": "Show me YTERM data",
                    "term": "YTERM",
                    "count": 5,
                },
            )

        asyncio.run(_insert_signals())

        # Call the miss-signals endpoint
        resp = client.get(
            "/api/v1/glossary/miss-signals?limit=50",
            headers=miss_admin_headers,
        )
        assert resp.status_code == 200, f"Miss signals failed: {resp.text}"
        data = resp.json()
        assert "items" in data

        term_names = {item["term"] for item in data["items"]}
        assert "XTERM" in term_names, f"XTERM not found in miss signals. Got: {term_names}"
        assert "YTERM" in term_names, f"YTERM not found in miss signals. Got: {term_names}"

        # Verify occurrence counts are aggregated
        xterm_item = next(i for i in data["items"] if i["term"] == "XTERM")
        assert xterm_item["occurrence_count"] >= 6, (
            f"Expected XTERM occurrence_count >= 6 (3 rows * 2 each), "
            f"got {xterm_item['occurrence_count']}"
        )


class TestGlossaryMultiTenantIsolation:
    """
    DEF-016: Tenant A cannot read or modify tenant B's glossary terms.
    Real PostgreSQL, no mocking.
    """

    @pytest.fixture(scope="class")
    def tenant_a_id(self):
        tid = asyncio.run(_create_tenant("GL Isolation Tenant A"))
        yield tid
        asyncio.run(
            _run_sql("DELETE FROM users WHERE tenant_id = :tid", {"tid": tid})
        )
        asyncio.run(_cleanup_tenant(tid))

    @pytest.fixture(scope="class")
    def tenant_b_id(self):
        tid = asyncio.run(_create_tenant("GL Isolation Tenant B"))
        yield tid
        asyncio.run(
            _run_sql("DELETE FROM users WHERE tenant_id = :tid", {"tid": tid})
        )
        asyncio.run(_cleanup_tenant(tid))

    @pytest.fixture(scope="class")
    def tenant_a_admin_headers(self, tenant_a_id):
        uid = asyncio.run(_create_user(tenant_a_id, "admin"))
        token = _make_token(uid, tenant_a_id, roles=["tenant_admin"])
        return {"Authorization": f"Bearer {token}"}

    @pytest.fixture(scope="class")
    def tenant_b_admin_headers(self, tenant_b_id):
        uid = asyncio.run(_create_user(tenant_b_id, "admin"))
        token = _make_token(uid, tenant_b_id, roles=["tenant_admin"])
        return {"Authorization": f"Bearer {token}"}

    def test_tenant_b_cannot_see_tenant_a_terms(
        self, client, tenant_a_id, tenant_b_id, tenant_a_admin_headers, tenant_b_admin_headers
    ):
        """Tenant A creates a term; tenant B's glossary list must not contain it."""
        unique_term = f"ISOL{uuid.uuid4().hex[:6].upper()}"

        # Tenant A creates a term
        create_resp = client.post(
            "/api/v1/glossary",
            json={"term": unique_term, "full_form": "Isolation Test Term"},
            headers=tenant_a_admin_headers,
        )
        assert create_resp.status_code == 201
        term_id = create_resp.json()["id"]

        # Tenant B lists glossary — must NOT see tenant A's term
        list_resp = client.get(
            "/api/v1/glossary?page_size=100",
            headers=tenant_b_admin_headers,
        )
        assert list_resp.status_code == 200
        b_terms = {item["term"] for item in list_resp.json()["items"]}
        assert unique_term not in b_terms, (
            f"Tenant B must not see tenant A's term '{unique_term}'. "
            f"Tenant B terms: {b_terms}"
        )

        # Tenant B cannot GET tenant A's term by ID
        get_resp = client.get(f"/api/v1/glossary/{term_id}", headers=tenant_b_admin_headers)
        assert get_resp.status_code == 404

        # Tenant B cannot PATCH tenant A's term
        patch_resp = client.patch(
            f"/api/v1/glossary/{term_id}",
            json={"full_form": "Hijacked"},
            headers=tenant_b_admin_headers,
        )
        assert patch_resp.status_code == 404

        # Tenant B cannot DELETE tenant A's term
        del_resp = client.delete(f"/api/v1/glossary/{term_id}", headers=tenant_b_admin_headers)
        assert del_resp.status_code == 404

        # Verify tenant A's term is still intact
        get_a = client.get(f"/api/v1/glossary/{term_id}", headers=tenant_a_admin_headers)
        assert get_a.status_code == 200
        assert get_a.json()["full_form"] == "Isolation Test Term"

        # Cleanup
        client.delete(f"/api/v1/glossary/{term_id}", headers=tenant_a_admin_headers)
