"""
Onboarding wizard persistence API (TA-031).

Endpoints:
- GET  /admin/onboarding/status   — get current onboarding progress
- PATCH /admin/onboarding/progress — mark a step complete/incomplete
- PATCH /admin/onboarding/dismiss  — dismiss the onboarding banner for 7 days

Progress is stored in tenant_configs with config_type='onboarding_progress'.
Dismiss is stored in tenant_configs with config_type='onboarding_dismiss'.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin-onboarding"])

# Ordered list of wizard steps
_ORDERED_STEPS = [
    "invite_users",
    "configure_kb",
    "configure_agent",
    "configure_sso",
    "done",
]
_VALID_STEPS = frozenset(_ORDERED_STEPS)

_ONBOARDING_CONFIG_TYPE = "onboarding_progress"
_DISMISS_CONFIG_TYPE = "onboarding_dismiss"
_DISMISS_DAYS = 7


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class OnboardingStatusResponse(BaseModel):
    current_step: str
    completed: bool
    steps: dict
    dismissed_until: Optional[str] = None


class PatchOnboardingProgressRequest(BaseModel):
    step: str = Field(
        ...,
        description="One of: invite_users, configure_kb, configure_agent, configure_sso, done",
    )
    completed: bool

    @field_validator("step")
    @classmethod
    def step_must_be_valid(cls, v: str) -> str:
        if v not in _VALID_STEPS:
            raise ValueError(f"step must be one of: {', '.join(_ORDERED_STEPS)}")
        return v


# ---------------------------------------------------------------------------
# DB helpers (mockable in unit tests)
# ---------------------------------------------------------------------------


def _compute_current_step(steps: dict) -> str:
    """Return the first incomplete step (in order). If all done, returns 'done'."""
    for step in _ORDERED_STEPS:
        if not steps.get(step, False):
            return step
    return "done"


async def get_onboarding_status_db(tenant_id: str, db) -> dict:
    """
    Load onboarding progress from tenant_configs.

    Returns a dict with keys: steps (dict), dismissed_until (str or None).
    """
    progress_result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tenant_id AND config_type = :config_type LIMIT 1"
        ),
        {"tenant_id": tenant_id, "config_type": _ONBOARDING_CONFIG_TYPE},
    )
    progress_row = progress_result.fetchone()

    default_steps = {s: False for s in _ORDERED_STEPS}
    if progress_row and progress_row[0]:
        stored = progress_row[0]
        if isinstance(stored, str):
            stored = json.loads(stored)
        # Only take recognised keys; default missing ones to False
        steps = {s: bool(stored.get(s, False)) for s in _ORDERED_STEPS}
    else:
        steps = default_steps

    dismiss_result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tenant_id AND config_type = :config_type LIMIT 1"
        ),
        {"tenant_id": tenant_id, "config_type": _DISMISS_CONFIG_TYPE},
    )
    dismiss_row = dismiss_result.fetchone()
    dismissed_until: Optional[str] = None
    if dismiss_row and dismiss_row[0]:
        dismiss_data = dismiss_row[0]
        if isinstance(dismiss_data, str):
            dismiss_data = json.loads(dismiss_data)
        dismissed_until = dismiss_data.get("dismissed_until")

    return {"steps": steps, "dismissed_until": dismissed_until}


async def upsert_onboarding_step_db(
    tenant_id: str,
    step: str,
    completed: bool,
    db,
) -> dict:
    """
    Set a single step's completed flag and persist.

    Returns updated steps dict.
    """
    current = await get_onboarding_status_db(tenant_id, db)
    steps = current["steps"]
    steps[step] = completed

    await db.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (:id, :tenant_id, :config_type, CAST(:config_data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) DO UPDATE SET config_data = CAST(:config_data AS jsonb)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "config_type": _ONBOARDING_CONFIG_TYPE,
            "config_data": json.dumps(steps),
        },
    )
    await db.commit()

    logger.info(
        "onboarding_step_updated",
        tenant_id=tenant_id,
        step=step,
        completed=completed,
    )

    return steps


async def dismiss_onboarding_db(tenant_id: str, db) -> str:
    """
    Set dismissed_until to now + 7 days in tenant_configs.

    Returns the ISO-format dismissed_until timestamp.
    """
    dismissed_until = (
        datetime.now(timezone.utc) + timedelta(days=_DISMISS_DAYS)
    ).isoformat()

    await db.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (:id, :tenant_id, :config_type, CAST(:config_data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) DO UPDATE SET config_data = CAST(:config_data AS jsonb)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "config_type": _DISMISS_CONFIG_TYPE,
            "config_data": json.dumps({"dismissed_until": dismissed_until}),
        },
    )
    await db.commit()

    logger.info(
        "onboarding_dismissed", tenant_id=tenant_id, dismissed_until=dismissed_until
    )

    return dismissed_until


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/onboarding/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> OnboardingStatusResponse:
    """TA-031: Get onboarding wizard progress for this tenant."""
    data = await get_onboarding_status_db(current_user.tenant_id, db)
    steps = data["steps"]
    dismissed_until = data["dismissed_until"]

    current_step = _compute_current_step(steps)
    all_completed = all(steps.get(s, False) for s in _ORDERED_STEPS)

    return OnboardingStatusResponse(
        current_step=current_step,
        completed=all_completed,
        steps=steps,
        dismissed_until=dismissed_until,
    )


@router.patch("/onboarding/progress", response_model=OnboardingStatusResponse)
async def patch_onboarding_progress(
    request: PatchOnboardingProgressRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> OnboardingStatusResponse:
    """TA-031: Mark an onboarding step as complete or incomplete."""
    steps = await upsert_onboarding_step_db(
        tenant_id=current_user.tenant_id,
        step=request.step,
        completed=request.completed,
        db=db,
    )

    # Re-fetch dismissed_until
    data = await get_onboarding_status_db(current_user.tenant_id, db)
    dismissed_until = data["dismissed_until"]

    current_step = _compute_current_step(steps)
    all_completed = all(steps.get(s, False) for s in _ORDERED_STEPS)

    return OnboardingStatusResponse(
        current_step=current_step,
        completed=all_completed,
        steps=steps,
        dismissed_until=dismissed_until,
    )


@router.patch("/onboarding/dismiss", response_model=OnboardingStatusResponse)
async def dismiss_onboarding(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> OnboardingStatusResponse:
    """TA-031: Dismiss the onboarding banner for 7 days."""
    dismissed_until = await dismiss_onboarding_db(current_user.tenant_id, db)

    data = await get_onboarding_status_db(current_user.tenant_id, db)
    steps = data["steps"]
    current_step = _compute_current_step(steps)
    all_completed = all(steps.get(s, False) for s in _ORDERED_STEPS)

    return OnboardingStatusResponse(
        current_step=current_step,
        completed=all_completed,
        steps=steps,
        dismissed_until=dismissed_until,
    )
