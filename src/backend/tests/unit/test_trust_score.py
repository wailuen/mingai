"""
Unit tests for HAR Trust Score computation (AI-046, AI-047).

Tier 1: Fast, isolated, uses AsyncMock for DB.
Tests compute_trust_score formula:
  trust_score = min(100, kyb_pts + txn_volume_score - dispute_penalty)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestComputeTrustScore:
    """Test compute_trust_score with various agent profiles."""

    @pytest.mark.asyncio
    async def test_zero_kyb_level_no_transactions(self):
        """Agent with kyb_level=0 and no transactions => trust_score = 0."""
        from app.modules.har.trust import compute_trust_score

        mock_db = AsyncMock()

        # kyb_level query: returns 0
        kyb_result = MagicMock()
        kyb_result.scalar.return_value = 0

        # completed txn count: 0
        completed_result = MagicMock()
        completed_result.scalar.return_value = 0

        # disputed txn count: 0
        disputed_result = MagicMock()
        disputed_result.scalar.return_value = 0

        # UPDATE result (rowcount)
        update_result = MagicMock()
        update_result.rowcount = 1

        mock_db.execute = AsyncMock(
            side_effect=[kyb_result, completed_result, disputed_result, update_result]
        )

        score = await compute_trust_score("agent-001", "tenant-001", mock_db)
        assert score == 0

    @pytest.mark.asyncio
    async def test_full_kyb_level_only(self):
        """Agent with kyb_level=3 and no transactions => trust_score = 40."""
        from app.modules.har.trust import compute_trust_score

        mock_db = AsyncMock()

        kyb_result = MagicMock()
        kyb_result.scalar.return_value = 3

        completed_result = MagicMock()
        completed_result.scalar.return_value = 0

        disputed_result = MagicMock()
        disputed_result.scalar.return_value = 0

        update_result = MagicMock()
        update_result.rowcount = 1

        mock_db.execute = AsyncMock(
            side_effect=[kyb_result, completed_result, disputed_result, update_result]
        )

        score = await compute_trust_score("agent-002", "tenant-001", mock_db)
        assert score == 40

    @pytest.mark.asyncio
    async def test_kyb_with_completed_transactions(self):
        """kyb_level=2 (30pts) + 5 completed transactions (5pts) => 35."""
        from app.modules.har.trust import compute_trust_score

        mock_db = AsyncMock()

        kyb_result = MagicMock()
        kyb_result.scalar.return_value = 2

        completed_result = MagicMock()
        completed_result.scalar.return_value = 5

        disputed_result = MagicMock()
        disputed_result.scalar.return_value = 0

        update_result = MagicMock()
        update_result.rowcount = 1

        mock_db.execute = AsyncMock(
            side_effect=[kyb_result, completed_result, disputed_result, update_result]
        )

        score = await compute_trust_score("agent-003", "tenant-001", mock_db)
        assert score == 35

    @pytest.mark.asyncio
    async def test_dispute_penalty_applied(self):
        """kyb_level=2 (30pts) + 3 disputes (30 penalty) => 0."""
        from app.modules.har.trust import compute_trust_score

        mock_db = AsyncMock()

        kyb_result = MagicMock()
        kyb_result.scalar.return_value = 2

        completed_result = MagicMock()
        completed_result.scalar.return_value = 0

        disputed_result = MagicMock()
        disputed_result.scalar.return_value = 3

        update_result = MagicMock()
        update_result.rowcount = 1

        mock_db.execute = AsyncMock(
            side_effect=[kyb_result, completed_result, disputed_result, update_result]
        )

        score = await compute_trust_score("agent-004", "tenant-001", mock_db)
        assert score == 0

    @pytest.mark.asyncio
    async def test_trust_score_capped_at_100(self):
        """kyb_level=3 (40pts) + 80 completed (capped at 30) => 70, not 110."""
        from app.modules.har.trust import compute_trust_score

        mock_db = AsyncMock()

        kyb_result = MagicMock()
        kyb_result.scalar.return_value = 3

        completed_result = MagicMock()
        completed_result.scalar.return_value = 80

        disputed_result = MagicMock()
        disputed_result.scalar.return_value = 0

        update_result = MagicMock()
        update_result.rowcount = 1

        mock_db.execute = AsyncMock(
            side_effect=[kyb_result, completed_result, disputed_result, update_result]
        )

        score = await compute_trust_score("agent-005", "tenant-001", mock_db)
        # 40 + 30 (capped) - 0 = 70
        assert score == 70
        # Ensure it never exceeds 100
        assert score <= 100

    @pytest.mark.asyncio
    async def test_trust_score_persisted_to_db(self):
        """After compute_trust_score, verify UPDATE was called with correct value."""
        from app.modules.har.trust import compute_trust_score

        mock_db = AsyncMock()

        kyb_result = MagicMock()
        kyb_result.scalar.return_value = 1  # 15pts

        completed_result = MagicMock()
        completed_result.scalar.return_value = 10  # 10pts

        disputed_result = MagicMock()
        disputed_result.scalar.return_value = 1  # 10 penalty

        update_result = MagicMock()
        update_result.rowcount = 1

        mock_db.execute = AsyncMock(
            side_effect=[kyb_result, completed_result, disputed_result, update_result]
        )

        score = await compute_trust_score("agent-006", "tenant-001", mock_db)
        # 15 + 10 - 10 = 15
        assert score == 15

        # The 4th call should be the UPDATE
        assert mock_db.execute.call_count == 4
        update_call = mock_db.execute.call_args_list[3]
        # Verify the UPDATE params include the computed score
        update_params = (
            update_call[0][1]
            if len(update_call[0]) > 1
            else update_call[1].get("parameters", {})
        )
        assert update_params["trust_score"] == 15
        assert update_params["agent_id"] == "agent-006"

    @pytest.mark.asyncio
    async def test_negative_score_floors_at_zero(self):
        """Dispute penalty > kyb_pts + txn_volume => score floors at 0, not negative."""
        from app.modules.har.trust import compute_trust_score

        mock_db = AsyncMock()

        kyb_result = MagicMock()
        kyb_result.scalar.return_value = 0  # 0pts

        completed_result = MagicMock()
        completed_result.scalar.return_value = 2  # 2pts

        disputed_result = MagicMock()
        disputed_result.scalar.return_value = 3  # 30 penalty

        update_result = MagicMock()
        update_result.rowcount = 1

        mock_db.execute = AsyncMock(
            side_effect=[kyb_result, completed_result, disputed_result, update_result]
        )

        score = await compute_trust_score("agent-007", "tenant-001", mock_db)
        assert score == 0
