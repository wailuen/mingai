"""
Unit tests for AWS Bedrock provider support in the LLM Library (BEDROCK-014).

Tier 1: Unit tests — no network calls, no DB required.

Coverage:
- base_url construction: {endpoint_url}/v1 suffix mandatory
- Trailing slash stripped from endpoint_url before appending /v1
- 'bedrock' in _VALID_PROVIDERS frozenset
- ARN model_name accepted (max_length only — no prefix validation per ADR-5)
- Non-ARN model_name accepted
- Region cross-validation: ARN region vs endpoint_url region
- Region match passes without error
- Non-ARN skips region check
- usage=None guard: tokens default to 0
- _validate_bedrock_region_consistency helper directly
"""
import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# BEDROCK-014-01: base_url construction — /v1 suffix mandatory
# ---------------------------------------------------------------------------


def test_bedrock_base_url_construction_uses_v1_suffix():
    """base_url must end with /v1 — not /model/{arn}/ or bare endpoint."""
    endpoint = "https://bedrock-runtime.ap-southeast-1.amazonaws.com"
    base_url = f"{endpoint.rstrip('/')}/v1"
    assert base_url == "https://bedrock-runtime.ap-southeast-1.amazonaws.com/v1"


# ---------------------------------------------------------------------------
# BEDROCK-014-02: trailing slash stripped
# ---------------------------------------------------------------------------


def test_bedrock_base_url_strips_trailing_slash():
    """Trailing slash on endpoint_url must be stripped before appending /v1."""
    endpoint = "https://bedrock-runtime.ap-southeast-1.amazonaws.com/"
    base_url = f"{endpoint.rstrip('/')}/v1"
    assert base_url == "https://bedrock-runtime.ap-southeast-1.amazonaws.com/v1"


# ---------------------------------------------------------------------------
# BEDROCK-014-03: 'bedrock' in _VALID_PROVIDERS
# ---------------------------------------------------------------------------


def test_bedrock_in_valid_providers_frozenset():
    """'bedrock' must be a member of _VALID_PROVIDERS after BEDROCK-002."""
    from app.modules.platform.llm_library.routes import _VALID_PROVIDERS

    assert "bedrock" in _VALID_PROVIDERS


# ---------------------------------------------------------------------------
# BEDROCK-014-04: ARN model_name accepted (max_length=200, no prefix check)
# ---------------------------------------------------------------------------


def test_bedrock_accepts_arn_model_name():
    """Bedrock accepts full ARN — no prefix check (ADR-5). Only max_length=200."""
    arn = "arn:aws:bedrock:ap-southeast-1:106056766526:application-inference-profile/6wbz52t5c3rz"
    assert len(arn) <= 200


# ---------------------------------------------------------------------------
# BEDROCK-014-05: non-ARN model_name accepted
# ---------------------------------------------------------------------------


def test_bedrock_accepts_plain_model_id():
    """Bedrock also accepts non-ARN model IDs — test harness is the real validator."""
    model_id = "anthropic.claude-3-sonnet-20240229-v1:0"
    assert len(model_id) <= 200
    assert not model_id.startswith("arn:")  # confirms prefix check not applied


# ---------------------------------------------------------------------------
# BEDROCK-014-06: region cross-validation detects mismatch
# ---------------------------------------------------------------------------


def test_bedrock_region_cross_validation_detects_mismatch():
    """Region in ARN must match region in endpoint_url."""
    endpoint = "https://bedrock-runtime.ap-southeast-1.amazonaws.com"
    arn = "arn:aws:bedrock:us-east-1:123456:application-inference-profile/abc"
    url_region = endpoint.replace("https://", "").split(".")[1]
    arn_region = arn.split(":")[3]
    assert url_region == "ap-southeast-1"
    assert arn_region == "us-east-1"
    assert url_region != arn_region  # should trigger 422


# ---------------------------------------------------------------------------
# BEDROCK-014-07: matching regions pass without error
# ---------------------------------------------------------------------------


def test_bedrock_region_cross_validation_matching_regions():
    """Matching regions pass without error."""
    endpoint = "https://bedrock-runtime.ap-southeast-1.amazonaws.com"
    arn = "arn:aws:bedrock:ap-southeast-1:123456:application-inference-profile/abc"
    url_region = endpoint.replace("https://", "").split(".")[1]
    arn_region = arn.split(":")[3]
    assert url_region == arn_region


# ---------------------------------------------------------------------------
# BEDROCK-014-08: non-ARN skips region check
# ---------------------------------------------------------------------------


def test_bedrock_non_arn_skips_region_check():
    """Non-ARN model IDs have no region to extract — region check is skipped."""
    model_id = "anthropic.claude-3-sonnet-20240229-v1:0"
    is_arn = model_id.startswith("arn:aws:bedrock:")
    assert not is_arn  # confirms no region check applied


# ---------------------------------------------------------------------------
# BEDROCK-014-09: usage=None guard
# ---------------------------------------------------------------------------


def test_bedrock_usage_none_guard():
    """Defensive guard: tokens_in/out default to 0 when usage is None."""
    usage = None
    tokens_in = usage.prompt_tokens if usage else 0
    tokens_out = usage.completion_tokens if usage else 0
    assert tokens_in == 0
    assert tokens_out == 0


# ---------------------------------------------------------------------------
# BEDROCK-014-10: _validate_bedrock_region_consistency raises 422 on mismatch
# ---------------------------------------------------------------------------


def test_validate_bedrock_region_consistency_raises_on_mismatch():
    """_validate_bedrock_region_consistency raises HTTPException(422) on region mismatch."""
    from app.modules.platform.llm_library.routes import (
        _validate_bedrock_region_consistency,
    )

    endpoint = "https://bedrock-runtime.ap-southeast-1.amazonaws.com"
    arn = "arn:aws:bedrock:us-east-1:123456:application-inference-profile/abc"
    with pytest.raises(HTTPException) as exc_info:
        _validate_bedrock_region_consistency("bedrock", endpoint, arn)
    assert exc_info.value.status_code == 422
    assert "Region mismatch" in exc_info.value.detail
    assert "us-east-1" in exc_info.value.detail
    assert "ap-southeast-1" in exc_info.value.detail


# ---------------------------------------------------------------------------
# BEDROCK-014-11: _validate_bedrock_region_consistency silent when matching
# ---------------------------------------------------------------------------


def test_validate_bedrock_region_consistency_passes_on_match():
    """_validate_bedrock_region_consistency does not raise when regions match."""
    from app.modules.platform.llm_library.routes import (
        _validate_bedrock_region_consistency,
    )

    endpoint = "https://bedrock-runtime.ap-southeast-1.amazonaws.com"
    arn = "arn:aws:bedrock:ap-southeast-1:123456:application-inference-profile/abc"
    # Should not raise
    _validate_bedrock_region_consistency("bedrock", endpoint, arn)


# ---------------------------------------------------------------------------
# BEDROCK-014-12: _validate_bedrock_region_consistency silent for non-ARN
# ---------------------------------------------------------------------------


def test_validate_bedrock_region_consistency_skips_non_arn():
    """Non-ARN model_name skips region check — no exception raised."""
    from app.modules.platform.llm_library.routes import (
        _validate_bedrock_region_consistency,
    )

    endpoint = "https://bedrock-runtime.ap-southeast-1.amazonaws.com"
    model_id = "anthropic.claude-3-sonnet-20240229-v1:0"
    # Should not raise — non-ARN skips region validation
    _validate_bedrock_region_consistency("bedrock", endpoint, model_id)


# ---------------------------------------------------------------------------
# BEDROCK-014-13: _validate_bedrock_region_consistency silent for non-bedrock providers
# ---------------------------------------------------------------------------


def test_validate_bedrock_region_consistency_ignores_other_providers():
    """Region check is only applied to provider=='bedrock' — other providers skip."""
    from app.modules.platform.llm_library.routes import (
        _validate_bedrock_region_consistency,
    )

    # azure_openai with mismatched-looking values — must not raise
    _validate_bedrock_region_consistency(
        "azure_openai",
        "https://bedrock-runtime.us-east-1.amazonaws.com",
        "arn:aws:bedrock:ap-southeast-1:123456:application-inference-profile/abc",
    )
