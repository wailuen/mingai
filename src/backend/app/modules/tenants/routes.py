"""
Platform admin tenant routes (API-024 to API-034).

Endpoints:
- GET    /platform/tenants           — List all tenants
- POST   /platform/tenants           — Provision new tenant
- GET    /platform/tenants/{id}      — Get tenant
- PATCH  /platform/tenants/{id}      — Update tenant
- POST   /platform/tenants/{id}/suspend  — Suspend tenant
- POST   /platform/tenants/{id}/activate — Activate tenant
- GET    /platform/llm-profiles      — List LLM profiles (platform-wide)
- POST   /platform/llm-profiles      — Create LLM profile for a tenant
- GET    /platform/stats             — Platform-wide stats

Schema notes:
- tenants: id, name, slug (UNIQUE NOT NULL), plan, status, primary_contact_email (NOT NULL)
- llm_profiles: tenant-scoped, fields: name, provider, primary_model, intent_model,
  embedding_model, endpoint_url, api_key_ref, is_default
"""
import datetime
import re
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_platform_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/platform", tags=["platform"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateTenantRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    plan: str = Field("professional", min_length=1, max_length=50)
    primary_contact_email: EmailStr
    slug: Optional[str] = Field(None, max_length=100)


class UpdateTenantRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    plan: Optional[str] = Field(None, max_length=50)
    primary_contact_email: Optional[EmailStr] = None
    status: Optional[str] = Field(None, pattern="^(active|suspended)$")


class CreateLLMProfileRequest(BaseModel):
    tenant_id: str = Field(..., description="Tenant this profile belongs to")
    name: str = Field(..., min_length=1, max_length=200)
    provider: str = Field(..., min_length=1, max_length=100)
    primary_model: str = Field(..., min_length=1, max_length=255)
    intent_model: str = Field(..., min_length=1, max_length=255)
    embedding_model: str = Field(..., min_length=1, max_length=255)
    endpoint_url: Optional[str] = Field(None, max_length=500)
    api_key_ref: Optional[str] = Field(None, max_length=500)
    is_default: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    """Generate a URL-safe slug from a tenant name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:100] or "tenant"


# ---------------------------------------------------------------------------
# DB helper functions (mockable in unit tests)
# ---------------------------------------------------------------------------


async def list_tenants_db(page: int, page_size: int, db) -> dict:
    """List all tenants (platform admin view)."""
    offset = (page - 1) * page_size
    count_result = await db.execute(text("SELECT COUNT(*) FROM tenants"))
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        text(
            "SELECT id, name, slug, plan, status, primary_contact_email, created_at "
            "FROM tenants "
            "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        ),
        {"limit": page_size, "offset": offset},
    )
    rows = rows_result.fetchall()
    items = [
        {
            "id": str(r[0]),
            "name": r[1],
            "slug": r[2],
            "plan": r[3],
            "status": r[4],
            "primary_contact_email": r[5],
            "created_at": str(r[6]),
        }
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def create_tenant_db(
    name: str,
    plan: str,
    primary_contact_email: str,
    slug: Optional[str],
    db,
) -> dict:
    """Provision a new tenant."""
    tenant_id = str(uuid.uuid4())
    effective_slug = slug or _slugify(name)
    # Ensure slug uniqueness by appending short UUID suffix if needed
    suffix = tenant_id[:8]
    effective_slug = f"{effective_slug}-{suffix}"

    await db.execute(
        text(
            "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
            "VALUES (:id, :name, :slug, :plan, :primary_contact_email, 'active')"
        ),
        {
            "id": tenant_id,
            "name": name,
            "slug": effective_slug,
            "plan": plan,
            "primary_contact_email": primary_contact_email,
        },
    )
    await db.commit()
    logger.info("tenant_created", tenant_id=tenant_id, name=name, plan=plan)
    return {
        "id": tenant_id,
        "name": name,
        "slug": effective_slug,
        "plan": plan,
        "status": "active",
        "primary_contact_email": primary_contact_email,
    }


async def get_tenant_db(tenant_id: str, db) -> Optional[dict]:
    """Get a tenant by ID."""
    result = await db.execute(
        text(
            "SELECT id, name, slug, plan, status, primary_contact_email, created_at "
            "FROM tenants WHERE id = :id"
        ),
        {"id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "name": row[1],
        "slug": row[2],
        "plan": row[3],
        "status": row[4],
        "primary_contact_email": row[5],
        "created_at": str(row[6]),
    }


_TENANT_UPDATE_ALLOWLIST = {"name", "plan", "primary_contact_email", "status"}


async def update_tenant_db(tenant_id: str, updates: dict, db) -> Optional[dict]:
    """Update tenant fields."""
    invalid = set(updates) - _TENANT_UPDATE_ALLOWLIST
    if invalid:
        raise ValueError(f"Invalid tenant update fields: {invalid}")
    set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
    params = {"id": tenant_id, **updates}
    result = await db.execute(
        text(f"UPDATE tenants SET {set_clauses} WHERE id = :id"),
        params,
    )
    await db.commit()
    if (result.rowcount or 0) == 0:
        return None
    return await get_tenant_db(tenant_id, db)


async def suspend_tenant_db(tenant_id: str, db) -> Optional[dict]:
    """Set tenant status to suspended."""
    result = await db.execute(
        text("UPDATE tenants SET status = 'suspended' WHERE id = :id"),
        {"id": tenant_id},
    )
    await db.commit()
    if (result.rowcount or 0) == 0:
        return None
    logger.info("tenant_suspended", tenant_id=tenant_id)
    return {"id": tenant_id, "status": "suspended"}


async def activate_tenant_db(tenant_id: str, db) -> Optional[dict]:
    """Set tenant status to active."""
    result = await db.execute(
        text("UPDATE tenants SET status = 'active' WHERE id = :id"),
        {"id": tenant_id},
    )
    await db.commit()
    if (result.rowcount or 0) == 0:
        return None
    logger.info("tenant_activated", tenant_id=tenant_id)
    return {"id": tenant_id, "status": "active"}


async def list_llm_profiles_db(db) -> list:
    """List all LLM profiles across all tenants (platform admin view)."""
    result = await db.execute(
        text(
            "SELECT id, tenant_id, name, provider, primary_model, intent_model, "
            "embedding_model, endpoint_url, is_default, created_at "
            "FROM llm_profiles "
            "ORDER BY created_at DESC"
        )
    )
    return [
        {
            "id": str(r[0]),
            "tenant_id": str(r[1]),
            "name": r[2],
            "provider": r[3],
            "primary_model": r[4],
            "intent_model": r[5],
            "embedding_model": r[6],
            "endpoint_url": r[7],
            "is_default": r[8],
            "created_at": str(r[9]),
        }
        for r in result.fetchall()
    ]


async def create_llm_profile_db(
    tenant_id: str,
    name: str,
    provider: str,
    primary_model: str,
    intent_model: str,
    embedding_model: str,
    endpoint_url: Optional[str],
    api_key_ref: Optional[str],
    is_default: bool,
    db,
) -> dict:
    """Create a new LLM profile for a tenant."""
    profile_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO llm_profiles "
            "(id, tenant_id, name, provider, primary_model, intent_model, "
            "embedding_model, endpoint_url, api_key_ref, is_default) "
            "VALUES (:id, :tenant_id, :name, :provider, :primary_model, :intent_model, "
            ":embedding_model, :endpoint_url, :api_key_ref, :is_default)"
        ),
        {
            "id": profile_id,
            "tenant_id": tenant_id,
            "name": name,
            "provider": provider,
            "primary_model": primary_model,
            "intent_model": intent_model,
            "embedding_model": embedding_model,
            "endpoint_url": endpoint_url,
            "api_key_ref": api_key_ref,
            "is_default": is_default,
        },
    )
    await db.commit()
    logger.info(
        "llm_profile_created",
        profile_id=profile_id,
        name=name,
        provider=provider,
        tenant_id=tenant_id,
    )
    return {
        "id": profile_id,
        "tenant_id": tenant_id,
        "name": name,
        "provider": provider,
        "primary_model": primary_model,
        "intent_model": intent_model,
        "embedding_model": embedding_model,
        "endpoint_url": endpoint_url,
        "is_default": is_default,
    }


async def get_platform_stats_db(db) -> dict:
    """Collect platform-wide statistics."""
    tenant_count = (
        await db.execute(text("SELECT COUNT(*) FROM tenants"))
    ).scalar() or 0

    active_tenant_count = (
        await db.execute(text("SELECT COUNT(*) FROM tenants WHERE status = 'active'"))
    ).scalar() or 0

    user_count = (
        await db.execute(text("SELECT COUNT(*) FROM users WHERE status = 'active'"))
    ).scalar() or 0

    today = datetime.date.today().isoformat()
    queries_today = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM messages "
                "WHERE role = 'user' AND created_at::date = :today"
            ),
            {"today": today},
        )
    ).scalar() or 0

    return {
        "total_tenants": tenant_count,
        "active_tenants": active_tenant_count,
        "total_users": user_count,
        "queries_today": queries_today,
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/tenants")
async def list_tenants(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-024: List all tenants (platform admin only)."""
    result = await list_tenants_db(page=page, page_size=page_size, db=session)
    return result


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    request: CreateTenantRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-025: Provision a new tenant."""
    result = await create_tenant_db(
        name=request.name,
        plan=request.plan,
        primary_contact_email=request.primary_contact_email,
        slug=request.slug,
        db=session,
    )
    return result


@router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-026: Get tenant details."""
    result = await get_tenant_db(tenant_id=tenant_id, db=session)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found",
        )
    return result


@router.patch("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    request: UpdateTenantRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-027: Update tenant configuration."""
    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )
    result = await update_tenant_db(tenant_id=tenant_id, updates=updates, db=session)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found",
        )
    return result


@router.post("/tenants/{tenant_id}/suspend")
async def suspend_tenant(
    tenant_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-028: Suspend a tenant (blocks all logins)."""
    result = await suspend_tenant_db(tenant_id=tenant_id, db=session)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found",
        )
    return result


@router.post("/tenants/{tenant_id}/activate")
async def activate_tenant(
    tenant_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-029: Activate a suspended tenant."""
    result = await activate_tenant_db(tenant_id=tenant_id, db=session)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found",
        )
    return result


@router.get("/llm-profiles")
async def list_llm_profiles(
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-030: List all LLM deployment profiles (platform-wide)."""
    result = await list_llm_profiles_db(db=session)
    return result


@router.post("/llm-profiles", status_code=status.HTTP_201_CREATED)
async def create_llm_profile(
    request: CreateLLMProfileRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-031: Create a new LLM profile for a tenant."""
    result = await create_llm_profile_db(
        tenant_id=request.tenant_id,
        name=request.name,
        provider=request.provider,
        primary_model=request.primary_model,
        intent_model=request.intent_model,
        embedding_model=request.embedding_model,
        endpoint_url=request.endpoint_url,
        api_key_ref=request.api_key_ref,
        is_default=request.is_default,
        db=session,
    )
    return result


@router.get("/stats")
async def get_platform_stats(
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-034: Get platform-wide statistics."""
    result = await get_platform_stats_db(db=session)
    return result
