"""
ToolResolver — resolves agent tool_ids to full tool configurations.

Single UNION ALL query across tool_catalog and mcp_servers.
One DB round-trip regardless of tool count.

SSRF note: This module does not make outbound calls. RULE A2A-04 applies
only to the tool execution layer, not to tool configuration resolution.

Column mapping (from migrations):
  tool_catalog: id, name, mcp_endpoint, auth_type, health_status
  mcp_servers:  id, name, endpoint, auth_type, status, tenant_id

v048 RLS dependency: tool_catalog's RLS policy (v048) must be deployed
for degraded tools to appear in results. Before v048, only healthy tools
are returned from tool_catalog.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


@dataclass
class ResolvedTool:
    tool_id: str
    name: str
    source: str  # "tool_catalog" | "mcp_server"
    endpoint: Optional[str]
    auth_type: Optional[str]
    status: str  # "healthy" | "degraded" | "active"


class ToolResolver:
    def __init__(self, db: AsyncSession, tenant_id: str):
        self._db = db
        self._tenant_id = tenant_id

    async def resolve(self, tool_ids: list[str]) -> list[ResolvedTool]:
        """
        Resolve tool_ids to ResolvedTool configs via a single UNION ALL query.

        Unknown tool IDs are logged and skipped — never raises.
        Returns empty list if tool_ids is empty or all IDs are unknown.
        """
        if not tool_ids:
            return []

        # UNION ALL: tool_catalog (global platform tools) + mcp_servers (tenant-scoped).
        # tool_catalog uses mcp_endpoint column (v026 schema).
        # mcp_servers uses endpoint column (v036 schema).
        # health_status != 'inactive' — v026 uses 'unavailable', not 'inactive',
        # but we filter positively: only healthy/degraded visible after v048 RLS.
        # mcp_servers.status = 'active' filters out inactive tenant servers.
        query = sa.text("""
            SELECT
                id::text           AS tool_id,
                name               AS name,
                'tool_catalog'     AS source,
                mcp_endpoint       AS endpoint,
                auth_type          AS auth_type,
                health_status      AS status
            FROM tool_catalog
            WHERE id::text = ANY(:tool_ids)
              AND health_status != 'unavailable'
            UNION ALL
            SELECT
                id::text           AS tool_id,
                name               AS name,
                'mcp_server'       AS source,
                endpoint           AS endpoint,
                auth_type          AS auth_type,
                'active'           AS status
            FROM mcp_servers
            WHERE id::text = ANY(:tool_ids)
              AND status = 'active'
              AND tenant_id = :tenant_id
        """)

        try:
            result = await self._db.execute(
                query,
                {"tool_ids": list(tool_ids), "tenant_id": self._tenant_id},
            )
            rows = result.fetchall()
        except Exception as e:
            logger.error(
                "tool_resolver_db_query_failed",
                error=str(e),
                exc_info=True,
            )
            return []

        resolved_ids: set[str] = set()
        resolved: list[ResolvedTool] = []
        for row in rows:
            resolved.append(
                ResolvedTool(
                    tool_id=row.tool_id,
                    name=row.name,
                    source=row.source,
                    endpoint=row.endpoint,
                    auth_type=row.auth_type,
                    status=row.status,
                )
            )
            resolved_ids.add(row.tool_id)

        # Log missing tool IDs (unknown or filtered-out by RLS / status)
        missing = [tid for tid in tool_ids if tid not in resolved_ids]
        if missing:
            logger.warning(
                "tool_resolution_missing",
                count=len(missing),
                tool_ids=missing,
            )

        return resolved
