"""
Tool Executor — dispatches tool calls based on executor_type.

Three executor types:
  - 'builtin': calls a platform Python function from REGISTRY
  - 'http_wrapper': makes HTTP POST to tool.endpoint_url with credential injection
  - 'mcp_sse': calls MCP server via SSE transport

Security requirements (non-negotiable):
  - SSRF protection: block all RFC 1918 + loopback + link-local ranges
  - No redirect following in all outbound HTTP calls
  - Response sanitization: strip <script>, javascript:, event handlers
  - Credential masking in all log output
  - Rate limiting per (tenant_id, tool_id) via Redis INCR

Usage counter: incremented in Redis on every tool invocation for analytics.
Key format: tool_invocations:{tool_id}:{YYYY-MM-DD}
TTL: 35 days
"""
from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

import structlog

from app.core.security.ssrf import SSRFBlockedError, resolve_and_pin_url

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Registry of built-in tool functions
# ---------------------------------------------------------------------------
from app.modules.tools.builtins.calculator import calculator
from app.modules.tools.builtins.data_formatter import data_formatter
from app.modules.tools.builtins.document_ocr import document_ocr
from app.modules.tools.builtins.file_reader import file_reader
from app.modules.tools.builtins.text_translator import text_translator
from app.modules.tools.builtins.web_search import web_search

BUILTIN_REGISTRY: dict[str, Any] = {
    "web_search": web_search,
    "document_ocr": document_ocr,
    "calculator": calculator,
    "data_formatter": data_formatter,
    "file_reader": file_reader,
    "text_translator": text_translator,
}

# Response sanitization patterns
_SCRIPT_TAG_RE = re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_JS_URI_RE = re.compile(r"javascript\s*:", re.IGNORECASE)
_EVENT_HANDLER_RE = re.compile(
    r'\s+on\w+\s*=\s*["\'][^"\']*["\']', re.IGNORECASE
)

# Redis usage counter TTL (35 days in seconds)
_USAGE_COUNTER_TTL = 35 * 24 * 3600


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    success: bool
    output: dict
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms: int = 0


class ToolExecutionError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"[{code}] {detail}")


# ---------------------------------------------------------------------------
# Response sanitization
# ---------------------------------------------------------------------------

def _sanitize_value(value: Any) -> Any:
    """Recursively sanitize a value, stripping dangerous HTML/JS from strings."""
    if isinstance(value, str):
        # Strip <script>...</script>
        value = _SCRIPT_TAG_RE.sub("", value)
        # Strip javascript: URI schemes
        value = _JS_URI_RE.sub("javascript_blocked:", value)
        # Strip HTML event handlers (onclick=, onload=, etc.)
        value = _EVENT_HANDLER_RE.sub("", value)
        return value
    if isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Rate limiting via Redis
# ---------------------------------------------------------------------------

async def _check_rate_limit(
    tool_id: str,
    tenant_id: str,
    rate_limit_rpm: int,
    redis: Any,
) -> None:
    """
    Enforce per-(tenant_id, tool_id) rate limit using Redis INCR/EXPIRE.
    Fail-open on Redis errors (log warning, do not block tool call).
    """
    if redis is None:
        return
    try:
        from app.core.redis_client import build_redis_key
        key = build_redis_key(tenant_id, "rate", f"tool_{tool_id}")
        current = await redis.incr(key)
        if current == 1:
            # First call in this window — set 60-second TTL
            await redis.expire(key, 60)
        if current > rate_limit_rpm:
            raise ToolExecutionError(
                "rate_limit_exceeded",
                f"Tool rate limit of {rate_limit_rpm} rpm exceeded",
            )
    except ToolExecutionError:
        raise
    except Exception as exc:
        logger.warning(
            "tool_rate_limit_redis_error",
            tool_id=tool_id,
            tenant_id=tenant_id,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Usage counter (analytics)
# ---------------------------------------------------------------------------

async def _increment_usage_counter(
    tool_id: str,
    redis: Any,
) -> None:
    """Increment Redis usage counter for analytics. Fail-silently."""
    if redis is None:
        return
    try:
        today = date.today().isoformat()
        key = f"tool_invocations:{tool_id}:{today}"
        await redis.incr(key)
        await redis.expire(key, _USAGE_COUNTER_TTL)
    except Exception as exc:
        logger.warning("tool_usage_counter_failed", tool_id=tool_id, error=str(exc))


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------

async def _resolve_credentials(
    tool: dict,
    tenant_id: str,
    agent_id: str,
    vault_client: Any,
) -> dict:
    """
    Fetch credentials from vault based on tool.credential_source.
    Never logs credential values.
    """
    credential_source = tool.get("credential_source", "none")

    if credential_source == "none":
        return {}

    if vault_client is None:
        logger.warning(
            "tool_credentials_vault_unavailable",
            tool_name=tool.get("name"),
            credential_source=credential_source,
        )
        return {}

    if credential_source == "platform_managed":
        try:
            return vault_client.get_all(f"platform/tools/{tool['id']}")
        except Exception as exc:
            logger.warning(
                "tool_platform_creds_fetch_failed",
                tool_id=tool.get("id"),
                error=str(exc),
            )
            return {}

    if credential_source == "tenant_managed":
        try:
            return vault_client.get_all(f"{tenant_id}/agents/{agent_id}")
        except Exception as exc:
            logger.warning(
                "tool_tenant_creds_fetch_failed",
                agent_id=agent_id,
                error=str(exc),
            )
            return {}

    raise ToolExecutionError(
        "unknown_credential_source",
        f"Unknown credential_source: {credential_source}",
    )


# ---------------------------------------------------------------------------
# Builtin executor
# ---------------------------------------------------------------------------

class BuiltinExecutor:
    """Dispatches to platform Python functions registered in BUILTIN_REGISTRY."""

    async def execute(self, tool: dict, input_data: dict, **_: Any) -> dict:
        tool_name = tool.get("name", "")
        if tool_name not in BUILTIN_REGISTRY:
            raise ToolExecutionError(
                "builtin_not_found",
                f"Built-in tool '{tool_name}' is not registered",
            )
        fn = BUILTIN_REGISTRY[tool_name]
        result = await fn(**input_data)
        return _sanitize_value(result)


# ---------------------------------------------------------------------------
# HTTP wrapper executor
# ---------------------------------------------------------------------------

class HttpWrapperExecutor:
    """Calls a tool via HTTP POST to its endpoint_url with credential injection."""

    async def execute(
        self,
        tool: dict,
        input_data: dict,
        credentials: dict,
        tenant_id: str,
        tool_id: str,
        redis: Any,
    ) -> dict:
        import httpx

        endpoint_url = tool.get("endpoint_url") or ""
        if not endpoint_url:
            raise ToolExecutionError("http_wrapper_no_endpoint", "Tool has no endpoint_url")

        # SSRF protection: resolve-and-pin DNS to eliminate TOCTOU rebinding window.
        try:
            pinned_url = await resolve_and_pin_url(endpoint_url)
        except SSRFBlockedError as exc:
            raise ToolExecutionError("ssrf_blocked", "Tool endpoint address is not permitted") from exc

        # Build request headers with credential injection
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if credentials:
            # Credentials are injected as Authorization header or custom header
            # The credential_schema defines which key maps to which header
            credential_schema = tool.get("credential_schema", [])
            for field in credential_schema:
                key = field.get("key", "")
                header_name = field.get("header_name", "Authorization")
                if key in credentials:
                    # Never log credential values
                    headers[header_name] = credentials[key]

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=False,  # Never follow redirects (SSRF vector)
            ) as client:
                response = await client.post(
                    pinned_url,
                    json=input_data,
                    headers=headers,
                )
                response.raise_for_status()
                output = response.json()
        except httpx.HTTPStatusError as exc:
            raise ToolExecutionError(
                "http_wrapper_error",
                f"HTTP {exc.response.status_code} from tool endpoint",
            ) from exc
        except httpx.TimeoutException:
            raise ToolExecutionError("http_wrapper_timeout", "Tool endpoint timed out (30s)")
        except Exception as exc:
            raise ToolExecutionError(
                "http_wrapper_failed",
                f"Tool call failed: {str(exc)[:200]}",
            ) from exc

        if not isinstance(output, dict):
            output = {"result": output}

        return _sanitize_value(output)


# ---------------------------------------------------------------------------
# MCP SSE executor
# ---------------------------------------------------------------------------

class McpSseExecutor:
    """Calls a tool via MCP SSE protocol through the MCP client."""

    async def execute(
        self,
        tool: dict,
        input_data: dict,
        credentials: dict,
        transport: str = "sse",
    ) -> dict:
        endpoint_url = tool.get("endpoint_url") or ""
        if not endpoint_url:
            raise ToolExecutionError("mcp_sse_no_endpoint", "Tool has no endpoint_url")

        # SSRF protection: resolve-and-pin DNS to eliminate TOCTOU rebinding window.
        # NOTE: mcp_client.call_tool also calls resolve_and_pin_url internally,
        # but we pin here first so the ToolExecutionError wrapping is correct.
        try:
            pinned_endpoint_url = await resolve_and_pin_url(endpoint_url)
        except SSRFBlockedError as exc:
            raise ToolExecutionError("ssrf_blocked", "Tool endpoint address is not permitted") from exc

        try:
            from app.modules.agents.mcp_client import MCPClient
            client = MCPClient()
            auth_config = {}
            if credentials:
                auth_config = {"credentials": credentials}
            result = await client.call_tool(
                endpoint_url=pinned_endpoint_url,
                transport=transport,
                auth_config=auth_config,
                tool_name=tool.get("name", ""),
                arguments=input_data,
                timeout=30.0,
            )
            output = result.output if hasattr(result, "output") else (result or {})
            if not isinstance(output, dict):
                output = {"result": output}
            return _sanitize_value(output)
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(
                "mcp_sse_failed",
                f"MCP tool call failed: {str(exc)[:200]}",
            ) from exc


# ---------------------------------------------------------------------------
# Main ToolExecutor
# ---------------------------------------------------------------------------

class ToolExecutor:
    """
    Main dispatcher for agent tool invocations.

    Credentials are fetched from vault at call time and never cached beyond
    the lifetime of this request.
    """

    def __init__(self, vault_client: Any = None, redis: Any = None) -> None:
        self._vault = vault_client
        self._redis = redis
        self._builtin = BuiltinExecutor()
        self._http = HttpWrapperExecutor()
        self._mcp = McpSseExecutor()

    async def execute(
        self,
        tool: dict,
        arguments: dict,
        tenant_id: str,
        agent_id: str,
    ) -> ToolResult:
        """
        Execute a tool call.

        Args:
            tool: Tool record dict (from tool_catalog or agent_template_tools).
            arguments: Input arguments for the tool.
            tenant_id: Calling tenant's UUID string.
            agent_id: Calling agent's UUID string.

        Returns:
            ToolResult with success/failure info.
        """
        import time

        tool_id = str(tool.get("id", ""))
        tool_name = tool.get("name", "unknown")
        executor_type = tool.get("executor_type") or tool.get("executor", "builtin")
        rate_limit_rpm = int(tool.get("rate_limit_rpm", 60))

        start_ms = int(time.time() * 1000)

        try:
            # Rate limit check (fail-open on Redis errors)
            await _check_rate_limit(tool_id, tenant_id, rate_limit_rpm, self._redis)

            # Resolve credentials
            credentials = await _resolve_credentials(tool, tenant_id, agent_id, self._vault)

            # Dispatch
            if executor_type == "builtin":
                output = await self._builtin.execute(tool, arguments)
            elif executor_type == "http_wrapper":
                output = await self._http.execute(
                    tool, arguments, credentials, tenant_id, tool_id, self._redis
                )
            elif executor_type == "mcp_sse":
                transport = "sse"
                output = await self._mcp.execute(tool, arguments, credentials, transport)
            else:
                raise ToolExecutionError(
                    "unknown_executor_type",
                    f"Unknown executor_type: {executor_type}",
                )

            # Increment usage counter
            await _increment_usage_counter(tool_id, self._redis)

            latency_ms = int(time.time() * 1000) - start_ms
            logger.info(
                "tool_execution_success",
                tool_name=tool_name,
                executor_type=executor_type,
                tenant_id=tenant_id,
                latency_ms=latency_ms,
            )
            return ToolResult(success=True, output=output, latency_ms=latency_ms)

        except ToolExecutionError as exc:
            latency_ms = int(time.time() * 1000) - start_ms
            logger.warning(
                "tool_execution_error",
                tool_name=tool_name,
                error_code=exc.code,
                error_detail=exc.detail,
                tenant_id=tenant_id,
                latency_ms=latency_ms,
            )
            return ToolResult(
                success=False,
                output={},
                error_code=exc.code,
                error_message=exc.detail,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = int(time.time() * 1000) - start_ms
            logger.error(
                "tool_execution_unexpected_error",
                tool_name=tool_name,
                error=str(exc),
                tenant_id=tenant_id,
                latency_ms=latency_ms,
            )
            return ToolResult(
                success=False,
                output={},
                error_code="internal_error",
                error_message=str(exc)[:200],
                latency_ms=latency_ms,
            )
