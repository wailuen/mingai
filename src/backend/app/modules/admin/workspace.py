"""
Workspace settings API (API-048/049).

Endpoints:
- GET  /admin/workspace   -- Get workspace settings (tenant_admin)
- PATCH /admin/workspace  -- Update workspace settings (tenant_admin)

Settings are stored in the tenant_configs table as a JSON value
with key='workspace_settings'.
"""
import uuid
import zoneinfo
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

WORKSPACE_DEFAULTS = {
    "name": "",
    "logo_url": None,
    "timezone": "UTC",
    "locale": "en",
    "auth_mode": "local",
    "notification_preferences": {},
}


class WorkspaceSettingsResponse(BaseModel):
    """Response schema for workspace settings."""

    name: str
    logo_url: Optional[str] = None
    timezone: str
    locale: str
    auth_mode: str  # "local" | "sso"
    notification_preferences: dict


class UpdateWorkspaceRequest(BaseModel):
    """PATCH request body for workspace settings."""

    name: Optional[str] = Field(None, max_length=100)
    timezone: Optional[str] = Field(None, max_length=100)
    locale: Optional[str] = Field(None, max_length=10)
    notification_preferences: Optional[dict] = Field(
        None,
        description="Notification preferences (max 20 keys, shallow dict only)",
    )

    @field_validator("notification_preferences")
    @classmethod
    def validate_notification_preferences(cls, v: Optional[dict]) -> Optional[dict]:
        if v is None:
            return v
        if len(v) > 20:
            raise ValueError("notification_preferences may not have more than 20 keys")
        import json

        if len(json.dumps(v)) > 4096:
            raise ValueError(
                "notification_preferences exceeds maximum allowed size (4KB)"
            )
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: Optional[str]) -> Optional[str]:
        """Validate timezone against Python stdlib zoneinfo."""
        if v is None:
            return v
        available = zoneinfo.available_timezones()
        if v not in available:
            raise ValueError(
                f"Invalid timezone '{v}'. Must be a valid IANA timezone "
                f"(e.g., 'UTC', 'America/New_York', 'Asia/Singapore')."
            )
        return v


# ---------------------------------------------------------------------------
# DB helper functions (mockable in unit tests)
# ---------------------------------------------------------------------------

_WORKSPACE_UPDATE_ALLOWLIST = {"name", "timezone", "locale", "notification_preferences"}


async def get_workspace_settings_db(tenant_id: str, db) -> dict:
    """
    Get workspace settings from tenant_configs table.

    Falls back to defaults if no config exists.
    """
    result = await db.execute(
        text(
            "SELECT value FROM tenant_configs "
            "WHERE tenant_id = :tenant_id AND key = 'workspace_settings'"
        ),
        {"tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return dict(WORKSPACE_DEFAULTS)

    import json

    stored = json.loads(row[0]) if isinstance(row[0], str) else row[0]

    # Merge with defaults for any missing keys
    merged = dict(WORKSPACE_DEFAULTS)
    merged.update(stored)
    return merged


async def update_workspace_settings_db(tenant_id: str, updates: dict, db) -> dict:
    """
    Update workspace settings with partial update (upsert).

    Only fields in the allowlist are persisted.
    Creates audit log entry for changes.
    """
    import json

    # Filter to allowlist
    invalid = set(updates) - _WORKSPACE_UPDATE_ALLOWLIST
    if invalid:
        raise ValueError(f"Invalid workspace update fields: {invalid}")

    # Get current settings
    current = await get_workspace_settings_db(tenant_id, db)

    # Merge updates
    current.update(updates)

    # Upsert into tenant_configs
    await db.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, key, value) "
            "VALUES (:id, :tenant_id, 'workspace_settings', :value) "
            "ON CONFLICT (tenant_id, key) DO UPDATE SET value = :value"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "value": json.dumps(current),
        },
    )

    # Create audit log entry
    await db.execute(
        text(
            "INSERT INTO audit_log (id, tenant_id, actor_id, action, resource_type, details) "
            "VALUES (:id, :tenant_id, :actor_id, 'update', 'workspace_settings', :details)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "actor_id": tenant_id,
            "details": json.dumps({"updated_fields": list(updates.keys())}),
        },
    )

    await db.commit()

    logger.info(
        "workspace_settings_updated",
        tenant_id=tenant_id,
        updated_fields=list(updates.keys()),
    )

    return current


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/workspace", response_model=WorkspaceSettingsResponse)
async def get_workspace_settings(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-048: Get workspace settings (tenant admin only)."""
    result = await get_workspace_settings_db(
        tenant_id=current_user.tenant_id, db=session
    )
    return result


@router.patch("/workspace", response_model=WorkspaceSettingsResponse)
async def update_workspace_settings(
    request: UpdateWorkspaceRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-049: Update workspace settings (tenant admin only)."""
    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )

    result = await update_workspace_settings_db(
        tenant_id=current_user.tenant_id,
        updates=updates,
        db=session,
    )
    return result


@router.get("/setup-checklist")
async def get_setup_checklist(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Setup checklist for tenant onboarding wizard."""
    from sqlalchemy import text

    # Check what's configured for this tenant
    users_result = await session.execute(
        text("SELECT COUNT(*) FROM users WHERE tenant_id = :tid"),
        {"tid": current_user.tenant_id},
    )
    user_count = users_result.scalar() or 0

    agents_result = await session.execute(
        text("SELECT COUNT(*) FROM agent_cards WHERE tenant_id = :tid AND status = 'active'"),
        {"tid": current_user.tenant_id},
    )
    agent_count = agents_result.scalar() or 0

    integrations_result = await session.execute(
        text("SELECT COUNT(*) FROM integrations WHERE tenant_id = :tid"),
        {"tid": current_user.tenant_id},
    )
    integration_count = integrations_result.scalar() or 0

    return {
        "items": [
            {
                "id": "invite_users",
                "label": "Invite your team members",
                "completed": user_count > 1,
                "action_href": "/settings/users",
            },
            {
                "id": "connect_knowledge_base",
                "label": "Connect a knowledge base",
                "completed": integration_count > 0,
                "action_href": "/settings/knowledge-base",
            },
            {
                "id": "configure_agent",
                "label": "Configure an AI agent",
                "completed": agent_count > 0,
                "action_href": "/settings/workspace",
            },
        ],
        "completed_count": sum([
            user_count > 1,
            integration_count > 0,
            agent_count > 0,
        ]),
        "total_count": 3,
    }
