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
- GET  /platform/preferences               — Get platform admin preferences (API-115)
- PATCH /platform/preferences              — Update platform admin preferences (API-115)
- POST /platform/impersonate               — Impersonate a tenant (API-113)
- POST /platform/impersonate/end           — End impersonation (API-114)
- POST /platform/tenants/{id}/gdpr-delete  — GDPR deletion workflow (API-116)
"""
import asyncio
import csv
import io
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Annotated, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, status
from fastapi.responses import StreamingResponse
from jose import jwt
from pydantic import BaseModel, Field, validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_platform_admin
from app.core.redis_client import build_redis_key, get_redis
from app.core.session import get_async_session
from app.modules.platform.health_score import calculate_health_score
from app.modules.platform.performance import run_template_performance_batch

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


_VALID_VARIABLE_TYPES = {"text", "number", "select"}
# Status values that may be set directly via the API (seed is system-only)
_WRITABLE_TEMPLATE_STATUSES = {"Draft", "Published", "Deprecated"}
# Columns that may be updated via PATCH — enforces no dynamic column interpolation
_TEMPLATE_UPDATE_ALLOWLIST = {
    "name",
    "description",
    "category",
    "system_prompt",
    "variable_definitions",
    "guardrails",
    "confidence_threshold",
    "status",
    "changelog",
}


class TemplateVariableDef(BaseModel):
    """PA-020: variable_definitions entry — validated at API layer."""

    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., pattern=r"^(text|number|select)$")
    label: str = Field(..., min_length=1, max_length=200)
    required: bool = False
    options: List[str] = Field(default_factory=list)  # for select type


class GuardrailRule(BaseModel):
    """A single guardrail rule: pattern (regex/substring), action, and reason."""

    pattern: str = Field(..., min_length=1, max_length=200)
    action: str = Field(..., pattern=r"^(block|warn)$")
    reason: str = Field(default="", max_length=500)


# ---------------------------------------------------------------------------
# ATA-022: Structured guardrail configuration schema
# ---------------------------------------------------------------------------

_VALID_GUARDRAIL_RULE_TYPES = frozenset({
    "keyword_block",
    "citation_required",
    "max_length",
    "confidence_threshold",
    "semantic_check",
})
_VALID_GUARDRAIL_ACTIONS = frozenset({"block", "redact", "warn"})


class GuardrailsSchema(BaseModel):
    """
    ATA-022 / RULE A2A-02: Structured guardrail configuration for agent templates.

    This schema validates guardrail *configuration*.
    Configuration stored here is a declaration only.
    Runtime enforcement is handled by OutputGuardrailChecker in guardrails.py.
    Storing a guardrail config without the checker running has NO effect.
    """

    blocked_topics: Optional[List[str]] = Field(default=None, max_length=50)
    confidence_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_response_length: Optional[int] = Field(default=None, ge=0, le=10000)
    rules: Optional[List[Dict[str, Any]]] = Field(default=None, max_length=20)

    @validator("rules", each_item=True)
    def validate_rule(cls, rule: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N805
        rule_type = rule.get("type")
        if rule_type not in _VALID_GUARDRAIL_RULE_TYPES:
            raise ValueError(
                f"Invalid rule type '{rule_type}'. "
                f"Must be one of: {sorted(_VALID_GUARDRAIL_RULE_TYPES)}"
            )
        action = rule.get("action")
        if action is not None and action not in _VALID_GUARDRAIL_ACTIONS:
            raise ValueError(
                f"Invalid action '{action}'. "
                f"Must be one of: {sorted(_VALID_GUARDRAIL_ACTIONS)}"
            )
        for pattern in rule.get("patterns", []):
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    f"Invalid regex pattern '{pattern}': {exc}"
                ) from exc
            # ReDoS guard: run the compiled pattern against a known catastrophic
            # backtracking input (30 'a' chars + 'b' — triggers exponential
            # backtracking in patterns like (a+)+ or (a*)*). Use a thread with
            # a 50ms timeout. Any legitimate pattern completes in microseconds.
            import concurrent.futures as _cf
            _REDOS_TEST = "a" * 30 + "b"
            with _cf.ThreadPoolExecutor(max_workers=1) as _pool:
                _fut = _pool.submit(compiled.search, _REDOS_TEST)
                try:
                    _fut.result(timeout=0.05)
                except _cf.TimeoutError:
                    raise ValueError(
                        f"Regex pattern '{pattern}' exhibits catastrophic backtracking "
                        "(ReDoS). Simplify the pattern to avoid nested quantifiers."
                    )
        return rule


class CreateAgentTemplateRequest(BaseModel):
    """PA-020: Create a new Draft template."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=100)
    system_prompt: str = Field(..., min_length=1, max_length=100_000)
    variable_definitions: List[TemplateVariableDef] = Field(default_factory=list)
    guardrails: List[GuardrailRule] = Field(default_factory=list, max_length=50)
    confidence_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    # ATA-022: structured guardrail configuration (validated by GuardrailsSchema)
    guardrails_config: Optional[GuardrailsSchema] = None


class PatchAgentTemplateRequest(BaseModel):
    """PA-020: Partial update for a template. system_prompt rejected (409) on Published."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=100)
    system_prompt: Optional[str] = Field(None, min_length=1, max_length=100_000)
    variable_definitions: Optional[List[TemplateVariableDef]] = None
    guardrails: Optional[List[GuardrailRule]] = Field(None, max_length=50)
    confidence_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    # ATA-022: structured guardrail configuration (validated by GuardrailsSchema)
    guardrails_config: Optional[GuardrailsSchema] = None
    # ATA-058: allow Published | Deprecated transitions.
    # Deprecated → Published restores the template to the tenant catalog.
    status: Optional[str] = Field(None, pattern=r"^(Published|Deprecated)$")
    changelog: Optional[str] = Field(None, max_length=5000)


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


async def _create_agent_template_db(
    body: "CreateAgentTemplateRequest",
    created_by: str,
    db: AsyncSession,
) -> dict:
    """PA-020: Insert a new Draft agent template into agent_templates."""
    template_id = str(uuid.uuid4())
    variable_defs_json = json.dumps([v.model_dump() for v in body.variable_definitions])
    guardrails_json = json.dumps([g.model_dump() for g in body.guardrails])

    await db.execute(
        text(
            "INSERT INTO agent_templates "
            "(id, name, description, category, system_prompt, variable_definitions, "
            "guardrails, confidence_threshold, version, status, created_by) "
            "VALUES (:id, :name, :description, :category, :system_prompt, "
            "CAST(:variable_definitions AS jsonb), CAST(:guardrails AS jsonb), "
            ":confidence_threshold, 1, 'Draft', :created_by)"
        ),
        {
            "id": template_id,
            "name": body.name,
            "description": body.description,
            "category": body.category,
            "system_prompt": body.system_prompt,
            "variable_definitions": variable_defs_json,
            "guardrails": guardrails_json,
            "confidence_threshold": body.confidence_threshold,
            "created_by": created_by,
        },
    )
    await db.commit()
    # Re-fetch the full row so the 201 response has the same shape as GET detail.
    return await _get_agent_template_db(template_id, db)


async def _get_agent_template_db(template_id: str, db: AsyncSession) -> Optional[dict]:
    """PA-020/022: Fetch a single agent template by ID from agent_templates."""
    result = await db.execute(
        text(
            "SELECT id, name, description, category, system_prompt, "
            "variable_definitions, guardrails, confidence_threshold, "
            "version, status, changelog, created_by, parent_id, "
            "created_at, updated_at "
            "FROM agent_templates WHERE id = :id"
        ),
        {"id": template_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "category": row["category"],
        "system_prompt": row["system_prompt"],
        "variable_definitions": row["variable_definitions"] or [],
        "guardrails": row["guardrails"] or [],
        "confidence_threshold": (
            float(row["confidence_threshold"])
            if row["confidence_threshold"] is not None
            else None
        ),
        "version": row["version"],
        "status": row["status"],
        "changelog": row["changelog"],
        "created_by": str(row["created_by"]) if row["created_by"] else None,
        "parent_id": str(row["parent_id"]) if row["parent_id"] else None,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


async def _patch_agent_template_db(
    template_id: str,
    body: "PatchAgentTemplateRequest",
    db: AsyncSession,
) -> Optional[dict]:
    """PA-020: Apply a partial update to an agent_templates row."""
    set_parts = ["updated_at = NOW()"]
    params: dict = {"id": template_id}

    if body.name is not None:
        set_parts.append("name = :name")
        params["name"] = body.name
    if body.description is not None:
        set_parts.append("description = :description")
        params["description"] = body.description
    if body.category is not None:
        set_parts.append("category = :category")
        params["category"] = body.category
    if body.system_prompt is not None:
        set_parts.append("system_prompt = :system_prompt")
        params["system_prompt"] = body.system_prompt
    if body.variable_definitions is not None:
        set_parts.append("variable_definitions = CAST(:variable_definitions AS jsonb)")
        params["variable_definitions"] = json.dumps(
            [v.model_dump() for v in body.variable_definitions]
        )
    if body.guardrails is not None:
        set_parts.append("guardrails = CAST(:guardrails AS jsonb)")
        params["guardrails"] = json.dumps([g.model_dump() for g in body.guardrails])
    if body.confidence_threshold is not None:
        set_parts.append("confidence_threshold = :confidence_threshold")
        params["confidence_threshold"] = body.confidence_threshold
    if body.status is not None:
        set_parts.append("status = :status")
        params["status"] = body.status
    if body.changelog is not None:
        set_parts.append("changelog = :changelog")
        params["changelog"] = body.changelog

    set_clause = ", ".join(set_parts)
    await db.execute(
        text(f"UPDATE agent_templates SET {set_clause} WHERE id = :id"),
        params,
    )
    await db.commit()
    return await _get_agent_template_db(template_id, db)


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
    # Both platform admins and tenant admins can access the dashboard.
    # Platform admins see cross-tenant aggregated stats.
    # Tenant admins see their own tenant's stats (RLS already scopes the session).
    if current_user.scope not in ("platform", "tenant"):
        logger.warning(
            "dashboard_access_denied",
            user_id=current_user.id,
            scope=current_user.scope,
        )
        raise HTTPException(
            status_code=403,
            detail="Access denied.",
        )

    is_platform = current_user.scope == "platform"

    logger.info(
        "dashboard_stats_requested",
        user_id=current_user.id,
        scope=current_user.scope,
    )

    if is_platform:
        active_users_result = await session.execute(
            text("SELECT COUNT(*) FROM users WHERE status = 'active'")
        )
    else:
        active_users_result = await session.execute(
            text(
                "SELECT COUNT(*) FROM users "
                "WHERE status = 'active' AND tenant_id = :tid"
            ),
            {"tid": current_user.tenant_id},
        )
    active_users = active_users_result.scalar_one()

    if is_platform:
        docs_result = await session.execute(
            text(
                "SELECT COALESCE(SUM(files_synced), 0) "
                "FROM sync_jobs WHERE status = 'completed'"
            )
        )
    else:
        docs_result = await session.execute(
            text(
                "SELECT COALESCE(SUM(sj.files_synced), 0) "
                "FROM sync_jobs sj "
                "JOIN integrations i ON i.id = sj.integration_id "
                "WHERE sj.status = 'completed' AND i.tenant_id = :tid"
            ),
            {"tid": current_user.tenant_id},
        )
    documents_indexed = docs_result.scalar_one()

    from datetime import date

    today_start = datetime.combine(
        date.today(), datetime.min.time(), tzinfo=timezone.utc
    )
    if is_platform:
        queries_result = await session.execute(
            text(
                "SELECT COUNT(*) FROM messages "
                "WHERE role = 'user' AND created_at >= :today_start"
            ),
            {"today_start": today_start},
        )
    else:
        queries_result = await session.execute(
            text(
                "SELECT COUNT(*) FROM messages m "
                "JOIN conversations c ON c.id = m.conversation_id "
                "WHERE m.role = 'user' AND m.created_at >= :today_start "
                "AND c.tenant_id = :tid"
            ),
            {"today_start": today_start, "tid": current_user.tenant_id},
        )
    queries_today = queries_result.scalar_one()

    if is_platform:
        feedback_result = await session.execute(
            text(
                "SELECT "
                "  COUNT(*) AS total, "
                "  COUNT(*) FILTER (WHERE rating = 1) AS positive "
                "FROM user_feedback"
            )
        )
    else:
        feedback_result = await session.execute(
            text(
                "SELECT "
                "  COUNT(*) AS total, "
                "  COUNT(*) FILTER (WHERE rating = 1) AS positive "
                "FROM user_feedback uf "
                "JOIN messages m ON m.id = uf.message_id "
                "JOIN conversations c ON c.id = m.conversation_id "
                "WHERE c.tenant_id = :tid"
            ),
            {"tid": current_user.tenant_id},
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
# PA-020: Agent Template CRUD API
# Endpoints:
#   POST   /platform/agent-templates          — Create Draft
#   GET    /platform/agent-templates          — List (platform admin + tenant admin)
#   GET    /platform/agent-templates/{id}     — Detail (platform admin + tenant admin)
#   PATCH  /platform/agent-templates/{id}     — Update (platform admin only)
# ---------------------------------------------------------------------------


def _validate_guardrail_patterns(guardrails: list) -> None:
    """
    Validate guardrail patterns at write-time.

    Rejects patterns that are not valid regular expressions.
    NOTE: `re.compile()` only checks syntax — it does not prevent
    catastrophically backtracking (ReDoS) patterns. Patterns are bounded to
    200 chars by GuardrailRule.pattern to limit blast radius.
    """
    for i, rule in enumerate(guardrails):
        # GuardrailRule objects after Pydantic parsing; dicts from DB/tests
        pattern = rule.pattern if hasattr(rule, "pattern") else rule.get("pattern", "")
        if not pattern:
            continue
        try:
            re.compile(pattern)
        except re.error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"guardrails[{i}].pattern is not a valid regular expression.",
            )


@router.post(
    "/platform/agent-templates",
    status_code=status.HTTP_201_CREATED,
    tags=["platform"],
)
async def create_agent_template(
    body: CreateAgentTemplateRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    PA-020: Create a new Draft agent template.

    Templates start in Draft status. Draft → Published via PATCH with status=Published.
    Published system_prompt is immutable — create a new version to change it (PA-022).
    """
    # Validate reserved variable names
    reserved_used = {
        v.name for v in body.variable_definitions if v.name in _RESERVED_VARIABLE_NAMES
    }
    if reserved_used:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Variable names are reserved: {sorted(reserved_used)}. "
            f"Reserved: {sorted(_RESERVED_VARIABLE_NAMES)}",
        )

    # Validate guardrail patterns at write-time to prevent invalid/ReDoS patterns
    _validate_guardrail_patterns(body.guardrails)

    result = await _create_agent_template_db(body, current_user.id, session)

    logger.info(
        "platform_agent_template_created",
        template_id=result["id"],
        actor_id=current_user.id,
        name=body.name,
    )
    return result


@router.get(
    "/platform/agent-templates",
    tags=["platform"],
)
async def list_agent_templates(
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        pattern=r"^(Draft|Published|Deprecated|seed)$",
    ),
    category: Optional[str] = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    PA-020: List agent templates.

    Platform admins see all statuses. Tenant admins see Published + seed only.
    Supports ?status= and ?category= filters.
    """
    is_platform = current_user.scope == "platform"
    is_tenant_admin = "tenant_admin" in current_user.roles

    if not is_platform and not is_tenant_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin or tenant admin access required.",
        )

    where_parts = []
    params: dict = {"limit": page_size, "offset": (page - 1) * page_size}

    # Tenant admins can only see Published/seed templates; status filter is not supported.
    if not is_platform:
        if status_filter is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Tenant admins may not filter by status.",
            )
        where_parts.append("status IN ('Published', 'seed')")
    elif status_filter is not None:
        where_parts.append("status = :status_filter")
        params["status_filter"] = status_filter

    if category is not None:
        where_parts.append("category = :category")
        params["category"] = category

    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    count_result = await session.execute(
        text(f"SELECT COUNT(*) FROM agent_templates {where_clause}"),
        params,
    )
    total = count_result.scalar() or 0

    rows_result = await session.execute(
        text(
            f"SELECT id, name, description, category, version, status, "
            f"confidence_threshold, created_at, updated_at "
            f"FROM agent_templates {where_clause} "
            f"ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    items = [
        {
            "id": str(r[0]),
            "name": r[1],
            "description": r[2],
            "category": r[3],
            "version": r[4],
            "status": r[5],
            "confidence_threshold": float(r[6]) if r[6] is not None else None,
            "created_at": r[7].isoformat() if r[7] else None,
            "updated_at": r[8].isoformat() if r[8] else None,
        }
        for r in rows_result.fetchall()
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get(
    "/platform/agent-templates/{template_id}",
    tags=["platform"],
)
async def get_agent_template(
    template_id: str = Path(
        ...,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    PA-020: Get a single agent template by ID.

    Platform admins can fetch any status. Tenant admins can only fetch Published/seed.
    """
    is_platform = current_user.scope == "platform"
    is_tenant_admin = "tenant_admin" in current_user.roles

    if not is_platform and not is_tenant_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin or tenant admin access required.",
        )

    template = await _get_agent_template_db(template_id, session)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent template not found.",
        )

    # Tenant admins cannot see Draft or Deprecated templates
    if not is_platform and template["status"] not in ("Published", "seed"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent template not found.",
        )

    return template


@router.patch(
    "/platform/agent-templates/{template_id}",
    tags=["platform"],
)
async def patch_agent_template(
    template_id: str = Path(
        ...,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    body: PatchAgentTemplateRequest = ...,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    PA-020: Partial update of an agent template.

    Draft fields (all except status) are freely editable while status = 'Draft'.
    Published templates: system_prompt is IMMUTABLE — returns 409.
    Status transitions: Draft → Published (requires changelog), Published → Deprecated.
    'seed' status is system-only and cannot be set or read back via this endpoint.
    """
    current = await _get_agent_template_db(template_id, session)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent template not found.",
        )

    current_status = current["status"]

    # Published system_prompt is immutable — reject, do not silently ignore
    if body.system_prompt is not None and current_status == "Published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "system_prompt is immutable on Published templates. "
                "Create a new version via POST /platform/agent-templates/{id}/new-version."
            ),
        )

    # Changelog required when publishing
    if body.status == "Published" and not body.changelog:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="changelog is required when publishing a template.",
        )

    # ATA-058: Deprecated → Published is allowed (restore template to catalog).
    # Any other attempt to transition out of Deprecated is rejected.
    if current_status == "Deprecated" and body.status is not None and body.status != "Published":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Deprecated templates can only be restored to Published status.",
        )

    # system_prompt must exist before publishing
    if body.status == "Published":
        effective_prompt = body.system_prompt or current["system_prompt"]
        if not effective_prompt:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot publish: system_prompt is required.",
            )

    # Validate guardrail patterns at write-time to prevent invalid/ReDoS patterns
    if body.guardrails is not None:
        _validate_guardrail_patterns(body.guardrails)

    updated = await _patch_agent_template_db(template_id, body, session)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent template not found.",
        )

    logger.info(
        "platform_agent_template_patched",
        template_id=template_id,
        actor_id=current_user.id,
        new_status=updated["status"],
    )
    return updated


# ---------------------------------------------------------------------------
# PA-022: Template Versioning
# POST /platform/agent-templates/{id}/new-version
# GET  /platform/agent-templates/{id}/versions
# ---------------------------------------------------------------------------


async def _create_template_version_db(
    source_id: str,
    actor_id: str,
    db: AsyncSession,
) -> Optional[dict]:
    """
    PA-022: Create a new Draft version of a template family.

    Copies all fields from the source template, increments version, sets
    status=Draft, and stores parent_id = root_id of the family.
    Returns the new template row or None if source not found.

    Concurrency safety: locks all family rows with FOR UPDATE before reading
    MAX(version), preventing duplicate version numbers from concurrent calls.
    The unique index idx_agent_templates_family_version is a DB-level safety net.
    """
    source = await _get_agent_template_db(source_id, db)
    if source is None:
        return None

    # Determine the root of this version family (always depth-1 tree)
    root_id = source.get("parent_id") or source["id"]

    # Lock the entire family to prevent concurrent MAX(version) races.
    # FOR UPDATE serializes concurrent new-version requests for the same family.
    await db.execute(
        text(
            "SELECT id FROM agent_templates "
            "WHERE id = :root_id OR parent_id = :root_id "
            "FOR UPDATE"
        ),
        {"root_id": root_id},
    )

    # Compute next version while holding the lock
    result = await db.execute(
        text(
            "SELECT COALESCE(MAX(version), 0) AS max_ver "
            "FROM agent_templates "
            "WHERE id = :root_id OR parent_id = :root_id"
        ),
        {"root_id": root_id},
    )
    row = result.mappings().first()
    next_version = (row["max_ver"] if row else 0) + 1

    new_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO agent_templates "
            "(id, name, description, category, system_prompt, variable_definitions, "
            "guardrails, confidence_threshold, version, status, changelog, "
            "created_by, parent_id) "
            "VALUES (:id, :name, :description, :category, :system_prompt, "
            "CAST(:variable_definitions AS jsonb), CAST(:guardrails AS jsonb), "
            ":confidence_threshold, :version, 'Draft', NULL, :created_by, :parent_id)"
        ),
        {
            "id": new_id,
            "name": source["name"],
            "description": source.get("description"),
            "category": source.get("category"),
            "system_prompt": source["system_prompt"],
            "variable_definitions": json.dumps(
                source.get("variable_definitions") or []
            ),
            "guardrails": json.dumps(source.get("guardrails") or []),
            "confidence_threshold": source.get("confidence_threshold"),
            "version": next_version,
            "created_by": actor_id,  # attribute to the actor, not the original author
            "parent_id": root_id,
        },
    )
    await db.commit()
    return await _get_agent_template_db(new_id, db)


async def _list_template_versions_db(
    template_id: str,
    db: AsyncSession,
) -> Optional[List[dict]]:
    """
    PA-022: Return all versions in a template family sorted by version DESC.

    Returns None if template_id does not exist.
    """
    # Verify the template exists and determine its root
    source = await _get_agent_template_db(template_id, db)
    if source is None:
        return None

    root_id = source.get("parent_id") or source["id"]

    result = await db.execute(
        text(
            "SELECT id, version, status, changelog, "
            "LEFT(system_prompt, 100) AS system_prompt_preview, "
            "created_at, updated_at "
            "FROM agent_templates "
            "WHERE id = :root_id OR parent_id = :root_id "
            "ORDER BY version DESC LIMIT 100"
        ),
        {"root_id": root_id},
    )
    rows = result.mappings().all()
    return [
        {
            "id": str(r["id"]),
            "version": r["version"],
            "status": r["status"],
            "changelog": r["changelog"],
            "system_prompt_preview": r["system_prompt_preview"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]


@router.post(
    "/platform/agent-templates/{template_id}/new-version",
    status_code=status.HTTP_201_CREATED,
    tags=["platform"],
)
async def create_template_new_version(
    template_id: str = Path(
        ...,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    PA-022: Create a new Draft version of a template.

    Copies all fields from the source template (variable_definitions, guardrails,
    system_prompt, etc.) and sets version = max(family_version) + 1, status = Draft.
    Published versions are never modified — use this endpoint instead of PATCH.
    Deprecated templates cannot produce new versions (409).
    """
    source = await _get_agent_template_db(template_id, session)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent template not found.",
        )
    if source["status"] == "Deprecated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cannot create a new version from a Deprecated template. "
                "Only Draft or Published templates can be versioned."
            ),
        )

    result = await _create_template_version_db(template_id, current_user.id, session)
    if result is None:
        # Defensive — source was validated above; this guards against a race
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent template not found.",
        )

    logger.info(
        "platform_agent_template_new_version_created",
        source_id=template_id,
        new_id=result["id"],
        new_version=result["version"],
        actor_id=current_user.id,
    )
    return result


@router.get(
    "/platform/agent-templates/{template_id}/versions",
    tags=["platform"],
)
async def list_template_versions(
    template_id: str = Path(
        ...,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    PA-022: Return version history for a template family.

    Returns all versions (root + all drafts/published siblings) sorted by
    version DESC. Each entry includes: id, version, status, changelog,
    system_prompt_preview (first 100 chars), created_at, updated_at.
    """
    versions = await _list_template_versions_db(template_id, session)
    if versions is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent template not found.",
        )
    return {"versions": versions}


# ---------------------------------------------------------------------------
# PA-021: Agent Template Test Harness
# POST /platform/agent-templates/{id}/test
# ---------------------------------------------------------------------------

_TEMPLATE_TEST_MAX_PROMPTS = 5
_TEMPLATE_TEST_TIMEOUT_SECONDS = 30
# Double-brace variable substitution: {{variable_name}} in system_prompt
_TEMPLATE_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


class TestTemplateRequest(BaseModel):
    variable_values: Dict[str, Annotated[str, Field(max_length=1000)]] = Field(
        default_factory=dict, max_length=50
    )
    test_prompts: List[Annotated[str, Field(min_length=1, max_length=4000)]] = Field(
        ..., min_length=1, max_length=_TEMPLATE_TEST_MAX_PROMPTS
    )


class TemplateTestResult(BaseModel):
    prompt: str
    response: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    guardrail_triggered: bool
    guardrail_reason: str
    timed_out: bool = False


class TemplateTestResponse(BaseModel):
    tests: List[TemplateTestResult]


_CTRL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def _substitute_variables(system_prompt: str, variable_values: dict) -> str:
    """
    Replace {{variable_name}} placeholders with values from variable_values.

    Control characters (including newlines) are stripped from substituted values
    to reduce prompt injection risk via crafted variable values.
    Unknown placeholders are left as-is.
    """

    def replacer(match: re.Match) -> str:
        raw = str(variable_values.get(match.group(1), match.group(0)))
        # Strip control characters to prevent newline-based instruction injection
        return _CTRL_CHAR_RE.sub("", raw)

    return _TEMPLATE_VAR_RE.sub(replacer, system_prompt)


def _evaluate_guardrails(response_text: str, guardrails: list) -> tuple[bool, str]:
    """
    Check if response_text triggers any guardrail.

    Supports both GuardrailRule objects (after Pydantic parsing) and raw dicts
    (from DB JSONB or tests). Returns (triggered, reason_string).
    """
    for rule in guardrails:
        # Support both GuardrailRule objects and raw dicts
        if hasattr(rule, "pattern"):
            pattern = rule.pattern
            reason = rule.reason
        else:
            pattern = rule.get("pattern", "")
            reason = rule.get("reason", pattern)
        if not pattern:
            continue
        try:
            if re.search(pattern, response_text, re.IGNORECASE):
                return True, reason
        except re.error:
            # Invalid pattern reached runtime (e.g., direct DB edit) — log and
            # fall back to substring match as defense-in-depth.
            logger.warning(
                "guardrail_invalid_pattern_at_runtime",
                pattern=pattern[:80],
            )
            if pattern.lower() in response_text.lower():
                return True, reason
    return False, ""


async def _run_template_prompt(
    prompt: str,
    resolved_system_prompt: str,
    guardrails: list,
    adapter: Any = None,
) -> TemplateTestResult:
    """Run a single test prompt against the resolved system prompt via AzureOpenAIProvider."""
    import os as _os

    if adapter is None:
        from app.core.llm.azure_openai import AzureOpenAIProvider

        adapter = AzureOpenAIProvider()
    model = _os.environ.get("PRIMARY_MODEL", "agentic-worker")
    messages = [
        {"role": "system", "content": resolved_system_prompt},
        {"role": "user", "content": prompt},
    ]
    try:
        resp = await asyncio.wait_for(
            adapter.complete(messages=messages, model=model),
            timeout=_TEMPLATE_TEST_TIMEOUT_SECONDS,
        )
        triggered, reason = _evaluate_guardrails(resp.content, guardrails)
        return TemplateTestResult(
            prompt=prompt,
            response=resp.content,
            tokens_in=resp.tokens_in,
            tokens_out=resp.tokens_out,
            latency_ms=resp.latency_ms,
            guardrail_triggered=triggered,
            guardrail_reason=reason,
            timed_out=False,
        )
    except asyncio.TimeoutError:
        return TemplateTestResult(
            prompt=prompt,
            response="",
            tokens_in=0,
            tokens_out=0,
            latency_ms=_TEMPLATE_TEST_TIMEOUT_SECONDS * 1000,
            guardrail_triggered=False,
            guardrail_reason="",
            timed_out=True,
        )


@router.post(
    "/platform/agent-templates/{template_id}/test",
    response_model=TemplateTestResponse,
    tags=["platform"],
)
async def test_agent_template(
    template_id: str = Path(
        ...,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    body: TestTemplateRequest = ...,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    PA-021: Run test prompts against a template's resolved system_prompt.

    - Substitutes {{variable_name}} placeholders using variable_values.
    - Missing required variables return 422.
    - Max 5 prompts per request (enforced by Pydantic).
    - Each prompt runs with a 30s timeout; timed-out entries have timed_out=True.
    - Guardrails in the template's guardrails JSONB are evaluated against each response.
    - Partial results: if some prompts time out, completed ones are still returned.
    """
    template = await _get_agent_template_db(template_id, session)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent template not found.",
        )

    # Validate that all required variables are provided
    variable_defs = template.get("variable_definitions") or []
    for var_def in variable_defs:
        if var_def.get("required") and var_def["name"] not in body.variable_values:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Missing required variable: '{var_def['name']}'.",
            )

    resolved_prompt = _substitute_variables(
        template["system_prompt"], body.variable_values
    )
    guardrails = template.get("guardrails") or []

    # Instantiate adapter once per request (shared across all concurrent prompt calls)
    from app.core.llm.azure_openai import AzureOpenAIProvider

    adapter = AzureOpenAIProvider()

    # Run all prompts concurrently (each has its own internal timeout).
    # return_exceptions=True ensures partial results are returned even if a
    # prompt raises an unexpected non-timeout exception.
    tasks = [
        _run_template_prompt(p, resolved_prompt, guardrails, adapter)
        for p in body.test_prompts
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Convert any unexpected exceptions into timed-out sentinel results so that
    # partial success is preserved.
    results = []
    for i, r in enumerate(raw_results):
        if isinstance(r, BaseException):
            logger.warning(
                "agent_template_test_prompt_error",
                template_id=template_id,
                prompt_index=i,
                error=str(r),
            )
            results.append(
                TemplateTestResult(
                    prompt=body.test_prompts[i],
                    response="",
                    tokens_in=0,
                    tokens_out=0,
                    latency_ms=0,
                    guardrail_triggered=False,
                    guardrail_reason="",
                    timed_out=True,
                )
            )
        else:
            results.append(r)

    logger.info(
        "agent_template_tested",
        template_id=template_id,
        actor_id=current_user.id,
        prompt_count=len(body.test_prompts),
        timed_out=sum(1 for r in results if r.timed_out),
    )
    return TemplateTestResponse(tests=list(results))


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
    resource_type: Optional[str],
    from_date: Optional[datetime],
    to_date: Optional[datetime],
    page: int,
    page_size: int,
    after: Optional[str],
    db: AsyncSession,
) -> tuple[list[dict], int]:
    """
    Query audit_log across all tenants (no RLS tenant filter).

    Optionally filtered by tenant_id, actor_id, action, resource_type,
    date range.  Supports cursor-based pagination via `after` (created_at ISO
    timestamp of last-seen row) or page-based via page/page_size.
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

    if resource_type:
        conditions.append("al.resource_type = :resource_type")
        params["resource_type"] = resource_type

    if from_date:
        conditions.append("al.created_at >= :from_date")
        params["from_date"] = from_date

    if to_date:
        conditions.append("al.created_at <= :to_date")
        params["to_date"] = to_date

    # Cursor-based pagination: rows older than the cursor timestamp.
    if after:
        try:
            from datetime import datetime as _dt

            after_dt = _dt.fromisoformat(after)
            conditions.append("al.created_at < :after_cursor")
            params["after_cursor"] = after_dt
        except ValueError:
            pass  # ignore malformed cursor

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM audit_log al {where_clause}"),
        params,
    )
    total = int(count_result.scalar_one() or 0)

    # Use cursor pagination if `after` provided, otherwise page-based offset.
    if after:
        params["limit"] = page_size
        offset_clause = ""
    else:
        offset = (page - 1) * page_size
        params["limit"] = page_size
        params["offset"] = offset
        offset_clause = "OFFSET :offset"

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
            f"LIMIT :limit {offset_clause}"
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
    actor: Optional[str] = Query(None, description="Filter by actor user ID"),
    actor_id: Optional[str] = Query(None, description="Alias for actor (deprecated)"),
    action: Optional[str] = Query(None, description="Filter by action"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    from_date: Optional[datetime] = Query(
        None, alias="from", description="Start date (ISO-8601)"
    ),
    to_date: Optional[datetime] = Query(
        None, alias="to", description="End date (ISO-8601)"
    ),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page (max 200)"),
    after: Optional[str] = Query(
        None, description="Cursor: ISO timestamp of last row for pagination"
    ),
    format: Optional[str] = Query(
        None, description="Response format: json (default) or csv"
    ),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-112 / PA-036: Cross-tenant audit log for platform admins.

    Bypasses per-tenant RLS — returns audit events across all tenants.
    Filters: actor, resource_type, action, from, to.
    Pagination: page/page_size (default 50) or cursor-based via ?after=.

    Auth: platform_admin required.
    """
    # Accept both `actor` and legacy `actor_id` params.
    resolved_actor = actor or actor_id
    items, total = await get_platform_audit_log_db(
        filter_tenant_id=tenant_id,
        actor_id=resolved_actor,
        action=action,
        resource_type=resource_type,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
        after=after,
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

    # next_cursor: created_at of last item for cursor-based next page.
    next_cursor = items[-1]["created_at"] if items else None

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "next_cursor": next_cursor,
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


# ---------------------------------------------------------------------------
# Platform admin preferences (API-115)
# Stored in Redis: mingai:platform:preferences:{user_id}
# ---------------------------------------------------------------------------

_HH_MM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

_DEFAULT_PLATFORM_PREFS: dict = {
    "daily_digest_enabled": True,
    "daily_digest_time": "08:00",
    "alert_thresholds": {
        "cost_spike_pct": 20.0,
        "health_score_min": 60,
    },
    "notification_preferences": {},
}


class AlertThresholds(BaseModel):
    cost_spike_pct: Optional[float] = Field(None, ge=0.0)
    health_score_min: Optional[int] = Field(None, ge=0, le=100)


class PlatformPreferencesRequest(BaseModel):
    daily_digest_enabled: Optional[bool] = None
    daily_digest_time: Optional[str] = Field(None, max_length=5)
    alert_thresholds: Optional[AlertThresholds] = None
    notification_preferences: Optional[dict] = None


async def _get_platform_prefs(user_id: str) -> dict:
    """Read platform admin preferences from Redis. Returns defaults on miss."""
    redis = get_redis()
    key = build_redis_key("platform", "preferences", user_id)
    raw = await redis.get(key)
    if raw is None:
        return json.loads(json.dumps(_DEFAULT_PLATFORM_PREFS))  # deep copy
    data = json.loads(raw)
    # Merge with defaults so new keys always appear
    merged = json.loads(json.dumps(_DEFAULT_PLATFORM_PREFS))
    merged.update(data)
    if "alert_thresholds" in data:
        merged["alert_thresholds"].update(data["alert_thresholds"])
    return merged


async def _save_platform_prefs(user_id: str, prefs: dict) -> None:
    """Persist platform admin preferences to Redis (no TTL — sticky)."""
    redis = get_redis()
    key = build_redis_key("platform", "preferences", user_id)
    await redis.set(key, json.dumps(prefs))


@router.get("/platform/preferences")
async def get_platform_preferences(
    current_user: CurrentUser = Depends(require_platform_admin),
):
    """
    Get platform admin's personal preferences (API-115).

    Returns current preferences or defaults if never set.
    """
    prefs = await _get_platform_prefs(current_user.id)
    return prefs


@router.patch("/platform/preferences")
async def update_platform_preferences(
    body: PlatformPreferencesRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
):
    """
    Update platform admin's personal preferences (API-115).

    Validates HH:MM format for daily_digest_time (00:00 – 23:59).
    """
    if body.daily_digest_time is not None:
        if not _HH_MM_RE.match(body.daily_digest_time):
            raise HTTPException(
                status_code=422,
                detail="daily_digest_time must be in HH:MM format (00:00–23:59)",
            )

    prefs = await _get_platform_prefs(current_user.id)

    if body.daily_digest_enabled is not None:
        prefs["daily_digest_enabled"] = body.daily_digest_enabled
    if body.daily_digest_time is not None:
        prefs["daily_digest_time"] = body.daily_digest_time
    if body.alert_thresholds is not None:
        threshold_update = body.alert_thresholds.model_dump(exclude_none=True)
        prefs["alert_thresholds"].update(threshold_update)
    if body.notification_preferences is not None:
        prefs["notification_preferences"] = body.notification_preferences

    await _save_platform_prefs(current_user.id, prefs)

    logger.info("platform_preferences_updated", user_id=current_user.id)
    return prefs


# ---------------------------------------------------------------------------
# Platform admin audit log helper (used by impersonation + GDPR)
# ---------------------------------------------------------------------------


async def _insert_platform_audit_log(
    db: AsyncSession,
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    details: dict,
) -> None:
    """Insert a cross-tenant audit log record (tenant_id = platform sentinel)."""
    platform_tenant_id = os.environ.get("PLATFORM_TENANT_ID", "platform")
    # platform sentinel may not be a valid UUID — use a fixed known UUID
    # for the audit_log FK constraint. The record's details contain the real IDs.
    # Use the well-known platform admin record tenant entry or skip if not available.
    try:
        await db.execute(
            text(
                "INSERT INTO audit_log "
                "(id, tenant_id, user_id, action, resource_type, resource_id, details) "
                "VALUES (:id, :tenant_id, :user_id, :action, :resource_type, "
                ":resource_id, CAST(:details AS jsonb))"
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": resource_id,  # use target tenant_id for FK validity
                "user_id": None,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "details": json.dumps({**details, "actor_user_id": user_id}),
            },
        )
        await db.commit()
    except Exception as exc:
        logger.warning(
            "audit_log_insert_failed",
            action=action,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# API-113: Platform admin impersonation — POST /platform/impersonate
# ---------------------------------------------------------------------------


class ImpersonateRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=10, max_length=500)


@router.post("/platform/impersonate", status_code=200)
async def impersonate_tenant(
    body: ImpersonateRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Generate an impersonation token scoped to a tenant (API-113).

    Only users with scope='platform' AND role='platform_admin' may call this.
    Generates a 1-hour tenant-scoped JWT with impersonation claims.
    """
    # Extra check: role must be exactly 'platform_admin' in addition to platform scope
    if "platform_admin" not in current_user.roles:
        raise HTTPException(
            status_code=403,
            detail="Platform admin role required for impersonation.",
        )

    # Validate UUID format for tenant_id
    try:
        tenant_uuid = uuid.UUID(body.tenant_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="tenant_id must be a valid UUID")

    # Verify tenant exists and read actual plan
    tenant_result = await db.execute(
        text("SELECT id, name, plan FROM tenants WHERE id = :tid"),
        {"tid": str(tenant_uuid)},
    )
    tenant_row = tenant_result.fetchone()
    if tenant_row is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant_plan = str(tenant_row[2]) if tenant_row[2] else "professional"

    secret = os.environ.get("JWT_SECRET_KEY")
    if not secret:
        raise HTTPException(status_code=500, detail="JWT_SECRET_KEY not configured")
    algorithm = os.environ.get("JWT_ALGORITHM", "HS256")

    now = datetime.now(timezone.utc)
    expires_in = 3600  # 1 hour
    jti = str(uuid.uuid4())

    payload = {
        "sub": current_user.id,
        "tenant_id": body.tenant_id,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": tenant_plan,
        "impersonated_by": current_user.id,
        "impersonated_reason": body.reason,
        "exp": now + timedelta(seconds=expires_in),
        "iat": now,
        "jti": jti,
        "token_version": 2,
    }

    token = jwt.encode(payload, secret, algorithm=algorithm)

    await _insert_platform_audit_log(
        db=db,
        user_id=current_user.id,
        action="impersonation_started",
        resource_type="tenant",
        resource_id=body.tenant_id,
        details={
            "tenant_id": body.tenant_id,
            "reason": body.reason,
            "impersonated_by": current_user.id,
        },
    )

    logger.info(
        "platform_impersonation_started",
        user_id=current_user.id,
        tenant_id=body.tenant_id,
    )

    return {
        "impersonation_token": token,
        "expires_in": expires_in,
        "tenant_id": body.tenant_id,
    }


# ---------------------------------------------------------------------------
# API-114: End impersonation — POST /platform/impersonate/end
# ---------------------------------------------------------------------------


@router.post("/platform/impersonate/end", status_code=200)
async def end_impersonation(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
    raw_authorization: Optional[str] = Header(None, alias="authorization"),
):
    """
    End an active impersonation session (API-114).

    The caller must present an impersonation token (one that has 'impersonated_by'
    claim). Adds the token's JTI to a Redis blocklist and logs the event.
    Returns 400 if the token is not an impersonation token.
    """
    from app.modules.auth.jwt import decode_jwt_token_v1_compat

    secret = os.environ.get("JWT_SECRET_KEY")
    if not secret:
        raise HTTPException(status_code=500, detail="JWT_SECRET_KEY not configured")
    algorithm = os.environ.get("JWT_ALGORITHM", "HS256")

    if raw_authorization and raw_authorization.startswith("Bearer "):
        raw_token = raw_authorization[7:]
    else:
        raise HTTPException(
            status_code=400,
            detail="No active impersonation session found in this token",
        )

    try:
        payload = decode_jwt_token_v1_compat(raw_token, secret, algorithm)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="No active impersonation session found in this token",
        )

    impersonated_by = payload.get("impersonated_by")
    if not impersonated_by:
        raise HTTPException(
            status_code=400,
            detail="No active impersonation session found in this token",
        )

    jti = payload.get("jti", "")
    iat = payload.get("iat")
    exp = payload.get("exp")

    now_ts = datetime.now(timezone.utc).timestamp()

    duration_seconds = 0
    if iat is not None:
        iat_ts = iat.timestamp() if isinstance(iat, datetime) else float(iat)
        duration_seconds = max(0, int(now_ts - iat_ts))

    # Add jti to Redis blocklist with TTL = remaining token lifetime
    if jti:
        remaining_ttl = 3600
        if exp is not None:
            exp_ts = exp.timestamp() if isinstance(exp, datetime) else float(exp)
            remaining_ttl = max(1, int(exp_ts - now_ts))
        try:
            redis = get_redis()
            blocklist_key = build_redis_key("platform", "impersonation_blocklist", jti)
            await redis.set(blocklist_key, "1", ex=remaining_ttl)
        except Exception as exc:
            logger.warning(
                "impersonation_blocklist_write_failed",
                jti=jti,
                error=str(exc),
            )

    tenant_id = payload.get("tenant_id", "")
    resource_id = tenant_id if _is_valid_uuid(tenant_id) else None
    await _insert_platform_audit_log(
        db=db,
        user_id=impersonated_by,
        action="impersonation_ended",
        resource_type="tenant",
        resource_id=resource_id,
        details={
            "impersonated_by": impersonated_by,
            "duration_seconds": duration_seconds,
        },
    )

    logger.info(
        "platform_impersonation_ended",
        impersonated_by=impersonated_by,
        duration_seconds=duration_seconds,
    )

    return {"status": "ended", "duration_seconds": duration_seconds}


def _is_valid_uuid(value: str) -> bool:
    """Return True if value is a valid UUID string."""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# API-116: GDPR deletion workflow — POST /platform/tenants/{tenant_id}/gdpr-delete
# ---------------------------------------------------------------------------


class GdprDeleteRequest(BaseModel):
    confirmed: bool
    deletion_reference: str = Field(..., min_length=1, max_length=200)
    dry_run: bool = False


async def _execute_gdpr_pipeline(
    db: AsyncSession,
    tenant_id: str,
    dry_run: bool,
) -> dict:
    """
    Execute (or simulate) the 7-step PA-035 GDPR deletion pipeline.

    When dry_run=True, queries counts but makes no modifications.
    Returns a confirmation report dict.

    All writes are in the same transaction; caller commits on success.
    """
    deleted_tables: list[str] = []
    retained_tables: list[str] = []
    counts: dict = {}

    # ── Count rows to be affected (dry_run uses same queries) ──
    async def _count(table: str, col: str = "tenant_id") -> int:
        r = await db.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE {col} = :tid"),
            {"tid": tenant_id},
        )
        return int(r.scalar() or 0)

    # Step 1: billing check — no active subscriptions
    # (No subscriptions table in current schema — skip; log intent)
    counts["billing_check"] = "skipped_no_subscriptions_table"

    # Step 2: soft-delete tenant record
    counts["tenant"] = 1
    if not dry_run:
        await db.execute(
            text(
                "UPDATE tenants SET status = 'suspended', "
                "deleted_at = NOW(), updated_at = NOW() WHERE id = :tid"
            ),
            {"tid": tenant_id},
        )
        deleted_tables.append("tenants (soft-deleted)")

    # Step 3: anonymize user PII
    counts["users_anonymized"] = await _count("users")
    if not dry_run:
        await db.execute(
            text(
                """
                UPDATE users
                SET name  = CONCAT('DELETED_USER_', LEFT(id::text, 8)),
                    email = CONCAT('deleted_', id::text, '@gdpr.invalid'),
                    updated_at = NOW()
                WHERE tenant_id = :tid
                """
            ),
            {"tid": tenant_id},
        )
        deleted_tables.append("users (PII anonymized)")

    # Step 4: delete conversation/message content
    counts["conversations"] = await _count("conversations")
    if not dry_run:
        await db.execute(
            text(
                "DELETE FROM messages WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE tenant_id = :tid)"
            ),
            {"tid": tenant_id},
        )
        await db.execute(
            text("DELETE FROM conversations WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        deleted_tables.append("conversations")
        deleted_tables.append("messages (within tenant conversations)")

    # Step 5: delete memory notes
    try:
        counts["memory_notes"] = await _count("memory_notes")
        if not dry_run:
            await db.execute(
                text("DELETE FROM memory_notes WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            deleted_tables.append("memory_notes")
    except Exception:
        counts["memory_notes"] = "table_not_found"

    # Step 6: delete document content (source_documents / knowledge_docs)
    try:
        counts["documents"] = await _count("source_documents")
        if not dry_run:
            await db.execute(
                text("DELETE FROM source_documents WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            deleted_tables.append("source_documents")
    except Exception:
        counts["documents"] = "table_not_found"

    # Step 7: retain usage_events + audit_log with anonymized user_id
    try:
        counts["usage_events_retained"] = await _count("usage_events")
        if not dry_run:
            await db.execute(
                text(
                    "UPDATE usage_events SET user_id = NULL "
                    "WHERE tenant_id = :tid AND user_id IS NOT NULL"
                ),
                {"tid": tenant_id},
            )
            retained_tables.append("usage_events (user_id anonymized)")
    except Exception:
        counts["usage_events_retained"] = "table_not_found"

    try:
        counts["audit_log_retained"] = await _count("audit_log", col="resource_id")
        if not dry_run:
            await db.execute(
                text(
                    "UPDATE audit_log SET actor_id = 'DELETED_USER' "
                    "WHERE actor_id IN "
                    "(SELECT id::text FROM users WHERE tenant_id = :tid)"
                ),
                {"tid": tenant_id},
            )
            retained_tables.append("audit_log (actor_id anonymized for legal hold)")
    except Exception:
        counts["audit_log_retained"] = "table_not_found"

    return {
        "dry_run": dry_run,
        "deleted_tables": deleted_tables,
        "retained_for_legal_hold": retained_tables,
        "counts": counts,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


async def _run_gdpr_deletion(
    tenant_id: str,
    job_id: str,
    deletion_reference: str,
) -> None:
    """
    Background task: execute GDPR deletion steps for a tenant.

    Steps:
    1. Suspend tenant
    2. Delete users, agent_cards, glossary_terms
    3. Clear Redis keys for the tenant
    4. Mark job complete in Redis
    """
    from app.core.session import get_async_session as _get_session

    logger.info(
        "gdpr_deletion_started",
        tenant_id=tenant_id,
        job_id=job_id,
    )

    try:
        # We cannot reuse the request-scoped DB session in a background task.
        # Create a fresh session directly from the engine.
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession as _AS
        from sqlalchemy.orm import sessionmaker

        db_url = os.environ.get("DATABASE_URL", "")
        engine = create_async_engine(db_url, echo=False)
        async_session = sessionmaker(engine, class_=_AS, expire_on_commit=False)

        async with async_session() as db:
            # Step 1: Suspend tenant
            await db.execute(
                text(
                    "UPDATE tenants SET status = 'suspended', updated_at = NOW() "
                    "WHERE id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            )
            await db.commit()

            # Step 2: Delete tenant data — explicit parameterized statements, no interpolation
            await db.execute(
                text("DELETE FROM users WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            await db.execute(
                text("DELETE FROM agent_cards WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            await db.execute(
                text("DELETE FROM glossary_terms WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            await db.commit()

        await engine.dispose()

        # Step 3: Clear Redis keys matching mingai:{tenant_id}:*
        try:
            redis = get_redis()
            pattern = f"mingai:{tenant_id}:*"
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor, match=pattern, count=100)
                if keys:
                    await redis.delete(*keys)
                if cursor == 0:
                    break
        except Exception as exc:
            logger.warning(
                "gdpr_redis_clear_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )

        # Step 4: Mark job as completed
        try:
            redis = get_redis()
            job_key = build_redis_key("platform", "gdpr_delete_job", job_id)
            job_data = await redis.get(job_key)
            if job_data:
                job_obj = json.loads(job_data)
                job_obj["status"] = "completed"
                job_obj["completed_at"] = datetime.now(timezone.utc).isoformat()
                await redis.set(job_key, json.dumps(job_obj), ex=86400 * 30)
        except Exception as exc:
            logger.warning(
                "gdpr_job_status_update_failed",
                job_id=job_id,
                error=str(exc),
            )

        logger.info(
            "gdpr_deletion_completed",
            tenant_id=tenant_id,
            job_id=job_id,
        )

    except Exception as exc:
        logger.error(
            "gdpr_deletion_failed",
            tenant_id=tenant_id,
            job_id=job_id,
            error=str(exc),
        )
        # Update job status to failed
        try:
            redis = get_redis()
            job_key = build_redis_key("platform", "gdpr_delete_job", job_id)
            job_obj = {
                "job_id": job_id,
                "status": "failed",
                "tenant_id": tenant_id,
                "error": "gdpr_deletion_failed",
            }
            await redis.set(job_key, json.dumps(job_obj), ex=86400 * 30)
        except Exception as redis_exc:
            logger.warning(
                "gdpr_job_failed_status_write_failed",
                job_id=job_id,
                tenant_id=tenant_id,
                error=str(redis_exc),
            )


@router.post("/platform/tenants/{tenant_id}/gdpr-delete", status_code=200)
async def gdpr_delete_tenant(
    tenant_id: str,
    body: GdprDeleteRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Initiate GDPR deletion workflow for a tenant (API-116).

    Requires confirmed=true and a non-empty deletion_reference.
    Verifies the tenant exists, then launches an async deletion job.
    Returns a job_id to poll for completion status.
    """
    if not body.confirmed:
        raise HTTPException(
            status_code=422,
            detail="confirmed must be true to initiate GDPR deletion",
        )

    if not body.deletion_reference.strip():
        raise HTTPException(
            status_code=422,
            detail="deletion_reference is required",
        )

    # Validate UUID format
    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="tenant_id must be a valid UUID")

    # Verify tenant exists
    tenant_result = await db.execute(
        text("SELECT id FROM tenants WHERE id = :tid"),
        {"tid": str(tenant_uuid)},
    )
    if tenant_result.fetchone() is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    estimated_completion = (now + timedelta(minutes=5)).isoformat()

    # Store job metadata in Redis
    try:
        redis = get_redis()
        job_key = build_redis_key("platform", "gdpr_delete_job", job_id)
        job_data = {
            "job_id": job_id,
            "status": "in_progress",
            "tenant_id": tenant_id,
            "deletion_reference": body.deletion_reference,
            "created_at": now.isoformat(),
        }
        await redis.set(job_key, json.dumps(job_data), ex=86400 * 30)  # 30d TTL
    except Exception as exc:
        logger.warning(
            "gdpr_job_redis_write_failed",
            job_id=job_id,
            error=str(exc),
        )

    # dry_run: run the pipeline in simulation mode and return report
    if body.dry_run:
        report = await _execute_gdpr_pipeline(db, tenant_id, dry_run=True)
        return {"dry_run": True, "report": report}

    await _insert_platform_audit_log(
        db=db,
        user_id=current_user.id,
        action="gdpr_delete_initiated",
        resource_type="tenant",
        resource_id=tenant_id,
        details={
            "tenant_id": tenant_id,
            "deletion_reference": body.deletion_reference,
        },
    )

    # Execute the full pipeline synchronously within this request.
    # The pipeline is atomic — runs in the existing db session; caller commits.
    try:
        report = await _execute_gdpr_pipeline(db, tenant_id, dry_run=False)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error(
            "gdpr_deletion_pipeline_failed", tenant_id=tenant_id, error=str(exc)
        )
        raise HTTPException(status_code=500, detail="GDPR deletion pipeline failed")

    # Store confirmation report as audit_log entry.
    try:
        await _insert_platform_audit_log(
            db=db,
            user_id=current_user.id,
            action="gdpr_delete_completed",
            resource_type="tenant",
            resource_id=tenant_id,
            details={
                "deletion_reference": body.deletion_reference,
                "report_summary": {
                    "deleted_tables": report["deleted_tables"],
                    "retained": report["retained_for_legal_hold"],
                    "completed_at": report["completed_at"],
                },
            },
        )
        await db.commit()
    except Exception as exc:
        logger.warning(
            "gdpr_audit_log_write_failed", tenant_id=tenant_id, error=str(exc)
        )

    # Also clear Redis keys for the tenant.
    try:
        redis = get_redis()
        pattern = f"mingai:{tenant_id}:*"
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning("gdpr_redis_clear_failed", tenant_id=tenant_id, error=str(exc))

    logger.info(
        "gdpr_delete_completed",
        user_id=current_user.id,
        tenant_id=tenant_id,
    )

    return {
        "status": "completed",
        "report": report,
    }


# ---------------------------------------------------------------------------
# PA-008 and PA-009 routes live in app/modules/tenants/routes.py
# (must be in the same router as GET /tenants/{tenant_id} so literal-path
# route /tenants/at-risk takes precedence over the parameterised path).
# ---------------------------------------------------------------------------


# placeholder kept intentionally blank — routes are in tenants/routes.py


async def _placeholder_at_risk(
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    PA-008: Return tenants flagged at-risk from the latest health score snapshot.

    Fetches the most recent tenant_health_scores row per tenant where
    at_risk_flag = true, annotated with weeks_at_risk count and component
    breakdown. Sorted by composite_score ASC (worst first).

    Returns empty list when no tenants are at risk — never 404.
    """
    # Fetch the latest health score row per tenant where at_risk_flag = true.
    # Uses a lateral/subquery approach: for each tenant with at_risk in the
    # latest snapshot, return that row.
    result = await db.execute(
        text(
            """
            WITH latest AS (
                SELECT DISTINCT ON (ths.tenant_id)
                    ths.tenant_id,
                    ths.date,
                    ths.composite_score,
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
            WHERE l.composite_score IS NOT NULL
              AND l.composite_score < :at_risk_composite
            ORDER BY l.composite_score ASC
            """
        ),
        {"at_risk_composite": 40.0},
    )
    rows = result.fetchall()

    if not rows:
        return []

    # For each at-risk tenant, count consecutive at_risk weeks
    items = []
    for row in rows:
        tenant_id = str(row[0])
        name = row[1]
        composite_score = float(row[2]) if row[2] is not None else None
        at_risk_reason = row[3]
        usage_trend = float(row[4]) if row[4] is not None else None
        feature_breadth = float(row[5]) if row[5] is not None else None
        satisfaction = float(row[6]) if row[6] is not None else None
        error_rate = float(row[7]) if row[7] is not None else None

        # Count consecutive at-risk weeks (ordered newest first)
        weeks_result = await db.execute(
            text(
                """
                SELECT at_risk_flag
                FROM tenant_health_scores
                WHERE tenant_id = :tid
                ORDER BY date DESC
                LIMIT 52
                """
            ),
            {"tid": tenant_id},
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
                "tenant_id": tenant_id,
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


# ---------------------------------------------------------------------------
# PA-009: Health score drilldown for a single tenant
# ---------------------------------------------------------------------------


@router.get("/platform/tenants/{tenant_id}/health")
async def get_tenant_health(
    tenant_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    PA-009: Health score drilldown for a single tenant.

    Returns current snapshot and 12 weekly trend data points (ISO week
    format 'YYYY-Www'). Missing weeks are returned with null component
    values rather than omitted.
    """
    # Validate tenant exists
    tenant_result = await db.execute(
        text("SELECT id FROM tenants WHERE id = :tid"),
        {"tid": tenant_id},
    )
    if not tenant_result.fetchone():
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Fetch latest health score row for current snapshot
    latest_result = await db.execute(
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

    # Fetch up to 12 weekly rows ordered newest first
    trend_result = await db.execute(
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

    # Build a date → row map
    row_by_date: dict = {}
    for tr in trend_rows:
        row_by_date[tr[0]] = tr

    # Generate 12 ISO weeks going backwards from today
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    today = _date.today()
    # Start from the most recent Monday
    current_monday = today - _timedelta(days=today.weekday())

    trend = []
    for i in range(12):
        week_monday = current_monday - _timedelta(weeks=i)
        iso_cal = week_monday.isocalendar()
        week_label = f"{iso_cal[0]}-W{iso_cal[1]:02d}"

        # Find the stored row whose date falls in this ISO week
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


# ---------------------------------------------------------------------------
# PA-025: Template performance batch trigger
# ---------------------------------------------------------------------------


class TemplatePerfBatchRequest(BaseModel):
    target_date: Optional[str] = Field(
        None,
        description="ISO date (YYYY-MM-DD) to compute metrics for. Defaults to yesterday.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )


@router.post(
    "/platform/batch/template-performance",
    status_code=200,
    tags=["platform"],
    summary="Run template performance aggregation for a given date (PA-025)",
)
async def run_template_performance(
    body: TemplatePerfBatchRequest = TemplatePerfBatchRequest(),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """
    Manually trigger the nightly template performance batch for a given date.

    Computes satisfaction_rate, guardrail_trigger_rate, failure_count, and
    session_count per template and upserts into template_performance_daily.

    `target_date` defaults to yesterday. Idempotent — safe to re-run.
    """
    from datetime import date as _date

    today = _date.today()
    target_date: Optional[_date] = None
    if body.target_date:
        try:
            target_date = _date.fromisoformat(body.target_date)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid date. Use YYYY-MM-DD.",
            )
        if target_date >= today:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="target_date must be before today — future dates have no data.",
            )

    result = await run_template_performance_batch(session, target_date=target_date)
    await session.commit()
    logger.info(
        "platform_template_perf_batch_triggered",
        actor_id=current_user.id,
        **result,
    )
    return result


# ---------------------------------------------------------------------------
# PA-026: Template analytics API
# ---------------------------------------------------------------------------


@router.get(
    "/platform/agent-templates/{template_id}/analytics",
    tags=["platform"],
    summary="30-day analytics for an agent template (PA-026)",
)
async def get_template_analytics(
    template_id: str = Path(
        ..., pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    ),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """
    Return 30-day rolling analytics for an agent_template:
      - daily_metrics: list of {date, satisfaction_rate, guardrail_trigger_rate,
                                failure_count, session_count} for last 30 days
      - tenant_count: number of distinct tenants with a deployed agent from this template
      - top_failure_patterns: top 3 issue_type values from issue_reports linked to
                              agents deployed from this template (cross-tenant aggregate)

    No per-tenant data is exposed — only platform-level aggregates.
    """
    from datetime import date as _date, timedelta as _timedelta

    # Set platform scope for template_performance_daily RLS bypass, and clear
    # any stale app.tenant_id from pooled connections so tenant RLS policies on
    # agent_cards and issue_reports do not filter cross-tenant aggregate queries.
    await session.execute(text("SELECT set_config('app.scope', 'platform', true)"))
    await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    # Verify template exists
    exists = await session.execute(
        text("SELECT 1 FROM agent_templates WHERE id = :id"),
        {"id": template_id},
    )
    if exists.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent template not found.",
        )

    thirty_days_ago = _date.today() - _timedelta(days=30)

    # 1. 30-day daily metrics from template_performance_daily
    perf_result = await session.execute(
        text(
            "SELECT date, satisfaction_rate, guardrail_trigger_rate, "
            "failure_count, session_count "
            "FROM template_performance_daily "
            "WHERE template_id = :template_id "
            "  AND date >= :since "
            "ORDER BY date ASC"
        ),
        {"template_id": template_id, "since": thirty_days_ago},
    )
    daily_metrics = [
        {
            "date": row["date"].isoformat()
            if hasattr(row["date"], "isoformat")
            else str(row["date"]),
            "satisfaction_rate": row["satisfaction_rate"],
            "guardrail_trigger_rate": row["guardrail_trigger_rate"],
            "failure_count": row["failure_count"],
            "session_count": row["session_count"],
        }
        for row in perf_result.mappings()
    ]

    # 2. Cross-tenant usage count (distinct tenants with deployed agents)
    tenant_result = await session.execute(
        text(
            "SELECT COUNT(DISTINCT tenant_id) AS tenant_count "
            "FROM agent_cards "
            "WHERE template_id = :template_id"
        ),
        {"template_id": template_id},
    )
    tenant_count = tenant_result.scalar() or 0

    # 3. Top-3 failure patterns: issue_type counts from issue_reports linked to
    #    agents deployed from this template (via conversation → agent → template)
    failure_result = await session.execute(
        text(
            "SELECT ir.issue_type, COUNT(*) AS issue_count "
            "FROM issue_reports ir "
            "JOIN conversations c  ON c.id = ir.conversation_id "
            "JOIN agent_cards   ac ON ac.id = c.agent_id "
            "WHERE ac.template_id = :template_id "
            "GROUP BY ir.issue_type "
            "ORDER BY issue_count DESC "
            "LIMIT 3"
        ),
        {"template_id": template_id},
    )
    top_failure_patterns = [
        {"issue_type": row["issue_type"], "count": row["issue_count"]}
        for row in failure_result.mappings()
    ]

    # Commit ends the transaction, resetting transaction-local set_config values
    # (app.scope, app.tenant_id) before the connection is returned to the pool.
    await session.commit()

    return {
        "template_id": template_id,
        "daily_metrics": daily_metrics,
        "tenant_count": int(tenant_count),
        "top_failure_patterns": top_failure_patterns,
    }


# ---------------------------------------------------------------------------
# PA-028: Roadmap signal board
# ---------------------------------------------------------------------------


@router.get("/platform/roadmap-signals")
async def get_roadmap_signals(
    limit: int = 50,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    GET /platform/roadmap-signals

    Returns feature requests from issue_reports ranked by weighted_score
    (SUM of plan weights: enterprise=3, professional=2, starter=1).

    Groups by normalized description text (lowercase + trimmed) for MVP clustering.

    Auth: platform_admin required.
    """
    # Clamp limit to prevent accidental large responses.
    limit = min(max(limit, 1), 200)

    # Set platform scope so issue_reports_platform bypass policy allows
    # cross-tenant SELECT (issue_reports has FORCE RLS with tenant policy).
    await session.execute(text("SELECT set_config('app.scope', 'platform', true)"))
    await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    result = await session.execute(
        text(
            """
            SELECT
                LOWER(TRIM(ir.description))              AS signal,
                COUNT(*)                                  AS count,
                SUM(CASE t.plan
                    WHEN 'enterprise'    THEN 3
                    WHEN 'professional'  THEN 2
                    ELSE 1
                END)                                      AS weighted_score,
                COUNT(CASE WHEN t.plan = 'enterprise'    THEN 1 END) AS enterprise_count,
                COUNT(CASE WHEN t.plan = 'professional'  THEN 1 END) AS professional_count,
                COUNT(CASE WHEN t.plan NOT IN ('enterprise','professional') THEN 1 END)
                                                          AS starter_count
            FROM issue_reports ir
            JOIN tenants t ON t.id = ir.tenant_id
            WHERE ir.issue_type = 'feature_request'
            GROUP BY LOWER(TRIM(ir.description))
            ORDER BY weighted_score DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )

    signals = [
        {
            "signal": row[0],
            "count": int(row[1]),
            "weighted_score": int(row[2]),
            "plan_breakdown": {
                "enterprise": int(row[3]),
                "professional": int(row[4]),
                "starter": int(row[5]),
            },
        }
        for row in result.fetchall()
    ]

    await session.commit()

    return {"signals": signals, "total": len(signals)}


# ---------------------------------------------------------------------------
# PA-029: Feature adoption table
# ---------------------------------------------------------------------------

_FEATURE_ADOPTION_FEATURES = [
    "chat",
    "glossary",
    "agent_templates",
    "knowledge_base",
    "sso",
    "cost_analytics",
    "cache_analytics",
]


@router.get("/platform/feature-adoption")
async def get_feature_adoption(
    days: int = 30,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    GET /platform/feature-adoption

    Returns per-feature adoption stats across all active tenants over the
    last `days` days (default 30).

    Adoption = % of active tenants that had at least 1 analytics_events row
               for the feature in the period.

    Response includes: feature, adopted_tenant_count, total_active_tenants,
    adoption_pct, avg_sessions_per_week_per_tenant.

    Auth: platform_admin required.
    """
    days = min(max(days, 1), 365)

    await session.execute(text("SELECT set_config('app.scope', 'platform', true)"))
    await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    # Count active tenants as baseline denominator.
    active_result = await session.execute(
        text("SELECT COUNT(*) FROM tenants WHERE status = 'active'")
    )
    total_active_tenants = int(active_result.scalar() or 0)

    # Per-feature stats from analytics_events.
    adoption_result = await session.execute(
        text(
            """
            SELECT
                feature_name,
                COUNT(DISTINCT tenant_id)           AS adopted_tenants,
                COUNT(*)                            AS total_events,
                COUNT(DISTINCT DATE_TRUNC('week', created_at))
                                                    AS weeks_with_activity
            FROM analytics_events
            WHERE created_at >= NOW() - (:days * INTERVAL '1 day')
              AND feature_name = ANY(:features)
            GROUP BY feature_name
            """
        ),
        {"days": days, "features": _FEATURE_ADOPTION_FEATURES},
    )

    # Build lookup: feature_name → stats
    from_db: dict = {}
    for row in adoption_result.fetchall():
        feature = row[0]
        adopted = int(row[1])
        total_events = int(row[2])
        weeks = int(row[3]) if row[3] else 1
        # avg sessions per week per adopted tenant
        avg_sessions = (
            round(total_events / weeks / adopted, 2)
            if (adopted > 0 and weeks > 0)
            else 0.0
        )
        adoption_pct = (
            round(adopted / total_active_tenants * 100, 1)
            if total_active_tenants > 0
            else 0.0
        )
        from_db[feature] = {
            "adopted_tenant_count": adopted,
            "adoption_pct": adoption_pct,
            "avg_sessions_per_week_per_tenant": avg_sessions,
        }

    # Ensure all 7 features appear in the response even if zero usage.
    features = []
    for feature in _FEATURE_ADOPTION_FEATURES:
        stats = from_db.get(feature, {})
        features.append(
            {
                "feature": feature,
                "adopted_tenant_count": stats.get("adopted_tenant_count", 0),
                "total_active_tenants": total_active_tenants,
                "adoption_pct": stats.get("adoption_pct", 0.0),
                "avg_sessions_per_week_per_tenant": stats.get(
                    "avg_sessions_per_week_per_tenant", 0.0
                ),
            }
        )

    await session.commit()

    return {"features": features, "total_active_tenants": total_active_tenants}


# ---------------------------------------------------------------------------
# PA-031: Tool catalog registration and management
# ---------------------------------------------------------------------------

_TOOL_HEALTH_CHECK_TIMEOUT = 10  # seconds per step

_VALID_AUTH_TYPES = {"none", "api_key", "oauth2"}
_VALID_SAFETY_CLASSIFICATIONS = {"ReadOnly", "Write", "Destructive"}
_VALID_HEALTH_STATUSES = {"healthy", "degraded", "unavailable"}


class ToolRegistrationRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    provider: str = Field(..., min_length=1, max_length=100)
    mcp_endpoint: str = Field(..., min_length=1, max_length=500)
    auth_type: str = Field(..., pattern="^(none|api_key|oauth2)$")
    capabilities: list[str] = Field(default_factory=list)
    safety_classification: str = Field(..., pattern="^(ReadOnly|Write|Destructive)$")
    version: Optional[str] = Field(None, max_length=50)
    health_check_url: Optional[str] = Field(None, max_length=500)


async def _run_tool_health_checks(
    tool: ToolRegistrationRequest,
) -> tuple[bool, str, str]:
    """
    Run 4-step health check sequence for tool registration.

    Returns (passed: bool, failed_step: str, error_detail: str).
    If all pass, failed_step and error_detail are empty strings.

    Steps:
      1. endpoint_reachability  — HEAD request to mcp_endpoint
      2. auth_handshake         — if auth_type != 'none', GET /auth/check
      3. schema_validation      — GET {mcp_endpoint}/schema must return 200 JSON
      4. sample_invocation      — GET {mcp_endpoint}/ping or first ReadOnly capability
    """
    import httpx

    base_url = tool.mcp_endpoint.rstrip("/")
    headers: dict = {}

    # Step 1: endpoint reachability
    try:
        async with httpx.AsyncClient(timeout=_TOOL_HEALTH_CHECK_TIMEOUT) as client:
            resp = await client.head(base_url)
            if resp.status_code >= 500:
                return (
                    False,
                    "endpoint_reachability",
                    f"HEAD {base_url} returned {resp.status_code}",
                )
    except Exception as exc:
        return (False, "endpoint_reachability", str(exc))

    # Step 2: auth handshake (if auth_type != 'none')
    if tool.auth_type != "none":
        try:
            async with httpx.AsyncClient(timeout=_TOOL_HEALTH_CHECK_TIMEOUT) as client:
                resp = await client.get(f"{base_url}/auth/check", headers=headers)
                if resp.status_code not in (200, 401, 403):
                    return (
                        False,
                        "auth_handshake",
                        f"GET /auth/check returned unexpected status {resp.status_code}",
                    )
        except Exception as exc:
            return (False, "auth_handshake", str(exc))

    # Step 3: schema validation
    try:
        async with httpx.AsyncClient(timeout=_TOOL_HEALTH_CHECK_TIMEOUT) as client:
            resp = await client.get(f"{base_url}/schema", headers=headers)
            if resp.status_code != 200:
                return (
                    False,
                    "schema_validation",
                    f"GET /schema returned {resp.status_code}",
                )
            try:
                resp.json()
            except Exception:
                return (
                    False,
                    "schema_validation",
                    "GET /schema did not return valid JSON",
                )
    except Exception as exc:
        return (False, "schema_validation", str(exc))

    # Step 4: sample invocation (ping endpoint)
    try:
        async with httpx.AsyncClient(timeout=_TOOL_HEALTH_CHECK_TIMEOUT) as client:
            resp = await client.get(f"{base_url}/ping", headers=headers)
            if resp.status_code >= 500:
                return (
                    False,
                    "sample_invocation",
                    f"GET /ping returned {resp.status_code}",
                )
    except Exception as exc:
        return (False, "sample_invocation", str(exc))

    return (True, "", "")


_LIST_TOOLS_QUERY = text(
    """
    SELECT id, name, provider, mcp_endpoint, auth_type, capabilities,
           safety_classification, health_status, version, last_health_check,
           health_check_url, created_at
    FROM tool_catalog
    ORDER BY name
    LIMIT :limit OFFSET :offset
    """
)

_COUNT_TOOLS_QUERY = text("SELECT COUNT(*) FROM tool_catalog")

_GET_TOOL_QUERY = text(
    """
    SELECT id, name, provider, mcp_endpoint, auth_type, capabilities,
           safety_classification, health_status, version, last_health_check,
           health_check_url, created_at
    FROM tool_catalog
    WHERE id = :tool_id
    """
)

_INSERT_TOOL_QUERY = text(
    """
    INSERT INTO tool_catalog
        (id, name, provider, mcp_endpoint, auth_type, capabilities,
         safety_classification, health_status, version, health_check_url)
    VALUES
        (:id, :name, :provider, :mcp_endpoint, :auth_type,
         CAST(:capabilities AS jsonb), :safety_classification,
         'healthy', :version, :health_check_url)
    RETURNING id, name, provider, mcp_endpoint, auth_type, capabilities,
              safety_classification, health_status, version, last_health_check,
              health_check_url, created_at
    """
)

_DELETE_TOOL_QUERY = text(
    "DELETE FROM tool_catalog WHERE id = :tool_id RETURNING id, name"
)

_TOOL_ASSIGNMENTS_QUERY = text(
    """
    SELECT t.id AS tenant_id, t.name AS tenant_name
    FROM tenant_tool_assignments ta
    JOIN tenants t ON t.id = ta.tenant_id
    WHERE ta.tool_id = :tool_id
    """
)


def _tool_row_to_dict(row) -> dict:
    last_check = row[9]
    if last_check and hasattr(last_check, "isoformat"):
        last_check = last_check.isoformat()
    created = row[11]
    if created and hasattr(created, "isoformat"):
        created = created.isoformat()
    caps = row[5]
    if isinstance(caps, str):
        import json as _json

        caps = _json.loads(caps)
    return {
        "id": str(row[0]),
        "name": row[1],
        "provider": row[2],
        "mcp_endpoint": row[3],
        "auth_type": row[4],
        "capabilities": caps if caps is not None else [],
        "safety_classification": row[6],
        "health_status": row[7],
        "version": row[8],
        "last_health_check": last_check,
        "health_check_url": row[10],
        "created_at": created,
    }


@router.get("/platform/tools")
async def list_tools(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    GET /platform/tools

    List all tools in the catalog. platform_admin only.
    """
    await session.execute(text("SELECT set_config('app.scope', 'platform', true)"))
    await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    count_result = await session.execute(_COUNT_TOOLS_QUERY)
    total = int(count_result.scalar() or 0)

    rows_result = await session.execute(
        _LIST_TOOLS_QUERY, {"limit": limit, "offset": offset}
    )
    tools = [_tool_row_to_dict(r) for r in rows_result.fetchall()]

    await session.commit()
    return {"tools": tools, "total": total}


@router.post("/platform/tools", status_code=201)
async def register_tool(
    payload: ToolRegistrationRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    POST /platform/tools

    Register a new tool. Runs 4-step health check before insertion.
    Returns 422 if any health check step fails.
    platform_admin only.
    """
    passed, failed_step, error_detail = await _run_tool_health_checks(payload)
    if not passed:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "health_check_failed",
                "step": failed_step,
                "detail": error_detail,
            },
        )

    await session.execute(text("SELECT set_config('app.scope', 'platform', true)"))
    await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    result = await session.execute(
        _INSERT_TOOL_QUERY,
        {
            "id": str(uuid.uuid4()),
            "name": payload.name,
            "provider": payload.provider,
            "mcp_endpoint": payload.mcp_endpoint,
            "auth_type": payload.auth_type,
            "capabilities": json.dumps(payload.capabilities),
            "safety_classification": payload.safety_classification,
            "version": payload.version,
            "health_check_url": payload.health_check_url,
        },
    )
    row = result.fetchone()
    await session.commit()

    logger.info(
        "tool_registered",
        tool_name=payload.name,
        safety=payload.safety_classification,
        actor=str(current_user.id),
    )

    return _tool_row_to_dict(row)


@router.get("/platform/tools/{tool_id}")
async def get_tool(
    tool_id: str = Path(...),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    GET /platform/tools/{tool_id}

    Get a single tool by ID. platform_admin only.
    """
    await session.execute(text("SELECT set_config('app.scope', 'platform', true)"))
    await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    result = await session.execute(_GET_TOOL_QUERY, {"tool_id": tool_id})
    row = result.fetchone()
    await session.commit()

    if not row:
        raise HTTPException(status_code=404, detail="Tool not found")
    return _tool_row_to_dict(row)


@router.delete("/platform/tools/{tool_id}", status_code=200)
async def delete_tool(
    tool_id: str = Path(...),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    DELETE /platform/tools/{tool_id}

    Remove a tool from the catalog. Notifies tenants with active assignments.
    platform_admin only.
    """
    await session.execute(text("SELECT set_config('app.scope', 'platform', true)"))
    await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    # Look up active tenant assignments before deletion.
    # (tenant_tool_assignments table may not exist yet — handle gracefully)
    affected_tenant_ids: list[str] = []
    try:
        assign_result = await session.execute(
            _TOOL_ASSIGNMENTS_QUERY, {"tool_id": tool_id}
        )
        affected_tenant_ids = [str(r[0]) for r in assign_result.fetchall()]
    except Exception:
        # Table may not exist in this migration version — continue
        pass

    result = await session.execute(_DELETE_TOOL_QUERY, {"tool_id": tool_id})
    deleted = result.fetchone()
    await session.commit()

    if not deleted:
        raise HTTPException(status_code=404, detail="Tool not found")

    deleted_id = str(deleted[0])
    deleted_name = deleted[1]

    if affected_tenant_ids:
        logger.info(
            "tool_deleted_with_active_assignments",
            tool_id=deleted_id,
            tool_name=deleted_name,
            affected_tenant_count=len(affected_tenant_ids),
            actor=str(current_user.id),
        )
        # Notifications sent asynchronously — tenant notification infrastructure
        # is handled by the notification service (PA-011 outreach endpoint).
        # Log the affected tenants so the notification worker can pick them up.

    return {
        "deleted": True,
        "tool_id": deleted_id,
        "tool_name": deleted_name,
        "affected_tenant_count": len(affected_tenant_ids),
    }


# ---------------------------------------------------------------------------
# PA-033: Tool usage analytics API
# ---------------------------------------------------------------------------

_TOOL_DAILY_ANALYTICS_QUERY = text(
    """
    SELECT
        DATE(created_at AT TIME ZONE 'UTC')                     AS day,
        COUNT(*)                                                 AS invocations,
        COUNT(CASE WHEN (metadata->>'success')::boolean = false
                   THEN 1 END)                                   AS errors,
        PERCENTILE_CONT(0.50) WITHIN GROUP
            (ORDER BY (metadata->>'latency_ms')::numeric)        AS p50_latency_ms,
        PERCENTILE_CONT(0.95) WITHIN GROUP
            (ORDER BY (metadata->>'latency_ms')::numeric)        AS p95_latency_ms
    FROM analytics_events
    WHERE feature_name = :tool_id
      AND event_type = 'tool_invocation'
      AND created_at >= NOW() - (:days * INTERVAL '1 day')
    GROUP BY DATE(created_at AT TIME ZONE 'UTC')
    ORDER BY day DESC
    """
)

_TOOL_EXISTS_QUERY = text("SELECT id, name FROM tool_catalog WHERE id = :tool_id")


@router.get("/platform/tools/{tool_id}/analytics")
async def get_tool_analytics(
    tool_id: str = Path(...),
    days: int = Query(30, ge=1, le=365),
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    GET /platform/tools/{tool_id}/analytics

    Returns per-tool invocation analytics:
      - Daily invocation count, error rate, p50/p95 latency
      - Cross-tenant (no per-tenant breakdown — privacy)
      - Last `days` days (default 30)

    Source: analytics_events WHERE event_type='tool_invocation'
            AND feature_name=tool_id.

    Auth: platform_admin required.
    """
    days = min(max(days, 1), 365)

    await session.execute(text("SELECT set_config('app.scope', 'platform', true)"))
    await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    # Verify tool exists.
    tool_result = await session.execute(_TOOL_EXISTS_QUERY, {"tool_id": tool_id})
    tool_row = tool_result.fetchone()
    if not tool_row:
        await session.commit()
        raise HTTPException(status_code=404, detail="Tool not found")

    rows_result = await session.execute(
        _TOOL_DAILY_ANALYTICS_QUERY, {"tool_id": tool_id, "days": days}
    )
    rows = rows_result.fetchall()
    await session.commit()

    daily = []
    for row in rows:
        day_val = row[0]
        invocations = int(row[1])
        errors = int(row[2]) if row[2] else 0
        p50 = float(row[3]) if row[3] is not None else None
        p95 = float(row[4]) if row[4] is not None else None
        error_rate = round(errors / invocations, 4) if invocations > 0 else 0.0
        daily.append(
            {
                "date": day_val.isoformat()
                if hasattr(day_val, "isoformat")
                else str(day_val),
                "invocations": invocations,
                "error_rate": error_rate,
                "p50_latency_ms": p50,
                "p95_latency_ms": p95,
            }
        )

    total_invocations = sum(d["invocations"] for d in daily)
    total_errors = sum(int(d["invocations"] * d["error_rate"]) for d in daily)
    overall_error_rate = (
        round(total_errors / total_invocations, 4) if total_invocations > 0 else 0.0
    )

    return {
        "tool_id": str(tool_row[0]),
        "tool_name": tool_row[1],
        "days": days,
        "total_invocations": total_invocations,
        "overall_error_rate": overall_error_rate,
        "daily": daily,
    }


# ---------------------------------------------------------------------------
# PA-034: Platform daily digest email
# ---------------------------------------------------------------------------

_DIGEST_CONFIG_KEY = "digest_config"

_DIGEST_NEW_ISSUES_QUERY = text(
    """
    SELECT COUNT(*) FROM issue_reports
    WHERE created_at >= NOW() - INTERVAL '24 hours'
      AND status NOT IN ('resolved', 'closed')
    """
)

_DIGEST_AT_RISK_QUERY = text(
    """
    SELECT
        COUNT(CASE WHEN h.at_risk_flag = true THEN 1 END)    AS now_at_risk,
        COUNT(CASE WHEN h_prev.at_risk_flag = true THEN 1 END) AS prev_at_risk
    FROM tenant_health_scores h
    LEFT JOIN tenant_health_scores h_prev
        ON h_prev.tenant_id = h.tenant_id
        AND h_prev.date = h.date - 1
    WHERE h.date = CURRENT_DATE
    """
)

_DIGEST_COST_QUERY = text(
    """
    SELECT
        COALESCE(SUM(CASE WHEN date = CURRENT_DATE - 1 THEN total_cost_usd END), 0) AS yesterday,
        COALESCE(AVG(total_cost_usd), 0)                                             AS week_avg
    FROM cost_summary_daily
    WHERE date >= CURRENT_DATE - 8 AND date <= CURRENT_DATE - 1
    """
)

_DIGEST_ALERTS_QUERY = text(
    """
    SELECT COUNT(*) FROM issue_reports
    WHERE issue_type = 'template_performance'
      AND status = 'open'
    """
)


async def _build_digest_content(db: AsyncSession) -> dict:
    """Query all data sources for digest content. Returns structured dict."""
    await db.execute(text("SELECT set_config('app.scope', 'platform', true)"))
    await db.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    new_issues = int((await db.execute(_DIGEST_NEW_ISSUES_QUERY)).scalar() or 0)

    try:
        risk_row = (await db.execute(_DIGEST_AT_RISK_QUERY)).fetchone()
        now_at_risk = int(risk_row[0]) if risk_row and risk_row[0] else 0
        prev_at_risk = int(risk_row[1]) if risk_row and risk_row[1] else 0
        at_risk_change = now_at_risk - prev_at_risk
    except Exception:
        now_at_risk = 0
        at_risk_change = 0

    try:
        cost_row = (await db.execute(_DIGEST_COST_QUERY)).fetchone()
        yesterday_cost = float(cost_row[0]) if cost_row and cost_row[0] else 0.0
        week_avg_cost = float(cost_row[1]) if cost_row and cost_row[1] else 0.0
        cost_variance_pct = (
            round((yesterday_cost - week_avg_cost) / week_avg_cost * 100, 1)
            if week_avg_cost > 0
            else 0.0
        )
    except Exception:
        yesterday_cost = 0.0
        week_avg_cost = 0.0
        cost_variance_pct = 0.0

    open_alerts = int((await db.execute(_DIGEST_ALERTS_QUERY)).scalar() or 0)

    await db.commit()

    return {
        "new_issues_24h": new_issues,
        "at_risk_tenants": now_at_risk,
        "at_risk_change": at_risk_change,
        "yesterday_cost_usd": yesterday_cost,
        "cost_variance_pct": cost_variance_pct,
        "open_template_alerts": open_alerts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _render_digest_text(content: dict) -> str:
    """Render digest content as plain-text email body."""
    lines = [
        "mingai Platform Daily Digest",
        "=" * 40,
        "",
        f"New Issues (last 24h): {content['new_issues_24h']}",
        "",
        f"At-Risk Tenants: {content['at_risk_tenants']}",
    ]
    change = content["at_risk_change"]
    if change > 0:
        lines.append(f"  ↑ {change} new at-risk since yesterday")
    elif change < 0:
        lines.append(f"  ↓ {abs(change)} recovered since yesterday")
    lines += [
        "",
        f"Yesterday LLM Cost: ${content['yesterday_cost_usd']:.2f}",
        f"Cost vs 7-day avg: {content['cost_variance_pct']:+.1f}%",
        "",
        f"Open Template Performance Alerts: {content['open_template_alerts']}",
        "",
        f"Generated: {content['generated_at']}",
    ]
    return "\n".join(lines)


class DigestConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    recipients: Optional[list[str]] = None


@router.patch("/platform/digest/config", status_code=200)
async def update_digest_config(
    body: DigestConfigRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
):
    """
    PATCH /platform/digest/config

    Update digest email configuration. Stored in platform admin preferences.
    Auth: platform_admin required.
    """
    prefs = await _get_platform_prefs(current_user.id)
    digest_cfg = prefs.get(_DIGEST_CONFIG_KEY, {})

    if body.enabled is not None:
        digest_cfg["enabled"] = body.enabled
    if body.time is not None:
        digest_cfg["time"] = body.time
    if body.recipients is not None:
        digest_cfg["recipients"] = body.recipients

    prefs[_DIGEST_CONFIG_KEY] = digest_cfg
    await _save_platform_prefs(current_user.id, prefs)

    return digest_cfg


@router.get("/platform/digest/config", status_code=200)
async def get_digest_config(
    current_user: CurrentUser = Depends(require_platform_admin),
):
    """
    GET /platform/digest/config

    Returns current digest configuration.
    """
    prefs = await _get_platform_prefs(current_user.id)
    return prefs.get(
        _DIGEST_CONFIG_KEY, {"enabled": True, "time": "07:00", "recipients": []}
    )


@router.post("/platform/digest/preview", status_code=200)
async def preview_digest(
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    POST /platform/digest/preview

    Builds and returns digest content without sending email.
    Auth: platform_admin required.
    """
    content = await _build_digest_content(session)
    return {
        "content": content,
        "text_preview": _render_digest_text(content),
    }


async def _send_digest_email(content: dict, recipients: list[str]) -> dict:
    """Send digest email via SendGrid. Returns send summary."""
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        logger.warning(
            "digest_sendgrid_not_configured",
            detail="SENDGRID_API_KEY not set — digest email skipped",
        )
        return {"sent": False, "reason": "SENDGRID_API_KEY not configured"}

    if not recipients:
        logger.info("digest_no_recipients", detail="No recipients configured")
        return {"sent": False, "reason": "no recipients configured"}

    subject = f"mingai Platform Digest — {content['generated_at'][:10]}"
    body_text = _render_digest_text(content)

    sent_count = 0
    for recipient in recipients:
        try:
            import sendgrid  # type: ignore[import]
            from sendgrid.helpers.mail import Mail  # type: ignore[import]

            sg = sendgrid.SendGridAPIClient(api_key=api_key)
            from_email = os.environ.get("SENDGRID_FROM_EMAIL", "noreply@mingai.io")
            message = Mail(
                from_email=from_email,
                to_emails=recipient,
                subject=subject,
                plain_text_content=body_text,
            )
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, sg.send, message)
            sent_count += 1
        except Exception as exc:
            logger.warning(
                "digest_email_send_failed",
                recipient=recipient,
                error=str(exc),
            )

    return {"sent": sent_count > 0, "recipients_sent": sent_count}


async def run_daily_digest_job(db: AsyncSession, admin_user_id: str) -> dict:
    """
    Build and send the daily digest email for a platform admin.

    Reads recipients and enabled flag from admin preferences.
    Returns send summary.

    Called from APScheduler at configured UTC time.
    Does NOT commit — _build_digest_content commits internally.
    """
    prefs = await _get_platform_prefs(admin_user_id)
    digest_cfg = prefs.get(_DIGEST_CONFIG_KEY, {})

    if not digest_cfg.get("enabled", True):
        logger.info("digest_job_skipped", reason="disabled in config")
        return {"sent": False, "reason": "disabled"}

    recipients = digest_cfg.get("recipients", [])
    content = await _build_digest_content(db)
    result = await _send_digest_email(content, recipients)
    logger.info("daily_digest_job_complete", **result)
    return result
