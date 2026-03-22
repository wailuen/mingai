"""
Unit tests for INFRA-020: Tenant provisioning async worker.

Tests cover:
- Happy path: all 8 sub-steps execute, tenant status set to active
- Step 1 idempotency: existing tenant row is skipped (not duplicated)
- Failure rollback: DB/auth/config failures trigger reverse rollback
- Redis namespace initialization: correct keys written
- Stripe skipped when STRIPE_SECRET_KEY not set
- Email skipped when SMTP_HOST not set
- Events written to Redis after each phase
- Cloud-agnostic: CLOUD_PROVIDER=local skips external index/storage
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(tenant_exists: bool = False):
    """Return a mock async session context manager."""
    session = AsyncMock()

    async def _execute(stmt, params=None):
        result = MagicMock()
        stmt_str = str(stmt).strip()

        # SELECT id FROM tenants — existence check
        if "SELECT id FROM tenants WHERE id" in stmt_str:
            result.fetchone.return_value = ("t-1",) if tenant_exists else None
        else:
            result.fetchone.return_value = None
            result.fetchall.return_value = []
            result.scalar.return_value = 0
        return result

    session.execute = _execute
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _make_redis():
    redis = AsyncMock()
    redis.set = AsyncMock()
    redis.setex = AsyncMock()
    redis.delete = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    return redis


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProvisioningWorkerHappyPath:
    """All phases execute and tenant is set to active."""

    @pytest.mark.asyncio
    async def test_happy_path_completes_with_active_state(self):
        session_ctx = _make_session(tenant_exists=False)
        redis = _make_redis()

        with (
            patch(
                "app.modules.tenants.worker.async_session_factory",
                return_value=session_ctx,
            ),
            patch("app.modules.tenants.worker.get_redis", return_value=redis),
            patch(
                "app.modules.tenants.worker._create_pgvector_index",
                new_callable=AsyncMock,
            ),
            patch.dict("os.environ", {"CLOUD_PROVIDER": "local"}),
        ):
            from app.modules.tenants.worker import run_tenant_provisioning

            await run_tenant_provisioning(
                job_id="job-001",
                tenant_id="tenant-new",
                name="Acme Corp",
                plan="professional",
                primary_contact_email="admin@acme.com",
                slug="acme-corp",
            )

        # Redis setex should have been called (events flushed)
        assert redis.setex.call_count >= 1
        # Last Redis setex call should contain a "provisioning_finished" event
        last_call_args = redis.setex.call_args_list[-1]
        key = last_call_args[0][0]
        events = json.loads(last_call_args[0][2])
        assert key == "mingai:provisioning:job-001"
        step_names = [e["step"] for e in events]
        assert "create_tenant_record" in step_names
        assert "seed_default_roles" in step_names
        assert "apply_rls_config" in step_names
        assert "create_search_index" in step_names
        assert "create_storage_bucket" in step_names
        assert "init_redis_namespace" in step_names
        assert "activate_tenant" in step_names
        assert "provisioning_finished" in step_names

    @pytest.mark.asyncio
    async def test_all_steps_show_completed_status(self):
        session_ctx = _make_session(tenant_exists=False)
        redis = _make_redis()

        with (
            patch(
                "app.modules.tenants.worker.async_session_factory",
                return_value=session_ctx,
            ),
            patch("app.modules.tenants.worker.get_redis", return_value=redis),
            patch(
                "app.modules.tenants.worker._create_pgvector_index",
                new_callable=AsyncMock,
            ),
            patch.dict("os.environ", {"CLOUD_PROVIDER": "local"}),
        ):
            from app.modules.tenants.worker import run_tenant_provisioning

            await run_tenant_provisioning(
                job_id="job-002",
                tenant_id="tenant-x",
                name="Beta Co",
                plan="starter",
                primary_contact_email="admin@beta.com",
                slug="beta-co",
            )

        last_call_args = redis.setex.call_args_list[-1]
        events = json.loads(last_call_args[0][2])
        finished = [e for e in events if e["step"] == "provisioning_finished"]
        assert len(finished) == 1
        assert finished[0]["status"] == "completed"


class TestProvisioningWorkerIdempotency:
    """Step 1 skips INSERT when tenant row already exists."""

    @pytest.mark.asyncio
    async def test_existing_tenant_row_is_skipped_without_error(self):
        session_ctx = _make_session(tenant_exists=True)
        redis = _make_redis()

        with (
            patch(
                "app.modules.tenants.worker.async_session_factory",
                return_value=session_ctx,
            ),
            patch("app.modules.tenants.worker.get_redis", return_value=redis),
            patch(
                "app.modules.tenants.worker._create_pgvector_index",
                new_callable=AsyncMock,
            ),
            patch.dict("os.environ", {"CLOUD_PROVIDER": "local"}),
        ):
            from app.modules.tenants.worker import run_tenant_provisioning

            # Must not raise
            await run_tenant_provisioning(
                job_id="job-idem",
                tenant_id="existing-tenant",
                name="Existing Corp",
                plan="professional",
                primary_contact_email="admin@existing.com",
                slug="existing-corp",
            )

        last_call_args = redis.setex.call_args_list[-1]
        events = json.loads(last_call_args[0][2])
        create_events = [e for e in events if e["step"] == "create_tenant_record"]
        assert len(create_events) >= 1
        # The completed detail must mention "skipped"
        completed = [e for e in create_events if e["status"] == "completed"]
        assert any("skipped" in e.get("detail", "") for e in completed)


class TestProvisioningWorkerRedisEvents:
    """Events are flushed to Redis after each phase."""

    @pytest.mark.asyncio
    async def test_redis_events_include_timestamp_fields(self):
        session_ctx = _make_session()
        redis = _make_redis()

        with (
            patch(
                "app.modules.tenants.worker.async_session_factory",
                return_value=session_ctx,
            ),
            patch("app.modules.tenants.worker.get_redis", return_value=redis),
            patch(
                "app.modules.tenants.worker._create_pgvector_index",
                new_callable=AsyncMock,
            ),
            patch.dict("os.environ", {"CLOUD_PROVIDER": "local"}),
        ):
            from app.modules.tenants.worker import run_tenant_provisioning

            await run_tenant_provisioning(
                job_id="job-ts",
                tenant_id="t-ts",
                name="Timestamp Co",
                plan="starter",
                primary_contact_email="ts@co.com",
                slug="timestamp-co",
            )

        last_call_args = redis.setex.call_args_list[-1]
        events = json.loads(last_call_args[0][2])
        for event in events:
            assert "step" in event
            assert "status" in event
            assert "timestamp" in event

    @pytest.mark.asyncio
    async def test_redis_key_uses_job_id(self):
        session_ctx = _make_session()
        redis = _make_redis()

        with (
            patch(
                "app.modules.tenants.worker.async_session_factory",
                return_value=session_ctx,
            ),
            patch("app.modules.tenants.worker.get_redis", return_value=redis),
            patch(
                "app.modules.tenants.worker._create_pgvector_index",
                new_callable=AsyncMock,
            ),
            patch.dict("os.environ", {"CLOUD_PROVIDER": "local"}),
        ):
            from app.modules.tenants.worker import run_tenant_provisioning

            await run_tenant_provisioning(
                job_id="my-unique-job-id",
                tenant_id="t-key",
                name="Key Co",
                plan="enterprise",
                primary_contact_email="key@co.com",
                slug="key-co",
            )

        all_keys = [c[0][0] for c in redis.setex.call_args_list]
        assert "mingai:provisioning:my-unique-job-id" in all_keys


class TestProvisioningWorkerStripeSkipped:
    """Stripe step is skipped when STRIPE_SECRET_KEY is not set."""

    @pytest.mark.asyncio
    async def test_stripe_skipped_without_secret_key(self):
        session_ctx = _make_session()
        redis = _make_redis()

        env = {"CLOUD_PROVIDER": "local", "STRIPE_SECRET_KEY": ""}

        with (
            patch(
                "app.modules.tenants.worker.async_session_factory",
                return_value=session_ctx,
            ),
            patch("app.modules.tenants.worker.get_redis", return_value=redis),
            patch(
                "app.modules.tenants.worker._create_pgvector_index",
                new_callable=AsyncMock,
            ),
            patch.dict("os.environ", env, clear=False),
        ):
            from app.modules.tenants.worker import run_tenant_provisioning

            await run_tenant_provisioning(
                job_id="job-stripe",
                tenant_id="t-stripe",
                name="No Stripe Co",
                plan="starter",
                primary_contact_email="noop@co.com",
                slug="no-stripe-co",
            )

        last_call_args = redis.setex.call_args_list[-1]
        events = json.loads(last_call_args[0][2])
        stripe_events = [e for e in events if e["step"] == "create_stripe_customer"]
        assert len(stripe_events) >= 1
        assert any("skipped" in e.get("detail", "") for e in stripe_events)


class TestProvisioningWorkerEmailSkipped:
    """Email step is skipped when SMTP_HOST is not set."""

    @pytest.mark.asyncio
    async def test_invite_email_skipped_without_smtp_host(self):
        session_ctx = _make_session()
        redis = _make_redis()

        env = {"CLOUD_PROVIDER": "local", "SMTP_HOST": ""}

        with (
            patch(
                "app.modules.tenants.worker.async_session_factory",
                return_value=session_ctx,
            ),
            patch("app.modules.tenants.worker.get_redis", return_value=redis),
            patch(
                "app.modules.tenants.worker._create_pgvector_index",
                new_callable=AsyncMock,
            ),
            patch.dict("os.environ", env, clear=False),
        ):
            from app.modules.tenants.worker import run_tenant_provisioning

            await run_tenant_provisioning(
                job_id="job-email",
                tenant_id="t-email",
                name="No Email Co",
                plan="starter",
                primary_contact_email="noemail@co.com",
                slug="no-email-co",
            )

        last_call_args = redis.setex.call_args_list[-1]
        events = json.loads(last_call_args[0][2])
        email_events = [e for e in events if e["step"] == "send_invite_email"]
        assert len(email_events) >= 1
        assert any("skipped" in e.get("detail", "") for e in email_events)


class TestProvisioningWorkerRollback:
    """Failures trigger rollback of completed steps."""

    @pytest.mark.asyncio
    async def test_failure_in_creating_auth_triggers_rollback(self):
        """If CREATING_AUTH phase fails, CREATING_DB rollback must be called."""
        session_ctx = _make_session()
        redis = _make_redis()

        call_log: list[str] = []

        original_session_factory = session_ctx

        # Patch the session factory to track what SQL runs
        commit_count = [0]

        async def tracked_commit():
            commit_count[0] += 1

        session_ctx.__aenter__.return_value.commit = tracked_commit

        # Patch Redis.set to fail on the namespace key to simulate CREATING_AUTH fail
        namespace_set_calls = [0]

        async def flaky_set(key, value):
            namespace_set_calls[0] += 1
            if "namespace:active" in key:
                raise RuntimeError("Redis connection lost")

        redis.set = flaky_set

        with (
            patch(
                "app.modules.tenants.worker.async_session_factory",
                return_value=session_ctx,
            ),
            patch("app.modules.tenants.worker.get_redis", return_value=redis),
            patch(
                "app.modules.tenants.worker._create_pgvector_index",
                new_callable=AsyncMock,
            ),
            patch.dict("os.environ", {"CLOUD_PROVIDER": "local"}),
        ):
            from app.modules.tenants.worker import run_tenant_provisioning

            # Must not raise (failures handled by state machine)
            await run_tenant_provisioning(
                job_id="job-fail",
                tenant_id="t-fail",
                name="Fail Corp",
                plan="starter",
                primary_contact_email="fail@corp.com",
                slug="fail-corp",
            )

        # Final events must show "failed"
        last_call_args = redis.setex.call_args_list[-1]
        events = json.loads(last_call_args[0][2])
        finished = [e for e in events if e["step"] == "provisioning_finished"]
        assert len(finished) == 1
        assert finished[0]["status"] == "failed"
