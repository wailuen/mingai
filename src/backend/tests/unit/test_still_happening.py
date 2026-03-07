"""
TEST-016: "Still happening" rate limit for issue reports.

Validates that StillHappeningRateLimiter correctly:
- Auto-escalates the FIRST "still happening" report after a fix deployment
- Routes the SECOND+ occurrence to human review (NOT auto-escalate)
- Tracks rate limit per (issue_id, fix_deployment_id), not per user
- Persists state in DB, not in-memory
- Resets counter when a new fix deployment is recorded

Tier 1: Fast, isolated, mocks DB only.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.issues.still_happening import StillHappeningRateLimiter


class TestStillHappeningRateLimiter:
    """TEST-016: Still-happening rate limit routing decisions."""

    # ------------------------------------------------------------------
    # 1. First occurrence auto-escalates
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_first_occurrence_auto_escalates(self):
        """First 'still happening' report after a fix deployment returns 'auto_escalate'."""
        mock_db = AsyncMock()
        # Simulate UPSERT returning count=1 (first occurrence)
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 1
        mock_db.execute.return_value = mock_result

        limiter = StillHappeningRateLimiter(db=mock_db)
        decision = await limiter.record_occurrence("issue-001", "fix-deploy-abc")

        assert (
            decision == "auto_escalate"
        ), f"First occurrence should return 'auto_escalate', got '{decision}'"

    # ------------------------------------------------------------------
    # 2. Second occurrence routes to human review
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_second_occurrence_routes_to_human_review(self):
        """Second 'still happening' report returns 'human_review'."""
        mock_db = AsyncMock()
        # Simulate UPSERT returning count=2 (second occurrence)
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 2
        mock_db.execute.return_value = mock_result

        limiter = StillHappeningRateLimiter(db=mock_db)
        decision = await limiter.record_occurrence("issue-001", "fix-deploy-abc")

        assert (
            decision == "human_review"
        ), f"Second occurrence should return 'human_review', got '{decision}'"

    # ------------------------------------------------------------------
    # 3. Different issues escalate independently
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_different_issue_escalates_independently(self):
        """Different issue_id gets its own counter and escalates independently."""
        mock_db = AsyncMock()

        # First call: issue-001, count=1 (first occurrence for this issue)
        mock_result_1 = MagicMock()
        mock_result_1.scalar_one.return_value = 1

        # Second call: issue-002, count=1 (first occurrence for different issue)
        mock_result_2 = MagicMock()
        mock_result_2.scalar_one.return_value = 1

        mock_db.execute.side_effect = [mock_result_1, mock_result_2]

        limiter = StillHappeningRateLimiter(db=mock_db)

        decision_1 = await limiter.record_occurrence("issue-001", "fix-deploy-abc")
        decision_2 = await limiter.record_occurrence("issue-002", "fix-deploy-abc")

        assert (
            decision_1 == "auto_escalate"
        ), "First issue should auto-escalate independently"
        assert (
            decision_2 == "auto_escalate"
        ), "Second (different) issue should also auto-escalate independently"

    # ------------------------------------------------------------------
    # 4. Fix deployment resets counter
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fix_deployment_resets_counter(self):
        """reset_for_fix() allows the first occurrence to auto-escalate again."""
        mock_db = AsyncMock()
        # After reset, next UPSERT returns count=1 again
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 1
        mock_db.execute.return_value = mock_result

        limiter = StillHappeningRateLimiter(db=mock_db)

        # Reset counter for the issue+fix
        await limiter.reset_for_fix("issue-001", "fix-deploy-abc")

        # Verify reset called execute (DELETE query)
        assert (
            mock_db.execute.call_count >= 1
        ), "reset_for_fix must issue a DB call to delete the counter row"

        # After reset, record occurrence should auto-escalate (count=1)
        decision = await limiter.record_occurrence("issue-001", "fix-deploy-abc")
        assert (
            decision == "auto_escalate"
        ), "After reset, first occurrence should auto-escalate again"

    # ------------------------------------------------------------------
    # 5. Rate limit tracked per issue, not per user
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_rate_limit_tracked_per_issue_not_per_user(self):
        """Same issue + same fix, different 'users' -- counter is shared.

        The counter key is (issue_id, fix_deployment_id), NOT (user_id, ...).
        So when user_A reports and then user_B reports the same issue with
        the same fix_deployment_id, user_B's report is the 2nd occurrence.
        """
        mock_db = AsyncMock()

        # First call from "user_A": count=1
        mock_result_1 = MagicMock()
        mock_result_1.scalar_one.return_value = 1

        # Second call from "user_B": count=2 (same issue, same fix)
        mock_result_2 = MagicMock()
        mock_result_2.scalar_one.return_value = 2

        mock_db.execute.side_effect = [mock_result_1, mock_result_2]

        limiter = StillHappeningRateLimiter(db=mock_db)

        # User A reports (first occurrence)
        decision_a = await limiter.record_occurrence("issue-001", "fix-deploy-xyz")
        assert decision_a == "auto_escalate"

        # User B reports same issue + same fix (second occurrence -- shared counter)
        decision_b = await limiter.record_occurrence("issue-001", "fix-deploy-xyz")
        assert decision_b == "human_review", (
            "Counter is per-issue, not per-user. Second occurrence from any user "
            "should route to human_review."
        )

    # ------------------------------------------------------------------
    # 6. Counter persists in DB, not memory
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_counter_persists_in_db_not_memory(self):
        """Verify DB is called for persistence -- not just in-memory counter.

        Creates two separate StillHappeningRateLimiter instances (simulating
        service restarts) sharing the same DB mock. The second instance must
        still read from DB and route correctly.
        """
        shared_db = AsyncMock()

        # Instance 1: first occurrence, count=1
        mock_result_1 = MagicMock()
        mock_result_1.scalar_one.return_value = 1
        shared_db.execute.return_value = mock_result_1

        limiter_1 = StillHappeningRateLimiter(db=shared_db)
        decision_1 = await limiter_1.record_occurrence("issue-001", "fix-deploy-abc")
        assert decision_1 == "auto_escalate"

        # Verify DB was called (not in-memory)
        assert shared_db.execute.call_count >= 1, (
            "StillHappeningRateLimiter must call db.execute() -- "
            "state must persist in DB, not memory"
        )

        # Instance 2 (simulating restart): second occurrence, count=2
        mock_result_2 = MagicMock()
        mock_result_2.scalar_one.return_value = 2
        shared_db.execute.return_value = mock_result_2

        limiter_2 = StillHappeningRateLimiter(db=shared_db)
        decision_2 = await limiter_2.record_occurrence("issue-001", "fix-deploy-abc")
        assert decision_2 == "human_review", (
            "After service restart (new instance), DB state must persist. "
            "Second occurrence should route to human_review."
        )

        # Both instances called DB -- no in-memory shortcut
        assert (
            shared_db.execute.call_count >= 2
        ), "Both instances must call DB -- state is DB-backed, not in-memory"
