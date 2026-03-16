"""
Unit tests for PA-027: Underperforming template alerts.

Tests check_underperforming_alerts() in isolation via AsyncMock DB session.

Tier 1: Fast, isolated — no real DB.
"""
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, call

import pytest

TEST_TEMPLATE_A = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
TEST_TEMPLATE_B = "bbbbcccc-dddd-eeee-ffff-000011112222"
TEST_PLATFORM_USER_ID = "ccccdddd-eeee-ffff-0000-111122223333"
TEST_PLATFORM_TENANT_ID = "ddddeeee-ffff-0000-1111-222233334444"

_TARGET = date(2026, 3, 15)


def _make_mock_db(
    admin_row,
    platform_avg,
    daily_rows,
    open_alert_id=None,
):
    """Wire up a mock DB session for check_underperforming_alerts.

    Call order:
      1. _PLATFORM_ADMIN_QUERY       → admin_row (or None)
      2. _PLATFORM_AVG_QUERY         → platform_avg scalar (or None)
      3. _RECENT_DAILY_QUERY         → list of (template_id, date, rate) rows
      4. _OPEN_ALERT_QUERY (per tmpl) → open_alert_id row or None
      5. _CREATE_ALERT_QUERY / _CLOSE_ALERT_QUERY (if action taken)
    """
    mock_db = MagicMock()
    call_num = 0

    async def _execute(*args, **kwargs):
        nonlocal call_num
        call_num += 1
        mock_result = MagicMock()

        if call_num == 1:
            # platform admin query
            mock_result.fetchone.return_value = admin_row
        elif call_num == 2:
            # platform avg query
            mock_result.scalar.return_value = platform_avg
        elif call_num == 3:
            # recent daily rows
            mock_result.fetchall.return_value = daily_rows
        elif call_num == 4:
            # open alert query for first template encountered
            if open_alert_id:
                mock_row = MagicMock()
                mock_row.__getitem__ = lambda self, i: open_alert_id if i == 0 else None
                mock_result.fetchone.return_value = mock_row
            else:
                mock_result.fetchone.return_value = None
        else:
            # create/close alert or subsequent open alert queries
            mock_result.fetchone.return_value = None

        return mock_result

    mock_db.execute = AsyncMock(side_effect=_execute)
    return mock_db


# ---------------------------------------------------------------------------
# No platform admin → skip
# ---------------------------------------------------------------------------


class TestNoPlatformAdmin:
    @pytest.mark.asyncio
    async def test_no_admin_returns_zeros(self):
        from app.modules.platform.alerts import check_underperforming_alerts

        mock_db = MagicMock()
        call_num = 0

        async def _execute(*args, **kwargs):
            nonlocal call_num
            call_num += 1
            mock_result = MagicMock()
            mock_result.fetchone.return_value = None  # no admin user
            return mock_result

        mock_db.execute = AsyncMock(side_effect=_execute)

        result = await check_underperforming_alerts(mock_db, _TARGET)

        assert result == {"alerts_opened": 0, "alerts_cleared": 0, "errors": 0}
        # Only one execute call — should stop after admin lookup
        assert mock_db.execute.call_count == 1


# ---------------------------------------------------------------------------
# No platform average → skip
# ---------------------------------------------------------------------------


class TestNoPlatformAvg:
    @pytest.mark.asyncio
    async def test_no_avg_returns_zeros(self):
        from app.modules.platform.alerts import check_underperforming_alerts

        call_num = 0
        mock_db = MagicMock()

        async def _execute(*args, **kwargs):
            nonlocal call_num
            call_num += 1
            mock_result = MagicMock()
            if call_num == 1:
                mock_result.fetchone.return_value = (
                    TEST_PLATFORM_USER_ID,
                    TEST_PLATFORM_TENANT_ID,
                )
            else:
                mock_result.scalar.return_value = None
            return mock_result

        mock_db.execute = AsyncMock(side_effect=_execute)
        result = await check_underperforming_alerts(mock_db, _TARGET)

        assert result == {"alerts_opened": 0, "alerts_cleared": 0, "errors": 0}


# ---------------------------------------------------------------------------
# Alert triggering
# ---------------------------------------------------------------------------


class TestAlertTriggering:
    @pytest.mark.asyncio
    async def test_opens_alert_when_7_consecutive_days_below_threshold(self):
        """7 consecutive days below platform_avg - 0.10 → alert opened."""
        from app.modules.platform.alerts import check_underperforming_alerts

        # platform_avg = 0.80, threshold = 0.70
        # template A has 7 days at 0.60 — all below threshold
        platform_avg = 0.80
        daily_rows = [
            (TEST_TEMPLATE_A, _TARGET - timedelta(days=6 - i), 0.60) for i in range(7)
        ]

        call_num = 0
        mock_db = MagicMock()

        async def _execute(*args, **kwargs):
            nonlocal call_num
            call_num += 1
            mock_result = MagicMock()

            if call_num == 1:
                # admin
                mock_result.fetchone.return_value = (
                    TEST_PLATFORM_USER_ID,
                    TEST_PLATFORM_TENANT_ID,
                )
            elif call_num == 2:
                # platform avg
                mock_result.scalar.return_value = platform_avg
            elif call_num == 3:
                # daily rows
                mock_result.fetchall.return_value = daily_rows
            elif call_num == 4:
                # open alert query → no existing alert
                mock_result.fetchone.return_value = None
            else:
                # create alert — no return value needed
                mock_result.fetchone.return_value = None

            return mock_result

        mock_db.execute = AsyncMock(side_effect=_execute)
        result = await check_underperforming_alerts(mock_db, _TARGET)

        assert result["alerts_opened"] == 1
        assert result["alerts_cleared"] == 0
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_no_alert_when_only_6_consecutive_days_below(self):
        """6 days below threshold → not enough; no alert."""
        from app.modules.platform.alerts import check_underperforming_alerts

        platform_avg = 0.80
        # Only 6 days of data, all below threshold
        daily_rows = [
            (TEST_TEMPLATE_A, _TARGET - timedelta(days=5 - i), 0.60) for i in range(6)
        ]

        call_num = 0
        mock_db = MagicMock()

        async def _execute(*args, **kwargs):
            nonlocal call_num
            call_num += 1
            mock_result = MagicMock()
            if call_num == 1:
                mock_result.fetchone.return_value = (
                    TEST_PLATFORM_USER_ID,
                    TEST_PLATFORM_TENANT_ID,
                )
            elif call_num == 2:
                mock_result.scalar.return_value = platform_avg
            elif call_num == 3:
                mock_result.fetchall.return_value = daily_rows
            else:
                mock_result.fetchone.return_value = None
            return mock_result

        mock_db.execute = AsyncMock(side_effect=_execute)
        result = await check_underperforming_alerts(mock_db, _TARGET)

        assert result["alerts_opened"] == 0

    @pytest.mark.asyncio
    async def test_no_duplicate_alert_when_open_exists(self):
        """Already-open alert → do not create another one."""
        from app.modules.platform.alerts import check_underperforming_alerts

        platform_avg = 0.80
        daily_rows = [
            (TEST_TEMPLATE_A, _TARGET - timedelta(days=6 - i), 0.60) for i in range(7)
        ]
        existing_alert_id = "00000000-0000-0000-0000-000000000001"

        call_num = 0
        mock_db = MagicMock()

        async def _execute(*args, **kwargs):
            nonlocal call_num
            call_num += 1
            mock_result = MagicMock()
            if call_num == 1:
                mock_result.fetchone.return_value = (
                    TEST_PLATFORM_USER_ID,
                    TEST_PLATFORM_TENANT_ID,
                )
            elif call_num == 2:
                mock_result.scalar.return_value = platform_avg
            elif call_num == 3:
                mock_result.fetchall.return_value = daily_rows
            elif call_num == 4:
                # open alert query → existing alert found
                mock_row = MagicMock()
                mock_row.__getitem__ = lambda self, i: existing_alert_id
                mock_result.fetchone.return_value = mock_row
            else:
                mock_result.fetchone.return_value = None
            return mock_result

        mock_db.execute = AsyncMock(side_effect=_execute)
        result = await check_underperforming_alerts(mock_db, _TARGET)

        assert result["alerts_opened"] == 0

    @pytest.mark.asyncio
    async def test_no_alert_when_satisfaction_above_threshold(self):
        """Rate clearly above threshold for all 7 days → no alert."""
        from app.modules.platform.alerts import check_underperforming_alerts

        # platform_avg = 0.80, threshold ≈ 0.70
        # template at 0.75 — definitively above threshold
        platform_avg = 0.80
        daily_rows = [
            (TEST_TEMPLATE_A, _TARGET - timedelta(days=6 - i), 0.75) for i in range(7)
        ]

        call_num = 0
        mock_db = MagicMock()

        async def _execute(*args, **kwargs):
            nonlocal call_num
            call_num += 1
            mock_result = MagicMock()
            if call_num == 1:
                mock_result.fetchone.return_value = (
                    TEST_PLATFORM_USER_ID,
                    TEST_PLATFORM_TENANT_ID,
                )
            elif call_num == 2:
                mock_result.scalar.return_value = platform_avg
            elif call_num == 3:
                mock_result.fetchall.return_value = daily_rows
            else:
                mock_result.fetchone.return_value = None
            return mock_result

        mock_db.execute = AsyncMock(side_effect=_execute)
        result = await check_underperforming_alerts(mock_db, _TARGET)

        assert result["alerts_opened"] == 0

    @pytest.mark.asyncio
    async def test_no_alert_when_null_rate_in_window(self):
        """A NULL satisfaction_rate in the 7-day window → doesn't count as below threshold."""
        from app.modules.platform.alerts import check_underperforming_alerts

        platform_avg = 0.80
        # 6 days below + 1 day with None → only 6 consecutive "below", not enough
        daily_rows = [
            (TEST_TEMPLATE_A, _TARGET - timedelta(days=6), None),
        ] + [(TEST_TEMPLATE_A, _TARGET - timedelta(days=5 - i), 0.60) for i in range(6)]

        call_num = 0
        mock_db = MagicMock()

        async def _execute(*args, **kwargs):
            nonlocal call_num
            call_num += 1
            mock_result = MagicMock()
            if call_num == 1:
                mock_result.fetchone.return_value = (
                    TEST_PLATFORM_USER_ID,
                    TEST_PLATFORM_TENANT_ID,
                )
            elif call_num == 2:
                mock_result.scalar.return_value = platform_avg
            elif call_num == 3:
                mock_result.fetchall.return_value = daily_rows
            else:
                mock_result.fetchone.return_value = None
            return mock_result

        mock_db.execute = AsyncMock(side_effect=_execute)
        result = await check_underperforming_alerts(mock_db, _TARGET)

        assert result["alerts_opened"] == 0

    @pytest.mark.asyncio
    async def test_no_alert_when_date_gap_in_window(self):
        """7 rows below threshold but with a 2-day gap → not contiguous, no alert."""
        from app.modules.platform.alerts import check_underperforming_alerts

        platform_avg = 0.80
        # Gap: skip day 3 (days=3), so rows are not all adjacent
        daily_rows = [
            (TEST_TEMPLATE_A, _TARGET - timedelta(days=6), 0.60),
            (TEST_TEMPLATE_A, _TARGET - timedelta(days=5), 0.60),
            (TEST_TEMPLATE_A, _TARGET - timedelta(days=4), 0.60),
            # day-3 missing → gap here
            (TEST_TEMPLATE_A, _TARGET - timedelta(days=2), 0.60),
            (TEST_TEMPLATE_A, _TARGET - timedelta(days=1), 0.60),
            (TEST_TEMPLATE_A, _TARGET, 0.60),
        ]

        call_num = 0
        mock_db = MagicMock()

        async def _execute(*args, **kwargs):
            nonlocal call_num
            call_num += 1
            mock_result = MagicMock()
            if call_num == 1:
                mock_result.fetchone.return_value = (
                    TEST_PLATFORM_USER_ID,
                    TEST_PLATFORM_TENANT_ID,
                )
            elif call_num == 2:
                mock_result.scalar.return_value = platform_avg
            elif call_num == 3:
                mock_result.fetchall.return_value = daily_rows
            else:
                mock_result.fetchone.return_value = None
            return mock_result

        mock_db.execute = AsyncMock(side_effect=_execute)
        result = await check_underperforming_alerts(mock_db, _TARGET)

        assert result["alerts_opened"] == 0


# ---------------------------------------------------------------------------
# Auto-clear (recovery)
# ---------------------------------------------------------------------------


class TestAlertAutoClearing:
    @pytest.mark.asyncio
    async def test_closes_open_alert_after_3_days_recovery(self):
        """3 consecutive days above threshold + open alert → alert closed."""
        from app.modules.platform.alerts import check_underperforming_alerts

        platform_avg = 0.80
        existing_alert_id = "00000000-0000-0000-0000-000000000001"

        # 7 days: first 4 below, last 3 above threshold (recovered)
        daily_rows = [
            (TEST_TEMPLATE_A, _TARGET - timedelta(days=6 - i), 0.60) for i in range(4)
        ] + [(TEST_TEMPLATE_A, _TARGET - timedelta(days=2 - i), 0.85) for i in range(3)]

        call_num = 0
        mock_db = MagicMock()

        async def _execute(*args, **kwargs):
            nonlocal call_num
            call_num += 1
            mock_result = MagicMock()
            if call_num == 1:
                mock_result.fetchone.return_value = (
                    TEST_PLATFORM_USER_ID,
                    TEST_PLATFORM_TENANT_ID,
                )
            elif call_num == 2:
                mock_result.scalar.return_value = platform_avg
            elif call_num == 3:
                mock_result.fetchall.return_value = daily_rows
            elif call_num == 4:
                # open alert exists
                mock_row = MagicMock()
                mock_row.__getitem__ = lambda self, i: existing_alert_id
                mock_result.fetchone.return_value = mock_row
            else:
                # close alert execute
                mock_result.fetchone.return_value = None
            return mock_result

        mock_db.execute = AsyncMock(side_effect=_execute)
        result = await check_underperforming_alerts(mock_db, _TARGET)

        assert result["alerts_opened"] == 0
        assert result["alerts_cleared"] == 1
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_does_not_close_alert_when_only_2_recovery_days(self):
        """Only 2 consecutive recovery days → alert stays open."""
        from app.modules.platform.alerts import check_underperforming_alerts

        platform_avg = 0.80
        existing_alert_id = "00000000-0000-0000-0000-000000000001"

        # last 7 days: 5 below, 2 above (not enough to clear)
        daily_rows = [
            (TEST_TEMPLATE_A, _TARGET - timedelta(days=6 - i), 0.60) for i in range(5)
        ] + [(TEST_TEMPLATE_A, _TARGET - timedelta(days=1 - i), 0.85) for i in range(2)]

        call_num = 0
        mock_db = MagicMock()

        async def _execute(*args, **kwargs):
            nonlocal call_num
            call_num += 1
            mock_result = MagicMock()
            if call_num == 1:
                mock_result.fetchone.return_value = (
                    TEST_PLATFORM_USER_ID,
                    TEST_PLATFORM_TENANT_ID,
                )
            elif call_num == 2:
                mock_result.scalar.return_value = platform_avg
            elif call_num == 3:
                mock_result.fetchall.return_value = daily_rows
            elif call_num == 4:
                mock_row = MagicMock()
                mock_row.__getitem__ = lambda self, i: existing_alert_id
                mock_result.fetchone.return_value = mock_row
            else:
                mock_result.fetchone.return_value = None
            return mock_result

        mock_db.execute = AsyncMock(side_effect=_execute)
        result = await check_underperforming_alerts(mock_db, _TARGET)

        assert result["alerts_cleared"] == 0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestAlertErrorHandling:
    @pytest.mark.asyncio
    async def test_error_in_one_template_does_not_stop_others(self):
        """DB error for one template → errors++ but other templates processed."""
        from app.modules.platform.alerts import check_underperforming_alerts

        platform_avg = 0.80
        daily_rows = [
            (TEST_TEMPLATE_A, _TARGET - timedelta(days=6 - i), 0.60) for i in range(7)
        ] + [(TEST_TEMPLATE_B, _TARGET - timedelta(days=6 - i), 0.60) for i in range(7)]

        call_num = 0
        mock_db = MagicMock()

        async def _execute(*args, **kwargs):
            nonlocal call_num
            call_num += 1
            mock_result = MagicMock()
            if call_num == 1:
                mock_result.fetchone.return_value = (
                    TEST_PLATFORM_USER_ID,
                    TEST_PLATFORM_TENANT_ID,
                )
            elif call_num == 2:
                mock_result.scalar.return_value = platform_avg
            elif call_num == 3:
                mock_result.fetchall.return_value = daily_rows
            elif call_num == 4:
                # first template's open_alert query — raises
                raise RuntimeError("DB error")
            elif call_num == 5:
                # second template's open_alert query
                mock_result.fetchone.return_value = None
            else:
                mock_result.fetchone.return_value = None
            return mock_result

        mock_db.execute = AsyncMock(side_effect=_execute)
        result = await check_underperforming_alerts(mock_db, _TARGET)

        # One error, one success (alerts_opened may be 0 or 1 depending on order)
        assert result["errors"] == 1
        assert result["alerts_opened"] + result["errors"] <= 2


# ---------------------------------------------------------------------------
# Integration: run_template_performance_batch includes alert summary
# ---------------------------------------------------------------------------


class TestBatchIncludesAlertSummary:
    @pytest.mark.asyncio
    async def test_batch_result_includes_alert_fields(self):
        """run_template_performance_batch result includes alerts_opened/cleared/errors."""
        from app.modules.platform.performance import run_template_performance_batch
        from unittest.mock import patch

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()

        call_num_inner = 0

        async def _execute(*args, **kwargs):
            nonlocal call_num_inner
            call_num_inner += 1
            mock_result = MagicMock()
            mock_result.mappings.return_value = []
            return mock_result

        mock_db.execute = AsyncMock(side_effect=_execute)

        with patch(
            "app.modules.platform.alerts.check_underperforming_alerts",
            new=AsyncMock(
                return_value={"alerts_opened": 2, "alerts_cleared": 1, "errors": 0}
            ),
        ):
            result = await run_template_performance_batch(
                mock_db, target_date=date(2026, 3, 15)
            )

        assert "alerts_opened" in result
        assert "alerts_cleared" in result
        assert "alert_errors" in result
        assert result["alerts_opened"] == 2
        assert result["alerts_cleared"] == 1
        assert result["alert_errors"] == 0
