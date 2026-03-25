"""
Platform LLM Library API (P2LLM-005).

Platform admins manage the curated list of LLM models available to tenants.
All endpoints require platform admin scope.

Status lifecycle:
    Draft → Published  (via POST /{id}/publish — validates credentials + test result)
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

Security invariants:
    - api_key_encrypted is NEVER in _SELECT_COLUMNS — fetched only in /test via separate query
    - api_key is NEVER returned in any response — only key_present: bool and api_key_last4
    - Decrypted key is ALWAYS cleared in finally block
    - api_key plaintext is cleared immediately after encryption in create/update handlers
"""
import asyncio
import re
import time
import uuid
from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_platform_admin
from app.core.security.ssrf import SSRFBlockedError, resolve_and_pin_url_sync
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

_VALID_PROVIDERS = frozenset({"azure_openai", "openai_direct", "anthropic", "bedrock", "ollama"})
_VALID_STATUSES = frozenset({"draft", "published", "deprecated", "disabled"})
_UPDATE_ALLOWLIST = frozenset(
    {
        "display_name",
        "model_name",
        "plan_tier",
        "is_recommended",
        "best_practices_md",
        "pricing_per_1k_tokens_in",
        "pricing_per_1k_tokens_out",
        "endpoint_url",
        "api_version",
        # capabilities handled via explicit JSONB cast path in update handler
        # api_key intentionally excluded — handled via explicit encryption path in update handler
    }
)

# Columns safe to return in all SELECT queries.
# api_key_encrypted is NEVER in this list — it is fetched only in the test endpoint
# via a separate query. key_present is derived as a computed bool from the encrypted column.
_SELECT_COLUMNS = (
    "id, provider, model_name, display_name, plan_tier, "
    "is_recommended, status, best_practices_md, "
    "pricing_per_1k_tokens_in, pricing_per_1k_tokens_out, "
    "created_at, updated_at, "
    "endpoint_url, capabilities, "
    "(api_key_encrypted IS NOT NULL) AS key_present, "
    "api_key_last4, api_version, last_test_passed_at, "
    "health_status, health_checked_at, "
    "(SELECT COUNT(*) FROM llm_profiles WHERE "
    "chat_library_id = llm_library.id OR intent_library_id = llm_library.id OR "
    "vision_library_id = llm_library.id OR agent_library_id = llm_library.id"
    ") AS profile_usage_count"
)

# api_version format: YYYY-MM-DD or YYYY-MM-DD-preview
_API_VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(-preview)?$")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateLLMLibraryRequest(BaseModel):
    provider: str = Field(
        ..., description="One of: azure_openai, openai_direct, anthropic, bedrock, ollama"
    )
    model_name: str = Field(..., max_length=200)
    display_name: str = Field(..., max_length=200)
    plan_tier: str = Field(..., max_length=50)
    is_recommended: bool = False
    best_practices_md: Optional[str] = Field(None, max_length=50000)
    pricing_per_1k_tokens_in: Optional[Decimal] = Field(None, ge=0)
    pricing_per_1k_tokens_out: Optional[Decimal] = Field(None, ge=0)
    endpoint_url: Optional[str] = Field(
        None, max_length=500, description="Required for azure_openai, bedrock, and ollama"
    )
    api_key: Optional[str] = Field(
        None,
        min_length=8,
        description="Plaintext API key — encrypted before storage, never returned",
    )
    api_version: Optional[str] = Field(
        None,
        max_length=50,
        description="Required for azure_openai, e.g. 2024-12-01-preview",
    )
    capabilities: Optional[dict] = Field(
        None,
        description="eligible_slots, supports_vision, supports_function_calling, context_window",
    )

    model_config = {"arbitrary_types_allowed": True, "protected_namespaces": ()}

    def validate_provider(self) -> None:
        if self.provider not in _VALID_PROVIDERS:
            raise ValueError(
                f"provider must be one of {sorted(_VALID_PROVIDERS)}, got {self.provider!r}"
            )

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        from urllib.parse import urlparse

        parsed = urlparse(v)
        # Allow http:// only for localhost/loopback (Ollama local deployments)
        _localhost_names = {"localhost", "127.0.0.1", "::1"}
        is_localhost = parsed.hostname in _localhost_names
        if not v.startswith("https://") and not (v.startswith("http://") and is_localhost):
            raise ValueError(
                "endpoint_url must start with https:// (or http:// for localhost)"
            )
        if not parsed.hostname:
            raise ValueError("endpoint_url must have a valid hostname")
        return v

    @field_validator("api_version")
    @classmethod
    def validate_api_version(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _API_VERSION_RE.match(v):
            raise ValueError(
                "api_version must match YYYY-MM-DD or YYYY-MM-DD-preview format"
            )
        return v


class UpdateLLMLibraryRequest(BaseModel):
    model_name: Optional[str] = Field(None, max_length=200)
    display_name: Optional[str] = Field(None, max_length=200)
    plan_tier: Optional[str] = Field(None, max_length=50)
    is_recommended: Optional[bool] = None
    best_practices_md: Optional[str] = Field(None, max_length=50000)
    pricing_per_1k_tokens_in: Optional[Decimal] = Field(None, ge=0)
    pricing_per_1k_tokens_out: Optional[Decimal] = Field(None, ge=0)
    endpoint_url: Optional[str] = Field(None, max_length=500)
    api_key: Optional[str] = Field(
        None,
        min_length=8,
        description="Plaintext API key — encrypted before storage, never returned",
    )
    api_version: Optional[str] = Field(None, max_length=50)
    capabilities: Optional[dict] = None

    model_config = {"arbitrary_types_allowed": True, "protected_namespaces": ()}

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        from urllib.parse import urlparse

        parsed = urlparse(v)
        # Allow http:// only for localhost/loopback (Ollama local deployments)
        _localhost_names = {"localhost", "127.0.0.1", "::1"}
        is_localhost = parsed.hostname in _localhost_names
        if not v.startswith("https://") and not (v.startswith("http://") and is_localhost):
            raise ValueError(
                "endpoint_url must start with https:// (or http:// for localhost)"
            )
        if not parsed.hostname:
            raise ValueError("endpoint_url must have a valid hostname")
        return v

    @field_validator("api_version")
    @classmethod
    def validate_api_version(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _API_VERSION_RE.match(v):
            raise ValueError(
                "api_version must match YYYY-MM-DD or YYYY-MM-DD-preview format"
            )
        return v


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
    # Credential metadata — api_key_encrypted is NEVER a field here
    endpoint_url: Optional[str] = None
    capabilities: Optional[dict] = None
    api_version: Optional[str] = None
    key_present: bool = False
    api_key_last4: Optional[str] = None
    last_test_passed_at: Optional[str] = None
    health_status: Optional[str] = None
    health_checked_at: Optional[str] = None
    created_at: str
    updated_at: str
    profile_usage_count: int = 0

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

# Column index map for _SELECT_COLUMNS (21 columns, 0-indexed):
#   0: id
#   1: provider
#   2: model_name
#   3: display_name
#   4: plan_tier
#   5: is_recommended
#   6: status
#   7: best_practices_md
#   8: pricing_per_1k_tokens_in
#   9: pricing_per_1k_tokens_out
#  10: created_at
#  11: updated_at
#  12: endpoint_url
#  13: capabilities  (JSONB)
#  14: key_present  (computed bool: api_key_encrypted IS NOT NULL)
#  15: api_key_last4
#  16: api_version
#  17: last_test_passed_at
#  18: health_status
#  19: health_checked_at
#  20: profile_usage_count  (correlated subquery: count of llm_profiles referencing this entry)


def _row_to_entry(row) -> LLMLibraryEntry:
    """Convert a DB row tuple (from _SELECT_COLUMNS) to LLMLibraryEntry.

    Row[13] is a computed bool (api_key_encrypted IS NOT NULL) — never raw bytes.
    """
    import json as _json
    caps = row[13]
    if isinstance(caps, str):
        caps = _json.loads(caps)
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
        endpoint_url=row[12],
        capabilities=caps,
        key_present=bool(row[14]),
        api_key_last4=row[15],
        api_version=row[16],
        last_test_passed_at=row[17].isoformat() if row[17] else None,
        health_status=row[18],
        health_checked_at=row[19].isoformat() if row[19] else None,
        profile_usage_count=int(row[20]) if row[20] is not None else 0,
    )


async def _get_entry(entry_id: str, db: AsyncSession) -> LLMLibraryEntry | None:
    """Fetch a single entry by ID. Returns None if not found or entry_id is not a valid UUID."""
    try:
        uuid.UUID(entry_id)
    except (ValueError, AttributeError):
        return None
    result = await db.execute(
        text(
            f"SELECT {_SELECT_COLUMNS} FROM llm_library WHERE id = :id"  # noqa: S608
        ),
        {"id": entry_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return _row_to_entry(row)


async def _get_encrypted_key(entry_id: str, db: AsyncSession) -> Optional[bytes]:
    """
    Fetch only the api_key_encrypted BYTEA for an entry.

    This is intentionally separate from _get_entry / _SELECT_COLUMNS so that
    encrypted bytes are never accidentally included in a normal response path.
    Called only by the test harness endpoint.
    """
    result = await db.execute(
        text("SELECT api_key_encrypted FROM llm_library WHERE id = :id"),
        {"id": entry_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return bytes(row[0]) if row[0] is not None else None


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


def _validate_bedrock_region_consistency(
    provider: str,
    endpoint_url: Optional[str],
    model_name: Optional[str],
) -> None:
    """
    Cross-validate Bedrock region in ARN vs endpoint_url.

    Only fires when provider == 'bedrock', both fields are present,
    and model_name looks like an ARN (starts with 'arn:aws:bedrock:').
    Skips the check silently for non-ARN model IDs (short model names).
    Raises HTTPException(422) on mismatch.
    """
    if provider != "bedrock":
        return
    if not endpoint_url or not model_name:
        return
    if not model_name.startswith("arn:aws:bedrock:"):
        return
    arn_parts = model_name.split(":")
    if len(arn_parts) < 4:
        return
    arn_region = arn_parts[3]
    url_parts = endpoint_url.replace("https://", "").split(".")
    if len(url_parts) < 2:
        return
    url_region = url_parts[1]
    if arn_region and url_region and arn_region != url_region:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Region mismatch: endpoint_url is '{url_region}' but "
                f"model identifier is '{arn_region}'"
            ),
        )


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

    # BEDROCK-005: cross-validate region when both endpoint_url and ARN model_name present
    _validate_bedrock_region_consistency(
        request.provider, request.endpoint_url, request.model_name
    )

    entry_id = str(uuid.uuid4())

    # Encrypt API key before storage — never store plaintext
    encrypted_key = None
    key_last4 = None
    if request.api_key:
        from app.core.crypto import encrypt_api_key

        encrypted_key = encrypt_api_key(request.api_key)
        key_last4 = (
            request.api_key[-4:] if len(request.api_key) >= 4 else request.api_key
        )
        # Clear plaintext immediately after encryption
        request.api_key = ""

    import json as _json

    caps_json = _json.dumps(request.capabilities) if request.capabilities is not None else None

    await db.execute(
        text(
            "INSERT INTO llm_library ("
            "  id, provider, model_name, display_name, plan_tier, "
            "  is_recommended, status, best_practices_md, "
            "  pricing_per_1k_tokens_in, pricing_per_1k_tokens_out, "
            "  endpoint_url, api_key_encrypted, api_key_last4, api_version, "
            "  capabilities"
            ") VALUES ("
            "  :id, :provider, :model_name, :display_name, :plan_tier, "
            "  :is_recommended, 'draft', :best_practices_md, "
            "  :pricing_in, :pricing_out, "
            "  :endpoint_url, :api_key_encrypted, :api_key_last4, :api_version, "
            "  CAST(:capabilities AS jsonb)"
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
            "endpoint_url": request.endpoint_url,
            "api_key_encrypted": encrypted_key,
            "api_key_last4": key_last4,
            "api_version": request.api_version,
            "capabilities": caps_json,
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
        api_key="[REDACTED]",
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
                f"SELECT {_SELECT_COLUMNS} FROM llm_library "  # noqa: S608
                "WHERE status = :status ORDER BY created_at DESC"
            ),
            {"status": status_filter},
        )
    else:
        result = await db.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM llm_library "  # noqa: S608
                "ORDER BY created_at DESC"
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

    if entry.status in ("deprecated", "Deprecated"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Deprecated entries cannot be modified.",
        )

    updates = dict(request.model_dump(exclude_none=True))
    if not updates:
        return entry

    # BEDROCK-005: cross-validate region when updating endpoint_url or model_name for Bedrock
    new_endpoint = updates.get("endpoint_url", entry.endpoint_url)
    new_model = updates.get("model_name", entry.model_name)
    _validate_bedrock_region_consistency(entry.provider, new_endpoint, new_model)

    # Build parameterized SET clause from allowlist + explicit credential paths
    set_parts: list[str] = []
    params: dict = {"id": entry_id}

    # Handle api_key separately — encrypt before storage, reset test timestamp
    credential_changed = False
    if updates.get("api_key"):
        from app.core.crypto import encrypt_api_key

        encrypted_key = encrypt_api_key(updates["api_key"])
        key_last4 = (
            updates["api_key"][-4:]
            if len(updates["api_key"]) >= 4
            else updates["api_key"]
        )
        # Clear plaintext immediately
        updates["api_key"] = ""
        set_parts.append("api_key_encrypted = :api_key_encrypted")
        set_parts.append("api_key_last4 = :api_key_last4")
        params["api_key_encrypted"] = encrypted_key
        params["api_key_last4"] = key_last4
        credential_changed = True
        logger.info(
            "llm_library_api_key_updated",
            entry_id=entry_id,
            api_key="[REDACTED]",
        )

    # Allowlist fields — api_key is excluded from this set
    if "display_name" in updates and "display_name" in _UPDATE_ALLOWLIST:
        set_parts.append("display_name = :display_name")
        params["display_name"] = updates["display_name"]
    if "model_name" in updates and "model_name" in _UPDATE_ALLOWLIST:
        set_parts.append("model_name = :model_name")
        params["model_name"] = updates["model_name"]
        # model_name change silently routes tenants to a different model — require re-test
        if updates["model_name"] != entry.model_name:
            credential_changed = True
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
    if "endpoint_url" in updates and "endpoint_url" in _UPDATE_ALLOWLIST:
        set_parts.append("endpoint_url = :endpoint_url")
        params["endpoint_url"] = updates["endpoint_url"]
        credential_changed = True
    if "api_version" in updates and "api_version" in _UPDATE_ALLOWLIST:
        set_parts.append("api_version = :api_version")
        params["api_version"] = updates["api_version"]
        credential_changed = True
    if "capabilities" in updates:
        import json as _json
        set_parts.append("capabilities = CAST(:capabilities AS jsonb)")
        params["capabilities"] = _json.dumps(updates["capabilities"])

    # Reset test result when any credential field changes — old test is no longer valid
    if credential_changed:
        set_parts.append("last_test_passed_at = NULL")

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
    """Transition an entry from Draft to Published. Validates credentials and test result."""
    entry = await _get_entry(entry_id, db)
    if entry is None:
        raise HTTPException(status_code=404, detail="LLM Library entry not found")

    if entry.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only Draft entries can be published. Current status: {entry.status}",
        )

    # Provider-specific required fields
    if entry.provider == "azure_openai":
        if not entry.endpoint_url or not entry.api_version:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Azure OpenAI entries require endpoint_url and api_version before publishing",
            )
    elif entry.provider == "bedrock":
        if not entry.endpoint_url:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Bedrock entries require endpoint_url (BEDROCK_BASE_URL)",
            )
        # api_version explicitly NOT required for bedrock

    # All providers require an API key — Ollama is exempt (no auth required)
    if entry.provider != "ollama" and not entry.key_present:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="api_key must be set before publishing",
        )

    # All providers require a successful connectivity test
    if entry.last_test_passed_at is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Entry must pass a connectivity test before publishing",
        )

    # All providers require pricing
    if (
        entry.pricing_per_1k_tokens_in is None
        or entry.pricing_per_1k_tokens_out is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="pricing_per_1k_tokens_in and pricing_per_1k_tokens_out must be set before publishing",
        )

    # Atomic publish: WHERE clause re-checks all gate conditions so a concurrent
    # PATCH that clears credentials or last_test_passed_at is caught at DB commit time.
    # Ollama does not store an API key, so the api_key_encrypted check is skipped for it.
    key_check = "" if entry.provider == "ollama" else "AND api_key_encrypted IS NOT NULL "
    result = await db.execute(
        text(
            "UPDATE llm_library SET status = 'published', updated_at = NOW() "
            "WHERE id = :id AND status = 'draft' "
            + key_check +
            "AND last_test_passed_at IS NOT NULL"
        ),
        {"id": entry_id},
    )
    if (result.rowcount or 0) == 0:
        raise HTTPException(
            status_code=409,
            detail="Could not publish entry — credentials or test result were modified concurrently.",
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

    if entry.status != "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only Published entries can be deprecated. Current status: {entry.status}",
        )

    if entry.profile_usage_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot deprecate: this entry is assigned to {entry.profile_usage_count} "
                f"LLM Profile{'s' if entry.profile_usage_count != 1 else ''}. "
                "Remove it from all profiles first."
            ),
        )

    result = await db.execute(
        text(
            "UPDATE llm_library SET status = 'deprecated', updated_at = NOW() "
            "WHERE id = :id AND status = 'published'"
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


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_library_entry(
    entry_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Delete a Draft entry. Published and Deprecated entries cannot be deleted."""
    entry = await _get_entry(entry_id, db)
    if entry is None:
        raise HTTPException(status_code=404, detail="LLM Library entry not found")

    if entry.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only Draft entries can be deleted. Use deprecate for Published entries. Current status: {entry.status}",
        )

    await db.execute(
        text("DELETE FROM llm_library WHERE id = :id AND status = 'draft'"),
        {"id": entry_id},
    )
    await db.commit()
    logger.info("llm_library_entry_deleted", entry_id=entry_id)


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


def _assert_endpoint_ssrf_safe(endpoint_url: str) -> None:
    """Validate endpoint_url against the shared SSRF blocklist and pin DNS.

    Delegates to resolve_and_pin_url_sync() from app.core.security.ssrf —
    the canonical shared SSRF module. Raises ValueError on any blocked address,
    DNS failure, or malformed URL.

    Only called at test-time — at field-validation time DNS resolution is not possible.
    The return value (pinned URL) is discarded here because Azure/OpenAI SDK clients
    accept the original endpoint URL and handle DNS internally; the purpose of this
    call is validation only (fail-closed before handing credentials to the SDK).
    """
    try:
        resolve_and_pin_url_sync(endpoint_url)
    except SSRFBlockedError as exc:
        raise ValueError(
            f"endpoint_url is not permitted — SSRF blocked ({exc.code})"
        ) from exc


async def _run_single_test_prompt(
    prompt: str,
    provider: str,
    deployment_name: str,
    api_key: str,
    endpoint_url: Optional[str],
    api_version: Optional[str],
    price_in: Optional[float],
    price_out: Optional[float],
) -> TestPromptResult:
    """
    Call the provider API with one prompt using entry-specific credentials.

    Constructs the appropriate client for each provider type. The api_key
    parameter must already be decrypted — the caller is responsible for
    clearing it in a finally block.
    """
    start = time.time()

    if provider == "azure_openai":
        from openai import AsyncAzureOpenAI

        if endpoint_url:
            _assert_endpoint_ssrf_safe(endpoint_url)
        client = AsyncAzureOpenAI(
            azure_endpoint=endpoint_url,
            api_key=api_key,
            api_version=api_version,
        )
        resp = await client.chat.completions.create(
            model=deployment_name,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = int((time.time() - start) * 1000)
        usage = resp.usage
        tokens_in = usage.prompt_tokens
        tokens_out = usage.completion_tokens
        content = resp.choices[0].message.content or ""

    elif provider in ("openai_direct", "openai"):
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model=deployment_name,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = int((time.time() - start) * 1000)
        usage = resp.usage
        tokens_in = usage.prompt_tokens
        tokens_out = usage.completion_tokens
        content = resp.choices[0].message.content or ""

    elif provider == "anthropic":
        import anthropic  # type: ignore[import]

        client = anthropic.AsyncAnthropic(api_key=api_key)
        msg = await client.messages.create(
            model=deployment_name,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = int((time.time() - start) * 1000)
        tokens_in = msg.usage.input_tokens
        tokens_out = msg.usage.output_tokens
        content = msg.content[0].text if msg.content else ""

    elif provider == "bedrock":
        # BEDROCK-006: Bedrock via OpenAI-compatible endpoint.
        # base_url = {endpoint_url}/v1 — model ARN is passed at call time, NOT in base_url.
        # SSRF check required before any outbound call.
        from openai import AsyncOpenAI

        if not endpoint_url:
            raise ValueError("Bedrock provider requires an endpoint_url (e.g. https://bedrock-runtime.ap-southeast-1.amazonaws.com)")
        _assert_endpoint_ssrf_safe(endpoint_url)
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=f"{endpoint_url.rstrip('/')}/v1",
        )
        resp = await client.chat.completions.create(
            model=deployment_name,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = int((time.time() - start) * 1000)
        usage = resp.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        content = (
            resp.choices[0].message.content or ""
            if resp.choices
            else ""
        )

    elif provider == "ollama":
        # OLLAMA-001: Ollama via OpenAI-compatible endpoint.
        # base_url = {endpoint_url}/v1 — no auth required; api_key defaults to "ollama".
        # SSRF check is intentionally skipped: Ollama is a local-only provider and
        # localhost/loopback endpoints are valid by design. Callers should ensure
        # the Ollama endpoint is not user-controlled in a multi-tenant context.
        from openai import AsyncOpenAI

        if not endpoint_url:
            raise ValueError("Ollama provider requires an endpoint_url (e.g. http://localhost:11434)")
        client = AsyncOpenAI(
            api_key=api_key or "ollama",
            base_url=f"{endpoint_url.rstrip('/')}/v1",
        )
        resp = await client.chat.completions.create(
            model=deployment_name,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,  # Cap to avoid thinking-model runaway (e.g. Qwen3.5)
        )
        latency_ms = int((time.time() - start) * 1000)
        usage = resp.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        content = (
            resp.choices[0].message.content or ""
            if resp.choices
            else ""
        )

    else:
        raise ValueError(f"Unsupported provider for test harness: {provider!r}")

    cost = _calculate_test_cost(tokens_in, tokens_out, price_in, price_out)
    return TestPromptResult(
        prompt=prompt,
        response=content,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        estimated_cost_usd=cost,
    )


@router.post("/{entry_id}/test", response_model=ProfileTestResponse)
async def test_llm_library_profile(
    entry_id: str,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Run 3 fixed test prompts against this library entry's configured credentials (PA-002).

    Uses the entry's own api_key_encrypted, endpoint_url, api_version, and model_name.
    On all prompts passing, writes NOW() to last_test_passed_at (required for publish gate).

    Returns 422 if the entry has no API key stored.
    Returns 504 if the LLM calls exceed 30 seconds total.
    Returns 502 if any LLM call fails.
    """
    entry = await _get_entry(entry_id, db)
    if entry is None:
        raise HTTPException(status_code=404, detail="LLM Library entry not found")

    if entry.status in ("deprecated", "Deprecated"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot test a Deprecated entry.",
        )

    # Guard: entry has no API key (e.g. rows created before credential columns existed)
    # Ollama is exempt — it doesn't require an API key (uses "ollama" as placeholder).
    if entry.provider != "ollama" and not entry.key_present:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "This entry has no API key configured. "
                "Edit the entry and add credentials before testing."
            ),
        )

    # Fetch encrypted key bytes separately — not in _SELECT_COLUMNS for security
    # Ollama: key may be absent; decrypted_key will fall back to "ollama" in test harness.
    encrypted_key_bytes = None if entry.provider == "ollama" else await _get_encrypted_key(entry_id, db)
    if entry.provider != "ollama" and not encrypted_key_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="API key not found for this entry.",
        )

    from app.core.crypto import decrypt_api_key

    decrypted_key = ""
    try:
        # Ollama: no key stored, test harness will use "ollama" as default
        decrypted_key = decrypt_api_key(encrypted_key_bytes) if encrypted_key_bytes else ""
        tasks = [
            _run_single_test_prompt(
                prompt=p,
                provider=entry.provider,
                deployment_name=entry.model_name,
                api_key=decrypted_key,
                endpoint_url=entry.endpoint_url,
                api_version=entry.api_version,
                price_in=entry.pricing_per_1k_tokens_in,
                price_out=entry.pricing_per_1k_tokens_out,
            )
            for p in _TEST_PROMPTS
        ]
        results = await asyncio.wait_for(
            asyncio.gather(*tasks),
            timeout=_TEST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        decrypted_key = ""  # Clear before re-raising to limit traceback exposure
        raise HTTPException(
            status_code=504,
            detail=f"LLM test calls exceeded {_TEST_TIMEOUT_SECONDS}s timeout.",
        ) from None
    except asyncio.CancelledError:
        decrypted_key = ""
        raise
    except Exception as exc:
        # Clear the decrypted key BEFORE capturing error details so it cannot
        # appear in exception tracebacks, log capture, or APM frame serialization.
        decrypted_key = ""
        # Surface provider error for admin self-diagnosis. Strip URLs to avoid
        # leaking Azure subscription paths or resource group names.
        import re as _re

        raw_error = str(exc)[:500]
        provider_error = _re.sub(r"https?://\S+", "[URL]", raw_error)
        logger.warning(
            "llm_library_test_failed",
            entry_id=entry_id,
            error=provider_error,
        )
        raise HTTPException(
            status_code=502,
            detail=f"LLM call failed: {provider_error}",
        ) from None
    finally:
        decrypted_key = ""  # Belt-and-suspenders: always clear on exit

    # Record successful test — required for publish gate
    await db.execute(
        text(
            "UPDATE llm_library SET last_test_passed_at = NOW() WHERE id = :id"
        ),
        {"id": entry_id},
    )
    await db.commit()

    logger.info(
        "llm_library_profile_tested",
        entry_id=entry_id,
        provider=entry.provider,
        model_name=entry.model_name,
        prompt_count=len(_TEST_PROMPTS),
        api_key="[REDACTED]",
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
