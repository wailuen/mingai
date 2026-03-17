"""
Unit tests for P3AUTH-004 SAML 2.0 SSO Wizard API (P3AUTH-018).

Endpoints under test:
- POST /api/v1/admin/sso/saml/configure  -- parse IdP metadata, create Auth0 connection
- GET  /api/v1/admin/sso/saml/sp-metadata -- return SP metadata XML
- POST /api/v1/admin/sso/saml/test       -- return Auth0 authorize URL

Tier 1: fast, isolated, all HTTP calls and DB helpers are mocked.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from lxml import etree

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

TEST_JWT_SECRET = "c" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "11112222-3333-4444-5555-666677778888"
TEST_ACTOR_ID = "actor-saml-001"

# Fixture SAML IdP metadata (from task spec)
FIXTURE_IDP_METADATA_XML = """<?xml version="1.0"?>
<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata"
  xmlns:ds="http://www.w3.org/2000/09/xmldsig#"
  entityID="https://idp.example.com/saml/metadata">
  <IDPSSODescriptor WantAuthnRequestsSigned="false"
    protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
      Location="https://idp.example.com/sso/saml"/>
    <KeyDescriptor use="signing">
      <ds:KeyInfo>
        <ds:X509Data>
          <ds:X509Certificate>MIIDXTCCAkWgAwIBAgIJAKZgJdKdcqmTMA0GCSqGSIb3DQEBCwUAMEUxCzAJBgNVBAYTAlVTMRMwEQYDVQQIDApTb21lLVN0YXRlMSEwHwYDVQQKDBhJbnRlcm5ldCBXaWRnaXRzIFB0eSBMdGQwHhcNMjMwMTAxMDAwMDAwWhcNMjQwMTAxMDAwMDAwWjBFMQswCQYDVQQGEwJVUzETMBEGA1UECAwKU29tZS1TdGF0ZTEhMB8GA1UECgwYSW50ZXJuZXQgV2lkZ2l0cyBQdHkgTHRkMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA2a2rwplBQLF29amygykEMmYz0+Kcj3bKBp29G2rFCNp8zJJRdOCFQMRQdSNS2sVDKNQQqpBi7X9bLJgqYnuQeioBlxHIkQbGPCNFRH6R1a9K0F01kZkC5bH5HKHbPKBbT1T4oJuGKrPzjrMIENNMjI6k7jZFHkSkXVbICVlEGmvRpWAMQpCXHCwCQFHVY3mVCTqbQe3jRJSRGsY0gxhz3RR8SbHgwOFHWWWLRaGm0k2IvL2VtJJ9GxCTKyWO2NvGJOQmqTuCk9KNjJKXJmgfKGjVBQyOjkLxGFpEWUqHdPJRzRvBw1FMTF+M4MmEHV5C9bVmOfgmIBMWYCJwIDAQABo1AwTjAdBgNVHQ4EFgQUQkMh/3r4yWPGKgG9TDNbXQQeHMswHwYDVR0jBBgwFoAUQkMh/3r4yWPGKgG9TDNbXQQeHMswDAYDVR0TBAUwAwEB/zANBgkqhkiG9w0BAQsFAAOCAQEAZ6B4e5wCZEgmfgKVFhfPLhNs8sPFJXbzBDPz6z3EkfYVkGJBmrS0qGKBJI2SV21HfH9QWDVXMQlFXvX/6wgWCbEF4iGBHCRYReBN2O7X0Y/zITL5JZLJ+WXzpuKXMNHNzZJlnIHYe7zCIYMSs+5FghHRCgqJLFPJ3xT6N7kD/FrSxYM5wFbXxVrMFGnCpKwQfVEKWqNKBJfDjZE7Cjpe4RBpV9VlKxWHxL3DZZOhm6YNJ0QfaJHBvmCaRkNT3/JWixbRMSF2ygPSS1vdKNdwAC5kWqMhXjE1S8kKhKlTFPXRXiEXJIkbkH9yENePXRtBD8ZFqBCBOX5NKA==</ds:X509Certificate>
        </ds:X509Data>
      </ds:KeyInfo>
    </KeyDescriptor>
  </IDPSSODescriptor>
</EntityDescriptor>"""

FIXTURE_IDP_ENTITY_ID = "https://idp.example.com/saml/metadata"
FIXTURE_IDP_SSO_URL = "https://idp.example.com/sso/saml"
FIXTURE_CERT_PREFIX = "MIIDXTCCAkWg"  # first chars of fixture cert (for assertion)

FAKE_CONNECTION_ID = "con_SamlTest1234567"


# ---------------------------------------------------------------------------
# JWT token factories
# ---------------------------------------------------------------------------


def _make_tenant_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": TEST_ACTOR_ID,
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": "admin@tenant.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_viewer_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "viewer-user-id",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["viewer"],
        "scope": "tenant",
        "plan": "professional",
        "email": "viewer@tenant.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def env_vars():
    env = {
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "JWT_ALGORITHM": TEST_JWT_ALGORITHM,
        "REDIS_URL": "redis://localhost:6379/0",
        "FRONTEND_URL": "http://localhost:3022",
        "AUTH0_DOMAIN": "mingai-dev.jp.auth0.com",
        "AUTH0_CLIENT_ID": "test_client_id_123",
        "AUTH0_MANAGEMENT_CLIENT_ID": "mgmt_client_id",
        "AUTH0_MANAGEMENT_CLIENT_SECRET": "mgmt_client_secret",
    }
    with patch.dict(os.environ, env):
        yield


@pytest.fixture
def client(env_vars):
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {_make_tenant_admin_token()}"}


@pytest.fixture
def viewer_headers():
    return {"Authorization": f"Bearer {_make_viewer_token()}"}


# ---------------------------------------------------------------------------
# Test 1: SP metadata is valid XML with entityID and ACS URL
# ---------------------------------------------------------------------------


class TestSPMetadataContent:
    """GET /api/v1/admin/sso/saml/sp-metadata"""

    def test_sp_metadata_is_valid_xml_with_entity_id_and_acs_url(
        self, client, admin_headers
    ):
        """SP metadata response is parseable XML containing entityID and ACS URL."""
        stored_config = {
            "provider_type": "saml",
            "auth0_connection_id": FAKE_CONNECTION_ID,
            "enabled": True,
        }
        with patch(
            "app.modules.admin.sso_saml._get_saml_config_db",
            new_callable=AsyncMock,
            return_value=stored_config,
        ):
            resp = client.get(
                "/api/v1/admin/sso/saml/sp-metadata", headers=admin_headers
            )

        assert resp.status_code == 200
        assert "application/xml" in resp.headers["content-type"]

        # Parse the returned XML with lxml
        root = etree.fromstring(resp.content)
        ns = {"md": "urn:oasis:names:tc:SAML:2.0:metadata"}

        entity_id = root.get("entityID")
        # TA-001: entityID must be https://{AUTH0_DOMAIN}/samlp/metadata/{connection_id}
        expected_entity_id = (
            f"https://mingai-dev.jp.auth0.com/samlp/metadata/{FAKE_CONNECTION_ID}"
        )
        assert (
            entity_id == expected_entity_id
        ), f"Expected entityID {expected_entity_id!r}, got {entity_id!r}"

        acs_elements = root.xpath(
            "//md:SPSSODescriptor/md:AssertionConsumerService", namespaces=ns
        )
        assert (
            len(acs_elements) >= 1
        ), "SP metadata must contain at least one ACS element"

        acs_location = acs_elements[0].get("Location")
        assert acs_location, "ACS element must have a Location attribute"
        assert (
            FAKE_CONNECTION_ID in acs_location
        ), f"ACS Location must include connection_id {FAKE_CONNECTION_ID!r}"
        assert (
            "mingai-dev.jp.auth0.com" in acs_location
        ), "ACS Location must include AUTH0_DOMAIN"

    def test_sp_metadata_returns_404_when_no_saml_configured(
        self, client, admin_headers
    ):
        """GET sp-metadata returns 404 when no SAML connection is configured."""
        with patch(
            "app.modules.admin.sso_saml._get_saml_config_db",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(
                "/api/v1/admin/sso/saml/sp-metadata", headers=admin_headers
            )

        assert resp.status_code == 404

    def test_sp_metadata_returns_404_for_non_saml_config(self, client, admin_headers):
        """GET sp-metadata returns 404 when tenant has OIDC (not SAML) configured."""
        oidc_config = {
            "provider_type": "oidc",
            "auth0_connection_id": "con_OidcConn",
            "enabled": True,
        }
        with patch(
            "app.modules.admin.sso_saml._get_saml_config_db",
            new_callable=AsyncMock,
            return_value=oidc_config,
        ):
            resp = client.get(
                "/api/v1/admin/sso/saml/sp-metadata", headers=admin_headers
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test 2: IdP metadata parsing from URL
# ---------------------------------------------------------------------------


class TestIdPMetadataParsingFromURL:
    """POST /admin/sso/saml/configure with metadata_url"""

    def test_configure_from_url_extracts_entity_id_sso_url_and_cert(
        self, client, admin_headers
    ):
        """Metadata fetched from URL is correctly parsed and connection is created."""
        mock_http_response = MagicMock()
        mock_http_response.content = FIXTURE_IDP_METADATA_XML.encode("utf-8")
        mock_http_response.raise_for_status = MagicMock()

        mock_auth0_resp = {"id": FAKE_CONNECTION_ID}

        with (
            patch(
                "app.modules.admin.sso_saml._get_saml_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_saml._store_saml_config_db",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.admin.sso_saml.management_api_request",
                new_callable=AsyncMock,
                return_value=mock_auth0_resp,
            ) as mock_mgmt,
            patch(
                "app.modules.admin.sso_saml._fetch_metadata_url",
                new_callable=AsyncMock,
                return_value=FIXTURE_IDP_METADATA_XML.encode("utf-8"),
            ),
        ):
            resp = client.post(
                "/api/v1/admin/sso/saml/configure",
                json={"metadata_url": "https://idp.example.com/metadata"},
                headers=admin_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["connection_id"] == FAKE_CONNECTION_ID
        assert data["sp_metadata_url"] == "/api/v1/admin/sso/saml/sp-metadata"

        # Verify the Management API was called with correct IdP params
        call_kwargs = mock_mgmt.call_args
        body = (
            call_kwargs.args[2]
            if len(call_kwargs.args) >= 3
            else call_kwargs.kwargs.get("body") or call_kwargs.args[2]
        )
        assert body["strategy"] == "samlp"
        assert body["options"]["signInEndpoint"] == FIXTURE_IDP_SSO_URL
        assert body["options"]["entityId"] == FIXTURE_IDP_ENTITY_ID
        assert FIXTURE_CERT_PREFIX in body["options"]["cert"]


# ---------------------------------------------------------------------------
# Test 3: IdP metadata parsing from raw XML
# ---------------------------------------------------------------------------


class TestIdPMetadataParsingFromXML:
    """POST /admin/sso/saml/configure with metadata_xml"""

    def test_configure_from_raw_xml_extracts_correct_fields(
        self, client, admin_headers
    ):
        """Raw metadata_xml is correctly parsed and connection is created."""
        mock_auth0_resp = {"id": FAKE_CONNECTION_ID}

        with (
            patch(
                "app.modules.admin.sso_saml._get_saml_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_saml._store_saml_config_db",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.admin.sso_saml.management_api_request",
                new_callable=AsyncMock,
                return_value=mock_auth0_resp,
            ) as mock_mgmt,
        ):
            resp = client.post(
                "/api/v1/admin/sso/saml/configure",
                json={"metadata_xml": FIXTURE_IDP_METADATA_XML},
                headers=admin_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["connection_id"] == FAKE_CONNECTION_ID

        call_kwargs = mock_mgmt.call_args
        body = call_kwargs.args[2]
        assert body["options"]["signInEndpoint"] == FIXTURE_IDP_SSO_URL
        assert body["options"]["entityId"] == FIXTURE_IDP_ENTITY_ID
        assert FIXTURE_CERT_PREFIX in body["options"]["cert"]


# ---------------------------------------------------------------------------
# Test 4: Invalid metadata XML raises 422
# ---------------------------------------------------------------------------


class TestInvalidMetadataXML:
    """POST /admin/sso/saml/configure with invalid XML"""

    def test_invalid_xml_returns_422(self, client, admin_headers):
        """Malformed XML in metadata_xml returns 422 Unprocessable Entity."""
        with patch(
            "app.modules.admin.sso_saml._get_saml_config_db",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post(
                "/api/v1/admin/sso/saml/configure",
                json={"metadata_xml": "this is not XML at all <broken>"},
                headers=admin_headers,
            )

        assert resp.status_code == 422

    def test_xml_missing_entity_id_returns_422(self, client, admin_headers):
        """XML that parses but lacks entityID attribute returns 422."""
        xml_no_entity_id = """<?xml version="1.0"?>
<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata">
  <IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
  </IDPSSODescriptor>
</EntityDescriptor>"""
        with patch(
            "app.modules.admin.sso_saml._get_saml_config_db",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post(
                "/api/v1/admin/sso/saml/configure",
                json={"metadata_xml": xml_no_entity_id},
                headers=admin_headers,
            )

        assert resp.status_code == 422

    def test_neither_field_provided_returns_422(self, client, admin_headers):
        """Providing neither metadata_url nor metadata_xml returns 422."""
        resp = client.post(
            "/api/v1/admin/sso/saml/configure",
            json={},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_both_fields_provided_returns_422(self, client, admin_headers):
        """Providing both metadata_url and metadata_xml returns 422."""
        resp = client.post(
            "/api/v1/admin/sso/saml/configure",
            json={
                "metadata_url": "https://idp.example.com/metadata",
                "metadata_xml": FIXTURE_IDP_METADATA_XML,
            },
            headers=admin_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test 5: Unreachable metadata URL raises 422 with timeout message
# ---------------------------------------------------------------------------


class TestMetadataURLFetchErrors:
    """POST /admin/sso/saml/configure — URL fetch failure cases"""

    def test_timeout_returns_422_with_timeout_message(self, client, admin_headers):
        """httpx.TimeoutException from metadata URL fetch returns 422 with timeout detail.

        _fetch_metadata_url converts TimeoutException to HTTPException(422) internally.
        We mock it to raise HTTPException(422) directly, matching its real contract.
        """
        from fastapi import HTTPException as FHTTPException

        with (
            patch(
                "app.modules.admin.sso_saml._get_saml_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_saml._fetch_metadata_url",
                new_callable=AsyncMock,
                side_effect=FHTTPException(
                    status_code=422,
                    detail="Timed out fetching SAML metadata from https://slow-idp.example.com/metadata",
                ),
            ),
        ):
            resp = client.post(
                "/api/v1/admin/sso/saml/configure",
                json={"metadata_url": "https://slow-idp.example.com/metadata"},
                headers=admin_headers,
            )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert (
            "timeout" in detail.lower() or "timed" in detail.lower()
        ), f"Expected timeout message in detail, got: {detail!r}"

    def test_connection_error_returns_422(self, client, admin_headers):
        """Network error from metadata URL fetch returns 422.

        _fetch_metadata_url converts ConnectError to HTTPException(422) internally.
        We mock it to raise HTTPException(422) directly, matching its real contract.
        """
        from fastapi import HTTPException as FHTTPException

        with (
            patch(
                "app.modules.admin.sso_saml._get_saml_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_saml._fetch_metadata_url",
                new_callable=AsyncMock,
                side_effect=FHTTPException(
                    status_code=422,
                    detail="Failed to fetch SAML metadata: connection refused",
                ),
            ),
        ):
            resp = client.post(
                "/api/v1/admin/sso/saml/configure",
                json={"metadata_url": "https://unreachable.example.com/metadata"},
                headers=admin_headers,
            )

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test 6: SAML connection already configured returns 409
# ---------------------------------------------------------------------------


class TestSAMLAlreadyConfigured:
    """POST /admin/sso/saml/configure — 409 duplicate guard"""

    def test_duplicate_saml_connection_returns_409(self, client, admin_headers):
        """Configuring SAML when tenant already has SAML connection returns 409."""
        existing_config = {
            "provider_type": "saml",
            "auth0_connection_id": "con_ExistingSaml123",
            "enabled": True,
        }
        with patch(
            "app.modules.admin.sso_saml._get_saml_config_db",
            new_callable=AsyncMock,
            return_value=existing_config,
        ):
            resp = client.post(
                "/api/v1/admin/sso/saml/configure",
                json={"metadata_xml": FIXTURE_IDP_METADATA_XML},
                headers=admin_headers,
            )

        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert (
            "already configured" in detail.lower() or "DELETE" in detail
        ), f"Expected duplicate-connection message, got: {detail!r}"

    def test_non_saml_existing_config_does_not_block(self, client, admin_headers):
        """Existing OIDC config does not block a new SAML configuration."""
        oidc_config = {
            "provider_type": "oidc",
            "auth0_connection_id": "con_OidcConn123",
            "enabled": True,
        }
        mock_auth0_resp = {"id": FAKE_CONNECTION_ID}

        with (
            patch(
                "app.modules.admin.sso_saml._get_saml_config_db",
                new_callable=AsyncMock,
                return_value=oidc_config,
            ),
            patch(
                "app.modules.admin.sso_saml._store_saml_config_db",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.admin.sso_saml.management_api_request",
                new_callable=AsyncMock,
                return_value=mock_auth0_resp,
            ),
        ):
            resp = client.post(
                "/api/v1/admin/sso/saml/configure",
                json={"metadata_xml": FIXTURE_IDP_METADATA_XML},
                headers=admin_headers,
            )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test 7: Auth0 API error on connection creation propagates as 502
# ---------------------------------------------------------------------------


class TestAuth0APIError:
    """POST /admin/sso/saml/configure — Auth0 Management API failure"""

    def test_auth0_api_error_returns_502(self, client, admin_headers):
        """RuntimeError from management_api_request propagates as 502 Bad Gateway."""
        with (
            patch(
                "app.modules.admin.sso_saml._get_saml_config_db",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.modules.admin.sso_saml.management_api_request",
                new_callable=AsyncMock,
                side_effect=RuntimeError(
                    "Auth0 Management API POST connections failed (HTTP 422): conflict"
                ),
            ),
        ):
            resp = client.post(
                "/api/v1/admin/sso/saml/configure",
                json={"metadata_xml": FIXTURE_IDP_METADATA_XML},
                headers=admin_headers,
            )

        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert (
            "Auth0" in detail or "connection creation failed" in detail.lower()
        ), f"Expected Auth0 error message in detail, got: {detail!r}"


# ---------------------------------------------------------------------------
# Test 8: Test endpoint returns URL with correct connection_id
# ---------------------------------------------------------------------------


class TestSAMLTestEndpoint:
    """POST /api/v1/admin/sso/saml/test"""

    def test_returns_test_url_with_connection_id(self, client, admin_headers):
        """Test endpoint returns Auth0 authorize URL containing correct connection_id."""
        stored_config = {
            "provider_type": "saml",
            "auth0_connection_id": FAKE_CONNECTION_ID,
            "enabled": True,
        }
        with patch(
            "app.modules.admin.sso_saml._get_saml_config_db",
            new_callable=AsyncMock,
            return_value=stored_config,
        ):
            resp = client.post("/api/v1/admin/sso/saml/test", headers=admin_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "test_url" in data
        test_url = data["test_url"]
        assert (
            FAKE_CONNECTION_ID in test_url
        ), f"test_url must contain connection_id {FAKE_CONNECTION_ID!r}"
        assert (
            "mingai-dev.jp.auth0.com" in test_url
        ), "test_url must include AUTH0_DOMAIN"
        assert "test_client_id_123" in test_url, "test_url must include AUTH0_CLIENT_ID"
        assert "openid" in test_url, "test_url must request openid scope"

    def test_test_endpoint_returns_404_when_no_saml_configured(
        self, client, admin_headers
    ):
        """Test endpoint returns 404 when no SAML connection is configured."""
        with patch(
            "app.modules.admin.sso_saml._get_saml_config_db",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post("/api/v1/admin/sso/saml/test", headers=admin_headers)

        assert resp.status_code == 404

    def test_test_endpoint_requires_tenant_admin(self, client, viewer_headers):
        """Test endpoint returns 403 for viewer role."""
        resp = client.post("/api/v1/admin/sso/saml/test", headers=viewer_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Test 9: SP metadata returns 404 when no SAML configured (dedicated class above)
# plus auth guard tests across all endpoints
# ---------------------------------------------------------------------------


class TestAuthGuards:
    """All SAML wizard endpoints require tenant_admin."""

    def test_configure_requires_auth(self, client):
        resp = client.post(
            "/api/v1/admin/sso/saml/configure",
            json={"metadata_xml": FIXTURE_IDP_METADATA_XML},
        )
        assert resp.status_code == 401

    def test_sp_metadata_requires_auth(self, client):
        resp = client.get("/api/v1/admin/sso/saml/sp-metadata")
        assert resp.status_code == 401

    def test_test_endpoint_requires_auth(self, client):
        resp = client.post("/api/v1/admin/sso/saml/test")
        assert resp.status_code == 401

    def test_configure_requires_tenant_admin(self, client, viewer_headers):
        resp = client.post(
            "/api/v1/admin/sso/saml/configure",
            json={"metadata_xml": FIXTURE_IDP_METADATA_XML},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_sp_metadata_requires_tenant_admin(self, client, viewer_headers):
        resp = client.get("/api/v1/admin/sso/saml/sp-metadata", headers=viewer_headers)
        assert resp.status_code == 403
