"""
JIT (Just-In-Time) provisioning endpoint (P3AUTH-008) and group-to-role sync (P3AUTH-009).

Internal-only endpoints called by the Auth0 Post-Login Action.
Authentication: X-Internal-Secret header matched against INTERNAL_SECRET_KEY env var.
This is NOT a public API endpoint — it is mounted under /internal/ in main.py.

Security notes:
- No JWT auth (Auth0 calls this before issuing the JWT).
- X-Internal-Secret must match INTERNAL_SECRET_KEY via constant-time comparison.
- All DB queries are RLS-bypassed via set_config('app.bypass_rls', 'on') — this call
  originates from Auth0, not from an end-user tenant context.
- No PII (email, name) is written to logs — only user_id (UUID) and auth0_user_id.
"""
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import get_async_session
from app.modules.auth.group_sync import sync_team_memberships_db

logger = structlog.get_logger()

internal_router = APIRouter(prefix="/users", tags=["internal"])


# ---------------------------------------------------------------------------
# Plan → session limit mapping (P3AUTH-011)
# ---------------------------------------------------------------------------

PLAN_SESSION_LIMITS: dict[str, Optional[int]] = {
    "starter": 3,
    "professional": 10,
    "enterprise": None,  # unlimited
}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class JITProvisionRequest(BaseModel):
    """Auth0 Post-Login Action payload for JIT user provisioning."""

    auth0_user_id: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=3, max_length=254)
    name: Optional[str] = Field(None, max_length=200)
    tenant_id: str = Field(..., min_length=1, max_length=255)
    groups: list[str] = Field(default_factory=list)


class JITProvisionResponse(BaseModel):
    action: str  # "created" | "updated"
    user_id: str


class SyncRolesRequest(BaseModel):
    """Auth0 Post-Login Action payload for group-to-role sync (P3AUTH-009)."""

    auth0_user_id: str = Field(..., min_length=1, max_length=255)
    groups: list[str] = Field(default_factory=list)
    tenant_id: str = Field(..., min_length=1, max_length=255)


class SyncRolesResponse(BaseModel):
    action: str  # "role_synced" | "no_change" | "noop"
    new_role: Optional[str] = None
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Authentication helper
# ---------------------------------------------------------------------------


def _verify_internal_secret(header_value: Optional[str]) -> None:
    """
    Validate X-Internal-Secret against INTERNAL_SECRET_KEY env var.

    Raises HTTP 401 if:
    - INTERNAL_SECRET_KEY is not configured in the environment.
    - The header is missing or does not match (constant-time comparison).
    """
    expected = os.environ.get("INTERNAL_SECRET_KEY", "")
    if not expected:
        logger.warning(
            "jit_provision_rejected_no_secret_configured",
            reason="INTERNAL_SECRET_KEY not set",
        )
        raise HTTPException(
            status_code=401,
            detail="Internal authentication not configured",
        )

    if not header_value:
        raise HTTPException(
            status_code=401,
            detail="X-Internal-Secret header required",
        )

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(header_value, expected):
        logger.warning("jit_provision_rejected_bad_secret")
        raise HTTPException(
            status_code=401,
            detail="Invalid internal secret",
        )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _bypass_rls(db: AsyncSession) -> None:
    """
    Set bypass_rls config for this session.

    JIT calls originate from Auth0 (no tenant context), so we bypass RLS
    to query users by auth0_user_id without a tenant context set.
    """
    await db.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))


async def _lookup_user_by_auth0_id(
    auth0_user_id: str,
    db: AsyncSession,
) -> Optional[dict]:
    """Fetch user row by auth0_user_id. Returns dict or None."""
    result = await db.execute(
        text(
            "SELECT id, tenant_id, status "
            "FROM users "
            "WHERE auth0_user_id = :auth0_user_id "
            "LIMIT 1"
        ),
        {"auth0_user_id": auth0_user_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {"id": str(row[0]), "tenant_id": str(row[1]), "status": str(row[2])}


async def _update_last_login(user_id: str, db: AsyncSession) -> None:
    """Update last_login_at for an existing user."""
    await db.execute(
        text(
            "UPDATE users SET last_login_at = :now " "WHERE id = CAST(:user_id AS uuid)"
        ),
        {"now": datetime.now(timezone.utc), "user_id": user_id},
    )


async def _get_jit_default_role(tenant_id: str, db: AsyncSession) -> str:
    """
    Read jit_default_role from the tenant's SSO connection config.

    Returns "viewer" if not configured (fail-safe default).
    """
    result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tid AND config_type = 'sso_connection_config' LIMIT 1"
        ),
        {"tid": tenant_id},
    )
    row = result.fetchone()
    if row is None or row[0] is None:
        return "viewer"
    import json as _json

    data = row[0]
    config = _json.loads(data) if isinstance(data, str) else data
    role = config.get("jit_default_role", "viewer")
    # Safety guard: never grant admin via JIT config
    if role not in {"viewer", "editor"}:
        return "viewer"
    return role


async def _create_user(
    user_id: str,
    auth0_user_id: str,
    email: str,
    name: Optional[str],
    tenant_id: str,
    db: AsyncSession,
    default_role: str = "viewer",
) -> None:
    """Insert a new user row with configurable default role and status=active."""
    display_name = name or email.split("@")[0]
    # Safety guard: JIT may never create an admin user
    safe_role = default_role if default_role in {"viewer", "editor"} else "viewer"
    await db.execute(
        text(
            "INSERT INTO users "
            "(id, tenant_id, email, name, auth0_user_id, role, status, created_at, updated_at) "
            "VALUES "
            "(CAST(:id AS uuid), CAST(:tenant_id AS uuid), :email, :name, "
            " :auth0_user_id, :role, 'active', :now, :now)"
        ),
        {
            "id": user_id,
            "tenant_id": tenant_id,
            "email": email,
            "name": display_name,
            "auth0_user_id": auth0_user_id,
            "role": safe_role,
            "now": datetime.now(timezone.utc),
        },
    )


async def _write_audit_log(
    actor_id: str,
    resource_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    """
    Write a user.created audit log entry.

    actor_id is the auth0_user_id (opaque string, not a UUID) for the
    self-provisioned case.  We store it in the metadata JSONB column to
    avoid a FK constraint mismatch with the UUID actor_id column.
    """
    await db.execute(
        text(
            "INSERT INTO audit_log "
            "(id, tenant_id, actor_id, action, resource_type, resource_id, "
            " metadata, created_at) "
            "VALUES "
            "(CAST(:id AS uuid), CAST(:tenant_id AS uuid), "
            " NULL, 'user.created', 'user', "
            " CAST(:resource_id AS uuid), "
            " CAST(:meta AS jsonb), :now)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "resource_id": resource_id,
            "meta": json.dumps({"provisioned_by": "auth0", "auth0_user_id": actor_id}),
            "now": datetime.now(timezone.utc),
        },
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@internal_router.post("/jit-provision", response_model=JITProvisionResponse)
async def jit_provision_user(
    request_body: JITProvisionRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
    db: AsyncSession = Depends(get_async_session),
) -> JITProvisionResponse:
    """
    POST /internal/users/jit-provision

    Called by Auth0 Post-Login Action to provision users on first login.

    - First login  → creates user with role=viewer, writes audit_log entry.
    - Repeat login → updates last_login_at only (no duplicate created).
    - Auth: X-Internal-Secret header (NOT JWT).
    """
    _verify_internal_secret(x_internal_secret)

    await _bypass_rls(db)

    existing = await _lookup_user_by_auth0_id(request_body.auth0_user_id, db)

    if existing is not None:
        # Repeat login — update last_login_at only
        await _update_last_login(existing["id"], db)
        await db.commit()

        logger.info(
            "jit_provision_updated",
            user_id=existing["id"],
            tenant_id=existing["tenant_id"],
        )
        return JITProvisionResponse(action="updated", user_id=existing["id"])

    # First login — create user
    new_user_id = str(uuid.uuid4())

    default_role = await _get_jit_default_role(request_body.tenant_id, db)

    await _create_user(
        user_id=new_user_id,
        auth0_user_id=request_body.auth0_user_id,
        email=request_body.email,
        name=request_body.name,
        tenant_id=request_body.tenant_id,
        db=db,
        default_role=default_role,
    )

    await _write_audit_log(
        actor_id=request_body.auth0_user_id,
        resource_id=new_user_id,
        tenant_id=request_body.tenant_id,
        db=db,
    )

    await db.commit()

    logger.info(
        "jit_provision_created",
        user_id=new_user_id,
        tenant_id=request_body.tenant_id,
    )

    return JITProvisionResponse(action="created", user_id=new_user_id)


# ---------------------------------------------------------------------------
# P3AUTH-009: Group-to-role sync helpers
# ---------------------------------------------------------------------------

# Role priority order — higher index = higher privilege
_ROLE_PRIORITY: dict[str, int] = {
    "viewer": 1,
    "editor": 2,
    "user": 2,  # "user" treated same priority as "editor"
    "admin": 3,
}


def _highest_role(roles: list[str]) -> Optional[str]:
    """
    Return the highest-privilege role from a list of matched roles.

    Priority: admin > editor|user > viewer.
    Returns None if the list is empty.
    """
    if not roles:
        return None
    return max(roles, key=lambda r: _ROLE_PRIORITY.get(r, 0))


async def _get_group_sync_mapping(
    tenant_id: str,
    db: AsyncSession,
) -> tuple[list[str], dict[str, str]]:
    """
    Read sso_group_sync config for this tenant from tenant_configs.

    Returns (allowlist, group_role_mapping). Both are empty when not configured.
    """
    result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tid AND config_type = 'sso_group_sync' LIMIT 1"
        ),
        {"tid": tenant_id},
    )
    row = result.fetchone()
    if row is None or row[0] is None:
        return [], {}
    import json as _json

    data = row[0]
    config = _json.loads(data) if isinstance(data, str) else data
    return (
        config.get("auth0_group_allowlist") or [],
        config.get("auth0_group_role_mapping") or {},
    )


async def _lookup_user_by_auth0_id_full(
    auth0_user_id: str,
    db: AsyncSession,
) -> Optional[dict]:
    """Fetch user row by auth0_user_id including role. Returns dict or None."""
    result = await db.execute(
        text(
            "SELECT id, tenant_id, role "
            "FROM users "
            "WHERE auth0_user_id = :auth0_user_id "
            "LIMIT 1"
        ),
        {"auth0_user_id": auth0_user_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "tenant_id": str(row[1]),
        "role": str(row[2]),
    }


async def _update_user_role(
    user_id: str,
    new_role: str,
    db: AsyncSession,
) -> None:
    """Update users.role for an existing user."""
    await db.execute(
        text(
            "UPDATE users SET role = :role, updated_at = :now "
            "WHERE id = CAST(:user_id AS uuid)"
        ),
        {"role": new_role, "now": datetime.now(timezone.utc), "user_id": user_id},
    )


async def _write_role_sync_audit_log(
    user_id: str,
    tenant_id: str,
    old_role: str,
    new_role: str,
    groups_matched: list[str],
    db: AsyncSession,
) -> None:
    """Write a user.role.sync audit log entry."""
    import json as _json

    await db.execute(
        text(
            "INSERT INTO audit_log "
            "(id, tenant_id, actor_id, action, resource_type, resource_id, "
            " metadata, created_at) "
            "VALUES "
            "(CAST(:id AS uuid), CAST(:tenant_id AS uuid), "
            " NULL, 'user.role.sync', 'user', "
            " CAST(:resource_id AS uuid), "
            " CAST(:meta AS jsonb), :now)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "resource_id": user_id,
            "meta": _json.dumps(
                {
                    "old_role": old_role,
                    "new_role": new_role,
                    "groups_matched": groups_matched,
                    "synced_by": "auth0_group_sync",
                }
            ),
            "now": datetime.now(timezone.utc),
        },
    )


# ---------------------------------------------------------------------------
# P3AUTH-009: POST /internal/users/sync-roles
# ---------------------------------------------------------------------------


@internal_router.post("/sync-roles", response_model=SyncRolesResponse)
async def sync_user_roles(
    request_body: SyncRolesRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
    db: AsyncSession = Depends(get_async_session),
) -> SyncRolesResponse:
    """
    POST /internal/users/sync-roles

    Called by Auth0 Post-Login Action after JIT provisioning to sync IdP
    group claims to mingai roles.

    Logic:
    1. Authenticate with X-Internal-Secret.
    2. RLS bypass (same as JIT).
    3. Look up user by auth0_user_id. If not found: 404 (JIT must run first).
    4. Read sso_group_sync config from tenant_configs. If not configured: noop.
    5. Find matching roles from group_role_mapping for groups in allowlist.
       Highest-privilege role wins.
    6. If role changed: UPDATE users.role + write audit_log.
    7. Return action and new_role.
    """
    _verify_internal_secret(x_internal_secret)

    await _bypass_rls(db)

    # Step 3: look up user
    user = await _lookup_user_by_auth0_id_full(request_body.auth0_user_id, db)
    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found — JIT provisioning must run before group sync",
        )

    # Step 4: load group sync config
    allowlist, mapping = await _get_group_sync_mapping(request_body.tenant_id, db)
    if not mapping:
        # No mapping configured — no-op
        return SyncRolesResponse(
            action="noop",
            reason="no_mapping_configured",
        )

    # Step 5: find matched roles
    matched_roles: list[str] = []
    groups_matched: list[str] = []
    for group in request_body.groups:
        # Only process groups in the allowlist (if allowlist is non-empty)
        if allowlist and group not in allowlist:
            continue
        if group in mapping:
            matched_roles.append(mapping[group])
            groups_matched.append(group)

    if not matched_roles:
        # No group matched any role mapping entry — teams may still need syncing.
        # Run team membership sync even when no role change occurs (DEF-008).
        await sync_team_memberships_db(
            tenant_id=request_body.tenant_id,
            user_id=user["id"],
            groups=request_body.groups,
            db=db,
        )
        await db.commit()
        return SyncRolesResponse(
            action="no_change",
            new_role=user["role"],
        )

    target_role = _highest_role(matched_roles)
    if target_role is None or target_role == user["role"]:
        # Role unchanged — still sync team memberships (DEF-008).
        await sync_team_memberships_db(
            tenant_id=request_body.tenant_id,
            user_id=user["id"],
            groups=request_body.groups,
            db=db,
        )
        await db.commit()
        return SyncRolesResponse(
            action="no_change",
            new_role=user["role"],
        )

    # Step 6: update role + audit
    await _update_user_role(user_id=user["id"], new_role=target_role, db=db)
    await _write_role_sync_audit_log(
        user_id=user["id"],
        tenant_id=request_body.tenant_id,
        old_role=user["role"],
        new_role=target_role,
        groups_matched=groups_matched,
        db=db,
    )

    # Step 7: sync team_memberships based on Auth0 group claims (DEF-008)
    await sync_team_memberships_db(
        tenant_id=request_body.tenant_id,
        user_id=user["id"],
        groups=request_body.groups,
        db=db,
    )

    await db.commit()

    logger.info(
        "group_sync_role_updated",
        user_id=user["id"],
        tenant_id=request_body.tenant_id,
        old_role=user["role"],
        new_role=target_role,
        groups_matched=groups_matched,
    )

    return SyncRolesResponse(action="role_synced", new_role=target_role)
