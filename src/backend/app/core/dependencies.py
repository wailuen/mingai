"""
FastAPI dependency injection functions.

Provides:
- get_current_user: Extract user from JWT token
- get_db: Database connection with RLS tenant context
- get_redis: Redis connection
- require_platform_admin: Platform admin authorization
- require_tenant_admin: Tenant admin authorization
"""
import os
from dataclasses import dataclass
from typing import Optional

import structlog
from fastapi import Depends, Header, HTTPException, status

from app.core.database import validate_tenant_id
from app.modules.auth.jwt import (
    JWTValidationError,
    _is_auth0_token,
    decode_jwt_token,
    decode_jwt_token_auth0,
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

    Token routing:
    - If AUTH0_DOMAIN is set AND the token header contains alg=RS256 with
      an issuer matching the configured Auth0 domain, validate via JWKS.
    - Otherwise fall back to HS256 local JWT (decode_jwt_token_v1_compat).

    Both paths produce the same CurrentUser fields.
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

    auth0_domain = os.environ.get("AUTH0_DOMAIN", "")

    # Route to Auth0 JWKS path when the token looks like an Auth0 RS256 token.
    # Local HS256 tokens are always validated via the local path regardless of
    # whether AUTH0_DOMAIN is configured — this is the P3AUTH-013 guarantee.
    if auth0_domain and _is_auth0_token(token, auth0_domain):
        try:
            payload = await decode_jwt_token_auth0(token)
        except JWTValidationError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.reason)
    else:
        # Local HS256 path (also handles AUTH0_DOMAIN absent)
        secret, algorithm = _get_jwt_settings()
        try:
            payload = decode_jwt_token_v1_compat(token, secret, algorithm)
        except JWTValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)

    # Check impersonation blocklist — impersonation tokens are revocable via
    # POST /platform/impersonate/end which stores the JTI in Redis.
    jti = payload.get("jti")
    if jti and payload.get("impersonated_by"):
        from app.core.redis_client import build_redis_key, get_redis  # noqa: PLC0415

        try:
            redis = get_redis()
            blocklist_key = build_redis_key("platform", "impersonation_blocklist", jti)
            is_blocked = await redis.exists(blocklist_key)
            if is_blocked:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Impersonation session has been ended",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        except HTTPException:
            raise
        except Exception:
            # Redis unavailable — fail open to avoid blocking all auth
            logger.warning("impersonation_blocklist_check_failed", jti=jti)

    return CurrentUser(
        id=payload["sub"],
        tenant_id=payload["tenant_id"],
        roles=payload.get("roles", []),
        scope=payload.get("scope", "tenant"),
        plan=payload.get("plan", "professional").lower(),
        email=payload.get("email"),
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


# ---------------------------------------------------------------------------
# Scoped admin middleware dependencies (TA-035)
# ---------------------------------------------------------------------------


async def _check_kb_admin_access(kb_id: str, user: CurrentUser, db) -> CurrentUser:
    """
    Verify that *user* may manage KB *kb_id*.

    Allowed if:
    1. user is a tenant_admin, OR
    2. user has an active (non-expired) kb_admin delegation for kb_id in this tenant.

    Raises HTTP 403 with a generic message otherwise.  Error message does NOT
    disclose the caller's scope or roles (403 security rule).
    """
    if "tenant_admin" in user.roles:
        return user

    if db is None:
        raise HTTPException(status_code=403, detail="Access denied.")

    from sqlalchemy import text as sa_text

    result = await db.execute(
        sa_text(
            "SELECT 1 FROM user_delegations "
            "WHERE user_id = :user_id AND tenant_id = :tenant_id "
            "AND delegated_scope = 'kb_admin' "
            "AND resource_id = CAST(:resource_id AS uuid) "
            "AND (expires_at IS NULL OR expires_at > NOW()) "
            "LIMIT 1"
        ),
        {
            "user_id": user.id,
            "tenant_id": user.tenant_id,
            "resource_id": kb_id,
        },
    )
    if result.fetchone() is None:
        raise HTTPException(status_code=403, detail="Access denied.")
    return user


async def _check_agent_admin_access(
    agent_id: str, user: CurrentUser, db
) -> CurrentUser:
    """
    Verify that *user* may manage agent *agent_id*.

    Allowed if:
    1. user is a tenant_admin, OR
    2. user has an active (non-expired) agent_admin delegation for agent_id in this tenant.

    Raises HTTP 403 with a generic message otherwise.
    """
    if "tenant_admin" in user.roles:
        return user

    if db is None:
        raise HTTPException(status_code=403, detail="Access denied.")

    from sqlalchemy import text as sa_text

    result = await db.execute(
        sa_text(
            "SELECT 1 FROM user_delegations "
            "WHERE user_id = :user_id AND tenant_id = :tenant_id "
            "AND delegated_scope = 'agent_admin' "
            "AND resource_id = CAST(:resource_id AS uuid) "
            "AND (expires_at IS NULL OR expires_at > NOW()) "
            "LIMIT 1"
        ),
        {
            "user_id": user.id,
            "tenant_id": user.tenant_id,
            "resource_id": agent_id,
        },
    )
    if result.fetchone() is None:
        raise HTTPException(status_code=403, detail="Access denied.")
    return user


def require_kb_admin(kb_id: str):
    """
    Dependency factory — returns a FastAPI dependency that allows:
    (1) tenant_admin role, or (2) active kb_admin delegation for kb_id.

    Typical usage with a fixed resource id::

        @router.get("/kb/{kb_id}/settings")
        async def handler(
            kb_id: str,
            current_user: CurrentUser = Depends(get_current_user),
            db: AsyncSession = Depends(get_async_session),
        ):
            await _check_kb_admin_access(kb_id, current_user, db)
            ...

    Or as a dependency factory when kb_id is known at route-definition time::

        router.get("/admin/kb/fixed-resource")(
            Depends(require_kb_admin("fixed-uuid"))
        )
    """
    from app.core.session import get_async_session as _gas

    async def _dep(
        user: CurrentUser = Depends(get_current_user),
        db=Depends(_gas),
    ) -> CurrentUser:
        return await _check_kb_admin_access(kb_id, user, db)

    return _dep


def require_agent_admin(agent_id: str):
    """
    Dependency factory — returns a FastAPI dependency that allows:
    (1) tenant_admin role, or (2) active agent_admin delegation for agent_id.
    """
    from app.core.session import get_async_session as _gas

    async def _dep(
        user: CurrentUser = Depends(get_current_user),
        db=Depends(_gas),
    ) -> CurrentUser:
        return await _check_agent_admin_access(agent_id, user, db)

    return _dep
