"""
SSO user import API (TA-033).

Endpoints:
- GET  /admin/sso/directory/users         — list IdP users from Auth0
- POST /admin/users/import-from-sso       — batch-import selected users

Auth0 org_id is read from tenant_configs.config_data under key
'sso_config.auth0_org_id'.  If the tenant has no such config row the
directory endpoint returns 404 with an explanatory message.

All imports are logged to audit_log.
require_tenant_admin is enforced on both endpoints.
"""
import json
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session
from app.modules.auth.management_api import management_api_request

logger = structlog.get_logger()

router = APIRouter(tags=["admin-sso"])

_MAX_IMPORT_BATCH = 50


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SSODirectoryUser(BaseModel):
    auth0_user_id: str
    email: str
    name: Optional[str] = None
    groups: list[str] = Field(default_factory=list)


class SSODirectoryResponse(BaseModel):
    users: list[SSODirectoryUser]
    total: int


class ImportFromSSORequest(BaseModel):
    auth0_user_ids: list[str] = Field(..., description="Auth0 user IDs to import")

    @field_validator("auth0_user_ids")
    @classmethod
    def validate_batch_size(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("auth0_user_ids must not be empty")
        if len(v) > _MAX_IMPORT_BATCH:
            raise ValueError(
                f"auth0_user_ids may not exceed {_MAX_IMPORT_BATCH} entries per batch"
            )
        return v


class ImportFailedUser(BaseModel):
    auth0_user_id: str
    reason: str


class ImportFromSSOResponse(BaseModel):
    created: int
    skipped: int
    failed: list[ImportFailedUser]


# ---------------------------------------------------------------------------
# DB helpers (injectable in unit tests)
# ---------------------------------------------------------------------------


async def get_tenant_auth0_org_id(tenant_id: str, db: AsyncSession) -> Optional[str]:
    """
    Return Auth0 org_id from tenant_configs where config_type = 'sso_config'.

    Returns None if no such config row exists or the key is absent.
    """
    result = await db.execute(
        text(
            "SELECT config_data FROM tenant_configs "
            "WHERE tenant_id = :tenant_id AND config_type = 'sso_config' "
            "LIMIT 1"
        ),
        {"tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    config_data = row[0]
    if isinstance(config_data, str):
        config_data = json.loads(config_data)
    return config_data.get("auth0_org_id")


async def find_existing_users_by_auth0_ids(
    auth0_user_ids: list[str],
    tenant_id: str,
    db: AsyncSession,
) -> set[str]:
    """Return the subset of auth0_user_ids already present in this tenant."""
    if not auth0_user_ids:
        return set()
    result = await db.execute(
        text(
            "SELECT auth0_user_id FROM users "
            "WHERE tenant_id = :tenant_id "
            "AND auth0_user_id = ANY(CAST(:ids AS text[]))"
        ),
        {"tenant_id": tenant_id, "ids": auth0_user_ids},
    )
    return {row[0] for row in result.fetchall()}


async def create_imported_user(
    auth0_user_id: str,
    email: str,
    name: Optional[str],
    tenant_id: str,
    db: AsyncSession,
) -> Optional[str]:
    """
    Insert a new user row for an SSO-imported user.

    Returns the new user UUID on success, None if the email already exists
    (unique constraint violation handled gracefully).
    """
    new_id = str(uuid.uuid4())
    try:
        await db.execute(
            text(
                "INSERT INTO users "
                "(id, tenant_id, auth0_user_id, email, name, role, status) "
                "VALUES (:id, :tenant_id, :auth0_user_id, :email, :name, 'viewer', 'invited')"
            ),
            {
                "id": new_id,
                "tenant_id": tenant_id,
                "auth0_user_id": auth0_user_id,
                "email": email,
                "name": name,
            },
        )
    except IntegrityError:
        await db.rollback()
        return None
    return new_id


async def log_sso_import_audit(
    actor_id: str,
    tenant_id: str,
    created_count: int,
    skipped_count: int,
    failed_count: int,
    db: AsyncSession,
) -> None:
    """Write a single audit_log entry summarising the import operation."""
    await db.execute(
        text(
            "INSERT INTO audit_log "
            "(id, tenant_id, user_id, action, resource_type, resource_id, details) "
            "VALUES (:id, :tenant_id, :user_id, 'sso_import', 'user', NULL, "
            "CAST(:details AS jsonb))"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "user_id": actor_id,
            "details": json.dumps(
                {
                    "created": created_count,
                    "skipped": skipped_count,
                    "failed": failed_count,
                }
            ),
        },
    )


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get(
    "/admin/sso/directory/users",
    response_model=SSODirectoryResponse,
    status_code=status.HTTP_200_OK,
)
async def list_sso_directory_users(
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> SSODirectoryResponse:
    """
    TA-033: List IdP users from Auth0 for the calling tenant.

    Reads the tenant's Auth0 Organization ID from tenant_configs then calls
    GET /api/v2/organizations/{org_id}/members.  Returns up to 200 users.

    Returns 404 if the tenant has no sso_config stored.
    Returns 422 if AUTH0_DOMAIN is not configured.
    """
    import os

    if not os.environ.get("AUTH0_DOMAIN"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Auth0 not configured for this tenant",
        )

    org_id = await get_tenant_auth0_org_id(current_user.tenant_id, db)
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Auth0 organization not configured for this tenant",
        )

    try:
        data = await management_api_request(
            "GET",
            f"organizations/{org_id}/members?per_page=200&include_totals=false",
        )
    except RuntimeError as exc:
        logger.error(
            "sso_directory_auth0_error",
            tenant_id=current_user.tenant_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to retrieve users from Auth0",
        )

    # Auth0 /organizations/{id}/members returns a list directly (no wrapper key
    # when include_totals=false). Normalise to list.
    raw_members: list = data if isinstance(data, list) else data.get("members", [])

    users: list[SSODirectoryUser] = []
    for member in raw_members[:200]:
        users.append(
            SSODirectoryUser(
                auth0_user_id=member.get("user_id", ""),
                email=member.get("email", ""),
                name=member.get("name"),
                groups=[],
            )
        )

    logger.info(
        "sso_directory_listed",
        tenant_id=current_user.tenant_id,
        count=len(users),
    )
    return SSODirectoryResponse(users=users, total=len(users))


@router.post(
    "/admin/users/import-from-sso",
    response_model=ImportFromSSOResponse,
    status_code=status.HTTP_200_OK,
)
async def import_users_from_sso(
    request: ImportFromSSORequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_async_session),
) -> ImportFromSSOResponse:
    """
    TA-033: Batch-import users from Auth0 into the tenant.

    For each auth0_user_id:
    - If already exists in users table (by auth0_user_id): skip.
    - Otherwise: fetch user profile from Auth0, create user with
      role=viewer, status=invited.

    Records a single audit_log entry on completion.
    Max 50 user IDs per call.
    """
    tenant_id = current_user.tenant_id

    # --- determine which IDs already exist in this tenant ---
    already_exists = await find_existing_users_by_auth0_ids(
        request.auth0_user_ids, tenant_id, db
    )

    created = 0
    skipped = len(already_exists)
    failed: list[ImportFailedUser] = []

    ids_to_create = [uid for uid in request.auth0_user_ids if uid not in already_exists]

    for auth0_uid in ids_to_create:
        # Fetch individual user profile from Auth0 to get email/name
        try:
            encoded_uid = auth0_uid.replace("|", "%7C")
            profile = await management_api_request("GET", f"users/{encoded_uid}")
        except RuntimeError as exc:
            logger.warning(
                "sso_import_profile_fetch_failed",
                auth0_user_id=auth0_uid,
                tenant_id=tenant_id,
                error=str(exc),
            )
            failed.append(
                ImportFailedUser(
                    auth0_user_id=auth0_uid,
                    reason="failed to fetch user profile from Auth0",
                )
            )
            continue

        email: str = profile.get("email", "")
        name: Optional[str] = profile.get("name")

        if not email:
            failed.append(
                ImportFailedUser(
                    auth0_user_id=auth0_uid,
                    reason="Auth0 profile has no email address",
                )
            )
            continue

        new_user_id = await create_imported_user(
            auth0_user_id=auth0_uid,
            email=email,
            name=name,
            tenant_id=tenant_id,
            db=db,
        )
        if new_user_id is None:
            # Email already exists in tenant (via local account) — count as skipped
            skipped += 1
            logger.info(
                "sso_import_user_skipped_email_conflict",
                auth0_user_id=auth0_uid,
                tenant_id=tenant_id,
            )
        else:
            created += 1
            logger.info(
                "sso_import_user_created",
                user_id=new_user_id,
                tenant_id=tenant_id,
            )

    # Audit log entry
    await log_sso_import_audit(
        actor_id=current_user.id,
        tenant_id=tenant_id,
        created_count=created,
        skipped_count=skipped,
        failed_count=len(failed),
        db=db,
    )

    await db.commit()

    logger.info(
        "sso_import_completed",
        tenant_id=tenant_id,
        created=created,
        skipped=skipped,
        failed=len(failed),
    )

    return ImportFromSSOResponse(
        created=created,
        skipped=skipped,
        failed=failed,
    )
