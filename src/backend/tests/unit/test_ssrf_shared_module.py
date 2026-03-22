"""
Unit tests for the shared SSRF module (app.core.security.ssrf).

Tests:
  - resolve_and_pin_url blocks private IPs (all RFC 1918, loopback, link-local,
    CGNAT, Azure Wire Server, ::1, fe80::)
  - resolve_and_pin_url returns a pinned URL (hostname replaced by IP)
  - SSRFBlockedError is raised on DNS failure
  - require_https=True blocks http:// URLs
  - resolve_and_pin_url_sync mirrors async behaviour

All DNS calls are mocked — these are Tier 1 unit tests.
"""
from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from app.core.security.ssrf import (
    SSRFBlockedError,
    resolve_and_pin_url,
    resolve_and_pin_url_sync,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _dns_result(ip: str) -> list:
    """Build a mock getaddrinfo return value for a single IP."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


def _dns_result_v6(ip: str) -> list:
    """Build a mock getaddrinfo return value for a single IPv6 IP."""
    return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0))]


# ---------------------------------------------------------------------------
# Block private IPv4 ranges
# ---------------------------------------------------------------------------

class TestBlockedPrivateIPv4:
    """All RFC 1918 + special ranges must be blocked."""

    @pytest.mark.parametrize("private_ip", [
        # RFC 1918 Class A
        "10.0.0.1",
        "10.255.255.255",
        # RFC 1918 Class B
        "172.16.0.1",
        "172.31.255.255",
        # RFC 1918 Class C
        "192.168.0.1",
        "192.168.100.100",
        # Loopback
        "127.0.0.1",
        "127.0.0.2",
        # Link-local / cloud metadata
        "169.254.169.254",
        "169.254.0.1",
        # CGNAT (RFC 6598)
        "100.64.0.1",
        "100.127.255.255",
        # Azure Wire Server
        "168.63.129.16",
    ])
    @pytest.mark.asyncio
    async def test_async_blocks_private_ip(self, private_ip):
        """resolve_and_pin_url must raise SSRFBlockedError for every blocked range."""
        with patch("socket.getaddrinfo", return_value=_dns_result(private_ip)):
            with pytest.raises(SSRFBlockedError) as exc_info:
                await resolve_and_pin_url(f"https://example.com/path")
            assert exc_info.value.code in (
                "blocked_resolved_ip", "blocked_ip_literal", "blocked_hostname"
            )

    @pytest.mark.parametrize("private_ip", [
        "10.0.0.1",
        "172.16.0.1",
        "192.168.0.1",
        "127.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "168.63.129.16",
    ])
    def test_sync_blocks_private_ip(self, private_ip):
        """resolve_and_pin_url_sync must also block all private ranges."""
        with patch("socket.getaddrinfo", return_value=_dns_result(private_ip)):
            with pytest.raises(SSRFBlockedError):
                resolve_and_pin_url_sync(f"https://example.com/path")


# ---------------------------------------------------------------------------
# Block private IPv6 ranges
# ---------------------------------------------------------------------------

class TestBlockedPrivateIPv6:
    """IPv6 loopback, link-local and ULA must all be blocked."""

    @pytest.mark.parametrize("ipv6_ip", [
        "::1",          # loopback
        "fe80::1",      # link-local (fe80::/10)
        "fd00::1",      # ULA (fc00::/7)
        "fc00::1",      # ULA start
    ])
    @pytest.mark.asyncio
    async def test_async_blocks_ipv6_private(self, ipv6_ip):
        with patch("socket.getaddrinfo", return_value=_dns_result_v6(ipv6_ip)):
            with pytest.raises(SSRFBlockedError):
                await resolve_and_pin_url("https://example.com/path")

    @pytest.mark.parametrize("ipv6_ip", [
        "::1",
        "fe80::1",
        "fd00::1",
    ])
    def test_sync_blocks_ipv6_private(self, ipv6_ip):
        with patch("socket.getaddrinfo", return_value=_dns_result_v6(ipv6_ip)):
            with pytest.raises(SSRFBlockedError):
                resolve_and_pin_url_sync("https://example.com/path")


# ---------------------------------------------------------------------------
# Literal private IP in URL hostname
# ---------------------------------------------------------------------------

class TestLiteralPrivateIPInURL:
    """Private IPs used directly as hostname must be blocked without DNS."""

    @pytest.mark.parametrize("url", [
        "https://10.0.0.1/api",
        "https://192.168.1.1/api",
        "https://127.0.0.1/api",
        "https://169.254.169.254/latest/",
        "https://100.64.0.1/api",
        "https://168.63.129.16/api",
    ])
    @pytest.mark.asyncio
    async def test_async_literal_private_ip_blocked(self, url):
        """Literal IP addresses in URL hostname must be rejected without DNS call."""
        # No DNS mock needed — literal IPs are rejected before getaddrinfo
        with pytest.raises(SSRFBlockedError):
            await resolve_and_pin_url(url)

    @pytest.mark.parametrize("url", [
        "https://10.0.0.1/api",
        "https://192.168.1.1/api",
        "https://127.0.0.1/api",
    ])
    def test_sync_literal_private_ip_blocked(self, url):
        with pytest.raises(SSRFBlockedError):
            resolve_and_pin_url_sync(url)


# ---------------------------------------------------------------------------
# Pinned URL — hostname replaced by resolved IP
# ---------------------------------------------------------------------------

class TestPinnedURLOutput:
    """resolve_and_pin_url must return URL with hostname replaced by resolved IP."""

    @pytest.mark.asyncio
    async def test_hostname_replaced_by_public_ip(self):
        public_ip = "93.184.216.34"
        with patch("socket.getaddrinfo", return_value=_dns_result(public_ip)):
            pinned = await resolve_and_pin_url("https://example.com/path?q=1")
        assert public_ip in pinned
        assert "example.com" not in pinned
        assert "/path" in pinned
        assert "q=1" in pinned

    @pytest.mark.asyncio
    async def test_port_preserved_in_pinned_url(self):
        public_ip = "93.184.216.34"
        with patch("socket.getaddrinfo", return_value=_dns_result(public_ip)):
            pinned = await resolve_and_pin_url("https://example.com:8443/api")
        assert public_ip in pinned
        assert "8443" in pinned

    @pytest.mark.asyncio
    async def test_ipv6_pinned_url_uses_bracket_notation(self):
        public_ipv6 = "2606:2800:220:1:248:1893:25c8:1946"
        with patch(
            "socket.getaddrinfo",
            return_value=_dns_result_v6(public_ipv6),
        ):
            pinned = await resolve_and_pin_url("https://example.com/path")
        assert f"[{public_ipv6}]" in pinned

    def test_sync_hostname_replaced_by_public_ip(self):
        public_ip = "93.184.216.34"
        with patch("socket.getaddrinfo", return_value=_dns_result(public_ip)):
            pinned = resolve_and_pin_url_sync("https://example.com/path")
        assert public_ip in pinned
        assert "example.com" not in pinned

    @pytest.mark.asyncio
    async def test_literal_public_ip_returned_as_is(self):
        """A literal public IP in the URL must pass through without DNS call."""
        public_ip = "93.184.216.34"
        original_url = f"https://{public_ip}/path"
        # No mock needed — literal public IPs bypass DNS
        pinned = await resolve_and_pin_url(original_url)
        assert pinned == original_url


# ---------------------------------------------------------------------------
# DNS failure
# ---------------------------------------------------------------------------

class TestDNSFailure:
    """DNS failures must raise SSRFBlockedError (fail closed)."""

    @pytest.mark.asyncio
    async def test_async_dns_gaierror_raises_ssrf_blocked(self):
        with patch(
            "socket.getaddrinfo",
            side_effect=socket.gaierror("Name or service not known"),
        ):
            with pytest.raises(SSRFBlockedError) as exc_info:
                await resolve_and_pin_url("https://nonexistent.example.com/api")
        assert exc_info.value.code == "dns_resolution_failed"

    def test_sync_dns_gaierror_raises_ssrf_blocked(self):
        with patch(
            "socket.getaddrinfo",
            side_effect=socket.gaierror("Name or service not known"),
        ):
            with pytest.raises(SSRFBlockedError) as exc_info:
                resolve_and_pin_url_sync("https://nonexistent.example.com/api")
        assert exc_info.value.code == "dns_resolution_failed"

    @pytest.mark.asyncio
    async def test_error_detail_not_exposed_in_message(self):
        """SSRFBlockedError message must be generic; details only in .detail attribute."""
        with patch(
            "socket.getaddrinfo",
            side_effect=socket.gaierror("DNS timeout for secret.internal"),
        ):
            with pytest.raises(SSRFBlockedError) as exc_info:
                await resolve_and_pin_url("https://example.com/api")
        # The str() of the error (returned to callers) must not expose internals
        error_str = str(exc_info.value)
        assert "secret.internal" not in error_str
        assert "DNS timeout" not in error_str
        # But .detail has the full info for server-side logging
        assert "secret.internal" in exc_info.value.detail


# ---------------------------------------------------------------------------
# require_https
# ---------------------------------------------------------------------------

class TestRequireHttps:
    """require_https=True must block http:// URLs."""

    @pytest.mark.asyncio
    async def test_async_http_blocked_when_require_https(self):
        public_ip = "93.184.216.34"
        with patch("socket.getaddrinfo", return_value=_dns_result(public_ip)):
            with pytest.raises(SSRFBlockedError) as exc_info:
                await resolve_and_pin_url("http://example.com/api", require_https=True)
        assert exc_info.value.code == "https_required"

    @pytest.mark.asyncio
    async def test_async_https_passes_when_require_https(self):
        public_ip = "93.184.216.34"
        with patch("socket.getaddrinfo", return_value=_dns_result(public_ip)):
            pinned = await resolve_and_pin_url("https://example.com/api", require_https=True)
        assert public_ip in pinned

    def test_sync_http_blocked_when_require_https(self):
        public_ip = "93.184.216.34"
        with patch("socket.getaddrinfo", return_value=_dns_result(public_ip)):
            with pytest.raises(SSRFBlockedError) as exc_info:
                resolve_and_pin_url_sync("http://example.com/api", require_https=True)
        assert exc_info.value.code == "https_required"

    @pytest.mark.asyncio
    async def test_async_http_allowed_without_require_https(self):
        """http:// must pass when require_https is not set (default False)."""
        public_ip = "93.184.216.34"
        with patch("socket.getaddrinfo", return_value=_dns_result(public_ip)):
            pinned = await resolve_and_pin_url("http://example.com/api")
        assert public_ip in pinned


# ---------------------------------------------------------------------------
# Known internal hostnames
# ---------------------------------------------------------------------------

class TestKnownInternalHostnames:
    """Localhost and cloud metadata hostnames must be blocked before DNS."""

    @pytest.mark.parametrize("url", [
        "https://localhost/api",
        "https://metadata.google.internal/computeMetadata/v1/",
        "http://169.254.169.254/latest/meta-data/",
    ])
    @pytest.mark.asyncio
    async def test_blocked_hostname_raises_ssrf_blocked(self, url):
        with pytest.raises(SSRFBlockedError) as exc_info:
            await resolve_and_pin_url(url)
        assert exc_info.value.code in ("blocked_hostname", "blocked_ip_literal")

    @pytest.mark.parametrize("url", [
        "https://localhost/api",
        "https://metadata.google.internal/",
    ])
    def test_sync_blocked_hostname(self, url):
        with pytest.raises(SSRFBlockedError):
            resolve_and_pin_url_sync(url)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Malformed URLs and edge cases."""

    @pytest.mark.asyncio
    async def test_url_with_no_hostname_raises(self):
        with pytest.raises(SSRFBlockedError) as exc_info:
            await resolve_and_pin_url("not-a-url")
        assert exc_info.value.code == "no_hostname"

    def test_sync_url_with_no_hostname_raises(self):
        with pytest.raises(SSRFBlockedError):
            resolve_and_pin_url_sync("")

    @pytest.mark.asyncio
    async def test_mixed_dns_one_private_blocks_all(self):
        """If DNS returns one public + one private IP, the whole request must be blocked."""
        mixed_result = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0)),
        ]
        with patch("socket.getaddrinfo", return_value=mixed_result):
            with pytest.raises(SSRFBlockedError):
                await resolve_and_pin_url("https://example.com/api")

    @pytest.mark.asyncio
    async def test_ssrf_blocked_error_is_value_error_subclass(self):
        """SSRFBlockedError must inherit from ValueError for backward compatibility."""
        err = SSRFBlockedError("test_code", "test detail")
        assert isinstance(err, ValueError)
        assert err.code == "test_code"
        assert err.detail == "test detail"
