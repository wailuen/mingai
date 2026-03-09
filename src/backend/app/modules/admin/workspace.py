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
    "welcome_message": "",
    "system_prompt_budget": 2000,
    "max_conversation_length": 50,
}


class WorkspaceSettingsResponse(BaseModel):
    """Response schema for workspace settings — aligned with frontend WorkspaceSettings."""

    tenant_name: str  # maps to tenants.name
    slug: str  # maps to tenants.slug
    plan: str  # maps to tenants.plan
    logo_url: Optional[str] = None
    timezone: str
    locale: str
    auth_mode: str  # "local" | "sso"
    notification_preferences: dict
    welcome_message: str = ""
    system_prompt_budget: int = 2000
    max_conversation_length: int = 50


class UpdateWorkspaceRequest(BaseModel):
    """PATCH request body for workspace settings."""

    tenant_name: Optional[str] = Field(None, max_length=100)
    timezone: Optional[str] = Field(None, max_length=100)
    locale: Optional[str] = Field(None, max_length=10)
    welcome_message: Optional[str] = Field(None, max_length=2000)
    system_prompt_budget: Optional[int] = Field(None, ge=500, le=8000)
    max_conversation_length: Optional[int] = Field(None, ge=5, le=200)
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

_WORKSPACE_UPDATE_ALLOWLIST = {
    "tenant_name",
    "timezone",
    "locale",
    "notification_preferences",
    "welcome_message",
    "system_prompt_budget",
    "max_conversation_length",
}


async def get_workspace_settings_db(tenant_id: str, db) -> dict:
    """
    Get workspace settings from tenant_configs + tenants tables.

    Merges tenant identity (name, slug, plan) with configurable settings.
    """
    import json

    # Fetch tenant identity fields
    tenant_result = await db.execute(
        text("SELECT name, slug, plan FROM tenants WHERE id = :tid"),
        {"tid": tenant_id},
    )
    tenant_row = tenant_result.fetchone()
    tenant_name = tenant_row[0] if tenant_row else ""
    slug = tenant_row[1] if tenant_row else ""
    plan = tenant_row[2] if tenant_row else ""

    # Fetch configurable settings from tenant_configs
    config_result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tenant_id AND config_type = 'workspace_settings'"
        ),
        {"tenant_id": tenant_id},
    )
    row = config_result.fetchone()

    merged = dict(WORKSPACE_DEFAULTS)
    if row is not None:
        stored = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        merged.update(stored)

    # Override with live tenant identity (source of truth)
    merged["tenant_name"] = tenant_name
    merged["slug"] = slug
    merged["plan"] = plan

    return merged


async def update_workspace_settings_db(tenant_id: str, updates: dict, db) -> dict:
    """
    Update workspace settings with partial update (upsert).

    tenant_name updates tenants.name directly.
    Other fields are stored in tenant_configs.
    Creates audit log entry for changes.
    """
    import json

    # Filter to allowlist
    invalid = set(updates) - _WORKSPACE_UPDATE_ALLOWLIST
    if invalid:
        raise ValueError(f"Invalid workspace update fields: {invalid}")

    # Update tenant name in tenants table if provided
    if "tenant_name" in updates:
        await db.execute(
            text("UPDATE tenants SET name = :name, updated_at = NOW() WHERE id = :tid"),
            {"name": updates.pop("tenant_name"), "tid": tenant_id},
        )

    # Get current settings
    current = await get_workspace_settings_db(tenant_id, db)

    # Merge remaining updates into configurable settings
    config_keys = {
        "timezone",
        "locale",
        "notification_preferences",
        "welcome_message",
        "system_prompt_budget",
        "max_conversation_length",
    }
    config_updates = {k: v for k, v in updates.items() if k in config_keys}
    current.update(config_updates)

    # Build config data (only configurable fields, not identity fields)
    config_data = {k: current[k] for k in config_keys if k in current}

    # Upsert into tenant_configs
    await db.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (:id, :tenant_id, 'workspace_settings', CAST(:config_data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) DO UPDATE SET config_data = CAST(:config_data AS jsonb)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "config_data": json.dumps(config_data),
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
        text(
            "SELECT COUNT(*) FROM agent_cards WHERE tenant_id = :tid AND status = 'active'"
        ),
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
        "completed_count": sum(
            [
                user_count > 1,
                integration_count > 0,
                agent_count > 0,
            ]
        ),
        "total_count": 3,
    }


# ---------------------------------------------------------------------------
# SSO Configuration (stub — Phase 2 full SAML/OIDC integration)
# ---------------------------------------------------------------------------


class SSOConfigResponse(BaseModel):
    """SSO configuration response."""

    provider: Optional[str] = None  # "saml" | "oidc" | null
    status: str = "not_configured"  # "configured" | "not_configured" | "error"


@router.get("/sso", response_model=SSOConfigResponse)
async def get_sso_config(
    current_user: CurrentUser = Depends(require_tenant_admin),
):
    """Get SSO configuration for this tenant."""
    return SSOConfigResponse(provider=None, status="not_configured")


@router.post("/sso", response_model=SSOConfigResponse)
async def save_sso_config(
    current_user: CurrentUser = Depends(require_tenant_admin),
):
    """Save SSO configuration (Phase 2 — full SAML/OIDC wiring)."""
    return SSOConfigResponse(provider=None, status="not_configured")


@router.post("/sso/test")
async def test_sso_connection(
    current_user: CurrentUser = Depends(require_tenant_admin),
):
    """Test SSO connection (Phase 2)."""
    return {"success": False, "message": "SSO integration is not yet configured."}


# ---------------------------------------------------------------------------
# Issue Reporting Settings
# ---------------------------------------------------------------------------


class IssueReportingConfig(BaseModel):
    """Issue reporting configuration for a tenant."""

    enabled: bool = False
    notify_email: str = ""
    auto_escalate_p0: bool = True
    auto_escalate_p1: bool = False
    escalation_threshold_hours: int = 4
    slack_webhook_url: Optional[str] = None


@router.get("/settings/issue-reporting", response_model=IssueReportingConfig)
async def get_issue_reporting_config(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Get issue reporting configuration for this tenant."""
    result = await session.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tid AND config_type = 'issue_reporting_settings' LIMIT 1"
        ),
        {"tid": current_user.tenant_id},
    )
    row = result.fetchone()
    if row and row[0]:
        return IssueReportingConfig(**row[0])
    return IssueReportingConfig()


@router.patch("/settings/issue-reporting", response_model=IssueReportingConfig)
async def update_issue_reporting_config(
    config: IssueReportingConfig,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Update issue reporting configuration for this tenant."""
    config_id = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (:id, :tid, 'issue_reporting_settings', CAST(:data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) DO UPDATE SET config_data = CAST(:data AS jsonb)"
        ),
        {
            "id": config_id,
            "tid": current_user.tenant_id,
            "data": config.model_dump_json(),
        },
    )
    await session.commit()
    return config
