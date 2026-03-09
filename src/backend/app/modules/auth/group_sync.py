"""
Auth0 group claim sync service.

When a user authenticates via Auth0, their JWT may contain a 'groups' claim
listing the Auth0 groups they belong to. This service maps those groups to
mingai roles using a tenant-configured allowlist + group-role mapping.

Only groups on the tenant's allowlist are processed — all others are ignored.
"""
from typing import Optional
import structlog

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
