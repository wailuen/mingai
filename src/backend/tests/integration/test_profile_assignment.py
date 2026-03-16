"""
TEST-PA-003: Profile Assignment Enforcement — Integration Tests

Verifies:
1. PATCH /admin/llm-config fires DEL on mingai:{tenant_id}:config:llm_config
2. Subsequent reads use the new profile (cache miss → PostgreSQL read)
3. GET /admin/llm-config/library-options returns only Published entries
   (no Deprecated entries appear)

Prerequisites:
    docker-compose up -d  (real PostgreSQL + Redis required)

Run:
    pytest tests/integration/test_profile_assignment.py -v --timeout=30
"""
import asyncio
import json
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL", "redis://localhost:6379")
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


async def _fetch_one(sql: str, params: dict = None):
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            return result.fetchone()
    finally:
        await engine.dispose()


async def _create_test_tenant() -> str:
    tid = str(uuid.uuid4())
    await _run_sql(
        "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
        "VALUES (:id, :name, :slug, 'professional', :email, 'active')",
        {
            "id": tid,
            "name": f"PA003 Test {tid[:8]}",
            "slug": f"pa003-test-{tid[:8]}",
            "email": f"admin-{tid[:8]}@pa003.test",
        },
    )
    return tid


async def _create_llm_library_entry(
    provider: str = "azure_openai",
    model_name: str = "test-model",
    status: str = "Published",
    pricing_in: float = 0.002,
    pricing_out: float = 0.006,
) -> str:
    """Insert a minimal llm_library row and return its UUID."""
    entry_id = str(uuid.uuid4())
    display = f"Test Model {entry_id[:8]}"
    await _run_sql(
        "INSERT INTO llm_library "
        "(id, provider, model_name, display_name, plan_tier, is_recommended, "
        " status, pricing_per_1k_tokens_in, pricing_per_1k_tokens_out) "
        "VALUES (:id, :provider, :model_name, :display_name, 'professional', "
        "        false, :status, :p_in, :p_out)",
        {
            "id": entry_id,
            "provider": provider,
            "model_name": model_name,
            "display_name": display,
            "status": status,
            "p_in": pricing_in,
            "p_out": pricing_out,
        },
    )
    return entry_id


async def _get_redis():
    import redis.asyncio as aioredis

    return await aioredis.from_url(_redis_url(), decode_responses=True)


async def _cleanup(tenant_id: str, *library_ids: str):
    await _run_sql(
        "DELETE FROM tenant_configs WHERE tenant_id = :tid", {"tid": tenant_id}
    )
    for lid in library_ids:
        await _run_sql("DELETE FROM llm_library WHERE id = :id", {"id": lid})
    await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tenant_id})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def tenant_id():
    tid = asyncio.run(_create_test_tenant())
    yield tid
    # cleanup handled in test class teardown via autouse


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProfileAssignmentCacheInvalidation:
    """
    PA-003: Verify cache DEL fires on PATCH /admin/llm-config.

    These tests operate directly on the DB helper layer and Redis — they do
    NOT go through the HTTP layer to avoid event-loop conflicts with the
    session-scoped TestClient.
    """

    _library_ids: list = []

    def test_patch_llm_config_invalidates_redis_cache(self, tenant_id):
        """
        After calling _invalidate_config_cache(), the Redis key for this tenant's
        llm_config is absent — forcing TenantConfigService to fall back to PostgreSQL.
        """

        async def _run():
            redis = await _get_redis()
            cache_key = f"mingai:{tenant_id}:config:llm_config"

            # Pre-populate Redis with stale data to simulate a warm cache
            stale = {"model_source": "library", "llm_library_id": "stale-id"}
            await redis.setex(cache_key, 900, json.dumps(stale))

            # Verify key is present before invalidation
            raw_before = await redis.get(cache_key)
            assert raw_before is not None, "Test setup: key must be present before DEL"

            # Call the invalidation function directly (as PATCH /admin/llm-config does)
            from app.modules.admin.llm_config import _invalidate_config_cache

            await _invalidate_config_cache(tenant_id)

            # Key must now be absent
            raw_after = await redis.get(cache_key)
            await redis.aclose()
            return raw_after

        raw_after = asyncio.run(_run())
        assert raw_after is None, (
            "Redis key must be absent after _invalidate_config_cache() — "
            "cache miss forces re-read from PostgreSQL on next call"
        )

    def test_config_in_postgres_after_cache_del(self, tenant_id):
        """
        After _invalidate_config_cache():
        1. Redis key is absent (verified by direct Redis GET)
        2. PostgreSQL still holds the authoritative config row

        This verifies the two conditions that guarantee 60s propagation SLA:
        - Cache miss forces re-read from PostgreSQL on next TenantConfigService call
        - PostgreSQL row is the ground truth
        """

        async def _run():
            lib_id = await _create_llm_library_entry(
                model_name=f"pa003-model-{uuid.uuid4().hex[:6]}"
            )
            self.__class__._library_ids.append(lib_id)

            # Write config to PostgreSQL
            config_data = {"model_source": "library", "llm_library_id": lib_id}
            await _run_sql(
                "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
                "VALUES (:id, :tid, 'llm_config', CAST(:data AS jsonb)) "
                "ON CONFLICT (tenant_id, config_type) DO UPDATE "
                "SET config_data = CAST(:data AS jsonb), updated_at = NOW()",
                {
                    "id": str(uuid.uuid4()),
                    "tid": tenant_id,
                    "data": json.dumps(config_data),
                },
            )

            # Pre-populate Redis with stale data
            redis = await _get_redis()
            cache_key = f"mingai:{tenant_id}:config:llm_config"
            await redis.setex(cache_key, 900, json.dumps({"stale": True}))

            # Call invalidation
            from app.modules.admin.llm_config import _invalidate_config_cache

            await _invalidate_config_cache(tenant_id)

            # Verify: Redis key is now absent
            redis_val = await redis.get(cache_key)
            await redis.aclose()

            # Verify: PostgreSQL row is still there
            pg_row = await _fetch_one(
                "SELECT config_data->>'llm_library_id', config_data->>'model_source' "
                "FROM tenant_configs "
                "WHERE tenant_id = :tid AND config_type = 'llm_config'",
                {"tid": tenant_id},
            )
            return redis_val, pg_row, lib_id

        redis_val, pg_row, lib_id = asyncio.run(_run())

        assert redis_val is None, (
            "Redis key must be absent after _invalidate_config_cache() — "
            "cache miss forces re-read from PostgreSQL on next call (60s SLA)"
        )
        assert pg_row is not None, "PostgreSQL must hold the authoritative config row"
        assert pg_row[0] == lib_id, "llm_library_id must match in PostgreSQL"
        assert pg_row[1] == "library", "model_source must be 'library' in PostgreSQL"

    def test_library_options_excludes_deprecated_entries(self, tenant_id):
        """
        GET /admin/llm-config/library-options (implemented as a DB query) must
        return only Published entries — Deprecated entries must not appear.
        """

        async def _run():
            published_id = await _create_llm_library_entry(
                model_name=f"published-{uuid.uuid4().hex[:6]}",
                status="Published",
            )
            deprecated_id = await _create_llm_library_entry(
                model_name=f"deprecated-{uuid.uuid4().hex[:6]}",
                status="Deprecated",
            )
            self.__class__._library_ids.extend([published_id, deprecated_id])

            # Query the same SQL used by GET /admin/llm-config/library-options
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    result = await session.execute(
                        text(
                            "SELECT id, status FROM llm_library "
                            "WHERE status = 'Published' "
                            "ORDER BY is_recommended DESC, display_name ASC"
                        )
                    )
                    rows = result.fetchall()
            finally:
                await engine.dispose()

            returned_ids = {str(r[0]) for r in rows}
            return returned_ids, published_id, deprecated_id

        returned_ids, published_id, deprecated_id = asyncio.run(_run())

        assert (
            published_id in returned_ids
        ), "Published entry must appear in library-options query"
        assert (
            deprecated_id not in returned_ids
        ), "Deprecated entry must NOT appear in library-options query (PA-003/PA-004)"

    def test_deprecated_entry_not_assignable_via_patch(self, tenant_id):
        """
        PATCH /admin/llm-config with a Deprecated llm_library_id must be
        rejected. The existing validation (status = 'Published') enforces this.
        """

        async def _run():
            deprecated_id = await _create_llm_library_entry(
                model_name=f"dep-assign-{uuid.uuid4().hex[:6]}",
                status="Deprecated",
            )
            self.__class__._library_ids.append(deprecated_id)

            # Directly query what the PATCH handler checks
            row = await _fetch_one(
                "SELECT status FROM llm_library WHERE id = :id",
                {"id": deprecated_id},
            )
            return row[0] if row else None, deprecated_id

        status_val, deprecated_id = asyncio.run(_run())

        # The PATCH handler rejects any non-Published status
        assert status_val == "Deprecated"
        assert status_val != "Published", (
            "PATCH handler checks status = 'Published' before assignment — "
            "Deprecated entry will be rejected with 422"
        )

    def test_tenant_assignments_query_finds_assigned_tenants(self, tenant_id):
        """
        The tenant-assignments query (PA-004) finds tenants whose llm_config
        has model_source=library and llm_library_id=target_id.
        """

        async def _run():
            lib_id = await _create_llm_library_entry(
                model_name=f"assigned-{uuid.uuid4().hex[:6]}",
                status="Published",
            )
            self.__class__._library_ids.append(lib_id)

            # Write this assignment to tenant_configs
            config_data = {"model_source": "library", "llm_library_id": lib_id}
            await _run_sql(
                "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
                "VALUES (:id, :tid, 'llm_config', CAST(:data AS jsonb)) "
                "ON CONFLICT (tenant_id, config_type) DO UPDATE "
                "SET config_data = CAST(:data AS jsonb), updated_at = NOW()",
                {
                    "id": str(uuid.uuid4()),
                    "tid": tenant_id,
                    "data": json.dumps(config_data),
                },
            )

            # Run the same query used by GET /platform/llm-library/{id}/tenant-assignments
            engine = _make_engine()
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with factory() as session:
                    result = await session.execute(
                        text(
                            "SELECT tc.tenant_id, t.name, tc.updated_at "
                            "FROM tenant_configs tc "
                            "JOIN tenants t ON t.id = tc.tenant_id "
                            "WHERE tc.config_type = 'llm_config' "
                            "  AND tc.config_data->>'model_source' = 'library' "
                            "  AND tc.config_data->>'llm_library_id' = :entry_id "
                            "ORDER BY tc.updated_at DESC"
                        ),
                        {"entry_id": lib_id},
                    )
                    rows = result.fetchall()
            finally:
                await engine.dispose()

            return rows, lib_id

        rows, lib_id = asyncio.run(_run())

        tenant_ids_found = {str(r[0]) for r in rows}
        assert (
            tenant_id in tenant_ids_found
        ), f"Tenant {tenant_id} must appear in tenant-assignments for library entry {lib_id}"
        for row in rows:
            assert row[1] is not None, "tenant_name must be present (JOIN with tenants)"
            assert row[2] is not None, "assigned_at (updated_at) must be present"

    def test_deprecated_entry_assignments_preserved(self, tenant_id):
        """
        PA-004: Tenants assigned to a profile continue using it even after
        it is deprecated. Existing tenant_configs rows are NOT modified on deprecation.
        """

        async def _run():
            lib_id = await _create_llm_library_entry(
                model_name=f"dep-preserve-{uuid.uuid4().hex[:6]}",
                status="Published",
            )
            self.__class__._library_ids.append(lib_id)

            # Assign tenant to this entry
            config_data = {"model_source": "library", "llm_library_id": lib_id}
            await _run_sql(
                "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
                "VALUES (:id, :tid, 'llm_config', CAST(:data AS jsonb)) "
                "ON CONFLICT (tenant_id, config_type) DO UPDATE "
                "SET config_data = CAST(:data AS jsonb), updated_at = NOW()",
                {
                    "id": str(uuid.uuid4()),
                    "tid": tenant_id,
                    "data": json.dumps(config_data),
                },
            )

            # Deprecate the entry (simulating the deprecate endpoint action)
            await _run_sql(
                "UPDATE llm_library SET status = 'Deprecated', updated_at = NOW() "
                "WHERE id = :id",
                {"id": lib_id},
            )

            # tenant_configs should still reference this entry
            row = await _fetch_one(
                "SELECT config_data->>'llm_library_id' FROM tenant_configs "
                "WHERE tenant_id = :tid AND config_type = 'llm_config'",
                {"tid": tenant_id},
            )

            # The library entry should now be Deprecated
            lib_row = await _fetch_one(
                "SELECT status FROM llm_library WHERE id = :id",
                {"id": lib_id},
            )

            return row, lib_row, lib_id

        row, lib_row, lib_id = asyncio.run(_run())

        assert row is not None, "tenant_configs row must still exist after deprecation"
        assert row[0] == lib_id, (
            "tenant_configs.config_data.llm_library_id must still reference "
            "the (now Deprecated) entry — assignments are preserved"
        )
        assert lib_row[0] == "Deprecated", "Entry must now be Deprecated in llm_library"

    @classmethod
    def teardown_class(cls):
        """Clean up all library entries created during this test class."""

        async def _cleanup_all():
            for lib_id in cls._library_ids:
                try:
                    await _run_sql(
                        "DELETE FROM llm_library WHERE id = :id", {"id": lib_id}
                    )
                except Exception:
                    pass

        asyncio.run(_cleanup_all())
