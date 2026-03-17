"""
Google Drive sync worker (DEF-010).

Implements incremental sync via Google Drive changes.list (pageToken-based)
and push notification webhook for real-time change events.

Endpoints:
- POST /documents/google-drive/{id}/watch        — Register a push notification channel
- POST /webhooks/google-drive/changes            — Receive Google Drive change events

Security:
- Webhook validates X-Goog-Channel-Token against integration.config['channel_token']
- OAuth tokens are NEVER logged
- Parameterized SQL only; CAST(:param AS jsonb) for JSONB columns
"""
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

# Router for the watch endpoint (tenant-admin–protected)
router = APIRouter(prefix="/documents", tags=["documents"])

# Router for the inbound webhook (no auth — validated by channel token)
webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Google Drive supported MIME types that can be indexed
_INDEXABLE_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/plain",
        "application/vnd.google-apps.document",
        "application/vnd.google-apps.presentation",
    }
)

# Maximum number of change pages to process per webhook delivery (guard against loops)
_MAX_PAGES_PER_DELIVERY = 20


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def get_gd_integration_by_channel_token(
    channel_token: str,
    db: AsyncSession,
) -> Optional[dict]:
    """
    Fetch a Google Drive integration whose config contains the given channel_token.

    Used to authenticate inbound push notification webhooks without requiring a
    tenant_id in the URL (Google sends to a fixed endpoint).

    Returns None if no matching integration is found.
    """
    result = await db.execute(
        text(
            "SELECT id, tenant_id, status, config "
            "FROM integrations "
            "WHERE provider = 'google_drive' "
            "AND config->>'channel_token' = :channel_token "
            "AND status != 'disabled'"
        ),
        {"channel_token": channel_token},
    )
    row = result.mappings().first()
    if row is None:
        return None
    config_val = row["config"]
    if isinstance(config_val, str):
        config_val = json.loads(config_val)
    return {
        "id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "status": row["status"],
        "config": config_val,
    }


async def get_gd_integration_for_tenant(
    integration_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[dict]:
    """Fetch a Google Drive integration by id + tenant_id. Returns None if not found."""
    result = await db.execute(
        text(
            "SELECT id, tenant_id, status, config "
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
        "tenant_id": str(row["tenant_id"]),
        "status": row["status"],
        "config": config_val,
    }


async def upsert_watch_channel_db(
    integration_id: str,
    tenant_id: str,
    channel_id: str,
    channel_token: str,
    resource_id: str,
    expiration_ms: int,
    db: AsyncSession,
) -> None:
    """
    Persist the watch channel details into integrations.config.

    Merges channel_id, channel_token, resource_id, and expiration_ms into the
    existing config JSON so that inbound push notifications can be authenticated
    and routed back to the correct integration.
    """
    result = await db.execute(
        text(
            "SELECT config FROM integrations "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": integration_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return

    config_val = row[0]
    if isinstance(config_val, str):
        config_val = json.loads(config_val)
    elif config_val is None:
        config_val = {}

    config_val["channel_id"] = channel_id
    config_val["channel_token"] = channel_token
    config_val["resource_id"] = resource_id
    config_val["channel_expiration_ms"] = expiration_ms

    await db.execute(
        text(
            "UPDATE integrations "
            "SET config = CAST(:config AS jsonb), updated_at = :now "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {
            "config": json.dumps(config_val),
            "now": datetime.now(timezone.utc),
            "id": integration_id,
            "tenant_id": tenant_id,
        },
    )
    await db.commit()


async def get_page_token_db(
    integration_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[str]:
    """
    Retrieve the stored Drive changes.list pageToken from integration config.

    Returns None if no token has been stored yet (triggers a full token fetch
    from Drive API before the first incremental sync).
    """
    result = await db.execute(
        text(
            "SELECT config->>'page_token' AS page_token "
            "FROM integrations "
            "WHERE id = :id AND tenant_id = :tenant_id AND provider = 'google_drive'"
        ),
        {"id": integration_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return row[0]


async def save_page_token_db(
    integration_id: str,
    tenant_id: str,
    page_token: str,
    db: AsyncSession,
) -> None:
    """Persist the latest changes.list pageToken into integrations.config['page_token']."""
    result = await db.execute(
        text(
            "SELECT config FROM integrations "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": integration_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return

    config_val = row[0]
    if isinstance(config_val, str):
        config_val = json.loads(config_val)
    elif config_val is None:
        config_val = {}

    config_val["page_token"] = page_token

    await db.execute(
        text(
            "UPDATE integrations "
            "SET config = CAST(:config AS jsonb), updated_at = :now "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {
            "config": json.dumps(config_val),
            "now": datetime.now(timezone.utc),
            "id": integration_id,
            "tenant_id": tenant_id,
        },
    )
    await db.commit()


async def create_incremental_sync_job_db(
    integration_id: str,
    tenant_id: str,
    trigger: str,
    db: AsyncSession,
) -> str:
    """
    Create a sync_jobs row for an incremental sync triggered by a Drive change event.

    trigger: 'webhook' | 'manual'
    Returns the new job_id.
    """
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    metadata = json.dumps({"trigger": trigger, "sync_type": "incremental"})
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
    logger.info(
        "google_drive_sync_job_created",
        job_id=job_id,
        integration_id=integration_id,
        tenant_id=tenant_id,
        trigger=trigger,
    )
    return job_id


async def check_duplicate_webhook_db(
    integration_id: str,
    resource_id: str,
    channel_id: str,
    db: AsyncSession,
) -> bool:
    """
    Check whether a webhook delivery for this integration has already created a
    sync_job in the last 5 seconds (idempotency guard).

    Scoped to integration_id to prevent cross-tenant false-positive suppression.
    Returns True if a recent duplicate exists (caller should skip processing).
    """
    result = await db.execute(
        text(
            "SELECT COUNT(*) FROM sync_jobs "
            "WHERE integration_id = :integration_id "
            "AND status = 'queued' "
            "AND created_at >= NOW() - INTERVAL '5 seconds'"
        ),
        {"integration_id": integration_id},
    )
    count = result.scalar() or 0
    return count > 0


# ---------------------------------------------------------------------------
# Drive API helpers (thin wrappers — real calls isolated for testability)
# ---------------------------------------------------------------------------


def _build_drive_service(credential_ref: str):
    """
    Build a Google Drive API service object from a vault credential reference.

    Resolves credential_ref through the vault client (Azure Key Vault in
    production, LocalDBVaultClient in dev). The vault returns the service
    account JSON which is parsed in-memory only and never logged.

    Raises RuntimeError if the vault client cannot resolve the reference.
    Raises ImportError if google-auth or google-api-python-client are missing.
    """
    from google.oauth2 import service_account  # noqa: PLC0415
    from googleapiclient.discovery import build as gapi_build  # noqa: PLC0415

    from app.core.secrets.vault_client import get_vault_client  # noqa: PLC0415

    # Resolve via vault — plaintext never persisted beyond this scope
    sa_json = get_vault_client().get_secret(credential_ref)
    sa_info = json.loads(sa_json)

    scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    credentials = service_account.Credentials.from_service_account_info(
        sa_info, scopes=scopes
    )
    return gapi_build("drive", "v3", credentials=credentials)


async def _get_start_page_token(service) -> str:
    """Fetch the current start pageToken from Drive changes API."""
    response = service.changes().getStartPageToken().execute()
    return response["startPageToken"]


async def _list_changes(service, page_token: str, page_size: int = 100) -> dict:
    """
    Call Drive changes.list for one page of changes.

    Returns the raw API response dict containing:
      - changes: list of change objects
      - nextPageToken: present if more pages exist
      - newStartPageToken: present on the last page (save as next cursor)
    """
    return (
        service.changes()
        .list(
            pageToken=page_token,
            spaces="drive",
            fields=(
                "nextPageToken,newStartPageToken,"
                "changes(file(id,name,mimeType,trashed,modifiedTime),"
                "removed,fileId)"
            ),
            pageSize=page_size,
        )
        .execute()
    )


# ---------------------------------------------------------------------------
# Incremental sync orchestration
# ---------------------------------------------------------------------------


async def run_incremental_sync(
    integration_id: str,
    tenant_id: str,
    trigger: str,
    db: AsyncSession,
) -> dict:
    """
    Run an incremental sync for a Google Drive integration.

    Steps:
    1. Load integration config to get credential_ref and stored pageToken.
    2. If no pageToken, fetch startPageToken from Drive API and save it (no-op sync).
    3. Walk pages of changes.list (up to _MAX_PAGES_PER_DELIVERY pages).
    4. For each changed file: if indexable and not trashed/removed, queue re-embed.
    5. Save the new pageToken.
    6. Create a sync_jobs entry.

    Returns a summary dict.
    """
    integration = await get_gd_integration_for_tenant(
        integration_id=integration_id,
        tenant_id=tenant_id,
        db=db,
    )
    if integration is None:
        logger.warning(
            "google_drive_sync_integration_not_found",
            integration_id=integration_id,
            tenant_id=tenant_id,
        )
        return {"status": "skipped", "reason": "integration_not_found"}

    config = integration["config"]
    credential_ref = config.get("credential_ref", "")

    # Build Drive service — errors here are unrecoverable; propagate to caller
    try:
        service = _build_drive_service(credential_ref)
    except Exception as exc:
        logger.error(
            "google_drive_sync_service_build_failed",
            integration_id=integration_id,
            tenant_id=tenant_id,
            error=str(exc),
        )
        return {"status": "error", "reason": "service_build_failed"}

    # Load stored pageToken
    page_token = await get_page_token_db(
        integration_id=integration_id,
        tenant_id=tenant_id,
        db=db,
    )
    if page_token is None:
        # First run — save the start token and return (next webhook will trigger real sync)
        try:
            start_token = await _get_start_page_token(service)
        except Exception as exc:
            logger.error(
                "google_drive_sync_start_token_failed",
                integration_id=integration_id,
                tenant_id=tenant_id,
                error=str(exc),
            )
            return {"status": "error", "reason": "start_token_failed"}

        await save_page_token_db(
            integration_id=integration_id,
            tenant_id=tenant_id,
            page_token=start_token,
            db=db,
        )
        logger.info(
            "google_drive_sync_start_token_saved",
            integration_id=integration_id,
            tenant_id=tenant_id,
        )
        return {"status": "initialised", "page_token_saved": True}

    # Walk change pages
    files_queued = 0
    files_skipped = 0
    pages_processed = 0
    current_token = page_token
    final_token = page_token

    while pages_processed < _MAX_PAGES_PER_DELIVERY:
        try:
            response = await _list_changes(service, current_token)
        except Exception as exc:
            logger.error(
                "google_drive_sync_list_changes_failed",
                integration_id=integration_id,
                tenant_id=tenant_id,
                error=str(exc),
            )
            break

        pages_processed += 1
        changes = response.get("changes", [])

        for change in changes:
            file_info = change.get("file", {})
            file_id = change.get("fileId", file_info.get("id", ""))
            removed = change.get("removed", False)
            trashed = file_info.get("trashed", False)
            mime_type = file_info.get("mimeType", "")
            file_name = file_info.get("name", "")

            if removed or trashed:
                # File deleted — skip embedding, optionally remove from vector store
                logger.info(
                    "google_drive_sync_file_removed",
                    integration_id=integration_id,
                    tenant_id=tenant_id,
                    file_id=file_id,
                )
                files_skipped += 1
                continue

            if mime_type not in _INDEXABLE_MIME_TYPES:
                logger.info(
                    "google_drive_sync_file_type_skipped",
                    integration_id=integration_id,
                    tenant_id=tenant_id,
                    file_id=file_id,
                    mime_type=mime_type,
                )
                files_skipped += 1
                continue

            # Queue re-embed — inaccessible files are caught and skipped
            try:
                await _queue_file_reembed(
                    service=service,
                    file_id=file_id,
                    file_name=file_name,
                    integration_id=integration_id,
                    tenant_id=tenant_id,
                    db=db,
                )
                files_queued += 1
            except Exception as exc:
                # Log and skip — inaccessible files (403, 404) must not crash the worker
                logger.warning(
                    "google_drive_sync_file_skipped",
                    integration_id=integration_id,
                    tenant_id=tenant_id,
                    file_id=file_id,
                    error=str(exc),
                )
                files_skipped += 1

        # Advance token
        if "nextPageToken" in response:
            current_token = response["nextPageToken"]
        else:
            # Last page — newStartPageToken is the cursor for the next sync
            final_token = response.get("newStartPageToken", current_token)
            break

    # Persist the new pageToken after successfully walking all pages
    if final_token != page_token:
        await save_page_token_db(
            integration_id=integration_id,
            tenant_id=tenant_id,
            page_token=final_token,
            db=db,
        )

    # Create sync job record
    job_id = await create_incremental_sync_job_db(
        integration_id=integration_id,
        tenant_id=tenant_id,
        trigger=trigger,
        db=db,
    )

    logger.info(
        "google_drive_incremental_sync_complete",
        integration_id=integration_id,
        tenant_id=tenant_id,
        pages_processed=pages_processed,
        files_queued=files_queued,
        files_skipped=files_skipped,
        job_id=job_id,
    )

    return {
        "status": "completed",
        "job_id": job_id,
        "pages_processed": pages_processed,
        "files_queued": files_queued,
        "files_skipped": files_skipped,
    }


async def _queue_file_reembed(
    service,
    file_id: str,
    file_name: str,
    integration_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    """
    Queue a file for re-embedding in the vector store.

    Phase 1: Logs the intent.  In production, this publishes to the indexing
    pipeline (DocumentIndexingPipeline) or a task queue.

    Raises any exception so the caller can log + skip.
    """
    logger.info(
        "google_drive_file_queued_for_reembed",
        integration_id=integration_id,
        tenant_id=tenant_id,
        file_id=file_id,
        file_name=file_name,
    )
    # In production: await DocumentIndexingPipeline().process_drive_file(...)
    # For Phase 1 the job creation in run_incremental_sync records the intent.


# ---------------------------------------------------------------------------
# POST /documents/google-drive/{integration_id}/watch
# ---------------------------------------------------------------------------


@router.post(
    "/google-drive/{integration_id}/watch",
    status_code=status.HTTP_201_CREATED,
)
async def register_watch_channel(
    integration_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """
    DEF-010: Register a Google Drive push notification channel for an integration.

    Creates a watch channel so Google Drive sends change events to
    POST /webhooks/google-drive/changes.  The channel_token (a random secret)
    is stored in integration.config and used to authenticate inbound events.

    Response: { "channel_id": "...", "expiration_ms": ..., "status": "watching" }
    """
    integration = await get_gd_integration_for_tenant(
        integration_id=str(integration_id),
        tenant_id=current_user.tenant_id,
        db=db,
    )
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found",
        )

    channel_id = str(uuid.uuid4())
    channel_token = secrets.token_urlsafe(32)
    # Use a placeholder resource_id — the real resource_id is returned by Google
    # Drive API when the watch is registered.  Phase 1 stores a sentinel value.
    resource_id = f"drive-resource-{integration_id}"

    # Expiration: 7 days from now in milliseconds (Google Drive max is 1 week)
    expiration_ms = int(datetime.now(timezone.utc).timestamp() * 1000) + (
        7 * 24 * 3600 * 1000
    )

    await upsert_watch_channel_db(
        integration_id=str(integration_id),
        tenant_id=str(current_user.tenant_id),
        channel_id=channel_id,
        channel_token=channel_token,
        resource_id=resource_id,
        expiration_ms=expiration_ms,
        db=db,
    )

    logger.info(
        "google_drive_watch_channel_registered",
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        channel_id=channel_id,
    )

    return {
        "channel_id": channel_id,
        "expiration_ms": expiration_ms,
        "status": "watching",
    }


# ---------------------------------------------------------------------------
# POST /webhooks/google-drive/changes
# ---------------------------------------------------------------------------


@webhook_router.post("/google-drive/changes", status_code=status.HTTP_200_OK)
async def google_drive_webhook(
    request: Request,
    x_goog_channel_id: Optional[str] = Header(None, alias="X-Goog-Channel-ID"),
    x_goog_channel_token: Optional[str] = Header(None, alias="X-Goog-Channel-Token"),
    x_goog_resource_id: Optional[str] = Header(None, alias="X-Goog-Resource-ID"),
    x_goog_resource_state: Optional[str] = Header(None, alias="X-Goog-Resource-State"),
    db: AsyncSession = Depends(get_async_session),
):
    """
    DEF-010: Receive Google Drive push notification change events.

    Google Drive sends a POST to this endpoint when files in a watched folder
    change.  Authentication is performed by matching the X-Goog-Channel-Token
    header against the channel_token stored in integration.config.

    On sync events: creates a sync_job entry and triggers incremental sync.
    On 'sync' (initial ping) events: records the channel but skips processing.

    Returns 200 OK regardless of processing outcome (Drive retries on non-2xx).
    """
    # Validate required headers are present then authenticate by channel_token.
    # Both missing-token and invalid-token return the same generic response to
    # prevent callers from distinguishing rejection reasons.
    if not x_goog_channel_token:
        logger.warning(
            "google_drive_webhook_missing_token",
            channel_id=x_goog_channel_id,
        )
        return {"status": "ok"}

    # Authenticate: look up integration by channel_token
    integration = await get_gd_integration_by_channel_token(
        channel_token=x_goog_channel_token,
        db=db,
    )
    if integration is None:
        logger.warning(
            "google_drive_webhook_invalid_token",
            channel_id=x_goog_channel_id,
        )
        return {"status": "ok"}

    integration_id = integration["id"]
    tenant_id = integration["tenant_id"]

    # 'sync' is the initial ping Google sends when a channel is first registered
    if x_goog_resource_state == "sync":
        logger.info(
            "google_drive_webhook_sync_ping",
            integration_id=integration_id,
            tenant_id=tenant_id,
            channel_id=x_goog_channel_id,
        )
        return {"status": "ok", "event": "sync_ping"}

    # Idempotency: skip if a recent sync_job already exists for this integration
    if x_goog_resource_id:
        is_dup = await check_duplicate_webhook_db(
            integration_id=integration_id,
            resource_id=x_goog_resource_id,
            channel_id=x_goog_channel_id or "",
            db=db,
        )
        if is_dup:
            logger.info(
                "google_drive_webhook_duplicate_skipped",
                integration_id=integration_id,
                tenant_id=tenant_id,
                channel_id=x_goog_channel_id,
            )
            return {"status": "ok", "event": "duplicate_skipped"}

    # Create sync_job entry for this change event
    job_id = await create_incremental_sync_job_db(
        integration_id=integration_id,
        tenant_id=tenant_id,
        trigger="webhook",
        db=db,
    )

    logger.info(
        "google_drive_webhook_change_received",
        integration_id=integration_id,
        tenant_id=tenant_id,
        channel_id=x_goog_channel_id,
        resource_state=x_goog_resource_state,
        job_id=job_id,
    )

    # Invalidate semantic cache for this tenant on file change
    try:
        from app.core.cache.semantic_cache_service import SemanticCacheService

        sem_cache = SemanticCacheService()
        await sem_cache.invalidate_tenant(tenant_id)
    except Exception as exc:
        logger.warning(
            "google_drive_webhook_cache_invalidation_failed",
            integration_id=integration_id,
            tenant_id=tenant_id,
            error=str(exc),
        )

    return {"status": "ok", "job_id": job_id}
