"""
Unit tests for LLM Library credential features (LLM-009).

Tier 1: Unit tests — uses mocked DB sessions and no real LLM calls.

Coverage:
- Create: encrypts api_key, stores last4, key_present=True in response
- Create without api_key: key_present=False
- Update: clears last_test_passed_at when api_key/endpoint_url/api_version changes
- Publish gate: azure provider requirements, key required, test required
- Test harness: 422 when no key stored
- Input validators: endpoint_url (https only), api_version (date format)
- _row_to_entry: correct mapping of new columns
"""
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError


TEST_JWT_SECRET = "a" * 64
TEST_ENTRY_ID = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# Schema validator tests (no DB needed)
# ---------------------------------------------------------------------------


class TestEndpointUrlValidator:
    """CreateLLMLibraryRequest and UpdateLLMLibraryRequest reject non-https endpoints."""

    def test_https_url_accepted(self):
        from app.modules.platform.llm_library.routes import CreateLLMLibraryRequest

        req = CreateLLMLibraryRequest(
            provider="azure_openai",
            model_name="gpt-4o",
            display_name="GPT-4o",
            plan_tier="Professional",
            endpoint_url="https://my-resource.openai.azure.com/",
        )
        assert req.endpoint_url == "https://my-resource.openai.azure.com/"

    def test_http_url_rejected(self):
        from app.modules.platform.llm_library.routes import CreateLLMLibraryRequest

        with pytest.raises(ValidationError) as exc_info:
            CreateLLMLibraryRequest(
                provider="azure_openai",
                model_name="gpt-4o",
                display_name="GPT-4o",
                plan_tier="Professional",
                endpoint_url="http://insecure.openai.azure.com/",
            )
        assert "https" in str(exc_info.value).lower()

    def test_bare_hostname_rejected(self):
        from app.modules.platform.llm_library.routes import CreateLLMLibraryRequest

        with pytest.raises(ValidationError):
            CreateLLMLibraryRequest(
                provider="azure_openai",
                model_name="gpt-4o",
                display_name="GPT-4o",
                plan_tier="Professional",
                endpoint_url="my-resource.openai.azure.com",
            )

    def test_none_accepted(self):
        """None is valid — endpoint is optional at create time."""
        from app.modules.platform.llm_library.routes import CreateLLMLibraryRequest

        req = CreateLLMLibraryRequest(
            provider="azure_openai",
            model_name="gpt-4o",
            display_name="GPT-4o",
            plan_tier="Professional",
            endpoint_url=None,
        )
        assert req.endpoint_url is None

    def test_update_request_validates_endpoint_url(self):
        """UpdateLLMLibraryRequest has the same validator."""
        from app.modules.platform.llm_library.routes import UpdateLLMLibraryRequest

        with pytest.raises(ValidationError):
            UpdateLLMLibraryRequest(endpoint_url="ftp://bad-scheme.example.com")


class TestApiVersionValidator:
    """api_version must match YYYY-MM-DD or YYYY-MM-DD-preview."""

    def test_valid_date_format_accepted(self):
        from app.modules.platform.llm_library.routes import CreateLLMLibraryRequest

        req = CreateLLMLibraryRequest(
            provider="azure_openai",
            model_name="gpt-4o",
            display_name="GPT-4o",
            plan_tier="Professional",
            api_version="2024-12-01",
        )
        assert req.api_version == "2024-12-01"

    def test_preview_suffix_accepted(self):
        from app.modules.platform.llm_library.routes import CreateLLMLibraryRequest

        req = CreateLLMLibraryRequest(
            provider="azure_openai",
            model_name="gpt-4o",
            display_name="GPT-4o",
            plan_tier="Professional",
            api_version="2024-12-01-preview",
        )
        assert req.api_version == "2024-12-01-preview"

    def test_freeform_string_rejected(self):
        from app.modules.platform.llm_library.routes import CreateLLMLibraryRequest

        with pytest.raises(ValidationError) as exc_info:
            CreateLLMLibraryRequest(
                provider="azure_openai",
                model_name="gpt-4o",
                display_name="GPT-4o",
                plan_tier="Professional",
                api_version="latest",
            )
        assert "YYYY-MM-DD" in str(exc_info.value)

    def test_partial_date_rejected(self):
        from app.modules.platform.llm_library.routes import CreateLLMLibraryRequest

        with pytest.raises(ValidationError):
            CreateLLMLibraryRequest(
                provider="azure_openai",
                model_name="gpt-4o",
                display_name="GPT-4o",
                plan_tier="Professional",
                api_version="2024-12",
            )

    def test_none_accepted(self):
        """None is valid — api_version is optional at create time."""
        from app.modules.platform.llm_library.routes import CreateLLMLibraryRequest

        req = CreateLLMLibraryRequest(
            provider="azure_openai",
            model_name="gpt-4o",
            display_name="GPT-4o",
            plan_tier="Professional",
            api_version=None,
        )
        assert req.api_version is None

    def test_update_request_validates_api_version(self):
        """UpdateLLMLibraryRequest has the same validator."""
        from app.modules.platform.llm_library.routes import UpdateLLMLibraryRequest

        with pytest.raises(ValidationError):
            UpdateLLMLibraryRequest(api_version="v2")


# ---------------------------------------------------------------------------
# _row_to_entry tests
# ---------------------------------------------------------------------------


class TestRowToEntry:
    """_row_to_entry correctly maps new credential columns."""

    def _make_row(
        self,
        *,
        key_present=False,
        api_key_last4=None,
        endpoint_url=None,
        api_version=None,
        last_test_passed_at=None,
    ):
        """Build a mock DB row tuple matching _SELECT_COLUMNS column order."""
        # 0: id, 1: provider, 2: model_name, 3: display_name, 4: plan_tier
        # 5: is_recommended, 6: status, 7: best_practices_md
        # 8: pricing_per_1k_tokens_in, 9: pricing_per_1k_tokens_out
        # 10: created_at, 11: updated_at
        # 12: endpoint_url, 13: key_present, 14: api_key_last4
        # 15: api_version, 16: last_test_passed_at
        now = datetime(2026, 3, 21, 0, 0, 0, tzinfo=timezone.utc)
        return (
            "11111111-1111-1111-1111-111111111111",  # 0 id
            "azure_openai",                           # 1 provider
            "gpt-4o",                                 # 2 model_name
            "GPT-4o Test",                            # 3 display_name
            "Professional",                           # 4 plan_tier
            True,                                     # 5 is_recommended
            "Draft",                                  # 6 status
            None,                                     # 7 best_practices_md
            0.002,                                    # 8 pricing_per_1k_tokens_in
            0.006,                                    # 9 pricing_per_1k_tokens_out
            now,                                      # 10 created_at
            now,                                      # 11 updated_at
            endpoint_url,                             # 12 endpoint_url
            key_present,                              # 13 key_present (computed bool)
            api_key_last4,                            # 14 api_key_last4
            api_version,                              # 15 api_version
            last_test_passed_at,                      # 16 last_test_passed_at
        )

    def test_key_present_false_when_null(self):
        """key_present=False when api_key_encrypted column is NULL."""
        from app.modules.platform.llm_library.routes import _row_to_entry

        row = self._make_row(key_present=False)
        entry = _row_to_entry(row)
        assert entry.key_present is False

    def test_key_present_true_when_set(self):
        """key_present=True when api_key_encrypted is NOT NULL."""
        from app.modules.platform.llm_library.routes import _row_to_entry

        row = self._make_row(key_present=True, api_key_last4="1234")
        entry = _row_to_entry(row)
        assert entry.key_present is True

    def test_api_key_last4_populated(self):
        """api_key_last4 is correctly mapped from row[14]."""
        from app.modules.platform.llm_library.routes import _row_to_entry

        row = self._make_row(key_present=True, api_key_last4="5678")
        entry = _row_to_entry(row)
        assert entry.api_key_last4 == "5678"

    def test_api_key_last4_none_when_no_key(self):
        """api_key_last4 is None when no key is stored."""
        from app.modules.platform.llm_library.routes import _row_to_entry

        row = self._make_row(key_present=False, api_key_last4=None)
        entry = _row_to_entry(row)
        assert entry.api_key_last4 is None

    def test_endpoint_url_populated(self):
        """endpoint_url is correctly mapped from row[12]."""
        from app.modules.platform.llm_library.routes import _row_to_entry

        url = "https://my.openai.azure.com/"
        row = self._make_row(endpoint_url=url)
        entry = _row_to_entry(row)
        assert entry.endpoint_url == url

    def test_api_version_populated(self):
        """api_version is correctly mapped from row[15]."""
        from app.modules.platform.llm_library.routes import _row_to_entry

        row = self._make_row(api_version="2024-12-01-preview")
        entry = _row_to_entry(row)
        assert entry.api_version == "2024-12-01-preview"

    def test_last_test_passed_at_iso_string(self):
        """last_test_passed_at serializes as ISO 8601 string."""
        from app.modules.platform.llm_library.routes import _row_to_entry

        ts = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        row = self._make_row(last_test_passed_at=ts)
        entry = _row_to_entry(row)
        assert entry.last_test_passed_at is not None
        assert "2026-03-21" in entry.last_test_passed_at

    def test_last_test_passed_at_none_when_not_set(self):
        """last_test_passed_at is None when column is NULL."""
        from app.modules.platform.llm_library.routes import _row_to_entry

        row = self._make_row(last_test_passed_at=None)
        entry = _row_to_entry(row)
        assert entry.last_test_passed_at is None

    def test_api_key_encrypted_never_in_entry(self):
        """api_key_encrypted is never a field on LLMLibraryEntry."""
        from app.modules.platform.llm_library.routes import LLMLibraryEntry, _row_to_entry

        row = self._make_row(key_present=True, api_key_last4="9999")
        entry = _row_to_entry(row)

        # Verify no api_key_encrypted field exists at all
        entry_dict = entry.model_dump()
        assert "api_key_encrypted" not in entry_dict
        assert "api_key" not in entry_dict


# ---------------------------------------------------------------------------
# Publish gate unit tests (using mocked entry objects)
# ---------------------------------------------------------------------------


class TestPublishGate:
    """Publish gate checks provider-specific requirements."""

    def _make_entry(self, **kwargs):
        """Build a minimal LLMLibraryEntry suitable for publish gate testing."""
        from app.modules.platform.llm_library.routes import LLMLibraryEntry

        defaults = dict(
            id=TEST_ENTRY_ID,
            provider="azure_openai",
            model_name="gpt-4o",
            display_name="GPT-4o",
            plan_tier="Professional",
            is_recommended=False,
            status="Draft",
            pricing_per_1k_tokens_in=0.002,
            pricing_per_1k_tokens_out=0.006,
            key_present=True,
            endpoint_url="https://my.openai.azure.com/",
            api_version="2024-12-01-preview",
            last_test_passed_at="2026-03-21T12:00:00+00:00",
            created_at="2026-03-21T00:00:00+00:00",
            updated_at="2026-03-21T00:00:00+00:00",
        )
        defaults.update(kwargs)
        return LLMLibraryEntry(**defaults)

    @pytest.mark.asyncio
    async def test_publish_gate_azure_requires_endpoint_url(self):
        """azure_openai without endpoint_url → 422."""
        from fastapi import HTTPException

        from app.modules.platform.llm_library.routes import publish_llm_library_entry

        entry = self._make_entry(endpoint_url=None)

        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            return_value=entry,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await publish_llm_library_entry(
                    entry_id=TEST_ENTRY_ID,
                    current_user=mock_user,
                    db=mock_db,
                )
            assert exc_info.value.status_code == 422
            assert "endpoint_url" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_publish_gate_azure_requires_api_version(self):
        """azure_openai without api_version → 422."""
        from fastapi import HTTPException

        from app.modules.platform.llm_library.routes import publish_llm_library_entry

        entry = self._make_entry(api_version=None)

        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            return_value=entry,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await publish_llm_library_entry(
                    entry_id=TEST_ENTRY_ID,
                    current_user=mock_user,
                    db=mock_db,
                )
            assert exc_info.value.status_code == 422
            assert "api_version" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_publish_gate_blocks_missing_api_key(self):
        """Any provider without api_key → 422 'api_key must be set'."""
        from fastapi import HTTPException

        from app.modules.platform.llm_library.routes import publish_llm_library_entry

        entry = self._make_entry(
            provider="openai_direct",
            endpoint_url=None,
            api_version=None,
            key_present=False,
        )

        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            return_value=entry,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await publish_llm_library_entry(
                    entry_id=TEST_ENTRY_ID,
                    current_user=mock_user,
                    db=mock_db,
                )
            assert exc_info.value.status_code == 422
            assert "api_key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_publish_gate_blocks_null_last_test_passed_at(self):
        """Entry with key set but no test → 422 'must pass a connectivity test'."""
        from fastapi import HTTPException

        from app.modules.platform.llm_library.routes import publish_llm_library_entry

        entry = self._make_entry(last_test_passed_at=None)

        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            return_value=entry,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await publish_llm_library_entry(
                    entry_id=TEST_ENTRY_ID,
                    current_user=mock_user,
                    db=mock_db,
                )
            assert exc_info.value.status_code == 422
            assert "connectivity test" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_publish_gate_blocks_missing_pricing(self):
        """Entry with all credentials but no pricing → 422."""
        from fastapi import HTTPException

        from app.modules.platform.llm_library.routes import publish_llm_library_entry

        entry = self._make_entry(pricing_per_1k_tokens_in=None)

        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            return_value=entry,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await publish_llm_library_entry(
                    entry_id=TEST_ENTRY_ID,
                    current_user=mock_user,
                    db=mock_db,
                )
            assert exc_info.value.status_code == 422
            assert "pricing" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_publish_gate_already_published_returns_409(self):
        """Entry that is already Published → 409 (existing check retained)."""
        from fastapi import HTTPException

        from app.modules.platform.llm_library.routes import publish_llm_library_entry

        entry = self._make_entry(status="Published")

        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            return_value=entry,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await publish_llm_library_entry(
                    entry_id=TEST_ENTRY_ID,
                    current_user=mock_user,
                    db=mock_db,
                )
            assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_publish_gate_openai_direct_no_endpoint_required(self):
        """openai_direct with key + test + pricing (no endpoint) — publish gate passes."""
        from app.modules.platform.llm_library.routes import (
            LLMLibraryEntry,
            publish_llm_library_entry,
        )

        entry = self._make_entry(
            provider="openai_direct",
            endpoint_url=None,
            api_version=None,
        )

        # Mock DB that returns rowcount=1 for the update and then the updated entry
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.execute.return_value = mock_result
        mock_db.commit = AsyncMock()
        mock_user = MagicMock()

        updated_entry = self._make_entry(
            provider="openai_direct",
            endpoint_url=None,
            api_version=None,
            status="Published",
        )

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            side_effect=[entry, updated_entry],
        ):
            result = await publish_llm_library_entry(
                entry_id=TEST_ENTRY_ID,
                current_user=mock_user,
                db=mock_db,
            )
        assert result.status == "Published"


# ---------------------------------------------------------------------------
# Test harness: 422 when no key stored
# ---------------------------------------------------------------------------


class TestTestHarnessNoKey:
    """test_llm_library_profile returns 422 when entry has no API key."""

    @pytest.mark.asyncio
    async def test_test_harness_returns_422_for_null_key(self):
        """POST /{id}/test on entry with key_present=False → 422."""
        from fastapi import HTTPException

        from app.modules.platform.llm_library.routes import test_llm_library_profile

        from app.modules.platform.llm_library.routes import LLMLibraryEntry

        entry = LLMLibraryEntry(
            id=TEST_ENTRY_ID,
            provider="azure_openai",
            model_name="gpt-4o",
            display_name="GPT-4o",
            plan_tier="Professional",
            is_recommended=False,
            status="Draft",
            key_present=False,
            created_at="2026-03-21T00:00:00+00:00",
            updated_at="2026-03-21T00:00:00+00:00",
        )

        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            return_value=entry,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await test_llm_library_profile(
                    entry_id=TEST_ENTRY_ID,
                    current_user=mock_user,
                    db=mock_db,
                )
            assert exc_info.value.status_code == 422
            assert "API key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_test_harness_returns_409_for_deprecated(self):
        """POST /{id}/test on Deprecated entry → 409 (regression)."""
        from fastapi import HTTPException

        from app.modules.platform.llm_library.routes import test_llm_library_profile

        from app.modules.platform.llm_library.routes import LLMLibraryEntry

        entry = LLMLibraryEntry(
            id=TEST_ENTRY_ID,
            provider="azure_openai",
            model_name="gpt-4o",
            display_name="GPT-4o",
            plan_tier="Professional",
            is_recommended=False,
            status="Deprecated",
            key_present=True,
            created_at="2026-03-21T00:00:00+00:00",
            updated_at="2026-03-21T00:00:00+00:00",
        )

        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            return_value=entry,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await test_llm_library_profile(
                    entry_id=TEST_ENTRY_ID,
                    current_user=mock_user,
                    db=mock_db,
                )
            assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Encrypt/decrypt round-trip (app.core.crypto)
# ---------------------------------------------------------------------------


class TestEncryptDecryptRoundTripInLibrary:
    """app.core.crypto round-trip — as called from LLM library create/update paths."""

    @pytest.fixture(autouse=True)
    def _set_jwt_secret(self):
        with patch.dict(os.environ, {"JWT_SECRET_KEY": TEST_JWT_SECRET}):
            yield

    def test_encrypt_decrypt_roundtrip(self):
        """encrypt_api_key followed by decrypt_api_key returns original."""
        from app.core.crypto import decrypt_api_key, encrypt_api_key

        original = "sk-test-library-key-9876"
        encrypted = encrypt_api_key(original)
        assert isinstance(encrypted, bytes)
        decrypted = decrypt_api_key(encrypted)
        assert decrypted == original

    def test_endpoint_url_validator_rejects_http(self):
        """endpoint_url with http:// scheme raises ValidationError."""
        from app.modules.platform.llm_library.routes import CreateLLMLibraryRequest

        with pytest.raises(ValidationError):
            CreateLLMLibraryRequest(
                provider="azure_openai",
                model_name="gpt-4o",
                display_name="GPT-4o",
                plan_tier="Professional",
                endpoint_url="http://should-be-https.example.com",
            )

    def test_api_version_validator_rejects_freeform(self):
        """api_version with freeform string raises ValidationError."""
        from app.modules.platform.llm_library.routes import CreateLLMLibraryRequest

        with pytest.raises(ValidationError):
            CreateLLMLibraryRequest(
                provider="azure_openai",
                model_name="gpt-4o",
                display_name="GPT-4o",
                plan_tier="Professional",
                api_version="v2024-latest",
            )

    def test_api_version_validator_accepts_preview_suffix(self):
        """api_version with -preview suffix is accepted."""
        from app.modules.platform.llm_library.routes import CreateLLMLibraryRequest

        req = CreateLLMLibraryRequest(
            provider="azure_openai",
            model_name="gpt-4o",
            display_name="GPT-4o",
            plan_tier="Professional",
            api_version="2024-12-01-preview",
        )
        assert req.api_version == "2024-12-01-preview"


# ---------------------------------------------------------------------------
# Update credential_changed logic
# ---------------------------------------------------------------------------


class TestUpdateCredentialChanged:
    """Verify last_test_passed_at is reset when credentials change."""

    @pytest.mark.asyncio
    async def test_update_entry_clears_test_timestamp_when_key_changes(self):
        """PATCH with new api_key includes last_test_passed_at = NULL in SET clause."""
        from app.modules.platform.llm_library.routes import (
            LLMLibraryEntry,
            update_llm_library_entry,
            UpdateLLMLibraryRequest,
        )

        existing_entry = LLMLibraryEntry(
            id=TEST_ENTRY_ID,
            provider="azure_openai",
            model_name="gpt-4o",
            display_name="GPT-4o",
            plan_tier="Professional",
            is_recommended=False,
            status="Draft",
            key_present=True,
            last_test_passed_at="2026-03-21T12:00:00+00:00",
            created_at="2026-03-21T00:00:00+00:00",
            updated_at="2026-03-21T00:00:00+00:00",
        )

        updated_entry = LLMLibraryEntry(
            id=TEST_ENTRY_ID,
            provider="azure_openai",
            model_name="gpt-4o",
            display_name="GPT-4o",
            plan_tier="Professional",
            is_recommended=False,
            status="Draft",
            key_present=True,
            last_test_passed_at=None,  # reset after key change
            created_at="2026-03-21T00:00:00+00:00",
            updated_at="2026-03-21T00:00:00+00:00",
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.execute.return_value = mock_result
        mock_db.commit = AsyncMock()
        mock_user = MagicMock()

        captured_sql = []

        async def capture_execute(sql, params=None):
            captured_sql.append(str(sql))
            return mock_result

        mock_db.execute.side_effect = capture_execute

        request = UpdateLLMLibraryRequest(api_key="sk-new-key-5678")

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            side_effect=[existing_entry, updated_entry],
        ):
            with patch.dict(os.environ, {"JWT_SECRET_KEY": TEST_JWT_SECRET}):
                result = await update_llm_library_entry(
                    entry_id=TEST_ENTRY_ID,
                    request=request,
                    current_user=mock_user,
                    db=mock_db,
                )

        # Verify that last_test_passed_at = NULL was in the UPDATE SQL
        update_sql = " ".join(captured_sql)
        assert "last_test_passed_at = NULL" in update_sql

    @pytest.mark.asyncio
    async def test_update_entry_clears_test_timestamp_when_endpoint_changes(self):
        """PATCH with new endpoint_url includes last_test_passed_at = NULL in SET clause."""
        from app.modules.platform.llm_library.routes import (
            LLMLibraryEntry,
            update_llm_library_entry,
            UpdateLLMLibraryRequest,
        )

        existing_entry = LLMLibraryEntry(
            id=TEST_ENTRY_ID,
            provider="azure_openai",
            model_name="gpt-4o",
            display_name="GPT-4o",
            plan_tier="Professional",
            is_recommended=False,
            status="Draft",
            key_present=True,
            last_test_passed_at="2026-03-21T12:00:00+00:00",
            endpoint_url="https://old.openai.azure.com/",
            created_at="2026-03-21T00:00:00+00:00",
            updated_at="2026-03-21T00:00:00+00:00",
        )

        updated_entry = LLMLibraryEntry(
            id=TEST_ENTRY_ID,
            provider="azure_openai",
            model_name="gpt-4o",
            display_name="GPT-4o",
            plan_tier="Professional",
            is_recommended=False,
            status="Draft",
            key_present=True,
            last_test_passed_at=None,
            endpoint_url="https://new.openai.azure.com/",
            created_at="2026-03-21T00:00:00+00:00",
            updated_at="2026-03-21T00:00:00+00:00",
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.execute.return_value = mock_result
        mock_db.commit = AsyncMock()
        mock_user = MagicMock()

        captured_sql = []

        async def capture_execute(sql, params=None):
            captured_sql.append(str(sql))
            return mock_result

        mock_db.execute.side_effect = capture_execute

        request = UpdateLLMLibraryRequest(endpoint_url="https://new.openai.azure.com/")

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            side_effect=[existing_entry, updated_entry],
        ):
            result = await update_llm_library_entry(
                entry_id=TEST_ENTRY_ID,
                request=request,
                current_user=mock_user,
                db=mock_db,
            )

        update_sql = " ".join(captured_sql)
        assert "last_test_passed_at = NULL" in update_sql

    def test_create_entry_no_key_key_present_false(self):
        """_row_to_entry with no key: key_present=False."""
        from app.modules.platform.llm_library.routes import _row_to_entry

        now = datetime(2026, 3, 21, tzinfo=timezone.utc)
        row = (
            TEST_ENTRY_ID, "openai_direct", "gpt-4o-mini", "Mini", "Starter",
            False, "Draft", None, None, None, now, now,
            None,   # endpoint_url
            False,  # key_present
            None,   # api_key_last4
            None,   # api_version
            None,   # last_test_passed_at
        )
        entry = _row_to_entry(row)
        assert entry.key_present is False
        assert entry.api_key_last4 is None

    def test_create_entry_encrypts_api_key_sets_key_present(self):
        """_row_to_entry with key_present=True: key_present True and last4 set."""
        from app.modules.platform.llm_library.routes import _row_to_entry

        now = datetime(2026, 3, 21, tzinfo=timezone.utc)
        row = (
            TEST_ENTRY_ID, "openai_direct", "gpt-4o-mini", "Mini", "Starter",
            False, "Draft", None, None, None, now, now,
            None,   # endpoint_url
            True,   # key_present (computed: api_key_encrypted IS NOT NULL)
            "5678", # api_key_last4
            None,   # api_version
            None,   # last_test_passed_at
        )
        entry = _row_to_entry(row)
        assert entry.key_present is True
        assert entry.api_key_last4 == "5678"
        # Verify api_key_encrypted is NOT in response
        assert "api_key_encrypted" not in entry.model_dump()


# ---------------------------------------------------------------------------
# DELETE endpoint tests
# ---------------------------------------------------------------------------


class TestDeleteLLMLibraryEntry:
    """DELETE /{entry_id} — Draft entries only."""

    def _make_entry(self, status: str = "Draft"):
        from app.modules.platform.llm_library.routes import LLMLibraryEntry

        return LLMLibraryEntry(
            id=TEST_ENTRY_ID,
            provider="openai_direct",
            model_name="gpt-4o-mini",
            display_name="Test Entry",
            plan_tier="Starter",
            is_recommended=False,
            status=status,
            key_present=False,
            last_test_passed_at=None,
            created_at="2026-03-21T00:00:00+00:00",
            updated_at="2026-03-21T00:00:00+00:00",
        )

    @pytest.mark.asyncio
    async def test_delete_draft_entry_succeeds(self):
        """DELETE on a Draft entry returns 204 and executes DELETE SQL."""
        from app.modules.platform.llm_library.routes import delete_llm_library_entry

        entry = self._make_entry("Draft")
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.execute.return_value = mock_result
        mock_db.commit = AsyncMock()
        mock_user = MagicMock()

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            return_value=entry,
        ):
            result = await delete_llm_library_entry(
                entry_id=TEST_ENTRY_ID,
                current_user=mock_user,
                db=mock_db,
            )

        assert result is None  # 204 No Content
        mock_db.commit.assert_called_once()

        # Verify DELETE SQL was executed
        call_args = mock_db.execute.call_args_list[0]
        sql_str = str(call_args[0][0])
        assert "DELETE" in sql_str
        assert "status = 'Draft'" in sql_str

    @pytest.mark.asyncio
    async def test_delete_published_entry_fails_409(self):
        """DELETE on a Published entry returns 409 Conflict."""
        from fastapi import HTTPException
        from app.modules.platform.llm_library.routes import delete_llm_library_entry

        entry = self._make_entry("Published")
        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            return_value=entry,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await delete_llm_library_entry(
                    entry_id=TEST_ENTRY_ID,
                    current_user=mock_user,
                    db=mock_db,
                )

        assert exc_info.value.status_code == 409
        assert "Draft" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_delete_deprecated_entry_fails_409(self):
        """DELETE on a Deprecated entry returns 409 Conflict."""
        from fastapi import HTTPException
        from app.modules.platform.llm_library.routes import delete_llm_library_entry

        entry = self._make_entry("Deprecated")
        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            return_value=entry,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await delete_llm_library_entry(
                    entry_id=TEST_ENTRY_ID,
                    current_user=mock_user,
                    db=mock_db,
                )

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_delete_nonexistent_entry_fails_404(self):
        """DELETE on a missing entry returns 404."""
        from fastapi import HTTPException
        from app.modules.platform.llm_library.routes import delete_llm_library_entry

        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await delete_llm_library_entry(
                    entry_id=TEST_ENTRY_ID,
                    current_user=mock_user,
                    db=mock_db,
                )

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# SSRF validation tests
# ---------------------------------------------------------------------------


class TestAssertEndpointSsrfSafe:
    """_assert_endpoint_ssrf_safe blocks private/loopback/link-local IPs."""

    def test_public_hostname_raises_no_error(self):
        """A hostname that resolves to a public IP should pass (mocked)."""
        from unittest.mock import patch
        from app.modules.platform.llm_library.routes import _assert_endpoint_ssrf_safe
        import socket

        # Mock socket.getaddrinfo to return a public IP
        with patch.object(
            socket, "getaddrinfo",
            return_value=[(None, None, None, None, ("8.8.8.8", 0))]
        ):
            # Should not raise
            _assert_endpoint_ssrf_safe("https://ai.cognitiveservices.azure.com/")

    def test_loopback_ip_raises(self):
        """127.x.x.x is blocked."""
        from unittest.mock import patch
        from app.modules.platform.llm_library.routes import _assert_endpoint_ssrf_safe
        import socket

        with patch.object(
            socket, "getaddrinfo",
            return_value=[(None, None, None, None, ("127.0.0.1", 0))]
        ):
            with pytest.raises(ValueError, match="non-routable"):
                _assert_endpoint_ssrf_safe("https://localhost/")

    def test_private_rfc1918_raises(self):
        """192.168.x.x is blocked."""
        from unittest.mock import patch
        from app.modules.platform.llm_library.routes import _assert_endpoint_ssrf_safe
        import socket

        with patch.object(
            socket, "getaddrinfo",
            return_value=[(None, None, None, None, ("192.168.1.1", 0))]
        ):
            with pytest.raises(ValueError, match="non-routable"):
                _assert_endpoint_ssrf_safe("https://internal.corp/")

    def test_link_local_raises(self):
        """169.254.x.x (Azure IMDS, AWS metadata) is blocked."""
        from unittest.mock import patch
        from app.modules.platform.llm_library.routes import _assert_endpoint_ssrf_safe
        import socket

        with patch.object(
            socket, "getaddrinfo",
            return_value=[(None, None, None, None, ("169.254.169.254", 0))]
        ):
            with pytest.raises(ValueError, match="non-routable"):
                _assert_endpoint_ssrf_safe("https://metadata.internal/")

    def test_missing_hostname_raises(self):
        """A URL with no hostname raises ValueError immediately."""
        from app.modules.platform.llm_library.routes import _assert_endpoint_ssrf_safe

        with pytest.raises(ValueError, match="hostname"):
            _assert_endpoint_ssrf_safe("https:///path")

    def test_dns_failure_raises(self):
        """Unresolvable hostname raises ValueError."""
        from unittest.mock import patch
        from app.modules.platform.llm_library.routes import _assert_endpoint_ssrf_safe
        import socket

        with patch.object(
            socket, "getaddrinfo",
            side_effect=socket.gaierror("Name or service not known")
        ):
            with pytest.raises(ValueError, match="Cannot resolve"):
                _assert_endpoint_ssrf_safe("https://does-not-exist.invalid/")


# ---------------------------------------------------------------------------
# model_name change triggers last_test_passed_at reset
# ---------------------------------------------------------------------------


class TestModelNameChangeResetsTest:
    """model_name change must set credential_changed=True → clear last_test_passed_at."""

    @pytest.mark.asyncio
    async def test_model_name_change_on_published_entry_clears_test(self):
        """Changing model_name on a Published entry must reset last_test_passed_at."""
        from datetime import datetime, timezone
        from app.modules.platform.llm_library.routes import (
            LLMLibraryEntry,
            UpdateLLMLibraryRequest,
            update_llm_library_entry,
        )

        now = datetime(2026, 3, 21, tzinfo=timezone.utc)
        existing_entry = LLMLibraryEntry(
            id=TEST_ENTRY_ID,
            provider="openai_direct",
            model_name="gpt-4o",
            display_name="My Entry",
            plan_tier="Professional",
            is_recommended=False,
            status="Published",
            key_present=True,
            last_test_passed_at=now.isoformat(),
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
        updated_entry = LLMLibraryEntry(
            id=TEST_ENTRY_ID,
            provider="openai_direct",
            model_name="gpt-4o-mini",
            display_name="My Entry",
            plan_tier="Professional",
            is_recommended=False,
            status="Published",
            key_present=True,
            last_test_passed_at=None,  # cleared after update
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.commit = AsyncMock()

        captured_sql = []

        async def capture_execute(sql, params=None):
            captured_sql.append(str(sql))
            return mock_result

        mock_db.execute.side_effect = capture_execute
        mock_user = MagicMock()

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            side_effect=[existing_entry, updated_entry],
        ):
            result = await update_llm_library_entry(
                entry_id=TEST_ENTRY_ID,
                request=UpdateLLMLibraryRequest(model_name="gpt-4o-mini"),
                current_user=mock_user,
                db=mock_db,
            )

        # last_test_passed_at = NULL must appear in the SQL
        update_sql = " ".join(captured_sql)
        assert "last_test_passed_at = NULL" in update_sql
        assert result.last_test_passed_at is None

    @pytest.mark.asyncio
    async def test_same_model_name_does_not_clear_test(self):
        """Updating model_name to the SAME value should NOT clear last_test_passed_at."""
        from datetime import datetime, timezone
        from app.modules.platform.llm_library.routes import (
            LLMLibraryEntry,
            UpdateLLMLibraryRequest,
            update_llm_library_entry,
        )

        now = datetime(2026, 3, 21, tzinfo=timezone.utc)
        existing_entry = LLMLibraryEntry(
            id=TEST_ENTRY_ID,
            provider="openai_direct",
            model_name="gpt-4o",
            display_name="My Entry",
            plan_tier="Professional",
            is_recommended=False,
            status="Published",
            key_present=True,
            last_test_passed_at=now.isoformat(),
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
        updated_entry = LLMLibraryEntry(
            id=TEST_ENTRY_ID,
            provider="openai_direct",
            model_name="gpt-4o",
            display_name="New Display Name",
            plan_tier="Professional",
            is_recommended=False,
            status="Published",
            key_present=True,
            last_test_passed_at=now.isoformat(),
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.commit = AsyncMock()

        captured_sql = []

        async def capture_execute(sql, params=None):
            captured_sql.append(str(sql))
            return mock_result

        mock_db.execute.side_effect = capture_execute
        mock_user = MagicMock()

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            side_effect=[existing_entry, updated_entry],
        ):
            await update_llm_library_entry(
                entry_id=TEST_ENTRY_ID,
                request=UpdateLLMLibraryRequest(
                    model_name="gpt-4o",  # same model
                    display_name="New Display Name",
                ),
                current_user=mock_user,
                db=mock_db,
            )

        update_sql = " ".join(captured_sql)
        # last_test_passed_at should NOT be cleared for same model name
        assert "last_test_passed_at = NULL" not in update_sql
