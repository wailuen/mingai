"""
Unit tests for TA-017: Credential expiry monitoring batch job.

Tier 1: Fast, isolated.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


TENANT_ID = str(uuid.uuid4())
ADMIN_ID = str(uuid.uuid4())
INTEGRATION_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# _extract_expiry pure function tests
# ---------------------------------------------------------------------------


class TestExtractExpiry:
    def setup_method(self):
        from app.modules.documents.credential_expiry_job import _extract_expiry

        self._fn = _extract_expiry

    def _make(self, provider: str, config: dict) -> dict:
        return {"id": INTEGRATION_ID, "provider": provider, "config": config}

    def test_sharepoint_reads_expiry_date(self):
        future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        result = self._fn(self._make("sharepoint", {"expiry_date": future}))
        assert result is not None
        assert result > datetime.now(timezone.utc)

    def test_google_drive_reads_token_expires_at(self):
        future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        result = self._fn(self._make("google_drive", {"token_expires_at": future}))
        assert result is not None

    def test_returns_none_when_no_expiry_field(self):
        result = self._fn(self._make("sharepoint", {"credential_ref": "vault://..."}))
        assert result is None

    def test_returns_none_on_invalid_date_string(self):
        result = self._fn(self._make("sharepoint", {"expiry_date": "not-a-date"}))
        assert result is None

    def test_naive_datetime_gets_utc_tzinfo(self):
        naive = "2030-01-01T00:00:00"  # no tz
        result = self._fn(self._make("sharepoint", {"expiry_date": naive}))
        assert result is not None
        assert result.tzinfo is not None

    def test_already_expired_is_in_past(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        result = self._fn(self._make("sharepoint", {"expiry_date": past}))
        assert result is not None
        assert result < datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# _seconds_until_next_run pure function tests
# ---------------------------------------------------------------------------


class TestSecondsUntilNextRun:
    def setup_method(self):
        from app.modules.documents.credential_expiry_job import _seconds_until_next_run

        self._fn = _seconds_until_next_run

    def test_always_positive(self):
        assert self._fn() > 0

    def test_less_than_25_hours(self):
        assert self._fn() <= 25 * 3600


# ---------------------------------------------------------------------------
# run_credential_expiry_job integration-style unit tests
# ---------------------------------------------------------------------------


class TestRunCredentialExpiryJob:
    @pytest.mark.asyncio
    async def test_job_skips_tenant_with_no_integrations(self):
        """Tenants with no integrations produce zero stats."""
        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()

        async def _execute(*args, **kwargs):
            result = MagicMock()
            sql = str(args[0]) if args else ""
            if "FROM tenants" in sql:
                result.fetchall.return_value = [(uuid.UUID(TENANT_ID),)]
            elif "FROM integrations" in sql:
                result.fetchall.return_value = []
            elif "FROM users" in sql:
                result.fetchall.return_value = []
            else:
                result.fetchall.return_value = []
            return result

        mock_db.execute = AsyncMock(side_effect=_execute)

        with patch(
            "app.modules.documents.credential_expiry_job.async_session_factory",
            return_value=mock_db,
        ):
            from app.modules.documents.credential_expiry_job import (
                run_credential_expiry_job,
            )

            summary = await run_credential_expiry_job()

        assert TENANT_ID in summary
        assert summary[TENANT_ID]["checked"] == 0

    @pytest.mark.asyncio
    async def test_job_handles_tenant_failure_gracefully(self):
        """Exception in one tenant does not abort the whole job."""
        # First factory call: returns tenant list successfully
        # Subsequent calls (inside _process_tenant): raises immediately
        first_db = MagicMock()
        first_db.__aenter__ = AsyncMock(return_value=first_db)
        first_db.__aexit__ = AsyncMock(return_value=False)

        async def _first_execute(*args, **kwargs):
            result = MagicMock()
            sql = str(args[0]) if args else ""
            if "FROM tenants" in sql:
                result.fetchall.return_value = [(uuid.UUID(TENANT_ID),)]
            else:
                result.fetchall.return_value = []
            return result

        first_db.execute = AsyncMock(side_effect=_first_execute)

        failing_db = MagicMock()
        failing_db.__aenter__ = AsyncMock(return_value=failing_db)
        failing_db.__aexit__ = AsyncMock(return_value=False)
        failing_db.execute = AsyncMock(side_effect=RuntimeError("DB error"))

        call_count = [0]

        def _factory():
            call_count[0] += 1
            return first_db if call_count[0] == 1 else failing_db

        with patch(
            "app.modules.documents.credential_expiry_job.async_session_factory",
            side_effect=_factory,
        ):
            from app.modules.documents.credential_expiry_job import (
                run_credential_expiry_job,
            )

            summary = await run_credential_expiry_job()

        # Job completes, tenant stats default to zeros
        assert TENANT_ID in summary
        assert summary[TENANT_ID]["checked"] == 0


# ---------------------------------------------------------------------------
# _process_tenant unit tests (logic-only, no real DB)
# ---------------------------------------------------------------------------


class TestProcessTenant:
    def _make_integration(self, provider: str, expiry_offset_days: int) -> dict:
        expiry = (
            datetime.now(timezone.utc) + timedelta(days=expiry_offset_days)
        ).isoformat()
        key = "expiry_date" if provider == "sharepoint" else "token_expires_at"
        return {
            "id": INTEGRATION_ID,
            "provider": provider,
            "config": {key: expiry, "name": "Test Integration"},
        }

    def _build_mock_db(self, integrations: list, admin_ids: list, existing_notif=False):
        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()

        async def _execute(*args, **kwargs):
            result = MagicMock()
            sql = str(args[0]) if args else ""
            if "FROM integrations" in sql and "SELECT" in sql.upper():
                result.fetchall.return_value = [
                    (
                        uuid.UUID(itg["id"]),
                        itg["provider"],
                        itg["config"],
                    )
                    for itg in integrations
                ]
            elif "FROM users" in sql:
                result.fetchall.return_value = [(uuid.UUID(aid),) for aid in admin_ids]
            elif "FROM notifications" in sql:
                if existing_notif:
                    result.fetchone.return_value = (uuid.uuid4(),)
                else:
                    result.fetchone.return_value = None
            else:
                result.fetchone.return_value = None
                result.fetchall.return_value = []
                result.rowcount = 1
            return result

        mock_db.execute = AsyncMock(side_effect=_execute)
        return mock_db

    @pytest.mark.asyncio
    async def test_p2_warn_for_30_day_expiry(self):
        """Integration expiring in 20 days triggers P2 (warn)."""
        mock_db = self._build_mock_db(
            integrations=[self._make_integration("sharepoint", 20)],
            admin_ids=[ADMIN_ID],
        )
        with patch(
            "app.modules.documents.credential_expiry_job.async_session_factory",
            return_value=mock_db,
        ):
            from app.modules.documents.credential_expiry_job import _process_tenant

            stats = await _process_tenant(TENANT_ID)

        assert stats["warned"] == 1
        assert stats["critical"] == 0

    @pytest.mark.asyncio
    async def test_p1_critical_for_7_day_expiry(self):
        """Integration expiring in 5 days triggers P1 (critical) + issue."""
        mock_db = self._build_mock_db(
            integrations=[self._make_integration("sharepoint", 5)],
            admin_ids=[ADMIN_ID],
        )
        with patch(
            "app.modules.documents.credential_expiry_job.async_session_factory",
            return_value=mock_db,
        ):
            from app.modules.documents.credential_expiry_job import _process_tenant

            stats = await _process_tenant(TENANT_ID)

        assert stats["critical"] == 1
        assert stats["warned"] == 0

    @pytest.mark.asyncio
    async def test_no_action_for_far_future_expiry(self):
        """Integration expiring in 60 days does not trigger anything."""
        mock_db = self._build_mock_db(
            integrations=[self._make_integration("sharepoint", 60)],
            admin_ids=[ADMIN_ID],
        )
        with patch(
            "app.modules.documents.credential_expiry_job.async_session_factory",
            return_value=mock_db,
        ):
            from app.modules.documents.credential_expiry_job import _process_tenant

            stats = await _process_tenant(TENANT_ID)

        assert stats["warned"] == 0
        assert stats["critical"] == 0

    @pytest.mark.asyncio
    async def test_duplicate_prevention_skips_existing_notification(self):
        """If an unread notification already exists, no new one is created."""
        mock_db = self._build_mock_db(
            integrations=[self._make_integration("sharepoint", 5)],
            admin_ids=[ADMIN_ID],
            existing_notif=True,
        )
        with patch(
            "app.modules.documents.credential_expiry_job.async_session_factory",
            return_value=mock_db,
        ):
            from app.modules.documents.credential_expiry_job import _process_tenant

            stats = await _process_tenant(TENANT_ID)

        # No new notifications/issues because duplicate was detected
        assert stats["critical"] == 0
        assert stats["warned"] == 0

    @pytest.mark.asyncio
    async def test_google_drive_expiry_detected(self):
        """Google Drive token expiry is also detected."""
        mock_db = self._build_mock_db(
            integrations=[self._make_integration("google_drive", 3)],
            admin_ids=[ADMIN_ID],
        )
        with patch(
            "app.modules.documents.credential_expiry_job.async_session_factory",
            return_value=mock_db,
        ):
            from app.modules.documents.credential_expiry_job import _process_tenant

            stats = await _process_tenant(TENANT_ID)

        assert stats["critical"] == 1

    @pytest.mark.asyncio
    async def test_no_action_when_no_admin_users(self):
        """If tenant has no active admins, no notifications are sent."""
        mock_db = self._build_mock_db(
            integrations=[self._make_integration("sharepoint", 5)],
            admin_ids=[],
        )
        with patch(
            "app.modules.documents.credential_expiry_job.async_session_factory",
            return_value=mock_db,
        ):
            from app.modules.documents.credential_expiry_job import _process_tenant

            stats = await _process_tenant(TENANT_ID)

        assert stats["warned"] == 0
        assert stats["critical"] == 0

    @pytest.mark.asyncio
    async def test_already_expired_counts_as_critical(self):
        """Integration that already expired triggers P1 critical."""
        mock_db = self._build_mock_db(
            integrations=[self._make_integration("sharepoint", -1)],
            admin_ids=[ADMIN_ID],
        )
        with patch(
            "app.modules.documents.credential_expiry_job.async_session_factory",
            return_value=mock_db,
        ):
            from app.modules.documents.credential_expiry_job import _process_tenant

            stats = await _process_tenant(TENANT_ID)

        assert stats["critical"] == 1
