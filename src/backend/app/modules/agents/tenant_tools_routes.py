"""
Tenant Tools Routes — Agent Studio Phase 1.

Public endpoints (require_tenant_admin for reads):
  GET  /tools               — List platform-scoped tools (builtin + http_wrapper, scope='platform')
  GET  /tools/{tool_id}     — Platform tool detail + adoption count

Admin endpoints (require_tenant_admin):
  GET  /admin/mcp-servers              — List tenant's registered MCP servers
  POST /admin/mcp-servers              — Register a new MCP server (async verification)
  GET  /admin/mcp-servers/{server_id}  — Server detail + enumerated tools
  PUT  /admin/mcp-servers/{server_id}  — Update config (triggers re-verification)
  DELETE /admin/mcp-servers/{server_id} — Delete (warns if tools in use)
  POST /admin/mcp-servers/{server_id}/verify — Manual re-verification

  GET  /admin/tools          — List tenant-scoped tools (from verified MCP servers)
  GET  /admin/tools/{tool_id} — Tool detail + usage

MCP server registration is asynchronous:
  1. INSERT with status='pending', respond 202
  2. Background task: MCPClient.verify_and_enumerate()
  3. On success: UPDATE status='verified', INSERT tool records with scope=tenant_id
  4. On failure: UPDATE status='error', last_error=error_message
  Clients poll GET /admin/mcp-servers/{id} until status != 'pending'.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import List, Literal, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

tools_router = APIRouter(prefix="/tools", tags=["tools"])
admin_tools_router = APIRouter(prefix="/admin/tools", tags=["admin-tools"])
mcp_router = APIRouter(prefix="/admin/mcp-servers", tags=["admin-mcp"])

# ---------------------------------------------------------------------------
# Valid sort/filter allowlists
# ---------------------------------------------------------------------------
_VALID_TOOL_SORT = {"name", "created_at", "executor_type", "plan_required"}
_VALID_MCP_SORT = {"name", "created_at", "status"}
_VALID_EXECUTOR_TYPES = {"builtin", "http_wrapper", "mcp_sse"}
_VALID_MCP_STATUSES = {"pending", "verified", "error", "inactive"}


def _get_set_tenant_sql(tenant_id: str) -> tuple[str, dict]:
    return (
        "SELECT set_config('app.current_tenant_id', :tid, true)",
        {"tid": tenant_id},
    )


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class RegisterMCPServerRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    endpoint_url: str = Field(..., min_length=10, max_length=2048)
    transport: Literal["sse", "streamable_http"] = "sse"
    auth_type: Literal["none", "bearer", "api_key"] = "none"
    auth_token: Optional[str] = Field(None, max_length=2048)
    auth_header_name: Optional[str] = Field(None, max_length=128)


class UpdateMCPServerRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    endpoint_url: Optional[str] = Field(None, min_length=10, max_length=2048)
    transport: Optional[Literal["sse", "streamable_http"]] = None
    auth_type: Optional[Literal["none", "bearer", "api_key"]] = None
    auth_token: Optional[str] = Field(None, max_length=2048)
    auth_header_name: Optional[str] = Field(None, max_length=128)


# ---------------------------------------------------------------------------
# Background verification task
# ---------------------------------------------------------------------------

async def _run_mcp_verification(
    server_id: str,
    tenant_id: str,
    endpoint_url: str,
    transport: str,
    auth_config: dict,
    db_url: str,
) -> None:
    """
    Background task: verify MCP server and enumerate tools.

    Creates its own DB session (cannot share the request session which is closed).
    Credential values are never logged.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession as _AsyncSession
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(db_url, echo=False)
    async_session_factory = sessionmaker(engine, class_=_AsyncSession, expire_on_commit=False)

    async with async_session_factory() as session:
        try:
            from app.modules.agents.mcp_client import MCPClient
            client = MCPClient()
            result = await client.verify_and_enumerate(
                endpoint_url=endpoint_url,
                auth_config=auth_config,
            )

            if result.success:
                # Update server status to verified
                await session.execute(
                    text(
                        "UPDATE tenant_mcp_servers SET status = 'verified', last_error = NULL, "
                        "last_verified_at = now() WHERE id = :sid"
                    ),
                    {"sid": server_id},
                )

                # Delete existing tool records for this server (re-enumerate)
                await session.execute(
                    text("DELETE FROM tool_catalog WHERE source_mcp_server_id = :sid"),
                    {"sid": server_id},
                )

                # Insert enumerated tools into tool_catalog
                for tool_schema in result.tools:
                    tool_id = str(uuid.uuid4())
                    await session.execute(
                        text("""
                            INSERT INTO tool_catalog (
                                id, name, description, executor_type,
                                scope, endpoint_url, is_active,
                                input_schema, output_schema,
                                source_mcp_server_id, created_at, updated_at
                            ) VALUES (
                                :id, :name, :description, 'mcp_sse',
                                :scope, :endpoint_url, true,
                                CAST(:input_schema AS jsonb), CAST(:output_schema AS jsonb),
                                :server_id, now(), now()
                            )
                        """),
                        {
                            "id": tool_id,
                            "name": tool_schema.name[:255],
                            "description": tool_schema.description[:1000],
                            "scope": tenant_id,
                            "endpoint_url": endpoint_url,
                            "input_schema": json.dumps(tool_schema.input_schema),
                            "output_schema": json.dumps(tool_schema.output_schema),
                            "server_id": server_id,
                        },
                    )

                logger.info(
                    "mcp_server_verified",
                    server_id=server_id,
                    tenant_id=tenant_id,
                    tool_count=len(result.tools),
                )
            else:
                await session.execute(
                    text(
                        "UPDATE tenant_mcp_servers SET status = 'error', last_error = :err "
                        "WHERE id = :sid"
                    ),
                    {"sid": server_id, "err": (result.error_message or "Unknown error")[:500]},
                )
                logger.warning(
                    "mcp_server_verification_failed",
                    server_id=server_id,
                    tenant_id=tenant_id,
                    error_code=result.error_code,
                )

            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error(
                "mcp_verification_background_error",
                server_id=server_id,
                tenant_id=tenant_id,
                error=str(exc),
            )
            try:
                async with async_session_factory() as err_session:
                    await err_session.execute(
                        text(
                            "UPDATE tenant_mcp_servers SET status = 'error', last_error = :err "
                            "WHERE id = :sid"
                        ),
                        {"sid": server_id, "err": str(exc)[:500]},
                    )
                    await err_session.commit()
            except Exception:
                pass
        finally:
            await engine.dispose()


# ---------------------------------------------------------------------------
# Platform tools (public read)
# ---------------------------------------------------------------------------

@tools_router.get("")
async def list_platform_tools(
    executor_type: Optional[str] = Query(None),
    plan_required: Optional[str] = Query(None),
    q: Optional[str] = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("name"),
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """List platform-scoped tools available to all tenants."""
    if sort not in _VALID_TOOL_SORT:
        sort = "name"

    filters = ["tc.scope = 'platform'", "tc.is_active = true"]
    params: dict = {}

    if executor_type and executor_type in _VALID_EXECUTOR_TYPES:
        filters.append("tc.executor_type = :executor_type")
        params["executor_type"] = executor_type

    if plan_required:
        filters.append("tc.plan_required = :plan_required")
        params["plan_required"] = plan_required

    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append("(tc.name ILIKE :q OR tc.description ILIKE :q)")
        params["q"] = f"%{escaped}%"

    where_clause = " AND ".join(filters)
    params["limit"] = limit
    params["offset"] = offset

    sort_map = {
        "name": "tc.name",
        "created_at": "tc.created_at",
        "executor_type": "tc.executor_type",
        "plan_required": "tc.plan_required",
    }
    order_col = sort_map[sort]

    result = await db.execute(
        text(f"""
            SELECT tc.id, tc.name, tc.description, tc.executor_type,
                   tc.plan_required, tc.credential_source, tc.rate_limit_rpm,
                   tc.input_schema, tc.output_schema, tc.created_at
            FROM tool_catalog tc
            WHERE {where_clause}
            ORDER BY {order_col}
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.mappings().all()

    count_result = await db.execute(
        text(f"SELECT count(*) FROM tool_catalog tc WHERE {where_clause}"),
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    )
    total = count_result.scalar() or 0

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@tools_router.get("/{tool_id}")
async def get_platform_tool(
    tool_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Get platform tool detail."""
    result = await db.execute(
        text("""
            SELECT tc.id, tc.name, tc.description, tc.executor_type,
                   tc.plan_required, tc.credential_source, tc.credential_schema,
                   tc.rate_limit_rpm, tc.input_schema, tc.output_schema,
                   tc.capabilities, tc.created_at,
                   (
                       SELECT count(*) FROM agent_template_tools att
                       WHERE att.tool_id = tc.id
                   ) AS agent_usage_count,
                   (
                       SELECT count(*) FROM skill_tool_dependencies std
                       WHERE std.tool_id = tc.id
                   ) AS skill_usage_count
            FROM tool_catalog tc
            WHERE tc.id = :tid AND tc.scope = 'platform' AND tc.is_active = true
        """),
        {"tid": tool_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(404, detail="Tool not found")
    return dict(row)


# ---------------------------------------------------------------------------
# Tenant MCP server management
# ---------------------------------------------------------------------------

@mcp_router.get("")
async def list_mcp_servers(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """List tenant MCP servers."""
    tenant_id = current_user.tenant_id
    sql, rls_params = _get_set_tenant_sql(tenant_id)
    await db.execute(text(sql), rls_params)

    filters = ["tenant_id = :tenant_id"]
    params: dict = {"tenant_id": tenant_id}

    if status and status in _VALID_MCP_STATUSES:
        filters.append("status = :status")
        params["status"] = status

    where_clause = " AND ".join(filters)
    params["limit"] = limit
    params["offset"] = offset

    result = await db.execute(
        text(f"""
            SELECT id, name, description, endpoint_url, transport,
                   auth_type, status, last_error, last_verified_at, created_at,
                   (
                       SELECT count(*) FROM tool_catalog
                       WHERE source_mcp_server_id = tenant_mcp_servers.id AND is_active = true
                   ) AS tool_count
            FROM tenant_mcp_servers
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.mappings().all()

    count_result = await db.execute(
        text(f"SELECT count(*) FROM tenant_mcp_servers WHERE {where_clause}"),
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    )
    total = count_result.scalar() or 0

    return {"items": [dict(r) for r in rows], "total": total}


@mcp_router.post("", status_code=202)
async def register_mcp_server(
    body: RegisterMCPServerRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """
    Register a new MCP server. Responds 202 immediately.
    Verification runs in background. Poll GET /admin/mcp-servers/{id} for status.
    """
    import os

    tenant_id = current_user.tenant_id
    server_id = str(uuid.uuid4())

    # Validate URL scheme
    endpoint_url = str(body.endpoint_url)
    if not (endpoint_url.startswith("https://") or endpoint_url.startswith("http://")):
        raise HTTPException(422, detail="endpoint_url must use https:// or http:// scheme")

    # Build auth_config for vault storage (never store token in DB)
    auth_config: dict = {"type": body.auth_type}
    vault_path_ref: Optional[str] = None

    if body.auth_token and body.auth_type != "none":
        # Store auth token in vault
        try:
            from app.modules.agents.credential_manager import CredentialManager
            mgr = CredentialManager()
            mgr.store_credential(
                tenant_id=tenant_id,
                agent_id=f"mcp-server-{server_id}",
                credential_key="auth_token",
                credential_value=body.auth_token,
            )
            vault_path_ref = f"{tenant_id}/agents/mcp-server-{server_id}"
        except Exception as exc:
            logger.warning(
                "mcp_server_vault_store_failed",
                server_id=server_id,
                tenant_id=tenant_id,
                error=str(exc),
            )
            # Continue without credential storage — server will have auth errors

    if body.auth_header_name:
        auth_config["header_name"] = body.auth_header_name

    sql, rls_params = _get_set_tenant_sql(tenant_id)
    await db.execute(text(sql), rls_params)

    await db.execute(
        text("""
            INSERT INTO tenant_mcp_servers (
                id, tenant_id, name, description, endpoint_url,
                transport, auth_type, auth_config, status, created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :name, :description, :endpoint_url,
                :transport, :auth_type, CAST(:auth_config AS jsonb),
                'pending', now(), now()
            )
        """),
        {
            "id": server_id,
            "tenant_id": tenant_id,
            "name": body.name,
            "description": body.description or "",
            "endpoint_url": endpoint_url,
            "transport": body.transport,
            "auth_type": body.auth_type,
            "auth_config": json.dumps(auth_config),
        },
    )
    await db.commit()

    # Build runtime auth_config for background task (resolves from vault)
    runtime_auth: dict = {}
    if body.auth_token and body.auth_type != "none":
        runtime_auth = {"credentials": {"auth_token": body.auth_token}}
        if body.auth_header_name:
            runtime_auth["header_map"] = {body.auth_header_name: "auth_token"}

    db_url = os.environ.get("DATABASE_URL", "")
    background_tasks.add_task(
        _run_mcp_verification,
        server_id=server_id,
        tenant_id=tenant_id,
        endpoint_url=endpoint_url,
        transport=body.transport,
        auth_config=runtime_auth,
        db_url=db_url,
    )

    logger.info(
        "mcp_server_registered",
        server_id=server_id,
        tenant_id=tenant_id,
        endpoint_url=endpoint_url,
    )
    return {"id": server_id, "status": "pending"}


@mcp_router.get("/{server_id}")
async def get_mcp_server(
    server_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Get MCP server detail including enumerated tools."""
    tenant_id = current_user.tenant_id
    sql, rls_params = _get_set_tenant_sql(tenant_id)
    await db.execute(text(sql), rls_params)

    result = await db.execute(
        text("""
            SELECT id, name, description, endpoint_url, transport,
                   auth_type, status, last_error, last_verified_at, created_at, updated_at
            FROM tenant_mcp_servers
            WHERE id = :sid AND tenant_id = :tid
        """),
        {"sid": server_id, "tid": tenant_id},
    )
    server = result.mappings().first()
    if server is None:
        raise HTTPException(404, detail="MCP server not found")

    tools_result = await db.execute(
        text("""
            SELECT id, name, description, input_schema, output_schema, is_active
            FROM tool_catalog
            WHERE source_mcp_server_id = :sid AND scope = :scope
            ORDER BY name
        """),
        {"sid": server_id, "scope": tenant_id},
    )
    tools_rows = tools_result.mappings().all()

    return {
        **dict(server),
        "tools": [dict(t) for t in tools_rows],
    }


@mcp_router.put("/{server_id}")
async def update_mcp_server(
    server_id: str,
    body: UpdateMCPServerRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Update MCP server config. Triggers re-verification if endpoint or auth changes."""
    import os

    tenant_id = current_user.tenant_id
    sql, rls_params = _get_set_tenant_sql(tenant_id)
    await db.execute(text(sql), rls_params)

    # Fetch existing
    result = await db.execute(
        text("SELECT * FROM tenant_mcp_servers WHERE id = :sid AND tenant_id = :tid"),
        {"sid": server_id, "tid": tenant_id},
    )
    server = result.mappings().first()
    if server is None:
        raise HTTPException(404, detail="MCP server not found")

    # Build update fragments (allowlisted columns only)
    _UPDATE_ALLOWLIST = {"name", "description", "endpoint_url", "transport", "auth_type"}
    updates: dict = {"sid": server_id}
    set_parts: list[str] = ["updated_at = now()"]

    update_dict = body.model_dump(exclude_none=True)
    endpoint_changed = "endpoint_url" in update_dict or "transport" in update_dict
    auth_changed = "auth_type" in update_dict or "auth_token" in update_dict

    for col in _UPDATE_ALLOWLIST:
        if col in update_dict:
            set_parts.append(f"{col} = :{col}")
            updates[col] = update_dict[col]

    if endpoint_changed or auth_changed:
        set_parts.append("status = 'pending'")
        set_parts.append("last_error = NULL")

    if not set_parts:
        raise HTTPException(422, detail="No valid fields to update")

    await db.execute(
        text(f"UPDATE tenant_mcp_servers SET {', '.join(set_parts)} WHERE id = :sid"),
        updates,
    )
    await db.commit()

    # Handle new auth token
    new_endpoint = update_dict.get("endpoint_url", str(server["endpoint_url"]))
    new_transport = update_dict.get("transport", server["transport"])
    runtime_auth: dict = {}

    if body.auth_token and body.auth_type and body.auth_type != "none":
        try:
            from app.modules.agents.credential_manager import CredentialManager
            mgr = CredentialManager()
            mgr.store_credential(
                tenant_id=tenant_id,
                agent_id=f"mcp-server-{server_id}",
                credential_key="auth_token",
                credential_value=body.auth_token,
            )
            runtime_auth = {"credentials": {"auth_token": body.auth_token}}
            if body.auth_header_name:
                runtime_auth["header_map"] = {body.auth_header_name: "auth_token"}
        except Exception as exc:
            logger.warning("mcp_server_cred_update_failed", server_id=server_id, error=str(exc))

    if endpoint_changed or auth_changed:
        db_url = os.environ.get("DATABASE_URL", "")
        background_tasks.add_task(
            _run_mcp_verification,
            server_id=server_id,
            tenant_id=tenant_id,
            endpoint_url=new_endpoint,
            transport=new_transport,
            auth_config=runtime_auth,
            db_url=db_url,
        )

    return {"id": server_id, "status": "pending" if (endpoint_changed or auth_changed) else server["status"]}


@mcp_router.delete("/{server_id}", status_code=204)
async def delete_mcp_server(
    server_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> None:
    """Delete an MCP server. Warns via 409 if tools are in active use by agents/skills."""
    tenant_id = current_user.tenant_id
    sql, rls_params = _get_set_tenant_sql(tenant_id)
    await db.execute(text(sql), rls_params)

    result = await db.execute(
        text("SELECT id FROM tenant_mcp_servers WHERE id = :sid AND tenant_id = :tid"),
        {"sid": server_id, "tid": tenant_id},
    )
    if result.first() is None:
        raise HTTPException(404, detail="MCP server not found")

    # Check if any tools from this server are in use
    usage_result = await db.execute(
        text("""
            SELECT count(*) FROM (
                SELECT att.tool_id FROM agent_template_tools att
                JOIN tool_catalog tc ON tc.id = att.tool_id
                WHERE tc.source_mcp_server_id = :sid
                UNION ALL
                SELECT std.tool_id FROM skill_tool_dependencies std
                JOIN tool_catalog tc ON tc.id = std.tool_id
                WHERE tc.source_mcp_server_id = :sid
            ) AS usages
        """),
        {"sid": server_id},
    )
    usage_count = usage_result.scalar() or 0
    if usage_count > 0:
        raise HTTPException(
            409,
            detail=f"Cannot delete MCP server: {usage_count} agent or skill reference(s) still use its tools. Remove those references first.",
        )

    # Delete enumerated tools
    await db.execute(
        text("DELETE FROM tool_catalog WHERE source_mcp_server_id = :sid"),
        {"sid": server_id},
    )

    await db.execute(
        text("DELETE FROM tenant_mcp_servers WHERE id = :sid AND tenant_id = :tid"),
        {"sid": server_id, "tid": tenant_id},
    )

    # Clean up vault credentials
    try:
        from app.modules.agents.credential_manager import CredentialManager
        mgr = CredentialManager()
        mgr.delete_credentials(
            tenant_id=tenant_id,
            agent_id=f"mcp-server-{server_id}",
        )
    except Exception as exc:
        logger.warning("mcp_server_cred_cleanup_failed", server_id=server_id, error=str(exc))

    await db.commit()


@mcp_router.post("/{server_id}/verify", status_code=202)
async def reverify_mcp_server(
    server_id: str,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Manually trigger re-verification of an MCP server."""
    import os

    tenant_id = current_user.tenant_id
    sql, rls_params = _get_set_tenant_sql(tenant_id)
    await db.execute(text(sql), rls_params)

    result = await db.execute(
        text("""
            SELECT id, endpoint_url, transport, auth_type, auth_config
            FROM tenant_mcp_servers
            WHERE id = :sid AND tenant_id = :tid
        """),
        {"sid": server_id, "tid": tenant_id},
    )
    server = result.mappings().first()
    if server is None:
        raise HTTPException(404, detail="MCP server not found")

    await db.execute(
        text(
            "UPDATE tenant_mcp_servers SET status = 'pending', last_error = NULL, "
            "updated_at = now() WHERE id = :sid"
        ),
        {"sid": server_id},
    )
    await db.commit()

    # Resolve runtime auth from vault
    runtime_auth: dict = {}
    if server["auth_type"] != "none":
        try:
            from app.modules.agents.credential_manager import CredentialManager
            mgr = CredentialManager()
            creds = mgr.get_credentials(
                tenant_id=tenant_id,
                agent_id=f"mcp-server-{server_id}",
            )
            if creds:
                runtime_auth = {"credentials": creds}
                auth_config_db = server["auth_config"] or {}
                if isinstance(auth_config_db, str):
                    auth_config_db = json.loads(auth_config_db)
                header_name = auth_config_db.get("header_name")
                if header_name:
                    runtime_auth["header_map"] = {header_name: "auth_token"}
        except Exception as exc:
            logger.warning("mcp_reverify_cred_load_failed", server_id=server_id, error=str(exc))

    db_url = os.environ.get("DATABASE_URL", "")
    background_tasks.add_task(
        _run_mcp_verification,
        server_id=server_id,
        tenant_id=tenant_id,
        endpoint_url=str(server["endpoint_url"]),
        transport=server["transport"],
        auth_config=runtime_auth,
        db_url=db_url,
    )

    return {"id": server_id, "status": "pending"}


# ---------------------------------------------------------------------------
# Tenant tools (from verified MCP servers)
# ---------------------------------------------------------------------------

@admin_tools_router.get("")
async def list_tenant_tools(
    q: Optional[str] = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """List tenant-scoped tools (enumerated from verified MCP servers)."""
    tenant_id = current_user.tenant_id
    sql, rls_params = _get_set_tenant_sql(tenant_id)
    await db.execute(text(sql), rls_params)

    filters = ["tc.scope = :scope", "tc.is_active = true"]
    params: dict = {"scope": tenant_id}

    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append("(tc.name ILIKE :q OR tc.description ILIKE :q)")
        params["q"] = f"%{escaped}%"

    where_clause = " AND ".join(filters)
    params["limit"] = limit
    params["offset"] = offset

    result = await db.execute(
        text(f"""
            SELECT tc.id, tc.name, tc.description, tc.executor_type,
                   tc.input_schema, tc.output_schema, tc.is_active,
                   tc.source_mcp_server_id,
                   ms.name AS server_name, ms.status AS server_status,
                   tc.created_at,
                   (
                       SELECT count(*) FROM agent_template_tools att WHERE att.tool_id = tc.id
                   ) AS agent_usage_count,
                   (
                       SELECT count(*) FROM skill_tool_dependencies std WHERE std.tool_id = tc.id
                   ) AS skill_usage_count
            FROM tool_catalog tc
            LEFT JOIN tenant_mcp_servers ms ON ms.id = tc.source_mcp_server_id
            WHERE {where_clause}
            ORDER BY tc.name
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.mappings().all()

    count_result = await db.execute(
        text(f"SELECT count(*) FROM tool_catalog tc WHERE {where_clause}"),
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    )
    total = count_result.scalar() or 0

    return {"items": [dict(r) for r in rows], "total": total}


@admin_tools_router.get("/{tool_id}")
async def get_tenant_tool(
    tool_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Get tenant tool detail + usage."""
    tenant_id = current_user.tenant_id
    sql, rls_params = _get_set_tenant_sql(tenant_id)
    await db.execute(text(sql), rls_params)

    result = await db.execute(
        text("""
            SELECT tc.id, tc.name, tc.description, tc.executor_type,
                   tc.input_schema, tc.output_schema, tc.is_active,
                   tc.source_mcp_server_id,
                   ms.name AS server_name, ms.status AS server_status,
                   tc.created_at, tc.updated_at,
                   (
                       SELECT count(*) FROM agent_template_tools att WHERE att.tool_id = tc.id
                   ) AS agent_usage_count,
                   (
                       SELECT count(*) FROM skill_tool_dependencies std WHERE std.tool_id = tc.id
                   ) AS skill_usage_count
            FROM tool_catalog tc
            LEFT JOIN tenant_mcp_servers ms ON ms.id = tc.source_mcp_server_id
            WHERE tc.id = :tid AND tc.scope = :scope AND tc.is_active = true
        """),
        {"tid": tool_id, "scope": tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(404, detail="Tool not found")

    return dict(row)
