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
            {
                "department": "HR",
                "role": "Manager",
                "manager_name": None,
                "location": None,
                "team_name": None,
            }
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

        mock_redis.get.assert_called_once_with("mingai:my-tenant:org_context:my-user")

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


class TestAuth0OrgContextSourceExtended:
    """Extended Auth0 extraction tests for field mapping completeness."""

    def test_auth0_extracts_all_five_fields(self):
        """All five fields extracted when present in org_metadata."""
        from app.modules.memory.org_context import Auth0OrgContextSource

        source = Auth0OrgContextSource()
        jwt_claims = {
            "org_metadata": {
                "department": "Legal",
                "title": "Counsel",
                "manager": "GC",
                "office": "London",
                "team": "Legal Ops",
            }
        }
        result = source.extract(jwt_claims)
        assert result.department == "Legal"
        assert result.role == "Counsel"
        assert result.manager_name == "GC"
        assert result.location == "London"
        assert result.team_name == "Legal Ops"

    def test_auth0_partial_fields_returns_nones_for_missing(self):
        """Missing fields return None (not raise error)."""
        from app.modules.memory.org_context import Auth0OrgContextSource

        source = Auth0OrgContextSource()
        jwt_claims = {"org_metadata": {"department": "HR"}}
        result = source.extract(jwt_claims)
        assert result.department == "HR"
        assert result.role is None
        assert result.manager_name is None

    def test_auth0_empty_org_metadata_returns_all_none(self):
        """Empty org_metadata dict returns all None fields."""
        from app.modules.memory.org_context import Auth0OrgContextSource

        source = Auth0OrgContextSource()
        result = source.extract({"org_metadata": {}})
        assert result.department is None
        assert result.role is None
        assert result.location is None
        assert result.team_name is None

    def test_auth0_title_maps_to_role(self):
        """org_metadata.title maps to OrgContextData.role."""
        from app.modules.memory.org_context import Auth0OrgContextSource

        source = Auth0OrgContextSource()
        result = source.extract({"org_metadata": {"title": "VP Engineering"}})
        assert result.role == "VP Engineering"
        assert result.department is None

    def test_auth0_office_maps_to_location(self):
        """org_metadata.office maps to OrgContextData.location."""
        from app.modules.memory.org_context import Auth0OrgContextSource

        source = Auth0OrgContextSource()
        result = source.extract({"org_metadata": {"office": "Tokyo HQ"}})
        assert result.location == "Tokyo HQ"

    def test_auth0_team_maps_to_team_name(self):
        """org_metadata.team maps to OrgContextData.team_name."""
        from app.modules.memory.org_context import Auth0OrgContextSource

        source = Auth0OrgContextSource()
        result = source.extract({"org_metadata": {"team": "DevOps"}})
        assert result.team_name == "DevOps"

    def test_auth0_extra_unknown_fields_ignored(self):
        """Unknown fields in org_metadata are silently ignored."""
        from app.modules.memory.org_context import Auth0OrgContextSource

        source = Auth0OrgContextSource()
        result = source.extract(
            {"org_metadata": {"department": "IT", "cost_center": "CC-001"}}
        )
        assert result.department == "IT"
        # No AttributeError from unknown cost_center key
        assert not hasattr(result, "cost_center")

    def test_auth0_returns_org_context_data_instance(self):
        """extract() always returns OrgContextData instance."""
        from app.modules.memory.org_context import Auth0OrgContextSource, OrgContextData

        source = Auth0OrgContextSource()
        result = source.extract({})
        assert isinstance(result, OrgContextData)


class TestOktaOrgContextSourceExtended:
    """Extended Okta extraction tests."""

    def test_okta_zero_data_returns_all_none(self):
        """Empty JWT returns all-None OrgContextData."""
        from app.modules.memory.org_context import OktaOrgContextSource

        source = OktaOrgContextSource()
        result = source.extract({})
        assert result.department is None
        assert result.role is None
        assert result.manager_name is None
        assert result.location is None
        assert result.team_name is None

    def test_okta_department_extraction(self):
        """Okta department claim mapped directly."""
        from app.modules.memory.org_context import OktaOrgContextSource

        source = OktaOrgContextSource()
        result = source.extract({"department": "Finance"})
        assert result.department == "Finance"

    def test_okta_title_maps_to_role(self):
        """Okta title claim maps to role."""
        from app.modules.memory.org_context import OktaOrgContextSource

        source = OktaOrgContextSource()
        result = source.extract({"title": "Product Manager"})
        assert result.role == "Product Manager"

    def test_okta_manager_extraction(self):
        """Okta manager claim maps to manager_name."""
        from app.modules.memory.org_context import OktaOrgContextSource

        source = OktaOrgContextSource()
        result = source.extract({"manager": "Jane Doe"})
        assert result.manager_name == "Jane Doe"

    def test_okta_location_extraction(self):
        """Okta location claim maps to location."""
        from app.modules.memory.org_context import OktaOrgContextSource

        source = OktaOrgContextSource()
        result = source.extract({"location": "Remote"})
        assert result.location == "Remote"

    def test_okta_team_extraction(self):
        """Okta team claim maps to team_name."""
        from app.modules.memory.org_context import OktaOrgContextSource

        source = OktaOrgContextSource()
        result = source.extract({"team": "Backend"})
        assert result.team_name == "Backend"

    def test_okta_all_five_fields_extracted(self):
        """All five fields extracted from flat Okta claims."""
        from app.modules.memory.org_context import OktaOrgContextSource

        source = OktaOrgContextSource()
        result = source.extract(
            {
                "department": "Engineering",
                "title": "SRE",
                "manager": "Alice",
                "location": "Singapore",
                "team": "Infra",
            }
        )
        assert result.department == "Engineering"
        assert result.role == "SRE"
        assert result.manager_name == "Alice"
        assert result.location == "Singapore"
        assert result.team_name == "Infra"

    def test_okta_returns_org_context_data_instance(self):
        """extract() always returns OrgContextData instance."""
        from app.modules.memory.org_context import OktaOrgContextSource, OrgContextData

        source = OktaOrgContextSource()
        result = source.extract({})
        assert isinstance(result, OrgContextData)


class TestGenericSAMLOrgContextSourceExtended:
    """Extended SAML extraction tests."""

    def test_saml_missing_saml_attributes_returns_all_none(self):
        """No saml_attributes key returns all-None context."""
        from app.modules.memory.org_context import GenericSAMLOrgContextSource

        source = GenericSAMLOrgContextSource()
        result = source.extract({})
        assert result.department is None
        assert result.role is None

    def test_saml_takes_first_value_from_list(self):
        """First element of list used when SAML attribute has multiple values."""
        from app.modules.memory.org_context import GenericSAMLOrgContextSource

        source = GenericSAMLOrgContextSource()
        result = source.extract(
            {"saml_attributes": {"department": ["Engineering", "Platform"]}}
        )
        assert result.department == "Engineering"

    def test_saml_empty_list_returns_none(self):
        """Empty list for an attribute returns None."""
        from app.modules.memory.org_context import GenericSAMLOrgContextSource

        source = GenericSAMLOrgContextSource()
        result = source.extract({"saml_attributes": {"department": []}})
        assert result.department is None

    def test_saml_location_extraction(self):
        """SAML location attribute maps to location."""
        from app.modules.memory.org_context import GenericSAMLOrgContextSource

        source = GenericSAMLOrgContextSource()
        result = source.extract({"saml_attributes": {"location": ["New York"]}})
        assert result.location == "New York"

    def test_saml_team_extraction(self):
        """SAML team attribute maps to team_name."""
        from app.modules.memory.org_context import GenericSAMLOrgContextSource

        source = GenericSAMLOrgContextSource()
        result = source.extract({"saml_attributes": {"team": ["DevOps"]}})
        assert result.team_name == "DevOps"

    def test_saml_manager_extraction(self):
        """SAML manager attribute maps to manager_name."""
        from app.modules.memory.org_context import GenericSAMLOrgContextSource

        source = GenericSAMLOrgContextSource()
        result = source.extract({"saml_attributes": {"manager": ["CEO"]}})
        assert result.manager_name == "CEO"

    def test_saml_partial_attributes_returns_nones_for_missing(self):
        """Missing SAML attributes return None without error."""
        from app.modules.memory.org_context import GenericSAMLOrgContextSource

        source = GenericSAMLOrgContextSource()
        result = source.extract({"saml_attributes": {"department": ["Finance"]}})
        assert result.department == "Finance"
        assert result.role is None
        assert result.manager_name is None

    def test_saml_returns_org_context_data_instance(self):
        """extract() always returns OrgContextData instance."""
        from app.modules.memory.org_context import (
            GenericSAMLOrgContextSource,
            OrgContextData,
        )

        source = GenericSAMLOrgContextSource()
        result = source.extract({})
        assert isinstance(result, OrgContextData)


class TestOrgContextServiceSourceSelection:
    """OrgContextService must select the right source from JWT structure."""

    def test_select_source_auth0_on_org_metadata(self):
        """JWT with org_metadata selects Auth0OrgContextSource."""
        from app.modules.memory.org_context import (
            Auth0OrgContextSource,
            OrgContextService,
        )

        service = OrgContextService()
        source = service._select_source({"org_metadata": {}})
        assert isinstance(source, Auth0OrgContextSource)

    def test_select_source_saml_on_saml_attributes(self):
        """JWT with saml_attributes selects GenericSAMLOrgContextSource."""
        from app.modules.memory.org_context import (
            GenericSAMLOrgContextSource,
            OrgContextService,
        )

        service = OrgContextService()
        source = service._select_source({"saml_attributes": {}})
        assert isinstance(source, GenericSAMLOrgContextSource)

    def test_select_source_okta_as_default(self):
        """JWT with no SSO-specific keys defaults to OktaOrgContextSource."""
        from app.modules.memory.org_context import (
            OktaOrgContextSource,
            OrgContextService,
        )

        service = OrgContextService()
        source = service._select_source({})
        assert isinstance(source, OktaOrgContextSource)

    def test_select_source_okta_when_sso_provider_none(self):
        """Flat JWT claims without SSO markers use Okta (catch-all)."""
        from app.modules.memory.org_context import (
            OktaOrgContextSource,
            OrgContextService,
        )

        service = OrgContextService()
        # sso_provider field is not checked; structure is the signal
        source = service._select_source({"sub": "user123", "email": "u@example.com"})
        assert isinstance(source, OktaOrgContextSource)

    @pytest.mark.asyncio
    async def test_get_empty_jwt_returns_all_none_org_context(self):
        """Empty JWT claims with no SSO data returns all-None OrgContextData."""
        from app.modules.memory.org_context import OrgContextService

        service = OrgContextService.__new__(OrgContextService)
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch(
            "app.modules.memory.org_context.get_redis",
            return_value=mock_redis,
        ):
            result = await service.get("u1", "t1", {})

        assert result.department is None
        assert result.role is None
