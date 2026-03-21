"""
A2A Discovery endpoint — /.well-known/agent.json

Implements the A2A v0.3 AgentCard specification for agent discovery.
No authentication required (A2A spec requirement).

SECURITY CONTRACT — Fields that MUST NEVER appear in this response:
- system_prompt (exposes agent configuration)
- tenant_id (exposes internal IDs)
- kb_bindings (exposes internal index IDs)
- credentials_vault_path (exposes vault paths)
- access_rules (exposes role IDs)
Reference: RULE A2A-04 (a2a_routing.py _validate_ssrf_safe_url)
"""
from __future__ import annotations

import os

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.middleware import get_limiter

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Rate limiter for this router — 60 requests per minute per IP.
# Uses the app-level limiter singleton so that RateLimitExceeded exceptions
# are handled by the handler registered in setup_middleware (returns 429).
# ---------------------------------------------------------------------------

_limiter = get_limiter()

# ---------------------------------------------------------------------------
# Router — no prefix, route lives at domain root per A2A spec
# ---------------------------------------------------------------------------

well_known_router = APIRouter()


@well_known_router.get("/.well-known/agent.json", include_in_schema=False)
@_limiter.limit("60/minute")
async def get_agent_card(request: Request) -> JSONResponse:
    """Return the A2A v0.3 AgentCard for this platform.

    No authentication required — this endpoint must be publicly accessible
    so that remote agents can discover this platform's capabilities.
    Rate limited to 60 requests/minute per IP to prevent enumeration abuse.
    """
    base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

    if not base_url:
        logger.warning(
            "discovery_not_configured",
            detail="PUBLIC_BASE_URL environment variable is not set",
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": "discovery_not_configured",
                "detail": "PUBLIC_BASE_URL environment variable is not set",
            },
        )

    agent_card = {
        "name": "mingai Enterprise AI Platform",
        "description": "Multi-tenant enterprise RAG platform with role-based AI agents",
        "url": base_url,
        "version": "1.0.0",
        "provider": {
            "organization": "mingai",
            "url": base_url,
        },
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "authentication": {
            "schemes": ["bearer"],
            "credentials": None,
        },
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "endpoints": {
            "chat": f"{base_url}/api/v1/chat",
            "agents": f"{base_url}/api/v1/agents",
        },
    }

    return JSONResponse(content=agent_card)
