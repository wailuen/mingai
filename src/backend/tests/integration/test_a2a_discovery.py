"""
ATA-017: A2A Discovery Endpoint Integration Tests

Tests for GET /.well-known/agent.json (ATA-016).

Uses the session-scoped TestClient from tests/conftest.py — no live server required.
Tests are isolated via monkeypatch to control PUBLIC_BASE_URL without side effects.
"""
import os

import pytest
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Forbidden fields — MUST NEVER appear in the discovery response per the
# SECURITY CONTRACT in app.modules.discovery.routes
# ---------------------------------------------------------------------------
_FORBIDDEN_FIELDS = [
    "tenant_id",
    "system_prompt",
    "kb_bindings",
    "credentials_vault_path",
    "access_rules",
]

_DISCOVERY_URL = "/.well-known/agent.json"
_TEST_BASE_URL = "https://test.example.com"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def discovery_client():
    """
    Module-scoped TestClient for discovery tests.

    Uses a dedicated TestClient instance so PUBLIC_BASE_URL manipulation
    doesn't bleed into the session-scoped client used by other integration tests.
    """
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDiscoveryEndpointWithBaseUrl:
    """Tests when PUBLIC_BASE_URL is configured."""

    def test_returns_200_with_json_content_type(self, discovery_client, monkeypatch):
        monkeypatch.setenv("PUBLIC_BASE_URL", _TEST_BASE_URL)

        resp = discovery_client.get(_DISCOVERY_URL)

        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]

    def test_response_contains_required_top_level_fields(
        self, discovery_client, monkeypatch
    ):
        monkeypatch.setenv("PUBLIC_BASE_URL", _TEST_BASE_URL)

        resp = discovery_client.get(_DISCOVERY_URL)
        body = resp.json()

        required_fields = [
            "name",
            "capabilities",
            "authentication",
            "endpoints",
            "url",
            "version",
            "provider",
        ]
        for field in required_fields:
            assert field in body, f"Missing required field: {field}"

    def test_url_field_uses_configured_base_url(self, discovery_client, monkeypatch):
        monkeypatch.setenv("PUBLIC_BASE_URL", _TEST_BASE_URL)

        resp = discovery_client.get(_DISCOVERY_URL)
        body = resp.json()

        assert body["url"] == _TEST_BASE_URL

    def test_endpoints_use_configured_base_url(self, discovery_client, monkeypatch):
        monkeypatch.setenv("PUBLIC_BASE_URL", _TEST_BASE_URL)

        resp = discovery_client.get(_DISCOVERY_URL)
        body = resp.json()

        assert "endpoints" in body
        for key, endpoint_url in body["endpoints"].items():
            assert endpoint_url.startswith(
                _TEST_BASE_URL
            ), f"Endpoint '{key}' does not start with base URL: {endpoint_url}"

    def test_provider_url_uses_configured_base_url(self, discovery_client, monkeypatch):
        monkeypatch.setenv("PUBLIC_BASE_URL", _TEST_BASE_URL)

        resp = discovery_client.get(_DISCOVERY_URL)
        body = resp.json()

        assert body["provider"]["url"] == _TEST_BASE_URL

    def test_capabilities_structure(self, discovery_client, monkeypatch):
        monkeypatch.setenv("PUBLIC_BASE_URL", _TEST_BASE_URL)

        resp = discovery_client.get(_DISCOVERY_URL)
        body = resp.json()

        caps = body["capabilities"]
        assert isinstance(caps.get("streaming"), bool)
        assert isinstance(caps.get("pushNotifications"), bool)
        assert isinstance(caps.get("stateTransitionHistory"), bool)

    def test_authentication_schemes_present(self, discovery_client, monkeypatch):
        monkeypatch.setenv("PUBLIC_BASE_URL", _TEST_BASE_URL)

        resp = discovery_client.get(_DISCOVERY_URL)
        body = resp.json()

        assert "schemes" in body["authentication"]
        assert isinstance(body["authentication"]["schemes"], list)
        assert len(body["authentication"]["schemes"]) > 0

    def test_no_authorization_header_required(self, discovery_client, monkeypatch):
        """Endpoint must be unauthenticated — no Authorization header sent."""
        monkeypatch.setenv("PUBLIC_BASE_URL", _TEST_BASE_URL)

        # Deliberately send no Authorization header
        resp = discovery_client.get(_DISCOVERY_URL)

        assert resp.status_code == 200

    @pytest.mark.parametrize("forbidden_field", _FORBIDDEN_FIELDS)
    def test_forbidden_field_not_in_response(
        self, forbidden_field, discovery_client, monkeypatch
    ):
        """Security contract: sensitive internal fields must never be exposed."""
        monkeypatch.setenv("PUBLIC_BASE_URL", _TEST_BASE_URL)

        resp = discovery_client.get(_DISCOVERY_URL)
        body = resp.json()

        assert (
            forbidden_field not in body
        ), f"Forbidden field '{forbidden_field}' found in discovery response"

    def test_base_url_trailing_slash_stripped(self, discovery_client, monkeypatch):
        """Trailing slashes in PUBLIC_BASE_URL should be stripped from response URLs."""
        monkeypatch.setenv("PUBLIC_BASE_URL", _TEST_BASE_URL + "/")

        resp = discovery_client.get(_DISCOVERY_URL)
        body = resp.json()

        assert not body["url"].endswith(
            "/"
        ), "URL field should not have a trailing slash"


class TestDiscoveryEndpointMissingBaseUrl:
    """Tests when PUBLIC_BASE_URL is not configured."""

    def test_returns_503_when_base_url_not_set(self, discovery_client, monkeypatch):
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)

        resp = discovery_client.get(_DISCOVERY_URL)

        assert resp.status_code == 503

    def test_503_body_has_error_code(self, discovery_client, monkeypatch):
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)

        resp = discovery_client.get(_DISCOVERY_URL)
        body = resp.json()

        assert body.get("error") == "discovery_not_configured"

    def test_503_body_has_detail(self, discovery_client, monkeypatch):
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)

        resp = discovery_client.get(_DISCOVERY_URL)
        body = resp.json()

        assert "detail" in body
        assert len(body["detail"]) > 0

    def test_503_content_type_is_json(self, discovery_client, monkeypatch):
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)

        resp = discovery_client.get(_DISCOVERY_URL)

        assert "application/json" in resp.headers["content-type"]


@pytest.mark.slow
@pytest.mark.skip(
    reason=(
        "Rate limit test makes 61+ HTTP requests. "
        "Run explicitly with: pytest -m slow --run-slow "
        "tests/integration/test_a2a_discovery.py"
    )
)
class TestDiscoveryRateLimit:
    """Rate limit tests — marked slow, skipped by default.

    To run: pytest -m slow tests/integration/test_a2a_discovery.py -p no:skip
    Sends 61 requests in a loop to verify the 62nd is rate-limited.
    This test is non-destructive but makes many HTTP requests.
    """

    def test_rate_limit_enforced_after_60_requests(
        self, discovery_client, monkeypatch
    ):
        monkeypatch.setenv("PUBLIC_BASE_URL", _TEST_BASE_URL)

        # Send 60 requests — all should succeed
        for i in range(60):
            resp = discovery_client.get(_DISCOVERY_URL)
            assert resp.status_code == 200, (
                f"Request {i + 1} failed with {resp.status_code}"
            )

        # The 61st request should be rate-limited
        resp = discovery_client.get(_DISCOVERY_URL)
        assert resp.status_code == 429, (
            f"Expected 429 rate limit on request 61, got {resp.status_code}"
        )
