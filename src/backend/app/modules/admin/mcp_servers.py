"""
MCP server registry API (DEF-005).

Endpoints (require tenant_admin):
    POST   /admin/mcp-servers          — register a new MCP server config
    GET    /admin/mcp-servers          — list all MCP servers for tenant
    DELETE /admin/mcp-servers/{id}     — remove an MCP server config

Security: auth_config stores ONLY a vault reference URI — never plaintext
credentials. The auth_config JSON is stored opaquely; the application never
interprets or logs the contents.
"""
import json
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin-mcp-servers"])

_VALID_AUTH_TYPES = frozenset({"none", "api_key", "oauth2"})
_VALID_STATUSES = frozenset({"active", "inactive"})


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateMCPServerRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    endpoint: str = Field(..., min_length=1, max_length=2048)
    auth_type: str = Field("none", description="none | api_key | oauth2")
    auth_config: Optional[dict] = Field(
        None,
        description="Vault reference config (only when auth_type != none). "
        "Never store plaintext credentials here.",
    )

    @field_validator("auth_type")
    @classmethod
    def validate_auth_type(cls, v: str) -> str:
        if v not in _VALID_AUTH_TYPES:
            raise ValueError(f"auth_type must be one of: {sorted(_VALID_AUTH_TYPES)}")
        return v

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, v: str) -> str:
        if not (
            v.startswith("http://")
            or v.startswith("https://")
            or v.startswith("mcp://")
        ):
            raise ValueError("endpoint must start with http://, https://, or mcp://")
        return v

    @model_validator(mode="after")
    def no_http_with_auth(self) -> "CreateMCPServerRequest":
        if self.auth_type != "none" and self.endpoint.startswith("http://"):
            raise ValueError(
                "endpoint must use https:// or mcp:// when auth_type is not 'none' "
                "— sending credentials over plain HTTP is not permitted"
            )
        return self


class MCPServerResponse(BaseModel):
    id: str
    name: str
    endpoint: str
    auth_type: str
    status: str
    last_verified_at: Optional[str] = None
    created_at: str


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post(
    "/mcp-servers",
    response_model=MCPServerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_mcp_server(
    body: CreateMCPServerRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> MCPServerResponse:
    """Register a new MCP server config for the tenant.

    auth_config must only contain a vault reference URI — never plaintext API keys.
    """
    # auth_type != none requires auth_config (vault ref)
    if body.auth_type != "none" and not body.auth_config:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="auth_config is required when auth_type is not 'none'",
        )

    server_id = str(uuid.uuid4())
    auth_config_json = json.dumps(body.auth_config) if body.auth_config else None

    try:
        result = await db.execute(
            text(
                "INSERT INTO mcp_servers "
                "  (id, tenant_id, name, endpoint, auth_type, auth_config) "
                "VALUES (:id, :tid, :name, :endpoint, :auth_type, "
                "        CAST(:auth_config AS jsonb)) "
                "RETURNING id, name, endpoint, auth_type, status, "
                "          last_verified_at, created_at"
            ),
            {
                "id": server_id,
                "tid": current_user.tenant_id,
                "name": body.name,
                "endpoint": body.endpoint,
                "auth_type": body.auth_type,
                "auth_config": auth_config_json,
            },
        )
    except Exception as exc:
        if "mcp_servers_tenant_name_unique" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An MCP server named {body.name!r} already exists for this tenant",
            )
        raise

    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to create MCP server")

    await db.commit()

    logger.info(
        "mcp_server_created",
        server_id=server_id,
        tenant_id=current_user.tenant_id,
        name=body.name,
        auth_type=body.auth_type,
    )

    return MCPServerResponse(
        id=str(row[0]),
        name=row[1],
        endpoint=row[2],
        auth_type=row[3],
        status=row[4],
        last_verified_at=row[5].isoformat() if row[5] else None,
        created_at=row[6].isoformat(),
    )


@router.get("/mcp-servers", response_model=list[MCPServerResponse])
async def list_mcp_servers(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> list[MCPServerResponse]:
    """List all MCP server configs for the tenant."""
    result = await db.execute(
        text(
            "SELECT id, name, endpoint, auth_type, status, "
            "       last_verified_at, created_at "
            "FROM mcp_servers "
            "WHERE tenant_id = :tid "
            "ORDER BY created_at DESC"
        ),
        {"tid": current_user.tenant_id},
    )
    rows = result.fetchall()
    return [
        MCPServerResponse(
            id=str(row[0]),
            name=row[1],
            endpoint=row[2],
            auth_type=row[3],
            status=row[4],
            last_verified_at=row[5].isoformat() if row[5] else None,
            created_at=row[6].isoformat(),
        )
        for row in rows
    ]


@router.delete(
    "/mcp-servers/{server_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_mcp_server(
    server_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> None:
    """Delete an MCP server config."""
    try:
        uuid.UUID(server_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="server_id must be a valid UUID")

    result = await db.execute(
        text("DELETE FROM mcp_servers " "WHERE id = :id AND tenant_id = :tid"),
        {"id": server_id, "tid": current_user.tenant_id},
    )
    if (result.rowcount or 0) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MCP server not found",
        )

    await db.commit()

    logger.info(
        "mcp_server_deleted",
        server_id=server_id,
        tenant_id=current_user.tenant_id,
    )
