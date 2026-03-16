"""
Platform LLM Library API (P2LLM-005).

Platform admins manage the curated list of LLM models available to tenants.
All endpoints require platform admin scope.

Status lifecycle:
    Draft → Published  (via POST /{id}/publish — validates pricing non-null)
    Published → Deprecated  (via POST /{id}/deprecate)
    Deprecated → any: BLOCKED with 409

Endpoints:
    POST   /platform/llm-library                    — create Draft entry
    GET    /platform/llm-library                    — list all (filter: ?status=)
    GET    /platform/llm-library/{id}               — get detail
    PATCH  /platform/llm-library/{id}               — update (Deprecated blocked)
    POST   /platform/llm-library/{id}/publish       — Draft → Published
    POST   /platform/llm-library/{id}/deprecate     — Published → Deprecated
    POST   /platform/llm-library/{id}/test          — run 3 fixed prompts (PA-002)
    GET    /platform/llm-library/{id}/tenant-assignments — tenants using this entry (PA-004)
"""
import asyncio
import json
import time
import uuid
from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_platform_admin
from app.core.session import get_async_session

# Test harness constants (PA-002)
_TEST_PROMPTS = [
    "What is the weather?",
    "Summarize this text.",
    "Translate: Bonjour",
]
_TEST_TIMEOUT_SECONDS = 30

logger = structlog.get_logger()

router = APIRouter(prefix="/platform/llm-library", tags=["platform-llm-library"])

# ---------------------------------------------------------------------------
# Allowlists
# ---------------------------------------------------------------------------

_VALID_PROVIDERS = frozenset({"azure_openai", "openai_direct", "anthropic"})
_VALID_STATUSES = frozenset({"Draft", "Published", "Deprecated"})
_UPDATE_ALLOWLIST = frozenset(
    {
        "display_name",
        "plan_tier",
        "is_recommended",
        "best_practices_md",
        "pricing_per_1k_tokens_in",
        "pricing_per_1k_tokens_out",
    }
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateLLMLibraryRequest(BaseModel):
    provider: str = Field(
        ..., description="One of: azure_openai, openai_direct, anthropic"
    )
    model_name: str = Field(..., max_length=200)
    display_name: str = Field(..., max_length=200)
    plan_tier: str = Field(..., max_length=50)
    is_recommended: bool = False
    best_practices_md: Optional[str] = None
    pricing_per_1k_tokens_in: Optional[Decimal] = Field(None, ge=0)
    pricing_per_1k_tokens_out: Optional[Decimal] = Field(None, ge=0)

    model_config = {"arbitrary_types_allowed": True, "protected_namespaces": ()}

    def validate_provider(self) -> None:
        if self.provider not in _VALID_PROVIDERS:
            raise ValueError(
                f"provider must be one of {sorted(_VALID_PROVIDERS)}, got {self.provider!r}"
            )


class UpdateLLMLibraryRequest(BaseModel):
    display_name: Optional[str] = Field(None, max_length=200)
    plan_tier: Optional[str] = Field(None, max_length=50)
    is_recommended: Optional[bool] = None
    best_practices_md: Optional[str] = None
    pricing_per_1k_tokens_in: Optional[Decimal] = Field(None, ge=0)
    pricing_per_1k_tokens_out: Optional[Decimal] = Field(None, ge=0)

    model_config = {"arbitrary_types_allowed": True, "protected_namespaces": ()}


class LLMLibraryEntry(BaseModel):
    id: str
    provider: str
    model_name: str
    display_name: str
    plan_tier: str
    is_recommended: bool
    status: str
    best_practices_md: Optional[str] = None
    pricing_per_1k_tokens_in: Optional[float] = None
    pricing_per_1k_tokens_out: Optional[float] = None
    created_at: str
    updated_at: str

    model_config = {"protected_namespaces": ()}


class TestPromptResult(BaseModel):
    """Result of running one test prompt against the profile's models (PA-002)."""

    prompt: str
    response: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    estimated_cost_usd: Optional[float] = None

    model_config = {"protected_namespaces": ()}


class ProfileTestResponse(BaseModel):
    """Response from POST /platform/llm-library/{id}/test (PA-002)."""

    tests: list[TestPromptResult]

    model_config = {"protected_namespaces": ()}


class TenantAssignment(BaseModel):
    """One tenant currently using an llm_library entry (PA-004)."""

    tenant_id: str
    tenant_name: str
    assigned_at: str

    model_config = {"protected_namespaces": ()}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _row_to_entry(row) -> LLMLibraryEntry:
    """Convert a DB row tuple to LLMLibraryEntry."""
    return LLMLibraryEntry(
        id=str(row[0]),
        provider=row[1],
        model_name=row[2],
        display_name=row[3],
        plan_tier=row[4],
        is_recommended=row[5],
        status=row[6],
        best_practices_md=row[7],
        pricing_per_1k_tokens_in=float(row[8]) if row[8] is not None else None,
        pricing_per_1k_tokens_out=float(row[9]) if row[9] is not None else None,
        created_at=row[10].isoformat() if row[10] else "",
        updated_at=row[11].isoformat() if row[11] else "",
    )


async def _get_entry(entry_id: str, db: AsyncSession) -> LLMLibraryEntry | None:
    """Fetch a single entry by ID. Returns None if not found or if entry_id is not a valid UUID."""
    try:
        uuid.UUID(entry_id)
    except (ValueError, AttributeError):
        return None
    result = await db.execute(
        text(
            "SELECT id, provider, model_name, display_name, plan_tier, "
            "is_recommended, status, best_practices_md, "
            "pricing_per_1k_tokens_in, pricing_per_1k_tokens_out, "
            "created_at, updated_at "
            "FROM llm_library WHERE id = :id"
        ),
        {"id": entry_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return _row_to_entry(row)


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post("", response_model=LLMLibraryEntry, status_code=status.HTTP_201_CREATED)
async def create_llm_library_entry(
    request: CreateLLMLibraryRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Create a new LLM Library entry in Draft status."""
    if request.provider not in _VALID_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"provider must be one of {sorted(_VALID_PROVIDERS)}",
        )

    entry_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO llm_library ("
            "  id, provider, model_name, display_name, plan_tier, "
            "  is_recommended, status, best_practices_md, "
            "  pricing_per_1k_tokens_in, pricing_per_1k_tokens_out"
            ") VALUES ("
            "  :id, :provider, :model_name, :display_name, :plan_tier, "
            "  :is_recommended, 'Draft', :best_practices_md, "
            "  :pricing_in, :pricing_out"
            ")"
        ),
        {
            "id": entry_id,
            "provider": request.provider,
            "model_name": request.model_name,
            "display_name": request.display_name,
            "plan_tier": request.plan_tier,
            "is_recommended": request.is_recommended,
            "best_practices_md": request.best_practices_md,
            "pricing_in": (
                str(request.pricing_per_1k_tokens_in)
                if request.pricing_per_1k_tokens_in is not None
                else None
            ),
            "pricing_out": (
                str(request.pricing_per_1k_tokens_out)
                if request.pricing_per_1k_tokens_out is not None
                else None
            ),
        },
    )
    await db.commit()

    entry = await _get_entry(entry_id, db)
    if entry is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve created entry")

    logger.info(
        "llm_library_entry_created",
        entry_id=entry_id,
        provider=request.provider,
        model_name=request.model_name,
    )
    return entry


@router.get("", response_model=list[LLMLibraryEntry])
async def list_llm_library_entries(
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """List all LLM Library entries. Optionally filter by status."""
    if status_filter is not None and status_filter not in _VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of {sorted(_VALID_STATUSES)}",
        )

    if status_filter:
        result = await db.execute(
            text(
                "SELECT id, provider, model_name, display_name, plan_tier, "
                "is_recommended, status, best_practices_md, "
                "pricing_per_1k_tokens_in, pricing_per_1k_tokens_out, "
                "created_at, updated_at "
                "FROM llm_library WHERE status = :status "
                "ORDER BY created_at DESC"
            ),
            {"status": status_filter},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, provider, model_name, display_name, plan_tier, "
                "is_recommended, status, best_practices_md, "
                "pricing_per_1k_tokens_in, pricing_per_1k_tokens_out, "
                "created_at, updated_at "
                "FROM llm_library ORDER BY created_at DESC"
            )
        )

    rows = result.fetchall()
    return [_row_to_entry(r) for r in rows]


@router.get("/{entry_id}", response_model=LLMLibraryEntry)
async def get_llm_library_entry(
    entry_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Get a single LLM Library entry by ID."""
    entry = await _get_entry(entry_id, db)
    if entry is None:
        raise HTTPException(status_code=404, detail="LLM Library entry not found")
    return entry


@router.patch("/{entry_id}", response_model=LLMLibraryEntry)
async def update_llm_library_entry(
    entry_id: str,
    request: UpdateLLMLibraryRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Update an LLM Library entry. Deprecated entries cannot be updated."""
    entry = await _get_entry(entry_id, db)
    if entry is None:
        raise HTTPException(status_code=404, detail="LLM Library entry not found")

    if entry.status == "Deprecated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Deprecated entries cannot be modified.",
        )

    updates = request.model_dump(exclude_none=True)
    if not updates:
        return entry

    # Build parameterized SET clause from allowlist only
    set_parts = []
    params: dict = {"id": entry_id}

    if "display_name" in updates and "display_name" in _UPDATE_ALLOWLIST:
        set_parts.append("display_name = :display_name")
        params["display_name"] = updates["display_name"]
    if "plan_tier" in updates and "plan_tier" in _UPDATE_ALLOWLIST:
        set_parts.append("plan_tier = :plan_tier")
        params["plan_tier"] = updates["plan_tier"]
    if "is_recommended" in updates and "is_recommended" in _UPDATE_ALLOWLIST:
        set_parts.append("is_recommended = :is_recommended")
        params["is_recommended"] = updates["is_recommended"]
    if "best_practices_md" in updates and "best_practices_md" in _UPDATE_ALLOWLIST:
        set_parts.append("best_practices_md = :best_practices_md")
        params["best_practices_md"] = updates["best_practices_md"]
    if (
        "pricing_per_1k_tokens_in" in updates
        and "pricing_per_1k_tokens_in" in _UPDATE_ALLOWLIST
    ):
        set_parts.append("pricing_per_1k_tokens_in = :pricing_in")
        params["pricing_in"] = str(updates["pricing_per_1k_tokens_in"])
    if (
        "pricing_per_1k_tokens_out" in updates
        and "pricing_per_1k_tokens_out" in _UPDATE_ALLOWLIST
    ):
        set_parts.append("pricing_per_1k_tokens_out = :pricing_out")
        params["pricing_out"] = str(updates["pricing_per_1k_tokens_out"])

    if not set_parts:
        return entry

    set_parts.append("updated_at = NOW()")
    # set_parts contains ONLY hardcoded literal strings from the allowlist checks above
    # (e.g. "display_name = :display_name", "updated_at = NOW()"). User input is bound
    # via named params — never interpolated into the SQL string.
    sql = f"UPDATE llm_library SET {', '.join(set_parts)} WHERE id = :id"  # noqa: S608

    result = await db.execute(text(sql), params)
    if (result.rowcount or 0) == 0:
        return entry

    await db.commit()

    updated = await _get_entry(entry_id, db)
    if updated is None:
        raise HTTPException(
            status_code=404, detail="LLM Library entry not found after update"
        )

    logger.info(
        "llm_library_entry_updated", entry_id=entry_id, fields=list(updates.keys())
    )
    return updated


@router.post("/{entry_id}/publish", response_model=LLMLibraryEntry)
async def publish_llm_library_entry(
    entry_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Transition an entry from Draft to Published. Validates required fields."""
    entry = await _get_entry(entry_id, db)
    if entry is None:
        raise HTTPException(status_code=404, detail="LLM Library entry not found")

    if entry.status != "Draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only Draft entries can be published. Current status: {entry.status}",
        )

    # Validate required fields for publishing
    if not entry.model_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="model_name is required before publishing",
        )
    if not entry.provider:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provider is required before publishing",
        )
    if (
        entry.pricing_per_1k_tokens_in is None
        or entry.pricing_per_1k_tokens_out is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="pricing_per_1k_tokens_in and pricing_per_1k_tokens_out must be set before publishing",
        )

    result = await db.execute(
        text(
            "UPDATE llm_library SET status = 'Published', updated_at = NOW() "
            "WHERE id = :id AND status = 'Draft'"
        ),
        {"id": entry_id},
    )
    if (result.rowcount or 0) == 0:
        raise HTTPException(
            status_code=409, detail="Could not publish entry (concurrent modification?)"
        )

    await db.commit()

    updated = await _get_entry(entry_id, db)
    if updated is None:
        raise HTTPException(
            status_code=404, detail="LLM Library entry not found after publish"
        )

    logger.info("llm_library_entry_published", entry_id=entry_id)
    return updated


@router.post("/{entry_id}/deprecate", response_model=LLMLibraryEntry)
async def deprecate_llm_library_entry(
    entry_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Transition an entry from Published to Deprecated."""
    entry = await _get_entry(entry_id, db)
    if entry is None:
        raise HTTPException(status_code=404, detail="LLM Library entry not found")

    if entry.status != "Published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only Published entries can be deprecated. Current status: {entry.status}",
        )

    result = await db.execute(
        text(
            "UPDATE llm_library SET status = 'Deprecated', updated_at = NOW() "
            "WHERE id = :id AND status = 'Published'"
        ),
        {"id": entry_id},
    )
    if (result.rowcount or 0) == 0:
        raise HTTPException(
            status_code=409,
            detail="Could not deprecate entry (concurrent modification?)",
        )

    await db.commit()

    updated = await _get_entry(entry_id, db)
    if updated is None:
        raise HTTPException(
            status_code=404, detail="LLM Library entry not found after deprecate"
        )

    logger.info("llm_library_entry_deprecated", entry_id=entry_id)
    return updated


# ---------------------------------------------------------------------------
# PA-002: Profile test harness
# ---------------------------------------------------------------------------


def _calculate_test_cost(
    tokens_in: int,
    tokens_out: int,
    price_in: Optional[float],
    price_out: Optional[float],
) -> Optional[float]:
    """
    Compute estimated cost for one test call.

    Formula: (tokens_in / 1000 * price_in) + (tokens_out / 1000 * price_out)
    Returns None if either price is unavailable.
    """
    if price_in is None or price_out is None:
        return None
    cost = (tokens_in / 1000.0 * price_in) + (tokens_out / 1000.0 * price_out)
    return round(cost, 8)


async def _run_single_test_prompt(
    prompt: str,
    model: str,
    price_in: Optional[float],
    price_out: Optional[float],
) -> TestPromptResult:
    """
    Call AzureOpenAIProvider with one prompt and return a TestPromptResult.

    Uses PRIMARY_MODEL-equivalent env-derived adapter (not tenant config —
    the test harness calls the profile's configured model directly).
    """
    from app.core.llm.azure_openai import AzureOpenAIProvider

    adapter = AzureOpenAIProvider()
    messages = [{"role": "user", "content": prompt}]
    response = await adapter.complete(messages=messages, model=model)

    cost = _calculate_test_cost(
        tokens_in=response.tokens_in,
        tokens_out=response.tokens_out,
        price_in=price_in,
        price_out=price_out,
    )

    return TestPromptResult(
        prompt=prompt,
        response=response.content,
        tokens_in=response.tokens_in,
        tokens_out=response.tokens_out,
        latency_ms=response.latency_ms,
        estimated_cost_usd=cost,
    )


@router.post("/{entry_id}/test", response_model=ProfileTestResponse)
async def test_llm_library_profile(
    entry_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Run 3 fixed test prompts against this library entry's configured model (PA-002).

    Works on Draft and Published entries alike. Sends to the entry's model_name
    via the platform AzureOpenAI adapter. Estimated cost is computed from the
    entry's pricing_per_1k_tokens_in/out fields when available.

    Returns 504 if the LLM calls exceed 30 seconds total.
    """
    entry = await _get_entry(entry_id, db)
    if entry is None:
        raise HTTPException(status_code=404, detail="LLM Library entry not found")

    if entry.status == "Deprecated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot test a Deprecated entry.",
        )

    price_in = entry.pricing_per_1k_tokens_in
    price_out = entry.pricing_per_1k_tokens_out
    model = entry.model_name

    try:
        tasks = [
            _run_single_test_prompt(
                prompt=p,
                model=model,
                price_in=price_in,
                price_out=price_out,
            )
            for p in _TEST_PROMPTS
        ]
        results = await asyncio.wait_for(
            asyncio.gather(*tasks),
            timeout=_TEST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"LLM test calls exceeded {_TEST_TIMEOUT_SECONDS}s timeout.",
        )
    except Exception as exc:
        logger.warning(
            "llm_library_test_failed",
            entry_id=entry_id,
            model=model,
            error=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail="LLM call failed — check server logs for details",
        )

    logger.info(
        "llm_library_profile_tested",
        entry_id=entry_id,
        model=model,
        prompt_count=len(_TEST_PROMPTS),
    )
    return ProfileTestResponse(tests=list(results))


# ---------------------------------------------------------------------------
# PA-004: Tenant assignment listing
# ---------------------------------------------------------------------------


@router.get("/{entry_id}/tenant-assignments", response_model=list[TenantAssignment])
async def list_tenant_assignments(
    entry_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    List all tenants whose llm_config is set to model_source=library and
    llm_library_id=this entry (PA-004).

    Tenants continue using Deprecated profiles unaffected.
    Returns tenant_id, tenant_name, and assigned_at (tenant_configs.updated_at).
    """
    # Verify entry exists (any status)
    entry = await _get_entry(entry_id, db)
    if entry is None:
        raise HTTPException(status_code=404, detail="LLM Library entry not found")

    result = await db.execute(
        text(
            "SELECT tc.tenant_id, t.name, tc.updated_at "
            "FROM tenant_configs tc "
            "JOIN tenants t ON t.id = tc.tenant_id "
            "WHERE tc.config_type = 'llm_config' "
            "  AND tc.config_data->>'model_source' = 'library' "
            "  AND tc.config_data->>'llm_library_id' = :entry_id "
            "ORDER BY tc.updated_at DESC"
        ),
        {"entry_id": entry_id},
    )
    rows = result.fetchall()

    assignments = [
        TenantAssignment(
            tenant_id=str(row[0]),
            tenant_name=row[1],
            assigned_at=row[2].isoformat() if row[2] else "",
        )
        for row in rows
    ]

    logger.info(
        "llm_library_tenant_assignments_listed",
        entry_id=entry_id,
        count=len(assignments),
    )
    return assignments
