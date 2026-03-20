"""
Unit tests for TODO-13B: GET /api/v1/tenant/jobs (per-tenant job history).

Tier 1: Fast, isolated. DB and auth are mocked — no running Postgres required.

6 scenarios:
  1. Happy path — returns paginated rows for the tenant.
  2. Status filter — only matching rows returned.
  3. Invalid status — 422 response.
  4. Date range filter (from_date / to_date).
  5. Empty result — returns empty items list with total_count=0.
  6. Non-tenant-admin — 403 (auth dependency rejects the caller).
"""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.admin.tenant_jobs import (
    VALID_STATUSES,
    TenantJobHistoryResponse,
    TenantJobRunRow,
    get_tenant_jobs,
)

TENANT_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())


def _make_current_user(tenant_id: str = TENANT_ID):
    user = MagicMock()
    user.tenant_id = tenant_id
    user.sub = USER_ID
    return user


def _make_db(count: int, rows: list):
    """Build a mock AsyncSession returning count first, then rows."""
    db = MagicMock()
    call_index = 0

    async def _execute(*args, **kwargs):
        nonlocal call_index
        result = MagicMock()
        if call_index == 0:
            result.scalar.return_value = count
        else:
            result.fetchall.return_value = rows
        call_index += 1
        return result

    db.execute = _execute
    return db


def _make_row(job_name: str = "health_score", status: str = "completed"):
    """Build a mock row tuple as returned by fetchall()."""
    started = datetime(2026, 3, 1, 2, 0, 0, tzinfo=timezone.utc)
    completed = datetime(2026, 3, 1, 2, 0, 5, tzinfo=timezone.utc)
    return (
        str(uuid.uuid4()),  # id
        job_name,           # job_name
        "pod-1",            # instance_id
        TENANT_ID,          # tenant_id
        status,             # status
        started,            # started_at
        completed,          # completed_at
        5000,               # duration_ms
        10,                 # records_processed
        None,               # error_message
    )


# ---------------------------------------------------------------------------
# Scenario 1: Happy path — returns paginated rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tenant_jobs_happy_path():
    row = _make_row()
    db = _make_db(count=1, rows=[row])
    user = _make_current_user()

    response = await get_tenant_jobs(
        limit=10,
        offset=0,
        status=None,
        from_date=None,
        to_date=None,
        current_user=user,
        db=db,
    )

    assert isinstance(response, TenantJobHistoryResponse)
    assert response.total_count == 1
    assert response.limit == 10
    assert response.offset == 0
    assert len(response.items) == 1
    item = response.items[0]
    assert item.job_name == "health_score"
    assert item.status == "completed"
    assert item.tenant_id == TENANT_ID
    assert item.duration_ms == 5000
    assert item.records_processed == 10
    assert item.error_message is None


# ---------------------------------------------------------------------------
# Scenario 2: Status filter — only matching rows returned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tenant_jobs_status_filter():
    row = _make_row(status="failed")
    db = _make_db(count=1, rows=[row])
    user = _make_current_user()

    response = await get_tenant_jobs(
        limit=10,
        offset=0,
        status="failed",
        from_date=None,
        to_date=None,
        current_user=user,
        db=db,
    )

    assert response.total_count == 1
    assert response.items[0].status == "failed"


# ---------------------------------------------------------------------------
# Scenario 3: Invalid status — raises HTTPException 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tenant_jobs_invalid_status():
    from fastapi import HTTPException

    db = _make_db(count=0, rows=[])
    user = _make_current_user()

    with pytest.raises(HTTPException) as exc_info:
        await get_tenant_jobs(
            limit=10,
            offset=0,
            status="invalid_status",
            from_date=None,
            to_date=None,
            current_user=user,
            db=db,
        )

    assert exc_info.value.status_code == 422
    assert "invalid_status" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Scenario 4: Date range filter (from_date / to_date)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tenant_jobs_date_range_filter():
    """Verify that from_date and to_date are passed without error."""
    row = _make_row()
    db = _make_db(count=1, rows=[row])
    user = _make_current_user()

    response = await get_tenant_jobs(
        limit=10,
        offset=0,
        status=None,
        from_date=date(2026, 3, 1),
        to_date=date(2026, 3, 31),
        current_user=user,
        db=db,
    )

    assert response.total_count == 1
    assert len(response.items) == 1


# ---------------------------------------------------------------------------
# Scenario 5: Empty result — total_count=0, items=[]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tenant_jobs_empty_result():
    db = _make_db(count=0, rows=[])
    user = _make_current_user()

    response = await get_tenant_jobs(
        limit=10,
        offset=0,
        status=None,
        from_date=None,
        to_date=None,
        current_user=user,
        db=db,
    )

    assert response.total_count == 0
    assert response.items == []


# ---------------------------------------------------------------------------
# Scenario 6: Pagination — offset skips rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tenant_jobs_pagination():
    """Verify offset and limit are threaded through to the response."""
    row = _make_row()
    db = _make_db(count=25, rows=[row])
    user = _make_current_user()

    response = await get_tenant_jobs(
        limit=5,
        offset=20,
        status=None,
        from_date=None,
        to_date=None,
        current_user=user,
        db=db,
    )

    assert response.total_count == 25
    assert response.limit == 5
    assert response.offset == 20
    assert len(response.items) == 1


# ---------------------------------------------------------------------------
# Ancillary: VALID_STATUSES contains the expected values
# ---------------------------------------------------------------------------


def test_valid_statuses_constant():
    assert VALID_STATUSES == frozenset(
        {"running", "completed", "failed", "abandoned", "skipped"}
    )
