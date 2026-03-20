"""
SCHED-026: Platform Admin job history endpoint.

GET /api/v1/platform/jobs/history — paginated view of job_run_log.
Supports filtering by job_name, status, and date range.
Platform Admin scope only.
"""
from datetime import date
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_platform_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/platform/jobs", tags=["platform"])

_VALID_STATUSES = {"running", "completed", "failed", "abandoned", "skipped"}
_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50


class JobRunRow(BaseModel):
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


class JobHistoryResponse(BaseModel):
    items: List[JobRunRow]
    total_count: int
    limit: int
    offset: int


@router.get("/history", response_model=JobHistoryResponse)
async def get_job_history(
    job_name: Optional[str] = Query(None, description="Filter by job name"),
    status: Optional[str] = Query(None, description="Filter by status"),
    from_date: Optional[date] = Query(None, description="Inclusive start date (UTC)"),
    to_date: Optional[date] = Query(None, description="Inclusive end date (UTC)"),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> JobHistoryResponse:
    """
    Return paginated job_run_log history for platform admins.

    Uses the (job_name, started_at DESC) index when job_name is specified,
    and the started_at DESC index for unfiltered views.
    """
    if status is not None and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
        )

    # Build WHERE clauses
    conditions = []
    params: dict = {}

    if job_name is not None:
        conditions.append("job_name = :job_name")
        params["job_name"] = job_name

    if status is not None:
        conditions.append("status = :status")
        params["status"] = status

    if from_date is not None:
        conditions.append("started_at >= :from_date")
        params["from_date"] = from_date

    if to_date is not None:
        # Inclusive: include the entire to_date day
        conditions.append("started_at < :to_date_exclusive")
        from datetime import timedelta
        params["to_date_exclusive"] = to_date + timedelta(days=1)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Count query
    count_sql = text(f"SELECT COUNT(*) FROM job_run_log {where_clause}")
    count_result = await db.execute(count_sql, params)
    total_count = count_result.scalar() or 0

    # Data query — ORDER BY started_at DESC uses idx_jrl_started_at or idx_jrl_job_name_time
    data_sql = text(
        f"SELECT id, job_name, instance_id, tenant_id, status, "
        f"       started_at, completed_at, duration_ms, records_processed, error_message "
        f"FROM job_run_log {where_clause} "
        f"ORDER BY started_at DESC "
        f"LIMIT :limit OFFSET :offset"
    )
    data_params = {**params, "limit": limit, "offset": offset}
    data_result = await db.execute(data_sql, data_params)
    rows = data_result.fetchall()

    items = [
        JobRunRow(
            id=str(r[0]),
            job_name=r[1],
            instance_id=r[2],
            tenant_id=str(r[3]) if r[3] else None,
            status=r[4],
            started_at=r[5].isoformat() if r[5] else "",
            completed_at=r[6].isoformat() if r[6] else None,
            duration_ms=r[7],
            records_processed=r[8],
            error_message=r[9],
        )
        for r in rows
    ]

    return JobHistoryResponse(
        items=items,
        total_count=total_count,
        limit=limit,
        offset=offset,
    )
