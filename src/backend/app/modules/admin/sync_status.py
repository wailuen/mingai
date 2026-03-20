"""
SCHED-027: Tenant Admin sync-status endpoint.

GET /api/v1/tenant/sync-status — outcome-centric view of scheduled jobs.
Tenant Admin scope only.

Returns human-meaningful outcome signals derived from job_run_log, not raw
execution internals. Enterprise tenants care about "are my documents current?"
not "how many milliseconds did credential_expiry take?"

All fields are nullable — if a job has never run for this tenant, the field is null.
"""
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/tenant", tags=["admin"])


class SyncStatusResponse(BaseModel):
    last_credentials_checked_at: Optional[str]
    credentials_expiry_days_remaining: Optional[int]
    last_query_warming_completed_at: Optional[str]
    last_health_score_calculated_at: Optional[str]
    glossary_terms_active: int


@router.get("/sync-status", response_model=SyncStatusResponse)
async def get_sync_status(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> SyncStatusResponse:
    """
    Return outcome-centric sync status signals for the tenant admin dashboard.

    Derives each signal from job_run_log (completed rows) and live table queries.
    Never exposes raw execution internals (duration_ms, instance_id, etc.).
    """
    tenant_id = current_user.tenant_id

    # Last credentials check for this tenant
    cred_result = await db.execute(
        text(
            "SELECT started_at FROM job_run_log "
            "WHERE job_name = 'credential_expiry' "
            "AND status = 'completed' "
            "AND tenant_id = :tenant_id "
            "ORDER BY started_at DESC LIMIT 1"
        ),
        {"tenant_id": str(tenant_id)},
    )
    cred_row = cred_result.fetchone()
    last_credentials_checked_at = (
        cred_row[0].isoformat() if cred_row and cred_row[0] else None
    )

    # Credential expiry days remaining — from the tenant's integration credentials
    expiry_result = await db.execute(
        text(
            "SELECT MIN(EXTRACT(EPOCH FROM (expires_at - NOW())) / 86400)::int "
            "FROM integrations "
            "WHERE tenant_id = :tenant_id "
            "AND expires_at IS NOT NULL "
            "AND expires_at > NOW()"
        ),
        {"tenant_id": str(tenant_id)},
    )
    expiry_row = expiry_result.fetchone()
    credentials_expiry_days_remaining = (
        int(expiry_row[0]) if expiry_row and expiry_row[0] is not None else None
    )

    # Last query warming — platform-scope job (tenant_id IS NULL), shared across tenants
    warming_result = await db.execute(
        text(
            "SELECT started_at FROM job_run_log "
            "WHERE job_name = 'query_warming' "
            "AND status = 'completed' "
            "AND tenant_id IS NULL "
            "ORDER BY started_at DESC LIMIT 1"
        ),
    )
    warming_row = warming_result.fetchone()
    last_query_warming_completed_at = (
        warming_row[0].isoformat() if warming_row and warming_row[0] else None
    )

    # Last health score calculation for this tenant
    health_result = await db.execute(
        text(
            "SELECT started_at FROM job_run_log "
            "WHERE job_name = 'health_score' "
            "AND status = 'completed' "
            "AND tenant_id = :tenant_id "
            "ORDER BY started_at DESC LIMIT 1"
        ),
        {"tenant_id": str(tenant_id)},
    )
    health_row = health_result.fetchone()
    last_health_score_calculated_at = (
        health_row[0].isoformat() if health_row and health_row[0] else None
    )

    # Active glossary terms — live count from glossary_terms table
    glossary_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM glossary_terms "
            "WHERE tenant_id = :tenant_id AND is_active = true"
        ),
        {"tenant_id": str(tenant_id)},
    )
    glossary_row = glossary_result.fetchone()
    glossary_terms_active = int(glossary_row[0]) if glossary_row and glossary_row[0] else 0

    return SyncStatusResponse(
        last_credentials_checked_at=last_credentials_checked_at,
        credentials_expiry_days_remaining=credentials_expiry_days_remaining,
        last_query_warming_completed_at=last_query_warming_completed_at,
        last_health_score_calculated_at=last_health_score_calculated_at,
        glossary_terms_active=glossary_terms_active,
    )
