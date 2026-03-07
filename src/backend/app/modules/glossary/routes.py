"""
Glossary API routes (API-066 to API-075).

Endpoints:
- GET    /glossary              — List glossary terms (paginated)
- POST   /glossary              — Create term (tenant admin only)
- GET    /glossary/{id}         — Get term
- PATCH  /glossary/{id}         — Update term (tenant admin only)
- DELETE /glossary/{id}         — Delete term (tenant admin only)
- POST   /glossary/import       — Bulk CSV import (tenant admin only)

Note: /import must be registered BEFORE /{id} to avoid path collision.

Schema: glossary_terms(id, tenant_id, term, full_form, aliases JSONB, created_at)
- term: the abbreviation/acronym (e.g. "HR")
- full_form: the expansion injected into queries (e.g. "Human Resources") — NOT NULL
- aliases: additional abbreviations that expand to the same full_form
"""
import csv
import io
import json
import uuid
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_tenant_admin
from app.core.redis_client import get_redis
from app.core.session import get_async_session
from app.modules.glossary.expander import (
    MAX_DEFINITION_LENGTH,
    MAX_TERMS_PER_TENANT,
    sanitize_glossary_definition,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/glossary", tags=["glossary"])


async def _invalidate_glossary_cache(tenant_id: str) -> None:
    """
    Invalidate the Redis glossary terms cache for a tenant (INFRA-038).

    Called after any write operation (create, update, delete, bulk import)
    so that GlossaryExpander reads fresh terms on the next expand() call.
    Failure is logged and suppressed — cache miss is safe (falls back to DB).
    """
    cache_key = f"mingai:{tenant_id}:glossary_terms"
    try:
        redis = get_redis()
        await redis.delete(cache_key)
        logger.debug(
            "glossary_cache_invalidated",
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.warning(
            "glossary_cache_invalidation_failed",
            tenant_id=tenant_id,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateTermRequest(BaseModel):
    term: str = Field(..., min_length=1, max_length=100)
    full_form: str = Field(..., min_length=1, max_length=MAX_DEFINITION_LENGTH)
    aliases: Optional[List[str]] = Field(default_factory=list)


class UpdateTermRequest(BaseModel):
    term: Optional[str] = Field(None, min_length=1, max_length=100)
    full_form: Optional[str] = Field(
        None, min_length=1, max_length=MAX_DEFINITION_LENGTH
    )
    aliases: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# DB helper functions (mockable in unit tests)
# ---------------------------------------------------------------------------


async def list_glossary_db(tenant_id: str, page: int, page_size: int, db) -> dict:
    """List glossary terms for a tenant, paginated."""
    offset = (page - 1) * page_size
    count_result = await db.execute(
        text("SELECT COUNT(*) FROM glossary_terms WHERE tenant_id = :tenant_id"),
        {"tenant_id": tenant_id},
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        text(
            "SELECT id, term, full_form, aliases, created_at FROM glossary_terms "
            "WHERE tenant_id = :tenant_id "
            "ORDER BY term ASC LIMIT :limit OFFSET :offset"
        ),
        {"tenant_id": tenant_id, "limit": page_size, "offset": offset},
    )
    rows = rows_result.fetchall()
    items = [
        {
            "id": str(r[0]),
            "term": r[1],
            "full_form": r[2],
            "aliases": r[3] or [],
            "created_at": str(r[4]),
        }
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def create_glossary_term_db(
    tenant_id: str,
    term: str,
    full_form: str,
    aliases: Optional[List[str]],
    db,
) -> dict:
    """Insert a new glossary term."""
    term_id = str(uuid.uuid4())
    safe_full_form = sanitize_glossary_definition(full_form)
    aliases_json = json.dumps(aliases or [])
    await db.execute(
        text(
            "INSERT INTO glossary_terms (id, tenant_id, term, full_form, aliases) "
            "VALUES (:id, :tenant_id, :term, :full_form, CAST(:aliases AS jsonb))"
        ),
        {
            "id": term_id,
            "tenant_id": tenant_id,
            "term": term,
            "full_form": safe_full_form,
            "aliases": aliases_json,
        },
    )
    await db.commit()
    logger.info(
        "glossary_term_created", term_id=term_id, term=term, tenant_id=tenant_id
    )
    return {
        "id": term_id,
        "term": term,
        "full_form": safe_full_form,
        "aliases": aliases or [],
    }


async def get_glossary_term_db(term_id: str, tenant_id: str, db) -> Optional[dict]:
    """Get a glossary term by ID."""
    result = await db.execute(
        text(
            "SELECT id, term, full_form, aliases, created_at FROM glossary_terms "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": term_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "term": row[1],
        "full_form": row[2],
        "aliases": row[3] or [],
        "created_at": str(row[4]),
    }


async def update_glossary_term_db(
    term_id: str,
    tenant_id: str,
    updates: dict,
    db,
) -> Optional[dict]:
    """Update glossary term fields."""
    if "full_form" in updates and updates["full_form"]:
        updates["full_form"] = sanitize_glossary_definition(updates["full_form"])
    if "aliases" in updates:
        updates["aliases"] = json.dumps(updates["aliases"] or [])

    _GLOSSARY_UPDATE_ALLOWLIST = {"term", "full_form", "aliases"}
    invalid = set(updates) - _GLOSSARY_UPDATE_ALLOWLIST
    if invalid:
        raise ValueError(f"Invalid glossary term update fields: {invalid}")

    set_parts = []
    for k in updates:
        if k == "aliases":
            set_parts.append(f"aliases = CAST(:{k} AS jsonb)")
        else:
            set_parts.append(f"{k} = :{k}")

    params = {"id": term_id, "tenant_id": tenant_id, **updates}
    result = await db.execute(
        text(
            f"UPDATE glossary_terms SET {', '.join(set_parts)} "
            f"WHERE id = :id AND tenant_id = :tenant_id"
        ),
        params,
    )
    await db.commit()
    if (result.rowcount or 0) == 0:
        return None
    return await get_glossary_term_db(term_id, tenant_id, db)


async def delete_glossary_term_db(term_id: str, tenant_id: str, db) -> bool:
    """Delete a glossary term."""
    result = await db.execute(
        text("DELETE FROM glossary_terms WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": term_id, "tenant_id": tenant_id},
    )
    await db.commit()
    return (result.rowcount or 0) > 0


async def bulk_import_glossary(
    tenant_id: str,
    csv_content: str,
    db,
) -> dict:
    """
    Bulk import glossary terms from CSV.

    Expected columns: term, full_form (optional: aliases as pipe-separated)
    Returns summary with counts of imported, skipped, and errors.
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    imported = 0
    skipped = 0
    errors = []

    if "term" not in (reader.fieldnames or []):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CSV must have a 'term' column",
        )

    if "full_form" not in (reader.fieldnames or []):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CSV must have a 'full_form' column",
        )

    for i, row in enumerate(reader, start=2):  # Row 1 is header
        term = (row.get("term") or "").strip()
        full_form = (row.get("full_form") or "").strip()
        aliases_raw = (row.get("aliases") or "").strip()
        aliases = (
            [a.strip() for a in aliases_raw.split("|") if a.strip()]
            if aliases_raw
            else []
        )

        if not term:
            errors.append({"row": i, "error": "term is empty"})
            skipped += 1
            continue

        if not full_form:
            errors.append({"row": i, "error": "full_form is empty"})
            skipped += 1
            continue

        if len(term) > 100:
            errors.append(
                {"row": i, "error": f"term exceeds 100 chars: {term[:20]}..."}
            )
            skipped += 1
            continue

        if len(full_form) > MAX_DEFINITION_LENGTH:
            full_form = full_form[:MAX_DEFINITION_LENGTH]

        try:
            safe_full_form = sanitize_glossary_definition(full_form)
            term_id = str(uuid.uuid4())
            await db.execute(
                text(
                    "INSERT INTO glossary_terms (id, tenant_id, term, full_form, aliases) "
                    "VALUES (:id, :tenant_id, :term, :full_form, CAST(:aliases AS jsonb)) "
                    "ON CONFLICT (tenant_id, term) DO UPDATE SET "
                    "full_form = EXCLUDED.full_form, aliases = EXCLUDED.aliases"
                ),
                {
                    "id": term_id,
                    "tenant_id": tenant_id,
                    "term": term,
                    "full_form": safe_full_form,
                    "aliases": json.dumps(aliases),
                },
            )
            imported += 1
        except Exception as e:
            logger.exception("glossary_bulk_import_row_error", row=i, term=term[:20])
            errors.append({"row": i, "error": f"Failed to import row {i}"})
            skipped += 1

    if imported > 0:
        await db.commit()

    logger.info(
        "glossary_bulk_import",
        tenant_id=tenant_id,
        imported=imported,
        skipped=skipped,
    )
    return {"imported": imported, "skipped": skipped, "errors": errors}


async def export_glossary_terms_db(tenant_id: str, db) -> list:
    """Fetch all glossary terms for a tenant (no pagination) for CSV export."""
    result = await db.execute(
        text(
            "SELECT term, full_form, aliases FROM glossary_terms "
            "WHERE tenant_id = :tenant_id ORDER BY term ASC"
        ),
        {"tenant_id": tenant_id},
    )
    rows = result.fetchall()
    return [
        {
            "term": r[0],
            "full_form": r[1],
            "aliases": r[2] or [],
        }
        for r in rows
    ]


async def list_miss_signals_db(tenant_id: str, limit: int, db) -> dict:
    """
    Aggregate glossary miss signals: group by unresolved_term, sum occurrence_count.

    Returns top N terms ordered by total occurrences descending.
    """
    result = await db.execute(
        text(
            "SELECT unresolved_term, SUM(occurrence_count) AS total_count, "
            "MAX(last_seen_at) AS last_seen "
            "FROM glossary_miss_signals "
            "WHERE tenant_id = :tenant_id "
            "GROUP BY unresolved_term "
            "ORDER BY total_count DESC "
            "LIMIT :limit"
        ),
        {"tenant_id": tenant_id, "limit": limit},
    )
    items = []
    for row in result.mappings():
        last_seen = row["last_seen"]
        if hasattr(last_seen, "isoformat"):
            last_seen = last_seen.isoformat()
        items.append(
            {
                "term": row["unresolved_term"],
                "occurrence_count": int(row["total_count"]),
                "last_seen": str(last_seen) if last_seen else None,
            }
        )
    return {"items": items}


# ---------------------------------------------------------------------------
# Route handlers (note: /import BEFORE /{id} to avoid path collision)
# ---------------------------------------------------------------------------


@router.post("/import")
async def import_glossary_csv(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-075: Bulk import glossary terms from a CSV file."""
    MAX_UPLOAD_BYTES = 1_048_576  # 1 MB limit for glossary CSVs
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="CSV file exceeds 1 MB limit",
        )
    csv_content = content.decode("utf-8", errors="replace")
    result = await bulk_import_glossary(
        tenant_id=current_user.tenant_id,
        csv_content=csv_content,
        db=session,
    )
    await _invalidate_glossary_cache(current_user.tenant_id)
    return result


@router.get("/export")
async def export_glossary_csv(
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-076: Export all glossary terms as CSV download."""
    terms = await export_glossary_terms_db(
        tenant_id=current_user.tenant_id,
        db=session,
    )

    # Prefix formula-starting values to prevent CSV formula injection (OWASP).
    # Values beginning with =, +, -, @, tab, or carriage return are prefixed with a tab.
    _FORMULA_CHARS = ("=", "+", "-", "@", "\t", "\r")

    def _safe_cell(value: str) -> str:
        if value and value[0] in _FORMULA_CHARS:
            return "\t" + value
        return value

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["term", "full_form", "aliases"])
    for term in terms:
        aliases_str = "|".join(term["aliases"]) if term["aliases"] else ""
        writer.writerow(
            [
                _safe_cell(term["term"]),
                _safe_cell(term["full_form"] or ""),
                _safe_cell(aliases_str),
            ]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="glossary.csv"',
        },
    )


@router.get("/miss-signals")
async def list_miss_signals(
    limit: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-077: List top uncovered terms from miss signals."""
    result = await list_miss_signals_db(
        tenant_id=current_user.tenant_id,
        limit=limit,
        db=session,
    )
    return result


@router.get("/")
async def list_glossary(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-066: List glossary terms for the tenant (all authenticated users)."""
    # Platform-scope users have no tenant UUID — return empty glossary
    try:
        uuid.UUID(current_user.tenant_id)
    except (ValueError, AttributeError):
        return {"items": [], "total": 0, "page": page, "page_size": page_size}
    result = await list_glossary_db(
        tenant_id=current_user.tenant_id,
        page=page,
        page_size=page_size,
        db=session,
    )
    return result


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_glossary_term(
    request: CreateTermRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-067: Create a new glossary term (tenant admin only)."""
    result = await create_glossary_term_db(
        tenant_id=current_user.tenant_id,
        term=request.term,
        full_form=request.full_form,
        aliases=request.aliases,
        db=session,
    )
    await _invalidate_glossary_cache(current_user.tenant_id)
    return result


@router.get("/{term_id}")
async def get_glossary_term(
    term_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-068: Get a glossary term by ID."""
    result = await get_glossary_term_db(
        term_id=term_id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Glossary term '{term_id}' not found",
        )
    return result


@router.patch("/{term_id}")
async def update_glossary_term(
    term_id: str,
    request: UpdateTermRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-069: Update a glossary term (tenant admin only)."""
    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )
    result = await update_glossary_term_db(
        term_id=term_id,
        tenant_id=current_user.tenant_id,
        updates=updates,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Glossary term '{term_id}' not found",
        )
    await _invalidate_glossary_cache(current_user.tenant_id)
    return result


@router.delete("/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_glossary_term(
    term_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-070: Delete a glossary term (tenant admin only)."""
    deleted = await delete_glossary_term_db(
        term_id=term_id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Glossary term '{term_id}' not found",
        )
    await _invalidate_glossary_cache(current_user.tenant_id)
    return None
