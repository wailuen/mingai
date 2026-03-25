"""
Unit tests for CredentialScrubber (C-01 security requirement).

These tests are pure unit tests — no DB, no HTTP, no vault interaction.
The scrubber must redact credential values from all error messages, log entries,
and LLM context regardless of injection type.
"""
import pytest

from app.core.credential_scrubber import CredentialScrubber


# ---------------------------------------------------------------------------
# Basic scrubbing
# ---------------------------------------------------------------------------


def test_scrubber_replaces_credential_in_error():
    """Credential value appearing in third-party error must be replaced."""
    resolved = {"API_KEY": "super-secret-value-12345"}
    scrubber = CredentialScrubber(resolved)
    raw = "Request failed: auth=super-secret-value-12345 endpoint=api.example.com"
    scrubbed = scrubber.scrub(raw)
    assert "super-secret-value-12345" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_scrubber_ignores_short_values():
    """Values with 4 or fewer characters are not tracked (too many false positives)."""
    resolved = {"SHORT": "abc"}  # len <= 4
    scrubber = CredentialScrubber(resolved)
    text = "contains abc in a message"
    assert scrubber.scrub(text) == text  # Short values must not be tracked


def test_scrubber_no_false_positives():
    """Scrubber must not modify strings that do not contain credential values."""
    resolved = {"KEY": "real-secret-value-xyz"}
    scrubber = CredentialScrubber(resolved)
    text = "normal log message with no credential"
    assert scrubber.scrub(text) == text


def test_scrubber_multiple_credentials():
    """All tracked values in the resolved dict are scrubbed from output."""
    resolved = {
        "KEY_A": "first-secret-aaa",
        "KEY_B": "second-secret-bbb",
    }
    scrubber = CredentialScrubber(resolved)
    raw = "auth=first-secret-aaa header=second-secret-bbb endpoint=api.example.com"
    scrubbed = scrubber.scrub(raw)
    assert "first-secret-aaa" not in scrubbed
    assert "second-secret-bbb" not in scrubbed
    assert scrubbed.count("[REDACTED]") == 2


def test_scrubber_empty_resolved():
    """Empty resolved dict — scrub is a no-op."""
    scrubber = CredentialScrubber({})
    text = "some text"
    assert scrubber.scrub(text) == text


def test_scrubber_empty_input():
    """Empty string input returns empty string without error."""
    resolved = {"KEY": "secret-value-xyz"}
    scrubber = CredentialScrubber(resolved)
    assert scrubber.scrub("") == ""
    assert scrubber.scrub(None) is None  # type: ignore[arg-type]


def test_scrubber_platform_credential_format():
    """Platform credential format {key: {"value": str, "injection_config": dict}} is supported."""
    resolved = {
        "API_KEY": {
            "value": "platform-secret-1234",
            "injection_config": {"type": "bearer"},
        }
    }
    scrubber = CredentialScrubber(resolved)
    raw = "Error: invalid token=platform-secret-1234"
    scrubbed = scrubber.scrub(raw)
    assert "platform-secret-1234" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_scrubber_flat_tenant_credential_format():
    """Tenant credential format {key: str} is also supported."""
    resolved = {"TENANT_KEY": "tenant-secret-5678"}
    scrubber = CredentialScrubber(resolved)
    raw = "Header X-Api-Key: tenant-secret-5678"
    scrubbed = scrubber.scrub(raw)
    assert "tenant-secret-5678" not in scrubbed
    assert "[REDACTED]" in scrubbed


# ---------------------------------------------------------------------------
# scrub_dict
# ---------------------------------------------------------------------------


def test_scrub_dict_string_values():
    """scrub_dict replaces credential values in string dict values."""
    resolved = {"KEY": "secret-dict-value"}
    scrubber = CredentialScrubber(resolved)
    data = {"message": "error contains secret-dict-value here", "code": 403}
    result = scrubber.scrub_dict(data)
    assert "secret-dict-value" not in result["message"]
    assert "[REDACTED]" in result["message"]
    assert result["code"] == 403


def test_scrub_dict_nested():
    """scrub_dict recursively handles nested dicts."""
    resolved = {"KEY": "nested-secret-xyz"}
    scrubber = CredentialScrubber(resolved)
    data = {"outer": {"inner": "contains nested-secret-xyz in value"}}
    result = scrubber.scrub_dict(data)
    assert "nested-secret-xyz" not in result["outer"]["inner"]
    assert "[REDACTED]" in result["outer"]["inner"]


def test_scrub_dict_list_values():
    """scrub_dict handles list values within dicts."""
    resolved = {"KEY": "list-secret-abc"}
    scrubber = CredentialScrubber(resolved)
    data = {"errors": ["error: list-secret-abc is invalid", "other error"]}
    result = scrubber.scrub_dict(data)
    assert "list-secret-abc" not in result["errors"][0]
    assert "[REDACTED]" in result["errors"][0]
    assert result["errors"][1] == "other error"


# ---------------------------------------------------------------------------
# All 4 injection type values are redacted
# ---------------------------------------------------------------------------


def test_scrubber_covers_all_injection_types():
    """CredentialScrubber must redact values regardless of injection type."""
    resolved_values = {
        "BEARER_KEY": "mytoken123456",
        "HEADER_KEY": "pb-secret-xyz-abc",
        "BASIC_CRED": "user:password12345",
        "QUERY_KEY": "qp-value-abc-def",
    }
    scrubber = CredentialScrubber(resolved_values)
    raw = "auth=mytoken123456 header=pb-secret-xyz-abc basic=user:password12345 qp=qp-value-abc-def"
    scrubbed = scrubber.scrub(raw)
    for val in resolved_values.values():
        assert val not in scrubbed, f"Value '{val}' was not redacted"
    assert scrubbed.count("[REDACTED]") == 4
