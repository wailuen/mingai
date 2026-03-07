"""
Memory Policy API (API-076/077).

Endpoints:
- GET  /admin/memory-policy  -- Get memory policy settings (tenant_admin)
- PATCH /admin/memory-policy -- Update memory policy settings (tenant_admin)

Settings are stored in tenant_configs with config_type='memory_policy'
and config_data JSONB. Validated fields are merged with defaults on read.
"""
import json
import uuid
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin"])

_CONFIG_TYPE = "memory_policy"

# ---------------------------------------------------------------------------
# Defaults and allowlist
# ---------------------------------------------------------------------------

MEMORY_POLICY_DEFAULTS: dict = {
    "profile_learning_enabled": True,
    "profile_learning_trigger_interval": 10,
    "working_memory_enabled": True,
    "working_memory_ttl_days": 7,
    "memory_notes_enabled": True,
    "memory_notes_max_per_user": 20,
    "org_context_enabled": False,
    "org_context_source": "none",
}

_VALID_ORG_CONTEXT_SOURCES = {"azure_ad", "okta", "saml", "none"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class MemoryPolicyResponse(BaseModel):
    """Response schema for memory policy settings."""

    profile_learning_enabled: bool
    profile_learning_trigger_interval: int
    working_memory_enabled: bool
    working_memory_ttl_days: int
    memory_notes_enabled: bool
    memory_notes_max_per_user: int
    org_context_enabled: bool
    org_context_source: str


class UpdateMemoryPolicyRequest(BaseModel):
    """PATCH request body for memory policy settings."""

    profile_learning_enabled: Optional[bool] = None
    profile_learning_trigger_interval: Optional[int] = Field(
        None,
        ge=5,
        le=25,
        description="Trigger interval in conversations (5-25)",
    )
    working_memory_enabled: Optional[bool] = None
    working_memory_ttl_days: Optional[int] = Field(
        None,
        ge=1,
        le=30,
        description="TTL in days for working memory (1-30)",
    )
    memory_notes_enabled: Optional[bool] = None
    memory_notes_max_per_user: Optional[int] = Field(
        None,
        ge=1,
        le=100,
        description="Maximum memory notes per user (1-100)",
    )
    org_context_enabled: Optional[bool] = None
    org_context_source: Optional[str] = Field(
        None,
        description="Org context provider: azure_ad, okta, saml, or none",
    )


# ---------------------------------------------------------------------------
# DB helper functions (mockable in unit tests)
# ---------------------------------------------------------------------------


async def get_memory_policy_db(tenant_id: str, db) -> dict:
    """
    Get memory policy from tenant_configs.

    Reads config_type='memory_policy' and merges with defaults for any
    missing keys. Returns defaults if no row exists.
    """
    result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tenant_id AND config_type = :config_type"
        ),
        {"tenant_id": tenant_id, "config_type": _CONFIG_TYPE},
    )
    row = result.fetchone()

    if row is None:
        return dict(MEMORY_POLICY_DEFAULTS)

    config_data = row[0]
    if isinstance(config_data, str):
        try:
            config_data = json.loads(config_data)
        except (ValueError, TypeError):
            config_data = {}
    if not isinstance(config_data, dict):
        config_data = {}

    # Merge stored values over defaults so new fields get their defaults
    merged = dict(MEMORY_POLICY_DEFAULTS)
    merged.update(config_data)
    return merged


async def update_memory_policy_db(
    tenant_id: str, updates: dict, actor_id: str, db
) -> dict:
    """
    Upsert memory policy settings for a tenant.

    Validates org_context_source against the allowlist before persisting.
    Creates an audit_log entry for the change. Returns the merged policy.
    """
    if "org_context_source" in updates:
        src = updates["org_context_source"]
        if src not in _VALID_ORG_CONTEXT_SOURCES:
            raise ValueError(
                f"Invalid org_context_source '{src}'. "
                f"Must be one of: {', '.join(sorted(_VALID_ORG_CONTEXT_SOURCES))}"
            )

    # Read current policy to merge
    current = await get_memory_policy_db(tenant_id, db)
    current.update(updates)

    config_json = json.dumps(current)

    await db.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (gen_random_uuid(), :tenant_id, :config_type, CAST(:config_data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) "
            "DO UPDATE SET config_data = CAST(:config_data AS jsonb), updated_at = NOW()"
        ),
        {
            "tenant_id": tenant_id,
            "config_type": _CONFIG_TYPE,
            "config_data": config_json,
        },
    )

    # Audit log entry — user_id is nullable per schema (v001); actor_id is the
    # JWT sub which may not have a corresponding users row (e.g. platform admin
    # or integration test tokens). Store actor_id in details to preserve
    # auditability without triggering a FK violation.
    await db.execute(
        text(
            "INSERT INTO audit_log (id, tenant_id, action, resource_type, details) "
            "VALUES (:id, :tenant_id, 'update', 'memory_policy', :details)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "details": json.dumps(
                {"actor_id": actor_id, "updated_fields": list(updates.keys())}
            ),
        },
    )

    await db.commit()

    logger.info(
        "memory_policy_updated",
        tenant_id=tenant_id,
        updated_fields=list(updates.keys()),
    )
    return current


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/memory-policy", response_model=MemoryPolicyResponse)
async def get_memory_policy(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-076: Get memory policy settings for the tenant (tenant admin only)."""
    result = await get_memory_policy_db(tenant_id=current_user.tenant_id, db=session)
    return result


@router.patch("/memory-policy", response_model=MemoryPolicyResponse)
async def update_memory_policy(
    request: UpdateMemoryPolicyRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-077: Update memory policy settings for the tenant (tenant admin only)."""
    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )

    try:
        result = await update_memory_policy_db(
            tenant_id=current_user.tenant_id,
            updates=updates,
            actor_id=current_user.id,
            db=session,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    return result
