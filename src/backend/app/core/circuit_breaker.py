"""
LLM Circuit Breaker — INFRA-055.

Per-tenant, per-LLM-slot circuit breaker that prevents cascading failures
when an LLM deployment is degraded or unavailable.

States:
    CLOSED    — Normal operation.  All requests pass through.
    OPEN      — Failing state.  All requests are rejected immediately.
                Transitions to HALF_OPEN after RESET_TIMEOUT_SECONDS.
    HALF_OPEN — Recovery probe.  A limited window of requests are allowed.
                3 consecutive successes → CLOSED.
                Any failure → OPEN (resets the timeout).

Thresholds:
    FAILURE_RATE_THRESHOLD   — 0.50 (50 %)
    MIN_REQUESTS_TO_EVALUATE — 5  (circuit never opens on <5 total requests)
    CONSECUTIVE_SUCCESSES    — 3  (needed in HALF_OPEN to close the circuit)
    RESET_TIMEOUT_SECONDS    — 60 (seconds in OPEN before probing)
    WINDOW_SECONDS           — 60 (sliding window for failure rate calculation)

Storage:
    Redis hash key: mingai:{tenant_id}:cb:{slot}
    Fields:
        state               — "closed" | "open" | "half_open"
        open_at             — Unix timestamp when circuit opened (float as str)
        half_open_successes — consecutive success counter in HALF_OPEN
        window_requests     — total requests in current sliding window
        window_failures     — failures in current sliding window
        window_start        — Unix timestamp when window opened
"""
import time
from typing import Literal

import structlog

from app.core.redis_client import build_redis_key, get_redis

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FAILURE_RATE_THRESHOLD: float = 0.50
MIN_REQUESTS_TO_EVALUATE: int = 5
CONSECUTIVE_SUCCESSES_TO_CLOSE: int = 3
RESET_TIMEOUT_SECONDS: int = 60
WINDOW_SECONDS: int = 60

CBState = Literal["closed", "open", "half_open"]

_STATE_CLOSED = "closed"
_STATE_OPEN = "open"
_STATE_HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Redis-backed circuit breaker for per-tenant, per-LLM-slot protection.

    All methods are async because they perform Redis I/O.

    Usage::

        cb = CircuitBreaker()

        if await cb.is_open(tenant_id, slot):
            raise HTTPException(503, "LLM service temporarily unavailable")

        try:
            result = await call_llm(...)
            await cb.record_success(tenant_id, slot)
        except LLMError:
            await cb.record_failure(tenant_id, slot)
            raise
    """

    def __init__(self, redis_client=None):
        """
        Construct a CircuitBreaker.

        Args:
            redis_client: Optional injected Redis client (for testing).
                          If None, uses the global get_redis() singleton.
        """
        self._redis = redis_client

    def _redis_client(self):
        """Return the Redis client to use."""
        return self._redis if self._redis is not None else get_redis()

    def _redis_key(self, tenant_id: str, slot: str) -> str:
        """Build the Redis hash key for this tenant+slot circuit breaker."""
        # slot may contain characters like '-' but not ':'
        # validate slot doesn't have colons
        if ":" in slot:
            raise ValueError(f"slot must not contain colons: {slot!r}")
        return build_redis_key(tenant_id, "cb", slot)

    async def get_state(self, tenant_id: str, slot: str) -> CBState:
        """
        Return current circuit state for the given tenant+slot.

        Transitions OPEN → HALF_OPEN automatically when RESET_TIMEOUT_SECONDS
        has elapsed since the circuit opened.

        Returns "closed" if no state record exists (first call).
        """
        redis = self._redis_client()
        key = self._redis_key(tenant_id, slot)

        data = await redis.hgetall(key)
        if not data:
            return _STATE_CLOSED

        state = data.get("state", _STATE_CLOSED)

        if state == _STATE_OPEN:
            open_at = float(data.get("open_at", "0"))
            if time.time() - open_at >= RESET_TIMEOUT_SECONDS:
                # Transition to HALF_OPEN — reset success counter
                await redis.hset(
                    key,
                    mapping={
                        "state": _STATE_HALF_OPEN,
                        "half_open_successes": "0",
                    },
                )
                logger.info(
                    "circuit_breaker_transition",
                    tenant_id=tenant_id,
                    slot=slot,
                    from_state=_STATE_OPEN,
                    to_state=_STATE_HALF_OPEN,
                )
                return _STATE_HALF_OPEN

        return state  # type: ignore[return-value]

    async def is_open(self, tenant_id: str, slot: str) -> bool:
        """
        Return True if requests to this slot should be rejected.

        Returns True in OPEN state.
        Returns False in CLOSED or HALF_OPEN state (HALF_OPEN allows probes).
        """
        state = await self.get_state(tenant_id, slot)
        return state == _STATE_OPEN

    async def record_success(self, tenant_id: str, slot: str) -> None:
        """
        Record a successful LLM call for the given tenant+slot.

        In HALF_OPEN: increments consecutive success counter.
            When counter reaches CONSECUTIVE_SUCCESSES_TO_CLOSE, transitions
            to CLOSED and resets all window counters.

        In CLOSED / OPEN: increments the sliding-window request counter.
            The window is NOT reset by successes in CLOSED state.
        """
        redis = self._redis_client()
        key = self._redis_key(tenant_id, slot)

        state = await self.get_state(tenant_id, slot)

        if state == _STATE_HALF_OPEN:
            successes = int((await redis.hget(key, "half_open_successes")) or "0") + 1

            if successes >= CONSECUTIVE_SUCCESSES_TO_CLOSE:
                # Circuit healed — reset everything
                await redis.hset(
                    key,
                    mapping={
                        "state": _STATE_CLOSED,
                        "open_at": "0",
                        "half_open_successes": "0",
                        "window_requests": "0",
                        "window_failures": "0",
                        "window_start": str(time.time()),
                    },
                )
                logger.info(
                    "circuit_breaker_transition",
                    tenant_id=tenant_id,
                    slot=slot,
                    from_state=_STATE_HALF_OPEN,
                    to_state=_STATE_CLOSED,
                    consecutive_successes=successes,
                )
            else:
                await redis.hset(key, "half_open_successes", str(successes))
            return

        # CLOSED state: update sliding window
        await self._update_window(redis, key, success=True)

    async def record_failure(self, tenant_id: str, slot: str) -> None:
        """
        Record a failed LLM call for the given tenant+slot.

        In HALF_OPEN: immediately transitions back to OPEN (resets timeout).

        In CLOSED: updates the sliding window and evaluates whether the
            failure rate exceeds the threshold.  Opens the circuit if it does.
        """
        redis = self._redis_client()
        key = self._redis_key(tenant_id, slot)

        state = await self.get_state(tenant_id, slot)

        if state == _STATE_HALF_OPEN:
            # Any failure in HALF_OPEN re-opens the circuit
            await redis.hset(
                key,
                mapping={
                    "state": _STATE_OPEN,
                    "open_at": str(time.time()),
                    "half_open_successes": "0",
                },
            )
            logger.warning(
                "circuit_breaker_transition",
                tenant_id=tenant_id,
                slot=slot,
                from_state=_STATE_HALF_OPEN,
                to_state=_STATE_OPEN,
                reason="failure_during_probe",
            )
            return

        # CLOSED state: update sliding window then evaluate
        window_requests, window_failures = await self._update_window(
            redis, key, success=False
        )

        if (
            window_requests >= MIN_REQUESTS_TO_EVALUATE
            and window_failures / window_requests > FAILURE_RATE_THRESHOLD
        ):
            await redis.hset(
                key,
                mapping={
                    "state": _STATE_OPEN,
                    "open_at": str(time.time()),
                    "half_open_successes": "0",
                },
            )
            logger.warning(
                "circuit_breaker_transition",
                tenant_id=tenant_id,
                slot=slot,
                from_state=_STATE_CLOSED,
                to_state=_STATE_OPEN,
                window_requests=window_requests,
                window_failures=window_failures,
                failure_rate=round(window_failures / window_requests, 3),
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _update_window(
        self,
        redis,
        key: str,
        success: bool,
    ) -> tuple[int, int]:
        """
        Update the sliding-window counters in Redis and return (requests, failures).

        Resets the window when WINDOW_SECONDS has elapsed since window_start.
        """
        data = await redis.hgetall(key)

        now = time.time()
        window_start = float(data.get("window_start", "0"))

        if now - window_start >= WINDOW_SECONDS:
            # Window expired — start fresh
            window_requests = 1
            window_failures = 0 if success else 1
            await redis.hset(
                key,
                mapping={
                    "window_start": str(now),
                    "window_requests": str(window_requests),
                    "window_failures": str(window_failures),
                },
            )
        else:
            window_requests = int(data.get("window_requests", "0")) + 1
            window_failures = int(data.get("window_failures", "0")) + (
                0 if success else 1
            )
            await redis.hset(
                key,
                mapping={
                    "window_requests": str(window_requests),
                    "window_failures": str(window_failures),
                },
            )

        return window_requests, window_failures


# ---------------------------------------------------------------------------
# Module-level singleton (lazy, for production use)
# ---------------------------------------------------------------------------

_circuit_breaker: CircuitBreaker | None = None


def get_circuit_breaker() -> CircuitBreaker:
    """Return the global CircuitBreaker singleton."""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker()
    return _circuit_breaker
