"""
TEST-DEF-014: SSO wizard integration tests (TEST-026, TEST-027).

Uses mocked Auth0 Management API — does NOT call real Auth0 in CI.
Tests the full wizard flow: parse metadata → create connection → store config.

Tier 2: real PostgreSQL, no DB mocking.
External HTTP (Auth0 Management API + OIDC discovery + SAML metadata fetch)
is mocked via unittest.mock.patch on the relevant callables.

Prerequisites:
    docker-compose up -d  # ensure PostgreSQL is running
    DATABASE_URL and JWT_SECRET_KEY must be set in .env

Run:
    pytest tests/integration/test_sso_wizards.py -v
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _run_sync(coro):
    """
    Run a coroutine in an isolated event loop.

    Uses new_event_loop() instead of asyncio.run() to avoid KQueue conflicts
    with the TestClient's anyio portal on macOS when both share the same thread.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(None)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


# ---------------------------------------------------------------------------
# Minimal SAML IdP metadata XML fixture
# ---------------------------------------------------------------------------

_SAML_CERT = (
    "MIIDpDCCAoygAwIBAgIGAXUQTnFvMA0GCSqGSIb3DQEBCwUAMIGSMQswCQYDVQQG"
    "EwJVUzETMBEGA1UECAwKQ2FsaWZvcm5pYTEWMBQGA1UEBwwNU2FuIEZyYW5jaXNj"
    "bzETMBEGA1UECgwKQ2xvdWRmbGFyZTEMMAoGA1UECwwDSVQxMTAvBgNVBAMMKHNh"
    "bWwtaWRwLmV4YW1wbGUuY29tMB4XDTIzMDEwMTAwMDAwMFoXDTI0MDEwMTAwMDAw"
    "MFowgZIxCzAJBgNVBAYTAlVTMRMwEQYDVQQIDApDYWxpZm9ybmlhMRYwFBYDVQQH"
    "DA1TYW4gRnJhbmNpc2NvMRMwEQYDVQQKDApDbG91ZGZsYXJlMQwwCgYDVQQLDANJ"
    "VDExMC8GA1UEAwwoc2FtbC1pZHAuZXhhbXBsZS5jb20wggEiMA0GCSqGSIb3DQEB"
    "AQUAA4IBDwAwggEKAoIBAQC7o4qne60TB3wolw6B5vT3SjxOp+m7LT7mGMPRRTFJ"
)

_SAML_METADATA_XML = f"""<?xml version="1.0"?>
<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata"
                  entityID="https://saml-idp.example.com">
  <IDPSSODescriptor
    WantAuthnRequestsSigned="false"
    protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <KeyDescriptor use="signing">
      <KeyInfo xmlns="http://www.w3.org/2000/09/xmldsig#">
        <X509Data>
          <X509Certificate>{_SAML_CERT}</X509Certificate>
        </X509Data>
      </KeyInfo>
    </KeyDescriptor>
    <SingleSignOnService
      Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
      Location="https://saml-idp.example.com/sso/saml"/>
  </IDPSSODescriptor>
</EntityDescriptor>
"""

# Fake OIDC discovery document
_OIDC_DISCOVERY_DOC = {
    "issuer": "https://oidc-idp.example.com",
    "authorization_endpoint": "https://oidc-idp.example.com/authorize",
    "token_endpoint": "https://oidc-idp.example.com/token",
    "jwks_uri": "https://oidc-idp.example.com/.well-known/jwks.json",
    "response_types_supported": ["code"],
}


# ---------------------------------------------------------------------------
# DB / auth helpers
# ---------------------------------------------------------------------------


def _jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        pytest.skip("JWT_SECRET_KEY not configured — skipping integration tests")
    return secret


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping integration tests")
    return url


def _make_engine():
    return create_async_engine(_db_url(), echo=False)


async def _run_sql(sql: str, params: dict | None = None):
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            await session.commit()
            return result
    finally:
        await engine.dispose()


async def _fetch_one(sql: str, params: dict | None = None):
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await session.execute(text(sql), params or {})
            return result.fetchone()
    finally:
        await engine.dispose()


def _make_admin_token(tenant_id: str, user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "enterprise",
        "email": f"admin-{user_id[:8]}@sso-test.test",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


# ---------------------------------------------------------------------------
# Module-scoped test tenant fixture
# ---------------------------------------------------------------------------

_TENANT_ID_SAML = str(uuid.uuid4())
_USER_ID_SAML = str(uuid.uuid4())
_TENANT_ID_OIDC = str(uuid.uuid4())
_USER_ID_OIDC = str(uuid.uuid4())


@pytest.fixture(scope="module")
def test_env_saml():
    """Provision tenant + tenant_admin user for SAML tests."""
    tid = _TENANT_ID_SAML
    uid = _USER_ID_SAML

    async def _setup():
        await _run_sql(
            "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
            "VALUES (:id, :name, :slug, 'enterprise', :email, 'active')",
            {
                "id": tid,
                "name": f"SAML Test Tenant {tid[:8]}",
                "slug": f"sso-saml-{tid[:8]}",
                "email": f"admin-{tid[:8]}@sso-test.test",
            },
        )
        await _run_sql(
            "INSERT INTO users (id, tenant_id, email, name, role, status) "
            "VALUES (:id, :tid, :email, :name, 'admin', 'active')",
            {
                "id": uid,
                "tid": tid,
                "email": f"admin-{uid[:8]}@sso-test.test",
                "name": f"SSO Admin {uid[:8]}",
            },
        )

    async def _teardown():
        await _run_sql(
            "DELETE FROM audit_log WHERE tenant_id = :tid",
            {"tid": tid},
        )
        await _run_sql(
            "DELETE FROM tenant_configs WHERE tenant_id = :tid",
            {"tid": tid},
        )
        await _run_sql("DELETE FROM users WHERE id = :id", {"id": uid})
        await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})

    _run_sync(_setup())
    yield {"tenant_id": tid, "user_id": uid}
    _run_sync(_teardown())


@pytest.fixture(scope="module")
def test_env_oidc():
    """Provision tenant + tenant_admin user for OIDC tests."""
    tid = _TENANT_ID_OIDC
    uid = _USER_ID_OIDC

    async def _setup():
        await _run_sql(
            "INSERT INTO tenants (id, name, slug, plan, primary_contact_email, status) "
            "VALUES (:id, :name, :slug, 'enterprise', :email, 'active')",
            {
                "id": tid,
                "name": f"OIDC Test Tenant {tid[:8]}",
                "slug": f"sso-oidc-{tid[:8]}",
                "email": f"admin-{tid[:8]}@oidc-test.test",
            },
        )
        await _run_sql(
            "INSERT INTO users (id, tenant_id, email, name, role, status) "
            "VALUES (:id, :tid, :email, :name, 'admin', 'active')",
            {
                "id": uid,
                "tid": tid,
                "email": f"admin-{uid[:8]}@oidc-test.test",
                "name": f"OIDC Admin {uid[:8]}",
            },
        )

    async def _teardown():
        await _run_sql(
            "DELETE FROM audit_log WHERE tenant_id = :tid",
            {"tid": tid},
        )
        await _run_sql(
            "DELETE FROM tenant_configs WHERE tenant_id = :tid",
            {"tid": tid},
        )
        await _run_sql("DELETE FROM users WHERE id = :id", {"id": uid})
        await _run_sql("DELETE FROM tenants WHERE id = :id", {"id": tid})

    _run_sync(_setup())
    yield {"tenant_id": tid, "user_id": uid}
    _run_sync(_teardown())


# ---------------------------------------------------------------------------
# TEST-026: SAML wizard integration tests
# ---------------------------------------------------------------------------


class TestSamlWizard:
    """TEST-026: SAML 2.0 SSO wizard flow."""

    def test_saml_configure_from_raw_xml(self, client, test_env_saml):
        """
        POST /admin/sso/saml/configure with metadata_xml.

        Mocks: management_api_request → returns fake connection_id.
        Verifies: 200 response with connection_id, tenant_configs row created.
        """
        tid = test_env_saml["tenant_id"]
        uid = test_env_saml["user_id"]
        token = _make_admin_token(tid, uid)

        fake_connection_id = f"con_saml_{uuid.uuid4().hex[:12]}"

        with patch(
            "app.modules.admin.sso_saml.management_api_request",
            new=AsyncMock(return_value={"id": fake_connection_id}),
        ):
            resp = client.post(
                "/api/v1/admin/sso/saml/configure",
                json={"metadata_xml": _SAML_METADATA_XML},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["connection_id"] == fake_connection_id
        assert "sp_metadata_url" in body

        # Verify tenant_configs row was written to real DB
        row = _run_sync(
            _fetch_one(
                "SELECT config_data FROM tenant_configs "
                "WHERE tenant_id = :tid AND config_type = 'sso_config'",
                {"tid": tid},
            )
        )
        assert row is not None
        config = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        assert config["auth0_connection_id"] == fake_connection_id
        assert config["provider_type"] == "saml"
        assert config["enabled"] is True

    def test_saml_configure_from_metadata_url(self, client, test_env_saml):
        """
        POST /admin/sso/saml/configure with metadata_url.

        Mocks:
        - httpx fetch inside _fetch_metadata_url → returns fixture XML bytes
        - management_api_request → returns fake connection_id

        SAML config already exists from previous test — clean it first.
        """
        tid = test_env_saml["tenant_id"]
        uid = test_env_saml["user_id"]
        token = _make_admin_token(tid, uid)

        # Remove the config written by the previous test so this one can run
        _run_sync(
            _run_sql(
                "DELETE FROM tenant_configs "
                "WHERE tenant_id = :tid AND config_type = 'sso_config'",
                {"tid": tid},
            )
        )

        fake_connection_id = f"con_saml_url_{uuid.uuid4().hex[:10]}"

        import httpx
        from unittest.mock import MagicMock

        fake_response = MagicMock(spec=httpx.Response)
        fake_response.content = _SAML_METADATA_XML.encode("utf-8")
        fake_response.raise_for_status = MagicMock()

        with patch(
            "app.modules.admin.sso_saml.management_api_request",
            new=AsyncMock(return_value={"id": fake_connection_id}),
        ), patch(
            "app.modules.admin.sso_saml._fetch_metadata_url",
            new=AsyncMock(return_value=_SAML_METADATA_XML.encode("utf-8")),
        ):
            resp = client.post(
                "/api/v1/admin/sso/saml/configure",
                json={"metadata_url": "https://saml-idp.example.com/metadata"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["connection_id"] == fake_connection_id

    def test_saml_sp_metadata_returns_xml(self, client, test_env_saml):
        """
        GET /admin/sso/saml/sp-metadata returns XML with correct entityID.

        Requires a prior SAML configuration in tenant_configs (created by previous
        test).  entityID must match Auth0 pattern:
        https://{AUTH0_DOMAIN}/samlp/metadata/{connection_id}
        """
        tid = test_env_saml["tenant_id"]
        uid = test_env_saml["user_id"]
        token = _make_admin_token(tid, uid)

        # Ensure there is a SAML config row from the previous test
        row = _run_sync(
            _fetch_one(
                "SELECT config_data FROM tenant_configs "
                "WHERE tenant_id = :tid AND config_type = 'sso_config'",
                {"tid": tid},
            )
        )
        if row is None:
            # Re-create config so we can test the metadata endpoint
            connection_id = f"con_saml_meta_{uuid.uuid4().hex[:10]}"
            _run_sync(
                _run_sql(
                    "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
                    "VALUES (:id, :tid, 'sso_config', CAST(:data AS jsonb))",
                    {
                        "id": str(uuid.uuid4()),
                        "tid": tid,
                        "data": json.dumps(
                            {
                                "provider_type": "saml",
                                "auth0_connection_id": connection_id,
                                "enabled": True,
                            }
                        ),
                    },
                )
            )
        else:
            config = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            connection_id = config["auth0_connection_id"]

        auth0_domain = os.environ.get("AUTH0_DOMAIN", "test.auth0.com")

        resp = client.get(
            "/api/v1/admin/sso/saml/sp-metadata",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("application/xml")
        xml_body = resp.text
        expected_entity_id = f"https://{auth0_domain}/samlp/metadata/{connection_id}"
        assert expected_entity_id in xml_body

    def test_saml_duplicate_rejected(self, client, test_env_saml):
        """
        A second POST /admin/sso/saml/configure with an existing SAML config
        returns 409 Conflict.
        """
        tid = test_env_saml["tenant_id"]
        uid = test_env_saml["user_id"]
        token = _make_admin_token(tid, uid)

        # Ensure a SAML config exists (from earlier tests)
        row = _run_sync(
            _fetch_one(
                "SELECT 1 FROM tenant_configs "
                "WHERE tenant_id = :tid AND config_type = 'sso_config'",
                {"tid": tid},
            )
        )
        if row is None:
            # Seed one so the 409 guard is exercisable
            _run_sync(
                _run_sql(
                    "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
                    "VALUES (:id, :tid, 'sso_config', CAST(:data AS jsonb))",
                    {
                        "id": str(uuid.uuid4()),
                        "tid": tid,
                        "data": json.dumps(
                            {
                                "provider_type": "saml",
                                "auth0_connection_id": "con_existing_saml",
                                "enabled": True,
                            }
                        ),
                    },
                )
            )

        with patch(
            "app.modules.admin.sso_saml.management_api_request",
            new=AsyncMock(return_value={"id": "con_should_not_reach"}),
        ):
            resp = client.post(
                "/api/v1/admin/sso/saml/configure",
                json={"metadata_xml": _SAML_METADATA_XML},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 409, resp.text
        assert "already configured" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# TEST-027: OIDC wizard integration tests
# ---------------------------------------------------------------------------


class TestOidcWizard:
    """TEST-027: OIDC SSO wizard flow."""

    def test_oidc_configure_with_discovery(self, client, test_env_oidc):
        """
        POST /admin/sso/oidc/configure with issuer, client_id, client_secret.

        Mocks:
        - _validate_oidc_discovery (httpx GET) → returns fake discovery doc
        - management_api_request → returns fake connection_id
        - vault store_secret → returns fake vault_ref

        Verifies: 200 response, tenant_configs row created with provider_type=oidc.
        """
        tid = test_env_oidc["tenant_id"]
        uid = test_env_oidc["user_id"]
        token = _make_admin_token(tid, uid)

        fake_connection_id = f"con_oidc_{uuid.uuid4().hex[:12]}"

        with patch(
            "app.modules.admin.sso_oidc._validate_oidc_discovery",
            new=AsyncMock(return_value=_OIDC_DISCOVERY_DOC),
        ), patch(
            "app.modules.admin.sso_oidc.management_api_request",
            new=AsyncMock(return_value={"id": fake_connection_id}),
        ), patch(
            "app.modules.admin.sso_oidc._encrypt_client_secret",
            return_value="vault://local/oidc-test-ref",
        ):
            resp = client.post(
                "/api/v1/admin/sso/oidc/configure",
                json={
                    "issuer": "https://oidc-idp.example.com",
                    "client_id": "test-client-id",
                    "client_secret": "test-client-secret",
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["connection_id"] == fake_connection_id
        assert body["issuer_validated"] is True

        # Verify tenant_configs row in real DB
        row = _run_sync(
            _fetch_one(
                "SELECT config_data FROM tenant_configs "
                "WHERE tenant_id = :tid AND config_type = 'sso_config'",
                {"tid": tid},
            )
        )
        assert row is not None
        config = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        assert config["provider_type"] == "oidc"
        assert config["auth0_connection_id"] == fake_connection_id
        assert config["enabled"] is True

    def test_oidc_test_url_returned(self, client, test_env_oidc):
        """
        POST /admin/sso/oidc/test returns {test_url} with Auth0 authorize URL.

        Requires an OIDC config to exist (created by previous test).
        """
        tid = test_env_oidc["tenant_id"]
        uid = test_env_oidc["user_id"]
        token = _make_admin_token(tid, uid)

        # Ensure an OIDC config row exists
        row = _run_sync(
            _fetch_one(
                "SELECT config_data FROM tenant_configs "
                "WHERE tenant_id = :tid AND config_type = 'sso_config'",
                {"tid": tid},
            )
        )
        if row is None:
            connection_id = f"con_oidc_test_{uuid.uuid4().hex[:10]}"
            _run_sync(
                _run_sql(
                    "INSERT INTO tenant_configs (id, tenant_id, config_type, config_data) "
                    "VALUES (:id, :tid, 'sso_config', CAST(:data AS jsonb))",
                    {
                        "id": str(uuid.uuid4()),
                        "tid": tid,
                        "data": json.dumps(
                            {
                                "provider_type": "oidc",
                                "auth0_connection_id": connection_id,
                                "enabled": True,
                            }
                        ),
                    },
                )
            )

        resp = client.post(
            "/api/v1/admin/sso/oidc/test",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "test_url" in body
        assert "authorize" in body["test_url"]
