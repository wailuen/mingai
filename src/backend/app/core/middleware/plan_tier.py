"""
Plan tier enforcement decorator (TODO-32).

Provides `require_plan` — a FastAPI dependency factory that gates access
to an endpoint based on the calling user's JWT `plan` claim.

Usage::

    from app.core.middleware.plan_tier import require_plan

    @router.post("/byollm")
    async def set_byollm(
        current_user: CurrentUser = Depends(require_plan("enterprise")),
        ...
    ):
        ...

    # Allow multiple tiers
    @router.get("/llm-profiles")
    async def list_profiles(
        current_user: CurrentUser = Depends(require_plan("professional", "enterprise")),
        ...
    ):
        ...

Security invariant:
    The 403 response MUST NOT disclose what plan is required or what plan the
    caller has. The message is intentionally generic.
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import Depends, HTTPException, status

from app.core.dependencies import CurrentUser, require_tenant_admin

logger = structlog.get_logger()

# Plans in order from lowest to highest
_PLAN_ORDER = ("starter", "professional", "enterprise")

_GENERIC_PLAN_ERROR = "Your current plan does not include this feature."


def require_plan(*allowed_plans: str):
    """Return a FastAPI dependency that enforces plan tier access.

    The returned dependency also implicitly requires tenant_admin role
    (it builds on require_tenant_admin).

    Args:
        *allowed_plans: One or more plan strings ("starter", "professional",
                        "enterprise"). At least one must be provided.

    Returns:
        A FastAPI dependency (callable that yields CurrentUser).

    Raises:
        ValueError: If no allowed plans are provided.
        HTTPException(403): If the caller's plan is not in allowed_plans.
    """
    if not allowed_plans:
        raise ValueError("require_plan() requires at least one plan tier argument")

    _allowed = frozenset(allowed_plans)

    async def _dependency(
        current_user: CurrentUser = Depends(require_tenant_admin),
    ) -> CurrentUser:
        caller_plan = getattr(current_user, "plan", None) or ""
        if caller_plan not in _allowed:
            logger.info(
                "plan_tier_access_denied",
                user_id=current_user.id,
                tenant_id=current_user.tenant_id,
                # Do NOT log the required plan — that would expose the gate
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_GENERIC_PLAN_ERROR,
            )
        return current_user

    return _dependency


def require_plan_or_above(minimum_plan: str):
    """Return a dependency that requires ``minimum_plan`` OR any higher tier.

    Plan order: starter < professional < enterprise.

    Args:
        minimum_plan: The lowest acceptable plan tier.

    Returns:
        A FastAPI dependency (callable that yields CurrentUser).
    """
    if minimum_plan not in _PLAN_ORDER:
        raise ValueError(
            f"Unknown plan '{minimum_plan}'. Must be one of {_PLAN_ORDER}"
        )
    min_idx = _PLAN_ORDER.index(minimum_plan)
    allowed = tuple(_PLAN_ORDER[min_idx:])
    return require_plan(*allowed)
