"""
Analytics API endpoints for Tenant Admin feedback monitoring (FE-037, API-074, API-075).
Also implements TA-026 through TA-030 analytics APIs.

Endpoints:
- GET /admin/analytics/satisfaction         -- satisfaction analytics with period, per_agent, trend (TA-026)
- GET /admin/analytics/low-confidence       -- Low retrieval-confidence messages
- GET /admin/analytics/engagement           -- DAU/WAU/MAU engagement analytics (TA-030)
- GET /admin/agents/{id}/analytics          -- Agent performance detail with root cause correlation (TA-027/028)
- GET /admin/glossary/analytics             -- Glossary term performance analytics (TA-029)
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


# ---------------------------------------------------------------------------
# TA-026: Satisfaction Dashboard — new response shape
# ---------------------------------------------------------------------------


async def get_satisfaction_dashboard_db(tenant_id: str, db: AsyncSession) -> dict:
    """
    TA-026: Compute 7-day rolling rate, total feedback count, per-agent stats,
    and 30-day daily trend.

    Conversations table has agent_id UUID directly.
    user_feedback does not join via messages→conversations for agent;
    we join: user_feedback → messages → conversations to get agent_id.
    """
    # Rolling 7d rate + total count
    rate_result = await db.execute(
        text(
            "SELECT "
            "  COUNT(*) AS total, "
            "  COUNT(CASE WHEN uf.rating = 1 THEN 1 END) AS positive "
            "FROM user_feedback uf "
            "WHERE uf.tenant_id = :tenant_id "
            "  AND uf.created_at >= NOW() - INTERVAL '7 days'"
        ),
        {"tenant_id": tenant_id},
    )
    rate_row = rate_result.fetchone()
    total_count = int(rate_row[0]) if rate_row else 0
    rolling_7d_rate: Optional[float] = (
        None if total_count == 0 else round(int(rate_row[1]) / total_count, 4)
    )

    # Total feedback count (all time for this tenant)
    total_result = await db.execute(
        text("SELECT COUNT(*) FROM user_feedback WHERE tenant_id = :tenant_id"),
        {"tenant_id": tenant_id},
    )
    total_feedback_count = int(total_result.scalar_one() or 0)

    # All agent_cards for tenant (to include agents with 0 feedback)
    agents_result = await db.execute(
        text("SELECT id, name FROM agent_cards WHERE tenant_id = :tenant_id"),
        {"tenant_id": tenant_id},
    )
    all_agents = {str(row[0]): str(row[1]) for row in agents_result.fetchall()}

    # Per-agent feedback stats: feedback via messages→conversations
    per_agent_result = await db.execute(
        text(
            "SELECT "
            "  c.agent_id::text AS agent_id, "
            "  COUNT(uf.id) AS feedback_count, "
            "  COUNT(CASE WHEN uf.rating = 1 THEN 1 END) AS positive "
            "FROM user_feedback uf "
            "JOIN messages m ON m.id = uf.message_id "
            "JOIN conversations c ON c.id = m.conversation_id "
            "WHERE uf.tenant_id = :tenant_id "
            "  AND c.tenant_id = :tenant_id "
            "  AND c.agent_id IS NOT NULL "
            "GROUP BY c.agent_id"
        ),
        {"tenant_id": tenant_id},
    )
    agent_feedback: dict[str, dict] = {}
    for row in per_agent_result.fetchall():
        aid = str(row[0])
        fc = int(row[1])
        pos = int(row[2])
        agent_feedback[aid] = {
            "feedback_count": fc,
            "satisfaction_rate": round(pos / fc, 4) if fc > 0 else None,
        }

    # Per-agent session count (last 7 days)
    session_result = await db.execute(
        text(
            "SELECT agent_id::text, COUNT(DISTINCT id) AS session_count "
            "FROM conversations "
            "WHERE tenant_id = :tenant_id "
            "  AND agent_id IS NOT NULL "
            "  AND created_at >= NOW() - INTERVAL '7 days' "
            "GROUP BY agent_id"
        ),
        {"tenant_id": tenant_id},
    )
    agent_sessions: dict[str, int] = {
        str(row[0]): int(row[1]) for row in session_result.fetchall()
    }

    agents_list = []
    for agent_id, agent_name in all_agents.items():
        fb = agent_feedback.get(agent_id, {})
        agents_list.append(
            {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "satisfaction_rate": fb.get("satisfaction_rate", None),
                "session_count": agent_sessions.get(agent_id, 0),
                "feedback_count": fb.get("feedback_count", 0),
            }
        )

    # 30-day daily trend
    trend_result = await db.execute(
        text(
            "SELECT "
            "  d.day::date AS date, "
            "  COALESCE(COUNT(uf.id), 0) AS cnt, "
            "  CASE "
            "    WHEN COUNT(uf.id) = 0 THEN NULL "
            "    ELSE ROUND("
            "      COUNT(CASE WHEN uf.rating = 1 THEN 1 END)::numeric / COUNT(uf.id), 4"
            "    ) "
            "  END AS satisfaction_rate "
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
    daily_trend = [
        {
            "date": str(row[0]),
            "satisfaction_rate": float(row[2]) if row[2] is not None else None,
            "count": int(row[1]),
        }
        for row in trend_result.fetchall()
    ]

    return {
        "rolling_7d_rate": rolling_7d_rate,
        "total_feedback_count": total_feedback_count,
        "agents": agents_list,
        "daily_trend": daily_trend,
    }


@router.get("/analytics/satisfaction-dashboard")
async def get_satisfaction_dashboard(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TA-026: Satisfaction dashboard — rolling 7d rate, total feedback, per-agent
    breakdown (including 0-feedback agents), and 30-day daily trend.

    Auth: tenant_admin required.
    """
    data = await get_satisfaction_dashboard_db(
        tenant_id=current_user.tenant_id, db=session
    )
    logger.info(
        "satisfaction_dashboard_fetched",
        tenant_id=current_user.tenant_id,
        total_feedback_count=data["total_feedback_count"],
        rolling_7d_rate=data["rolling_7d_rate"],
    )
    return data


# ---------------------------------------------------------------------------
# TA-027 + TA-028: Agent Performance Detail + Root Cause Correlation
# ---------------------------------------------------------------------------


async def get_agent_daily_satisfaction_db(
    tenant_id: str, agent_id: str, db: AsyncSession
) -> list[dict]:
    """30-day daily satisfaction for a specific agent."""
    result = await db.execute(
        text(
            "SELECT "
            "  d.day::date AS date, "
            "  COALESCE(COUNT(uf.id), 0) AS cnt, "
            "  CASE "
            "    WHEN COUNT(uf.id) = 0 THEN NULL "
            "    ELSE ROUND("
            "      COUNT(CASE WHEN uf.rating = 1 THEN 1 END)::numeric / COUNT(uf.id), 4"
            "    ) "
            "  END AS satisfaction_rate "
            "FROM generate_series("
            "  CURRENT_DATE - INTERVAL '29 days', "
            "  CURRENT_DATE, "
            "  INTERVAL '1 day'"
            ") AS d(day) "
            "LEFT JOIN ("
            "  SELECT uf.id, uf.rating, uf.created_at "
            "  FROM user_feedback uf "
            "  JOIN messages m ON m.id = uf.message_id "
            "  JOIN conversations c ON c.id = m.conversation_id "
            "  WHERE uf.tenant_id = :tenant_id "
            "    AND c.agent_id = CAST(:agent_id AS uuid) "
            ") uf ON uf.created_at::date = d.day::date "
            "GROUP BY d.day "
            "ORDER BY d.day ASC"
        ),
        {"tenant_id": tenant_id, "agent_id": agent_id},
    )
    return [
        {
            "date": str(row[0]),
            "satisfaction_rate": float(row[2]) if row[2] is not None else None,
            "count": int(row[1]),
        }
        for row in result.fetchall()
    ]


async def get_low_confidence_for_agent_db(
    tenant_id: str, agent_id: str, db: AsyncSession
) -> list[dict]:
    """Last 50 messages with confidence < 0.70 for a specific agent."""
    try:
        result = await db.execute(
            text(
                "SELECT m.id, m.content, m.retrieval_confidence, m.created_at "
                "FROM messages m "
                "JOIN conversations c ON c.id = m.conversation_id "
                "WHERE m.tenant_id = :tenant_id "
                "  AND c.agent_id = CAST(:agent_id AS uuid) "
                "  AND m.retrieval_confidence IS NOT NULL "
                "  AND m.retrieval_confidence < 0.70 "
                "  AND m.role = 'user' "
                "ORDER BY m.created_at DESC "
                "LIMIT 50"
            ),
            {"tenant_id": tenant_id, "agent_id": agent_id},
        )
        rows = result.fetchall()
        if not rows:
            # Fallback: metadata JSONB confidence
            result = await db.execute(
                text(
                    "SELECT m.id, m.content, "
                    "  CAST(m.metadata->>'retrieval_confidence' AS FLOAT) AS conf, "
                    "  m.created_at "
                    "FROM messages m "
                    "JOIN conversations c ON c.id = m.conversation_id "
                    "WHERE m.tenant_id = :tenant_id "
                    "  AND c.agent_id = CAST(:agent_id AS uuid) "
                    "  AND m.metadata->>'retrieval_confidence' IS NOT NULL "
                    "  AND CAST(m.metadata->>'retrieval_confidence' AS FLOAT) < 0.70 "
                    "  AND m.role = 'user' "
                    "ORDER BY m.created_at DESC "
                    "LIMIT 50"
                ),
                {"tenant_id": tenant_id, "agent_id": agent_id},
            )
            rows = result.fetchall()
        return [
            {
                "conversation_id": str(row[0]),
                "query_snippet": (row[1] or "")[:40],
                "confidence": float(row[2]) if row[2] is not None else 0.0,
                "timestamp": row[3].isoformat() if row[3] else None,
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning(
            "low_confidence_agent_query_failed",
            tenant_id=tenant_id,
            agent_id=agent_id,
            error=str(exc),
        )
        return []


async def get_guardrail_events_for_agent_db(
    tenant_id: str, agent_id: str, db: AsyncSession
) -> list[dict]:
    """Last 100 guardrail_trigger events from analytics_events for a specific agent."""
    try:
        result = await db.execute(
            text(
                "SELECT "
                "  ae.metadata->>'trigger_reason' AS trigger_reason, "
                "  ae.metadata->>'query_snippet' AS query_snippet, "
                "  ae.created_at "
                "FROM analytics_events ae "
                "WHERE ae.tenant_id = :tenant_id "
                "  AND ae.event_type = 'guardrail_trigger' "
                "  AND ae.metadata->>'agent_id' = :agent_id "
                "ORDER BY ae.created_at DESC "
                "LIMIT 100"
            ),
            {"tenant_id": tenant_id, "agent_id": agent_id},
        )
        rows = result.fetchall()
        return [
            {
                "trigger_reason": row[0] or "unknown",
                "query_snippet": (row[1] or "")[:40],
                "timestamp": row[2].isoformat() if row[2] else None,
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning(
            "guardrail_events_query_failed",
            tenant_id=tenant_id,
            agent_id=agent_id,
            error=str(exc),
        )
        return []


async def compute_root_cause_correlation_db(
    tenant_id: str,
    agent_id: str,
    daily_satisfaction: list[dict],
    db: AsyncSession,
) -> Optional[dict]:
    """
    TA-028: Find first 10pp satisfaction drop and check for sync_job
    completion within 48h prior to the drop.

    Returns correlation dict or None.
    """
    # Find first day with >= 10pp drop vs previous day (both non-null)
    drop_day: Optional[str] = None
    drop_magnitude: float = 0.0
    prev_rate: Optional[float] = None
    for entry in daily_satisfaction:
        rate = entry.get("satisfaction_rate")
        if rate is None:
            prev_rate = None
            continue
        if prev_rate is not None:
            drop = prev_rate - rate
            if drop >= 0.10:  # 10 percentage points (rates are 0-1 fractions)
                drop_day = entry["date"]
                drop_magnitude = round(drop * 100, 1)
                break
        prev_rate = rate

    if drop_day is None:
        return None

    # Check for sync_job completion within 48h before the drop day
    try:
        sync_result = await db.execute(
            text(
                "SELECT sj.completed_at "
                "FROM sync_jobs sj "
                "JOIN integrations i ON i.id = sj.integration_id "
                "WHERE sj.tenant_id = :tenant_id "
                "  AND sj.status = 'completed' "
                "  AND sj.completed_at IS NOT NULL "
                "  AND sj.completed_at >= CAST(:drop_day AS timestamptz) - INTERVAL '48 hours' "
                "  AND sj.completed_at < CAST(:drop_day AS timestamptz) "
                "ORDER BY sj.completed_at DESC "
                "LIMIT 1"
            ),
            {"tenant_id": tenant_id, "drop_day": drop_day},
        )
        sync_row = sync_result.fetchone()
    except Exception as exc:
        logger.warning(
            "root_cause_sync_query_failed",
            tenant_id=tenant_id,
            agent_id=agent_id,
            error=str(exc),
        )
        return None

    if sync_row is None:
        return None

    return {
        "potential_cause": "document_freshness",
        "sync_at": sync_row[0].isoformat() if sync_row[0] else None,
        "satisfaction_drop_at": f"{drop_day}T00:00:00Z",
        "drop_magnitude": drop_magnitude,
        "confidence": "medium",
    }


@router.get("/agents/{agent_id}/analytics")
async def get_agent_analytics(
    agent_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TA-027/028: Agent performance detail — daily satisfaction, low-confidence
    responses, guardrail events, and root cause correlation.

    Auth: tenant_admin required.
    """
    # Verify agent belongs to this tenant
    agent_result = await session.execute(
        text(
            "SELECT id, name FROM agent_cards "
            "WHERE id = CAST(:agent_id AS uuid) AND tenant_id = :tenant_id"
        ),
        {"agent_id": agent_id, "tenant_id": current_user.tenant_id},
    )
    agent_row = agent_result.fetchone()
    if agent_row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Agent not found")

    agent_name = str(agent_row[1])

    daily_satisfaction = await get_agent_daily_satisfaction_db(
        tenant_id=current_user.tenant_id, agent_id=agent_id, db=session
    )
    low_confidence = await get_low_confidence_for_agent_db(
        tenant_id=current_user.tenant_id, agent_id=agent_id, db=session
    )
    guardrail_events = await get_guardrail_events_for_agent_db(
        tenant_id=current_user.tenant_id, agent_id=agent_id, db=session
    )
    correlation = await compute_root_cause_correlation_db(
        tenant_id=current_user.tenant_id,
        agent_id=agent_id,
        daily_satisfaction=daily_satisfaction,
        db=session,
    )

    logger.info(
        "agent_analytics_fetched",
        tenant_id=current_user.tenant_id,
        agent_id=agent_id,
        low_confidence_count=len(low_confidence),
        guardrail_count=len(guardrail_events),
        has_correlation=correlation is not None,
    )

    return {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "daily_satisfaction": daily_satisfaction,
        "low_confidence_responses": low_confidence,
        "guardrail_events": guardrail_events,
        "correlation": correlation,
    }


# ---------------------------------------------------------------------------
# TA-029: Glossary Performance Analytics
# ---------------------------------------------------------------------------


async def get_glossary_analytics_db(tenant_id: str, db: AsyncSession) -> list[dict]:
    """
    TA-029: Per-term satisfaction lift from analytics_events with event_type='glossary_match'.

    Uses 3 batch queries (not N*2 per term) to compute lift for all terms at once:
      1. Fetch all (term_id, conversation_id) from analytics_events
      2. Fetch all glossary terms
      3. Fetch feedback aggregated per conversation

    Per-term "with" stats come from conversations in the match set.
    Per-term "without" stats = total feedback minus per-term "with" stats.
    """
    # Query 1: all glossary_match events for this tenant (batch — no per-term loop)
    try:
        events_result = await db.execute(
            text(
                "SELECT "
                "  ae.metadata->>'term_id' AS term_id, "
                "  ae.metadata->>'conversation_id' AS conversation_id "
                "FROM analytics_events ae "
                "WHERE ae.tenant_id = :tenant_id "
                "  AND ae.event_type = 'glossary_match' "
                "  AND ae.metadata->>'term_id' IS NOT NULL "
                "  AND ae.metadata->>'conversation_id' IS NOT NULL"
            ),
            {"tenant_id": tenant_id},
        )
        event_rows = events_result.fetchall()
    except Exception as exc:
        logger.warning(
            "glossary_analytics_events_failed", tenant_id=tenant_id, error=str(exc)
        )
        return []

    if not event_rows:
        logger.info("glossary_analytics_no_events", tenant_id=tenant_id)
        return []

    # Build term_id → set of conversation_id strings
    term_convs: dict[str, set] = {}
    for row in event_rows:
        tid = str(row[0])
        cid = str(row[1])
        if tid not in term_convs:
            term_convs[tid] = set()
        term_convs[tid].add(cid)

    # Query 2: all glossary terms for this tenant
    terms_result = await db.execute(
        text("SELECT id, term FROM glossary_terms WHERE tenant_id = :tenant_id"),
        {"tenant_id": tenant_id},
    )
    terms = {str(row[0]): str(row[1]) for row in terms_result.fetchall()}
    if not terms:
        return []

    # Query 3: feedback aggregated per conversation (one query covers all terms)
    try:
        fb_result = await db.execute(
            text(
                "SELECT "
                "  c.id::text AS conversation_id, "
                "  COUNT(uf.id) AS feedback_count, "
                "  COUNT(CASE WHEN uf.rating = 1 THEN 1 END) AS positive_count "
                "FROM user_feedback uf "
                "JOIN messages m ON m.id = uf.message_id "
                "JOIN conversations c ON c.id = m.conversation_id "
                "WHERE uf.tenant_id = :tenant_id "
                "  AND c.tenant_id = :tenant_id "
                "GROUP BY c.id"
            ),
            {"tenant_id": tenant_id},
        )
        conv_feedback: dict[str, tuple] = {}
        total_feedback = 0
        total_positive = 0
        for row in fb_result.fetchall():
            cid = str(row[0])
            fc = int(row[1])
            pc = int(row[2])
            conv_feedback[cid] = (fc, pc)
            total_feedback += fc
            total_positive += pc
    except Exception as exc:
        logger.warning(
            "glossary_analytics_feedback_failed", tenant_id=tenant_id, error=str(exc)
        )
        return []

    # Compute per-term stats in Python (no more per-term DB queries)
    results = []
    for term_id, term_text in terms.items():
        matched_convs = term_convs.get(term_id, set())

        with_feedback = sum(conv_feedback.get(c, (0, 0))[0] for c in matched_convs)
        with_positive = sum(conv_feedback.get(c, (0, 0))[1] for c in matched_convs)

        without_feedback = total_feedback - with_feedback
        without_positive = total_positive - with_positive

        sat_with: Optional[float] = (
            round(with_positive / with_feedback, 4) if with_feedback > 0 else None
        )
        sat_without: Optional[float] = (
            round(without_positive / without_feedback, 4)
            if without_feedback > 0
            else None
        )

        lift_pct: Optional[float] = None
        if sat_with is not None and sat_without is not None and sat_without > 0:
            lift_pct = round((sat_with - sat_without) / sat_without * 100, 1)

        data_quality = (
            "sufficient"
            if with_feedback >= 10 and without_feedback >= 10
            else "insufficient"
        )

        results.append(
            {
                "term_id": term_id,
                "term": term_text,
                "satisfaction_with": sat_with,
                "satisfaction_without": sat_without,
                "query_count_with": with_feedback,
                "lift_pct": lift_pct,
                "data_quality": data_quality,
            }
        )

    # Sort by lift_pct DESC (None last)
    results.sort(
        key=lambda x: x["lift_pct"] if x["lift_pct"] is not None else float("-inf"),
        reverse=True,
    )
    return results


@router.get("/glossary/analytics")
async def get_glossary_analytics(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TA-029: Glossary performance analytics — per-term satisfaction lift,
    query counts, and data quality assessment.

    Auth: tenant_admin required.
    """
    items = await get_glossary_analytics_db(
        tenant_id=current_user.tenant_id, db=session
    )
    logger.info(
        "glossary_analytics_fetched",
        tenant_id=current_user.tenant_id,
        term_count=len(items),
    )
    return items


# ---------------------------------------------------------------------------
# TA-030: User Engagement Analytics (new response shape)
# ---------------------------------------------------------------------------


async def get_engagement_v2_db(tenant_id: str, db: AsyncSession) -> dict:
    """
    TA-030: DAU/WAU/MAU aggregate, per-agent DAU/WAU/MAU, inactive users,
    and feature adoption from analytics_events.
    """
    # Aggregate DAU/WAU/MAU from conversations
    dau_result = await db.execute(
        text(
            "SELECT COUNT(DISTINCT user_id) FROM conversations "
            "WHERE tenant_id = :tenant_id "
            "  AND created_at >= NOW() - INTERVAL '1 day'"
        ),
        {"tenant_id": tenant_id},
    )
    dau = int(dau_result.scalar_one() or 0)

    wau_result = await db.execute(
        text(
            "SELECT COUNT(DISTINCT user_id) FROM conversations "
            "WHERE tenant_id = :tenant_id "
            "  AND created_at >= NOW() - INTERVAL '7 days'"
        ),
        {"tenant_id": tenant_id},
    )
    wau = int(wau_result.scalar_one() or 0)

    mau_result = await db.execute(
        text(
            "SELECT COUNT(DISTINCT user_id) FROM conversations "
            "WHERE tenant_id = :tenant_id "
            "  AND created_at >= NOW() - INTERVAL '30 days'"
        ),
        {"tenant_id": tenant_id},
    )
    mau = int(mau_result.scalar_one() or 0)

    # Inactive users: active users with no conversation in last 30 days
    active_users_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM users "
            "WHERE tenant_id = :tenant_id AND status = 'active'"
        ),
        {"tenant_id": tenant_id},
    )
    active_users_total = int(active_users_result.scalar_one() or 0)
    inactive_users = max(0, active_users_total - mau)

    # Per-agent DAU/WAU/MAU
    per_agent_result = await db.execute(
        text(
            "SELECT "
            "  ac.id::text AS agent_id, "
            "  ac.name AS agent_name, "
            "  COUNT(DISTINCT CASE WHEN c.created_at >= NOW() - INTERVAL '1 day' THEN c.user_id END) AS dau, "
            "  COUNT(DISTINCT CASE WHEN c.created_at >= NOW() - INTERVAL '7 days' THEN c.user_id END) AS wau, "
            "  COUNT(DISTINCT CASE WHEN c.created_at >= NOW() - INTERVAL '30 days' THEN c.user_id END) AS mau "
            "FROM agent_cards ac "
            "LEFT JOIN conversations c ON c.agent_id = ac.id AND c.tenant_id = :tenant_id "
            "WHERE ac.tenant_id = :tenant_id "
            "GROUP BY ac.id, ac.name "
            "ORDER BY wau DESC"
        ),
        {"tenant_id": tenant_id},
    )
    per_agent = [
        {
            "agent_id": str(row[0]),
            "agent_name": str(row[1]),
            "dau": int(row[2] or 0),
            "wau": int(row[3] or 0),
            "mau": int(row[4] or 0),
        }
        for row in per_agent_result.fetchall()
    ]

    # Feature adoption from analytics_events
    try:
        feature_result = await db.execute(
            text(
                "SELECT feature_name, COUNT(*) AS adoption_count "
                "FROM analytics_events "
                "WHERE tenant_id = :tenant_id "
                "GROUP BY feature_name "
                "ORDER BY adoption_count DESC"
            ),
            {"tenant_id": tenant_id},
        )
        feature_adoption = [
            {"feature_name": str(row[0]), "adoption_count": int(row[1])}
            for row in feature_result.fetchall()
        ]
    except Exception as exc:
        logger.warning(
            "feature_adoption_query_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )
        feature_adoption = []

    return {
        "aggregate": {
            "dau": dau,
            "wau": wau,
            "mau": mau,
            "inactive_users": inactive_users,
        },
        "per_agent": per_agent,
        "feature_adoption": feature_adoption,
    }


@router.get("/analytics/engagement-v2")
async def get_engagement_v2(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TA-030: User engagement analytics — DAU/WAU/MAU aggregate, per-agent
    breakdown, inactive users, and feature adoption from analytics_events.

    Auth: tenant_admin required.
    """
    data = await get_engagement_v2_db(tenant_id=current_user.tenant_id, db=session)
    logger.info(
        "engagement_v2_fetched",
        tenant_id=current_user.tenant_id,
        dau=data["aggregate"]["dau"],
        mau=data["aggregate"]["mau"],
    )
    return data
