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


async def update_workspace_settings_db(
    tenant_id: str, actor_id: str, updates: dict, db
) -> dict:
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
            "actor_id": actor_id,
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
        actor_id=current_user.id,
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
# SSO Configuration (P3AUTH-003 partial — config storage; SAML/OIDC Auth0
# wiring is P3AUTH-004/005 and requires P3AUTH-001 external setup)
# ---------------------------------------------------------------------------


class SSOConfigResponse(BaseModel):
    """SSO configuration response."""

    provider: Optional[str] = None  # "saml" | "oidc" | null
    status: str = "not_configured"  # "configured" | "not_configured" | "error"
    saml: Optional[dict] = None
    oidc: Optional[dict] = None


async def _get_sso_config_db(tenant_id: str, db) -> dict:
    """Read SSO config from tenant_configs (config_type='sso_config')."""
    result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tid AND config_type = 'sso_config'"
        ),
        {"tid": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return {}
    import json as _json

    data = row[0]
    return _json.loads(data) if isinstance(data, str) else (data or {})


@router.get("/sso", response_model=SSOConfigResponse)
async def get_sso_config(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Get SSO configuration for this tenant."""
    config = await _get_sso_config_db(current_user.tenant_id, session)
    if not config:
        return SSOConfigResponse(provider=None, status="not_configured")
    return SSOConfigResponse(
        provider=config.get("provider"),
        status=config.get("status", "configured"),
        saml=config.get("saml"),
        oidc=config.get("oidc"),
    )


class SSOConfigRequest(BaseModel):
    """Request body for saving SSO config."""

    provider: str = Field(..., pattern="^(saml|oidc)$")
    status: str = Field(default="configured", pattern="^(configured|error)$")
    saml: Optional[dict] = None
    oidc: Optional[dict] = None


@router.post("/sso", response_model=SSOConfigResponse)
async def save_sso_config(
    request: SSOConfigRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Save SSO configuration."""
    import json as _json

    data = request.model_dump(exclude_none=True)
    await session.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (:id, :tid, 'sso_config', CAST(:data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) DO UPDATE SET config_data = CAST(:data AS jsonb)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": current_user.tenant_id,
            "data": _json.dumps(data),
        },
    )
    await session.commit()
    logger.info(
        "sso_config_saved", tenant_id=current_user.tenant_id, provider=request.provider
    )
    return SSOConfigResponse(
        provider=request.provider,
        status=request.status,
        saml=request.saml,
        oidc=request.oidc,
    )


@router.post("/sso/test")
async def test_sso_connection(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Test SSO connection — verifies config is stored; full Auth0 test flow requires P3AUTH-001."""
    config = await _get_sso_config_db(current_user.tenant_id, session)
    if not config or not config.get("provider"):
        return {"success": False, "message": "SSO is not configured for this tenant."}
    return {
        "success": True,
        "message": f"SSO config found (provider={config['provider']}). "
        "Live connection test requires Auth0 integration (P3AUTH-001).",
    }


# ---------------------------------------------------------------------------
# Group Sync Config (P3AUTH-010)
# ---------------------------------------------------------------------------

_VALID_MAPPING_ROLES = {"admin", "editor", "viewer", "user"}


_MAX_GROUPS = 200
_MAX_GROUP_NAME_LEN = 256


class GroupSyncConfigRequest(BaseModel):
    """PATCH /admin/sso/group-sync/config request body."""

    allowed_groups: list[str] = Field(default_factory=list, max_length=_MAX_GROUPS)
    group_role_mapping: dict[str, str] = Field(
        default_factory=dict, max_length=_MAX_GROUPS
    )

    @field_validator("allowed_groups")
    @classmethod
    def validate_group_name_lengths(cls, v: list[str]) -> list[str]:
        for name in v:
            if len(name) > _MAX_GROUP_NAME_LEN:
                raise ValueError(f"Group name exceeds {_MAX_GROUP_NAME_LEN} characters")
        return v

    @field_validator("group_role_mapping")
    @classmethod
    def validate_role_values(cls, v: dict[str, str]) -> dict[str, str]:
        for key in v:
            if len(key) > _MAX_GROUP_NAME_LEN:
                raise ValueError(
                    f"Group name key exceeds {_MAX_GROUP_NAME_LEN} characters"
                )
        invalid = {role for role in v.values() if role not in _VALID_MAPPING_ROLES}
        if invalid:
            raise ValueError(
                f"Invalid role values: {sorted(invalid)}. "
                f"Allowed: {sorted(_VALID_MAPPING_ROLES)}"
            )
        return v


class GroupSyncConfigResponse(BaseModel):
    """GET/PATCH /admin/sso/group-sync/config response body."""

    allowed_groups: list[str]
    group_role_mapping: dict[str, str]


async def _get_group_sync_config_db(
    tenant_id: str, db: AsyncSession
) -> tuple[list[str], dict[str, str]]:
    """Fetch current group sync config from tenant_configs."""
    result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tid AND config_type = 'sso_group_sync' LIMIT 1"
        ),
        {"tid": tenant_id},
    )
    row = result.fetchone()
    if row and row[0]:
        config = row[0] if isinstance(row[0], dict) else {}
        return (
            config.get("auth0_group_allowlist") or [],
            config.get("auth0_group_role_mapping") or {},
        )
    return [], {}


async def _upsert_group_sync_config_db(
    tenant_id: str,
    allowed_groups: list[str],
    group_role_mapping: dict[str, str],
    db: AsyncSession,
) -> None:
    """Upsert group sync config into tenant_configs."""
    import json as _json

    config_data = _json.dumps(
        {
            "auth0_group_allowlist": allowed_groups,
            "auth0_group_role_mapping": group_role_mapping,
        }
    )
    config_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (:id, :tid, 'sso_group_sync', CAST(:data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) DO UPDATE SET "
            "config_data = CAST(:data AS jsonb)"
        ),
        {"id": config_id, "tid": tenant_id, "data": config_data},
    )
    await db.commit()


@router.get("/sso/group-sync/config", response_model=GroupSyncConfigResponse)
async def get_group_sync_config(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-086: Get the tenant's Auth0 group sync allowlist and role mapping."""
    allowlist, mapping = await _get_group_sync_config_db(
        current_user.tenant_id, session
    )
    return GroupSyncConfigResponse(
        allowed_groups=allowlist,
        group_role_mapping=mapping,
    )


@router.patch("/sso/group-sync/config", response_model=GroupSyncConfigResponse)
async def update_group_sync_config(
    request: GroupSyncConfigRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-086: Update the tenant's Auth0 group sync allowlist and role mapping.

    Stores config under tenant_configs.config_type='sso_group_sync'.
    Role values must be one of: admin, editor, viewer, user.
    """
    await _upsert_group_sync_config_db(
        tenant_id=current_user.tenant_id,
        allowed_groups=request.allowed_groups,
        group_role_mapping=request.group_role_mapping,
        db=session,
    )

    # Read back to confirm persistence
    allowlist, mapping = await _get_group_sync_config_db(
        current_user.tenant_id, session
    )

    logger.info(
        "sso_group_sync_config_updated",
        tenant_id=current_user.tenant_id,
        group_count=len(allowlist),
        mapping_count=len(mapping),
    )

    return GroupSyncConfigResponse(
        allowed_groups=allowlist,
        group_role_mapping=mapping,
    )


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
