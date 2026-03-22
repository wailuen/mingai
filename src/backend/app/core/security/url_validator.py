"""
SSRF validation for LLM endpoint URLs (TODO-28).

Protects against three attack vectors:
1. Domain allowlist check — only approved provider domains permitted
2. RFC 1918 / special-range denylist — blocks literal private IP addresses
3. DNS rebinding protection — resolves hostname and checks resolved IPs

Usage::

    from app.core.security.url_validator import validate_llm_endpoint, SSRFValidationError

    try:
        validate_llm_endpoint(url)
    except SSRFValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

All three steps run for every call. Error messages never include the URL,
rejected domain, regex patterns, or any internal network topology details.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from typing import Optional
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Domain allowlist (regex patterns)
# ---------------------------------------------------------------------------

_ALLOWED_DOMAIN_PATTERNS = [
    re.compile(r".*\.openai\.azure\.com$"),
    re.compile(r"^api\.openai\.com$"),
    re.compile(r"^api\.anthropic\.com$"),
    re.compile(r"^generativelanguage\.googleapis\.com$"),
    re.compile(r"^api\.groq\.com$"),
    # AWS Bedrock Runtime endpoints
    re.compile(r"^bedrock-runtime\.[a-z0-9-]+\.amazonaws\.com$"),
    # AWS Bedrock Agent Runtime endpoints
    re.compile(r"^bedrock-agent-runtime\.[a-z0-9-]+\.amazonaws\.com$"),
]

# ---------------------------------------------------------------------------
# Private / restricted IP ranges
# ---------------------------------------------------------------------------

_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / AWS metadata service
    ipaddress.ip_network("127.0.0.0/8"),       # loopback
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
    ipaddress.ip_network("100.64.0.0/10"),     # Carrier-grade NAT (RFC 6598)
    ipaddress.ip_network("0.0.0.0/8"),          # "This network"
]

# DNS resolution timeout (seconds)
_DNS_TIMEOUT_SECONDS = 2


class SSRFValidationError(ValueError):
    """Raised when an LLM endpoint URL fails SSRF validation.

    The ``url`` attribute stores the original URL for internal logging
    but is NEVER included in user-facing error messages to avoid leaking
    internal network topology or allowlist structure.
    """

    def __init__(self, message: str, url: str = "") -> None:
        super().__init__(message)
        self.url = url  # stored internally — never exposed to callers


def _is_private_ip(addr_str: str) -> bool:
    """Return True if the address falls inside any restricted IP range."""
    try:
        addr = ipaddress.ip_address(addr_str)
    except ValueError:
        return False
    return any(addr in network for network in _PRIVATE_RANGES)


def validate_llm_endpoint(url: str) -> None:
    """
    Validate that an LLM endpoint URL is safe to call.

    Raises SSRFValidationError for any of:
    - Missing or malformed hostname
    - Domain not in approved provider list
    - Hostname is a literal private IP address
    - Hostname resolves (DNS) to any private IP address

    Error messages are deliberately vague — they do not expose the URL,
    domain, regex patterns, or network topology details.

    Args:
        url: The fully-qualified endpoint URL to validate.

    Raises:
        SSRFValidationError: If the URL fails any SSRF check.
    """
    # -----------------------------------------------------------------------
    # Step 0 — parse and sanity check
    # -----------------------------------------------------------------------
    try:
        parsed = urlparse(url)
    except Exception:
        raise SSRFValidationError("Endpoint URL could not be parsed", url=url)

    hostname = parsed.hostname
    if not hostname:
        raise SSRFValidationError(
            "Endpoint URL must include a valid hostname",
            url=url,
        )

    # -----------------------------------------------------------------------
    # Step 1 — Domain allowlist
    # -----------------------------------------------------------------------
    if not any(p.match(hostname) for p in _ALLOWED_DOMAIN_PATTERNS):
        logger.warning(
            "ssrf_domain_not_allowlisted",
            hostname=hostname,
        )
        raise SSRFValidationError(
            "Endpoint domain is not on the approved provider list",
            url=url,
        )

    # -----------------------------------------------------------------------
    # Step 2 — RFC 1918 / literal IP denylist
    # -----------------------------------------------------------------------
    # If the hostname is already a literal IP address, check it directly.
    try:
        ipaddress.ip_address(hostname)
        # It IS a literal IP
        if _is_private_ip(hostname):
            logger.warning(
                "ssrf_literal_private_ip_blocked",
                hostname=hostname,
            )
            raise SSRFValidationError(
                "Endpoint URL must not point to a private or internal address",
                url=url,
            )
    except ValueError:
        # Not a literal IP — continue to DNS step
        pass

    # -----------------------------------------------------------------------
    # Step 3 — DNS resolution and rebinding check
    # -----------------------------------------------------------------------
    original_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(_DNS_TIMEOUT_SECONDS)
        try:
            addr_infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            raise SSRFValidationError(
                "Could not verify endpoint address — DNS resolution failed",
                url=url,
            )
        except OSError:
            raise SSRFValidationError(
                "Could not verify endpoint address — DNS resolution failed",
                url=url,
            )
    finally:
        socket.setdefaulttimeout(original_timeout)

    for addr_info in addr_infos:
        resolved_ip = addr_info[4][0]
        if _is_private_ip(resolved_ip):
            logger.warning(
                "ssrf_resolved_ip_private",
                hostname=hostname,
                resolved_ip=resolved_ip,
            )
            raise SSRFValidationError(
                "Endpoint URL must not point to a private or internal address",
                url=url,
            )
