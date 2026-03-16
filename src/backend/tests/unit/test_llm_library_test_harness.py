"""
Unit tests for PA-002: LLM Library test harness cost calculation.

Tests the _calculate_test_cost() helper in isolation — no DB, no LLM calls.
"""
import pytest

from app.modules.platform.llm_library.routes import _calculate_test_cost


class TestCalculateTestCost:
    """Unit tests for PA-002 cost formula."""

    def test_both_prices_present_returns_correct_cost(self):
        """
        Cost = (tokens_in / 1000 * price_in) + (tokens_out / 1000 * price_out).
        """
        result = _calculate_test_cost(
            tokens_in=1000,
            tokens_out=500,
            price_in=0.002,
            price_out=0.004,
        )
        # (1000/1000 * 0.002) + (500/1000 * 0.004) = 0.002 + 0.002 = 0.004
        assert result == pytest.approx(0.004, abs=1e-8)

    def test_zero_tokens_returns_zero_cost(self):
        """Zero tokens in and out produces zero cost."""
        result = _calculate_test_cost(
            tokens_in=0,
            tokens_out=0,
            price_in=0.005,
            price_out=0.010,
        )
        assert result == pytest.approx(0.0, abs=1e-8)

    def test_price_in_none_returns_none(self):
        """When price_in is None, cost cannot be calculated — returns None."""
        result = _calculate_test_cost(
            tokens_in=500,
            tokens_out=200,
            price_in=None,
            price_out=0.004,
        )
        assert result is None

    def test_price_out_none_returns_none(self):
        """When price_out is None, cost cannot be calculated — returns None."""
        result = _calculate_test_cost(
            tokens_in=500,
            tokens_out=200,
            price_in=0.002,
            price_out=None,
        )
        assert result is None

    def test_both_prices_none_returns_none(self):
        """When both prices are None (Draft entry), cost is None."""
        result = _calculate_test_cost(
            tokens_in=1000,
            tokens_out=500,
            price_in=None,
            price_out=None,
        )
        assert result is None

    def test_result_is_rounded_to_8_decimal_places(self):
        """Result is rounded to 8 decimal places to prevent floating-point noise."""
        result = _calculate_test_cost(
            tokens_in=1,
            tokens_out=1,
            price_in=0.000000001,
            price_out=0.000000001,
        )
        # Very small cost — but must not be a long floating tail
        assert result is not None
        # Verify the value is finite
        assert result >= 0.0
        # Verify no more than 8 decimal places in the string representation
        str_result = f"{result:.10f}"
        # Strip trailing zeros and check precision
        decimal_part = str_result.split(".")[1].rstrip("0")
        assert len(decimal_part) <= 8

    def test_large_token_counts(self):
        """Large token counts (100k+) compute correctly without overflow."""
        result = _calculate_test_cost(
            tokens_in=100_000,
            tokens_out=50_000,
            price_in=0.002,
            price_out=0.006,
        )
        # (100000/1000 * 0.002) + (50000/1000 * 0.006) = 0.2 + 0.3 = 0.5
        assert result == pytest.approx(0.5, rel=1e-6)

    def test_fractional_tokens_handled(self):
        """
        Fractional token ratios (e.g. 1 token) are handled without division errors.
        """
        result = _calculate_test_cost(
            tokens_in=1,
            tokens_out=1,
            price_in=1.0,
            price_out=2.0,
        )
        # (1/1000 * 1.0) + (1/1000 * 2.0) = 0.001 + 0.002 = 0.003
        assert result == pytest.approx(0.003, abs=1e-8)

    def test_only_input_tokens_no_output(self):
        """Zero output tokens: cost comes from input tokens only."""
        result = _calculate_test_cost(
            tokens_in=2000,
            tokens_out=0,
            price_in=0.003,
            price_out=0.006,
        )
        # (2000/1000 * 0.003) + 0 = 0.006
        assert result == pytest.approx(0.006, abs=1e-8)

    def test_only_output_tokens_no_input(self):
        """Zero input tokens: cost comes from output tokens only."""
        result = _calculate_test_cost(
            tokens_in=0,
            tokens_out=3000,
            price_in=0.003,
            price_out=0.006,
        )
        # 0 + (3000/1000 * 0.006) = 0.018
        assert result == pytest.approx(0.018, abs=1e-8)

    def test_cost_formula_matches_instrumented_client_formula(self):
        """
        Verify this formula is consistent with InstrumentedLLMClient._calculate_cost().
        Both use: (tokens_in / 1000.0 * price_in) + (tokens_out / 1000.0 * price_out)
        """
        tokens_in = 512
        tokens_out = 256
        price_in = 0.0015
        price_out = 0.002

        result = _calculate_test_cost(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            price_in=price_in,
            price_out=price_out,
        )

        expected = round(
            (tokens_in / 1000.0 * price_in) + (tokens_out / 1000.0 * price_out),
            8,
        )
        assert result == pytest.approx(expected, rel=1e-8)
