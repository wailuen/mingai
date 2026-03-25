"""
Platform Credential Vault — CRUD routes.

All routes require platform_admin role.
Credential VALUES are NEVER returned in API responses.
All write operations append to platform_credential_audit.

Endpoints:
- POST   /platform/templates/{template_id}/credentials          — store credential (FR-01)
- GET    /platform/templates/{template_id}/credentials          — list keys (FR-02)
- GET    /platform/templates/{template_id}/credentials/health   — health check (FR-06/07)
- PUT    /platform/templates/{template_id}/credentials/{key}    — rotate credential (FR-03)
- DELETE /platform/templates/{template_id}/credentials/{key}    — soft-delete (FR-04)
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_platform_admin
from app.core.session import get_async_session
from app.modules.agents.credential_manager import (
    PlatformVaultUnavailableError,
    delete_platform_credential,
    get_platform_credential_health,
    set_platform_credential,
)

logger = structlog.get_logger()

router = APIRouter(tags=["platform"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_INJECTION_CONFIG = {
    "type": "header",
    "header_name": "Authorization",
    "header_format": "{value}",
}

_VALID_INJECTION_TYPES = {"bearer", "header", "query_param", "basic_auth"}

_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
}


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class StoreCredentialRequest(BaseModel):
    key: str = Field(
        ...,
        pattern=r"^[a-zA-Z][a-zA-Z0-9_]{1,63}$",
        description="Credential key name — starts with letter, alphanumeric + underscore",
    )
    value: str = Field(
        ..., min_length=1, max_length=8000, description="Secret value — write-only"
    )
    description: Optional[str] = Field(None, max_length=256)
    allowed_domains: List[str] = Field(
        ...,
        min_length=1,
        description="SSRF allowlist — at least one domain required",
    )
    injection_config: Optional[dict] = Field(
        None,
        description="How to inject credential at runtime. Defaults to bearer header.",
    )

    @field_validator("allowed_domains")
    @classmethod
    def domains_not_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError(
                "allowed_domains must contain at least one domain for SSRF protection"
            )
        return v

    @field_validator("injection_config")
    @classmethod
    def validate_injection_config(cls, v: Optional[dict]) -> Optional[dict]:
        if v is None:
            return v
        if v.get("type") not in _VALID_INJECTION_TYPES:
            raise ValueError(
                f"injection_config.type must be one of {sorted(_VALID_INJECTION_TYPES)}"
            )
        return v


class RotateCredentialRequest(BaseModel):
    value: str = Field(
        ..., min_length=1, max_length=8000, description="New secret value — write-only"
    )


# ---------------------------------------------------------------------------
# Audit helper
# ---------------------------------------------------------------------------


async def _write_audit(
    db: AsyncSession,
    action: str,
    template_id: uuid.UUID,
    key: str,
    actor_id: str,
    tenant_id: Optional[str] = None,
    request_id: Optional[str] = None,
    source_ip: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Append a row to platform_credential_audit."""
    # Validate source_ip before casting — TestClient and proxies may send
    # non-IP strings (e.g. "testclient"). Store NULL for invalid IPs.
    import ipaddress as _ipaddress

    _valid_ip: Optional[str] = None
    if source_ip:
        try:
            _ipaddress.ip_address(source_ip.split("/")[0])
            _valid_ip = source_ip
        except ValueError:
            pass

    await db.execute(
        text(
            """
            INSERT INTO platform_credential_audit
            (actor_id, tenant_id, request_id, action, template_id, key, source_ip, metadata)
            VALUES (:actor_id, :tenant_id, :request_id, :action, :template_id, :key,
                    CAST(:source_ip AS inet), CAST(:metadata AS jsonb))
            """
        ),
        {
            "actor_id": actor_id,
            "tenant_id": tenant_id,
            "request_id": request_id,
            "action": action,
            "template_id": str(template_id),
            "key": key,
            "source_ip": _valid_ip,
            "metadata": json.dumps(metadata) if metadata else None,
        },
    )


def _get_source_ip(request: Request) -> Optional[str]:
    """Extract client IP from request, preferring X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _set_no_cache(response: Response) -> None:
    """Apply no-store cache headers to a response."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


# ---------------------------------------------------------------------------
# POST /platform/templates/{template_id}/credentials
# ---------------------------------------------------------------------------


@router.post(
    "/platform/templates/{template_id}/credentials",
    status_code=status.HTTP_201_CREATED,
)
async def store_credential(
    template_id: uuid.UUID,
    body: StoreCredentialRequest,
    request: Request,
    response: Response,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Store a new platform credential for an agent template (FR-01).

    Returns 201 with metadata. The credential VALUE is never returned.
    """
    _set_no_cache(response)

    # 1. Verify template exists
    result = await db.execute(
        text("SELECT id FROM agent_templates WHERE id = :tid"),
        {"tid": str(template_id)},
    )
    if result.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent template {template_id} not found",
        )

    # 2. Check for existing active key with same (template_id, key)
    dup_result = await db.execute(
        text(
            "SELECT id FROM platform_credential_metadata "
            "WHERE template_id = :tid AND key = :key AND deleted_at IS NULL"
        ),
        {"tid": str(template_id), "key": body.key},
    )
    if dup_result.fetchone() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Credential key '{body.key}' already exists for this template. Use PUT to rotate.",
        )

    injection_config = body.injection_config or _DEFAULT_INJECTION_CONFIG

    # 3. Write value to vault
    try:
        set_platform_credential(
            template_id=str(template_id),
            key=body.key,
            value=body.value,
            allowed_domains=body.allowed_domains,
            injection_config=injection_config,
            description=body.description,
            actor_id=current_user.id,
        )
    except PlatformVaultUnavailableError as exc:
        logger.error(
            "platform_vault_unavailable",
            template_id=str(template_id),
            key=body.key,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Platform credential vault is not available",
        )

    # 4. Insert metadata row
    now = datetime.now(timezone.utc)
    meta_result = await db.execute(
        text(
            """
            INSERT INTO platform_credential_metadata
            (template_id, key, description, allowed_domains, version,
             injection_config, created_by, updated_by, created_at, updated_at)
            VALUES (
                :template_id, :key, :description, CAST(:allowed_domains AS jsonb),
                1, CAST(:injection_config AS jsonb), :created_by, :created_by,
                :now, :now
            )
            RETURNING id, created_at
            """
        ),
        {
            "template_id": str(template_id),
            "key": body.key,
            "description": body.description,
            "allowed_domains": json.dumps(body.allowed_domains),
            "injection_config": json.dumps(injection_config),
            "created_by": current_user.id,
            "now": now,
        },
    )
    inserted = meta_result.fetchone()

    # 5. Insert audit row
    await _write_audit(
        db=db,
        action="store",
        template_id=template_id,
        key=body.key,
        actor_id=current_user.id,
        source_ip=_get_source_ip(request),
    )

    await db.commit()

    logger.info(
        "platform_credential_stored_via_api",
        template_id=str(template_id),
        key=body.key,
        actor_id=current_user.id,
    )

    return {
        "key": body.key,
        "template_id": str(template_id),
        "description": body.description,
        "version": 1,
        "created_at": inserted[1].isoformat() if inserted else now.isoformat(),
        "created_by": current_user.id,
    }


# ---------------------------------------------------------------------------
# GET /platform/templates/{template_id}/credentials
# ---------------------------------------------------------------------------


@router.get("/platform/templates/{template_id}/credentials")
async def list_credentials(
    template_id: uuid.UUID,
    response: Response,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """List all active credential keys for an agent template (FR-02).

    Credential VALUES are never returned — only key names and metadata.
    """
    _set_no_cache(response)

    # Verify template exists
    result = await db.execute(
        text("SELECT id FROM agent_templates WHERE id = :tid"),
        {"tid": str(template_id)},
    )
    if result.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent template {template_id} not found",
        )

    rows_result = await db.execute(
        text(
            """
            SELECT key, description, created_at, updated_at, created_by, version, injection_config
            FROM platform_credential_metadata
            WHERE template_id = :tid AND deleted_at IS NULL
            ORDER BY created_at ASC
            """
        ),
        {"tid": str(template_id)},
    )
    rows = rows_result.fetchall()

    credentials = [
        {
            "key": row[0],
            "description": row[1],
            "created_at": row[2].isoformat() if row[2] else None,
            "updated_at": row[3].isoformat() if row[3] else None,
            "created_by": row[4],
            "version": row[5],
            "injection_config": row[6],
        }
        for row in rows
    ]

    return {
        "template_id": str(template_id),
        "credentials": credentials,
    }


# ---------------------------------------------------------------------------
# GET /platform/templates/{template_id}/credentials/health
# NOTE: This route MUST be declared before /{key} to prevent path shadowing.
# ---------------------------------------------------------------------------


@router.get("/platform/templates/{template_id}/credentials/health")
async def credential_health(
    template_id: uuid.UUID,
    response: Response,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Check completeness of platform credentials for a template (FR-06/07).

    Returns per-key status: stored | missing | revoked.
    Overall status: complete | incomplete | not_required.
    """
    _set_no_cache(response)

    # 1. Fetch template and its required_credentials
    tmpl_result = await db.execute(
        text(
            "SELECT id, required_credentials FROM agent_templates WHERE id = :tid"
        ),
        {"tid": str(template_id)},
    )
    tmpl_row = tmpl_result.fetchone()
    if tmpl_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent template {template_id} not found",
        )

    required_credentials = tmpl_row[1] or []
    if not required_credentials:
        return {
            "template_id": str(template_id),
            "required_credentials": [],
            "status": "not_required",
            "keys": {},
        }

    # Extract string keys — required_credentials may be stored as [{key: str}] or [str]
    if required_credentials and isinstance(required_credentials[0], dict):
        required_keys = [
            c.get("key") or c.get("name") or ""
            for c in required_credentials
            if isinstance(c, dict)
        ]
        required_keys = [k for k in required_keys if k]
    else:
        required_keys = [c for c in required_credentials if isinstance(c, str)]

    if not required_keys:
        return {
            "template_id": str(template_id),
            "required_credentials": [],
            "status": "not_required",
            "keys": {},
        }

    # 2. Get vault-level health (stored | missing)
    health = await get_platform_credential_health(str(template_id), required_keys)

    # 3. Merge with DB metadata to detect "revoked" (soft-deleted) keys
    db_result = await db.execute(
        text(
            """
            SELECT key, deleted_at
            FROM platform_credential_metadata
            WHERE template_id = :tid AND key = ANY(:keys)
            """
        ),
        {"tid": str(template_id), "keys": required_keys},
    )
    db_rows = db_result.fetchall()

    # Build a map: key -> deleted_at (None means active)
    db_key_map: dict = {}
    for row in db_rows:
        db_key_map[row[0]] = row[1]  # None if active, timestamp if revoked

    # Override vault status with "revoked" if soft-deleted in DB
    keys_status = dict(health["keys"])
    for key, deleted_at in db_key_map.items():
        if deleted_at is not None:
            keys_status[key] = "revoked"

    # Recalculate overall status after merging revoked state
    all_stored = all(v == "stored" for v in keys_status.values())
    any_incomplete = any(v in ("missing", "revoked") for v in keys_status.values())

    if all_stored:
        overall_status = "complete"
    elif any_incomplete:
        overall_status = "incomplete"
    else:
        overall_status = "incomplete"

    return {
        "template_id": str(template_id),
        "required_credentials": required_keys,
        "status": overall_status,
        "keys": keys_status,
    }


# ---------------------------------------------------------------------------
# PUT /platform/templates/{template_id}/credentials/{key}
# ---------------------------------------------------------------------------


@router.put("/platform/templates/{template_id}/credentials/{key}")
async def rotate_credential(
    template_id: uuid.UUID,
    key: str,
    body: RotateCredentialRequest,
    request: Request,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Rotate a platform credential value (FR-03).

    Requires `If-Match: {version}` header for optimistic concurrency control.
    Returns 409 if the version does not match the current metadata version.
    """
    _set_no_cache(response)

    # 1. Require If-Match header
    if if_match is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="If-Match header is required for credential rotation. "
            "Provide the current credential version as the If-Match value.",
        )

    try:
        expected_version = int(if_match)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"If-Match header must be a valid integer version. Got: '{if_match}'",
        )

    # 2. Fetch active metadata row
    meta_result = await db.execute(
        text(
            """
            SELECT id, version, deleted_at, updated_at
            FROM platform_credential_metadata
            WHERE template_id = :tid AND key = :key
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"tid": str(template_id), "key": key},
    )
    meta_row = meta_result.fetchone()
    if meta_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential key '{key}' not found for template {template_id}",
        )

    # 3. Check if deleted
    if meta_row[2] is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot rotate a deleted credential '{key}'. Store a new credential instead.",
        )

    # 4. Check optimistic concurrency version
    current_version = meta_row[1]
    if current_version != expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Credential version mismatch: expected {expected_version}, "
                f"current is {current_version}. Fetch the latest version and retry."
            ),
        )

    # 5. Write new value to vault
    try:
        set_platform_credential(
            template_id=str(template_id),
            key=key,
            value=body.value,
            actor_id=current_user.id,
        )
    except PlatformVaultUnavailableError as exc:
        logger.error(
            "platform_vault_unavailable_rotate",
            template_id=str(template_id),
            key=key,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Platform credential vault is not available",
        )

    # 6. Update metadata row
    new_version = current_version + 1
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            """
            UPDATE platform_credential_metadata
            SET version = :new_version, updated_at = :now, updated_by = :updated_by
            WHERE template_id = :tid AND key = :key AND deleted_at IS NULL
            """
        ),
        {
            "new_version": new_version,
            "now": now,
            "updated_by": current_user.id,
            "tid": str(template_id),
            "key": key,
        },
    )

    # 7. Insert audit row
    await _write_audit(
        db=db,
        action="rotate",
        template_id=template_id,
        key=key,
        actor_id=current_user.id,
        source_ip=_get_source_ip(request),
    )

    await db.commit()

    logger.info(
        "platform_credential_rotated",
        template_id=str(template_id),
        key=key,
        new_version=new_version,
        actor_id=current_user.id,
    )

    return {
        "key": key,
        "template_id": str(template_id),
        "updated_at": now.isoformat(),
        "updated_by": current_user.id,
        "version": new_version,
    }


# ---------------------------------------------------------------------------
# DELETE /platform/templates/{template_id}/credentials/{key}
# ---------------------------------------------------------------------------


@router.delete("/platform/templates/{template_id}/credentials/{key}")
async def delete_credential(
    template_id: uuid.UUID,
    key: str,
    request: Request,
    response: Response,
    force: bool = Query(False, description="Force delete even when active agents exist"),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Soft-delete a platform credential (FR-04).

    Returns 409 with affected_agent_count when active agents exist and force=false.
    Credential value is purged from the vault; metadata row is soft-deleted with
    a 30-day retention period.
    """
    _set_no_cache(response)

    # 1. Fetch active metadata row
    meta_result = await db.execute(
        text(
            """
            SELECT id, deleted_at
            FROM platform_credential_metadata
            WHERE template_id = :tid AND key = :key
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"tid": str(template_id), "key": key},
    )
    meta_row = meta_result.fetchone()
    if meta_row is None or meta_row[1] is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active credential key '{key}' not found for template {template_id}",
        )

    # 2. Count active agent cards deployed from this template
    count_result = await db.execute(
        text(
            """
            SELECT COUNT(*)
            FROM agent_cards
            WHERE template_id = :tid AND status = 'active'
            """
        ),
        {"tid": str(template_id)},
    )
    active_agent_count = count_result.scalar() or 0

    if active_agent_count > 0 and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "active_agents",
                "affected_agent_count": active_agent_count,
                "force_available": True,
                "message": (
                    f"{active_agent_count} active agent(s) use this template with "
                    "platform_credentials auth. Use ?force=true to delete anyway."
                ),
            },
        )

    # 3. Soft-delete the metadata row
    now = datetime.now(timezone.utc)
    retention_until = now + timedelta(days=30)

    await db.execute(
        text(
            """
            UPDATE platform_credential_metadata
            SET deleted_at = :now, deleted_by = :deleted_by, retention_until = :retention_until
            WHERE template_id = :tid AND key = :key AND deleted_at IS NULL
            """
        ),
        {
            "now": now,
            "deleted_by": current_user.id,
            "retention_until": retention_until,
            "tid": str(template_id),
            "key": key,
        },
    )

    # 4. Delete value from vault
    delete_platform_credential(
        template_id=str(template_id),
        key=key,
        actor_id=current_user.id,
    )

    # 5. Insert audit row
    await _write_audit(
        db=db,
        action="delete",
        template_id=template_id,
        key=key,
        actor_id=current_user.id,
        source_ip=_get_source_ip(request),
        metadata={"affected_agents": active_agent_count},
    )

    await db.commit()

    logger.info(
        "platform_credential_deleted_via_api",
        template_id=str(template_id),
        key=key,
        actor_id=current_user.id,
        affected_agents=active_agent_count,
        force=force,
    )

    return {
        "key": key,
        "deleted_at": now.isoformat(),
        "retention_until": retention_until.isoformat(),
        "affected_agents": active_agent_count,
    }
