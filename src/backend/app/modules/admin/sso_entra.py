"""
Azure Entra ID SSO wizard (ENTRA-001/002/004).

Endpoints (all require tenant_admin):
    POST  /admin/sso/entra/configure  — create Auth0 waad connection
    PATCH /admin/sso/entra/configure  — update domain or rotate secret
    POST  /admin/sso/entra/test       — return Auth0 authorize URL

Security invariants:
    - client_secret is sent to Auth0 once and NEVER stored in mingai DB
    - auth0_org_id absent → warn + continue (connection created, org-enable deferred)
    - Duplicate check (409) prevents double-configuration per tenant
    - All configurations logged to audit_log
"""
from __future__ import annotations

import json
import os
import re
import uuid
from urllib.parse import quote, urlencode
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session
from app.modules.auth.management_api import management_api_request
from app.modules.admin.sso_oidc import (
    _get_any_sso_config_db,
    _get_sso_provider_config_db,
)
from app.modules.admin.sso_import import get_tenant_auth0_org_id

logger = structlog.get_logger()

router = APIRouter(tags=["admin-sso-entra"])

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------

_DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$"
)
_CLIENT_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class EntraConfigureRequest(BaseModel):
    client_id: str = Field(
        ..., description="Azure application (client) ID — UUID format"
    )
    client_secret: str = Field(
        ..., min_length=1, description="Azure client secret value"
    )
    domain: str = Field(..., description="Tenant domain, e.g. contoso.com")

    @field_validator("client_id")
    @classmethod
    def validate_client_id_format(cls, v: str) -> str:
        if not _CLIENT_ID_RE.match(v):
            raise ValueError(
                "client_id must be a valid UUID "
                "(e.g. 12345678-1234-1234-1234-123456789abc)"
            )
        return v

    @field_validator("domain")
    @classmethod
    def validate_domain_format(cls, v: str) -> str:
        if not _DOMAIN_RE.match(v):
            raise ValueError(
                "domain must be a valid DNS name with at least one dot "
                "(e.g. contoso.com)"
            )
        return v


class EntraConfigureResponse(BaseModel):
    connection_id: str
    test_url: str
    domain: str


class EntraUpdateRequest(BaseModel):
    client_secret: Optional[str] = Field(
        None, min_length=1, description="New client secret (rotation)"
    )
    domain: Optional[str] = Field(None, description="Updated tenant domain")

    @field_validator("domain")
    @classmethod
    def validate_domain_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not _DOMAIN_RE.match(v):
            raise ValueError(
                "domain must be a valid DNS name with at least one dot "
                "(e.g. contoso.com)"
            )
        return v


class EntraTestResponse(BaseModel):
    test_url: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_test_url(connection_id: str) -> str:
    """Construct Auth0 authorize URL for testing the Entra connection."""
    auth0_domain = os.environ.get("AUTH0_DOMAIN", "")
    auth0_client_id = os.environ.get("AUTH0_CLIENT_ID", "")
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3022")
    params = urlencode(
        {
            "connection": connection_id,
            "client_id": auth0_client_id,
            "response_type": "code",
            "redirect_uri": f"{frontend_url}/api/auth/callback",
            "scope": "openid email profile",
        },
        quote_via=quote,
    )
    return f"https://{auth0_domain}/authorize?{params}"


async def _upsert_entra_config_db(
    tenant_id: str,
    actor_id: str,
    connection_id: str,
    domain: str,
    client_id: str,
    db: AsyncSession,
) -> None:
    """
    Upsert Entra SSO config into tenant_configs (config_type='sso_config').

    NOTE: client_secret is deliberately excluded — it is never stored in mingai DB.
    Both the INSERT and audit_log writes are done without an intermediate commit;
    caller must commit.
    """
    config: dict = {
        "provider_type": "entra",
        "auth0_connection_id": connection_id,
        "enabled": True,
        "domain": domain,
        "client_id": client_id,
    }
    config_data = json.dumps(config)

    await db.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (:id, :tid, 'sso_config', CAST(:data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) DO UPDATE "
            "SET config_data = CAST(:data AS jsonb)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": tenant_id,
            "data": config_data,
        },
    )

    await db.execute(
        text(
            "INSERT INTO audit_log "
            "(id, tenant_id, user_id, action, resource_type, details) "
            "VALUES (:id, :tenant_id, :user_id, :action, 'sso_connection', :details)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "user_id": actor_id,
            "action": "sso.entra.configured",
            "details": json.dumps(
                {
                    "provider_type": "entra",
                    "auth0_connection_id": connection_id,
                    "domain": domain,
                }
            ),
        },
    )


# ---------------------------------------------------------------------------
# POST /admin/sso/entra/configure  (ENTRA-001)
# ---------------------------------------------------------------------------


@router.post(
    "/admin/sso/entra/configure",
    response_model=EntraConfigureResponse,
    status_code=status.HTTP_200_OK,
)
async def configure_entra_sso(
    request: EntraConfigureRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> EntraConfigureResponse:
    """
    ENTRA-001: Configure Azure Entra ID SSO for the calling tenant.

    Steps:
    1. Duplicate check — 409 if any SSO connection already exists.
    2. Create Auth0 waad connection via Management API (secret sent once, never stored).
    3. Attempt to enable the connection for the tenant's Auth0 Org (non-fatal if missing).
    4. Persist config (without secret) to tenant_configs + audit_log.
    5. Return connection_id, test_url, domain.
    """
    # 1. Duplicate check
    existing = await _get_any_sso_config_db(current_user.tenant_id, db)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An SSO connection is already configured for this tenant",
        )

    # 2. Create Auth0 waad connection — client_secret is sent to Auth0 and never
    #    stored anywhere in mingai's database.
    try:
        result = await management_api_request(
            "POST",
            "connections",
            {
                "name": f"entra-{current_user.tenant_id[:8]}",
                "strategy": "waad",
                "options": {
                    "client_id": request.client_id,
                    "client_secret": request.client_secret,
                    "tenant_domain": request.domain,
                    "waad_protocol": "openid-connect",
                    "app_id": request.client_id,
                },
            },
        )
    except RuntimeError as exc:
        logger.error(
            "entra_configure_auth0_error",
            tenant_id=current_user.tenant_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create Entra ID connection in Auth0",
        )

    connection_id: str = result.get("id", "")
    if not connection_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Auth0 returned an empty connection ID",
        )

    # 3. Enable connection for the tenant's Auth0 Organization (best-effort).
    try:
        org_id = await get_tenant_auth0_org_id(current_user.tenant_id, db)
        if org_id:
            await management_api_request(
                "POST",
                f"organizations/{org_id}/enabled_connections",
                {
                    "connection_id": connection_id,
                    "assign_membership_on_login": True,
                },
            )
        else:
            logger.warning(
                "entra_org_enable_skipped",
                tenant_id=current_user.tenant_id,
                reason="auth0_org_id not configured for tenant",
                connection_id=connection_id,
            )
    except Exception as exc:
        logger.warning(
            "entra_org_enable_failed",
            tenant_id=current_user.tenant_id,
            connection_id=connection_id,
            error=str(exc),
        )
        # Non-fatal — connection still usable; org enable can be retried manually.

    # 4. Persist config (no secret) + audit log
    await _upsert_entra_config_db(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        connection_id=connection_id,
        domain=request.domain,
        client_id=request.client_id,
        db=db,
    )
    await db.commit()

    logger.info(
        "sso_entra_configured",
        tenant_id=current_user.tenant_id,
        connection_id=connection_id,
        domain=request.domain,
    )

    return EntraConfigureResponse(
        connection_id=connection_id,
        test_url=_build_test_url(connection_id),
        domain=request.domain,
    )


# ---------------------------------------------------------------------------
# PATCH /admin/sso/entra/configure  (ENTRA-002)
# ---------------------------------------------------------------------------


@router.patch(
    "/admin/sso/entra/configure",
    response_model=EntraConfigureResponse,
    status_code=status.HTTP_200_OK,
)
async def update_entra_sso(
    request: EntraUpdateRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> EntraConfigureResponse:
    """
    ENTRA-002: Update Entra ID SSO — rotate client_secret or change domain.

    At least one of client_secret or domain must be provided.
    client_secret is forwarded to Auth0's PATCH /connections/{id} only — never stored.
    """
    if request.client_secret is None and request.domain is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one of client_secret or domain must be provided",
        )

    # Read existing config — 404 if not yet configured
    config = await _get_sso_provider_config_db(current_user.tenant_id, "entra", db)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entra ID SSO is not configured for this tenant",
        )

    connection_id: str = config.get("auth0_connection_id", "")
    current_domain: str = config.get("domain", "")
    current_client_id: str = config.get("client_id", "")

    # Build Auth0 PATCH options — include only the fields being changed
    patch_options: dict = {}
    if request.client_secret is not None:
        patch_options["client_secret"] = request.client_secret
    if request.domain is not None:
        patch_options["tenant_domain"] = request.domain

    # Propagate changes to Auth0
    try:
        await management_api_request(
            "PATCH",
            f"connections/{connection_id}",
            {"options": patch_options},
        )
    except RuntimeError as exc:
        logger.error(
            "entra_update_auth0_error",
            tenant_id=current_user.tenant_id,
            connection_id=connection_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to update Entra ID connection in Auth0",
        )

    # If domain changed, update the stored config
    new_domain = request.domain if request.domain is not None else current_domain
    domain_changed = request.domain is not None and request.domain != current_domain
    secret_rotated = request.client_secret is not None

    if domain_changed:
        updated_config: dict = {
            "provider_type": "entra",
            "auth0_connection_id": connection_id,
            "enabled": config.get("enabled", True),
            "domain": new_domain,
            "client_id": current_client_id,
        }
        config_data = json.dumps(updated_config)
        await db.execute(
            text(
                "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
                "VALUES (:id, :tid, 'sso_config', CAST(:data AS jsonb)) "
                "ON CONFLICT (tenant_id, config_type) DO UPDATE "
                "SET config_data = CAST(:data AS jsonb)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tid": current_user.tenant_id,
                "data": config_data,
            },
        )

    # Audit log entry
    await db.execute(
        text(
            "INSERT INTO audit_log "
            "(id, tenant_id, user_id, action, resource_type, details) "
            "VALUES (:id, :tenant_id, :user_id, :action, 'sso_connection', :details)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": current_user.tenant_id,
            "user_id": current_user.id,
            "action": "sso.entra.updated",
            "details": json.dumps(
                {
                    "domain_changed": domain_changed,
                    "client_secret_rotated": secret_rotated,
                }
            ),
        },
    )
    await db.commit()

    logger.info(
        "sso_entra_updated",
        tenant_id=current_user.tenant_id,
        connection_id=connection_id,
        domain_changed=domain_changed,
        secret_rotated=secret_rotated,
    )

    return EntraConfigureResponse(
        connection_id=connection_id,
        test_url=_build_test_url(connection_id),
        domain=new_domain,
    )


# ---------------------------------------------------------------------------
# POST /admin/sso/entra/test  (ENTRA-004)
# ---------------------------------------------------------------------------


@router.post(
    "/admin/sso/entra/test",
    response_model=EntraTestResponse,
    status_code=status.HTTP_200_OK,
)
async def test_entra_sso(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> EntraTestResponse:
    """
    ENTRA-004: Return the Auth0 authorize URL for testing the Entra ID connection.

    Returns 404 if no Entra connection is configured or the connection is disabled.
    """
    config = await _get_sso_provider_config_db(current_user.tenant_id, "entra", db)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entra ID SSO is not configured for this tenant",
        )
    if not config.get("enabled", True):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entra ID SSO connection is disabled",
        )

    connection_id: str = config.get("auth0_connection_id", "")
    return EntraTestResponse(test_url=_build_test_url(connection_id))
