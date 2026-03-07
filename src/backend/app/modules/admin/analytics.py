"""
Analytics API endpoints for Tenant Admin feedback monitoring (FE-037, API-074, API-075).

Endpoints:
- GET /admin/analytics/satisfaction  -- satisfaction analytics with period, per_agent, trend
- GET /admin/analytics/low-confidence -- Low retrieval-confidence messages
- GET /admin/analytics/engagement    -- DAU/WAU/MAU engagement analytics
"""
import os
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
# Allowlists
# ---------------------------------------------------------------------------

_VALID_PERIODS = {"7d", "30d", "90d"}
_PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90}


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


async def get_satisfaction_overall_db(
    tenant_id: str, days: int, db: AsyncSession
) -> tuple[float, int]:
    """
    Get overall satisfaction rate and total ratings for a given period.

    Returns (satisfaction_rate, total_ratings).
    """
    try:
        result = await db.execute(
            text(
                "SELECT "
                "  COUNT(*) AS total, "
                "  COUNT(CASE WHEN rating = 1 THEN 1 END) AS positive "
                "FROM user_feedback "
                "WHERE tenant_id = :tenant_id "
                "  AND created_at >= NOW() - INTERVAL '1 day' * :days"
            ),
            {"tenant_id": tenant_id, "days": days},
        )
        row = result.fetchone()
        if row is None or row[0] == 0:
            return 0.0, 0
        total = int(row[0])
        positive = int(row[1])
        rate = round(100.0 * positive / total, 1)
        return rate, total
    except Exception as exc:
        logger.warning(
            "satisfaction_overall_query_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )
        return 0.0, 0


async def get_satisfaction_per_agent_db(
    tenant_id: str, days: int, db: AsyncSession
) -> list[dict]:
    """
    Get per-agent satisfaction breakdown for the period.

    Joins user_feedback → messages → agent_cards.
    ac.id is UUID; messages.metadata->>'agent_id' is text, so cast ac.id::text.
    """
    try:
        result = await db.execute(
            text(
                "SELECT "
                "  ac.id AS agent_id, "
                "  ac.name AS agent_name, "
                "  COUNT(uf.id) AS ratings_count, "
                "  ROUND(100.0 * COUNT(CASE WHEN uf.rating = 1 THEN 1 END) / COUNT(uf.id), 1) AS satisfaction_rate "
                "FROM user_feedback uf "
                "JOIN messages m ON m.id = uf.message_id "
                "JOIN agent_cards ac ON ac.id::text = m.metadata->>'agent_id' "
                "WHERE uf.tenant_id = :tenant_id "
                "  AND uf.created_at >= NOW() - INTERVAL '1 day' * :days "
                "  AND ac.tenant_id = :tenant_id "
                "GROUP BY ac.id, ac.name "
                "ORDER BY ratings_count DESC"
            ),
            {"tenant_id": tenant_id, "days": days},
        )
        rows = result.fetchall()
        return [
            {
                "agent_id": str(row[0]),
                "name": str(row[1]),
                "satisfaction_rate": float(row[3]) if row[3] is not None else 0.0,
                "ratings_count": int(row[2]),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning(
            "satisfaction_per_agent_query_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )
        return []


async def get_satisfaction_trend_period_db(
    tenant_id: str, days: int, db: AsyncSession
) -> list[dict]:
    """
    Get daily satisfaction rate for the period.

    Returns list of {date, rate} dicts.
    """
    try:
        result = await db.execute(
            text(
                "SELECT "
                "  d.day::date AS date, "
                "  CASE "
                "    WHEN COUNT(uf.id) = 0 THEN 0.0 "
                "    ELSE ROUND(100.0 * COUNT(CASE WHEN uf.rating = 1 THEN 1 END) / COUNT(uf.id), 1) "
                "  END AS rate "
                "FROM generate_series("
                "  CURRENT_DATE - INTERVAL '1 day' * (:days - 1), "
                "  CURRENT_DATE, "
                "  INTERVAL '1 day'"
                ") AS d(day) "
                "LEFT JOIN user_feedback uf "
                "  ON uf.tenant_id = :tenant_id "
                "  AND uf.created_at::date = d.day::date "
                "GROUP BY d.day "
                "ORDER BY d.day ASC"
            ),
            {"tenant_id": tenant_id, "days": days},
        )
        rows = result.fetchall()
        return [
            {
                "date": str(row[0]),
                "rate": float(row[1]),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning(
            "satisfaction_trend_period_query_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )
        return []


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


async def get_engagement_db(
    tenant_id: str, days: int, agent_id: Optional[str], db: AsyncSession
) -> dict:
    """
    Get engagement metrics: DAU, WAU, MAU, inactive users, feature adoption.

    DAU/WAU/MAU are computed from messages (distinct users).
    """
    base_filter = "WHERE m.tenant_id = :tenant_id"
    params: dict = {"tenant_id": tenant_id}

    if agent_id:
        base_filter += " AND m.metadata->>'agent_id' = :agent_id"
        params["agent_id"] = agent_id

    # DAU, WAU, MAU
    dau_result = await db.execute(
        text(
            f"SELECT COUNT(DISTINCT c.user_id) "
            f"FROM messages m "
            f"JOIN conversations c ON c.id = m.conversation_id "
            f"{base_filter} "
            f"AND m.role = 'user' "
            f"AND m.created_at >= NOW() - INTERVAL '1 day'"
        ),
        params,
    )
    dau = int(dau_result.scalar_one() or 0)

    wau_result = await db.execute(
        text(
            f"SELECT COUNT(DISTINCT c.user_id) "
            f"FROM messages m "
            f"JOIN conversations c ON c.id = m.conversation_id "
            f"{base_filter} "
            f"AND m.role = 'user' "
            f"AND m.created_at >= NOW() - INTERVAL '7 days'"
        ),
        params,
    )
    wau = int(wau_result.scalar_one() or 0)

    mau_result = await db.execute(
        text(
            f"SELECT COUNT(DISTINCT c.user_id) "
            f"FROM messages m "
            f"JOIN conversations c ON c.id = m.conversation_id "
            f"{base_filter} "
            f"AND m.role = 'user' "
            f"AND m.created_at >= NOW() - INTERVAL '30 days'"
        ),
        params,
    )
    mau = int(mau_result.scalar_one() or 0)

    # Total users for this tenant
    total_users_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM users "
            "WHERE tenant_id = :tenant_id AND status = 'active'"
        ),
        {"tenant_id": tenant_id},
    )
    total_users = int(total_users_result.scalar_one() or 0)

    # Inactive users: users with no messages in last 30 days
    active_30d_result = await db.execute(
        text(
            "SELECT COUNT(DISTINCT c.user_id) "
            "FROM messages m "
            "JOIN conversations c ON c.id = m.conversation_id "
            "WHERE m.tenant_id = :tenant_id "
            "  AND m.role = 'user' "
            "  AND m.created_at >= NOW() - INTERVAL '30 days'"
        ),
        {"tenant_id": tenant_id},
    )
    active_30d = int(active_30d_result.scalar_one() or 0)
    inactive_count = max(0, total_users - active_30d)
    inactive_pct = (
        round(100.0 * inactive_count / total_users, 1) if total_users > 0 else 0.0
    )

    # Feature adoption: memory_notes
    users_with_notes_result = await db.execute(
        text(
            "SELECT COUNT(DISTINCT user_id) FROM memory_notes "
            "WHERE tenant_id = :tenant_id"
        ),
        {"tenant_id": tenant_id},
    )
    users_with_notes = int(users_with_notes_result.scalar_one() or 0)
    memory_notes_adoption = (
        round(users_with_notes / total_users, 4) if total_users > 0 else 0.0
    )

    # Feature adoption: feedback (% of conversations with at least 1 feedback)
    total_convs_result = await db.execute(
        text("SELECT COUNT(*) FROM conversations WHERE tenant_id = :tenant_id"),
        {"tenant_id": tenant_id},
    )
    total_convs = int(total_convs_result.scalar_one() or 0)

    convs_with_feedback_result = await db.execute(
        text(
            "SELECT COUNT(DISTINCT m.conversation_id) "
            "FROM user_feedback uf "
            "JOIN messages m ON m.id = uf.message_id "
            "WHERE uf.tenant_id = :tenant_id"
        ),
        {"tenant_id": tenant_id},
    )
    convs_with_feedback = int(convs_with_feedback_result.scalar_one() or 0)
    feedback_adoption = (
        round(convs_with_feedback / total_convs, 4) if total_convs > 0 else 0.0
    )

    # Feature adoption: glossary queries (% of messages with glossary expansion)
    total_msgs_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM messages "
            "WHERE tenant_id = :tenant_id AND role = 'user'"
        ),
        {"tenant_id": tenant_id},
    )
    total_msgs = int(total_msgs_result.scalar_one() or 0)

    glossary_msgs_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM messages "
            "WHERE tenant_id = :tenant_id "
            "  AND role = 'user' "
            "  AND metadata->>'glossary_expanded' = 'true'"
        ),
        {"tenant_id": tenant_id},
    )
    glossary_msgs = int(glossary_msgs_result.scalar_one() or 0)
    glossary_adoption = round(glossary_msgs / total_msgs, 4) if total_msgs > 0 else 0.0

    # Per-agent DAU/WAU
    per_agent_result = await db.execute(
        text(
            "SELECT "
            "  ac.id AS agent_id, "
            "  ac.name AS agent_name, "
            "  COUNT(DISTINCT CASE WHEN m.created_at >= NOW() - INTERVAL '1 day' THEN c.user_id END) AS dau, "
            "  COUNT(DISTINCT CASE WHEN m.created_at >= NOW() - INTERVAL '7 days' THEN c.user_id END) AS wau "
            "FROM messages m "
            "JOIN conversations c ON c.id = m.conversation_id "
            "JOIN agent_cards ac ON ac.id::text = m.metadata->>'agent_id' "
            "WHERE m.tenant_id = :tenant_id "
            "  AND m.role = 'user' "
            "  AND ac.tenant_id = :tenant_id "
            "GROUP BY ac.id, ac.name "
            "ORDER BY wau DESC"
        ),
        {"tenant_id": tenant_id},
    )
    per_agent_rows = per_agent_result.fetchall()
    per_agent = [
        {
            "agent_id": str(row[0]),
            "name": str(row[1]),
            "dau": int(row[2] or 0),
            "wau": int(row[3] or 0),
        }
        for row in per_agent_rows
    ]

    return {
        "dau": dau,
        "wau": wau,
        "mau": mau,
        "inactive_users": {
            "count": inactive_count,
            "pct": inactive_pct,
        },
        "feature_adoption": {
            "memory_notes": memory_notes_adoption,
            "glossary_queries": glossary_adoption,
            "feedback": feedback_adoption,
        },
        "per_agent": per_agent,
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/analytics/satisfaction")
async def get_satisfaction(
    period: str = Query("30d", description="Time period: 7d or 30d"),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-074: Get satisfaction analytics with period filter, per-agent breakdown,
    daily trend, and not_enough_data flag.

    Auth: tenant_admin required.
    """
    if period not in ("7d", "30d"):
        period = "30d"

    days = _PERIOD_DAYS.get(period, 30)

    overall_rate, total_ratings = await get_satisfaction_overall_db(
        tenant_id=current_user.tenant_id, days=days, db=session
    )
    not_enough_data = total_ratings < 50

    per_agent = await get_satisfaction_per_agent_db(
        tenant_id=current_user.tenant_id, days=days, db=session
    )

    trend = await get_satisfaction_trend_period_db(
        tenant_id=current_user.tenant_id, days=days, db=session
    )

    # Legacy fields (kept for backward compatibility with existing tests)
    trend_30d = await get_satisfaction_trend_db(
        tenant_id=current_user.tenant_id, db=session
    )
    satisfaction_7d = await get_satisfaction_7d_db(
        tenant_id=current_user.tenant_id, db=session
    )

    logger.info(
        "satisfaction_analytics_fetched",
        tenant_id=current_user.tenant_id,
        period=period,
        total_ratings=total_ratings,
        overall_rate=overall_rate,
    )

    return {
        "overall_rate": overall_rate,
        "total_ratings": total_ratings,
        "period": period,
        "per_agent": per_agent,
        # "trend" retains the legacy 30-day per-day breakdown (backward compat)
        "trend": trend_30d,
        # "daily_trend" is the period-scoped trend (new API-074 field)
        "daily_trend": trend,
        "not_enough_data": not_enough_data,
        "satisfaction_7d": satisfaction_7d,
    }


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


@router.get("/analytics/engagement")
async def get_engagement(
    period: str = Query("30d", description="Time period: 7d, 30d, or 90d"),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-075: Get engagement analytics (DAU/WAU/MAU, inactive users, feature adoption).

    Auth: tenant_admin required.
    """
    if period not in _VALID_PERIODS:
        period = "30d"

    days = _PERIOD_DAYS[period]

    data = await get_engagement_db(
        tenant_id=current_user.tenant_id,
        days=days,
        agent_id=agent_id,
        db=session,
    )

    logger.info(
        "engagement_analytics_fetched",
        tenant_id=current_user.tenant_id,
        period=period,
        dau=data["dau"],
        mau=data["mau"],
    )

    return {
        "dau": data["dau"],
        "wau": data["wau"],
        "mau": data["mau"],
        "period": period,
        "per_agent": data["per_agent"],
        "inactive_users": data["inactive_users"],
        "feature_adoption": data["feature_adoption"],
    }
