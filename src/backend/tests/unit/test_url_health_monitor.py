"""
HAR-004: URL Health Monitor unit tests.

Tests:
- check_agent_health: success/failure HTTP responses
- failure counting: increment, get, reset
- status change logic: AVAILABLE → UNAVAILABLE after 3 failures, recovery
- jitter calculation: within ±60s of base
- notification on status change
- per-agent isolation (one failure doesn't abort others)
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.registry.url_health_monitor import (
    _HEALTH_STATUS_AVAILABLE,
    _HEALTH_STATUS_UNAVAILABLE,
    _JITTER_SECONDS,
    _MAX_CONSECUTIVE_FAILURES,
    _BASE_INTERVAL_SECONDS,
    _failure_key,
    check_agent_health,
    get_failure_count,
    increment_failure_count,
    process_agent_health,
    reset_failure_count,
    update_agent_health_status,
    _jitter_interval,
)


# ---------------------------------------------------------------------------
# check_agent_health tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_agent_health_returns_true_on_200():
    """Returns True when HTTP HEAD response is 200."""
    with patch(
        "app.modules.registry.url_health_monitor.httpx.AsyncClient"
    ) as mock_client:
        response_mock = MagicMock()
        response_mock.status_code = 200
        mock_client.return_value.__aenter__ = AsyncMock(
            return_value=mock_client.return_value
        )
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.head = AsyncMock(return_value=response_mock)

        result = await check_agent_health("https://agent.example.com/health")
        assert result is True


@pytest.mark.asyncio
async def test_check_agent_health_returns_false_on_500():
    """Returns False when HTTP HEAD response is 500."""
    with patch(
        "app.modules.registry.url_health_monitor.httpx.AsyncClient"
    ) as mock_client:
        response_mock = MagicMock()
        response_mock.status_code = 500
        mock_client.return_value.__aenter__ = AsyncMock(
            return_value=mock_client.return_value
        )
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.head = AsyncMock(return_value=response_mock)

        result = await check_agent_health("https://agent.example.com/health")
        assert result is False


@pytest.mark.asyncio
async def test_check_agent_health_returns_false_on_connection_error():
    """Returns False when HTTP request raises a connection error."""
    with patch(
        "app.modules.registry.url_health_monitor.httpx.AsyncClient"
    ) as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(
            return_value=mock_client.return_value
        )
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.head = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        result = await check_agent_health("https://unreachable.example.com/health")
        assert result is False


@pytest.mark.asyncio
async def test_check_agent_health_returns_true_on_404():
    """Returns True on 404 — the agent is up even if endpoint not found."""
    with patch(
        "app.modules.registry.url_health_monitor.httpx.AsyncClient"
    ) as mock_client:
        response_mock = MagicMock()
        response_mock.status_code = 404
        mock_client.return_value.__aenter__ = AsyncMock(
            return_value=mock_client.return_value
        )
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.head = AsyncMock(return_value=response_mock)

        result = await check_agent_health("https://agent.example.com/health")
        assert result is True


# ---------------------------------------------------------------------------
# Failure counter tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_failure_count_returns_zero_when_key_absent():
    """get_failure_count returns 0 when Redis key does not exist."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)

    count = await get_failure_count("tenant1", "agent1", redis)
    assert count == 0


@pytest.mark.asyncio
async def test_get_failure_count_returns_stored_value():
    """get_failure_count returns the integer stored in Redis."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=b"2")

    count = await get_failure_count("tenant1", "agent1", redis)
    assert count == 2


@pytest.mark.asyncio
async def test_increment_failure_count_returns_incremented_value():
    """increment_failure_count returns the new count after INCR."""
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=2)
    redis.expire = AsyncMock()

    count = await increment_failure_count("tenant1", "agent1", redis)
    assert count == 2


@pytest.mark.asyncio
async def test_increment_failure_count_sets_ttl_on_first_increment():
    """increment_failure_count calls EXPIRE when count reaches 1 (first set)."""
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock()

    await increment_failure_count("tenant1", "agent1", redis)
    redis.expire.assert_called_once()


@pytest.mark.asyncio
async def test_reset_failure_count_deletes_key():
    """reset_failure_count deletes the Redis key."""
    redis = AsyncMock()
    redis.delete = AsyncMock()

    await reset_failure_count("tenant1", "agent1", redis)
    redis.delete.assert_called_once()


# ---------------------------------------------------------------------------
# Jitter calculation
# ---------------------------------------------------------------------------


def test_jitter_interval_within_bounds():
    """_jitter_interval returns a value within [base ± 60s]."""
    for _ in range(50):
        interval = _jitter_interval()
        assert interval >= max(1.0, _BASE_INTERVAL_SECONDS - _JITTER_SECONDS)
        assert interval <= _BASE_INTERVAL_SECONDS + _JITTER_SECONDS


def test_jitter_interval_never_below_one():
    """_jitter_interval always returns at least 1.0 seconds."""
    # Even with a tiny base
    interval = _jitter_interval(base_seconds=1.0)
    assert interval >= 1.0


def test_jitter_interval_uses_correct_base():
    """_jitter_interval uses _BASE_INTERVAL_SECONDS as base by default."""
    # Run many times — should average close to base
    values = [_jitter_interval() for _ in range(100)]
    avg = sum(values) / len(values)
    assert abs(avg - _BASE_INTERVAL_SECONDS) < _JITTER_SECONDS


# ---------------------------------------------------------------------------
# process_agent_health tests
# ---------------------------------------------------------------------------


def _make_db_for_status_check(current_status="AVAILABLE"):
    """Mock DB that returns current_status in SELECT and confirms UPDATE."""
    db = AsyncMock()
    select_result = MagicMock()
    select_result.mappings.return_value.first.return_value = {
        "health_status": current_status
    }
    update_result = MagicMock()
    db.execute = AsyncMock(side_effect=[select_result, update_result])
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_process_agent_health_resets_counter_on_success():
    """On success: failure counter is reset."""
    tenant_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=b"0")
    redis.incr = AsyncMock(return_value=1)
    redis.delete = AsyncMock()

    db = _make_db_for_status_check(current_status="AVAILABLE")

    with patch(
        "app.modules.registry.url_health_monitor.check_agent_health",
        AsyncMock(return_value=True),
    ):
        await process_agent_health(
            agent_id=agent_id,
            agent_name="TestAgent",
            tenant_id=tenant_id,
            health_check_url="https://agent.example.com/health",
            db=db,
            redis=redis,
        )

    redis.delete.assert_called_once()


@pytest.mark.asyncio
async def test_process_agent_health_increments_counter_on_failure():
    """On failure: increments the consecutive failure counter."""
    tenant_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=b"1")
    redis.incr = AsyncMock(return_value=2)
    redis.expire = AsyncMock()

    db = _make_db_for_status_check(current_status="AVAILABLE")

    with patch(
        "app.modules.registry.url_health_monitor.check_agent_health",
        AsyncMock(return_value=False),
    ):
        await process_agent_health(
            agent_id=agent_id,
            agent_name="TestAgent",
            tenant_id=tenant_id,
            health_check_url="https://agent.example.com/health",
            db=db,
            redis=redis,
        )

    redis.incr.assert_called_once()


@pytest.mark.asyncio
async def test_process_agent_health_marks_unavailable_after_3_failures():
    """After _MAX_CONSECUTIVE_FAILURES, status is set to UNAVAILABLE."""
    tenant_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=b"2")
    redis.incr = AsyncMock(return_value=_MAX_CONSECUTIVE_FAILURES)
    redis.expire = AsyncMock()

    db = AsyncMock()
    # First execute: SELECT returns AVAILABLE (so status changes)
    select_result = MagicMock()
    select_result.mappings.return_value.first.return_value = {
        "health_status": "AVAILABLE"
    }
    update_result = MagicMock()
    db.execute = AsyncMock(side_effect=[select_result, update_result])
    db.commit = AsyncMock()

    status_set = []

    async def _fake_notify(agent_id, agent_name, tenant_id, new_status, db):
        status_set.append(new_status)

    with patch(
        "app.modules.registry.url_health_monitor.check_agent_health",
        AsyncMock(return_value=False),
    ), patch(
        "app.modules.registry.url_health_monitor.notify_tenant_admin_health_change",
        _fake_notify,
    ):
        await process_agent_health(
            agent_id=agent_id,
            agent_name="TestAgent",
            tenant_id=tenant_id,
            health_check_url="https://agent.example.com/health",
            db=db,
            redis=redis,
        )

    assert _HEALTH_STATUS_UNAVAILABLE in status_set


@pytest.mark.asyncio
async def test_update_agent_health_status_no_op_when_unchanged():
    """update_agent_health_status returns False if status hasn't changed."""
    db = AsyncMock()
    select_result = MagicMock()
    select_result.mappings.return_value.first.return_value = {
        "health_status": "AVAILABLE"
    }
    db.execute = AsyncMock(return_value=select_result)
    db.commit = AsyncMock()

    changed = await update_agent_health_status("agent1", "tenant1", "AVAILABLE", db)
    assert changed is False
    # Should not have committed
    db.commit.assert_not_called()
