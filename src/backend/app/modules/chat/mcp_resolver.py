"""
MCPToolResolver — Redis-cached MCP server configuration resolver.

Cache key: build_redis_key(tenant_id, "mcp_tool", tool_id)
TTL: 300 seconds
Cache None: json.dumps(None) written for non-existent tools (prevents repeated DB
    queries for tools that don't exist).

SSRF note: This module does not make outbound calls. RULE A2A-04 applies
only to the tool execution layer, not to tool configuration resolution.
"""
import json
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import build_redis_key

logger = structlog.get_logger()

# Cache TTL in seconds — 5 minutes
_MCP_TOOL_CACHE_TTL = 300


async def get_mcp_tool_config(
    tool_id: str,
    tenant_id: str,
    redis,
    db: AsyncSession,
) -> Optional[dict]:
    """
    Return MCP server config for the given tool_id scoped to tenant_id.

    Lookup order:
    1. Redis cache (key: mingai:{tenant_id}:mcp_tool:{tool_id}, TTL 300s)
    2. PostgreSQL — mcp_servers WHERE id = :tool_id AND tenant_id = :tenant_id
       AND status = 'active'

    On DB miss (tool not found or inactive), caches json.dumps(None) to
    prevent thundering-herd repeated DB queries for non-existent tools.

    Args:
        tool_id:   UUID string of the MCP server record.
        tenant_id: Tenant UUID string — enforces RLS-equivalent scoping.
        redis:     Async Redis client (decode_responses=True pool).
        db:        Active async SQLAlchemy session.

    Returns:
        Dict with id, name, endpoint, auth_type, auth_config keys, or None
        if the tool does not exist / is not active for this tenant.
    """
    cache_key = build_redis_key(tenant_id, "mcp_tool", tool_id)

    # --- Cache check (best-effort — Redis failure falls through to DB) ---
    try:
        cached = await redis.get(cache_key)
        if cached is not None:
            logger.debug(
                "mcp_tool_config_cache_hit",
                tool_id=tool_id,
                tenant_id=tenant_id,
            )
            return json.loads(cached)
    except Exception as redis_exc:
        logger.warning(
            "mcp_tool_config_cache_read_failed",
            tool_id=tool_id,
            tenant_id=tenant_id,
            error=str(redis_exc),
        )

    # --- DB query (fail-safe — errors return None, never raise) ---
    try:
        result = await db.execute(
            text(
                "SELECT id, name, endpoint, auth_type, auth_config "
                "FROM mcp_servers "
                "WHERE id = :tool_id "
                "  AND tenant_id = :tenant_id "
                "  AND status = 'active'"
            ),
            {"tool_id": tool_id, "tenant_id": tenant_id},
        )
        row = result.fetchone()
    except Exception as db_exc:
        logger.warning(
            "mcp_tool_config_db_query_failed",
            tool_id=tool_id,
            tenant_id=tenant_id,
            error=str(db_exc),
        )
        return None

    config_dict: Optional[dict] = None
    if row is not None:
        config_dict = {
            "id": str(row[0]),
            "name": row[1],
            "endpoint": row[2],
            "auth_type": row[3],
            "auth_config": row[4],
        }

    # --- Populate cache (best-effort — Redis failure discarded, result still returned) ---
    try:
        await redis.setex(cache_key, _MCP_TOOL_CACHE_TTL, json.dumps(config_dict))
    except Exception as cache_write_exc:
        logger.warning(
            "mcp_tool_config_cache_write_failed",
            tool_id=tool_id,
            tenant_id=tenant_id,
            error=str(cache_write_exc),
        )

    logger.debug(
        "mcp_tool_config_cache_miss",
        tool_id=tool_id,
        tenant_id=tenant_id,
        found=config_dict is not None,
    )

    return config_dict


async def invalidate_mcp_tool_cache(
    tenant_id: str,
    tool_id: str,
    redis,
) -> None:
    """
    Immediately delete the Redis cache entry for the given MCP tool.

    Called after create, delete, or status-change operations on the
    mcp_servers table so subsequent lookups always reflect the DB state.

    Args:
        tenant_id: Tenant UUID string.
        tool_id:   UUID string of the MCP server record.
        redis:     Async Redis client.
    """
    cache_key = build_redis_key(tenant_id, "mcp_tool", tool_id)
    await redis.delete(cache_key)
    logger.debug(
        "mcp_tool_cache_invalidated",
        tool_id=tool_id,
        tenant_id=tenant_id,
    )
