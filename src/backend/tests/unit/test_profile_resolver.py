"""
Unit tests for ProfileResolver (TODO-30 / TODO-34).

Tests validate:
- Feature flag gate (LLM_PROFILE_SLOT_ROUTING)
- In-process LRU cache hit/miss/expiry
- ResolvedProfile and ResolvedSlot data classes
- Cache serialization round-trip
"""
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.llm.profile_resolver import (
    ProfileResolver,
    ResolvedProfile,
    ResolvedSlot,
    _REDIS_TTL_SECONDS,
    _LRU_TTL_SECONDS,
    _lru_cache,
    _slot_routing_enabled,
)


class TestSlotRoutingFlag:
    """Feature flag LLM_PROFILE_SLOT_ROUTING controls resolver activation."""

    def test_flag_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_PROFILE_SLOT_ROUTING", None)
            assert _slot_routing_enabled() is False

    def test_flag_enabled_when_set_to_1(self):
        with patch.dict(os.environ, {"LLM_PROFILE_SLOT_ROUTING": "1"}):
            assert _slot_routing_enabled() is True

    def test_flag_disabled_when_set_to_0(self):
        with patch.dict(os.environ, {"LLM_PROFILE_SLOT_ROUTING": "0"}):
            assert _slot_routing_enabled() is False

    def test_flag_disabled_for_other_values(self):
        for val in ("true", "yes", "on", "True"):
            with patch.dict(os.environ, {"LLM_PROFILE_SLOT_ROUTING": val}):
                assert _slot_routing_enabled() is False


class TestResolvedSlot:
    """ResolvedSlot is a frozen dataclass."""

    def test_create_with_all_fields(self):
        slot = ResolvedSlot(
            slot="chat",
            library_id="abc123",
            params={"temperature": 0.7},
            traffic_split=[{"library_id": "abc123", "weight": 100}],
        )
        assert slot.slot == "chat"
        assert slot.library_id == "abc123"
        assert slot.params["temperature"] == 0.7

    def test_create_with_defaults(self):
        slot = ResolvedSlot(slot="intent", library_id=None)
        assert slot.params == {}
        assert slot.traffic_split == []

    def test_frozen_cannot_mutate(self):
        slot = ResolvedSlot(slot="chat", library_id="abc")
        with pytest.raises((AttributeError, TypeError)):
            slot.library_id = "changed"  # type: ignore[misc]


class TestResolvedProfile:
    """ResolvedProfile serialization and get_slot."""

    def _make_profile(self) -> ResolvedProfile:
        return ResolvedProfile(
            profile_id="prof-001",
            profile_name="Test Profile",
            owner_tenant_id=None,
            slots={
                "chat": ResolvedSlot(slot="chat", library_id="lib-chat"),
                "intent": ResolvedSlot(slot="intent", library_id="lib-intent"),
                "vision": ResolvedSlot(slot="vision", library_id=None),
                "agent": ResolvedSlot(slot="agent", library_id=None),
            },
        )

    def test_get_slot_returns_correct_slot(self):
        profile = self._make_profile()
        slot = profile.get_slot("chat")
        assert slot is not None
        assert slot.library_id == "lib-chat"

    def test_get_slot_returns_none_for_unknown(self):
        profile = self._make_profile()
        assert profile.get_slot("unknown") is None

    def test_cache_round_trip(self):
        profile = self._make_profile()
        d = profile.to_cache_dict()
        restored = ResolvedProfile.from_cache_dict(d)

        assert restored.profile_id == "prof-001"
        assert restored.profile_name == "Test Profile"
        assert restored.owner_tenant_id is None
        assert restored.get_slot("chat").library_id == "lib-chat"
        assert restored.get_slot("intent").library_id == "lib-intent"
        assert restored.get_slot("vision").library_id is None

    def test_cache_dict_does_not_contain_slot_objects(self):
        """Serialized form must contain plain dicts, not ResolvedSlot instances."""
        profile = self._make_profile()
        d = profile.to_cache_dict()
        for slot_data in d["slots"].values():
            assert not isinstance(slot_data, ResolvedSlot)
            assert isinstance(slot_data, dict)


class TestLRUCache:
    """In-process LRU cache hit/miss/expiry behaviour."""

    def setup_method(self):
        """Clear LRU before each test."""
        _lru_cache.clear()

    def test_cache_miss_returns_none(self):
        resolver = ProfileResolver()
        result = resolver._lru_get("nonexistent_key")
        assert result is None

    def test_cache_set_then_get_returns_profile(self):
        resolver = ProfileResolver()
        profile = ResolvedProfile(
            profile_id="p1",
            profile_name="P1",
            owner_tenant_id=None,
            slots={},
        )
        resolver._lru_set("key1", profile)
        result = resolver._lru_get("key1")
        assert result is not None
        assert result.profile_id == "p1"

    def test_expired_entry_returns_none(self):
        resolver = ProfileResolver()
        profile = ResolvedProfile(
            profile_id="p2",
            profile_name="P2",
            owner_tenant_id=None,
            slots={},
        )
        # Manually insert an already-expired entry
        _lru_cache["expiry_key"] = (time.time() - 1, profile.to_cache_dict())
        result = resolver._lru_get("expiry_key")
        assert result is None
        # Expired entry must be evicted
        assert "expiry_key" not in _lru_cache


class TestProfileResolverFlagGate:
    """resolve() returns None immediately when flag is disabled."""

    def setup_method(self):
        _lru_cache.clear()

    @pytest.mark.asyncio
    async def test_returns_none_when_flag_disabled(self):
        resolver = ProfileResolver()
        mock_db = AsyncMock()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_PROFILE_SLOT_ROUTING", None)
            result = await resolver.resolve("tenant-1", "professional", mock_db)
        assert result is None
        # DB should not be touched
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_queries_db_when_flag_enabled(self):
        """When flag is on and caches miss, DB is consulted."""
        resolver = ProfileResolver()
        mock_db = AsyncMock()

        # tenants.llm_profile_id, plan → (None, None)
        # Step 1 query now selects two columns: llm_profile_id and plan.
        tenant_result = MagicMock()
        tenant_result.fetchone.return_value = (None, None)

        # BYOLLM profile → None
        byollm_result = MagicMock()
        byollm_result.fetchone.return_value = None

        # Platform default → None
        default_result = MagicMock()
        default_result.fetchone.return_value = None

        mock_db.execute.side_effect = [tenant_result, byollm_result, default_result]

        with patch.dict(os.environ, {"LLM_PROFILE_SLOT_ROUTING": "1"}):
            with patch.object(resolver, "_redis_get", new=AsyncMock(return_value=None)):
                with patch.object(resolver, "_redis_set", new=AsyncMock()):
                    result = await resolver.resolve("tenant-abc", "professional", mock_db)

        assert result is None
        assert mock_db.execute.call_count == 3

    @pytest.mark.asyncio
    async def test_resolution_error_returns_none_gracefully(self):
        """DB errors must not propagate — return None and log warning."""
        resolver = ProfileResolver()
        mock_db = AsyncMock()
        mock_db.execute.side_effect = RuntimeError("DB connection lost")

        with patch.dict(os.environ, {"LLM_PROFILE_SLOT_ROUTING": "1"}):
            with patch.object(resolver, "_redis_get", new=AsyncMock(return_value=None)):
                result = await resolver.resolve("tenant-err", "enterprise", mock_db)

        assert result is None
