"""
Unit tests for DEF-008: Auth0 group sync — role resolution and
team_memberships DB writes.

Tests:
- sync_auth0_groups() role resolution (existing logic)
- sync_team_memberships_db() adds correct memberships for known group→team
- sync_team_memberships_db() removes memberships for groups no longer present
- sync_team_memberships_db() is idempotent (calling twice → same memberships)
- sync_team_memberships_db() with empty groups removes all group-synced memberships
- build_group_sync_config() extracts config correctly

All DB operations are mocked — Tier 1 unit tests.
"""
from unittest.mock import AsyncMock, MagicMock, patch, call
import uuid

import pytest

from app.modules.auth.group_sync import (
    MAPPABLE_ROLES,
    build_group_sync_config,
    sync_auth0_groups,
    sync_team_memberships_db,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_uuid() -> str:
    return str(uuid.uuid4())


def _make_mock_db() -> AsyncMock:
    """
    Return a lightweight async DB session mock.

    execute() returns a mock whose fetchall() / fetchone() can be configured
    per-test via .return_value.
    """
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# sync_auth0_groups — role resolution
# ---------------------------------------------------------------------------


class TestSyncAuth0Groups:
    def test_empty_allowlist_returns_empty(self):
        result = sync_auth0_groups(
            jwt_groups=["Engineering", "Admins"],
            allowlist=[],
            group_role_mapping={"Engineering": "editor"},
        )
        assert result == []

    def test_empty_jwt_groups_returns_empty(self):
        result = sync_auth0_groups(
            jwt_groups=[],
            allowlist=["Engineering"],
            group_role_mapping={"Engineering": "editor"},
        )
        assert result == []

    def test_group_not_in_allowlist_ignored(self):
        result = sync_auth0_groups(
            jwt_groups=["NotAllowed"],
            allowlist=["Engineering"],
            group_role_mapping={"NotAllowed": "admin"},
        )
        assert result == []

    def test_group_in_allowlist_but_no_mapping_ignored(self):
        result = sync_auth0_groups(
            jwt_groups=["Engineering"],
            allowlist=["Engineering"],
            group_role_mapping={},
        )
        assert result == []

    def test_valid_group_returns_role(self):
        result = sync_auth0_groups(
            jwt_groups=["Engineering"],
            allowlist=["Engineering"],
            group_role_mapping={"Engineering": "editor"},
        )
        assert result == ["editor"]

    def test_multiple_groups_return_multiple_roles(self):
        result = sync_auth0_groups(
            jwt_groups=["Engineering", "Admins"],
            allowlist=["Engineering", "Admins"],
            group_role_mapping={"Engineering": "editor", "Admins": "admin"},
        )
        assert "editor" in result
        assert "admin" in result

    def test_duplicate_role_only_appears_once(self):
        result = sync_auth0_groups(
            jwt_groups=["TeamA", "TeamB"],
            allowlist=["TeamA", "TeamB"],
            group_role_mapping={"TeamA": "editor", "TeamB": "editor"},
        )
        assert result.count("editor") == 1

    def test_invalid_role_in_mapping_is_rejected(self):
        result = sync_auth0_groups(
            jwt_groups=["Hackers"],
            allowlist=["Hackers"],
            group_role_mapping={"Hackers": "superadmin"},
        )
        assert result == []

    def test_all_mappable_roles_accepted(self):
        for role in MAPPABLE_ROLES:
            result = sync_auth0_groups(
                jwt_groups=["G1"],
                allowlist=["G1"],
                group_role_mapping={"G1": role},
            )
            assert role in result


# ---------------------------------------------------------------------------
# build_group_sync_config
# ---------------------------------------------------------------------------


class TestBuildGroupSyncConfig:
    def test_none_input_returns_empty(self):
        allowlist, mapping = build_group_sync_config(None)
        assert allowlist == []
        assert mapping == {}

    def test_empty_dict_returns_empty(self):
        allowlist, mapping = build_group_sync_config({})
        assert allowlist == []
        assert mapping == {}

    def test_extracts_allowlist_and_mapping(self):
        row = {
            "config_data": {
                "auth0_group_allowlist": ["Engineering", "Admins"],
                "auth0_group_role_mapping": {
                    "Engineering": "editor",
                    "Admins": "admin",
                },
            }
        }
        allowlist, mapping = build_group_sync_config(row)
        assert allowlist == ["Engineering", "Admins"]
        assert mapping == {"Engineering": "editor", "Admins": "admin"}

    def test_missing_keys_return_empty(self):
        row = {"config_data": {"some_other_key": True}}
        allowlist, mapping = build_group_sync_config(row)
        assert allowlist == []
        assert mapping == {}


# ---------------------------------------------------------------------------
# sync_team_memberships_db — DB write behaviour
# ---------------------------------------------------------------------------


class TestSyncTeamMembershipsDb:
    """
    All DB interactions are mocked.  We verify the *calls* made to db.execute()
    rather than real DB state — that is the correct Tier 1 pattern.
    """

    @pytest.mark.anyio
    async def test_adds_membership_for_matched_group(self):
        """Group Engineering matches team → INSERT executed for that team."""
        tenant_id = _make_uuid()
        user_id = _make_uuid()
        team_id = _make_uuid()

        db = _make_mock_db()

        # Sequence of execute() calls:
        # 1. _get_teams_by_auth0_groups → returns one team row
        # 2. _get_current_team_memberships → no existing synced memberships
        # 3. _upsert_team_membership → rowcount=1 (inserted)
        # 4. _write_team_membership_audit → no return value needed

        teams_result = MagicMock()
        teams_result.fetchall.return_value = [(team_id, "Engineering", "Engineering")]

        current_result = MagicMock()
        current_result.fetchall.return_value = []

        upsert_result = MagicMock()
        upsert_result.rowcount = 1

        audit_result = MagicMock()

        db.execute.side_effect = [
            teams_result,  # _get_teams_by_auth0_groups
            current_result,  # _get_current_team_memberships
            upsert_result,  # _upsert_team_membership
            audit_result,  # _write_team_membership_audit
        ]

        result = await sync_team_memberships_db(
            tenant_id=tenant_id,
            user_id=user_id,
            groups=["Engineering"],
            db=db,
        )

        assert team_id in result["added"]
        assert result["removed"] == []
        # db.execute must have been called 4 times
        assert db.execute.call_count == 4

    @pytest.mark.anyio
    async def test_removes_stale_membership_not_in_current_groups(self):
        """
        User currently belongs to team X (group-synced), but incoming groups
        no longer include X's group → DELETE executed.
        """
        tenant_id = _make_uuid()
        user_id = _make_uuid()
        stale_team_id = _make_uuid()

        db = _make_mock_db()

        teams_result = MagicMock()
        teams_result.fetchall.return_value = []  # no matched teams from incoming groups

        current_result = MagicMock()
        current_result.fetchall.return_value = [(stale_team_id,)]  # stale membership

        delete_result = MagicMock()
        delete_result.rowcount = 1

        audit_result = MagicMock()

        # groups=[] → _get_teams_by_auth0_groups returns early (no db.execute call)
        db.execute.side_effect = [
            current_result,  # _get_current_team_memberships
            delete_result,  # _delete_team_membership
            audit_result,  # _write_team_membership_audit
        ]

        result = await sync_team_memberships_db(
            tenant_id=tenant_id,
            user_id=user_id,
            groups=[],  # no groups — remove all
            db=db,
        )

        assert result["added"] == []
        assert stale_team_id in result["removed"]

    @pytest.mark.anyio
    async def test_idempotent_second_call_produces_same_memberships(self):
        """
        Calling sync_team_memberships_db twice produces no additional inserts
        on the second call (ON CONFLICT DO NOTHING → rowcount=0).
        """
        tenant_id = _make_uuid()
        user_id = _make_uuid()
        team_id = _make_uuid()

        db = _make_mock_db()

        # First call: team matched, no current membership → inserts
        # Second call: team matched, membership already exists (rowcount=0)

        teams_result_1 = MagicMock()
        teams_result_1.fetchall.return_value = [(team_id, "Engineering", "Engineering")]
        current_result_1 = MagicMock()
        current_result_1.fetchall.return_value = []
        upsert_result_1 = MagicMock()
        upsert_result_1.rowcount = 1  # inserted
        # No audit on second call for add since rowcount=0, but we still write audit
        audit_result_1 = MagicMock()

        teams_result_2 = MagicMock()
        teams_result_2.fetchall.return_value = [(team_id, "Engineering", "Engineering")]
        current_result_2 = MagicMock()
        current_result_2.fetchall.return_value = [(team_id,)]  # already member
        upsert_result_2 = MagicMock()
        upsert_result_2.rowcount = 0  # already existed — no insert
        # Audit skipped on second call because teams_added=[] and teams_removed=[]

        db.execute.side_effect = [
            # First call
            teams_result_1,
            current_result_1,
            upsert_result_1,
            audit_result_1,
            # Second call
            teams_result_2,
            current_result_2,
            upsert_result_2,
            # No audit execute on second call (no changes)
        ]

        result1 = await sync_team_memberships_db(
            tenant_id=tenant_id,
            user_id=user_id,
            groups=["Engineering"],
            db=db,
        )
        result2 = await sync_team_memberships_db(
            tenant_id=tenant_id,
            user_id=user_id,
            groups=["Engineering"],
            db=db,
        )

        # First call added the membership
        assert team_id in result1["added"]
        # Second call: no new inserts
        assert result2["added"] == []
        assert result2["removed"] == []

    @pytest.mark.anyio
    async def test_empty_groups_removes_all_synced_memberships(self):
        """
        Passing empty groups should remove all group-synced team memberships.
        """
        tenant_id = _make_uuid()
        user_id = _make_uuid()
        team_id_a = _make_uuid()
        team_id_b = _make_uuid()

        db = _make_mock_db()

        teams_result = MagicMock()
        teams_result.fetchall.return_value = []  # no groups → no matched teams

        current_result = MagicMock()
        current_result.fetchall.return_value = [(team_id_a,), (team_id_b,)]

        delete_result_a = MagicMock()
        delete_result_a.rowcount = 1
        delete_result_b = MagicMock()
        delete_result_b.rowcount = 1

        audit_result = MagicMock()

        # groups=[] → _get_teams_by_auth0_groups returns early (no db.execute call)
        db.execute.side_effect = [
            current_result,
            delete_result_a,
            delete_result_b,
            audit_result,
        ]

        result = await sync_team_memberships_db(
            tenant_id=tenant_id,
            user_id=user_id,
            groups=[],
            db=db,
        )

        assert result["added"] == []
        assert set(result["removed"]) == {team_id_a, team_id_b}

    @pytest.mark.anyio
    async def test_no_changes_skips_audit_write(self):
        """
        When the membership state is already correct (no adds or removes),
        the audit INSERT should NOT be executed.
        """
        tenant_id = _make_uuid()
        user_id = _make_uuid()
        team_id = _make_uuid()

        db = _make_mock_db()

        teams_result = MagicMock()
        teams_result.fetchall.return_value = [(team_id, "Engineering", "Engineering")]

        current_result = MagicMock()
        current_result.fetchall.return_value = [(team_id,)]  # already synced

        upsert_result = MagicMock()
        upsert_result.rowcount = 0  # conflict — nothing inserted

        db.execute.side_effect = [
            teams_result,
            current_result,
            upsert_result,
            # Audit NOT called because teams_added=[] and teams_removed=[]
        ]

        result = await sync_team_memberships_db(
            tenant_id=tenant_id,
            user_id=user_id,
            groups=["Engineering"],
            db=db,
        )

        assert result["added"] == []
        assert result["removed"] == []
        # Only 3 execute calls — no audit INSERT
        assert db.execute.call_count == 3
