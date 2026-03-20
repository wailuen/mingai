"""
Unit tests for SCHED-038: run_tenants_throttled semaphore throttle.

Tests:
- All tenants processed and results returned in correct order
- Max concurrency is respected (never more than N tasks in flight simultaneously)
- Failed tenants return Exception instances; other tenants still complete
- SCHEDULER_MAX_CONCURRENT_TENANTS env var controls the limit
- Invalid env var falls back to 5
- Empty tenant list returns empty result
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.core.scheduler.tenant_throttle import run_tenants_throttled


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_tenants_processed():
    """Every tenant_id in the input is passed to coro_factory and returned."""
    tenant_ids = ["t1", "t2", "t3", "t4", "t5"]
    calls = []

    async def factory(tid):
        calls.append(tid)
        return {"tenant": tid, "warmed": 1}

    results = await run_tenants_throttled(tenant_ids, factory, max_concurrent=3)

    assert len(results) == 5
    assert sorted(calls) == sorted(tenant_ids)
    # Results align positionally with input
    for i, result in enumerate(results):
        assert result["tenant"] == tenant_ids[i]


@pytest.mark.asyncio
async def test_concurrency_limited():
    """
    At no point should more than max_concurrent tasks be running simultaneously.
    Uses a shared counter to track the high-water mark.
    """
    max_concurrent = 3
    in_flight = [0]
    high_water = [0]

    async def factory(tid):
        in_flight[0] += 1
        if in_flight[0] > high_water[0]:
            high_water[0] = in_flight[0]
        await asyncio.sleep(0.01)  # simulate work
        in_flight[0] -= 1
        return tid

    tenant_ids = [f"t{i}" for i in range(10)]
    await run_tenants_throttled(tenant_ids, factory, max_concurrent=max_concurrent)

    assert high_water[0] <= max_concurrent, (
        f"Concurrency exceeded limit: {high_water[0]} > {max_concurrent}"
    )


@pytest.mark.asyncio
async def test_failed_tenant_returns_exception_not_raises():
    """
    A tenant whose coroutine raises returns an Exception in the results list.
    Other tenants still complete successfully.
    """
    async def factory(tid):
        if tid == "bad":
            raise ValueError("tenant connection failed")
        return {"tenant": tid, "ok": True}

    tenant_ids = ["good1", "bad", "good2"]
    results = await run_tenants_throttled(tenant_ids, factory, max_concurrent=5)

    assert len(results) == 3
    assert isinstance(results[0], dict) and results[0]["ok"] is True
    assert isinstance(results[1], ValueError)
    assert isinstance(results[2], dict) and results[2]["ok"] is True


@pytest.mark.asyncio
async def test_empty_tenant_list_returns_empty():
    """Empty input produces empty output without any coro_factory calls."""
    called = []

    async def factory(tid):
        called.append(tid)
        return tid

    results = await run_tenants_throttled([], factory, max_concurrent=5)

    assert results == []
    assert called == []


@pytest.mark.asyncio
async def test_env_var_controls_max_concurrent():
    """SCHEDULER_MAX_CONCURRENT_TENANTS env var is read when max_concurrent=None."""
    high_water = [0]
    in_flight = [0]

    async def factory(tid):
        in_flight[0] += 1
        if in_flight[0] > high_water[0]:
            high_water[0] = in_flight[0]
        await asyncio.sleep(0.01)
        in_flight[0] -= 1
        return tid

    with patch.dict("os.environ", {"SCHEDULER_MAX_CONCURRENT_TENANTS": "2"}):
        tenant_ids = [f"t{i}" for i in range(8)]
        await run_tenants_throttled(tenant_ids, factory)  # max_concurrent=None → reads env

    assert high_water[0] <= 2, (
        f"Concurrency exceeded env var limit: {high_water[0]} > 2"
    )


@pytest.mark.asyncio
async def test_invalid_env_var_falls_back_to_5():
    """When SCHEDULER_MAX_CONCURRENT_TENANTS is not a valid int, default of 5 is used."""
    high_water = [0]
    in_flight = [0]

    async def factory(tid):
        in_flight[0] += 1
        if in_flight[0] > high_water[0]:
            high_water[0] = in_flight[0]
        await asyncio.sleep(0.01)
        in_flight[0] -= 1
        return tid

    with patch.dict("os.environ", {"SCHEDULER_MAX_CONCURRENT_TENANTS": "not_a_number"}):
        tenant_ids = [f"t{i}" for i in range(20)]
        await run_tenants_throttled(tenant_ids, factory)

    # Default of 5 means high-water should be ≤ 5
    assert high_water[0] <= 5, (
        f"Concurrency exceeded default limit: {high_water[0]} > 5"
    )


@pytest.mark.asyncio
async def test_results_aligned_with_input_order():
    """
    Even though tasks run concurrently, the returned list is aligned with
    tenant_ids input order (not completion order).
    """
    import random

    async def factory(tid):
        # Random sleep to ensure tasks complete in arbitrary order
        await asyncio.sleep(random.uniform(0, 0.02))
        return f"result_{tid}"

    tenant_ids = [f"t{i}" for i in range(10)]
    results = await run_tenants_throttled(tenant_ids, factory, max_concurrent=5)

    for i, (tid, result) in enumerate(zip(tenant_ids, results)):
        assert result == f"result_{tid}", f"Position {i}: expected result_{tid}, got {result}"
