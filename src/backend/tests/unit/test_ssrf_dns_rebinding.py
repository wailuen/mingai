"""
Unit tests for SSRF DNS rebinding protection (TODO-28).

Tests that validate_llm_endpoint() checks ALL resolved IPs from DNS and
rejects requests where any resolved address is private, even when the
domain is on the allowlist.
"""
from unittest.mock import patch

import pytest

from app.core.security.url_validator import SSRFValidationError, validate_llm_endpoint


def _make_dns_result(ips: list[str]) -> list:
    """Build a mock getaddrinfo result list for the given IP addresses."""
    return [(2, 1, 6, "", (ip, 0)) for ip in ips]


class TestDNSRebindingProtection:
    """DNS rebinding: allowlisted domain returns private IP — must be blocked."""

    def test_single_private_ip_response_blocked(self):
        """Single DNS response with private IP must be blocked."""
        with patch(
            "socket.getaddrinfo",
            return_value=_make_dns_result(["192.168.1.1"]),
        ):
            with pytest.raises(SSRFValidationError):
                validate_llm_endpoint("https://api.openai.com/v1/chat/completions")

    def test_mixed_public_private_ips_blocked(self):
        """If DNS returns both public and private IPs, the request must still be blocked.

        This is the classic DNS rebinding vector: the attacker includes one
        legitimate IP to pass simple checks, but the actual requests hit the
        private IP on retry.
        """
        with patch(
            "socket.getaddrinfo",
            return_value=_make_dns_result(["8.8.8.8", "10.0.0.1"]),
        ):
            with pytest.raises(SSRFValidationError):
                validate_llm_endpoint("https://api.openai.com/v1/chat/completions")

    def test_all_private_ips_blocked(self):
        """DNS returning only private IPs must be blocked."""
        with patch(
            "socket.getaddrinfo",
            return_value=_make_dns_result(["10.0.0.1", "172.16.5.5"]),
        ):
            with pytest.raises(SSRFValidationError):
                validate_llm_endpoint("https://api.anthropic.com/v1/messages")

    def test_loopback_in_dns_response_blocked(self):
        """127.x.x.x in DNS response must be blocked."""
        with patch(
            "socket.getaddrinfo",
            return_value=_make_dns_result(["127.0.0.1"]),
        ):
            with pytest.raises(SSRFValidationError):
                validate_llm_endpoint("https://api.openai.com/v1/chat/completions")

    def test_link_local_aws_metadata_in_dns_blocked(self):
        """169.254.169.254 (AWS metadata service) in DNS response must be blocked."""
        with patch(
            "socket.getaddrinfo",
            return_value=_make_dns_result(["169.254.169.254"]),
        ):
            with pytest.raises(SSRFValidationError):
                validate_llm_endpoint("https://api.openai.com/v1/chat/completions")

    def test_carrier_nat_ip_in_dns_blocked(self):
        """100.64.0.0/10 (carrier-grade NAT, RFC 6598) in DNS response must be blocked."""
        with patch(
            "socket.getaddrinfo",
            return_value=_make_dns_result(["100.100.0.1"]),
        ):
            with pytest.raises(SSRFValidationError):
                validate_llm_endpoint("https://api.openai.com/v1/chat/completions")

    def test_error_message_does_not_expose_resolved_ip(self):
        """The error message must not reveal the private IP that was resolved."""
        private_ip = "10.42.0.100"
        with patch(
            "socket.getaddrinfo",
            return_value=_make_dns_result([private_ip]),
        ):
            with pytest.raises(SSRFValidationError) as exc_info:
                validate_llm_endpoint("https://api.openai.com/v1/chat/completions")
        error_msg = str(exc_info.value)
        assert private_ip not in error_msg
        assert "not on the approved provider list" not in error_msg
        assert "private or internal" in error_msg


class TestDNSResolutionEdgeCases:
    """Edge cases in DNS resolution handling."""

    def test_dns_timeout_raises_ssrf_error(self):
        """DNS timeout (OSError) must fail closed — raise SSRFValidationError."""
        import socket

        with patch("socket.getaddrinfo", side_effect=OSError("timed out")):
            with pytest.raises(SSRFValidationError) as exc_info:
                validate_llm_endpoint("https://api.openai.com/v1/chat/completions")
        assert "DNS resolution failed" in str(exc_info.value)

    def test_empty_dns_response_passes(self):
        """Empty DNS response (no addresses returned) should not raise — no IPs to check."""
        with patch("socket.getaddrinfo", return_value=[]):
            # No addresses to check means no private IPs found — should pass
            validate_llm_endpoint("https://api.openai.com/v1/chat/completions")

    def test_multiple_public_ips_pass(self):
        """Multiple public IPs all pass the private-IP check."""
        with patch(
            "socket.getaddrinfo",
            return_value=_make_dns_result(["104.18.2.161", "104.18.3.161"]),
        ):
            # Should not raise
            validate_llm_endpoint("https://api.openai.com/v1/chat/completions")

    def test_bedrock_domain_with_private_dns_blocked(self):
        """Allowlisted Bedrock domain resolving to private IP must be blocked."""
        with patch(
            "socket.getaddrinfo",
            return_value=_make_dns_result(["172.31.0.5"]),
        ):
            with pytest.raises(SSRFValidationError):
                validate_llm_endpoint(
                    "https://bedrock-runtime.us-east-1.amazonaws.com/"
                )
