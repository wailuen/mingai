"""
Unit tests for PA-016: Billing reconciliation export.

Coverage:
- GET /platform/cost-analytics/export — 200 with month param
- GET /platform/cost-analytics/export — 200 with from/to params
- GET /platform/cost-analytics/export — 200 with no params (defaults to current month)
- CSV headers correct
- CSV rows contain expected data (tenant_id, name, plan_tier, tokens, costs, margins)
- Tenant name with embedded comma — properly quoted in CSV
- Empty result (no data in period) — headers-only CSV returned (not 404)
- Content-Type: text/csv
- Content-Disposition: attachment with billing-{period}.csv filename
- 401 without Authorization header
- 403 for tenant_admin caller
- 422 for invalid month format
- 422 for month with invalid value (month=13)
- 422 for from without to
- 422 for to without from
- 422 for from > to
- 422 for bad ISO date format in from/to
- _parse_export_period unit tests (happy path + error paths)

Tier 1: Fast, isolated, uses mocking.
"""
import csv
import io
import os
from calendar import monthrange
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

_EXPORT_URL = "/api/v1/platform/cost-analytics/export"


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


@pytest.fixture
def client(env_vars):
    from app.core.session import get_async_session
    from app.main import app

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

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


# ---------------------------------------------------------------------------
# Sample DB row factory
# ---------------------------------------------------------------------------


def _make_export_row(
    tenant_id: str = "t1t1t1t1-0000-0000-0000-000000000001",
    tenant_name: str = "Acme Corp",
    plan_tier: str = "professional",
    tokens_in: int = 10000,
    tokens_out: int = 5000,
    total_cost_usd: float = 1.234567,
    gross_margin_pct: float | None = 45.12,
    plan_revenue_usd: float = 299.0,
) -> tuple:
    """Return a tuple matching the SELECT column order in the export query."""
    return (
        tenant_id,
        tenant_name,
        plan_tier,
        tokens_in,
        tokens_out,
        total_cost_usd,
        gross_margin_pct,
        plan_revenue_usd,
    )


def _build_mock_db_with_rows(rows: list[tuple]) -> AsyncMock:
    """
    Return a mock AsyncSession that yields the given rows on the 3rd execute call
    (after the two set_config calls).
    """
    mock_db = AsyncMock()

    set_config_result = MagicMock()
    export_result = MagicMock()
    export_result.fetchall.return_value = rows

    mock_db.execute = AsyncMock(
        side_effect=[
            set_config_result,  # set_config user_role
            set_config_result,  # set_config current_scope
            export_result,  # SELECT FROM cost_summary_daily
        ]
    )
    mock_db.commit = AsyncMock()
    return mock_db


# ---------------------------------------------------------------------------
# Tests: _parse_export_period (pure unit)
# ---------------------------------------------------------------------------


class TestParseExportPeriod:
    """Unit tests for the period-parsing helper — no HTTP overhead."""

    def _call(self, month=None, from_date=None, to_date=None):
        from app.modules.platform.cost_analytics import _parse_export_period

        return _parse_export_period(month, from_date, to_date)

    def test_month_param_returns_full_month(self):
        start, end, label = self._call(month="2026-03")
        assert start == date(2026, 3, 1)
        assert end == date(2026, 3, 31)
        assert label == "2026-03"

    def test_month_february_correct_end_day(self):
        """February 2024 is a leap year → 29 days."""
        start, end, label = self._call(month="2024-02")
        assert start == date(2024, 2, 1)
        assert end == date(2024, 2, 29)
        assert label == "2024-02"

    def test_from_to_returns_correct_range(self):
        start, end, label = self._call(from_date="2026-03-01", to_date="2026-03-15")
        assert start == date(2026, 3, 1)
        assert end == date(2026, 3, 15)
        assert label == "2026-03-01_2026-03-15"

    def test_no_params_defaults_to_current_month(self):
        today = date.today()
        expected_start = date(today.year, today.month, 1)
        last_day = monthrange(today.year, today.month)[1]
        expected_end = date(today.year, today.month, last_day)

        start, end, label = self._call()
        assert start == expected_start
        assert end == expected_end
        assert label == today.strftime("%Y-%m")

    def test_invalid_month_format_raises_422(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            self._call(month="03-2026")  # wrong order
        assert exc_info.value.status_code == 422

    def test_invalid_month_value_raises_422(self):
        """month=2026-13 is not a valid month."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            self._call(month="2026-13")
        assert exc_info.value.status_code == 422

    def test_month_zero_raises_422(self):
        """month=2026-00 is a common off-by-one typo — must be rejected."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            self._call(month="2026-00")
        assert exc_info.value.status_code == 422

    def test_from_without_to_raises_422(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            self._call(from_date="2026-03-01")
        assert exc_info.value.status_code == 422

    def test_to_without_from_raises_422(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            self._call(to_date="2026-03-15")
        assert exc_info.value.status_code == 422

    def test_from_after_to_raises_422(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            self._call(from_date="2026-03-20", to_date="2026-03-01")
        assert exc_info.value.status_code == 422

    def test_bad_from_date_format_raises_422(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            self._call(from_date="not-a-date", to_date="2026-03-15")
        assert exc_info.value.status_code == 422

    def test_bad_to_date_format_raises_422(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            self._call(from_date="2026-03-01", to_date="2026/03/15")
        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Tests: Route RBAC / Auth
# ---------------------------------------------------------------------------


class TestExportBillingCsvAuth:
    def test_no_auth_returns_401(self, client):
        """401 when no Authorization header is provided."""
        resp = client.get(_EXPORT_URL, params={"month": "2026-03"})
        assert resp.status_code == 401

    def test_tenant_admin_returns_403(self, client, tenant_admin_headers):
        """403 when caller is tenant_admin — only platform_admin may export."""
        resp = client.get(
            _EXPORT_URL,
            params={"month": "2026-03"},
            headers=tenant_admin_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: CSV content and headers
# ---------------------------------------------------------------------------


class TestExportBillingCsvContent:
    def _get_csv(self, client, platform_headers, params, rows):
        """Helper: GET export with a mock DB returning `rows`."""
        mock_db = _build_mock_db_with_rows(rows)

        from app.core.session import get_async_session
        from app.main import app

        async def _override():
            yield mock_db

        app.dependency_overrides[get_async_session] = _override
        try:
            resp = client.get(_EXPORT_URL, params=params, headers=platform_headers)
        finally:
            app.dependency_overrides.pop(get_async_session, None)

        return resp

    def test_200_with_month_param(self, client, platform_headers, env_vars):
        row = _make_export_row()
        resp = self._get_csv(client, platform_headers, {"month": "2026-03"}, [row])
        assert resp.status_code == 200

    def test_content_type_is_text_csv(self, client, platform_headers, env_vars):
        row = _make_export_row()
        resp = self._get_csv(client, platform_headers, {"month": "2026-03"}, [row])
        assert "text/csv" in resp.headers["content-type"]

    def test_content_disposition_attachment_with_month_filename(
        self, client, platform_headers, env_vars
    ):
        row = _make_export_row()
        resp = self._get_csv(client, platform_headers, {"month": "2026-03"}, [row])
        disposition = resp.headers["content-disposition"]
        assert "attachment" in disposition
        assert "billing-2026-03.csv" in disposition

    def test_content_disposition_with_from_to_filename(
        self, client, platform_headers, env_vars
    ):
        row = _make_export_row()
        resp = self._get_csv(
            client,
            platform_headers,
            {"from": "2026-03-01", "to": "2026-03-15"},
            [row],
        )
        disposition = resp.headers["content-disposition"]
        assert "billing-2026-03-01_2026-03-15.csv" in disposition

    def test_csv_headers_are_correct(self, client, platform_headers, env_vars):
        resp = self._get_csv(client, platform_headers, {"month": "2026-03"}, [])
        reader = csv.reader(io.StringIO(resp.text))
        headers = next(reader)
        assert headers == [
            "tenant_id",
            "tenant_name",
            "plan_tier",
            "total_tokens_in",
            "total_tokens_out",
            "total_cost_usd",
            "gross_margin_pct",
            "plan_revenue_usd",
            "period_start",
            "period_end",
        ]

    def test_csv_row_data_matches_query_result(
        self, client, platform_headers, env_vars
    ):
        """Row values are correctly mapped to CSV columns."""
        row = _make_export_row(
            tenant_id="t1t1t1t1-0000-0000-0000-000000000001",
            tenant_name="Acme Corp",
            plan_tier="professional",
            tokens_in=10000,
            tokens_out=5000,
            total_cost_usd=1.234567,
            gross_margin_pct=45.12,
            plan_revenue_usd=299.0,
        )
        resp = self._get_csv(client, platform_headers, {"month": "2026-03"}, [row])
        reader = csv.reader(io.StringIO(resp.text))
        next(reader)  # skip header
        data_row = next(reader)

        assert data_row[0] == "t1t1t1t1-0000-0000-0000-000000000001"  # tenant_id
        assert data_row[1] == "Acme Corp"  # tenant_name
        assert data_row[2] == "professional"  # plan_tier
        assert int(data_row[3]) == 10000  # total_tokens_in
        assert int(data_row[4]) == 5000  # total_tokens_out
        assert float(data_row[5]) == pytest.approx(1.234567, abs=1e-6)  # total_cost_usd
        assert float(data_row[6]) == pytest.approx(45.12, abs=0.01)  # gross_margin_pct
        assert float(data_row[7]) == pytest.approx(299.0, abs=0.01)  # plan_revenue_usd
        assert data_row[8] == "2026-03-01"  # period_start
        assert data_row[9] == "2026-03-31"  # period_end

    def test_tenant_name_with_comma_properly_quoted(
        self, client, platform_headers, env_vars
    ):
        """Tenant names containing commas must not corrupt the CSV structure."""
        row = _make_export_row(tenant_name="Smith, Jones & Co")
        resp = self._get_csv(client, platform_headers, {"month": "2026-03"}, [row])
        reader = csv.reader(io.StringIO(resp.text))
        next(reader)  # header
        data_row = next(reader)
        # csv.reader will correctly unquote the name
        assert data_row[1] == "Smith, Jones & Co"
        # There should still be exactly 10 columns
        assert len(data_row) == 10

    def test_empty_result_returns_headers_only(
        self, client, platform_headers, env_vars
    ):
        """When no cost_summary_daily rows exist for the period, return header row only."""
        resp = self._get_csv(client, platform_headers, {"month": "2026-03"}, [])
        assert resp.status_code == 200
        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        # Only the header row should be present
        assert len(rows) == 1
        assert rows[0][0] == "tenant_id"

    def test_null_gross_margin_serialized_as_empty_string(
        self, client, platform_headers, env_vars
    ):
        """Tenants with no plan_revenue (0.0) → gross_margin_pct is NULL → empty string."""
        row = _make_export_row(gross_margin_pct=None, plan_revenue_usd=0.0)
        resp = self._get_csv(client, platform_headers, {"month": "2026-03"}, [row])
        reader = csv.reader(io.StringIO(resp.text))
        next(reader)  # header
        data_row = next(reader)
        assert data_row[6] == ""  # gross_margin_pct empty
        assert data_row[7] == "0.00"  # plan_revenue_usd is 0

    def test_db_null_plan_revenue_serialized_as_empty_string(
        self, client, platform_headers, env_vars
    ):
        """DB NULL for plan_revenue_usd (None in Python) → empty string in CSV."""
        row = _make_export_row(gross_margin_pct=None, plan_revenue_usd=None)
        resp = self._get_csv(client, platform_headers, {"month": "2026-03"}, [row])
        reader = csv.reader(io.StringIO(resp.text))
        next(reader)  # header
        data_row = next(reader)
        assert data_row[6] == ""  # gross_margin_pct empty
        assert data_row[7] == ""  # plan_revenue_usd empty (None → "" branch)

    def test_multiple_tenants_in_csv(self, client, platform_headers, env_vars):
        """Multiple DB rows produce one CSV row each (plus header)."""
        rows = [
            _make_export_row(tenant_id="t1t1t1t1-0000-0000-0000-000000000001"),
            _make_export_row(tenant_id="t2t2t2t2-0000-0000-0000-000000000002"),
            _make_export_row(tenant_id="t3t3t3t3-0000-0000-0000-000000000003"),
        ]
        resp = self._get_csv(client, platform_headers, {"month": "2026-03"}, rows)
        reader = csv.reader(io.StringIO(resp.text))
        all_rows = list(reader)
        # 1 header + 3 data rows
        assert len(all_rows) == 4


# ---------------------------------------------------------------------------
# Tests: CSV formula injection sanitization
# ---------------------------------------------------------------------------


class TestCsvInjectionSanitization:
    """
    Verify that tenant names / plan_tier values starting with formula trigger
    characters are prefixed with a single-quote in the CSV output.
    """

    def _sanitize(self, value: str) -> str:
        from app.modules.platform.cost_analytics import _sanitize_csv_field

        return _sanitize_csv_field(value)

    def test_equals_sign_prefixed(self):
        assert self._sanitize("=CMD|'calc'!A0").startswith("'")

    def test_plus_sign_prefixed(self):
        assert self._sanitize("+test").startswith("'")

    def test_minus_sign_prefixed(self):
        assert self._sanitize("-1+1").startswith("'")

    def test_at_sign_prefixed(self):
        assert self._sanitize("@SUM(A1:A10)").startswith("'")

    def test_safe_name_unchanged(self):
        assert self._sanitize("Acme Corp") == "Acme Corp"

    def test_empty_string_unchanged(self):
        assert self._sanitize("") == ""

    def test_formula_tenant_name_in_csv_is_prefixed(
        self, client, platform_headers, env_vars
    ):
        """A tenant name starting with '=' is written as '='... in the CSV."""
        row = _make_export_row(tenant_name="=SUM(A1:A10)")

        mock_db = _build_mock_db_with_rows([row])
        from app.core.session import get_async_session
        from app.main import app

        async def _override():
            yield mock_db

        app.dependency_overrides[get_async_session] = _override
        try:
            resp = client.get(
                _EXPORT_URL,
                params={"month": "2026-03"},
                headers=platform_headers,
            )
        finally:
            app.dependency_overrides.pop(get_async_session, None)

        assert resp.status_code == 200
        reader = csv.reader(io.StringIO(resp.text))
        next(reader)  # skip header
        data_row = next(reader)
        # The tenant_name field must start with single-quote to neutralise the formula
        assert data_row[1].startswith("'")
        assert "=SUM(A1:A10)" in data_row[1]


# ---------------------------------------------------------------------------
# Tests: Period validation via HTTP (422 responses)
# ---------------------------------------------------------------------------


class TestExportPeriodValidation:
    def _get(self, client, platform_headers, params):
        return client.get(_EXPORT_URL, params=params, headers=platform_headers)

    def test_invalid_month_format_returns_422(self, client, platform_headers, env_vars):
        resp = self._get(client, platform_headers, {"month": "03/2026"})
        assert resp.status_code == 422

    def test_invalid_month_value_returns_422(self, client, platform_headers, env_vars):
        resp = self._get(client, platform_headers, {"month": "2026-13"})
        assert resp.status_code == 422

    def test_from_without_to_returns_422(self, client, platform_headers, env_vars):
        resp = self._get(client, platform_headers, {"from": "2026-03-01"})
        assert resp.status_code == 422

    def test_to_without_from_returns_422(self, client, platform_headers, env_vars):
        resp = self._get(client, platform_headers, {"to": "2026-03-31"})
        assert resp.status_code == 422

    def test_from_after_to_returns_422(self, client, platform_headers, env_vars):
        resp = self._get(
            client, platform_headers, {"from": "2026-03-31", "to": "2026-03-01"}
        )
        assert resp.status_code == 422

    def test_bad_from_date_format_returns_422(self, client, platform_headers, env_vars):
        resp = self._get(
            client, platform_headers, {"from": "2026/03/01", "to": "2026-03-31"}
        )
        assert resp.status_code == 422
