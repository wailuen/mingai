"""
FastAPI dependency injection functions.

Provides:
- get_current_user: Extract user from JWT token
- get_db: Database connection with RLS tenant context
- get_redis: Redis connection
- require_platform_admin: Platform admin authorization
- require_tenant_admin: Tenant admin authorization
"""
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, status

import structlog

from app.core.database import validate_tenant_id
from app.modules.auth.jwt import (
    JWTValidationError,
    decode_jwt_token,
    decode_jwt_token_v1_compat,
)

logger = structlog.get_logger()


@dataclass
class CurrentUser:
    """Authenticated user context extracted from JWT."""

    id: str
    tenant_id: str
    roles: list[str]
    scope: str
    plan: str
    email: Optional[str] = None


def _get_jwt_settings() -> tuple[str, str]:
    """Get JWT settings from environment. Raises if not configured."""
    import os

    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="Authentication service unavailable",
        )

    algorithm = os.environ.get("JWT_ALGORITHM", "HS256")
    return secret, algorithm


async def get_current_user(
    authorization: Optional[str] = Header(None, description="Bearer token"),
) -> CurrentUser:
    """
    Extract and validate user from JWT Bearer token.

    Sets up user context for downstream handlers.
    Works for both Phase 1 (local JWT) and Phase 2 (Auth0).
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authorization header must use Bearer scheme",
        )

    token = authorization[7:]  # Remove "Bearer " prefix
    secret, algorithm = _get_jwt_settings()

    try:
        payload = decode_jwt_token_v1_compat(token, secret, algorithm)
    except JWTValidationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.reason)

    return CurrentUser(
        id=payload["sub"],
        tenant_id=payload["tenant_id"],
        roles=payload.get("roles", []),
        scope=payload.get("scope", "tenant"),
        plan=payload.get("plan", "professional"),
    )


async def require_platform_admin(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Require platform admin scope. Returns 403 if not authorized."""
    if user.scope != "platform":
        raise HTTPException(
            status_code=403,
            detail="Platform admin access required.",
        )
    return user


async def require_tenant_admin(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Require tenant admin role. Returns 403 if not authorized."""
    if "tenant_admin" not in user.roles:
        raise HTTPException(
            status_code=403,
            detail="Tenant admin role required.",
        )
    return user
