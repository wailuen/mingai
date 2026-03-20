"""
Unit tests for PA-007: health score job at-risk detection and composite logic.

Tests the scoring edge cases and at-risk flag conditions without hitting
a real database — all DB calls are replaced with simple async stubs.
"""
from __future__ import annotations

import asyncio
import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.scheduler import seconds_until_utc
from app.modules.platform.health_score_job import (
    _AT_RISK_COMPOSITE_THRESHOLD,
    _AT_RISK_SATISFACTION_THRESHOLD,
    _SATISFACTION_WEEKS_REQUIRED,
    _USAGE_DECLINE_WEEKS_REQUIRED,
    _detect_at_risk,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_with_scores(rows: list[tuple]) -> Any:
    """
    Build an async mock DB that returns the provided rows from fetchall().
    """
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows

    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


# ---------------------------------------------------------------------------
# Tests: _detect_at_risk
# ---------------------------------------------------------------------------


class TestDetectAtRisk:
    """PA-007 at-risk detection rules."""

    # ------------------------------------------------------------------
    # Rule 1: composite_low
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_composite_below_threshold_flags_composite_low(self):
        """composite_score < 40 → at_risk_flag=True, reason='composite_low'."""
        db = _make_db_with_scores([])  # no prior rows needed
        flag, reason = await _detect_at_risk(
            tenant_id="t1",
            composite_score=39.9,
            satisfaction_score=80.0,
            db=db,
        )
        assert flag is True
        assert reason == "composite_low"

    @pytest.mark.asyncio
    async def test_composite_exactly_at_threshold_not_flagged(self):
        """composite_score == 40.0 → not flagged (threshold is strictly <)."""
        db = _make_db_with_scores([])
        flag, reason = await _detect_at_risk(
            tenant_id="t1",
            composite_score=40.0,
            satisfaction_score=80.0,
            db=db,
        )
        assert flag is False
        assert reason is None

    @pytest.mark.asyncio
    async def test_composite_well_above_threshold_not_flagged(self):
        """composite_score = 75.0 → no at-risk rule triggers."""
        db = _make_db_with_scores([])
        flag, reason = await _detect_at_risk(
            tenant_id="t1",
            composite_score=75.0,
            satisfaction_score=80.0,
            db=db,
        )
        assert flag is False
        assert reason is None

    # ------------------------------------------------------------------
    # Rule 2: satisfaction_declining
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_satisfaction_below_50_for_2_consecutive_weeks(self):
        """
        satisfaction_score (weighted component, max=35) < 17.5 AND prior week also < 17.5
        → at_risk_flag=True, reason='satisfaction_declining'.
        (17.5 = 50% raw satisfaction * 35 component weight)
        """
        # Return one prior row with satisfaction_score < 17.5
        db = _make_db_with_scores([(Decimal("12.0"),)])
        flag, reason = await _detect_at_risk(
            tenant_id="t1",
            composite_score=55.0,  # above composite threshold
            satisfaction_score=14.0,  # current weighted satisfaction below 17.5
            db=db,
        )
        assert flag is True
        assert reason == "satisfaction_declining"

    @pytest.mark.asyncio
    async def test_satisfaction_below_50_but_prior_week_above_50_not_flagged(self):
        """
        satisfaction_score below threshold for current week only (prior week was OK)
        → no flag.
        """
        db = _make_db_with_scores([(Decimal("25.0"),)])  # prior was fine (above 17.5)
        flag, reason = await _detect_at_risk(
            tenant_id="t1",
            composite_score=55.0,
            satisfaction_score=14.0,  # current below threshold, prior above
            db=db,
        )
        assert flag is False
        assert reason is None

    @pytest.mark.asyncio
    async def test_satisfaction_none_skips_rule_2(self):
        """satisfaction_score=None → rule 2 is skipped entirely."""
        db = _make_db_with_scores([])
        flag, reason = await _detect_at_risk(
            tenant_id="t1",
            composite_score=55.0,
            satisfaction_score=None,
            db=db,
        )
        assert flag is False
        assert reason is None

    # ------------------------------------------------------------------
    # Rule 3: usage_trending_down
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_composite_declining_3_consecutive_weeks(self):
        """
        Current composite < prior_w1 < prior_w2 < prior_w3 (all strictly declining)
        → at_risk_flag=True, reason='usage_trending_down'.
        """
        # Three prior rows in DESC order (most recent stored first):
        # w1=65, w2=70, w3=75 — declining from 75→70→65→current(60)
        prior_rows = [
            (Decimal("65.0"),),
            (Decimal("70.0"),),
            (Decimal("75.0"),),
        ]
        db = _make_db_with_scores(prior_rows)
        flag, reason = await _detect_at_risk(
            tenant_id="t1",
            composite_score=60.0,  # current < 65 (most recent stored)
            satisfaction_score=80.0,  # satisfaction fine
            db=db,
        )
        assert flag is True
        assert reason == "usage_trending_down"

    @pytest.mark.asyncio
    async def test_composite_declining_only_2_weeks_not_enough(self):
        """
        Only 2 prior rows available → rule 3 requires 3 → not flagged.
        """
        prior_rows = [
            (Decimal("65.0"),),
            (Decimal("70.0"),),
        ]
        db = _make_db_with_scores(prior_rows)
        flag, reason = await _detect_at_risk(
            tenant_id="t1",
            composite_score=60.0,
            satisfaction_score=80.0,
            db=db,
        )
        assert flag is False
        assert reason is None

    @pytest.mark.asyncio
    async def test_composite_not_strictly_declining_not_flagged(self):
        """
        Prior weeks not strictly increasing (w2 >= w1) → not flagged.
        Pattern: current=60, w1=65, w2=65, w3=75 — not strictly declining.
        """
        prior_rows = [
            (Decimal("65.0"),),
            (Decimal("65.0"),),  # flat — not strictly declining
            (Decimal("75.0"),),
        ]
        db = _make_db_with_scores(prior_rows)
        flag, reason = await _detect_at_risk(
            tenant_id="t1",
            composite_score=60.0,
            satisfaction_score=80.0,
            db=db,
        )
        assert flag is False
        assert reason is None

    @pytest.mark.asyncio
    async def test_no_prior_rows_no_flag(self):
        """No stored rows → neither rule 2 nor rule 3 fires."""
        db = _make_db_with_scores([])
        flag, reason = await _detect_at_risk(
            tenant_id="t1",
            composite_score=55.0,
            satisfaction_score=80.0,
            db=db,
        )
        assert flag is False
        assert reason is None


# ---------------------------------------------------------------------------
# Tests: scheduler timing helper
# ---------------------------------------------------------------------------


class TestSecondsUntilNextRun:
    """Test the 02:00 UTC scheduler delay calculation."""

    def test_returns_at_least_60_seconds(self):
        """Always returns >= 60s regardless of current time."""
        delay = seconds_until_utc(2, 0)
        assert delay >= 60.0

    def test_returns_at_most_one_day(self):
        """Delay cannot exceed 24 hours plus 60s buffer."""
        delay = seconds_until_utc(2, 0)
        assert delay <= 24 * 3600 + 60.0


# ---------------------------------------------------------------------------
# Tests: composite weighting via calculate_health_score
# ---------------------------------------------------------------------------


class TestCompositeWeighting:
    """Verify the composite = sum(components) is correctly weighted."""

    def test_composite_formula_matches_spec(self):
        """
        Spec: (usage*0.30) + (breadth*0.20) + (satisfaction*0.35) + (error*0.15).
        100% inputs → components sum to 100 → composite = 100.
        """
        from app.modules.platform.health_score import calculate_health_score

        result = calculate_health_score(
            usage_trend_pct=0.0,  # 30 * 1.0 = 30
            feature_breadth=1.0,  # 20 * 1.0 = 20
            satisfaction_pct=100.0,  # 35 * 1.0 = 35
            error_rate_pct=0.0,  # 15 * 1.0 = 15
        )
        assert result.score == 100.0
        assert result.components["usage_trend"] == 30.0
        assert result.components["feature_breadth"] == 20.0
        assert result.components["satisfaction"] == 35.0
        assert result.components["error_rate"] == 15.0

    def test_composite_50_pct_inputs(self):
        """
        50% inputs → composite ≈ 57.5.
        usage: 30 * 0.5 = 15
        breadth: 20 * 0.5 = 10
        satisfaction: 35 * 0.5 = 17.5
        error: 15 * 0.5 = 7.5
        total = 50.0
        """
        from app.modules.platform.health_score import calculate_health_score

        result = calculate_health_score(
            usage_trend_pct=-0.5,  # 1 + (-0.5) = 0.5 → 30 * 0.5 = 15
            feature_breadth=0.5,  # 20 * 0.5 = 10
            satisfaction_pct=50.0,  # 35 * 0.5 = 17.5
            error_rate_pct=50.0,  # (1 - 0.5) * 15 = 7.5
        )
        assert result.score == 50.0

    def test_missing_all_signals_raises_without_last_known(self):
        """All-None inputs with no last_known raises ValueError."""
        from app.modules.platform.health_score import calculate_health_score

        with pytest.raises(ValueError):
            calculate_health_score(
                usage_trend_pct=None,
                feature_breadth=None,
                satisfaction_pct=None,
                error_rate_pct=None,
            )

    def test_missing_all_signals_uses_last_known(self):
        """All-None inputs with last_known falls back cleanly."""
        from app.modules.platform.health_score import calculate_health_score

        last_known = {
            "usage_trend": 24.0,
            "feature_breadth": 16.0,
            "satisfaction": 28.0,
            "error_rate": 12.0,
        }
        result = calculate_health_score(
            usage_trend_pct=None,
            feature_breadth=None,
            satisfaction_pct=None,
            error_rate_pct=None,
            last_known=last_known,
        )
        assert result.score == 80.0
