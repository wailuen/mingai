"""
PA-007: Nightly health score batch job.

Scheduled daily at 02:00 UTC. For each active tenant, fetches raw signal
data from the DB, calls calculate_health_score(), and upserts the result
into tenant_health_scores (unique on tenant_id, date).

At-risk detection rules:
  - composite_low:            composite_score < 40
  - satisfaction_declining:   satisfaction_score < 50 for 2+ consecutive weeks
  - usage_trending_down:      composite_score declining for 3+ consecutive weeks

Composite formula:
  (usage_trend * 0.30) + (feature_breadth * 0.20) + (satisfaction * 0.35)
  + (error_rate * 0.15)

This formula is already encoded inside calculate_health_score() in health_score.py.
The component scores returned there already include the weight multiplication, so
composite = sum(components.values()).
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import text

from app.core.scheduler import DistributedJobLock, job_run_context, seconds_until_utc
from app.core.scheduler.timing import check_missed_job
from app.core.session import async_session_factory
from app.modules.platform.health_score import calculate_health_score

logger = structlog.get_logger()

# At-risk thresholds
_AT_RISK_COMPOSITE_THRESHOLD = 40.0
# satisfaction_score stored in tenant_health_scores is the weighted component (0–35),
# not the raw percentage. 50% raw = (50/100)*35 = 17.5 in component units.
_AT_RISK_SATISFACTION_THRESHOLD = 17.5
_SATISFACTION_WEEKS_REQUIRED = 2
_USAGE_DECLINE_WEEKS_REQUIRED = 3


# ---------------------------------------------------------------------------
# Signal fetching helpers
# ---------------------------------------------------------------------------


async def _fetch_tenant_signals(
    tenant_id: str,
    db,
) -> dict:
    """
    Fetch raw signal inputs for a single tenant from the DB.

    Signals sourced from existing tables:
      - usage_trend_pct:  week-over-week query volume change from usage_events
      - feature_breadth:  fraction of distinct event_type values seen in past 30d
      - satisfaction_pct: positive feedback % from feedback table (past 30d)
      - error_rate_pct:   error rate % from usage_events (past 30d)

    Returns a dict with keys matching calculate_health_score() parameters.
    Missing or zero-data signals return None (will use last_known fallback).
    """
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)
    fourteen_days_ago = today - timedelta(days=14)

    signals: dict = {
        "usage_trend_pct": None,
        "feature_breadth": None,
        "satisfaction_pct": None,
        "error_rate_pct": None,
    }

    # --- usage_trend_pct: compare current 14d vs prior 14d query counts ---
    try:
        result = await db.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (WHERE created_at >= :fourteen_days_ago)  AS recent,
                    COUNT(*) FILTER (
                        WHERE created_at >= :thirty_days_ago
                          AND created_at < :fourteen_days_ago
                    ) AS prior
                FROM usage_events
                WHERE tenant_id = :tid
                  AND created_at >= :thirty_days_ago
                  AND event_type = 'query'
                """
            ),
            {
                "tid": tenant_id,
                "thirty_days_ago": thirty_days_ago,
                "fourteen_days_ago": fourteen_days_ago,
            },
        )
        row = result.fetchone()
        if row and row[1] and row[1] > 0:
            recent = float(row[0] or 0)
            prior = float(row[1])
            signals["usage_trend_pct"] = (recent - prior) / prior
        elif row and row[0] and row[0] > 0:
            # Has recent queries but no prior period — treat as neutral (0% change)
            signals["usage_trend_pct"] = 0.0
    except Exception as exc:
        logger.warning(
            "health_score_job_usage_trend_fetch_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )

    # --- feature_breadth: distinct event_type / total known types in 30d ---
    # Known feature event types for breadth calculation
    _KNOWN_FEATURE_TYPES = {
        "query",
        "document_upload",
        "glossary_lookup",
        "agent_invocation",
        "feedback",
    }
    try:
        result = await db.execute(
            text(
                """
                SELECT COUNT(DISTINCT event_type)
                FROM usage_events
                WHERE tenant_id = :tid
                  AND created_at >= :thirty_days_ago
                  AND event_type = ANY(:types)
                """
            ),
            {
                "tid": tenant_id,
                "thirty_days_ago": thirty_days_ago,
                "types": list(_KNOWN_FEATURE_TYPES),
            },
        )
        row = result.fetchone()
        if row is not None:
            distinct_count = int(row[0] or 0)
            signals["feature_breadth"] = distinct_count / len(_KNOWN_FEATURE_TYPES)
    except Exception as exc:
        logger.warning(
            "health_score_job_feature_breadth_fetch_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )

    # --- satisfaction_pct: positive feedback % (rating > 0) in 30d ---
    try:
        result = await db.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (WHERE rating = 1)  AS positive,
                    COUNT(*)                              AS total
                FROM feedback
                WHERE tenant_id = :tid
                  AND created_at >= :thirty_days_ago
                """
            ),
            {"tid": tenant_id, "thirty_days_ago": thirty_days_ago},
        )
        row = result.fetchone()
        if row and row[1] and row[1] > 0:
            signals["satisfaction_pct"] = float(row[0] or 0) / float(row[1]) * 100.0
    except Exception as exc:
        logger.warning(
            "health_score_job_satisfaction_fetch_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )

    # --- error_rate_pct: error events / total events % in 30d ---
    try:
        result = await db.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (WHERE event_type = 'error') AS errors,
                    COUNT(*)                                       AS total
                FROM usage_events
                WHERE tenant_id = :tid
                  AND created_at >= :thirty_days_ago
                """
            ),
            {"tid": tenant_id, "thirty_days_ago": thirty_days_ago},
        )
        row = result.fetchone()
        if row and row[1] and row[1] > 0:
            signals["error_rate_pct"] = float(row[0] or 0) / float(row[1]) * 100.0
        elif row and row[1] == 0:
            # No events at all — treat as 0% error rate
            signals["error_rate_pct"] = 0.0
    except Exception as exc:
        logger.warning(
            "health_score_job_error_rate_fetch_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )

    return signals


async def _fetch_last_known(tenant_id: str, db) -> dict[str, float]:
    """
    Fetch the most recent stored component scores for a tenant as last_known.

    Used as fallback when live signal data is unavailable.
    Returns empty dict if no prior row exists.
    """
    result = await db.execute(
        text(
            """
            SELECT usage_trend_score, feature_breadth_score,
                   satisfaction_score, error_rate_score
            FROM tenant_health_scores
            WHERE tenant_id = :tid
            ORDER BY date DESC
            LIMIT 1
            """
        ),
        {"tid": tenant_id},
    )
    row = result.fetchone()
    if not row:
        return {}

    last_known: dict[str, float] = {}
    if row[0] is not None:
        last_known["usage_trend"] = float(row[0])
    if row[1] is not None:
        last_known["feature_breadth"] = float(row[1])
    if row[2] is not None:
        last_known["satisfaction"] = float(row[2])
    if row[3] is not None:
        last_known["error_rate"] = float(row[3])
    return last_known


# ---------------------------------------------------------------------------
# At-risk detection helpers
# ---------------------------------------------------------------------------


async def _detect_at_risk(
    tenant_id: str,
    composite_score: float,
    satisfaction_score: Optional[float],
    db,
) -> tuple[bool, Optional[str]]:
    """
    Determine at_risk_flag and at_risk_reason for a tenant.

    Rules (evaluated in priority order, first match wins):
      1. composite_low:           composite_score < 40
      2. satisfaction_declining:  satisfaction_score < 50 in latest 2 weeks
      3. usage_trending_down:     composite_score declining for 3+ consecutive weeks

    Returns (at_risk_flag, at_risk_reason).
    """
    # Rule 1: immediate composite threshold breach
    if composite_score < _AT_RISK_COMPOSITE_THRESHOLD:
        return True, "composite_low"

    # Rule 2: satisfaction < 50 for 2+ consecutive weeks
    if (
        satisfaction_score is not None
        and satisfaction_score < _AT_RISK_SATISFACTION_THRESHOLD
    ):
        # Check how many consecutive recent rows also had satisfaction < 50
        result = await db.execute(
            text(
                """
                SELECT satisfaction_score
                FROM tenant_health_scores
                WHERE tenant_id = :tid
                ORDER BY date DESC
                LIMIT :weeks
                """
            ),
            {"tid": tenant_id, "weeks": _SATISFACTION_WEEKS_REQUIRED - 1},
        )
        prior_rows = result.fetchall()
        # If prior row(s) also had satisfaction < 50, flag it
        if prior_rows and all(
            r[0] is not None and float(r[0]) < _AT_RISK_SATISFACTION_THRESHOLD
            for r in prior_rows
        ):
            return True, "satisfaction_declining"

    # Rule 3: composite declining for 3+ consecutive weeks
    result = await db.execute(
        text(
            """
            SELECT composite_score
            FROM tenant_health_scores
            WHERE tenant_id = :tid
            ORDER BY date DESC
            LIMIT :weeks
            """
        ),
        {"tid": tenant_id, "weeks": _USAGE_DECLINE_WEEKS_REQUIRED},
    )
    prior_rows = result.fetchall()
    if len(prior_rows) >= _USAGE_DECLINE_WEEKS_REQUIRED:
        prior_scores = [float(r[0]) for r in prior_rows if r[0] is not None]
        if len(prior_scores) >= _USAGE_DECLINE_WEEKS_REQUIRED:
            # All prior scores must be strictly greater than the next (descending order
            # means prior_scores[0] is the most recent stored, prior_scores[-1] oldest)
            # Current week score < prior_scores[0] < prior_scores[1] < prior_scores[2]
            is_declining = composite_score < prior_scores[0] and all(
                prior_scores[i] < prior_scores[i + 1]
                for i in range(len(prior_scores) - 1)
            )
            if is_declining:
                return True, "usage_trending_down"

    return False, None


# ---------------------------------------------------------------------------
# Per-tenant processing
# ---------------------------------------------------------------------------


async def _process_tenant(tenant_id: str, today: date, db) -> None:
    """
    Compute and upsert a health score row for one tenant.

    Fetches signals, calls calculate_health_score(), detects at-risk state,
    and upserts into tenant_health_scores (conflict on tenant_id, date).
    """
    signals = await _fetch_tenant_signals(tenant_id, db)
    last_known = await _fetch_last_known(tenant_id, db)

    try:
        result = calculate_health_score(
            usage_trend_pct=signals["usage_trend_pct"],
            feature_breadth=signals["feature_breadth"],
            satisfaction_pct=signals["satisfaction_pct"],
            error_rate_pct=signals["error_rate_pct"],
            last_known=last_known if last_known else None,
        )
    except ValueError as exc:
        logger.warning(
            "health_score_job_calculate_failed",
            tenant_id=tenant_id,
            error=str(exc),
            hint="All signals are None and no last_known available — skipping tenant",
        )
        return

    composite = result.score
    usage_trend_score = result.components.get("usage_trend")
    feature_breadth_score = result.components.get("feature_breadth")
    satisfaction_score = result.components.get("satisfaction")
    error_rate_score = result.components.get("error_rate")

    at_risk_flag, at_risk_reason = await _detect_at_risk(
        tenant_id=tenant_id,
        composite_score=composite,
        satisfaction_score=satisfaction_score,
        db=db,
    )

    await db.execute(
        text(
            """
            INSERT INTO tenant_health_scores
                (tenant_id, date, usage_trend_score, feature_breadth_score,
                 satisfaction_score, error_rate_score, composite_score,
                 at_risk_flag, at_risk_reason)
            VALUES
                (:tid, :date, :usage_trend, :feature_breadth,
                 :satisfaction, :error_rate, :composite,
                 :at_risk_flag, :at_risk_reason)
            ON CONFLICT (tenant_id, date) DO UPDATE SET
                usage_trend_score    = EXCLUDED.usage_trend_score,
                feature_breadth_score = EXCLUDED.feature_breadth_score,
                satisfaction_score   = EXCLUDED.satisfaction_score,
                error_rate_score     = EXCLUDED.error_rate_score,
                composite_score      = EXCLUDED.composite_score,
                at_risk_flag         = EXCLUDED.at_risk_flag,
                at_risk_reason       = EXCLUDED.at_risk_reason,
                created_at           = NOW()
            """
        ),
        {
            "tid": tenant_id,
            "date": today,
            "usage_trend": usage_trend_score,
            "feature_breadth": feature_breadth_score,
            "satisfaction": satisfaction_score,
            "error_rate": error_rate_score,
            "composite": composite,
            "at_risk_flag": at_risk_flag,
            "at_risk_reason": at_risk_reason,
        },
    )
    await db.commit()

    logger.info(
        "health_score_job_tenant_processed",
        tenant_id=tenant_id,
        composite=composite,
        at_risk_flag=at_risk_flag,
        at_risk_reason=at_risk_reason,
    )


# ---------------------------------------------------------------------------
# Public job entrypoint
# ---------------------------------------------------------------------------


async def run_health_score_job() -> None:
    """
    Execute one full health score run across all active tenants.

    Fetches active tenant IDs and processes each one sequentially.
    Per-tenant errors are isolated: an exception for one tenant never
    stops processing of others.
    Never raises — all top-level exceptions are logged.
    """
    job_start = time.monotonic()
    today = date.today()
    processed = 0
    skipped = 0
    errors = 0

    try:
        async with async_session_factory() as db:
            # Fetch active tenants — no RLS context needed (superuser session)
            result = await db.execute(
                text("SELECT id FROM tenants WHERE status = 'active'")
            )
            tenant_rows = result.fetchall()
    except Exception as exc:
        logger.error(
            "health_score_job_tenant_fetch_failed",
            error=str(exc),
        )
        return

    tenant_ids = [str(row[0]) for row in tenant_rows]

    if not tenant_ids:
        logger.info("health_score_job_no_active_tenants")
        return

    for tenant_id in tenant_ids:
        try:
            async with async_session_factory() as db:
                # Platform-scope RLS bypass required for tenant_health_scores table
                await db.execute(text("SET LOCAL app.current_scope = 'platform'"))
                await _process_tenant(tenant_id, today, db)
            processed += 1
        except Exception as exc:
            errors += 1
            logger.error(
                "health_score_job_tenant_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )

    duration_ms = round((time.monotonic() - job_start) * 1000, 1)

    logger.info(
        "health_score_job_complete",
        total_tenants=len(tenant_ids),
        processed=processed,
        skipped=skipped,
        errors=errors,
        duration_ms=duration_ms,
    )

    return processed


# ---------------------------------------------------------------------------
# Scheduler (daily at 02:00 UTC)
# ---------------------------------------------------------------------------


async def run_health_score_scheduler() -> None:
    """
    Infinite asyncio loop that fires run_health_score_job() daily at 02:00 UTC.

    Designed to be launched as an asyncio background task via asyncio.create_task()
    in app/main.py lifespan. Exits gracefully on CancelledError.
    """
    logger.info(
        "health_score_scheduler_started",
        schedule="daily at 02:00 UTC",
    )

    while True:
        try:
            # SCHED-025: Missed-job recovery — runs immediately on the first
            # iteration if the 02:00 UTC slot passed today with no completed row.
            # On subsequent iterations check_missed_job returns False (row exists).
            async with async_session_factory() as _db:
                if await check_missed_job(
                    _db, "health_score", scheduled_hour=2, scheduled_minute=0
                ):
                    async with DistributedJobLock("health_score", ttl=3600) as _acquired:
                        if _acquired:
                            async with job_run_context("health_score") as ctx:
                                _tenants_scored = await run_health_score_job()
                                ctx.records_processed = _tenants_scored or 0
                    logger.info("health_score_missed_job_recovered")

            sleep_secs = seconds_until_utc(2, 0)
            logger.debug(
                "health_score_next_run_in",
                seconds=round(sleep_secs, 0),
            )
            await asyncio.sleep(sleep_secs)
            async with DistributedJobLock("health_score", ttl=3600) as acquired:
                if not acquired:
                    logger.debug(
                        "health_score_job_skipped",
                        reason="lock_held_by_another_pod",
                    )
                else:
                    async with job_run_context("health_score") as ctx:
                        tenants_scored = await run_health_score_job()
                        ctx.records_processed = tenants_scored or 0
        except asyncio.CancelledError:
            logger.info("health_score_scheduler_cancelled")
            return
        except Exception as exc:
            # Never crash the scheduler loop — log and retry on next cycle
            logger.error(
                "health_score_scheduler_loop_error",
                error=str(exc),
            )
