"""FastAPI router implementing the MCP protocol for the embedded Pitchbook server.

Endpoints
---------
GET  /mcp/pitchbook/health         — health check (no auth)
GET  /mcp/pitchbook/tools/list     — list available tools (no auth)
POST /mcp/pitchbook/tools/call     — execute a tool (requires Pitchbook API key)

Authentication for /tools/call
-------------------------------
The caller must supply a Pitchbook API key in one of two ways:
  - Header  X-Api-Key: <key>
  - Header  Authorization: Bearer <key>

If neither is present a 401 is returned immediately.
"""

from __future__ import annotations

import re
import time
from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.modules.mcp_servers.pitchbook.client import (
    PitchbookAPIError,
    PitchbookAuthError,
    PitchbookClient,
    PitchbookNotFoundError,
    PitchbookRateLimitError,
)
from app.modules.mcp_servers.pitchbook.tools import (
    PITCHBOOK_TOOLS,
    VALID_ENUM_VALUES,
    get_tool,
    normalize_enum_value,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/mcp/pitchbook", tags=["mcp-pitchbook"])

_SERVER_NAME = "Pitchbook MCP"
_SERVER_VERSION = "1.0.0"

# Parameters whose values should go through enum normalisation
_ENUM_PARAMS = set(VALID_ENUM_VALUES.keys())

# Regex that matches {placeholder} patterns in endpoint strings
_PATH_PARAM_RE = re.compile(r"\{(\w+)\}")

# Entity types used for name→pbId resolution
_ENTITY_TYPE_MAP = {
    "company_name": "COMPANY",
    "investor_name": "INVESTOR",
    "fund_name": "FUND",
    "lp_name": "LIMITED_PARTNER",
    "person_name": "PERSON",
}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ToolCallRequest(BaseModel):
    tool: str
    parameters: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_api_key(request: Request) -> str | None:
    """Extract the Pitchbook API key from X-Api-Key or Authorization header."""
    key = request.headers.get("x-api-key") or request.headers.get("X-Api-Key")
    if key:
        return key
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _build_path(endpoint: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Substitute path parameters in an endpoint template.

    Returns (resolved_path, remaining_query_params).
    """
    path_params = _PATH_PARAM_RE.findall(endpoint)
    remaining = dict(params)
    path = endpoint
    for placeholder in path_params:
        value = remaining.pop(placeholder, None)
        if value is None:
            raise ValueError(f"Missing required path parameter: {placeholder}")
        path = path.replace(f"{{{placeholder}}}", str(value))
    return path, remaining


def _normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Normalise enum values and strip None/empty string params."""
    result: dict[str, Any] = {}
    for k, v in params.items():
        if v is None or v == "":
            continue
        if isinstance(v, str) and k in _ENUM_PARAMS:
            v = normalize_enum_value(k, v)
        result[k] = v
    return result


async def _resolve_entity_name(client: PitchbookClient, params: dict[str, Any]) -> dict[str, Any]:
    """If params contain a name key but not pbId, resolve the name to a pbId.

    Modifies and returns the params dict.
    """
    for name_key, entity_type in _ENTITY_TYPE_MAP.items():
        if name_key in params and "pbId" not in params:
            name_value = params.pop(name_key)
            search_result = await client.get(
                "/entities/search",
                params={"name": name_value, "entityType": entity_type},
            )
            entities = search_result.get("entities") or search_result.get("data") or []
            if not entities:
                raise PitchbookNotFoundError(
                    f"No entity found for {entity_type} named '{name_value}'",
                    status_code=404,
                )
            params["pbId"] = entities[0].get("pbId") or entities[0].get("id")
    return params


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health")
async def health() -> dict[str, Any]:
    """Simple health check — no API key required."""
    return {
        "status": "ok",
        "server": _SERVER_NAME,
        "tools_count": len(PITCHBOOK_TOOLS),
    }


@router.get("/tools/list")
async def list_tools() -> dict[str, Any]:
    """Return the list of available Pitchbook tools in MCP format."""
    tools_out = []
    for t in PITCHBOOK_TOOLS:
        tools_out.append(
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                "output_schema": {},
                "tags": t.tags,
                "version": _SERVER_VERSION,
            }
        )
    return {
        "server_name": _SERVER_NAME,
        "server_version": _SERVER_VERSION,
        "tools": tools_out,
    }


@router.post("/tools/call")
async def call_tool(body: ToolCallRequest, request: Request) -> JSONResponse:
    """Execute a Pitchbook MCP tool.

    The caller must supply the Pitchbook API key via X-Api-Key or
    Authorization: Bearer <key>.
    """
    api_key = _extract_api_key(request)
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Pitchbook API key required (X-Api-Key header or Authorization: Bearer <key>)",
        )

    tool = get_tool(body.tool)
    if tool is None:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": False,
                "output": None,
                "error_code": "unknown_tool",
                "error_message": f"Unknown tool: {body.tool}",
                "latency_ms": 0,
            },
        )

    start_ms = time.monotonic()

    try:
        result = await _dispatch(api_key, tool.name, tool.endpoint, tool.method, body.parameters)
        latency_ms = int((time.monotonic() - start_ms) * 1000)
        return JSONResponse(
            content={
                "success": True,
                "output": result,
                "error_code": None,
                "error_message": None,
                "latency_ms": latency_ms,
            }
        )

    except PitchbookRateLimitError as exc:
        latency_ms = int((time.monotonic() - start_ms) * 1000)
        logger.warning("pitchbook_rate_limited", tool=body.tool, retry_after=exc.retry_after)
        return JSONResponse(
            content={
                "success": False,
                "output": None,
                "error_code": "rate_limited",
                "error_message": exc.message,
                "retry_after": exc.retry_after,
                "latency_ms": latency_ms,
            }
        )

    except PitchbookAuthError as exc:
        latency_ms = int((time.monotonic() - start_ms) * 1000)
        logger.warning("pitchbook_auth_error", tool=body.tool, status=exc.status_code)
        return JSONResponse(
            content={
                "success": False,
                "output": None,
                "error_code": "auth_failed",
                "error_message": "Invalid Pitchbook API key",
                "latency_ms": latency_ms,
            }
        )

    except PitchbookNotFoundError as exc:
        latency_ms = int((time.monotonic() - start_ms) * 1000)
        return JSONResponse(
            content={
                "success": False,
                "output": None,
                "error_code": "not_found",
                "error_message": exc.message,
                "latency_ms": latency_ms,
            }
        )

    except PitchbookAPIError as exc:
        latency_ms = int((time.monotonic() - start_ms) * 1000)
        logger.error("pitchbook_tool_error", tool=body.tool, status=exc.status_code, message=exc.message)
        return JSONResponse(
            content={
                "success": False,
                "output": None,
                "error_code": "tool_error",
                "error_message": exc.message,
                "latency_ms": latency_ms,
            }
        )

    except Exception as exc:
        latency_ms = int((time.monotonic() - start_ms) * 1000)
        logger.exception("pitchbook_unexpected_error", tool=body.tool)
        return JSONResponse(
            content={
                "success": False,
                "output": None,
                "error_code": "tool_error",
                "error_message": str(exc),
                "latency_ms": latency_ms,
            }
        )


# ---------------------------------------------------------------------------
# Dispatch logic
# ---------------------------------------------------------------------------


async def _dispatch(
    api_key: str,
    tool_name: str,
    endpoint_template: str,
    method: str,
    raw_params: dict[str, Any],
) -> dict[str, Any]:
    """Route a tool call to the correct Pitchbook API endpoint."""
    is_search = tool_name.startswith("pitchbook_search")

    async with PitchbookClient(api_key=api_key) as client:
        if is_search:
            # Search tools: pass all non-empty params as query params
            query_params = _normalize_params(raw_params)
            return await client.get(endpoint_template, params=query_params or None)

        # Non-search tools may need entity name resolution
        params = dict(raw_params)
        params = await _resolve_entity_name(client, params)
        params = _normalize_params(params)

        if method.upper() == "POST":
            path, _ = _build_path(endpoint_template, params)
            return await client.post(path, data=params)

        # GET with path param substitution
        path, query_params = _build_path(endpoint_template, params)
        return await client.get(path, params=query_params or None)
