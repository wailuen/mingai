"""
Platform Admin API endpoints.

Provides dashboard stats and platform-level management endpoints.
All endpoints require platform admin scope (scope='platform').
"""
from datetime import date, datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["platform"])


class DashboardStatsResponse(BaseModel):
    """Platform dashboard statistics returned to the frontend."""

    active_users: int
    documents_indexed: int
    queries_today: int
    satisfaction_pct: float


@router.get("/dashboard", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> DashboardStatsResponse:
    """
    GET /api/v1/admin/dashboard

    Returns platform-level dashboard statistics.
    Requires platform admin scope -- returns 403 for non-platform users.

    Stats are queried from real database tables:
    - active_users: COUNT of users with status='active' across all tenants
    - documents_indexed: SUM of files_synced from completed sync_jobs
    - queries_today: COUNT of messages with role='user' created today
    - satisfaction_pct: percentage of positive feedback (rating=1) from user_feedback
    """
    if current_user.scope != "platform":
        logger.warning(
            "dashboard_access_denied",
            user_id=current_user.id,
            scope=current_user.scope,
            required_scope="platform",
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "Platform admin access required. "
                f"Your scope is '{current_user.scope}' but 'platform' is needed."
            ),
        )

    logger.info(
        "dashboard_stats_requested",
        user_id=current_user.id,
        scope=current_user.scope,
    )

    # Query active users count from the users table
    active_users_result = await session.execute(
        text("SELECT COUNT(*) FROM users WHERE status = 'active'")
    )
    active_users = active_users_result.scalar_one()

    # Query documents indexed: SUM of files_synced from completed sync jobs
    # sync_jobs tracks file ingestion; files_synced is the count of successfully indexed files
    docs_result = await session.execute(
        text(
            "SELECT COALESCE(SUM(files_synced), 0) "
            "FROM sync_jobs WHERE status = 'completed'"
        )
    )
    documents_indexed = docs_result.scalar_one()

    # Query messages created today with role='user' (user queries)
    today_start = datetime.combine(
        date.today(), datetime.min.time(), tzinfo=timezone.utc
    )
    queries_result = await session.execute(
        text(
            "SELECT COUNT(*) FROM messages "
            "WHERE role = 'user' AND created_at >= :today_start"
        ),
        {"today_start": today_start},
    )
    queries_today = queries_result.scalar_one()

    # Calculate satisfaction percentage from user_feedback
    # rating=1 is positive (thumbs up), rating=-1 is negative (thumbs down)
    feedback_result = await session.execute(
        text(
            "SELECT "
            "  COUNT(*) AS total, "
            "  COUNT(*) FILTER (WHERE rating = 1) AS positive "
            "FROM user_feedback"
        )
    )
    feedback_row = feedback_result.one()
    total_feedback = feedback_row.total
    positive_feedback = feedback_row.positive

    if total_feedback > 0:
        satisfaction_pct = round((positive_feedback / total_feedback) * 100, 1)
    else:
        # No feedback yet -- 0.0 is the honest value, not a default
        satisfaction_pct = 0.0

    logger.info(
        "dashboard_stats_returned",
        user_id=current_user.id,
        active_users=active_users,
        documents_indexed=documents_indexed,
        queries_today=queries_today,
        satisfaction_pct=satisfaction_pct,
    )

    return DashboardStatsResponse(
        active_users=active_users,
        documents_indexed=documents_indexed,
        queries_today=queries_today,
        satisfaction_pct=satisfaction_pct,
    )
