"""Shared SSRF protection utilities (INFRA-SSRF).

All outbound HTTP helpers that accept user-supplied URLs MUST go through
resolve_and_pin_url() instead of resolving DNS independently. This eliminates
the TOCTOU window in which DNS rebinding can redirect a post-validation request
to a private address.

Usage:
    from app.core.security.ssrf import resolve_and_pin_url, SSRFBlockedError

    pinned_url = await resolve_and_pin_url(user_supplied_url)
    async with httpx.AsyncClient() as client:
        resp = await client.get(pinned_url, ...)

For synchronous contexts:
    from app.core.security.ssrf import resolve_and_pin_url_sync, SSRFBlockedError

    pinned_url = resolve_and_pin_url_sync(user_supplied_url)
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import urllib.parse
from typing import Optional

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Canonical SSRF blocklist — import from here, never copy-paste per-file
# ---------------------------------------------------------------------------

SSRF_BLOCKED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("10.0.0.0/8"),         # RFC1918 private (Class A)
    ipaddress.ip_network("172.16.0.0/12"),       # RFC1918 private (Class B)
    ipaddress.ip_network("192.168.0.0/16"),      # RFC1918 private (Class C)
    ipaddress.ip_network("127.0.0.0/8"),         # Loopback (IPv4)
    ipaddress.ip_network("::1/128"),             # Loopback (IPv6)
    ipaddress.ip_network("169.254.0.0/16"),      # Link-local / cloud metadata (AWS IMDSv1, GCP, Azure)
    ipaddress.ip_network("fe80::/10"),           # IPv6 link-local
    ipaddress.ip_network("fc00::/7"),            # IPv6 ULA (unique local)
    ipaddress.ip_network("100.64.0.0/10"),       # CGNAT shared address space (RFC 6598)
    ipaddress.ip_network("168.63.129.16/32"),    # Azure Wire Server (platform services)
    ipaddress.ip_network("0.0.0.0/8"),           # "This network" (reserved)
    ipaddress.ip_network("240.0.0.0/4"),         # Reserved (class E)
]

# Well-known internal hostnames — rejected before DNS resolution
_BLOCKED_HOSTNAMES: frozenset[str] = frozenset({
    "localhost",
    "metadata.google.internal",
    "169.254.169.254",
    "fd00:ec2::254",
})


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class SSRFBlockedError(ValueError):
    """Raised when a URL is blocked by SSRF protection.

    ``code`` is a machine-readable error code.
    ``detail`` carries internal diagnostic information — logged server-side
    but NEVER returned to callers (avoids leaking network topology).
    """

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"Request blocked for security reasons ({code})")


# ---------------------------------------------------------------------------
# Shared IP check helper
# ---------------------------------------------------------------------------

def _is_blocked_ip(ip_str: str) -> bool:
    """Return True if the IP address falls within any blocked network range."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in SSRF_BLOCKED_NETWORKS)
    except ValueError:
        return True  # Fail closed on unparseable IP


def _parse_hostname_and_port(url: str) -> tuple[str, Optional[int], urllib.parse.ParseResult]:
    """Parse URL and extract hostname + port. Raise SSRFBlockedError on failure."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        raise SSRFBlockedError("malformed_url", f"URL parse failed: {exc}") from exc

    hostname = parsed.hostname
    if not hostname:
        raise SSRFBlockedError("no_hostname", f"URL has no hostname: {url!r}")

    return hostname, parsed.port, parsed


def _build_pinned_url(parsed: urllib.parse.ParseResult, pinned_ip: str, port: Optional[int]) -> str:
    """Substitute the hostname in the parsed URL with a resolved IP, return pinned URL."""
    ip_addr = ipaddress.ip_address(pinned_ip)
    if ip_addr.version == 6:
        netloc = f"[{pinned_ip}]"
    else:
        netloc = pinned_ip
    if port:
        netloc = f"{netloc}:{port}"
    return urllib.parse.urlunparse(parsed._replace(netloc=netloc))


def _validate_and_pin_sync(url: str, require_https: bool) -> str:
    """Core synchronous resolve-and-pin logic shared by both the sync and async variants."""
    hostname, port, parsed = _parse_hostname_and_port(url)

    if require_https and parsed.scheme != "https":
        raise SSRFBlockedError(
            "https_required",
            f"URL scheme {parsed.scheme!r} rejected — only https is permitted",
        )

    # Reject well-known internal hostnames without DNS resolution
    if hostname.lower() in _BLOCKED_HOSTNAMES or hostname.startswith("169.254."):
        raise SSRFBlockedError(
            "blocked_hostname",
            f"Hostname {hostname!r} is a known internal endpoint",
        )

    # Reject explicit IP literals in blocked ranges immediately (no DNS required)
    try:
        literal_addr = ipaddress.ip_address(hostname)
        if _is_blocked_ip(str(literal_addr)):
            raise SSRFBlockedError(
                "blocked_ip_literal",
                f"Hostname {hostname!r} is a blocked IP literal",
            )
        # Already an IP literal and it is public — no rebinding possible, return as-is
        return url
    except ValueError:
        pass  # Not an IP literal — fall through to DNS resolution
    except SSRFBlockedError:
        raise

    # Single DNS resolution — validate ALL returned IPs, then pin to first
    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        logger.warning("ssrf_dns_resolution_failed", hostname=hostname, error=str(exc))
        raise SSRFBlockedError(
            "dns_resolution_failed",
            f"DNS resolution failed for hostname {hostname!r}: {exc}",
        ) from exc

    if not resolved:
        raise SSRFBlockedError(
            "dns_no_records",
            f"DNS returned no records for hostname {hostname!r}",
        )

    for _fam, _typ, _proto, _canon, sockaddr in resolved:
        ip_str = sockaddr[0]
        if _is_blocked_ip(ip_str):
            logger.warning(
                "ssrf_private_range_blocked",
                hostname=hostname,
                resolved_ip=ip_str,
            )
            raise SSRFBlockedError(
                "blocked_resolved_ip",
                f"Hostname {hostname!r} resolves to blocked IP {ip_str!r}",
            )

    # Pin to the first validated IP — httpx uses this IP directly (no re-resolution)
    pinned_ip = resolved[0][4][0]
    return _build_pinned_url(parsed, pinned_ip, port)


# ---------------------------------------------------------------------------
# Public API — async version
# ---------------------------------------------------------------------------

async def resolve_and_pin_url(url: str, *, require_https: bool = False) -> str:
    """Validate and DNS-pin a user-supplied URL in a single DNS pass.

    Eliminates the TOCTOU window between SSRF validation and the actual HTTP
    request. httpx would re-resolve DNS independently; an attacker can serve a
    safe IP at validation time then flip the DNS record to a private IP for the
    actual request (DNS rebinding, CWE-918).

    This function resolves once, validates ALL returned IPs against the blocklist,
    and returns the URL with the hostname substituted by the first resolved IP.
    The caller MUST use the returned pinned_url for the HTTP request — no further
    DNS lookup occurs.

    Args:
        url: User-supplied URL to validate and pin.
        require_https: If True, raise SSRFBlockedError for non-https URLs.

    Returns:
        URL with hostname replaced by the resolved IP address.

    Raises:
        SSRFBlockedError: On any blocked IP, DNS failure, or scheme mismatch.
            Details are logged server-side; the error message is generic.
    """
    # DNS resolution via run_in_executor to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _validate_and_pin_sync, url, require_https)


# ---------------------------------------------------------------------------
# Public API — synchronous version
# ---------------------------------------------------------------------------

def resolve_and_pin_url_sync(url: str, *, require_https: bool = False) -> str:
    """Synchronous version of resolve_and_pin_url().

    Use this in synchronous contexts (e.g., FastAPI path operations that cannot
    be made async, or Pydantic validators). For async route handlers, prefer
    resolve_and_pin_url() to avoid blocking the event loop during DNS resolution.

    Args:
        url: User-supplied URL to validate and pin.
        require_https: If True, raise SSRFBlockedError for non-https URLs.

    Returns:
        URL with hostname replaced by the resolved IP address.

    Raises:
        SSRFBlockedError: On any blocked IP, DNS failure, or scheme mismatch.
    """
    return _validate_and_pin_sync(url, require_https)
