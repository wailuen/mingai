"""
SAML 2.0 SSO Wizard API (P3AUTH-004).

Endpoints:
- POST /admin/sso/saml/configure   -- Parse IdP metadata, create Auth0 SAML connection
- GET  /admin/sso/saml/sp-metadata -- Return SP metadata XML for download
- POST /admin/sso/saml/test        -- Return Auth0 authorize URL for SAML flow testing

All endpoints require tenant_admin role.

XML parsing uses defusedxml for safe parsing (XXE protection) and lxml for XPath extraction.
Auth0 SAML connections are created via the Management API (management_api.py).
Connection IDs are persisted in tenant_configs (config_type='sso_config',
provider_type='saml'). Credentials (cert, signing keys) are never stored in the DB.
"""
import json
import os
import uuid
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session
from app.modules.auth.management_api import management_api_request

logger = structlog.get_logger()

router = APIRouter(prefix="/admin/sso/saml", tags=["admin-sso"])

# ---------------------------------------------------------------------------
# SAML metadata namespace constants
# ---------------------------------------------------------------------------

_SAML_MD_NS = "urn:oasis:names:tc:SAML:2.0:metadata"
_SAML_POST_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
_DS_NS = "http://www.w3.org/2000/09/xmldsig#"

_SSO_CONFIG_TYPE = "sso_config"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


_MAX_METADATA_XML_BYTES = 512 * 1024  # 512 KB — protects against DoS via oversized XML


class SAMLConfigureRequest(BaseModel):
    """POST /admin/sso/saml/configure request body.

    Exactly one of metadata_url or metadata_xml must be provided.
    """

    metadata_url: Optional[str] = None
    metadata_xml: Optional[str] = None

    @field_validator("metadata_xml")
    @classmethod
    def validate_xml_size(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v.encode("utf-8")) > _MAX_METADATA_XML_BYTES:
            raise ValueError(
                f"metadata_xml must not exceed {_MAX_METADATA_XML_BYTES // 1024} KB"
            )
        return v


class SAMLConfigureResponse(BaseModel):
    """POST /admin/sso/saml/configure response body."""

    connection_id: str
    sp_metadata_url: str


# ---------------------------------------------------------------------------
# Internal: IdP metadata parsing helpers
# ---------------------------------------------------------------------------


def _parse_saml_idp_metadata(xml_bytes: bytes) -> dict:
    """
    Parse SAML 2.0 IdP metadata XML and extract connection parameters.

    Uses defusedxml for initial safety parse, then lxml for XPath traversal.

    Args:
        xml_bytes: Raw XML bytes from the IdP metadata document.

    Returns:
        dict with keys: entity_id (str), sso_url (str), certificate (str).

    Raises:
        HTTPException(422): If the XML is unparseable, missing required elements,
                            or does not contain a POST-binding SSO service.
    """
    import defusedxml.ElementTree as safe_et
    from lxml import etree

    # Step 1: safe parse via defusedxml (blocks XXE, billion-laughs, etc.)
    try:
        safe_et.fromstring(xml_bytes)
    except Exception as exc:
        logger.warning("saml_metadata_parse_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid SAML metadata XML: {exc}",
        )

    # Step 2: lxml parse for XPath — only reached if defusedxml accepted the doc
    try:
        root = etree.fromstring(xml_bytes)  # noqa: S320 — defusedxml already validated
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid SAML metadata XML: {exc}",
        )

    ns = {
        "md": _SAML_MD_NS,
        "ds": _DS_NS,
    }

    # entityID from root EntityDescriptor attribute
    entity_id: Optional[str] = root.get("entityID")
    if not entity_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="SAML metadata missing required entityID attribute on EntityDescriptor",
        )

    # SSO URL — prefer HTTP-POST binding, fall back to any SingleSignOnService
    sso_elements = root.xpath(
        "//md:IDPSSODescriptor/md:SingleSignOnService[@Binding='"
        + _SAML_POST_BINDING
        + "']",
        namespaces=ns,
    )
    if not sso_elements:
        # Try any binding as fallback
        sso_elements = root.xpath(
            "//md:IDPSSODescriptor/md:SingleSignOnService",
            namespaces=ns,
        )
    if not sso_elements:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="SAML metadata missing SingleSignOnService element in IDPSSODescriptor",
        )

    sso_url: Optional[str] = sso_elements[0].get("Location")
    if not sso_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="SAML metadata SingleSignOnService element missing Location attribute",
        )

    # X.509 certificate — first signing cert under IDPSSODescriptor KeyDescriptor
    cert_elements = root.xpath(
        "//md:IDPSSODescriptor/md:KeyDescriptor[@use='signing']"
        "/ds:KeyInfo/ds:X509Data/ds:X509Certificate",
        namespaces=ns,
    )
    if not cert_elements:
        # Try without use filter
        cert_elements = root.xpath(
            "//md:IDPSSODescriptor/md:KeyDescriptor"
            "/ds:KeyInfo/ds:X509Data/ds:X509Certificate",
            namespaces=ns,
        )
    if not cert_elements:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="SAML metadata missing X509Certificate in IDPSSODescriptor KeyDescriptor",
        )

    certificate: str = (cert_elements[0].text or "").strip()
    if not certificate:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="SAML metadata X509Certificate is empty",
        )

    return {
        "entity_id": entity_id,
        "sso_url": sso_url,
        "certificate": certificate,
    }


async def _fetch_metadata_url(url: str) -> bytes:
    """
    Fetch SAML IdP metadata from a remote URL.

    Args:
        url: HTTPS URL to fetch metadata from (HTTP rejected — SSRF guard).

    Returns:
        Raw response bytes.

    Raises:
        HTTPException(422): On timeout, connection error, or non-HTTPS URL.
    """
    # SSRF guard: only allow HTTPS scheme to prevent internal network probing
    if not url.startswith("https://"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Metadata URL must use HTTPS",
        )
    try:
        async with httpx.AsyncClient(
            timeout=10.0, verify=True, follow_redirects=False
        ) as http:
            response = await http.get(url)
        response.raise_for_status()
        return response.content
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Timed out fetching SAML metadata from {url}",
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"HTTP {exc.response.status_code} fetching SAML metadata from {url}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to fetch SAML metadata: {exc}",
        )


# ---------------------------------------------------------------------------
# Internal: DB helpers
# ---------------------------------------------------------------------------


async def _get_saml_config_db(tenant_id: str, db: AsyncSession) -> Optional[dict]:
    """
    Read the tenant's SAML SSO config from tenant_configs.

    Returns the stored config dict (containing provider_type, auth0_connection_id,
    enabled) or None if not configured.
    """
    result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tid AND config_type = :ctype LIMIT 1"
        ),
        {"tid": tenant_id, "ctype": _SSO_CONFIG_TYPE},
    )
    row = result.fetchone()
    if row is None or row[0] is None:
        return None
    data = row[0]
    return data if isinstance(data, dict) else json.loads(data)


async def _store_saml_config_db(
    tenant_id: str,
    actor_id: str,
    connection_id: str,
    db: AsyncSession,
) -> None:
    """
    Persist the SAML connection config in tenant_configs and write an audit log entry.

    Both writes are committed by the caller.
    """
    config_data = json.dumps(
        {
            "provider_type": "saml",
            "auth0_connection_id": connection_id,
            "enabled": True,
        }
    )

    await db.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (:id, :tid, :ctype, CAST(:data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) DO UPDATE "
            "SET config_data = CAST(:data AS jsonb)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": tenant_id,
            "ctype": _SSO_CONFIG_TYPE,
            "data": config_data,
        },
    )

    await db.execute(
        text(
            "INSERT INTO audit_log "
            "(id, tenant_id, user_id, action, resource_type, details) "
            "VALUES (:id, :tenant_id, :user_id, :action, :resource_type, :details)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "user_id": actor_id,
            "action": "sso.saml.configured",
            "resource_type": "sso_config",
            "details": json.dumps({"auth0_connection_id": connection_id}),
        },
    )


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post("/configure", response_model=SAMLConfigureResponse)
async def configure_saml(
    request: SAMLConfigureRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """P3AUTH-004: Parse IdP metadata and create an Auth0 SAML connection.

    Exactly one of metadata_url or metadata_xml must be provided.

    Flow:
    1. Fetch / accept IdP metadata XML.
    2. Parse entityID, SSO URL, and X.509 certificate.
    3. Check for existing SAML connection (409 if present).
    4. Create Auth0 SAML connection via Management API.
    5. Persist connection_id in tenant_configs.
    6. Write audit log entry.
    """
    # Validate mutual exclusivity
    has_url = bool(request.metadata_url)
    has_xml = bool(request.metadata_xml)

    if not has_url and not has_xml:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Exactly one of metadata_url or metadata_xml must be provided",
        )
    if has_url and has_xml:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide only one of metadata_url or metadata_xml, not both",
        )

    # Fetch / accept metadata XML
    if has_url:
        xml_bytes = await _fetch_metadata_url(request.metadata_url)  # type: ignore[arg-type]
    else:
        xml_bytes = request.metadata_xml.encode("utf-8")  # type: ignore[union-attr]

    # Parse IdP metadata
    idp_params = _parse_saml_idp_metadata(xml_bytes)

    # 409 guard: tenant must not already have a SAML connection
    existing = await _get_saml_config_db(current_user.tenant_id, session)
    if existing and existing.get("provider_type") == "saml":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "SAML connection already configured. "
                "DELETE the existing connection first."
            ),
        )

    # Create Auth0 SAML connection
    connection_name = f"saml-{current_user.tenant_id[:8]}"
    try:
        auth0_resp = await management_api_request(
            "POST",
            "connections",
            {
                "name": connection_name,
                "strategy": "samlp",
                "options": {
                    "signInEndpoint": idp_params["sso_url"],
                    "cert": idp_params["certificate"],
                    "entityId": idp_params["entity_id"],
                },
            },
        )
    except RuntimeError as exc:
        logger.error(
            "saml_auth0_connection_create_failed",
            tenant_id=current_user.tenant_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Auth0 connection creation failed: {exc}",
        )

    connection_id: str = auth0_resp["id"]

    # Persist and audit
    await _store_saml_config_db(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        connection_id=connection_id,
        db=session,
    )
    await session.commit()

    logger.info(
        "saml_connection_configured",
        tenant_id=current_user.tenant_id,
        connection_id=connection_id,
        entity_id=idp_params["entity_id"],
    )

    return SAMLConfigureResponse(
        connection_id=connection_id,
        sp_metadata_url="/api/v1/admin/sso/saml/sp-metadata",
    )


@router.get("/sp-metadata")
async def get_sp_metadata(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """P3AUTH-004: Return SP metadata XML for download.

    Contains our ACS URL and entityID so the IdP admin can configure
    the service provider side.
    """
    config = await _get_saml_config_db(current_user.tenant_id, session)
    if not config or config.get("provider_type") != "saml":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No SAML connection configured for this tenant",
        )

    connection_id = config["auth0_connection_id"]
    auth0_domain = os.environ.get("AUTH0_DOMAIN", "")

    # TA-001: entityID must match Auth0's SAML SP metadata URL pattern:
    # https://{AUTH0_DOMAIN}/samlp/metadata/{connection_id}
    entity_id = f"https://{auth0_domain}/samlp/metadata/{connection_id}"

    xml_string = (
        '<?xml version="1.0"?>\n'
        '<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata"'
        f' entityID="{entity_id}">\n'
        "  <SPSSODescriptor"
        ' AuthnRequestsSigned="false"'
        ' WantAssertionsSigned="true"'
        ' protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">\n'
        "    <AssertionConsumerService"
        ' Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"\n'
        f'      Location="https://{auth0_domain}/login/callback?connection={connection_id}"\n'
        '      index="0" isDefault="true"/>\n'
        "  </SPSSODescriptor>\n"
        "</EntityDescriptor>\n"
    )

    return Response(content=xml_string, media_type="application/xml")


@router.post("/test")
async def test_saml_connection(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """P3AUTH-004: Return the Auth0 authorize URL for testing the SAML flow.

    The returned URL initiates the SP-initiated SAML flow via Auth0.
    """
    config = await _get_saml_config_db(current_user.tenant_id, session)
    if not config or config.get("provider_type") != "saml":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No SAML connection configured for this tenant",
        )

    auth0_domain = os.environ.get("AUTH0_DOMAIN", "")
    auth0_client_id = os.environ.get("AUTH0_CLIENT_ID", "")
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3022")
    connection_id = config["auth0_connection_id"]

    test_url = (
        f"https://{auth0_domain}/authorize"
        f"?connection={connection_id}"
        f"&client_id={auth0_client_id}"
        f"&response_type=code"
        f"&redirect_uri={frontend_url}/api/auth/callback"
        f"&scope=openid%20email%20profile"
    )

    logger.info(
        "saml_test_initiated",
        tenant_id=current_user.tenant_id,
        connection_id=connection_id,
    )

    return {"test_url": test_url}
