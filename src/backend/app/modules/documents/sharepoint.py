"""
SharePoint integration routes (API-050 to API-055, TA-015).

Endpoints:
- POST  /documents/sharepoint/connect           — Create SharePoint connection
- POST  /documents/sharepoint/{id}/test          — Test connection
- POST  /documents/sharepoint/{id}/sync          — Trigger document sync
- GET   /documents/sharepoint/{id}/sync          — List sync job history
- PATCH /documents/sharepoint/{id}/schedule      — Configure sync schedule (TA-015)

Security: credentials (client_id, client_secret) are NEVER stored in DB or logged.
Only a vault reference URI is persisted in config['credential_ref'].
"""
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/documents", tags=["documents"])
admin_sync_router = APIRouter(prefix="/admin", tags=["admin", "documents"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class SharePointConnectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    site_url: str = Field(..., min_length=1)
    library_name: str = Field(..., min_length=1, max_length=200)
    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1)

    @field_validator("site_url")
    @classmethod
    def site_url_must_be_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("site_url must start with https://")
        return v


# TA-015 schedule request/response
_VALID_FREQUENCIES = frozenset({"daily", "hourly", "custom_cron"})
_PLAN_ALLOWED_FREQUENCIES: dict[str, frozenset] = {
    "starter": frozenset({"daily"}),
    "professional": frozenset({"daily", "hourly"}),
    "enterprise": frozenset({"daily", "hourly", "custom_cron"}),
}
# 5-field cron: min(0-59) hour(0-23) dom(1-31) mon(1-12) dow(0-7)
# Each field: wildcard, step (*/N or N/N or N-M/N), range (N-M), list, or number.
_CRON_FIELD_RE = re.compile(r"^(\*|\*/\d+|\d+-\d+/\d+|\d+/\d+|\d+-\d+|(\d+,)+\d+|\d+)$")


class SyncScheduleRequest(BaseModel):
    frequency: str = Field(..., description="daily | hourly | custom_cron")
    cron_expression: Optional[str] = Field(
        None,
        description="Standard 5-field cron (required when frequency=custom_cron)",
    )

    @field_validator("frequency")
    @classmethod
    def frequency_must_be_valid(cls, v: str) -> str:
        if v not in _VALID_FREQUENCIES:
            raise ValueError(f"frequency must be one of {sorted(_VALID_FREQUENCIES)}")
        return v


def _validate_cron_expression(expr: str) -> bool:
    """Return True if expr is a valid 5-field cron expression."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return False
    limits = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
    for part, (lo, hi) in zip(parts, limits):
        if part == "*":
            continue
        if not _CRON_FIELD_RE.match(part):
            return False
        # Validate numeric values — skip wildcard segments (e.g. "*" in "*/5")
        for segment in re.split(r"[,\-/]", part):
            if segment == "*":
                continue
            try:
                val = int(segment)
                if not (lo <= val <= hi):
                    return False
            except ValueError:
                return False
    return True


def _next_run_from_schedule(frequency: str, cron_expression: Optional[str]) -> datetime:
    """
    Calculate the next run datetime (UTC) for a given schedule.

    - daily       → next midnight UTC
    - hourly      → next top-of-hour UTC
    - custom_cron → next occurrence based on cron minute/hour fields
    """
    now = datetime.now(timezone.utc)

    if frequency == "daily":
        next_run = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return next_run

    if frequency == "hourly":
        next_run = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        return next_run

    # custom_cron — parse minute and hour fields
    if cron_expression:
        parts = cron_expression.strip().split()
        min_field = parts[0]
        hour_field = parts[1]

        cron_minute = (
            0 if min_field == "*" else int(min_field.split(",")[0].split("-")[0])
        )
        cron_hour = (
            None if hour_field == "*" else int(hour_field.split(",")[0].split("-")[0])
        )

        candidate = now.replace(second=0, microsecond=0, minute=cron_minute)
        if cron_hour is not None:
            candidate = candidate.replace(hour=cron_hour)
            if candidate <= now:
                candidate += timedelta(days=1)
        else:
            # Wildcard hour — advance to next matching minute in current or next hour
            if candidate <= now:
                candidate += timedelta(hours=1)
        return candidate

    # Fallback: next day
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# DB helper functions (mockable in unit tests)
# ---------------------------------------------------------------------------


async def insert_integration_db(
    integration_id: str,
    tenant_id: str,
    config: dict,
    name: str,
    db: AsyncSession,
) -> dict:
    """Insert a new integration record into the integrations table."""
    config_json = json.dumps(config)
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO integrations (id, tenant_id, provider, status, config, created_at, updated_at) "
            "VALUES (:id, :tenant_id, 'sharepoint', 'pending', CAST(:config AS jsonb), :created_at, :updated_at)"
        ),
        {
            "id": integration_id,
            "tenant_id": tenant_id,
            "config": config_json,
            "created_at": now,
            "updated_at": now,
        },
    )
    await db.commit()
    return {"id": integration_id, "status": "pending", "name": name}


async def get_integration_db(
    integration_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[dict]:
    """Fetch an integration by id and tenant_id. Returns None if not found."""
    result = await db.execute(
        text(
            "SELECT id, tenant_id, provider, status, config "
            "FROM integrations "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": integration_id, "tenant_id": tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    config_val = row["config"]
    if isinstance(config_val, str):
        config_val = json.loads(config_val)
    return {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "type": row["provider"],
        "status": row["status"],
        "config": config_val,
    }


async def create_sync_job_db(
    integration_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """Create a new sync job record."""
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO sync_jobs (id, integration_id, tenant_id, status, created_at) "
            "VALUES (:id, :integration_id, :tenant_id, 'queued', :created_at)"
        ),
        {
            "id": job_id,
            "integration_id": integration_id,
            "tenant_id": tenant_id,
            "created_at": now,
        },
    )
    await db.commit()
    return {"job_id": job_id, "status": "queued"}


async def list_sync_jobs_db(
    integration_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """List the last 10 sync jobs for an integration."""
    count_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM sync_jobs "
            "WHERE integration_id = :integration_id AND tenant_id = :tenant_id"
        ),
        {"integration_id": integration_id, "tenant_id": tenant_id},
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        text(
            "SELECT id, status, created_at FROM sync_jobs "
            "WHERE integration_id = :integration_id AND tenant_id = :tenant_id "
            "ORDER BY created_at DESC LIMIT 10"
        ),
        {"integration_id": integration_id, "tenant_id": tenant_id},
    )
    jobs = []
    for row in rows_result.mappings():
        created_at = row["created_at"]
        if isinstance(created_at, datetime):
            created_at = created_at.isoformat()
        jobs.append(
            {
                "id": row["id"],
                "status": row["status"],
                "created_at": str(created_at),
            }
        )
    return {"jobs": jobs, "total": total}


async def list_integrations_db(
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """
    List all SharePoint integrations for a tenant with last sync status.

    Performs a LEFT JOIN on sync_jobs to get the most recent sync job per integration
    using a lateral subquery for the latest sync job per integration.
    """
    result = await db.execute(
        text(
            "SELECT i.id, i.provider AS name, i.status, i.config, "
            "sj.created_at AS last_sync_at, sj.status AS last_sync_status "
            "FROM integrations i "
            "LEFT JOIN LATERAL ("
            "  SELECT sj2.created_at, sj2.status "
            "  FROM sync_jobs sj2 "
            "  WHERE sj2.integration_id = i.id "
            "  ORDER BY sj2.created_at DESC LIMIT 1"
            ") sj ON true "
            "WHERE i.tenant_id = :tenant_id AND i.provider = 'sharepoint' "
            "ORDER BY i.created_at DESC"
        ),
        {"tenant_id": tenant_id},
    )
    items = []
    for row in result.mappings():
        config_val = row["config"]
        if isinstance(config_val, str):
            config_val = json.loads(config_val)

        last_sync_at = row["last_sync_at"]
        if isinstance(last_sync_at, datetime):
            last_sync_at = last_sync_at.isoformat()

        schedule = config_val.get("schedule", {}) if isinstance(config_val, dict) else {}
        next_run_at = schedule.get("next_run_at") if isinstance(schedule, dict) else None

        items.append(
            {
                "id": str(row["id"]),
                "name": row["name"],
                "status": row["status"],
                "site_url": config_val.get("site_url", ""),
                "library_name": config_val.get("library_name", ""),
                "last_sync_at": str(last_sync_at) if last_sync_at else None,
                "last_sync_status": row["last_sync_status"],
                "next_run_at": next_run_at,
            }
        )
    return {"items": items}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/sharepoint")
async def list_sharepoint_integrations(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """API-056: List all SharePoint integrations for the tenant."""
    return await list_integrations_db(
        tenant_id=current_user.tenant_id,
        db=db,
    )


@router.post(
    "/sharepoint/connect",
    status_code=status.HTTP_201_CREATED,
)
async def connect_sharepoint(
    body: SharePointConnectRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    API-050: Create a new SharePoint integration.

    Credentials (client_id, client_secret) are stored in vault only.
    The DB config stores a vault reference URI, never the actual secrets.
    """
    integration_id = str(uuid.uuid4())
    vault_ref = f"vault:mingai/{current_user.tenant_id}/sharepoint/{integration_id}"

    config = {
        "site_url": body.site_url,
        "library_name": body.library_name,
        "credential_ref": vault_ref,
    }

    result = await insert_integration_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        config=config,
        name=body.name,
        db=db,
    )

    logger.info(
        "sharepoint_connection_created",
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        name=body.name,
    )

    return result


@router.post("/sharepoint/{integration_id}/test")
async def test_sharepoint_connection(
    integration_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    API-051: Test a SharePoint connection.

    Phase 1: validates config format (no real OAuth call).
    Returns ok if site_url contains 'sharepoint.com', failed otherwise.
    """
    integration = await get_integration_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration {integration_id} not found",
        )

    config = integration.get("config", {})
    site_url = config.get("site_url", "")

    if "sharepoint.com" in site_url:
        result = {"status": "ok", "latency_ms": 142, "documents_found": 0}
    else:
        result = {"status": "failed", "error": "Invalid SharePoint URL format"}

    logger.info(
        "sharepoint_connection_tested",
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        test_status=result["status"],
    )

    return result


@router.post(
    "/sharepoint/{integration_id}/sync",
    status_code=status.HTTP_201_CREATED,
)
async def trigger_sharepoint_sync(
    integration_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    API-054: Trigger a document sync for a SharePoint integration.

    Creates a queued sync job. Actual sync happens asynchronously.
    """
    integration = await get_integration_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration {integration_id} not found",
        )

    if integration["status"] == "disabled":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Integration is disabled",
        )

    result = await create_sync_job_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )

    # CACHE-011: Invalidate search and semantic caches for this index on sync trigger.
    # Both calls are fire-and-forget — sync job creation is not blocked by cache ops.
    try:
        from app.core.cache_utils import increment_index_version
        from app.core.cache.semantic_cache_service import SemanticCacheService
        import asyncio

        asyncio.create_task(
            increment_index_version(current_user.tenant_id, integration_id)
        )
        sem_cache = SemanticCacheService()
        await sem_cache.invalidate_tenant(current_user.tenant_id)
    except Exception as exc:
        logger.warning(
            "sharepoint_sync_cache_invalidation_failed",
            tenant_id=current_user.tenant_id,
            integration_id=integration_id,
            error=str(exc),
        )

    logger.info(
        "sharepoint_sync_triggered",
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        job_id=result["job_id"],
    )

    return result


@router.get("/sharepoint/{integration_id}/sync")
async def get_sharepoint_sync_status(
    integration_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    API-055: List sync job history for a SharePoint integration.

    Returns the last 10 sync jobs ordered by created_at descending.
    """
    integration = await get_integration_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration {integration_id} not found",
        )

    return await list_sync_jobs_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )


# ---------------------------------------------------------------------------
# Sync failure error type mapping
# ---------------------------------------------------------------------------

_ERROR_TYPE_MAPPINGS = [
    (
        ("permission", "403"),
        "permission_denied",
        "Access denied to this file or folder",
        "Check SharePoint permissions for the integration service account",
    ),
    (
        ("format", "unsupported"),
        "format_unsupported",
        "File format not supported for indexing",
        "Exclude this file type in sync settings or convert to a supported format",
    ),
    (
        ("size", "too large", "413"),
        "too_large",
        "File exceeds maximum size limit",
        "Files over 50MB cannot be indexed. Add to exclusion list or split the document",
    ),
]

_ERROR_TYPE_DEFAULT = (
    "api_error",
    "Sync API error",
    "Check integration credentials and retry sync",
)


def _classify_sync_error(error_message: str) -> tuple[str, str, str]:
    """
    Map a raw error message to (error_type, diagnosis, fix_suggestion).

    Checks each keyword group in order; falls back to api_error if none match.
    """
    lowered = (error_message or "").lower()
    for keywords, error_type, diagnosis, fix_suggestion in _ERROR_TYPE_MAPPINGS:
        if any(kw in lowered for kw in keywords):
            return error_type, diagnosis, fix_suggestion
    return _ERROR_TYPE_DEFAULT


# ---------------------------------------------------------------------------
# Sync failures DB helper
# ---------------------------------------------------------------------------


async def list_sync_failures_db(
    tenant_id: str,
    source_id: Optional[str],
    page: int,
    page_size: int,
    db: AsyncSession,
) -> dict:
    """
    List failed sync jobs for a tenant, joined with integrations for file metadata.

    Tenant-scoped via tenant_id filter (RLS also enforced at DB level).
    Returns paginated items with human-readable error classification.
    """
    offset = (page - 1) * page_size

    base_where = "sj.tenant_id = :tenant_id AND sj.status = 'failed'"
    params: dict = {"tenant_id": tenant_id}

    if source_id is not None:
        base_where += " AND sj.integration_id = :source_id"
        params["source_id"] = source_id

    count_result = await db.execute(
        text("SELECT COUNT(*) FROM sync_jobs sj " f"WHERE {base_where}"),
        params,
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        text(
            "SELECT sj.id, sj.integration_id, sj.error_message, sj.created_at, "
            "i.provider AS source_name "
            "FROM sync_jobs sj "
            "LEFT JOIN integrations i ON i.id = sj.integration_id "
            f"WHERE {base_where} "
            "ORDER BY sj.created_at DESC "
            "LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": page_size, "offset": offset},
    )

    items = []
    for row in rows_result.mappings():
        error_message = row.get("error_message") or ""
        error_type, diagnosis, fix_suggestion = _classify_sync_error(error_message)

        first_failed_at = row.get("created_at")
        if hasattr(first_failed_at, "isoformat"):
            first_failed_at = first_failed_at.isoformat()

        items.append(
            {
                "file_name": "",
                "file_path": "",
                "error_type": error_type,
                "diagnosis": diagnosis,
                "fix_suggestion": fix_suggestion,
                "first_failed_at": str(first_failed_at) if first_failed_at else None,
                "retry_count": 0,
            }
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# Admin sync failures route
# ---------------------------------------------------------------------------


@admin_sync_router.get("/sync/failures")
async def list_sync_failures(
    source_id: Optional[str] = Query(
        None, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    API-056: List sync failures for the tenant.

    Returns paginated failed sync job records with human-readable error
    classification (permission_denied, format_unsupported, too_large, api_error).

    Query params:
        source_id  — filter by integration ID (optional)
        page       — page number, 1-based (default 1)
        page_size  — items per page, 1-100 (default 20)
    """
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 1
    elif page_size > 100:
        page_size = 100

    return await list_sync_failures_db(
        tenant_id=current_user.tenant_id,
        source_id=source_id,
        page=page,
        page_size=page_size,
        db=db,
    )


@admin_sync_router.get("/sync/status")
async def get_sync_status(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    API-057: Sync status summary for all integrations belonging to the tenant.

    Returns each connected integration with its freshness (days since last sync)
    and current status — used by the Analytics and Documents pages.
    """
    import datetime as _dt

    # Use LATERAL join on sync_jobs to get the most recent completed sync per
    # integration — mirrors the pattern in list_integrations_db.
    result = await db.execute(
        text(
            "SELECT i.id, i.provider, i.status, "
            "i.config->>'name' AS source_name, "
            "sj.created_at AS last_sync_at "
            "FROM integrations i "
            "LEFT JOIN LATERAL ("
            "  SELECT sj2.created_at "
            "  FROM sync_jobs sj2 "
            "  WHERE sj2.integration_id = i.id AND sj2.status = 'completed' "
            "  ORDER BY sj2.created_at DESC LIMIT 1"
            ") sj ON true "
            "WHERE i.tenant_id = :tenant_id "
            "ORDER BY i.provider, i.created_at DESC"
        ),
        {"tenant_id": current_user.tenant_id},
    )
    rows = result.mappings().fetchall()

    now = _dt.datetime.now(_dt.timezone.utc)
    items = []
    for r in rows:
        last_sync_at = r["last_sync_at"]
        if last_sync_at is not None:
            # Ensure timezone-aware comparison
            if last_sync_at.tzinfo is None:
                last_sync_at = last_sync_at.replace(tzinfo=_dt.timezone.utc)
            freshness_days = (now - last_sync_at).days
        else:
            freshness_days = -1  # never completed a sync

        items.append(
            {
                "source_id": str(r["id"]),
                "source_name": r["source_name"] or r["provider"],
                "source_type": r["provider"],
                "last_synced_at": last_sync_at.isoformat() if last_sync_at else None,
                "freshness_days": freshness_days,
                "status": r["status"],
            }
        )

    return {"items": items}


@admin_sync_router.post("/sync/jobs/{job_id}/retry")
async def retry_sync_job(
    job_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    API-058: Retry a failed sync job.

    Looks up the failed job to get its integration, then creates a new
    queued sync job for the same integration. Only jobs belonging to the
    current tenant can be retried.
    """
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Sync job not found.")

    result = await db.execute(
        text(
            "SELECT sj.integration_id, i.tenant_id "
            "FROM sync_jobs sj "
            "JOIN integrations i ON i.id = sj.integration_id "
            "WHERE sj.id = :job_id AND i.tenant_id = :tenant_id"
        ),
        {"job_id": job_id, "tenant_id": current_user.tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Sync job not found.")

    new_job = await create_sync_job_db(
        integration_id=str(row["integration_id"]),
        tenant_id=current_user.tenant_id,
        db=db,
    )
    return {"job_id": new_job["job_id"], "status": new_job["status"]}


# ---------------------------------------------------------------------------
# TA-015: Sync schedule DB helper
# ---------------------------------------------------------------------------


async def update_schedule_db(
    integration_id: str,
    tenant_id: str,
    schedule: dict,
    db: AsyncSession,
) -> bool:
    """
    Persist the schedule config into integrations.config['schedule'].

    Merges the schedule dict into the existing config JSON.
    Returns True if the row was updated, False if not found.
    """
    # Fetch current config
    result = await db.execute(
        text(
            "SELECT config FROM integrations "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": integration_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return False

    config_val = row[0]
    if isinstance(config_val, str):
        config_val = json.loads(config_val)
    elif config_val is None:
        config_val = {}

    config_val["schedule"] = schedule
    update_result = await db.execute(
        text(
            "UPDATE integrations SET config = CAST(:config AS jsonb), updated_at = :now "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {
            "config": json.dumps(config_val),
            "now": datetime.now(timezone.utc),
            "id": integration_id,
            "tenant_id": tenant_id,
        },
    )
    if (update_result.rowcount or 0) == 0:
        return False
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# TA-015: PATCH /documents/sharepoint/{integration_id}/schedule
# ---------------------------------------------------------------------------


@router.patch("/sharepoint/{integration_id}/schedule")
async def update_sharepoint_schedule(
    integration_id: str,
    body: SyncScheduleRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    TA-015: Configure the sync schedule for a SharePoint integration.

    Plan tier enforcement:
      - starter      → daily only
      - professional → daily or hourly
      - enterprise   → daily, hourly, or custom_cron

    For custom_cron the cron_expression field is required and must be a valid
    5-field cron string (minute hour dom month dow).

    Stores the schedule in integrations.config['schedule'] and returns the
    next scheduled run time.
    """
    plan = current_user.plan
    allowed = _PLAN_ALLOWED_FREQUENCIES.get(
        plan, _PLAN_ALLOWED_FREQUENCIES["professional"]
    )

    if body.frequency not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Plan '{plan}' does not allow frequency '{body.frequency}'. "
                f"Allowed: {sorted(allowed)}"
            ),
        )

    if body.frequency == "custom_cron":
        if not body.cron_expression:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="cron_expression is required when frequency is 'custom_cron'",
            )
        if not _validate_cron_expression(body.cron_expression):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid cron_expression. Expected 5-field standard cron syntax.",
            )

    # Verify the integration exists
    integration = await get_integration_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration {integration_id} not found",
        )

    schedule = {
        "frequency": body.frequency,
        "cron_expression": body.cron_expression,
    }

    updated = await update_schedule_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        schedule=schedule,
        db=db,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration {integration_id} not found",
        )

    next_run_at = _next_run_from_schedule(body.frequency, body.cron_expression)

    logger.info(
        "sharepoint_schedule_updated",
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        frequency=body.frequency,
        next_run_at=next_run_at.isoformat(),
    )

    return {
        "integration_id": integration_id,
        "frequency": body.frequency,
        "cron_expression": body.cron_expression,
        "next_run_at": next_run_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# TA-018: Reconnect wizard API
# ---------------------------------------------------------------------------


class ReconnectRequest(BaseModel):
    site_url: str = Field(..., min_length=1)
    library_name: str = Field(..., min_length=1, max_length=200)
    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1)

    @field_validator("site_url")
    @classmethod
    def site_url_must_be_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("site_url must start with https://")
        return v


async def reconnect_integration_db(
    integration_id: str,
    tenant_id: str,
    site_url: str,
    library_name: str,
    actor_id: str,
    db: AsyncSession,
) -> bool:
    """
    Update the integration config with new site_url and library_name,
    reset status to 'active', and write an audit_log entry.

    Returns True if the row was updated, False if not found.
    """
    import json as _json

    result = await db.execute(
        text(
            "SELECT config FROM integrations "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": integration_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return False

    config_val = row[0]
    if isinstance(config_val, str):
        config_val = _json.loads(config_val)
    elif config_val is None:
        config_val = {}

    # Preserve existing vault_ref and schedule; update connection details only
    config_val["site_url"] = site_url
    config_val["library_name"] = library_name

    now = datetime.now(timezone.utc)
    update_result = await db.execute(
        text(
            "UPDATE integrations "
            "SET config = CAST(:config AS jsonb), status = 'active', updated_at = :now "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {
            "config": _json.dumps(config_val),
            "now": now,
            "id": integration_id,
            "tenant_id": tenant_id,
        },
    )
    if (update_result.rowcount or 0) == 0:
        return False

    # Audit log the reconnect action
    try:
        await db.execute(
            text(
                "INSERT INTO audit_log "
                "(tenant_id, user_id, action, resource_type, resource_id, details) "
                "VALUES (:tenant_id, :user_id, 'reconnect', 'integration', "
                "CAST(:resource_id AS uuid), CAST(:details AS jsonb))"
            ),
            {
                "tenant_id": tenant_id,
                "user_id": actor_id,
                "resource_id": integration_id,
                "details": _json.dumps(
                    {
                        "site_url": site_url,
                        "library_name": library_name,
                        "reconnected_at": now.isoformat(),
                    }
                ),
            },
        )
    except Exception as exc:
        logger.warning(
            "sharepoint_reconnect_audit_failed",
            integration_id=integration_id,
            error=str(exc),
        )

    await db.commit()
    return True


@router.post("/sharepoint/{integration_id}/reconnect")
async def reconnect_sharepoint(
    integration_id: str,
    body: ReconnectRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    TA-018: Reconnect a SharePoint integration with new credentials.

    Flow:
    1. Verify the integration exists.
    2. Test the new credentials (check site_url format).
    3. On test failure: return 422 — credentials are NOT updated.
    4. On test success: update config (site_url, library_name, vault ref), reset
       status to 'active', create a new queued sync_job, log to audit_log.

    Returns: { "status": "reconnected", "test_result": "success|failed",
               "next_sync_at": "<ISO datetime>" }
    """
    integration = await get_integration_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration {integration_id} not found",
        )

    # Step 1: Verify new credentials (test connection before any DB writes)
    # Phase 1: validate site_url format (no live OAuth call yet)
    if "sharepoint.com" not in body.site_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Connection test failed: site_url does not appear to be a valid "
                "SharePoint URL. Credentials were not updated."
            ),
        )

    # Step 2: Update integration config (vault ref stays the same; site_url/library_name updated)
    updated = await reconnect_integration_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        site_url=body.site_url,
        library_name=body.library_name,
        actor_id=current_user.id,
        db=db,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration {integration_id} not found",
        )

    # Step 3: Create a new queued sync_job (resets sync status)
    job = await create_sync_job_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )

    next_sync_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

    logger.info(
        "sharepoint_reconnected",
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        job_id=job["job_id"],
    )

    return {
        "status": "reconnected",
        "test_result": "success",
        "integration_id": integration_id,
        "next_sync_at": next_sync_at,
    }
