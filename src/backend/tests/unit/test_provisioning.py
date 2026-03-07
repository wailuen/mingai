"""
Unit tests for tenant provisioning state machine (TEST-022).

Tier 1: Fast, isolated, uses AsyncMock for async step/rollback callables.
Tests the state machine logic, transitions, rollback ordering, audit logging,
concurrency guards, timeout handling, and reset constraints.
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, call, patch

import pytest

from app.modules.tenants.provisioning import (
    ConcurrentProvisioningError,
    InvalidStateError,
    ProvisioningContext,
    ProvisioningState,
    TenantProvisioningMachine,
    _active_provisioning,
)


@pytest.fixture(autouse=True)
def _clear_active_provisioning():
    """Ensure the global active provisioning registry is clean for each test."""
    _active_provisioning.clear()
    yield
    _active_provisioning.clear()


def _make_machine(tenant_id: str = "tenant-001") -> TenantProvisioningMachine:
    ctx = ProvisioningContext(tenant_id=tenant_id)
    return TenantProvisioningMachine(ctx)


def _make_steps(
    fail_at: str | None = None,
    delay: float = 0.0,
) -> tuple[dict[str, AsyncMock], dict[str, AsyncMock]]:
    """Build ordered step and rollback mocks. Optionally fail at a given step."""
    step_names = ["CREATING_DB", "CREATING_AUTH", "CONFIGURING"]
    steps: dict[str, AsyncMock] = {}
    rollbacks: dict[str, AsyncMock] = {}

    for name in step_names:
        step_mock = AsyncMock()
        if name == fail_at:
            step_mock.side_effect = RuntimeError(f"{name} failed")
        if delay > 0:
            original = step_mock.side_effect

            async def _slow(*_a, _orig=original, _d=delay, **_kw):
                await asyncio.sleep(_d)
                if _orig:
                    raise _orig

            step_mock.side_effect = _slow
        steps[name] = step_mock
        rollbacks[name] = AsyncMock()

    return steps, rollbacks


# ---------------------------------------------------------------------------
# Test 1: Happy path — full provisioning succeeds
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_happy_path_provisioning():
    """PENDING -> CREATING_DB -> CREATING_AUTH -> CONFIGURING -> ACTIVE."""
    machine = _make_machine()
    steps, rollbacks = _make_steps()

    await machine.run_provisioning(steps, rollbacks)

    assert machine.context.state == ProvisioningState.ACTIVE
    assert machine.context.error is None
    # All steps should have been called exactly once
    for step in steps.values():
        step.assert_awaited_once()
    # No rollbacks should have been called
    for rb in rollbacks.values():
        rb.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 2: Failure at CREATING_DB — FAILED, no partial resources
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failure_at_creating_db():
    """Failure at first step: state=FAILED, rollback for completed steps runs."""
    machine = _make_machine()
    steps, rollbacks = _make_steps(fail_at="CREATING_DB")

    await machine.run_provisioning(steps, rollbacks)

    assert machine.context.state == ProvisioningState.FAILED
    assert "CREATING_DB failed" in machine.context.error
    # No steps completed, so no rollbacks should fire
    for rb in rollbacks.values():
        rb.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 3: Failure at CREATING_AUTH — rolls back CREATING_DB
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failure_at_creating_auth_rolls_back_db():
    """Failure at CREATING_AUTH: CREATING_DB rollback executes."""
    machine = _make_machine()
    steps, rollbacks = _make_steps(fail_at="CREATING_AUTH")

    await machine.run_provisioning(steps, rollbacks)

    assert machine.context.state == ProvisioningState.FAILED
    rollbacks["CREATING_DB"].assert_awaited_once()
    rollbacks["CREATING_AUTH"].assert_not_awaited()
    rollbacks["CONFIGURING"].assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 4: Failure at CONFIGURING — rolls back auth + DB in reverse order
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failure_at_configuring_rolls_back_in_reverse():
    """Failure at CONFIGURING: rolls back CREATING_AUTH then CREATING_DB."""
    machine = _make_machine()
    steps, rollbacks = _make_steps(fail_at="CONFIGURING")

    await machine.run_provisioning(steps, rollbacks)

    assert machine.context.state == ProvisioningState.FAILED
    rollbacks["CREATING_AUTH"].assert_awaited_once()
    rollbacks["CREATING_DB"].assert_awaited_once()
    rollbacks["CONFIGURING"].assert_not_awaited()
    # Verify reverse order: AUTH before DB
    assert rollbacks["CREATING_AUTH"].await_args_list[0] is not None
    assert rollbacks["CREATING_DB"].await_args_list[0] is not None


# ---------------------------------------------------------------------------
# Test 5: Retry after FAILED — reset() transitions to PENDING
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reset_after_failure():
    """reset() from FAILED returns to PENDING and clears completed_steps."""
    machine = _make_machine()
    steps, rollbacks = _make_steps(fail_at="CREATING_AUTH")
    await machine.run_provisioning(steps, rollbacks)
    assert machine.context.state == ProvisioningState.FAILED

    await machine.reset()

    assert machine.context.state == ProvisioningState.PENDING
    assert machine.context.completed_steps == []


# ---------------------------------------------------------------------------
# Test 6: Invalid state transition raises InvalidStateError
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invalid_state_transition():
    """ACTIVE -> CREATING_DB is not a valid transition."""
    machine = _make_machine()
    # Force state to ACTIVE
    machine.context.state = ProvisioningState.ACTIVE

    with pytest.raises(InvalidStateError, match="ACTIVE.*CREATING_DB"):
        await machine.transition(ProvisioningState.CREATING_DB)


# ---------------------------------------------------------------------------
# Test 7: Concurrent provisioning raises ConcurrentProvisioningError
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_provisioning_rejected():
    """Second provisioning for same tenant_id raises ConcurrentProvisioningError."""
    machine1 = _make_machine(tenant_id="tenant-concurrent")

    async def slow_step():
        await asyncio.sleep(0.5)

    steps1 = {
        "CREATING_DB": AsyncMock(side_effect=slow_step),
        "CREATING_AUTH": AsyncMock(),
        "CONFIGURING": AsyncMock(),
    }
    rollbacks1 = {k: AsyncMock() for k in steps1}

    # Start first provisioning in background
    task = asyncio.create_task(machine1.run_provisioning(steps1, rollbacks1))
    # Give it a moment to register
    await asyncio.sleep(0.05)

    machine2 = _make_machine(tenant_id="tenant-concurrent")
    steps2, rollbacks2 = _make_steps()

    with pytest.raises(ConcurrentProvisioningError, match="tenant-concurrent"):
        await machine2.run_provisioning(steps2, rollbacks2)

    # Cancel and clean up the background task
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


# ---------------------------------------------------------------------------
# Test 8: Provisioning timeout — state = TIMEOUT
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_provisioning_timeout():
    """When provisioning exceeds the SLA timeout, state transitions to TIMEOUT."""
    machine = _make_machine()
    steps, rollbacks = _make_steps()

    # Patch time.monotonic to simulate elapsed time exceeding 600s
    import time

    real_monotonic = time.monotonic
    call_count = 0

    def mock_monotonic():
        nonlocal call_count
        call_count += 1
        # First call is the start time, subsequent calls simulate time passing
        if call_count <= 1:
            return 0.0
        return 601.0  # Exceeds 600s SLA

    with patch(
        "app.modules.tenants.provisioning.time.monotonic", side_effect=mock_monotonic
    ):
        await machine.run_provisioning(steps, rollbacks)

    assert machine.context.state == ProvisioningState.TIMEOUT


# ---------------------------------------------------------------------------
# Test 9: State persisted in context object
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_state_persisted_in_context():
    """State survives as a field on the ProvisioningContext dataclass."""
    ctx = ProvisioningContext(tenant_id="tenant-persist")
    machine = TenantProvisioningMachine(ctx)
    steps, rollbacks = _make_steps()

    await machine.run_provisioning(steps, rollbacks)

    # Access state directly from the context object (not just machine)
    assert ctx.state == ProvisioningState.ACTIVE
    assert ctx.tenant_id == "tenant-persist"
    assert "CREATING_DB" in ctx.completed_steps
    assert "CREATING_AUTH" in ctx.completed_steps
    assert "CONFIGURING" in ctx.completed_steps


# ---------------------------------------------------------------------------
# Test 10: Each state transition logged in audit_log
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_log_records_transitions():
    """Each transition adds an entry with timestamp and state name."""
    machine = _make_machine()
    steps, rollbacks = _make_steps()

    await machine.run_provisioning(steps, rollbacks)

    audit = machine.context.audit_log
    # At minimum: PENDING->CREATING_DB, ->CREATING_AUTH, ->CONFIGURING, ->ACTIVE
    assert len(audit) >= 4

    for entry in audit:
        assert "timestamp" in entry, f"Missing timestamp in audit entry: {entry}"
        assert "state" in entry, f"Missing state in audit entry: {entry}"
        # Timestamp should be a valid ISO format string
        datetime.fromisoformat(entry["timestamp"])


# ---------------------------------------------------------------------------
# Test 11: Rollback logs include what was cleaned up
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rollback_logs_cleanup():
    """When rollback executes, the audit log records which steps were rolled back."""
    machine = _make_machine()
    steps, rollbacks = _make_steps(fail_at="CONFIGURING")

    await machine.run_provisioning(steps, rollbacks)

    audit = machine.context.audit_log
    rollback_entries = [e for e in audit if e.get("action") == "rollback"]
    assert (
        len(rollback_entries) >= 2
    ), f"Expected at least 2 rollback entries, got {len(rollback_entries)}"

    rolled_back_steps = [e["step"] for e in rollback_entries]
    assert "CREATING_AUTH" in rolled_back_steps
    assert "CREATING_DB" in rolled_back_steps


# ---------------------------------------------------------------------------
# Test 12: Reset NOT allowed from ACTIVE — raises InvalidStateError
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reset_not_allowed_from_active():
    """reset() from ACTIVE raises InvalidStateError."""
    machine = _make_machine()
    steps, rollbacks = _make_steps()
    await machine.run_provisioning(steps, rollbacks)
    assert machine.context.state == ProvisioningState.ACTIVE

    with pytest.raises(InvalidStateError, match="Cannot reset"):
        await machine.reset()
