"""
Integration-style unit tests for AWS Bedrock provider lifecycle (BEDROCK-015).

Tier 1: Unit tests using AsyncMock/patch — no real DB, no real LLM calls.
Follows the same pattern as test_llm_library_credentials.py.

Scenarios covered:
1. Bedrock publish gate: missing endpoint_url → 422
2. Bedrock publish gate: with endpoint_url but without api_version → succeeds (no api_version gate)
3. Bedrock publish gate: missing api_key → 422 (shared gate)
4. Bedrock publish gate: missing last_test_passed_at → 422 (shared gate)
5. Bedrock region mismatch at create time → 422
6. Bedrock region mismatch at update time → 422
7. Azure OpenAI publish gate unchanged — still requires api_version
8. api_key_encrypted never appears in publish gate path (only key_present bool exposed)
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

TEST_ENTRY_ID = "22222222-2222-2222-2222-222222222222"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bedrock_entry(**kwargs):
    """Build a minimal LLMLibraryEntry for Bedrock publish gate testing."""
    from app.modules.platform.llm_library.routes import LLMLibraryEntry

    defaults = dict(
        id=TEST_ENTRY_ID,
        provider="bedrock",
        model_name="arn:aws:bedrock:ap-southeast-1:123456:application-inference-profile/abc",
        display_name="Bedrock Claude 3 Sonnet",
        plan_tier="enterprise",
        is_recommended=False,
        status="draft",
        pricing_per_1k_tokens_in=0.003,
        pricing_per_1k_tokens_out=0.015,
        key_present=True,
        endpoint_url="https://bedrock-runtime.ap-southeast-1.amazonaws.com",
        api_version=None,  # Bedrock does NOT use api_version
        last_test_passed_at="2026-03-22T12:00:00+00:00",
        created_at="2026-03-22T00:00:00+00:00",
        updated_at="2026-03-22T00:00:00+00:00",
    )
    defaults.update(kwargs)
    return LLMLibraryEntry(**defaults)


# ---------------------------------------------------------------------------
# BEDROCK-015-01: Bedrock publish gate — missing endpoint_url → 422
# ---------------------------------------------------------------------------


class TestBedrockPublishGate:
    """Bedrock publish gate enforces endpoint_url requirement (not api_version)."""

    @pytest.mark.asyncio
    async def test_publish_gate_bedrock_requires_endpoint_url(self):
        """Bedrock without endpoint_url → 422 with 'Bedrock entries require endpoint_url'."""
        from fastapi import HTTPException

        from app.modules.platform.llm_library.routes import publish_llm_library_entry

        entry = _make_bedrock_entry(endpoint_url=None)
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
            assert "Bedrock entries require endpoint_url" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_publish_gate_bedrock_does_not_require_api_version(self):
        """Bedrock with endpoint_url but without api_version passes the provider-specific gate."""
        from fastapi import HTTPException

        from app.modules.platform.llm_library.routes import publish_llm_library_entry

        # endpoint_url present, api_version=None — should NOT trigger provider gate
        # but will still be blocked by the shared 'last_test_passed_at' gate
        entry = _make_bedrock_entry(
            api_version=None,
            last_test_passed_at=None,  # trigger shared gate, not api_version gate
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
            # Must NOT be about api_version — must be the shared connectivity test gate
            assert exc_info.value.status_code == 422
            assert "api_version" not in exc_info.value.detail
            assert "connectivity test" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_publish_gate_bedrock_missing_api_key(self):
        """Bedrock without api_key → 422 'api_key must be set before publishing'."""
        from fastapi import HTTPException

        from app.modules.platform.llm_library.routes import publish_llm_library_entry

        entry = _make_bedrock_entry(key_present=False)
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
    async def test_publish_gate_bedrock_missing_last_test_passed_at(self):
        """Bedrock without last_test_passed_at → 422 'must pass a connectivity test'."""
        from fastapi import HTTPException

        from app.modules.platform.llm_library.routes import publish_llm_library_entry

        entry = _make_bedrock_entry(last_test_passed_at=None)
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


# ---------------------------------------------------------------------------
# BEDROCK-015-05: Region mismatch at create time → 422
# BEDROCK-015-06: Region mismatch at update time → 422
# ---------------------------------------------------------------------------


class TestBedrockRegionValidation:
    """_validate_bedrock_region_consistency called at create and update time."""

    @pytest.mark.asyncio
    async def test_create_bedrock_region_mismatch_returns_422(self):
        """POST /platform/llm-library with mismatched ARN/endpoint regions → 422."""
        from fastapi import HTTPException

        from app.modules.platform.llm_library.routes import create_llm_library_entry
        from app.modules.platform.llm_library.routes import CreateLLMLibraryRequest

        request = CreateLLMLibraryRequest(
            provider="bedrock",
            model_name="arn:aws:bedrock:us-east-1:123456:application-inference-profile/abc",
            display_name="Bedrock Test",
            plan_tier="enterprise",
            endpoint_url="https://bedrock-runtime.ap-southeast-1.amazonaws.com",
        )
        mock_db = AsyncMock()
        mock_user = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await create_llm_library_entry(
                request=request,
                current_user=mock_user,
                db=mock_db,
            )
        assert exc_info.value.status_code == 422
        assert "Region mismatch" in exc_info.value.detail
        assert "us-east-1" in exc_info.value.detail
        assert "ap-southeast-1" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_update_bedrock_region_mismatch_returns_422(self):
        """PATCH /{id} with mismatched ARN/endpoint regions → 422."""
        from fastapi import HTTPException

        from app.modules.platform.llm_library.routes import update_llm_library_entry
        from app.modules.platform.llm_library.routes import UpdateLLMLibraryRequest

        existing_entry = _make_bedrock_entry()
        request = UpdateLLMLibraryRequest(
            model_name="arn:aws:bedrock:us-east-1:123456:application-inference-profile/abc",
        )
        mock_db = AsyncMock()
        mock_user = MagicMock()

        with patch(
            "app.modules.platform.llm_library.routes._get_entry",
            return_value=existing_entry,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await update_llm_library_entry(
                    entry_id=TEST_ENTRY_ID,
                    request=request,
                    current_user=mock_user,
                    db=mock_db,
                )
        assert exc_info.value.status_code == 422
        assert "Region mismatch" in exc_info.value.detail


# ---------------------------------------------------------------------------
# BEDROCK-015-07: Azure OpenAI publish gate unchanged — still requires api_version
# ---------------------------------------------------------------------------


class TestAzurePublishGateUnchanged:
    """Azure OpenAI publish gate still requires api_version after Bedrock changes."""

    @pytest.mark.asyncio
    async def test_azure_publish_still_requires_api_version(self):
        """azure_openai without api_version → 422 — Bedrock changes must not break Azure gate."""
        from fastapi import HTTPException

        from app.modules.platform.llm_library.routes import LLMLibraryEntry
        from app.modules.platform.llm_library.routes import publish_llm_library_entry

        entry = LLMLibraryEntry(
            id=TEST_ENTRY_ID,
            provider="azure_openai",
            model_name="gpt-4o",
            display_name="GPT-4o",
            plan_tier="professional",
            is_recommended=False,
            status="draft",
            pricing_per_1k_tokens_in=0.002,
            pricing_per_1k_tokens_out=0.006,
            key_present=True,
            endpoint_url="https://my-resource.cognitiveservices.azure.com",
            api_version=None,  # Missing — should be blocked
            last_test_passed_at="2026-03-22T12:00:00+00:00",
            created_at="2026-03-22T00:00:00+00:00",
            updated_at="2026-03-22T00:00:00+00:00",
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
            assert "api_version" in exc_info.value.detail


# ---------------------------------------------------------------------------
# BEDROCK-015-08: api_key_encrypted never in publish gate response path
# ---------------------------------------------------------------------------


class TestBedrockCredentialSecurity:
    """api_key_encrypted must never appear in any code path through the publish gate."""

    def test_llm_library_entry_schema_has_no_api_key_encrypted_field(self):
        """LLMLibraryEntry Pydantic model does not expose api_key_encrypted."""
        from app.modules.platform.llm_library.routes import LLMLibraryEntry

        fields = set(LLMLibraryEntry.model_fields.keys())
        assert "api_key_encrypted" not in fields
        # key_present (bool) and api_key_last4 are the only credential exposure points
        assert "key_present" in fields
        assert "api_key_last4" in fields

    def test_select_columns_expresses_api_key_as_bool_not_bytes(self):
        """_SELECT_COLUMNS exposes api_key_encrypted only as a computed bool, never raw bytes.

        The column appears as '(api_key_encrypted IS NOT NULL) AS key_present' — the
        raw BYTEA value is never selected by _SELECT_COLUMNS queries.
        """
        from app.modules.platform.llm_library.routes import _SELECT_COLUMNS

        # api_key_encrypted appears only inside a NULL check expression — never bare
        assert "(api_key_encrypted IS NOT NULL) AS key_present" in _SELECT_COLUMNS
        # It does NOT appear as a standalone column name (which would return raw bytes)
        assert "api_key_encrypted," not in _SELECT_COLUMNS
        assert _SELECT_COLUMNS.strip().startswith("id,")
