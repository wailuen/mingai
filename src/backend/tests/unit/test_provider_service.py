"""
PVDR-017: Unit tests for ProviderService.

Tier 1: Unit tests — mocked DB sessions, no real PostgreSQL.

9 test cases:
1. encrypt/decrypt round-trip
2. encrypt output is bytes
3. encrypt output != plaintext.encode("utf-8")
4. list_providers() never has api_key_encrypted key
5. set_default() calls db.execute exactly twice in correct order
6. test_connectivity() returns (True, None) on success
7. test_connectivity() returns (False, "message") on failure
8. create_provider() encrypts key before DB write
9. update_provider() without api_key: SQL doesn't reference api_key_encrypted
"""
import os
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

TEST_JWT_SECRET = "z" * 64
FAKE_API_KEY = "sk-test-key-1234567890"
FAKE_ENDPOINT = "https://fake.openai.azure.com/"


@pytest.fixture(autouse=True)
def _set_jwt_secret():
    with patch.dict(os.environ, {"JWT_SECRET_KEY": TEST_JWT_SECRET}):
        yield


# ---------------------------------------------------------------------------
# Test 1: encrypt/decrypt round-trip
# ---------------------------------------------------------------------------


class TestEncryptDecryptRoundTrip:
    def test_encrypt_decrypt_round_trip(self):
        """encrypt_api_key / decrypt_api_key produce identical plaintext."""
        from app.core.llm.provider_service import ProviderService

        svc = ProviderService()
        plaintext = "my-secret-api-key-abc123"
        encrypted = svc.encrypt_api_key(plaintext)
        decrypted = svc.decrypt_api_key(encrypted)
        assert decrypted == plaintext


# ---------------------------------------------------------------------------
# Test 2: encrypt output is bytes
# ---------------------------------------------------------------------------


class TestEncryptOutputIsBytes:
    def test_encrypt_returns_bytes(self):
        """encrypt_api_key returns bytes (suitable for BYTEA column)."""
        from app.core.llm.provider_service import ProviderService

        svc = ProviderService()
        result = svc.encrypt_api_key(FAKE_API_KEY)
        assert isinstance(result, bytes)


# ---------------------------------------------------------------------------
# Test 3: encrypted bytes != plaintext bytes
# ---------------------------------------------------------------------------


class TestEncryptedNotPlaintext:
    def test_encrypted_differs_from_plaintext(self):
        """Encrypted bytes must not equal plaintext.encode('utf-8')."""
        from app.core.llm.provider_service import ProviderService

        svc = ProviderService()
        plaintext = FAKE_API_KEY
        encrypted = svc.encrypt_api_key(plaintext)
        assert encrypted != plaintext.encode("utf-8")


# ---------------------------------------------------------------------------
# Test 4: list_providers() never has api_key_encrypted key
# ---------------------------------------------------------------------------


class TestListProvidersNoKey:
    @pytest.mark.asyncio
    async def test_list_providers_never_has_api_key_encrypted(self):
        """list_providers() response dicts never contain api_key_encrypted key."""
        from app.core.llm.provider_service import ProviderService

        svc = ProviderService()

        # Build a fake row: (id, type, display_name, desc, endpoint, models, options,
        #  pricing, is_enabled, is_default, status, last_health, health_error,
        #  created_at, updated_at, created_by, key_present)
        from unittest.mock import MagicMock
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        fake_row = (
            "00000000-0000-0000-0000-000000000001",  # id
            "azure_openai",  # provider_type
            "Test Provider",  # display_name
            None,  # description
            FAKE_ENDPOINT,  # endpoint
            {"primary": "gpt-5"},  # models
            {},  # options
            None,  # pricing
            True,  # is_enabled
            True,  # is_default
            "unchecked",  # provider_status
            None,  # last_health_check_at
            None,  # health_error
            now,  # created_at
            now,  # updated_at
            None,  # created_by
            True,  # key_present
        )

        mock_db = AsyncMock()
        mock_execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [fake_row]
        mock_execute.return_value = mock_result
        mock_db.execute = mock_execute

        providers = await svc.list_providers(mock_db)

        assert len(providers) == 1
        provider = providers[0]
        assert "api_key_encrypted" not in provider
        assert "key_present" in provider
        assert provider["key_present"] is True


# ---------------------------------------------------------------------------
# Test 5: set_default() calls db.execute exactly twice in correct order
# ---------------------------------------------------------------------------


class TestSetDefaultTwoStep:
    @pytest.mark.asyncio
    async def test_set_default_calls_execute_twice_in_order(self):
        """set_default() executes EXACTLY two UPDATE statements in the correct order."""
        from app.core.llm.provider_service import ProviderService

        svc = ProviderService()
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        target_id = "test-provider-uuid"
        await svc.set_default(mock_db, target_id)

        # Verify exactly 3 execute calls: set_config + clear all + set one
        # The actual DB executes are calls 1 and 2 (index 1 and 2)
        all_calls = mock_db.execute.call_args_list
        assert len(all_calls) == 3  # set_config + clear + set

        # Extract SQL strings from calls (args[0] is the text() object)
        sql_strings = []
        for c in all_calls:
            sql_arg = c.args[0] if c.args else None
            if sql_arg is not None:
                sql_strings.append(str(sql_arg))

        # First execute: set_config for platform scope
        assert "set_config" in sql_strings[0].lower()

        # Second execute: clear all is_default = true
        assert "is_default = false" in sql_strings[1]
        assert "is_default = true" in sql_strings[1]

        # Third execute: set is_default = true WHERE id = :id
        assert "is_default = true" in sql_strings[2]
        assert ":id" in sql_strings[2]

        # Commit must be called exactly once
        mock_db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 6: test_connectivity() returns (True, None) on success
# ---------------------------------------------------------------------------


class TestConnectivitySuccess:
    @pytest.mark.asyncio
    async def test_test_connectivity_success(self):
        """test_connectivity() returns (True, None) when API call succeeds."""
        from app.core.llm.provider_service import ProviderService

        svc = ProviderService()

        provider_row = {
            "id": "test-id",
            "provider_type": "azure_openai",
            "endpoint": FAKE_ENDPOINT,
            "models": {"primary": "agentic-worker"},
            "options": {},
        }

        encrypted = svc.encrypt_api_key(FAKE_API_KEY)

        class _FakeCtxSuccess:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def execute(self, *a, **kw):
                mock_result = MagicMock()
                mock_row = (
                    "test-id",
                    "azure_openai",
                    "T",
                    None,
                    FAKE_ENDPOINT,
                    {},
                    {},
                    None,
                    True,
                    False,
                    "unchecked",
                    None,
                    None,
                    None,
                    None,
                    None,
                    True,
                    encrypted,
                )
                mock_result.fetchone.return_value = mock_row
                return mock_result

        def _fake_session_factory_success():
            return _FakeCtxSuccess()

        with patch(
            "app.core.llm.provider_service.async_session_factory",
            _fake_session_factory_success,
        ):
            with patch(
                "app.core.llm.provider_service._do_connectivity_test",
                AsyncMock(return_value=(True, None)),
            ):
                success, error = await svc.test_connectivity(provider_row)

        assert success is True
        assert error is None


# ---------------------------------------------------------------------------
# Test 7: test_connectivity() returns (False, "message") on failure
# ---------------------------------------------------------------------------


class TestConnectivityFailure:
    @pytest.mark.asyncio
    async def test_test_connectivity_failure(self):
        """test_connectivity() returns (False, error_message) when API call fails."""
        from app.core.llm.provider_service import ProviderService

        svc = ProviderService()

        provider_row = {
            "id": "test-id",
            "provider_type": "azure_openai",
            "endpoint": FAKE_ENDPOINT,
            "models": {},
            "options": {},
        }

        encrypted = svc.encrypt_api_key(FAKE_API_KEY)

        class _FakeCtxFailure:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def execute(self, *a, **kw):
                mock_result = MagicMock()
                mock_row = (
                    "test-id",
                    "azure_openai",
                    "T",
                    None,
                    FAKE_ENDPOINT,
                    {},
                    {},
                    None,
                    True,
                    False,
                    "unchecked",
                    None,
                    None,
                    None,
                    None,
                    None,
                    True,
                    encrypted,
                )
                mock_result.fetchone.return_value = mock_row
                return mock_result

        def _fake_session_factory_failure():
            return _FakeCtxFailure()

        error_msg = "AuthenticationError: Invalid API key"

        with patch(
            "app.core.llm.provider_service.async_session_factory",
            _fake_session_factory_failure,
        ):
            with patch(
                "app.core.llm.provider_service._do_connectivity_test",
                AsyncMock(return_value=(False, error_msg)),
            ):
                success, error = await svc.test_connectivity(provider_row)

        assert success is False
        assert error == error_msg


# ---------------------------------------------------------------------------
# Test 8: create_provider() encrypts key before DB write
# ---------------------------------------------------------------------------


class TestCreateProviderEncryptsKey:
    @pytest.mark.asyncio
    async def test_create_provider_encrypts_api_key(self):
        """create_provider() stores encrypted bytes, not plaintext key."""
        from app.core.llm.provider_service import ProviderService
        from datetime import datetime, timezone

        svc = ProviderService()

        # Track what was passed to db.execute
        captured_params = []
        now = datetime.now(timezone.utc)

        # Fake row for get_provider call after creation
        fake_provider_row = (
            "new-id",
            "azure_openai",
            "Test",
            None,
            FAKE_ENDPOINT,
            {},
            {},
            None,
            True,
            False,
            "unchecked",
            None,
            None,
            now,
            now,
            None,
            True,
        )

        call_count = [0]

        async def _fake_execute(stmt, params=None):
            if params is not None:
                captured_params.append(dict(params) if params else {})
            mock_result = MagicMock()
            mock_result.fetchone.return_value = fake_provider_row
            mock_result.fetchall.return_value = []
            return mock_result

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_fake_execute)
        mock_db.commit = AsyncMock()

        payload = {
            "provider_type": "azure_openai",
            "display_name": "Test Provider",
            "endpoint": FAKE_ENDPOINT,
            "api_key": FAKE_API_KEY,
            "models": {},
            "options": {},
        }

        await svc.create_provider(mock_db, payload, created_by=None)

        # Find the INSERT call params (contains api_key_encrypted)
        insert_params = None
        for p in captured_params:
            if "api_key_encrypted" in p:
                insert_params = p
                break

        assert insert_params is not None, "INSERT call not found in captured params"
        stored_key = insert_params["api_key_encrypted"]

        # Must be bytes
        assert isinstance(stored_key, bytes), "api_key_encrypted must be bytes"

        # Must not equal plaintext
        assert stored_key != FAKE_API_KEY.encode(
            "utf-8"
        ), "api_key_encrypted must not equal plaintext bytes"

        # Must decrypt correctly
        decrypted = svc.decrypt_api_key(stored_key)
        assert decrypted == FAKE_API_KEY


# ---------------------------------------------------------------------------
# Test 9: update_provider() without api_key: SQL doesn't reference api_key_encrypted
# ---------------------------------------------------------------------------


class TestUpdateProviderNoKeyChange:
    @pytest.mark.asyncio
    async def test_update_without_api_key_does_not_touch_encrypted_column(self):
        """
        update_provider() with no api_key in updates must not reference
        api_key_encrypted in the SQL statement.
        """
        from app.core.llm.provider_service import ProviderService
        from datetime import datetime, timezone

        svc = ProviderService()
        now = datetime.now(timezone.utc)

        captured_sqls = []
        fake_row = (
            "test-id",
            "azure_openai",
            "Updated Name",
            None,
            FAKE_ENDPOINT,
            {},
            {},
            None,
            True,
            False,
            "unchecked",
            None,
            None,
            now,
            now,
            None,
            True,
        )

        async def _fake_execute(stmt, params=None):
            sql_str = str(stmt)
            captured_sqls.append(sql_str)
            mock_result = MagicMock()
            mock_result.fetchone.return_value = fake_row
            mock_result.rowcount = 1
            return mock_result

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_fake_execute)
        mock_db.commit = AsyncMock()

        updates = {"display_name": "Updated Name"}
        await svc.update_provider(mock_db, "test-id", updates)

        # The UPDATE SQL must not reference api_key_encrypted in the SET clause.
        # (The subsequent re-fetch SELECT contains api_key_encrypted inside octet_length()
        # for the key_present flag — that is expected safe read-only usage.)
        update_sqls = [
            s for s in captured_sqls if s.strip().upper().startswith("UPDATE")
        ]
        assert len(update_sqls) >= 1, "No UPDATE SQL found"

        for sql in update_sqls:
            assert (
                "api_key_encrypted" not in sql
            ), f"api_key_encrypted appeared in UPDATE SQL when api_key not in updates: {sql}"
