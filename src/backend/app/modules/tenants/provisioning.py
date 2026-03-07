"""
Tenant provisioning state machine.

Manages the lifecycle of tenant provisioning through a deterministic state
machine: PENDING -> CREATING_DB -> CREATING_AUTH -> CONFIGURING -> ACTIVE.

On failure at any step, completed steps are rolled back in reverse order
and the state transitions to FAILED. A 600-second SLA timeout transitions
to TIMEOUT.

Concurrent provisioning for the same tenant_id is rejected via a
module-level registry.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Awaitable, Callable, Optional

import structlog

logger = structlog.get_logger(__name__)


class ProvisioningState(str, Enum):
    PENDING = "PENDING"
    CREATING_DB = "CREATING_DB"
    CREATING_AUTH = "CREATING_AUTH"
    CONFIGURING = "CONFIGURING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class InvalidStateError(Exception):
    """Raised on invalid state transitions."""

    pass


class ConcurrentProvisioningError(Exception):
    """Raised when same tenant_id is provisioned concurrently."""

    pass


@dataclass
class ProvisioningContext:
    tenant_id: str
    state: ProvisioningState = ProvisioningState.PENDING
    completed_steps: list[str] = field(default_factory=list)
    error: Optional[str] = None
    audit_log: list[dict] = field(default_factory=list)


# Module-level registry tracking active provisioning by tenant_id.
# Maps tenant_id -> current state string.
_active_provisioning: dict[str, str] = {}

# Lock protecting the check-and-set on _active_provisioning (H2: TOCTOU fix).
# Only held for the brief atomic check+register/deregister, not during provisioning.
_provisioning_registry_lock = asyncio.Lock()

# Provisioning SLA timeout in seconds.
_PROVISIONING_TIMEOUT_SECONDS = 600

# Ordered list of provisioning step names (matches ProvisioningState values).
_STEP_ORDER = ["CREATING_DB", "CREATING_AUTH", "CONFIGURING"]


class TenantProvisioningMachine:
    """State machine for tenant provisioning lifecycle."""

    VALID_TRANSITIONS: dict[ProvisioningState, list[ProvisioningState]] = {
        ProvisioningState.PENDING: [
            ProvisioningState.CREATING_DB,
            ProvisioningState.FAILED,
        ],
        ProvisioningState.CREATING_DB: [
            ProvisioningState.CREATING_AUTH,
            ProvisioningState.FAILED,
        ],
        ProvisioningState.CREATING_AUTH: [
            ProvisioningState.CONFIGURING,
            ProvisioningState.FAILED,
        ],
        ProvisioningState.CONFIGURING: [
            ProvisioningState.ACTIVE,
            ProvisioningState.FAILED,
        ],
        ProvisioningState.ACTIVE: [],
        ProvisioningState.FAILED: [ProvisioningState.PENDING],
        ProvisioningState.TIMEOUT: [ProvisioningState.PENDING],
    }

    def __init__(self, context: ProvisioningContext) -> None:
        self.context = context

    async def transition(self, new_state: ProvisioningState) -> None:
        """Validate and execute a state transition, logging to audit_log.

        Raises InvalidStateError if the transition is not allowed.
        """
        current = self.context.state
        valid_next = self.VALID_TRANSITIONS.get(current, [])

        if new_state not in valid_next:
            raise InvalidStateError(
                f"Invalid transition from {current.value} to {new_state.value}. "
                f"Valid transitions from {current.value}: {[s.value for s in valid_next]}"
            )

        self.context.state = new_state
        self.context.audit_log.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "state": new_state.value,
                "previous_state": current.value,
            }
        )
        logger.info(
            "provisioning_state_transition",
            tenant_id=self.context.tenant_id,
            from_state=current.value,
            to_state=new_state.value,
        )

    async def run_provisioning(
        self,
        steps: dict[str, Callable[..., Awaitable]],
        rollbacks: dict[str, Callable[..., Awaitable]],
    ) -> None:
        """Execute provisioning steps in order with rollback on failure.

        Args:
            steps: Mapping of step name to async callable for each phase.
            rollbacks: Mapping of step name to async rollback callable.

        The method checks for concurrent provisioning, enforces the 600s SLA
        timeout, and rolls back completed steps in reverse on any failure.
        """
        tenant_id = self.context.tenant_id

        # Concurrency guard (H2: atomic check-and-set via lock to prevent TOCTOU race)
        async with _provisioning_registry_lock:
            if tenant_id in _active_provisioning:
                raise ConcurrentProvisioningError(
                    f"Tenant {tenant_id} is already being provisioned "
                    f"(current state: {_active_provisioning[tenant_id]})"
                )
            _active_provisioning[tenant_id] = self.context.state.value
        start_time = time.monotonic()

        try:
            for step_name in _STEP_ORDER:
                # Check SLA timeout before each step
                elapsed = time.monotonic() - start_time
                if elapsed > _PROVISIONING_TIMEOUT_SECONDS:
                    # H1: capture previous_state BEFORE overwriting self.context.state
                    previous_state_value = self.context.state.value
                    self.context.state = ProvisioningState.TIMEOUT
                    self.context.error = (
                        f"Provisioning timed out after {elapsed:.1f}s "
                        f"(SLA: {_PROVISIONING_TIMEOUT_SECONDS}s)"
                    )
                    self.context.audit_log.append(
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "state": ProvisioningState.TIMEOUT.value,
                            "previous_state": previous_state_value,
                        }
                    )
                    logger.warning(
                        "provisioning_timeout",
                        tenant_id=tenant_id,
                        elapsed_seconds=elapsed,
                        sla_seconds=_PROVISIONING_TIMEOUT_SECONDS,
                    )
                    return

                target_state = ProvisioningState(step_name)
                await self.transition(target_state)
                _active_provisioning[tenant_id] = target_state.value

                try:
                    step_fn = steps[step_name]
                    await step_fn()
                    self.context.completed_steps.append(step_name)
                except Exception as exc:
                    error_msg = f"{step_name} failed: {exc}"
                    logger.error(
                        "provisioning_step_failed",
                        tenant_id=tenant_id,
                        step=step_name,
                        error=str(exc),
                    )
                    await self._rollback(rollbacks)
                    await self.transition(ProvisioningState.FAILED)
                    self.context.error = str(exc)
                    return

            # All steps completed successfully
            await self.transition(ProvisioningState.ACTIVE)
            logger.info(
                "provisioning_completed",
                tenant_id=tenant_id,
                completed_steps=self.context.completed_steps,
            )

        finally:
            _active_provisioning.pop(tenant_id, None)

    async def _rollback(
        self,
        rollbacks: dict[str, Callable[..., Awaitable]],
    ) -> None:
        """Execute rollback for all completed steps in reverse order."""
        for step_name in reversed(self.context.completed_steps):
            rollback_fn = rollbacks.get(step_name)
            if rollback_fn is None:
                logger.warning(
                    "provisioning_rollback_missing",
                    tenant_id=self.context.tenant_id,
                    step=step_name,
                )
                continue
            try:
                await rollback_fn()
                self.context.audit_log.append(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "action": "rollback",
                        "step": step_name,
                    }
                )
                logger.info(
                    "provisioning_rollback_executed",
                    tenant_id=self.context.tenant_id,
                    step=step_name,
                )
            except Exception as exc:
                logger.error(
                    "provisioning_rollback_failed",
                    tenant_id=self.context.tenant_id,
                    step=step_name,
                    error=str(exc),
                )
                self.context.audit_log.append(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "action": "rollback_failed",
                        "step": step_name,
                        "error": str(exc),
                    }
                )

    async def reset(self) -> None:
        """Reset state to PENDING. Only allowed from FAILED or TIMEOUT.

        Raises InvalidStateError if current state is not FAILED or TIMEOUT.
        """
        if self.context.state not in (
            ProvisioningState.FAILED,
            ProvisioningState.TIMEOUT,
        ):
            raise InvalidStateError(
                f"Cannot reset from {self.context.state.value}. "
                f"Reset is only allowed from FAILED or TIMEOUT."
            )
        await self.transition(ProvisioningState.PENDING)
        self.context.completed_steps.clear()
        self.context.error = None
        logger.info(
            "provisioning_reset",
            tenant_id=self.context.tenant_id,
        )
