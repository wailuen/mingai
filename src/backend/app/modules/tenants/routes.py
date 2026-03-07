"""
Platform admin tenant routes (API-024 to API-034).

Endpoints:
- GET    /platform/tenants           — List all tenants
- POST   /platform/tenants           — Provision new tenant
- GET    /platform/tenants/{id}      — Get tenant
- PATCH  /platform/tenants/{id}      — Update tenant
- POST   /platform/tenants/{id}/suspend  — Suspend tenant
- POST   /platform/tenants/{id}/activate — Activate tenant
- GET    /platform/llm-profiles      — List LLM profiles
- POST   /platform/llm-profiles      — Create LLM profile
- GET    /platform/stats             — Platform-wide stats
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.dependencies import CurrentUser, require_platform_admin

logger = structlog.get_logger()

router = APIRouter(prefix="/platform", tags=["platform"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateTenantRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    plan: str = Field(..., min_length=1, max_length=50)
    contact_email: Optional[str] = None
    max_users: Optional[int] = Field(None, ge=1)


class UpdateTenantRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    plan: Optional[str] = Field(None, max_length=50)
    contact_email: Optional[str] = None
    max_users: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None


class CreateLLMProfileRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    provider: str = Field(..., min_length=1, max_length=50)
    deployment_name: str = Field(..., min_length=1, max_length=200)
    slot: Optional[str] = Field(None, max_length=50)


# ---------------------------------------------------------------------------
# DB helper functions (mockable in unit tests)
# ---------------------------------------------------------------------------


async def list_tenants_db(page: int, page_size: int, db) -> dict:
    """List all tenants (platform admin view)."""
    offset = (page - 1) * page_size
    count_result = await db.execute("SELECT COUNT(*) FROM tenants")
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        "SELECT id, name, plan, status, created_at FROM tenants "
        "ORDER BY created_at DESC LIMIT :limit OFFSET :offset",
        {"limit": page_size, "offset": offset},
    )
    rows = rows_result.fetchall()
    items = [
        {
            "id": r[0],
            "name": r[1],
            "plan": r[2],
            "status": r[3],
            "created_at": str(r[4]),
        }
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def create_tenant_db(
    name: str,
    plan: str,
    contact_email: Optional[str],
    max_users: Optional[int],
    db,
) -> dict:
    """Provision a new tenant."""
    tenant_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO tenants (id, name, plan, contact_email, max_users, status) "
        "VALUES (:id, :name, :plan, :contact_email, :max_users, 'active')",
        {
            "id": tenant_id,
            "name": name,
            "plan": plan,
            "contact_email": contact_email,
            "max_users": max_users or 100,
        },
    )
    logger.info("tenant_created", tenant_id=tenant_id, name=name, plan=plan)
    return {"id": tenant_id, "name": name, "plan": plan, "status": "active"}


async def get_tenant_db(tenant_id: str, db) -> Optional[dict]:
    """Get a tenant by ID."""
    result = await db.execute(
        "SELECT id, name, plan, status, contact_email, max_users, created_at FROM tenants "
        "WHERE id = :id",
        {"id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "plan": row[2],
        "status": row[3],
        "contact_email": row[4],
        "max_users": row[5],
        "created_at": str(row[6]),
    }


async def update_tenant_db(tenant_id: str, updates: dict, db) -> Optional[dict]:
    """Update tenant fields."""
    set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
    params = {"id": tenant_id, **updates}
    await db.execute(
        f"UPDATE tenants SET {set_clauses} WHERE id = :id",
        params,
    )
    return await get_tenant_db(tenant_id, db)


async def suspend_tenant_db(tenant_id: str, db) -> Optional[dict]:
    """Set tenant status to suspended."""
    result = await db.execute(
        "UPDATE tenants SET status = 'suspended' WHERE id = :id",
        {"id": tenant_id},
    )
    if (result.rowcount or 0) == 0:
        return None
    logger.info("tenant_suspended", tenant_id=tenant_id)
    return {"id": tenant_id, "status": "suspended"}


async def activate_tenant_db(tenant_id: str, db) -> Optional[dict]:
    """Set tenant status to active."""
    result = await db.execute(
        "UPDATE tenants SET status = 'active' WHERE id = :id",
        {"id": tenant_id},
    )
    if (result.rowcount or 0) == 0:
        return None
    logger.info("tenant_activated", tenant_id=tenant_id)
    return {"id": tenant_id, "status": "active"}


async def list_llm_profiles_db(db) -> list:
    """List all LLM profiles."""
    result = await db.execute(
        "SELECT id, name, provider, deployment_name, slot, created_at FROM llm_profiles "
        "ORDER BY created_at DESC"
    )
    return [
        {
            "id": r[0],
            "name": r[1],
            "provider": r[2],
            "deployment_name": r[3],
            "slot": r[4],
            "created_at": str(r[5]),
        }
        for r in result.fetchall()
    ]


async def create_llm_profile_db(
    name: str,
    provider: str,
    deployment_name: str,
    slot: Optional[str],
    db,
) -> dict:
    """Create a new LLM profile."""
    profile_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO llm_profiles (id, name, provider, deployment_name, slot) "
        "VALUES (:id, :name, :provider, :deployment_name, :slot)",
        {
            "id": profile_id,
            "name": name,
            "provider": provider,
            "deployment_name": deployment_name,
            "slot": slot,
        },
    )
    logger.info(
        "llm_profile_created", profile_id=profile_id, name=name, provider=provider
    )
    return {
        "id": profile_id,
        "name": name,
        "provider": provider,
        "deployment_name": deployment_name,
        "slot": slot,
    }


async def get_platform_stats_db(db) -> dict:
    """Collect platform-wide statistics."""
    tenant_count = (await db.execute("SELECT COUNT(*) FROM tenants")).scalar() or 0

    active_tenant_count = (
        await db.execute("SELECT COUNT(*) FROM tenants WHERE status = 'active'")
    ).scalar() or 0

    user_count = (
        await db.execute("SELECT COUNT(*) FROM users WHERE is_active = true")
    ).scalar() or 0

    import datetime

    today = datetime.date.today().isoformat()
    queries_today = (
        await db.execute(
            "SELECT COUNT(*) FROM messages WHERE role = 'user' AND created_at::date = :today",
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
):
    """API-024: List all tenants (platform admin only)."""
    result = await list_tenants_db(page=page, page_size=page_size, db=None)
    return result


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    request: CreateTenantRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
):
    """API-025: Provision a new tenant."""
    result = await create_tenant_db(
        name=request.name,
        plan=request.plan,
        contact_email=request.contact_email,
        max_users=request.max_users,
        db=None,
    )
    return result


@router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
):
    """API-026: Get tenant details."""
    result = await get_tenant_db(tenant_id=tenant_id, db=None)
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
):
    """API-027: Update tenant configuration."""
    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )
    result = await update_tenant_db(tenant_id=tenant_id, updates=updates, db=None)
    return result


@router.post("/tenants/{tenant_id}/suspend")
async def suspend_tenant(
    tenant_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
):
    """API-028: Suspend a tenant (blocks all logins)."""
    result = await suspend_tenant_db(tenant_id=tenant_id, db=None)
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
):
    """API-029: Activate a suspended tenant."""
    result = await activate_tenant_db(tenant_id=tenant_id, db=None)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found",
        )
    return result


@router.get("/llm-profiles")
async def list_llm_profiles(
    current_user: CurrentUser = Depends(require_platform_admin),
):
    """API-030: List all LLM deployment profiles."""
    result = await list_llm_profiles_db(db=None)
    return result


@router.post("/llm-profiles", status_code=status.HTTP_201_CREATED)
async def create_llm_profile(
    request: CreateLLMProfileRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
):
    """API-031: Create a new LLM profile mapping slot → deployment."""
    result = await create_llm_profile_db(
        name=request.name,
        provider=request.provider,
        deployment_name=request.deployment_name,
        slot=request.slot,
        db=None,
    )
    return result


@router.get("/stats")
async def get_platform_stats(
    current_user: CurrentUser = Depends(require_platform_admin),
):
    """API-034: Get platform-wide statistics."""
    result = await get_platform_stats_db(db=None)
    return result
