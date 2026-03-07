"""
TEST-021: Health score algorithm — unit tests.

Validates the tenant health score calculation:
- 4 weighted components: usage_trend (30%), feature_breadth (20%),
  satisfaction (35%), error_rate (15%)
- Clamping, rounding, category classification
- Missing data fallback via last_known values
"""
import pytest

from app.modules.platform.health_score import (
    HealthScore,
    calculate_health_score,
)


class TestHealthScoreAlgorithm:
    """TEST-021: Health score calculation correctness."""

    # ------------------------------------------------------------------
    # 1. Perfect and zero scores
    # ------------------------------------------------------------------

    def test_all_components_at_100_pct(self):
        """All inputs at maximum yield score = 100."""
        result = calculate_health_score(
            usage_trend_pct=0.0,  # no decline → full 30
            feature_breadth=1.0,  # all features used → full 20
            satisfaction_pct=100.0,  # 100% positive → full 35
            error_rate_pct=0.0,  # 0% errors → full 15
        )
        assert result.score == 100.0
        assert result.category == "excellent"

    def test_all_components_at_0_pct(self):
        """All inputs at minimum yield score = 0."""
        result = calculate_health_score(
            usage_trend_pct=-1.0,  # 100% decline → 0
            feature_breadth=0.0,  # no features → 0
            satisfaction_pct=0.0,  # 0% positive → 0
            error_rate_pct=100.0,  # 100% errors → 0
        )
        assert result.score == 0.0
        assert result.category == "critical"

    # ------------------------------------------------------------------
    # 2. Individual component isolation
    # ------------------------------------------------------------------

    def test_usage_trend_only(self):
        """Usage trend at max, others at zero → score = 30."""
        result = calculate_health_score(
            usage_trend_pct=0.0,
            feature_breadth=0.0,
            satisfaction_pct=0.0,
            error_rate_pct=100.0,
        )
        assert result.score == 30.0
        assert result.components["usage_trend"] == 30.0

    def test_feature_breadth_only(self):
        """Feature breadth at max, others at zero → score = 20."""
        result = calculate_health_score(
            usage_trend_pct=-1.0,
            feature_breadth=1.0,
            satisfaction_pct=0.0,
            error_rate_pct=100.0,
        )
        assert result.score == 20.0
        assert result.components["feature_breadth"] == 20.0

    def test_satisfaction_only(self):
        """Satisfaction at max, others at zero → score = 35."""
        result = calculate_health_score(
            usage_trend_pct=-1.0,
            feature_breadth=0.0,
            satisfaction_pct=100.0,
            error_rate_pct=100.0,
        )
        assert result.score == 35.0
        assert result.components["satisfaction"] == 35.0

    def test_error_rate_only(self):
        """Error rate at zero (best), others at worst → score = 15."""
        result = calculate_health_score(
            usage_trend_pct=-1.0,
            feature_breadth=0.0,
            satisfaction_pct=0.0,
            error_rate_pct=0.0,
        )
        assert result.score == 15.0
        assert result.components["error_rate"] == 15.0

    # ------------------------------------------------------------------
    # 3. Proportional calculations
    # ------------------------------------------------------------------

    def test_usage_trend_declining_20_pct(self):
        """20% decline → usage_trend component = 30 * 0.80 = 24.0."""
        result = calculate_health_score(
            usage_trend_pct=-0.20,
            feature_breadth=1.0,
            satisfaction_pct=100.0,
            error_rate_pct=0.0,
        )
        assert result.components["usage_trend"] == 24.0

    def test_feature_breadth_1_of_5(self):
        """1 of 5 features used (0.2) → component = 0.2 * 20 = 4.0."""
        result = calculate_health_score(
            usage_trend_pct=0.0,
            feature_breadth=0.2,
            satisfaction_pct=100.0,
            error_rate_pct=0.0,
        )
        assert result.components["feature_breadth"] == 4.0

    def test_satisfaction_80_pct(self):
        """80% satisfaction → component = 0.80 * 35 = 28.0."""
        result = calculate_health_score(
            usage_trend_pct=0.0,
            feature_breadth=1.0,
            satisfaction_pct=80.0,
            error_rate_pct=0.0,
        )
        assert result.components["satisfaction"] == 28.0

    def test_error_rate_5_pct(self):
        """5% error rate → component = 0.95 * 15 = 14.25."""
        result = calculate_health_score(
            usage_trend_pct=0.0,
            feature_breadth=1.0,
            satisfaction_pct=100.0,
            error_rate_pct=5.0,
        )
        assert result.components["error_rate"] == 14.25

    # ------------------------------------------------------------------
    # 4. Boundary clamping
    # ------------------------------------------------------------------

    def test_usage_trend_beyond_100_pct_decline_clamped(self):
        """Decline > 100% is clamped to 0 (not negative)."""
        result = calculate_health_score(
            usage_trend_pct=-1.5,
            feature_breadth=1.0,
            satisfaction_pct=100.0,
            error_rate_pct=0.0,
        )
        assert result.components["usage_trend"] == 0.0

    def test_error_rate_above_100_clamped(self):
        """Error rate > 100% (data anomaly) → component clamped to 0."""
        result = calculate_health_score(
            usage_trend_pct=0.0,
            feature_breadth=1.0,
            satisfaction_pct=100.0,
            error_rate_pct=150.0,
        )
        assert result.components["error_rate"] == 0.0

    # ------------------------------------------------------------------
    # 5. Rounding
    # ------------------------------------------------------------------

    def test_score_rounded_to_1_decimal(self):
        """Score with fractional components is rounded to 1 decimal."""
        # usage_trend: 30 * (1 + (-0.13)) = 30 * 0.87 = 26.1
        # feature_breadth: 0.33 * 20 = 6.6
        # satisfaction: 73.0 / 100 * 35 = 25.55
        # error_rate: (1 - 7.0/100) * 15 = 0.93 * 15 = 13.95
        # total = 26.1 + 6.6 + 25.55 + 13.95 = 72.2
        result = calculate_health_score(
            usage_trend_pct=-0.13,
            feature_breadth=0.33,
            satisfaction_pct=73.0,
            error_rate_pct=7.0,
        )
        assert result.score == 72.2

    # ------------------------------------------------------------------
    # 6. Category classification
    # ------------------------------------------------------------------

    def test_score_categories(self):
        """Verify category thresholds: critical/warning/healthy/excellent."""
        # 75 → healthy
        # Build inputs to hit score ~75: usage 30, breadth 20, sat 17.5, err 7.5
        result_healthy = calculate_health_score(
            usage_trend_pct=0.0,  # 30
            feature_breadth=1.0,  # 20
            satisfaction_pct=50.0,  # 17.5
            error_rate_pct=50.0,  # 7.5
        )
        assert result_healthy.score == 75.0
        assert result_healthy.category == "healthy"

        # 45 → warning
        result_warning = calculate_health_score(
            usage_trend_pct=-0.50,  # 15.0
            feature_breadth=0.5,  # 10.0
            satisfaction_pct=40.0,  # 14.0
            error_rate_pct=60.0,  # 6.0
        )
        assert result_warning.score == 45.0
        assert result_warning.category == "warning"

        # 30 → critical
        result_critical = calculate_health_score(
            usage_trend_pct=-1.0,  # 0
            feature_breadth=0.5,  # 10.0
            satisfaction_pct=40.0,  # 14.0
            error_rate_pct=60.0,  # 6.0
        )
        assert result_critical.score == 30.0
        assert result_critical.category == "critical"

        # 90 → excellent
        result_excellent = calculate_health_score(
            usage_trend_pct=0.0,  # 30
            feature_breadth=1.0,  # 20
            satisfaction_pct=80.0,  # 28.0
            error_rate_pct=20.0,  # 12.0
        )
        assert result_excellent.score == 90.0
        assert result_excellent.category == "excellent"

    # ------------------------------------------------------------------
    # 7. Missing data fallback
    # ------------------------------------------------------------------

    def test_missing_component_uses_last_known(self):
        """None inputs fall back to last_known values, not zero."""
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
        # All from last_known: 24 + 16 + 28 + 12 = 80.0
        assert result.score == 80.0
        assert result.components["usage_trend"] == 24.0
        assert result.components["feature_breadth"] == 16.0
        assert result.components["satisfaction"] == 28.0
        assert result.components["error_rate"] == 12.0
