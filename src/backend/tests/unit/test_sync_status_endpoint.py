"""
Unit tests for SCHED-027: GET /api/v1/tenant/sync-status endpoint.

Tests:
- No credentials → 401 or 403
- Valid tenant_admin user with mocked DB → 200 with all required fields
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.main import app


def _tenant_admin_user(tenant_id: str = "tenant-aaa-001"):
    """Return a minimal CurrentUser mock for require_tenant_admin dependency bypass."""
    user = MagicMock()
    user.id = "user-001"
    user.tenant_id = tenant_id
    user.roles = ["tenant_admin"]
    user.scope = "tenant"
    user.plan = "professional"
    return user


@pytest.mark.asyncio
async def test_sync_status_requires_tenant_admin():
    """GET /api/v1/tenant/sync-status with no credentials → 401 or 403."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/api/v1/tenant/sync-status")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_sync_status_returns_outcome_fields():
    """
    With a mocked tenant_admin user and a mocked DB session that returns
    realistic rows for all queries → 200 with all required response fields.

    Endpoint makes 5 sequential db.execute() calls:
      1. credential_expiry last completed started_at → fetchone() → row with datetime
      2. credential expiry days remaining (MIN EXTRACT) → fetchone() → row with int
      3. query_warming last completed started_at → fetchone() → row with datetime
      4. health_score last completed started_at → fetchone() → row with datetime
      5. glossary_terms active COUNT → fetchone() → row with int
    """
    from app.core.dependencies import require_tenant_admin
    from app.core.session import get_async_session

    mock_user = _tenant_admin_user()
    now = datetime.now(timezone.utc)

    # Build mock rows for each query
    cred_row = MagicMock()
    cred_row.__getitem__ = lambda self, i: now  # row[0] = started_at datetime

    expiry_row = MagicMock()
    expiry_row.__getitem__ = lambda self, i: 14  # row[0] = 14 days remaining

    warming_row = MagicMock()
    warming_row.__getitem__ = lambda self, i: now  # row[0] = started_at datetime

    health_row = MagicMock()
    health_row.__getitem__ = lambda self, i: now  # row[0] = started_at datetime

    glossary_row = MagicMock()
    glossary_row.__getitem__ = lambda self, i: 7  # row[0] = count

    # Build mock results — each .fetchone() returns its respective row
    def _make_result(row):
        r = MagicMock()
        r.fetchone.return_value = row
        return r

    mock_session = AsyncMock()
    mock_session.execute.side_effect = [
        _make_result(cred_row),
        _make_result(expiry_row),
        _make_result(warming_row),
        _make_result(health_row),
        _make_result(glossary_row),
    ]

    app.dependency_overrides[require_tenant_admin] = lambda: mock_user
    app.dependency_overrides[get_async_session] = lambda: mock_session

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get("/api/v1/tenant/sync-status")
        assert resp.status_code == 200
        body = resp.json()
        assert "last_credentials_checked_at" in body
        assert "credentials_expiry_days_remaining" in body
        assert "last_query_warming_completed_at" in body
        assert "last_health_score_calculated_at" in body
        assert "glossary_terms_active" in body
        # Verify non-null values from mocked rows
        assert body["last_credentials_checked_at"] is not None
        assert body["credentials_expiry_days_remaining"] == 14
        assert body["last_query_warming_completed_at"] is not None
        assert body["last_health_score_calculated_at"] is not None
        assert body["glossary_terms_active"] == 7
    finally:
        app.dependency_overrides.clear()
