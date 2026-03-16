"""
BYOLLM (Bring Your Own LLM) API (P2LLM-007).

Enterprise-only. Allows tenants to supply their own LLM provider credentials.
API keys are encrypted at rest using the same Fernet pattern as HAR keypairs.

Endpoints (require tenant_admin + enterprise plan):
    PATCH  /admin/llm-config/byollm  — store encrypted key ref
    DELETE /admin/llm-config/byollm  — remove key, revert to library mode

Security invariants:
    - API key encrypted before persistence using get_fernet() from har/crypto.py
    - Only an opaque encrypted token (encrypted_key_ref) stored in DB
    - Plaintext key is NEVER stored in DB, never logged, never returned in API
    - GET /admin/llm-config shows key_present: bool only — no key value
"""
import json
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session
from app.modules.admin.llm_config import _invalidate_config_cache

logger = structlog.get_logger()

router = APIRouter(prefix="/admin/llm-config", tags=["admin-byollm"])

_VALID_BYOLLM_PROVIDERS = frozenset({"openai_direct", "azure_openai"})


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SetBYOLLMRequest(BaseModel):
    provider: str = Field(..., description="One of: openai_direct, azure_openai")
    api_key: str = Field(
        ..., min_length=1, description="Provider API key — encrypted at rest"
    )
    endpoint: Optional[str] = Field(
        None,
        description="Required for azure_openai, optional for openai_direct",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"provider": "openai_direct", "api_key": "sk-..."}]
        }
    }


class BYOLLMStatusResponse(BaseModel):
    provider: Optional[str] = None
    key_present: bool
    endpoint: Optional[str] = None


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.patch("/byollm", response_model=BYOLLMStatusResponse)
async def set_byollm_config(
    request: SetBYOLLMRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Store BYOLLM provider credentials (encrypted) for this tenant.

    Requires enterprise plan. API key is Fernet-encrypted before storage —
    the plaintext key never touches the database.
    """
    if current_user.plan != "enterprise":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="BYOLLM requires an enterprise plan.",
        )

    if request.provider not in _VALID_BYOLLM_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"provider must be one of {sorted(_VALID_BYOLLM_PROVIDERS)}",
        )

    if request.provider == "azure_openai" and not request.endpoint:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="endpoint is required for azure_openai provider",
        )

    # Encrypt the API key — plaintext key is in-memory only here
    from app.modules.har.crypto import get_fernet

    fernet = get_fernet()
    encrypted_key_ref = fernet.encrypt(request.api_key.encode("utf-8")).decode("ascii")
    # api_key variable goes out of scope — Python GC will collect it

    # Store encrypted ref + provider in tenant_configs
    config_data = {
        "provider": request.provider,
        "encrypted_key_ref": encrypted_key_ref,
        "endpoint": request.endpoint,
    }

    await db.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (:id, :tid, 'byollm_key_ref', CAST(:data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) DO UPDATE SET config_data = CAST(:data AS jsonb)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": current_user.tenant_id,
            "data": json.dumps(config_data),
        },
    )
    # Also update llm_config model_source to byollm
    await db.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (:id, :tid, 'llm_config', CAST(:data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) DO UPDATE SET config_data = CAST(:data AS jsonb)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": current_user.tenant_id,
            "data": json.dumps({"model_source": "byollm", "llm_library_id": None}),
        },
    )
    await db.commit()

    await _invalidate_config_cache(current_user.tenant_id)

    logger.info(
        "byollm_key_stored",
        tenant_id=current_user.tenant_id,
        provider=request.provider,
    )

    # Never return the key or encrypted token — return status only
    return BYOLLMStatusResponse(
        provider=request.provider,
        key_present=True,
        endpoint=request.endpoint,
    )


@router.delete("/byollm", status_code=status.HTTP_204_NO_CONTENT)
async def delete_byollm_config(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Remove BYOLLM credentials for this tenant and revert to library mode.

    Deletes the encrypted key ref from DB. Non-enterprise tenants cannot
    have BYOLLM configured, but can still call DELETE for idempotency.
    """
    # Remove byollm_key_ref row
    await db.execute(
        text(
            "DELETE FROM tenant_configs "
            "WHERE tenant_id = :tid AND config_type = 'byollm_key_ref'"
        ),
        {"tid": current_user.tenant_id},
    )

    # Revert llm_config model_source to library
    await db.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (:id, :tid, 'llm_config', CAST(:data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) DO UPDATE SET config_data = CAST(:data AS jsonb)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": current_user.tenant_id,
            "data": json.dumps({"model_source": "library", "llm_library_id": None}),
        },
    )
    await db.commit()

    await _invalidate_config_cache(current_user.tenant_id)

    logger.info(
        "byollm_key_deleted",
        tenant_id=current_user.tenant_id,
    )
