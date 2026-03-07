"""
OrgContextService (AI-016 to AI-021).

Extracts organizational context from SSO JWT claims (Auth0, Okta, SAML).
Caches in Redis with 24-hour TTL. Budget: 100 tokens.

Redis key: mingai:{tenant_id}:org_context:{user_id}
All sources are JWT-only, zero external API calls.
"""
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import structlog

from app.core.redis_client import get_redis

logger = structlog.get_logger()

ORG_CONTEXT_CACHE_TTL_SECONDS = 86400  # 24 hours


@dataclass
class OrgContextData:
    """Organizational context data extracted from SSO claims."""

    department: str | None = None
    role: str | None = None
    manager_name: str | None = None
    location: str | None = None
    team_name: str | None = None

    def to_dict(self) -> dict:
        """Convert to dict for serialization."""
        return {
            "department": self.department,
            "role": self.role,
            "manager_name": self.manager_name,
            "location": self.location,
            "team_name": self.team_name,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OrgContextData":
        """Create from dict."""
        return cls(
            department=d.get("department"),
            role=d.get("role"),
            manager_name=d.get("manager_name"),
            location=d.get("location"),
            team_name=d.get("team_name"),
        )


class OrgContextSource(ABC):
    """Abstract base class for SSO-specific org context extraction."""

    @abstractmethod
    def extract(self, jwt_claims: dict) -> OrgContextData:
        """Extract org context from JWT claims."""
        ...


class Auth0OrgContextSource(OrgContextSource):
    """Extract org context from Auth0 JWT org_metadata claim."""

    def extract(self, jwt_claims: dict) -> OrgContextData:
        """
        Extract from Auth0's org_metadata claim.

        Auth0 stores org info under the 'org_metadata' key with fields:
        department, title, manager, office, team.
        """
        meta = jwt_claims.get("org_metadata", {})
        return OrgContextData(
            department=meta.get("department"),
            role=meta.get("title"),
            manager_name=meta.get("manager"),
            location=meta.get("office"),
            team_name=meta.get("team"),
        )


class OktaOrgContextSource(OrgContextSource):
    """Extract org context from Okta-style JWT claims."""

    def extract(self, jwt_claims: dict) -> OrgContextData:
        """
        Extract from Okta's flat JWT claims.

        Okta places org fields directly in the token: department, title, manager.
        """
        return OrgContextData(
            department=jwt_claims.get("department"),
            role=jwt_claims.get("title"),
            manager_name=jwt_claims.get("manager"),
            location=jwt_claims.get("location"),
            team_name=jwt_claims.get("team"),
        )


class GenericSAMLOrgContextSource(OrgContextSource):
    """Extract org context from SAML assertion attributes."""

    def extract(self, jwt_claims: dict) -> OrgContextData:
        """
        Extract from SAML attributes (typically arrays).

        SAML attributes are stored under 'saml_attributes' key,
        with each value as a list (SAML multi-value convention).
        """
        attrs = jwt_claims.get("saml_attributes", {})
        return OrgContextData(
            department=self._first(attrs.get("department")),
            role=self._first(attrs.get("title")),
            manager_name=self._first(attrs.get("manager")),
            location=self._first(attrs.get("location")),
            team_name=self._first(attrs.get("team")),
        )

    @staticmethod
    def _first(values: list | None) -> str | None:
        """Get first value from SAML multi-value attribute."""
        if values and isinstance(values, list) and len(values) > 0:
            return values[0]
        return None


# Source registry by SSO provider
_SOURCE_MAP = {
    "auth0": Auth0OrgContextSource,
    "okta": OktaOrgContextSource,
    "saml": GenericSAMLOrgContextSource,
}


class OrgContextService:
    """
    Service for loading and caching organizational context.

    Selects the appropriate SSO source based on JWT claims,
    caches results in Redis with 24-hour TTL.
    Budget: 100 tokens max.
    """

    async def get(
        self,
        user_id: str,
        tenant_id: str,
        jwt_claims: dict,
    ) -> OrgContextData:
        """
        Get org context for a user, with Redis caching.

        Args:
            user_id: User identifier.
            tenant_id: Tenant scope.
            jwt_claims: JWT token claims containing SSO org data.

        Returns:
            OrgContextData with extracted fields.
        """
        cache_key = f"mingai:{tenant_id}:org_context:{user_id}"
        redis = get_redis()

        # Check cache
        cached = await redis.get(cache_key)
        if cached:
            data = json.loads(cached)
            return OrgContextData.from_dict(data)

        # Extract from JWT claims
        source = self._select_source(jwt_claims)
        result = source.extract(jwt_claims)

        # Cache the result
        await redis.setex(
            cache_key,
            ORG_CONTEXT_CACHE_TTL_SECONDS,
            json.dumps(result.to_dict()),
        )

        logger.debug(
            "org_context_extracted",
            user_id=user_id,
            tenant_id=tenant_id,
            has_department=result.department is not None,
            has_role=result.role is not None,
        )

        return result

    @staticmethod
    def _select_source(jwt_claims: dict) -> OrgContextSource:
        """
        Select the appropriate org context source based on JWT structure.

        Detects the SSO provider from claim patterns:
        - 'org_metadata' key -> Auth0
        - 'saml_attributes' key -> SAML
        - Default -> Okta (flat claims)
        """
        if "org_metadata" in jwt_claims:
            return Auth0OrgContextSource()
        elif "saml_attributes" in jwt_claims:
            return GenericSAMLOrgContextSource()
        else:
            return OktaOrgContextSource()


def format_for_prompt(
    org_data: OrgContextData,
    share_manager_info: bool = True,
) -> dict:
    """
    Format org context for SystemPromptBuilder injection.

    Respects user's share_manager_info privacy toggle.
    Budget: 100 tokens max.

    Args:
        org_data: The org context data.
        share_manager_info: Whether to include manager name.

    Returns:
        Dict with non-None org context fields.
    """
    result = {}

    if org_data.department is not None:
        result["department"] = org_data.department
    if org_data.role is not None:
        result["role"] = org_data.role
    if org_data.location is not None:
        result["location"] = org_data.location
    if org_data.team_name is not None:
        result["team_name"] = org_data.team_name

    # Privacy control: only include manager if user allows it
    if share_manager_info and org_data.manager_name is not None:
        result["manager_name"] = org_data.manager_name

    return result
