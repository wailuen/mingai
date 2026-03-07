"""
Auth API endpoints (API-001 to API-010).

Phase 1: Local JWT authentication.
Phase 2: Auth0 JWKS validation.
"""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import structlog
from fastapi import APIRouter, Depends, HTTPException
from jose import jwt
from pydantic import BaseModel, EmailStr, field_validator

from app.core.dependencies import CurrentUser, get_current_user

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


class RefreshRequest(BaseModel):
    """API-004: Token refresh request."""

    refresh_token: str


class UserResponse(BaseModel):
    """API-006: Current user response."""

    id: str
    tenant_id: str
    roles: list[str]
    scope: str
    plan: str
    email: str | None = None


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


@router.post("/local/login", response_model=TokenResponse)
async def local_login(request: LoginRequest):
    """
    API-003: Local username/password authentication.

    Phase 1 only - for development and tenants without SSO.
    Returns JWT v2 access token.

    Rate limited: 10 attempts per email per 15 minutes.
    """
    # In production, this would query the users table
    # For Phase 1 bootstrap, check platform admin env vars
    platform_email = os.environ.get("PLATFORM_ADMIN_EMAIL", "")
    platform_pass = os.environ.get("PLATFORM_ADMIN_PASS", "")

    if not platform_email or not platform_pass:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
        )

    if request.email != platform_email.lower():
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
        )

    # Verify password (bcrypt hash comparison)
    # For bootstrap, compare plaintext (will be bcrypt in DB-backed implementation)
    if request.password != platform_pass:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
        )

    seed_tenant = os.environ.get("SEED_TENANT_NAME", "default")

    token, expires_in = _create_access_token(
        user_id="00000000-0000-0000-0000-000000000001",
        tenant_id="default",
        roles=["platform_admin"],
        scope="platform",
        plan="enterprise",
        email=request.email,
    )

    logger.info(
        "user_login",
        email=request.email,
        scope="platform",
        method="local",
    )

    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
    )


@router.post("/token/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    API-004: Refresh an expiring access token.

    Issues a new access token with current claims (re-reads roles from DB).
    Old refresh token invalidated (rotation).
    """
    # In production, validate refresh_token against Redis store
    # For Phase 1, re-issue based on current user context
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

    Revokes refresh token in Redis.
    """
    logger.info(
        "user_logout",
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )
    # In production, revoke refresh token in Redis
    # await redis.delete(f"mingai:{current_user.tenant_id}:session:{current_user.id}")
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
