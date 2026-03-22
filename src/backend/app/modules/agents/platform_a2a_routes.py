"""
Platform A2A Registry Routes — TODO-24.

Platform admins register external A2A agents at platform scope.
These become available to eligible tenants filtered by plan gate and
explicit tenant assignment.

Endpoints (all require require_platform_admin):
  GET    /platform/a2a-agents                  — List platform A2A agents
  GET    /platform/a2a-agents/registry-summary — Aggregate stats
  POST   /platform/a2a-agents/register         — Register external A2A agent (platform scope)
  GET    /platform/a2a-agents/{id}             — Agent detail + health stats
  PUT    /platform/a2a-agents/{id}             — Update wrapper config
  POST   /platform/a2a-agents/{id}/verify      — Manual health check
  POST   /platform/a2a-agents/{id}/deprecate   — Start 30-day deprecation window
  DELETE /platform/a2a-agents/{id}             — Hard delete (only if no tenant deployments)

Security: all endpoints require scope == 'platform' (require_platform_admin).
Generic 403 messages only — no scope/role disclosure.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_platform_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/platform/a2a-agents", tags=["platform-a2a"])

_DEPRECATION_DAYS = 30
_VALID_PLANS = {"starter", "professional", "enterprise"}


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class RegisterPlatformA2ARequest(BaseModel):
    source_card_url: str = Field(..., min_length=10, max_length=2048)
    plan_required: Optional[str] = Field(None, pattern="^(starter|professional|enterprise)$")
    assigned_tenants: Optional[List[str]] = Field(default_factory=list)
    guardrail_overlay: Optional[dict] = Field(default_factory=dict)
    name_override: Optional[str] = Field(None, max_length=255)
    description_override: Optional[str] = Field(None, max_length=2000)


class UpdatePlatformA2ARequest(BaseModel):
    plan_required: Optional[str] = Field(None, pattern="^(starter|professional|enterprise)$")
    assigned_tenants: Optional[List[str]] = None
    guardrail_overlay: Optional[dict] = None
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)


# ---------------------------------------------------------------------------
# Aggregate summary
# ---------------------------------------------------------------------------

@router.get("/registry-summary")
async def get_registry_summary(
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Platform A2A registry aggregate stats."""
    # Platform-scope A2A agents
    platform_count_result = await db.execute(
        text("""
            SELECT count(*) FROM agent_cards
            WHERE template_type = 'registered_a2a'
              AND a2a_scope = 'platform'
              AND (deprecation_at IS NULL OR deprecation_at > now())
        """)
    )
    platform_count = platform_count_result.scalar() or 0

    # Tenant-scope A2A agents (aggregate, no PII)
    tenant_count_result = await db.execute(
        text("""
            SELECT count(*) FROM agent_cards
            WHERE template_type = 'registered_a2a'
              AND a2a_scope = 'tenant'
        """)
    )
    tenant_count = tenant_count_result.scalar() or 0

    # Total A2A invocations trailing 30d (from analytics events if available)
    invocations_30d = 0
    try:
        inv_result = await db.execute(
            text("""
                SELECT count(*) FROM analytics_events
                WHERE event_type = 'a2a_invocation'
                  AND created_at >= now() - interval '30 days'
            """)
        )
        invocations_30d = inv_result.scalar() or 0
    except Exception:
        # analytics_events may not have this event_type yet
        pass

    return {
        "platform_count": platform_count,
        "tenant_count": tenant_count,
        "total_invocations_30d": invocations_30d,
    }


# ---------------------------------------------------------------------------
# List platform A2A agents
# ---------------------------------------------------------------------------

@router.get("")
async def list_platform_a2a_agents(
    q: Optional[str] = Query(None, max_length=200),
    health_status: Optional[str] = Query(None),
    plan_required: Optional[str] = Query(None),
    include_deprecated: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """List all platform-scope A2A agents."""
    filters = [
        "template_type = 'registered_a2a'",
        "a2a_scope = 'platform'",
    ]
    params: dict = {}

    if not include_deprecated:
        filters.append("(deprecation_at IS NULL OR deprecation_at > now())")

    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append("(name ILIKE :q OR description ILIKE :q)")
        params["q"] = f"%{escaped}%"

    if health_status:
        filters.append("health_status = :health_status")
        params["health_status"] = health_status

    if plan_required and plan_required in _VALID_PLANS:
        filters.append("plan_required = :plan_required")
        params["plan_required"] = plan_required

    where_clause = " AND ".join(filters)
    params["limit"] = limit
    params["offset"] = offset

    result = await db.execute(
        text(f"""
            SELECT id, name, description, a2a_endpoint, source_card_url,
                   plan_required, assigned_tenants, guardrail_overlay,
                   health_status, health_consecutive_failures,
                   last_health_check_at, last_health_http_status,
                   deprecation_at, deprecated_by,
                   created_at, updated_at
            FROM agent_cards
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.mappings().all()

    count_result = await db.execute(
        text(f"SELECT count(*) FROM agent_cards WHERE {where_clause}"),
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    )
    total = count_result.scalar() or 0

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# Register platform A2A agent
# ---------------------------------------------------------------------------

@router.post("/register", status_code=201)
async def register_platform_a2a_agent(
    body: RegisterPlatformA2ARequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """
    Register an external A2A agent at platform scope.

    Fetches and validates the A2A card from source_card_url, then creates an
    agent_cards record with template_type='registered_a2a' and a2a_scope='platform'.
    """
    from app.modules.agents.a2a_card_fetcher import fetch_and_validate_card

    card_url = str(body.source_card_url)
    fetch_result = await fetch_and_validate_card(card_url)

    if not fetch_result.success:
        raise HTTPException(
            422,
            detail=f"Failed to fetch A2A card: {fetch_result.error_message}",
        )

    card = fetch_result.card
    agent_id = str(uuid.uuid4())

    name = body.name_override or (card.name if card else "Unknown")
    description = body.description_override or (card.description if card else "")
    a2a_endpoint = card.a2a_endpoint if card else ""
    imported_card_json = json.dumps(card.raw) if card else "{}"
    plan_required = body.plan_required or "starter"
    assigned_tenants = body.assigned_tenants or []
    guardrail_overlay = body.guardrail_overlay or {}

    await db.execute(
        text("""
            INSERT INTO agent_cards (
                id, name, description, template_type, a2a_scope,
                a2a_endpoint, source_card_url, imported_card,
                plan_required, assigned_tenants, guardrail_overlay,
                is_public, status, health_status,
                health_consecutive_failures,
                created_at, updated_at
            ) VALUES (
                :id, :name, :description, 'registered_a2a', 'platform',
                :a2a_endpoint, :source_card_url, CAST(:imported_card AS jsonb),
                :plan_required,
                CAST(:assigned_tenants AS jsonb),
                CAST(:guardrail_overlay AS jsonb),
                true, 'active', 'unknown', 0,
                now(), now()
            )
        """),
        {
            "id": agent_id,
            "name": name[:255],
            "description": description[:2000],
            "a2a_endpoint": a2a_endpoint,
            "source_card_url": card_url,
            "imported_card": imported_card_json,
            "plan_required": plan_required,
            "assigned_tenants": json.dumps(assigned_tenants),
            "guardrail_overlay": json.dumps(guardrail_overlay),
        },
    )
    await db.commit()

    logger.info(
        "platform_a2a_agent_registered",
        agent_id=agent_id,
        card_url=card_url,
        name=name,
    )

    # Trigger initial health check in background
    import os
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        from app.modules.agents.a2a_health_worker import run_health_checks
        background_tasks.add_task(run_health_checks, db_url=db_url)

    return {"id": agent_id, "name": name, "status": "active"}


# ---------------------------------------------------------------------------
# Agent detail
# ---------------------------------------------------------------------------

@router.get("/{agent_id}")
async def get_platform_a2a_agent(
    agent_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Get platform A2A agent detail including health stats."""
    result = await db.execute(
        text("""
            SELECT id, name, description, a2a_endpoint, source_card_url,
                   plan_required, assigned_tenants, guardrail_overlay,
                   health_status, health_consecutive_failures,
                   last_health_check_at, last_health_http_status,
                   deprecation_at, deprecated_by,
                   imported_card, created_at, updated_at
            FROM agent_cards
            WHERE id = :id
              AND template_type = 'registered_a2a'
              AND a2a_scope = 'platform'
        """),
        {"id": agent_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(404, detail="Platform A2A agent not found")

    # Count tenant deployments derived from this platform agent
    deployment_result = await db.execute(
        text("""
            SELECT count(*) FROM agent_cards
            WHERE source_card_url = :card_url
              AND a2a_scope = 'tenant'
        """),
        {"card_url": str(row["source_card_url"])},
    )
    tenant_deployments = deployment_result.scalar() or 0

    return {
        **dict(row),
        "tenant_deployment_count": tenant_deployments,
    }


# ---------------------------------------------------------------------------
# Update wrapper config
# ---------------------------------------------------------------------------

@router.put("/{agent_id}")
async def update_platform_a2a_agent(
    agent_id: str,
    body: UpdatePlatformA2ARequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Update platform A2A agent wrapper configuration."""
    result = await db.execute(
        text("""
            SELECT id FROM agent_cards
            WHERE id = :id AND template_type = 'registered_a2a' AND a2a_scope = 'platform'
        """),
        {"id": agent_id},
    )
    if result.first() is None:
        raise HTTPException(404, detail="Platform A2A agent not found")

    _UPDATE_ALLOWLIST = {"name", "description", "plan_required"}
    set_parts: list[str] = ["updated_at = now()"]
    params: dict = {"id": agent_id}

    update_dict = body.model_dump(exclude_none=True)
    for col in _UPDATE_ALLOWLIST:
        if col in update_dict:
            set_parts.append(f"{col} = :{col}")
            params[col] = update_dict[col]

    if body.assigned_tenants is not None:
        set_parts.append("assigned_tenants = CAST(:assigned_tenants AS jsonb)")
        params["assigned_tenants"] = json.dumps(body.assigned_tenants)

    if body.guardrail_overlay is not None:
        set_parts.append("guardrail_overlay = CAST(:guardrail_overlay AS jsonb)")
        params["guardrail_overlay"] = json.dumps(body.guardrail_overlay)

    if not set_parts:
        raise HTTPException(422, detail="No valid fields to update")

    await db.execute(
        text(f"UPDATE agent_cards SET {', '.join(set_parts)} WHERE id = :id"),
        params,
    )
    await db.commit()

    return {"id": agent_id, "updated": True}


# ---------------------------------------------------------------------------
# Manual health check
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/verify")
async def verify_platform_a2a_agent(
    agent_id: str,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Trigger a manual health check for a platform A2A agent."""
    result = await db.execute(
        text("""
            SELECT id, a2a_endpoint, health_consecutive_failures
            FROM agent_cards
            WHERE id = :id AND template_type = 'registered_a2a' AND a2a_scope = 'platform'
        """),
        {"id": agent_id},
    )
    agent = result.mappings().first()
    if agent is None:
        raise HTTPException(404, detail="Platform A2A agent not found")

    from app.modules.agents.a2a_health_worker import check_a2a_agent_health

    new_status, new_failures, http_status = await check_a2a_agent_health(
        agent_id=agent_id,
        a2a_endpoint=str(agent["a2a_endpoint"]),
        consecutive_failures=int(agent["health_consecutive_failures"] or 0),
    )

    await db.execute(
        text("""
            UPDATE agent_cards
            SET health_status = :status,
                health_consecutive_failures = :failures,
                last_health_check_at = now(),
                last_health_http_status = :http_status
            WHERE id = :id
        """),
        {
            "status": new_status,
            "failures": new_failures,
            "http_status": http_status,
            "id": agent_id,
        },
    )
    await db.commit()

    return {
        "id": agent_id,
        "health_status": new_status,
        "last_health_http_status": http_status,
    }


# ---------------------------------------------------------------------------
# Deprecation
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/deprecate")
async def deprecate_platform_a2a_agent(
    agent_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """
    Start a 30-day deprecation window for a platform A2A agent.

    Notifies all affected tenant admins whose deployments use this agent.
    Agent continues to function until deprecation_at.
    """
    result = await db.execute(
        text("""
            SELECT id, name, source_card_url, deprecation_at
            FROM agent_cards
            WHERE id = :id AND template_type = 'registered_a2a' AND a2a_scope = 'platform'
        """),
        {"id": agent_id},
    )
    agent = result.mappings().first()
    if agent is None:
        raise HTTPException(404, detail="Platform A2A agent not found")

    if agent["deprecation_at"] is not None:
        raise HTTPException(409, detail="Agent is already scheduled for deprecation")

    deprecation_at = datetime.now(timezone.utc) + timedelta(days=_DEPRECATION_DAYS)

    await db.execute(
        text("""
            UPDATE agent_cards
            SET deprecation_at = :dep_at,
                deprecated_by = :dep_by,
                updated_at = now()
            WHERE id = :id
        """),
        {
            "dep_at": deprecation_at,
            "dep_by": str(current_user.user_id),
            "id": agent_id,
        },
    )

    # Find affected tenant deployments and send notifications
    tenant_result = await db.execute(
        text("""
            SELECT DISTINCT ac.tenant_id, ac.name AS instance_name
            FROM agent_cards ac
            WHERE ac.source_card_url = :card_url
              AND ac.a2a_scope = 'tenant'
        """),
        {"card_url": str(agent["source_card_url"])},
    )
    tenant_deployments = tenant_result.mappings().all()

    for deployment in tenant_deployments:
        tenant_id = str(deployment["tenant_id"])
        try:
            # Find a tenant admin to notify
            admin_result = await db.execute(
                text("""
                    SELECT id FROM users
                    WHERE tenant_id = :tid
                      AND roles @> '["tenant_admin"]'::jsonb
                    LIMIT 1
                """),
                {"tid": tenant_id},
            )
            admin_row = admin_result.first()
            if admin_row:
                from app.modules.notifications.publisher import publish_notification
                await publish_notification(
                    user_id=str(admin_row[0]),
                    tenant_id=tenant_id,
                    notification_type="a2a_deprecation_notice",
                    title=f"A2A Agent '{agent['name']}' is being deprecated",
                    body=(
                        f"Platform A2A agent '{agent['name']}' will be deprecated on "
                        f"{deprecation_at.strftime('%Y-%m-%d')}. "
                        "Your deployed instances will continue to work until that date. "
                        "Please migrate to an alternative agent before then."
                    ),
                )
        except Exception as exc:
            logger.warning(
                "a2a_deprecation_notification_failed",
                tenant_id=tenant_id,
                agent_id=agent_id,
                error=str(exc),
            )

    await db.commit()

    logger.info(
        "platform_a2a_agent_deprecated",
        agent_id=agent_id,
        deprecation_at=deprecation_at.isoformat(),
        affected_tenants=len(tenant_deployments),
        deprecated_by=str(current_user.user_id),
    )

    return {
        "id": agent_id,
        "deprecation_at": deprecation_at.isoformat(),
        "affected_tenant_count": len(tenant_deployments),
    }


# ---------------------------------------------------------------------------
# Hard delete
# ---------------------------------------------------------------------------

@router.delete("/{agent_id}", status_code=204)
async def delete_platform_a2a_agent(
    agent_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> None:
    """
    Hard delete a platform A2A agent.
    Returns 409 if any tenant has deployed instances derived from this agent.
    """
    result = await db.execute(
        text("""
            SELECT id, source_card_url FROM agent_cards
            WHERE id = :id AND template_type = 'registered_a2a' AND a2a_scope = 'platform'
        """),
        {"id": agent_id},
    )
    agent = result.mappings().first()
    if agent is None:
        raise HTTPException(404, detail="Platform A2A agent not found")

    # Check for tenant deployments
    deployment_result = await db.execute(
        text("""
            SELECT count(*) FROM agent_cards
            WHERE source_card_url = :card_url AND a2a_scope = 'tenant'
        """),
        {"card_url": str(agent["source_card_url"])},
    )
    deployment_count = deployment_result.scalar() or 0
    if deployment_count > 0:
        raise HTTPException(
            409,
            detail=f"Cannot delete: {deployment_count} tenant deployment(s) reference this agent. "
                   "Deprecate the agent instead to allow tenants to migrate.",
        )

    await db.execute(
        text("DELETE FROM agent_cards WHERE id = :id AND a2a_scope = 'platform'"),
        {"id": agent_id},
    )
    await db.commit()

    logger.info(
        "platform_a2a_agent_deleted",
        agent_id=agent_id,
        deleted_by=str(current_user.user_id),
    )
