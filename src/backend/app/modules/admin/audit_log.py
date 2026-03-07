"""
Workspace audit log API endpoint (API-087).

Endpoint:
- GET /admin/audit-log  -- paginated audit log for the tenant with optional filters and CSV export

Schema note: audit_log table has columns:
  id, tenant_id, user_id (actor), action, resource_type, resource_id, details (JSONB), ip_address, created_at
"""
import csv
import io
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin-audit-log"])

_PAGE_SIZE_MAX = 100


async def get_audit_log_db(
    tenant_id: str,
    actor_id: Optional[str],
    resource_type: Optional[str],
    action: Optional[str],
    search: Optional[str],
    from_date: Optional[datetime],
    to_date: Optional[datetime],
    page: int,
    page_size: int,
    db: AsyncSession,
) -> tuple[list[dict], int]:
    """
    Query audit_log for a tenant with optional filters.

    JOINs users to get actor_email. Keyword search matches action or resource_type.
    Returns (items, total).
    """
    # Build WHERE clauses from hardcoded fragments only — no f-string user data
    conditions = ["al.tenant_id = :tenant_id"]
    params: dict = {"tenant_id": tenant_id}

    if actor_id:
        conditions.append("al.user_id = :actor_id")
        params["actor_id"] = actor_id

    if resource_type:
        conditions.append("al.resource_type = :resource_type")
        params["resource_type"] = resource_type

    if action:
        conditions.append("al.action = :action")
        params["action"] = action

    if search:
        conditions.append(
            "(al.action ILIKE :search_pattern OR al.resource_type ILIKE :search_pattern)"
        )
        params["search_pattern"] = f"%{search}%"

    if from_date:
        conditions.append("al.created_at >= :from_date")
        params["from_date"] = from_date

    if to_date:
        conditions.append("al.created_at <= :to_date")
        params["to_date"] = to_date

    where_clause = " AND ".join(conditions)

    # Count total matching rows
    count_result = await db.execute(
        text(f"SELECT COUNT(*) " f"FROM audit_log al " f"WHERE {where_clause}"),
        params,
    )
    total = int(count_result.scalar_one() or 0)

    # Fetch paginated rows with actor email via JOIN
    offset = (page - 1) * page_size
    params["limit"] = page_size
    params["offset"] = offset

    rows_result = await db.execute(
        text(
            f"SELECT "
            f"  al.id, al.user_id, u.email AS actor_email, "
            f"  al.action, al.resource_type, al.resource_id, "
            f"  al.details, al.created_at "
            f"FROM audit_log al "
            f"LEFT JOIN users u ON u.id = al.user_id "
            f"WHERE {where_clause} "
            f"ORDER BY al.created_at DESC "
            f"LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    rows = rows_result.fetchall()

    items = [
        {
            "id": str(row[0]),
            "actor_id": str(row[1]) if row[1] else None,
            "actor_email": row[2] or "",
            "action": row[3] or "",
            "resource_type": row[4] or "",
            "resource_id": str(row[5]) if row[5] else None,
            "metadata": row[6] if row[6] is not None else {},
            "created_at": row[7].isoformat() if row[7] else "",
        }
        for row in rows
    ]

    return items, total


def _build_csv_response(items: list[dict]) -> StreamingResponse:
    """Build a CSV StreamingResponse from audit log items."""
    output = io.StringIO()
    fieldnames = [
        "id",
        "actor_id",
        "actor_email",
        "action",
        "resource_type",
        "resource_id",
        "metadata",
        "created_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for item in items:
        row = dict(item)
        row["metadata"] = str(row.get("metadata", {}))
        writer.writerow(row)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit-log.csv"},
    )


@router.get("/audit-log")
async def get_audit_log(
    actor_id: Optional[str] = Query(None, description="Filter by actor user ID"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    action: Optional[str] = Query(None, description="Filter by action"),
    search: Optional[str] = Query(
        None, description="Keyword search on action or resource_type"
    ),
    from_date: Optional[datetime] = Query(None, description="Start date (ISO-8601)"),
    to_date: Optional[datetime] = Query(None, description="End date (ISO-8601)"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(
        20, ge=1, le=_PAGE_SIZE_MAX, description="Items per page (max 100)"
    ),
    format: Optional[str] = Query(
        None, description="Response format: json (default) or csv"
    ),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-087: Paginated audit log for the current tenant.

    Supports optional filters by actor, resource_type, action, keyword search,
    and date range. Returns JSON by default; use format=csv for CSV export.

    Auth: tenant_admin required.
    """
    items, total = await get_audit_log_db(
        tenant_id=current_user.tenant_id,
        actor_id=actor_id,
        resource_type=resource_type,
        action=action,
        search=search,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
        db=session,
    )

    logger.info(
        "audit_log_fetched",
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        total=total,
        page=page,
        page_size=page_size,
    )

    if format == "csv":
        return _build_csv_response(items)

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
