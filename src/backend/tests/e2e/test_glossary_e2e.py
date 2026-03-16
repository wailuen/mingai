"""
TEST-039: Glossary Admin and Expansion E2E Tests

End-to-end tests for the glossary workflow:
1. Add a glossary term via API
2. Verify the term is returned in GET /glossary
3. Verify the GlossaryExpander expands the term in a query
4. Update the term and verify the update persists
5. Delete the term via API
6. Verify it is no longer returned
7. Test cache invalidation (add term, verify cache cleared, GET returns new term)

Tier 3: E2E, NO mocking, <10s timeout, requires Docker infrastructure.

Prerequisites:
    docker-compose up -d  # ensure DB and Redis are running

Run:
    pytest tests/e2e/test_glossary_e2e.py -v --timeout=10
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        pytest.skip("JWT_SECRET_KEY not configured -- skipping E2E tests")
    return secret


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured -- skipping E2E tests")
    return url


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL", "")
    if not url:
        pytest.skip("REDIS_URL not configured -- skipping E2E tests")
    return url


def _make_token(
    user_id: str,
    tenant_id: str,
    roles: list[str],
    scope: str = "tenant",
    plan: str = "professional",
    email: str = "e2e@glossary.test",
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": scope,
        "plan": plan,
        "email": email,
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


async def _run_sql(sql: str, params: dict | None = None):
    engine = create_async_engine(_db_url(), echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(sql), params or {})
            await session.commit()
    finally:
        await engine.dispose()


async def _get_redis_value(key: str) -> str | None:
    """Read a key from Redis to check cache state. Returns None if not found."""
    import redis.asyncio as aioredis

    r = aioredis.from_url(_redis_url(), decode_responses=True)
    try:
        return await r.get(key)
    finally:
        await r.aclose()


async def _delete_redis_key(key: str) -> None:
    """Delete a Redis key (for cache pre-warming setup)."""
    import redis.asyncio as aioredis

    r = aioredis.from_url(_redis_url(), decode_responses=True)
    try:
        await r.delete(key)
    finally:
        await r.aclose()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tenant_id():
    """Provision a test tenant for E2E glossary tests."""
    tid = str(uuid.uuid4())

    async def setup():
        await _run_sql(
            "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
            "VALUES (:id, :name, :slug, :plan, :email, 'active')",
            {
                "id": tid,
                "name": f"Glossary E2E Tenant {tid[:8]}",
                "slug": f"glossary-e2e-{tid[:8]}",
                "plan": "professional",
                "email": f"admin@glossary-e2e-{tid[:8]}.test",
            },
        )

    async def teardown():
        await _run_sql(
            "DELETE FROM glossary_terms WHERE tenant_id = :tid", {"tid": tid}
        )
        await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})
        # Clean up Redis glossary cache for this tenant
        cache_key = f"mingai:{tid}:glossary_terms"
        try:
            await _delete_redis_key(cache_key)
        except Exception:
            pass

    asyncio.run(setup())
    yield tid
    asyncio.run(teardown())


@pytest.fixture(scope="module")
def admin_headers(tenant_id):
    admin_id = str(uuid.uuid4())
    token = _make_token(admin_id, tenant_id, roles=["tenant_admin"])
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def user_headers(tenant_id):
    uid = str(uuid.uuid4())
    token = _make_token(uid, tenant_id, roles=["end_user"])
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def client():
    """Session-scoped TestClient for E2E tests."""
    from fastapi.testclient import TestClient

    from app.main import app

    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    except RuntimeError as exc:
        if "event loop is closed" not in str(exc).lower():
            raise


# ---------------------------------------------------------------------------
# E2E Test: Full Glossary Admin Lifecycle
# ---------------------------------------------------------------------------


class TestGlossaryFullLifecycle:
    """
    E2E: Add term -> List -> Get -> Update -> Verify update -> Delete -> Verify deleted.
    All operations use real DB + Redis, no mocking.
    """

    def test_full_glossary_crud_lifecycle(
        self, client, tenant_id, admin_headers, user_headers
    ):
        """Complete CRUD lifecycle through the API with real infrastructure."""
        unique_term = f"E2ETERM{uuid.uuid4().hex[:6].upper()}"

        # 1. CREATE a glossary term
        create_resp = client.post(
            "/api/v1/glossary",
            json={
                "term": unique_term,
                "full_form": "End-to-End Test Expansion",
                "aliases": ["E2EALIAS"],
            },
            headers=admin_headers,
        )
        assert create_resp.status_code == 201, create_resp.text
        created = create_resp.json()
        term_id = created["id"]
        assert created["term"] == unique_term
        assert created["full_form"] == "End-to-End Test Expansion"
        assert "E2EALIAS" in created["aliases"]

        # 2. LIST -- term must appear
        list_resp = client.get(
            "/api/v1/glossary?page_size=100",
            headers=user_headers,
        )
        assert list_resp.status_code == 200
        terms = {item["term"] for item in list_resp.json()["items"]}
        assert (
            unique_term in terms
        ), f"Created term {unique_term} not found in glossary list"

        # 3. GET by ID
        get_resp = client.get(f"/api/v1/glossary/{term_id}", headers=user_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["term"] == unique_term

        # 4. UPDATE the term's full_form
        patch_resp = client.patch(
            f"/api/v1/glossary/{term_id}",
            json={"full_form": "Updated E2E Expansion"},
            headers=admin_headers,
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["full_form"] == "Updated E2E Expansion"

        # 5. VERIFY update persisted
        get_after_update = client.get(
            f"/api/v1/glossary/{term_id}", headers=user_headers
        )
        assert get_after_update.json()["full_form"] == "Updated E2E Expansion"

        # 6. DELETE the term
        del_resp = client.delete(f"/api/v1/glossary/{term_id}", headers=admin_headers)
        assert del_resp.status_code == 204

        # 7. VERIFY deleted -- GET returns 404
        get_after_del = client.get(f"/api/v1/glossary/{term_id}", headers=user_headers)
        assert get_after_del.status_code == 404

        # 8. VERIFY deleted -- term no longer in list
        list_after_del = client.get(
            "/api/v1/glossary?page_size=100",
            headers=user_headers,
        )
        assert list_after_del.status_code == 200
        remaining_terms = {item["term"] for item in list_after_del.json()["items"]}
        assert unique_term not in remaining_terms


# ---------------------------------------------------------------------------
# E2E Test: Glossary Expansion in Query
# ---------------------------------------------------------------------------


class TestGlossaryExpansion:
    """
    E2E: Verify GlossaryExpander expands terms stored in real DB.
    Uses real PostgreSQL + Redis -- no mocking.
    """

    def test_glossary_expander_expands_real_term(
        self, client, tenant_id, admin_headers
    ):
        """
        Create a term in DB, then use GlossaryExpander.expand() to verify
        the term is expanded inline in a query string.
        """
        unique_term = f"XPND{uuid.uuid4().hex[:4].upper()}"
        full_form = "Expanded Term Definition"

        # Create the term via API (writes to real DB + invalidates cache)
        create_resp = client.post(
            "/api/v1/glossary",
            json={"term": unique_term, "full_form": full_form},
            headers=admin_headers,
        )
        assert create_resp.status_code == 201
        term_id = create_resp.json()["id"]

        # Use GlossaryExpander with a real DB session to expand a query
        async def _expand():
            from app.modules.glossary.expander import GlossaryExpander

            engine = create_async_engine(_db_url(), echo=False)
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    expander = GlossaryExpander(db=session)
                    query = f"What does {unique_term} mean for our company?"
                    expanded, applied = await expander.expand(query, tenant_id)
                    return expanded, applied
            finally:
                await engine.dispose()

        expanded_query, applied_expansions = asyncio.run(_expand())

        # The expanded query must include the full_form
        assert (
            full_form in expanded_query
        ), f"Expected '{full_form}' in expanded query: '{expanded_query}'"
        # The applied expansions list must contain the expansion
        assert len(applied_expansions) >= 1
        assert any(unique_term in exp for exp in applied_expansions)

        # Cleanup
        client.delete(f"/api/v1/glossary/{term_id}", headers=admin_headers)

    def test_deleted_term_no_longer_expands(self, client, tenant_id, admin_headers):
        """
        After deleting a term, GlossaryExpander must NOT expand it.
        Verifies cache invalidation works.
        """
        unique_term = f"DELT{uuid.uuid4().hex[:4].upper()}"
        full_form = "Term That Will Be Deleted"

        # Create term
        create_resp = client.post(
            "/api/v1/glossary",
            json={"term": unique_term, "full_form": full_form},
            headers=admin_headers,
        )
        assert create_resp.status_code == 201
        term_id = create_resp.json()["id"]

        # Delete term (this should invalidate the Redis cache)
        del_resp = client.delete(f"/api/v1/glossary/{term_id}", headers=admin_headers)
        assert del_resp.status_code == 204

        # Attempt expansion -- term should NOT expand
        async def _expand():
            from app.modules.glossary.expander import GlossaryExpander

            engine = create_async_engine(_db_url(), echo=False)
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    expander = GlossaryExpander(db=session)
                    query = f"What does {unique_term} mean?"
                    expanded, applied = await expander.expand(query, tenant_id)
                    return expanded, applied
            finally:
                await engine.dispose()

        expanded_query, applied_expansions = asyncio.run(_expand())

        # The deleted term's full_form should NOT appear in the expanded query
        assert full_form not in expanded_query
        assert len(applied_expansions) == 0


# ---------------------------------------------------------------------------
# E2E Test: Cache Invalidation
# ---------------------------------------------------------------------------


class TestGlossaryCacheInvalidation:
    """
    E2E: Verify that write operations (create, update, delete) invalidate
    the Redis glossary cache so subsequent reads see fresh data.
    """

    def test_create_invalidates_cache(
        self, client, tenant_id, admin_headers, user_headers
    ):
        """
        1. Seed Redis cache with stale data
        2. Create a new term via API (should invalidate cache)
        3. Verify the new term appears in GET /glossary (cache was cleared)
        """
        cache_key = f"mingai:{tenant_id}:glossary_terms"
        unique_term = f"CACHE{uuid.uuid4().hex[:4].upper()}"

        # Step 1: Seed Redis with a stale cache entry
        async def _seed_stale_cache():
            import redis.asyncio as aioredis

            r = aioredis.from_url(_redis_url(), decode_responses=True)
            try:
                stale_data = json.dumps(
                    [
                        {
                            "term": "STALE_TERM",
                            "full_form": "This is stale",
                            "aliases": [],
                        }
                    ]
                )
                await r.setex(cache_key, 3600, stale_data)
            finally:
                await r.aclose()

        asyncio.run(_seed_stale_cache())

        # Step 2: Create a new term (this invalidates the cache)
        create_resp = client.post(
            "/api/v1/glossary",
            json={"term": unique_term, "full_form": "Fresh Cache Test"},
            headers=admin_headers,
        )
        assert create_resp.status_code == 201
        term_id = create_resp.json()["id"]

        # Step 3: Verify the Redis cache was invalidated
        # (the cache key should be gone or refreshed)
        async def _check_cache():
            return await _get_redis_value(cache_key)

        cached = asyncio.run(_check_cache())
        # After invalidation, the cache should be empty (None)
        # or if re-populated, should NOT contain stale "STALE_TERM"
        if cached is not None:
            cached_terms = json.loads(cached)
            stale_names = {t["term"] for t in cached_terms}
            assert "STALE_TERM" not in stale_names or unique_term in stale_names

        # Step 4: Verify the new term appears via API (reads from DB, not stale cache)
        list_resp = client.get(
            "/api/v1/glossary?page_size=100",
            headers=user_headers,
        )
        assert list_resp.status_code == 200
        terms = {item["term"] for item in list_resp.json()["items"]}
        assert unique_term in terms

        # Cleanup
        client.delete(f"/api/v1/glossary/{term_id}", headers=admin_headers)

    def test_delete_invalidates_cache(
        self, client, tenant_id, admin_headers, user_headers
    ):
        """
        1. Create a term
        2. GET /glossary (populates cache)
        3. Delete the term (should invalidate cache)
        4. GET /glossary -- term must NOT appear (stale cache cleared)
        """
        unique_term = f"DCACHE{uuid.uuid4().hex[:4].upper()}"

        # Step 1: Create
        create_resp = client.post(
            "/api/v1/glossary",
            json={"term": unique_term, "full_form": "Delete Cache Test"},
            headers=admin_headers,
        )
        assert create_resp.status_code == 201
        term_id = create_resp.json()["id"]

        # Step 2: GET to populate cache
        list_resp = client.get(
            "/api/v1/glossary?page_size=100",
            headers=user_headers,
        )
        assert list_resp.status_code == 200
        terms_before = {item["term"] for item in list_resp.json()["items"]}
        assert unique_term in terms_before

        # Step 3: Delete (should invalidate cache)
        del_resp = client.delete(f"/api/v1/glossary/{term_id}", headers=admin_headers)
        assert del_resp.status_code == 204

        # Step 4: GET again -- term must be gone
        list_after = client.get(
            "/api/v1/glossary?page_size=100",
            headers=user_headers,
        )
        assert list_after.status_code == 200
        terms_after = {item["term"] for item in list_after.json()["items"]}
        assert unique_term not in terms_after


# ---------------------------------------------------------------------------
# E2E Test: Authorization Enforcement
# ---------------------------------------------------------------------------


class TestGlossaryAuthE2E:
    """E2E authorization: end users can read but cannot write glossary terms."""

    def test_end_user_can_list_glossary(self, client, user_headers):
        """End users can list glossary terms."""
        resp = client.get("/api/v1/glossary", headers=user_headers)
        assert resp.status_code == 200

    def test_end_user_cannot_create_term(self, client, user_headers):
        """End users cannot create glossary terms (403)."""
        resp = client.post(
            "/api/v1/glossary",
            json={"term": "BLOCKED", "full_form": "Should Fail"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_end_user_cannot_delete_term(self, client, user_headers):
        """End users cannot delete glossary terms (403)."""
        resp = client.delete(
            f"/api/v1/glossary/{uuid.uuid4()}",
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_unauthenticated_cannot_list_glossary(self, client):
        """Unauthenticated requests are rejected with 401."""
        resp = client.get("/api/v1/glossary")
        assert resp.status_code == 401
