"""
A2A Card Fetcher — fetches and validates Agent-to-Agent (A2A) card manifests.

An A2A card is a JSON document published by an external agent that describes
its capabilities, endpoints, trust level, and required credentials.

Security requirements:
  - SSRF protection on all outbound requests
  - Response size capped at 512KB
  - No redirect following
  - Schema validation: required fields enforced
  - Domain allowlist: ALLOWED_A2A_DOMAINS env var (comma-separated; empty = any HTTPS)
  - Credential values never logged

Card schema (minimum required fields):
  {
    "name": str,
    "version": str,
    "description": str,
    "a2a_endpoint": str (HTTPS URL),
    "capabilities": list[str],
    "trust_level": int (0-4),
    "authentication": { "type": str }
  }
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

import structlog

from app.core.security.ssrf import SSRFBlockedError, resolve_and_pin_url

logger = structlog.get_logger()

_MAX_CARD_BYTES = 512 * 1024  # 512 KB
_FETCH_TIMEOUT = 15.0

# Required fields in a valid A2A card
_REQUIRED_CARD_FIELDS = {
    "name",
    "version",
    "a2a_endpoint",
    "capabilities",
    "authentication",
}

# Regex for version format (semver or simple N.N.N)
_VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")


def _check_domain_allowlist(url: str) -> None:
    """
    Check the URL against ALLOWED_A2A_DOMAINS env var.

    ALLOWED_A2A_DOMAINS is a comma-separated list of allowed hostnames/domains.
    If empty or not set, any HTTPS domain is allowed.
    """
    allowed_raw = os.environ.get("ALLOWED_A2A_DOMAINS", "").strip()
    if not allowed_raw:
        return  # No restriction

    allowed_domains = [d.strip().lower() for d in allowed_raw.split(",") if d.strip()]
    if not allowed_domains:
        return

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    for allowed in allowed_domains:
        if hostname == allowed or hostname.endswith(f".{allowed}"):
            return

    raise CardFetchError(
        "domain_not_allowed",
        f"A2A card domain '{hostname}' is not in the allowed domains list",
    )


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class A2ACard:
    """Parsed and validated A2A card manifest."""
    name: str
    version: str
    description: str
    a2a_endpoint: str
    capabilities: list[str]
    trust_level: int
    authentication: dict
    transaction_types: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    language_support: list[str] = field(default_factory=list)
    public_key: Optional[str] = None
    raw: dict = field(default_factory=dict)


@dataclass
class CardFetchResult:
    """Result of fetch_and_validate_card()."""
    success: bool
    card: Optional[A2ACard] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    http_status: Optional[int] = None
    latency_ms: int = 0


class CardFetchError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"[{code}] {detail}")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_card_schema(data: dict) -> None:
    """
    Validate the A2A card JSON against required fields and type constraints.

    Raises CardFetchError if validation fails.
    """
    missing = _REQUIRED_CARD_FIELDS - set(data.keys())
    if missing:
        raise CardFetchError(
            "card_schema_invalid",
            f"A2A card missing required fields: {', '.join(sorted(missing))}",
        )

    name = data.get("name", "")
    if not isinstance(name, str) or not name.strip():
        raise CardFetchError("card_schema_invalid", "A2A card 'name' must be a non-empty string")
    if len(name) > 255:
        raise CardFetchError("card_schema_invalid", "A2A card 'name' exceeds 255 characters")

    version = data.get("version", "")
    if not isinstance(version, str) or not version.strip():
        raise CardFetchError("card_schema_invalid", "A2A card 'version' must be a non-empty string")

    a2a_endpoint = data.get("a2a_endpoint", "")
    if not isinstance(a2a_endpoint, str) or not a2a_endpoint.startswith("https://"):
        raise CardFetchError(
            "card_schema_invalid",
            "A2A card 'a2a_endpoint' must be an HTTPS URL",
        )

    capabilities = data.get("capabilities", [])
    if not isinstance(capabilities, list):
        raise CardFetchError("card_schema_invalid", "A2A card 'capabilities' must be a list")

    trust_level = data.get("trust_level", 0)
    if not isinstance(trust_level, int) or trust_level < 0 or trust_level > 4:
        raise CardFetchError(
            "card_schema_invalid",
            "A2A card 'trust_level' must be an integer 0-4",
        )

    authentication = data.get("authentication", {})
    if not isinstance(authentication, dict):
        raise CardFetchError(
            "card_schema_invalid",
            "A2A card 'authentication' must be an object",
        )
    if "type" not in authentication:
        raise CardFetchError(
            "card_schema_invalid",
            "A2A card 'authentication' must have a 'type' field",
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_and_validate_card(url: str) -> CardFetchResult:
    """
    Fetch an A2A card from a URL and validate its schema.

    Steps:
      1. SSRF protection check
      2. Domain allowlist check
      3. HTTP GET with 15s timeout, no redirects, 512KB response cap
      4. JSON parse
      5. Schema validation
      6. Return CardFetchResult

    Args:
        url: URL where the A2A card JSON is published.

    Returns:
        CardFetchResult with success=True and parsed A2ACard if valid.
    """
    import time
    import httpx

    start_ms = int(time.time() * 1000)

    # SSRF protection: resolve-and-pin + https enforcement
    try:
        pinned_url = await resolve_and_pin_url(url, require_https=True)
    except SSRFBlockedError as exc:
        return CardFetchResult(
            success=False,
            error_code=exc.code,
            error_message="A2A card URL is not permitted",
            latency_ms=int(time.time() * 1000) - start_ms,
        )

    try:
        _check_domain_allowlist(url)
    except CardFetchError as exc:
        return CardFetchResult(
            success=False,
            error_code=exc.code,
            error_message=exc.detail,
            latency_ms=int(time.time() * 1000) - start_ms,
        )

    try:
        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT,
            follow_redirects=False,
        ) as client:
            response = await client.get(
                pinned_url,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()

            content_len = len(response.content)
            if content_len > _MAX_CARD_BYTES:
                return CardFetchResult(
                    success=False,
                    error_code="card_too_large",
                    error_message=f"A2A card exceeds {_MAX_CARD_BYTES} byte limit",
                    http_status=response.status_code,
                    latency_ms=int(time.time() * 1000) - start_ms,
                )

            try:
                data = response.json()
            except Exception as exc:
                return CardFetchResult(
                    success=False,
                    error_code="card_parse_error",
                    error_message=f"A2A card is not valid JSON: {str(exc)[:200]}",
                    http_status=response.status_code,
                    latency_ms=int(time.time() * 1000) - start_ms,
                )

    except httpx.HTTPStatusError as exc:
        return CardFetchResult(
            success=False,
            error_code="card_fetch_http_error",
            error_message=f"HTTP {exc.response.status_code} fetching A2A card",
            http_status=exc.response.status_code,
            latency_ms=int(time.time() * 1000) - start_ms,
        )
    except httpx.TimeoutException:
        return CardFetchResult(
            success=False,
            error_code="card_fetch_timeout",
            error_message=f"Timed out fetching A2A card ({_FETCH_TIMEOUT}s)",
            latency_ms=int(time.time() * 1000) - start_ms,
        )
    except CardFetchError as exc:
        return CardFetchResult(
            success=False,
            error_code=exc.code,
            error_message=exc.detail,
            latency_ms=int(time.time() * 1000) - start_ms,
        )
    except Exception as exc:
        return CardFetchResult(
            success=False,
            error_code="card_fetch_failed",
            error_message=str(exc)[:200],
            latency_ms=int(time.time() * 1000) - start_ms,
        )

    try:
        _validate_card_schema(data)
    except CardFetchError as exc:
        return CardFetchResult(
            success=False,
            error_code=exc.code,
            error_message=exc.detail,
            http_status=200,
            latency_ms=int(time.time() * 1000) - start_ms,
        )

    card = A2ACard(
        name=str(data["name"])[:255],
        version=str(data.get("version", "unknown")),
        description=str(data.get("description", ""))[:2000],
        a2a_endpoint=str(data["a2a_endpoint"]),
        capabilities=[str(c)[:100] for c in (data.get("capabilities") or [])],
        trust_level=int(data.get("trust_level", 0)),
        authentication=dict(data.get("authentication", {})),
        transaction_types=[str(t)[:100] for t in (data.get("transaction_types") or [])],
        industries=[str(i)[:100] for i in (data.get("industries") or [])],
        language_support=[str(l)[:20] for l in (data.get("language_support") or [])],
        public_key=str(data["public_key"]) if data.get("public_key") else None,
        raw=data,
    )

    logger.info(
        "a2a_card_fetched",
        card_url=url,
        card_name=card.name,
        trust_level=card.trust_level,
    )

    return CardFetchResult(
        success=True,
        card=card,
        http_status=200,
        latency_ms=int(time.time() * 1000) - start_ms,
    )
