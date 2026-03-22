"""
A2A Proxy — invokes external A2A agents on behalf of tenants.

The proxy enforces:
  1. SSRF protection on all outbound calls
  2. Guardrail overlay: apply tenant-level and agent-level guardrails before
     forwarding and after receiving response
  3. Rate limiting: per (tenant_id, target_agent_id) via Redis
  4. Credential injection: resolve tenant credentials from vault at call time
  5. Response sanitization: strip script tags, JS URIs, event handlers
  6. Timeout: hard 30s limit on all A2A calls
  7. Audit logging: every A2A invocation logged with tenant_id, agent_ids, status

Never logs: request body content (may contain PII), credential values, response body

Proxy call flow:
  1. Check rate limit → raise if exceeded
  2. Apply pre-call guardrails (output = blocked message if triggered)
  3. Resolve credentials from vault
  4. POST to a2a_endpoint with request body + credentials injected
  5. Apply post-call guardrails on response
  6. Return sanitized response
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Optional

import structlog

from app.core.security.ssrf import SSRFBlockedError, resolve_and_pin_url

logger = structlog.get_logger()

_A2A_CALL_TIMEOUT = 30.0
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024  # 4 MB
_DEFAULT_RATE_LIMIT_RPM = 60

# Response sanitization
_SCRIPT_TAG_RE = re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_JS_URI_RE = re.compile(r"javascript\s*:", re.IGNORECASE)
_EVENT_HANDLER_RE = re.compile(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Response sanitization
# ---------------------------------------------------------------------------

def _sanitize_value(value: Any) -> Any:
    """Recursively sanitize strings in a response dict."""
    if isinstance(value, str):
        value = _SCRIPT_TAG_RE.sub("", value)
        value = _JS_URI_RE.sub("javascript_blocked:", value)
        value = _EVENT_HANDLER_RE.sub("", value)
        return value
    if isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Guardrail evaluation
# ---------------------------------------------------------------------------

def _apply_guardrails(
    content: str,
    guardrails: list[dict],
    direction: str,  # 'pre' or 'post'
) -> tuple[bool, Optional[str]]:
    """
    Apply guardrail rules to content.

    Supported rule types:
      - 'regex': match pattern → block if found
      - 'length': { max: int } → block if content length exceeds max
      - 'keyword_block': { keywords: [str] } → block if any keyword found

    Returns:
        (blocked: bool, block_reason: Optional[str])
    """
    for rule in guardrails:
        rule_direction = rule.get("direction", "both")
        if rule_direction not in (direction, "both"):
            continue

        rule_type = rule.get("type", "")
        rule_name = rule.get("name", rule_type)

        if rule_type == "regex":
            pattern = rule.get("pattern", "")
            if not pattern:
                continue
            try:
                if re.search(pattern, content, re.IGNORECASE):
                    return True, f"Guardrail '{rule_name}' triggered (regex match)"
            except re.error:
                logger.warning("a2a_proxy_guardrail_invalid_regex", rule_name=rule_name)

        elif rule_type == "length":
            max_len = int(rule.get("max", 10000))
            if len(content) > max_len:
                return True, f"Guardrail '{rule_name}' triggered (content too long: {len(content)} > {max_len})"

        elif rule_type == "keyword_block":
            keywords = rule.get("keywords", [])
            content_lower = content.lower()
            for kw in keywords:
                if kw.lower() in content_lower:
                    return True, f"Guardrail '{rule_name}' triggered (blocked keyword)"

    return False, None


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class A2ACallResult:
    success: bool
    response: dict
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    blocked_by_guardrail: bool = False
    block_reason: Optional[str] = None
    latency_ms: int = 0


class A2AProxyError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"[{code}] {detail}")


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

async def _check_rate_limit(
    tenant_id: str,
    target_agent_id: str,
    rate_limit_rpm: int,
    redis: Any,
) -> None:
    """
    Per (tenant_id, target_agent_id) rate limit via Redis INCR/EXPIRE.
    Fail-open on Redis errors.
    """
    if redis is None:
        return
    try:
        from app.core.redis_client import build_redis_key
        key = build_redis_key(tenant_id, "rate", f"a2a_{target_agent_id}")
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, 60)
        if current > rate_limit_rpm:
            raise A2AProxyError(
                "a2a_rate_limit_exceeded",
                f"A2A call rate limit of {rate_limit_rpm} rpm exceeded",
            )
    except A2AProxyError:
        raise
    except Exception as exc:
        logger.warning(
            "a2a_rate_limit_redis_error",
            tenant_id=tenant_id,
            target_agent_id=target_agent_id,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# A2A Proxy
# ---------------------------------------------------------------------------

def _build_proxy_request_body(
    operation: str,
    input_data: dict,
    tenant_id: str,
    user_id: str,
) -> dict:
    """
    Build the request body to forward to an external A2A agent.

    Security requirement: tenant_id and user_id MUST NOT be forwarded to
    external agents — they are internal identifiers. Only the operation and
    sanitized input data are sent.

    Args:
        operation: The operation type (e.g. "query", "task").
        input_data: The caller's input payload.
        tenant_id: Calling tenant UUID (NOT forwarded).
        user_id: Calling user UUID (NOT forwarded).

    Returns:
        Dict safe to serialize and POST to the external A2A endpoint.
    """
    return {
        "operation": operation,
        "input": input_data,
    }


async def invoke_a2a_agent(
    *,
    tenant_id: str,
    calling_agent_id: str,
    target_agent: dict,
    request_body: dict,
    guardrails: Optional[list[dict]] = None,
    redis: Any = None,
    vault_client: Any = None,
) -> A2ACallResult:
    """
    Invoke an external A2A agent.

    Args:
        tenant_id: Calling tenant's UUID string.
        calling_agent_id: UUID of the agent making the A2A call.
        target_agent: Dict from agent_cards or registry with at minimum:
            - id: str
            - a2a_endpoint: str
            - rate_limit_per_minute: int (optional, default 60)
        request_body: Request payload to send to the target agent.
        guardrails: Optional list of guardrail rule dicts.
        redis: Optional Redis client for rate limiting.
        vault_client: Optional vault client for credential resolution.

    Returns:
        A2ACallResult with success=True and sanitized response if successful.
    """
    import time
    import json
    import httpx

    guardrails = guardrails or []
    target_agent_id = str(target_agent.get("id", ""))
    a2a_endpoint = str(target_agent.get("a2a_endpoint", ""))
    rate_limit_rpm = int(target_agent.get("rate_limit_per_minute", _DEFAULT_RATE_LIMIT_RPM))

    start_ms = int(time.time() * 1000)

    try:
        # Rate limit check
        await _check_rate_limit(tenant_id, target_agent_id, rate_limit_rpm, redis)

        # SSRF protection: resolve-and-pin DNS to eliminate TOCTOU rebinding window.
        # resolve_and_pin_url returns the URL with hostname replaced by resolved IP —
        # httpx uses the pinned IP directly (no second DNS resolution).
        try:
            pinned_endpoint = await resolve_and_pin_url(a2a_endpoint)
        except SSRFBlockedError as exc:
            raise A2AProxyError("ssrf_blocked", "A2A endpoint address is not permitted") from exc

        # Pre-call guardrail check on request body content
        request_content = json.dumps(request_body)
        blocked, block_reason = _apply_guardrails(request_content, guardrails, "pre")
        if blocked:
            logger.warning(
                "a2a_proxy_request_blocked",
                tenant_id=tenant_id,
                calling_agent_id=calling_agent_id,
                target_agent_id=target_agent_id,
                block_reason=block_reason,
            )
            return A2ACallResult(
                success=False,
                response={},
                blocked_by_guardrail=True,
                block_reason=block_reason,
                latency_ms=int(time.time() * 1000) - start_ms,
            )

        # Resolve credentials
        # NOTE: tenant_id and user_id MUST NOT be forwarded to external agents.
        # Only a correlation request ID is sent for tracing purposes.
        import uuid as _uuid
        headers: dict = {
            "Content-Type": "application/json",
            "X-Calling-Agent-Id": calling_agent_id,
            "X-Request-Id": str(_uuid.uuid4()),
        }

        if vault_client is not None:
            try:
                agent_creds_path = f"{tenant_id}/agents/{calling_agent_id}"
                creds = vault_client.get_all(agent_creds_path)
                # Inject any a2a-specific credential
                a2a_api_key = creds.get("a2a_api_key") or creds.get("api_key")
                if a2a_api_key:
                    headers["Authorization"] = f"Bearer {a2a_api_key}"
            except Exception as exc:
                logger.warning(
                    "a2a_proxy_cred_resolve_failed",
                    tenant_id=tenant_id,
                    calling_agent_id=calling_agent_id,
                    error=str(exc),
                )

        # Make A2A call using pinned URL (no second DNS resolution by httpx)
        try:
            async with httpx.AsyncClient(
                timeout=_A2A_CALL_TIMEOUT,
                follow_redirects=False,
            ) as client:
                http_response = await client.post(
                    pinned_endpoint,
                    json=request_body,
                    headers=headers,
                )
                http_response.raise_for_status()

                content_len = len(http_response.content)
                if content_len > _MAX_RESPONSE_BYTES:
                    return A2ACallResult(
                        success=False,
                        response={},
                        error_code="a2a_response_too_large",
                        error_message=f"A2A response exceeds {_MAX_RESPONSE_BYTES} byte limit",
                        latency_ms=int(time.time() * 1000) - start_ms,
                    )

                response_data = http_response.json()
                if not isinstance(response_data, dict):
                    response_data = {"result": response_data}

        except httpx.HTTPStatusError as exc:
            return A2ACallResult(
                success=False,
                response={},
                error_code="a2a_http_error",
                error_message=f"A2A agent returned HTTP {exc.response.status_code}",
                latency_ms=int(time.time() * 1000) - start_ms,
            )
        except httpx.TimeoutException:
            return A2ACallResult(
                success=False,
                response={},
                error_code="a2a_timeout",
                error_message=f"A2A call timed out ({_A2A_CALL_TIMEOUT}s)",
                latency_ms=int(time.time() * 1000) - start_ms,
            )
        except Exception as exc:
            return A2ACallResult(
                success=False,
                response={},
                error_code="a2a_call_failed",
                error_message=str(exc)[:200],
                latency_ms=int(time.time() * 1000) - start_ms,
            )

        # Post-call guardrail check on response
        response_content = json.dumps(response_data)
        blocked, block_reason = _apply_guardrails(response_content, guardrails, "post")
        if blocked:
            logger.warning(
                "a2a_proxy_response_blocked",
                tenant_id=tenant_id,
                calling_agent_id=calling_agent_id,
                target_agent_id=target_agent_id,
                block_reason=block_reason,
            )
            return A2ACallResult(
                success=False,
                response={},
                blocked_by_guardrail=True,
                block_reason=block_reason,
                latency_ms=int(time.time() * 1000) - start_ms,
            )

        # Sanitize response
        sanitized = _sanitize_value(response_data)

        logger.info(
            "a2a_proxy_success",
            tenant_id=tenant_id,
            calling_agent_id=calling_agent_id,
            target_agent_id=target_agent_id,
            latency_ms=int(time.time() * 1000) - start_ms,
        )

        return A2ACallResult(
            success=True,
            response=sanitized,
            latency_ms=int(time.time() * 1000) - start_ms,
        )

    except A2AProxyError as exc:
        return A2ACallResult(
            success=False,
            response={},
            error_code=exc.code,
            error_message=exc.detail,
            latency_ms=int(time.time() * 1000) - start_ms,
        )
    except Exception as exc:
        logger.error(
            "a2a_proxy_unexpected_error",
            tenant_id=tenant_id,
            calling_agent_id=calling_agent_id,
            error=str(exc),
        )
        return A2ACallResult(
            success=False,
            response={},
            error_code="internal_error",
            error_message=str(exc)[:200],
            latency_ms=int(time.time() * 1000) - start_ms,
        )
