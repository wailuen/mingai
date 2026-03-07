"""
Analytics API endpoints for Tenant Admin feedback monitoring (FE-037).

Endpoints:
- GET /admin/analytics/satisfaction  -- 30-day satisfaction trend + 7-day rolling
- GET /admin/analytics/low-confidence -- Low retrieval-confidence messages
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin-analytics"])


# ---------------------------------------------------------------------------
# DB helper functions (mockable in unit tests)
# ---------------------------------------------------------------------------


async def get_satisfaction_trend_db(tenant_id: str, db: AsyncSession) -> list[dict]:
    """
    Get 30-day rolling satisfaction data.

    For each of the last 30 days, count positive (rating=1) vs total ratings,
    returning satisfaction_pct and total count.
    """
    result = await db.execute(
        text(
            "SELECT "
            "  d.day::date AS date, "
            "  COALESCE(COUNT(uf.id), 0) AS total, "
            "  CASE "
            "    WHEN COUNT(uf.id) = 0 THEN 0.0 "
            "    ELSE ROUND(100.0 * COUNT(CASE WHEN uf.rating = 1 THEN 1 END) / COUNT(uf.id), 1) "
            "  END AS satisfaction_pct "
            "FROM generate_series("
            "  CURRENT_DATE - INTERVAL '29 days', "
            "  CURRENT_DATE, "
            "  INTERVAL '1 day'"
            ") AS d(day) "
            "LEFT JOIN user_feedback uf "
            "  ON uf.tenant_id = :tenant_id "
            "  AND uf.created_at::date = d.day::date "
            "GROUP BY d.day "
            "ORDER BY d.day ASC"
        ),
        {"tenant_id": tenant_id},
    )
    rows = result.fetchall()
    return [
        {
            "date": str(row[0]),
            "total": int(row[1]),
            "satisfaction_pct": float(row[2]),
        }
        for row in rows
    ]


async def get_satisfaction_7d_db(tenant_id: str, db: AsyncSession) -> float:
    """
    Get 7-day rolling satisfaction percentage.

    Returns 0.0 if no feedback in the last 7 days.
    """
    result = await db.execute(
        text(
            "SELECT "
            "  COUNT(*) AS total, "
            "  COUNT(CASE WHEN rating = 1 THEN 1 END) AS positive "
            "FROM user_feedback "
            "WHERE tenant_id = :tenant_id "
            "  AND created_at >= CURRENT_DATE - INTERVAL '7 days'"
        ),
        {"tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None or row[0] == 0:
        return 0.0
    return round(100.0 * row[1] / row[0], 1)


async def get_low_confidence_messages_db(
    tenant_id: str,
    limit: int,
    db: AsyncSession,
) -> list[dict]:
    """
    Get messages with low retrieval confidence (< 0.6).

    Uses the retrieval_confidence column on the messages table.
    Falls back to metadata->>'retrieval_confidence' if the column
    approach returns no results and metadata exists.
    """
    try:
        result = await db.execute(
            text(
                "SELECT m.id, m.content, m.created_at, m.retrieval_confidence "
                "FROM messages m "
                "WHERE m.tenant_id = :tenant_id "
                "  AND m.retrieval_confidence IS NOT NULL "
                "  AND m.retrieval_confidence < 0.6 "
                "ORDER BY m.created_at DESC "
                "LIMIT :limit"
            ),
            {"tenant_id": tenant_id, "limit": limit},
        )
        rows = result.fetchall()

        if not rows:
            # Try metadata JSONB fallback
            result = await db.execute(
                text(
                    "SELECT m.id, m.content, m.created_at, "
                    "  CAST(m.metadata->>'retrieval_confidence' AS FLOAT) AS conf "
                    "FROM messages m "
                    "WHERE m.tenant_id = :tenant_id "
                    "  AND m.metadata->>'retrieval_confidence' IS NOT NULL "
                    "  AND CAST(m.metadata->>'retrieval_confidence' AS FLOAT) < 0.6 "
                    "ORDER BY m.created_at DESC "
                    "LIMIT :limit"
                ),
                {"tenant_id": tenant_id, "limit": limit},
            )
            rows = result.fetchall()

        return [
            {
                "message_id": str(row[0]),
                "query_text": row[1][:200] if row[1] else "",
                "created_at": str(row[2]),
                "retrieval_confidence": float(row[3]) if row[3] is not None else 0.0,
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning(
            "low_confidence_query_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )
        return []


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/analytics/satisfaction")
async def get_satisfaction(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    FE-037: Get 30-day satisfaction trend and 7-day rolling score.

    Auth: tenant_admin required.
    """
    trend = await get_satisfaction_trend_db(
        tenant_id=current_user.tenant_id, db=session
    )
    satisfaction_7d = await get_satisfaction_7d_db(
        tenant_id=current_user.tenant_id, db=session
    )

    logger.info(
        "satisfaction_analytics_fetched",
        tenant_id=current_user.tenant_id,
        trend_count=len(trend),
        satisfaction_7d=satisfaction_7d,
    )

    return {"trend": trend, "satisfaction_7d": satisfaction_7d}


@router.get("/analytics/low-confidence")
async def get_low_confidence(
    limit: int = Query(20, ge=1, le=50, description="Max items to return (1-50)"),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    FE-037: Get messages with low retrieval confidence (< 0.6).

    Auth: tenant_admin required.
    """
    items = await get_low_confidence_messages_db(
        tenant_id=current_user.tenant_id,
        limit=limit,
        db=session,
    )

    logger.info(
        "low_confidence_analytics_fetched",
        tenant_id=current_user.tenant_id,
        item_count=len(items),
        limit=limit,
    )

    return {"items": items}
