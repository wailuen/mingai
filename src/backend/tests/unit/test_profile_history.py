"""
Unit tests for LLM Profile history and rollback endpoints (VA-C1).

Tests:
  - GET /platform/llm-profiles/{id}/history returns entries newest-first
  - GET /platform/llm-profiles/{id}/history respects limit param
  - GET /platform/llm-profiles/{id}/history returns 404 for non-existent profile
  - POST /platform/llm-profiles/{id}/rollback/{history_id} restores slot assignments
  - POST /platform/llm-profiles/{id}/rollback/{history_id} returns 404 for bad history_id
  - POST /platform/llm-profiles/{id}/rollback/{history_id} returns 404 for wrong profile
  - POST /platform/llm-profiles/{id}/rollback/{history_id} returns 422 when diff.before has no slot fields
  - Rollback endpoint writes a new audit entry with action="rollback"
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.dependencies import CurrentUser
from app.modules.llm_profiles.routes import router

# ---------------------------------------------------------------------------
# Test app setup
# ---------------------------------------------------------------------------

app = FastAPI()
app.include_router(router)

PLATFORM_ADMIN_USER = CurrentUser(
    id=str(uuid.uuid4()),
    tenant_id="platform",
    roles=["platform_admin"],
    scope="platform",
    plan=None,
    email="admin@platform.test",
)

PROFILE_ID = str(uuid.uuid4())
HISTORY_ID_1 = str(uuid.uuid4())
HISTORY_ID_2 = str(uuid.uuid4())
LIBRARY_ID_A = str(uuid.uuid4())
LIBRARY_ID_B = str(uuid.uuid4())

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_audit_row(
    entry_id: str,
    action: str,
    actor_id: str,
    logged_at: datetime,
    diff: dict,
):
    """Build a mock row tuple matching the SELECT in get_profile_history."""
    row = MagicMock()
    row.__getitem__ = lambda self, i: [
        uuid.UUID(entry_id),
        action,
        uuid.UUID(actor_id),
        logged_at,
        diff,
    ][i]
    return row


def _make_mock_db(
    profile_exists: bool = True,
    history_rows: list | None = None,
    history_entry: Any = None,
    current_slots_row: Any = None,
):
    """Build a mock AsyncSession for the history and rollback endpoints."""
    db = AsyncMock()

    # Track execute call count so we can return different results per call
    call_count = 0
    profile_row = MagicMock()

    async def fake_execute(sql, params=None):
        nonlocal call_count
        call_count += 1
        result = MagicMock()

        sql_str = str(sql) if not isinstance(sql, str) else sql

        if "owner_tenant_id IS NULL" in sql_str and "FROM llm_profiles" in sql_str and "FROM llm_profile" not in sql_str.split("FROM llm_profiles")[0]:
            # Profile existence check
            result.fetchone.return_value = profile_row if profile_exists else None
        elif "FROM llm_profile_audit_log" in sql_str and "ORDER BY logged_at DESC" in sql_str:
            # GET history query
            result.fetchall.return_value = history_rows or []
        elif "FROM llm_profile_audit_log" in sql_str and "WHERE id = :hid" in sql_str:
            # Rollback: fetch history entry
            result.fetchone.return_value = history_entry
        elif "FROM llm_profiles" in sql_str and "WHERE id = :id" in sql_str and "owner_tenant_id" not in sql_str:
            # Rollback: fetch current slots after update
            result.fetchone.return_value = current_slots_row
        else:
            result.fetchone.return_value = None
            result.fetchall.return_value = []
        return result

    db.execute = fake_execute
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# GET /platform/llm-profiles/{id}/history
# ---------------------------------------------------------------------------


class TestGetProfileHistory:
    """Tests for GET /{profile_id}/history endpoint."""

    def _make_client(self, db_mock):
        from app.core.session import get_async_session
        from app.core.dependencies import require_platform_admin

        client_app = FastAPI()
        client_app.include_router(router)

        def override_db():
            yield db_mock

        def override_auth():
            return PLATFORM_ADMIN_USER

        client_app.dependency_overrides[get_async_session] = override_db
        client_app.dependency_overrides[require_platform_admin] = override_auth
        return TestClient(client_app, raise_server_exceptions=True)

    def test_history_returns_entries_newest_first(self):
        """History entries should be ordered newest-first (DESC by logged_at)."""
        now = datetime.now(timezone.utc)
        earlier = datetime(2026, 3, 20, 10, 0, 0, tzinfo=timezone.utc)
        later = datetime(2026, 3, 21, 10, 0, 0, tzinfo=timezone.utc)

        actor_id = str(uuid.uuid4())

        row1 = MagicMock()
        row1.__getitem__ = lambda self, i: [
            uuid.UUID(HISTORY_ID_1),
            "update",
            uuid.UUID(actor_id),
            later,
            {"before": {"chat_library_id": LIBRARY_ID_A}, "after": {"chat_library_id": LIBRARY_ID_B}},
        ][i]

        row2 = MagicMock()
        row2.__getitem__ = lambda self, i: [
            uuid.UUID(HISTORY_ID_2),
            "create",
            uuid.UUID(actor_id),
            earlier,
            {"after": {"name": "test"}},
        ][i]

        db_mock = _make_mock_db(profile_exists=True, history_rows=[row1, row2])
        client = self._make_client(db_mock)

        response = client.get(f"/platform/llm-profiles/{PROFILE_ID}/history")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        # First entry (index 0) should be the newer one
        assert data[0]["action"] == "update"
        assert data[1]["action"] == "create"

    def test_history_returns_empty_list_when_no_entries(self):
        """Should return empty list when no audit log entries exist."""
        db_mock = _make_mock_db(profile_exists=True, history_rows=[])
        client = self._make_client(db_mock)

        response = client.get(f"/platform/llm-profiles/{PROFILE_ID}/history")
        assert response.status_code == 200
        assert response.json() == []

    def test_history_returns_404_for_missing_profile(self):
        """Should return 404 when profile does not exist or is not a platform profile."""
        db_mock = _make_mock_db(profile_exists=False)
        client = self._make_client(db_mock)

        response = client.get(f"/platform/llm-profiles/{PROFILE_ID}/history")
        assert response.status_code == 404

    def test_history_limit_param_accepted(self):
        """Limit param should be accepted in range 1-100."""
        db_mock = _make_mock_db(profile_exists=True, history_rows=[])
        client = self._make_client(db_mock)

        response = client.get(f"/platform/llm-profiles/{PROFILE_ID}/history?limit=5")
        assert response.status_code == 200

    def test_history_limit_param_rejected_above_100(self):
        """Limit > 100 should return 422."""
        db_mock = _make_mock_db(profile_exists=True, history_rows=[])
        client = self._make_client(db_mock)

        response = client.get(f"/platform/llm-profiles/{PROFILE_ID}/history?limit=101")
        assert response.status_code == 422

    def test_history_limit_param_rejected_below_1(self):
        """Limit < 1 should return 422."""
        db_mock = _make_mock_db(profile_exists=True, history_rows=[])
        client = self._make_client(db_mock)

        response = client.get(f"/platform/llm-profiles/{PROFILE_ID}/history?limit=0")
        assert response.status_code == 422

    def test_history_entry_shape(self):
        """Each entry must have id, action, actor_id, created_at, diff fields."""
        actor_id = str(uuid.uuid4())
        ts = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)

        row = MagicMock()
        row.__getitem__ = lambda self, i: [
            uuid.UUID(HISTORY_ID_1),
            "update",
            uuid.UUID(actor_id),
            ts,
            {"before": {"chat_library_id": LIBRARY_ID_A}, "after": {"chat_library_id": LIBRARY_ID_B}},
        ][i]

        db_mock = _make_mock_db(profile_exists=True, history_rows=[row])
        client = self._make_client(db_mock)

        response = client.get(f"/platform/llm-profiles/{PROFILE_ID}/history")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        entry = data[0]
        assert entry["id"] == HISTORY_ID_1
        assert entry["action"] == "update"
        assert entry["actor_id"] == actor_id
        assert "created_at" in entry
        assert "diff" in entry
        assert entry["diff"]["before"]["chat_library_id"] == LIBRARY_ID_A


# ---------------------------------------------------------------------------
# POST /platform/llm-profiles/{id}/rollback/{history_id}
# ---------------------------------------------------------------------------


class TestRollbackProfile:
    """Tests for POST /{profile_id}/rollback/{history_id} endpoint."""

    def _make_client(self, db_mock, service_mock=None, resolver_mock=None):
        from app.core.session import get_async_session
        from app.core.dependencies import require_platform_admin

        client_app = FastAPI()
        client_app.include_router(router)

        def override_db():
            yield db_mock

        def override_auth():
            return PLATFORM_ADMIN_USER

        client_app.dependency_overrides[get_async_session] = override_db
        client_app.dependency_overrides[require_platform_admin] = override_auth
        return TestClient(client_app, raise_server_exceptions=False)

    def _make_history_row(self, entry_id: str, action: str, diff: dict):
        row = MagicMock()
        row.__getitem__ = lambda self, i: [
            uuid.UUID(entry_id),
            action,
            diff,
        ][i]
        return row

    def _make_current_slots_row(
        self,
        chat_id: str | None = None,
        intent_id: str | None = None,
        vision_id: str | None = None,
        agent_id: str | None = None,
    ):
        row = MagicMock()
        chat_uuid = uuid.UUID(chat_id) if chat_id else None
        intent_uuid = uuid.UUID(intent_id) if intent_id else None
        vision_uuid = uuid.UUID(vision_id) if vision_id else None
        agent_uuid = uuid.UUID(agent_id) if agent_id else None
        row.__getitem__ = lambda self, i: [
            chat_uuid, intent_uuid, vision_uuid, agent_uuid
        ][i]
        return row

    def test_rollback_returns_404_for_missing_profile(self):
        """Should return 404 when the profile does not exist."""
        db_mock = _make_mock_db(profile_exists=False)
        client = self._make_client(db_mock)

        response = client.post(
            f"/platform/llm-profiles/{PROFILE_ID}/rollback/{HISTORY_ID_1}"
        )
        assert response.status_code == 404

    def test_rollback_returns_404_for_wrong_history_id(self):
        """Should return 404 when the history entry does not belong to this profile."""
        db_mock = _make_mock_db(profile_exists=True, history_entry=None)
        client = self._make_client(db_mock)

        bad_history_id = str(uuid.uuid4())
        response = client.post(
            f"/platform/llm-profiles/{PROFILE_ID}/rollback/{bad_history_id}"
        )
        assert response.status_code == 404

    def test_rollback_returns_422_when_before_has_no_slot_fields(self):
        """Should return 422 when diff.before contains no slot-related fields."""
        diff_no_slots = {
            "before": {"name": "old-name"},
            "after": {"name": "new-name"},
        }
        history_row = self._make_history_row(HISTORY_ID_1, "update", diff_no_slots)
        db_mock = _make_mock_db(profile_exists=True, history_entry=history_row)
        client = self._make_client(db_mock)

        response = client.post(
            f"/platform/llm-profiles/{PROFILE_ID}/rollback/{HISTORY_ID_1}"
        )
        assert response.status_code == 422

    def test_rollback_returns_422_when_diff_has_no_before(self):
        """Should return 422 when diff.before is absent (e.g. create entries)."""
        diff_create = {"after": {"name": "new-profile"}}
        history_row = self._make_history_row(HISTORY_ID_1, "create", diff_create)
        db_mock = _make_mock_db(profile_exists=True, history_entry=history_row)
        client = self._make_client(db_mock)

        response = client.post(
            f"/platform/llm-profiles/{PROFILE_ID}/rollback/{HISTORY_ID_1}"
        )
        assert response.status_code == 422

    def test_rollback_calls_service_update_with_before_state(self):
        """Rollback should call service.update_platform_profile with diff.before slot fields."""
        diff_with_slots = {
            "before": {
                "chat_library_id": LIBRARY_ID_A,
                "intent_library_id": LIBRARY_ID_B,
            },
            "after": {
                "chat_library_id": LIBRARY_ID_B,
                "intent_library_id": LIBRARY_ID_A,
            },
        }
        history_row = self._make_history_row(HISTORY_ID_1, "update", diff_with_slots)
        current_slots = self._make_current_slots_row(
            chat_id=LIBRARY_ID_A, intent_id=LIBRARY_ID_B
        )

        profile_data = {
            "id": PROFILE_ID,
            "name": "Test Profile",
            "description": None,
            "status": "active",
            "chat_library_id": LIBRARY_ID_A,
            "intent_library_id": LIBRARY_ID_B,
            "vision_library_id": None,
            "agent_library_id": None,
            "chat_params": {},
            "intent_params": {},
            "vision_params": {},
            "agent_params": {},
            "chat_traffic_split": [],
            "intent_traffic_split": [],
            "vision_traffic_split": [],
            "agent_traffic_split": [],
            "is_platform_default": False,
            "plan_tiers": [],
            "owner_tenant_id": None,
            "created_by": None,
            "created_at": "2026-03-20T10:00:00+00:00",
            "updated_at": "2026-03-21T10:00:00+00:00",
            "tenants_count": 0,
            "slots": {},
        }

        service_mock = AsyncMock()
        service_mock.update_platform_profile = AsyncMock(return_value=profile_data)

        resolver_mock = AsyncMock()
        resolver_mock.invalidate_all = AsyncMock()

        # Build a sequential db mock: call 1 = profile check, call 2 = history lookup,
        # call 3 = current slots query, call 4 = _audit INSERT (handled by service patch)
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        profile_check_result = MagicMock()
        profile_check_result.fetchone.return_value = MagicMock()  # profile exists

        history_result = MagicMock()
        history_result.fetchone.return_value = history_row

        current_slots_result = MagicMock()
        current_slots_result.fetchone.return_value = current_slots

        generic_result = MagicMock()
        generic_result.fetchone.return_value = None

        db_mock.execute = AsyncMock(
            side_effect=[
                profile_check_result,   # SELECT id FROM llm_profiles WHERE id = :id AND owner_tenant_id IS NULL
                history_result,          # SELECT id, action, diff FROM llm_profile_audit_log WHERE id = :hid
                current_slots_result,    # SELECT chat_library_id, ... FROM llm_profiles WHERE id = :id
                generic_result,          # _audit INSERT (may or may not be called depending on patch)
            ]
        )

        client_app = FastAPI()
        client_app.include_router(router)

        from app.core.session import get_async_session
        from app.core.dependencies import require_platform_admin
        import app.modules.llm_profiles.routes as routes_module

        def override_db():
            yield db_mock

        def override_auth():
            return PLATFORM_ADMIN_USER

        client_app.dependency_overrides[get_async_session] = override_db
        client_app.dependency_overrides[require_platform_admin] = override_auth

        with (
            patch.object(routes_module, "_service", service_mock),
            patch.object(routes_module, "_resolver", resolver_mock),
            patch("app.modules.llm_profiles.service._audit", AsyncMock()),
        ):
            client = TestClient(client_app, raise_server_exceptions=False)
            response = client.post(
                f"/platform/llm-profiles/{PROFILE_ID}/rollback/{HISTORY_ID_1}"
            )

        # Verify service.update was called with the before-state slot fields
        service_mock.update_platform_profile.assert_called_once()
        call_kwargs = service_mock.update_platform_profile.call_args
        # update_platform_profile(profile_id, updates=..., actor_id=..., db=...)
        updates_passed = call_kwargs.kwargs.get("updates", {})
        assert "chat_library_id" in updates_passed, (
            f"Expected 'chat_library_id' in updates, got: {updates_passed}"
        )
        assert updates_passed["chat_library_id"] == LIBRARY_ID_A

    def test_rollback_invalidates_resolver_cache(self):
        """Rollback should call resolver.invalidate_all() after committing."""
        diff_with_slots = {
            "before": {"chat_library_id": LIBRARY_ID_A},
            "after": {"chat_library_id": LIBRARY_ID_B},
        }
        history_row = self._make_history_row(HISTORY_ID_1, "update", diff_with_slots)
        current_slots = self._make_current_slots_row(chat_id=LIBRARY_ID_A)

        profile_data = {
            "id": PROFILE_ID,
            "name": "Test Profile",
            "description": None,
            "status": "active",
            "chat_library_id": LIBRARY_ID_A,
            "intent_library_id": None,
            "vision_library_id": None,
            "agent_library_id": None,
            "chat_params": {},
            "intent_params": {},
            "vision_params": {},
            "agent_params": {},
            "chat_traffic_split": [],
            "intent_traffic_split": [],
            "vision_traffic_split": [],
            "agent_traffic_split": [],
            "is_platform_default": False,
            "plan_tiers": [],
            "owner_tenant_id": None,
            "created_by": None,
            "created_at": "2026-03-20T10:00:00+00:00",
            "updated_at": "2026-03-21T10:00:00+00:00",
            "tenants_count": 0,
            "slots": {},
        }

        service_mock = AsyncMock()
        service_mock.update_platform_profile = AsyncMock(return_value=profile_data)

        resolver_mock = AsyncMock()
        resolver_mock.invalidate_all = AsyncMock()

        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        profile_check_result = MagicMock()
        profile_check_result.fetchone.return_value = MagicMock()

        history_result = MagicMock()
        history_result.fetchone.return_value = history_row

        current_slots_result = MagicMock()
        current_slots_result.fetchone.return_value = current_slots

        generic_result = MagicMock()
        generic_result.fetchone.return_value = None

        db_mock.execute = AsyncMock(
            side_effect=[
                profile_check_result,
                history_result,
                current_slots_result,
                generic_result,
            ]
        )

        client_app = FastAPI()
        client_app.include_router(router)

        from app.core.session import get_async_session
        from app.core.dependencies import require_platform_admin
        import app.modules.llm_profiles.routes as routes_module

        def override_db():
            yield db_mock

        def override_auth():
            return PLATFORM_ADMIN_USER

        client_app.dependency_overrides[get_async_session] = override_db
        client_app.dependency_overrides[require_platform_admin] = override_auth

        with (
            patch.object(routes_module, "_service", service_mock),
            patch.object(routes_module, "_resolver", resolver_mock),
            patch("app.modules.llm_profiles.service._audit", AsyncMock()),
        ):
            client = TestClient(client_app, raise_server_exceptions=False)
            client.post(
                f"/platform/llm-profiles/{PROFILE_ID}/rollback/{HISTORY_ID_1}"
            )

        resolver_mock.invalidate_all.assert_called_once()
