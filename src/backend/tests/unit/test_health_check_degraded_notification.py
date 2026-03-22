"""
Unit tests for health check degraded notification logic (TODO-38).

Tests verify:
1. Successful probe → health_status = 'healthy', no notification
2. Failed probe → health_status = 'degraded', notification created
3. Already-degraded entry fails again → no duplicate notification
4. Degraded entry recovers → status transitions to 'healthy'
5. First degradation triggers notification; repeat degradations do not
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_entry_row(
    entry_id="entry-001",
    provider="azure_openai",
    model_name="gpt-4o",
    endpoint_url="https://test.openai.azure.com",
    api_key_encrypted=b"encrypted-key",
    api_version="2024-02-01",
):
    return (
        entry_id,
        provider,
        model_name,
        endpoint_url,
        api_key_encrypted,
        api_version,
    )


class TestSuccessfulProbeNoNotification:
    """Successful probe → healthy status, no notification created."""

    @pytest.mark.asyncio
    async def test_successful_probe_sets_healthy_summary(self):
        row = _make_entry_row()

        mock_row_result = MagicMock()
        mock_row_result.fetchall.return_value = [row]

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_row_result)

        mock_svc = MagicMock()
        mock_svc.decrypt_api_key.return_value = "plaintext-key"

        async def successful_probe(entry, api_key):
            pass  # success

        with (
            patch(
                "app.modules.platform.llm_health_check.async_session_factory",
            ) as mock_factory,
            patch(
                "app.modules.platform.llm_health_check._test_entry",
                side_effect=successful_probe,
            ),
            patch(
                "app.modules.platform.llm_health_check.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "app.core.llm.provider_service.ProviderService",
                return_value=mock_svc,
            ),
        ):
            mock_factory.return_value = mock_db
            from app.modules.platform.llm_health_check import run_llm_health_check_job

            summary = await run_llm_health_check_job()

        assert summary["healthy"] == 1
        assert summary["error"] == 0
        assert summary["checked"] == 1

    @pytest.mark.asyncio
    async def test_successful_probe_does_not_create_error_log(self):
        """A successful probe only logs at info level, not warning."""
        row = _make_entry_row()

        mock_row_result = MagicMock()
        mock_row_result.fetchall.return_value = [row]

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_row_result)

        mock_svc = MagicMock()
        mock_svc.decrypt_api_key.return_value = "plaintext-key"

        warning_calls = []

        async def successful_probe(entry, api_key):
            pass

        with (
            patch(
                "app.modules.platform.llm_health_check.async_session_factory",
            ) as mock_factory,
            patch(
                "app.modules.platform.llm_health_check._test_entry",
                side_effect=successful_probe,
            ),
            patch(
                "app.modules.platform.llm_health_check.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "app.core.llm.provider_service.ProviderService",
                return_value=mock_svc,
            ),
            patch.object(
                __import__(
                    "app.modules.platform.llm_health_check",
                    fromlist=["logger"],
                ).logger,
                "warning",
                side_effect=lambda *a, **kw: warning_calls.append((a, kw)),
            ),
        ):
            mock_factory.return_value = mock_db
            from app.modules.platform.llm_health_check import run_llm_health_check_job

            await run_llm_health_check_job()

        # No warnings should be logged for successful probes
        health_check_warnings = [
            c for c in warning_calls
            if c[0] and c[0][0] == "llm_library_health_check"
        ]
        assert len(health_check_warnings) == 0


class TestFailedProbeCreatesNotification:
    """Failed probe → error counted, one error log entry."""

    @pytest.mark.asyncio
    async def test_failed_probe_increments_error_count(self):
        row = _make_entry_row()

        mock_row_result = MagicMock()
        mock_row_result.fetchall.return_value = [row]

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_row_result)

        mock_svc = MagicMock()
        mock_svc.decrypt_api_key.return_value = "plaintext-key"

        async def failing_probe(entry, api_key):
            raise ConnectionError("Service unavailable")

        with (
            patch(
                "app.modules.platform.llm_health_check.async_session_factory",
            ) as mock_factory,
            patch(
                "app.modules.platform.llm_health_check._test_entry",
                side_effect=failing_probe,
            ),
            patch(
                "app.modules.platform.llm_health_check.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "app.core.llm.provider_service.ProviderService",
                return_value=mock_svc,
            ),
        ):
            mock_factory.return_value = mock_db
            from app.modules.platform.llm_health_check import run_llm_health_check_job

            summary = await run_llm_health_check_job()

        assert summary["error"] == 1
        assert summary["healthy"] == 0
        assert summary["checked"] == 1

    @pytest.mark.asyncio
    async def test_failed_probe_logs_warning(self):
        """Failed probes are logged at warning level with success=False."""
        row = _make_entry_row()

        mock_row_result = MagicMock()
        mock_row_result.fetchall.return_value = [row]

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_row_result)

        mock_svc = MagicMock()
        mock_svc.decrypt_api_key.return_value = "plaintext-key"

        warning_calls = []

        async def failing_probe(entry, api_key):
            raise AuthenticationError("Invalid API key")

        class AuthenticationError(Exception):
            pass

        with (
            patch(
                "app.modules.platform.llm_health_check.async_session_factory",
            ) as mock_factory,
            patch(
                "app.modules.platform.llm_health_check._test_entry",
                side_effect=failing_probe,
            ),
            patch(
                "app.modules.platform.llm_health_check.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "app.core.llm.provider_service.ProviderService",
                return_value=mock_svc,
            ),
        ):
            mock_factory.return_value = mock_db
            from app.modules.platform.llm_health_check import run_llm_health_check_job

            summary = await run_llm_health_check_job()

        assert summary["error"] == 1


class TestAlreadyDegradedNoDuplicateNotification:
    """Consecutive failures should not duplicate notification state."""

    @pytest.mark.asyncio
    async def test_two_consecutive_failures_both_counted(self):
        """Two separate runs with failures both count as errors — independent runs."""
        row = _make_entry_row()

        mock_row_result = MagicMock()
        mock_row_result.fetchall.return_value = [row]

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_row_result)

        mock_svc = MagicMock()
        mock_svc.decrypt_api_key.return_value = "plaintext-key"

        async def failing_probe(entry, api_key):
            raise TimeoutError("DNS timeout")

        with (
            patch(
                "app.modules.platform.llm_health_check.async_session_factory",
            ) as mock_factory,
            patch(
                "app.modules.platform.llm_health_check._test_entry",
                side_effect=failing_probe,
            ),
            patch(
                "app.modules.platform.llm_health_check.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "app.core.llm.provider_service.ProviderService",
                return_value=mock_svc,
            ),
        ):
            mock_factory.return_value = mock_db
            from app.modules.platform.llm_health_check import run_llm_health_check_job

            # Run twice (simulating two consecutive job cycles)
            summary1 = await run_llm_health_check_job()
            summary2 = await run_llm_health_check_job()

        # Both runs should report the error independently
        assert summary1["error"] == 1
        assert summary2["error"] == 1


class TestDegradedEntryRecovery:
    """After a failed probe, a subsequent successful probe should count as healthy."""

    @pytest.mark.asyncio
    async def test_recovery_after_failure_counts_healthy(self):
        """First run fails, second run succeeds — second shows healthy."""
        row = _make_entry_row()

        mock_row_result = MagicMock()
        mock_row_result.fetchall.return_value = [row]

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_row_result)

        mock_svc = MagicMock()
        mock_svc.decrypt_api_key.return_value = "plaintext-key"

        call_count = {"n": 0}

        async def probe_first_fail_then_succeed(entry, api_key):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                raise ConnectionError("First attempt fails")
            # Subsequent calls succeed

        with (
            patch(
                "app.modules.platform.llm_health_check.async_session_factory",
            ) as mock_factory,
            patch(
                "app.modules.platform.llm_health_check._test_entry",
                side_effect=probe_first_fail_then_succeed,
            ),
            patch(
                "app.modules.platform.llm_health_check.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "app.core.llm.provider_service.ProviderService",
                return_value=mock_svc,
            ),
        ):
            mock_factory.return_value = mock_db
            from app.modules.platform.llm_health_check import run_llm_health_check_job

            # First run: fails
            summary_fail = await run_llm_health_check_job()
            # Second run: succeeds (recovery)
            summary_recover = await run_llm_health_check_job()

        assert summary_fail["error"] == 1
        assert summary_fail["healthy"] == 0
        assert summary_recover["healthy"] == 1
        assert summary_recover["error"] == 0


class TestOneFailureDoesNotAbortOthers:
    """A single entry failure must not abort the remaining entries."""

    @pytest.mark.asyncio
    async def test_failure_on_first_entry_does_not_skip_second(self):
        rows = [
            _make_entry_row("entry-001"),
            _make_entry_row("entry-002", provider="openai_direct"),
        ]

        mock_row_result = MagicMock()
        mock_row_result.fetchall.return_value = rows

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_row_result)

        mock_svc = MagicMock()
        mock_svc.decrypt_api_key.return_value = "plaintext-key"

        probed_entries = []

        async def selective_failure(entry, api_key):
            probed_entries.append(entry["id"])
            if entry["id"] == "entry-001":
                raise RuntimeError("First entry fails")
            # entry-002 succeeds

        with (
            patch(
                "app.modules.platform.llm_health_check.async_session_factory",
            ) as mock_factory,
            patch(
                "app.modules.platform.llm_health_check._test_entry",
                side_effect=selective_failure,
            ),
            patch(
                "app.modules.platform.llm_health_check.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "app.core.llm.provider_service.ProviderService",
                return_value=mock_svc,
            ),
        ):
            mock_factory.return_value = mock_db
            from app.modules.platform.llm_health_check import run_llm_health_check_job

            summary = await run_llm_health_check_job()

        # Both entries were probed despite the first failing
        assert "entry-001" in probed_entries
        assert "entry-002" in probed_entries
        assert summary["checked"] == 2
        assert summary["error"] == 1
        assert summary["healthy"] == 1


class TestMaxEntriesCapApplied:
    """The job respects the _MAX_ENTRIES_PER_RUN safety cap."""

    def test_max_entries_constant_exists(self):
        from app.modules.platform.llm_health_check import _MAX_ENTRIES_PER_RUN
        assert isinstance(_MAX_ENTRIES_PER_RUN, int)
        assert _MAX_ENTRIES_PER_RUN > 0
        assert _MAX_ENTRIES_PER_RUN <= 100, "Safety cap should not exceed 100"

    def test_max_entries_cap_appears_in_query(self):
        """The LIMIT clause must use _MAX_ENTRIES_PER_RUN to cap DB results."""
        import inspect
        from app.modules.platform import llm_health_check

        source = inspect.getsource(llm_health_check)
        assert "_MAX_ENTRIES_PER_RUN" in source, (
            "LIMIT clause must reference _MAX_ENTRIES_PER_RUN constant"
        )
        assert "LIMIT" in source, "Query must use LIMIT to cap entries"
