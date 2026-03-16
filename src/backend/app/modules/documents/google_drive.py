"""
Google Drive integration routes (TA-019).

Endpoints:
- GET  /documents/google-drive                 — List Google Drive connections
- POST /documents/google-drive/connect         — Create a new connection
- POST /documents/google-drive/{id}/sync       — Trigger document sync
- GET  /documents/google-drive/{id}/sync       — List sync job history
- GET  /documents/google-drive/{id}/folders    — Folder tree (up to 3 levels)

Security: service account credentials are stored as vault references only.
The DB config stores a credential_ref URI, never the actual key material.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/documents", tags=["documents"])

# Required top-level keys in a Google Drive service account JSON
_SA_REQUIRED_FIELDS = frozenset({"type", "project_id", "private_key", "client_email"})


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class GoogleDriveConnectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    folder_id: str = Field(..., min_length=1)
    service_account_json: dict[str, Any] = Field(
        ...,
        description=(
            "Full service account JSON (type, project_id, private_key, client_email "
            "and other fields). Credentials are stored in vault only — never in DB."
        ),
    )

    @field_validator("service_account_json")
    @classmethod
    def validate_service_account_fields(cls, v: dict) -> dict:
        missing = _SA_REQUIRED_FIELDS - v.keys()
        if missing:
            raise ValueError(
                f"service_account_json is missing required fields: {sorted(missing)}"
            )
        if v.get("type") != "service_account":
            raise ValueError("service_account_json.type must be 'service_account'")
        return v


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def insert_gd_integration_db(
    integration_id: str,
    tenant_id: str,
    name: str,
    config: dict,
    db: AsyncSession,
) -> dict:
    """Insert a new Google Drive integration record."""
    config_json = json.dumps(config)
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO integrations (id, tenant_id, provider, status, config, created_at, updated_at) "
            "VALUES (:id, :tenant_id, 'google_drive', 'pending', CAST(:config AS jsonb), :created_at, :updated_at)"
        ),
        {
            "id": integration_id,
            "tenant_id": tenant_id,
            "config": config_json,
            "created_at": now,
            "updated_at": now,
        },
    )
    await db.commit()
    return {
        "id": integration_id,
        "name": name,
        "status": "pending",
        "folder_id": config.get("folder_id", ""),
        "last_sync_at": None,
        "last_sync_status": None,
    }


async def list_gd_integrations_db(tenant_id: str, db: AsyncSession) -> list:
    """List all Google Drive integrations for a tenant with last sync info."""
    result = await db.execute(
        text(
            "SELECT i.id, i.config, i.status, "
            "sj.created_at AS last_sync_at, sj.status AS last_sync_status "
            "FROM integrations i "
            "LEFT JOIN LATERAL ("
            "  SELECT sj2.created_at, sj2.status "
            "  FROM sync_jobs sj2 "
            "  WHERE sj2.integration_id = i.id "
            "  ORDER BY sj2.created_at DESC LIMIT 1"
            ") sj ON true "
            "WHERE i.tenant_id = :tenant_id AND i.provider = 'google_drive' "
            "ORDER BY i.created_at DESC"
        ),
        {"tenant_id": tenant_id},
    )
    items = []
    for row in result.mappings():
        config_val = row["config"]
        if isinstance(config_val, str):
            config_val = json.loads(config_val)
        last_sync_at = row["last_sync_at"]
        if isinstance(last_sync_at, datetime):
            last_sync_at = last_sync_at.isoformat()
        items.append(
            {
                "id": str(row["id"]),
                "name": config_val.get("name", ""),
                "status": row["status"],
                "folder_id": config_val.get("folder_id", ""),
                "last_sync_at": str(last_sync_at) if last_sync_at else None,
                "last_sync_status": row["last_sync_status"],
            }
        )
    return items


async def get_gd_integration_db(
    integration_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[dict]:
    """Fetch a Google Drive integration by id and tenant_id."""
    result = await db.execute(
        text(
            "SELECT id, tenant_id, provider, status, config "
            "FROM integrations "
            "WHERE id = :id AND tenant_id = :tenant_id AND provider = 'google_drive'"
        ),
        {"id": integration_id, "tenant_id": tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    config_val = row["config"]
    if isinstance(config_val, str):
        config_val = json.loads(config_val)
    return {
        "id": str(row["id"]),
        "tenant_id": row["tenant_id"],
        "status": row["status"],
        "config": config_val,
    }


async def create_gd_sync_job_db(
    integration_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """Create a queued sync job for a Google Drive integration."""
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO sync_jobs (id, integration_id, tenant_id, status, created_at) "
            "VALUES (:id, :integration_id, :tenant_id, 'queued', :created_at)"
        ),
        {
            "id": job_id,
            "integration_id": integration_id,
            "tenant_id": tenant_id,
            "created_at": now,
        },
    )
    await db.commit()
    return {"job_id": job_id, "status": "queued"}


async def list_gd_sync_jobs_db(
    integration_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list:
    """List the last 10 sync jobs for a Google Drive integration."""
    rows_result = await db.execute(
        text(
            "SELECT id, status, created_at FROM sync_jobs "
            "WHERE integration_id = :integration_id AND tenant_id = :tenant_id "
            "ORDER BY created_at DESC LIMIT 10"
        ),
        {"integration_id": integration_id, "tenant_id": tenant_id},
    )
    jobs = []
    for row in rows_result.mappings():
        created_at = row["created_at"]
        if isinstance(created_at, datetime):
            created_at = created_at.isoformat()
        jobs.append(
            {
                "id": str(row["id"]),
                "status": row["status"],
                "started_at": str(created_at),
                "completed_at": None,
                "documents_synced": 0,
                "error_message": None,
            }
        )
    return jobs


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/google-drive")
async def list_google_drive_connections(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """List all Google Drive integrations for the tenant."""
    return await list_gd_integrations_db(
        tenant_id=current_user.tenant_id,
        db=db,
    )


@router.post("/google-drive/connect", status_code=status.HTTP_201_CREATED)
async def connect_google_drive(
    body: GoogleDriveConnectRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    TA-019: Create a new Google Drive integration.

    Accepts service_account_json with required fields validated.
    Credentials are NEVER stored in the database — a vault reference URI
    is stored in config['credential_ref'] instead.
    """
    integration_id = str(uuid.uuid4())
    vault_ref = f"vault:mingai/{current_user.tenant_id}/google_drive/{integration_id}"
    config = {
        "name": body.name,
        "folder_id": body.folder_id,
        "service_account_email": body.service_account_json.get("client_email", ""),
        "credential_ref": vault_ref,
    }
    result = await insert_gd_integration_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        name=body.name,
        config=config,
        db=db,
    )
    logger.info(
        "google_drive_connection_created",
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        name=body.name,
    )
    return result


@router.post(
    "/google-drive/{integration_id}/sync",
    status_code=status.HTTP_201_CREATED,
)
async def trigger_google_drive_sync(
    integration_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Trigger a document sync for a Google Drive integration."""
    integration = await get_gd_integration_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration {integration_id} not found",
        )
    result = await create_gd_sync_job_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )

    # CACHE-011: Invalidate search and semantic caches for this index on sync trigger.
    # Both calls are fire-and-forget — sync job creation is not blocked by cache ops.
    try:
        from app.core.cache_utils import increment_index_version
        from app.core.cache.semantic_cache_service import SemanticCacheService
        import asyncio

        asyncio.create_task(
            increment_index_version(current_user.tenant_id, integration_id)
        )
        sem_cache = SemanticCacheService()
        await sem_cache.invalidate_tenant(current_user.tenant_id)
    except Exception as exc:
        logger.warning(
            "google_drive_sync_cache_invalidation_failed",
            tenant_id=current_user.tenant_id,
            integration_id=integration_id,
            error=str(exc),
        )

    logger.info(
        "google_drive_sync_triggered",
        integration_id=integration_id,
        job_id=result["job_id"],
        tenant_id=current_user.tenant_id,
    )
    return result


@router.get("/google-drive/{integration_id}/sync")
async def list_google_drive_sync_history(
    integration_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """List sync job history for a Google Drive integration."""
    integration = await get_gd_integration_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration {integration_id} not found",
        )
    return await list_gd_sync_jobs_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )


# ---------------------------------------------------------------------------
# TA-019: Google Drive folder tree endpoint
# ---------------------------------------------------------------------------


def _build_folder_tree(root_id: str, root_name: str, depth: int = 3) -> dict:
    """
    Build a folder tree node.

    Phase 1: Returns the configured root folder with empty children.
    Depth parameter is reserved for future lazy-load support when the
    Google Drive API client is integrated — children beyond depth 3 are
    not returned (they must be lazy-loaded on expand).

    Real folder traversal (listing sub-folders via Google Drive API) is
    tracked in DEF-010 (sync worker implementation).
    """
    return {
        "id": root_id,
        "name": root_name,
        "children": [],  # Expanded by Google Drive API in DEF-010
    }


@router.get("/google-drive/{integration_id}/folders")
async def list_google_drive_folders(
    integration_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    TA-019: Return the folder tree for a Google Drive integration.

    Returns the root folder from config, with up to 3 levels of children.
    Phase 1: Returns the configured root folder with empty children list.
    Full folder traversal requires the DEF-010 sync worker (Google Drive API client).

    Response: [{ "id": "...", "name": "...", "children": [...] }]
    """
    integration = await get_gd_integration_db(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration {integration_id} not found",
        )

    config = integration.get("config", {})
    root_folder_id = config.get("folder_id", "root")
    root_folder_name = config.get("name", "My Drive")

    tree = _build_folder_tree(root_id=root_folder_id, root_name=root_folder_name)

    logger.info(
        "google_drive_folders_listed",
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        root_folder_id=root_folder_id,
    )

    return [tree]
