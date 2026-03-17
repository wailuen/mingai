"""
Auth0 group claim sync service.

When a user authenticates via Auth0, their JWT may contain a 'groups' claim
listing the Auth0 groups they belong to. This service maps those groups to
mingai roles using a tenant-configured allowlist + group-role mapping.

Only groups on the tenant's allowlist are processed — all others are ignored.

Team membership sync (DEF-008):
    `sync_team_memberships_db()` resolves which `tenant_teams` rows are matched
    by the incoming groups (via `auth0_group_name` column) and performs an
    idempotent upsert/delete cycle on `team_memberships`.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# Default roles available for group mapping
MAPPABLE_ROLES = {"admin", "user", "viewer", "editor"}


def sync_auth0_groups(
    jwt_groups: list[str],
    allowlist: list[str],
    group_role_mapping: dict[str, str],
) -> list[str]:
    """
    Resolve which mingai roles should be granted based on Auth0 group claims.

    Args:
        jwt_groups: Groups from Auth0 JWT 'groups' claim.
        allowlist: Tenant-configured list of allowed group names to process.
                   Empty list means no groups are synced.
        group_role_mapping: Mapping of group name -> mingai role.
                            Groups not in this mapping grant no role.

    Returns:
        List of mingai role strings to assign to the user.
        Empty list if no groups match or allowlist is empty.
    """
    if not allowlist:
        logger.debug("auth0_group_sync_skipped", reason="empty_allowlist")
        return []

    if not jwt_groups:
        logger.debug("auth0_group_sync_skipped", reason="no_jwt_groups")
        return []

    allowed_set = set(allowlist)
    assigned_roles: list[str] = []

    for group in jwt_groups:
        if group not in allowed_set:
            logger.debug(
                "auth0_group_not_in_allowlist",
                group=group,
            )
            continue

        role = group_role_mapping.get(group)
        if role is None:
            logger.debug(
                "auth0_group_no_role_mapping",
                group=group,
            )
            continue

        if role not in MAPPABLE_ROLES:
            logger.warning(
                "auth0_group_invalid_role",
                group=group,
                role=role,
                valid_roles=list(MAPPABLE_ROLES),
            )
            continue

        if role not in assigned_roles:
            assigned_roles.append(role)
            logger.info(
                "auth0_group_role_assigned",
                group=group,
                role=role,
            )

    return assigned_roles


def build_group_sync_config(
    tenant_configs_row: Optional[dict],
) -> tuple[list[str], dict[str, str]]:
    """
    Extract allowlist and group-role mapping from a tenant_configs row.

    Returns:
        (allowlist, group_role_mapping) tuple.
        Both empty if no config row or missing keys.
    """
    if not tenant_configs_row:
        return [], {}

    config_data = tenant_configs_row.get("config_data") or {}
    allowlist = config_data.get("auth0_group_allowlist") or []
    mapping = config_data.get("auth0_group_role_mapping") or {}

    return allowlist, mapping


# ---------------------------------------------------------------------------
# DEF-008: Team membership sync helpers
# ---------------------------------------------------------------------------


async def _get_teams_by_auth0_groups(
    tenant_id: str,
    groups: list[str],
    db: AsyncSession,
) -> list[dict]:
    """
    Look up tenant_teams rows whose auth0_group_name matches one of the
    provided groups.

    Returns a list of dicts with keys: id (UUID str), name (str), auth0_group_name (str).
    Returns empty list if `groups` is empty.
    """
    if not groups:
        return []

    # Parameterized ANY(:groups) query — no f-string interpolation of user data.
    result = await db.execute(
        text(
            "SELECT id, name, auth0_group_name "
            "FROM tenant_teams "
            "WHERE tenant_id = CAST(:tenant_id AS uuid) "
            "  AND auth0_group_name = ANY(:groups)"
        ),
        {"tenant_id": tenant_id, "groups": groups},
    )
    rows = result.fetchall()
    return [
        {"id": str(row[0]), "name": str(row[1]), "auth0_group_name": str(row[2])}
        for row in rows
    ]


async def _get_current_team_memberships(
    tenant_id: str,
    user_id: str,
    db: AsyncSession,
) -> list[str]:
    """
    Return the list of team_id (UUID str) that the user currently belongs to
    within the given tenant, filtered to teams that have an auth0_group_name
    (i.e. those managed via group sync).

    Only group-synced teams are considered for removal — manually-added
    memberships (source='manual') in non-synced teams are never touched.
    """
    result = await db.execute(
        text(
            "SELECT tm.team_id::text "
            "FROM team_memberships tm "
            "JOIN tenant_teams tt ON tt.id = tm.team_id "
            "WHERE tm.tenant_id = CAST(:tenant_id AS uuid) "
            "  AND tm.user_id = CAST(:user_id AS uuid) "
            "  AND tt.auth0_group_name IS NOT NULL"
        ),
        {"tenant_id": tenant_id, "user_id": user_id},
    )
    return [str(row[0]) for row in result.fetchall()]


async def _upsert_team_membership(
    team_id: str,
    user_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> bool:
    """
    Upsert a team_memberships row with source='group_sync'.

    Returns True if a new row was inserted, False if the row already existed.
    """
    result = await db.execute(
        text(
            "INSERT INTO team_memberships (team_id, user_id, tenant_id, source, added_at) "
            "VALUES (CAST(:team_id AS uuid), CAST(:user_id AS uuid), "
            "        CAST(:tenant_id AS uuid), 'group_sync', :now) "
            "ON CONFLICT (team_id, user_id) DO NOTHING"
        ),
        {
            "team_id": team_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "now": datetime.now(timezone.utc),
        },
    )
    inserted = (result.rowcount or 0) > 0
    return inserted


async def _delete_team_membership(
    team_id: str,
    user_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> bool:
    """
    Remove a team_memberships row.

    Returns True if a row was deleted, False if it did not exist.
    """
    result = await db.execute(
        text(
            "DELETE FROM team_memberships "
            "WHERE team_id = CAST(:team_id AS uuid) "
            "  AND user_id = CAST(:user_id AS uuid) "
            "  AND tenant_id = CAST(:tenant_id AS uuid)"
        ),
        {"team_id": team_id, "user_id": user_id, "tenant_id": tenant_id},
    )
    deleted = (result.rowcount or 0) > 0
    return deleted


async def _write_team_membership_audit(
    tenant_id: str,
    user_id: str,
    teams_added: list[str],
    teams_removed: list[str],
    groups: list[str],
    db: AsyncSession,
) -> None:
    """
    Write a single audit_log entry for team_membership.sync when any change
    occurred.  Uses the canonical audit_log schema: user_id + details columns.
    """
    if not teams_added and not teams_removed:
        return

    await db.execute(
        text(
            "INSERT INTO audit_log "
            "(id, tenant_id, user_id, action, resource_type, details, created_at) "
            "VALUES "
            "(CAST(:id AS uuid), CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), "
            " 'team_membership.sync', 'team_membership', "
            " CAST(:details AS jsonb), :now)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "details": json.dumps(
                {
                    "teams_added": teams_added,
                    "teams_removed": teams_removed,
                    "groups_matched": groups,
                    "synced_by": "auth0_group_sync",
                }
            ),
            "now": datetime.now(timezone.utc),
        },
    )


async def sync_team_memberships_db(
    tenant_id: str,
    user_id: str,
    groups: list[str],
    db: AsyncSession,
) -> dict:
    """
    Idempotent sync of team_memberships based on Auth0 group claims.

    Logic:
    1. Look up tenant_teams that match the incoming groups via auth0_group_name.
    2. Fetch the user's current group-synced team memberships.
    3. Upsert membership for each matched team (adds missing ones).
    4. Remove memberships for group-synced teams that are no longer matched.
    5. Write an audit_log entry when any change occurred.

    This function does NOT call db.commit() — the caller must commit.

    Args:
        tenant_id: UUID string of the tenant.
        user_id:   UUID string of the user.
        groups:    List of Auth0 group names from the JWT 'groups' claim.
        db:        Async SQLAlchemy session (RLS bypass expected by the caller).

    Returns:
        dict with keys:
            added   — list of team_id strings that were added
            removed — list of team_id strings that were removed
    """
    # Step 1: resolve matched teams
    matched_teams = await _get_teams_by_auth0_groups(tenant_id, groups, db)
    matched_team_ids: set[str] = {t["id"] for t in matched_teams}

    # Step 2: current group-synced memberships
    current_team_ids: list[str] = await _get_current_team_memberships(
        tenant_id, user_id, db
    )
    current_set: set[str] = set(current_team_ids)

    # Step 3: upsert for all matched teams
    teams_added: list[str] = []
    for team in matched_teams:
        inserted = await _upsert_team_membership(
            team_id=team["id"],
            user_id=user_id,
            tenant_id=tenant_id,
            db=db,
        )
        if inserted:
            teams_added.append(team["id"])
            logger.info(
                "team_membership_added",
                user_id=user_id,
                team_id=team["id"],
                tenant_id=tenant_id,
                auth0_group=team["auth0_group_name"],
            )

    # Step 4: remove stale memberships (was synced but group no longer present)
    teams_removed: list[str] = []
    stale_ids = current_set - matched_team_ids
    for stale_team_id in stale_ids:
        deleted = await _delete_team_membership(
            team_id=stale_team_id,
            user_id=user_id,
            tenant_id=tenant_id,
            db=db,
        )
        if deleted:
            teams_removed.append(stale_team_id)
            logger.info(
                "team_membership_removed",
                user_id=user_id,
                team_id=stale_team_id,
                tenant_id=tenant_id,
            )

    # Step 5: audit if any change
    matched_group_names = [t["auth0_group_name"] for t in matched_teams]
    await _write_team_membership_audit(
        tenant_id=tenant_id,
        user_id=user_id,
        teams_added=teams_added,
        teams_removed=teams_removed,
        groups=matched_group_names,
        db=db,
    )

    return {"added": teams_added, "removed": teams_removed}
