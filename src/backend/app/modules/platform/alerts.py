"""
PA-027: Underperforming template alerts.

Called from the nightly template performance batch after computing daily metrics.

Logic:
  - Compute platform-average satisfaction rate for target_date (across all
    Published templates with data that day).
  - Threshold: template_satisfaction < platform_avg - 0.10
  - Open alert: if threshold breached for 7 consecutive days AND no open
    P2 alert already exists for this template.
  - Auto-clear: if satisfaction has recovered above threshold for 3 consecutive
    days, close any open P2 alert for this template.

Alerts are stored as issue_reports rows:
  - issue_type = 'template_performance'
  - severity   = 'high'  (P2 in the platform issue queue)
  - status     = 'open'
  - metadata   = {source: 'platform_batch', template_id: ..., ...}
  - reporter   = first platform_admin user (system-generated; no human reporter)
  - tenant     = same tenant as the platform_admin user

No alert is created if no platform_admin user exists in the DB (misconfigured
system). The function logs a warning and returns without raising.
"""
import json
import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# Minimum consecutive days below threshold to trigger an alert.
_ALERT_TRIGGER_DAYS = 7

# Minimum consecutive days above threshold (recovered) to auto-close.
_ALERT_CLEAR_DAYS = 3

# How far below the platform average a template must be to count as underperforming.
_UNDERPERFORM_MARGIN = 0.10

# ------------------------------------------------------------------
# Queries
# ------------------------------------------------------------------

_PLATFORM_AVG_QUERY = text(
    """
    SELECT AVG(satisfaction_rate)
    FROM template_performance_daily
    WHERE date = :target_date
      AND satisfaction_rate IS NOT NULL
    """
)

_RECENT_DAILY_QUERY = text(
    """
    SELECT template_id, date, satisfaction_rate
    FROM template_performance_daily
    WHERE date >= :since
      AND date <= :until
    ORDER BY template_id, date
    """
)

_OPEN_ALERT_QUERY = text(
    """
    SELECT id FROM issue_reports
    WHERE issue_type = 'template_performance'
      AND status NOT IN ('resolved', 'closed')
      AND metadata->>'template_id' = :template_id
    ORDER BY created_at DESC
    LIMIT 1
    """
)

_CREATE_ALERT_QUERY = text(
    """
    INSERT INTO issue_reports
        (id, tenant_id, reporter_id, issue_type, description, severity,
         status, blur_acknowledged, metadata)
    VALUES
        (:id, :tenant_id, :reporter_id, :issue_type, :description, :severity,
         :status, false, CAST(:metadata AS jsonb))
    """
)

_CLOSE_ALERT_QUERY = text(
    """
    UPDATE issue_reports
    SET status = 'resolved', updated_at = NOW()
    WHERE id = :issue_id
    """
)

_PLATFORM_ADMIN_QUERY = text(
    """
    SELECT id, tenant_id
    FROM users
    WHERE role = 'platform_admin'
    LIMIT 1
    """
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _contiguous_days(day_list: list) -> bool:
    """Return True iff all adjacent dates in day_list are exactly 1 day apart.

    This guards against triggering an alert on non-consecutive data (e.g. a
    missing day because the batch didn't run or the template had zero sessions).
    day_list must be sorted ascending by date before calling this.
    """
    for i in range(1, len(day_list)):
        if (day_list[i][0] - day_list[i - 1][0]).days != 1:
            return False
    return True


# ------------------------------------------------------------------
# Public function
# ------------------------------------------------------------------


async def check_underperforming_alerts(
    db: AsyncSession,
    target_date: date,
    *,
    trigger_days: int = _ALERT_TRIGGER_DAYS,
    clear_days: int = _ALERT_CLEAR_DAYS,
    margin: float = _UNDERPERFORM_MARGIN,
) -> dict:
    """
    Check template_performance_daily for underperforming templates and
    manage P2 alerts in issue_reports.

    Returns summary dict:
        {alerts_opened: int, alerts_cleared: int, errors: int}

    Does NOT commit — caller is responsible for commit.
    """
    alerts_opened = 0
    alerts_cleared = 0
    errors = 0

    # Look up the platform admin user (reporter_id + tenant_id for the alert row).
    admin_result = await db.execute(_PLATFORM_ADMIN_QUERY)
    admin_row = admin_result.fetchone()
    if not admin_row:
        logger.warning(
            "underperforming_alerts_no_platform_admin",
            note="No platform_admin user found; skipping alert creation.",
        )
        return {"alerts_opened": 0, "alerts_cleared": 0, "errors": 0}

    platform_reporter_id = str(admin_row[0])
    platform_tenant_id = str(admin_row[1])

    # Platform average satisfaction for target_date.
    avg_result = await db.execute(_PLATFORM_AVG_QUERY, {"target_date": target_date})
    platform_avg = avg_result.scalar()
    if platform_avg is None:
        # No data today — cannot compute threshold, skip.
        logger.info(
            "underperforming_alerts_no_platform_avg",
            date=str(target_date),
        )
        return {"alerts_opened": 0, "alerts_cleared": 0, "errors": 0}

    threshold = float(platform_avg) - margin

    # Fetch recent daily rows spanning enough days for both trigger and clear checks.
    lookback = max(trigger_days, clear_days)
    since = target_date - timedelta(days=lookback - 1)
    rows_result = await db.execute(
        _RECENT_DAILY_QUERY,
        {"since": since, "until": target_date},
    )
    rows = rows_result.fetchall()

    # Group by template_id → sorted list of (date, satisfaction_rate).
    by_template: dict[str, list[tuple[date, Optional[float]]]] = defaultdict(list)
    for row in rows:
        by_template[str(row[0])].append((row[1], row[2]))

    for template_id, day_list in by_template.items():
        # Sort ascending by date.
        day_list.sort(key=lambda x: x[0])

        # Most-recent N days for trigger / clear checks.
        recent_trigger = day_list[-trigger_days:]
        recent_clear = day_list[-clear_days:]

        try:
            # ------ Check trigger ------
            # Requires exactly trigger_days rows with no calendar gaps — a missing
            # day means not all data is present, so we cannot confirm consecutive breach.
            all_below = (
                len(recent_trigger) == trigger_days
                and _contiguous_days(recent_trigger)
                and all(
                    rate is not None and float(rate) < threshold
                    for _, rate in recent_trigger
                )
            )

            # ------ Check recovery ------
            all_recovered = (
                len(recent_clear) == clear_days
                and _contiguous_days(recent_clear)
                and all(
                    rate is not None and float(rate) >= threshold
                    for _, rate in recent_clear
                )
            )

            # Look up any existing open alert for this template.
            open_result = await db.execute(
                _OPEN_ALERT_QUERY, {"template_id": template_id}
            )
            open_row = open_result.fetchone()
            open_alert_id: Optional[str] = str(open_row[0]) if open_row else None

            if all_below and not open_alert_id:
                # Open a new P2 alert.
                latest_rate = recent_trigger[-1][1]
                description = (
                    f"Template {template_id} satisfaction rate "
                    f"({latest_rate:.1%} on {target_date}) has been below the "
                    f"platform average minus {margin:.0%} "
                    f"(threshold: {threshold:.1%}) for "
                    f"{trigger_days} consecutive days."
                )
                await db.execute(
                    _CREATE_ALERT_QUERY,
                    {
                        "id": str(uuid.uuid4()),
                        "tenant_id": platform_tenant_id,
                        "reporter_id": platform_reporter_id,
                        "issue_type": "template_performance",
                        "description": description,
                        "severity": "high",
                        "status": "open",
                        "metadata": json.dumps(
                            {
                                "source": "platform_batch",
                                "template_id": template_id,
                                "trigger_days": trigger_days,
                                "platform_avg": float(platform_avg),
                                "threshold": threshold,
                                "latest_satisfaction_rate": latest_rate,
                            }
                        ),
                    },
                )
                alerts_opened += 1
                logger.info(
                    "underperforming_template_alert_opened",
                    template_id=template_id,
                    date=str(target_date),
                    latest_rate=latest_rate,
                    threshold=threshold,
                )

            elif all_recovered and open_alert_id:
                # Auto-close the existing alert.
                await db.execute(_CLOSE_ALERT_QUERY, {"issue_id": open_alert_id})
                alerts_cleared += 1
                logger.info(
                    "underperforming_template_alert_cleared",
                    template_id=template_id,
                    date=str(target_date),
                )

        except Exception as exc:
            errors += 1
            logger.error(
                "underperforming_alerts_row_error",
                template_id=template_id,
                date=str(target_date),
                error=str(exc),
            )

    return {
        "alerts_opened": alerts_opened,
        "alerts_cleared": alerts_cleared,
        "errors": errors,
    }
