"""
Unit tests for HAR A2A Transaction State Machine (AI-043, AI-044).

Tests state transition validation, terminal states, and all valid transitions.
Tier 1: Fast, isolated, uses mocking for DB helpers.
"""
import pytest

from app.modules.har.state_machine import VALID_TRANSITIONS


# ---------------------------------------------------------------------------
# State Transition Validation (AI-043)
# ---------------------------------------------------------------------------


class TestValidTransitions:
    """Test VALID_TRANSITIONS map correctness."""

    def test_valid_transition_draft_to_open(self):
        """DRAFT -> OPEN is a valid transition."""
        assert "OPEN" in VALID_TRANSITIONS["DRAFT"]

    def test_invalid_transition_draft_to_committed(self):
        """DRAFT -> COMMITTED is not a valid transition."""
        assert "COMMITTED" not in VALID_TRANSITIONS["DRAFT"]

    @pytest.mark.parametrize(
        "from_state,to_state",
        [
            ("DRAFT", "OPEN"),
            ("OPEN", "NEGOTIATING"),
            ("OPEN", "ABANDONED"),
            ("NEGOTIATING", "COMMITTED"),
            ("NEGOTIATING", "ABANDONED"),
            ("COMMITTED", "EXECUTING"),
            ("COMMITTED", "ABANDONED"),
            ("EXECUTING", "COMPLETED"),
            ("EXECUTING", "DISPUTED"),
            ("DISPUTED", "RESOLVED"),
        ],
    )
    def test_all_valid_transitions_accepted(self, from_state: str, to_state: str):
        """All specified valid transitions must be in the map."""
        assert to_state in VALID_TRANSITIONS[from_state], (
            f"Expected {from_state} -> {to_state} to be valid, "
            f"but allowed transitions are {VALID_TRANSITIONS[from_state]}"
        )

    def test_abandoned_is_terminal(self):
        """ABANDONED is a terminal state with no outgoing transitions."""
        assert (
            VALID_TRANSITIONS.get("ABANDONED", []) == []
        ), "ABANDONED must be a terminal state with no valid transitions"

    def test_completed_is_terminal(self):
        """COMPLETED is a terminal state with no outgoing transitions."""
        assert (
            VALID_TRANSITIONS.get("COMPLETED", []) == []
        ), "COMPLETED must be a terminal state with no valid transitions"

    def test_resolved_is_terminal(self):
        """RESOLVED is a terminal state with no outgoing transitions."""
        assert (
            VALID_TRANSITIONS.get("RESOLVED", []) == []
        ), "RESOLVED must be a terminal state with no valid transitions"


# ---------------------------------------------------------------------------
# check_requires_approval (AI-045)
# ---------------------------------------------------------------------------


class TestCheckRequiresApproval:
    """Test approval threshold logic."""

    @pytest.mark.asyncio
    async def test_amount_above_threshold_requires_approval(self):
        """Amount >= 5000 should require approval."""
        from unittest.mock import AsyncMock

        from app.modules.har.state_machine import check_requires_approval

        mock_db = AsyncMock()
        result = await check_requires_approval(
            amount=6000.0, tenant_id="tenant-001", db=mock_db
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_amount_at_threshold_requires_approval(self):
        """Amount exactly 5000 should require approval."""
        from unittest.mock import AsyncMock

        from app.modules.har.state_machine import check_requires_approval

        mock_db = AsyncMock()
        result = await check_requires_approval(
            amount=5000.0, tenant_id="tenant-001", db=mock_db
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_amount_below_threshold_no_approval(self):
        """Amount < 5000 should not require approval."""
        from unittest.mock import AsyncMock

        from app.modules.har.state_machine import check_requires_approval

        mock_db = AsyncMock()
        result = await check_requires_approval(
            amount=4999.99, tenant_id="tenant-001", db=mock_db
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_none_amount_no_approval(self):
        """None amount should not require approval."""
        from unittest.mock import AsyncMock

        from app.modules.har.state_machine import check_requires_approval

        mock_db = AsyncMock()
        result = await check_requires_approval(
            amount=None, tenant_id="tenant-001", db=mock_db
        )
        assert result is False
