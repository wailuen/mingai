"""
Unit tests for ATA-010: end-user agent list filtered by agent_access_control.

Tests the list_published_agents_db helper function in agents/routes.py.
Tier 1 unit tests — DB calls are mocked.
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(agent_id="agent-1", name="Test Agent", description="Desc", category="HR", avatar=None):
    """Build a fake SQLAlchemy row-like object."""
    row = MagicMock()
    row.__getitem__ = lambda self, i: [agent_id, name, description, category, avatar][i]
    return row


def _make_scalar_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _make_fetchall_result(rows):
    result = MagicMock()
    result.fetchall.return_value = rows
    return result


def _build_db_session(count_value=1, rows=None):
    """Build a mock AsyncSession that returns controlled query results."""
    if rows is None:
        rows = [_make_row()]

    db = AsyncMock()
    # First execute call is set_config (RLS), subsequent are count and rows.
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),                            # set_config
            _make_scalar_result(count_value),       # COUNT(*)
            _make_fetchall_result(rows),             # SELECT rows
        ]
    )
    return db


# ---------------------------------------------------------------------------
# Import target under test
# ---------------------------------------------------------------------------

from app.modules.agents.routes import list_published_agents_db  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: no ACL row → agent is visible (workspace_wide fallback)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_access_control_row_agent_is_visible():
    """
    When no agent_access_control row exists the query LEFT JOIN produces NULL
    for aac.agent_id. The WHERE clause allows it (aac.agent_id IS NULL).
    The DB returns 1 agent — function must surface it.
    """
    db = _build_db_session(count_value=1, rows=[_make_row()])
    result = await list_published_agents_db(
        tenant_id="tenant-abc",
        user_id="user-1",
        user_roles=["user"],
        page=1,
        page_size=20,
        db=db,
    )
    assert result["total"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["id"] == "agent-1"


# ---------------------------------------------------------------------------
# Test 2: workspace_wide → visible to any user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workspace_wide_agent_visible_to_any_user():
    """
    workspace_wide access mode: any authenticated user should see the agent.
    The DB (with the correct SQL) returns the agent row.
    """
    db = _build_db_session(count_value=1, rows=[_make_row(name="Finance Bot")])
    result = await list_published_agents_db(
        tenant_id="tenant-abc",
        user_id="user-xyz",
        user_roles=[],          # no special roles
        page=1,
        page_size=20,
        db=db,
    )
    assert result["total"] == 1
    assert result["items"][0]["name"] == "Finance Bot"


# ---------------------------------------------------------------------------
# Test 3: role_restricted → visible only to matching role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_role_restricted_visible_to_matching_role():
    """
    role_restricted: a user whose roles intersect allowed_roles sees the agent.
    The DB should return the agent when the user has a matching role.
    """
    db = _build_db_session(count_value=1, rows=[_make_row(name="HR Bot")])
    result = await list_published_agents_db(
        tenant_id="tenant-abc",
        user_id="user-hr",
        user_roles=["hr_manager"],
        page=1,
        page_size=20,
        db=db,
    )
    assert result["total"] == 1
    assert result["items"][0]["name"] == "HR Bot"


@pytest.mark.asyncio
async def test_role_restricted_not_visible_without_matching_role():
    """
    role_restricted: a user with no matching role gets an empty list (DB returns 0).
    """
    db = _build_db_session(count_value=0, rows=[])
    result = await list_published_agents_db(
        tenant_id="tenant-abc",
        user_id="user-basic",
        user_roles=["user"],
        page=1,
        page_size=20,
        db=db,
    )
    assert result["total"] == 0
    assert result["items"] == []


# ---------------------------------------------------------------------------
# Test 4: user_specific → visible only to the specific user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_specific_visible_to_specific_user():
    """
    user_specific: the designated user_id sees the agent.
    """
    db = _build_db_session(count_value=1, rows=[_make_row(name="Exec Bot")])
    result = await list_published_agents_db(
        tenant_id="tenant-abc",
        user_id="allowed-user-id",
        user_roles=[],
        page=1,
        page_size=20,
        db=db,
    )
    assert result["total"] == 1
    assert result["items"][0]["name"] == "Exec Bot"


@pytest.mark.asyncio
async def test_user_specific_not_visible_to_other_users():
    """
    user_specific: a different user does not see the agent (DB returns 0).
    """
    db = _build_db_session(count_value=0, rows=[])
    result = await list_published_agents_db(
        tenant_id="tenant-abc",
        user_id="other-user-id",
        user_roles=[],
        page=1,
        page_size=20,
        db=db,
    )
    assert result["total"] == 0
    assert result["items"] == []


# ---------------------------------------------------------------------------
# Test 5: SQL passes correct bind parameters (RULE A2A-01 guard)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_access_filter_sql_includes_tenant_and_user_params():
    """
    Ensure the access control query is issued with tenant_id, user_roles, and
    user_id_cast bind params — RULE A2A-06 cross-tenant isolation guard.
    """
    db = _build_db_session(count_value=0, rows=[])
    await list_published_agents_db(
        tenant_id="tenant-xyz",
        user_id="user-123",
        user_roles=["editor"],
        page=1,
        page_size=10,
        db=db,
    )
    # db.execute was called 3 times: set_config, count, rows
    calls = db.execute.call_args_list
    assert len(calls) == 3

    # COUNT call (index 1) and SELECT call (index 2) must pass access-filter params.
    for call in calls[1:3]:
        _, kwargs = call
        params = call.args[1] if len(call.args) > 1 else {}
        assert params.get("tenant_id") == "tenant-xyz", (
            "tenant_id must be bound to prevent cross-tenant bypass"
        )
        assert params.get("user_id_cast") == "user-123", (
            "user_id_cast must be passed for user_specific access mode"
        )
        assert params.get("user_roles") == ["editor"], (
            "user_roles must be passed for role_restricted access mode"
        )


# ---------------------------------------------------------------------------
# Test 6: pagination parameters are forwarded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pagination_limit_and_offset_applied():
    """
    Verify LIMIT and OFFSET bind params are passed correctly for pagination.
    """
    db = _build_db_session(count_value=50, rows=[])
    await list_published_agents_db(
        tenant_id="tenant-abc",
        user_id="user-1",
        user_roles=[],
        page=3,
        page_size=10,
        db=db,
    )
    # The SELECT rows call (index 2) should have limit=10, offset=20
    select_call = db.execute.call_args_list[2]
    params = select_call.args[1] if len(select_call.args) > 1 else {}
    assert params.get("limit") == 10
    assert params.get("offset") == 20
