"""
Issue Reports API routes (API-013, API-014, API-015, API-016, API-017).

Endpoints:
- GET    /issue-reports/presign               — Presigned upload URL (API-014, any user)
- GET    /my-reports                          — List current user's reports (API-015)
- GET    /my-reports/{id}                     — Get own report detail (API-016)
- POST   /issue-reports/{id}/still-happening  — Still happening confirmation (API-017)
- GET    /issues                              — List tenant issues (tenant admin only)
- POST   /issues                              — Create issue (any authenticated user)
- GET    /issues/{issue_id}                   — Get issue (tenant admin or issue owner)
- PATCH  /issues/{issue_id}/status            — Update status (tenant admin only)
- POST   /issues/{issue_id}/events            — Add event/comment (tenant admin only)

Schema: issue_reports(id, tenant_id, reporter_id, conversation_id, message_id,
        issue_type, description, severity, status, screenshot_url,
        blur_acknowledged, metadata, created_at)

Note: /issues/{issue_id}/status and /issues/{issue_id}/events routes must
be registered BEFORE /{issue_id} to avoid path collision.
"""
import re
import uuid
from enum import Enum

# Module-level UUID pattern — reused across batch validation and create_issue_db.
_UUID_PATTERN_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, field_validator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(tags=["issues"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class IssueStatus(str, Enum):
    open = "open"
    investigating = "investigating"
    resolved = "resolved"
    closed = "closed"


class IssueType(str, Enum):
    bug = "bug"
    performance = "performance"
    ux = "ux"
    feature_request = "feature_request"


class CreateIssueRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    issue_type: IssueType = Field(IssueType.bug)
    description: str = Field(..., min_length=1, max_length=2000)
    screenshot_url: Optional[str] = Field(None, max_length=500)
    blur_acknowledged: bool = Field(False)


class UpdateIssueStatusRequest(BaseModel):
    status: IssueStatus


class AddIssueEventRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


class StillHappeningRequest(BaseModel):
    additional_context: Optional[str] = Field(None, max_length=2000)
    fix_deployment_id: Optional[str] = Field(None, max_length=200)


# ---------------------------------------------------------------------------
# DB / service helper functions (mockable in unit tests)
# ---------------------------------------------------------------------------


async def list_issues_db(
    tenant_id: str,
    page: int,
    page_size: int,
    status_filter: Optional[str],
    db,
) -> dict:
    """List issue reports for a tenant, paginated."""
    offset = (page - 1) * page_size

    if status_filter:
        count_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM issue_reports "
                "WHERE tenant_id = :tenant_id AND status = :status"
            ),
            {"tenant_id": tenant_id, "status": status_filter},
        )
    else:
        count_result = await db.execute(
            text("SELECT COUNT(*) FROM issue_reports WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
    total = count_result.scalar() or 0

    if status_filter:
        rows_result = await db.execute(
            text(
                "SELECT id, reporter_id, issue_type, description, screenshot_url, status, "
                "blur_acknowledged, created_at FROM issue_reports "
                "WHERE tenant_id = :tenant_id AND status = :status "
                "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            {
                "tenant_id": tenant_id,
                "status": status_filter,
                "limit": page_size,
                "offset": offset,
            },
        )
    else:
        rows_result = await db.execute(
            text(
                "SELECT id, reporter_id, issue_type, description, screenshot_url, status, "
                "blur_acknowledged, created_at FROM issue_reports "
                "WHERE tenant_id = :tenant_id "
                "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            {"tenant_id": tenant_id, "limit": page_size, "offset": offset},
        )

    rows = rows_result.fetchall()
    items = [
        {
            "id": str(r[0]),
            "reporter_id": str(r[1]),
            "issue_type": r[2],
            "description": r[3],
            "screenshot_url": r[4],
            "status": r[5],
            "blur_acknowledged": r[6],
            "created_at": str(r[7]),
        }
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def create_issue_db(
    tenant_id: str,
    reporter_id: str,
    issue_type: str,
    title: str,
    description: str,
    screenshot_url: Optional[str],
    blur_acknowledged: bool,
    db,
) -> dict:
    """Create a new issue report."""
    import json as _json

    # Validate tenant_id is a real UUID — the platform admin bootstrap uses
    # the sentinel value "default" which is not a valid UUID column value.
    if not _UUID_PATTERN_RE.match(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Issue creation requires a tenant-scoped user account.",
        )

    issue_id = str(uuid.uuid4())
    # metadata is a JSONB column — use CAST to avoid asyncpg type inference errors
    await db.execute(
        text(
            "INSERT INTO issue_reports "
            "(id, tenant_id, reporter_id, issue_type, description, screenshot_url, status, blur_acknowledged, metadata) "
            "VALUES (:id, :tenant_id, :reporter_id, :issue_type, :description, :screenshot_url, :status, :blur_acknowledged, CAST(:metadata AS jsonb))"
        ),
        {
            "id": issue_id,
            "tenant_id": tenant_id,
            "reporter_id": reporter_id,
            "issue_type": issue_type,
            "description": description,
            "screenshot_url": screenshot_url,
            "status": "open",
            "blur_acknowledged": blur_acknowledged,
            "metadata": _json.dumps({"title": title}),
        },
    )
    await db.commit()

    # Trigger blur pipeline if screenshot is attached (INFRA-019)
    if screenshot_url:
        from app.modules.issues.blur_pipeline import apply_blur_to_uploaded_screenshot

        blur_ok = await apply_blur_to_uploaded_screenshot(
            blob_url=screenshot_url,
            content_type="image/png",
        )
        logger.info(
            "issue_screenshot_attached",
            issue_id=issue_id,
            screenshot_url=screenshot_url,
            blur_acknowledged=blur_acknowledged,
            blur_applied=blur_ok,
        )

    logger.info(
        "issue_created",
        issue_id=issue_id,
        issue_type=issue_type,
        tenant_id=tenant_id,
        reporter_id=reporter_id,
    )
    return {
        "id": issue_id,
        "issue_type": issue_type,
        "description": description,
        "screenshot_url": screenshot_url,
        "status": "open",
        "blur_acknowledged": blur_acknowledged,
        "tenant_id": tenant_id,
        "reporter_id": reporter_id,
    }


async def get_issue_db(issue_id: str, tenant_id: str, db) -> Optional[dict]:
    """Get an issue report by ID, scoped to tenant."""
    result = await db.execute(
        text(
            "SELECT id, reporter_id, issue_type, description, screenshot_url, status, "
            "blur_acknowledged, created_at FROM issue_reports "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": issue_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "reporter_id": str(row[1]),
        "issue_type": row[2],
        "description": row[3],
        "screenshot_url": row[4],
        "status": row[5],
        "blur_acknowledged": row[6],
        "created_at": str(row[7]),
    }


async def update_issue_status_db(
    issue_id: str, tenant_id: str, new_status: str, db
) -> Optional[dict]:
    """Update the status of an issue report."""
    result = await db.execute(
        text(
            "UPDATE issue_reports SET status = :status "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": issue_id, "tenant_id": tenant_id, "status": new_status},
    )
    await db.commit()
    if (result.rowcount or 0) == 0:
        return None
    return await get_issue_db(issue_id, tenant_id, db)


async def add_issue_event_db(
    issue_id: str, tenant_id: str, user_id: str, content: str, db
) -> dict:
    """Add an event/comment to an issue's log."""
    # Verify the issue exists and belongs to the tenant
    issue = await get_issue_db(issue_id, tenant_id, db)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )

    event_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO issue_report_events (id, issue_id, tenant_id, event_type, data) "
            "VALUES (:id, :issue_id, :tenant_id, :event_type, :data)"
        ),
        {
            "id": event_id,
            "issue_id": issue_id,
            "tenant_id": tenant_id,
            "event_type": "comment",
            "data": content,
        },
    )
    await db.commit()

    logger.info(
        "issue_event_added",
        event_id=event_id,
        issue_id=issue_id,
        user_id=user_id,
    )
    return {
        "id": event_id,
        "issue_id": issue_id,
        "user_id": user_id,
        "content": content,
    }


# ---------------------------------------------------------------------------
# Route handlers
# Note: /issues/{issue_id}/status and /issues/{issue_id}/events
# MUST be registered BEFORE /{issue_id} to avoid path collision.
# ---------------------------------------------------------------------------


async def list_my_issues_db(
    user_id: str,
    tenant_id: str,
    page: int,
    page_size: int,
    status_filter: Optional[str],
    db,
) -> dict:
    """List issue reports submitted by the current user."""
    offset = (page - 1) * page_size

    if status_filter:
        count_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM issue_reports "
                "WHERE reporter_id = :reporter_id AND tenant_id = :tenant_id AND status = :status"
            ),
            {"reporter_id": user_id, "tenant_id": tenant_id, "status": status_filter},
        )
    else:
        count_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM issue_reports "
                "WHERE reporter_id = :reporter_id AND tenant_id = :tenant_id"
            ),
            {"reporter_id": user_id, "tenant_id": tenant_id},
        )
    total = count_result.scalar() or 0

    if status_filter:
        rows_result = await db.execute(
            text(
                "SELECT id, issue_type, description, screenshot_url, status, "
                "blur_acknowledged, created_at, updated_at, metadata->>'title' AS title "
                "FROM issue_reports "
                "WHERE reporter_id = :reporter_id AND tenant_id = :tenant_id AND status = :status "
                "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            {
                "reporter_id": user_id,
                "tenant_id": tenant_id,
                "status": status_filter,
                "limit": page_size,
                "offset": offset,
            },
        )
    else:
        rows_result = await db.execute(
            text(
                "SELECT id, issue_type, description, screenshot_url, status, "
                "blur_acknowledged, created_at, updated_at, metadata->>'title' AS title "
                "FROM issue_reports "
                "WHERE reporter_id = :reporter_id AND tenant_id = :tenant_id "
                "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            {
                "reporter_id": user_id,
                "tenant_id": tenant_id,
                "limit": page_size,
                "offset": offset,
            },
        )

    rows = rows_result.fetchall()
    items = [
        {
            "id": str(r[0]),
            "issue_type": r[1],
            "title": r[8] or r[2] or r[1],  # metadata title → description → issue_type
            "description": r[2],
            "screenshot_url": r[3],
            "status": r[4],
            "blur_acknowledged": r[5],
            "created_at": str(r[6]),
            "updated_at": str(r[7]) if r[7] else None,
        }
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def get_my_issue_db(
    issue_id: str, user_id: str, tenant_id: str, db
) -> Optional[dict]:
    """Get a single issue report owned by the current user."""
    result = await db.execute(
        text(
            "SELECT id, issue_type, description, screenshot_url, status, "
            "blur_acknowledged, created_at, updated_at, metadata->>'title' AS title "
            "FROM issue_reports "
            "WHERE id = :id AND reporter_id = :reporter_id AND tenant_id = :tenant_id"
        ),
        {"id": issue_id, "reporter_id": user_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return None

    # Fetch timeline events for this issue
    events_result = await db.execute(
        text(
            "SELECT id, data, created_at FROM issue_report_events "
            "WHERE issue_id = :issue_id ORDER BY created_at ASC"
        ),
        {"issue_id": issue_id},
    )
    timeline = [
        {"id": str(e[0]), "event": e[1], "timestamp": str(e[2])}
        for e in events_result.fetchall()
    ]

    return {
        "id": str(row[0]),
        "issue_type": row[1],
        "title": row[8]
        or row[2]
        or row[1],  # metadata title → description → issue_type
        "description": row[2],
        "screenshot_url": row[3],
        "status": row[4],
        "blur_acknowledged": row[5],
        "created_at": str(row[6]),
        "updated_at": str(row[7]) if row[7] else None,
        "timeline": timeline,
    }


async def record_still_happening_db(
    issue_id: str,
    user_id: str,
    tenant_id: str,
    additional_context: Optional[str],
    fix_deployment_id: str,
    db,
) -> dict:
    """
    Record a 'still happening' occurrence and create a regression report.

    Creates a new issue report linked to the original, records the occurrence
    in the rate limiter, and returns routing decision + new report ID.

    The issue existence check runs BEFORE the rate-limiter UPSERT to avoid
    incrementing an orphaned counter for a non-existent issue.
    """
    from app.modules.issues.still_happening import StillHappeningRateLimiter

    # Verify original issue exists BEFORE touching the rate-limiter counter.
    # This prevents orphaned counter rows that would prematurely route valid
    # future reports to human_review instead of auto_escalate.
    orig = await get_issue_db(issue_id, tenant_id, db)
    if orig is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )

    # Record occurrence in rate limiter
    limiter = StillHappeningRateLimiter(db=db)
    routing = await limiter.record_occurrence(issue_id, fix_deployment_id)

    # Create a regression report linked to the original issue
    regression_title = f"[REGRESSION] {orig['title']}"
    regression_desc = (
        f"User reports issue is still occurring after fix deployment '{fix_deployment_id}'.\n"
        f"Original issue: {issue_id}\n"
        f"Additional context: {additional_context or 'None'}"
    )
    new_report = await create_issue_db(
        tenant_id=tenant_id,
        reporter_id=user_id,
        issue_type="bug",
        title=regression_title,
        description=regression_desc,
        screenshot_url=None,
        blur_acknowledged=False,
        db=db,
    )

    logger.info(
        "still_happening_recorded",
        original_issue_id=issue_id,
        new_report_id=new_report["id"],
        routing=routing,
        fix_deployment_id=fix_deployment_id,
    )
    return {
        "status": "regression_reported",
        "new_report_id": new_report["id"],
        "routing": routing,
    }


@router.get("/issue-reports/presign")
async def presign_screenshot_upload(
    filename: str = Query(..., min_length=1, max_length=255),
    content_type: str = Query(..., alias="content_type"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    API-014: Generate a presigned URL for direct screenshot upload.

    Returns upload_url (PUT target), blob_url (permanent reference after upload),
    and expires_in (300 seconds). Content-type restricted to image/png and image/jpeg.
    Storage path is scoped to the caller's tenant_id.
    """
    from app.core.storage import ALLOWED_CONTENT_TYPES, generate_presigned_upload

    if content_type not in ALLOWED_CONTENT_TYPES:
        allowed = ", ".join(sorted(ALLOWED_CONTENT_TYPES))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"content_type must be one of: {allowed}",
        )

    try:
        result = generate_presigned_upload(
            tenant_id=current_user.tenant_id,
            filename=filename,
            content_type=content_type,
        )
    except Exception as exc:
        logger.error(
            "presign_failed",
            tenant_id=current_user.tenant_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate upload URL",
        )

    return {
        "upload_url": result.upload_url,
        "blob_url": result.blob_url,
        "expires_in": result.expires_in,
    }


@router.get("/my-reports")
async def list_my_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[IssueStatus] = Query(None, alias="status"),
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-015: List current user's own submitted issue reports (paginated)."""
    # Platform admins operate cross-tenant and cannot access per-tenant my-reports
    try:
        import uuid as _uuid

        _uuid.UUID(current_user.tenant_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not available for platform scope users",
        )
    result = await list_my_issues_db(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter.value if status_filter else None,
        db=session,
    )
    return result


@router.get("/my-reports/{report_id}")
async def get_my_report(
    report_id: str = Path(..., max_length=36),
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-016: Get detail of one of the current user's own issue reports."""
    result = await get_my_issue_db(
        issue_id=report_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue report '{report_id}' not found",
        )
    return result


@router.post(
    "/issue-reports/{issue_id}/still-happening", status_code=status.HTTP_201_CREATED
)
async def still_happening(
    issue_id: str = Path(..., max_length=36),
    request: StillHappeningRequest = ...,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-017: Confirm issue is still occurring after a fix was deployed.

    Rate limited: max 1 auto-escalation per fix deployment. Second occurrence
    triggers human review. Creates a linked regression report.
    """
    # Use provided fix_deployment_id or fall back to the original issue_id as a proxy
    fix_deployment_id = request.fix_deployment_id or f"fix-for-{issue_id}"

    result = await record_still_happening_db(
        issue_id=issue_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        additional_context=request.additional_context,
        fix_deployment_id=fix_deployment_id,
        db=session,
    )
    return result


@router.get("/issues")
async def list_issues(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[IssueStatus] = Query(None, alias="status"),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-013: List all issue reports for the tenant (tenant admin only)."""
    result = await list_issues_db(
        tenant_id=current_user.tenant_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter.value if status_filter else None,
        db=session,
    )
    return result


@router.post("/issues", status_code=status.HTTP_201_CREATED)
async def create_issue(
    request: CreateIssueRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-013: Create a new issue report (any authenticated user)."""
    # INFRA-019: Enforce blur acknowledgement when screenshot is attached
    if request.screenshot_url is not None and not request.blur_acknowledged:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="blur_acknowledged must be true when screenshot_url is provided",
        )
    result = await create_issue_db(
        tenant_id=current_user.tenant_id,
        reporter_id=current_user.id,
        issue_type=request.issue_type.value,
        title=request.title,
        description=request.description,
        screenshot_url=request.screenshot_url,
        blur_acknowledged=request.blur_acknowledged,
        db=session,
    )
    return result


@router.patch("/issues/{issue_id}/status")
async def update_issue_status(
    issue_id: str,
    request: UpdateIssueStatusRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-013: Update issue status (tenant admin only)."""
    result = await update_issue_status_db(
        issue_id=issue_id,
        tenant_id=current_user.tenant_id,
        new_status=request.status.value,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    return result


@router.post("/issues/{issue_id}/events", status_code=status.HTTP_201_CREATED)
async def add_issue_event(
    issue_id: str,
    request: AddIssueEventRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-013: Add event/comment to an issue (tenant admin only)."""
    result = await add_issue_event_db(
        issue_id=issue_id,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        content=request.content,
        db=session,
    )
    return result


@router.get("/issues/{issue_id}")
async def get_issue(
    issue_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-013: Get issue details (tenant admin or issue owner)."""
    result = await get_issue_db(
        issue_id=issue_id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )

    # Authorization: tenant admins can see all issues; others can only see their own
    is_admin = "tenant_admin" in current_user.roles
    is_owner = result["reporter_id"] == current_user.id
    if not is_admin and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own issues",
        )

    return result


# ---------------------------------------------------------------------------
# Phase 2: Admin issue queues (API-019, 020) + Platform admin (API-021, 022, 023)
# + GitHub webhook (API-018)
# ---------------------------------------------------------------------------

import hashlib
import hmac as _hmac
import os
from datetime import datetime, timezone

from app.core.dependencies import require_platform_admin

# Sub-routers registered in api/router.py
admin_issues_router = APIRouter(prefix="/admin/issues", tags=["admin-issues"])
platform_issues_router = APIRouter(prefix="/platform/issues", tags=["platform-issues"])
webhooks_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Admin issue queue DB helpers (API-019)
# ---------------------------------------------------------------------------

_VALID_SORT_COLUMNS = {"created_at", "severity", "status"}


async def list_admin_issues_db(
    tenant_id: str,
    page: int,
    page_size: int,
    status_filter: Optional[str],
    severity_filter: Optional[str],
    type_filter: Optional[str],
    sort_by: str,
    sort_order: str,
    db,
) -> dict:
    """List issues for a tenant with full filtering (API-019)."""
    # Allowlist sort column and order to prevent injection
    col = sort_by if sort_by in _VALID_SORT_COLUMNS else "created_at"
    order = "DESC" if sort_order.upper() != "ASC" else "ASC"

    conditions = ["ir.tenant_id = :tenant_id"]
    params: dict = {"tenant_id": tenant_id}

    if status_filter:
        conditions.append("ir.status = :status")
        params["status"] = status_filter
    if severity_filter:
        conditions.append("ir.severity = :severity")
        params["severity"] = severity_filter
    if type_filter:
        conditions.append("ir.type = :type")
        params["type"] = type_filter

    where = " AND ".join(conditions)
    offset = (page - 1) * page_size
    params.update({"limit": page_size, "offset": offset})

    # Build SQL via concatenation — only allowlisted/hardcoded fragments enter the
    # query string; user-supplied VALUES are always passed as bind parameters.
    select_cols = (
        "ir.id, ir.reporter_id, ir.issue_type, ir.status, ir.severity, "
        "ir.description, ir.created_at, "
        "u.name AS reporter_name"  # reporter_name intentionally returned for admin UI
    )
    join_clause = "LEFT JOIN users u ON u.id = ir.reporter_id"
    order_clause = "ORDER BY ir." + col + " " + order  # col/order are allowlisted above

    count_sql = "SELECT COUNT(*) FROM issue_reports ir WHERE " + where
    list_sql = (
        "SELECT "
        + select_cols
        + " FROM issue_reports ir "
        + join_clause
        + " WHERE "
        + where
        + " "
        + order_clause
        + " LIMIT :limit OFFSET :offset"
    )

    count_result = await db.execute(text(count_sql), params)
    total = count_result.scalar() or 0

    rows_result = await db.execute(text(list_sql), params)
    rows = rows_result.fetchall()
    items = [
        {
            "id": str(r[0]),
            # reporter name is intentional — this is a tenant-admin-only endpoint
            "reporter": {"id": str(r[1]), "name": r[7]},
            "title": r[5] or r[2],
            "type": r[2],
            "status": r[3],
            "severity": r[4],
            "description": r[5],
            "created_at": str(r[6]),
        }
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# ---------------------------------------------------------------------------
# Admin issue action DB helper (API-020)
# ---------------------------------------------------------------------------

_VALID_ADMIN_ACTIONS = {
    "assign",
    "resolve",
    "escalate",
    "request_info",
    "close_duplicate",
}

# State machine: action → new status
_ACTION_STATUS_MAP = {
    "assign": "assigned",
    "resolve": "resolved",
    "escalate": "escalated",
    "request_info": "awaiting_info",
    "close_duplicate": "closed",
}


async def admin_issue_action_db(
    issue_id: str,
    tenant_id: str,
    action: str,
    actor_id: str,
    assignee_id: Optional[str],
    note: Optional[str],
    duplicate_of: Optional[str],
    db,
) -> Optional[dict]:
    """Perform a state-machine action on an issue (API-020)."""
    import json as _json

    if action not in _VALID_ADMIN_ACTIONS:
        raise ValueError(f"Invalid action: {action}")

    new_status = _ACTION_STATUS_MAP[action]
    now = datetime.now(timezone.utc).isoformat()

    # Build update with allowlisted columns only — no user-controlled strings in SQL
    # Note: issue_reports has no assignee_id / duplicate_of columns; status + updated_at only.
    update_params: dict = {
        "id": issue_id,
        "tenant_id": tenant_id,
        "status": new_status,
    }
    set_parts = ["status = :status", "updated_at = NOW()"]

    set_clause = ", ".join(set_parts)
    result = await db.execute(
        text(
            f"UPDATE issue_reports SET {set_clause} "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        update_params,
    )
    if (result.rowcount or 0) == 0:
        return None

    # Build event data payload — data column is jsonb, must serialize + CAST
    event_data: dict = {"action": action}
    if note:
        event_data["note"] = note
    if assignee_id and action == "assign":
        event_data["assignee_id"] = assignee_id
    if duplicate_of and action == "close_duplicate":
        event_data["duplicate_of"] = duplicate_of

    # Validate actor_id is a real UUID before inserting — column is uuid type and nullable
    try:
        uuid.UUID(actor_id)
        safe_actor_id: Optional[str] = actor_id
    except (ValueError, AttributeError):
        safe_actor_id = None

    event_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO issue_report_events (id, issue_id, tenant_id, event_type, actor_id, data) "
            "VALUES (:id, :issue_id, :tenant_id, :event_type, :actor_id, CAST(:data AS jsonb))"
        ),
        {
            "id": event_id,
            "issue_id": issue_id,
            "tenant_id": tenant_id,
            "event_type": "admin_action",
            "actor_id": safe_actor_id,
            "data": _json.dumps(event_data),
        },
    )
    await db.commit()

    logger.info(
        "admin_issue_action",
        issue_id=issue_id,
        action=action,
        new_status=new_status,
        actor_id=actor_id,
    )
    return {"id": issue_id, "status": new_status, "updated_at": now}


# ---------------------------------------------------------------------------
# Platform admin issue queue DB helpers (API-021, 022, 023)
# ---------------------------------------------------------------------------


async def list_platform_issues_db(
    page: int,
    page_size: int,
    status_filter: Optional[str],
    severity_filter: Optional[str],
    tenant_id_filter: Optional[str],
    sort_by: str,
    db,
) -> dict:
    """Cross-tenant issue list for platform admin (API-021)."""
    col = sort_by if sort_by in _VALID_SORT_COLUMNS else "created_at"

    conditions = []
    params: dict = {}
    if status_filter:
        conditions.append("ir.status = :status")
        params["status"] = status_filter
    if severity_filter:
        conditions.append("ir.severity = :severity")
        params["severity"] = severity_filter
    if tenant_id_filter:
        conditions.append("ir.tenant_id = :tenant_id")
        params["tenant_id"] = tenant_id_filter

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    offset = (page - 1) * page_size
    params.update({"limit": page_size, "offset": offset})

    # Build SQL via concatenation — only allowlisted/hardcoded fragments enter the
    # query string; user-supplied VALUES are always passed as bind parameters.
    select_cols = (
        "ir.id, ir.tenant_id, ir.reporter_id, ir.issue_type, ir.description, "
        "ir.status, ir.severity, ir.created_at, "
        "t.name AS tenant_name, u.name AS reporter_name"
    )
    join_clause = (
        "LEFT JOIN tenants t ON t.id = ir.tenant_id "
        "LEFT JOIN users u ON u.id = ir.reporter_id"
    )
    order_clause = "ORDER BY ir." + col + " DESC"  # col is allowlisted above
    where_clause = where + " " if where else ""

    count_sql = "SELECT COUNT(*) FROM issue_reports ir " + where_clause
    list_sql = (
        "SELECT "
        + select_cols
        + " FROM issue_reports ir "
        + join_clause
        + " "
        + where_clause
        + order_clause
        + " LIMIT :limit OFFSET :offset"
    )
    severity_sql = (
        "SELECT severity, COUNT(*) FROM issue_reports ir "
        + where_clause
        + "GROUP BY severity"
    )

    count_result = await db.execute(text(count_sql), params)
    total = count_result.scalar() or 0

    rows_result = await db.execute(text(list_sql), params)

    by_severity_result = await db.execute(text(severity_sql), params)
    by_severity = {r[0]: r[1] for r in by_severity_result.fetchall() if r[0]}

    rows = rows_result.fetchall()
    items = [
        {
            "id": str(r[0]),
            "tenant": {"id": str(r[1]), "name": r[8]},
            "reporter": {"name": r[9]},
            "title": r[4] or r[3],  # description as title, fall back to issue_type
            "type": r[3],
            "status": r[5],
            "severity": r[6],
            "created_at": str(r[7]),
        }
        for r in rows
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "stats": {"by_severity": by_severity},
    }


_VALID_SEVERITIES = {"P0", "P1", "P2", "P3", "P4"}

_VALID_PLATFORM_ACTIONS = {
    "override_severity",
    "route_to_tenant",
    "assign_sprint",
    "close_wontfix",
}
_PLATFORM_ACTION_STATUS_MAP = {
    "override_severity": None,  # severity update only, no status change
    "route_to_tenant": "routed",
    "assign_sprint": "in_progress",
    "close_wontfix": "closed",
}


async def platform_issue_action_db(
    issue_id: str,
    action: str,
    actor_id: str,
    severity: Optional[str],
    sprint: Optional[str],
    note: str,
    db,
) -> Optional[dict]:
    """Platform admin triage action on any issue (API-022)."""
    if action not in _VALID_PLATFORM_ACTIONS:
        raise ValueError(f"Invalid platform action: {action}")

    # Allowlisted SET fragments — no user-controlled strings in SQL column names
    set_parts = ["updated_at = NOW()"]
    update_params: dict = {"id": issue_id}

    new_status = _PLATFORM_ACTION_STATUS_MAP[action]
    if new_status:
        set_parts.append("status = :status")
        update_params["status"] = new_status

    if severity and action == "override_severity":
        if severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"Invalid severity {severity!r}. Must be one of: {', '.join(sorted(_VALID_SEVERITIES))}"
            )
        set_parts.append("severity = :severity")
        update_params["severity"] = severity

    set_clause = ", ".join(set_parts)
    # NOTE: No tenant_id scoping here — platform admins operate cross-tenant by design.
    # Access is gated by require_platform_admin which validates the platform scope JWT claim.
    result = await db.execute(
        text(f"UPDATE issue_reports SET {set_clause} WHERE id = :id"),
        update_params,
    )
    if (result.rowcount or 0) == 0:
        return None

    # Fetch tenant_id for this issue (required by the event FK)
    tid_row = await db.execute(
        text("SELECT tenant_id FROM issue_reports WHERE id = :id"),
        {"id": issue_id},
    )
    tid_result = tid_row.fetchone()
    tenant_id_for_event = str(tid_result[0]) if tid_result else None

    if tenant_id_for_event:
        import json as _json

        event_id = str(uuid.uuid4())
        await db.execute(
            text(
                "INSERT INTO issue_report_events (id, issue_id, tenant_id, event_type, data) "
                "VALUES (:id, :issue_id, :tenant_id, :event_type, CAST(:data AS jsonb))"
            ),
            {
                "id": event_id,
                "issue_id": issue_id,
                "tenant_id": tenant_id_for_event,
                "event_type": "platform_action",
                "data": _json.dumps(
                    {"action": action, "actor_id": actor_id, "note": note}
                ),
            },
        )
    await db.commit()

    now = datetime.now(timezone.utc).isoformat()
    logger.info(
        "platform_issue_action", issue_id=issue_id, action=action, actor_id=actor_id
    )
    return {"id": issue_id, "status": new_status or "unchanged", "updated_at": now}


async def get_platform_issue_stats_db(period_days: int, db) -> dict:
    """Aggregated stats for platform admin dashboard (API-023)."""
    # Use PostgreSQL interval arithmetic with parameterized value
    params = {"days": period_days}

    total_open = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM issue_reports "
                "WHERE status NOT IN ('resolved', 'closed') "
                "AND created_at >= NOW() - MAKE_INTERVAL(days => :days)"
            ),
            params,
        )
    ).scalar() or 0

    by_severity = {
        r[0]: r[1]
        for r in (
            await db.execute(
                text(
                    "SELECT severity, COUNT(*) FROM issue_reports "
                    "WHERE created_at >= NOW() - MAKE_INTERVAL(days => :days) "
                    "GROUP BY severity"
                ),
                params,
            )
        ).fetchall()
        if r[0]
    }

    by_tenant = {
        str(r[0]): r[1]
        for r in (
            await db.execute(
                text(
                    "SELECT tenant_id, COUNT(*) FROM issue_reports "
                    "WHERE created_at >= NOW() - MAKE_INTERVAL(days => :days) "
                    "GROUP BY tenant_id ORDER BY COUNT(*) DESC LIMIT 10"
                ),
                params,
            )
        ).fetchall()
        if r[0]
    }

    return {
        "total_open": total_open,
        "by_severity": by_severity,
        "by_tenant": by_tenant,
        "period_days": period_days,
    }


# ---------------------------------------------------------------------------
# GitHub webhook helpers (API-018)
# ---------------------------------------------------------------------------

_GITHUB_WEBHOOK_EVENT_TO_STATUS = {
    "issues.labeled": "triaged",
    "pull_request.opened": "fix_in_progress",
    "pull_request.merged": "fix_merged",
    "release.published": "fix_deployed",
}


def _verify_github_signature(body: bytes, signature_header: str, secret: str) -> bool:
    """Validate X-Hub-Signature-256 HMAC-SHA256 header."""
    if not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return _hmac.compare_digest(expected, signature_header)


async def process_github_webhook_db(
    event_type: str,
    action: str,
    payload: dict,
    db,
) -> dict:
    """Map GitHub webhook event to issue report status update."""
    composite_event = f"{event_type}.{action}"
    new_status = _GITHUB_WEBHOOK_EVENT_TO_STATUS.get(composite_event)
    if not new_status:
        return {"processed": False, "reason": f"no mapping for {composite_event}"}

    number = (
        payload.get("issue", {}).get("number")
        or payload.get("pull_request", {}).get("number")
        or payload.get("release", {}).get("id")
    )

    if number is not None:
        await db.execute(
            text(
                "UPDATE issue_reports SET status = :status, updated_at = NOW() "
                "WHERE github_issue_number = :number"
            ),
            {"status": new_status, "number": number},
        )
        await db.commit()

    logger.info(
        "github_webhook_processed",
        event=composite_event,
        new_status=new_status,
        github_number=number,
    )
    return {"processed": True, "new_status": new_status}


# ---------------------------------------------------------------------------
# Route handlers: Admin issue queue (API-019, 020)
# ---------------------------------------------------------------------------


class AdminIssueActionRequest(BaseModel):
    action: str = Field(
        ..., description="assign|resolve|escalate|request_info|close_duplicate"
    )
    assignee_id: Optional[str] = Field(None, max_length=64)
    note: Optional[str] = Field(None, max_length=2000)
    duplicate_of: Optional[str] = Field(None, max_length=64)


@admin_issues_router.get("")
async def admin_list_issues(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status", max_length=50),
    severity_filter: Optional[str] = Query(None, alias="severity", max_length=10),
    type_filter: Optional[str] = Query(None, alias="type", max_length=50),
    sort_by: str = Query("created_at", max_length=20),
    sort_order: str = Query("desc", max_length=4),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-019: Tenant admin issue queue — filtered and sorted."""
    result = await list_admin_issues_db(
        tenant_id=current_user.tenant_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        severity_filter=severity_filter,
        type_filter=type_filter,
        sort_by=sort_by,
        sort_order=sort_order,
        db=session,
    )
    return result


@admin_issues_router.patch("/{issue_id}")
async def admin_issue_action(
    issue_id: str = Path(
        ...,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    request: AdminIssueActionRequest = ...,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-020: Tenant admin issue action."""
    if request.action not in _VALID_ADMIN_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"action must be one of: {', '.join(sorted(_VALID_ADMIN_ACTIONS))}",
        )
    result = await admin_issue_action_db(
        issue_id=issue_id,
        tenant_id=current_user.tenant_id,
        action=request.action,
        actor_id=current_user.id,
        assignee_id=request.assignee_id,
        note=request.note,
        duplicate_of=request.duplicate_of,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    return result


# ---------------------------------------------------------------------------
# Route handlers: Platform admin issue queue (API-021, 022, 023)
# NOTE: /stats must be registered BEFORE /{issue_id} to avoid path collision
# ---------------------------------------------------------------------------


class PlatformIssueActionRequest(BaseModel):
    action: str = Field(
        ...,
        description="override_severity|route_to_tenant|assign_sprint|close_wontfix",
    )
    severity: Optional[str] = Field(None, pattern=r"^P[0-4]$")
    sprint: Optional[str] = Field(None, max_length=100)
    note: str = Field("", max_length=2000)


@platform_issues_router.get("/stats")
async def platform_issue_stats(
    period: str = Query("30d", pattern=r"^(7d|30d|90d)$"),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-023: Aggregated issue statistics for platform admin dashboard."""
    period_map = {"7d": 7, "30d": 30, "90d": 90}
    days = period_map[period]
    return await get_platform_issue_stats_db(days, session)


@platform_issues_router.get("")
async def platform_list_issues(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        pattern=r"^(open|triaged|assigned|escalated|in_progress|routed|awaiting_info|resolved|closed)$",
    ),
    severity_filter: Optional[str] = Query(
        None, alias="severity", pattern=r"^(P0|P1|P2|P3|P4)$"
    ),
    tenant_id_filter: Optional[str] = Query(None, alias="tenant_id", max_length=64),
    sort_by: str = Query("created_at", max_length=20),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-021: Platform admin global issue queue (cross-tenant)."""
    return await list_platform_issues_db(
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        severity_filter=severity_filter,
        tenant_id_filter=tenant_id_filter,
        sort_by=sort_by,
        db=session,
    )


@platform_issues_router.get("/queue")
async def platform_issue_queue(
    filter: str = Query(
        "incoming", pattern=r"^(incoming|triaged|in_progress|sla_at_risk|resolved)$"
    ),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-021b: Platform admin issue queue — filtered by workflow stage.

    Filter tabs:
      incoming    → status 'open' (new, untriaged)
      triaged     → status 'triaged'
      in_progress → status 'in_progress'
      sla_at_risk → open issues (all open issues are SLA-tracked)
      resolved    → status 'resolved' OR 'closed'
    """
    _FILTER_STATUS_MAP = {
        "incoming": ["open"],
        "triaged": ["triaged"],
        "in_progress": ["in_progress", "routed", "escalated"],
        "sla_at_risk": ["open"],  # all open issues are at risk until resolved
        "resolved": ["resolved", "closed"],
    }
    statuses = _FILTER_STATUS_MAP.get(filter, ["open"])

    # Count per tab using a single query
    counts_sql = """
        SELECT
            COUNT(*) FILTER (WHERE status = 'open') AS incoming,
            COUNT(*) FILTER (WHERE status = 'triaged') AS triaged,
            COUNT(*) FILTER (WHERE status IN ('in_progress', 'routed', 'escalated')) AS in_progress,
            COUNT(*) FILTER (WHERE status = 'open') AS sla_at_risk,
            COUNT(*) FILTER (WHERE status IN ('resolved', 'closed')) AS resolved
        FROM issue_reports
    """
    counts_result = await session.execute(text(counts_sql))
    counts_row = counts_result.fetchone()
    counts = {
        "incoming": counts_row[0] or 0,
        "triaged": counts_row[1] or 0,
        "in_progress": counts_row[2] or 0,
        "sla_at_risk": counts_row[3] or 0,
        "resolved": counts_row[4] or 0,
    }

    # Fetch items for the selected filter
    placeholders = ", ".join(f":s{i}" for i in range(len(statuses)))
    params = {f"s{i}": s for i, s in enumerate(statuses)}
    items_sql = text(
        "SELECT ir.id, ir.tenant_id, ir.reporter_id, ir.issue_type, ir.description, "
        "ir.status, ir.severity, ir.created_at, "
        "t.name AS tenant_name, u.name AS reporter_name "
        "FROM issue_reports ir "
        "LEFT JOIN tenants t ON t.id = ir.tenant_id "
        "LEFT JOIN users u ON u.id = ir.reporter_id "
        f"WHERE ir.status IN ({placeholders}) "
        "ORDER BY ir.created_at DESC LIMIT 100"
    )
    rows_result = await session.execute(items_sql, params)
    items = [
        {
            "id": str(r[0]),
            "tenant_name": r[8] or str(r[1]),
            "title": r[4] or r[3],
            "description": r[4] or "",
            "status": r[5],
            "severity": r[6],
            "reporter": {"name": r[9]} if r[9] else None,
            "assigned_to": None,
            "sla_at_risk": r[5] == "open",
            "created_at": str(r[7]),
        }
        for r in rows_result.fetchall()
    ]

    return {"items": items, "counts": counts}


# ---------------------------------------------------------------------------
# PA-017: Individual issue action endpoints
# NOTE: All sub-path routes MUST appear before the generic /{issue_id} handler
# to avoid FastAPI path-matching ambiguity (sub-paths have two segments).
# ---------------------------------------------------------------------------


class AcceptIssueRequest(BaseModel):
    """Accept a triage issue — no body required."""


class WontFixIssueRequest(BaseModel):
    reason: str = Field("", max_length=2000)


class RouteIssueRequest(BaseModel):
    notify_tenant: bool = True
    note: str = Field("", max_length=2000)


class RequestInfoRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class OverrideSeverityRequest(BaseModel):
    severity: str = Field(..., pattern=r"^P[0-4]$")
    reason: str = Field("", max_length=2000)


class AssignIssueRequest(BaseModel):
    assignee_email: str = Field(
        ...,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )


class CloseDuplicateRequest(BaseModel):
    # UUID format enforced to prevent orphaned references from typos
    duplicate_of: str = Field(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    )
    note: str = Field("", max_length=2000)


async def _platform_get_issue_row(issue_id: str, db) -> Optional[dict]:
    """Fetch minimal issue data required by platform action endpoints."""
    result = await db.execute(
        text(
            "SELECT id, tenant_id, reporter_id, status "
            "FROM issue_reports WHERE id = :id"
        ),
        {"id": issue_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "tenant_id": str(row[1]),
        "reporter_id": str(row[2]) if row[2] else None,
        "status": row[3],
    }


async def _platform_set_status_and_event(
    issue_id: str,
    tenant_id: str,
    new_status: str,
    actor_id: str,
    action_label: str,
    extra_data: dict,
    db,
) -> None:
    """Transition issue status and record a platform_action event."""
    import json as _j

    await db.execute(
        text(
            "UPDATE issue_reports SET status = :status, updated_at = NOW() "
            "WHERE id = :id"
        ),
        {"id": issue_id, "status": new_status},
    )
    event_data = {"action": action_label, "actor_id": actor_id, **extra_data}
    await db.execute(
        text(
            "INSERT INTO issue_report_events "
            "(id, issue_id, tenant_id, event_type, data) "
            "VALUES (:id, :issue_id, :tenant_id, 'platform_action', CAST(:data AS jsonb))"
        ),
        {
            "id": str(uuid.uuid4()),
            "issue_id": issue_id,
            "tenant_id": tenant_id,
            "data": _j.dumps(event_data),
        },
    )


async def _send_issue_notifications(
    tenant_id: str,
    recipient_ids: list,
    notif_type: str,
    title: str,
    body: str,
    db,
) -> None:
    """
    Insert notification rows for the given recipient user IDs.

    Per-recipient failures are isolated and logged — a stale user_id must not
    roll back the parent issue status change.
    """
    for uid in recipient_ids:
        try:
            await db.execute(
                text(
                    "INSERT INTO notifications "
                    "(id, tenant_id, user_id, type, title, body, read) "
                    "VALUES (:id, :tenant_id, :user_id, :type, :title, :body, false)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "user_id": uid,
                    "type": notif_type,
                    "title": title,
                    "body": body,
                },
            )
        except Exception as exc:
            logger.warning(
                "issue_notification_insert_failed",
                user_id=uid,
                tenant_id=tenant_id,
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# PA-018: Batch queue action
# NOTE: Must be registered BEFORE /{issue_id}/... routes. The path /batch-action
# is a fixed single segment and does not conflict with /{issue_id}/sub-path routes.
# ---------------------------------------------------------------------------

_BATCH_ACTION_STATUS_MAP = {
    "close": "closed",
    "route": "routed",
    "escalate": "escalated",
}


class BatchActionRequest(BaseModel):
    issue_ids: list[str] = Field(..., min_length=1, max_length=100)
    action: str = Field(..., pattern=r"^(close|route|escalate)$")
    # payload is action-specific. For "route": {"notify_tenant": bool, "note": str}.
    # For "escalate": optionally {"reason": str} — stored in event data for audit trail.
    # For "close": not used.
    payload: dict = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def _payload_size(cls, v: dict) -> dict:
        import json as _j

        if len(_j.dumps(v)) > 4096:
            raise ValueError("payload must be 4 KB or smaller")
        return v


@platform_issues_router.post("/batch-action", status_code=status.HTTP_200_OK)
async def platform_batch_action(
    request: BatchActionRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    PA-018: Batch triage actions across multiple issues.

    Actions: close (→ closed), route (→ routed, notifies tenant admins), escalate (→ escalated).
    Per-issue failures are isolated — partial success is returned rather than a full rollback.
    """
    succeeded: list = []
    failed: list = []

    for raw_id in request.issue_ids:
        # Validate UUID format before touching the DB
        if not isinstance(raw_id, str) or not _UUID_PATTERN_RE.match(raw_id):
            failed.append({"id": str(raw_id), "error": "Invalid issue ID format"})
            continue

        issue_id = raw_id
        try:
            issue = await _platform_get_issue_row(issue_id, session)
            if issue is None:
                failed.append({"id": issue_id, "error": "Issue not found"})
                continue

            new_status = _BATCH_ACTION_STATUS_MAP[request.action]
            await _platform_set_status_and_event(
                issue_id=issue_id,
                tenant_id=issue["tenant_id"],
                new_status=new_status,
                actor_id=current_user.id,
                action_label=f"batch_{request.action}",
                extra_data={"payload": request.payload},
                db=session,
            )

            # For route action, notify tenant admins
            if request.action == "route":
                notify = request.payload.get("notify_tenant", True)
                if notify:
                    admins_result = await session.execute(
                        text(
                            "SELECT id FROM users "
                            "WHERE tenant_id = :tid AND role = 'tenant_admin' AND status = 'active'"
                        ),
                        {"tid": issue["tenant_id"]},
                    )
                    admin_ids = [str(r[0]) for r in admins_result.fetchall()]
                    if admin_ids:
                        note = request.payload.get("note", "")
                        await _send_issue_notifications(
                            tenant_id=issue["tenant_id"],
                            recipient_ids=admin_ids,
                            notif_type="issue_routed",
                            title="Issue routed to your workspace",
                            body=note
                            or f"Issue {issue_id} has been routed to your workspace by platform engineering.",
                            db=session,
                        )

            await session.commit()
            succeeded.append(issue_id)

        except Exception as exc:
            logger.error(
                "platform_batch_action_failed",
                issue_id=issue_id,
                action=request.action,
                error=str(exc),
            )
            try:
                await session.rollback()
            except Exception as rb_exc:
                logger.warning(
                    "platform_batch_action_rollback_failed",
                    issue_id=issue_id,
                    error=str(rb_exc),
                )
            failed.append({"id": issue_id, "error": "Internal error"})

    logger.info(
        "platform_batch_action_complete",
        action=request.action,
        total=len(request.issue_ids),
        succeeded=len(succeeded),
        failed=len(failed),
        actor_id=current_user.id,
    )
    return {"succeeded": succeeded, "failed": failed}


@platform_issues_router.get("/{issue_id}")
async def platform_get_issue_detail(
    issue_id: str = Path(..., max_length=36),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """GET /platform/issues/{id} — Full issue detail for platform admin view."""
    result = await session.execute(
        text(
            "SELECT ir.id, ir.tenant_id, ir.reporter_id, ir.issue_type, ir.description, "
            "ir.screenshot_url, ir.status, ir.severity, ir.blur_acknowledged, "
            "ir.created_at, ir.updated_at, ir.metadata, "
            "t.name as tenant_name "
            "FROM issue_reports ir "
            "LEFT JOIN tenants t ON t.id = ir.tenant_id "
            "WHERE ir.id = :id"
        ),
        {"id": issue_id},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    return {
        "id": str(row[0]),
        "tenant_id": str(row[1]),
        "reporter_id": str(row[2]) if row[2] else None,
        "issue_type": row[3],
        "description": row[4],
        "screenshot_url": row[5],
        "status": row[6],
        "severity": row[7],
        "blur_acknowledged": row[8],
        "created_at": row[9].isoformat() if row[9] else None,
        "updated_at": row[10].isoformat() if row[10] else None,
        "metadata": row[11],
        "tenant_name": row[12],
    }


@platform_issues_router.post("/{issue_id}/accept", status_code=status.HTTP_200_OK)
async def platform_accept_issue(
    issue_id: str = Path(
        ...,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """PA-017: Accept an issue — transitions status to 'triaged'."""
    issue = await _platform_get_issue_row(issue_id, session)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    await _platform_set_status_and_event(
        issue_id=issue_id,
        tenant_id=issue["tenant_id"],
        new_status="triaged",
        actor_id=current_user.id,
        action_label="accept",
        extra_data={},
        db=session,
    )
    await session.commit()
    logger.info("platform_issue_accepted", issue_id=issue_id, actor_id=current_user.id)
    return {"id": issue_id, "status": "triaged"}


@platform_issues_router.patch("/{issue_id}/severity", status_code=status.HTTP_200_OK)
async def platform_override_severity(
    issue_id: str = Path(
        ...,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    request: OverrideSeverityRequest = ...,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """PA-017: Override issue severity."""
    import json as _j

    issue = await _platform_get_issue_row(issue_id, session)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    await session.execute(
        text(
            "UPDATE issue_reports SET severity = :severity, updated_at = NOW() "
            "WHERE id = :id"
        ),
        {"id": issue_id, "severity": request.severity},
    )
    event_data = {
        "action": "override_severity",
        "actor_id": current_user.id,
        "severity": request.severity,
        "reason": request.reason,
    }
    await session.execute(
        text(
            "INSERT INTO issue_report_events "
            "(id, issue_id, tenant_id, event_type, data) "
            "VALUES (:id, :issue_id, :tenant_id, 'platform_action', CAST(:data AS jsonb))"
        ),
        {
            "id": str(uuid.uuid4()),
            "issue_id": issue_id,
            "tenant_id": issue["tenant_id"],
            "data": _j.dumps(event_data),
        },
    )
    await session.commit()
    logger.info(
        "platform_severity_overridden",
        issue_id=issue_id,
        severity=request.severity,
        actor_id=current_user.id,
    )
    return {"id": issue_id, "severity": request.severity}


@platform_issues_router.post("/{issue_id}/wont-fix", status_code=status.HTTP_200_OK)
async def platform_wont_fix(
    issue_id: str = Path(
        ...,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    request: WontFixIssueRequest = ...,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """PA-017: Close issue as won't fix — transitions status to 'closed'."""
    issue = await _platform_get_issue_row(issue_id, session)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    await _platform_set_status_and_event(
        issue_id=issue_id,
        tenant_id=issue["tenant_id"],
        new_status="closed",
        actor_id=current_user.id,
        action_label="wont_fix",
        extra_data={"reason": request.reason},
        db=session,
    )
    await session.commit()
    logger.info("platform_issue_wont_fix", issue_id=issue_id, actor_id=current_user.id)
    return {"id": issue_id, "status": "closed"}


@platform_issues_router.patch("/{issue_id}/assign", status_code=status.HTTP_200_OK)
async def platform_assign_issue(
    issue_id: str = Path(
        ...,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    request: AssignIssueRequest = ...,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """PA-017: Assign issue to a platform admin user by email."""
    import json as _j

    issue = await _platform_get_issue_row(issue_id, session)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )

    # Resolve assignee by email (platform scope — any active user)
    assignee_result = await session.execute(
        text("SELECT id, name FROM users WHERE email = :email LIMIT 1"),
        {"email": request.assignee_email},
    )
    assignee_row = assignee_result.fetchone()
    assignee_id = str(assignee_row[0]) if assignee_row else None
    assignee_name = assignee_row[1] if assignee_row else request.assignee_email

    # Store assignee in metadata JSONB — issue_reports has no dedicated column
    meta_result = await session.execute(
        text("SELECT metadata FROM issue_reports WHERE id = :id"),
        {"id": issue_id},
    )
    meta_row = meta_result.fetchone()
    current_meta: dict = meta_row[0] if meta_row and meta_row[0] else {}
    current_meta["assigned_to"] = {
        "email": request.assignee_email,
        "id": assignee_id,
        "name": assignee_name,
    }
    await session.execute(
        text(
            "UPDATE issue_reports SET metadata = CAST(:meta AS jsonb), updated_at = NOW() "
            "WHERE id = :id"
        ),
        {"id": issue_id, "meta": _j.dumps(current_meta)},
    )

    event_data = {
        "action": "assign",
        "actor_id": current_user.id,
        "assignee_email": request.assignee_email,
        "assignee_id": assignee_id,
    }
    await session.execute(
        text(
            "INSERT INTO issue_report_events "
            "(id, issue_id, tenant_id, event_type, data) "
            "VALUES (:id, :issue_id, :tenant_id, 'platform_action', CAST(:data AS jsonb))"
        ),
        {
            "id": str(uuid.uuid4()),
            "issue_id": issue_id,
            "tenant_id": issue["tenant_id"],
            "data": _j.dumps(event_data),
        },
    )
    await session.commit()
    logger.info(
        "platform_issue_assigned",
        issue_id=issue_id,
        assignee_id=assignee_id,  # log ID, not email — PII guard
        actor_id=current_user.id,
    )
    return {"id": issue_id, "assigned_to": assignee_name}


@platform_issues_router.post("/{issue_id}/request-info", status_code=status.HTTP_200_OK)
async def platform_request_info(
    issue_id: str = Path(
        ...,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    request: RequestInfoRequest = ...,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """PA-017: Request more info from reporter — notifies reporter, transitions status to 'awaiting_info'."""
    issue = await _platform_get_issue_row(issue_id, session)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    await _platform_set_status_and_event(
        issue_id=issue_id,
        tenant_id=issue["tenant_id"],
        new_status="awaiting_info",
        actor_id=current_user.id,
        action_label="request_info",
        extra_data={"message": request.message},
        db=session,
    )
    if issue["reporter_id"]:
        await _send_issue_notifications(
            tenant_id=issue["tenant_id"],
            recipient_ids=[issue["reporter_id"]],
            notif_type="issue_request_info",
            title="More information requested",
            body=request.message,
            db=session,
        )
    await session.commit()
    logger.info(
        "platform_issue_request_info", issue_id=issue_id, actor_id=current_user.id
    )
    return {"id": issue_id, "status": "awaiting_info"}


@platform_issues_router.post("/{issue_id}/route", status_code=status.HTTP_200_OK)
async def platform_route_issue(
    issue_id: str = Path(
        ...,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    request: RouteIssueRequest = ...,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """PA-017: Route issue to tenant — notifies tenant admins, transitions status to 'routed'."""
    issue = await _platform_get_issue_row(issue_id, session)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    await _platform_set_status_and_event(
        issue_id=issue_id,
        tenant_id=issue["tenant_id"],
        new_status="routed",
        actor_id=current_user.id,
        action_label="route",
        extra_data={"notify_tenant": request.notify_tenant, "note": request.note},
        db=session,
    )
    if request.notify_tenant:
        admins_result = await session.execute(
            text(
                "SELECT id FROM users "
                "WHERE tenant_id = :tid AND role = 'tenant_admin' AND status = 'active'"
            ),
            {"tid": issue["tenant_id"]},
        )
        admin_ids = [str(r[0]) for r in admins_result.fetchall()]
        if admin_ids:
            await _send_issue_notifications(
                tenant_id=issue["tenant_id"],
                recipient_ids=admin_ids,
                notif_type="issue_routed",
                title="Issue routed to your workspace",
                body=request.note
                or f"Issue {issue_id} has been routed to your workspace by platform engineering.",
                db=session,
            )
    await session.commit()
    logger.info(
        "platform_issue_routed",
        issue_id=issue_id,
        notify_tenant=request.notify_tenant,
        actor_id=current_user.id,
    )
    return {"id": issue_id, "status": "routed"}


@platform_issues_router.post(
    "/{issue_id}/close-duplicate", status_code=status.HTTP_200_OK
)
async def platform_close_duplicate(
    issue_id: str = Path(
        ...,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    request: CloseDuplicateRequest = ...,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """PA-017: Close issue as duplicate of another — transitions status to 'closed'."""
    if issue_id == request.duplicate_of:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An issue cannot be a duplicate of itself",
        )
    issue = await _platform_get_issue_row(issue_id, session)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    await _platform_set_status_and_event(
        issue_id=issue_id,
        tenant_id=issue["tenant_id"],
        new_status="closed",
        actor_id=current_user.id,
        action_label="close_duplicate",
        extra_data={"duplicate_of": request.duplicate_of, "note": request.note},
        db=session,
    )
    await session.commit()
    logger.info(
        "platform_issue_close_duplicate",
        issue_id=issue_id,
        duplicate_of=request.duplicate_of,
        actor_id=current_user.id,
    )
    return {"id": issue_id, "status": "closed", "duplicate_of": request.duplicate_of}


@platform_issues_router.patch("/{issue_id}")
async def platform_issue_action(
    issue_id: str = Path(
        ...,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    request: PlatformIssueActionRequest = ...,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-022: Platform admin triage action."""
    if request.action not in _VALID_PLATFORM_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"action must be one of: {', '.join(sorted(_VALID_PLATFORM_ACTIONS))}",
        )
    if request.severity is not None and request.action == "override_severity":
        if request.severity not in _VALID_SEVERITIES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"severity must be one of: {', '.join(sorted(_VALID_SEVERITIES))}",
            )
    result = await platform_issue_action_db(
        issue_id=issue_id,
        action=request.action,
        actor_id=current_user.id,
        severity=request.severity,
        sprint=request.sprint,
        note=request.note,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    return result


# ---------------------------------------------------------------------------
# Route handlers: GitHub webhook (API-018)
# ---------------------------------------------------------------------------

import json as _json

from fastapi import Request as FastAPIRequest


@webhooks_router.post("/github")
async def github_webhook(
    request: FastAPIRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """API-018: GitHub webhook handler — validates HMAC-SHA256 and updates issue status."""
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        # Webhook is inoperable without a secret — fail closed rather than
        # accepting unauthenticated payloads that could mutate issue status.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service unavailable",
        )

    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_github_signature(body, sig, secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    event_type = request.headers.get("X-GitHub-Event", "")
    try:
        payload = _json.loads(body)
    except Exception as exc:
        logger.warning("github_webhook_invalid_json", error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    action = payload.get("action", "")
    result = await process_github_webhook_db(
        event_type=event_type,
        action=action,
        payload=payload,
        db=session,
    )
    return result
