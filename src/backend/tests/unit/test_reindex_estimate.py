"""
Unit tests for KB re-index estimate and reindex endpoints (TA-016).

Tests cover:
- GET /reindex-estimate returns correct document_count, avg_tokens, cost, duration
- GET /reindex-estimate with default tokens (no stats) uses 800
- GET /reindex-estimate with zero docs returns zero cost and duration
- GET /reindex-estimate with invalid kb_id UUID returns 422
- POST /reindex returns job_id and status=queued
- POST /reindex returns 409 when reindex already in progress
- POST /reindex with invalid kb_id returns 422
- _get_kb_document_count returns count from integrations
- _get_avg_tokens returns default when no stats
- _check_reindex_in_progress returns True when in-progress job exists
- Estimated duration formula: doc_count * 0.05
- Cost formula: doc_count × avg_tokens × cost_per_token
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin(tenant_id="tenant-1"):
    from app.core.dependencies import CurrentUser

    return CurrentUser(
        id="admin-1",
        tenant_id=tenant_id,
        roles=["tenant_admin"],
        scope="tenant",
        plan="professional",
    )


def _mock_db_with_scalar(value):
    """DB mock where fetchone returns (value,)."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = (value,)
    db.execute.return_value = mock_result
    db.commit = AsyncMock()
    return db


def _mock_db_no_row():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_result.fetchall.return_value = []
    db.execute.return_value = mock_result
    db.commit = AsyncMock()
    return db


KB_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_kb_document_count():
    """Returns count from integrations table."""
    from app.modules.documents.reindex import _get_kb_document_count

    db = _mock_db_with_scalar(42)
    count = await _get_kb_document_count(KB_ID, "tenant-1", db)
    assert count == 42


@pytest.mark.asyncio
async def test_get_kb_document_count_zero():
    """Returns 0 when no integrations match."""
    from app.modules.documents.reindex import _get_kb_document_count

    db = _mock_db_with_scalar(0)
    count = await _get_kb_document_count(KB_ID, "tenant-1", db)
    assert count == 0


@pytest.mark.asyncio
async def test_get_avg_tokens_default_when_no_stats():
    """Returns 800 default when no sync_jobs stats exist."""
    from app.modules.documents.reindex import _get_avg_tokens, _DEFAULT_AVG_TOKENS

    db = _mock_db_no_row()
    tokens = await _get_avg_tokens(KB_ID, "tenant-1", db)
    assert tokens == _DEFAULT_AVG_TOKENS


@pytest.mark.asyncio
async def test_get_avg_tokens_from_stats():
    """Returns avg_tokens_per_doc from sync_jobs when available."""
    from app.modules.documents.reindex import _get_avg_tokens

    db = _mock_db_with_scalar("1200")  # stored as string in JSONB
    tokens = await _get_avg_tokens(KB_ID, "tenant-1", db)
    assert tokens == 1200


@pytest.mark.asyncio
async def test_check_reindex_in_progress_false():
    """Returns False when no pending/running reindex jobs."""
    from app.modules.documents.reindex import _check_reindex_in_progress

    db = _mock_db_no_row()
    result = await _check_reindex_in_progress(KB_ID, "tenant-1", db)
    assert result is False


@pytest.mark.asyncio
async def test_check_reindex_in_progress_true():
    """Returns True when a pending reindex job exists."""
    from app.modules.documents.reindex import _check_reindex_in_progress

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = (1,)  # row found
    db.execute.return_value = mock_result

    result = await _check_reindex_in_progress(KB_ID, "tenant-1", db)
    assert result is True


# ---------------------------------------------------------------------------
# Estimate endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_reindex_estimate_full():
    """GET estimate returns correct calculations."""
    from app.modules.documents.reindex import get_reindex_estimate

    with (
        patch(
            "app.modules.documents.reindex._get_kb_document_count",
            new=AsyncMock(return_value=100),
        ),
        patch(
            "app.modules.documents.reindex._get_avg_tokens",
            new=AsyncMock(return_value=800),
        ),
        patch(
            "app.modules.documents.reindex._get_embedding_cost_per_token",
            new=AsyncMock(return_value=0.00000002),  # $0.00002 / 1000
        ),
    ):
        # Existence check (first db.execute call) must return a row so the
        # 404 guard passes. Helper functions are patched so subsequent
        # db.execute calls are not made by the handler.
        db = _mock_db_with_scalar(1)
        user = _make_admin()
        resp = await get_reindex_estimate(kb_id=KB_ID, current_user=user, db=db)

    assert resp.document_count == 100
    assert resp.avg_tokens == 800
    # 100 * 800 * 0.00000002 = 0.0016
    assert abs(resp.estimated_cost_usd - 0.0016) < 1e-9
    # 100 * 0.05 = 5.0 minutes
    assert resp.estimated_duration_minutes == 5.0


@pytest.mark.asyncio
async def test_get_reindex_estimate_zero_docs():
    """GET estimate with 0 docs returns zero cost and duration."""
    from app.modules.documents.reindex import get_reindex_estimate

    with (
        patch(
            "app.modules.documents.reindex._get_kb_document_count",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.modules.documents.reindex._get_avg_tokens",
            new=AsyncMock(return_value=800),
        ),
        patch(
            "app.modules.documents.reindex._get_embedding_cost_per_token",
            new=AsyncMock(return_value=0.00000002),
        ),
    ):
        # Existence check must return a row so the 404 guard passes.
        db = _mock_db_with_scalar(1)
        user = _make_admin()
        resp = await get_reindex_estimate(kb_id=KB_ID, current_user=user, db=db)

    assert resp.document_count == 0
    assert resp.estimated_cost_usd == 0.0
    assert resp.estimated_duration_minutes == 0.0


@pytest.mark.asyncio
async def test_get_reindex_estimate_invalid_uuid():
    """GET estimate with non-UUID kb_id returns 422."""
    from fastapi import HTTPException
    from app.modules.documents.reindex import get_reindex_estimate

    db = _mock_db_no_row()
    user = _make_admin()

    with pytest.raises(HTTPException) as exc_info:
        await get_reindex_estimate(kb_id="not-a-uuid", current_user=user, db=db)

    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Reindex endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_reindex_returns_queued():
    """POST reindex returns job_id and status=queued."""
    from app.modules.documents.reindex import trigger_reindex
    from fastapi import BackgroundTasks

    with (
        patch(
            "app.modules.documents.reindex._check_reindex_in_progress",
            new=AsyncMock(return_value=False),
        ),
    ):
        db = AsyncMock()
        # First call: find integration_id
        mock_result_int = MagicMock()
        mock_result_int.fetchone.return_value = (uuid.uuid4(),)
        # Second call: INSERT sync_jobs
        mock_result_ins = MagicMock()
        db.execute = AsyncMock(side_effect=[mock_result_int, mock_result_ins])
        db.commit = AsyncMock()

        user = _make_admin()
        bg = BackgroundTasks()

        resp = await trigger_reindex(
            kb_id=KB_ID, background_tasks=bg, current_user=user, db=db
        )

    assert resp.status == "queued"
    assert uuid.UUID(resp.job_id)  # valid UUID


@pytest.mark.asyncio
async def test_trigger_reindex_409_when_in_progress():
    """POST reindex returns 409 when another job is in progress."""
    from fastapi import BackgroundTasks, HTTPException
    from app.modules.documents.reindex import trigger_reindex

    with patch(
        "app.modules.documents.reindex._check_reindex_in_progress",
        new=AsyncMock(return_value=True),
    ):
        db = _mock_db_no_row()
        user = _make_admin()
        bg = BackgroundTasks()

        with pytest.raises(HTTPException) as exc_info:
            await trigger_reindex(
                kb_id=KB_ID, background_tasks=bg, current_user=user, db=db
            )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_trigger_reindex_invalid_uuid():
    """POST reindex with invalid kb_id returns 422."""
    from fastapi import BackgroundTasks, HTTPException
    from app.modules.documents.reindex import trigger_reindex

    db = _mock_db_no_row()
    user = _make_admin()
    bg = BackgroundTasks()

    with pytest.raises(HTTPException) as exc_info:
        await trigger_reindex(
            kb_id="not-a-uuid", background_tasks=bg, current_user=user, db=db
        )
    assert exc_info.value.status_code == 422
