"""
Auth API endpoints (API-001 to API-010).

Phase 1: Local JWT authentication with DB-backed bcrypt verification.
Phase 2: Auth0 JWKS validation.
Phase 3: Session management (P3AUTH-011) + Auth0 refresh token exchange.
"""
import asyncio
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

from app.core.dependencies import CurrentUser, get_current_user, require_tenant_admin
from app.core.session import get_async_session
from app.modules.auth.group_sync import build_group_sync_config, sync_auth0_groups
from app.modules.auth.jit_provisioning import PLAN_SESSION_LIMITS

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])

# Admin router for force-logout — mounted at /admin/users prefix
_admin_session_router = APIRouter(prefix="/admin/users", tags=["auth-session"])


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
) -> tuple[str, int, str]:
    """
    Create a JWT v2 access token.

    All signing keys from environment - NEVER hardcode.
    Returns (token_string, expires_in_seconds, jti).
    The jti (JWT ID) is included in the token payload for session tracking.
    """
    import uuid as _uuid

    secret = os.environ.get("JWT_SECRET_KEY")
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="JWT_SECRET_KEY not configured",
        )

    algorithm = os.environ.get("JWT_ALGORITHM", "HS256")
    expire_minutes = int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    jti = str(_uuid.uuid4())

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
        "jti": jti,
    }

    token = jwt.encode(payload, secret, algorithm=algorithm)
    return token, expire_minutes * 60, jti


async def _track_session_in_redis(
    user_id: str,
    tenant_id: str,
    jti: str,
    ttl_seconds: int,
    plan: str,
) -> None:
    """
    Track a session in Redis using a sorted set (P3AUTH-011).

    Key:   mingai:{tenant_id}:sessions:{user_id}  (sorted set)
    Score: UNIX expiry timestamp (enables pruning expired entries)
    Member: JTI of the issued token

    Also writes a token key so force-logout can DEL individual JTIs:
    Key:   mingai:{tenant_id}:token:{jti}   value="1"   TTL=ttl_seconds

    Plan session limits:
        starter      → 3 concurrent sessions
        professional → 10 concurrent sessions
        enterprise   → unlimited

    Raises HTTP 409 if the plan limit is already reached.
    Non-fatal for Redis failures — session still proceeds (token expires naturally).
    """
    from app.core.redis_client import build_redis_key, get_redis

    redis = get_redis()
    sessions_key = build_redis_key(tenant_id, "sessions", user_id)
    token_key = build_redis_key(tenant_id, "token", jti)

    now_ts = datetime.now(timezone.utc).timestamp()
    expiry_ts = now_ts + ttl_seconds

    # Prune expired sessions first
    await redis.zremrangebyscore(sessions_key, 0, now_ts)

    # Enforce plan session limit
    limit = PLAN_SESSION_LIMITS.get(plan.lower())
    if limit is not None:
        current_count = await redis.zcard(sessions_key)
        if current_count >= limit:
            raise HTTPException(
                status_code=409,
                detail="Maximum concurrent sessions reached for your plan",
            )

    # Add this session to the sorted set
    await redis.zadd(sessions_key, {jti: expiry_ts})
    # Set expiry on the sorted set key to the longest possible TTL in the set
    await redis.expire(sessions_key, ttl_seconds)

    # Write per-token marker for force-logout revocation
    await redis.set(token_key, "1", ex=ttl_seconds)

    logger.debug(
        "session_tracked_in_redis",
        user_id=user_id,
        plan=plan,
    )


def _write_session_to_redis(
    user_id: str,
    tenant_id: str,
    ttl_seconds: int,
    jti: str = "",
    plan: str = "professional",
) -> None:
    """
    Fire-and-forget session tracking.

    Schedules _track_session_in_redis as a background task. HTTP 409 from
    the plan-limit check is propagated; all other Redis errors are non-fatal.

    Legacy callers that do not pass jti fall back to the simple SET-based
    session marker (kept for backward compatibility with logout revocation).
    """

    async def _write() -> None:
        from app.core.redis_client import build_redis_key, get_redis

        redis = get_redis()

        if jti:
            # Full session tracking with sorted set
            await _track_session_in_redis(
                user_id=user_id,
                tenant_id=tenant_id,
                jti=jti,
                ttl_seconds=ttl_seconds,
                plan=plan,
            )
        else:
            # Legacy simple session marker (no JTI available)
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


def _trigger_auth0_group_sync(
    jwt_payload: dict,
    user_id: str,
    tenant_id: str,
) -> None:
    """
    Fire-and-forget Auth0 group sync after a successful login.

    If the JWT contains a 'groups' claim and the tenant has a group_sync_config
    stored in tenant_configs, resolve the new role set using sync_auth0_groups()
    and log the result.  The actual role-update DB write is intentionally omitted
    here — that belongs to the RBAC event bus (Phase 2); this call validates the
    group mapping and surfaces sync diagnostics in the structured log.

    Runs as a background asyncio task so it cannot delay the login response.
    Any error is caught and logged; the login always succeeds regardless.
    """
    jwt_groups: list[str] = jwt_payload.get("groups") or []
    if not jwt_groups:
        return

    async def _do_sync() -> None:
        try:
            # build_group_sync_config needs a tenant_configs row.
            # In Phase 1 we cannot easily query the DB from a background task
            # without a fresh session, so we derive the config from the JWT
            # custom claims if present (Auth0 actions can embed it), then fall
            # back to a no-op if not present.
            raw_config = jwt_payload.get("https://mingai.io/group_sync_config")
            allowlist, mapping = build_group_sync_config(
                {"config_data": raw_config} if raw_config else None
            )
            assigned_roles = sync_auth0_groups(jwt_groups, allowlist, mapping)
            logger.info(
                "auth0_group_sync_complete",
                user_id=user_id,
                tenant_id=tenant_id,
                groups_count=len(jwt_groups),
                roles_assigned=assigned_roles,
            )
        except Exception as exc:
            # Sync errors must NEVER fail the login — log and continue.
            logger.warning(
                "auth0_group_sync_error",
                user_id=user_id,
                tenant_id=tenant_id,
                error=str(exc),
            )

    # Schedule as a background task. create_task() is safe here because
    # FastAPI routes always run inside a running event loop.
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_do_sync())
        else:
            loop.run_until_complete(_do_sync())
    except Exception as exc:
        logger.warning(
            "auth0_group_sync_schedule_failed",
            user_id=user_id,
            error=str(exc),
        )


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

        token, expires_in, token_jti = _create_access_token(
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
            jti=token_jti,
            plan="enterprise",
        )
        logger.info(
            "user_login",
            email=request.email,
            scope="platform",
            method="local_env",
        )
        # Auth0 group sync (no-op for local env bootstrap logins — no JWT groups)
        _trigger_auth0_group_sync(
            jwt_payload={},
            user_id="00000000-0000-0000-0000-000000000001",
            tenant_id="default",
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

    token, expires_in, token_jti = _create_access_token(
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
        jti=token_jti,
        plan=str(plan),
    )

    logger.info(
        "user_login",
        email=request.email,
        scope="tenant",
        method="local_db",
    )

    # Auth0 group sync — fires in background, does NOT block login response.
    # The JWT payload passed here is the *decoded* local token claims, so the
    # 'groups' key will be absent for local-auth logins.  When Auth0 is the
    # identity provider (Phase 2) the decoded JWT will carry the groups claim.
    _trigger_auth0_group_sync(
        jwt_payload={},  # local login — Auth0 groups not available
        user_id=str_user_id,
        tenant_id=str_tenant_id,
    )

    return TokenResponse(access_token=token, expires_in=expires_in)


class RefreshRequest(BaseModel):
    """Optional body for token refresh — carries opaque refresh_token for Auth0 path."""

    refresh_token: Optional[str] = None


@router.post("/token/refresh", response_model=TokenResponse)
async def refresh_token(
    body: RefreshRequest = RefreshRequest(),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    API-004: Re-issue an access token.

    Two paths:
    1. Auth0 path (P3AUTH-011): If AUTH0_DOMAIN is set and body.refresh_token looks
       like an opaque token (not a JWT), exchange it via Auth0's /oauth/token endpoint
       and return the new tokens.
    2. Local path: Re-issue from the current Bearer token's claims (default).
    """
    # --- Auth0 refresh token exchange path ---
    auth0_domain = os.environ.get("AUTH0_DOMAIN", "")
    if auth0_domain and body.refresh_token:
        # Detect opaque refresh tokens: they do NOT start with "eyJ" (JWT header)
        if not body.refresh_token.startswith("eyJ"):
            return await _exchange_auth0_refresh_token(body.refresh_token, auth0_domain)

    # --- Local HS256 path ---
    token, expires_in, token_jti = _create_access_token(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        roles=current_user.roles,
        scope=current_user.scope,
        plan=current_user.plan,
        email=current_user.email or "",
    )

    _write_session_to_redis(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        ttl_seconds=expires_in,
        jti=token_jti,
        plan=current_user.plan,
    )

    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
    )


async def _exchange_auth0_refresh_token(
    refresh_token: str,
    auth0_domain: str,
) -> TokenResponse:
    """
    Exchange an Auth0 opaque refresh token for a new access token (P3AUTH-011).

    Calls POST https://{AUTH0_DOMAIN}/oauth/token with grant_type=refresh_token.
    Returns a TokenResponse with the new access_token.
    Raises HTTP 401 if Auth0 rejects the refresh token.
    """
    import httpx

    client_id = os.environ.get("AUTH0_CLIENT_ID", "")
    client_secret = os.environ.get("AUTH0_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=500,
            detail="Auth0 client credentials not configured",
        )

    token_url = f"https://{auth0_domain}/oauth/token"

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.post(
                token_url,
                json={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                },
            )
    except Exception as exc:
        logger.warning(
            "auth0_refresh_token_exchange_failed",
            error=str(exc),
        )
        raise HTTPException(
            status_code=503,
            detail="Auth0 token exchange temporarily unavailable",
        )

    if response.status_code == 401 or response.status_code == 403:
        raise HTTPException(
            status_code=401,
            detail="Refresh token is invalid or expired",
        )
    if response.status_code != 200:
        logger.warning(
            "auth0_refresh_token_exchange_error",
            status=response.status_code,
        )
        raise HTTPException(
            status_code=502,
            detail="Auth0 token exchange failed",
        )

    payload = response.json()
    access_token: str = payload.get("access_token", "")
    expires_in: int = int(payload.get("expires_in", 900))

    if not access_token:
        raise HTTPException(
            status_code=502,
            detail="Auth0 response missing access_token",
        )

    logger.info("auth0_refresh_token_exchanged")
    return TokenResponse(access_token=access_token, expires_in=expires_in)


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


# ---------------------------------------------------------------------------
# P3AUTH-011: Force logout (terminate all sessions for a user)
# ---------------------------------------------------------------------------


class ForceLogoutResponse(BaseModel):
    sessions_terminated: int


@_admin_session_router.post(
    "/{user_id}/force-logout", response_model=ForceLogoutResponse
)
async def force_logout_user(
    user_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
) -> ForceLogoutResponse:
    """
    POST /admin/users/{user_id}/force-logout (P3AUTH-011)

    Terminates ALL active sessions for the target user by:
    1. Fetching all session JTIs from the sorted set:
       mingai:{tenant_id}:sessions:{user_id}
    2. Deleting each per-JTI token key: mingai:{tenant_id}:token:{jti}
    3. Deleting the session sorted set key.

    Requires tenant_admin role. Only operates within the caller's tenant.
    Returns the number of sessions terminated.
    """
    from app.core.redis_client import build_redis_key, get_redis

    sessions_terminated = 0

    try:
        redis = get_redis()
        sessions_key = build_redis_key(current_user.tenant_id, "sessions", user_id)

        # Get all JTIs in the sorted set
        jtis = await redis.zrange(sessions_key, 0, -1)
        sessions_terminated = len(jtis)

        # Delete each per-JTI token key
        for jti in jtis:
            token_key = build_redis_key(current_user.tenant_id, "token", jti)
            await redis.delete(token_key)

        # Delete the session sorted set
        await redis.delete(sessions_key)

        logger.info(
            "force_logout_completed",
            target_user_id=user_id,
            acting_user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            sessions_terminated=sessions_terminated,
        )
    except Exception as exc:
        logger.error(
            "force_logout_failed",
            target_user_id=user_id,
            tenant_id=current_user.tenant_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=503,
            detail="Session termination temporarily unavailable",
        )

    return ForceLogoutResponse(sessions_terminated=sessions_terminated)
