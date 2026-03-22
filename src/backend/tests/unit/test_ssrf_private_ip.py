"""
Unit tests for SSRF RFC 1918 / literal private IP denylist (TODO-28).

Tests that validate_llm_endpoint() raises SSRFValidationError when the
hostname is a literal private, loopback, or link-local IP address, even
if the domain allowlist check would otherwise pass.
"""
from unittest.mock import patch

import pytest

from app.core.security.url_validator import SSRFValidationError, validate_llm_endpoint


class TestLiteralPrivateIPsBlocked:
    """Literal RFC 1918 and special-range IPs must be rejected before DNS."""

    @pytest.mark.parametrize(
        "url",
        [
            # RFC 1918 — Class A
            "https://10.0.0.1/v1/chat",
            "https://10.255.255.255/v1/chat",
            # RFC 1918 — Class B
            "https://172.16.0.1/v1/chat",
            "https://172.31.255.255/v1/chat",
            # RFC 1918 — Class C
            "https://192.168.0.1/v1/chat",
            "https://192.168.100.100/v1/chat",
            # Loopback
            "https://127.0.0.1/v1/chat",
            "https://127.0.0.2/v1/chat",
            # Link-local / AWS metadata service
            "https://169.254.169.254/latest/meta-data/",
            "https://169.254.0.1/v1/chat",
            # Carrier-grade NAT (RFC 6598)
            "https://100.64.0.1/v1/chat",
            "https://100.127.255.255/v1/chat",
        ],
    )
    def test_literal_private_ip_rejected(self, url):
        """Literal private IPs must never reach the DNS step — blocked by allowlist."""
        # These IPs don't match any domain pattern, so they fail the allowlist check.
        # Regardless of which step catches them, the result must be SSRFValidationError.
        with pytest.raises(SSRFValidationError):
            validate_llm_endpoint(url)

    def test_aws_metadata_endpoint_rejected(self):
        """The AWS instance metadata endpoint (169.254.169.254) must be blocked."""
        url = "https://169.254.169.254/latest/meta-data/iam/security-credentials/"
        with pytest.raises(SSRFValidationError):
            validate_llm_endpoint(url)

    def test_error_does_not_expose_ip(self):
        """Error message must not reveal the rejected IP address."""
        url = "https://192.168.1.100/v1/chat"
        with pytest.raises(SSRFValidationError) as exc_info:
            validate_llm_endpoint(url)
        error_msg = str(exc_info.value)
        assert "192.168.1.100" not in error_msg


class TestPrivateIPDeniedAtDNSStep:
    """DNS-resolved private IPs must be blocked even for allowlisted domains."""

    @pytest.mark.parametrize(
        "private_ip",
        [
            "10.0.0.1",
            "172.16.0.1",
            "192.168.0.1",
            "127.0.0.1",
            "169.254.169.254",
            "100.64.0.1",
        ],
    )
    def test_allowlisted_domain_resolving_to_private_ip_rejected(self, private_ip):
        """An allowlisted domain that resolves to a private IP must be blocked (DNS rebinding)."""
        url = "https://api.openai.com/v1/chat/completions"

        def mock_dns_private(hostname, *args, **kwargs):
            return [(2, 1, 6, "", (private_ip, 0))]

        with patch("socket.getaddrinfo", side_effect=mock_dns_private):
            with pytest.raises(SSRFValidationError) as exc_info:
                validate_llm_endpoint(url)
        error_msg = str(exc_info.value)
        # Error must not reveal which IP was resolved
        assert private_ip not in error_msg

    def test_dns_resolution_failure_raises_ssrf_error(self):
        """If DNS resolution fails, validation must fail closed (raise SSRFValidationError)."""
        import socket

        url = "https://api.openai.com/v1/chat/completions"

        def mock_dns_fail(hostname, *args, **kwargs):
            raise socket.gaierror("Name or service not known")

        with patch("socket.getaddrinfo", side_effect=mock_dns_fail):
            with pytest.raises(SSRFValidationError) as exc_info:
                validate_llm_endpoint(url)
        assert "DNS resolution failed" in str(exc_info.value)


class TestIPv6PrivateRangesBlocked:
    """IPv6 private ranges must be blocked in url_validator.py (not only in the older helper)."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://[::1]/v1/chat",           # IPv6 loopback
            "https://[fe80::1]/v1/chat",       # IPv6 link-local (newly added fe80::/10)
            "https://[fd00::1]/v1/chat",       # IPv6 ULA (fc00::/7)
        ],
    )
    def test_ipv6_literal_private_rejected(self, url):
        """IPv6 literal private addresses must be rejected before DNS."""
        with pytest.raises(SSRFValidationError):
            validate_llm_endpoint(url)

    @pytest.mark.parametrize(
        "ipv6_addr",
        [
            "::1",             # loopback
            "fe80::1",         # link-local (fe80::/10)
            "fd12:3456::1",    # ULA (fc00::/7)
        ],
    )
    def test_allowlisted_domain_resolving_to_ipv6_private_rejected(self, ipv6_addr):
        """An allowlisted domain resolving to a private IPv6 address must be blocked."""
        import socket
        url = "https://api.openai.com/v1/chat/completions"

        def mock_dns(hostname, *args, **kwargs):
            # AF_INET6 = 10, return IPv6 result
            return [(socket.AF_INET6, 1, 6, "", (ipv6_addr, 0, 0, 0))]

        with patch("socket.getaddrinfo", side_effect=mock_dns):
            with pytest.raises(SSRFValidationError) as exc_info:
                validate_llm_endpoint(url)
        # Error must not reveal the resolved address
        assert ipv6_addr not in str(exc_info.value)

    def test_ipv6_link_local_error_does_not_expose_address(self):
        """fe80:: address in error message would aid network topology discovery."""
        url = "https://[fe80::dead:beef]/v1/chat"
        with pytest.raises(SSRFValidationError) as exc_info:
            validate_llm_endpoint(url)
        assert "fe80" not in str(exc_info.value)
        assert "dead" not in str(exc_info.value)


class TestPublicIPsAllowed:
    """Public IPs (when returned by DNS for allowlisted domains) must pass."""

    @pytest.mark.parametrize(
        "public_ip",
        [
            "8.8.8.8",
            "1.1.1.1",
            "208.67.222.222",
            "13.107.42.14",  # Azure OpenAI
        ],
    )
    def test_allowlisted_domain_resolving_to_public_ip_passes(self, public_ip):
        """An allowlisted domain resolving to a public IP must pass all checks."""
        url = "https://api.openai.com/v1/chat/completions"

        def mock_dns_public(hostname, *args, **kwargs):
            return [(2, 1, 6, "", (public_ip, 0))]

        with patch("socket.getaddrinfo", side_effect=mock_dns_public):
            # Should not raise
            validate_llm_endpoint(url)
