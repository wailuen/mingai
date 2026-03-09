"""
Tenant context middleware — injects tenant_id into request state.

INFRA-048: Resolves tenant context for every inbound request and attaches
it to `request.state` so that downstream handlers, services, and DB helpers
can rely on it without re-decoding the JWT token.

Multi-tenant behaviour:
  MULTI_TENANT_ENABLED=True  — tenant_id extracted from JWT Bearer token.
  MULTI_TENANT_ENABLED=False — tenant_id fixed to "default" (single-tenant).

The RLS SET (`SET app.tenant_id`) is intentionally NOT done here — that
belongs to the per-request database session (INFRA-049).  This middleware
only populates request.state so that session helpers can read it without
re-parsing the JWT.

Exempt paths (no JWT required, tenant_id set to ""):
  /health, /ready, /metrics, /docs, /openapi.json, /redoc
"""
import os
from typing import Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger()

# Paths that are exempt from tenant resolution.
# These are infrastructure / observability endpoints that do not touch
# tenant data and must be reachable without a JWT.
_EXEMPT_PATHS: frozenset[str] = frozenset(
    [
        "/health",
        "/ready",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/v1/health",
        "/api/docs",
    ]
)


def _extract_claims_from_jwt(
    authorization_header: str,
) -> tuple[str | None, str | None]:
    """
    Decode the JWT once and return (tenant_id, scope) claims.

    Single decode per request — avoids redundant HMAC verification.
    This is a read-only decode — it does NOT raise HTTP exceptions.
    Returns (None, None) if the token is absent, malformed, or lacks claims.
    The full auth validation with HTTP 401/403 is handled by the
    `get_current_user` dependency on individual route handlers.
    """
    if not authorization_header:
        return None, None
    if not authorization_header.startswith("Bearer "):
        return None, None

    token = authorization_header[7:]

    secret = os.environ.get("JWT_SECRET_KEY", "")
    algorithm = os.environ.get("JWT_ALGORITHM", "HS256")
    if not secret:
        return None, None

    try:
        from app.modules.auth.jwt import decode_jwt_token_v1_compat

        payload = decode_jwt_token_v1_compat(token, secret, algorithm)
        return payload.get("tenant_id") or None, payload.get("scope") or None
    except Exception:
        # Validation failures are surfaced by get_current_user on routes that
        # require auth.  Middleware silently skips so exempt/public routes
        # continue to work without a valid token.
        return None, None


class TenantContextMiddleware(BaseHTTPMiddleware):
    """
    Starlette BaseHTTPMiddleware that resolves and injects tenant context.

    After this middleware runs, all downstream handlers can read:
        request.state.tenant_id  — str, may be "" for unauthenticated exempt paths
        request.state.scope      — str ("tenant" | "platform" | "")

    The scope is extracted from the JWT `scope` claim when available.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Exempt paths: infrastructure / docs — skip tenant resolution.
        if path in _EXEMPT_PATHS:
            request.state.tenant_id = ""
            request.state.scope = ""
            return await call_next(request)

        # Check feature flag
        multi_tenant_enabled = _is_multi_tenant_enabled()

        if not multi_tenant_enabled:
            # Single-tenant mode: all requests belong to the "default" tenant.
            request.state.tenant_id = "default"
            request.state.scope = "tenant"
            logger.debug(
                "tenant_context_resolved",
                tenant_id="default",
                mode="single_tenant",
                path=path,
            )
            return await call_next(request)

        # Multi-tenant mode: resolve from JWT (single decode for both claims).
        authorization = request.headers.get("Authorization", "")
        tenant_id, scope = _extract_claims_from_jwt(authorization)

        if tenant_id:
            request.state.tenant_id = tenant_id
            request.state.scope = scope or "tenant"
            logger.debug(
                "tenant_context_resolved",
                tenant_id=tenant_id,
                scope=scope,
                mode="multi_tenant",
                path=path,
            )
        else:
            # No valid JWT — tenant_id unresolved.
            # Routes that require auth will reject the request via
            # get_current_user / require_tenant_admin dependencies.
            # Public routes (auth endpoints) proceed without tenant context.
            request.state.tenant_id = ""
            request.state.scope = ""

        return await call_next(request)


def _is_multi_tenant_enabled() -> bool:
    """
    Return the multi_tenant_enabled setting.

    Reads from MULTI_TENANT_ENABLED env var directly to avoid the heavy
    Settings() instantiation on every request.  Falls back to True (the
    secure default) if unset.
    """
    val = os.environ.get("MULTI_TENANT_ENABLED", "true").strip().lower()
    return val not in ("false", "0", "no", "off")
