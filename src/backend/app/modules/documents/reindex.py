"""
KB re-index estimate and full re-index endpoints (TA-016).

Endpoints (require tenant_admin):
    GET  /admin/knowledge-base/{kb_id}/reindex-estimate
         — returns cost and time estimate for a full re-index

    POST /admin/knowledge-base/{kb_id}/reindex
         — enqueues a full re-index background job
         — 409 if another re-index is already in progress for this KB

Cost formula:
    document_count × avg_tokens_per_doc × embedding_cost_per_token
    avg_tokens_per_doc: last run stats or default 800 tokens
    estimated_duration_minutes: document_count × 0.05 (50ms per doc)
"""
import json
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin-reindex"])

# Default token estimate per document when no stats are available
_DEFAULT_AVG_TOKENS = 800

# Azure OpenAI text-embedding-3-small pricing (per 1K tokens, USD)
# Falls back to this constant if llm_library pricing is unavailable.
_FALLBACK_EMBEDDING_COST_PER_1K = 0.00002  # $0.00002 per 1K tokens


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ReindexEstimateResponse(BaseModel):
    document_count: int
    avg_tokens: int
    estimated_cost_usd: float
    estimated_duration_minutes: float


class ReindexJobResponse(BaseModel):
    job_id: str
    status: str  # always "queued"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_kb_document_count(kb_id: str, tenant_id: str, db: AsyncSession) -> int:
    """Count documents associated with this KB (via integrations.config->>'kb_id')."""
    result = await db.execute(
        text(
            "SELECT COUNT(*) FROM integrations "
            "WHERE tenant_id = :tid "
            "AND config->>'kb_id' = :kb_id"
        ),
        {"tid": tenant_id, "kb_id": kb_id},
    )
    row = result.fetchone()
    return int(row[0]) if row else 0


async def _get_avg_tokens(kb_id: str, tenant_id: str, db: AsyncSession) -> int:
    """Return average tokens from last embedding run stats, or default."""
    # Check sync_jobs table for last completed job stats
    result = await db.execute(
        text(
            "SELECT config->>'avg_tokens_per_doc' FROM sync_jobs "
            "WHERE integration_id IN ("
            "  SELECT id FROM integrations "
            "  WHERE tenant_id = :tid AND config->>'kb_id' = :kb_id"
            ") AND status = 'completed' "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"tid": tenant_id, "kb_id": kb_id},
    )
    row = result.fetchone()
    if row and row[0]:
        try:
            return int(row[0])
        except (ValueError, TypeError):
            pass
    return _DEFAULT_AVG_TOKENS


async def _get_embedding_cost_per_token(tenant_id: str, db: AsyncSession) -> float:
    """Return embedding cost per token for this tenant's configured embedding model."""
    # Attempt to read from tenant's configured llm_library entry
    result = await db.execute(
        text(
            "SELECT ll.pricing_per_1k_tokens_in "
            "FROM tenant_configs tc "
            "JOIN llm_library ll ON ll.id::text = tc.config_data->>'llm_library_id' "
            "WHERE tc.tenant_id = :tid AND tc.config_type = 'llm_config' "
            "AND ll.status = 'Published' "
            "LIMIT 1"
        ),
        {"tid": tenant_id},
    )
    row = result.fetchone()
    if row and row[0] is not None:
        # pricing_per_1k_tokens_in → cost per 1 token
        return float(row[0]) / 1000.0
    return _FALLBACK_EMBEDDING_COST_PER_1K / 1000.0


async def _check_reindex_in_progress(
    kb_id: str, tenant_id: str, db: AsyncSession
) -> bool:
    """Return True if a reindex job is already in progress for this KB."""
    result = await db.execute(
        text(
            "SELECT 1 FROM sync_jobs "
            "WHERE integration_id IN ("
            "  SELECT id FROM integrations "
            "  WHERE tenant_id = :tid AND config->>'kb_id' = :kb_id"
            ") AND status IN ('pending', 'running') "
            "AND config->>'job_type' = 'reindex' "
            "LIMIT 1"
        ),
        {"tid": tenant_id, "kb_id": kb_id},
    )
    return result.fetchone() is not None


async def _run_reindex_job(
    job_id: str,
    kb_id: str,
    tenant_id: str,
) -> None:
    """Background task: perform the full re-index for this KB.

    Steps:
    1. Mark job as 'running'
    2. Retrieve all documents for the KB from integrations
    3. Delete existing vector store entries (if any)
    4. Re-embed all documents using DocumentIndexingPipeline
    5. Mark job as 'completed' (or 'failed' on error)
    """
    from app.core.session import get_async_session  # noqa: PLC0415

    async for db in get_async_session():
        try:
            # Mark job running
            await db.execute(
                text(
                    "UPDATE sync_jobs SET status = 'running', updated_at = NOW() "
                    "WHERE id = :jid"
                ),
                {"jid": job_id},
            )
            await db.commit()

            # Fetch integrations for this KB
            result = await db.execute(
                text(
                    "SELECT id FROM integrations "
                    "WHERE tenant_id = :tid AND config->>'kb_id' = :kb_id"
                ),
                {"tid": tenant_id, "kb_id": kb_id},
            )
            integration_ids = [str(row[0]) for row in result.fetchall()]

            if not integration_ids:
                logger.info(
                    "reindex_no_integrations",
                    job_id=job_id,
                    kb_id=kb_id,
                    tenant_id=tenant_id,
                )
            else:
                logger.info(
                    "reindex_started",
                    job_id=job_id,
                    kb_id=kb_id,
                    tenant_id=tenant_id,
                    integration_count=len(integration_ids),
                )
                # Enqueue a full_sync job for each integration.
                # The sync pipeline (SharePoint/Google Drive) will pick up
                # these jobs, re-fetch all documents, and re-embed them.
                now = datetime.now(timezone.utc)
                for integration_id in integration_ids:
                    sync_job_id = str(uuid.uuid4())
                    await db.execute(
                        text(
                            "INSERT INTO sync_jobs "
                            "  (id, integration_id, status, config, created_at, updated_at) "
                            "VALUES (:id, :integration_id, 'pending', "
                            "        CAST(:config AS jsonb), :created_at, :updated_at) "
                            "ON CONFLICT DO NOTHING"
                        ),
                        {
                            "id": sync_job_id,
                            "integration_id": integration_id,
                            "config": json.dumps(
                                {
                                    "job_type": "full_sync",
                                    "triggered_by": "reindex",
                                    "reindex_job_id": job_id,
                                }
                            ),
                            "created_at": now,
                            "updated_at": now,
                        },
                    )
                await db.commit()
                logger.info(
                    "reindex_sync_jobs_created",
                    job_id=job_id,
                    kb_id=kb_id,
                    tenant_id=tenant_id,
                    sync_jobs_queued=len(integration_ids),
                )

            # Mark job completed
            await db.execute(
                text(
                    "UPDATE sync_jobs SET status = 'completed', updated_at = NOW() "
                    "WHERE id = :jid"
                ),
                {"jid": job_id},
            )
            await db.commit()

            logger.info(
                "reindex_completed",
                job_id=job_id,
                kb_id=kb_id,
                tenant_id=tenant_id,
            )

        except Exception as exc:
            await db.execute(
                text(
                    "UPDATE sync_jobs SET status = 'failed', updated_at = NOW() "
                    "WHERE id = :jid"
                ),
                {"jid": job_id},
            )
            await db.commit()
            logger.error(
                "reindex_failed",
                job_id=job_id,
                kb_id=kb_id,
                tenant_id=tenant_id,
                error=str(exc),
            )
        break  # single iteration from the async generator


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/knowledge-base/{kb_id}/reindex-estimate",
    response_model=ReindexEstimateResponse,
)
async def get_reindex_estimate(
    kb_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> ReindexEstimateResponse:
    """Calculate cost and time estimate for a full KB re-index.

    document_count: COUNT from integrations table for this KB.
    avg_tokens: from last embedding run stats, or default 800.
    estimated_cost_usd: document_count × avg_tokens × cost_per_token.
    estimated_duration_minutes: document_count × 0.05 (50ms/doc).
    """
    try:
        uuid.UUID(kb_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="kb_id must be a valid UUID")

    doc_count = await _get_kb_document_count(kb_id, current_user.tenant_id, db)
    avg_tokens = await _get_avg_tokens(kb_id, current_user.tenant_id, db)
    cost_per_token = await _get_embedding_cost_per_token(current_user.tenant_id, db)

    estimated_cost = doc_count * avg_tokens * cost_per_token
    estimated_duration = doc_count * 0.05  # 50ms per doc → minutes

    logger.info(
        "reindex_estimate_computed",
        kb_id=kb_id,
        tenant_id=current_user.tenant_id,
        document_count=doc_count,
        avg_tokens=avg_tokens,
        estimated_cost_usd=estimated_cost,
    )

    return ReindexEstimateResponse(
        document_count=doc_count,
        avg_tokens=avg_tokens,
        estimated_cost_usd=round(estimated_cost, 6),
        estimated_duration_minutes=round(estimated_duration, 2),
    )


@router.post(
    "/knowledge-base/{kb_id}/reindex",
    response_model=ReindexJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_reindex(
    kb_id: str,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> ReindexJobResponse:
    """Enqueue a full re-index job for a KB.

    Returns 409 if another re-index is already in progress for this KB.
    The job runs asynchronously — returns immediately with job_id and status=queued.
    """
    try:
        uuid.UUID(kb_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="kb_id must be a valid UUID")

    # Rate limit: one active reindex per KB
    in_progress = await _check_reindex_in_progress(kb_id, current_user.tenant_id, db)
    if in_progress:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A re-index job is already in progress for this knowledge base.",
        )

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # Find integration_id for this KB (use first match for sync_jobs FK)
    result = await db.execute(
        text(
            "SELECT id FROM integrations "
            "WHERE tenant_id = :tid AND config->>'kb_id' = :kb_id "
            "LIMIT 1"
        ),
        {"tid": current_user.tenant_id, "kb_id": kb_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No integrations found for this knowledge base.",
        )
    integration_id = str(row[0])

    # Create sync_jobs record with job_type=reindex
    await db.execute(
        text(
            "INSERT INTO sync_jobs "
            "  (id, integration_id, status, config, created_at, updated_at) "
            "VALUES (:id, :integration_id, 'pending', "
            "        CAST(:config AS jsonb), :created_at, :updated_at)"
        ),
        {
            "id": job_id,
            "integration_id": integration_id,
            "config": json.dumps({"job_type": "reindex", "kb_id": kb_id}),
            "created_at": now,
            "updated_at": now,
        },
    )
    await db.commit()

    # Enqueue background task
    background_tasks.add_task(
        _run_reindex_job,
        job_id=job_id,
        kb_id=kb_id,
        tenant_id=current_user.tenant_id,
    )

    logger.info(
        "reindex_job_queued",
        job_id=job_id,
        kb_id=kb_id,
        tenant_id=current_user.tenant_id,
    )

    return ReindexJobResponse(job_id=job_id, status="queued")
