"""
Platform LLM Provider Credentials Management API (PVDR-003).

Platform admins manage encrypted LLM provider credentials.
All endpoints require platform admin scope.

Endpoints:
    GET    /platform/providers                      — list all providers
    GET    /platform/providers/health-summary       — aggregate health stats
    GET    /platform/providers/{id}                 — get detail
    POST   /platform/providers                      — create provider
    PATCH  /platform/providers/{id}                 — update provider
    DELETE /platform/providers/{id}                 — delete provider
    POST   /platform/providers/{id}/test            — connectivity test
    POST   /platform/providers/{id}/set-default     — set as default

Security:
    - api_key is accepted at POST/PATCH but NEVER returned in any response
    - api_key is logged as "[REDACTED]" in all structlog calls
    - All routes require require_platform_admin
    - 403 messages never disclose scope/roles
"""
import time
import uuid as _uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_platform_admin
from app.core.llm.provider_service import ProviderService, _VALID_PROVIDER_TYPES
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/platform/providers", tags=["platform-providers"])

_svc = ProviderService()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateProviderRequest(BaseModel):
    provider_type: str = Field(
        ...,
        description="One of: azure_openai, openai, anthropic, deepseek, dashscope, doubao, gemini",
    )
    display_name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    endpoint: Optional[str] = Field(None, max_length=500)
    api_key: str = Field(
        ...,
        min_length=1,
        description="Plaintext API key — encrypted at rest, never returned",
    )
    models: dict = Field(
        default_factory=dict, description="Slot → deployment name mapping"
    )
    options: dict = Field(default_factory=dict, description="Provider-specific options")
    pricing: Optional[dict] = None
    is_enabled: bool = True
    is_default: bool = False

    model_config = {"protected_namespaces": ()}


class UpdateProviderRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    endpoint: Optional[str] = Field(None, max_length=500)
    api_key: Optional[str] = Field(
        None, min_length=1, description="New API key — omit to keep existing"
    )
    models: Optional[dict] = None
    options: Optional[dict] = None
    pricing: Optional[dict] = None
    is_enabled: Optional[bool] = None

    model_config = {"protected_namespaces": ()}


class TestConnectivityResponse(BaseModel):
    success: bool
    latency_ms: int
    error: Optional[str] = None


class ProviderResponse(BaseModel):
    """Safe provider dict — no api_key_encrypted field."""

    id: str
    provider_type: str
    display_name: str
    description: Optional[str] = None
    endpoint: Optional[str] = None
    models: dict = {}
    options: dict = {}
    pricing: Optional[dict] = None
    is_enabled: bool
    is_default: bool
    provider_status: str
    last_health_check_at: Optional[str] = None
    health_error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    key_present: bool

    model_config = {"protected_namespaces": ()}


class ProviderListResponse(BaseModel):
    providers: list[ProviderResponse]
    bootstrap_active: bool  # True when 0 rows or env fallback active

    model_config = {"protected_namespaces": ()}


class HealthSummaryResponse(BaseModel):
    total: int
    healthy: int
    error: int
    unchecked: int
    last_checked_at: Optional[str] = None

    model_config = {"protected_namespaces": ()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_platform_scope_stmt():
    return text("SELECT set_config('app.scope', 'platform', true)")


async def _check_env_fallback_active(db: AsyncSession) -> bool:
    """Return True if zero provider rows exist (env fallback is active)."""
    await db.execute(_set_platform_scope_stmt())
    result = await db.execute(text("SELECT COUNT(*) FROM llm_providers"))
    row = result.fetchone()
    return (int(row[0]) if row else 0) == 0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=ProviderListResponse)
async def list_providers(
    enabled_only: bool = Query(False, description="Return only enabled providers"),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """List all platform LLM providers. Never returns api_key_encrypted."""
    providers = await _svc.list_providers(db, enabled_only=enabled_only)
    bootstrap_active = len(providers) == 0

    return ProviderListResponse(
        providers=[ProviderResponse(**p) for p in providers],
        bootstrap_active=bootstrap_active,
    )


@router.get("/health-summary", response_model=HealthSummaryResponse)
async def get_health_summary(
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Aggregate health status across all enabled providers (PVDR-011)."""
    await db.execute(_set_platform_scope_stmt())

    result = await db.execute(
        text(
            "SELECT provider_status, COUNT(*), MAX(last_health_check_at) "
            "FROM llm_providers WHERE is_enabled = true "
            "GROUP BY provider_status"
        )
    )
    rows = result.fetchall()

    total = 0
    healthy = 0
    error_count = 0
    unchecked = 0
    last_checked_at = None

    for row in rows:
        status_val, count, last_check = row[0], int(row[1]), row[2]
        total += count
        if status_val == "healthy":
            healthy += count
        elif status_val in ("error", "timeout", "auth_failed"):
            error_count += count
        elif status_val == "unchecked":
            unchecked += count
        if last_check is not None:
            if last_checked_at is None or last_check > last_checked_at:
                last_checked_at = last_check

    return HealthSummaryResponse(
        total=total,
        healthy=healthy,
        error=error_count,
        unchecked=unchecked,
        last_checked_at=last_checked_at.isoformat() if last_checked_at else None,
    )


@router.get("/{provider_id}", response_model=ProviderResponse)
async def get_provider(
    provider_id: _uuid.UUID,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Get a single provider. Never returns api_key_encrypted."""
    provider = await _svc.get_provider(db, str(provider_id))
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )
    return ProviderResponse(**provider)


@router.post("", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_provider(
    request: CreateProviderRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Create a new LLM provider. api_key is encrypted at rest and never returned.
    api_key is logged as "[REDACTED]".
    """
    if request.provider_type not in _VALID_PROVIDER_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"provider_type must be one of: {sorted(_VALID_PROVIDER_TYPES)}",
        )

    if request.provider_type == "azure_openai" and not request.endpoint:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="endpoint is required for azure_openai provider type",
        )

    payload = {
        "provider_type": request.provider_type,
        "display_name": request.display_name,
        "description": request.description,
        "endpoint": request.endpoint,
        "api_key": request.api_key,
        "models": request.models,
        "options": request.options,
        "pricing": request.pricing,
        "is_enabled": request.is_enabled,
        "is_default": request.is_default,
    }

    provider = await _svc.create_provider(db, payload, created_by=current_user.user_id)

    logger.info(
        "platform_provider_created",
        provider_id=provider["id"],
        provider_type=request.provider_type,
        created_by=current_user.user_id,
        api_key="[REDACTED]",
    )

    return ProviderResponse(**provider)


@router.patch("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: _uuid.UUID,
    request: UpdateProviderRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Update provider fields. Omit api_key to keep existing encrypted key.
    api_key is logged as "[REDACTED]" if provided.
    """
    updates = {}
    if request.display_name is not None:
        updates["display_name"] = request.display_name
    if request.description is not None:
        updates["description"] = request.description
    if request.endpoint is not None:
        updates["endpoint"] = request.endpoint
    if request.api_key is not None:
        updates["api_key"] = request.api_key
    if request.models is not None:
        updates["models"] = request.models
    if request.options is not None:
        updates["options"] = request.options
    if request.pricing is not None:
        updates["pricing"] = request.pricing
    if request.is_enabled is not None:
        updates["is_enabled"] = request.is_enabled

    provider = await _svc.update_provider(db, str(provider_id), updates)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )

    logger.info(
        "platform_provider_updated",
        provider_id=provider_id,
        updated_by=current_user.user_id,
        api_key="[REDACTED]" if request.api_key is not None else None,
    )

    return ProviderResponse(**provider)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: _uuid.UUID,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Delete a provider.
    Returns 409 if the provider is the default or the only enabled provider.
    """
    provider = await _svc.get_provider(db, str(provider_id))
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )

    if provider["is_default"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete the default provider. Set another provider as default first.",
        )

    # Check if it's the only enabled provider
    await db.execute(_set_platform_scope_stmt())
    count_result = await db.execute(
        text("SELECT COUNT(*) FROM llm_providers WHERE is_enabled = true")
    )
    count_row = count_result.fetchone()
    enabled_count = int(count_row[0]) if count_row else 0

    if enabled_count == 1 and provider["is_enabled"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete the only enabled provider.",
        )

    deleted = await _svc.delete_provider(db, str(provider_id))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )

    logger.info(
        "platform_provider_deleted",
        provider_id=provider_id,
        deleted_by=current_user.user_id,
    )


@router.post("/{provider_id}/test", response_model=TestConnectivityResponse)
async def test_provider(
    provider_id: _uuid.UUID,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Test connectivity to a provider via a real API call.
    Returns latency_ms measured from test start to completion.
    """
    provider = await _svc.get_provider(db, str(provider_id))
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )

    start = time.time()
    success, error = await _svc.test_connectivity(provider)
    latency_ms = int((time.time() - start) * 1000)

    # Update provider_status and last_health_check_at
    new_status = "healthy" if success else "error"
    await _svc.update_provider(
        db,
        str(provider_id),
        {
            "provider_status": new_status,
        },
    )
    await db.execute(_set_platform_scope_stmt())
    await db.execute(
        text(
            "UPDATE llm_providers SET last_health_check_at = NOW(), "
            "health_error = :health_error WHERE id = :id"
        ),
        {"health_error": error, "id": str(provider_id)},
    )
    await db.commit()

    logger.info(
        "platform_provider_tested",
        provider_id=provider_id,
        success=success,
        latency_ms=latency_ms,
        tested_by=current_user.user_id,
    )

    return TestConnectivityResponse(
        success=success,
        latency_ms=latency_ms,
        error=error,
    )


@router.post("/{provider_id}/set-default", status_code=status.HTTP_200_OK)
async def set_default_provider(
    provider_id: _uuid.UUID,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Atomically set a provider as the default.
    Clears is_default from all other rows, then sets this one.
    """
    provider = await _svc.get_provider(db, str(provider_id))
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )

    if not provider["is_enabled"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot set a disabled provider as default",
        )

    await _svc.set_default(db, str(provider_id))

    logger.info(
        "platform_provider_default_set",
        provider_id=provider_id,
        set_by=current_user.user_id,
    )

    updated = await _svc.get_provider(db, str(provider_id))
    return ProviderResponse(**updated)
