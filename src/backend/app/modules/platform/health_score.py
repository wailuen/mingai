"""
Tenant health score algorithm.

Computes a composite 0-100 health score from four weighted components:
  - usage_trend  (30%): query volume trend vs. prior period
  - feature_breadth (20%): fraction of available features in use
  - satisfaction (35%): positive feedback percentage
  - error_rate (15%): inverse of error occurrence rate

Missing inputs fall back to explicit last_known component values.
Raises ValueError when a component is None and no last_known is available.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Component weights (must sum to 100)
# ---------------------------------------------------------------------------
WEIGHT_USAGE_TREND = 30.0
WEIGHT_FEATURE_BREADTH = 20.0
WEIGHT_SATISFACTION = 35.0
WEIGHT_ERROR_RATE = 15.0

# ---------------------------------------------------------------------------
# Category thresholds
# ---------------------------------------------------------------------------
_CATEGORY_THRESHOLDS: list[tuple[float, str]] = [
    (81.0, "excellent"),
    (61.0, "healthy"),
    (41.0, "warning"),
]
_CATEGORY_DEFAULT = "critical"


@dataclass(frozen=True)
class HealthScore:
    """Immutable result of a health score calculation."""

    score: float
    category: str
    components: dict[str, float]


def _classify(score: float) -> str:
    """Return category string for a numeric score."""
    for threshold, label in _CATEGORY_THRESHOLDS:
        if score >= threshold:
            return label
    return _CATEGORY_DEFAULT


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp *value* to [low, high]."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def _compute_usage_trend(usage_trend_pct: float) -> float:
    """Usage trend component: 30 * max(0, min(1, 1 + pct))."""
    factor = _clamp(1.0 + usage_trend_pct, 0.0, 1.0)
    return round(WEIGHT_USAGE_TREND * factor, 2)


def _compute_feature_breadth(feature_breadth: float) -> float:
    """Feature breadth component: breadth_fraction * 20."""
    factor = _clamp(feature_breadth, 0.0, 1.0)
    return round(WEIGHT_FEATURE_BREADTH * factor, 2)


def _compute_satisfaction(satisfaction_pct: float) -> float:
    """Satisfaction component: (pct / 100) * 35."""
    factor = _clamp(satisfaction_pct / 100.0, 0.0, 1.0)
    return round(WEIGHT_SATISFACTION * factor, 2)


def _compute_error_rate(error_rate_pct: float) -> float:
    """Error rate component: (1 - pct/100) * 15."""
    factor = _clamp(1.0 - error_rate_pct / 100.0, 0.0, 1.0)
    return round(WEIGHT_ERROR_RATE * factor, 2)


def calculate_health_score(
    usage_trend_pct: float | None,
    feature_breadth: float | None,
    satisfaction_pct: float | None,
    error_rate_pct: float | None,
    last_known: dict[str, float] | None = None,
) -> HealthScore:
    """Calculate a composite health score from four input signals.

    Parameters
    ----------
    usage_trend_pct:
        Growth rate as a fraction (e.g. -0.25 = 25 % decline). ``None``
        triggers fallback to *last_known*.
    feature_breadth:
        Fraction of features in use, 0.0-1.0.
    satisfaction_pct:
        Positive-feedback percentage, 0-100.
    error_rate_pct:
        Error occurrence percentage, 0-100.
    last_known:
        Dict mapping component names to their last computed scores.
        Used when the corresponding raw input is ``None``.

    Returns
    -------
    HealthScore
        Dataclass with ``score``, ``category``, and ``components``.

    Raises
    ------
    ValueError
        If an input is ``None`` and no ``last_known`` value exists for
        that component.
    """
    if last_known is None:
        last_known = {}

    components: dict[str, float] = {}

    # --- usage_trend ---
    if usage_trend_pct is not None:
        components["usage_trend"] = _compute_usage_trend(usage_trend_pct)
    elif "usage_trend" in last_known:
        components["usage_trend"] = last_known["usage_trend"]
        logger.info(
            "usage_trend_pct is None; using last_known value %.2f",
            last_known["usage_trend"],
        )
    else:
        raise ValueError(
            "usage_trend_pct is None and no last_known value provided for 'usage_trend'"
        )

    # --- feature_breadth ---
    if feature_breadth is not None:
        components["feature_breadth"] = _compute_feature_breadth(feature_breadth)
    elif "feature_breadth" in last_known:
        components["feature_breadth"] = last_known["feature_breadth"]
        logger.info(
            "feature_breadth is None; using last_known value %.2f",
            last_known["feature_breadth"],
        )
    else:
        raise ValueError(
            "feature_breadth is None and no last_known value provided for 'feature_breadth'"
        )

    # --- satisfaction ---
    if satisfaction_pct is not None:
        components["satisfaction"] = _compute_satisfaction(satisfaction_pct)
    elif "satisfaction" in last_known:
        components["satisfaction"] = last_known["satisfaction"]
        logger.info(
            "satisfaction_pct is None; using last_known value %.2f",
            last_known["satisfaction"],
        )
    else:
        raise ValueError(
            "satisfaction_pct is None and no last_known value provided for 'satisfaction'"
        )

    # --- error_rate ---
    if error_rate_pct is not None:
        components["error_rate"] = _compute_error_rate(error_rate_pct)
    elif "error_rate" in last_known:
        components["error_rate"] = last_known["error_rate"]
        logger.info(
            "error_rate_pct is None; using last_known value %.2f",
            last_known["error_rate"],
        )
    else:
        raise ValueError(
            "error_rate_pct is None and no last_known value provided for 'error_rate'"
        )

    raw_score = sum(components.values())
    score = round(_clamp(raw_score, 0.0, 100.0), 1)
    category = _classify(score)

    return HealthScore(score=score, category=category, components=components)
