"""
Still-happening rate limiter for issue escalation (TEST-016).

When a fix is deployed for an issue and users report it is "still happening",
the system applies rate-limited escalation:

- FIRST occurrence after a fix deployment -> auto-escalate to developer
- SECOND+ occurrence -> route to human review (NOT auto-escalate)

Rate limit state is keyed by (issue_id, fix_deployment_id), NOT per user.
State persists in the DB table `still_happening_counters` so it survives
service restarts.

DB table schema:
    still_happening_counters (
        issue_id TEXT NOT NULL,
        fix_deployment_id TEXT NOT NULL,
        count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (issue_id, fix_deployment_id)
    )
"""
import structlog
from sqlalchemy import text

logger = structlog.get_logger()

# Routing decision constants
AUTO_ESCALATE = "auto_escalate"
HUMAN_REVIEW = "human_review"


class StillHappeningRateLimiter:
    """
    Rate limiter for "still happening" issue escalations.

    First occurrence after a fix deployment -> auto-escalates (returns "auto_escalate").
    Second+ occurrence -> routes to human review (returns "human_review").

    Rate limit state stored in DB table: still_happening_counters
    (issue_id TEXT, fix_deployment_id TEXT, count INTEGER,
     PRIMARY KEY (issue_id, fix_deployment_id))

    Counter resets when a new fix_deployment_id is recorded (reset_for_fix() method).
    """

    def __init__(self, db=None):
        if db is None:
            raise ValueError(
                "StillHappeningRateLimiter requires a database session (db). "
                "Pass an AsyncSession instance -- state must persist in DB, "
                "not in memory."
            )
        self._db = db

    async def record_occurrence(self, issue_id: str, fix_deployment_id: str) -> str:
        """
        Record a still-happening occurrence and return the routing decision.

        Uses an atomic UPSERT to increment the counter and returns the new count
        in a single round-trip. No race conditions.

        Args:
            issue_id: The issue being reported as still happening.
            fix_deployment_id: The fix deployment that was supposed to resolve it.

        Returns:
            "auto_escalate" if this is the first occurrence for this fix_deployment_id.
            "human_review" if this is the second or subsequent occurrence.

        Raises:
            ValueError: If issue_id or fix_deployment_id is empty/None.
        """
        self._validate_inputs(issue_id, fix_deployment_id)

        upsert_sql = text(
            "INSERT INTO still_happening_counters (issue_id, fix_deployment_id, count) "
            "VALUES (:issue_id, :fix_deployment_id, 1) "
            "ON CONFLICT (issue_id, fix_deployment_id) DO UPDATE "
            "SET count = still_happening_counters.count + 1 "
            "RETURNING count"
        )

        result = await self._db.execute(
            upsert_sql,
            {"issue_id": issue_id, "fix_deployment_id": fix_deployment_id},
        )
        new_count = result.scalar_one()

        if new_count == 1:
            logger.info(
                "still_happening.auto_escalate",
                issue_id=issue_id,
                fix_deployment_id=fix_deployment_id,
                count=new_count,
            )
            return AUTO_ESCALATE

        logger.info(
            "still_happening.human_review",
            issue_id=issue_id,
            fix_deployment_id=fix_deployment_id,
            count=new_count,
        )
        return HUMAN_REVIEW

    async def reset_for_fix(self, issue_id: str, fix_deployment_id: str) -> None:
        """
        Reset the counter when a new fix is deployed.

        Deletes the counter row for (issue_id, fix_deployment_id) so the next
        "still happening" report will be treated as the first occurrence.

        Args:
            issue_id: The issue whose counter should be reset.
            fix_deployment_id: The fix deployment to reset the counter for.

        Raises:
            ValueError: If issue_id or fix_deployment_id is empty/None.
        """
        self._validate_inputs(issue_id, fix_deployment_id)

        delete_sql = text(
            "DELETE FROM still_happening_counters "
            "WHERE issue_id = :issue_id AND fix_deployment_id = :fix_deployment_id"
        )

        await self._db.execute(
            delete_sql,
            {"issue_id": issue_id, "fix_deployment_id": fix_deployment_id},
        )

        logger.info(
            "still_happening.counter_reset",
            issue_id=issue_id,
            fix_deployment_id=fix_deployment_id,
        )

    async def get_occurrence_count(self, issue_id: str, fix_deployment_id: str) -> int:
        """
        Get current occurrence count for (issue_id, fix_deployment_id).

        Returns 0 if no counter exists (no occurrences recorded yet).

        Args:
            issue_id: The issue to query.
            fix_deployment_id: The fix deployment to query.

        Returns:
            Current count (0 if no row exists).

        Raises:
            ValueError: If issue_id or fix_deployment_id is empty/None.
        """
        self._validate_inputs(issue_id, fix_deployment_id)

        select_sql = text(
            "SELECT count FROM still_happening_counters "
            "WHERE issue_id = :issue_id AND fix_deployment_id = :fix_deployment_id"
        )

        result = await self._db.execute(
            select_sql,
            {"issue_id": issue_id, "fix_deployment_id": fix_deployment_id},
        )
        row = result.scalar_one_or_none()

        if row is None:
            return 0
        return row

    @staticmethod
    def _validate_inputs(issue_id: str, fix_deployment_id: str) -> None:
        """
        Validate that issue_id and fix_deployment_id are non-empty strings.

        Raises ValueError with clear context if validation fails.
        """
        if not issue_id or not isinstance(issue_id, str) or not issue_id.strip():
            raise ValueError(f"issue_id must be a non-empty string, got: {issue_id!r}")
        if (
            not fix_deployment_id
            or not isinstance(fix_deployment_id, str)
            or not fix_deployment_id.strip()
        ):
            raise ValueError(
                f"fix_deployment_id must be a non-empty string, got: {fix_deployment_id!r}"
            )
