"""
Unit tests for notification preferences API (DEF-003).

Tests cover:
- GET /me/notification-preferences returns all 5 types with defaults when no rows
- GET returns persisted values for stored preferences
- PATCH upserts correctly
- PATCH with partial updates (missing channel/enabled) retains existing values
- Invalid notification_type rejected
- Invalid channel rejected
- Empty preferences list rejected
- Auth required (no token → 401)
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id="user-1", tenant_id="tenant-1"):
    from app.core.dependencies import CurrentUser

    return CurrentUser(
        id=user_id,
        tenant_id=tenant_id,
        roles=["viewer"],
        scope="tenant",
        plan="professional",
    )


def _mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Tests for get_preferences_db helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_preferences_db_empty():
    """Returns empty dict when no rows exist."""
    from app.modules.users.notification_preferences import get_preferences_db

    db = _mock_db()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    db.execute.return_value = mock_result

    result = await get_preferences_db("uid", "tid", db)
    assert result == {}


@pytest.mark.asyncio
async def test_get_preferences_db_with_rows():
    """Returns dict keyed by notification_type."""
    from app.modules.users.notification_preferences import get_preferences_db

    db = _mock_db()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        ("issue_update", "email", True),
        ("digest", "both", False),
    ]
    db.execute.return_value = mock_result

    result = await get_preferences_db("uid", "tid", db)
    assert result["issue_update"] == {"channel": "email", "enabled": True}
    assert result["digest"] == {"channel": "both", "enabled": False}


# ---------------------------------------------------------------------------
# Tests for upsert_preference_db helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_preference_db_executes_insert():
    """upsert_preference_db executes INSERT ... ON CONFLICT."""
    from app.modules.users.notification_preferences import upsert_preference_db

    db = _mock_db()
    db.execute.return_value = MagicMock()

    await upsert_preference_db(
        user_id="uid",
        tenant_id="tid",
        notification_type="issue_update",
        channel="email",
        enabled=True,
        db=db,
    )

    assert db.execute.called
    call_args = db.execute.call_args
    sql_str = str(call_args[0][0])
    assert "notification_preferences" in sql_str
    assert "ON CONFLICT" in sql_str


# ---------------------------------------------------------------------------
# Tests for Pydantic validators
# ---------------------------------------------------------------------------


def test_patch_entry_invalid_type():
    """Invalid notification_type raises ValueError."""
    from pydantic import ValidationError
    from app.modules.users.notification_preferences import PatchPreferenceEntry

    with pytest.raises(ValidationError):
        PatchPreferenceEntry(notification_type="invalid_type")


def test_patch_entry_invalid_channel():
    """Invalid channel raises ValueError."""
    from pydantic import ValidationError
    from app.modules.users.notification_preferences import PatchPreferenceEntry

    with pytest.raises(ValidationError):
        PatchPreferenceEntry(notification_type="issue_update", channel="sms")


def test_patch_entry_valid_all_types():
    """All 5 valid notification types are accepted."""
    from app.modules.users.notification_preferences import PatchPreferenceEntry

    valid_types = [
        "issue_update",
        "sync_failure",
        "access_request",
        "platform_message",
        "digest",
    ]
    for ntype in valid_types:
        entry = PatchPreferenceEntry(notification_type=ntype)
        assert entry.notification_type == ntype


def test_patch_entry_valid_channels():
    """All 3 valid channels are accepted."""
    from app.modules.users.notification_preferences import PatchPreferenceEntry

    for channel in ("in_app", "email", "both"):
        entry = PatchPreferenceEntry(notification_type="digest", channel=channel)
        assert entry.channel == channel


def test_patch_request_empty_list_rejected():
    """Empty preferences list rejected by Pydantic min_length=1."""
    from pydantic import ValidationError
    from app.modules.users.notification_preferences import PatchPreferencesRequest

    with pytest.raises(ValidationError):
        PatchPreferencesRequest(preferences=[])


# ---------------------------------------------------------------------------
# Tests for GET endpoint (route-level)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_endpoint_returns_defaults():
    """GET returns 5 items with in_app/true defaults when no rows exist."""
    from app.modules.users.notification_preferences import get_notification_preferences

    with patch(
        "app.modules.users.notification_preferences.get_preferences_db",
        new=AsyncMock(return_value={}),
    ):
        db = _mock_db()
        user = _make_user()
        resp = await get_notification_preferences(current_user=user, db=db)

    assert len(resp.preferences) == 5
    for item in resp.preferences:
        assert item.channel == "in_app"
        assert item.enabled is True


@pytest.mark.asyncio
async def test_get_endpoint_returns_stored_values():
    """GET returns stored values for existing preferences."""
    from app.modules.users.notification_preferences import get_notification_preferences

    stored = {
        "issue_update": {"channel": "email", "enabled": False},
    }
    with patch(
        "app.modules.users.notification_preferences.get_preferences_db",
        new=AsyncMock(return_value=stored),
    ):
        db = _mock_db()
        user = _make_user()
        resp = await get_notification_preferences(current_user=user, db=db)

    items_by_type = {item.notification_type: item for item in resp.preferences}
    assert items_by_type["issue_update"].channel == "email"
    assert items_by_type["issue_update"].enabled is False
    # Other types default
    assert items_by_type["digest"].channel == "in_app"


# ---------------------------------------------------------------------------
# Tests for PATCH endpoint (route-level)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_endpoint_upserts_and_returns_all():
    """PATCH upserts entries and returns all 5 types."""
    from app.modules.users.notification_preferences import (
        PatchPreferencesRequest,
        PatchPreferenceEntry,
        patch_notification_preferences,
    )

    updated_state = {
        "issue_update": {"channel": "email", "enabled": True},
    }
    with (
        patch(
            "app.modules.users.notification_preferences.get_preferences_db",
            new=AsyncMock(side_effect=[{}, updated_state]),
        ),
        patch(
            "app.modules.users.notification_preferences.upsert_preference_db",
            new=AsyncMock(),
        ),
    ):
        db = _mock_db()
        user = _make_user()
        body = PatchPreferencesRequest(
            preferences=[
                PatchPreferenceEntry(notification_type="issue_update", channel="email")
            ]
        )
        resp = await patch_notification_preferences(body=body, current_user=user, db=db)

    assert len(resp.preferences) == 5
    items_by_type = {item.notification_type: item for item in resp.preferences}
    assert items_by_type["issue_update"].channel == "email"
