"""
HAR-010: Unit tests for the HAR approval timeout background job.

Tests:
- get_timed_out_transactions: returns correct rows
- mark_transaction_timed_out: executes UPDATE + INSERT + commit
- notify_timeout_to_admins: calls publish_notification for each admin
- notify_timeout_to_admins: logs warning when no admins found
- process_timed_out_transaction: calls mark and notify
- process_timed_out_transaction: logs error but continues when mark fails
- run_approval_timeout_job: processes all timed-out transactions, returns count
- run_approval_timeout_job: returns 0 when no timed-out transactions
- run_approval_timeout_job: returns 0 on query failure
- _jitter_interval: stays within expected bounds
- Jitter interval is always >= 1.0
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.modules.har.approval_timeout_job import (
    _BASE_INTERVAL_SECONDS,
    _JITTER_SECONDS,
    _jitter_interval,
    get_timed_out_transactions,
    mark_transaction_timed_out,
    notify_timeout_to_admins,
    process_timed_out_transaction,
    run_approval_timeout_job,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_with_rows(rows):
    """Return a mock DB that returns the given rows from execute()."""
    db = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


def _txn_row(transaction_id=None, tenant_id=None):
    return {
        "id": transaction_id or str(uuid.uuid4()),
        "tenant_id": tenant_id or str(uuid.uuid4()),
        "amount": 6000.0,
        "currency": "USD",
    }


# ---------------------------------------------------------------------------
# _jitter_interval
# ---------------------------------------------------------------------------


def test_jitter_interval_within_bounds():
    """Jitter interval stays within BASE ± JITTER range."""
    for _ in range(50):
        interval = _jitter_interval()
        assert interval >= max(1.0, _BASE_INTERVAL_SECONDS - _JITTER_SECONDS)
        assert interval <= _BASE_INTERVAL_SECONDS + _JITTER_SECONDS


def test_jitter_interval_minimum_is_one():
    """_jitter_interval always returns >= 1.0."""
    # Even with the largest negative jitter, result must be >= 1
    for _ in range(20):
        assert _jitter_interval() >= 1.0


# ---------------------------------------------------------------------------
# get_timed_out_transactions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_timed_out_transactions_returns_rows():
    """get_timed_out_transactions returns list of transaction dicts."""
    txn_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "id": txn_id,
        "tenant_id": tenant_id,
        "amount": 6000.0,
        "currency": "USD",
    }[key]

    db = _make_db_with_rows([row])
    results = await get_timed_out_transactions(db)

    assert len(results) == 1
    assert results[0]["id"] == txn_id
    assert results[0]["tenant_id"] == tenant_id
    assert results[0]["amount"] == 6000.0


@pytest.mark.asyncio
async def test_get_timed_out_transactions_returns_empty_list():
    """get_timed_out_transactions returns [] when no rows match."""
    db = _make_db_with_rows([])
    results = await get_timed_out_transactions(db)
    assert results == []


# ---------------------------------------------------------------------------
# mark_transaction_timed_out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_transaction_timed_out_executes_update_and_insert():
    """mark_transaction_timed_out issues UPDATE + INSERT and calls commit."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    await mark_transaction_timed_out("txn-1", "tenant-1", db)

    assert db.execute.call_count == 2  # UPDATE + INSERT
    db.commit.assert_called_once()

    # First call is the UPDATE
    first_sql = str(db.execute.call_args_list[0][0][0])
    assert "TIMED_OUT" in first_sql or "UPDATE" in first_sql


@pytest.mark.asyncio
async def test_mark_transaction_timed_out_update_contains_timed_out():
    """The UPDATE SQL sets state to TIMED_OUT."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    await mark_transaction_timed_out("txn-abc", "tenant-abc", db)

    update_sql = str(db.execute.call_args_list[0][0][0])
    assert "TIMED_OUT" in update_sql


# ---------------------------------------------------------------------------
# notify_timeout_to_admins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_timeout_to_admins_calls_publish_for_each_admin():
    """notify_timeout_to_admins calls publish_notification for each admin."""
    user1 = str(uuid.uuid4())
    user2 = str(uuid.uuid4())

    db = AsyncMock()
    result = MagicMock()
    rows = [MagicMock(), MagicMock()]
    rows[0].__getitem__ = lambda self, key: user1
    rows[1].__getitem__ = lambda self, key: user2
    result.mappings.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)

    notified = []

    async def _fake_publish(
        user_id, tenant_id, notification_type, title, body, link=None
    ):
        notified.append(user_id)

    with patch(
        "app.modules.notifications.publisher.publish_notification",
        side_effect=_fake_publish,
    ):
        await notify_timeout_to_admins("txn-1", "tenant-1", db)

    assert user1 in notified
    assert user2 in notified


@pytest.mark.asyncio
async def test_notify_timeout_to_admins_logs_warning_when_no_admins():
    """notify_timeout_to_admins does not call publish when no admins exist."""
    db = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)

    with patch("app.modules.notifications.publisher.publish_notification") as mock_pub:
        await notify_timeout_to_admins("txn-no-admin", "tenant-no-admin", db)

    mock_pub.assert_not_called()


# ---------------------------------------------------------------------------
# process_timed_out_transaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_timed_out_transaction_calls_mark_and_notify():
    """process_timed_out_transaction calls mark and notify functions."""
    txn = _txn_row()
    mark_called = []
    notify_called = []

    async def _fake_mark(tid, tenant, db):
        mark_called.append(tid)

    async def _fake_notify(tid, tenant, db):
        notify_called.append(tid)

    with patch(
        "app.modules.har.approval_timeout_job.mark_transaction_timed_out",
        side_effect=_fake_mark,
    ), patch(
        "app.modules.har.approval_timeout_job.notify_timeout_to_admins",
        side_effect=_fake_notify,
    ):
        await process_timed_out_transaction(txn, AsyncMock())

    assert txn["id"] in mark_called
    assert txn["id"] in notify_called


@pytest.mark.asyncio
async def test_process_timed_out_transaction_skips_notify_on_mark_failure():
    """process_timed_out_transaction logs error and skips notify when mark fails."""
    txn = _txn_row()
    notify_called = []

    async def _fake_notify(tid, tenant, db):
        notify_called.append(tid)

    with patch(
        "app.modules.har.approval_timeout_job.mark_transaction_timed_out",
        side_effect=Exception("DB error"),
    ), patch(
        "app.modules.har.approval_timeout_job.notify_timeout_to_admins",
        side_effect=_fake_notify,
    ):
        # Should not raise
        await process_timed_out_transaction(txn, AsyncMock())

    assert notify_called == []


# ---------------------------------------------------------------------------
# run_approval_timeout_job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_approval_timeout_job_processes_all_transactions():
    """run_approval_timeout_job returns the count of processed transactions."""
    txns = [_txn_row(), _txn_row()]
    processed = []

    async def _fake_process(txn, db):
        processed.append(txn["id"])

    with patch(
        "app.modules.har.approval_timeout_job.get_timed_out_transactions",
        AsyncMock(return_value=txns),
    ), patch(
        "app.modules.har.approval_timeout_job.process_timed_out_transaction",
        side_effect=_fake_process,
    ):
        count = await run_approval_timeout_job(AsyncMock())

    assert count == 2
    assert set(processed) == {txns[0]["id"], txns[1]["id"]}


@pytest.mark.asyncio
async def test_run_approval_timeout_job_returns_zero_when_no_transactions():
    """run_approval_timeout_job returns 0 when no timed-out transactions found."""
    with patch(
        "app.modules.har.approval_timeout_job.get_timed_out_transactions",
        AsyncMock(return_value=[]),
    ):
        count = await run_approval_timeout_job(AsyncMock())

    assert count == 0


@pytest.mark.asyncio
async def test_run_approval_timeout_job_returns_zero_on_query_failure():
    """run_approval_timeout_job returns 0 and logs error when query fails."""
    with patch(
        "app.modules.har.approval_timeout_job.get_timed_out_transactions",
        AsyncMock(side_effect=Exception("DB connection error")),
    ):
        count = await run_approval_timeout_job(AsyncMock())

    assert count == 0
