"""
Platform Admin API endpoints.

Provides dashboard stats and platform-level management endpoints.
All endpoints require platform admin scope (scope='platform').

Endpoints:
- GET  /admin/dashboard                    — Platform dashboard stats
- POST /platform/agent-templates           — Publish agent template (API-038)
- PATCH /platform/agent-templates/{id}     — Update/version template (API-040)
- GET  /platform/tool-catalog              — List tool catalog (API-041)
- POST /platform/tool-catalog              — Register new tool (API-042)
- GET  /platform/audit-log                 — Cross-tenant audit log (API-112)
- GET  /platform/analytics/cost            — Cross-tenant cost analytics (API-036)
- GET  /platform/analytics/health          — Tenant health scores dashboard (API-037)
"""
import csv
import io
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_platform_admin
from app.core.session import get_async_session
from app.modules.platform.health_score import calculate_health_score

logger = structlog.get_logger()

router = APIRouter(tags=["platform"])

# ---------------------------------------------------------------------------
# Constants / allowlists
# ---------------------------------------------------------------------------

_VALID_PLAN_TIERS = {"starter", "professional", "enterprise"}
_VALID_TEMPLATE_STATUSES = {"draft", "published", "deprecated"}
_VALID_AUTH_TYPES = {"api_key", "oauth2", "none"}
_VALID_SAFETY_CLASSES = {"read_only", "write", "destructive"}
_VALID_TOOL_STATUSES = {"healthy", "degraded", "unavailable", "pending_health_check"}

# Analytics periods (days per label)
_ANALYTICS_PERIODS = {"7d": 7, "30d": 30, "90d": 90}
_VALID_HEALTH_SORT = {"score", "name"}

# Revenue per month by plan (USD) — used for cost analytics
_PLAN_REVENUE_MONTHLY: dict[str, float] = {
    "starter": 0.0,
    "professional": 299.0,
    "enterprise": 999.0,
}

# Variable names reserved by the platform — cannot be used in template variables
_RESERVED_VARIABLE_NAMES = {"company_name", "user_name", "date"}


def _get_platform_tenant_id() -> str:
    """Return PLATFORM_TENANT_ID env var, defaulting to 'platform'."""
    return os.environ.get("PLATFORM_TENANT_ID", "platform")


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class DashboardStatsResponse(BaseModel):
    """Platform dashboard statistics returned to the frontend."""

    active_users: int
    documents_indexed: int
    queries_today: int
    satisfaction_pct: float


class TemplateVariable(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., min_length=1, max_length=50)
    description: str = Field(default="", max_length=500)
    required: bool = False
    example: str = Field(default="", max_length=500)


class TemplateGuardrails(BaseModel):
    blocked_topics: List[str] = Field(default_factory=list)
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    max_response_length: int = Field(default=2000, ge=100, le=10000)


class PublishAgentTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    system_prompt: str = Field(..., min_length=1)
    variables: List[TemplateVariable] = Field(default_factory=list)
    guardrails: TemplateGuardrails = Field(default_factory=TemplateGuardrails)
    plan_tiers: List[str] = Field(..., min_length=1)


class UpdateAgentTemplateRequest(BaseModel):
    system_prompt: Optional[str] = None
    variables: Optional[List[TemplateVariable]] = None
    guardrails: Optional[TemplateGuardrails] = None
    status: Optional[str] = Field(None, pattern="^(draft|published|deprecated)$")
    changelog: Optional[str] = Field(None, max_length=2000)


class RegisterToolRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    provider: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=1000)
    endpoint_url: str = Field(..., min_length=8)
    auth_type: str = Field(...)
    capabilities: List[str] = Field(default_factory=list)
    safety_class: str = Field(...)
    plan_tiers: List[str] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# DB helpers (mockable in unit tests)
# ---------------------------------------------------------------------------


async def publish_agent_template_db(
    name: str,
    category: str,
    description: str,
    system_prompt: str,
    variables: list,
    guardrails: dict,
    plan_tiers: list,
    platform_tenant_id: str,
    db: AsyncSession,
) -> dict:
    """Insert a new agent template into agent_cards under the platform tenant."""
    template_id = str(uuid.uuid4())
    capabilities = {
        "variables": variables,
        "guardrails": guardrails,
        "plan_tiers": plan_tiers,
    }
    capabilities_json = json.dumps(capabilities)

    await db.execute(
        text(
            "INSERT INTO agent_cards "
            "(id, tenant_id, name, category, description, system_prompt, "
            "capabilities, status, version, source) "
            "VALUES (:id, :tenant_id, :name, :category, :description, :system_prompt, "
            "CAST(:capabilities AS jsonb), 'draft', 1, 'platform')"
        ),
        {
            "id": template_id,
            "tenant_id": platform_tenant_id,
            "name": name,
            "category": category,
            "description": description,
            "system_prompt": system_prompt,
            "capabilities": capabilities_json,
        },
    )
    await db.commit()

    logger.info(
        "agent_template_published",
        template_id=template_id,
        name=name,
        category=category,
    )
    return {"id": template_id, "name": name, "version": 1, "status": "draft"}


async def get_platform_template_db(
    template_id: str, platform_tenant_id: str, db: AsyncSession
) -> Optional[dict]:
    """Fetch a platform template by ID."""
    result = await db.execute(
        text(
            "SELECT id, name, description, system_prompt, capabilities, status, "
            "version, updated_at "
            "FROM agent_cards "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": template_id, "tenant_id": platform_tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    capabilities = row["capabilities"]
    if isinstance(capabilities, str):
        capabilities = json.loads(capabilities)
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "system_prompt": row["system_prompt"],
        "capabilities": capabilities or {},
        "status": row["status"],
        "version": row["version"],
        "updated_at": row["updated_at"],
    }


async def update_platform_template_db(
    template_id: str,
    current: dict,
    system_prompt: Optional[str],
    variables: Optional[list],
    guardrails: Optional[dict],
    new_status: Optional[str],
    changelog: Optional[str],
    platform_tenant_id: str,
    db: AsyncSession,
) -> dict:
    """Apply a partial update to a platform agent template."""
    capabilities = current.get("capabilities") or {}
    if isinstance(capabilities, str):
        capabilities = json.loads(capabilities)

    # Determine new version: bump if system_prompt changes on a published template
    current_version = current["version"]
    current_status = current["status"]
    new_version = current_version

    effective_prompt = (
        system_prompt if system_prompt is not None else current["system_prompt"]
    )

    if system_prompt is not None and current_status == "published":
        new_version = current_version + 1

    # Update capabilities JSONB fields as requested
    if variables is not None:
        capabilities["variables"] = variables
    if guardrails is not None:
        capabilities["guardrails"] = guardrails
    if changelog is not None:
        capabilities["changelog"] = changelog

    effective_status = new_status if new_status is not None else current_status

    capabilities_json = json.dumps(capabilities)

    await db.execute(
        text(
            "UPDATE agent_cards "
            "SET system_prompt = :system_prompt, "
            "    capabilities = CAST(:capabilities AS jsonb), "
            "    status = :status, "
            "    version = :version, "
            "    updated_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {
            "system_prompt": effective_prompt,
            "capabilities": capabilities_json,
            "status": effective_status,
            "version": new_version,
            "id": template_id,
            "tenant_id": platform_tenant_id,
        },
    )
    await db.commit()

    updated = await get_platform_template_db(template_id, platform_tenant_id, db)
    logger.info(
        "agent_template_updated",
        template_id=template_id,
        new_status=effective_status,
        new_version=new_version,
    )
    return updated


async def list_tools_db(
    page: int,
    page_size: int,
    safety_class: Optional[str],
    tool_status: Optional[str],
    db: AsyncSession,
) -> dict:
    """List all mcp_servers (platform-wide tool catalog)."""
    offset = (page - 1) * page_size

    # Build WHERE clause from hardcoded fragments — no f-strings with user data
    where_parts = []
    params: dict = {"limit": page_size, "offset": offset}

    if safety_class is not None:
        where_parts.append("safety_class = :safety_class")
        params["safety_class"] = safety_class

    if tool_status is not None:
        where_parts.append("status = :tool_status")
        params["tool_status"] = tool_status

    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    count_result = await db.execute(
        text(
            f"SELECT COUNT(*) FROM mcp_servers {where_clause}"
        ),  # noqa: S608 — hardcoded fragments only
        params,
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        text(
            f"SELECT id, name, description, auth_type, capabilities, "  # noqa: S608
            f"safety_class, status, health_check_last, plan_tiers, created_at "
            f"FROM mcp_servers {where_clause} "
            f"ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        ),
        params,
    )

    items = []
    for row in rows_result.mappings():
        capabilities = row["capabilities"]
        if isinstance(capabilities, str):
            capabilities = json.loads(capabilities)

        plan_tiers = row["plan_tiers"]
        if isinstance(plan_tiers, str):
            plan_tiers = json.loads(plan_tiers)

        # Extract provider from capabilities or auth_type field
        provider = ""
        if isinstance(capabilities, dict):
            provider = capabilities.get("provider", "")

        health_ts = row["health_check_last"]
        items.append(
            {
                "id": str(row["id"]),
                "name": row["name"],
                "provider": provider,
                "description": row["description"] or "",
                "safety_class": row["safety_class"],
                "status": row["status"],
                "health_check_last": health_ts.isoformat() if health_ts else None,
                "plan_tiers": plan_tiers or [],
            }
        )

    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def register_tool_db(
    name: str,
    provider: str,
    description: str,
    endpoint_url: str,
    auth_type: str,
    capabilities: list,
    safety_class: str,
    plan_tiers: list,
    db: AsyncSession,
) -> dict:
    """Insert a new mcp_servers row."""
    tool_id = str(uuid.uuid4())
    capabilities_json = json.dumps({"provider": provider, "tools": capabilities})
    plan_tiers_json = json.dumps(plan_tiers)
    now = datetime.now(timezone.utc)

    await db.execute(
        text(
            "INSERT INTO mcp_servers "
            "(id, name, description, endpoint_url, auth_type, capabilities, "
            "safety_class, status, plan_tiers, created_at) "
            "VALUES (:id, :name, :description, :endpoint_url, :auth_type, "
            "CAST(:capabilities AS jsonb), :safety_class, 'pending_health_check', "
            "CAST(:plan_tiers AS jsonb), :created_at)"
        ),
        {
            "id": tool_id,
            "name": name,
            "description": description,
            "endpoint_url": endpoint_url,
            "auth_type": auth_type,
            "capabilities": capabilities_json,
            "safety_class": safety_class,
            "plan_tiers": plan_tiers_json,
            "created_at": now,
        },
    )

    # Immediately mark as healthy (no external health check infra yet)
    await db.execute(
        text(
            "UPDATE mcp_servers SET status = 'healthy', health_check_last = NOW() "
            "WHERE id = :id"
        ),
        {"id": tool_id},
    )
    await db.commit()

    logger.info(
        "tool_registered",
        tool_id=tool_id,
        name=name,
        safety_class=safety_class,
    )
    return {
        "id": tool_id,
        "name": name,
        "status": "pending_health_check",
        "created_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Route: GET /admin/dashboard
# ---------------------------------------------------------------------------


@router.get("/admin/dashboard", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> DashboardStatsResponse:
    """
    GET /api/v1/admin/dashboard

    Returns platform-level dashboard statistics.
    Requires platform admin scope -- returns 403 for non-platform users.
    """
    if current_user.scope != "platform":
        logger.warning(
            "dashboard_access_denied",
            user_id=current_user.id,
            scope=current_user.scope,
            required_scope="platform",
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "Platform admin access required. "
                f"Your scope is '{current_user.scope}' but 'platform' is needed."
            ),
        )

    logger.info(
        "dashboard_stats_requested",
        user_id=current_user.id,
        scope=current_user.scope,
    )

    active_users_result = await session.execute(
        text("SELECT COUNT(*) FROM users WHERE status = 'active'")
    )
    active_users = active_users_result.scalar_one()

    docs_result = await session.execute(
        text(
            "SELECT COALESCE(SUM(files_synced), 0) "
            "FROM sync_jobs WHERE status = 'completed'"
        )
    )
    documents_indexed = docs_result.scalar_one()

    from datetime import date

    today_start = datetime.combine(
        date.today(), datetime.min.time(), tzinfo=timezone.utc
    )
    queries_result = await session.execute(
        text(
            "SELECT COUNT(*) FROM messages "
            "WHERE role = 'user' AND created_at >= :today_start"
        ),
        {"today_start": today_start},
    )
    queries_today = queries_result.scalar_one()

    feedback_result = await session.execute(
        text(
            "SELECT "
            "  COUNT(*) AS total, "
            "  COUNT(*) FILTER (WHERE rating = 1) AS positive "
            "FROM user_feedback"
        )
    )
    feedback_row = feedback_result.one()
    total_feedback = feedback_row.total
    positive_feedback = feedback_row.positive

    if total_feedback > 0:
        satisfaction_pct = round((positive_feedback / total_feedback) * 100, 1)
    else:
        satisfaction_pct = 0.0

    logger.info(
        "dashboard_stats_returned",
        user_id=current_user.id,
        active_users=active_users,
        documents_indexed=documents_indexed,
        queries_today=queries_today,
        satisfaction_pct=satisfaction_pct,
    )

    return DashboardStatsResponse(
        active_users=active_users,
        documents_indexed=documents_indexed,
        queries_today=queries_today,
        satisfaction_pct=satisfaction_pct,
    )


# ---------------------------------------------------------------------------
# Route: POST /platform/agent-templates  (API-038)
# ---------------------------------------------------------------------------


@router.post(
    "/platform/agent-templates",
    status_code=status.HTTP_201_CREATED,
    tags=["platform"],
)
async def publish_agent_template(
    body: PublishAgentTemplateRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-038: Publish a new agent template to the platform library.

    Platform admins create templates here. Tenant admins can later deploy
    published templates for their workspace via GET /agents/templates.
    """
    # Validate plan_tiers values
    invalid_tiers = set(body.plan_tiers) - _VALID_PLAN_TIERS
    if invalid_tiers:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid plan_tiers: {sorted(invalid_tiers)}. "
            f"Allowed: {sorted(_VALID_PLAN_TIERS)}",
        )

    # Validate at least one plan_tier
    if not body.plan_tiers:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one plan_tier is required.",
        )

    # Validate variables: no reserved names
    reserved_used = {
        v.name for v in body.variables if v.name in _RESERVED_VARIABLE_NAMES
    }
    if reserved_used:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Variable names are reserved by the platform: {sorted(reserved_used)}. "
            f"Reserved names: {sorted(_RESERVED_VARIABLE_NAMES)}",
        )

    platform_tenant_id = _get_platform_tenant_id()

    variables_list = [v.model_dump() for v in body.variables]
    guardrails_dict = body.guardrails.model_dump()

    result = await publish_agent_template_db(
        name=body.name,
        category=body.category,
        description=body.description,
        system_prompt=body.system_prompt,
        variables=variables_list,
        guardrails=guardrails_dict,
        plan_tiers=body.plan_tiers,
        platform_tenant_id=platform_tenant_id,
        db=session,
    )

    logger.info(
        "platform_agent_template_created",
        template_id=result["id"],
        user_id=current_user.id,
        name=body.name,
    )
    return result


# ---------------------------------------------------------------------------
# Route: PATCH /platform/agent-templates/{template_id}  (API-040)
# ---------------------------------------------------------------------------


@router.patch(
    "/platform/agent-templates/{template_id}",
    tags=["platform"],
)
async def update_agent_template(
    template_id: str,
    body: UpdateAgentTemplateRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-040: Update or version an existing platform agent template.

    - If current status is 'published' and system_prompt changes: version is incremented.
    - Transitioning to 'published': system_prompt must exist and capabilities must
      include at least one plan_tier.
    - Transitioning to 'deprecated': allowed unconditionally.
    - changelog is stored inside the capabilities JSONB.
    """
    platform_tenant_id = _get_platform_tenant_id()

    current = await get_platform_template_db(template_id, platform_tenant_id, session)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent template '{template_id}' not found.",
        )

    # Validate transition to 'published'
    if body.status == "published":
        effective_prompt = body.system_prompt or current["system_prompt"]
        if not effective_prompt:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot publish: system_prompt is required.",
            )
        caps = current.get("capabilities") or {}
        if isinstance(caps, str):
            caps = json.loads(caps)
        plan_tiers = caps.get("plan_tiers", [])
        if not plan_tiers:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot publish: at least one plan_tier must be set in capabilities.",
            )

    variables_list = (
        [v.model_dump() for v in body.variables] if body.variables is not None else None
    )
    guardrails_dict = (
        body.guardrails.model_dump() if body.guardrails is not None else None
    )

    updated = await update_platform_template_db(
        template_id=template_id,
        current=current,
        system_prompt=body.system_prompt,
        variables=variables_list,
        guardrails=guardrails_dict,
        new_status=body.status,
        changelog=body.changelog,
        platform_tenant_id=platform_tenant_id,
        db=session,
    )

    logger.info(
        "platform_agent_template_updated",
        template_id=template_id,
        user_id=current_user.id,
        new_status=updated["status"],
        version=updated["version"],
    )

    updated_at = updated["updated_at"]
    updated_at_str = (
        updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at)
    )

    return {
        "id": updated["id"],
        "version": updated["version"],
        "status": updated["status"],
        "updated_at": updated_at_str,
    }


# ---------------------------------------------------------------------------
# Route: GET /platform/tool-catalog  (API-041)
# ---------------------------------------------------------------------------


@router.get(
    "/platform/tool-catalog",
    tags=["platform"],
)
async def list_tool_catalog(
    safety_class: Optional[str] = Query(None, description="Filter by safety class"),
    tool_status: Optional[str] = Query(
        None, alias="status", description="Filter by status"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-041: List the tool catalog.

    Platform admins see all tools.
    Tenant admins see tools whose plan_tiers overlap with their plan.
    """
    if current_user.scope != "platform" and "tenant_admin" not in current_user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin or tenant admin access required.",
        )

    # Validate allowlisted filter values
    if safety_class is not None and safety_class not in _VALID_SAFETY_CLASSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid safety_class. Allowed: {sorted(_VALID_SAFETY_CLASSES)}",
        )
    if tool_status is not None and tool_status not in _VALID_TOOL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status. Allowed: {sorted(_VALID_TOOL_STATUSES)}",
        )

    result = await list_tools_db(
        page=page,
        page_size=page_size,
        safety_class=safety_class,
        tool_status=tool_status,
        db=session,
    )

    # For tenant admins: filter items by plan_tiers overlap
    if current_user.scope != "platform":
        user_plan = current_user.plan
        result["items"] = [
            item
            for item in result["items"]
            if not item["plan_tiers"] or user_plan in item["plan_tiers"]
        ]
        result["total"] = len(result["items"])

    logger.info(
        "tool_catalog_listed",
        user_id=current_user.id,
        scope=current_user.scope,
        total=result["total"],
    )
    return result


# ---------------------------------------------------------------------------
# Route: POST /platform/tool-catalog  (API-042)
# ---------------------------------------------------------------------------


@router.post(
    "/platform/tool-catalog",
    status_code=status.HTTP_201_CREATED,
    tags=["platform"],
)
async def register_tool(
    body: RegisterToolRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-042: Register a new tool in the platform tool catalog.

    endpoint_url MUST use HTTPS. Auth credentials are NOT stored (no vault yet).
    Tool status is set to 'pending_health_check' initially, then immediately
    updated to 'healthy' (health check infra pending).
    """
    # Validate HTTPS requirement
    if not body.endpoint_url.startswith("https://"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="endpoint_url must use HTTPS (http:// URLs are not allowed).",
        )

    # Validate auth_type
    if body.auth_type not in _VALID_AUTH_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid auth_type. Allowed: {sorted(_VALID_AUTH_TYPES)}",
        )

    # Validate safety_class
    if body.safety_class not in _VALID_SAFETY_CLASSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid safety_class. Allowed: {sorted(_VALID_SAFETY_CLASSES)}",
        )

    # Validate plan_tiers
    invalid_tiers = set(body.plan_tiers) - _VALID_PLAN_TIERS
    if invalid_tiers:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid plan_tiers: {sorted(invalid_tiers)}. "
            f"Allowed: {sorted(_VALID_PLAN_TIERS)}",
        )

    result = await register_tool_db(
        name=body.name,
        provider=body.provider,
        description=body.description,
        endpoint_url=body.endpoint_url,
        auth_type=body.auth_type,
        capabilities=body.capabilities,
        safety_class=body.safety_class,
        plan_tiers=body.plan_tiers,
        db=session,
    )

    logger.info(
        "platform_tool_registered",
        tool_id=result["id"],
        user_id=current_user.id,
        name=body.name,
        safety_class=body.safety_class,
    )
    return result


# ---------------------------------------------------------------------------
# API-112: Platform audit log (cross-tenant)
# ---------------------------------------------------------------------------


async def get_platform_audit_log_db(
    filter_tenant_id: Optional[str],
    actor_id: Optional[str],
    action: Optional[str],
    from_date: Optional[datetime],
    to_date: Optional[datetime],
    page: int,
    page_size: int,
    db: AsyncSession,
) -> tuple[list[dict], int]:
    """
    Query audit_log across all tenants (no RLS tenant filter).

    Optionally filtered by tenant_id, actor_id, action, date range.
    Returns (items, total).
    """
    conditions: list[str] = []
    params: dict = {}

    if filter_tenant_id:
        conditions.append("al.tenant_id = :tenant_id")
        params["tenant_id"] = filter_tenant_id

    if actor_id:
        conditions.append("al.user_id = :actor_id")
        params["actor_id"] = actor_id

    if action:
        conditions.append("al.action = :action")
        params["action"] = action

    if from_date:
        conditions.append("al.created_at >= :from_date")
        params["from_date"] = from_date

    if to_date:
        conditions.append("al.created_at <= :to_date")
        params["to_date"] = to_date

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM audit_log al {where_clause}"),
        params,
    )
    total = int(count_result.scalar_one() or 0)

    offset = (page - 1) * page_size
    params["limit"] = page_size
    params["offset"] = offset

    rows_result = await db.execute(
        text(
            f"SELECT "
            f"  al.id, al.user_id, u.email AS actor_email, "
            f"  al.action, al.resource_type, al.resource_id, "
            f"  al.details, al.created_at "
            f"FROM audit_log al "
            f"LEFT JOIN users u ON u.id = al.user_id "
            f"{where_clause} "
            f"ORDER BY al.created_at DESC "
            f"LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    rows = rows_result.fetchall()

    items = [
        {
            "id": str(row[0]),
            "actor_id": str(row[1]) if row[1] else None,
            "actor_email": row[2] or "",
            "action": row[3] or "",
            "resource_type": row[4] or "",
            "resource_id": str(row[5]) if row[5] else None,
            "metadata": row[6] if row[6] is not None else {},
            "created_at": row[7].isoformat() if row[7] else "",
        }
        for row in rows
    ]

    return items, total


def _build_audit_csv_response(
    items: list[dict], filename: str = "audit-log.csv"
) -> StreamingResponse:
    """Build a CSV StreamingResponse from audit log items."""
    output = io.StringIO()
    fieldnames = [
        "id",
        "actor_id",
        "actor_email",
        "action",
        "resource_type",
        "resource_id",
        "metadata",
        "created_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for item in items:
        row = dict(item)
        row["metadata"] = str(row.get("metadata", {}))
        writer.writerow(row)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/platform/audit-log", tags=["platform"])
async def get_platform_audit_log(
    tenant_id: Optional[str] = Query(None, description="Filter by tenant ID"),
    actor_id: Optional[str] = Query(None, description="Filter by actor user ID"),
    action: Optional[str] = Query(None, description="Filter by action"),
    from_date: Optional[datetime] = Query(None, description="Start date (ISO-8601)"),
    to_date: Optional[datetime] = Query(None, description="End date (ISO-8601)"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    format: Optional[str] = Query(
        None, description="Response format: json (default) or csv"
    ),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-112: Cross-tenant audit log for platform admins.

    Bypasses per-tenant RLS — returns audit events across all tenants.
    Optional filters: tenant_id, actor_id, action, date range.

    Auth: platform_admin required.
    """
    items, total = await get_platform_audit_log_db(
        filter_tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
        db=session,
    )

    logger.info(
        "platform_audit_log_fetched",
        user_id=current_user.id,
        filter_tenant_id=tenant_id,
        total=total,
        page=page,
    )

    if format == "csv":
        return _build_audit_csv_response(items, filename="platform-audit-log.csv")

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# API-036: Cross-tenant cost analytics
# ---------------------------------------------------------------------------


async def get_cost_analytics_db(
    days: int,
    filter_tenant_id: Optional[str],
    db: AsyncSession,
) -> tuple[list[dict], float, float]:
    """
    Aggregate token usage and compute LLM cost per tenant for the period.

    Cost rates read from env: INPUT_COST_PER_1K (default 0.005), OUTPUT_COST_PER_1K (default 0.015).
    Revenue prorated from plan × (days / 30).

    Returns (by_tenant, platform_llm_total, platform_revenue_total).
    """
    input_cost_per_1k = float(os.environ.get("INPUT_COST_PER_1K", "0.005"))
    output_cost_per_1k = float(os.environ.get("OUTPUT_COST_PER_1K", "0.015"))

    tenant_filter_clause = ""
    params: dict = {"days": days}
    if filter_tenant_id:
        tenant_filter_clause = "AND m.tenant_id = :filter_tenant_id"
        params["filter_tenant_id"] = filter_tenant_id

    rows_result = await db.execute(
        text(
            f"SELECT "
            f"  t.id AS tenant_id, "
            f"  t.name AS tenant_name, "
            f"  t.plan AS tenant_plan, "
            f"  COALESCE(SUM(CAST(m.metadata->>'tokens_in' AS BIGINT)), 0) AS tokens_in, "
            f"  COALESCE(SUM(CAST(m.metadata->>'tokens_out' AS BIGINT)), 0) AS tokens_out "
            f"FROM tenants t "
            f"LEFT JOIN messages m "
            f"  ON m.tenant_id = t.id "
            f"  AND m.created_at >= NOW() - INTERVAL '1 day' * :days "
            f"  {tenant_filter_clause} "
            f"WHERE t.status = 'active' "
            f"GROUP BY t.id, t.name, t.plan "
            f"ORDER BY tokens_in DESC"
        ),
        params,
    )
    rows = rows_result.fetchall()

    by_tenant = []
    platform_llm_total = 0.0
    platform_revenue_total = 0.0

    for row in rows:
        tid = str(row[0])
        tname = row[1]
        plan = row[2] or "professional"
        tokens_in = int(row[3])
        tokens_out = int(row[4])

        llm_cost = round(
            tokens_in * input_cost_per_1k / 1000.0
            + tokens_out * output_cost_per_1k / 1000.0,
            4,
        )

        monthly_revenue = _PLAN_REVENUE_MONTHLY.get(plan, 299.0)
        period_revenue = round(monthly_revenue * days / 30.0, 4)

        gross_margin = None
        if period_revenue > 0:
            gross_margin = round(
                ((period_revenue - llm_cost) / period_revenue) * 100.0, 2
            )

        platform_llm_total += llm_cost
        platform_revenue_total += period_revenue

        by_tenant.append(
            {
                "tenant_id": tid,
                "name": tname,
                "plan": plan,
                "llm_cost_usd": llm_cost,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "gross_margin_pct": gross_margin,
            }
        )

    return by_tenant, round(platform_llm_total, 4), round(platform_revenue_total, 4)


@router.get("/platform/analytics/cost", tags=["platform"])
async def get_cost_analytics(
    period: str = Query("30d", description="Time period: 7d, 30d, or 90d"),
    tenant_id: Optional[str] = Query(None, description="Filter to a single tenant"),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-036: Cross-tenant LLM cost and revenue analytics.

    Aggregates token usage from messages.metadata per tenant per period.
    Cost rates read from env: INPUT_COST_PER_1K (default 0.005), OUTPUT_COST_PER_1K (default 0.015).
    Revenue prorated from plan × (days/30).

    Auth: platform_admin required.
    """
    if period not in _ANALYTICS_PERIODS:
        period = "30d"
    days = _ANALYTICS_PERIODS[period]

    by_tenant, platform_llm_total, platform_revenue_total = await get_cost_analytics_db(
        days=days,
        filter_tenant_id=tenant_id,
        db=session,
    )

    platform_gross_margin = None
    if platform_revenue_total > 0:
        platform_gross_margin = round(
            ((platform_revenue_total - platform_llm_total) / platform_revenue_total)
            * 100.0,
            2,
        )

    logger.info(
        "platform_cost_analytics_fetched",
        user_id=current_user.id,
        period=period,
        platform_llm_total=platform_llm_total,
        platform_revenue_total=platform_revenue_total,
    )

    return {
        "period": period,
        "platform_total": {
            "llm_cost_usd": platform_llm_total,
            "revenue_usd": platform_revenue_total,
            "gross_margin_pct": platform_gross_margin,
        },
        "by_tenant": by_tenant,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# API-037: Tenant health scores dashboard
# ---------------------------------------------------------------------------


async def get_health_scores_db(
    db: AsyncSession,
    at_risk_only: bool,
    sort_by: str,
) -> tuple[list[dict], int, int, float]:
    """
    Compute health scores for all active tenants.

    Returns (tenant_scores_list, active_count, at_risk_count, avg_satisfaction).
    """
    tenants_result = await db.execute(
        text("SELECT id, name FROM tenants WHERE status = 'active' ORDER BY name ASC")
    )
    tenants = tenants_result.fetchall()

    tenant_scores = []
    total_satisfaction_sum = 0.0
    satisfaction_count = 0

    for row in tenants:
        tid = str(row[0])
        tname = row[1]

        # Usage trend: current week vs prior week message count
        trend_result = await db.execute(
            text(
                "SELECT "
                "  COUNT(CASE WHEN created_at >= NOW() - INTERVAL '7 days' THEN 1 END) AS current_week, "
                "  COUNT(CASE WHEN created_at >= NOW() - INTERVAL '14 days' "
                "             AND created_at < NOW() - INTERVAL '7 days' THEN 1 END) AS prior_week "
                "FROM messages "
                "WHERE tenant_id = :tenant_id AND role = 'user'"
            ),
            {"tenant_id": tid},
        )
        trend_row = trend_result.fetchone()
        current_week = int(trend_row[0] or 0)
        prior_week = int(trend_row[1] or 0)
        usage_trend_pct = (
            (current_week - prior_week) / prior_week if prior_week > 0 else 0.0
        )

        # Feature breadth: fraction of 4 features in use
        has_docs = await db.execute(
            text(
                "SELECT COUNT(*) > 0 FROM sync_jobs WHERE tenant_id = :tid AND status = 'completed'"
            ),
            {"tid": tid},
        )
        has_feedback = await db.execute(
            text("SELECT COUNT(*) > 0 FROM user_feedback WHERE tenant_id = :tid"),
            {"tid": tid},
        )
        has_glossary = await db.execute(
            text("SELECT COUNT(*) > 0 FROM glossary_terms WHERE tenant_id = :tid"),
            {"tid": tid},
        )
        has_agents = await db.execute(
            text("SELECT COUNT(*) > 0 FROM agent_cards WHERE tenant_id = :tid"),
            {"tid": tid},
        )
        feature_flags = [
            bool(has_docs.scalar_one()),
            bool(has_feedback.scalar_one()),
            bool(has_glossary.scalar_one()),
            bool(has_agents.scalar_one()),
        ]
        feature_breadth = sum(1 for f in feature_flags if f) / len(feature_flags)

        # Satisfaction percentage
        sat_result = await db.execute(
            text(
                "SELECT COUNT(*), COUNT(CASE WHEN rating = 1 THEN 1 END) "
                "FROM user_feedback WHERE tenant_id = :tid"
            ),
            {"tid": tid},
        )
        sat_row = sat_result.fetchone()
        sat_total = int(sat_row[0] or 0)
        sat_positive = int(sat_row[1] or 0)
        satisfaction_pct = (
            round(100.0 * sat_positive / sat_total, 1) if sat_total > 0 else 50.0
        )

        # Error rate: % of messages with metadata->>'error' = 'true'
        err_result = await db.execute(
            text(
                "SELECT "
                "  COUNT(*) AS total, "
                "  COUNT(CASE WHEN metadata->>'error' = 'true' THEN 1 END) AS errors "
                "FROM messages WHERE tenant_id = :tid"
            ),
            {"tid": tid},
        )
        err_row = err_result.fetchone()
        err_total = int(err_row[0] or 0)
        err_count = int(err_row[1] or 0)
        error_rate_pct = (
            round(100.0 * err_count / err_total, 1) if err_total > 0 else 0.0
        )

        try:
            hs = calculate_health_score(
                usage_trend_pct=usage_trend_pct,
                feature_breadth=feature_breadth,
                satisfaction_pct=satisfaction_pct,
                error_rate_pct=error_rate_pct,
            )
            health_score = int(hs.score)
        except ValueError:
            health_score = 50

        # Trend: compare current week vs prior week satisfaction
        cur_sat_result = await db.execute(
            text(
                "SELECT COUNT(*), COUNT(CASE WHEN rating = 1 THEN 1 END) "
                "FROM user_feedback WHERE tenant_id = :tid "
                "  AND created_at >= NOW() - INTERVAL '7 days'"
            ),
            {"tid": tid},
        )
        cur_sat_row = cur_sat_result.fetchone()
        cur_sat_total = int(cur_sat_row[0] or 0)
        cur_sat_pos = int(cur_sat_row[1] or 0)
        cur_week_sat = (
            100.0 * cur_sat_pos / cur_sat_total if cur_sat_total > 0 else 50.0
        )

        prior_sat_result = await db.execute(
            text(
                "SELECT COUNT(*), COUNT(CASE WHEN rating = 1 THEN 1 END) "
                "FROM user_feedback WHERE tenant_id = :tid "
                "  AND created_at >= NOW() - INTERVAL '14 days' "
                "  AND created_at < NOW() - INTERVAL '7 days'"
            ),
            {"tid": tid},
        )
        prior_sat_row = prior_sat_result.fetchone()
        prior_sat_total = int(prior_sat_row[0] or 0)
        prior_sat_pos = int(prior_sat_row[1] or 0)
        prior_week_sat = (
            100.0 * prior_sat_pos / prior_sat_total if prior_sat_total > 0 else 50.0
        )

        sat_delta = cur_week_sat - prior_week_sat
        if sat_delta >= 5.0:
            trend = "improving"
        elif sat_delta <= -5.0:
            trend = "declining"
        else:
            trend = "stable"

        at_risk = health_score < 70

        total_satisfaction_sum += satisfaction_pct
        satisfaction_count += 1

        tenant_scores.append(
            {
                "id": tid,
                "name": tname,
                "health_score": health_score,
                "at_risk": at_risk,
                "trend": trend,
                "satisfaction_rate": satisfaction_pct,
            }
        )

    active_count = len(tenant_scores)
    at_risk_count = sum(1 for t in tenant_scores if t["at_risk"])
    avg_satisfaction = (
        round(total_satisfaction_sum / satisfaction_count, 1)
        if satisfaction_count > 0
        else 0.0
    )

    if at_risk_only:
        tenant_scores = [t for t in tenant_scores if t["at_risk"]]

    if sort_by == "name":
        tenant_scores.sort(key=lambda x: x["name"])
    else:
        tenant_scores.sort(key=lambda x: x["health_score"], reverse=True)

    return tenant_scores, active_count, at_risk_count, avg_satisfaction


@router.get("/platform/analytics/health", tags=["platform"])
async def get_health_dashboard(
    sort_by: str = Query("score", description="Sort by: score (desc) or name (asc)"),
    at_risk_only: bool = Query(
        False, description="Return only at-risk tenants (health_score < 70)"
    ),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-037: Tenant health scores dashboard.

    Computes health score for every active tenant using weighted signals:
    usage_trend (30%), feature_breadth (20%), satisfaction (35%), error_rate (15%).

    at_risk: health_score < 70
    trend: improving if satisfaction delta >= +5pp over prior week, declining if <= -5pp

    Auth: platform_admin required.
    """
    if sort_by not in _VALID_HEALTH_SORT:
        sort_by = "score"

    (
        tenant_scores,
        active_count,
        at_risk_count,
        avg_satisfaction,
    ) = await get_health_scores_db(
        db=session,
        at_risk_only=at_risk_only,
        sort_by=sort_by,
    )

    logger.info(
        "health_scores_dashboard_fetched",
        user_id=current_user.id,
        active_count=active_count,
        at_risk_count=at_risk_count,
    )

    return {
        "summary": {
            "active_tenants": active_count,
            "at_risk_count": at_risk_count,
            "avg_satisfaction": avg_satisfaction,
        },
        "tenants": tenant_scores,
    }
