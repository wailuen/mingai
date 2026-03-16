"""
Unit tests for PA-015: Cost Alert Thresholds.

Coverage:
- POST /platform/tenants/{id}/cost-alerts → 200 with valid payload
- POST → 401 without auth, 403 for tenant_admin
- PATCH /platform/cost-alerts/defaults → 200
- GET /platform/cost-alerts/defaults → 200
- GET /platform/tenants/{id}/cost-alerts → 200 (per-tenant and fallback to global)
- Job: spend above threshold → issue created
- Job: spend below threshold → no issue
- Job: margin below floor → issue created
- Job: duplicate suppression (issue already exists → skip)
- Job: tenant with no config → skip gracefully
- Job: tenant with no cost_summary row → skip gracefully
- Scheduler timing constants

Tier 1: Fast, isolated, uses mocking.
"""
import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_JWT_SECRET = "b" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_PLATFORM_ADMIN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TEST_TENANT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TEST_TARGET_TENANT_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def _make_platform_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": TEST_PLATFORM_ADMIN_ID,
        "tenant_id": TEST_TENANT_ID,
        "roles": ["platform_admin"],
        "scope": "platform",
        "plan": "enterprise",
        "email": "platform@mingai.io",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_tenant_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "tenant-admin-user-id",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": "admin@tenant.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def env_vars():
    env = {
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "JWT_ALGORITHM": TEST_JWT_ALGORITHM,
        "REDIS_URL": "redis://localhost:6379/0",
        "FRONTEND_URL": "http://localhost:3022",
    }
    with patch.dict(os.environ, env, clear=False):
        yield


def _make_mock_db():
    """Return a mock AsyncSession that silently accepts execute/commit calls."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    return mock_db


@pytest.fixture
def client(env_vars):
    from app.core.session import get_async_session
    from app.main import app

    mock_db = _make_mock_db()

    async def _override_session():
        yield mock_db

    app.dependency_overrides[get_async_session] = _override_session
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(get_async_session, None)


@pytest.fixture
def platform_headers():
    return {"Authorization": f"Bearer {_make_platform_token()}"}


@pytest.fixture
def tenant_admin_headers():
    return {"Authorization": f"Bearer {_make_tenant_admin_token()}"}


# Reusable mock config rows
_MOCK_CONFIG = {
    "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
    "tenant_id": TEST_TARGET_TENANT_ID,
    "daily_spend_threshold_usd": 50.0,
    "margin_floor_pct": 20.0,
    "created_at": "2026-03-16T00:00:00",
    "updated_at": "2026-03-16T00:00:00",
}

_MOCK_GLOBAL_CONFIG = {
    "id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
    "tenant_id": None,
    "daily_spend_threshold_usd": 100.0,
    "margin_floor_pct": 15.0,
    "created_at": "2026-03-16T00:00:00",
    "updated_at": "2026-03-16T00:00:00",
}


def _set_cost_alerts_url(tenant_id: str = TEST_TARGET_TENANT_ID) -> str:
    return f"/api/v1/platform/tenants/{tenant_id}/cost-alerts"


_DEFAULT_ALERTS_URL = "/api/v1/platform/cost-alerts/defaults"


# ---------------------------------------------------------------------------
# Tests: Route auth/RBAC
# ---------------------------------------------------------------------------


class TestCostAlertsAuth:
    def test_post_tenant_alerts_requires_auth(self, client):
        """401 when no Authorization header."""
        resp = client.post(
            _set_cost_alerts_url(),
            json={"daily_spend_threshold_usd": 50.0},
        )
        assert resp.status_code == 401

    def test_post_tenant_alerts_requires_platform_admin(
        self, client, tenant_admin_headers
    ):
        """403 when caller is tenant_admin."""
        resp = client.post(
            _set_cost_alerts_url(),
            json={"daily_spend_threshold_usd": 50.0},
            headers=tenant_admin_headers,
        )
        assert resp.status_code == 403

    def test_patch_defaults_requires_platform_admin(self, client, tenant_admin_headers):
        """403 when caller is tenant_admin."""
        resp = client.patch(
            _DEFAULT_ALERTS_URL,
            json={"daily_spend_threshold_usd": 100.0},
            headers=tenant_admin_headers,
        )
        assert resp.status_code == 403

    def test_get_defaults_requires_auth(self, client):
        """401 when no Authorization header."""
        resp = client.get(_DEFAULT_ALERTS_URL)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: POST /platform/tenants/{id}/cost-alerts
# ---------------------------------------------------------------------------


class TestSetTenantCostAlerts:
    def test_set_tenant_alerts_200(self, client, platform_headers):
        """200 with valid payload and correct response shape."""
        with (
            patch(
                "app.modules.platform.cost_alerts.get_tenant_exists_db",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.modules.platform.cost_alerts.upsert_cost_alert_config_db",
                new_callable=AsyncMock,
                return_value=_MOCK_CONFIG,
            ),
            patch(
                "app.modules.platform.cost_alerts.write_audit_log_db",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                _set_cost_alerts_url(),
                json={"daily_spend_threshold_usd": 50.0, "margin_floor_pct": 20.0},
                headers=platform_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["daily_spend_threshold_usd"] == 50.0
        assert data["margin_floor_pct"] == 20.0
        assert data["is_global_default"] is False
        assert data["tenant_id"] == TEST_TARGET_TENANT_ID

    def test_set_tenant_alerts_404_unknown_tenant(self, client, platform_headers):
        """404 when tenant does not exist."""
        with patch(
            "app.modules.platform.cost_alerts.get_tenant_exists_db",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post(
                _set_cost_alerts_url(),
                json={"daily_spend_threshold_usd": 50.0},
                headers=platform_headers,
            )
        assert resp.status_code == 404

    def test_set_tenant_alerts_null_thresholds_accepted(self, client, platform_headers):
        """NULL thresholds are valid (disables the alert)."""
        null_config = {
            **_MOCK_CONFIG,
            "daily_spend_threshold_usd": None,
            "margin_floor_pct": None,
        }
        with (
            patch(
                "app.modules.platform.cost_alerts.get_tenant_exists_db",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.modules.platform.cost_alerts.upsert_cost_alert_config_db",
                new_callable=AsyncMock,
                return_value=null_config,
            ),
            patch(
                "app.modules.platform.cost_alerts.write_audit_log_db",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                _set_cost_alerts_url(),
                json={"daily_spend_threshold_usd": None, "margin_floor_pct": None},
                headers=platform_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["daily_spend_threshold_usd"] is None
        assert data["margin_floor_pct"] is None


# ---------------------------------------------------------------------------
# Tests: PATCH /platform/cost-alerts/defaults
# ---------------------------------------------------------------------------


class TestPatchGlobalDefaults:
    def test_patch_defaults_200(self, client, platform_headers):
        """200 with valid payload; is_global_default=True."""
        with (
            patch(
                "app.modules.platform.cost_alerts.upsert_cost_alert_config_db",
                new_callable=AsyncMock,
                return_value=_MOCK_GLOBAL_CONFIG,
            ),
            patch(
                "app.modules.platform.cost_alerts.write_audit_log_db",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.patch(
                _DEFAULT_ALERTS_URL,
                json={"daily_spend_threshold_usd": 100.0, "margin_floor_pct": 15.0},
                headers=platform_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_global_default"] is True
        assert data["tenant_id"] is None
        assert data["daily_spend_threshold_usd"] == 100.0


# ---------------------------------------------------------------------------
# Tests: GET /platform/cost-alerts/defaults
# ---------------------------------------------------------------------------


class TestGetGlobalDefaults:
    def test_get_defaults_200(self, client, platform_headers):
        """200 returns global config."""
        with patch(
            "app.modules.platform.cost_alerts.get_cost_alert_config_db",
            new_callable=AsyncMock,
            return_value=_MOCK_GLOBAL_CONFIG,
        ):
            resp = client.get(_DEFAULT_ALERTS_URL, headers=platform_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_global_default"] is True
        assert data["daily_spend_threshold_usd"] == 100.0

    def test_get_defaults_404_when_not_configured(self, client, platform_headers):
        """404 when no global default has been set."""
        with patch(
            "app.modules.platform.cost_alerts.get_cost_alert_config_db",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(_DEFAULT_ALERTS_URL, headers=platform_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: GET /platform/tenants/{id}/cost-alerts
# ---------------------------------------------------------------------------


class TestGetTenantCostAlerts:
    def test_get_tenant_alerts_returns_per_tenant_config(
        self, client, platform_headers
    ):
        """Returns per-tenant config when it exists."""
        with (
            patch(
                "app.modules.platform.cost_alerts.get_tenant_exists_db",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.modules.platform.cost_alerts.get_cost_alert_config_db",
                new_callable=AsyncMock,
                return_value=_MOCK_CONFIG,
            ),
        ):
            resp = client.get(_set_cost_alerts_url(), headers=platform_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == TEST_TARGET_TENANT_ID
        assert data["is_global_default"] is False

    def test_get_tenant_alerts_falls_back_to_global(self, client, platform_headers):
        """Falls back to global default when no per-tenant config exists."""
        call_count = 0

        async def _side_effect(tenant_id, db):
            nonlocal call_count
            call_count += 1
            # First call (per-tenant) returns None; second call (global) returns config
            if tenant_id is not None:
                return None
            return _MOCK_GLOBAL_CONFIG

        with (
            patch(
                "app.modules.platform.cost_alerts.get_tenant_exists_db",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.modules.platform.cost_alerts.get_cost_alert_config_db",
                side_effect=_side_effect,
            ),
        ):
            resp = client.get(_set_cost_alerts_url(), headers=platform_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_global_default"] is True
        assert data["tenant_id"] is None


# ---------------------------------------------------------------------------
# Tests: Cost alert job evaluation logic
# ---------------------------------------------------------------------------


class TestCostAlertJobEvaluation:
    """Tests for run_cost_alert_job() / _evaluate_tenant() logic."""

    @pytest.mark.asyncio
    async def test_spend_above_threshold_creates_issue(self):
        """Issue and notification created when actual spend > threshold."""
        from app.modules.platform.cost_alert_job import _evaluate_tenant

        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        target_date = date(2026, 3, 15)

        with (
            patch(
                "app.modules.platform.cost_alert_job._get_cost_summary",
                new_callable=AsyncMock,
                return_value={"total_cost_usd": 75.0, "gross_margin_pct": 30.0},
            ),
            patch(
                "app.modules.platform.cost_alert_job._get_alert_config",
                new_callable=AsyncMock,
                return_value={
                    "daily_spend_threshold_usd": 50.0,
                    "margin_floor_pct": None,
                },
            ),
            patch(
                "app.modules.platform.cost_alert_job._get_tenant_name",
                new_callable=AsyncMock,
                return_value="Acme Corp",
            ),
            patch(
                "app.modules.platform.cost_alert_job._issue_already_exists",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.modules.platform.cost_alert_job._create_alert_issue",
                new_callable=AsyncMock,
            ) as mock_create_issue,
            patch(
                "app.modules.platform.cost_alert_job._create_alert_notification",
                new_callable=AsyncMock,
            ) as mock_create_notif,
        ):
            await _evaluate_tenant("tenant-1", target_date, db)

        mock_create_issue.assert_called_once()
        mock_create_notif.assert_called_once()
        # Verify the issue title is spend-related
        call_args = mock_create_issue.call_args
        assert (
            "threshold" in call_args[0][1].lower() or "spend" in call_args[0][1].lower()
        )

    @pytest.mark.asyncio
    async def test_spend_below_threshold_no_issue(self):
        """No issue created when actual spend <= threshold."""
        from app.modules.platform.cost_alert_job import _evaluate_tenant

        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        target_date = date(2026, 3, 15)

        with (
            patch(
                "app.modules.platform.cost_alert_job._get_cost_summary",
                new_callable=AsyncMock,
                return_value={"total_cost_usd": 30.0, "gross_margin_pct": 40.0},
            ),
            patch(
                "app.modules.platform.cost_alert_job._get_alert_config",
                new_callable=AsyncMock,
                return_value={
                    "daily_spend_threshold_usd": 50.0,
                    "margin_floor_pct": None,
                },
            ),
            patch(
                "app.modules.platform.cost_alert_job._get_tenant_name",
                new_callable=AsyncMock,
                return_value="Acme Corp",
            ),
            patch(
                "app.modules.platform.cost_alert_job._create_alert_issue",
                new_callable=AsyncMock,
            ) as mock_create_issue,
        ):
            await _evaluate_tenant("tenant-1", target_date, db)

        mock_create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_margin_below_floor_creates_issue(self):
        """Issue and notification created when actual margin < floor."""
        from app.modules.platform.cost_alert_job import _evaluate_tenant

        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        target_date = date(2026, 3, 15)

        with (
            patch(
                "app.modules.platform.cost_alert_job._get_cost_summary",
                new_callable=AsyncMock,
                return_value={"total_cost_usd": 20.0, "gross_margin_pct": 10.0},
            ),
            patch(
                "app.modules.platform.cost_alert_job._get_alert_config",
                new_callable=AsyncMock,
                return_value={
                    "daily_spend_threshold_usd": None,
                    "margin_floor_pct": 20.0,
                },
            ),
            patch(
                "app.modules.platform.cost_alert_job._get_tenant_name",
                new_callable=AsyncMock,
                return_value="Acme Corp",
            ),
            patch(
                "app.modules.platform.cost_alert_job._issue_already_exists",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.modules.platform.cost_alert_job._create_alert_issue",
                new_callable=AsyncMock,
            ) as mock_create_issue,
            patch(
                "app.modules.platform.cost_alert_job._create_alert_notification",
                new_callable=AsyncMock,
            ) as mock_create_notif,
        ):
            await _evaluate_tenant("tenant-1", target_date, db)

        mock_create_issue.assert_called_once()
        mock_create_notif.assert_called_once()
        # Verify the issue title is margin-related
        call_args = mock_create_issue.call_args
        assert "margin" in call_args[0][1].lower() or "floor" in call_args[0][1].lower()

    @pytest.mark.asyncio
    async def test_duplicate_suppression_skips_existing_issue(self):
        """No issue created when an issue for the same date already exists."""
        from app.modules.platform.cost_alert_job import _evaluate_tenant

        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        target_date = date(2026, 3, 15)

        with (
            patch(
                "app.modules.platform.cost_alert_job._get_cost_summary",
                new_callable=AsyncMock,
                return_value={"total_cost_usd": 75.0, "gross_margin_pct": 30.0},
            ),
            patch(
                "app.modules.platform.cost_alert_job._get_alert_config",
                new_callable=AsyncMock,
                return_value={
                    "daily_spend_threshold_usd": 50.0,
                    "margin_floor_pct": None,
                },
            ),
            patch(
                "app.modules.platform.cost_alert_job._get_tenant_name",
                new_callable=AsyncMock,
                return_value="Acme Corp",
            ),
            patch(
                "app.modules.platform.cost_alert_job._issue_already_exists",
                new_callable=AsyncMock,
                return_value=True,  # Already exists — suppress
            ),
            patch(
                "app.modules.platform.cost_alert_job._create_alert_issue",
                new_callable=AsyncMock,
            ) as mock_create_issue,
        ):
            await _evaluate_tenant("tenant-1", target_date, db)

        mock_create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_config_skips_gracefully(self):
        """No issue created when tenant has no alert config (no thresholds)."""
        from app.modules.platform.cost_alert_job import _evaluate_tenant

        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        target_date = date(2026, 3, 15)

        with (
            patch(
                "app.modules.platform.cost_alert_job._get_cost_summary",
                new_callable=AsyncMock,
                return_value={"total_cost_usd": 200.0, "gross_margin_pct": 5.0},
            ),
            patch(
                "app.modules.platform.cost_alert_job._get_alert_config",
                new_callable=AsyncMock,
                # No thresholds configured
                return_value={
                    "daily_spend_threshold_usd": None,
                    "margin_floor_pct": None,
                },
            ),
            patch(
                "app.modules.platform.cost_alert_job._create_alert_issue",
                new_callable=AsyncMock,
            ) as mock_create_issue,
        ):
            await _evaluate_tenant("tenant-1", target_date, db)

        mock_create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_cost_summary_row_skips_gracefully(self):
        """No issue created when the cost_summary_daily row does not exist for the date."""
        from app.modules.platform.cost_alert_job import _evaluate_tenant

        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        target_date = date(2026, 3, 15)

        with (
            patch(
                "app.modules.platform.cost_alert_job._get_cost_summary",
                new_callable=AsyncMock,
                return_value=None,  # No row for this date
            ),
            patch(
                "app.modules.platform.cost_alert_job._create_alert_issue",
                new_callable=AsyncMock,
            ) as mock_create_issue,
        ):
            await _evaluate_tenant("tenant-1", target_date, db)

        mock_create_issue.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: RLS context — all three SET LOCAL statements in _evaluate_tenant
# ---------------------------------------------------------------------------


class TestEvaluateTenantRLSContext:
    """_evaluate_tenant must set all three RLS context vars for full access."""

    @pytest.mark.asyncio
    async def test_all_three_set_local_statements_issued(self):
        """
        _evaluate_tenant must issue:
          SET LOCAL app.current_scope = 'platform'  (cost_summary_daily, cost_alert_configs)
          SET LOCAL app.user_role = 'platform_admin' (tenants, issue_reports)
          SET LOCAL app.tenant_id = :tid             (notifications RLS)
        """
        from app.modules.platform.cost_alert_job import _evaluate_tenant

        issued_stmts: list[str] = []
        issued_params: list = []

        async def capture_execute(stmt, params=None):
            issued_stmts.append(str(stmt))
            issued_params.append(params or {})
            return AsyncMock()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=capture_execute)
        db.commit = AsyncMock()

        target_date = date(2026, 3, 15)

        with (
            patch(
                "app.modules.platform.cost_alert_job._get_cost_summary",
                new_callable=AsyncMock,
                return_value=None,  # exit early — we only need the SET LOCAL calls
            ),
        ):
            await _evaluate_tenant("tenant-rls-test", target_date, db)

        all_stmts = " ".join(issued_stmts)
        assert (
            "current_scope" in all_stmts and "platform" in all_stmts
        ), "SET LOCAL app.current_scope = 'platform' must be issued"
        assert (
            "user_role" in all_stmts and "platform_admin" in all_stmts
        ), "SET LOCAL app.user_role = 'platform_admin' must be issued"
        # app.tenant_id must appear in the issued SQL statements
        assert any(
            "app.tenant_id" in s for s in issued_stmts
        ), "SET LOCAL app.tenant_id must be issued"
        # The correct tenant_id value must appear in the params passed to that call
        assert any(
            "tenant-rls-test" in str(p) for p in issued_params
        ), "SET LOCAL app.tenant_id must carry the correct tenant_id value"


# ---------------------------------------------------------------------------
# Tests: Scheduler timing constants
# ---------------------------------------------------------------------------


class TestSchedulerConstants:
    def test_schedule_hour_is_4_utc(self):
        from app.modules.platform.cost_alert_job import _SCHEDULE_HOUR_UTC

        assert _SCHEDULE_HOUR_UTC == 4

    def test_schedule_minute_is_0(self):
        from app.modules.platform.cost_alert_job import _SCHEDULE_MINUTE_UTC

        assert _SCHEDULE_MINUTE_UTC == 0

    def test_seconds_until_next_run_minimum_60(self):
        """_seconds_until_next_run always returns at least 60 seconds."""
        from app.modules.platform.cost_alert_job import _seconds_until_next_run

        secs = _seconds_until_next_run()
        assert secs >= 60.0

    def test_seconds_until_next_run_max_one_day(self):
        """_seconds_until_next_run never returns more than 24 hours."""
        from app.modules.platform.cost_alert_job import _seconds_until_next_run

        secs = _seconds_until_next_run()
        assert secs <= 86400.0 + 1  # 24 hours + 1s tolerance
