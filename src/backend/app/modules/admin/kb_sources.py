"""
Multiple document source management API (TA-034).

Endpoints:
- GET  /admin/knowledge-base/{kb_id}/sources                  — list all sources with health
- GET  /admin/knowledge-base/{kb_id}/documents?search=        — search documents across sources
- DELETE /admin/knowledge-base/{kb_id}/sources/{integration_id} — remove a source from a KB

A "KB" (knowledge base) is identified by its index_id (UUID).  Integrations are
associated with a KB via integrations.config->>'kb_id'.  This module reads and
manages those associations.

Health indicator:
  - active + recent sync (<24h)   → "healthy"
  - active + no recent sync       → "stale"
  - disabled / error status        → "unhealthy"
  - pending                        → "pending"
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin-kb-sources"])

_HEALTH_STALE_THRESHOLD_HOURS = 24


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class KBSourceItem(BaseModel):
    integration_id: str
    name: str
    provider: str
    sync_status: str
    last_sync_at: Optional[str] = None
    document_count: int
    health_indicator: str  # "healthy" | "stale" | "unhealthy" | "pending"


class KBDocumentItem(BaseModel):
    id: str
    title: str
    source: str
    integration_id: str
    last_synced: Optional[str] = None
    document_count: int


# ---------------------------------------------------------------------------
# Health helper
# ---------------------------------------------------------------------------


def _compute_health(integration_status: str, last_sync_at: Optional[datetime]) -> str:
    """Derive a health indicator from integration status and last sync time."""
    if integration_status in ("disabled", "error", "failed"):
        return "unhealthy"
    if integration_status == "pending":
        return "pending"
    if last_sync_at is None:
        return "stale"
    threshold = datetime.now(timezone.utc) - timedelta(
        hours=_HEALTH_STALE_THRESHOLD_HOURS
    )
    if last_sync_at < threshold:
        return "stale"
    return "healthy"


# ---------------------------------------------------------------------------
# DB helpers (mockable in unit tests)
# ---------------------------------------------------------------------------


async def list_kb_sources_db(
    kb_id: str,
    tenant_id: str,
    db,
) -> list[dict]:
    """
    Return all integrations associated with this KB (config->>'kb_id' = :kb_id)
    plus their last sync time and document count from sync_jobs.
    """
    result = await db.execute(
        text(
            "SELECT i.id, i.provider, i.status, i.config, "
            "sj.created_at AS last_sync_at, sj.status AS last_sync_status "
            "FROM integrations i "
            "LEFT JOIN LATERAL ("
            "  SELECT sj2.created_at, sj2.status "
            "  FROM sync_jobs sj2 "
            "  WHERE sj2.integration_id = i.id "
            "  ORDER BY sj2.created_at DESC LIMIT 1"
            ") sj ON true "
            "WHERE i.tenant_id = :tenant_id "
            "  AND i.config->>'kb_id' = :kb_id "
            "ORDER BY i.created_at DESC"
        ),
        {"tenant_id": tenant_id, "kb_id": kb_id},
    )

    items = []
    for row in result.mappings():
        config_val = row["config"]
        if isinstance(config_val, str):
            config_val = json.loads(config_val)

        last_sync_at = row["last_sync_at"]
        if isinstance(last_sync_at, str):
            try:
                last_sync_at = datetime.fromisoformat(last_sync_at)
            except ValueError:
                last_sync_at = None

        health = _compute_health(row["status"], last_sync_at)

        items.append(
            {
                "integration_id": str(row["id"]),
                "name": config_val.get("name", row["provider"]),
                "provider": row["provider"],
                "sync_status": row["last_sync_status"] or row["status"],
                "last_sync_at": last_sync_at.isoformat()
                if isinstance(last_sync_at, datetime)
                else (str(last_sync_at) if last_sync_at else None),
                "document_count": config_val.get("document_count", 0),
                "health_indicator": health,
            }
        )
    return items


async def search_kb_documents_db(
    kb_id: str,
    tenant_id: str,
    search: Optional[str],
    db,
) -> list[dict]:
    """
    Search documents across all integrations attached to this KB.

    Documents are stored in the sync_jobs.result_data JSONB when they exist,
    but the primary document tracking is in the integrations.config metadata.
    We query sync_jobs for document-level metadata where available, and fall
    back to integration-level document counts for sources without per-document
    indexing records.

    Returns unified document items with source info.
    """
    # First get all integration IDs for this KB
    int_result = await db.execute(
        text(
            "SELECT id, provider, config FROM integrations "
            "WHERE tenant_id = :tenant_id AND config->>'kb_id' = :kb_id"
        ),
        {"tenant_id": tenant_id, "kb_id": kb_id},
    )
    integrations = int_result.fetchall()

    if not integrations:
        return []

    integration_ids = [str(row[0]) for row in integrations]
    integration_meta = {}
    for row in integrations:
        config_val = row[2]
        if isinstance(config_val, str):
            config_val = json.loads(config_val)
        integration_meta[str(row[0])] = {
            "provider": row[1],
            "name": config_val.get("name", row[1]),
            "document_count": config_val.get("document_count", 0),
        }

    # Query sync_jobs for per-document metadata (stored in result_data)
    if search:
        # LIKE search on title/content stored in sync_jobs result_data
        # Escape LIKE metacharacters to prevent wildcard injection
        escaped = (
            search.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        like_param = f"%{escaped}%"
        jobs_result = await db.execute(
            text(
                "SELECT sj.id, sj.integration_id, sj.created_at, sj.result_data "
                "FROM sync_jobs sj "
                "WHERE sj.integration_id = ANY(CAST(:ids AS uuid[])) "
                "  AND sj.tenant_id = :tenant_id "
                "  AND sj.status = 'completed' "
                "  AND (LOWER(sj.result_data->>'title') LIKE :search "
                "       OR LOWER(sj.result_data->>'content') LIKE :search) "
                "ORDER BY sj.created_at DESC LIMIT 100"
            ),
            {
                "ids": integration_ids,
                "tenant_id": tenant_id,
                "search": like_param,
            },
        )
    else:
        jobs_result = await db.execute(
            text(
                "SELECT sj.id, sj.integration_id, sj.created_at, sj.result_data "
                "FROM sync_jobs sj "
                "WHERE sj.integration_id = ANY(CAST(:ids AS uuid[])) "
                "  AND sj.tenant_id = :tenant_id "
                "  AND sj.status = 'completed' "
                "ORDER BY sj.created_at DESC LIMIT 100"
            ),
            {"ids": integration_ids, "tenant_id": tenant_id},
        )

    rows = jobs_result.fetchall()

    if rows:
        items = []
        for row in rows:
            result_data = row[3]
            if isinstance(result_data, str):
                try:
                    result_data = json.loads(result_data)
                except (ValueError, TypeError):
                    result_data = {}
            result_data = result_data or {}

            int_id = str(row[1])
            meta = integration_meta.get(int_id, {})
            last_synced = row[2]
            items.append(
                {
                    "id": str(row[0]),
                    "title": result_data.get("title", f"Sync job {str(row[0])[:8]}"),
                    "source": meta.get("name", meta.get("provider", int_id)),
                    "integration_id": int_id,
                    "last_synced": last_synced.isoformat()
                    if isinstance(last_synced, datetime)
                    else (str(last_synced) if last_synced else None),
                    "document_count": result_data.get(
                        "document_count", meta.get("document_count", 0)
                    ),
                }
            )
        return items

    # No sync_job rows — fall back to one item per integration (summary)
    items = []
    for int_id, meta in integration_meta.items():
        # When searching and no rows match, return empty
        if search:
            continue
        items.append(
            {
                "id": int_id,
                "title": meta["name"],
                "source": meta["provider"],
                "integration_id": int_id,
                "last_synced": None,
                "document_count": meta["document_count"],
            }
        )
    return items


async def delete_kb_source_db(
    kb_id: str,
    integration_id: str,
    tenant_id: str,
    db,
) -> bool:
    """
    Detach an integration from a KB by removing the kb_id from its config.

    Returns True if the integration was found and updated, False otherwise.
    """
    # Verify the integration belongs to this tenant and is attached to this KB
    check_result = await db.execute(
        text(
            "SELECT id, config FROM integrations "
            "WHERE id = :id AND tenant_id = :tenant_id "
            "  AND config->>'kb_id' = :kb_id"
        ),
        {"id": integration_id, "tenant_id": tenant_id, "kb_id": kb_id},
    )
    row = check_result.fetchone()
    if row is None:
        return False

    config_val = row[1]
    if isinstance(config_val, str):
        config_val = json.loads(config_val)

    # Remove kb_id from config
    config_val.pop("kb_id", None)

    update_result = await db.execute(
        text(
            "UPDATE integrations SET config = CAST(:config AS jsonb), updated_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {
            "config": json.dumps(config_val),
            "id": integration_id,
            "tenant_id": tenant_id,
        },
    )
    await db.commit()

    if (update_result.rowcount or 0) == 0:
        return False

    logger.info(
        "kb_source_removed",
        kb_id=kb_id,
        integration_id=integration_id,
        tenant_id=tenant_id,
    )
    return True


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/knowledge-base/{kb_id}/sources", response_model=list[KBSourceItem])
async def list_kb_sources(
    kb_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> list[KBSourceItem]:
    """TA-034: List all document sources attached to a KB with health status."""
    try:
        uuid.UUID(kb_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="kb_id must be a valid UUID")

    items = await list_kb_sources_db(kb_id, current_user.tenant_id, db)
    return [KBSourceItem(**item) for item in items]


@router.get("/knowledge-base/{kb_id}/documents", response_model=list[KBDocumentItem])
async def list_kb_documents(
    kb_id: str,
    search: Optional[str] = Query(None, max_length=200),
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> list[KBDocumentItem]:
    """TA-034: Search documents across all sources attached to a KB."""
    try:
        uuid.UUID(kb_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="kb_id must be a valid UUID")

    items = await search_kb_documents_db(kb_id, current_user.tenant_id, search, db)
    return [KBDocumentItem(**item) for item in items]


@router.delete(
    "/knowledge-base/{kb_id}/sources/{integration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_kb_source(
    kb_id: str,
    integration_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """TA-034: Remove an integration from a KB (detach source)."""
    try:
        uuid.UUID(kb_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="kb_id must be a valid UUID")

    try:
        uuid.UUID(integration_id)
    except ValueError:
        raise HTTPException(
            status_code=422, detail="integration_id must be a valid UUID"
        )

    removed = await delete_kb_source_db(
        kb_id, integration_id, current_user.tenant_id, db
    )
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found or not attached to this KB",
        )
    return None
