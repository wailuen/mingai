"""
Issue Reports API routes (API-013).

Endpoints:
- GET    /issues                      — List tenant issues (tenant admin only)
- POST   /issues                      — Create issue (any authenticated user)
- GET    /issues/{issue_id}           — Get issue (tenant admin or issue owner)
- PATCH  /issues/{issue_id}/status    — Update status (tenant admin only)
- POST   /issues/{issue_id}/events    — Add event/comment (tenant admin only)

Schema: issue_reports(id, tenant_id, user_id, title, description,
        screenshot_url, status, blur_acknowledged, created_at)

Note: /issues/{issue_id}/status and /issues/{issue_id}/events routes must
be registered BEFORE /{issue_id} to avoid path collision.
"""
import uuid
from enum import Enum
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

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


class CreateIssueRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=2000)
    screenshot_url: Optional[str] = Field(None, max_length=500)
    blur_acknowledged: bool = Field(False)


class UpdateIssueStatusRequest(BaseModel):
    status: IssueStatus


class AddIssueEventRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


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
                "SELECT id, user_id, title, description, screenshot_url, status, "
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
                "SELECT id, user_id, title, description, screenshot_url, status, "
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
            "user_id": str(r[1]),
            "title": r[2],
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
    user_id: str,
    title: str,
    description: str,
    screenshot_url: Optional[str],
    blur_acknowledged: bool,
    db,
) -> dict:
    """Create a new issue report."""
    issue_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO issue_reports "
            "(id, tenant_id, user_id, title, description, screenshot_url, status, blur_acknowledged) "
            "VALUES (:id, :tenant_id, :user_id, :title, :description, :screenshot_url, :status, :blur_acknowledged)"
        ),
        {
            "id": issue_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "title": title,
            "description": description,
            "screenshot_url": screenshot_url,
            "status": "open",
            "blur_acknowledged": blur_acknowledged,
        },
    )
    await db.commit()

    # Trigger blur pipeline if screenshot is attached
    if screenshot_url:
        logger.info(
            "issue_screenshot_attached",
            issue_id=issue_id,
            screenshot_url=screenshot_url,
            blur_acknowledged=blur_acknowledged,
        )

    logger.info(
        "issue_created",
        issue_id=issue_id,
        title=title,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    return {
        "id": issue_id,
        "title": title,
        "description": description,
        "screenshot_url": screenshot_url,
        "status": "open",
        "blur_acknowledged": blur_acknowledged,
        "tenant_id": tenant_id,
        "user_id": user_id,
    }


async def get_issue_db(issue_id: str, tenant_id: str, db) -> Optional[dict]:
    """Get an issue report by ID, scoped to tenant."""
    result = await db.execute(
        text(
            "SELECT id, user_id, title, description, screenshot_url, status, "
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
        "user_id": str(row[1]),
        "title": row[2],
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
            detail=f"Issue '{issue_id}' not found",
        )

    event_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO issue_events (id, issue_id, user_id, content) "
            "VALUES (:id, :issue_id, :user_id, :content)"
        ),
        {
            "id": event_id,
            "issue_id": issue_id,
            "user_id": user_id,
            "content": content,
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
        status_filter=status_filter,
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
        user_id=current_user.id,
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
            detail=f"Issue '{issue_id}' not found",
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
            detail=f"Issue '{issue_id}' not found",
        )

    # Authorization: tenant admins can see all issues; others can only see their own
    is_admin = "tenant_admin" in current_user.roles
    is_owner = result["user_id"] == current_user.id
    if not is_admin and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own issues",
        )

    return result
