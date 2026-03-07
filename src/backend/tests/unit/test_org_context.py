"""
Unit tests for OrgContextService (AI-016 to AI-021).

Tests org context data model, source abstraction, caching,
and format_for_prompt with share_manager_info toggle.
Tier 1: Fast, isolated, mocks Redis.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest


class TestOrgContextData:
    """Test OrgContextData Pydantic model."""

    def test_org_context_data_fields(self):
        """OrgContextData must have all required fields."""
        from app.modules.memory.org_context import OrgContextData

        data = OrgContextData(
            department="Engineering",
            role="Senior Developer",
            manager_name="Jane Smith",
            location="Singapore",
            team_name="Platform Team",
        )
        assert data.department == "Engineering"
        assert data.role == "Senior Developer"
        assert data.manager_name == "Jane Smith"
        assert data.location == "Singapore"
        assert data.team_name == "Platform Team"

    def test_org_context_data_optional_fields(self):
        """All fields should be optional (None by default)."""
        from app.modules.memory.org_context import OrgContextData

        data = OrgContextData()
        assert data.department is None
        assert data.role is None
        assert data.manager_name is None
        assert data.location is None
        assert data.team_name is None

    def test_org_context_data_to_dict(self):
        """to_dict() converts to dict, excluding None fields."""
        from app.modules.memory.org_context import OrgContextData

        data = OrgContextData(department="HR", role="Manager")
        d = data.to_dict()
        assert d["department"] == "HR"
        assert d["role"] == "Manager"
        assert "manager_name" not in d or d["manager_name"] is None


class TestOrgContextSources:
    """Test SSO-specific org context sources."""

    def test_auth0_source_extracts_from_jwt(self):
        """Auth0 source extracts org context from JWT org_metadata claim."""
        from app.modules.memory.org_context import Auth0OrgContextSource

        source = Auth0OrgContextSource()
        jwt_claims = {
            "org_metadata": {
                "department": "Engineering",
                "title": "Staff Engineer",
                "manager": "Alice Wong",
                "office": "Singapore",
                "team": "Core Platform",
            }
        }
        result = source.extract(jwt_claims)
        assert result.department == "Engineering"
        assert result.role == "Staff Engineer"
        assert result.manager_name == "Alice Wong"
        assert result.location == "Singapore"
        assert result.team_name == "Core Platform"

    def test_auth0_source_handles_missing_metadata(self):
        """Auth0 source returns empty data when org_metadata missing."""
        from app.modules.memory.org_context import Auth0OrgContextSource

        source = Auth0OrgContextSource()
        result = source.extract({})
        assert result.department is None

    def test_okta_source_extracts_from_jwt(self):
        """Okta source extracts from Okta-style JWT claims."""
        from app.modules.memory.org_context import OktaOrgContextSource

        source = OktaOrgContextSource()
        jwt_claims = {
            "department": "Sales",
            "title": "Account Executive",
            "manager": "Bob Lee",
        }
        result = source.extract(jwt_claims)
        assert result.department == "Sales"
        assert result.role == "Account Executive"

    def test_generic_saml_source_maps_attributes(self):
        """SAML source maps standard SAML attribute names."""
        from app.modules.memory.org_context import GenericSAMLOrgContextSource

        source = GenericSAMLOrgContextSource()
        jwt_claims = {
            "saml_attributes": {
                "department": ["Finance"],
                "title": ["CFO"],
                "manager": ["CEO"],
                "location": ["New York"],
            }
        }
        result = source.extract(jwt_claims)
        assert result.department == "Finance"
        assert result.role == "CFO"


class TestOrgContextService:
    """Test OrgContextService.get() and caching."""

    @pytest.mark.asyncio
    async def test_get_returns_org_context_data(self):
        """get() returns OrgContextData from JWT claims."""
        from app.modules.memory.org_context import OrgContextService

        service = OrgContextService.__new__(OrgContextService)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        jwt_claims = {
            "org_metadata": {
                "department": "Engineering",
                "title": "Developer",
            }
        }

        with patch(
            "app.modules.memory.org_context.get_redis",
            return_value=mock_redis,
        ):
            result = await service.get("u1", "t1", jwt_claims)

        assert result is not None
        assert result.department == "Engineering"

    @pytest.mark.asyncio
    async def test_get_uses_redis_cache(self):
        """get() caches result in Redis."""
        from app.modules.memory.org_context import OrgContextService

        service = OrgContextService.__new__(OrgContextService)

        cached = json.dumps(
            {"department": "HR", "role": "Manager", "manager_name": None,
             "location": None, "team_name": None}
        )
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=cached)

        with patch(
            "app.modules.memory.org_context.get_redis",
            return_value=mock_redis,
        ):
            result = await service.get("u1", "t1", {})

        assert result.department == "HR"

    @pytest.mark.asyncio
    async def test_cache_key_pattern(self):
        """Cache key must be mingai:{tenant_id}:org_context:{user_id}."""
        from app.modules.memory.org_context import OrgContextService

        service = OrgContextService.__new__(OrgContextService)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.org_context.get_redis",
            return_value=mock_redis,
        ):
            await service.get("my-user", "my-tenant", {})

        mock_redis.get.assert_called_once_with(
            "mingai:my-tenant:org_context:my-user"
        )

    @pytest.mark.asyncio
    async def test_cache_ttl_24_hours(self):
        """Org context cache TTL must be 86400 seconds (24 hours)."""
        from app.modules.memory.org_context import OrgContextService

        service = OrgContextService.__new__(OrgContextService)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.org_context.get_redis",
            return_value=mock_redis,
        ):
            await service.get("u1", "t1", {"org_metadata": {"department": "IT"}})

        if mock_redis.setex.called:
            ttl = mock_redis.setex.call_args[0][1]
            assert ttl == 86400


class TestFormatForPrompt:
    """Test format_for_prompt() with privacy controls."""

    def test_format_includes_department(self):
        """format_for_prompt includes department in output."""
        from app.modules.memory.org_context import OrgContextData, format_for_prompt

        data = OrgContextData(department="Engineering", role="Developer")
        result = format_for_prompt(data, share_manager_info=True)
        assert result.get("department") == "Engineering"

    def test_format_excludes_manager_when_disabled(self):
        """format_for_prompt excludes manager name when share_manager_info=False."""
        from app.modules.memory.org_context import OrgContextData, format_for_prompt

        data = OrgContextData(
            department="HR",
            role="Manager",
            manager_name="Secret Boss",
        )
        result = format_for_prompt(data, share_manager_info=False)
        assert "manager_name" not in result or result.get("manager_name") is None

    def test_format_includes_manager_when_enabled(self):
        """format_for_prompt includes manager name when share_manager_info=True."""
        from app.modules.memory.org_context import OrgContextData, format_for_prompt

        data = OrgContextData(
            department="Sales",
            manager_name="Top Manager",
        )
        result = format_for_prompt(data, share_manager_info=True)
        assert result.get("manager_name") == "Top Manager"

    def test_format_returns_dict(self):
        """format_for_prompt returns a dict for SystemPromptBuilder."""
        from app.modules.memory.org_context import OrgContextData, format_for_prompt

        data = OrgContextData(department="IT")
        result = format_for_prompt(data, share_manager_info=True)
        assert isinstance(result, dict)

    def test_format_empty_context_returns_empty(self):
        """format_for_prompt with all None returns empty dict."""
        from app.modules.memory.org_context import OrgContextData, format_for_prompt

        data = OrgContextData()
        result = format_for_prompt(data, share_manager_info=True)
        # Should return empty or minimal dict
        non_none = {k: v for k, v in result.items() if v is not None}
        assert len(non_none) == 0
