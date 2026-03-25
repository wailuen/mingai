"""
Platform issues analytics endpoints.

Endpoints:
- GET /platform/analytics/issues/summary    — KPI summary (total, open, P0, SLA %, avg MTTR)
- GET /platform/analytics/issues/by-tenant  — Issues broken down per tenant
- GET /platform/analytics/issues/by-severity — Count + % by severity tier
- GET /platform/analytics/issues/sla        — SLA adherence gauge
- GET /platform/analytics/issues/mttr       — Mean time to resolution by severity
- GET /platform/analytics/issues/trend      — Weekly issue volume trend by severity
- GET /platform/analytics/issues/top-bugs   — Most-reported issue types (cross-tenant)
- GET /platform/analytics/issues/duplicates — Potential duplicate clusters (by issue_type)

Auth: require_platform_admin on every endpoint.
Graceful degradation: if issue_reports table is missing (shouldn't happen in prod),
return zeroed-out responses rather than 500.
"""
import re as _re
from typing import List

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_platform_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/platform/analytics/issues", tags=["platform-issue-analytics"])

# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------

_VALID_PERIODS = {"7d", "30d", "90d"}

# SLA thresholds in hours by severity
_SLA_HOURS: dict[str, int] = {
    "P0": 4,
    "P1": 24,
    "P2": 72,
    "P3": 168,
    "P4": 336,
}

_DEFAULT_SLA_HOURS = 168  # fallback for unknown severity


def _period_to_days(period: str) -> int:
    mapping = {"7d": 7, "30d": 30, "90d": 90}
    return mapping.get(period, 30)


def _validate_period(period: str) -> str:
    if period not in _VALID_PERIODS:
        return "30d"
    return period


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class IssuesSummary(BaseModel):
    total: int
    open: int
    resolved_in_sla_pct: float
    avg_resolution_hours: float
    p0_count: int
    p1_count: int


class TenantIssueStat(BaseModel):
    tenant_name: str
    total: int
    open: int
    p0_count: int


class SeverityBreakdown(BaseModel):
    severity: str
    count: int
    pct: float


class SLAAdherenceData(BaseModel):
    adherence_pct: float
    target_pct: float
    resolved_in_sla: int
    resolved_out_sla: int
    total_resolved: int


class MTTREntry(BaseModel):
    severity: str
    avg_hours: float
    median_hours: float
    count: int


class TrendEntry(BaseModel):
    week: str
    p0: int
    p1: int
    p2: int
    p3: int
    p4: int
    total: int


class TopBug(BaseModel):
    id: str
    title: str
    report_count: int
    tenant_count: int
    status: str


class DuplicateCluster(BaseModel):
    cluster_id: str
    title: str
    affected_tenants: List[str]
    tenant_count: int
    total_reports: int
    first_report_id: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=IssuesSummary)
async def get_issues_summary(
    period: str = Query("30d"),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> IssuesSummary:
    period = _validate_period(period)
    days = _period_to_days(period)
    try:
        result = await db.execute(
            text(
                "SELECT "
                "  COUNT(*) AS total, "
                "  COUNT(*) FILTER (WHERE status = 'open') AS open_count, "
                "  COUNT(*) FILTER (WHERE severity = 'P0') AS p0_count, "
                "  COUNT(*) FILTER (WHERE severity = 'P1') AS p1_count, "
                "  COUNT(*) FILTER (WHERE status IN ('resolved','wont_fix')) AS resolved_count "
                "FROM issue_reports "
                "WHERE created_at >= NOW() - (:days * INTERVAL '1 day')"
            ),
            {"days": days},
        )
        row = result.fetchone()
        if not row:
            return IssuesSummary(total=0, open=0, resolved_in_sla_pct=0.0,
                                 avg_resolution_hours=0.0, p0_count=0, p1_count=0)
        total = row[0] or 0
        open_count = row[1] or 0
        p0_count = row[2] or 0
        p1_count = row[3] or 0
        resolved_count = row[4] or 0

        # Compute SLA adherence (resolved within threshold)
        sla_ok = 0
        if resolved_count > 0:
            sla_result = await db.execute(
                text(
                    "SELECT COUNT(*) FROM issue_reports "
                    "WHERE status IN ('resolved','wont_fix') "
                    "AND created_at >= NOW() - (:days * INTERVAL '1 day') "
                    "AND EXTRACT(EPOCH FROM (updated_at - created_at)) / 3600 <= "
                    "  CASE severity "
                    "    WHEN 'P0' THEN 4 WHEN 'P1' THEN 24 WHEN 'P2' THEN 72 "
                    "    WHEN 'P3' THEN 168 ELSE 336 END"
                ),
                {"days": days},
            )
            sla_row = sla_result.fetchone()
            sla_ok = sla_row[0] if sla_row else 0

        resolved_in_sla_pct = round((sla_ok / resolved_count * 100) if resolved_count else 0.0, 1)

        # Average resolution hours
        avg_result = await db.execute(
            text(
                "SELECT AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 3600) "
                "FROM issue_reports "
                "WHERE status IN ('resolved','wont_fix') "
                "AND created_at >= NOW() - (:days * INTERVAL '1 day')"
            ),
            {"days": days},
        )
        avg_row = avg_result.fetchone()
        avg_hours = round(float(avg_row[0] or 0.0), 1)

        return IssuesSummary(
            total=total,
            open=open_count,
            resolved_in_sla_pct=resolved_in_sla_pct,
            avg_resolution_hours=avg_hours,
            p0_count=p0_count,
            p1_count=p1_count,
        )
    except ProgrammingError:
        return IssuesSummary(total=0, open=0, resolved_in_sla_pct=0.0,
                             avg_resolution_hours=0.0, p0_count=0, p1_count=0)


@router.get("/by-tenant", response_model=List[TenantIssueStat])
async def get_issues_by_tenant(
    period: str = Query("30d"),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> List[TenantIssueStat]:
    period = _validate_period(period)
    days = _period_to_days(period)
    try:
        result = await db.execute(
            text(
                "SELECT t.name, "
                "  COUNT(ir.id) AS total, "
                "  COUNT(ir.id) FILTER (WHERE ir.status = 'open') AS open_count, "
                "  COUNT(ir.id) FILTER (WHERE ir.severity = 'P0') AS p0_count "
                "FROM issue_reports ir "
                "JOIN tenants t ON t.id = ir.tenant_id "
                "WHERE ir.created_at >= NOW() - (:days * INTERVAL '1 day') "
                "GROUP BY t.name "
                "ORDER BY total DESC "
                "LIMIT 20"
            ),
            {"days": days},
        )
        rows = result.fetchall()
        return [
            TenantIssueStat(
                tenant_name=r[0],
                total=r[1] or 0,
                open=r[2] or 0,
                p0_count=r[3] or 0,
            )
            for r in rows
        ]
    except ProgrammingError:
        return []


@router.get("/by-severity", response_model=List[SeverityBreakdown])
async def get_issues_by_severity(
    period: str = Query("30d"),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> List[SeverityBreakdown]:
    period = _validate_period(period)
    days = _period_to_days(period)
    try:
        result = await db.execute(
            text(
                "SELECT severity, COUNT(*) AS cnt "
                "FROM issue_reports "
                "WHERE created_at >= NOW() - (:days * INTERVAL '1 day') "
                "AND severity IS NOT NULL "
                "GROUP BY severity "
                "ORDER BY cnt DESC"
            ),
            {"days": days},
        )
        rows = result.fetchall()
        total = sum(r[1] for r in rows) or 1
        return [
            SeverityBreakdown(
                severity=r[0],
                count=r[1] or 0,
                pct=round(r[1] / total * 100, 1),
            )
            for r in rows
        ]
    except ProgrammingError:
        return []


@router.get("/sla", response_model=SLAAdherenceData)
async def get_sla_adherence(
    period: str = Query("30d"),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> SLAAdherenceData:
    period = _validate_period(period)
    days = _period_to_days(period)
    try:
        result = await db.execute(
            text(
                "SELECT "
                "  COUNT(*) AS total_resolved, "
                "  COUNT(*) FILTER ("
                "    WHERE EXTRACT(EPOCH FROM (updated_at - created_at)) / 3600 <= "
                "    CASE severity "
                "      WHEN 'P0' THEN 4 WHEN 'P1' THEN 24 WHEN 'P2' THEN 72 "
                "      WHEN 'P3' THEN 168 ELSE 336 END"
                "  ) AS resolved_in_sla "
                "FROM issue_reports "
                "WHERE status IN ('resolved','wont_fix') "
                "AND created_at >= NOW() - (:days * INTERVAL '1 day')"
            ),
            {"days": days},
        )
        row = result.fetchone()
        total_resolved = row[0] if row else 0
        resolved_in_sla = row[1] if row else 0
        resolved_out_sla = (total_resolved or 0) - (resolved_in_sla or 0)
        adherence_pct = round(
            (resolved_in_sla / total_resolved * 100) if total_resolved else 0.0, 1
        )
        return SLAAdherenceData(
            adherence_pct=adherence_pct,
            target_pct=95.0,
            resolved_in_sla=resolved_in_sla or 0,
            resolved_out_sla=max(resolved_out_sla, 0),
            total_resolved=total_resolved or 0,
        )
    except ProgrammingError:
        return SLAAdherenceData(adherence_pct=0.0, target_pct=95.0,
                                resolved_in_sla=0, resolved_out_sla=0, total_resolved=0)


@router.get("/mttr", response_model=List[MTTREntry])
async def get_mttr(
    period: str = Query("30d"),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> List[MTTREntry]:
    period = _validate_period(period)
    days = _period_to_days(period)
    try:
        result = await db.execute(
            text(
                "SELECT severity, "
                "  AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 3600) AS avg_h, "
                "  PERCENTILE_CONT(0.5) WITHIN GROUP "
                "    (ORDER BY EXTRACT(EPOCH FROM (updated_at - created_at)) / 3600) AS median_h, "
                "  COUNT(*) AS cnt "
                "FROM issue_reports "
                "WHERE status IN ('resolved','wont_fix') "
                "AND created_at >= NOW() - (:days * INTERVAL '1 day') "
                "AND severity IS NOT NULL "
                "GROUP BY severity "
                "ORDER BY severity"
            ),
            {"days": days},
        )
        rows = result.fetchall()
        return [
            MTTREntry(
                severity=r[0],
                avg_hours=round(float(r[1] or 0.0), 1),
                median_hours=round(float(r[2] or 0.0), 1),
                count=r[3] or 0,
            )
            for r in rows
        ]
    except ProgrammingError:
        return []


@router.get("/trend", response_model=List[TrendEntry])
async def get_issue_trend(
    period: str = Query("30d"),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> List[TrendEntry]:
    period = _validate_period(period)
    days = _period_to_days(period)
    try:
        result = await db.execute(
            text(
                "SELECT "
                "  DATE_TRUNC('week', created_at)::DATE::TEXT AS week, "
                "  COUNT(*) FILTER (WHERE severity = 'P0') AS p0, "
                "  COUNT(*) FILTER (WHERE severity = 'P1') AS p1, "
                "  COUNT(*) FILTER (WHERE severity = 'P2') AS p2, "
                "  COUNT(*) FILTER (WHERE severity = 'P3') AS p3, "
                "  COUNT(*) FILTER (WHERE severity = 'P4') AS p4, "
                "  COUNT(*) AS total "
                "FROM issue_reports "
                "WHERE created_at >= NOW() - (:days * INTERVAL '1 day') "
                "GROUP BY DATE_TRUNC('week', created_at) "
                "ORDER BY week ASC"
            ),
            {"days": days},
        )
        rows = result.fetchall()
        return [
            TrendEntry(
                week=r[0],
                p0=r[1] or 0,
                p1=r[2] or 0,
                p2=r[3] or 0,
                p3=r[4] or 0,
                p4=r[5] or 0,
                total=r[6] or 0,
            )
            for r in rows
        ]
    except ProgrammingError:
        return []


@router.get("/top-bugs", response_model=List[TopBug])
async def get_top_bugs(
    period: str = Query("30d"),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> List[TopBug]:
    period = _validate_period(period)
    days = _period_to_days(period)
    try:
        result = await db.execute(
            text(
                "SELECT "
                "  MIN(id)::TEXT AS first_id, "
                "  issue_type AS title, "
                "  COUNT(*) AS report_count, "
                "  COUNT(DISTINCT tenant_id) AS tenant_count, "
                "  MAX(status) AS status "
                "FROM issue_reports "
                "WHERE created_at >= NOW() - (:days * INTERVAL '1 day') "
                "GROUP BY issue_type, severity "
                "ORDER BY report_count DESC, tenant_count DESC "
                "LIMIT 10"
            ),
            {"days": days},
        )
        rows = result.fetchall()
        return [
            TopBug(
                id=r[0] or "",
                title=r[1] or "",
                report_count=int(r[2] or 1),
                tenant_count=int(r[3] or 1),
                status=r[4] or "open",
            )
            for r in rows
        ]
    except ProgrammingError:
        return []


@router.get("/duplicates", response_model=List[DuplicateCluster])
async def get_duplicate_clusters(
    period: str = Query("30d"),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_async_session),
) -> List[DuplicateCluster]:
    period = _validate_period(period)
    days = _period_to_days(period)
    try:
        # Group by issue_type + severity as a proxy for duplicate detection
        result = await db.execute(
            text(
                "SELECT "
                "  issue_type || ':' || COALESCE(severity,'P3') AS cluster_id, "
                "  issue_type AS title, "
                "  ARRAY_AGG(DISTINCT t.name ORDER BY t.name) AS tenant_names, "
                "  COUNT(DISTINCT ir.tenant_id) AS tenant_count, "
                "  COUNT(ir.id) AS total_reports, "
                "  MIN(ir.id)::TEXT AS first_report_id "
                "FROM issue_reports ir "
                "JOIN tenants t ON t.id = ir.tenant_id "
                "WHERE ir.created_at >= NOW() - (:days * INTERVAL '1 day') "
                "GROUP BY issue_type, severity "
                "HAVING COUNT(DISTINCT ir.tenant_id) >= 2 "
                "ORDER BY total_reports DESC "
                "LIMIT 10"
            ),
            {"days": days},
        )
        rows = result.fetchall()
        return [
            DuplicateCluster(
                cluster_id=r[0],
                title=r[1] or "",
                affected_tenants=list(r[2]) if r[2] else [],
                tenant_count=r[3] or 0,
                total_reports=r[4] or 0,
                first_report_id=r[5] or "",
            )
            for r in rows
        ]
    except ProgrammingError:
        return []
