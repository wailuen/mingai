"""
TODO-13B: Per-tenant job history endpoint.

GET /api/v1/tenant/jobs — filtered view of job_run_log for the requesting tenant.
Tenant Admin scope only.
"""
from datetime import date, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/tenant", tags=["admin"])

VALID_STATUSES = frozenset({"running", "completed", "failed", "abandoned", "skipped"})


class TenantJobRunRow(BaseModel):
    id: str
    job_name: str
    instance_id: Optional[str]
    tenant_id: Optional[str]
    status: str
    started_at: str
    completed_at: Optional[str]
    duration_ms: Optional[int]
    records_processed: Optional[int]
    error_message: Optional[str]


class TenantJobHistoryResponse(BaseModel):
    items: list[TenantJobRunRow]
    total_count: int
    limit: int
    offset: int


@router.get("/jobs", response_model=TenantJobHistoryResponse)
async def get_tenant_jobs(
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = Query(default=None),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> TenantJobHistoryResponse:
    """
    Return job execution history for the requesting tenant.

    Reads only rows where tenant_id = current_user.tenant_id.
    Supports filtering by status and date range.
    """
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

    tenant_id = str(current_user.tenant_id)

    # Build WHERE clause fragments.
    # INVARIANT: every element appended to `conditions` MUST be a hardcoded
    # string literal. User-supplied values MUST only appear in `params` as
    # named bind parameters. Never interpolate user values directly.
    conditions = ["tenant_id = :tenant_id"]
    filter_params: dict = {"tenant_id": tenant_id}
    params: dict = {"tenant_id": tenant_id, "limit": limit, "offset": offset}

    if status is not None:
        conditions.append("status = :status")
        filter_params["status"] = status
        params["status"] = status

    if from_date is not None:
        conditions.append("started_at >= :from_date")
        filter_params["from_date"] = from_date
        params["from_date"] = from_date

    if to_date is not None:
        conditions.append("started_at < :to_date_exclusive")
        filter_params["to_date_exclusive"] = to_date + timedelta(days=1)
        params["to_date_exclusive"] = to_date + timedelta(days=1)

    where_sql = " AND ".join(conditions)

    # Count query — uses filter_params only (no :limit/:offset)
    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM job_run_log WHERE {where_sql}"),
        filter_params,
    )
    total_count = count_result.scalar() or 0

    # Data query — ORDER BY started_at DESC for most-recent-first
    data_result = await db.execute(
        text(
            f"SELECT id, job_name, instance_id, tenant_id, status, "
            f"started_at, completed_at, duration_ms, records_processed, error_message "
            f"FROM job_run_log "
            f"WHERE {where_sql} "
            f"ORDER BY started_at DESC "
            f"LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    rows = data_result.fetchall()

    items = [
        TenantJobRunRow(
            id=str(row[0]),
            job_name=row[1],
            instance_id=row[2],
            tenant_id=str(row[3]) if row[3] else None,
            status=row[4],
            started_at=row[5].isoformat() if row[5] else "",
            completed_at=row[6].isoformat() if row[6] else None,
            duration_ms=row[7],
            records_processed=row[8],
            error_message=row[9],
        )
        for row in rows
    ]

    logger.info(
        "tenant_jobs_listed",
        tenant_id=tenant_id,
        total_count=total_count,
        limit=limit,
        offset=offset,
    )

    return TenantJobHistoryResponse(
        items=items,
        total_count=total_count,
        limit=limit,
        offset=offset,
    )
