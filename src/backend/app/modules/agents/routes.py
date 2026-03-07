"""
Agent Templates API routes (API-110 to API-115, API-039) and Agent Studio management (API-069 to API-073).

Endpoints (public router /agents):
- GET    /agents/templates                      - List agent templates (seed + DB + platform)
- GET    /agents/templates/{template_id}        - Get template detail
- POST   /agents/templates/{template_id}/deploy - Deploy template as new agent

Endpoints (admin router /admin/agents):
- GET    /admin/agents                          - List workspace agents (API-069)
- POST   /admin/agents                          - Create agent (API-070)
- PUT    /admin/agents/{agent_id}               - Update agent (API-071)
- PATCH  /admin/agents/{agent_id}/status        - Update agent status (API-072)
- POST   /admin/agents/deploy                   - Deploy from template library (API-073)

Seed templates are hardcoded and always available. DB templates come from agent_cards table.
Platform templates are stored in agent_cards under PLATFORM_TENANT_ID.
"""
import json
import os
import re
import uuid
from typing import Dict, List, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_tenant_admin
from app.core.session import get_async_session
from app.modules.har.crypto import generate_agent_keypair

logger = structlog.get_logger()

router = APIRouter(prefix="/agents", tags=["agents"])
admin_router = APIRouter(prefix="/admin/agents", tags=["admin-agents"])

# ---------------------------------------------------------------------------
# Seed templates — always available, not stored in DB
# ---------------------------------------------------------------------------

SEED_TEMPLATES = [
    {
        "id": "seed-hr",
        "name": "HR Policy Assistant",
        "description": "Answers HR policy questions, leave requests, and benefits enquiries with empathy and precision.",
        "system_prompt": "You are an HR Policy Assistant for {{company_name}}. You help employees understand HR policies, leave procedures, benefits, and workplace guidelines. Be empathetic, clear, and direct. Always reference specific policy sections when answering. If you are unsure, say so and suggest contacting HR directly.",
        "capabilities": ["hr_policies", "leave_management", "benefits"],
        "category": "HR",
        "status": "published",
        "is_seed": True,
        "version": 1,
    },
    {
        "id": "seed-it",
        "name": "IT Helpdesk Assistant",
        "description": "Diagnoses and resolves common IT issues, guides through troubleshooting steps, and escalates when needed.",
        "system_prompt": "You are an IT Helpdesk Assistant for {{company_name}}. You help employees resolve technical issues including software, hardware, network connectivity, and access problems. Walk users through troubleshooting steps clearly. Escalate to Level 2 support if the issue cannot be resolved in 3 steps.",
        "capabilities": ["troubleshooting", "ticket_creation", "escalation"],
        "category": "IT",
        "status": "published",
        "is_seed": True,
        "version": 1,
    },
    {
        "id": "seed-procurement",
        "name": "Procurement Assistant",
        "description": "Guides procurement requests, vendor comparisons, and purchase order workflows per company policy.",
        "system_prompt": "You are a Procurement Assistant for {{company_name}}. You help employees submit purchase requests, understand procurement policies, compare vendors, and track order status. Always check budget availability before approving requests. Flag purchases over {{approval_threshold}} for manager approval.",
        "capabilities": ["purchase_requests", "vendor_management", "policy_guidance"],
        "category": "Procurement",
        "status": "published",
        "is_seed": True,
        "version": 1,
    },
    {
        "id": "seed-onboarding",
        "name": "Onboarding Guide",
        "description": "Guides new employees through their first 30/60/90 days, checklists, and introductions.",
        "system_prompt": "You are an Onboarding Guide for {{company_name}}. You help new employees navigate their first weeks: setting up accounts, completing required training, understanding company culture, and finding key resources. Be welcoming, patient, and proactive. Customize guidance for {{employee_role}} and {{start_date}}.",
        "capabilities": ["onboarding_checklist", "account_setup", "culture_intro"],
        "category": "Onboarding",
        "status": "published",
        "is_seed": True,
        "version": 1,
    },
]

# Index seed templates by id for fast lookup
_SEED_BY_ID = {t["id"]: t for t in SEED_TEMPLATES}


# ---------------------------------------------------------------------------
# Allowlists
# ---------------------------------------------------------------------------

_VALID_AGENT_STATUSES = {"draft", "published", "unpublished"}
_VALID_AGENT_SOURCES = {"library", "custom", "seed"}
_VALID_SORT_COLUMNS = {"created_at", "name", "status"}

# Hardcoded SQL fragments for agent_cards UPDATE — column names never from user input.
_AGENT_UPDATE_SQL: dict[str, str] = {
    "name": "name = :name",
    "description": "description = :description",
    "category": "category = :category",
    "avatar": "avatar = :avatar",
    "system_prompt": "system_prompt = :system_prompt",
    "capabilities": "capabilities = CAST(:capabilities AS jsonb)",
    "status": "status = :status",
    "version": "version = :version",
}


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class DeployAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    access_control: Literal["workspace", "role", "user"] = Field(...)
    kb_ids: List[str] = Field(default_factory=list)


class GuardrailsSchema(BaseModel):
    blocked_topics: List[str] = Field(default_factory=list)
    confidence_threshold: float = Field(0.5, ge=0.0, le=1.0)
    max_response_length: int = Field(2000, ge=100, le=10000)


class CreateAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=100)
    avatar: Optional[str] = Field(None, max_length=500)
    system_prompt: str = Field(..., min_length=1)
    kb_ids: List[str] = Field(default_factory=list)
    kb_mode: Literal["grounded", "extended"] = Field("grounded")
    tool_ids: List[str] = Field(default_factory=list)
    guardrails: GuardrailsSchema = Field(default_factory=GuardrailsSchema)
    access_mode: Literal["workspace_wide", "role_restricted", "user_specific"] = Field(
        "workspace_wide"
    )
    status: Literal["draft", "published", "unpublished"] = Field("draft")


class UpdateAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=100)
    avatar: Optional[str] = Field(None, max_length=500)
    system_prompt: str = Field(..., min_length=1)
    kb_ids: List[str] = Field(default_factory=list)
    kb_mode: Literal["grounded", "extended"] = Field("grounded")
    tool_ids: List[str] = Field(default_factory=list)
    guardrails: GuardrailsSchema = Field(default_factory=GuardrailsSchema)
    access_mode: Literal["workspace_wide", "role_restricted", "user_specific"] = Field(
        "workspace_wide"
    )
    status: Literal["draft", "published", "unpublished"] = Field("draft")


class UpdateAgentStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(draft|published|unpublished)$")


class DeployFromLibraryRequest(BaseModel):
    template_id: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    variables: Dict[str, str] = Field(default_factory=dict)
    kb_ids: List[str] = Field(default_factory=list)
    access_mode: Literal["workspace_wide", "role_restricted", "user_specific"] = Field(
        "workspace_wide"
    )


# ---------------------------------------------------------------------------
# DB helper functions (mockable in unit tests)
# ---------------------------------------------------------------------------


async def list_agent_templates_db(
    tenant_id: str, page: int, page_size: int, db: AsyncSession
) -> dict:
    """List agent_cards templates for a tenant from DB."""
    offset = (page - 1) * page_size
    count_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM agent_cards "
            "WHERE tenant_id = :tenant_id AND status IN ('published', 'draft')"
        ),
        {"tenant_id": tenant_id},
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        text(
            "SELECT id, name, description, system_prompt, capabilities, status, version, created_at "
            "FROM agent_cards "
            "WHERE tenant_id = :tenant_id AND status IN ('published', 'draft') "
            "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        ),
        {"tenant_id": tenant_id, "limit": page_size, "offset": offset},
    )
    items = []
    for row in rows_result.mappings():
        capabilities = row["capabilities"]
        if isinstance(capabilities, str):
            capabilities = json.loads(capabilities)
        items.append(
            {
                "id": str(row["id"]),
                "name": row["name"],
                "description": row["description"],
                "system_prompt": row["system_prompt"],
                "capabilities": capabilities or [],
                "status": row["status"],
                "version": row["version"],
                "is_seed": False,
                "created_at": str(row["created_at"]),
            }
        )
    return {"items": items, "total": total}


async def get_agent_template_db(
    template_id: str, tenant_id: str, db: AsyncSession
) -> Optional[dict]:
    """Fetch a single agent_cards template by id and tenant_id."""
    result = await db.execute(
        text(
            "SELECT id, name, description, system_prompt, capabilities, status, version, created_at "
            "FROM agent_cards "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": template_id, "tenant_id": tenant_id},
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
        "capabilities": capabilities or [],
        "status": row["status"],
        "version": row["version"],
        "is_seed": False,
        "created_at": str(row["created_at"]),
    }


async def deploy_agent_template_db(
    tenant_id: str,
    name: str,
    description: str,
    system_prompt: str,
    capabilities: list,
    access_control: str,
    kb_ids: list,
    created_by: str,
    db: AsyncSession,
) -> dict:
    """Insert a new published agent_cards row from a template deployment."""
    agent_id = str(uuid.uuid4())
    capabilities_json = json.dumps(capabilities)
    kb_ids_json = json.dumps(kb_ids)
    await db.execute(
        text(
            "INSERT INTO agent_cards "
            "(id, tenant_id, name, description, system_prompt, capabilities, status, version, created_by) "
            "VALUES (:id, :tenant_id, :name, :description, :system_prompt, "
            "CAST(:capabilities AS jsonb), 'published', 1, :created_by)"
        ),
        {
            "id": agent_id,
            "tenant_id": tenant_id,
            "name": name,
            "description": description,
            "system_prompt": system_prompt,
            "capabilities": capabilities_json,
            "created_by": created_by,
        },
    )
    # Generate Ed25519 keypair and store encrypted private key (AI-040)
    try:
        public_key, private_key_enc = generate_agent_keypair()
        await db.execute(
            text(
                "UPDATE agent_cards "
                "SET public_key = :public_key, private_key_enc = :private_key_enc "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {
                "public_key": public_key,
                "private_key_enc": private_key_enc,
                "id": agent_id,
                "tenant_id": tenant_id,
            },
        )
        await db.commit()
        logger.info(
            "agent_keypair_generated",
            agent_id=agent_id,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.warning(
            "agent_keypair_generation_failed",
            agent_id=agent_id,
            tenant_id=tenant_id,
            error=str(exc),
        )

    logger.info(
        "agent_template_deployed",
        agent_id=agent_id,
        template_name=name,
        tenant_id=tenant_id,
        access_control=access_control,
    )
    return {"id": agent_id, "name": name, "status": "published"}


async def list_platform_templates_db(
    platform_tenant_id: str,
    status_filter: Optional[str],
    category_filter: Optional[str],
    plan_tier_filter: Optional[str],
    is_platform_admin: bool,
    caller_plan: str,
    db: AsyncSession,
) -> List[dict]:
    """
    API-039: Fetch platform-controlled templates from agent_cards.

    Platform admins: see all statuses.
    Tenant admins: see only 'published' templates whose capabilities.plan_tiers
                   contain their plan.
    """
    params: dict = {"platform_tenant_id": platform_tenant_id}

    if is_platform_admin:
        # Platform admin sees all statuses unless a specific filter is requested
        if status_filter is not None:
            status_condition = "AND status = :status_filter"
            params["status_filter"] = status_filter
        else:
            status_condition = ""
    else:
        # Tenant admin sees only published templates
        status_condition = "AND status = 'published'"

    rows_result = await db.execute(
        text(
            "SELECT id, name, description, system_prompt, capabilities, "
            "status, version, category, created_at "
            "FROM agent_cards "
            f"WHERE tenant_id = :platform_tenant_id {status_condition} "  # noqa: S608
            "ORDER BY created_at DESC"
        ),
        params,
    )

    items = []
    for row in rows_result.mappings():
        capabilities = row["capabilities"]
        if isinstance(capabilities, str):
            capabilities = json.loads(capabilities)
        if capabilities is None:
            capabilities = {}

        plan_tiers = (
            capabilities.get("plan_tiers", []) if isinstance(capabilities, dict) else []
        )

        # For tenant admins: filter by plan_tiers overlap
        if not is_platform_admin and plan_tiers and caller_plan not in plan_tiers:
            continue

        # Apply plan_tier_filter (explicit query param)
        if plan_tier_filter is not None and plan_tier_filter not in plan_tiers:
            continue

        row_category = row["category"] or ""
        # Apply category_filter
        if (
            category_filter is not None
            and row_category.lower() != category_filter.lower()
        ):
            continue

        # Count adoption: how many deployed agents reference this template
        adoption_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM agent_cards "
                "WHERE template_id = :template_id AND tenant_id != :platform_tenant_id"
            ),
            {"template_id": str(row["id"]), "platform_tenant_id": platform_tenant_id},
        )
        adoption_count = adoption_result.scalar() or 0

        items.append(
            {
                "id": str(row["id"]),
                "name": row["name"],
                "description": row["description"] or "",
                "system_prompt": row["system_prompt"],
                "capabilities": capabilities,
                "status": row["status"],
                "version": row["version"],
                "category": row_category,
                "is_seed": False,
                "is_platform": True,
                "plan_tiers": plan_tiers,
                "adoption_count": adoption_count,
                "created_at": str(row["created_at"]),
            }
        )
    return items


def _get_platform_tenant_id() -> str:
    """Return PLATFORM_TENANT_ID env var, defaulting to 'platform'."""
    return os.environ.get("PLATFORM_TENANT_ID", "platform")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/templates")
async def list_agent_templates(
    category: Optional[str] = Query(None, description="Filter by category"),
    template_status: Optional[str] = Query(
        None,
        alias="status",
        description="Filter by template status (platform admin only for non-published)",
    ),
    plan_tier: Optional[str] = Query(None, description="Filter by plan tier"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-110 / API-039: List agent templates (seed + DB + platform library).

    - Platform admin: all seed templates + tenant DB templates + all platform templates
      (any status). Supports status/category/plan_tier filters.
    - Tenant admin: seed templates + tenant DB templates + published platform templates
      matching caller's plan. Supports category/plan_tier filters.
    """
    is_platform_admin = current_user.scope == "platform"
    is_tenant_admin = "tenant_admin" in current_user.roles

    if not is_platform_admin and not is_tenant_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant admin or platform admin access required.",
        )

    platform_tenant_id = _get_platform_tenant_id()

    # 1. Platform templates from DB
    platform_items = await list_platform_templates_db(
        platform_tenant_id=platform_tenant_id,
        status_filter=template_status,
        category_filter=category,
        plan_tier_filter=plan_tier,
        is_platform_admin=is_platform_admin,
        caller_plan=current_user.plan,
        db=session,
    )

    # 2. Tenant-own templates from DB (skip for platform admin, they manage via /platform routes)
    if not is_platform_admin:
        db_result = await list_agent_templates_db(
            tenant_id=current_user.tenant_id,
            page=page,
            page_size=page_size,
            db=session,
        )
        tenant_db_items = db_result["items"]
    else:
        tenant_db_items = []

    # 3. Seed templates — apply category + plan_tier filters
    seed_items = list(SEED_TEMPLATES)
    if category is not None:
        category_lower = category.lower()
        seed_items = [
            item
            for item in seed_items
            if item.get("category", "").lower() == category_lower
        ]
    # Seed templates have no plan_tier restriction — always include them

    # 4. Merge: seed + platform + tenant_db
    all_items = seed_items + platform_items + tenant_db_items

    # Apply category filter to tenant_db_items (already applied to platform/seed above)
    # tenant_db_items need category filter applied separately if not already
    if category is not None and tenant_db_items:
        category_lower = category.lower()
        tenant_already_filtered = platform_items  # platform items already filtered
        all_items = (
            seed_items
            + tenant_already_filtered
            + [
                item
                for item in tenant_db_items
                if item.get("category", "").lower() == category_lower
            ]
        )

    total = len(all_items)

    return {
        "items": all_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/templates/{template_id}")
async def get_agent_template(
    template_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-111: Get agent template detail by ID."""
    # Check seed templates first
    if template_id in _SEED_BY_ID:
        return _SEED_BY_ID[template_id]

    # Fall back to DB lookup
    result = await get_agent_template_db(
        template_id=template_id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent template '{template_id}' not found",
        )
    return result


@router.post(
    "/templates/{template_id}/deploy",
    status_code=status.HTTP_201_CREATED,
)
async def deploy_agent_template(
    template_id: str,
    body: DeployAgentRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-112: Deploy an agent template as a new published agent."""
    # Resolve the source template
    if template_id in _SEED_BY_ID:
        source = _SEED_BY_ID[template_id]
    else:
        source = await get_agent_template_db(
            template_id=template_id,
            tenant_id=current_user.tenant_id,
            db=session,
        )
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent template '{template_id}' not found",
            )

    result = await deploy_agent_template_db(
        tenant_id=current_user.tenant_id,
        name=body.name,
        description=source.get("description", ""),
        system_prompt=source["system_prompt"],
        capabilities=source.get("capabilities", []),
        access_control=body.access_control,
        kb_ids=body.kb_ids,
        created_by=current_user.id,
        db=session,
    )

    # Log access_control and kb_ids received — these fields are not yet fully persisted
    # to the agent_cards schema (columns pending in next migration). They are accepted
    # in the API contract so the frontend deploy form works without changes once the
    # schema is extended. Without this log, the values would be silently discarded.
    if body.kb_ids or body.access_control != "workspace":
        logger.warning(
            "agent_deploy_config_not_persisted",
            agent_id=result["id"],
            tenant_id=current_user.tenant_id,
            access_control=body.access_control,
            kb_ids_count=len(body.kb_ids),
            note="access_control and kb_ids require schema migration before they are enforced",
        )

    return result


@router.get("/templates/{agent_id}/public-key")
async def get_agent_public_key(
    agent_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """AI-040: Get the Ed25519 public key for an agent (for signature verification)."""
    result = await session.execute(
        text(
            "SELECT id, public_key FROM agent_cards "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": agent_id, "tenant_id": current_user.tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )
    if not row["public_key"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' does not have a public key (keypair not yet generated)",
        )
    return {"agent_id": str(row["id"]), "public_key": row["public_key"]}


@router.post("/templates/{agent_id}/compute-trust-score")
async def compute_agent_trust_score(
    agent_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """AI-046: Trigger trust score recomputation for an agent."""
    from app.modules.har.trust import compute_trust_score

    # Verify agent exists and belongs to this tenant
    exists_result = await session.execute(
        text("SELECT id FROM agent_cards WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": agent_id, "tenant_id": current_user.tenant_id},
    )
    if exists_result.mappings().first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    trust_score = await compute_trust_score(agent_id, current_user.tenant_id, session)
    await session.commit()
    return {"agent_id": agent_id, "trust_score": trust_score}


# ---------------------------------------------------------------------------
# Admin DB helper functions (API-069 to API-073)
# ---------------------------------------------------------------------------


async def list_workspace_agents_db(
    tenant_id: str,
    page: int,
    page_size: int,
    status_filter: Optional[str],
    db: AsyncSession,
) -> dict:
    """List agent_cards for a tenant with optional status filter and usage metrics."""
    offset = (page - 1) * page_size
    params: dict = {"tenant_id": tenant_id, "limit": page_size, "offset": offset}

    if status_filter:
        count_sql = (
            "SELECT COUNT(*) FROM agent_cards "
            "WHERE tenant_id = :tenant_id AND status = :status"
        )
        rows_sql = (
            "SELECT id, name, description, category, source, status, version, created_at "
            "FROM agent_cards "
            "WHERE tenant_id = :tenant_id AND status = :status "
            "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        )
        params["status"] = status_filter
    else:
        count_sql = "SELECT COUNT(*) FROM agent_cards WHERE tenant_id = :tenant_id"
        rows_sql = (
            "SELECT id, name, description, category, source, status, version, created_at "
            "FROM agent_cards "
            "WHERE tenant_id = :tenant_id "
            "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        )

    count_result = await db.execute(text(count_sql), params)
    total = count_result.scalar() or 0

    rows_result = await db.execute(text(rows_sql), params)
    items = []
    for row in rows_result.mappings():
        agent_id_str = str(row["id"])

        # user_count: distinct users who sent messages via this agent in the last 30 days
        uc_result = await db.execute(
            text(
                "SELECT COUNT(DISTINCT c.user_id) FROM conversations c "
                "JOIN messages m ON m.conversation_id = c.id "
                "WHERE c.agent_id = :agent_id "
                "AND c.tenant_id = :tenant_id "
                "AND m.created_at >= NOW() - INTERVAL '30 days'"
            ),
            {"agent_id": agent_id_str, "tenant_id": tenant_id},
        )
        user_count = uc_result.scalar() or 0

        # satisfaction_rate: ratio of +1 ratings to total ratings (null if no ratings)
        sr_result = await db.execute(
            text(
                "SELECT "
                "  COUNT(*) FILTER (WHERE uf.rating = 1) AS positive, "
                "  COUNT(*) AS total "
                "FROM user_feedback uf "
                "JOIN messages m ON m.id = uf.message_id "
                "JOIN conversations c ON c.id = m.conversation_id "
                "WHERE c.agent_id = :agent_id AND c.tenant_id = :tenant_id"
            ),
            {"agent_id": agent_id_str, "tenant_id": tenant_id},
        )
        sr_row = sr_result.mappings().first()
        satisfaction_rate = None
        if sr_row and sr_row["total"] and int(sr_row["total"]) > 0:
            satisfaction_rate = round(
                int(sr_row["positive"]) / int(sr_row["total"]) * 100, 1
            )

        items.append(
            {
                "id": agent_id_str,
                "name": row["name"],
                "description": row["description"],
                "category": row["category"],
                "source": row["source"],
                "status": row["status"],
                "version": row["version"],
                "satisfaction_rate": satisfaction_rate,
                "user_count": user_count,
                "created_at": str(row["created_at"]),
            }
        )
    return {"items": items, "total": total}


async def create_agent_studio_db(
    tenant_id: str,
    name: str,
    description: Optional[str],
    category: Optional[str],
    avatar: Optional[str],
    system_prompt: str,
    capabilities: dict,
    agent_status: str,
    created_by: str,
    db: AsyncSession,
) -> dict:
    """Insert a new agent_cards row for Agent Studio (API-070)."""
    agent_id = str(uuid.uuid4())
    capabilities_json = json.dumps(capabilities)
    await db.execute(
        text(
            "INSERT INTO agent_cards "
            "(id, tenant_id, name, description, category, avatar, system_prompt, "
            "capabilities, status, version, source, created_by) "
            "VALUES (:id, :tenant_id, :name, :description, :category, :avatar, "
            ":system_prompt, CAST(:capabilities AS jsonb), :status, 1, 'custom', :created_by)"
        ),
        {
            "id": agent_id,
            "tenant_id": tenant_id,
            "name": name,
            "description": description,
            "category": category,
            "avatar": avatar,
            "system_prompt": system_prompt,
            "capabilities": capabilities_json,
            "status": agent_status,
            "created_by": created_by,
        },
    )
    await db.commit()
    logger.info(
        "agent_studio_created",
        agent_id=agent_id,
        tenant_id=tenant_id,
        agent_status=agent_status,
    )
    return {"id": agent_id}


async def get_agent_by_id_db(
    agent_id: str, tenant_id: str, db: AsyncSession
) -> Optional[dict]:
    """Fetch a single agent_cards row by id and tenant."""
    result = await db.execute(
        text(
            "SELECT id, name, description, category, avatar, source, system_prompt, "
            "capabilities, status, version, template_id, template_version, "
            "created_at, updated_at "
            "FROM agent_cards "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": agent_id, "tenant_id": tenant_id},
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
        "category": row["category"],
        "avatar": row["avatar"],
        "source": row["source"],
        "system_prompt": row["system_prompt"],
        "capabilities": capabilities,
        "status": row["status"],
        "version": row["version"],
        "template_id": row["template_id"],
        "template_version": row["template_version"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


async def update_agent_studio_db(
    agent_id: str,
    tenant_id: str,
    name: str,
    description: Optional[str],
    category: Optional[str],
    avatar: Optional[str],
    system_prompt: str,
    capabilities: dict,
    agent_status: str,
    db: AsyncSession,
) -> Optional[dict]:
    """Update an agent_cards row. Increments version if currently published (API-071)."""
    existing = await get_agent_by_id_db(agent_id, tenant_id, db)
    if existing is None:
        return None

    new_version = existing["version"]
    if existing["status"] == "published":
        new_version = existing["version"] + 1

    capabilities_json = json.dumps(capabilities)
    await db.execute(
        text(
            "UPDATE agent_cards "
            "SET name = :name, description = :description, category = :category, "
            "avatar = :avatar, system_prompt = :system_prompt, "
            "capabilities = CAST(:capabilities AS jsonb), status = :status, "
            "version = :version, updated_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {
            "name": name,
            "description": description,
            "category": category,
            "avatar": avatar,
            "system_prompt": system_prompt,
            "capabilities": capabilities_json,
            "status": agent_status,
            "version": new_version,
            "id": agent_id,
            "tenant_id": tenant_id,
        },
    )
    await db.commit()
    logger.info(
        "agent_studio_updated",
        agent_id=agent_id,
        tenant_id=tenant_id,
        new_version=new_version,
    )
    return await get_agent_by_id_db(agent_id, tenant_id, db)


async def update_agent_status_db(
    agent_id: str,
    tenant_id: str,
    new_status: str,
    db: AsyncSession,
) -> Optional[dict]:
    """Update agent status. Re-publishing an already-published agent increments version."""
    existing = await get_agent_by_id_db(agent_id, tenant_id, db)
    if existing is None:
        return None

    new_version = existing["version"]
    if new_status == "published" and existing["status"] == "published":
        new_version = existing["version"] + 1

    await db.execute(
        text(
            "UPDATE agent_cards "
            "SET status = :status, version = :version, updated_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {
            "status": new_status,
            "version": new_version,
            "id": agent_id,
            "tenant_id": tenant_id,
        },
    )
    await db.commit()
    logger.info(
        "agent_status_changed",
        agent_id=agent_id,
        tenant_id=tenant_id,
        old_status=existing["status"],
        new_status=new_status,
    )
    return {"id": agent_id, "status": new_status}


async def insert_audit_log(
    tenant_id: str,
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict,
    db: AsyncSession,
) -> None:
    """Insert an audit_log entry (non-fatal on failure)."""
    try:
        details_json = json.dumps(details)
        await db.execute(
            text(
                "INSERT INTO audit_log "
                "(tenant_id, user_id, action, resource_type, resource_id, details) "
                "VALUES (:tenant_id, :user_id, :action, :resource_type, "
                "CAST(:resource_id AS uuid), CAST(:details AS jsonb))"
            ),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "details": details_json,
            },
        )
        await db.commit()
    except Exception as exc:
        logger.warning(
            "audit_log_insert_failed",
            tenant_id=tenant_id,
            action=action,
            error=str(exc),
        )


async def deploy_from_library_db(
    tenant_id: str,
    template_id: str,
    template_version: int,
    name: str,
    system_prompt: str,
    description: str,
    category: Optional[str],
    capabilities: list,
    created_by: str,
    db: AsyncSession,
) -> dict:
    """Create a new published agent from a library or seed template (API-073)."""
    agent_id = str(uuid.uuid4())
    capabilities_json = json.dumps(capabilities)
    await db.execute(
        text(
            "INSERT INTO agent_cards "
            "(id, tenant_id, name, description, category, system_prompt, "
            "capabilities, status, version, source, template_id, template_version, created_by) "
            "VALUES (:id, :tenant_id, :name, :description, :category, :system_prompt, "
            "CAST(:capabilities AS jsonb), 'published', 1, 'library', "
            ":template_id, :template_version, :created_by)"
        ),
        {
            "id": agent_id,
            "tenant_id": tenant_id,
            "name": name,
            "description": description,
            "category": category,
            "system_prompt": system_prompt,
            "capabilities": capabilities_json,
            "template_id": template_id,
            "template_version": template_version,
            "created_by": created_by,
        },
    )
    try:
        public_key, private_key_enc = generate_agent_keypair()
        await db.execute(
            text(
                "UPDATE agent_cards "
                "SET public_key = :public_key, private_key_enc = :private_key_enc "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {
                "public_key": public_key,
                "private_key_enc": private_key_enc,
                "id": agent_id,
                "tenant_id": tenant_id,
            },
        )
        await db.commit()
        logger.info(
            "agent_library_keypair_generated", agent_id=agent_id, tenant_id=tenant_id
        )
    except Exception as exc:
        logger.warning(
            "agent_library_keypair_failed",
            agent_id=agent_id,
            tenant_id=tenant_id,
            error=str(exc),
        )

    logger.info(
        "agent_deployed_from_library",
        agent_id=agent_id,
        template_id=template_id,
        tenant_id=tenant_id,
    )
    return {
        "id": agent_id,
        "name": name,
        "template_id": template_id,
        "template_version": template_version,
        "status": "published",
    }


def _substitute_variables(prompt: str, variables: dict) -> str:
    """Replace {{variable_name}} placeholders.

    Only alphanumeric/underscore variable names are substituted to prevent
    injection via malformed placeholder names.
    """
    for key, value in variables.items():
        if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", key):
            prompt = prompt.replace("{{" + key + "}}", str(value))
    return prompt


# ---------------------------------------------------------------------------
# Admin route handlers (API-069 to API-073)
# ---------------------------------------------------------------------------


@admin_router.get("")
async def list_workspace_agents(
    status: Optional[str] = Query(
        None, description="Filter by status: draft|published|unpublished"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-069: List workspace agents for the tenant (tenant admin only)."""
    if status is not None and status not in _VALID_AGENT_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid status '{status}'. "
                f"Must be one of: {', '.join(sorted(_VALID_AGENT_STATUSES))}"
            ),
        )
    result = await list_workspace_agents_db(
        tenant_id=current_user.tenant_id,
        page=page,
        page_size=page_size,
        status_filter=status,
        db=session,
    )
    return {
        "items": result["items"],
        "total": result["total"],
        "page": page,
        "page_size": page_size,
    }


@admin_router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: CreateAgentRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-070: Create a new agent (Agent Studio)."""
    capabilities = {
        "guardrails": body.guardrails.model_dump(),
        "kb_ids": body.kb_ids,
        "kb_mode": body.kb_mode,
        "tool_ids": body.tool_ids,
        "access_mode": body.access_mode,
    }
    result = await create_agent_studio_db(
        tenant_id=current_user.tenant_id,
        name=body.name,
        description=body.description,
        category=body.category,
        avatar=body.avatar,
        system_prompt=body.system_prompt,
        capabilities=capabilities,
        agent_status=body.status,
        created_by=current_user.id,
        db=session,
    )
    agent_id = result["id"]
    await insert_audit_log(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="agent_created",
        resource_type="agent",
        resource_id=agent_id,
        details={"name": body.name, "status": body.status},
        db=session,
    )
    ts_result = await session.execute(
        text(
            "SELECT created_at FROM agent_cards "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": agent_id, "tenant_id": current_user.tenant_id},
    )
    ts_row = ts_result.mappings().first()
    created_at = str(ts_row["created_at"]) if ts_row else None
    return {
        "id": agent_id,
        "name": body.name,
        "status": body.status,
        "created_at": created_at,
    }


@admin_router.put("/{agent_id}")
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-071: Update an agent (Agent Studio)."""
    capabilities = {
        "guardrails": body.guardrails.model_dump(),
        "kb_ids": body.kb_ids,
        "kb_mode": body.kb_mode,
        "tool_ids": body.tool_ids,
        "access_mode": body.access_mode,
    }
    result = await update_agent_studio_db(
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        name=body.name,
        description=body.description,
        category=body.category,
        avatar=body.avatar,
        system_prompt=body.system_prompt,
        capabilities=capabilities,
        agent_status=body.status,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )
    await insert_audit_log(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="agent_updated",
        resource_type="agent",
        resource_id=agent_id,
        details={"name": body.name, "status": body.status},
        db=session,
    )
    return {
        "id": result["id"],
        "version": result["version"],
        "status": result["status"],
        "updated_at": result["updated_at"],
    }


@admin_router.patch("/{agent_id}/status")
async def update_agent_status(
    agent_id: str,
    body: UpdateAgentStatusRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-072: Update agent status (draft|published|unpublished)."""
    existing = await get_agent_by_id_db(agent_id, current_user.tenant_id, session)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )
    if body.status == "published":
        if not existing.get("system_prompt", "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot publish agent: system_prompt must not be empty",
            )
        if not existing.get("name", "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot publish agent: name must not be empty",
            )
    old_status = existing["status"]
    result = await update_agent_status_db(
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        new_status=body.status,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )
    await insert_audit_log(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="agent_status_changed",
        resource_type="agent",
        resource_id=agent_id,
        details={"old_status": old_status, "new_status": body.status},
        db=session,
    )
    return {"id": agent_id, "status": body.status}


@admin_router.post("/deploy", status_code=status.HTTP_201_CREATED)
async def deploy_from_library(
    body: DeployFromLibraryRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-073: Deploy an agent from the template library (seed or DB)."""
    template_id = body.template_id

    if template_id in _SEED_BY_ID:
        tmpl = _SEED_BY_ID[template_id]
        source_version = tmpl.get("version", 1)
        system_prompt = tmpl["system_prompt"]
        description = tmpl.get("description", "")
        category = tmpl.get("category")
        capabilities = tmpl.get("capabilities", [])
    else:
        db_result = await session.execute(
            text(
                "SELECT id, description, system_prompt, capabilities, version, category "
                "FROM agent_cards "
                "WHERE id = :id AND status = 'published'"
            ),
            {"id": template_id},
        )
        db_row = db_result.mappings().first()
        if db_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template '{template_id}' not found",
            )
        caps = db_row["capabilities"]
        if isinstance(caps, str):
            caps = json.loads(caps)
        source_version = db_row["version"]
        system_prompt = db_row["system_prompt"]
        description = db_row["description"] or ""
        category = db_row["category"]
        capabilities = caps if isinstance(caps, list) else []

    system_prompt = _substitute_variables(system_prompt, body.variables)

    result = await deploy_from_library_db(
        tenant_id=current_user.tenant_id,
        template_id=template_id,
        template_version=source_version,
        name=body.name,
        system_prompt=system_prompt,
        description=description,
        category=category,
        capabilities=capabilities,
        created_by=current_user.id,
        db=session,
    )
    await insert_audit_log(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="agent_deployed_from_library",
        resource_type="agent",
        resource_id=result["id"],
        details={"template_id": template_id, "name": body.name},
        db=session,
    )
    return result
