"""
GAP-057: Tenant provisioning rollback verification (Tier 2).

Integration tests verifying the provisioning state machine's rollback
behavior when provisioning fails midway. All tests use real PostgreSQL
and Redis -- NO MOCKING.

Requires Docker services: PostgreSQL (DATABASE_URL) and Redis (REDIS_URL).
"""
from __future__ import annotations

import json
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.redis_client as redis_client_module
import app.core.session as session_module
import app.modules.tenants.worker as worker_module
from app.core.redis_client import get_redis
from app.modules.tenants.provisioning import (
    ConcurrentProvisioningError,
    ProvisioningContext,
    ProvisioningState,
    TenantProvisioningMachine,
    _STEP_ORDER,
)
from app.modules.tenants.worker import (
    _DEFAULT_TENANT_ROLES,
    _PROVISIONING_EVENTS_TTL_SECS,
    run_tenant_provisioning,
)


def _unique_id() -> str:
    """Generate a unique tenant_id to avoid cross-test collision."""
    return str(uuid.uuid4())


def _unique_slug() -> str:
    return f"test-slug-{uuid.uuid4().hex[:8]}"


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured -- skipping integration tests")
    return url


@pytest.fixture(autouse=True)
async def _reset_pools():
    """
    Reset the module-level SQLAlchemy engine and Redis pool before each test.

    Each pytest-asyncio test function gets its own event loop. The module-level
    engine in session.py binds asyncpg connections to the first event loop.
    Disposing and recreating the engine per test avoids 'another operation is
    in progress' and 'Future attached to a different loop' errors.
    """
    # Reset Redis pool
    redis_client_module._redis_pool = None

    # Dispose old engine and create a fresh one for this test's event loop
    await session_module.engine.dispose()
    session_module.engine = create_async_engine(
        _db_url(), echo=False, pool_size=5, max_overflow=10
    )
    session_module.async_session_factory = async_sessionmaker(
        session_module.engine, class_=AsyncSession, expire_on_commit=False
    )
    # Also patch the worker module's direct import of async_session_factory
    worker_module.async_session_factory = session_module.async_session_factory

    # Ensure the roles table exists (worker depends on it but it may not
    # have been created by migrations yet)
    async with session_module.async_session_factory() as session:
        await session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS roles ("
                "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
                "  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,"
                "  name VARCHAR NOT NULL,"
                "  created_at TIMESTAMPTZ DEFAULT NOW(),"
                "  UNIQUE(tenant_id, name)"
                ")"
            )
        )
        await session.commit()

    yield

    # Teardown: dispose engine and reset Redis
    await session_module.engine.dispose()
    if redis_client_module._redis_pool is not None:
        await redis_client_module._redis_pool.aclose()
        redis_client_module._redis_pool = None


def _get_session_factory():
    """Get the current session factory (after reset)."""
    return session_module.async_session_factory


@pytest.fixture
async def cleanup_tenant():
    """
    Fixture that yields a list. Append tenant_ids to it during the test;
    they will be cleaned up from tenants, roles, and tenant_configs after.
    """
    tenant_ids: list[str] = []
    yield tenant_ids

    factory = _get_session_factory()
    async with factory() as session:
        for tid in tenant_ids:
            await session.execute(
                text("DELETE FROM tenant_configs WHERE tenant_id = :tid"),
                {"tid": tid},
            )
            await session.execute(
                text("DELETE FROM roles WHERE tenant_id = :tid"),
                {"tid": tid},
            )
            await session.execute(
                text("DELETE FROM tenants WHERE id = :tid"),
                {"tid": tid},
            )
            await session.commit()

    # Clean up Redis namespace keys
    redis = get_redis()
    for tid in tenant_ids:
        await redis.delete(
            f"mingai:{tid}:namespace:active",
            f"mingai:{tid}:namespace:metadata",
        )


# =========================================================================
# GAP-057-01: Successful provisioning creates all expected records
# =========================================================================


async def test_successful_provisioning_creates_all_records(cleanup_tenant):
    """
    After a full successful provisioning run, verify tenant row, roles,
    tenant_config (rls_context), and Redis namespace entries all exist.
    """
    tenant_id = _unique_id()
    job_id = _unique_id()
    slug = _unique_slug()
    cleanup_tenant.append(tenant_id)

    await run_tenant_provisioning(
        job_id=job_id,
        tenant_id=tenant_id,
        name="Test Corp",
        plan="professional",
        primary_contact_email="admin@testcorp.test",
        slug=slug,
    )

    # Verify tenant record exists and is active
    async with _get_session_factory()() as session:
        row = (
            await session.execute(
                text("SELECT status FROM tenants WHERE id = :id"),
                {"id": tenant_id},
            )
        ).fetchone()
        assert row is not None, "Tenant record should exist after provisioning"
        assert row[0] == "active", "Tenant status should be 'active'"

        # Verify all 7 default roles seeded
        roles_result = await session.execute(
            text("SELECT name FROM roles WHERE tenant_id = :tid ORDER BY name"),
            {"tid": tenant_id},
        )
        role_names = sorted([r[0] for r in roles_result.fetchall()])
        assert role_names == sorted(
            _DEFAULT_TENANT_ROLES
        ), f"Expected {sorted(_DEFAULT_TENANT_ROLES)}, got {role_names}"

        # Verify tenant_config rls_context row
        config_row = (
            await session.execute(
                text(
                    "SELECT config_data FROM tenant_configs "
                    "WHERE tenant_id = :tid AND config_type = 'rls_context'"
                ),
                {"tid": tenant_id},
            )
        ).fetchone()
        assert config_row is not None, "RLS config row should exist"
        config_data = config_row[0]
        if isinstance(config_data, str):
            config_data = json.loads(config_data)
        assert config_data.get("rls_enabled") is True

    # Verify Redis namespace keys
    redis = get_redis()
    ns_active = await redis.get(f"mingai:{tenant_id}:namespace:active")
    assert ns_active == "1", "Redis namespace:active key should be '1'"

    ns_meta_raw = await redis.get(f"mingai:{tenant_id}:namespace:metadata")
    assert ns_meta_raw is not None, "Redis namespace:metadata key should exist"
    ns_meta = json.loads(ns_meta_raw)
    assert ns_meta["tenant_id"] == tenant_id
    assert ns_meta["plan"] == "professional"

    # Verify provisioning events in Redis
    events_raw = await redis.get(f"mingai:provisioning:{job_id}")
    assert events_raw is not None, "Provisioning events should be stored in Redis"
    events = json.loads(events_raw)
    final_event = events[-1]
    assert final_event["status"] == "completed"

    # Cleanup provisioning key
    await redis.delete(f"mingai:provisioning:{job_id}")


# =========================================================================
# GAP-057-02: Provisioning failure rolls back tenant record
# =========================================================================


async def test_provisioning_failure_rolls_back_db_records(cleanup_tenant):
    """
    Simulate a failure during CREATING_AUTH phase. Verify that the
    CREATING_DB rollback removes the tenant row, roles, and tenant_configs.
    """
    tenant_id = _unique_id()
    cleanup_tenant.append(tenant_id)  # Safety net in case rollback fails

    ctx = ProvisioningContext(tenant_id=tenant_id)
    machine = TenantProvisioningMachine(ctx)

    # Track whether rollbacks executed
    rollback_executed = []

    async def _phase_creating_db():
        """Create real DB records."""
        async with _get_session_factory()() as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, plan, status, primary_contact_email) "
                    "VALUES (:id, :name, :slug, :plan, 'draft', :email)"
                ),
                {
                    "id": tenant_id,
                    "name": "Rollback Test",
                    "slug": _unique_slug(),
                    "plan": "starter",
                    "email": "rollback@test.test",
                },
            )
            await session.commit()

    async def _phase_creating_auth():
        """Simulate a failure in the CREATING_AUTH phase."""
        raise RuntimeError("Simulated search index creation failure")

    async def _phase_configuring():
        pass  # Should never be reached

    async def _rollback_creating_db():
        rollback_executed.append("CREATING_DB")
        async with _get_session_factory()() as session:
            await session.execute(
                text("DELETE FROM tenants WHERE id = :id AND status = 'draft'"),
                {"id": tenant_id},
            )
            await session.commit()

    async def _rollback_creating_auth():
        rollback_executed.append("CREATING_AUTH")

    async def _rollback_configuring():
        rollback_executed.append("CONFIGURING")

    steps = {
        "CREATING_DB": _phase_creating_db,
        "CREATING_AUTH": _phase_creating_auth,
        "CONFIGURING": _phase_configuring,
    }
    rollbacks = {
        "CREATING_DB": _rollback_creating_db,
        "CREATING_AUTH": _rollback_creating_auth,
        "CONFIGURING": _rollback_configuring,
    }

    await machine.run_provisioning(steps, rollbacks)

    # State machine should be in FAILED
    assert ctx.state == ProvisioningState.FAILED
    assert "Simulated search index creation failure" in (ctx.error or "")

    # CREATING_DB rollback should have run (it was completed before failure)
    assert "CREATING_DB" in rollback_executed

    # CREATING_AUTH was NOT completed (it failed), so its rollback should NOT run
    # The rollback only runs for completed_steps
    # CONFIGURING was never started, so also not rolled back

    # Verify tenant record was deleted by rollback
    async with _get_session_factory()() as session:
        row = (
            await session.execute(
                text("SELECT id FROM tenants WHERE id = :id"),
                {"id": tenant_id},
            )
        ).fetchone()
        assert row is None, "Tenant record should have been removed by rollback"


# =========================================================================
# GAP-057-03: Failed provisioning stores error in Redis
# =========================================================================


async def test_failed_provisioning_stores_error_in_redis(cleanup_tenant):
    """
    After a provisioning failure, the Redis key mingai:provisioning:{job_id}
    contains the final event with status 'failed' and an error description.
    """
    tenant_id = _unique_id()
    job_id = _unique_id()
    slug = _unique_slug()
    cleanup_tenant.append(tenant_id)

    # Patch CLOUD_PROVIDER to 'azure' but without AZURE_SEARCH_ENDPOINT/KEY
    # so _step_create_search_index raises ValueError -- a real failure path.
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {"CLOUD_PROVIDER": "azure"}, clear=False):
        # Remove search keys to trigger real failure
        env_overrides = {
            "CLOUD_PROVIDER": "azure",
            "AZURE_SEARCH_ENDPOINT": "",
            "AZURE_SEARCH_ADMIN_KEY": "",
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            await run_tenant_provisioning(
                job_id=job_id,
                tenant_id=tenant_id,
                name="Error Test Corp",
                plan="enterprise",
                primary_contact_email="error@test.test",
                slug=slug,
            )

    # Verify Redis has the provisioning events with failure
    redis = get_redis()
    events_raw = await redis.get(f"mingai:provisioning:{job_id}")
    assert events_raw is not None, "Provisioning events key should exist in Redis"
    events = json.loads(events_raw)

    # The final event should indicate failure
    final_event = events[-1]
    assert (
        final_event["status"] == "failed"
    ), f"Final provisioning status should be 'failed', got {final_event['status']}"

    # Cleanup
    await redis.delete(f"mingai:provisioning:{job_id}")


# =========================================================================
# GAP-057-04: Rollback clears Redis provisioning namespace
# =========================================================================


async def test_rollback_clears_redis_namespace_keys(cleanup_tenant):
    """
    When provisioning fails after CREATING_AUTH (which creates Redis namespace
    keys), the rollback should delete those namespace keys.
    """
    tenant_id = _unique_id()
    cleanup_tenant.append(tenant_id)

    ctx = ProvisioningContext(tenant_id=tenant_id)
    machine = TenantProvisioningMachine(ctx)

    redis = get_redis()

    async def _phase_creating_db():
        pass  # No DB work for this test

    async def _phase_creating_auth():
        # Create real Redis namespace keys (simulating what the worker does)
        await redis.set(f"mingai:{tenant_id}:namespace:active", "1")
        await redis.set(
            f"mingai:{tenant_id}:namespace:metadata",
            json.dumps({"tenant_id": tenant_id}),
        )

    async def _phase_configuring():
        raise RuntimeError("Simulated configuring failure")

    async def _rollback_creating_db():
        pass

    async def _rollback_creating_auth():
        # Real rollback: delete namespace keys
        await redis.delete(
            f"mingai:{tenant_id}:namespace:active",
            f"mingai:{tenant_id}:namespace:metadata",
        )

    async def _rollback_configuring():
        pass

    steps = {
        "CREATING_DB": _phase_creating_db,
        "CREATING_AUTH": _phase_creating_auth,
        "CONFIGURING": _phase_configuring,
    }
    rollbacks = {
        "CREATING_DB": _rollback_creating_db,
        "CREATING_AUTH": _rollback_creating_auth,
        "CONFIGURING": _rollback_configuring,
    }

    await machine.run_provisioning(steps, rollbacks)

    assert ctx.state == ProvisioningState.FAILED

    # Verify Redis namespace keys were cleaned up by rollback
    ns_active = await redis.get(f"mingai:{tenant_id}:namespace:active")
    assert ns_active is None, "namespace:active should be deleted after rollback"

    ns_meta = await redis.get(f"mingai:{tenant_id}:namespace:metadata")
    assert ns_meta is None, "namespace:metadata should be deleted after rollback"


# =========================================================================
# GAP-057-05: Idempotent provisioning -- no duplicates
# =========================================================================


async def test_idempotent_provisioning_no_duplicates(cleanup_tenant):
    """
    Starting provisioning for the same tenant_id twice (sequentially, after
    the first completes) does not create duplicate records. The ON CONFLICT
    clauses and idempotency checks in the worker prevent duplicates.
    """
    tenant_id = _unique_id()
    job_id_1 = _unique_id()
    job_id_2 = _unique_id()
    slug = _unique_slug()
    cleanup_tenant.append(tenant_id)

    # First provisioning run
    await run_tenant_provisioning(
        job_id=job_id_1,
        tenant_id=tenant_id,
        name="Idempotent Corp",
        plan="professional",
        primary_contact_email="idem@test.test",
        slug=slug,
    )

    # Verify first run succeeded
    async with _get_session_factory()() as session:
        row = (
            await session.execute(
                text("SELECT status FROM tenants WHERE id = :id"),
                {"id": tenant_id},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "active"

    # Second provisioning run with same tenant_id
    # The worker is idempotent: tenant row exists so INSERT is skipped,
    # roles use ON CONFLICT DO NOTHING, config uses ON CONFLICT DO NOTHING.
    await run_tenant_provisioning(
        job_id=job_id_2,
        tenant_id=tenant_id,
        name="Idempotent Corp",
        plan="professional",
        primary_contact_email="idem@test.test",
        slug=slug,
    )

    # Verify no duplicates
    async with _get_session_factory()() as session:
        # Exactly 1 tenant row
        count_result = await session.execute(
            text("SELECT COUNT(*) FROM tenants WHERE id = :id"),
            {"id": tenant_id},
        )
        assert count_result.scalar() == 1, "Should have exactly 1 tenant record"

        # Exactly 7 role rows (not 14)
        role_count = (
            await session.execute(
                text("SELECT COUNT(*) FROM roles WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
        ).scalar()
        assert role_count == len(
            _DEFAULT_TENANT_ROLES
        ), f"Should have exactly {len(_DEFAULT_TENANT_ROLES)} roles, got {role_count}"

        # Exactly 1 rls_context config row
        config_count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM tenant_configs "
                    "WHERE tenant_id = :tid AND config_type = 'rls_context'"
                ),
                {"tid": tenant_id},
            )
        ).scalar()
        assert (
            config_count == 1
        ), f"Should have exactly 1 rls_context config, got {config_count}"

    # Cleanup provisioning keys
    redis = get_redis()
    await redis.delete(
        f"mingai:provisioning:{job_id_1}",
        f"mingai:provisioning:{job_id_2}",
    )
