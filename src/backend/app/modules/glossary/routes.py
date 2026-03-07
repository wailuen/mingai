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
"""
import csv
import io
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from app.core.dependencies import CurrentUser, get_current_user, require_tenant_admin
from app.modules.glossary.expander import (
    MAX_DEFINITION_LENGTH,
    MAX_TERMS_PER_TENANT,
    sanitize_glossary_definition,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/glossary", tags=["glossary"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateTermRequest(BaseModel):
    term: str = Field(..., min_length=1, max_length=100)
    definition: Optional[str] = Field(None, max_length=MAX_DEFINITION_LENGTH)
    full_form: Optional[str] = Field(None, max_length=200)


class UpdateTermRequest(BaseModel):
    term: Optional[str] = Field(None, max_length=100)
    definition: Optional[str] = Field(None, max_length=MAX_DEFINITION_LENGTH)
    full_form: Optional[str] = Field(None, max_length=200)


# ---------------------------------------------------------------------------
# DB helper functions (mockable in unit tests)
# ---------------------------------------------------------------------------


async def list_glossary_db(tenant_id: str, page: int, page_size: int, db) -> dict:
    """List glossary terms for a tenant, paginated."""
    offset = (page - 1) * page_size
    count_result = await db.execute(
        "SELECT COUNT(*) FROM glossary_terms WHERE tenant_id = :tenant_id",
        {"tenant_id": tenant_id},
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        "SELECT id, term, definition, full_form, created_at FROM glossary_terms "
        "WHERE tenant_id = :tenant_id "
        "ORDER BY term ASC LIMIT :limit OFFSET :offset",
        {"tenant_id": tenant_id, "limit": page_size, "offset": offset},
    )
    rows = rows_result.fetchall()
    items = [
        {
            "id": r[0],
            "term": r[1],
            "definition": r[2],
            "full_form": r[3],
            "created_at": str(r[4]),
        }
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def create_glossary_term_db(
    tenant_id: str,
    term: str,
    definition: Optional[str],
    full_form: Optional[str],
    db,
) -> dict:
    """Insert a new glossary term."""
    term_id = str(uuid.uuid4())
    safe_definition = sanitize_glossary_definition(definition) if definition else None
    await db.execute(
        "INSERT INTO glossary_terms (id, tenant_id, term, definition, full_form) "
        "VALUES (:id, :tenant_id, :term, :definition, :full_form)",
        {
            "id": term_id,
            "tenant_id": tenant_id,
            "term": term,
            "definition": safe_definition,
            "full_form": full_form,
        },
    )
    logger.info(
        "glossary_term_created", term_id=term_id, term=term, tenant_id=tenant_id
    )
    return {
        "id": term_id,
        "term": term,
        "definition": safe_definition,
        "full_form": full_form,
    }


async def get_glossary_term_db(term_id: str, tenant_id: str, db) -> Optional[dict]:
    """Get a glossary term by ID."""
    result = await db.execute(
        "SELECT id, term, definition, full_form, created_at FROM glossary_terms "
        "WHERE id = :id AND tenant_id = :tenant_id",
        {"id": term_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "term": row[1],
        "definition": row[2],
        "full_form": row[3],
        "created_at": str(row[4]),
    }


async def update_glossary_term_db(
    term_id: str,
    tenant_id: str,
    updates: dict,
    db,
) -> Optional[dict]:
    """Update glossary term fields."""
    if "definition" in updates and updates["definition"]:
        updates["definition"] = sanitize_glossary_definition(updates["definition"])
    set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
    params = {"id": term_id, "tenant_id": tenant_id, **updates}
    await db.execute(
        f"UPDATE glossary_terms SET {set_clauses} WHERE id = :id AND tenant_id = :tenant_id",
        params,
    )
    return await get_glossary_term_db(term_id, tenant_id, db)


async def delete_glossary_term_db(term_id: str, tenant_id: str, db) -> bool:
    """Delete a glossary term."""
    result = await db.execute(
        "DELETE FROM glossary_terms WHERE id = :id AND tenant_id = :tenant_id",
        {"id": term_id, "tenant_id": tenant_id},
    )
    return (result.rowcount or 0) > 0


async def bulk_import_glossary(
    tenant_id: str,
    csv_content: str,
    db,
) -> dict:
    """
    Bulk import glossary terms from CSV.

    Expected columns: term, definition (optional: full_form)
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

    for i, row in enumerate(reader, start=2):  # Row 1 is header
        term = (row.get("term") or "").strip()
        definition = (row.get("definition") or "").strip() or None
        full_form = (row.get("full_form") or "").strip() or None

        if not term:
            errors.append({"row": i, "error": "term is empty"})
            skipped += 1
            continue

        if len(term) > 100:
            errors.append(
                {"row": i, "error": f"term exceeds 100 chars: {term[:20]}..."}
            )
            skipped += 1
            continue

        if definition and len(definition) > MAX_DEFINITION_LENGTH:
            definition = definition[:MAX_DEFINITION_LENGTH]

        try:
            safe_def = sanitize_glossary_definition(definition) if definition else None
            term_id = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO glossary_terms (id, tenant_id, term, definition, full_form) "
                "VALUES (:id, :tenant_id, :term, :definition, :full_form) "
                "ON CONFLICT (tenant_id, term) DO UPDATE SET "
                "definition = EXCLUDED.definition, full_form = EXCLUDED.full_form",
                {
                    "id": term_id,
                    "tenant_id": tenant_id,
                    "term": term,
                    "definition": safe_def,
                    "full_form": full_form,
                },
            )
            imported += 1
        except Exception as e:
            errors.append({"row": i, "error": str(e)})
            skipped += 1

    logger.info(
        "glossary_bulk_import",
        tenant_id=tenant_id,
        imported=imported,
        skipped=skipped,
    )
    return {"imported": imported, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Route handlers (note: /import BEFORE /{id} to avoid path collision)
# ---------------------------------------------------------------------------


@router.post("/import")
async def import_glossary_csv(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_tenant_admin),
):
    """API-075: Bulk import glossary terms from a CSV file."""
    content = await file.read()
    csv_content = content.decode("utf-8", errors="replace")
    result = await bulk_import_glossary(
        tenant_id=current_user.tenant_id,
        csv_content=csv_content,
        db=None,
    )
    return result


@router.get("/")
async def list_glossary(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
):
    """API-066: List glossary terms for the tenant (all authenticated users)."""
    result = await list_glossary_db(
        tenant_id=current_user.tenant_id,
        page=page,
        page_size=page_size,
        db=None,
    )
    return result


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_glossary_term(
    request: CreateTermRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
):
    """API-067: Create a new glossary term (tenant admin only)."""
    result = await create_glossary_term_db(
        tenant_id=current_user.tenant_id,
        term=request.term,
        definition=request.definition,
        full_form=request.full_form,
        db=None,
    )
    return result


@router.get("/{term_id}")
async def get_glossary_term(
    term_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """API-068: Get a glossary term by ID."""
    result = await get_glossary_term_db(
        term_id=term_id,
        tenant_id=current_user.tenant_id,
        db=None,
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
        db=None,
    )
    return result


@router.delete("/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_glossary_term(
    term_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
):
    """API-070: Delete a glossary term (tenant admin only)."""
    deleted = await delete_glossary_term_db(
        term_id=term_id,
        tenant_id=current_user.tenant_id,
        db=None,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Glossary term '{term_id}' not found",
        )
    return None
