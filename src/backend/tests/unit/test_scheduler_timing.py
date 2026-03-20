"""
Unit tests for SCHED-003: seconds_until_utc timing utility.

Tier 1: Pure function — no mocking needed.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.core.scheduler.timing import seconds_until_utc


class TestSecondsUntilUtc:
    """Unit tests for seconds_until_utc."""

    def _now_at(self, hour: int, minute: int = 0, second: int = 0) -> datetime:
        """Return a UTC datetime with today's date set to HH:MM:SS."""
        now = datetime.now(timezone.utc)
        return now.replace(hour=hour, minute=minute, second=second, microsecond=0)

    def test_returns_positive_seconds(self):
        s = seconds_until_utc(3, 30)
        assert s > 0

    def test_returns_float(self):
        s = seconds_until_utc(3, 30)
        assert isinstance(s, float)

    def test_target_in_future_same_day(self):
        """If target is ahead of now, result < 24h."""
        future = self._now_at(23, 59)
        with patch("app.core.scheduler.timing.datetime") as mock_dt:
            # Set 'now' to 00:00 so 23:59 is ahead
            mock_dt.now.return_value = self._now_at(0, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            s = seconds_until_utc(23, 59)
        assert s < 86400

    def test_target_already_passed_schedules_tomorrow(self):
        """If target is in the past, result is tomorrow (> 0)."""
        past = self._now_at(0, 1)  # 00:01
        with patch("app.core.scheduler.timing.datetime") as mock_dt:
            # Set 'now' to 01:00 so 00:01 is already past
            mock_dt.now.return_value = self._now_at(1, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            s = seconds_until_utc(0, 1)
        assert 0 < s < 86401

    def test_exact_match_schedules_tomorrow(self):
        """If now == target, result is ~86400s (prevents double-firing)."""
        now = datetime.now(timezone.utc)
        s = seconds_until_utc(now.hour, now.minute)
        # Result is target.replace(...) + 1 day — always positive
        assert s > 0
        # Within 1 day + 60s tolerance (minute boundary)
        assert s <= 86400 + 60

    def test_midnight_boundary(self):
        s = seconds_until_utc(0, 0)
        assert s > 0
        assert s <= 86400

    def test_minute_param_defaults_to_zero(self):
        s_with_default = seconds_until_utc(3)
        s_explicit = seconds_until_utc(3, 0)
        # Both should be within 1 second of each other
        assert abs(s_with_default - s_explicit) < 1.0
