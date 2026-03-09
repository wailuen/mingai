"""
Unit tests for INFRA-055 — LLM Circuit Breaker.

Verifies state machine transitions:
  CLOSED → OPEN when failure_rate > 50% with >= 5 requests
  OPEN → HALF_OPEN when RESET_TIMEOUT_SECONDS elapsed
  HALF_OPEN → CLOSED on 3 consecutive successes
  HALF_OPEN → OPEN on any failure
  CLOSED stays CLOSED on successes and low failure rates
"""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_redis_mock(initial_data: dict | None = None):
    """Build an async Redis mock that simulates hgetall/hset/hget."""
    store: dict = dict(initial_data or {})

    async def hgetall(key):
        return dict(store)

    async def hset(key, *args, mapping=None, **kwargs):
        if mapping:
            store.update(mapping)
        elif args:
            # hset(key, field, value)
            if len(args) == 2:
                store[args[0]] = args[1]

    async def hget(key, field):
        return store.get(field)

    mock = AsyncMock()
    mock.hgetall = hgetall
    mock.hset = hset
    mock.hget = hget
    return mock, store


class TestCircuitBreakerClosed:
    """CLOSED state — normal operation."""

    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self):
        from app.core.circuit_breaker import CircuitBreaker

        redis_mock, _ = _make_redis_mock({})
        cb = CircuitBreaker(redis_client=redis_mock)

        state = await cb.get_state("tenant1", "primary")
        assert state == "closed"

    @pytest.mark.asyncio
    async def test_is_open_returns_false_when_closed(self):
        from app.core.circuit_breaker import CircuitBreaker

        redis_mock, _ = _make_redis_mock({})
        cb = CircuitBreaker(redis_client=redis_mock)

        assert await cb.is_open("tenant1", "primary") is False

    @pytest.mark.asyncio
    async def test_circuit_stays_closed_below_threshold(self):
        """4 failures out of 4 requests — below MIN_REQUESTS_TO_EVALUATE=5."""
        from app.core.circuit_breaker import CircuitBreaker

        redis_mock, store = _make_redis_mock(
            {
                "state": "closed",
                "window_start": str(time.time()),
                "window_requests": "4",
                "window_failures": "4",
            }
        )
        cb = CircuitBreaker(redis_client=redis_mock)

        await cb.record_failure("tenant1", "primary")

        # 5 requests, 5 failures = 100% > 50% — should open
        # But let's test the 4-request case stays closed
        store.update(
            {
                "state": "closed",
                "window_requests": "4",
                "window_failures": "3",
                "window_start": str(time.time()),
            }
        )
        # Re-instantiate to get fresh store reference
        redis_mock2, store2 = _make_redis_mock(
            {
                "state": "closed",
                "window_start": str(time.time()),
                "window_requests": "3",
                "window_failures": "2",
            }
        )
        cb2 = CircuitBreaker(redis_client=redis_mock2)
        # 4 total requests, 3 failures = 75% but only 4 requests < 5 min
        await cb2.record_failure("tenant1", "primary")
        assert store2.get("state", "closed") == "closed"

    @pytest.mark.asyncio
    async def test_circuit_opens_when_failure_rate_exceeds_threshold(self):
        """5 requests, 4 failures (80%) → OPEN."""
        from app.core.circuit_breaker import CircuitBreaker

        redis_mock, store = _make_redis_mock(
            {
                "state": "closed",
                "window_start": str(time.time()),
                "window_requests": "4",
                "window_failures": "4",
            }
        )
        cb = CircuitBreaker(redis_client=redis_mock)

        # 5th request is also a failure → 5/5 = 100% > 50%
        await cb.record_failure("tenant1", "primary")

        assert store.get("state") == "open"
        assert "open_at" in store

    @pytest.mark.asyncio
    async def test_circuit_stays_closed_on_successes(self):
        from app.core.circuit_breaker import CircuitBreaker

        redis_mock, store = _make_redis_mock(
            {
                "state": "closed",
                "window_start": str(time.time()),
                "window_requests": "10",
                "window_failures": "1",
            }
        )
        cb = CircuitBreaker(redis_client=redis_mock)

        await cb.record_success("tenant1", "primary")

        assert store.get("state", "closed") == "closed"


class TestCircuitBreakerOpen:
    """OPEN state — all requests rejected."""

    @pytest.mark.asyncio
    async def test_is_open_returns_true_when_open(self):
        from app.core.circuit_breaker import CircuitBreaker

        redis_mock, _ = _make_redis_mock(
            {
                "state": "open",
                "open_at": str(time.time()),
            }
        )
        cb = CircuitBreaker(redis_client=redis_mock)

        assert await cb.is_open("tenant1", "primary") is True

    @pytest.mark.asyncio
    async def test_open_transitions_to_half_open_after_timeout(self):
        """After RESET_TIMEOUT_SECONDS, OPEN → HALF_OPEN."""
        from app.core.circuit_breaker import (
            CircuitBreaker,
            RESET_TIMEOUT_SECONDS,
        )

        # open_at far in the past
        past = time.time() - RESET_TIMEOUT_SECONDS - 1
        redis_mock, store = _make_redis_mock(
            {
                "state": "open",
                "open_at": str(past),
            }
        )
        cb = CircuitBreaker(redis_client=redis_mock)

        state = await cb.get_state("tenant1", "primary")
        assert state == "half_open"
        assert store.get("state") == "half_open"

    @pytest.mark.asyncio
    async def test_open_stays_open_before_timeout(self):
        from app.core.circuit_breaker import CircuitBreaker

        redis_mock, _ = _make_redis_mock(
            {
                "state": "open",
                "open_at": str(time.time()),  # just opened
            }
        )
        cb = CircuitBreaker(redis_client=redis_mock)

        state = await cb.get_state("tenant1", "primary")
        assert state == "open"


class TestCircuitBreakerHalfOpen:
    """HALF_OPEN state — probe requests."""

    @pytest.mark.asyncio
    async def test_half_open_to_closed_on_consecutive_successes(self):
        """3 consecutive successes in HALF_OPEN → CLOSED."""
        from app.core.circuit_breaker import (
            CircuitBreaker,
            CONSECUTIVE_SUCCESSES_TO_CLOSE,
        )

        redis_mock, store = _make_redis_mock(
            {
                "state": "half_open",
                "half_open_successes": str(CONSECUTIVE_SUCCESSES_TO_CLOSE - 1),
            }
        )
        cb = CircuitBreaker(redis_client=redis_mock)

        # One more success completes the required count
        await cb.record_success("tenant1", "primary")

        assert store.get("state") == "closed"

    @pytest.mark.asyncio
    async def test_half_open_to_open_on_failure(self):
        """Any failure in HALF_OPEN → OPEN."""
        from app.core.circuit_breaker import CircuitBreaker

        redis_mock, store = _make_redis_mock(
            {
                "state": "half_open",
                "half_open_successes": "2",
            }
        )
        cb = CircuitBreaker(redis_client=redis_mock)

        await cb.record_failure("tenant1", "primary")

        assert store.get("state") == "open"
        assert "open_at" in store

    @pytest.mark.asyncio
    async def test_half_open_increments_success_counter(self):
        """Partial successes increment the counter without closing the circuit."""
        from app.core.circuit_breaker import CircuitBreaker

        redis_mock, store = _make_redis_mock(
            {
                "state": "half_open",
                "half_open_successes": "0",
            }
        )
        cb = CircuitBreaker(redis_client=redis_mock)

        await cb.record_success("tenant1", "primary")

        # Not enough to close — counter incremented
        assert store.get("state") == "half_open"
        assert int(store.get("half_open_successes", "0")) == 1


class TestCircuitBreakerWindowReset:
    """Sliding window resets after WINDOW_SECONDS."""

    @pytest.mark.asyncio
    async def test_window_resets_on_expiry(self):
        """After WINDOW_SECONDS, window counters reset on next call."""
        from app.core.circuit_breaker import CircuitBreaker, WINDOW_SECONDS

        old_start = time.time() - WINDOW_SECONDS - 1
        redis_mock, store = _make_redis_mock(
            {
                "state": "closed",
                "window_start": str(old_start),
                "window_requests": "100",
                "window_failures": "90",
            }
        )
        cb = CircuitBreaker(redis_client=redis_mock)

        # A success triggers window reset
        await cb.record_success("tenant1", "primary")

        # After reset, requests count should be 1 (just this call)
        assert int(store.get("window_requests", "0")) == 1
        assert int(store.get("window_failures", "0")) == 0


class TestCircuitBreakerRedisKeyValidation:
    """Redis key construction validates slot for colons."""

    def test_slot_with_colon_raises(self):
        from app.core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(redis_client=MagicMock())

        with pytest.raises(ValueError, match="colons"):
            cb._redis_key("tenant1", "slot:with:colon")

    def test_valid_slot_builds_key(self):
        from app.core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(redis_client=MagicMock())

        key = cb._redis_key("tenant-abc", "primary")
        assert key == "mingai:tenant-abc:cb:primary"


class TestBuildReadyResponse:
    """build_ready_response includes circuit breaker state (INFRA-055)."""

    def test_ready_when_all_ok_no_open_circuits(self):
        from app.core.health import build_ready_response

        resp = build_ready_response(
            database_ok=True,
            redis_ok=True,
            circuit_breakers={"acme:primary": "closed"},
        )
        assert resp["status"] == "ready"
        assert resp["open_circuits"] == []

    def test_degraded_when_circuit_open(self):
        from app.core.health import build_ready_response

        resp = build_ready_response(
            database_ok=True,
            redis_ok=True,
            circuit_breakers={"acme:primary": "open"},
        )
        assert resp["status"] == "degraded"
        assert "acme:primary" in resp["open_circuits"]

    def test_not_ready_when_db_down(self):
        from app.core.health import build_ready_response

        resp = build_ready_response(
            database_ok=False,
            redis_ok=True,
            circuit_breakers={},
        )
        assert resp["status"] == "not_ready"

    def test_degraded_when_redis_down(self):
        from app.core.health import build_ready_response

        resp = build_ready_response(
            database_ok=True,
            redis_ok=False,
            circuit_breakers={},
        )
        assert resp["status"] == "degraded"

    def test_circuit_breakers_in_response(self):
        from app.core.health import build_ready_response

        cb_map = {"t1:primary": "closed", "t2:primary": "half_open"}
        resp = build_ready_response(
            database_ok=True,
            redis_ok=True,
            circuit_breakers=cb_map,
        )
        assert resp["circuit_breakers"] == cb_map

    def test_version_present(self):
        from app.core.health import build_ready_response

        resp = build_ready_response(database_ok=True, redis_ok=True)
        assert "version" in resp
        assert resp["version"]
