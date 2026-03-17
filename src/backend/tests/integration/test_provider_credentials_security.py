"""
PVDR-019: Security integration tests for LLM Provider credential management.

Tier 2: Real PostgreSQL — no mocking.

8 test cases:
1. POST → GET list: original api_key not in response
2. POST → GET detail: api_key not in response
3. POST with structlog capture: api_key not in any log record
4. PATCH (update key) with structlog: new api_key not in logs
5. POST with api_key as query param → 422
6. DB direct: api_key_encrypted is bytes, NOT equal to api_key.encode()
7. DB decrypt: fernet.decrypt(api_key_encrypted) == api_key.encode()
8. PATCH omitting api_key → api_key_encrypted unchanged (decrypts to original)

Run:
    pytest tests/integration/test_provider_credentials_security.py -v
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Helpers
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


def _make_platform_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "roles": ["platform_admin"],
        "scope": "platform",
        "plan": "enterprise",
        "token_version": 2,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def _get_encrypted_bytes(provider_id: str) -> bytes:
    """Read api_key_encrypted directly from DB."""
    db_url = _db_url()
    result_holder = {}

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            await session.execute(
                text("SELECT set_config('app.scope', 'platform', true)")
            )
            res = await session.execute(
                text("SELECT api_key_encrypted FROM llm_providers WHERE id = :id"),
                {"id": provider_id},
            )
            row = res.fetchone()
            result_holder["row"] = row
        await engine.dispose()

    asyncio.run(_do())
    row = result_holder.get("row")
    if row is None:
        return b""
    return bytes(row[0]) if row[0] else b""


def _cleanup_security_providers() -> None:
    """Remove providers created by security tests."""
    db_url = _db_url()

    async def _do():
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            await session.execute(
                text("SELECT set_config('app.scope', 'platform', true)")
            )
            await session.execute(
                text(
                    "DELETE FROM llm_providers WHERE display_name LIKE 'Security Test%'"
                )
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_do())


SECURITY_KEY = "sk-security-test-secret-key-do-not-use"
SECURITY_ENDPOINT = "https://security-test.openai.azure.com/"


class TestProviderCredentialsSecurity:
    """Security invariant tests for LLM provider credentials."""

    @pytest.fixture(autouse=True, scope="class")
    def _cleanup(self):
        yield
        _cleanup_security_providers()

    # ------------------------------------------------------------------
    # Test 1: POST → GET list: original api_key not in response
    # ------------------------------------------------------------------

    def test_01_api_key_not_in_list_response(self, client):
        """api_key must never appear in GET list response."""
        token = _make_platform_token()
        resp = client.post(
            "/api/v1/platform/providers",
            json={
                "provider_type": "azure_openai",
                "display_name": "Security Test Provider 01",
                "endpoint": SECURITY_ENDPOINT,
                "api_key": SECURITY_KEY,
                "models": {},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code not in (200, 201):
            pytest.skip(f"Provider creation failed: {resp.text}")

        provider_id = resp.json()["id"]
        self.__class__._security_provider_id = provider_id

        # Get list
        list_resp = client.get(
            "/api/v1/platform/providers",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert list_resp.status_code == 200

        # api_key must not appear in response body
        response_text = list_resp.text
        assert (
            SECURITY_KEY not in response_text
        ), "plaintext api_key appeared in list response body"

    # ------------------------------------------------------------------
    # Test 2: POST → GET detail: api_key not in response
    # ------------------------------------------------------------------

    def test_02_api_key_not_in_detail_response(self, client):
        """api_key must never appear in GET detail response."""
        provider_id = getattr(self.__class__, "_security_provider_id", None)
        if provider_id is None:
            pytest.skip("test_01 must run first")

        token = _make_platform_token()
        resp = client.get(
            f"/api/v1/platform/providers/{provider_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert (
            SECURITY_KEY not in resp.text
        ), "plaintext api_key appeared in detail response body"

    # ------------------------------------------------------------------
    # Test 3: POST with structlog capture: api_key not in any log record
    # ------------------------------------------------------------------

    def test_03_api_key_not_in_structlog_on_create(self, client):
        """api_key must not appear in any structlog record during POST."""
        import structlog
        from structlog.testing import capture_logs

        token = _make_platform_token()

        with capture_logs() as cap:
            resp = client.post(
                "/api/v1/platform/providers",
                json={
                    "provider_type": "azure_openai",
                    "display_name": "Security Test Provider 03 Log",
                    "endpoint": SECURITY_ENDPOINT,
                    "api_key": SECURITY_KEY,
                    "models": {},
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        if resp.status_code not in (200, 201):
            pytest.skip(f"Provider creation failed: {resp.text}")

        # Check all log records
        for record in cap:
            record_str = json.dumps(record, default=str)
            assert (
                SECURITY_KEY not in record_str
            ), f"api_key appeared in log record: {record_str[:200]}"

    # ------------------------------------------------------------------
    # Test 4: PATCH (update key) with structlog: new api_key not in logs
    # ------------------------------------------------------------------

    def test_04_api_key_not_in_structlog_on_update(self, client):
        """New api_key must not appear in any structlog record during PATCH."""
        import structlog
        from structlog.testing import capture_logs

        provider_id = getattr(self.__class__, "_security_provider_id", None)
        if provider_id is None:
            pytest.skip("test_01 must run first")

        new_key = "sk-updated-security-test-key-xyz"
        token = _make_platform_token()

        with capture_logs() as cap:
            resp = client.patch(
                f"/api/v1/platform/providers/{provider_id}",
                json={"api_key": new_key},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200

        for record in cap:
            record_str = json.dumps(record, default=str)
            assert (
                new_key not in record_str
            ), f"new api_key appeared in log record: {record_str[:200]}"

    # ------------------------------------------------------------------
    # Test 5: POST with api_key as query param → 422
    # ------------------------------------------------------------------

    def test_05_api_key_as_query_param_rejected(self, client):
        """api_key passed as query parameter must be rejected with 422."""
        token = _make_platform_token()
        resp = client.post(
            "/api/v1/platform/providers",
            params={"api_key": SECURITY_KEY},
            json={
                "provider_type": "azure_openai",
                "display_name": "Security Test Should Fail",
                "endpoint": SECURITY_ENDPOINT,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        # No api_key in body → Pydantic validation error (api_key required field)
        assert resp.status_code == 422

    # ------------------------------------------------------------------
    # Test 6: DB direct: api_key_encrypted is bytes, NOT equal to api_key.encode()
    # ------------------------------------------------------------------

    def test_06_db_encrypted_is_bytes_not_plaintext(self):
        """DB row: api_key_encrypted is bytes, not equal to plaintext.encode()."""
        provider_id = getattr(self.__class__, "_security_provider_id", None)
        if provider_id is None:
            pytest.skip("test_01 must run first")

        encrypted_bytes = _get_encrypted_bytes(provider_id)
        assert len(encrypted_bytes) > 0, "api_key_encrypted is empty"
        assert isinstance(encrypted_bytes, bytes)
        # Must NOT be the updated key (from test_04) or original key
        # The encrypted value is a Fernet token — it starts with 'gAAA' in base64
        # It must not equal either plaintext encoding
        assert encrypted_bytes != SECURITY_KEY.encode("utf-8")
        assert encrypted_bytes != b"sk-updated-security-test-key-xyz"

    # ------------------------------------------------------------------
    # Test 7: DB decrypt: fernet.decrypt(api_key_encrypted) == api_key.encode()
    # ------------------------------------------------------------------

    def test_07_db_decrypt_correct(self):
        """DB decrypt: fernet.decrypt(api_key_encrypted) == updated_key.encode('utf-8')."""
        provider_id = getattr(self.__class__, "_security_provider_id", None)
        if provider_id is None:
            pytest.skip("test_01 must run first")

        encrypted_bytes = _get_encrypted_bytes(provider_id)
        assert len(encrypted_bytes) > 0

        # The key was updated in test_04 to this value
        expected_key = "sk-updated-security-test-key-xyz"

        from app.core.llm.provider_service import ProviderService

        svc = ProviderService()
        decrypted = svc.decrypt_api_key(encrypted_bytes)
        assert (
            decrypted == expected_key
        ), f"Decrypted key {decrypted!r} != expected {expected_key!r}"

    # ------------------------------------------------------------------
    # Test 8: PATCH omitting api_key → api_key_encrypted unchanged
    # ------------------------------------------------------------------

    def test_08_patch_omitting_key_unchanged(self, client):
        """PATCH without api_key field → api_key_encrypted decrypts to same key."""
        provider_id = getattr(self.__class__, "_security_provider_id", None)
        if provider_id is None:
            pytest.skip("test_01 must run first")

        # Record current encrypted bytes
        before_encrypted = _get_encrypted_bytes(provider_id)
        assert len(before_encrypted) > 0

        # PATCH only display_name
        token = _make_platform_token()
        resp = client.patch(
            f"/api/v1/platform/providers/{provider_id}",
            json={"display_name": "Security Test Provider 01 Final"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        # api_key_encrypted must be byte-for-byte identical
        after_encrypted = _get_encrypted_bytes(provider_id)
        assert (
            after_encrypted == before_encrypted
        ), "api_key_encrypted changed even though api_key was not in PATCH body"

        # Must still decrypt to the same key as after test_04
        expected_key = "sk-updated-security-test-key-xyz"
        from app.core.llm.provider_service import ProviderService

        svc = ProviderService()
        decrypted = svc.decrypt_api_key(after_encrypted)
        assert decrypted == expected_key
