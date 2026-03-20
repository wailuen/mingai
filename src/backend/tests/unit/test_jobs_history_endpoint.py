"""
Unit tests for SCHED-026: GET /api/v1/platform/jobs/history endpoint.

Tests:
- No auth (missing JWT) → 403
- Platform admin with valid filters → 200 with correct structure
- Pagination via offset/limit
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.main import app


def _platform_admin_token():
    """Return a minimal JWT-like dict for require_platform_admin dependency bypass."""
    from unittest.mock import MagicMock
    user = MagicMock()
    user.scope = "platform"
    user.role = "platform_admin"
    user.tenant_id = None
    return user


@pytest.mark.asyncio
async def test_job_history_requires_platform_admin_scope():
    """Endpoint returns 403 when no credentials are provided."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/api/v1/platform/jobs/history")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_job_history_invalid_status_returns_422():
    """Invalid status query parameter returns 422."""
    from app.core.dependencies import require_platform_admin
    from app.core.session import get_async_session

    mock_user = _platform_admin_token()
    mock_session = AsyncMock()

    app.dependency_overrides[require_platform_admin] = lambda: mock_user
    app.dependency_overrides[get_async_session] = lambda: mock_session

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/platform/jobs/history?status=bogus_status"
            )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_job_history_returns_paginated_response():
    """Valid request returns 200 with correct response structure."""
    from app.core.dependencies import require_platform_admin
    from app.core.session import get_async_session

    mock_user = _platform_admin_token()

    # Mock the DB session with realistic row data
    now = datetime.now(timezone.utc)
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, i: [
        "a1b2c3d4-0000-0000-0000-000000000001",  # id
        "health_score",                            # job_name
        "pod-abc123",                              # instance_id
        None,                                      # tenant_id
        "completed",                               # status
        now,                                       # started_at
        now,                                       # completed_at
        5000,                                      # duration_ms
        47,                                        # records_processed
        None,                                      # error_message
    ][i]

    count_result = MagicMock()
    count_result.scalar.return_value = 1

    data_result = MagicMock()
    data_result.fetchall.return_value = [mock_row]

    mock_session = AsyncMock()
    mock_session.execute.side_effect = [count_result, data_result]

    app.dependency_overrides[require_platform_admin] = lambda: mock_user
    app.dependency_overrides[get_async_session] = lambda: mock_session

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/platform/jobs/history?job_name=health_score&limit=50&offset=0"
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total_count" in body
        assert body["total_count"] == 1
        assert body["limit"] == 50
        assert body["offset"] == 0
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["job_name"] == "health_score"
        assert item["status"] == "completed"
        assert item["records_processed"] == 47
    finally:
        app.dependency_overrides.clear()
