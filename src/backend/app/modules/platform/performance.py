"""
PA-025: Template performance tracking batch job.

Runs nightly; upserts one row per template into template_performance_daily.

Metrics computed per template per date:
  - satisfaction_rate: (thumbs-up count) / (total feedback count)
  - guardrail_trigger_rate: (distinct conversations with a guardrail event) / session_count
  - failure_count: thumbs-down (rating = -1) count
  - session_count: distinct conversation_ids for sessions using this template

Data sources:
  - user_feedback → messages → conversations → agent_cards (template_id)
  - guardrail_events (template_id direct)

Called from: app.modules.platform.batch (nightly scheduler) and
             POST /platform/batch/template-performance (manual trigger).
"""
import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SET_PLATFORM_SCOPE = text("SELECT set_config('app.scope', 'platform', true)")

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Aggregation query helpers
# ---------------------------------------------------------------------------

_SATISFACTION_QUERY = text(
    """
    SELECT
        CAST(ac.template_id AS UUID)                                         AS template_id,
        COUNT(CASE WHEN uf.rating =  1 THEN 1 END)                          AS positive_count,
        COUNT(CASE WHEN uf.rating = -1 THEN 1 END)                          AS negative_count,
        COUNT(uf.id)                                                          AS total_feedback
    FROM user_feedback uf
    JOIN messages      m  ON m.id = uf.message_id
    JOIN conversations c  ON c.id = m.conversation_id
    JOIN agent_cards   ac ON ac.id = c.agent_id
    WHERE ac.template_id IS NOT NULL
      AND uf.created_at >= :day_start
      AND uf.created_at <  :day_end
    GROUP BY CAST(ac.template_id AS UUID)
    """
)

_GUARDRAIL_QUERY = text(
    """
    SELECT
        ge.template_id,
        COUNT(DISTINCT ge.conversation_id) AS guardrail_sessions
    FROM guardrail_events ge
    WHERE ge.template_id IS NOT NULL
      AND ge.created_at >= :day_start
      AND ge.created_at <  :day_end
    GROUP BY ge.template_id
    """
)

_SESSION_NO_FEEDBACK_QUERY = text(
    """
    SELECT
        CAST(ac.template_id AS UUID)   AS template_id,
        COUNT(DISTINCT c.id)           AS session_count
    FROM conversations c
    JOIN agent_cards   ac ON ac.id = c.agent_id
    WHERE ac.template_id IS NOT NULL
      AND c.created_at >= :day_start
      AND c.created_at <  :day_end
    GROUP BY CAST(ac.template_id AS UUID)
    """
)

_UPSERT_QUERY = text(
    """
    INSERT INTO template_performance_daily
        (id, template_id, date, satisfaction_rate, guardrail_trigger_rate,
         failure_count, session_count, computed_at)
    VALUES
        (gen_random_uuid(), :template_id, :date, :satisfaction_rate,
         :guardrail_trigger_rate, :failure_count, :session_count, NOW())
    ON CONFLICT (template_id, date) DO UPDATE SET
        satisfaction_rate       = EXCLUDED.satisfaction_rate,
        guardrail_trigger_rate  = EXCLUDED.guardrail_trigger_rate,
        failure_count           = EXCLUDED.failure_count,
        session_count           = EXCLUDED.session_count,
        computed_at             = NOW()
    """
)


# ---------------------------------------------------------------------------
# Main batch function
# ---------------------------------------------------------------------------


async def run_template_performance_batch(
    db: AsyncSession,
    target_date: Optional[date] = None,
) -> dict:
    """
    Aggregate template performance metrics for `target_date` (defaults to yesterday).

    Returns a summary dict: {"date": str, "templates_updated": int, "errors": int}.

    Safe to run multiple times for the same date — uses UPSERT.
    Does NOT commit — caller must commit after calling this function.
    """
    if target_date is None:
        target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    day_start = datetime.combine(target_date, datetime.min.time()).replace(
        tzinfo=timezone.utc
    )
    day_end = day_start + timedelta(days=1)
    params = {"day_start": day_start, "day_end": day_end}

    logger.info("template_performance_batch_start", date=str(target_date))

    # Set app.scope = 'platform' so the guardrail_events RLS bypass policy
    # (guardrail_events_platform) allows cross-tenant SELECT in this session.
    await db.execute(_SET_PLATFORM_SCOPE)

    # 1. Satisfaction / feedback metrics per template
    sat_result = await db.execute(_SATISFACTION_QUERY, params)
    sat_rows = {str(row["template_id"]): row for row in sat_result.mappings()}

    # 2. Session count for templates without any feedback (still need to be tracked)
    all_sessions_result = await db.execute(_SESSION_NO_FEEDBACK_QUERY, params)
    all_sessions = {
        str(row["template_id"]): row["session_count"]
        for row in all_sessions_result.mappings()
    }

    # 3. Guardrail trigger sessions per template
    guardrail_result = await db.execute(_GUARDRAIL_QUERY, params)
    guardrail_rows = {
        str(row["template_id"]): row["guardrail_sessions"]
        for row in guardrail_result.mappings()
    }

    # Merge: all_sessions is the union of templates that had any activity today
    all_template_ids = set(sat_rows) | set(all_sessions) | set(guardrail_rows)
    templates_updated = 0
    errors = 0

    for template_id in all_template_ids:
        try:
            sat_row = sat_rows.get(template_id)
            # Use _SESSION_NO_FEEDBACK_QUERY as the authoritative session count.
            # _SATISFACTION_QUERY only counts conversations with feedback, which
            # would inflate guardrail_trigger_rate (smaller denominator).
            session_count = int(all_sessions.get(template_id, 0))

            if sat_row and sat_row["total_feedback"] > 0:
                satisfaction_rate = float(sat_row["positive_count"]) / float(
                    sat_row["total_feedback"]
                )
                failure_count = int(sat_row["negative_count"])
            else:
                satisfaction_rate = None
                failure_count = 0

            guardrail_sessions = int(guardrail_rows.get(template_id, 0))
            guardrail_trigger_rate = (
                float(guardrail_sessions) / float(session_count)
                if session_count > 0
                else None
            )

            await db.execute(
                _UPSERT_QUERY,
                {
                    "template_id": template_id,
                    "date": target_date,
                    "satisfaction_rate": satisfaction_rate,
                    "guardrail_trigger_rate": guardrail_trigger_rate,
                    "failure_count": failure_count,
                    "session_count": session_count,
                },
            )
            templates_updated += 1

        except Exception as exc:
            errors += 1
            logger.error(
                "template_performance_batch_row_error",
                template_id=template_id,
                date=str(target_date),
                error=str(exc),
            )

    logger.info(
        "template_performance_batch_complete",
        date=str(target_date),
        templates_updated=templates_updated,
        errors=errors,
    )
    return {
        "date": str(target_date),
        "templates_updated": templates_updated,
        "errors": errors,
    }
