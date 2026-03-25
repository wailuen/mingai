"""
Agent Templates API routes (API-110 to API-115, API-039) and Agent Studio management (API-069 to API-073).

Endpoints (public router /agents):
- GET    /agents                                        - List published agents for end user (API-117)
- GET    /agents/templates                              - List agent templates (seed + DB + platform)
- GET    /agents/templates/{template_id}                - Get template detail
- POST   /agents/templates/{template_id}/deploy         - Deploy template as new agent

Endpoints (admin router /admin/agents):
- GET    /admin/agents                                  - List workspace agents (API-069)
- POST   /admin/agents                                  - Create agent (API-070)
- PUT    /admin/agents/{agent_id}                       - Update agent (API-071)
- PATCH  /admin/agents/{agent_id}/status                - Update agent status (API-072)
- POST   /admin/agents/deploy                           - Deploy from template library (API-073)
- GET    /admin/agents/{agent_id}/upgrade-available     - Check if newer template version exists (TA-024)
- PATCH  /admin/agents/{agent_id}/upgrade               - Upgrade to latest published template version (TA-024)

Seed templates are hardcoded and always available. DB templates come from agent_cards table.
Platform templates are stored in agent_cards under PLATFORM_TENANT_ID.
"""
import hashlib
import json
import os
import re
import uuid
from typing import Annotated, Dict, List, Literal, Optional

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
        "template_type": "rag",
        "llm_policy": {"tenant_can_override": True, "defaults": {"temperature": 0.3, "max_tokens": 2000}},
        "kb_policy": {"ownership": "tenant_managed", "recommended_categories": [], "required_kb_ids": []},
        "attached_skills": [],
        "attached_tools": [],
        "a2a_interface": {"a2a_enabled": False, "operations": [], "auth_required": False},
        "plan_required": None,
        "auth_mode": "none",
        "instance_count": 0,
        "icon": None,
        "tags": [],
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
        "template_type": "rag",
        "llm_policy": {"tenant_can_override": True, "defaults": {"temperature": 0.3, "max_tokens": 2000}},
        "kb_policy": {"ownership": "tenant_managed", "recommended_categories": [], "required_kb_ids": []},
        "attached_skills": [],
        "attached_tools": [],
        "a2a_interface": {"a2a_enabled": False, "operations": [], "auth_required": False},
        "plan_required": None,
        "auth_mode": "none",
        "instance_count": 0,
        "icon": None,
        "tags": [],
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
        "template_type": "rag",
        "llm_policy": {"tenant_can_override": True, "defaults": {"temperature": 0.3, "max_tokens": 2000}},
        "kb_policy": {"ownership": "tenant_managed", "recommended_categories": [], "required_kb_ids": []},
        "attached_skills": [],
        "attached_tools": [],
        "a2a_interface": {"a2a_enabled": False, "operations": [], "auth_required": False},
        "plan_required": None,
        "auth_mode": "none",
        "instance_count": 0,
        "icon": None,
        "tags": [],
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
        "template_type": "rag",
        "llm_policy": {"tenant_can_override": True, "defaults": {"temperature": 0.3, "max_tokens": 2000}},
        "kb_policy": {"ownership": "tenant_managed", "recommended_categories": [], "required_kb_ids": []},
        "attached_skills": [],
        "attached_tools": [],
        "a2a_interface": {"a2a_enabled": False, "operations": [], "auth_required": False},
        "plan_required": None,
        "auth_mode": "none",
        "instance_count": 0,
        "icon": None,
        "tags": [],
    },
]

# Index seed templates by id for fast lookup
_SEED_BY_ID = {t["id"]: t for t in SEED_TEMPLATES}


def _parse_jsonb(val, default):
    """Safely coerce a JSONB column value to a Python object.

    asyncpg returns JSONB as a dict/list already; psycopg2 returns it as a
    str. This helper handles both and falls back to ``default`` on any error.
    """
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (ValueError, TypeError):
        return default


def _extract_variable_schema(system_prompt: str) -> List[dict]:
    """Return a schema list for all ``{{variable}}`` tokens in *system_prompt*.

    Each token appears at most once in the result.  Tokens are returned in the
    order they first appear in the prompt.
    """
    tokens = re.findall(r'\{\{(\w+)\}\}', system_prompt or "")
    seen: set = set()
    result = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            result.append({"name": token, "type": "string", "required": True, "description": ""})
    return result


# ---------------------------------------------------------------------------
# Allowlists
# ---------------------------------------------------------------------------

_VALID_AGENT_STATUSES = {
    "draft",
    "published",
    "unpublished",
    "active",
    "paused",
    "archived",
}
_VALID_AGENT_SOURCES = {"library", "custom", "seed"}
_VALID_SORT_COLUMNS = {"created_at", "name", "status"}
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_VALID_CRED_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
# Strip control characters (including newlines) from variable substitution values
# to prevent newline-based prompt injection in system prompts (H3 — CWE-93).
_CTRL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")

# C2: Map DeployAgentRequest.access_control API values to agent_access_control.visibility_mode
# DB column uses CHECK constraint values: 'workspace_wide', 'role_restricted', 'user_specific'.
# API uses shorter human-readable values. MUST be used in ALL three deploy paths.
_ACCESS_CONTROL_MAP = {
    "workspace": "workspace_wide",
    "role": "role_restricted",
    "user": "user_specific",
}

# RULE A2A-06: Every UPDATE to agent_cards MUST include tenant_id = :tenant_id
# in the WHERE clause — not only the initial INSERT. Missing tenant_id on the
# UPDATE path allows a crafted request to overwrite a different tenant's agent
# access control configuration (cross-tenant RLS bypass via application layer).
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
    access_control: Literal["workspace", "role", "user"] = Field("workspace")
    kb_ids: List[str] = Field(default_factory=list)
    allowed_roles: List[str] = Field(default_factory=list)
    allowed_user_ids: List[str] = Field(default_factory=list)
    credentials: Optional[Dict[str, str]] = None  # Required when auth_mode='tenant_credentials'


class GuardrailsSchema(BaseModel):
    """
    RULE A2A-02: Guardrail configuration stored in agent_cards.capabilities.

    CRITICAL: Storing guardrails in this schema does nothing unless
    ChatOrchestrationService reads and applies them on every request. Guardrail
    config persisted to DB must be enforced at Stage 7b (OutputGuardrailChecker)
    on every chat request. DB storage != enforcement. See guardrails.py Stage 7b
    and orchestrator.py ChatOrchestrationService docstring for the enforcement path.
    """

    blocked_topics: List[str] = Field(default_factory=list)
    confidence_threshold: float = Field(0.5, ge=0.0, le=1.0)
    max_response_length: int = Field(2000, ge=100, le=10000)


class CreateAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=100)
    avatar: Optional[str] = Field(None, max_length=500)
    system_prompt: str = Field(..., min_length=1, max_length=32000)
    kb_ids: List[str] = Field(default_factory=list)
    kb_mode: Literal["grounded", "extended"] = Field("grounded")
    tool_ids: List[str] = Field(default_factory=list)
    guardrails: GuardrailsSchema = Field(default_factory=GuardrailsSchema)
    access_mode: Literal["workspace_wide", "role_restricted", "user_specific"] = Field(
        "workspace_wide"
    )
    # Required when access_mode=role_restricted or user_specific (R5)
    allowed_roles: List[str] = Field(default_factory=list)
    allowed_user_ids: List[str] = Field(default_factory=list)
    status: Literal[
        "draft", "published", "unpublished", "active", "paused", "archived"
    ] = Field("draft")


class UpdateAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=100)
    avatar: Optional[str] = Field(None, max_length=500)
    system_prompt: str = Field(..., min_length=1, max_length=32000)
    kb_ids: List[str] = Field(default_factory=list)
    kb_mode: Literal["grounded", "extended"] = Field("grounded")
    tool_ids: List[str] = Field(default_factory=list)
    guardrails: GuardrailsSchema = Field(default_factory=GuardrailsSchema)
    access_mode: Literal["workspace_wide", "role_restricted", "user_specific"] = Field(
        "workspace_wide"
    )
    status: Literal[
        "draft", "published", "unpublished", "active", "paused", "archived"
    ] = Field("draft")


class UpdateAgentStatusRequest(BaseModel):
    status: str = Field(
        ..., pattern="^(draft|published|unpublished|active|paused|archived)$"
    )


class AgentTestRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)


class DeployFromLibraryRequest(BaseModel):
    template_id: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    # `variables` is the legacy field; `variable_values` is the PA-023 canonical name.
    # Both are accepted; variable_values takes priority if both are sent.
    # Per-value length cap prevents oversized prompt injection payloads.
    variables: Dict[str, str] = Field(default_factory=dict)
    variable_values: Optional[Dict[str, Annotated[str, Field(max_length=500)]]] = None
    kb_ids: List[str] = Field(default_factory=list, max_length=20)
    access_mode: Literal["workspace_wide", "role_restricted", "user_specific"] = Field(
        "workspace_wide"
    )
    credentials: Optional[Dict[str, str]] = None  # Required when auth_mode='tenant_credentials'
    # TODO-15: Deploy wizard ACL + capabilities fields
    allowed_roles: List[str] = Field(default_factory=list)
    allowed_user_ids: List[str] = Field(default_factory=list)
    kb_search_mode: Literal["parallel", "priority"] = Field("parallel")
    rate_limit_per_minute: Optional[int] = Field(None, ge=1, le=1000)


# ---------------------------------------------------------------------------
# ATA-025: Credential deploy validation helper
# ---------------------------------------------------------------------------


def _pre_validate_credentials(
    auth_mode: str,
    required_credentials: list,
    provided_credentials: Optional[Dict[str, str]],
) -> None:
    """
    Pure validation — raises HTTPException 422 if credentials are invalid.
    No vault or DB interaction. Call this BEFORE inserting the agent card so
    that a 422 does not leave an orphaned agent row.
    """
    if not auth_mode or auth_mode == "none":
        return

    if auth_mode == "platform_credentials":
        # Platform credentials are resolved server-side from the vault at runtime.
        # The health pre-check happens in _validate_and_store_credentials.
        return

    if auth_mode == "tenant_credentials":
        required_keys = [
            c["key"] for c in (required_credentials or [])
            if c.get("required", False)
        ]
        provided = provided_credentials or {}
        missing = sorted([k for k in required_keys if k not in provided])
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required credentials: {missing}",
            )


async def _validate_and_store_credentials(
    tenant_id: str,
    agent_id: str,
    auth_mode: str,
    required_credentials: list,
    provided_credentials: Optional[Dict[str, str]],
    vault_client,
    db: AsyncSession,
) -> Optional[str]:
    """
    Validate and store agent credentials in vault.

    Returns the vault path prefix if credentials were stored, None otherwise.

    SSRF note: This function does not make outbound calls. RULE A2A-04 applies
    only to credential test endpoints (separate step, not implemented here).

    Raises HTTPException 422 for:
    - auth_mode='tenant_credentials' with missing required credential keys
    (platform_credentials health check is done at call site using template_id)
    """
    if not auth_mode or auth_mode == "none":
        return None

    if auth_mode == "platform_credentials":
        # Platform credentials are stored in the platform vault, not the tenant vault.
        # Health pre-check is done at the deploy_from_library call site using template_id.
        # No vault writes needed here.
        return None

    if auth_mode == "tenant_credentials":
        required_keys = [
            c["key"] for c in (required_credentials or [])
            if c.get("required", False)
        ]
        provided = provided_credentials or {}
        missing = sorted([k for k in required_keys if k not in provided])

        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required credentials: {missing}",
            )

        # Validate key names before constructing vault paths — prevents path traversal.
        # Key names must be alphanumeric + underscore only (no slashes, dots, or special chars).
        invalid_keys = [k for k in provided if not _VALID_CRED_KEY_RE.match(k)]
        if invalid_keys:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid credential key names (must match ^[a-zA-Z_][a-zA-Z0-9_]*$): {sorted(invalid_keys)}",
            )

        vault_path_prefix = f"{tenant_id}/agents/{agent_id}"
        if vault_client is not None and provided:
            for key, value in provided.items():
                vault_client.store_secret(f"{vault_path_prefix}/{key}", value)

        await db.execute(
            text(
                "UPDATE agent_cards SET credentials_vault_path = :path "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {"path": vault_path_prefix, "id": agent_id, "tenant_id": tenant_id},
        )

        return vault_path_prefix

    return None


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
            "WHERE tenant_id = :tenant_id AND status IN ('published', 'draft', 'active')"
        ),
        {"tenant_id": tenant_id},
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        text(
            "SELECT id, name, description, system_prompt, capabilities, status, version, created_at "
            "FROM agent_cards "
            "WHERE tenant_id = :tenant_id AND status IN ('published', 'draft', 'active') "
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
    import uuid as _uuid_mod

    try:
        _uuid_mod.UUID(template_id)
    except ValueError:
        return None

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
    allowed_roles: list | None = None,
    allowed_user_ids: list | None = None,
) -> dict:
    """
    Insert a new published agent_cards row from a template deployment.

    RULE A2A-03: access_control and kb_ids are enforced via a 422 gate at the route
    handler layer until Phase A enforcement (ATA-006–ATA-009) is fully deployed.
    Once enforcement is confirmed in staging, the gate is removed in ATA-057 and
    these values will be persisted and enforced at runtime.
    """
    agent_id = str(uuid.uuid4())
    # Per ADR-01: kb_ids are stored inside the capabilities JSONB (no join table).
    # Normalise capabilities to a dict so kb_ids, guardrails, and access_mode can
    # all live in the same JSONB column — matching the Agent Studio path.
    # If capabilities is a list (seed template format), wrap it.
    if isinstance(capabilities, list):
        capabilities = {"feature_tags": capabilities}
    capabilities["kb_ids"] = kb_ids  # always set — may be [] for no-KB agents
    capabilities_json = json.dumps(capabilities)
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

    # INSERT access control record in the same transaction as the agent row.
    # Removing the intermediate commit prevents an orphaned agent with no ACL
    # row if a crash occurs between the two INSERTs.
    visibility_mode = _ACCESS_CONTROL_MAP.get(access_control, "workspace_wide")
    await db.execute(
        text("""
            INSERT INTO agent_access_control
                (agent_id, tenant_id, visibility_mode, allowed_roles, allowed_user_ids)
            VALUES
                (:agent_id, :tenant_id, :visibility_mode, :allowed_roles, :allowed_user_ids)
            ON CONFLICT (tenant_id, agent_id) DO NOTHING
        """),
        {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "visibility_mode": visibility_mode,
            "allowed_roles": list(allowed_roles or []),
            "allowed_user_ids": list(allowed_user_ids or []),
        },
    )
    await db.commit()

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
        del private_key_enc  # Zeroize key material — do not leave in scope after DB write
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
            "status, version, category, created_at, "
            "template_type, llm_policy, kb_policy, attached_skills, attached_tools, a2a_interface "
            "FROM agent_cards "
            f"WHERE tenant_id = :platform_tenant_id {status_condition} "  # noqa: S608
            "ORDER BY created_at DESC"
        ),
        params,
    )

    _DEFAULT_LLM_POLICY = {"tenant_can_override": True, "defaults": {"temperature": 0.3, "max_tokens": 2000}}
    _DEFAULT_KB_POLICY = {"ownership": "tenant_managed", "recommended_categories": [], "required_kb_ids": []}
    _DEFAULT_A2A_INTERFACE = {"a2a_enabled": False, "operations": [], "auth_required": False}

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
                # TODO-14: rich card fields
                "template_type": row["template_type"] or "rag",
                "llm_policy": _parse_jsonb(row["llm_policy"], _DEFAULT_LLM_POLICY),
                "kb_policy": _parse_jsonb(row["kb_policy"], _DEFAULT_KB_POLICY),
                "attached_skills": _parse_jsonb(row["attached_skills"], []),
                "attached_tools": _parse_jsonb(row["attached_tools"], []),
                "a2a_interface": _parse_jsonb(row["a2a_interface"], _DEFAULT_A2A_INTERFACE),
                "plan_required": capabilities.get("plan_required") if isinstance(capabilities, dict) else None,
                "auth_mode": capabilities.get("auth_mode", "none") if isinstance(capabilities, dict) else "none",
                "icon": None,
                "tags": [],
                "instance_count": adoption_count,
            }
        )
    return items


async def list_studio_templates_for_ta(
    caller_plan: str,
    caller_tenant_id: str,
    db: AsyncSession,
) -> List[dict]:
    """TODO-14: Return Published agent_templates for TA catalog view.

    These are templates authored via PA Template Studio (TODO-20).
    All Published templates are returned regardless of plan_required — the
    frontend renders a plan-gated lock for templates the caller cannot deploy.
    """
    _DEFAULT_LLM_POLICY = {"tenant_can_override": True, "defaults": {"temperature": 0.3, "max_tokens": 2000}}
    _DEFAULT_KB_POLICY = {"ownership": "tenant_managed", "recommended_categories": [], "required_kb_ids": []}
    _DEFAULT_A2A_INTERFACE = {"a2a_enabled": False, "operations": [], "auth_required": False}

    result = await db.execute(
        text(
            "SELECT id, name, description, category, icon, tags, system_prompt, "
            "template_type, llm_policy, kb_policy, attached_skills, attached_tools, "
            "a2a_interface, plan_required, auth_mode, version, status, "
            "confidence_threshold, guardrails "
            "FROM agent_templates "
            "WHERE status = 'Published' "
            "ORDER BY created_at DESC"
        )
    )

    items = []
    for row in result.mappings():
        # Count instances deployed by this tenant from this template
        instance_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM agent_cards "
                "WHERE template_id = :template_id AND tenant_id = :tenant_id"
            ),
            {"template_id": str(row["id"]), "tenant_id": caller_tenant_id},
        )
        instance_count = instance_result.scalar() or 0

        items.append(
            {
                "id": str(row["id"]),
                "name": row["name"],
                "description": row["description"] or "",
                "category": row["category"] or "Custom",
                "icon": row["icon"],
                "tags": _parse_jsonb(row["tags"], []),
                "template_type": row["template_type"] or "rag",
                "llm_policy": _parse_jsonb(row["llm_policy"], _DEFAULT_LLM_POLICY),
                "kb_policy": _parse_jsonb(row["kb_policy"], _DEFAULT_KB_POLICY),
                "attached_skills": _parse_jsonb(row["attached_skills"], []),
                "attached_tools": _parse_jsonb(row["attached_tools"], []),
                "a2a_interface": _parse_jsonb(row["a2a_interface"], _DEFAULT_A2A_INTERFACE),
                "plan_required": row["plan_required"],
                "auth_mode": row["auth_mode"] or "none",
                "version": row["version"],
                "status": row["status"],
                "instance_count": instance_count,
                "is_seed": False,
                "is_platform": True,
                "is_studio_template": True,
            }
        )
    return items


def _get_platform_tenant_id() -> Optional[str]:
    """Return PLATFORM_TENANT_ID env var. Returns None if not set or not a valid UUID."""
    val = os.environ.get("PLATFORM_TENANT_ID", "")
    if not val:
        return None
    try:
        import uuid as _uuid

        _uuid.UUID(val)
        return val
    except ValueError:
        return None


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

    # 1. Platform templates from DB (skip if PLATFORM_TENANT_ID not configured)
    if platform_tenant_id is not None:
        platform_items = await list_platform_templates_db(
            platform_tenant_id=platform_tenant_id,
            status_filter=template_status,
            category_filter=category,
            plan_tier_filter=plan_tier,
            is_platform_admin=is_platform_admin,
            caller_plan=current_user.plan,
            db=session,
        )
    else:
        platform_items = []

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

    # 5. TODO-14: For tenant admins, include Published agent_templates from PA Template Studio
    if not is_platform_admin and is_tenant_admin:
        studio_items = await list_studio_templates_for_ta(
            caller_plan=current_user.plan or "starter",
            caller_tenant_id=current_user.tenant_id,
            db=session,
        )
        # Deduplicate by name (case-insensitive) — studio templates take precedence
        existing_names = {item["name"].lower() for item in all_items}
        for item in studio_items:
            if item["name"].lower() not in existing_names:
                all_items.append(item)

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
    # Check seed templates first — enrich with variable_schema and changelog for detail panel
    if template_id in _SEED_BY_ID:
        seed = dict(_SEED_BY_ID[template_id])
        seed["variable_schema"] = _extract_variable_schema(seed.get("system_prompt", ""))
        seed["changelog"] = []
        return seed

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

    # RULE A2A-03: Return 422 for access-restricted or KB-bound deploys.
    # This gate will be removed in ATA-057 once Phase A enforcement (ATA-006–ATA-009) is live.
    # Note: ATA-003 covers access_control and kb_ids fields only.
    # platform_credentials interim 422 is handled separately in ATA-025.
    if body.access_control not in ("workspace", None) or body.kb_ids:
        raise HTTPException(
            status_code=422,
            detail=(
                "Access-restricted and KB-bound agent deployment is not yet available. "
                "Deploy with access_control='workspace' and no kb_ids."
            ),
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
        allowed_roles=body.allowed_roles,
        allowed_user_ids=body.allowed_user_ids,
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
            "SELECT id, name, description, category, source, status, version, "
            "template_id, template_name, created_at "
            "FROM agent_cards "
            "WHERE tenant_id = :tenant_id AND status = :status "
            "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        )
        params["status"] = status_filter
    else:
        count_sql = "SELECT COUNT(*) FROM agent_cards WHERE tenant_id = :tenant_id"
        rows_sql = (
            "SELECT id, name, description, category, source, status, version, "
            "template_id, template_name, created_at "
            "FROM agent_cards "
            "WHERE tenant_id = :tenant_id "
            "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        )

    count_result = await db.execute(text(count_sql), params)
    total = count_result.scalar() or 0

    rows_result = await db.execute(text(rows_sql), params)
    rows = list(rows_result.mappings())

    if not rows:
        return {"items": [], "total": total}

    agent_ids = [str(r["id"]) for r in rows]

    # Batch satisfaction_rate_7d — one query for all agents on this page
    sr_batch_result = await db.execute(
        text(
            "SELECT c.agent_id, "
            "  COUNT(*) FILTER (WHERE uf.rating = 1) AS positive, "
            "  COUNT(*) AS total "
            "FROM user_feedback uf "
            "JOIN messages m ON m.id = uf.message_id "
            "JOIN conversations c ON c.id = m.conversation_id "
            "WHERE c.agent_id = ANY(CAST(:agent_ids AS uuid[])) "
            "AND c.tenant_id = :tenant_id "
            "AND uf.created_at >= NOW() - INTERVAL '7 days' "
            "GROUP BY c.agent_id"
        ),
        {"agent_ids": agent_ids, "tenant_id": tenant_id},
    )
    sr_by_agent: dict = {}
    for sr_row in sr_batch_result.mappings():
        aid = str(sr_row["agent_id"])
        total_ratings = int(sr_row["total"])
        if total_ratings > 0:
            sr_by_agent[aid] = round(int(sr_row["positive"]) / total_ratings * 100, 1)
        else:
            sr_by_agent[aid] = None

    # Batch session_count_7d — one query for all agents on this page
    sc_batch_result = await db.execute(
        text(
            "SELECT c.agent_id, COUNT(DISTINCT c.id) AS session_count "
            "FROM conversations c "
            "WHERE c.agent_id = ANY(CAST(:agent_ids AS uuid[])) "
            "AND c.tenant_id = :tenant_id "
            "AND c.created_at >= NOW() - INTERVAL '7 days' "
            "GROUP BY c.agent_id"
        ),
        {"agent_ids": agent_ids, "tenant_id": tenant_id},
    )
    sc_by_agent: dict = {}
    for sc_row in sc_batch_result.mappings():
        sc_by_agent[str(sc_row["agent_id"])] = int(sc_row["session_count"])

    items = []
    for row in rows:
        agent_id_str = str(row["id"])
        items.append(
            {
                "id": agent_id_str,
                "name": row["name"],
                "description": row["description"],
                "category": row["category"],
                "source": row["source"],
                "status": row["status"],
                "version": row["version"],
                "template_id": row["template_id"],
                "template_name": row["template_name"],
                "satisfaction_rate_7d": sr_by_agent.get(agent_id_str),
                "session_count_7d": sc_by_agent.get(agent_id_str, 0),
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
    access_mode: str = "workspace_wide",
    allowed_roles: Optional[List[str]] = None,
    allowed_user_ids: Optional[List[str]] = None,
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
    # INSERT ACL row in the same transaction as the agent row.
    # access_mode already uses DB values (workspace_wide/role_restricted/user_specific).
    visibility_mode = access_mode if access_mode in (
        "workspace_wide", "role_restricted", "user_specific"
    ) else "workspace_wide"
    await db.execute(
        text("""
            INSERT INTO agent_access_control
                (agent_id, tenant_id, visibility_mode, allowed_roles, allowed_user_ids)
            VALUES
                (:agent_id, :tenant_id, :visibility_mode, :allowed_roles, :allowed_user_ids)
            ON CONFLICT (tenant_id, agent_id) DO NOTHING
        """),
        {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "visibility_mode": visibility_mode,
            "allowed_roles": list(allowed_roles or []),
            "allowed_user_ids": list(allowed_user_ids or []),
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
            "credentials_vault_path, created_at, updated_at "
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
        # has_credentials: True if vault path is set; vault path itself is NOT exposed
        "has_credentials": row["credentials_vault_path"] is not None,
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
    template_name: str,
    name: str,
    system_prompt: str,
    description: str,
    category: Optional[str],
    capabilities: list,
    created_by: str,
    db: AsyncSession,
    access_mode: str = "workspace_wide",
    kb_ids: Optional[List[str]] = None,
    allowed_roles: list = None,
    allowed_user_ids: list = None,
    kb_search_mode: str = "parallel",
    rate_limit_per_minute: Optional[int] = None,
) -> dict:
    """Create a new published agent from a library or seed template (API-073)."""
    agent_id = str(uuid.uuid4())
    # Normalise mutable defaults
    if allowed_roles is None:
        allowed_roles = []
    if allowed_user_ids is None:
        allowed_user_ids = []
    # Per ADR-01: kb_ids are stored inside the capabilities JSONB (no join table).
    # Normalise capabilities to a dict so kb_ids can coexist with feature_tags.
    if isinstance(capabilities, list):
        capabilities = {"feature_tags": capabilities}
    capabilities["kb_ids"] = list(kb_ids or [])
    # TODO-15: store deploy-wizard settings inside capabilities JSONB
    capabilities["kb_search_mode"] = kb_search_mode
    if rate_limit_per_minute is not None:
        capabilities["rate_limit_per_minute"] = rate_limit_per_minute
    capabilities_json = json.dumps(capabilities)
    await db.execute(
        text(
            "INSERT INTO agent_cards "
            "(id, tenant_id, name, description, category, system_prompt, "
            "capabilities, status, version, source, template_id, template_version, "
            "template_name, created_by) "
            "VALUES (:id, :tenant_id, :name, :description, :category, :system_prompt, "
            "CAST(:capabilities AS jsonb), 'active', 1, 'library', "
            ":template_id, :template_version, :template_name, :created_by)"
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
            "template_name": template_name,
            "created_by": created_by,
        },
    )
    # INSERT ACL row in the same transaction as the agent row.
    # access_mode already uses DB values (workspace_wide/role_restricted/user_specific).
    visibility_mode = access_mode if access_mode in (
        "workspace_wide", "role_restricted", "user_specific"
    ) else "workspace_wide"
    await db.execute(
        text("""
            INSERT INTO agent_access_control
                (agent_id, tenant_id, visibility_mode, allowed_roles, allowed_user_ids)
            VALUES
                (:agent_id, :tenant_id, :visibility_mode, :allowed_roles, :allowed_user_ids)
            ON CONFLICT (tenant_id, agent_id) DO NOTHING
        """),
        {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "visibility_mode": visibility_mode,
            "allowed_roles": list(allowed_roles),
            "allowed_user_ids": list(allowed_user_ids),
        },
    )
    # Commit agent + ACL together — keypair generation is best-effort after commit.
    await db.commit()
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
        del private_key_enc  # Zeroize key material — do not leave in scope after DB write
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

    # Fetch created_at from the inserted row
    ts_result = await db.execute(
        text(
            "SELECT created_at FROM agent_cards "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": agent_id, "tenant_id": tenant_id},
    )
    ts_row = ts_result.mappings().first()
    created_at = str(ts_row["created_at"]) if ts_row else None

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
        "template_name": template_name,
        "status": "active",
        "created_at": created_at,
    }


async def _is_agent_template_deprecated(
    template_id: str, db: AsyncSession
) -> bool:
    """
    ATA-058: Return True if the template exists in agent_templates with status='Deprecated'.

    Used to surface a specific 422 instead of a generic 404 when a caller
    tries to deploy a deprecated template.
    """
    if not _UUID_RE.match(str(template_id)):
        return False
    result = await db.execute(
        text(
            "SELECT 1 FROM agent_templates WHERE id = :id AND status = 'Deprecated'"
        ),
        {"id": template_id},
    )
    return result.first() is not None


async def _get_agent_template_by_id(
    template_id: str, db: AsyncSession
) -> Optional[dict]:
    """
    PA-023: Look up an agent_templates row (from PA-019 table) by id.

    Only returns Published or seed templates — Draft and Deprecated cannot be deployed.
    Returns None if not found, not in a deployable status, or if template_id is not a
    valid UUID (e.g. seed IDs like 'seed-hr' fall through to the seed check instead).
    """
    if not _UUID_RE.match(str(template_id)):
        return None
    result = await db.execute(
        text(
            "SELECT id, name, description, category, system_prompt, "
            "variable_definitions, guardrails, confidence_threshold, version, "
            "auth_mode, required_credentials "
            "FROM agent_templates "
            "WHERE id = :id AND status IN ('Published', 'seed')"
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
        "version": row["version"],
        "auth_mode": row["auth_mode"] or "none",
        "required_credentials": row["required_credentials"] or [],
    }


async def _validate_kb_ids_for_tenant(
    kb_ids: list, tenant_id: str, db: AsyncSession
) -> None:
    """
    PA-023: Validate that all kb_ids belong to the calling tenant.

    Raises HTTPException 403 if any kb_id is not found in `integrations`
    for this tenant (prevents cross-tenant KB linking).
    """
    if not kb_ids:
        return
    # Validate UUIDs before querying
    for kb_id in kb_ids:
        if not _UUID_RE.match(str(kb_id)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"kb_id '{kb_id}' is not a valid UUID.",
            )

    result = await db.execute(
        text(
            "SELECT id FROM integrations "
            "WHERE tenant_id = :tenant_id "
            "AND id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"tenant_id": tenant_id, "ids": kb_ids},
    )
    found_ids = {str(r["id"]) for r in result.mappings()}
    missing = [k for k in kb_ids if str(k) not in found_ids]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="One or more kb_ids do not belong to this workspace.",
        )


def _substitute_variables(prompt: str, variables: dict) -> str:
    """Replace {{variable_name}} placeholders.

    Only alphanumeric/underscore variable names are substituted to prevent
    injection via malformed placeholder names.  Control characters (including
    newlines) are stripped from substituted values to prevent newline-based
    instruction injection into system prompts (CWE-93).
    """
    for key, value in variables.items():
        if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", key):
            safe_value = _CTRL_CHAR_RE.sub("", str(value))
            prompt = prompt.replace("{{" + key + "}}", safe_value)
    return prompt


# ---------------------------------------------------------------------------
# Admin route handlers (API-069 to API-073)
# ---------------------------------------------------------------------------


@admin_router.get("")
async def list_workspace_agents(
    status: Optional[str] = Query(
        None,
        description="Filter by status: draft|published|unpublished|active|paused|archived",
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


@admin_router.get("/{agent_id}")
async def get_agent_detail(
    agent_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """ATA-025: Get a single agent's detail. Returns has_credentials (bool) but NOT vault path."""
    agent = await get_agent_by_id_db(agent_id, current_user.tenant_id, session)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )
    return agent


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
        access_mode=body.access_mode,
        allowed_roles=body.allowed_roles,
        allowed_user_ids=body.allowed_user_ids,
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
    """
    API-073 / PA-023: Deploy an agent from the template library.

    Template resolution priority:
    1. agent_templates table (PA-019) — if template_id is a UUID found there
    2. Legacy seed templates (hardcoded SEED_TEMPLATES)
    3. Legacy agent_cards platform templates (status='published')

    For agent_templates sources, required variables are validated and kb_ids are
    checked for tenant ownership before deployment.
    """
    template_id = body.template_id
    # variable_values takes priority over legacy variables field
    effective_vars = (
        body.variable_values if body.variable_values is not None else body.variables
    )
    template_display_name: str = ""
    # ATA-025: track auth_mode and required_credentials from the template
    _tmpl_auth_mode: str = "none"
    _tmpl_required_credentials: list = []

    # 1. Check agent_templates (PA-019) first
    agent_tmpl = await _get_agent_template_by_id(template_id, session)
    # ATA-058: surface a specific 422 when the template exists but is Deprecated
    if agent_tmpl is None and await _is_agent_template_deprecated(template_id, session):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Template has been deprecated and is no longer available.",
        )
    if agent_tmpl is not None:
        # Validate required variables
        var_defs = agent_tmpl.get("variable_definitions") or []
        for var_def in var_defs:
            if var_def.get("required") and var_def["name"] not in effective_vars:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Missing required variable: '{var_def['name']}'.",
                )
        # Validate kb_ids belong to this tenant
        await _validate_kb_ids_for_tenant(body.kb_ids, current_user.tenant_id, session)

        source_version = agent_tmpl["version"]
        system_prompt = _substitute_variables(
            agent_tmpl["system_prompt"], effective_vars
        )
        description = body.description or agent_tmpl.get("description") or ""
        category = agent_tmpl.get("category")
        template_display_name = agent_tmpl["name"]
        # Store kb_ids in capabilities for this agent
        capabilities = [
            {"type": "knowledge_base", "id": kb_id} for kb_id in body.kb_ids
        ]
        _tmpl_auth_mode = agent_tmpl.get("auth_mode") or "none"
        _tmpl_required_credentials = agent_tmpl.get("required_credentials") or []

    elif template_id in _SEED_BY_ID:
        # 2. Legacy seed
        tmpl = _SEED_BY_ID[template_id]
        source_version = tmpl.get("version", 1)
        system_prompt = _substitute_variables(tmpl["system_prompt"], effective_vars)
        description = body.description or tmpl.get("description", "")
        category = tmpl.get("category")
        template_display_name = tmpl.get("name", template_id)
        capabilities = tmpl.get("capabilities", [])
    else:
        # 3. Legacy agent_cards platform templates — scoped to PLATFORM_TENANT_ID only.
        # Templates from other tenants must not be deployable cross-tenant.
        ptid = _get_platform_tenant_id()
        if ptid is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template '{template_id}' not found",
            )
        db_result = await session.execute(
            text(
                "SELECT id, name, description, system_prompt, capabilities, version, category "
                "FROM agent_cards "
                "WHERE id = :id AND tenant_id = :platform_tenant_id AND status = 'published'"
            ),
            {"id": template_id, "platform_tenant_id": ptid},
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
        system_prompt = _substitute_variables(db_row["system_prompt"], effective_vars)
        description = body.description or db_row["description"] or ""
        category = db_row["category"]
        template_display_name = db_row["name"] or template_id
        capabilities = caps if isinstance(caps, list) else []

    # ATA-025: pre-validate credentials BEFORE inserting the agent card so that
    # a 422 does not leave an orphaned agent row in the DB.
    _pre_validate_credentials(
        auth_mode=_tmpl_auth_mode,
        required_credentials=_tmpl_required_credentials,
        provided_credentials=body.credentials,
    )

    # TODO-47: For platform_credentials templates, check vault completeness before deployment.
    # Uses template_id (not agent_id) since credentials are stored per-template, not per-agent.
    if _tmpl_auth_mode == "platform_credentials" and _tmpl_required_credentials:
        from app.modules.agents.credential_manager import get_platform_credential_health
        _cred_keys: list[str] = []
        for _c in _tmpl_required_credentials:
            if isinstance(_c, dict):
                _cred_keys.append(_c.get("key") or _c.get("name") or "")
            elif isinstance(_c, str):
                _cred_keys.append(_c)
        _cred_keys = [k for k in _cred_keys if k]
        if _cred_keys:
            _health = await get_platform_credential_health(
                template_id=template_id,
                required_keys=_cred_keys,
            )
            _missing = [k for k, st in _health["keys"].items() if st in ("missing", "revoked")]
            if _missing:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Cannot deploy: missing platform credentials: {_missing}",
                )

    result = await deploy_from_library_db(
        tenant_id=current_user.tenant_id,
        template_id=template_id,
        template_version=source_version,
        template_name=template_display_name,
        name=body.name,
        system_prompt=system_prompt,
        description=description,
        category=category,
        capabilities=capabilities,
        created_by=current_user.id,
        db=session,
        access_mode=body.access_mode,
        kb_ids=body.kb_ids,
        allowed_roles=body.allowed_roles,
        allowed_user_ids=body.allowed_user_ids,
        kb_search_mode=body.kb_search_mode,
        rate_limit_per_minute=body.rate_limit_per_minute,
    )

    # ATA-025: store credentials to vault (agent_id is now available after INSERT)
    if _tmpl_auth_mode and _tmpl_auth_mode != "none":
        from app.core.secrets.vault_client import get_vault_client as _get_vault_client
        _vault = _get_vault_client()
        await _validate_and_store_credentials(
            tenant_id=current_user.tenant_id,
            agent_id=result["id"],
            auth_mode=_tmpl_auth_mode,
            required_credentials=_tmpl_required_credentials,
            provided_credentials=body.credentials,
            vault_client=_vault,
            db=session,
        )
        await session.commit()

    await insert_audit_log(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="agent_deployed_from_library",
        resource_type="agent",
        resource_id=result["id"],
        details={"template_id": template_id, "name": body.name},
        db=session,
    )
    # TODO-15: best-effort cache invalidation so agent list caches are flushed
    try:
        import json as _json

        from app.core.redis_client import build_redis_key, get_redis

        _redis = get_redis()
        cache_key = build_redis_key(
            current_user.tenant_id, "cache-invalidate-agents"
        )
        await _redis.publish(
            cache_key,
            _json.dumps(
                {
                    "event": "agent_deployed",
                    "agent_id": result["id"],
                    "tenant_id": current_user.tenant_id,
                }
            ),
        )
    except Exception:
        pass  # Cache invalidation is best-effort — do not block deploy success
    return result


# ---------------------------------------------------------------------------
# TODO-15: Test credentials endpoint (Step 4 of deploy wizard)
# ---------------------------------------------------------------------------


class TestCredentialsRequest(BaseModel):
    template_id: str
    credentials: Dict[str, str]


@admin_router.post("/test-credentials")
async def test_agent_credentials(
    body: TestCredentialsRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
):
    """Test credentials before deploy (Step 4 of wizard). 15s hard timeout."""
    from app.modules.agents.credential_manager import test_credentials

    result = await test_credentials(
        template_id=body.template_id,
        credentials=body.credentials,
    )
    return {
        "passed": result.passed,
        "error_message": result.error_message,
        "latency_ms": result.latency_ms,
    }


# ---------------------------------------------------------------------------
# TA-024: Template upgrade workflow
# GET  /admin/agents/{id}/upgrade-available — check if newer template version exists
# PATCH /admin/agents/{id}/upgrade           — upgrade to latest published template version
# ---------------------------------------------------------------------------


async def _get_latest_published_template_version(
    template_id: str, db: AsyncSession
) -> Optional[dict]:
    """
    Return the highest-version Published (or seed) row for the given template family.

    The family is defined as: root row (parent_id IS NULL) OR any child row whose
    parent_id = template_id.  We pick the row with the highest version number.

    Returns a dict with keys: id, name, version, changelog (may be None), or None
    if no Published/seed row exists for this template family.
    """
    if not _UUID_RE.match(str(template_id)):
        return None
    # Normalize to root id: if this is a child row, follow parent_id up one level.
    # This ensures we always search the full family (root + all children).
    root_result = await db.execute(
        text(
            "SELECT COALESCE(parent_id, id) AS root_id "
            "FROM agent_templates WHERE id = :tid"
        ),
        {"tid": template_id},
    )
    root_row = root_result.fetchone()
    if root_row is None:
        return None
    root_id = str(root_row[0])

    result = await db.execute(
        text(
            "SELECT id, name, version, changelog "
            "FROM agent_templates "
            "WHERE status IN ('Published', 'seed') "
            "AND (id = :root_id OR parent_id = :root_id) "
            "ORDER BY version DESC "
            "LIMIT 1"
        ),
        {"root_id": root_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "version": row["version"],
        "changelog": row["changelog"],
    }


@admin_router.get("/{agent_id}/upgrade-available")
async def check_agent_upgrade_available(
    agent_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TA-024: Check whether a newer Published version of the agent's source template exists.

    Compares agent_cards.template_version against the highest Published version in the
    agent_templates family (root row + all sibling drafts published as new versions).

    Returns:
      { "upgrade_available": true,  "current_version": N, "available_version": M, "changelog": "..." }
      { "upgrade_available": false }

    If the agent has no template_id (custom/seed agent), returns upgrade_available: false.
    """
    # Set tenant RLS context
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": current_user.tenant_id},
    )
    # Set tenant scope so agent_templates RLS policy allows SELECT
    await session.execute(
        text("SELECT set_config('app.current_scope', 'tenant', true)")
    )

    agent = await get_agent_by_id_db(agent_id, current_user.tenant_id, session)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    template_id = agent.get("template_id")
    if template_id is None:
        logger.info(
            "agent_upgrade_check_no_template",
            agent_id=agent_id,
            tenant_id=current_user.tenant_id,
        )
        return {"upgrade_available": False}

    current_version = agent.get("template_version") or 0

    latest = await _get_latest_published_template_version(str(template_id), session)
    if latest is None or latest["version"] <= current_version:
        logger.info(
            "agent_upgrade_check_no_upgrade",
            agent_id=agent_id,
            tenant_id=current_user.tenant_id,
            template_id=str(template_id),
            current_version=current_version,
        )
        return {"upgrade_available": False}

    # changelog: prefer the changelog column, fall back to description via name
    changelog = latest.get("changelog") or ""

    logger.info(
        "agent_upgrade_available",
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        template_id=str(template_id),
        current_version=current_version,
        available_version=latest["version"],
    )
    return {
        "upgrade_available": True,
        "current_version": current_version,
        "available_version": latest["version"],
        "changelog": changelog,
    }


@admin_router.patch("/{agent_id}/upgrade")
async def upgrade_agent_template(
    agent_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TA-024: Upgrade an agent's template reference to the latest Published version.

    This is a metadata-only upgrade — it updates template_version and template_name
    on the agent_cards row to match the latest Published version in the template
    family.  The agent's system_prompt is NOT changed by this operation: the prompt
    was already variable-substituted at deploy time, so re-substituting it here
    would require the original variable values, which are not stored on the agent
    row.  If the tenant admin wants the new prompt text they should re-deploy from
    the library using POST /admin/agents/deploy with the desired variable values.

    Returns 409 Conflict if the agent is already on the latest version (or has no
    template_id).
    """
    # Set tenant RLS context
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": current_user.tenant_id},
    )
    await session.execute(
        text("SELECT set_config('app.current_scope', 'tenant', true)")
    )

    agent = await get_agent_by_id_db(agent_id, current_user.tenant_id, session)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    template_id = agent.get("template_id")
    if template_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent has no associated template — upgrade is not applicable.",
        )

    current_version = agent.get("template_version") or 0
    latest = await _get_latest_published_template_version(str(template_id), session)

    if latest is None or latest["version"] <= current_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent is already on the latest template version.",
        )

    new_version = latest["version"]
    new_template_name = latest["name"]

    result = await session.execute(
        text(
            "UPDATE agent_cards "
            "SET template_version = :new_version, "
            "template_name = :new_template_name, "
            "updated_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {
            "new_version": new_version,
            "new_template_name": new_template_name,
            "id": agent_id,
            "tenant_id": current_user.tenant_id,
        },
    )
    if (result.rowcount or 0) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )
    await session.commit()

    await insert_audit_log(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="agent_template_upgraded",
        resource_type="agent",
        resource_id=agent_id,
        details={
            "template_id": str(template_id),
            "old_version": current_version,
            "new_version": new_version,
        },
        db=session,
    )

    logger.info(
        "agent_template_upgraded",
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        template_id=str(template_id),
        old_version=current_version,
        new_version=new_version,
    )
    return {"id": agent_id, "template_version": new_version, "upgraded": True}


# ---------------------------------------------------------------------------
# TA-023: Agent test harness — POST /admin/agents/{id}/test
# Runs a one-shot query against the agent's KB + LLM without writing to DB.
# ---------------------------------------------------------------------------


@admin_router.post("/{agent_id}/test")
async def test_agent(
    agent_id: str,
    body: AgentTestRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TA-023: Run a one-shot test query against an agent.

    Uses the agent's system_prompt and KB (via vector search) to produce a
    response, but writes nothing to conversations, messages, or user_feedback.
    Returns answer, sources, confidence, token counts, and latency_ms.
    Wraps the LLM call with a 30-second timeout — raises 504 on timeout.
    """
    import asyncio
    import os
    import time

    # 1. Fetch agent — 404 if not found for this tenant
    agent = await get_agent_by_id_db(agent_id, current_user.tenant_id, session)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    system_prompt = agent.get("system_prompt") or ""

    # 2. Extract KB ids from capabilities
    capabilities = agent.get("capabilities") or []
    kb_ids: list = []
    if isinstance(capabilities, list):
        for cap in capabilities:
            if isinstance(cap, dict) and cap.get("type") == "knowledge_base":
                kb_ids.append(cap.get("id", ""))
    elif isinstance(capabilities, dict):
        kb_ids = capabilities.get("kb_ids", [])

    # 3. KB retrieval via vector search (best-effort — skip on any failure)
    sources: list = []
    retrieval_confidence = 0.0
    try:
        from app.modules.chat.embedding import EmbeddingService
        from app.modules.chat.vector_search import VectorSearchService

        embedding_service = EmbeddingService()
        query_vector = await embedding_service.embed(
            body.query, tenant_id=current_user.tenant_id
        )

        vector_service = VectorSearchService()
        search_results = await vector_service.search(
            query_vector=query_vector,
            tenant_id=current_user.tenant_id,
            agent_id=agent_id,
        )

        for r in search_results:
            r_dict = r.to_dict() if hasattr(r, "to_dict") else r
            sources.append(
                {
                    "doc_id": r_dict.get("document_id", ""),
                    "chunk_text": r_dict.get("content", ""),
                    "relevance_score": float(r_dict.get("score", 0.0)),
                }
            )
        retrieval_confidence = (
            min(1.0, len(search_results) * 0.2) if search_results else 0.0
        )
    except Exception as kb_err:
        logger.warning(
            "agent_test_kb_retrieval_failed",
            agent_id=agent_id,
            tenant_id=current_user.tenant_id,
            error=str(kb_err),
        )

    # 4. LLM call — non-streaming, with 30-second timeout
    model = os.environ.get("PRIMARY_MODEL", "").strip()
    if not model:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM not configured: PRIMARY_MODEL environment variable is required.",
        )

    cloud_provider = os.environ.get("CLOUD_PROVIDER", "local").strip()

    if cloud_provider == "azure":
        from openai import AsyncAzureOpenAI

        api_key = os.environ.get("AZURE_PLATFORM_OPENAI_API_KEY", "").strip()
        endpoint = os.environ.get("AZURE_PLATFORM_OPENAI_ENDPOINT", "").strip()
        api_version = os.environ.get(
            "AZURE_PLATFORM_OPENAI_API_VERSION", "2024-02-01"
        ).strip()
        llm_client = AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
        )
    else:
        from openai import AsyncOpenAI

        llm_client = AsyncOpenAI()

    start_ms = time.monotonic()

    async def _call_llm() -> dict:
        completion = await llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": body.query},
            ],
            stream=False,
        )
        answer = completion.choices[0].message.content or ""
        usage = completion.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        return {"answer": answer, "tokens_in": tokens_in, "tokens_out": tokens_out}

    try:
        llm_result = await asyncio.wait_for(_call_llm(), timeout=30.0)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Agent test timed out after 30 seconds.",
        )

    latency_ms = int((time.monotonic() - start_ms) * 1000)

    # Write last_tested_at so publish gate can verify the agent was tested.
    await session.execute(
        text(
            "UPDATE agent_cards SET last_tested_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": agent_id, "tenant_id": current_user.tenant_id},
    )

    await insert_audit_log(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="agent_test_run",
        resource_type="agent",
        resource_id=agent_id,
        details={
            "mode": "test",
            "test_as_user_id": current_user.id,
            "query_preview": body.query[:100],
        },
        db=session,
    )

    logger.info(
        "agent_test_completed",
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        latency_ms=latency_ms,
        sources_count=len(sources),
    )

    return {
        "answer": llm_result["answer"],
        "sources": sources,
        "confidence": retrieval_confidence,
        "tokens_in": llm_result["tokens_in"],
        "tokens_out": llm_result["tokens_out"],
        "latency_ms": latency_ms,
    }


# ---------------------------------------------------------------------------
# API-117: End-user agent list — GET /agents
# Lists published agents visible to any authenticated end user.
# Distinct from /admin/agents (which includes drafts + metrics).
# ---------------------------------------------------------------------------


async def list_published_agents_db(
    tenant_id: str,
    user_id: str = "",
    user_roles: list | None = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = None,
) -> dict:
    """List published agent_cards for the end-user agents list (API-117).

    # RULE A2A-01: agent list filtered by access_control — users only see agents they can access.
    Uses a LEFT JOIN against agent_access_control to apply per-agent visibility rules:
      - No ACL row → include (workspace_wide fallback)
      - workspace_wide → include for any user
      - role_restricted → include if user's roles intersect allowed_roles
      - user_specific → include if user_id is in allowed_user_ids
    """
    user_roles = user_roles or []
    offset = (page - 1) * page_size

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    # RULE A2A-01: agent list filtered by access_control — users only see agents they can access.
    # The access filter mirrors _check_agent_access in orchestrator.py.
    # LEFT JOIN means agents with no ACL row are included (workspace_wide fallback).
    access_filter_sql = (
        "LEFT JOIN agent_access_control aac "
        "  ON aac.agent_id = ac.id AND aac.tenant_id = :tenant_id "
        "WHERE ac.tenant_id = :tenant_id AND ac.status IN ('published', 'active') "
        "  AND ("
        "    aac.agent_id IS NULL"                                    # no ACL row → allow
        "    OR aac.visibility_mode = 'workspace_wide'"               # workspace_wide → allow all
        "    OR (aac.visibility_mode = 'role_restricted'"
        "        AND aac.allowed_roles && CAST(:user_roles AS VARCHAR[]))"  # role intersection
        "    OR (aac.visibility_mode = 'user_specific'"
        "        AND :user_id_cast = ANY(aac.allowed_user_ids))"      # user in list
        "  )"
    )

    count_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM agent_cards ac "
            + access_filter_sql
        ),
        {
            "tenant_id": tenant_id,
            "user_roles": list(user_roles),
            "user_id_cast": user_id,
        },
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        text(
            "SELECT ac.id, ac.name, ac.description, ac.category, ac.avatar "
            "FROM agent_cards ac "
            + access_filter_sql
            + " ORDER BY ac.name ASC LIMIT :limit OFFSET :offset"
        ),
        {
            "tenant_id": tenant_id,
            "user_roles": list(user_roles),
            "user_id_cast": user_id,
            "limit": page_size,
            "offset": offset,
        },
    )
    items = [
        {
            "id": str(row[0]),
            "name": row[1],
            "description": row[2],
            "category": row[3],
            "avatar": row[4],
        }
        for row in rows_result.fetchall()
    ]
    return {"items": items, "total": total}


@router.get("")
async def list_agents_for_user(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    List published agents available to the current authenticated user (API-117).

    End-user view — returns only published agents with name, description,
    category, and avatar. No metrics, no draft status. RLS enforces tenant scope.
    Access is filtered by agent_access_control (RULE A2A-01).
    """
    result = await list_published_agents_db(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        user_roles=current_user.roles,
        page=page,
        page_size=page_size,
        db=session,
    )
    logger.info(
        "user_agents_listed",
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        total=result["total"],
    )
    return result


# ---------------------------------------------------------------------------
# TODO-18: Custom Agent Studio endpoints
# POST /admin/agents/studio/create       — create custom agent with skills+tools
# PUT  /admin/agents/studio/{id}         — update with ETag/If-Match concurrency
# POST /admin/agents/studio/{id}/test    — test with audit log mode='test'
# POST /admin/agents/studio/{id}/publish — publish + access_control + cache inv.
# ---------------------------------------------------------------------------

# studio_router is registered under admin_router prefix /admin/agents
studio_router = APIRouter(prefix="/admin/agents/studio", tags=["admin-agents-studio"])


class SkillAttachment(BaseModel):
    """A skill attached to a custom agent, with optional pipeline trigger override."""
    skill_id: str = Field(..., min_length=1, max_length=255)
    invocation_override: Optional[str] = Field(
        None,
        max_length=500,
        description="Custom pipeline_trigger value overriding the skill's default.",
    )


class CreateCustomAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=100)
    icon: Optional[str] = Field(None, max_length=100)
    system_prompt: str = Field(..., min_length=1, max_length=3000)
    kb_ids: List[str] = Field(default_factory=list)
    attached_skills: List[SkillAttachment] = Field(default_factory=list)
    attached_tools: List[str] = Field(default_factory=list)  # tool catalog IDs
    guardrails: GuardrailsSchema = Field(default_factory=GuardrailsSchema)
    access_rules: Optional[dict] = None


class UpdateCustomAgentRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=100)
    icon: Optional[str] = Field(None, max_length=100)
    system_prompt: Optional[str] = Field(None, max_length=3000)
    kb_ids: Optional[List[str]] = None
    attached_skills: Optional[List[SkillAttachment]] = None
    attached_tools: Optional[List[str]] = None
    guardrails: Optional[GuardrailsSchema] = None


class StudioPublishRequest(BaseModel):
    access_rules: Optional[dict] = None  # {mode, allowed_roles, allowed_user_ids}


async def _validate_skill_ids_for_tenant(
    skill_ids: List[str], tenant_id: str, db: AsyncSession
) -> None:
    """
    Validate that all skill_ids are accessible to the tenant:
    - platform skills the tenant has adopted (in tenant_skill_adoptions)
    - tenant-authored skills with status='published' belonging to this tenant

    Raises HTTPException 403 if any skill is not accessible.
    """
    if not skill_ids:
        return
    for sid in skill_ids:
        if not _UUID_RE.match(str(sid)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"skill_id '{sid}' is not a valid UUID.",
            )
    skill_ids_str = [str(s) for s in skill_ids]
    # Check platform-adopted skills OR tenant-owned published skills
    result = await db.execute(
        text(
            "SELECT id FROM skills "
            "WHERE id = ANY(CAST(:ids AS uuid[])) "
            "AND ("
            "  (tenant_id IS NULL AND EXISTS ("
            "    SELECT 1 FROM tenant_skill_adoptions tsa "
            "    WHERE tsa.skill_id = skills.id AND tsa.tenant_id = :tenant_id"
            "  ))"
            "  OR (tenant_id = :tenant_id AND status = 'published')"
            ")"
        ),
        {"ids": skill_ids_str, "tenant_id": tenant_id},
    )
    found_ids = {str(r[0]) for r in result.fetchall()}
    missing = [s for s in skill_ids_str if s not in found_ids]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="One or more skill_ids are not accessible to this tenant.",
        )


async def _validate_tool_ids_for_tenant(
    tool_ids: List[str], tenant_id: str, db: AsyncSession
) -> None:
    """
    Validate that all tool_ids are accessible to the tenant:
    - platform-scoped tools (tenant_id IS NULL)
    - tenant-scoped tools belonging to this tenant

    Raises HTTPException 403 if any tool is not accessible.
    """
    if not tool_ids:
        return
    for tid in tool_ids:
        if not _UUID_RE.match(str(tid)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"tool_id '{tid}' is not a valid UUID.",
            )
    tool_ids_str = [str(t) for t in tool_ids]
    result = await db.execute(
        text(
            "SELECT id FROM tool_catalog "
            "WHERE id = ANY(CAST(:ids AS uuid[])) "
            "AND (tenant_id IS NULL OR tenant_id = :tenant_id)"
        ),
        {"ids": tool_ids_str, "tenant_id": tenant_id},
    )
    found_ids = {str(r[0]) for r in result.fetchall()}
    missing = [t for t in tool_ids_str if t not in found_ids]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="One or more tool_ids are not accessible to this tenant.",
        )


def _compute_template_type(
    attached_skills: List[SkillAttachment],
    attached_tools: List[str],
) -> str:
    """Derive template_type from skill/tool attachments."""
    if attached_tools:
        return "tool_augmented"
    if attached_skills:
        return "skill_augmented"
    return "rag"


async def _upsert_agent_skill_attachments(
    agent_id: str,
    tenant_id: str,
    attached_skills: List[SkillAttachment],
    db: AsyncSession,
) -> None:
    """
    Persist skill attachments into agent_template_skills.
    Deletes all existing rows for this agent then re-inserts (simpler than diff).
    Invocation overrides stored in invocation_override JSONB column.
    """
    # Delete existing skill associations for this agent
    await db.execute(
        text(
            "DELETE FROM agent_template_skills "
            "WHERE agent_id = CAST(:agent_id AS uuid) AND tenant_id = :tenant_id"
        ),
        {"agent_id": agent_id, "tenant_id": tenant_id},
    )
    for attachment in attached_skills:
        override_json: Optional[str] = None
        if attachment.invocation_override is not None:
            override_json = json.dumps(
                {"pipeline_trigger": attachment.invocation_override}
            )
        await db.execute(
            text(
                "INSERT INTO agent_template_skills "
                "(agent_id, skill_id, tenant_id, invocation_override) "
                "VALUES (CAST(:agent_id AS uuid), CAST(:skill_id AS uuid), "
                ":tenant_id, CAST(:override AS jsonb))"
            ),
            {
                "agent_id": agent_id,
                "skill_id": attachment.skill_id,
                "tenant_id": tenant_id,
                "override": override_json,
            },
        )


async def _invalidate_agent_cache(
    agent_id: str, tenant_id: str, redis_client=None
) -> None:
    """
    Publish a Redis Pub/Sub cache invalidation event for the agent.
    Fail-open: if Redis is unavailable, log a warning and continue.
    """
    try:
        from app.core.redis_client import build_redis_key

        channel = build_redis_key(tenant_id, "agent_invalidation", agent_id)
        if redis_client is not None:
            await redis_client.publish(channel, json.dumps({"agent_id": agent_id}))
    except Exception as exc:
        logger.warning(
            "agent_cache_invalidation_failed",
            agent_id=agent_id,
            tenant_id=tenant_id,
            error=str(exc),
        )


@studio_router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_custom_agent(
    body: CreateCustomAgentRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TODO-18: Create a custom agent from scratch with skills/tools/guardrails.

    - Runs SystemPromptValidator on system_prompt before INSERT
    - Validates all skill IDs accessible to tenant
    - Validates all tool IDs accessible to tenant
    - Persists skill attachments with invocation_override into agent_template_skills
    - Persists tool IDs into agent_cards.attached_tools JSONB
    - Sets template_type based on skills/tools presence
    """
    from app.modules.agents.prompt_validator import SKILL_PROMPT_MAX_CHARS, validate_prompt

    # 1. SystemPromptValidator — 422 on violation
    pv_result = validate_prompt(body.system_prompt, max_chars=SKILL_PROMPT_MAX_CHARS)
    if not pv_result.valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"System prompt failed validation: {pv_result.reason}",
        )

    skill_ids = [sa.skill_id for sa in body.attached_skills]
    tool_ids = body.attached_tools

    # 2. Validate skills/tools belong to the tenant
    await _validate_skill_ids_for_tenant(skill_ids, current_user.tenant_id, session)
    await _validate_tool_ids_for_tenant(tool_ids, current_user.tenant_id, session)

    template_type = _compute_template_type(body.attached_skills, tool_ids)

    # 3. Build capabilities JSONB
    capabilities = {
        "guardrails": body.guardrails.model_dump(),
        "kb_ids": body.kb_ids,
        "tool_ids": tool_ids,
        "template_type": template_type,
    }
    if body.icon:
        capabilities["icon"] = body.icon

    agent_id = str(uuid.uuid4())
    capabilities_json = json.dumps(capabilities)

    # 4. INSERT agent_cards — status='draft' for custom agents
    await session.execute(
        text(
            "INSERT INTO agent_cards "
            "(id, tenant_id, name, description, category, avatar, system_prompt, "
            "capabilities, status, version, source, template_type, created_by) "
            "VALUES (:id, :tenant_id, :name, :description, :category, :avatar, "
            ":system_prompt, CAST(:capabilities AS jsonb), 'draft', 1, 'custom', "
            ":template_type, :created_by)"
        ),
        {
            "id": agent_id,
            "tenant_id": current_user.tenant_id,
            "name": body.name,
            "description": body.description,
            "category": body.category,
            "avatar": body.icon,
            "system_prompt": body.system_prompt,
            "capabilities": capabilities_json,
            "template_type": template_type,
            "created_by": current_user.id,
        },
    )

    # 5. Insert default ACL row in the same transaction
    access_rules = body.access_rules or {}
    visibility_mode = _ACCESS_CONTROL_MAP.get(
        access_rules.get("mode", "workspace"), "workspace_wide"
    )
    await session.execute(
        text("""
            INSERT INTO agent_access_control
                (agent_id, tenant_id, visibility_mode, allowed_roles, allowed_user_ids)
            VALUES
                (:agent_id, :tenant_id, :visibility_mode, :allowed_roles, :allowed_user_ids)
            ON CONFLICT (tenant_id, agent_id) DO NOTHING
        """),
        {
            "agent_id": agent_id,
            "tenant_id": current_user.tenant_id,
            "visibility_mode": visibility_mode,
            "allowed_roles": list(access_rules.get("allowed_roles", [])),
            "allowed_user_ids": list(access_rules.get("allowed_user_ids", [])),
        },
    )
    await session.commit()

    # 6. Persist skill attachments
    await _upsert_agent_skill_attachments(
        agent_id, current_user.tenant_id, body.attached_skills, session
    )
    await session.commit()

    await insert_audit_log(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="custom_agent_created",
        resource_type="agent",
        resource_id=agent_id,
        details={
            "name": body.name,
            "template_type": template_type,
            "skill_count": len(body.attached_skills),
            "tool_count": len(tool_ids),
        },
        db=session,
    )
    logger.info(
        "custom_agent_created",
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        template_type=template_type,
    )
    return {
        "id": agent_id,
        "name": body.name,
        "status": "draft",
        "template_type": template_type,
    }


@studio_router.put("/{agent_id}")
async def update_custom_agent(
    agent_id: str,
    body: UpdateCustomAgentRequest,
    if_match: Optional[str] = None,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TODO-18: Update a custom agent.

    - Returns ETag header based on updated_at
    - Accepts If-Match header; returns 409 on conflict
    - Runs SystemPromptValidator on system_prompt if provided
    - Validates updated skills/tools
    """
    from app.modules.agents.prompt_validator import SKILL_PROMPT_MAX_CHARS, validate_prompt
    from fastapi.responses import JSONResponse

    # 1. Fetch existing agent
    existing = await get_agent_by_id_db(agent_id, current_user.tenant_id, session)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    # 2. ETag concurrency check
    updated_at_str = existing.get("updated_at", "")
    current_etag = '"' + hashlib.sha256(updated_at_str.encode()).hexdigest()[:16] + '"'
    if if_match is not None and if_match != current_etag:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ETag mismatch — agent was modified by another request. Re-fetch and retry.",
        )

    # 3. Validate system_prompt if provided
    if body.system_prompt is not None:
        pv_result = validate_prompt(body.system_prompt, max_chars=SKILL_PROMPT_MAX_CHARS)
        if not pv_result.valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"System prompt failed validation: {pv_result.reason}",
            )

    # 4. Validate skills/tools if updating them
    if body.attached_skills is not None:
        skill_ids = [sa.skill_id for sa in body.attached_skills]
        await _validate_skill_ids_for_tenant(skill_ids, current_user.tenant_id, session)

    if body.attached_tools is not None:
        await _validate_tool_ids_for_tenant(
            body.attached_tools, current_user.tenant_id, session
        )

    # 5. Compute new capabilities
    existing_caps = existing.get("capabilities") or {}
    if not isinstance(existing_caps, dict):
        existing_caps = {}

    new_kb_ids = body.kb_ids if body.kb_ids is not None else existing_caps.get("kb_ids", [])
    new_tool_ids = (
        body.attached_tools if body.attached_tools is not None
        else existing_caps.get("tool_ids", [])
    )
    new_skills = body.attached_skills if body.attached_skills is not None else None
    new_guardrails = (
        body.guardrails.model_dump() if body.guardrails is not None
        else existing_caps.get("guardrails", GuardrailsSchema().model_dump())
    )

    effective_skills = new_skills if new_skills is not None else []
    template_type = _compute_template_type(effective_skills, new_tool_ids)

    new_capabilities = {
        **existing_caps,
        "guardrails": new_guardrails,
        "kb_ids": new_kb_ids,
        "tool_ids": new_tool_ids,
        "template_type": template_type,
    }
    if body.icon is not None:
        new_capabilities["icon"] = body.icon

    # 6. Build SET clauses — only update provided fields
    set_parts = []
    params: dict = {
        "id": agent_id,
        "tenant_id": current_user.tenant_id,
        "capabilities": json.dumps(new_capabilities),
        "template_type": template_type,
    }
    set_parts.append("capabilities = CAST(:capabilities AS jsonb)")
    set_parts.append("template_type = :template_type")
    set_parts.append("updated_at = NOW()")

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
    if body.icon is not None:
        set_parts.append("avatar = :avatar")
        params["avatar"] = body.icon

    set_clause = ", ".join(set_parts)
    result = await session.execute(
        text(
            f"UPDATE agent_cards SET {set_clause} "  # noqa: S608 — only hardcoded allowlisted fragments
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        params,
    )
    if (result.rowcount or 0) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )
    await session.commit()

    # 7. Update skill attachments if provided
    if body.attached_skills is not None:
        await _upsert_agent_skill_attachments(
            agent_id, current_user.tenant_id, body.attached_skills, session
        )
        await session.commit()

    # 8. Re-fetch for new updated_at
    updated = await get_agent_by_id_db(agent_id, current_user.tenant_id, session)
    new_updated_at = updated.get("updated_at", "") if updated else ""
    new_etag = '"' + hashlib.sha256(new_updated_at.encode()).hexdigest()[:16] + '"'

    await insert_audit_log(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="custom_agent_updated",
        resource_type="agent",
        resource_id=agent_id,
        details={"name": body.name, "template_type": template_type},
        db=session,
    )
    logger.info(
        "custom_agent_updated",
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
    )
    response_data = {
        "id": agent_id,
        "version": updated.get("version") if updated else None,
        "status": updated.get("status") if updated else None,
        "updated_at": new_updated_at,
    }
    return JSONResponse(
        content=response_data,
        headers={"ETag": new_etag},
    )


@studio_router.post("/{agent_id}/test")
async def test_custom_agent_studio(
    agent_id: str,
    body: AgentTestRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TODO-18: Run a one-shot test of a custom agent draft.

    Audit log is written with mode='test' and test_as_user_id = requesting admin's own ID.
    Delegates to the existing test_agent handler logic.
    Returns: response, confidence, sources, skill_invocations, tool_calls,
             guardrail_events, latency_ms.
    """
    import asyncio
    import os
    import time

    # 1. Fetch agent — must belong to this tenant
    agent = await get_agent_by_id_db(agent_id, current_user.tenant_id, session)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    # 2. Write audit log with mode='test' BEFORE executing — so partial failures are
    #    still traceable.
    await insert_audit_log(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="agent_test_run",
        resource_type="agent",
        resource_id=agent_id,
        details={
            "mode": "test",
            "test_as_user_id": current_user.id,
            "query_preview": body.query[:100],
        },
        db=session,
    )

    system_prompt = agent.get("system_prompt") or ""
    capabilities = agent.get("capabilities") or {}
    if isinstance(capabilities, str):
        capabilities = json.loads(capabilities)
    kb_ids: list = capabilities.get("kb_ids", []) if isinstance(capabilities, dict) else []

    # 3. KB retrieval (best-effort)
    sources: list = []
    retrieval_confidence = 0.0
    try:
        from app.modules.chat.embedding import EmbeddingService
        from app.modules.chat.vector_search import VectorSearchService

        embedding_service = EmbeddingService()
        query_vector = await embedding_service.embed(
            body.query, tenant_id=current_user.tenant_id
        )
        vector_service = VectorSearchService()
        search_results = await vector_service.search(
            query_vector=query_vector,
            tenant_id=current_user.tenant_id,
            agent_id=agent_id,
        )
        for r in search_results:
            r_dict = r.to_dict() if hasattr(r, "to_dict") else r
            sources.append(
                {
                    "doc_id": r_dict.get("document_id", ""),
                    "chunk_text": r_dict.get("content", ""),
                    "relevance_score": float(r_dict.get("score", 0.0)),
                }
            )
        retrieval_confidence = (
            min(1.0, len(search_results) * 0.2) if search_results else 0.0
        )
    except Exception as kb_err:
        logger.warning(
            "studio_test_kb_retrieval_failed",
            agent_id=agent_id,
            tenant_id=current_user.tenant_id,
            error=str(kb_err),
        )

    # 4. LLM call with 30s timeout
    model = os.environ.get("PRIMARY_MODEL", "").strip()
    if not model:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM not configured: PRIMARY_MODEL environment variable is required.",
        )

    cloud_provider = os.environ.get("CLOUD_PROVIDER", "local").strip()
    if cloud_provider == "azure":
        from openai import AsyncAzureOpenAI

        llm_client = AsyncAzureOpenAI(
            api_key=os.environ.get("AZURE_PLATFORM_OPENAI_API_KEY", "").strip(),
            azure_endpoint=os.environ.get("AZURE_PLATFORM_OPENAI_ENDPOINT", "").strip(),
            api_version=os.environ.get(
                "AZURE_PLATFORM_OPENAI_API_VERSION", "2024-02-01"
            ).strip(),
        )
    else:
        from openai import AsyncOpenAI

        llm_client = AsyncOpenAI()

    start_ms = time.monotonic()

    async def _call_llm() -> dict:
        completion = await llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": body.query},
            ],
            stream=False,
        )
        answer = completion.choices[0].message.content or ""
        usage = completion.usage
        return {
            "answer": answer,
            "tokens_in": usage.prompt_tokens if usage else 0,
            "tokens_out": usage.completion_tokens if usage else 0,
        }

    try:
        llm_result = await asyncio.wait_for(_call_llm(), timeout=30.0)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Agent test timed out after 30 seconds.",
        )

    latency_ms = int((time.monotonic() - start_ms) * 1000)

    # Write last_tested_at so publish gate can verify the agent was tested.
    # MUST commit here — no subsequent insert_audit_log to trigger commit.
    await session.execute(
        text(
            "UPDATE agent_cards SET last_tested_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": agent_id, "tenant_id": current_user.tenant_id},
    )
    await session.commit()

    logger.info(
        "studio_agent_test_completed",
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        latency_ms=latency_ms,
    )
    return {
        "response": llm_result["answer"],
        "confidence": retrieval_confidence,
        "sources": sources,
        "skill_invocations": [],   # populated by SkillExecutor in Phase 2 integration
        "tool_calls": [],           # populated by ToolExecutor in Phase 2 integration
        "guardrail_events": [],     # populated by guardrail middleware in Phase 2 integration
        "tokens_in": llm_result["tokens_in"],
        "tokens_out": llm_result["tokens_out"],
        "latency_ms": latency_ms,
    }


@studio_router.post("/{agent_id}/publish")
async def publish_custom_agent(
    agent_id: str,
    body: StudioPublishRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TODO-18: Publish a custom agent draft to active.

    - Validates required fields (name, system_prompt non-empty)
    - Transitions status: draft → active
    - UPSERT agent_access_control from access_rules
    - Publishes Redis cache invalidation event
    """
    agent = await get_agent_by_id_db(agent_id, current_user.tenant_id, session)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    if not agent.get("name", "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot publish: agent name must not be empty.",
        )
    if not agent.get("system_prompt", "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot publish: system_prompt must not be empty.",
        )

    # Atomic publish gate: require at least one test run AND transition status in one UPDATE.
    # Using last_tested_at IS NOT NULL in the WHERE clause eliminates the TOCTOU race
    # that would exist if we read last_tested_at and updated status in separate statements.
    upd_result = await session.execute(
        text(
            "UPDATE agent_cards "
            "SET status = 'active', updated_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id "
            "AND last_tested_at IS NOT NULL"
        ),
        {"id": agent_id, "tenant_id": current_user.tenant_id},
    )
    if (upd_result.rowcount or 0) == 0:
        # Either agent not found OR last_tested_at IS NULL — distinguish for user message.
        check = await session.execute(
            text(
                "SELECT last_tested_at FROM agent_cards "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {"id": agent_id, "tenant_id": current_user.tenant_id},
        )
        row = check.fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent '{agent_id}' not found",
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Cannot publish: agent must be tested at least once before publishing. "
                "Use the Test button to run a test query first."
            ),
        )

    # UPSERT access control from access_rules
    access_rules = body.access_rules or {}
    visibility_mode = _ACCESS_CONTROL_MAP.get(
        access_rules.get("mode", "workspace"), "workspace_wide"
    )
    await session.execute(
        text("""
            INSERT INTO agent_access_control
                (agent_id, tenant_id, visibility_mode, allowed_roles, allowed_user_ids)
            VALUES
                (:agent_id, :tenant_id, :visibility_mode, :allowed_roles, :allowed_user_ids)
            ON CONFLICT (tenant_id, agent_id) DO UPDATE
                SET visibility_mode = EXCLUDED.visibility_mode,
                    allowed_roles = EXCLUDED.allowed_roles,
                    allowed_user_ids = EXCLUDED.allowed_user_ids
        """),
        {
            "agent_id": agent_id,
            "tenant_id": current_user.tenant_id,
            "visibility_mode": visibility_mode,
            "allowed_roles": list(access_rules.get("allowed_roles", [])),
            "allowed_user_ids": list(access_rules.get("allowed_user_ids", [])),
        },
    )
    await session.commit()

    # Cache invalidation (fail-open)
    await _invalidate_agent_cache(agent_id, current_user.tenant_id)

    await insert_audit_log(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="custom_agent_published",
        resource_type="agent",
        resource_id=agent_id,
        details={"visibility_mode": visibility_mode},
        db=session,
    )
    logger.info(
        "custom_agent_published",
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        visibility_mode=visibility_mode,
    )
    return {"id": agent_id, "status": "active"}


# ---------------------------------------------------------------------------
# TODO-19: Tenant A2A Agent Registration endpoints
# POST   /admin/agents/a2a/register         — register external A2A agent
# GET    /admin/agents/a2a/{id}/card        — return imported_card JSONB
# POST   /admin/agents/a2a/{id}/verify      — re-fetch card + health check
# DELETE /admin/agents/a2a/{id}             — soft delete (status=archived)
# ---------------------------------------------------------------------------

a2a_tenant_router = APIRouter(
    prefix="/admin/agents/a2a", tags=["admin-agents-a2a"]
)


class RegisterA2AAgentRequest(BaseModel):
    card_url: str = Field(..., min_length=8, max_length=2048, description="HTTPS URL of A2A card")
    display_name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    icon: Optional[str] = Field(None, max_length=100)
    access_rules: Optional[dict] = None


@a2a_tenant_router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_a2a_agent(
    body: RegisterA2AAgentRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TODO-19: Register an external A2A agent by fetching and validating its card.

    - Fetches agent card from card_url (SSRF-protected, HTTPS-only)
    - Validates card schema (required fields, trust_level, auth.type)
    - Inserts agent_cards row with template_type='registered_a2a', status='active'
    - Inserts access control row
    - Returns the parsed card preview
    """
    from app.modules.agents.a2a_card_fetcher import A2ACardValidationError, fetch_and_validate_card

    # Validate HTTPS scheme before fetching (belt-and-suspenders beyond a2a_card_fetcher)
    if not body.card_url.startswith("https://"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="card_url must use HTTPS.",
        )

    try:
        card = await fetch_and_validate_card(body.card_url)
    except A2ACardValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"A2A card validation failed: {exc}",
        ) from exc
    except Exception as exc:
        logger.warning(
            "a2a_card_fetch_failed",
            card_url=body.card_url,
            tenant_id=current_user.tenant_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not fetch A2A card from the provided URL. Check that the URL is reachable and returns a valid A2A card.",
        ) from exc

    agent_id = str(uuid.uuid4())
    capabilities = {
        "a2a_endpoint": card.a2a_endpoint,
        "trust_level": card.trust_level,
        "transaction_types": card.transaction_types,
        "industries": card.industries,
        "capabilities": card.capabilities,
    }
    if body.icon:
        capabilities["icon"] = body.icon

    capabilities_json = json.dumps(capabilities)
    imported_card_json = json.dumps(card.raw)

    await session.execute(
        text(
            "INSERT INTO agent_cards "
            "(id, tenant_id, name, description, avatar, system_prompt, "
            "capabilities, status, version, source, template_type, "
            "a2a_endpoint, source_card_url, imported_card, created_by) "
            "VALUES (:id, :tenant_id, :name, :description, :avatar, '', "
            "CAST(:capabilities AS jsonb), 'active', 1, 'registered_a2a', "
            "'registered_a2a', :a2a_endpoint, :source_card_url, "
            "CAST(:imported_card AS jsonb), :created_by)"
        ),
        {
            "id": agent_id,
            "tenant_id": current_user.tenant_id,
            "name": body.display_name,
            "description": body.description,
            "avatar": body.icon,
            "capabilities": capabilities_json,
            "a2a_endpoint": card.a2a_endpoint,
            "source_card_url": body.card_url,
            "imported_card": imported_card_json,
            "created_by": current_user.id,
        },
    )

    # ACL row
    access_rules = body.access_rules or {}
    visibility_mode = _ACCESS_CONTROL_MAP.get(
        access_rules.get("mode", "workspace"), "workspace_wide"
    )
    await session.execute(
        text("""
            INSERT INTO agent_access_control
                (agent_id, tenant_id, visibility_mode, allowed_roles, allowed_user_ids)
            VALUES
                (:agent_id, :tenant_id, :visibility_mode, :allowed_roles, :allowed_user_ids)
            ON CONFLICT (tenant_id, agent_id) DO NOTHING
        """),
        {
            "agent_id": agent_id,
            "tenant_id": current_user.tenant_id,
            "visibility_mode": visibility_mode,
            "allowed_roles": list(access_rules.get("allowed_roles", [])),
            "allowed_user_ids": list(access_rules.get("allowed_user_ids", [])),
        },
    )
    await session.commit()

    await insert_audit_log(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="a2a_agent_registered",
        resource_type="agent",
        resource_id=agent_id,
        details={"card_url": body.card_url, "display_name": body.display_name},
        db=session,
    )
    logger.info(
        "a2a_agent_registered",
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        card_url=body.card_url,
    )
    return {
        "id": agent_id,
        "name": body.display_name,
        "status": "active",
        "card_preview": {
            "name": card.name,
            "description": card.description,
            "a2a_endpoint": card.a2a_endpoint,
            "trust_level": card.trust_level,
            "capabilities": card.capabilities,
        },
    }


@a2a_tenant_router.get("/{agent_id}/card")
async def get_a2a_agent_card(
    agent_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """TODO-19: Return the imported_card JSONB for a registered A2A agent."""
    result = await session.execute(
        text(
            "SELECT id, name, imported_card, source_card_url, status "
            "FROM agent_cards "
            "WHERE id = :id AND tenant_id = :tenant_id "
            "AND template_type = 'registered_a2a'"
        ),
        {"id": agent_id, "tenant_id": current_user.tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"A2A agent '{agent_id}' not found",
        )
    imported_card = row["imported_card"]
    if isinstance(imported_card, str):
        imported_card = json.loads(imported_card)
    return {
        "agent_id": str(row["id"]),
        "name": row["name"],
        "card_url": row["source_card_url"],
        "status": row["status"],
        "card": imported_card,
    }


@a2a_tenant_router.post("/{agent_id}/verify")
async def verify_a2a_agent(
    agent_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TODO-19: Re-fetch agent card and ping health endpoint.
    Updates status and stores refreshed card.
    """
    from app.modules.agents.a2a_card_fetcher import A2ACardValidationError, fetch_and_validate_card
    from app.modules.agents.a2a_health_worker import check_a2a_agent_health

    # Also fetch current consecutive_failures for health check state computation
    verify_row_result = await session.execute(
        text(
            "SELECT id, source_card_url, a2a_endpoint, health_consecutive_failures "
            "FROM agent_cards "
            "WHERE id = :id AND tenant_id = :tenant_id "
            "AND template_type = 'registered_a2a'"
        ),
        {"id": agent_id, "tenant_id": current_user.tenant_id},
    )
    row = verify_row_result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"A2A agent '{agent_id}' not found",
        )

    card_url = row["source_card_url"]
    a2a_endpoint = row["a2a_endpoint"]
    current_failures = int(row["health_consecutive_failures"] or 0)

    # Re-fetch card
    card_valid = False
    card_error: str = ""
    try:
        card = await fetch_and_validate_card(card_url, timeout=10.0)
        # Update imported_card with refreshed version
        await session.execute(
            text(
                "UPDATE agent_cards "
                "SET imported_card = CAST(:card AS jsonb), updated_at = NOW() "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {
                "card": json.dumps(card.raw),
                "id": agent_id,
                "tenant_id": current_user.tenant_id,
            },
        )
        card_valid = True
    except A2ACardValidationError as exc:
        logger.warning("a2a_verify_card_invalid", agent_id=agent_id, error=str(exc))
        card_error = "A2A card validation failed."
    except Exception as exc:
        logger.warning("a2a_verify_card_fetch_failed", agent_id=agent_id, error=str(exc))
        card_error = "Could not fetch or validate the A2A card."

    # Health check — returns (new_status, new_failures, http_status) tuple
    health_status, new_failures, _http_status = await check_a2a_agent_health(
        agent_id=agent_id,
        a2a_endpoint=a2a_endpoint or card_url,
        consecutive_failures=current_failures,
    )
    health_ok = health_status == "healthy"
    new_status = "active" if (card_valid and health_ok) else "unhealthy"

    await session.execute(
        text(
            "UPDATE agent_cards "
            "SET status = :status, health_consecutive_failures = :failures, "
            "last_health_check_at = NOW(), updated_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {
            "status": new_status,
            "failures": new_failures,
            "id": agent_id,
            "tenant_id": current_user.tenant_id,
        },
    )
    await session.commit()

    # Cache invalidation
    await _invalidate_agent_cache(agent_id, current_user.tenant_id)

    await insert_audit_log(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="a2a_agent_verified",
        resource_type="agent",
        resource_id=agent_id,
        details={
            "card_valid": card_valid,
            "health_status": new_status,
            "card_error": card_error,
        },
        db=session,
    )
    return {
        "agent_id": agent_id,
        "status": new_status,
        "card_valid": card_valid,
        "health_check": health_ok,
        "card_error": card_error or None,
    }


@a2a_tenant_router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deregister_a2a_agent(
    agent_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TODO-19: Soft-delete a registered A2A agent (status → archived).
    Removes agent from chat selector. Existing conversation history is preserved.
    """
    result = await session.execute(
        text(
            "UPDATE agent_cards "
            "SET status = 'archived', updated_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id "
            "AND template_type = 'registered_a2a'"
        ),
        {"id": agent_id, "tenant_id": current_user.tenant_id},
    )
    if (result.rowcount or 0) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"A2A agent '{agent_id}' not found",
        )
    await session.commit()

    # Cache invalidation so agent disappears from chat selector immediately
    await _invalidate_agent_cache(agent_id, current_user.tenant_id)

    await insert_audit_log(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="a2a_agent_deregistered",
        resource_type="agent",
        resource_id=agent_id,
        details={},
        db=session,
    )
    logger.info(
        "a2a_agent_deregistered",
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
    )


# ---------------------------------------------------------------------------
# Template versioning helpers (TODO-20, PA Template Studio)
# ---------------------------------------------------------------------------


def _bump_version(current_version: str, bump_type: str) -> str:
    """
    Bump a semver string by the given type.

    Args:
        current_version: Semver string in "major.minor.patch" format.
        bump_type: One of "major", "minor", "patch".

    Returns:
        New version string.

    Rules:
        - major: increment major, reset minor and patch to 0
        - minor: increment minor, reset patch to 0
        - patch: increment patch only
    """
    try:
        parts = current_version.split(".")
        major = int(parts[0]) if len(parts) > 0 else 1
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        major, minor, patch = 1, 0, 0

    if bump_type == "major":
        return f"{major + 1}.0.0"
    if bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    # patch (default)
    return f"{major}.{minor}.{patch + 1}"


def _detect_breaking_changes(old: dict, new: dict) -> str:
    """
    Determine the semver bump type required by comparing old and new template configs.

    Change classification:
        major  — auth_mode changed OR required_credentials changed (breaking API contract)
        minor  — system_prompt or guardrails changed (behavior change, not API contract)
        patch  — only name, description, avatar, or other metadata changed

    Args:
        old: Previous template config dict (keys: auth_mode, required_credentials,
             system_prompt, guardrails, name, description, ...).
        new: New template config dict.

    Returns:
        "major", "minor", or "patch"
    """
    # Major: breaking auth/credential contract changes
    if old.get("auth_mode") != new.get("auth_mode"):
        return "major"

    old_creds = sorted(
        [str(c) for c in (old.get("required_credentials") or [])],
    )
    new_creds = sorted(
        [str(c) for c in (new.get("required_credentials") or [])],
    )
    if old_creds != new_creds:
        return "major"

    # Minor: behavior-affecting changes
    if old.get("system_prompt") != new.get("system_prompt"):
        return "minor"
    if old.get("guardrails") != new.get("guardrails"):
        return "minor"

    # Patch: metadata-only changes
    return "patch"


# ---------------------------------------------------------------------------
# TODO-20: Platform Admin Template Studio API
# POST   /platform/agent-templates           — create template
# PUT    /platform/agent-templates/{id}      — update with ETag concurrency
# POST   /platform/agent-templates/{id}/publish  — publish + version record
# GET    /platform/agent-templates/{id}/versions  — version history
# GET    /platform/agent-templates/{id}/instances — tenant deployments
# ---------------------------------------------------------------------------

from app.core.dependencies import require_platform_admin  # noqa: E402 — already imported above

platform_templates_router = APIRouter(
    prefix="/platform/agent-templates",
    tags=["platform-agent-templates"],
)

# Fields that may be set on create/update
_VALID_TEMPLATE_TYPES = {
    "rag", "skill_augmented", "tool_augmented", "credentialed", "registered_a2a"
}
_VALID_AUTH_MODES = {"none", "tenant_credentials", "platform_credentials"}
_VALID_PLAN_TIERS = {"starter", "professional", "enterprise"}


class PlatformTemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    category: Optional[str] = Field(None, max_length=100)
    avatar: Optional[str] = Field(None, max_length=500)
    system_prompt: str = Field(..., min_length=1, max_length=2000)
    auth_mode: str = Field("none", pattern="^(none|tenant_credentials|platform_credentials)$")
    required_credentials: List[dict] = Field(default_factory=list)
    plan_required: Optional[str] = Field(
        None, pattern="^(starter|professional|enterprise)$"
    )
    capabilities: List[str] = Field(default_factory=list)
    cannot_do: List[str] = Field(default_factory=list)
    recommended_kb_categories: List[str] = Field(default_factory=list)
    llm_policy: Optional[dict] = None
    kb_policy: Optional[dict] = None
    attached_skills: List[str] = Field(default_factory=list)
    attached_tools: List[str] = Field(default_factory=list)
    a2a_interface: Optional[dict] = None
    template_type: str = Field(
        "rag",
        pattern="^(rag|skill_augmented|tool_augmented|credentialed|registered_a2a)$",
    )
    guardrails: Optional[List[dict]] = Field(default_factory=list)
    # PA override for prompt validation bypass (writes audit log entry)
    override_validation: bool = Field(False)
    override_reason: Optional[str] = Field(None, max_length=500)


class PlatformTemplateUpdateRequest(PlatformTemplateCreateRequest):
    # All same fields as create; ETag is supplied via If-Match header
    pass


class PublishTemplateRequest(BaseModel):
    version_label: str = Field(
        ..., min_length=1, max_length=20,
        description="Semver version label (e.g. '1.2.0')",
    )
    changelog: str = Field(..., min_length=1, max_length=4000)


def _get_platform_tenant_id_required(current_user) -> str:
    """Return PLATFORM_TENANT_ID, raising 503 if not configured."""
    ptid = _get_platform_tenant_id()
    if ptid is None:
        raise HTTPException(
            status_code=503,
            detail="Platform templates not available: PLATFORM_TENANT_ID is not configured.",
        )
    return ptid


def _build_template_capabilities_json(body) -> str:
    """Pack all template fields into the capabilities JSONB blob."""
    cap: dict = {
        "capabilities": body.capabilities or [],
        "cannot_do": body.cannot_do or [],
        "recommended_kb_categories": body.recommended_kb_categories or [],
        "guardrails": body.guardrails or [],
    }
    if body.llm_policy is not None:
        cap["llm_policy"] = body.llm_policy
    if body.kb_policy is not None:
        cap["kb_policy"] = body.kb_policy
    return json.dumps(cap)


def _template_etag(updated_at_str: str) -> str:
    """Compute ETag from updated_at timestamp."""
    return hashlib.sha256(str(updated_at_str).encode()).hexdigest()[:16]


@platform_templates_router.post("", status_code=status.HTTP_201_CREATED)
async def create_platform_template(
    body: PlatformTemplateCreateRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TODO-20: Create a new platform agent template.

    Runs SystemPromptValidator on system_prompt. Returns ETag header.
    Platform admin only.
    """
    from app.modules.agents.prompt_validator import validate_prompt, TEMPLATE_PROMPT_MAX_CHARS

    ptid = _get_platform_tenant_id_required(current_user)

    # Validate system_prompt (OWASP LLM Top 10 + 2000-char limit)
    validation = validate_prompt(body.system_prompt, max_chars=TEMPLATE_PROMPT_MAX_CHARS)
    if not validation.valid:
        if body.override_validation and body.override_reason:
            await insert_audit_log(
                tenant_id=ptid,
                user_id=current_user.id,
                action="prompt_validation_override",
                resource_type="agent_template",
                resource_id="new",
                details={
                    "reason": body.override_reason,
                    "blocked_patterns": validation.blocked_patterns,
                },
                db=session,
            )
        else:
            raise HTTPException(
                status_code=422,
                detail=validation.reason or "Prompt failed validation",
            )

    template_id = str(uuid.uuid4())
    capabilities_json = _build_template_capabilities_json(body)

    await session.execute(
        text(
            "INSERT INTO agent_cards ("
            "  id, tenant_id, name, description, category, avatar, system_prompt,"
            "  capabilities, status, version, source, auth_mode, required_credentials,"
            "  plan_required, template_type, llm_policy, kb_policy,"
            "  attached_skills, attached_tools, a2a_interface, created_by"
            ") VALUES ("
            "  :id, :tenant_id, :name, :description, :category, :avatar, :system_prompt,"
            "  CAST(:capabilities AS jsonb), 'draft', 1, 'platform',"
            "  :auth_mode, CAST(:required_credentials AS jsonb), :plan_required,"
            "  :template_type, CAST(:llm_policy AS jsonb), CAST(:kb_policy AS jsonb),"
            "  CAST(:attached_skills AS jsonb), CAST(:attached_tools AS jsonb),"
            "  CAST(:a2a_interface AS jsonb), :created_by"
            ")"
        ),
        {
            "id": template_id,
            "tenant_id": ptid,
            "name": body.name,
            "description": body.description,
            "category": body.category,
            "avatar": body.avatar,
            "system_prompt": body.system_prompt,
            "capabilities": capabilities_json,
            "auth_mode": body.auth_mode,
            "required_credentials": json.dumps(body.required_credentials),
            "plan_required": body.plan_required,
            "template_type": body.template_type,
            "llm_policy": json.dumps(
                body.llm_policy or {"tenant_can_override": True, "defaults": {"temperature": 0.3, "max_tokens": 2000}}
            ),
            "kb_policy": json.dumps(
                body.kb_policy or {"ownership": "tenant_managed", "recommended_categories": [], "required_kb_ids": []}
            ),
            "attached_skills": json.dumps(body.attached_skills),
            "attached_tools": json.dumps(body.attached_tools),
            "a2a_interface": json.dumps(
                body.a2a_interface or {"a2a_enabled": False, "operations": [], "auth_required": False}
            ),
            "created_by": current_user.id,
        },
    )
    await session.commit()

    # Fetch updated_at for ETag
    ts_result = await session.execute(
        text("SELECT updated_at FROM agent_cards WHERE id = :id"),
        {"id": template_id},
    )
    ts_row = ts_result.mappings().first()
    etag = _template_etag(str(ts_row["updated_at"])) if ts_row else template_id[:16]

    await insert_audit_log(
        tenant_id=ptid,
        user_id=current_user.id,
        action="platform_template_created",
        resource_type="agent_template",
        resource_id=template_id,
        details={"name": body.name, "template_type": body.template_type},
        db=session,
    )
    logger.info(
        "platform_template_created",
        template_id=template_id,
        name=body.name,
        admin_id=current_user.id,
    )

    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"id": template_id, "status": "draft", "version": "1.0.0"},
        status_code=201,
        headers={"ETag": etag},
    )


@platform_templates_router.put("/{template_id}")
async def update_platform_template(
    template_id: str,
    body: PlatformTemplateUpdateRequest,
    if_match: Optional[str] = None,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TODO-20: Update a platform agent template.

    Requires If-Match header for optimistic concurrency — returns 409 if stale.
    Runs SystemPromptValidator. Returns updated ETag.
    """
    from app.modules.agents.prompt_validator import validate_prompt, TEMPLATE_PROMPT_MAX_CHARS
    from fastapi import Header

    ptid = _get_platform_tenant_id_required(current_user)

    # Validate UUID
    if not _UUID_RE.match(template_id):
        raise HTTPException(status_code=404, detail="Template not found")

    # Fetch existing template
    existing_result = await session.execute(
        text(
            "SELECT id, updated_at, auth_mode, required_credentials, system_prompt, "
            "guardrails, status "
            "FROM agent_cards "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": template_id, "tenant_id": ptid},
    )
    existing = existing_result.mappings().first()
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    # ETag / optimistic concurrency check
    if if_match is not None:
        current_etag = _template_etag(str(existing["updated_at"]))
        # Strip quotes if present (HTTP spec)
        client_etag = if_match.strip('"')
        if client_etag != current_etag:
            raise HTTPException(
                status_code=409,
                detail="Template was modified by another session. Refresh and try again.",
            )

    # Validate system_prompt
    validation = validate_prompt(body.system_prompt, max_chars=TEMPLATE_PROMPT_MAX_CHARS)
    if not validation.valid:
        if body.override_validation and body.override_reason:
            await insert_audit_log(
                tenant_id=ptid,
                user_id=current_user.id,
                action="prompt_validation_override",
                resource_type="agent_template",
                resource_id=template_id,
                details={"reason": body.override_reason, "blocked_patterns": validation.blocked_patterns},
                db=session,
            )
        else:
            raise HTTPException(
                status_code=422,
                detail=validation.reason or "Prompt failed validation",
            )

    capabilities_json = _build_template_capabilities_json(body)

    await session.execute(
        text(
            "UPDATE agent_cards SET "
            "  name = :name, description = :description, category = :category, "
            "  avatar = :avatar, system_prompt = :system_prompt, "
            "  capabilities = CAST(:capabilities AS jsonb), "
            "  auth_mode = :auth_mode, "
            "  required_credentials = CAST(:required_credentials AS jsonb), "
            "  plan_required = :plan_required, "
            "  template_type = :template_type, "
            "  llm_policy = CAST(:llm_policy AS jsonb), "
            "  kb_policy = CAST(:kb_policy AS jsonb), "
            "  attached_skills = CAST(:attached_skills AS jsonb), "
            "  attached_tools = CAST(:attached_tools AS jsonb), "
            "  a2a_interface = CAST(:a2a_interface AS jsonb), "
            "  updated_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {
            "name": body.name,
            "description": body.description,
            "category": body.category,
            "avatar": body.avatar,
            "system_prompt": body.system_prompt,
            "capabilities": capabilities_json,
            "auth_mode": body.auth_mode,
            "required_credentials": json.dumps(body.required_credentials),
            "plan_required": body.plan_required,
            "template_type": body.template_type,
            "llm_policy": json.dumps(
                body.llm_policy or {"tenant_can_override": True, "defaults": {"temperature": 0.3, "max_tokens": 2000}}
            ),
            "kb_policy": json.dumps(
                body.kb_policy or {"ownership": "tenant_managed", "recommended_categories": [], "required_kb_ids": []}
            ),
            "attached_skills": json.dumps(body.attached_skills),
            "attached_tools": json.dumps(body.attached_tools),
            "a2a_interface": json.dumps(
                body.a2a_interface or {"a2a_enabled": False, "operations": [], "auth_required": False}
            ),
            "id": template_id,
            "tenant_id": ptid,
        },
    )
    await session.commit()

    # Fetch new updated_at for ETag
    ts_result = await session.execute(
        text("SELECT updated_at FROM agent_cards WHERE id = :id"),
        {"id": template_id},
    )
    ts_row = ts_result.mappings().first()
    etag = _template_etag(str(ts_row["updated_at"])) if ts_row else template_id[:16]

    await insert_audit_log(
        tenant_id=ptid,
        user_id=current_user.id,
        action="platform_template_updated",
        resource_type="agent_template",
        resource_id=template_id,
        details={"name": body.name},
        db=session,
    )
    logger.info(
        "platform_template_updated",
        template_id=template_id,
        admin_id=current_user.id,
    )

    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"id": template_id, "status": existing["status"]},
        headers={"ETag": etag},
    )


@platform_templates_router.post("/{template_id}/publish", status_code=status.HTTP_200_OK)
async def publish_platform_template(
    template_id: str,
    body: PublishTemplateRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TODO-20: Publish a platform agent template.

    Required: version_label (semver) and changelog (non-empty).
    Performs breaking-change detection against the last published snapshot.
    Writes an agent_template_versions row and sets status = 'published'.
    Returns the new ETag.
    """
    ptid = _get_platform_tenant_id_required(current_user)

    if not _UUID_RE.match(template_id):
        raise HTTPException(status_code=404, detail="Template not found")

    existing_result = await session.execute(
        text(
            "SELECT id, name, status, auth_mode, required_credentials, system_prompt, "
            "guardrails, updated_at "
            "FROM agent_cards "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": template_id, "tenant_id": ptid},
    )
    existing = existing_result.mappings().first()
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    # Fetch last published snapshot for change detection
    last_version_result = await session.execute(
        text(
            "SELECT snapshot FROM agent_template_versions "
            "WHERE template_id = :tid ORDER BY published_at DESC LIMIT 1"
        ),
        {"tid": template_id},
    )
    last_version_row = last_version_result.mappings().first()

    old_snapshot: dict = {}
    if last_version_row and last_version_row["snapshot"]:
        snap = last_version_row["snapshot"]
        if isinstance(snap, str):
            old_snapshot = json.loads(snap)
        elif isinstance(snap, dict):
            old_snapshot = snap

    new_snapshot: dict = {
        "auth_mode": existing["auth_mode"],
        "required_credentials": existing["required_credentials"] or [],
        "system_prompt": existing["system_prompt"],
        "guardrails": existing["guardrails"],
        "name": existing["name"],
    }

    change_type = _detect_breaking_changes(old_snapshot, new_snapshot)
    is_initial = not old_snapshot

    # Insert version record
    version_id = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO agent_template_versions "
            "  (id, template_id, version_label, change_type, changelog, published_by, snapshot) "
            "VALUES "
            "  (:id, :template_id, :version_label, :change_type, :changelog, :published_by, "
            "   CAST(:snapshot AS jsonb))"
        ),
        {
            "id": version_id,
            "template_id": template_id,
            "version_label": body.version_label,
            "change_type": "initial" if is_initial else change_type,
            "changelog": body.changelog,
            "published_by": current_user.id,
            "snapshot": json.dumps(new_snapshot),
        },
    )

    # Update template status to published
    await session.execute(
        text(
            "UPDATE agent_cards "
            "SET status = 'published', version = version + 1, updated_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": template_id, "tenant_id": ptid},
    )
    await session.commit()

    # New ETag
    ts_result = await session.execute(
        text("SELECT updated_at FROM agent_cards WHERE id = :id"),
        {"id": template_id},
    )
    ts_row = ts_result.mappings().first()
    etag = _template_etag(str(ts_row["updated_at"])) if ts_row else template_id[:16]

    await insert_audit_log(
        tenant_id=ptid,
        user_id=current_user.id,
        action="platform_template_published",
        resource_type="agent_template",
        resource_id=template_id,
        details={
            "version_label": body.version_label,
            "change_type": "initial" if is_initial else change_type,
        },
        db=session,
    )
    logger.info(
        "platform_template_published",
        template_id=template_id,
        version_label=body.version_label,
        change_type=change_type,
        admin_id=current_user.id,
    )

    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={
            "id": template_id,
            "status": "published",
            "version_label": body.version_label,
            "change_type": "initial" if is_initial else change_type,
        },
        headers={"ETag": etag},
    )


@platform_templates_router.get("/{template_id}/versions")
async def get_platform_template_versions(
    template_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TODO-20: Return version history for a platform agent template.

    Newest versions first. Includes version_label, change_type, changelog,
    published_by (user_id), published_at, and snapshot (optional).
    """
    ptid = _get_platform_tenant_id_required(current_user)

    if not _UUID_RE.match(template_id):
        raise HTTPException(status_code=404, detail="Template not found")

    # Verify template belongs to platform tenant
    exists_result = await session.execute(
        text("SELECT 1 FROM agent_cards WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": template_id, "tenant_id": ptid},
    )
    if exists_result.first() is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    rows_result = await session.execute(
        text(
            "SELECT id, version_label, change_type, changelog, published_by, published_at "
            "FROM agent_template_versions "
            "WHERE template_id = :template_id "
            "ORDER BY published_at DESC"
        ),
        {"template_id": template_id},
    )
    versions = []
    for row in rows_result.mappings():
        versions.append(
            {
                "id": str(row["id"]),
                "version_label": row["version_label"],
                "change_type": row["change_type"],
                "changelog": row["changelog"],
                "published_by": str(row["published_by"]),
                "published_at": str(row["published_at"]),
            }
        )

    return {"template_id": template_id, "versions": versions, "total": len(versions)}


@platform_templates_router.get("/{template_id}/instances")
async def get_platform_template_instances(
    template_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TODO-20: Return tenant deployments of a platform agent template.

    Security: returns ONLY tenant_name (not tenant_id), pinned_version,
    status, and last_active_at. Never returns system_prompt, KB IDs,
    credentials, or other tenant-specific data.
    """
    ptid = _get_platform_tenant_id_required(current_user)

    if not _UUID_RE.match(template_id):
        raise HTTPException(status_code=404, detail="Template not found")

    # Verify template belongs to platform tenant
    exists_result = await session.execute(
        text("SELECT 1 FROM agent_cards WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": template_id, "tenant_id": ptid},
    )
    if exists_result.first() is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    # Join agent_cards (deployed instances) with tenants to get name only.
    # Intentionally select tenant name, NOT tenant_id — data sovereignty.
    rows_result = await session.execute(
        text(
            "SELECT "
            "  t.name AS tenant_name, "
            "  ac.template_version AS pinned_version, "
            "  ac.status, "
            "  ac.updated_at AS last_active_at "
            "FROM agent_cards ac "
            "JOIN tenants t ON t.id = ac.tenant_id "
            "WHERE ac.template_id = :template_id "
            "  AND ac.tenant_id != :platform_tenant_id "
            "ORDER BY ac.updated_at DESC"
        ),
        {"template_id": template_id, "platform_tenant_id": ptid},
    )
    instances = []
    for row in rows_result.mappings():
        instances.append(
            {
                "tenant_name": row["tenant_name"],
                "pinned_version": row["pinned_version"],
                "status": row["status"],
                "last_active_at": str(row["last_active_at"]) if row["last_active_at"] else None,
            }
        )

    return {"template_id": template_id, "instances": instances, "total": len(instances)}
