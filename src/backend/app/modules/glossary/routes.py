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


async def list_glossary_db(
    tenant_id: str,
    page: int,
    page_size: int,
    db,
    search: str | None = None,
) -> dict:
    """List glossary terms for a tenant, paginated. Optionally filter by search (term ILIKE)."""
    offset = (page - 1) * page_size

    # Escape LIKE metacharacters in search input (must be in this order)
    if search:
        safe_search = (
            search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        search_pattern = f"%{safe_search}%"
        where_extra = " AND term ILIKE :search"
        params_extra: dict = {"search": search_pattern}
    else:
        where_extra = ""
        params_extra = {}

    count_result = await db.execute(
        text(
            f"SELECT COUNT(*) FROM glossary_terms WHERE tenant_id = :tenant_id{where_extra}"
        ),
        {"tenant_id": tenant_id, **params_extra},
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        text(
            f"SELECT id, term, full_form, aliases, created_at FROM glossary_terms "
            f"WHERE tenant_id = :tenant_id{where_extra} "
            "ORDER BY term ASC LIMIT :limit OFFSET :offset"
        ),
        {"tenant_id": tenant_id, "limit": page_size, "offset": offset, **params_extra},
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
    commit: bool = True,
) -> Optional[dict]:
    """Update glossary term fields."""
    updates = dict(updates)  # avoid mutating caller's dict
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
    if commit:
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


async def get_miss_analytics_db(tenant_id: str, interval: str, limit: int, db) -> list:
    """
    API-063: Aggregate glossary miss signals grouped by unresolved_term.

    Returns top N terms ordered by frequency descending within the given time window.
    interval must be a value from _VALID_MISS_PERIODS (hardcoded SQL fragment, not
    user input) — asyncpg cannot bind a string to an INTERVAL parameter via CAST.
    """
    # _VALID_MISS_PERIODS maps query param to PostgreSQL interval literal.
    # The interval value is taken from a hardcoded allowlist in the caller —
    # it is never derived from raw user input, so direct string interpolation
    # into the SQL fragment is safe here.
    _SAFE_INTERVAL_FRAGMENTS = {
        "7 days": "INTERVAL '7 days'",
        "30 days": "INTERVAL '30 days'",
    }
    interval_sql = _SAFE_INTERVAL_FRAGMENTS.get(interval, "INTERVAL '30 days'")

    result = await db.execute(
        text(
            "SELECT unresolved_term, COUNT(*) AS frequency, "
            "array_agg(DISTINCT query_text) FILTER (WHERE query_text IS NOT NULL) "
            "AS example_queries "
            "FROM glossary_miss_signals "
            "WHERE tenant_id = :tenant_id "
            f"AND created_at >= NOW() - {interval_sql} "
            "GROUP BY unresolved_term "
            "ORDER BY frequency DESC "
            "LIMIT :limit"
        ),
        {"tenant_id": tenant_id, "limit": limit},
    )
    items = []
    for row in result.mappings():
        examples = row.get("example_queries") or []
        # Return only first 3 example queries
        examples = list(examples)[:3]
        items.append(
            {
                "term": row["unresolved_term"],
                "frequency": int(row["frequency"]),
                "example_queries": examples,
            }
        )
    return items


async def list_miss_signals_db(tenant_id: str, limit: int, db) -> dict:
    """
    Aggregate glossary miss signals: group by unresolved_term, sum occurrence_count.

    Returns top N terms ordered by total occurrences descending.
    """
    result = await db.execute(
        text(
            "SELECT unresolved_term, SUM(occurrence_count) AS total_count, "
            "MAX(updated_at) AS last_seen "
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
    """API-062: Export all glossary terms as CSV download.

    Returns a UTF-8 BOM CSV (Excel-compatible) with columns:
    term, full_form, definition, context_tags, scope

    Formula injection prevention: any cell starting with =, +, -, @ is
    prefixed with a single quote to neutralise spreadsheet formula execution.
    """
    terms = await export_glossary_terms_db(
        tenant_id=current_user.tenant_id,
        db=session,
    )

    # OWASP CSV formula injection prevention.
    # Prefix with single quote — Excel treats it as a text literal prefix.
    _FORMULA_CHARS = ("=", "+", "-", "@")

    def _safe_cell(value: str) -> str:
        if value and value[0] in _FORMULA_CHARS:
            return "'" + value
        return value

    output = io.StringIO()
    writer = csv.writer(output)
    # Columns per API-062 spec: term, full_form, definition, context_tags, scope
    writer.writerow(["term", "full_form", "definition", "context_tags", "scope"])
    for term in terms:
        # definition = full_form (same content — glossary_terms has no separate definition)
        # context_tags = semicolon-separated aliases (analogous to tags)
        # scope = empty (no scope column in schema)
        context_tags = ";".join(term["aliases"]) if term["aliases"] else ""
        writer.writerow(
            [
                _safe_cell(term["term"]),
                _safe_cell(term["full_form"] or ""),
                _safe_cell(term["full_form"] or ""),
                _safe_cell(context_tags),
                "",  # scope — not present in schema
            ]
        )

    csv_content = output.getvalue()
    # UTF-8 BOM for Excel compatibility (b'\xef\xbb\xbf')
    bom = b"\xef\xbb\xbf"
    encoded = bom + csv_content.encode("utf-8")

    return StreamingResponse(
        iter([encoded]),
        media_type="text/csv; charset=utf-8-sig",
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


# ---------------------------------------------------------------------------
# TA-013: Admin miss-signals endpoint — returns term + query_count +
#         example_queries (up to 3 snippets, 40 chars each, truncated).
# ---------------------------------------------------------------------------

admin_router = APIRouter(prefix="/admin/glossary", tags=["admin-glossary"])


async def get_admin_miss_signals_db(tenant_id: str, limit: int, db) -> list:
    """
    TA-013: Return top N uncovered terms with query_count and example_queries.

    Groups by unresolved_term, sums occurrence_count as query_count, and
    aggregates up to 3 distinct query_text samples (≤ 40 chars each).
    """
    result = await db.execute(
        text(
            "SELECT unresolved_term, "
            "  SUM(occurrence_count) AS query_count, "
            "  array_agg(DISTINCT LEFT(query_text, 40)) AS example_queries "
            "FROM glossary_miss_signals "
            "WHERE tenant_id = :tenant_id "
            "GROUP BY unresolved_term "
            "ORDER BY query_count DESC "
            "LIMIT :limit"
        ),
        {"tenant_id": tenant_id, "limit": limit},
    )
    items = []
    for row in result.mappings():
        examples = list(row.get("example_queries") or [])
        # Return at most 3, truncated to 40 chars (belt-and-suspenders guard)
        examples = [str(e)[:40] for e in examples if e][:3]
        items.append(
            {
                "term": row["unresolved_term"],
                "query_count": int(row["query_count"]),
                "example_queries": examples,
            }
        )
    return items


@admin_router.get("/miss-signals")
async def admin_list_miss_signals(
    limit: int = Query(50, ge=1, le=200),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TA-013: List top unresolved glossary terms with query_count and example_queries.

    Returns terms that appeared in user queries but are not yet in the tenant
    glossary, ranked by occurrence frequency.
    """
    items = await get_admin_miss_signals_db(
        tenant_id=current_user.tenant_id,
        limit=limit,
        db=session,
    )
    return {"items": items, "total": len(items)}


_VALID_MISS_PERIODS = {"7d": "7 days", "30d": "30 days"}


@router.get("/analytics/misses")
async def get_miss_analytics(
    period: str = Query("30d", pattern="^(7d|30d)$"),
    limit: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-063: Glossary miss analytics — top unresolved terms by frequency.

    Query params:
        period — '7d' or '30d' (default '30d')
        limit  — max results, 1-100 (default 20)

    Returns anonymized miss signal aggregations with no user attribution.
    """
    interval = _VALID_MISS_PERIODS.get(period, "30 days")
    terms = await get_miss_analytics_db(
        tenant_id=current_user.tenant_id,
        interval=interval,
        limit=limit,
        db=session,
    )
    return {"terms": terms, "period": period}


@router.get("/")
async def list_glossary(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=100),
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
        search=search,
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

    # Fetch current state before update for audit log
    before = await get_glossary_term_db(term_id, current_user.tenant_id, session)
    if before is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Glossary term '{term_id}' not found",
        )

    result = await update_glossary_term_db(
        term_id=term_id,
        tenant_id=current_user.tenant_id,
        updates=updates,
        db=session,
        commit=False,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Glossary term '{term_id}' not found",
        )

    changed_fields = list(updates.keys())
    audit_details = json.dumps(
        {
            "changed_fields": changed_fields,
            "before": {k: before.get(k) for k in changed_fields},
            "after": {k: result.get(k) for k in changed_fields},
        }
    )
    await session.execute(
        text(
            "INSERT INTO audit_log "
            "(tenant_id, user_id, action, resource_type, resource_id, details) "
            "VALUES (:tenant_id, :user_id, 'update', 'glossary_term', "
            "CAST(:resource_id AS uuid), CAST(:details AS jsonb))"
        ),
        {
            "tenant_id": current_user.tenant_id,
            "user_id": current_user.id,
            "resource_id": term_id,
            "details": audit_details,
        },
    )
    await session.commit()

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


# ---------------------------------------------------------------------------
# TA-012: Glossary version history and rollback
# ---------------------------------------------------------------------------

_GLOSSARY_UPDATABLE_FIELDS = frozenset({"term", "full_form", "aliases"})


@router.get("/{term_id}/history")
async def get_glossary_history(
    term_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TA-012: Return audit_log entries for a glossary term, newest first.

    Each entry includes timestamp, actor email, changed_fields, before, and after values.
    """
    try:
        uuid.UUID(term_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="term_id must be a valid UUID")

    result = await session.execute(
        text(
            "SELECT al.id, al.user_id, al.action, al.details, al.created_at, "
            "  u.email AS actor_email "
            "FROM audit_log al "
            "LEFT JOIN users u ON u.id = al.user_id "
            "WHERE al.tenant_id = :tenant_id "
            "  AND al.resource_type = 'glossary_term' "
            "  AND al.resource_id = CAST(:term_id AS uuid) "
            "ORDER BY al.created_at DESC "
            "LIMIT 100"
        ),
        {"tenant_id": current_user.tenant_id, "term_id": term_id},
    )
    rows = result.fetchall()
    items = []
    for row in rows:
        details = row[3] or {}
        items.append(
            {
                "id": str(row[0]),
                "actor_id": row[1],
                "actor_email": row[5],
                "action": row[2],
                "changed_fields": details.get("changed_fields", []),
                "before": details.get("before", {}),
                "after": details.get("after", {}),
                "created_at": row[4].isoformat() if row[4] else None,
            }
        )
    return {"items": items, "total": len(items)}


@router.patch("/{term_id}/rollback/{version_id}")
async def rollback_glossary_term(
    term_id: str,
    version_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    TA-012: Restore a glossary term to the state captured in the given audit_log entry.

    The version_id refers to audit_log.id. The `before` JSON from that entry is applied.
    A new audit_log entry is created to record the rollback.
    """
    try:
        uuid.UUID(term_id)
        uuid.UUID(version_id)
    except ValueError:
        raise HTTPException(
            status_code=422, detail="term_id and version_id must be valid UUIDs"
        )

    # Fetch the audit log entry (scoped to tenant + term)
    result = await session.execute(
        text(
            "SELECT id, details FROM audit_log "
            "WHERE id = CAST(:version_id AS uuid) "
            "  AND tenant_id = :tenant_id "
            "  AND resource_type = 'glossary_term' "
            "  AND resource_id = CAST(:term_id AS uuid)"
        ),
        {
            "version_id": version_id,
            "tenant_id": current_user.tenant_id,
            "term_id": term_id,
        },
    )
    audit_row = result.fetchone()
    if audit_row is None:
        raise HTTPException(
            status_code=404,
            detail="Version not found for this glossary term",
        )

    details = audit_row[1] or {}
    before_state = details.get("before", {})
    if not before_state:
        raise HTTPException(
            status_code=422,
            detail="This version entry has no 'before' state to restore",
        )

    # Build SET clause from the before_state using the allowlist
    updates = {k: v for k, v in before_state.items() if k in _GLOSSARY_UPDATABLE_FIELDS}
    if not updates:
        raise HTTPException(
            status_code=422,
            detail="No restorable fields in the selected version",
        )

    # Fetch current state for the after snapshot in the new audit entry
    current = await get_glossary_term_db(term_id, current_user.tenant_id, session)
    if current is None:
        raise HTTPException(status_code=404, detail="Glossary term not found")

    # Apply the restore (deferred commit — audit INSERT must be in same transaction)
    result = await update_glossary_term_db(
        term_id=term_id,
        tenant_id=current_user.tenant_id,
        updates=updates,
        db=session,
        commit=False,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Glossary term not found")

    # Write rollback audit_log entry in the same transaction
    rollback_details = json.dumps(
        {
            "rollback_to_version": version_id,
            "changed_fields": list(updates.keys()),
            "before": {k: current.get(k) for k in updates},
            "after": updates,
        }
    )
    await session.execute(
        text(
            "INSERT INTO audit_log "
            "(tenant_id, user_id, action, resource_type, resource_id, details) "
            "VALUES (:tenant_id, :user_id, 'rollback', 'glossary_term', "
            "CAST(:resource_id AS uuid), CAST(:details AS jsonb))"
        ),
        {
            "tenant_id": current_user.tenant_id,
            "user_id": current_user.id,
            "resource_id": term_id,
            "details": rollback_details,
        },
    )
    # Commit both the term update and audit entry atomically
    await session.commit()

    await _invalidate_glossary_cache(current_user.tenant_id)
    return result
