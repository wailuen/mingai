"""
Unit tests for SSRF domain allowlist enforcement (TODO-28).

Tests that validate_llm_endpoint() raises SSRFValidationError for domains
not in the approved provider list, and passes for all approved domains.
"""
from unittest.mock import patch

import pytest

from app.core.security.url_validator import SSRFValidationError, validate_llm_endpoint


def _mock_dns_success(hostname, *args, **kwargs):
    """Return a public IP (8.8.8.8) for any hostname during DNS resolution."""
    return [(2, 1, 6, "", ("8.8.8.8", 0))]


class TestAllowlistedDomainsPass:
    """Known provider domains must pass the allowlist check."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://mydeployment.openai.azure.com/",
            "https://mydeployment.openai.azure.com/openai/deployments/gpt-4o",
            "https://api.openai.com/v1/chat/completions",
            "https://api.anthropic.com/v1/messages",
            "https://generativelanguage.googleapis.com/v1/models",
            "https://api.groq.com/openai/v1/chat/completions",
            "https://bedrock-runtime.ap-southeast-1.amazonaws.com/",
            "https://bedrock-runtime.us-east-1.amazonaws.com/",
            "https://bedrock-agent-runtime.us-west-2.amazonaws.com/",
        ],
    )
    def test_approved_domains_pass(self, url):
        with patch("socket.getaddrinfo", side_effect=_mock_dns_success):
            # Should not raise
            validate_llm_endpoint(url)


class TestNonAllowlistedDomainsFail:
    """Domains not in the allowlist must raise SSRFValidationError."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://notallowed.example.com/api",
            "https://malicious.openai.azure.com.evil.com/api",  # subdomain squatting
            "https://api.openai.com.evil.com/",                  # suffix squatting
            "https://evil.com/",
            "https://localhost/api",
            "http://notallowed.example.com/api",
        ],
    )
    def test_rejected_domains_raise(self, url):
        with patch("socket.getaddrinfo", side_effect=_mock_dns_success):
            with pytest.raises(SSRFValidationError) as exc_info:
                validate_llm_endpoint(url)
            # Error message must NOT expose URL or domain details
            assert url not in str(exc_info.value)
            assert "not on the approved provider list" in str(exc_info.value)

    def test_error_message_does_not_expose_url(self):
        """Security invariant: rejected URL must never appear in error message."""
        url = "https://secret-internal-service.corp/api"
        with patch("socket.getaddrinfo", side_effect=_mock_dns_success):
            with pytest.raises(SSRFValidationError) as exc_info:
                validate_llm_endpoint(url)
        # URL should NOT be in the error message text shown to users
        assert url not in str(exc_info.value)
        assert "secret-internal-service" not in str(exc_info.value)
