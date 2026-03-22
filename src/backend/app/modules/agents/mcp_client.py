"""
MCPClient — calls MCP servers via SSE transport.

Responsibilities:
  - verify_and_enumerate(): fetch /tools/list from an MCP server, validate schema
  - call_tool(): invoke a specific tool and return structured output

Security requirements:
  - SSRF protection on all outbound requests (RFC 1918 blocklist)
  - No redirect following
  - Credential values never logged
  - Response size capped at 2MB

MCP SSE Transport:
  The client establishes an SSE connection to the MCP server endpoint, sends
  tool call requests, and collects streaming response events until a 'result'
  or 'error' event is received.

  For lightweight tool calls (non-streaming responses), the client also supports
  a REST-style POST to /tools/call if the server advertises 'rest_mode: true'
  in its /info response.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from app.core.security.ssrf import SSRFBlockedError, resolve_and_pin_url

logger = structlog.get_logger()

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2 MB
_MCP_CALL_TIMEOUT = 30.0  # seconds
_MCP_LIST_TIMEOUT = 15.0  # seconds


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class MCPToolSchema:
    """Represents a single tool advertised by an MCP server."""
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    version: Optional[str] = None


@dataclass
class MCPEnumerationResult:
    """Result of verify_and_enumerate()."""
    success: bool
    server_name: Optional[str] = None
    server_version: Optional[str] = None
    tools: list[MCPToolSchema] = field(default_factory=list)
    error_code: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class MCPCallResult:
    """Result of call_tool()."""
    success: bool
    output: dict = field(default_factory=dict)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms: int = 0


class MCPError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"[{code}] {detail}")


# ---------------------------------------------------------------------------
# MCPClient
# ---------------------------------------------------------------------------

class MCPClient:
    """
    Client for MCP (Model Context Protocol) servers.

    Usage:
        client = MCPClient()
        enum_result = await client.verify_and_enumerate(
            endpoint_url="https://mcp.example.com",
            auth_config={"credentials": {"api_key": "..."}},
        )
        call_result = await client.call_tool(
            endpoint_url="https://mcp.example.com",
            transport="sse",
            auth_config={"credentials": {"api_key": "..."}},
            tool_name="web_search",
            arguments={"query": "hello world"},
        )
    """

    def _build_auth_headers(self, auth_config: dict) -> dict:
        """Build HTTP headers from auth_config without logging values."""
        headers: dict = {"Content-Type": "application/json", "Accept": "application/json"}
        credentials = auth_config.get("credentials", {})
        # Inject API key from credentials if present under common key names
        for key_name in ("api_key", "token", "bearer_token"):
            if key_name in credentials:
                headers["Authorization"] = f"Bearer {credentials[key_name]}"
                break
        # Support custom header injection via header_map
        header_map: dict = auth_config.get("header_map", {})
        for header_name, cred_key in header_map.items():
            if cred_key in credentials:
                headers[header_name] = credentials[cred_key]
        return headers

    async def verify_and_enumerate(
        self,
        endpoint_url: str,
        auth_config: Optional[dict] = None,
    ) -> MCPEnumerationResult:
        """
        Verify an MCP server is reachable and enumerate its tools.

        Fetches /info (server metadata) and /tools/list (tool catalog).
        Both endpoints are optional — missing /info is tolerated; missing /tools/list
        results in an empty tools list with success=True.

        Args:
            endpoint_url: Base URL of the MCP server (e.g., https://mcp.example.com).
            auth_config: Optional dict with 'credentials' and/or 'header_map'.

        Returns:
            MCPEnumerationResult with success=True and tool list if reachable.
        """
        import httpx

        auth_config = auth_config or {}
        headers = self._build_auth_headers(auth_config)

        # SSRF protection: resolve-and-pin DNS to eliminate TOCTOU rebinding window.
        try:
            pinned_endpoint_url = await resolve_and_pin_url(endpoint_url)
        except SSRFBlockedError as exc:
            return MCPEnumerationResult(
                success=False,
                error_code="ssrf_blocked",
                error_message="MCP endpoint address is not permitted",
            )

        base_url = pinned_endpoint_url.rstrip("/")

        server_name: Optional[str] = None
        server_version: Optional[str] = None
        tools: list[MCPToolSchema] = []

        try:
            async with httpx.AsyncClient(
                timeout=_MCP_LIST_TIMEOUT,
                follow_redirects=False,
            ) as client:
                # Step 1: Fetch server info (optional)
                try:
                    info_resp = await client.get(f"{base_url}/info", headers=headers)
                    if info_resp.status_code == 200:
                        info_data = info_resp.json()
                        server_name = info_data.get("name") or info_data.get("server_name")
                        server_version = info_data.get("version")
                except Exception:
                    # /info is optional — continue without it
                    pass

                # Step 2: Fetch tool list
                try:
                    list_resp = await client.get(f"{base_url}/tools/list", headers=headers)
                    list_resp.raise_for_status()
                    list_data = list_resp.json()
                    raw_tools = list_data.get("tools", [])
                    if not isinstance(raw_tools, list):
                        raw_tools = []
                    for raw_tool in raw_tools:
                        if not isinstance(raw_tool, dict):
                            continue
                        tools.append(MCPToolSchema(
                            name=str(raw_tool.get("name", "")),
                            description=str(raw_tool.get("description", "")),
                            input_schema=raw_tool.get("inputSchema") or raw_tool.get("input_schema") or {},
                            output_schema=raw_tool.get("outputSchema") or raw_tool.get("output_schema") or {},
                            tags=list(raw_tool.get("tags", [])),
                            version=raw_tool.get("version"),
                        ))
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        # Server doesn't expose /tools/list — treat as empty
                        pass
                    else:
                        return MCPEnumerationResult(
                            success=False,
                            error_code="mcp_list_http_error",
                            error_message=f"HTTP {exc.response.status_code} from /tools/list",
                        )

            logger.info(
                "mcp_enumeration_success",
                endpoint_url=endpoint_url,
                tool_count=len(tools),
                server_name=server_name,
            )
            return MCPEnumerationResult(
                success=True,
                server_name=server_name,
                server_version=server_version,
                tools=tools,
            )

        except MCPError as exc:
            return MCPEnumerationResult(
                success=False,
                error_code=exc.code,
                error_message=exc.detail,
            )
        except Exception as exc:
            return MCPEnumerationResult(
                success=False,
                error_code="mcp_enumeration_failed",
                error_message=str(exc)[:200],
            )

    async def call_tool(
        self,
        endpoint_url: str,
        transport: str = "sse",
        auth_config: Optional[dict] = None,
        tool_name: str = "",
        arguments: Optional[dict] = None,
        timeout: float = _MCP_CALL_TIMEOUT,
    ) -> MCPCallResult:
        """
        Invoke a tool on an MCP server.

        Supports two transports:
          - 'sse': SSE streaming (default). Sends POST /tools/call and reads
            SSE events until a 'result' or 'error' event is received.
          - 'rest': REST mode. Sends POST /tools/call and reads JSON response directly.
            Used when the MCP server advertises rest_mode in its /info.

        Args:
            endpoint_url: Base URL of the MCP server.
            transport: 'sse' (default) or 'rest'.
            auth_config: Optional authentication config.
            tool_name: Name of the tool to invoke.
            arguments: Tool input arguments.
            timeout: Request timeout in seconds.

        Returns:
            MCPCallResult with success=True and output dict if successful.
        """
        import time

        auth_config = auth_config or {}
        arguments = arguments or {}

        # SSRF protection: resolve-and-pin DNS to eliminate TOCTOU rebinding window.
        try:
            pinned_endpoint_url = await resolve_and_pin_url(endpoint_url)
        except SSRFBlockedError as exc:
            return MCPCallResult(
                success=False,
                error_code="ssrf_blocked",
                error_message="MCP endpoint address is not permitted",
            )

        headers = self._build_auth_headers(auth_config)
        base_url = pinned_endpoint_url.rstrip("/")
        call_url = f"{base_url}/tools/call"
        payload = {"name": tool_name, "arguments": arguments}

        start_ms = int(time.time() * 1000)

        if transport == "rest":
            return await self._call_rest(call_url, payload, headers, timeout, start_ms)
        else:
            return await self._call_sse(call_url, payload, headers, timeout, start_ms)

    async def _call_rest(
        self,
        call_url: str,
        payload: dict,
        headers: dict,
        timeout: float,
        start_ms: int,
    ) -> MCPCallResult:
        """REST mode: POST /tools/call and read JSON response."""
        import time
        import httpx

        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
            ) as client:
                response = await client.post(call_url, json=payload, headers=headers)
                response.raise_for_status()

                # Enforce response size cap
                content_len = len(response.content)
                if content_len > _MAX_RESPONSE_BYTES:
                    return MCPCallResult(
                        success=False,
                        error_code="response_too_large",
                        error_message=f"MCP response exceeds {_MAX_RESPONSE_BYTES} bytes",
                        latency_ms=int(time.time() * 1000) - start_ms,
                    )

                data = response.json()
                output = data.get("result") or data.get("output") or data
                if not isinstance(output, dict):
                    output = {"result": output}

                return MCPCallResult(
                    success=True,
                    output=output,
                    latency_ms=int(time.time() * 1000) - start_ms,
                )

        except httpx.HTTPStatusError as exc:
            return MCPCallResult(
                success=False,
                error_code="mcp_http_error",
                error_message=f"HTTP {exc.response.status_code} from MCP tool call",
                latency_ms=int(time.time() * 1000) - start_ms,
            )
        except httpx.TimeoutException:
            return MCPCallResult(
                success=False,
                error_code="mcp_timeout",
                error_message=f"MCP tool call timed out ({timeout}s)",
                latency_ms=int(time.time() * 1000) - start_ms,
            )
        except Exception as exc:
            return MCPCallResult(
                success=False,
                error_code="mcp_call_failed",
                error_message=str(exc)[:200],
                latency_ms=int(time.time() * 1000) - start_ms,
            )

    async def _call_sse(
        self,
        call_url: str,
        payload: dict,
        headers: dict,
        timeout: float,
        start_ms: int,
    ) -> MCPCallResult:
        """
        SSE mode: POST /tools/call, read Server-Sent Events until result/error.

        The SSE protocol expects events in the format:
            event: result
            data: {"output": {...}}

        or:
            event: error
            data: {"code": "...", "message": "..."}
        """
        import time
        import httpx

        sse_headers = dict(headers)
        sse_headers["Accept"] = "text/event-stream"

        accumulated_bytes = 0
        result_data: Optional[dict] = None
        error_data: Optional[dict] = None

        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "POST",
                    call_url,
                    json=payload,
                    headers=sse_headers,
                ) as response:
                    response.raise_for_status()

                    current_event: Optional[str] = None
                    current_data_parts: list[str] = []

                    async for line in response.aiter_lines():
                        accumulated_bytes += len(line.encode())
                        if accumulated_bytes > _MAX_RESPONSE_BYTES:
                            return MCPCallResult(
                                success=False,
                                error_code="response_too_large",
                                error_message=f"MCP SSE response exceeds {_MAX_RESPONSE_BYTES} bytes",
                                latency_ms=int(time.time() * 1000) - start_ms,
                            )

                        if line.startswith("event:"):
                            current_event = line[6:].strip()
                        elif line.startswith("data:"):
                            current_data_parts.append(line[5:].strip())
                        elif line == "" and current_event is not None:
                            # End of SSE event block — parse accumulated data
                            raw_data = " ".join(current_data_parts)
                            try:
                                parsed = json.loads(raw_data)
                            except json.JSONDecodeError:
                                parsed = {"raw": raw_data}

                            if current_event == "result":
                                result_data = parsed
                                break
                            elif current_event == "error":
                                error_data = parsed
                                break

                            current_event = None
                            current_data_parts = []

            if error_data is not None:
                return MCPCallResult(
                    success=False,
                    error_code=str(error_data.get("code", "mcp_tool_error")),
                    error_message=str(error_data.get("message", "MCP tool returned error"))[:200],
                    latency_ms=int(time.time() * 1000) - start_ms,
                )

            if result_data is not None:
                output = result_data.get("output") or result_data.get("result") or result_data
                if not isinstance(output, dict):
                    output = {"result": output}
                return MCPCallResult(
                    success=True,
                    output=output,
                    latency_ms=int(time.time() * 1000) - start_ms,
                )

            return MCPCallResult(
                success=False,
                error_code="mcp_no_result",
                error_message="MCP SSE stream ended without a result event",
                latency_ms=int(time.time() * 1000) - start_ms,
            )

        except httpx.HTTPStatusError as exc:
            return MCPCallResult(
                success=False,
                error_code="mcp_http_error",
                error_message=f"HTTP {exc.response.status_code} from MCP SSE call",
                latency_ms=int(time.time() * 1000) - start_ms,
            )
        except httpx.TimeoutException:
            return MCPCallResult(
                success=False,
                error_code="mcp_timeout",
                error_message=f"MCP SSE call timed out ({timeout}s)",
                latency_ms=int(time.time() * 1000) - start_ms,
            )
        except Exception as exc:
            return MCPCallResult(
                success=False,
                error_code="mcp_sse_failed",
                error_message=str(exc)[:200],
                latency_ms=int(time.time() * 1000) - start_ms,
            )
