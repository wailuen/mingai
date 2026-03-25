"""
Skills routes — Agent Studio Phase 1 TA Skills Catalog + Authoring.

Endpoints (public router /skills — tenant-readable):
  GET  /skills                   — List platform published skills + adopted status
  GET  /skills/{skill_id}        — Skill detail + versions
  POST /skills/{skill_id}/adopt  — Adopt platform skill into tenant catalog
  DELETE /skills/{skill_id}/adopt  — Remove adoption (not for mandatory skills)
  PUT  /skills/{skill_id}/pin    — Pin/unpin to specific version

Endpoints (admin router /admin/skills — require_tenant_admin):
  GET  /admin/skills                    — List tenant-authored skills
  POST /admin/skills                    — Create new tenant skill (draft)
  GET  /admin/skills/{skill_id}         — Get tenant skill detail
  PUT  /admin/skills/{skill_id}         — Update tenant skill
  POST /admin/skills/{skill_id}/publish — Publish draft
  DELETE /admin/skills/{skill_id}       — Delete (drafts only; 409 if published)
  POST /admin/skills/{skill_id}/test    — Test skill with sample input values
  POST /admin/skills/{skill_id}/submit-for-promotion — Submit for platform library
"""
from __future__ import annotations

import json
import re
import uuid
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_platform_admin, require_tenant_admin
from app.core.session import get_async_session
from app.modules.agents.prompt_validator import validate_prompt, SKILL_PROMPT_MAX_CHARS

logger = structlog.get_logger()

router = APIRouter(prefix="/skills", tags=["skills"])
admin_router = APIRouter(prefix="/admin/skills", tags=["admin-skills"])
platform_admin_router = APIRouter(prefix="/platform/skills", tags=["platform-skills"])

# ---------------------------------------------------------------------------
# Plan-gate helpers
# ---------------------------------------------------------------------------
PLAN_ORDER: dict[str, int] = {"starter": 0, "professional": 1, "enterprise": 2}


def tenant_meets_plan(tenant_plan: str, required_plan: str) -> bool:
    """Return True if tenant_plan is equal to or higher than required_plan."""
    return PLAN_ORDER.get(tenant_plan, -1) >= PLAN_ORDER.get(required_plan, 999)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class CreateSkillRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=100)
    execution_pattern: str = Field("prompt")
    invocation_mode: str = Field("llm_invoked")
    pipeline_trigger: Optional[str] = None
    prompt_template: str = Field(..., max_length=SKILL_PROMPT_MAX_CHARS)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    tool_dependencies: List[str] = Field(default_factory=list)
    llm_config: dict = Field(default_factory=lambda: {"temperature": 0.3, "max_tokens": 2000})

    model_config = ConfigDict(extra="forbid")


class UpdateSkillRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=100)
    execution_pattern: Optional[str] = None
    invocation_mode: Optional[str] = None
    pipeline_trigger: Optional[str] = None
    prompt_template: Optional[str] = Field(None, max_length=SKILL_PROMPT_MAX_CHARS)
    input_schema: Optional[dict] = None
    output_schema: Optional[dict] = None
    tool_dependencies: Optional[List[str]] = None
    llm_config: Optional[dict] = None

    model_config = ConfigDict(extra="forbid")


class AdoptSkillRequest(BaseModel):
    pinned_version: Optional[str] = None  # None = always latest

    model_config = ConfigDict(extra="forbid")


class PinSkillVersionRequest(BaseModel):
    pinned_version: Optional[str] = None  # None = unpin (always latest)

    model_config = ConfigDict(extra="forbid")


class TestSkillRequest(BaseModel):
    input_values: dict = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_VALID_EXECUTION_PATTERNS = {"prompt", "tool_composing", "sequential_pipeline"}
_VALID_INVOCATION_MODES = {"llm_invoked", "pipeline"}

# Allowlist for skill UPDATE SQL fields
_SKILL_UPDATE_ALLOWLIST: dict[str, str] = {
    "name": "name = :name",
    "description": "description = :description",
    "category": "category = :category",
    "execution_pattern": "execution_pattern = :execution_pattern",
    "invocation_mode": "invocation_mode = :invocation_mode",
    "pipeline_trigger": "pipeline_trigger = :pipeline_trigger",
    "prompt_template": "prompt_template = :prompt_template",
    "input_schema": "input_schema = CAST(:input_schema AS jsonb)",
    "output_schema": "output_schema = CAST(:output_schema AS jsonb)",
    "tool_dependencies": "tool_dependencies = CAST(:tool_dependencies AS jsonb)",
    "llm_config": "llm_config = CAST(:llm_config AS jsonb)",
}


async def _get_rls_context(db: AsyncSession, tenant_id: str) -> None:
    """Set RLS context for the current session."""
    await db.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


async def _get_platform_rls_context(db: AsyncSession) -> None:
    """Set RLS context for platform admin operations."""
    await db.execute(text("SELECT set_config('app.scope', 'platform', true)"))


# ---------------------------------------------------------------------------
# Platform skills — public read
# ---------------------------------------------------------------------------

@router.get("")
async def list_platform_skills(
    category: Optional[str] = Query(None, max_length=100),
    search: Optional[str] = Query(None, max_length=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """
    List published platform skills plus adopted status for the calling tenant.
    """
    await _get_rls_context(db, current_user.tenant_id)

    params: dict = {}
    conditions = ["scope = 'platform'", "status = 'published'", "is_active = true"]

    if category:
        conditions.append("category = :category")
        params["category"] = category

    if search:
        # Escape LIKE wildcards in search string
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(
            "(name ILIKE :search OR description ILIKE :search)"
        )
        params["search"] = f"%{escaped}%"

    where_clause = " AND ".join(conditions)

    rows_result = await db.execute(
        text(
            f"SELECT id, name, description, category, version, execution_pattern, "  # noqa: S608
            f"invocation_mode, plan_required, mandatory, tool_dependencies, llm_config, "
            f"published_at, scope "
            f"FROM skills WHERE {where_clause} ORDER BY name ASC"
        ),
        params,
    )
    skills_rows = list(rows_result.mappings())

    # Fetch adopted skill IDs for this tenant
    adopted_result = await db.execute(
        text(
            "SELECT skill_id, pinned_version FROM tenant_skills "
            "WHERE tenant_id = :tenant_id"
        ),
        {"tenant_id": current_user.tenant_id},
    )
    adopted_map = {
        str(row["skill_id"]): row["pinned_version"]
        for row in adopted_result.mappings()
    }

    items = []
    for row in skills_rows:
        skill_id = str(row["id"])
        tool_deps = row["tool_dependencies"]
        if isinstance(tool_deps, str):
            tool_deps = json.loads(tool_deps)

        items.append({
            "id": skill_id,
            "name": row["name"],
            "description": row["description"],
            "category": row["category"],
            "version": row["version"],
            "execution_pattern": row["execution_pattern"],
            "invocation_mode": row["invocation_mode"],
            "plan_required": row["plan_required"],
            "mandatory": row["mandatory"],
            "tool_dependencies": tool_deps or [],
            "published_at": str(row["published_at"]) if row["published_at"] else None,
            "is_adopted": skill_id in adopted_map,
            "pinned_version": adopted_map.get(skill_id),
        })

    return {"items": items, "total": len(items)}


@router.get("/{skill_id}")
async def get_platform_skill(
    skill_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Get platform skill detail plus version history."""
    await _get_rls_context(db, current_user.tenant_id)

    result = await db.execute(
        text(
            "SELECT id, name, description, category, version, execution_pattern, "
            "invocation_mode, pipeline_trigger, prompt_template, input_schema, "
            "output_schema, tool_dependencies, llm_config, plan_required, "
            "mandatory, status, published_at, scope "
            "FROM skills "
            "WHERE id = :skill_id AND scope = 'platform'"
        ),
        {"skill_id": skill_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Fetch versions
    versions_result = await db.execute(
        text(
            "SELECT version_label, change_type, changelog, published_at "
            "FROM skill_versions WHERE skill_id = :skill_id "
            "ORDER BY published_at DESC LIMIT 10"
        ),
        {"skill_id": skill_id},
    )
    versions = [
        {
            "version_label": v["version_label"],
            "change_type": v["change_type"],
            "changelog": v["changelog"],
            "published_at": str(v["published_at"]),
        }
        for v in versions_result.mappings()
    ]

    def _load_json(value):
        if isinstance(value, str):
            return json.loads(value)
        return value or {}

    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "category": row["category"],
        "version": row["version"],
        "execution_pattern": row["execution_pattern"],
        "invocation_mode": row["invocation_mode"],
        "pipeline_trigger": row["pipeline_trigger"],
        "prompt_template": row["prompt_template"],
        "input_schema": _load_json(row["input_schema"]),
        "output_schema": _load_json(row["output_schema"]),
        "tool_dependencies": _load_json(row["tool_dependencies"]) if row["tool_dependencies"] else [],
        "llm_config": _load_json(row["llm_config"]),
        "plan_required": row["plan_required"],
        "mandatory": row["mandatory"],
        "status": row["status"],
        "published_at": str(row["published_at"]) if row["published_at"] else None,
        "versions": versions,
    }


@router.post("/{skill_id}/adopt")
async def adopt_skill(
    skill_id: str,
    body: AdoptSkillRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Adopt a platform skill into the tenant's skill catalog.
    Enforces plan-gate checks on both skill and its tool dependencies.
    """
    await _get_rls_context(db, current_user.tenant_id)

    # Load the skill (must be platform scope and published)
    skill_result = await db.execute(
        text(
            "SELECT id, name, plan_required, mandatory "
            "FROM skills WHERE id = :skill_id AND scope = 'platform' AND status = 'published'"
        ),
        {"skill_id": skill_id},
    )
    skill = skill_result.mappings().first()
    if skill is None:
        raise HTTPException(status_code=404, detail="Platform skill not found")

    # Plan-gate check on skill
    tenant_plan = current_user.plan or "starter"
    if skill["plan_required"] and not tenant_meets_plan(tenant_plan, skill["plan_required"]):
        raise HTTPException(
            status_code=403,
            detail=f"Skill requires '{skill['plan_required']}' plan",
        )

    # Plan-gate check on tool dependencies
    deps_result = await db.execute(
        text(
            "SELECT tc.name, tc.plan_required "
            "FROM skill_tool_dependencies std "
            "JOIN tool_catalog tc ON tc.id = std.tool_id "
            "WHERE std.skill_id = :skill_id AND std.required = true"
        ),
        {"skill_id": skill_id},
    )
    for dep in deps_result.mappings():
        if dep["plan_required"] and not tenant_meets_plan(tenant_plan, dep["plan_required"]):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Skill depends on tool '{dep['name']}' which requires "
                    f"'{dep['plan_required']}' plan"
                ),
            )

    # Insert adoption record
    try:
        await db.execute(
            text(
                "INSERT INTO tenant_skills (tenant_id, skill_id, pinned_version) "
                "VALUES (:tenant_id, :skill_id, :pinned_version) "
                "ON CONFLICT (tenant_id, skill_id) DO UPDATE "
                "SET pinned_version = EXCLUDED.pinned_version"
            ),
            {
                "tenant_id": current_user.tenant_id,
                "skill_id": skill_id,
                "pinned_version": body.pinned_version,
            },
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("skill_adopt_failed", error=str(exc), tenant_id=current_user.tenant_id)
        raise HTTPException(status_code=500, detail="Failed to adopt skill")

    return {"status": "adopted", "skill_id": skill_id, "pinned_version": body.pinned_version}


@router.delete("/{skill_id}/adopt")
async def unadopt_skill(
    skill_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Remove skill adoption. 409 if the skill is mandatory."""
    await _get_rls_context(db, current_user.tenant_id)

    # Check mandatory flag
    skill_result = await db.execute(
        text("SELECT mandatory FROM skills WHERE id = :skill_id AND scope = 'platform'"),
        {"skill_id": skill_id},
    )
    skill = skill_result.mappings().first()
    if skill and skill["mandatory"]:
        raise HTTPException(
            status_code=409,
            detail="Cannot remove a mandatory platform skill",
        )

    await db.execute(
        text(
            "DELETE FROM tenant_skills "
            "WHERE tenant_id = :tenant_id AND skill_id = :skill_id"
        ),
        {"tenant_id": current_user.tenant_id, "skill_id": skill_id},
    )
    await db.commit()
    return {"status": "unadopted", "skill_id": skill_id}


@router.put("/{skill_id}/pin")
async def pin_skill_version(
    skill_id: str,
    body: PinSkillVersionRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Pin an adopted skill to a specific version or unpin (always latest)."""
    await _get_rls_context(db, current_user.tenant_id)

    result = await db.execute(
        text(
            "UPDATE tenant_skills SET pinned_version = :pinned_version "
            "WHERE tenant_id = :tenant_id AND skill_id = :skill_id"
        ),
        {
            "tenant_id": current_user.tenant_id,
            "skill_id": skill_id,
            "pinned_version": body.pinned_version,
        },
    )
    if (result.rowcount or 0) == 0:
        raise HTTPException(status_code=404, detail="Skill not adopted by this tenant")
    await db.commit()
    return {"status": "pinned", "skill_id": skill_id, "pinned_version": body.pinned_version}


# ---------------------------------------------------------------------------
# Tenant skill CRUD — admin router
# ---------------------------------------------------------------------------

@admin_router.get("")
async def list_tenant_skills(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """List tenant-authored private skills."""
    await _get_rls_context(db, current_user.tenant_id)

    result = await db.execute(
        text(
            "SELECT id, name, description, category, version, execution_pattern, "
            "invocation_mode, status, created_at, updated_at "
            "FROM skills "
            "WHERE scope = :tenant_id "
            "ORDER BY name ASC"
        ),
        {"tenant_id": current_user.tenant_id},
    )
    items = [
        {
            "id": str(row["id"]),
            "name": row["name"],
            "description": row["description"],
            "category": row["category"],
            "version": row["version"],
            "execution_pattern": row["execution_pattern"],
            "invocation_mode": row["invocation_mode"],
            "status": row["status"],
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
        for row in result.mappings()
    ]
    return {"items": items, "total": len(items)}


@admin_router.post("")
async def create_tenant_skill(
    body: CreateSkillRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Create a new tenant-authored skill (draft status)."""
    await _get_rls_context(db, current_user.tenant_id)

    # Validate execution pattern and invocation mode
    if body.execution_pattern not in _VALID_EXECUTION_PATTERNS:
        raise HTTPException(
            status_code=422,
            detail=f"execution_pattern must be one of {sorted(_VALID_EXECUTION_PATTERNS)}",
        )
    if body.execution_pattern == "sequential_pipeline":
        raise HTTPException(
            status_code=422,
            detail="sequential_pipeline execution_pattern is reserved for platform admins",
        )
    if body.invocation_mode not in _VALID_INVOCATION_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"invocation_mode must be one of {sorted(_VALID_INVOCATION_MODES)}",
        )

    # Validate prompt
    validation = validate_prompt(body.prompt_template, max_chars=SKILL_PROMPT_MAX_CHARS)
    if not validation.valid:
        raise HTTPException(
            status_code=422,
            detail=validation.reason,
            headers={"X-Blocked-Patterns": ",".join(validation.blocked_patterns)},
        )

    skill_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO skills "
            "(id, name, description, category, execution_pattern, invocation_mode, "
            "pipeline_trigger, prompt_template, input_schema, output_schema, "
            "tool_dependencies, llm_config, scope, status, created_by) "
            "VALUES "
            "(:id, :name, :description, :category, :execution_pattern, :invocation_mode, "
            ":pipeline_trigger, :prompt_template, CAST(:input_schema AS jsonb), "
            "CAST(:output_schema AS jsonb), CAST(:tool_dependencies AS jsonb), "
            "CAST(:llm_config AS jsonb), :scope, 'draft', :created_by)"
        ),
        {
            "id": skill_id,
            "name": body.name,
            "description": body.description,
            "category": body.category,
            "execution_pattern": body.execution_pattern,
            "invocation_mode": body.invocation_mode,
            "pipeline_trigger": body.pipeline_trigger,
            "prompt_template": body.prompt_template,
            "input_schema": json.dumps(body.input_schema),
            "output_schema": json.dumps(body.output_schema),
            "tool_dependencies": json.dumps(body.tool_dependencies),
            "llm_config": json.dumps(body.llm_config),
            "scope": current_user.tenant_id,
            "created_by": current_user.id,
        },
    )
    await db.commit()

    logger.info("tenant_skill_created", skill_id=skill_id, tenant_id=current_user.tenant_id)
    return {"id": skill_id, "status": "draft"}


@admin_router.get("/{skill_id}")
async def get_tenant_skill(
    skill_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Get tenant skill detail."""
    await _get_rls_context(db, current_user.tenant_id)

    result = await db.execute(
        text(
            "SELECT id, name, description, category, version, execution_pattern, "
            "invocation_mode, pipeline_trigger, prompt_template, input_schema, "
            "output_schema, tool_dependencies, llm_config, status, "
            "created_at, updated_at, published_at "
            "FROM skills "
            "WHERE id = :skill_id AND scope = :tenant_id"
        ),
        {"skill_id": skill_id, "tenant_id": current_user.tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    def _load(v):
        return json.loads(v) if isinstance(v, str) else (v or {})

    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "category": row["category"],
        "version": row["version"],
        "execution_pattern": row["execution_pattern"],
        "invocation_mode": row["invocation_mode"],
        "pipeline_trigger": row["pipeline_trigger"],
        "prompt_template": row["prompt_template"],
        "input_schema": _load(row["input_schema"]),
        "output_schema": _load(row["output_schema"]),
        "tool_dependencies": _load(row["tool_dependencies"]) if row["tool_dependencies"] else [],
        "llm_config": _load(row["llm_config"]),
        "status": row["status"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "published_at": str(row["published_at"]) if row["published_at"] else None,
    }


@admin_router.put("/{skill_id}")
async def update_tenant_skill(
    skill_id: str,
    body: UpdateSkillRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Update a tenant skill. Runs SystemPromptValidator on prompt_template."""
    await _get_rls_context(db, current_user.tenant_id)

    # Validate prompt if provided
    if body.prompt_template is not None:
        validation = validate_prompt(body.prompt_template, max_chars=SKILL_PROMPT_MAX_CHARS)
        if not validation.valid:
            raise HTTPException(
                status_code=422,
                detail=validation.reason,
                headers={"X-Blocked-Patterns": ",".join(validation.blocked_patterns)},
            )

    if body.execution_pattern is not None and body.execution_pattern not in _VALID_EXECUTION_PATTERNS:
        raise HTTPException(
            status_code=422,
            detail=f"execution_pattern must be one of {sorted(_VALID_EXECUTION_PATTERNS)}",
        )
    if body.execution_pattern == "sequential_pipeline":
        raise HTTPException(
            status_code=422,
            detail="sequential_pipeline is reserved for platform admins",
        )
    if body.invocation_mode is not None and body.invocation_mode not in _VALID_INVOCATION_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"invocation_mode must be one of {sorted(_VALID_INVOCATION_MODES)}",
        )

    updates = dict(body)
    updates_copy = dict(updates)  # Never mutate caller's dict

    set_clauses = []
    params: dict = {
        "skill_id": skill_id,
        "tenant_id": current_user.tenant_id,
    }

    for field_name, sql_fragment in _SKILL_UPDATE_ALLOWLIST.items():
        if field_name in updates_copy and updates_copy[field_name] is not None:
            set_clauses.append(sql_fragment)
            val = updates_copy[field_name]
            if field_name in ("input_schema", "output_schema", "tool_dependencies", "llm_config"):
                params[field_name] = json.dumps(val)
            else:
                params[field_name] = val

    if not set_clauses:
        raise HTTPException(status_code=422, detail="No valid fields to update")

    set_clauses.append("updated_at = NOW()")
    set_sql = ", ".join(set_clauses)

    result = await db.execute(
        text(
            f"UPDATE skills SET {set_sql} "  # noqa: S608
            f"WHERE id = :skill_id AND scope = :tenant_id"
        ),
        params,
    )
    if (result.rowcount or 0) == 0:
        raise HTTPException(status_code=404, detail="Skill not found")
    await db.commit()

    return {"status": "updated", "skill_id": skill_id}


@admin_router.post("/{skill_id}/publish")
async def publish_tenant_skill(
    skill_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Publish a draft tenant skill (draft → published)."""
    await _get_rls_context(db, current_user.tenant_id)

    # Verify skill exists and is draft
    result = await db.execute(
        text(
            "SELECT id, status, prompt_template FROM skills "
            "WHERE id = :skill_id AND scope = :tenant_id"
        ),
        {"skill_id": skill_id, "tenant_id": current_user.tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if row["status"] != "draft":
        raise HTTPException(
            status_code=409,
            detail=f"Only draft skills can be published (current status: {row['status']})",
        )

    # Validate prompt one more time before publish
    if row["prompt_template"]:
        validation = validate_prompt(row["prompt_template"], max_chars=SKILL_PROMPT_MAX_CHARS)
        if not validation.valid:
            raise HTTPException(
                status_code=422,
                detail=f"Skill prompt failed validation: {validation.reason}",
            )

    await db.execute(
        text(
            "UPDATE skills SET status = 'published', published_at = NOW(), updated_at = NOW() "
            "WHERE id = :skill_id AND scope = :tenant_id"
        ),
        {"skill_id": skill_id, "tenant_id": current_user.tenant_id},
    )
    await db.commit()

    logger.info("tenant_skill_published", skill_id=skill_id, tenant_id=current_user.tenant_id)
    return {"status": "published", "skill_id": skill_id}


@admin_router.delete("/{skill_id}")
async def delete_tenant_skill(
    skill_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Delete a tenant skill. 409 if published (must deprecate instead)."""
    await _get_rls_context(db, current_user.tenant_id)

    result = await db.execute(
        text(
            "SELECT status FROM skills "
            "WHERE id = :skill_id AND scope = :tenant_id"
        ),
        {"skill_id": skill_id, "tenant_id": current_user.tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if row["status"] == "published":
        raise HTTPException(
            status_code=409,
            detail="Published skills cannot be deleted. Set status to 'deprecated' instead.",
        )

    await db.execute(
        text("DELETE FROM skills WHERE id = :skill_id AND scope = :tenant_id"),
        {"skill_id": skill_id, "tenant_id": current_user.tenant_id},
    )
    await db.commit()

    return {"status": "deleted", "skill_id": skill_id}


@admin_router.post("/{skill_id}/test")
async def test_tenant_skill(
    skill_id: str,
    body: TestSkillRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Test a tenant skill with sample input values.

    Interpolates input_values into the prompt template, executes via LLM,
    and returns: output, latency_ms, tokens_used, budget_remaining, tool_calls.
    Writes audit log with mode='skill_test'.
    """
    import time

    await _get_rls_context(db, current_user.tenant_id)

    result = await db.execute(
        text(
            "SELECT id, name, prompt_template, execution_pattern, invocation_mode, "
            "llm_config, tool_dependencies, scope "
            "FROM skills "
            "WHERE id = :skill_id AND (scope = :tenant_id OR scope = 'platform')"
        ),
        {"skill_id": skill_id, "tenant_id": current_user.tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Interpolate {{input.field}} tokens
    prompt_template = row["prompt_template"] or ""
    interpolated = prompt_template
    for key, value in body.input_values.items():
        # Sanitize value: strip control characters to prevent injection
        safe_value = re.sub(r"[\x00-\x1f\x7f]", "", str(value))
        interpolated = interpolated.replace(f"{{{{input.{key}}}}}", safe_value)

    llm_config = row["llm_config"]
    if isinstance(llm_config, str):
        llm_config = json.loads(llm_config)
    token_budget = (llm_config or {}).get("max_tokens", 2000)

    start_ms = int(time.time() * 1000)
    tokens_used = 0
    output = None
    tool_calls_list: list = []

    # Write audit log before execution (mode=skill_test)
    await db.execute(
        text(
            "INSERT INTO audit_log (tenant_id, user_id, action, resource_type, resource_id, metadata) "
            "VALUES (:tenant_id, :user_id, 'skill_test', 'skill', :skill_id, "
            "CAST(:metadata AS jsonb)) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "tenant_id": current_user.tenant_id,
            "user_id": current_user.id,
            "skill_id": skill_id,
            "metadata": json.dumps({
                "mode": "skill_test",
                "test_as_user_id": current_user.id,
                "skill_name": row["name"],
            }),
        },
    )
    await db.commit()

    # Execute skill (best-effort — return partial results on error)
    try:
        from app.modules.skills.executor import SkillExecutor, ExecutionContext
        executor = SkillExecutor()
        context = ExecutionContext(
            tenant_id=current_user.tenant_id,
            agent_id="skill_test",
            conversation_id="skill_test",
            token_budget=token_budget,
        )
        skill_record = dict(row)
        if isinstance(skill_record.get("tool_dependencies"), str):
            skill_record["tool_dependencies"] = json.loads(skill_record["tool_dependencies"])

        skill_result = await executor.execute(
            skill_id=skill_id,
            input_data=body.input_values,
            context=context,
        )
        output = skill_result.output if hasattr(skill_result, "output") else str(skill_result)
        tokens_used = getattr(skill_result, "tokens_used", 0)
        tool_calls_list = getattr(skill_result, "tool_calls", [])
    except Exception as exc:
        logger.warning(
            "skill_test_execution_failed",
            skill_id=skill_id,
            error=str(exc),
            tenant_id=current_user.tenant_id,
        )
        output = f"Skill test error: {str(exc)[:300]}"

    latency_ms = int(time.time() * 1000) - start_ms
    budget_remaining = max(0, token_budget - tokens_used)

    return {
        "output": output,
        "latency_ms": latency_ms,
        "tokens_used": tokens_used,
        "budget_remaining": budget_remaining,
        "tool_calls": tool_calls_list,
    }


@admin_router.post("/{skill_id}/submit-for-promotion")
async def submit_skill_for_promotion(
    skill_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Submit a tenant skill for promotion to the platform library."""
    await _get_rls_context(db, current_user.tenant_id)

    # Verify skill is published
    result = await db.execute(
        text(
            "SELECT id, status FROM skills "
            "WHERE id = :skill_id AND scope = :tenant_id AND status = 'published'"
        ),
        {"skill_id": skill_id, "tenant_id": current_user.tenant_id},
    )
    if result.mappings().first() is None:
        raise HTTPException(
            status_code=404,
            detail="Skill not found or not published",
        )

    submission_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO skill_promotion_requests "
            "(id, skill_id, tenant_id, submitted_by, status) "
            "VALUES (:id, :skill_id, :tenant_id, :submitted_by, 'pending')"
        ),
        {
            "id": submission_id,
            "skill_id": skill_id,
            "tenant_id": current_user.tenant_id,
            "submitted_by": current_user.id,
        },
    )
    await db.commit()

    logger.info(
        "skill_promotion_submitted",
        submission_id=submission_id,
        skill_id=skill_id,
        tenant_id=current_user.tenant_id,
    )
    return {"submission_id": submission_id, "status": "pending"}


# ---------------------------------------------------------------------------
# Platform admin skills management
# ---------------------------------------------------------------------------

class PlatformCreateSkillRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=100)
    execution_pattern: str = Field("prompt")
    invocation_mode: str = Field("llm_invoked")
    pipeline_trigger: Optional[str] = None
    prompt_template: str = Field(..., max_length=SKILL_PROMPT_MAX_CHARS)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    tool_dependencies: List[str] = Field(default_factory=list)
    llm_config: dict = Field(default_factory=lambda: {"temperature": 0.3, "max_tokens": 2000})
    mandatory: bool = Field(False)
    plan_required: Optional[str] = Field(None)

    model_config = ConfigDict(extra="forbid")


class PlatformUpdateSkillRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=100)
    execution_pattern: Optional[str] = None
    invocation_mode: Optional[str] = None
    pipeline_trigger: Optional[str] = None
    prompt_template: Optional[str] = Field(None, max_length=SKILL_PROMPT_MAX_CHARS)
    input_schema: Optional[dict] = None
    output_schema: Optional[dict] = None
    tool_dependencies: Optional[List[str]] = None
    llm_config: Optional[dict] = None
    mandatory: Optional[bool] = None
    plan_required: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


_PLATFORM_SKILL_UPDATE_ALLOWLIST: dict[str, str] = {
    "name": "name = :name",
    "description": "description = :description",
    "category": "category = :category",
    "execution_pattern": "execution_pattern = :execution_pattern",
    "invocation_mode": "invocation_mode = :invocation_mode",
    "pipeline_trigger": "pipeline_trigger = :pipeline_trigger",
    "prompt_template": "prompt_template = :prompt_template",
    "input_schema": "input_schema = CAST(:input_schema AS jsonb)",
    "output_schema": "output_schema = CAST(:output_schema AS jsonb)",
    "tool_dependencies": "tool_dependencies = CAST(:tool_dependencies AS jsonb)",
    "llm_config": "llm_config = CAST(:llm_config AS jsonb)",
    "mandatory": "mandatory = :mandatory",
    "plan_required": "plan_required = :plan_required",
}


@platform_admin_router.get("")
async def platform_list_skills(
    status: Optional[str] = Query(None, pattern="^(draft|published|deprecated)$"),
    category: Optional[str] = Query(None, max_length=100),
    search: Optional[str] = Query(None, max_length=200),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """List all platform-scoped skills. Platform admin only."""
    await _get_platform_rls_context(db)
    conditions = ["scope = 'platform'"]
    params: dict = {}

    if status:
        conditions.append("status = :status")
        params["status"] = status
    if category:
        conditions.append("category = :category")
        params["category"] = category
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append("(name ILIKE :search OR description ILIKE :search)")
        params["search"] = f"%{escaped}%"

    where_clause = " AND ".join(conditions)

    result = await db.execute(
        text(
            f"SELECT s.id, s.name, s.description, s.category, s.version, "  # noqa: S608
            f"s.execution_pattern, s.invocation_mode, s.status, s.mandatory, s.plan_required, "
            f"s.published_at, s.created_at, s.updated_at, "
            f"COALESCE((SELECT COUNT(*) FROM tenant_skills ts WHERE ts.skill_id = s.id), 0) AS adoption_count "
            f"FROM skills s WHERE {where_clause} ORDER BY s.name ASC"
        ),
        params,
    )
    items = []
    for row in result.mappings():
        items.append({
            "id": str(row["id"]),
            "name": row["name"],
            "description": row["description"],
            "category": row["category"],
            "version": row["version"],
            "execution_pattern": row["execution_pattern"],
            "invocation_mode": row["invocation_mode"],
            "status": row["status"],
            "mandatory": row["mandatory"],
            "plan_required": row["plan_required"],
            "adoption_count": row["adoption_count"] or 0,
            "scope": "platform",
            "published_at": str(row["published_at"]) if row["published_at"] else None,
            "created_at": str(row["created_at"]) if row["created_at"] else None,
            "updated_at": str(row["updated_at"]) if row["updated_at"] else None,
        })
    return {"items": items, "total": len(items)}


@platform_admin_router.post("")
async def platform_create_skill(
    body: PlatformCreateSkillRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Create a new platform skill (draft status). Platform admin only."""
    await _get_platform_rls_context(db)
    if body.execution_pattern not in _VALID_EXECUTION_PATTERNS:
        raise HTTPException(
            status_code=422,
            detail=f"execution_pattern must be one of {sorted(_VALID_EXECUTION_PATTERNS)}",
        )
    if body.invocation_mode not in _VALID_INVOCATION_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"invocation_mode must be one of {sorted(_VALID_INVOCATION_MODES)}",
        )

    validation = validate_prompt(body.prompt_template, max_chars=SKILL_PROMPT_MAX_CHARS)
    if not validation.valid:
        raise HTTPException(
            status_code=422,
            detail=validation.reason,
            headers={"X-Blocked-Patterns": ",".join(validation.blocked_patterns)},
        )

    skill_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO skills "
            "(id, name, description, category, execution_pattern, invocation_mode, "
            "pipeline_trigger, prompt_template, input_schema, output_schema, "
            "tool_dependencies, llm_config, scope, status, mandatory, plan_required, created_by) "
            "VALUES "
            "(:id, :name, :description, :category, :execution_pattern, :invocation_mode, "
            ":pipeline_trigger, :prompt_template, CAST(:input_schema AS jsonb), "
            "CAST(:output_schema AS jsonb), CAST(:tool_dependencies AS jsonb), "
            "CAST(:llm_config AS jsonb), 'platform', 'draft', :mandatory, :plan_required, :created_by)"
        ),
        {
            "id": skill_id,
            "name": body.name,
            "description": body.description,
            "category": body.category,
            "execution_pattern": body.execution_pattern,
            "invocation_mode": body.invocation_mode,
            "pipeline_trigger": body.pipeline_trigger,
            "prompt_template": body.prompt_template,
            "input_schema": json.dumps(body.input_schema),
            "output_schema": json.dumps(body.output_schema),
            "tool_dependencies": json.dumps(body.tool_dependencies),
            "llm_config": json.dumps(body.llm_config),
            "mandatory": body.mandatory,
            "plan_required": body.plan_required,
            "created_by": current_user.id,
        },
    )
    await db.commit()
    logger.info("platform_skill_created", skill_id=skill_id)
    return {"id": skill_id, "status": "draft"}


@platform_admin_router.get("/{skill_id}")
async def platform_get_skill(
    skill_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Get platform skill detail. Platform admin only."""
    await _get_platform_rls_context(db)
    result = await db.execute(
        text(
            "SELECT id, name, description, category, version, "
            "execution_pattern, invocation_mode, pipeline_trigger, prompt_template, "
            "input_schema, output_schema, tool_dependencies, llm_config, "
            "mandatory, plan_required, status, published_at, created_at, updated_at "
            "FROM skills WHERE id = :skill_id AND scope = 'platform'"
        ),
        {"skill_id": skill_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Platform skill not found")

    def _load(v):
        return json.loads(v) if isinstance(v, str) else (v or {})

    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "category": row["category"],
        "version": row["version"],
        "execution_pattern": row["execution_pattern"],
        "invocation_mode": row["invocation_mode"],
        "pipeline_trigger": row["pipeline_trigger"],
        "prompt_template": row["prompt_template"],
        "input_schema": _load(row["input_schema"]),
        "output_schema": _load(row["output_schema"]),
        "tool_dependencies": _load(row["tool_dependencies"]) if row["tool_dependencies"] else [],
        "llm_config": _load(row["llm_config"]),
        "mandatory": row["mandatory"],
        "plan_required": row["plan_required"],
        "status": row["status"],
        "scope": "platform",
        "published_at": str(row["published_at"]) if row["published_at"] else None,
        "created_at": str(row["created_at"]) if row["created_at"] else None,
        "updated_at": str(row["updated_at"]) if row["updated_at"] else None,
    }


@platform_admin_router.put("/{skill_id}")
async def platform_update_skill(
    skill_id: str,
    body: PlatformUpdateSkillRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Update a platform skill. Platform admin only."""
    await _get_platform_rls_context(db)
    if body.prompt_template is not None:
        validation = validate_prompt(body.prompt_template, max_chars=SKILL_PROMPT_MAX_CHARS)
        if not validation.valid:
            raise HTTPException(
                status_code=422,
                detail=validation.reason,
                headers={"X-Blocked-Patterns": ",".join(validation.blocked_patterns)},
            )
    if body.execution_pattern is not None and body.execution_pattern not in _VALID_EXECUTION_PATTERNS:
        raise HTTPException(
            status_code=422,
            detail=f"execution_pattern must be one of {sorted(_VALID_EXECUTION_PATTERNS)}",
        )
    if body.invocation_mode is not None and body.invocation_mode not in _VALID_INVOCATION_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"invocation_mode must be one of {sorted(_VALID_INVOCATION_MODES)}",
        )

    updates = body.model_dump(exclude_none=True)
    set_clauses = []
    params: dict = {"skill_id": skill_id}

    for field_name, sql_fragment in _PLATFORM_SKILL_UPDATE_ALLOWLIST.items():
        if field_name in updates:
            set_clauses.append(sql_fragment)
            val = updates[field_name]
            if field_name in ("input_schema", "output_schema", "tool_dependencies", "llm_config"):
                params[field_name] = json.dumps(val)
            else:
                params[field_name] = val

    if not set_clauses:
        raise HTTPException(status_code=422, detail="No valid fields to update")

    set_clauses.append("updated_at = NOW()")
    set_sql = ", ".join(set_clauses)

    result = await db.execute(
        text(f"UPDATE skills SET {set_sql} WHERE id = :skill_id AND scope = 'platform'"),  # noqa: S608
        params,
    )
    if (result.rowcount or 0) == 0:
        raise HTTPException(status_code=404, detail="Platform skill not found")
    await db.commit()
    return {"status": "updated", "skill_id": skill_id}


@platform_admin_router.post("/{skill_id}/publish")
async def platform_publish_skill(
    skill_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Publish a draft platform skill. Platform admin only."""
    await _get_platform_rls_context(db)
    result = await db.execute(
        text(
            "SELECT id, status, prompt_template FROM skills "
            "WHERE id = :skill_id AND scope = 'platform'"
        ),
        {"skill_id": skill_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Platform skill not found")
    if row["status"] != "draft":
        raise HTTPException(
            status_code=409,
            detail=f"Only draft skills can be published (current status: {row['status']})",
        )

    if row["prompt_template"]:
        validation = validate_prompt(row["prompt_template"], max_chars=SKILL_PROMPT_MAX_CHARS)
        if not validation.valid:
            raise HTTPException(
                status_code=422,
                detail=f"Skill prompt failed validation: {validation.reason}",
            )

    await db.execute(
        text(
            "UPDATE skills SET status = 'published', published_at = NOW(), "
            "updated_at = NOW() WHERE id = :skill_id AND scope = 'platform'"
        ),
        {"skill_id": skill_id},
    )
    await db.commit()
    logger.info("platform_skill_published", skill_id=skill_id)
    return {"status": "published", "skill_id": skill_id}


@platform_admin_router.post("/{skill_id}/deprecate")
async def platform_deprecate_skill(
    skill_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Deprecate a published platform skill. Platform admin only."""
    await _get_platform_rls_context(db)
    result = await db.execute(
        text(
            "SELECT id, status FROM skills "
            "WHERE id = :skill_id AND scope = 'platform'"
        ),
        {"skill_id": skill_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Platform skill not found")
    if row["status"] != "published":
        raise HTTPException(
            status_code=409,
            detail=f"Only published skills can be deprecated (current status: {row['status']})",
        )

    await db.execute(
        text(
            "UPDATE skills SET status = 'deprecated', updated_at = NOW() "
            "WHERE id = :skill_id AND scope = 'platform'"
        ),
        {"skill_id": skill_id},
    )
    await db.commit()
    logger.info("platform_skill_deprecated", skill_id=skill_id)
    return {"status": "deprecated", "skill_id": skill_id}


@platform_admin_router.delete("/{skill_id}")
async def platform_delete_skill(
    skill_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Delete a draft platform skill. 409 if published or deprecated. Platform admin only."""
    await _get_platform_rls_context(db)
    result = await db.execute(
        text("SELECT status FROM skills WHERE id = :skill_id AND scope = 'platform'"),
        {"skill_id": skill_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Platform skill not found")
    if row["status"] in ("published", "deprecated"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete a {row['status']} skill. Deprecate it first.",
        )

    await db.execute(
        text("DELETE FROM skills WHERE id = :skill_id AND scope = 'platform'"),
        {"skill_id": skill_id},
    )
    await db.commit()
    return {"status": "deleted", "skill_id": skill_id}
