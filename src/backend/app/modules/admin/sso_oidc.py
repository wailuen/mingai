"""
OIDC/Google/Okta SSO wizard API (P3AUTH-005/006/007).

Endpoints (all require tenant_admin):
    POST /admin/sso/oidc/configure   — OIDC auto-discovery + Auth0 connection creation
    POST /admin/sso/oidc/test        — Return Auth0 authorize URL for test flow
    POST /admin/sso/google/configure — Google Workspace OAuth2 via Auth0
    POST /admin/sso/okta/configure   — Okta OIDC via Auth0 (reuses discovery logic)

Security invariants:
    - client_secret values are NEVER stored plaintext in DB
    - Vault ref pattern (get_vault_client().store_secret) wraps secrets before DB write
    - OIDC discovery validates required fields before any Auth0 API call
    - Duplicate connection check (409) prevents double-configuration per provider per tenant
    - All configurations are logged to audit_log
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session
from app.modules.auth.management_api import management_api_request

logger = structlog.get_logger()

router = APIRouter(tags=["admin-sso-oidc"])

# ---------------------------------------------------------------------------
# Required OIDC discovery fields (RFC 8414)
# ---------------------------------------------------------------------------

_REQUIRED_OIDC_FIELDS = {"authorization_endpoint", "token_endpoint", "jwks_uri"}

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class OIDCConfigureRequest(BaseModel):
    issuer: str = Field(
        ..., description="OIDC issuer URL, e.g. https://accounts.google.com"
    )
    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1)


class OIDCConfigureResponse(BaseModel):
    connection_id: str
    issuer_validated: bool


class OIDCTestResponse(BaseModel):
    test_url: str


class GoogleConfigureRequest(BaseModel):
    client_id: str = Field(..., min_length=1, description="Google OAuth client_id")
    client_secret: str = Field(
        ..., min_length=1, description="Google OAuth client_secret"
    )


class GoogleConfigureResponse(BaseModel):
    connection_id: str
    google_auth_url: str


class OktaConfigureRequest(BaseModel):
    okta_domain: str = Field(..., min_length=1, description="e.g. mycompany.okta.com")
    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1)


class OktaConfigureResponse(BaseModel):
    connection_id: str
    issuer_validated: bool


# ---------------------------------------------------------------------------
# OIDC discovery helper (shared by OIDC and Okta flows)
# ---------------------------------------------------------------------------


async def _validate_oidc_discovery(issuer: str) -> dict:
    """
    Fetch and validate the OIDC discovery document at {issuer}/.well-known/openid-configuration.

    Returns the parsed discovery document on success.

    Raises:
        HTTPException 422 if required fields are missing, scheme is not HTTPS,
        or the request times out / fails.
    """
    # SSRF guard: only allow HTTPS scheme to prevent internal network probing
    if not issuer.startswith("https://"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="OIDC issuer must use HTTPS",
        )
    discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(
            timeout=10.0, verify=True, follow_redirects=False
        ) as http:
            response = await http.get(discovery_url)
        response.raise_for_status()
        doc = response.json()
    except httpx.TimeoutException:
        logger.warning("oidc_discovery_timeout", issuer=issuer)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="OIDC discovery request timed out",
        )
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "oidc_discovery_http_error",
            issuer=issuer,
            status_code=exc.response.status_code,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"OIDC discovery returned HTTP {exc.response.status_code}",
        )
    except Exception as exc:
        logger.warning("oidc_discovery_failed", issuer=issuer, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="OIDC discovery request failed",
        )

    missing = _REQUIRED_OIDC_FIELDS - set(doc.keys())
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"OIDC discovery missing required fields: {sorted(missing)}",
        )

    return doc


# ---------------------------------------------------------------------------
# DB helpers (injectable in unit tests)
# ---------------------------------------------------------------------------


async def _get_sso_provider_config_db(
    tenant_id: str, provider_type: str, db: AsyncSession
) -> Optional[dict]:
    """
    Return the stored tenant_configs row for the given SSO provider type, or None.

    Reads config_type='sso_config' and checks provider_type inside config_data.
    """
    result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tid AND config_type = 'sso_config' LIMIT 1"
        ),
        {"tid": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    data = row[0]
    config = json.loads(data) if isinstance(data, str) else (data or {})
    if config.get("provider_type") == provider_type:
        return config
    return None


async def _get_any_sso_config_db(tenant_id: str, db: AsyncSession) -> Optional[dict]:
    """
    Return any stored SSO config for the tenant, regardless of provider type.

    Used for the 409 duplicate guard — a tenant may only have one SSO connection.
    """
    result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tid AND config_type = 'sso_config' LIMIT 1"
        ),
        {"tid": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    data = row[0]
    return json.loads(data) if isinstance(data, str) else (data or {})


async def _upsert_sso_provider_config_db(
    tenant_id: str,
    actor_id: str,
    provider_type: str,
    auth0_connection_id: str,
    db: AsyncSession,
    client_secret_vault_ref: Optional[str] = None,
) -> None:
    """
    Upsert the SSO provider config into tenant_configs and write an audit_log entry.

    client_secret_vault_ref is the vault URI for the encrypted client_secret.
    It is stored alongside auth0_connection_id so the secret can be retrieved
    or rotated without storing plaintext.  May be None for providers that do not
    require a client_secret (e.g. future PKCE-only flows).

    Both writes are done without an intermediate commit — caller must commit.
    """
    config: dict = {
        "provider_type": provider_type,
        "auth0_connection_id": auth0_connection_id,
        "enabled": True,
    }
    if client_secret_vault_ref is not None:
        config["client_secret_vault_ref"] = client_secret_vault_ref
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
            "action": f"sso.{provider_type}.configured",
            "details": json.dumps(
                {
                    "provider_type": provider_type,
                    "auth0_connection_id": auth0_connection_id,
                }
            ),
        },
    )


def _encrypt_client_secret(tenant_id: str, secret: str) -> str:
    """
    Encrypt a client_secret using the vault ref pattern.

    Uses get_vault_client().store_secret() with key_id = "{tenant_id[:8]}-sso-secret".
    In dev/CI the LocalDBVaultClient returns a local:// URI (base64-encoded).
    In production with AZURE_KEY_VAULT_URL set, the AzureVaultClient is used.

    The returned vault_ref is safe to store in DB — the plaintext is never persisted.
    """
    from app.core.secrets.vault_client import get_vault_client

    vault = get_vault_client()
    key_id = f"{tenant_id[:8]}-sso-secret"
    vault_ref = vault.store_secret(key_id, secret)
    return vault_ref


# ---------------------------------------------------------------------------
# POST /admin/sso/oidc/configure  (P3AUTH-005)
# ---------------------------------------------------------------------------


@router.post(
    "/admin/sso/oidc/configure",
    response_model=OIDCConfigureResponse,
    status_code=status.HTTP_200_OK,
)
async def configure_oidc_sso(
    request: OIDCConfigureRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> OIDCConfigureResponse:
    """
    P3AUTH-005: Configure OIDC SSO for the calling tenant.

    Steps:
    1. Validate OIDC discovery document at {issuer}/.well-known/openid-configuration.
    2. Encrypt client_secret via vault ref pattern.
    3. Check for existing OIDC connection — 409 if already configured.
    4. Create Auth0 OIDC connection via Management API.
    5. Store connection config in tenant_configs + audit_log.
    """
    # 1. OIDC auto-discovery — validates HTTPS scheme and reachability
    await _validate_oidc_discovery(request.issuer)

    # 2. Duplicate check — reject any existing SSO config regardless of provider type
    existing = await _get_any_sso_config_db(current_user.tenant_id, db)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An SSO connection is already configured for this tenant",
        )

    # 3. Create Auth0 connection — send plaintext secret to Auth0
    try:
        result = await management_api_request(
            "POST",
            "connections",
            {
                "name": f"oidc-{current_user.tenant_id[:8]}",
                "strategy": "oidc",
                "options": {
                    "type": "back_channel",
                    "discovery_url": f"{request.issuer.rstrip('/')}/.well-known/openid-configuration",
                    "client_id": request.client_id,
                    "client_secret": request.client_secret,
                    "scope": "openid email profile",
                },
            },
        )
    except RuntimeError as exc:
        logger.error(
            "oidc_configure_auth0_error",
            tenant_id=current_user.tenant_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create OIDC connection in Auth0",
        )

    connection_id: str = result.get("id", "")

    # 4. Encrypt client_secret for local storage — vault ref stored in DB, not Auth0
    encrypted_secret = _encrypt_client_secret(
        current_user.tenant_id, request.client_secret
    )

    # 5. Store config + audit log (vault ref stored alongside connection_id)
    await _upsert_sso_provider_config_db(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        provider_type="oidc",
        auth0_connection_id=connection_id,
        db=db,
        client_secret_vault_ref=encrypted_secret,
    )
    await db.commit()

    logger.info(
        "sso_oidc_configured",
        tenant_id=current_user.tenant_id,
        connection_id=connection_id,
    )

    return OIDCConfigureResponse(
        connection_id=connection_id,
        issuer_validated=True,
    )


# ---------------------------------------------------------------------------
# POST /admin/sso/oidc/test  (P3AUTH-005)
# ---------------------------------------------------------------------------


@router.post(
    "/admin/sso/oidc/test",
    response_model=OIDCTestResponse,
    status_code=status.HTTP_200_OK,
)
async def test_oidc_sso(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> OIDCTestResponse:
    """
    P3AUTH-005: Return Auth0 authorize URL for OIDC test flow.

    Returns 404 if no OIDC connection is configured for this tenant.
    """
    config = await _get_sso_provider_config_db(current_user.tenant_id, "oidc", db)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No OIDC connection configured for this tenant",
        )

    auth0_domain = os.environ.get("AUTH0_DOMAIN", "")
    auth0_client_id = os.environ.get("AUTH0_CLIENT_ID", "")
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3022")
    connection_id = config.get("auth0_connection_id", "")

    test_url = (
        f"https://{auth0_domain}/authorize"
        f"?connection={connection_id}"
        f"&client_id={auth0_client_id}"
        f"&response_type=code"
        f"&redirect_uri={frontend_url}/api/auth/callback"
        f"&scope=openid%20email%20profile"
    )

    return OIDCTestResponse(test_url=test_url)


# ---------------------------------------------------------------------------
# POST /admin/sso/google/configure  (P3AUTH-006)
# ---------------------------------------------------------------------------


@router.post(
    "/admin/sso/google/configure",
    response_model=GoogleConfigureResponse,
    status_code=status.HTTP_200_OK,
)
async def configure_google_sso(
    request: GoogleConfigureRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> GoogleConfigureResponse:
    """
    P3AUTH-006: Configure Google Workspace SSO for the calling tenant.

    Steps:
    1. Encrypt client_secret via vault ref pattern.
    2. Check for existing Google connection — 409 if already configured.
    3. Create Auth0 google-oauth2 connection via Management API.
    4. Store config in tenant_configs + audit_log.
    5. Return connection_id + google_auth_url for immediate test flow.
    """
    # 1. Duplicate check — reject any existing SSO config regardless of provider type
    existing = await _get_any_sso_config_db(current_user.tenant_id, db)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An SSO connection is already configured for this tenant",
        )

    # 2. Create Auth0 Google connection — send plaintext secret to Auth0
    auth0_domain = os.environ.get("AUTH0_DOMAIN", "")
    auth0_client_id = os.environ.get("AUTH0_CLIENT_ID", "")
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3022")
    try:
        result = await management_api_request(
            "POST",
            "connections",
            {
                "name": f"google-{current_user.tenant_id[:8]}",
                "strategy": "google-oauth2",
                "options": {
                    "client_id": request.client_id,
                    "client_secret": request.client_secret,
                    "scope": ["openid", "email", "profile"],
                },
            },
        )
    except RuntimeError as exc:
        logger.error(
            "google_configure_auth0_error",
            tenant_id=current_user.tenant_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create Google connection in Auth0",
        )

    connection_id: str = result.get("id", "")

    # 3. Encrypt client_secret for local storage — vault ref stored in DB, not Auth0
    google_vault_ref = _encrypt_client_secret(
        current_user.tenant_id, request.client_secret
    )

    # 4. Store config + audit log (vault ref stored alongside connection_id)
    await _upsert_sso_provider_config_db(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        provider_type="google",
        auth0_connection_id=connection_id,
        db=db,
        client_secret_vault_ref=google_vault_ref,
    )
    await db.commit()

    # 5. Build google_auth_url using FRONTEND_URL from env
    google_auth_url = (
        f"https://{auth0_domain}/authorize"
        f"?connection={connection_id}"
        f"&client_id={auth0_client_id}"
        f"&response_type=code"
        f"&redirect_uri={frontend_url}/api/auth/callback"
        f"&scope=openid%20email%20profile"
    )

    logger.info(
        "sso_google_configured",
        tenant_id=current_user.tenant_id,
        connection_id=connection_id,
    )

    return GoogleConfigureResponse(
        connection_id=connection_id,
        google_auth_url=google_auth_url,
    )


# ---------------------------------------------------------------------------
# POST /admin/sso/okta/configure  (P3AUTH-007)
# ---------------------------------------------------------------------------


@router.post(
    "/admin/sso/okta/configure",
    response_model=OktaConfigureResponse,
    status_code=status.HTTP_200_OK,
)
async def configure_okta_sso(
    request: OktaConfigureRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> OktaConfigureResponse:
    """
    P3AUTH-007: Configure Okta SSO for the calling tenant.

    Steps:
    1. Construct Okta OIDC discovery URL from okta_domain.
    2. Validate OIDC discovery document (reuses _validate_oidc_discovery helper).
    3. Encrypt client_secret via vault ref pattern.
    4. Check for existing Okta connection — 409 if already configured.
    5. Create Auth0 OIDC connection named okta-{tenant_id[:8]}.
    6. Store config in tenant_configs + audit_log.
    """
    # 1. Construct Okta issuer from domain
    okta_issuer = f"https://{request.okta_domain}"

    # 2. Validate OIDC discovery — raises 422 if domain not reachable or invalid
    try:
        await _validate_oidc_discovery(okta_issuer)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Okta domain not reachable or invalid OIDC configuration",
        )

    # 3. Duplicate check — reject any existing SSO config regardless of provider type
    existing = await _get_any_sso_config_db(current_user.tenant_id, db)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An SSO connection is already configured for this tenant",
        )

    # 4. Create Auth0 OIDC connection for Okta — send plaintext secret to Auth0
    try:
        result = await management_api_request(
            "POST",
            "connections",
            {
                "name": f"okta-{current_user.tenant_id[:8]}",
                "strategy": "oidc",
                "options": {
                    "type": "back_channel",
                    "discovery_url": f"{okta_issuer}/.well-known/openid-configuration",
                    "client_id": request.client_id,
                    "client_secret": request.client_secret,
                    "scope": "openid email profile",
                },
            },
        )
    except RuntimeError as exc:
        logger.error(
            "okta_configure_auth0_error",
            tenant_id=current_user.tenant_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create Okta connection in Auth0",
        )

    connection_id: str = result.get("id", "")

    # 5. Encrypt client_secret for local storage — vault ref stored in DB, not Auth0
    okta_vault_ref = _encrypt_client_secret(
        current_user.tenant_id, request.client_secret
    )

    # 6. Store config + audit log (vault ref stored alongside connection_id)
    await _upsert_sso_provider_config_db(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        provider_type="okta",
        auth0_connection_id=connection_id,
        db=db,
        client_secret_vault_ref=okta_vault_ref,
    )
    await db.commit()

    logger.info(
        "sso_okta_configured",
        tenant_id=current_user.tenant_id,
        connection_id=connection_id,
    )

    return OktaConfigureResponse(
        connection_id=connection_id,
        issuer_validated=True,
    )
