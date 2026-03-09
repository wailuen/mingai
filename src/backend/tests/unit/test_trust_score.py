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

    @pytest.mark.asyncio
    async def test_high_completed_transactions_high_kyb_near_max(self):
        """kyb_level=3 (40pts) + 30 completed (30pts, capped) + 0 disputes => 70."""
        from app.modules.har.trust import compute_trust_score

        mock_db = AsyncMock()

        kyb_result = MagicMock()
        kyb_result.scalar.return_value = 3

        completed_result = MagicMock()
        completed_result.scalar.return_value = 30

        disputed_result = MagicMock()
        disputed_result.scalar.return_value = 0

        update_result = MagicMock()
        update_result.rowcount = 1

        mock_db.execute = AsyncMock(
            side_effect=[kyb_result, completed_result, disputed_result, update_result]
        )

        score = await compute_trust_score("agent-high", "tenant-001", mock_db)
        # 40 + 30 - 0 = 70 (maximum achievable score)
        assert score == 70

    @pytest.mark.asyncio
    async def test_low_completed_transactions_low_kyb(self):
        """kyb_level=1 (15pts) + 1 completed (1pt) + 2 disputes (20 penalty) => 0."""
        from app.modules.har.trust import compute_trust_score

        mock_db = AsyncMock()

        kyb_result = MagicMock()
        kyb_result.scalar.return_value = 1

        completed_result = MagicMock()
        completed_result.scalar.return_value = 1

        disputed_result = MagicMock()
        disputed_result.scalar.return_value = 2

        update_result = MagicMock()
        update_result.rowcount = 1

        mock_db.execute = AsyncMock(
            side_effect=[kyb_result, completed_result, disputed_result, update_result]
        )

        score = await compute_trust_score("agent-low", "tenant-001", mock_db)
        # 15 + 1 - 20 = -4 => floored to 0
        assert score == 0

    @pytest.mark.asyncio
    async def test_score_recomputed_fresh_each_call(self):
        """Each call to compute_trust_score queries DB fresh — not stale/cached."""
        from app.modules.har.trust import compute_trust_score

        mock_db = AsyncMock()

        # First call: kyb=2, 10 completed, 0 disputes => 30 + 10 = 40
        kyb1 = MagicMock()
        kyb1.scalar.return_value = 2
        comp1 = MagicMock()
        comp1.scalar.return_value = 10
        disp1 = MagicMock()
        disp1.scalar.return_value = 0
        upd1 = MagicMock()
        upd1.rowcount = 1

        # Second call: kyb=2, 10 completed, 3 disputes => 30 + 10 - 30 = 10
        kyb2 = MagicMock()
        kyb2.scalar.return_value = 2
        comp2 = MagicMock()
        comp2.scalar.return_value = 10
        disp2 = MagicMock()
        disp2.scalar.return_value = 3
        upd2 = MagicMock()
        upd2.rowcount = 1

        mock_db.execute = AsyncMock(
            side_effect=[kyb1, comp1, disp1, upd1, kyb2, comp2, disp2, upd2]
        )

        score1 = await compute_trust_score("agent-x", "tenant-001", mock_db)
        score2 = await compute_trust_score("agent-x", "tenant-001", mock_db)

        assert score1 == 40
        assert score2 == 10
        # Score changed immediately — not stale
        assert score1 != score2
