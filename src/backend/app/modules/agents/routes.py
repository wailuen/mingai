"""
Agent Templates API routes (API-110 to API-115).

Endpoints:
- GET    /agents/templates                     - List agent templates (seed + DB)
- GET    /agents/templates/{template_id}       - Get template detail
- POST   /agents/templates/{template_id}/deploy - Deploy template as new agent

Seed templates are hardcoded and always available. DB templates come from agent_cards table.
"""
import json
import uuid
from typing import List, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session
from app.modules.har.crypto import generate_agent_keypair

logger = structlog.get_logger()

router = APIRouter(prefix="/agents", tags=["agents"])

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
# Request schemas
# ---------------------------------------------------------------------------


class DeployAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    access_control: Literal["workspace", "role", "user"] = Field(...)
    kb_ids: List[str] = Field(default_factory=list)


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
                "WHERE id = :id"
            ),
            {
                "public_key": public_key,
                "private_key_enc": private_key_enc,
                "id": agent_id,
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


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/templates")
async def list_agent_templates(
    category: Optional[str] = Query(None, description="Filter by category"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-110: List agent templates (seed + DB) for the tenant."""
    db_result = await list_agent_templates_db(
        tenant_id=current_user.tenant_id,
        page=page,
        page_size=page_size,
        db=session,
    )

    # Merge seed templates with DB results
    all_items = list(SEED_TEMPLATES) + db_result["items"]

    # Apply category filter if specified
    if category is not None:
        category_lower = category.lower()
        all_items = [
            item
            for item in all_items
            if item.get("category", "").lower() == category_lower
        ]

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
