"""
Auth API endpoints (API-001 to API-010).

Phase 1: Local JWT authentication with DB-backed bcrypt verification.
Phase 2: Auth0 JWKS validation.
"""
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import structlog
from fastapi import APIRouter, Depends, HTTPException
from jose import jwt
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """API-003: Login request body."""

    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        if not v or "@" not in v:
            raise ValueError("Valid email address required")
        return v.lower().strip()

    @field_validator("password")
    @classmethod
    def validate_password_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("Password required")
        return v


class TokenResponse(BaseModel):
    """JWT token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ReissueRequest(BaseModel):
    """
    API-004: Token reissue request.

    Re-issues an access token using the current user's JWT claims.
    Phase 2 will add Redis-backed refresh token rotation; for Phase 1 the
    endpoint re-issues from the Bearer token in the Authorization header.
    """

    pass  # No body required — identity comes from the Bearer token


class UserResponse(BaseModel):
    """API-006: Current user response."""

    id: str
    tenant_id: str
    roles: list[str]
    scope: str
    plan: str
    email: Optional[str] = None


def _create_access_token(
    user_id: str,
    tenant_id: str,
    roles: list[str],
    scope: str,
    plan: str,
    email: str,
) -> tuple[str, int]:
    """
    Create a JWT v2 access token.

    All signing keys from environment - NEVER hardcode.
    Returns (token_string, expires_in_seconds).
    """
    secret = os.environ.get("JWT_SECRET_KEY")
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="JWT_SECRET_KEY not configured",
        )

    algorithm = os.environ.get("JWT_ALGORITHM", "HS256")
    expire_minutes = int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)

    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": scope,
        "plan": plan,
        "email": email,
        "exp": expires_at,
        "iat": datetime.now(timezone.utc),
        "token_version": 2,
    }

    token = jwt.encode(payload, secret, algorithm=algorithm)
    return token, expire_minutes * 60


def _write_session_to_redis(user_id: str, tenant_id: str, ttl_seconds: int) -> None:
    """
    Write a session marker to Redis so logout can revoke it.

    Key: mingai:{tenant_id}:session:{user_id}
    TTL: matches the JWT access token lifetime.
    Non-fatal — if Redis is unavailable, login still succeeds (token expires naturally).
    """
    import asyncio

    async def _write() -> None:
        from app.core.redis_client import build_redis_key, get_redis

        redis = get_redis()
        session_key = build_redis_key(tenant_id, "session", user_id)
        await redis.set(session_key, "1", ex=ttl_seconds)
        logger.debug("session_written_to_redis", user_id=user_id)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_write())
        else:
            loop.run_until_complete(_write())
    except Exception as exc:
        logger.warning(
            "session_write_to_redis_skipped",
            user_id=user_id,
            error=str(exc),
            reason="Redis unavailable — token expires naturally after JWT TTL",
        )


def _verify_password(plain: str, stored: str) -> bool:
    """
    Verify a password against stored value.

    Supports bcrypt hashes (prefix $2b$ or $2a$) and plaintext (bootstrap only).
    Production passwords must be bcrypt hashes.
    """
    stored_bytes = stored.encode()
    if stored_bytes.startswith(b"$2b$") or stored_bytes.startswith(b"$2a$"):
        return bcrypt.checkpw(plain.encode(), stored_bytes)
    # Plaintext fallback for bootstrap env vars only — constant-time comparison
    # to prevent timing side-channels even on non-hashed values.
    return hmac.compare_digest(plain, stored)


@router.post("/local/login", response_model=TokenResponse)
async def local_login(
    request: LoginRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-003: Local username/password authentication.

    Lookup order:
    1. Platform admin bootstrap — checked via PLATFORM_ADMIN_EMAIL / PLATFORM_ADMIN_PASS
       env vars. Supports bcrypt hash or plaintext (for bootstrap convenience).
    2. Tenant users — looked up in the users table with bcrypt password verification.

    Returns JWT v2 access token.
    Rate limited: 10 attempts per email per 15 minutes (enforced at gateway layer).
    """
    # --- Platform admin bootstrap path ---
    platform_email = os.environ.get("PLATFORM_ADMIN_EMAIL", "")
    platform_pass = os.environ.get("PLATFORM_ADMIN_PASS", "")

    if platform_email and request.email == platform_email.lower():
        if not platform_pass or not _verify_password(request.password, platform_pass):
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials",
            )

        token, expires_in = _create_access_token(
            user_id="00000000-0000-0000-0000-000000000001",
            tenant_id="default",
            roles=["platform_admin"],
            scope="platform",
            plan="enterprise",
            email=request.email,
        )

        _write_session_to_redis(
            user_id="00000000-0000-0000-0000-000000000001",
            tenant_id="default",
            ttl_seconds=expires_in,
        )
        logger.info(
            "user_login",
            email=request.email,
            scope="platform",
            method="local_env",
        )
        return TokenResponse(access_token=token, expires_in=expires_in)

    # --- DB-backed tenant user lookup ---
    try:
        result = await session.execute(
            text(
                "SELECT u.id, u.tenant_id, u.email, u.password_hash, u.role, t.plan "
                "FROM users u "
                "JOIN tenants t ON u.tenant_id = t.id "
                "WHERE u.email = :email AND u.status = 'active' "
                "ORDER BY u.created_at ASC LIMIT 1"
            ),
            {"email": request.email},
        )
        row = result.fetchone()
    except Exception as exc:
        logger.warning(
            "db_user_lookup_failed",
            email=request.email,
            error=str(exc),
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if row is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user_id, tenant_id, email, password_hash, role, plan = row

    if not password_hash or not _verify_password(request.password, str(password_hash)):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    str_user_id = str(user_id)
    str_tenant_id = str(tenant_id)

    token, expires_in = _create_access_token(
        user_id=str_user_id,
        tenant_id=str_tenant_id,
        roles=[role],
        scope="tenant",
        plan=plan,
        email=email,
    )

    _write_session_to_redis(
        user_id=str_user_id,
        tenant_id=str_tenant_id,
        ttl_seconds=expires_in,
    )

    logger.info(
        "user_login",
        email=request.email,
        scope="tenant",
        method="local_db",
    )
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post("/token/refresh", response_model=TokenResponse)
async def refresh_token(
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    API-004: Re-issue an access token using the current Bearer token's claims.

    Re-issues an access token with the same claims as the presented token.
    The caller must send a valid, non-expired Bearer token in Authorization header.

    Phase 2 upgrade path: add Redis-backed refresh token issuance at login
    and validate a separate long-lived refresh token here (rotation pattern).
    """
    token, expires_in = _create_access_token(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        roles=current_user.roles,
        scope=current_user.scope,
        plan=current_user.plan,
        email=current_user.email or "",
    )

    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
    )


@router.post("/logout", status_code=204)
async def logout(current_user: CurrentUser = Depends(get_current_user)):
    """
    API-005: Invalidate current session.

    Revokes the session key in Redis so the token cannot be reused.
    Non-fatal if Redis is unavailable — token naturally expires after JWT TTL.
    """
    logger.info(
        "user_logout",
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )

    # Revoke session in Redis (non-fatal — token expires naturally if Redis is down)
    try:
        from app.core.redis_client import build_redis_key, get_redis

        redis = get_redis()
        session_key = build_redis_key(
            current_user.tenant_id, "session", current_user.id
        )
        await redis.delete(session_key)
        logger.info("session_revoked_in_redis", user_id=current_user.id)
    except Exception as exc:
        logger.warning(
            "session_revocation_skipped",
            user_id=current_user.id,
            error=str(exc),
            reason="Redis unavailable — token expires naturally after JWT TTL",
        )

    return None


@router.get("/current", response_model=UserResponse)
async def get_current_user_info(
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    API-006: Get current authenticated user info.

    Returns user ID, tenant, roles, scope, and plan.
    """
    return UserResponse(
        id=current_user.id,
        tenant_id=current_user.tenant_id,
        roles=current_user.roles,
        scope=current_user.scope,
        plan=current_user.plan,
        email=current_user.email,
    )
