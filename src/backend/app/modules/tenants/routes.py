"""
Platform admin tenant routes (API-024 to API-034).

Endpoints:
- GET    /platform/tenants           — List all tenants
- POST   /platform/tenants           — Provision new tenant
- GET    /platform/tenants/{id}      — Get tenant
- PATCH  /platform/tenants/{id}      — Update tenant
- POST   /platform/tenants/{id}/suspend  — Suspend tenant
- POST   /platform/tenants/{id}/activate — Activate tenant
- GET    /platform/llm-profiles           — List LLM profiles (platform-wide)
- POST   /platform/llm-profiles           — Create LLM profile for a tenant
- GET    /platform/llm-profiles/{id}      — Get LLM profile by ID
- PATCH  /platform/llm-profiles/{id}      — Update LLM profile
- DELETE /platform/llm-profiles/{id}      — Delete unused LLM profile
- GET    /platform/stats                  — Platform-wide stats
- GET    /platform/tenants/at-risk        — At-risk tenant signal detection (PA-008)
- GET    /platform/tenants/{id}/health    — Health score drilldown with trend (PA-009)
- POST   /platform/tenants/{id}/message  — Platform admin proactive outreach to tenant admins (PA-011)

Schema notes:
- tenants: id, name, slug (UNIQUE NOT NULL), plan, status, primary_contact_email (NOT NULL)
- llm_profiles: tenant-scoped, fields: name, provider, primary_model, intent_model,
  embedding_model, endpoint_url, api_key_ref, is_default
"""
import asyncio
import datetime
import json
import os
import re
import uuid
from typing import List, Optional

import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Path,
    Query,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy.exc import IntegrityError

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_platform_admin
from app.core.session import get_async_session
from app.modules.tenants.worker import run_tenant_provisioning

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


class LLMSlots(BaseModel):
    """Slot-based model assignment used by the Platform Admin UI."""

    primary: str = Field(..., min_length=1, max_length=255)
    intent: str = Field(..., min_length=1, max_length=255)
    embedding: str = Field(..., min_length=1, max_length=255)
    vision: Optional[str] = Field(None, max_length=255)
    router: Optional[str] = Field(None, max_length=255)
    worker: Optional[str] = Field(None, max_length=255)


class CreateLLMProfileRequest(BaseModel):
    """Create an LLM profile.

    Accepts either the flat-field format (primary_model, intent_model,
    embedding_model) or the slot-based format (slots.primary, slots.intent,
    slots.embedding) used by the Platform Admin UI.  When ``slots`` is
    provided it takes precedence over the individual model fields.
    """

    tenant_id: Optional[str] = Field(
        None,
        description="Tenant this profile belongs to; defaults to platform default tenant",
    )
    name: str = Field(..., min_length=1, max_length=200)
    provider: str = Field("azure_openai", min_length=1, max_length=100)
    # Flat-field format
    primary_model: Optional[str] = Field(None, min_length=1, max_length=255)
    intent_model: Optional[str] = Field(None, min_length=1, max_length=255)
    embedding_model: Optional[str] = Field(None, min_length=1, max_length=255)
    # Slot-based format (alternative to flat fields)
    slots: Optional[LLMSlots] = None
    description: Optional[str] = Field(None, max_length=1000)
    endpoint_url: Optional[str] = Field(None, max_length=500)
    api_key_ref: Optional[str] = Field(None, max_length=500)
    is_default: bool = False

    @model_validator(mode="after")
    def resolve_model_fields(self) -> "CreateLLMProfileRequest":
        """Map slots format to flat fields when slots is provided."""
        if self.slots is not None:
            self.primary_model = self.slots.primary
            self.intent_model = self.slots.intent
            self.embedding_model = self.slots.embedding
        # After resolving, all three flat fields must be present
        missing = [
            f
            for f in ("primary_model", "intent_model", "embedding_model")
            if not getattr(self, f)
        ]
        if missing:
            raise ValueError(
                "Provide either 'slots' or all of: primary_model, intent_model, embedding_model"
            )
        return self


class UpdateQuotaRequest(BaseModel):
    monthly_token_limit: Optional[int] = Field(None, ge=0)
    storage_gb: Optional[float] = Field(None, ge=0)
    users_max: Optional[int] = Field(None, ge=1)


class UpdateLLMProfileRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    provider: Optional[str] = Field(None, min_length=1, max_length=100)
    primary_model: Optional[str] = Field(None, min_length=1, max_length=255)
    intent_model: Optional[str] = Field(None, min_length=1, max_length=255)
    embedding_model: Optional[str] = Field(None, min_length=1, max_length=255)
    endpoint_url: Optional[str] = Field(None, max_length=500)
    api_key_ref: Optional[str] = Field(None, max_length=500)
    is_default: Optional[bool] = None


_VALID_SEND_VIA = {"in_app", "email"}


class ProactiveOutreachRequest(BaseModel):
    """PA-011: Platform admin sends in-app/email notification to all tenant admins."""

    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=5000)
    send_via: List[str] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_send_via(self) -> "ProactiveOutreachRequest":
        if not self.send_via:
            raise ValueError("send_via must contain at least one channel")
        invalid = set(self.send_via) - _VALID_SEND_VIA
        if invalid:
            raise ValueError(
                f"Invalid send_via values: {invalid}. Must be one of: {_VALID_SEND_VIA}"
            )
        return self


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
    """
    Insert a new tenant record with status 'active'.

    The caller is responsible for launching run_tenant_provisioning() as a
    background task which will execute the remaining 7 steps and flip the
    status to 'active' on success.
    """
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
    """Update tenant fields.

    Column names are sourced only from the allowlist — never from dict keys directly —
    to structurally prevent SQL injection even if validation is bypassed upstream.
    """
    safe_updates = {k: v for k, v in updates.items() if k in _TENANT_UPDATE_ALLOWLIST}
    invalid = set(updates) - _TENANT_UPDATE_ALLOWLIST
    if invalid:
        raise ValueError(f"Invalid tenant update fields: {invalid}")
    # Column names sourced exclusively from _TENANT_UPDATE_ALLOWLIST (static set).
    # Values remain parameterized (`:col`). No user-controlled strings reach SQL.
    set_clauses = ", ".join(f"{col} = :{col}" for col in safe_updates)
    params = {"id": tenant_id, **safe_updates}
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


async def get_tenant_admins_db(tenant_id: str, db) -> list[dict]:
    """Return all active users with role 'tenant_admin' for a given tenant.

    Used by the proactive outreach endpoint (PA-011) to identify recipients.
    """
    result = await db.execute(
        text(
            "SELECT id, email FROM users "
            "WHERE tenant_id = :tenant_id AND role = 'tenant_admin' "
            "AND status = 'active'"
        ),
        {"tenant_id": tenant_id},
    )
    rows = result.fetchall()
    return [{"id": str(r[0]), "email": r[1]} for r in rows]


async def insert_platform_outreach_notifications_db(
    tenant_id: str,
    recipients: list[dict],
    subject: str,
    body: str,
    db,
) -> None:
    """Insert one notification row per recipient for a platform admin outreach.

    Each row has from_platform_admin = TRUE and type = 'platform_outreach'.
    Notifications are written inside a single transaction; the caller commits.
    """
    for recipient in recipients:
        await db.execute(
            text(
                "INSERT INTO notifications "
                "(id, tenant_id, user_id, type, title, body, read, from_platform_admin) "
                "VALUES (:id, :tenant_id, :user_id, 'platform_outreach', "
                ":title, :body, false, true)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "user_id": recipient["id"],
                "title": subject,
                "body": body,
            },
        )


async def write_audit_log_db(
    tenant_id: str,
    actor_user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict,
    db,
) -> None:
    """Insert one row into audit_log.

    Column names are hardcoded — not sourced from user input.
    CAST(:details AS jsonb) avoids the asyncpg positional-rewriter issue.
    """
    await db.execute(
        text(
            "INSERT INTO audit_log "
            "(id, tenant_id, user_id, action, resource_type, resource_id, details) "
            "VALUES (:id, :tenant_id, :user_id, :action, :resource_type, "
            ":resource_id, CAST(:details AS jsonb))"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "user_id": actor_user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": json.dumps(details),
        },
    )


async def send_outreach_email(
    recipient_email: str,
    subject: str,
    body: str,
) -> None:
    """Send a plain-text email via SendGrid for platform admin outreach.

    Silently skips (logs warning) if SENDGRID_API_KEY is not configured.
    Any SendGrid exception is caught and logged — email failure never aborts
    the overall request.
    """
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        logger.warning(
            "sendgrid_not_configured",
            detail="SENDGRID_API_KEY env var is not set — skipping outreach email",
            recipient_email=recipient_email,
        )
        return

    try:
        import sendgrid  # type: ignore[import]
        from sendgrid.helpers.mail import Mail  # type: ignore[import]

        sg = sendgrid.SendGridAPIClient(api_key=api_key)
        from_email = os.environ.get("SENDGRID_FROM_EMAIL", "noreply@mingai.io")
        message = Mail(
            from_email=from_email,
            to_emails=recipient_email,
            subject=subject,
            plain_text_content=body,
        )
        # sg.send is synchronous — run in executor to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, sg.send, message)
        logger.info(
            "outreach_email_sent",
            recipient_email=recipient_email,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "outreach_email_failed",
            recipient_email=recipient_email,
            error=str(exc),
        )


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
    """Create a new LLM profile for a tenant.

    Enforces name uniqueness per tenant — raises ValueError on duplicate.
    """
    existing = await db.execute(
        text(
            "SELECT id FROM llm_profiles "
            "WHERE tenant_id = :tenant_id AND name = :name"
        ),
        {"tenant_id": tenant_id, "name": name},
    )
    if existing.fetchone() is not None:
        raise ValueError(
            f"LLM profile with name '{name}' already exists for this tenant"
        )

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
    # Re-fetch to return consistent shape with get_llm_profile_db (includes timestamps)
    return await get_llm_profile_db(profile_id, db)


async def get_llm_profile_db(profile_id: str, db) -> Optional[dict]:
    """Get a single LLM profile by ID."""
    result = await db.execute(
        text(
            "SELECT id, tenant_id, name, provider, primary_model, intent_model, "
            "embedding_model, endpoint_url, is_default, created_at, updated_at, "
            "COALESCE(status, 'active') AS status "
            "FROM llm_profiles WHERE id = :id"
        ),
        {"id": profile_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "tenant_id": str(row[1]),
        "name": row[2],
        "provider": row[3],
        "primary_model": row[4],
        "intent_model": row[5],
        "embedding_model": row[6],
        "endpoint_url": row[7],
        "is_default": row[8],
        "created_at": str(row[9]),
        "updated_at": str(row[10]),
        "status": row[11],
    }


_LLM_PROFILE_UPDATE_ALLOWLIST = {
    "name",
    "provider",
    "primary_model",
    "intent_model",
    "embedding_model",
    "endpoint_url",
    "api_key_ref",
    "is_default",
}


async def update_llm_profile_db(profile_id: str, updates: dict, db) -> Optional[dict]:
    """Update LLM profile fields. Returns updated profile or None if not found.

    Column names are sourced only from the allowlist — never from dict keys directly —
    to structurally prevent SQL injection even if validation is bypassed upstream.
    """
    safe_updates = {
        k: v for k, v in updates.items() if k in _LLM_PROFILE_UPDATE_ALLOWLIST
    }
    invalid = set(updates) - _LLM_PROFILE_UPDATE_ALLOWLIST
    if invalid:
        raise ValueError(f"Invalid LLM profile update fields: {invalid}")
    if not safe_updates:
        raise ValueError("No valid fields to update")
    # Column names sourced exclusively from _LLM_PROFILE_UPDATE_ALLOWLIST (static set).
    # Values remain parameterized (`:col`). No user-controlled strings reach SQL.
    set_clauses = ", ".join(f"{col} = :{col}" for col in safe_updates)
    set_clauses += ", updated_at = NOW()"
    params = {"id": profile_id, **safe_updates}
    result = await db.execute(
        text(f"UPDATE llm_profiles SET {set_clauses} WHERE id = :id"),
        params,
    )
    await db.commit()
    if (result.rowcount or 0) == 0:
        return None
    logger.info("llm_profile_updated", profile_id=profile_id, fields=list(updates))
    return await get_llm_profile_db(profile_id, db)


async def delete_llm_profile_db(profile_id: str, db) -> dict:
    """
    Delete an LLM profile.

    Returns {"deleted": True} on success.
    Raises ValueError if the profile is currently assigned to any tenant
    (tenants.llm_profile_id = profile_id) — callers convert this to 409.
    Raises LookupError if the profile_id does not exist.
    """
    # Check for active tenant assignments
    in_use_result = await db.execute(
        text("SELECT COUNT(*) FROM tenants WHERE llm_profile_id = :id"),
        {"id": profile_id},
    )
    in_use_count = in_use_result.scalar() or 0
    if in_use_count > 0:
        raise ValueError(
            f"LLM profile '{profile_id}' is assigned to {in_use_count} tenant(s). "
            "Unassign it before deleting."
        )

    result = await db.execute(
        text("DELETE FROM llm_profiles WHERE id = :id"),
        {"id": profile_id},
    )
    await db.commit()
    if (result.rowcount or 0) == 0:
        raise LookupError(f"LLM profile '{profile_id}' not found")

    logger.info("llm_profile_deleted", profile_id=profile_id)
    return {"deleted": True, "id": profile_id}


async def deprecate_llm_profile_db(profile_id: str, db) -> Optional[dict]:
    """
    API-035: Soft-delete an LLM profile by setting status to 'deprecated'.

    Returns {"id": profile_id, "status": "deprecated"} on success.
    Raises LookupError if the profile does not exist.
    Raises ValueError if the profile is already deprecated.
    """
    profile = await get_llm_profile_db(profile_id, db)
    if profile is None:
        raise LookupError(f"LLM profile '{profile_id}' not found")

    if profile.get("status") == "deprecated":
        raise ValueError(f"LLM profile '{profile_id}' is already deprecated.")

    result = await db.execute(
        text(
            "UPDATE llm_profiles SET status = 'deprecated', updated_at = NOW() "
            "WHERE id = :id"
        ),
        {"id": profile_id},
    )
    await db.commit()
    if (result.rowcount or 0) == 0:
        raise LookupError(f"LLM profile '{profile_id}' not found")

    logger.info("llm_profile_deprecated", profile_id=profile_id)
    return {"id": profile_id, "status": "deprecated"}


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

    today = datetime.date.today()
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
# Quota DB helpers (API-030, API-031)
# ---------------------------------------------------------------------------

QUOTA_CONFIG_TYPE = "quota"
QUOTA_DEFAULTS = {
    "monthly_token_limit": 1000000,
    "storage_gb": 10.0,
    "users_max": 50,
}


async def get_tenant_quota_db(tenant_id: str, db) -> Optional[dict]:
    """
    Read quota data for a tenant.

    Reads limits from tenant_configs (config_type='quota') and counts active
    users from the users table. Returns None if the tenant does not exist.
    """
    # Check tenant exists
    tenant = await get_tenant_db(tenant_id, db)
    if tenant is None:
        return None

    # Read quota config from tenant_configs
    result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tenant_id AND config_type = :config_type"
        ),
        {"tenant_id": tenant_id, "config_type": QUOTA_CONFIG_TYPE},
    )
    row = result.fetchone()
    if row is not None and row[0] is not None:
        config_data = row[0] if isinstance(row[0], dict) else {}
    else:
        config_data = {}

    monthly_token_limit = config_data.get(
        "monthly_token_limit", QUOTA_DEFAULTS["monthly_token_limit"]
    )
    storage_gb_limit = config_data.get("storage_gb", QUOTA_DEFAULTS["storage_gb"])
    users_max = config_data.get("users_max", QUOTA_DEFAULTS["users_max"])

    # Count current users for this tenant
    user_count_result = await db.execute(
        text("SELECT COUNT(*) FROM users WHERE tenant_id = :tenant_id"),
        {"tenant_id": tenant_id},
    )
    user_count = user_count_result.scalar() or 0

    # Sum tokens used in the current calendar month from messages table
    tokens_used_result = await db.execute(
        text(
            "SELECT COALESCE(SUM(tokens_used), 0) FROM messages "
            "WHERE tenant_id = :tenant_id "
            "AND created_at >= DATE_TRUNC('month', NOW())"
        ),
        {"tenant_id": tenant_id},
    )
    tokens_used = int(tokens_used_result.scalar() or 0)

    return {
        "tenant_id": tenant_id,
        "tokens": {
            "limit": monthly_token_limit,
            "used": tokens_used,
            "period": "monthly",
        },
        "storage_gb": {
            "limit": float(storage_gb_limit),
        },
        "users": {"limit": users_max, "used": user_count},
    }


_QUOTA_UPDATE_ALLOWLIST = {"monthly_token_limit", "storage_gb", "users_max"}


async def update_tenant_quota_db(tenant_id: str, updates: dict, db) -> Optional[bool]:
    """
    Upsert quota settings for a tenant into tenant_configs.

    Returns True on success, None if the tenant does not exist.
    Raises ValueError if invalid fields are provided.

    Uses the UPSERT pattern (INSERT ... ON CONFLICT DO UPDATE) to ensure
    the quota config row exists after the operation.
    """
    safe_updates = {k: v for k, v in updates.items() if k in _QUOTA_UPDATE_ALLOWLIST}
    invalid = set(updates) - _QUOTA_UPDATE_ALLOWLIST
    if invalid:
        raise ValueError(f"Invalid quota update fields: {invalid}")
    if not safe_updates:
        raise ValueError("No valid quota fields to update")

    # Check tenant exists
    tenant = await get_tenant_db(tenant_id, db)
    if tenant is None:
        return None

    # Read existing config_data to merge with updates
    result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tenant_id AND config_type = :config_type"
        ),
        {"tenant_id": tenant_id, "config_type": QUOTA_CONFIG_TYPE},
    )
    row = result.fetchone()
    existing_data = {}
    if row is not None and row[0] is not None:
        existing_data = row[0] if isinstance(row[0], dict) else {}

    # Merge updates into existing config
    merged = {**existing_data, **safe_updates}

    import json

    config_json = json.dumps(merged)

    await db.execute(
        text(
            "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
            "VALUES (gen_random_uuid(), :tenant_id, :config_type, CAST(:config_data AS jsonb)) "
            "ON CONFLICT (tenant_id, config_type) "
            "DO UPDATE SET config_data = CAST(:config_data AS jsonb), updated_at = NOW()"
        ),
        {
            "tenant_id": tenant_id,
            "config_type": QUOTA_CONFIG_TYPE,
            "config_data": config_json,
        },
    )
    await db.commit()
    logger.info("tenant_quota_updated", tenant_id=tenant_id, fields=list(safe_updates))
    return True


# ---------------------------------------------------------------------------
# Provisioning SSE helper (API-025)
# ---------------------------------------------------------------------------


async def get_provisioning_events(job_id: str) -> Optional[list]:
    """
    Read provisioning job events from Redis.

    Key: mingai:provisioning:{job_id}
    Value: JSON-encoded list of step dicts.

    Returns the list of events, or None if the job_id is not found.
    """
    import json as json_mod

    from app.core.redis_client import get_redis

    redis = get_redis()
    redis_key = f"mingai:provisioning:{job_id}"
    raw = await redis.get(redis_key)
    if raw is None:
        logger.warning("provisioning_job_not_found", job_id=job_id)
        return None

    try:
        events = json_mod.loads(raw)
        if not isinstance(events, list):
            logger.error(
                "provisioning_events_invalid_format",
                job_id=job_id,
                type=type(events).__name__,
            )
            raise ValueError(f"Provisioning events for job '{job_id}' are not a list")
        return events
    except json_mod.JSONDecodeError as exc:
        logger.error(
            "provisioning_events_decode_error",
            job_id=job_id,
            error=str(exc),
        )
        raise ValueError(
            f"Failed to decode provisioning events for job '{job_id}': {exc}"
        ) from exc


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
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-024: Provision a new tenant.

    Creates the tenant record synchronously and enqueues the full 8-step
    provisioning workflow as a FastAPI background task. Returns immediately
    with status='active' and a job_id the client can use with
    GET /platform/provisioning/{job_id} (SSE) to track progress.
    """
    result = await create_tenant_db(
        name=request.name,
        plan=request.plan,
        primary_contact_email=request.primary_contact_email,
        slug=request.slug,
        db=session,
    )

    job_id = str(uuid.uuid4())
    background_tasks.add_task(
        run_tenant_provisioning,
        job_id=job_id,
        tenant_id=result["id"],
        name=result["name"],
        plan=result["plan"],
        primary_contact_email=result["primary_contact_email"],
        slug=result["slug"],
    )

    logger.info(
        "tenant_provisioning_started",
        tenant_id=result["id"],
        job_id=job_id,
    )
    return {**result, "job_id": job_id}


_UUID_PATH = Path(..., max_length=64, pattern=r"^[a-zA-Z0-9_-]{1,64}$")


# PA-008: literal-path route must be BEFORE /tenants/{tenant_id} in the same
# router so FastAPI resolves it before the parameterised path.
@router.get("/tenants/at-risk")
async def list_at_risk_tenants(
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    PA-008: Return tenants flagged at-risk from the latest health score snapshot.

    Fetches the most recent tenant_health_scores row per tenant where
    composite_score < 40, sorted by composite_score ASC (worst first).
    Returns empty list — never 404 — when no tenants are at risk.
    """
    result = await session.execute(
        text(
            """
            WITH latest AS (
                SELECT DISTINCT ON (ths.tenant_id)
                    ths.tenant_id,
                    ths.date,
                    ths.composite_score,
                    ths.at_risk_flag,
                    ths.at_risk_reason,
                    ths.usage_trend_score,
                    ths.feature_breadth_score,
                    ths.satisfaction_score,
                    ths.error_rate_score
                FROM tenant_health_scores ths
                ORDER BY ths.tenant_id, ths.date DESC
            )
            SELECT
                l.tenant_id,
                t.name,
                l.composite_score,
                l.at_risk_reason,
                l.usage_trend_score,
                l.feature_breadth_score,
                l.satisfaction_score,
                l.error_rate_score
            FROM latest l
            JOIN tenants t ON t.id = l.tenant_id
            WHERE l.at_risk_flag = TRUE
            ORDER BY l.composite_score ASC NULLS LAST
            """
        ),
    )
    rows = result.fetchall()

    if not rows:
        return []

    items = []
    for row in rows:
        tid = str(row[0])
        name = row[1]
        composite_score = float(row[2]) if row[2] is not None else None
        at_risk_reason = row[3]
        usage_trend = float(row[4]) if row[4] is not None else None
        feature_breadth = float(row[5]) if row[5] is not None else None
        satisfaction = float(row[6]) if row[6] is not None else None
        error_rate = float(row[7]) if row[7] is not None else None

        # Count consecutive ISO-weeks at risk (1 row per week via DISTINCT ON)
        # so daily snapshot jobs don't inflate the count.
        weeks_result = await session.execute(
            text(
                """
                SELECT at_risk_flag
                FROM (
                    SELECT DISTINCT ON (DATE_TRUNC('week', date))
                        DATE_TRUNC('week', date) AS week_start,
                        at_risk_flag
                    FROM tenant_health_scores
                    WHERE tenant_id = :tid
                    ORDER BY DATE_TRUNC('week', date) DESC, date DESC
                ) AS weekly
                ORDER BY week_start DESC
                LIMIT 52
                """
            ),
            {"tid": tid},
        )
        week_rows = weeks_result.fetchall()
        weeks_at_risk = 0
        for wr in week_rows:
            if wr[0]:
                weeks_at_risk += 1
            else:
                break

        items.append(
            {
                "tenant_id": tid,
                "name": name,
                "composite_score": composite_score,
                "at_risk_reason": at_risk_reason,
                "weeks_at_risk": weeks_at_risk,
                "component_breakdown": {
                    "usage_trend_score": usage_trend,
                    "feature_breadth_score": feature_breadth,
                    "satisfaction_score": satisfaction,
                    "error_rate_score": error_rate,
                },
            }
        )

    logger.info(
        "at_risk_tenants_listed",
        user_id=current_user.id,
        count=len(items),
    )
    return items


@router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str = _UUID_PATH,
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
    request: UpdateTenantRequest,
    tenant_id: str = _UUID_PATH,
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
    tenant_id: str = _UUID_PATH,
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
    tenant_id: str = _UUID_PATH,
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


@router.get("/provisioning/{job_id}")
async def get_provisioning_status(
    job_id: str = Path(..., max_length=64, pattern=r"^[a-zA-Z0-9_-]{1,64}$"),
    current_user: CurrentUser = Depends(require_platform_admin),
):
    """API-025: SSE stream for tenant provisioning job progress."""
    import json as json_mod

    events = await get_provisioning_events(job_id)
    if events is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provisioning job '{job_id}' not found",
        )

    async def event_stream():
        for event in events:
            yield f"data: {json_mod.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/tenants/{tenant_id}/quota")
async def get_tenant_quota(
    tenant_id: str = _UUID_PATH,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-030: Get tenant quota (limits and usage)."""
    result = await get_tenant_quota_db(tenant_id=tenant_id, db=session)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found",
        )
    return result


@router.patch("/tenants/{tenant_id}/quota")
async def update_tenant_quota(
    request: UpdateQuotaRequest,
    tenant_id: str = _UUID_PATH,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-031: Update tenant quota limits."""
    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )
    result = await update_tenant_quota_db(
        tenant_id=tenant_id, updates=updates, db=session
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found",
        )
    # Return the updated quota
    quota = await get_tenant_quota_db(tenant_id=tenant_id, db=session)
    return quota


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
    """API-032: Create a new LLM profile for a tenant.

    Returns 409 Conflict if a profile with the same name already exists for the tenant.
    """
    _uuid_re = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    # Resolve tenant_id: use provided value or fall back to platform default tenant
    tenant_id = request.tenant_id
    if not tenant_id:
        # Platform Admin creating a global profile — attach to the default tenant
        result = await session.execute(
            text("SELECT id FROM tenants ORDER BY created_at LIMIT 1")
        )
        row = result.fetchone()
        tenant_id = str(row[0]) if row else None
    if not tenant_id or not _uuid_re.match(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"tenant_id '{tenant_id}' is not a valid UUID. "
            "Provide the UUID of an existing tenant.",
        )

    try:
        result = await create_llm_profile_db(
            tenant_id=tenant_id,
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
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except IntegrityError:
        # DB-level UNIQUE constraint violation (concurrent creates race)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"An LLM profile with name '{request.name}' already exists "
                "for this tenant."
            ),
        )
    return result


@router.get("/llm-profiles/{profile_id}")
async def get_llm_profile(
    profile_id: str = _UUID_PATH,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-033: Get a single LLM profile by ID."""
    result = await get_llm_profile_db(profile_id=profile_id, db=session)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM profile '{profile_id}' not found",
        )
    return result


@router.patch("/llm-profiles/{profile_id}")
async def update_llm_profile(
    request: UpdateLLMProfileRequest,
    profile_id: str = _UUID_PATH,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-034: Update an LLM profile."""
    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )
    result = await update_llm_profile_db(
        profile_id=profile_id, updates=updates, db=session
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM profile '{profile_id}' not found",
        )
    return result


@router.delete("/llm-profiles/{profile_id}")
async def delete_llm_profile(
    profile_id: str = _UUID_PATH,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-035: Soft-delete (deprecate) an LLM profile.

    Sets status to 'deprecated'. Cannot delete an already-deprecated profile.
    Returns {"id": "uuid", "status": "deprecated"} on success.
    """
    try:
        result = await deprecate_llm_profile_db(profile_id=profile_id, db=session)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM profile '{profile_id}' not found",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return result


@router.get("/stats")
async def get_platform_stats(
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-036: Get platform-wide statistics."""
    result = await get_platform_stats_db(db=session)
    return result


async def get_tenant_health_components_db(tenant_id: str, db) -> dict:
    """
    Query all raw health score component data for a tenant from the DB.

    Returns values in the units that calculate_health_score() expects:
      usage_trend_pct  — growth rate fraction (0.0 = flat, -0.25 = 25% decline)
      feature_breadth  — 0.0-1.0 fraction of 5 core features active
      satisfaction_pct — 0-100 positive-feedback percentage
      error_rate_pct   — 0-100 error occurrence percentage (0 = no errors)
    Plus raw DB counts for the response detail fields.
    """
    # --- Usage trend: query volume this 30 days vs prior 30 days ---
    usage_result = await db.execute(
        text(
            "SELECT "
            "  COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days') AS recent, "
            "  COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '60 days' "
            "    AND created_at < NOW() - INTERVAL '30 days') AS prior "
            "FROM messages "
            "WHERE tenant_id = :tenant_id"
        ),
        {"tenant_id": tenant_id},
    )
    usage_row = usage_result.fetchone()
    recent_queries = usage_row[0] or 0
    prior_queries = usage_row[1] or 0
    # Growth rate: (recent / prior) - 1; -1.0 when no activity at all
    if prior_queries > 0:
        usage_trend_pct = (recent_queries / prior_queries) - 1.0
    elif recent_queries > 0:
        usage_trend_pct = 0.0  # new usage, treat as flat
    else:
        usage_trend_pct = -1.0  # no activity = maximum decline signal

    # --- Feature breadth: fraction of 5 core features active in past 30 days ---
    # Features: conversations, feedback, teams, glossary terms, memory notes
    breadth_result = await db.execute(
        text(
            "SELECT "
            "  (SELECT COUNT(*) > 0 FROM conversations WHERE tenant_id = :t AND created_at >= NOW() - INTERVAL '30 days')::int, "
            "  (SELECT COUNT(*) > 0 FROM user_feedback WHERE tenant_id = :t AND created_at >= NOW() - INTERVAL '30 days')::int, "
            "  (SELECT COUNT(*) > 0 FROM tenant_teams WHERE tenant_id = :t)::int, "
            "  (SELECT COUNT(*) > 0 FROM glossary_terms WHERE tenant_id = :t)::int, "
            "  (SELECT COUNT(*) > 0 FROM memory_notes WHERE tenant_id = :t AND created_at >= NOW() - INTERVAL '30 days')::int"
        ),
        {"t": tenant_id},
    )
    breadth_row = breadth_result.fetchone()
    # Guard against None elements (e.g. asyncpg returning None for a cast)
    features_active = sum(int(x or 0) for x in breadth_row) if breadth_row else 0
    feature_breadth = features_active / 5.0

    # --- Satisfaction: positive feedback percentage (0-100) in past 30 days ---
    # rating column is INTEGER: 1 = positive (thumbs up), -1 = negative (thumbs down)
    satisfaction_result = await db.execute(
        text(
            "SELECT "
            "  COUNT(*) FILTER (WHERE rating = 1) AS positive, "
            "  COUNT(*) AS total "
            "FROM user_feedback "
            "WHERE tenant_id = :tenant_id AND created_at >= NOW() - INTERVAL '30 days'"
        ),
        {"tenant_id": tenant_id},
    )
    sat_row = satisfaction_result.fetchone()
    positive = sat_row[0] or 0
    total_feedback = sat_row[1] or 0
    # Percentage 0-100; default to 70 (neutral) when no feedback
    satisfaction_pct = (
        (positive / total_feedback * 100.0) if total_feedback > 0 else 70.0
    )

    # --- Error rate percentage (0-100): 0 issues → 0%, 10+ issues → 100% ---
    error_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM issue_reports "
            "WHERE tenant_id = :tenant_id AND status = 'open' "
            "AND created_at >= NOW() - INTERVAL '30 days'"
        ),
        {"tenant_id": tenant_id},
    )
    open_issues = error_result.scalar() or 0
    error_rate_pct = min(100.0, open_issues * 10.0)

    return {
        "usage_trend_pct": usage_trend_pct,
        "feature_breadth": feature_breadth,
        "satisfaction_pct": satisfaction_pct,
        "error_rate_pct": error_rate_pct,
        "recent_queries": recent_queries,
        "prior_queries": prior_queries,
        "features_active": features_active,
        "positive_feedback": positive,
        "total_feedback": total_feedback,
        "open_issues": open_issues,
    }


@router.get("/tenants/{tenant_id}/health")
async def get_tenant_health_score(
    tenant_id: str = _UUID_PATH,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    PA-009 / API-029: Health score drilldown for a single tenant.

    Returns the most recent stored snapshot from tenant_health_scores plus
    12 weekly trend data points (ISO week format 'YYYY-Www').
    Missing weeks return null values — they are never omitted.
    """
    # Verify tenant exists
    tenant = await get_tenant_db(tenant_id=tenant_id, db=session)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found",
        )

    # Fetch latest health score row for current snapshot
    latest_result = await session.execute(
        text(
            """
            SELECT composite_score, usage_trend_score, feature_breadth_score,
                   satisfaction_score, error_rate_score, at_risk_flag
            FROM tenant_health_scores
            WHERE tenant_id = :tid
            ORDER BY date DESC
            LIMIT 1
            """
        ),
        {"tid": tenant_id},
    )
    latest_row = latest_result.fetchone()

    if latest_row:
        current = {
            "composite": float(latest_row[0]) if latest_row[0] is not None else None,
            "usage_trend": float(latest_row[1]) if latest_row[1] is not None else None,
            "feature_breadth": float(latest_row[2])
            if latest_row[2] is not None
            else None,
            "satisfaction": float(latest_row[3]) if latest_row[3] is not None else None,
            "error_rate": float(latest_row[4]) if latest_row[4] is not None else None,
            "at_risk_flag": bool(latest_row[5]) if latest_row[5] is not None else False,
        }
    else:
        current = {
            "composite": None,
            "usage_trend": None,
            "feature_breadth": None,
            "satisfaction": None,
            "error_rate": None,
            "at_risk_flag": False,
        }

    # Fetch up to 12 stored rows ordered newest first for trend
    trend_result = await session.execute(
        text(
            """
            SELECT date, composite_score, usage_trend_score, satisfaction_score
            FROM tenant_health_scores
            WHERE tenant_id = :tid
            ORDER BY date DESC
            LIMIT 12
            """
        ),
        {"tid": tenant_id},
    )
    trend_rows = trend_result.fetchall()

    # Map date → row for ISO-week alignment
    row_by_date: dict = {}
    for tr in trend_rows:
        row_by_date[tr[0]] = tr

    # Generate 12 ISO weeks going backwards from the current week
    today = datetime.date.today()
    current_monday = today - datetime.timedelta(days=today.weekday())

    trend = []
    for i in range(12):
        week_monday = current_monday - datetime.timedelta(weeks=i)
        iso_cal = week_monday.isocalendar()
        week_label = f"{iso_cal[0]}-W{iso_cal[1]:02d}"

        matched_row = None
        for d, r in row_by_date.items():
            d_iso = d.isocalendar()
            if d_iso[0] == iso_cal[0] and d_iso[1] == iso_cal[1]:
                matched_row = r
                break

        if matched_row:
            trend.append(
                {
                    "week": week_label,
                    "composite": float(matched_row[1])
                    if matched_row[1] is not None
                    else None,
                    "usage_trend": float(matched_row[2])
                    if matched_row[2] is not None
                    else None,
                    "satisfaction": float(matched_row[3])
                    if matched_row[3] is not None
                    else None,
                }
            )
        else:
            trend.append(
                {
                    "week": week_label,
                    "composite": None,
                    "usage_trend": None,
                    "satisfaction": None,
                }
            )

    logger.info(
        "tenant_health_drilldown",
        user_id=current_user.id,
        tenant_id=tenant_id,
    )

    return {
        "current": current,
        "trend": trend,
    }


@router.post("/tenants/{tenant_id}/message", status_code=status.HTTP_200_OK)
async def proactive_outreach(
    request: ProactiveOutreachRequest,
    tenant_id: str = _UUID_PATH,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    PA-011: Platform admin sends an in-app notification (and optionally email)
    to all active tenant_admin users of the specified tenant.

    Channels:
    - in_app: Inserts a persistent row in the notifications table with
              type='platform_outreach' and from_platform_admin=TRUE.
    - email:  Sends via SendGrid if SENDGRID_API_KEY is configured; silently
              skips (warns) if the env var is absent or SendGrid fails.

    Writes an audit_log entry recording the actor, target tenant, recipient
    count, and channels used.

    Returns 404 if the tenant does not exist.
    Returns 422 if subject/body are blank or send_via is empty.
    """
    # 1. Verify tenant exists
    tenant = await get_tenant_db(tenant_id=tenant_id, db=session)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found",
        )

    # 2. Fetch all active tenant_admin recipients for this tenant
    recipients = await get_tenant_admins_db(tenant_id=tenant_id, db=session)
    send_via = list(set(request.send_via))  # deduplicate

    # 3a. In-app: insert notification rows
    if "in_app" in send_via and recipients:
        await insert_platform_outreach_notifications_db(
            tenant_id=tenant_id,
            recipients=recipients,
            subject=request.subject,
            body=request.body,
            db=session,
        )

    # 4. Write audit log (resource_id is the target tenant)
    await write_audit_log_db(
        tenant_id=tenant_id,
        actor_user_id=current_user.id,
        action="proactive_outreach",
        resource_type="tenant",
        resource_id=tenant_id,
        details={
            "recipient_count": len(recipients),
            "send_via": send_via,
            "subject": request.subject,
        },
        db=session,
    )

    await session.commit()

    # 3b. Email: fire after commit so DB rows are durable even if email fails.
    # Runs synchronously but each call is non-blocking internally (logs on failure).
    if "email" in send_via:
        for recipient in recipients:
            await send_outreach_email(
                recipient_email=recipient["email"],
                subject=request.subject,
                body=request.body,
            )

    logger.info(
        "platform_outreach_sent",
        actor_user_id=current_user.id,
        tenant_id=tenant_id,
        recipient_count=len(recipients),
        send_via=send_via,
    )

    return {
        "tenant_id": tenant_id,
        "recipients": len(recipients),
        "send_via": send_via,
        "message": "Outreach sent",
    }
