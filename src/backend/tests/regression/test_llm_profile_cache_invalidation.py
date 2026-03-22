"""
Regression tests for LLM Profile cache invalidation and dual-default prevention.

RED TEAM round 1 findings:
  CRITICAL-3: ProfileResolver.invalidate() never called from llm_profiles routes
  CRITICAL-4: create_platform_profile allowed two profiles to have is_platform_default=true
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.regression
def test_profile_resolver_has_invalidate_all():
    """CRITICAL-3: ProfileResolver must expose invalidate_all() for platform-wide changes."""
    import inspect
    from app.core.llm.profile_resolver import ProfileResolver

    resolver = ProfileResolver()
    assert hasattr(resolver, "invalidate_all"), (
        "ProfileResolver must have invalidate_all() method for platform-wide cache invalidation"
    )
    assert inspect.iscoroutinefunction(resolver.invalidate_all), (
        "ProfileResolver.invalidate_all() must be async"
    )


@pytest.mark.regression
def test_llm_profiles_routes_imports_profile_resolver():
    """CRITICAL-3: llm_profiles/routes.py must import and use ProfileResolver."""
    import inspect
    from app.modules.llm_profiles import routes

    source = inspect.getsource(routes)
    assert "ProfileResolver" in source, (
        "llm_profiles/routes.py must import ProfileResolver to invalidate caches on writes"
    )
    assert "invalidate_all" in source, (
        "llm_profiles/routes.py must call invalidate_all() after write operations"
    )


@pytest.mark.regression
def test_create_platform_profile_source_clears_existing_default():
    """CRITICAL-4: When creating a profile with is_platform_default=True,
    the service must first clear the is_platform_default flag on any existing default.

    Without this fix, two profiles can have is_platform_default=True simultaneously,
    causing non-deterministic profile resolution for tenants.

    Verifies the UPDATE guard is present and ordered before the INSERT.
    """
    import inspect
    from app.modules.llm_profiles.service import LLMProfileService

    source = inspect.getsource(LLMProfileService.create_platform_profile)

    # The UPDATE must appear before the INSERT
    update_pos = source.find("UPDATE llm_profiles")
    insert_pos = source.find("INSERT INTO llm_profiles")

    assert update_pos != -1, (
        "create_platform_profile must contain UPDATE to clear is_platform_default "
        "before inserting new default"
    )
    assert insert_pos != -1, "create_platform_profile must INSERT new profile"
    assert update_pos < insert_pos, (
        "UPDATE (clear existing default) must come BEFORE INSERT (new default) — "
        "otherwise the new profile's is_platform_default=True is cleared by the UPDATE"
    )


@pytest.mark.regression
def test_create_platform_profile_service_has_clear_default_logic():
    """CRITICAL-4: Source code must contain atomic default-clearing logic in create."""
    import inspect
    from app.modules.llm_profiles.service import LLMProfileService

    source = inspect.getsource(LLMProfileService.create_platform_profile)
    # The fix: UPDATE ... SET is_platform_default = false ... before INSERT
    assert "is_platform_default = false" in source, (
        "create_platform_profile must clear existing defaults before setting the new one"
    )
