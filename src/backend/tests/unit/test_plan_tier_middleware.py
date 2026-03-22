"""
Unit tests for plan tier enforcement middleware (TODO-32 / TODO-34).

Tests validate:
- require_plan() rejects callers on wrong plan
- require_plan() passes callers on correct plan
- require_plan_or_above() tier ordering
- 403 error message does not reveal required plan
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.core.middleware.plan_tier import require_plan, require_plan_or_above


def _make_user(plan: str):
    """Build a mock CurrentUser with a given plan."""
    user = MagicMock()
    user.plan = plan
    user.id = "user-abc"
    user.tenant_id = "tenant-xyz"
    user.roles = ["tenant_admin"]
    return user


async def _invoke_dep(dep_factory, *args, user):
    """Invoke a require_plan dependency by injecting the user directly.

    Bypasses Depends(require_tenant_admin) by patching it with a stub
    that returns the supplied mock user.
    """
    from unittest.mock import patch
    from app.core.middleware import plan_tier as _pt_module

    # The inner _dependency captures `require_tenant_admin` from app.core.dependencies.
    # Patch it so FastAPI's Depends is satisfied with our mock user.
    with patch("app.core.middleware.plan_tier.require_tenant_admin", return_value=user):
        inner = dep_factory(*args)
        # inner is a coroutine function whose only Depends arg resolves to `user`
        return await inner(current_user=user)


class TestRequirePlan:
    """require_plan() factory."""

    def test_raises_value_error_with_no_plans(self):
        with pytest.raises(ValueError, match="at least one"):
            require_plan()

    @pytest.mark.asyncio
    async def test_passes_matching_plan(self):
        """Enterprise user on enterprise-only endpoint returns the user object."""
        user = _make_user("enterprise")
        result = await _invoke_dep(require_plan, "enterprise", user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_blocks_non_matching_plan(self):
        """Starter tenant attempting enterprise-only endpoint gets 403."""
        user = _make_user("starter")
        with pytest.raises(HTTPException) as exc_info:
            await _invoke_dep(require_plan, "enterprise", user=user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_403_message_does_not_reveal_required_plan(self):
        """The 403 detail must not disclose what plan is required."""
        user = _make_user("starter")
        with pytest.raises(HTTPException) as exc_info:
            await _invoke_dep(require_plan, "enterprise", user=user)
        detail = exc_info.value.detail
        assert "enterprise" not in str(detail)
        assert "professional" not in str(detail)
        assert "starter" not in str(detail)

    @pytest.mark.asyncio
    async def test_multi_allowed_passes_any_matching(self):
        """professional user allowed when both professional and enterprise accepted."""
        user = _make_user("professional")
        result = await _invoke_dep(require_plan, "professional", "enterprise", user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_multi_allowed_blocks_missing(self):
        """starter user blocked when only professional and enterprise accepted."""
        user = _make_user("starter")
        with pytest.raises(HTTPException) as exc_info:
            await _invoke_dep(require_plan, "professional", "enterprise", user=user)
        assert exc_info.value.status_code == 403

    def test_error_message_generic(self):
        """The 403 detail must not reveal the required plan."""
        from app.core.middleware.plan_tier import _GENERIC_PLAN_ERROR

        assert "enterprise" not in _GENERIC_PLAN_ERROR
        assert "professional" not in _GENERIC_PLAN_ERROR
        assert "starter" not in _GENERIC_PLAN_ERROR
        assert "plan" in _GENERIC_PLAN_ERROR.lower() or "feature" in _GENERIC_PLAN_ERROR.lower()

    def test_require_plan_returns_callable(self):
        dep = require_plan("enterprise")
        assert callable(dep)


class TestRequirePlanOrAbove:
    """require_plan_or_above() tier ordering."""

    def test_starter_minimum_allows_all_plans(self):
        # plan_or_above("starter") should include starter, professional, enterprise
        from app.core.middleware.plan_tier import _PLAN_ORDER

        min_idx = _PLAN_ORDER.index("starter")
        allowed = set(_PLAN_ORDER[min_idx:])
        assert "starter" in allowed
        assert "professional" in allowed
        assert "enterprise" in allowed

    def test_professional_minimum_excludes_starter(self):
        from app.core.middleware.plan_tier import _PLAN_ORDER

        min_idx = _PLAN_ORDER.index("professional")
        allowed = set(_PLAN_ORDER[min_idx:])
        assert "starter" not in allowed
        assert "professional" in allowed
        assert "enterprise" in allowed

    def test_enterprise_minimum_allows_only_enterprise(self):
        from app.core.middleware.plan_tier import _PLAN_ORDER

        min_idx = _PLAN_ORDER.index("enterprise")
        allowed = set(_PLAN_ORDER[min_idx:])
        assert "starter" not in allowed
        assert "professional" not in allowed
        assert "enterprise" in allowed

    def test_raises_for_unknown_plan(self):
        with pytest.raises(ValueError, match="Unknown plan"):
            require_plan_or_above("gold")

    def test_returns_callable(self):
        dep = require_plan_or_above("professional")
        assert callable(dep)
