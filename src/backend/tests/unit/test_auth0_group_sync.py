"""
TEST-056: Auth0 group claim sync — unit tests.

Tests the allowlist-gated group-to-role mapping logic.
"""
import pytest
from app.modules.auth.group_sync import sync_auth0_groups, build_group_sync_config


class TestEmptyAllowlist:
    """Empty allowlist means no groups are ever synced."""

    def test_empty_allowlist_no_groups_synced(self):
        """With empty allowlist, no groups are synced regardless of JWT groups."""
        jwt_groups = ["Engineering", "Procurement", "Legal"]
        allowlist: list[str] = []
        mapping = {"Engineering": "admin", "Procurement": "user"}

        result = sync_auth0_groups(jwt_groups, allowlist, mapping)

        assert result == [], "Empty allowlist must ignore all groups"

    def test_empty_allowlist_with_empty_jwt_groups(self):
        """Empty allowlist + empty JWT groups = no roles."""
        result = sync_auth0_groups([], [], {})
        assert result == []


class TestAllowlistFiltering:
    """Only groups on the allowlist are processed."""

    def test_allowlist_with_3_groups_only_those_synced(self):
        """Only the 3 allowlisted groups produce roles; others are ignored."""
        jwt_groups = ["Engineering", "Finance", "Marketing", "Legal"]
        allowlist = ["Engineering", "Finance", "Legal"]
        mapping = {
            "Engineering": "admin",
            "Finance": "user",
            "Legal": "viewer",
            "Marketing": "editor",  # Not in allowlist
        }

        result = sync_auth0_groups(jwt_groups, allowlist, mapping)

        assert set(result) == {"admin", "user", "viewer"}
        assert "editor" not in result

    def test_group_in_allowlist_not_in_jwt_no_role_change(self):
        """Group on allowlist but absent from JWT → no role assigned."""
        jwt_groups = ["Finance"]
        allowlist = ["Engineering", "Finance"]
        mapping = {"Engineering": "admin", "Finance": "user"}

        result = sync_auth0_groups(jwt_groups, allowlist, mapping)

        assert "admin" not in result, "Engineering not in JWT → no admin role"
        assert "user" in result, "Finance in JWT and allowlist → user role"

    def test_group_in_jwt_not_in_allowlist_ignored(self):
        """Group in JWT but NOT in allowlist is silently ignored."""
        jwt_groups = ["Engineering", "SecretOps"]
        allowlist = ["Engineering"]
        mapping = {"Engineering": "admin", "SecretOps": "admin"}

        result = sync_auth0_groups(jwt_groups, allowlist, mapping)

        assert result == ["admin"]

    def test_group_in_both_allowlist_and_jwt_role_assigned(self):
        """Group present in both allowlist and JWT → role assigned."""
        jwt_groups = ["Procurement"]
        allowlist = ["Procurement"]
        mapping = {"Procurement": "user"}

        result = sync_auth0_groups(jwt_groups, allowlist, mapping)

        assert result == ["user"]

    def test_allowlist_update_uses_new_allowlist(self):
        """When allowlist changes, subsequent calls use the new allowlist."""
        jwt_groups = ["Engineering", "Finance"]
        mapping = {"Engineering": "admin", "Finance": "user"}

        # Old allowlist: only Engineering
        result_old = sync_auth0_groups(jwt_groups, ["Engineering"], mapping)
        assert result_old == ["admin"]
        assert "user" not in result_old

        # New allowlist: both Engineering and Finance
        result_new = sync_auth0_groups(jwt_groups, ["Engineering", "Finance"], mapping)
        assert set(result_new) == {"admin", "user"}


class TestBuildGroupSyncConfig:
    """build_group_sync_config extracts config from tenant_configs row."""

    def test_none_row_returns_empty(self):
        """None tenant_configs row → empty allowlist and mapping."""
        allowlist, mapping = build_group_sync_config(None)
        assert allowlist == []
        assert mapping == {}

    def test_missing_keys_return_empty(self):
        """Row with no relevant keys → empty config."""
        allowlist, mapping = build_group_sync_config({"config_data": {}})
        assert allowlist == []
        assert mapping == {}

    def test_extracts_allowlist_and_mapping(self):
        """Correctly extracts allowlist and mapping from config_data."""
        row = {
            "config_data": {
                "auth0_group_allowlist": ["Engineering", "Finance"],
                "auth0_group_role_mapping": {
                    "Engineering": "admin",
                    "Finance": "user",
                },
            }
        }
        allowlist, mapping = build_group_sync_config(row)
        assert allowlist == ["Engineering", "Finance"]
        assert mapping == {"Engineering": "admin", "Finance": "user"}
