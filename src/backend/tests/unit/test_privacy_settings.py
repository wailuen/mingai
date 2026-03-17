"""
Unit tests for user privacy settings API and service hooks (DEF-004).

Tests cover:
- GET returns all-true defaults when no row exists
- GET returns persisted values
- PATCH upserts correctly
- PATCH with partial updates retains existing values
- _check_privacy_setting returns True for missing row (default-permissive)
- _check_privacy_setting returns stored value when row exists
- _check_privacy_setting raises ValueError for unknown setting name
- WorkingMemoryService.update() skips when working_memory_enabled=False
- WorkingMemoryService.update() proceeds when working_memory_enabled=True
- OrgContextService.get() returns empty OrgContextData when org_context_enabled=False
- OrgContextService.get() proceeds when org_context_enabled=True
- ProfileLearningService.on_query_completed() skips when disabled
- ProfileLearningService.on_query_completed() proceeds when enabled
"""
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


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


def _mock_db(row=None):
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = row
    db.execute.return_value = mock_result
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# _check_privacy_setting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_privacy_setting_no_row_returns_true():
    """Returns True (default-permissive) when no row exists."""
    from app.modules.users.privacy_settings import _check_privacy_setting

    db = _mock_db(row=None)
    result = await _check_privacy_setting(db, "tid", "uid", "profile_learning_enabled")
    assert result is True


@pytest.mark.asyncio
async def test_check_privacy_setting_true_row():
    """Returns True when DB row has True."""
    from app.modules.users.privacy_settings import _check_privacy_setting

    db = _mock_db(row=(True,))
    result = await _check_privacy_setting(db, "tid", "uid", "working_memory_enabled")
    assert result is True


@pytest.mark.asyncio
async def test_check_privacy_setting_false_row():
    """Returns False when DB row has False."""
    from app.modules.users.privacy_settings import _check_privacy_setting

    db = _mock_db(row=(False,))
    result = await _check_privacy_setting(db, "tid", "uid", "org_context_enabled")
    assert result is False


@pytest.mark.asyncio
async def test_check_privacy_setting_unknown_name_raises():
    """Raises ValueError for unknown setting name."""
    from app.modules.users.privacy_settings import _check_privacy_setting

    db = _mock_db(row=None)
    with pytest.raises(ValueError, match="Unknown privacy setting"):
        await _check_privacy_setting(db, "tid", "uid", "nonexistent_setting")


# ---------------------------------------------------------------------------
# GET endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_privacy_settings_defaults():
    """GET returns all-true defaults when no row exists."""
    from app.modules.users.privacy_settings import get_privacy_settings

    with patch(
        "app.modules.users.privacy_settings.get_privacy_settings_db",
        new=AsyncMock(return_value=None),
    ):
        db = _mock_db()
        user = _make_user()
        resp = await get_privacy_settings(current_user=user, db=db)

    assert resp.profile_learning_enabled is True
    assert resp.working_memory_enabled is True
    assert resp.org_context_enabled is True


@pytest.mark.asyncio
async def test_get_privacy_settings_stored_values():
    """GET returns stored values."""
    from app.modules.users.privacy_settings import get_privacy_settings

    stored = {
        "profile_learning_enabled": False,
        "working_memory_enabled": True,
        "org_context_enabled": False,
    }
    with patch(
        "app.modules.users.privacy_settings.get_privacy_settings_db",
        new=AsyncMock(return_value=stored),
    ):
        db = _mock_db()
        user = _make_user()
        resp = await get_privacy_settings(current_user=user, db=db)

    assert resp.profile_learning_enabled is False
    assert resp.working_memory_enabled is True
    assert resp.org_context_enabled is False


# ---------------------------------------------------------------------------
# PATCH endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_privacy_settings_partial_update():
    """PATCH with only one field changes only that field."""
    from app.modules.users.privacy_settings import (
        PatchPrivacySettingsRequest,
        patch_privacy_settings,
    )

    existing = {
        "profile_learning_enabled": True,
        "working_memory_enabled": True,
        "org_context_enabled": True,
    }
    with (
        patch(
            "app.modules.users.privacy_settings.get_privacy_settings_db",
            new=AsyncMock(return_value=existing),
        ),
        patch(
            "app.modules.users.privacy_settings.upsert_privacy_settings_db",
            new=AsyncMock(),
        ),
    ):
        db = _mock_db()
        user = _make_user()
        body = PatchPrivacySettingsRequest(profile_learning_enabled=False)
        resp = await patch_privacy_settings(body=body, current_user=user, db=db)

    assert resp.profile_learning_enabled is False
    assert resp.working_memory_enabled is True  # unchanged
    assert resp.org_context_enabled is True  # unchanged


@pytest.mark.asyncio
async def test_patch_privacy_settings_new_row_defaults():
    """PATCH with no existing row uses True as default for unset fields."""
    from app.modules.users.privacy_settings import (
        PatchPrivacySettingsRequest,
        patch_privacy_settings,
    )

    with (
        patch(
            "app.modules.users.privacy_settings.get_privacy_settings_db",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.modules.users.privacy_settings.upsert_privacy_settings_db",
            new=AsyncMock(),
        ),
    ):
        db = _mock_db()
        user = _make_user()
        body = PatchPrivacySettingsRequest(working_memory_enabled=False)
        resp = await patch_privacy_settings(body=body, current_user=user, db=db)

    assert resp.working_memory_enabled is False
    assert resp.profile_learning_enabled is True  # default
    assert resp.org_context_enabled is True  # default


# ---------------------------------------------------------------------------
# WorkingMemoryService service hook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_working_memory_skips_when_disabled():
    """WorkingMemoryService.update() skips when working_memory_enabled=False."""
    from app.modules.memory.working_memory import WorkingMemoryService

    db = _mock_db()
    svc = WorkingMemoryService()

    with patch(
        "app.modules.users.privacy_settings._check_privacy_setting",
        new=AsyncMock(return_value=False),
    ):
        with patch("app.modules.memory.working_memory.get_redis") as mock_redis:
            await svc.update(
                user_id="uid",
                tenant_id="tid",
                agent_id="agent-1",
                query="test query",
                response="response",
                db=db,
            )
            # Redis should NOT be called
            mock_redis.assert_not_called()


@pytest.mark.asyncio
async def test_working_memory_proceeds_when_enabled():
    """WorkingMemoryService.update() proceeds when working_memory_enabled=True."""
    from app.modules.memory.working_memory import WorkingMemoryService

    db = _mock_db()
    svc = WorkingMemoryService()

    mock_redis_inst = AsyncMock()
    mock_redis_inst.get = AsyncMock(return_value=None)
    mock_redis_inst.setex = AsyncMock()

    with patch(
        "app.modules.users.privacy_settings._check_privacy_setting",
        new=AsyncMock(return_value=True),
    ):
        with patch(
            "app.modules.memory.working_memory.get_redis",
            return_value=mock_redis_inst,
        ):
            await svc.update(
                user_id="uid",
                tenant_id="tid",
                agent_id="agent-1",
                query="test query",
                response="response",
                db=db,
            )
            # Redis setex should be called (memory was stored)
            mock_redis_inst.setex.assert_called_once()


# ---------------------------------------------------------------------------
# OrgContextService service hook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_context_returns_empty_when_disabled():
    """OrgContextService.get() returns empty OrgContextData when disabled."""
    from app.modules.memory.org_context import OrgContextData, OrgContextService

    db = _mock_db()
    svc = OrgContextService()

    with patch(
        "app.modules.users.privacy_settings._check_privacy_setting",
        new=AsyncMock(return_value=False),
    ):
        result = await svc.get(
            user_id="uid",
            tenant_id="tid",
            jwt_claims={},
            db=db,
        )

    assert isinstance(result, OrgContextData)
    assert result.department is None
    assert result.role is None


@pytest.mark.asyncio
async def test_org_context_proceeds_when_enabled():
    """OrgContextService.get() proceeds with normal logic when enabled."""
    from app.modules.memory.org_context import OrgContextService

    db = _mock_db()
    svc = OrgContextService()

    mock_redis_inst = AsyncMock()
    mock_redis_inst.get = AsyncMock(return_value=None)
    mock_redis_inst.setex = AsyncMock()

    with patch(
        "app.modules.users.privacy_settings._check_privacy_setting",
        new=AsyncMock(return_value=True),
    ):
        with patch(
            "app.modules.memory.org_context.get_redis",
            return_value=mock_redis_inst,
        ):
            result = await svc.get(
                user_id="uid",
                tenant_id="tid",
                jwt_claims={"department": "Engineering"},
                db=db,
            )

    # Should not return None; some extraction attempted
    assert result is not None


# ---------------------------------------------------------------------------
# ProfileLearningService service hook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_learning_skips_when_disabled():
    """ProfileLearningService.on_query_completed() skips when disabled."""
    from app.modules.memory.profile_learning import ProfileLearningService

    db = _mock_db()
    svc = ProfileLearningService()

    with patch(
        "app.modules.users.privacy_settings._check_privacy_setting",
        new=AsyncMock(return_value=False),
    ) as mock_check:
        await svc.on_query_completed(
            user_id="uid",
            tenant_id="tid",
            query="test",
            agent_id="agent-1",
            db=db,
        )
        mock_check.assert_called_once_with(db, "tid", "uid", "profile_learning_enabled")


@pytest.mark.asyncio
async def test_profile_learning_proceeds_when_enabled():
    """ProfileLearningService.on_query_completed() completes without error when enabled."""
    from app.modules.memory.profile_learning import ProfileLearningService

    db = _mock_db()
    svc = ProfileLearningService()

    with patch(
        "app.modules.users.privacy_settings._check_privacy_setting",
        new=AsyncMock(return_value=True),
    ):
        # Should not raise
        await svc.on_query_completed(
            user_id="uid",
            tenant_id="tid",
            query="test query",
            agent_id="agent-1",
            db=db,
        )
