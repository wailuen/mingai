"""
INFRA-020: Tenant provisioning async worker.

Executes the full 8-step tenant provisioning workflow using the
TenantProvisioningMachine state machine for lifecycle management and
rollback guarantees.

Steps mapped to state machine phases:

  CREATING_DB:
    Step 1 — Create tenant record in PostgreSQL
    Step 2 — Seed 7 default system roles for the tenant
    Step 3 — Apply RLS policy context row in tenant_configs

  CREATING_AUTH:
    Step 4 — Create search index (cloud-agnostic via CLOUD_PROVIDER)
    Step 5 — Create object storage bucket with tenant-scoped prefix
    Step 6 — Initialize Redis key namespace (tombstone + metadata keys)

  CONFIGURING:
    Step 7 — Create Stripe customer record (if STRIPE_SECRET_KEY configured)
    Step 8 — Send invite email to tenant admin contact

SLA: all steps complete within 600 seconds (enforced by TenantProvisioningMachine).
Cloud-agnostic: CLOUD_PROVIDER controls external resource creation.
Progress events written to Redis: mingai:provisioning:{job_id} (list of dicts)
for consumption by the SSE endpoint (API-025).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text

from app.core.redis_client import get_redis
from app.core.session import async_session_factory
from app.modules.tenants.provisioning import (
    ProvisioningContext,
    ProvisioningState,
    TenantProvisioningMachine,
)

logger = structlog.get_logger(__name__)

# Default system roles seeded for every new tenant
_DEFAULT_TENANT_ROLES = [
    "tenant_admin",
    "end_user",
    "kb_editor",
    "kb_viewer",
    "analytics_viewer",
    "agent_builder",
    "billing_manager",
]

# Redis key TTL for provisioning events (24 hours — enough for any SSE consumer)
_PROVISIONING_EVENTS_TTL_SECS = 86_400


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_tenant_provisioning(
    *,
    job_id: str,
    tenant_id: str,
    name: str,
    plan: str,
    primary_contact_email: str,
    slug: str,
) -> None:
    """
    Execute the 8-step tenant provisioning workflow.

    Writes step events to Redis (mingai:provisioning:{job_id}) as each
    step completes or fails. Idempotent for the DB step — if the tenant
    row already exists (created by the API before launching the worker),
    that step is skipped without error.

    Args:
        job_id: Unique identifier for this provisioning job (UUID).
        tenant_id: Tenant ID to provision.
        name: Display name.
        plan: Subscription plan (e.g., "professional").
        primary_contact_email: Tenant admin email address.
        slug: URL-safe slug (UNIQUE in tenants table).
    """
    ctx = ProvisioningContext(tenant_id=tenant_id)
    machine = TenantProvisioningMachine(ctx)
    events: list[dict] = []

    def _record(step: str, status: str, detail: str = "") -> None:
        event = {
            "step": step,
            "status": status,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        events.append(event)
        logger.info(
            "provisioning_step_event",
            job_id=job_id,
            tenant_id=tenant_id,
            step=step,
            status=status,
        )

    async def _flush_events() -> None:
        """Persist current event list to Redis for SSE consumption."""
        redis = get_redis()
        key = f"mingai:provisioning:{job_id}"
        await redis.setex(key, _PROVISIONING_EVENTS_TTL_SECS, json.dumps(events))

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    async def _step_create_db_record():
        _record("create_tenant_record", "started")
        async with async_session_factory() as session:
            existing = (
                await session.execute(
                    text("SELECT id FROM tenants WHERE id = :id"),
                    {"id": tenant_id},
                )
            ).fetchone()

            if existing is None:
                await session.execute(
                    text(
                        "INSERT INTO tenants "
                        "(id, name, slug, plan, status, primary_contact_email) "
                        "VALUES (:id, :name, :slug, :plan, 'draft', :email)"
                    ),
                    {
                        "id": tenant_id,
                        "name": name,
                        "slug": slug,
                        "plan": plan,
                        "email": primary_contact_email,
                    },
                )
                await session.commit()
                _record("create_tenant_record", "completed", "tenant row created")
            else:
                _record(
                    "create_tenant_record",
                    "completed",
                    "tenant row already exists — skipped",
                )
        await _flush_events()

    async def _rollback_create_db_record():
        """Remove tenant row if it was created by this job."""
        async with async_session_factory() as session:
            await session.execute(
                text("DELETE FROM tenants WHERE id = :id AND status = 'draft'"),
                {"id": tenant_id},
            )
            await session.commit()
        logger.info("provisioning_rollback_tenant_record", tenant_id=tenant_id)

    async def _step_seed_roles():
        _record("seed_default_roles", "started")
        async with async_session_factory() as session:
            for role_name in _DEFAULT_TENANT_ROLES:
                await session.execute(
                    text(
                        "INSERT INTO roles (id, tenant_id, name, created_at) "
                        "VALUES (:id, :tenant_id, :name, NOW()) "
                        "ON CONFLICT (tenant_id, name) DO NOTHING"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "tenant_id": tenant_id,
                        "name": role_name,
                    },
                )
            await session.commit()
        _record(
            "seed_default_roles",
            "completed",
            f"{len(_DEFAULT_TENANT_ROLES)} roles seeded",
        )
        await _flush_events()

    async def _rollback_seed_roles():
        async with async_session_factory() as session:
            await session.execute(
                text("DELETE FROM roles WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            await session.commit()
        logger.info("provisioning_rollback_roles", tenant_id=tenant_id)

    async def _step_apply_rls_config():
        _record("apply_rls_config", "started")
        async with async_session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO tenant_configs "
                    "(id, tenant_id, config_type, config_data) "
                    "VALUES (:id, :tenant_id, 'rls_context', CAST(:data AS jsonb)) "
                    "ON CONFLICT (tenant_id, config_type) DO NOTHING"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "data": json.dumps({"rls_enabled": True}),
                },
            )
            await session.commit()
        _record("apply_rls_config", "completed", "rls_context config row created")
        await _flush_events()

    async def _rollback_apply_rls_config():
        async with async_session_factory() as session:
            await session.execute(
                text(
                    "DELETE FROM tenant_configs "
                    "WHERE tenant_id = :tenant_id AND config_type = 'rls_context'"
                ),
                {"tenant_id": tenant_id},
            )
            await session.commit()

    async def _step_create_search_index():
        _record("create_search_index", "started")
        cloud = os.environ.get("CLOUD_PROVIDER", "local").strip().lower()
        if cloud in ("local", "aws", "gcp"):
            await _create_pgvector_index(tenant_id)
            _record(
                "create_search_index",
                "completed",
                "pgvector partial HNSW index created",
            )
        else:
            logger.warning(
                "provisioning_unknown_cloud_provider",
                cloud_provider=cloud,
                tenant_id=tenant_id,
            )
            _record(
                "create_search_index",
                "skipped",
                f"unknown provider '{cloud}' — search index not created",
            )
        await _flush_events()

    async def _rollback_create_search_index():
        cloud = os.environ.get("CLOUD_PROVIDER", "local").strip().lower()
        try:
            await _delete_pgvector_index(tenant_id)
        except Exception as exc:
            logger.warning(
                "provisioning_rollback_search_index_failed",
                tenant_id=tenant_id,
                cloud_provider=cloud,
                error=str(exc),
            )
        logger.info(
            "provisioning_rollback_search_index",
            tenant_id=tenant_id,
            cloud_provider=cloud,
        )

    async def _step_create_storage_bucket():
        _record("create_storage_bucket", "started")
        cloud = os.environ.get("CLOUD_PROVIDER", "local").strip().lower()
        if cloud == "local":
            import pathlib

            base = os.environ.get("LOCAL_STORAGE_PATH", "/tmp/mingai_storage")
            bucket_path = pathlib.Path(base) / tenant_id
            bucket_path.mkdir(parents=True, exist_ok=True)
            _record("create_storage_bucket", "completed", f"local dir: {bucket_path}")
        else:
            # AWS S3 / Azure Blob / GCP GCS: prefix-based isolation within shared bucket
            bucket_prefix = f"tenants/{tenant_id}/"
            _record(
                "create_storage_bucket",
                "completed",
                f"storage prefix reserved: {bucket_prefix}",
            )
        await _flush_events()

    async def _rollback_create_storage_bucket():
        cloud = os.environ.get("CLOUD_PROVIDER", "local").strip().lower()
        if cloud == "local":
            import shutil
            import pathlib

            base = os.environ.get("LOCAL_STORAGE_PATH", "/tmp/mingai_storage")
            bucket_path = pathlib.Path(base) / tenant_id
            if bucket_path.exists():
                shutil.rmtree(bucket_path, ignore_errors=True)
        logger.info("provisioning_rollback_storage_bucket", tenant_id=tenant_id)

    async def _step_init_redis_namespace():
        _record("init_redis_namespace", "started")
        redis = get_redis()
        # Write a tombstone key that signals this tenant's namespace is active
        namespace_key = f"mingai:{tenant_id}:namespace:active"
        metadata_key = f"mingai:{tenant_id}:namespace:metadata"
        metadata = json.dumps(
            {
                "tenant_id": tenant_id,
                "plan": plan,
                "provisioned_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        await redis.set(namespace_key, "1")
        await redis.set(metadata_key, metadata)
        _record("init_redis_namespace", "completed", "namespace keys created")
        await _flush_events()

    async def _rollback_init_redis_namespace():
        redis = get_redis()
        await redis.delete(
            f"mingai:{tenant_id}:namespace:active",
            f"mingai:{tenant_id}:namespace:metadata",
        )
        logger.info("provisioning_rollback_redis_namespace", tenant_id=tenant_id)

    async def _step_create_stripe_customer():
        _record("create_stripe_customer", "started")
        stripe_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
        if not stripe_key:
            _record(
                "create_stripe_customer",
                "completed",
                "STRIPE_SECRET_KEY not set — Stripe customer creation skipped",
            )
            await _flush_events()
            return

        try:
            import stripe  # type: ignore[import-not-found]

            customer = stripe.Customer.create(
                api_key=stripe_key,
                email=primary_contact_email,
                name=name,
                metadata={"tenant_id": tenant_id, "plan": plan},
            )
            # Store Stripe customer ID in tenant_configs
            async with async_session_factory() as session:
                await session.execute(
                    text(
                        "INSERT INTO tenant_configs "
                        "(id, tenant_id, config_type, config_data) "
                        "VALUES (:id, :tenant_id, 'stripe', CAST(:data AS jsonb)) "
                        "ON CONFLICT (tenant_id, config_type) DO UPDATE "
                        "SET config_data = CAST(:data AS jsonb)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "tenant_id": tenant_id,
                        "data": json.dumps({"customer_id": customer["id"]}),
                    },
                )
                await session.commit()
            _record(
                "create_stripe_customer",
                "completed",
                f"Stripe customer {customer['id']} created",
            )
        except Exception as exc:
            # Stripe errors are non-fatal: log and continue
            logger.warning(
                "provisioning_stripe_customer_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )
            _record(
                "create_stripe_customer",
                "warning",
                "Stripe customer creation failed — billing setup incomplete",
            )
        await _flush_events()

    async def _rollback_create_stripe_customer():
        # Stripe customer deletion is handled by billing ops; worker does not delete
        logger.info("provisioning_rollback_stripe_customer_noop", tenant_id=tenant_id)

    async def _step_send_invite_email():
        _record("send_invite_email", "started")
        smtp_host = os.environ.get("SMTP_HOST", "").strip()
        if not smtp_host:
            logger.warning(
                "provisioning_invite_email_skipped",
                tenant_id=tenant_id,
                reason="SMTP_HOST not configured",
            )
            _record(
                "send_invite_email",
                "completed",
                "SMTP_HOST not configured — invite email skipped",
            )
            await _flush_events()
            return

        try:
            import smtplib
            from email.mime.text import MIMEText

            smtp_port = int(os.environ.get("SMTP_PORT", "587"))
            smtp_user = os.environ.get("SMTP_USER", "").strip()
            smtp_pass = os.environ.get("SMTP_PASS", "").strip()
            smtp_from = os.environ.get("SMTP_FROM", smtp_user)

            body = (
                f"Hello,\n\n"
                f"Your mingai workspace '{name}' has been provisioned.\n\n"
                f"Plan: {plan}\n"
                f"Tenant ID: {tenant_id}\n\n"
                f"Please log in to complete your setup.\n\n"
                f"Regards,\nmingai Platform Team"
            )
            msg = MIMEText(body)
            msg["Subject"] = f"Your mingai workspace '{name}' is ready"
            msg["From"] = smtp_from
            msg["To"] = primary_contact_email

            with smtplib.SMTP(smtp_host, smtp_port) as smtp_conn:
                smtp_conn.ehlo()
                if smtp_user and smtp_pass:
                    smtp_conn.starttls()
                    smtp_conn.login(smtp_user, smtp_pass)
                smtp_conn.sendmail(smtp_from, [primary_contact_email], msg.as_string())

            _email_domain = (
                primary_contact_email.split("@", 1)[-1]
                if "@" in primary_contact_email
                else "unknown"
            )
            _record(
                "send_invite_email",
                "completed",
                f"invite sent to *@{_email_domain}",
            )
        except Exception as exc:
            # Email failure is non-fatal — provisioning still succeeds
            logger.warning(
                "provisioning_invite_email_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )
            _record(
                "send_invite_email",
                "warning",
                "email delivery failed — invite not sent",
            )
        await _flush_events()

    async def _rollback_send_invite_email():
        # Emails cannot be unsent; no-op rollback
        logger.info("provisioning_rollback_invite_email_noop", tenant_id=tenant_id)

    async def _step_activate_tenant():
        _record("activate_tenant", "started")
        async with async_session_factory() as session:
            await session.execute(
                text("UPDATE tenants SET status = 'active' WHERE id = :id"),
                {"id": tenant_id},
            )
            await session.commit()
        _record("activate_tenant", "completed", "tenant status set to active")
        await _flush_events()

    # ------------------------------------------------------------------
    # Map 8 sub-steps to 3 state machine phase callables
    # ------------------------------------------------------------------

    async def _phase_creating_db():
        await _step_create_db_record()
        await _step_seed_roles()
        await _step_apply_rls_config()

    async def _phase_creating_auth():
        await _step_create_search_index()
        await _step_create_storage_bucket()
        await _step_init_redis_namespace()

    async def _phase_configuring():
        await _step_create_stripe_customer()
        await _step_send_invite_email()
        await _step_activate_tenant()

    async def _rollback_creating_db():
        await _rollback_apply_rls_config()
        await _rollback_seed_roles()
        await _rollback_create_db_record()

    async def _rollback_creating_auth():
        await _rollback_init_redis_namespace()
        await _rollback_create_storage_bucket()
        await _rollback_create_search_index()

    async def _rollback_configuring():
        await _rollback_send_invite_email()
        await _rollback_create_stripe_customer()
        # tenant record stays — keep in FAILED state for operator review

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

    logger.info(
        "provisioning_worker_started",
        job_id=job_id,
        tenant_id=tenant_id,
        plan=plan,
    )

    await machine.run_provisioning(steps, rollbacks)

    # Write final state event
    final_status = "completed" if ctx.state == ProvisioningState.ACTIVE else "failed"
    _record(
        "provisioning_finished",
        final_status,
        ctx.error or "all steps completed successfully",
    )
    await _flush_events()

    logger.info(
        "provisioning_worker_finished",
        job_id=job_id,
        tenant_id=tenant_id,
        final_state=ctx.state.value,
        error=ctx.error,
    )


# ---------------------------------------------------------------------------
# pgvector helpers (per-tenant partial HNSW index on search_chunks)
# ---------------------------------------------------------------------------


async def _create_pgvector_index(tenant_id: str) -> None:
    """
    Create a per-tenant partial HNSW index on search_chunks for this tenant.

    Uses a raw asyncpg autocommit connection because CREATE INDEX CONCURRENTLY
    cannot run inside a transaction block (which SQLAlchemy sessions use).

    Index name is SHA256-derived to avoid UUID truncation collisions:
      idx_sc_embedding_t_{sha256(tenant_id)[:20]}
    """
    import asyncpg

    short = hashlib.sha256(tenant_id.encode()).hexdigest()[:20]
    # index_name uses f-string DDL because PostgreSQL DDL identifiers cannot be
    # parameterized ($1). SHA256 output is always [0-9a-f]{20} — the assertion
    # below makes this safety property explicit and catches any future regressions.
    assert re.fullmatch(r"[0-9a-f]{20}", short), f"Unexpected index suffix: {short!r}"
    index_name = f"idx_sc_embedding_t_{short}"

    # Use raw asyncpg (autocommit) for DDL — SQLAlchemy sessions use transactions
    # which would prevent CREATE INDEX CONCURRENTLY
    dsn = os.environ["DATABASE_URL"]
    # SQLAlchemy uses postgresql+asyncpg:// — strip the dialect prefix for asyncpg
    raw_dsn = dsn.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )

    conn = await asyncpg.connect(raw_dsn)
    try:
        await conn.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name}
            ON search_chunks USING hnsw(embedding halfvec_cosine_ops)
            WITH (m = 16, ef_construction = 128)
            WHERE tenant_id = $1::uuid
            """,
            tenant_id,
        )
    finally:
        await conn.close()

    # Register in search_index_registry (uses RLS-aware session)
    async with async_session_factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO search_index_registry
                    (tenant_id, index_id, source_type, display_name)
                VALUES
                    (:tenant_id, :index_id, 'tenant', 'Tenant Search Index')
                ON CONFLICT (tenant_id, index_id) DO NOTHING
                """
            ),
            {
                "tenant_id": tenant_id,
                "index_id": f"tenant_{tenant_id}",
            },
        )
        await session.commit()

    logger.info(
        "pgvector_index_created",
        tenant_id=tenant_id,
        index_name=index_name,
    )


async def _delete_pgvector_index(tenant_id: str) -> None:
    """
    Drop the per-tenant partial HNSW index and clean all search data for this tenant.

    Errors during DROP INDEX are logged as warnings — the index may already be
    gone on rollback scenarios.
    """
    import asyncpg

    short = hashlib.sha256(tenant_id.encode()).hexdigest()[:20]
    # index_name uses f-string DDL because PostgreSQL DDL identifiers cannot be
    # parameterized ($1). SHA256 output is always [0-9a-f]{20} — the assertion
    # makes this safety property explicit and enforced.
    assert re.fullmatch(r"[0-9a-f]{20}", short), f"Unexpected index suffix: {short!r}"
    index_name = f"idx_sc_embedding_t_{short}"

    dsn = os.environ["DATABASE_URL"]
    raw_dsn = dsn.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )

    conn = await asyncpg.connect(raw_dsn)
    try:
        await conn.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")
    except Exception as exc:
        logger.warning(
            "pgvector_index_drop_failed",
            tenant_id=tenant_id,
            index_name=index_name,
            error=str(exc),
        )
    finally:
        await conn.close()

    # Clean all search data for this tenant
    async with async_session_factory() as session:
        await session.execute(
            text("DELETE FROM search_chunks WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await session.execute(
            text("DELETE FROM search_index_registry WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await session.commit()

    logger.info(
        "pgvector_index_deleted",
        tenant_id=tenant_id,
        index_name=index_name,
    )
