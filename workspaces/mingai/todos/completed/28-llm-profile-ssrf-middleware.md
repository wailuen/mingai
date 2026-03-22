---
id: 28
title: LLM Profile Redesign — Phase B1: SSRF Validation Middleware
status: pending
priority: critical
phase: B
estimated_days: 0.5
---

# LLM Profile Redesign — Phase B1: SSRF Validation Middleware

## Context

BYOLLM allows tenant admins to configure arbitrary endpoint URLs for LLM calls. Without validation this is a classic SSRF vector — a tenant could point an endpoint at internal AWS metadata services (169.254.169.254), private subnet hosts, or internal infrastructure. This middleware must be in place before any BYOLLM endpoint goes live and before any BYOLLM library entry can be saved or tested.

This is a security prerequisite, not an optional hardening. All three SSRF attack vectors must be covered: direct private IP, RFC 1918 ranges, and DNS rebinding (where a hostname initially resolves to a public IP but is later changed to point at internal infrastructure).

## Scope

Files to create:

- `src/backend/app/core/security/url_validator.py` — the validator module
- `tests/integration/test_ssrf_domain_allowlist.py` — allowlist enforcement tests
- `tests/integration/test_ssrf_private_ip.py` — RFC 1918 denylist tests
- `tests/integration/test_ssrf_dns_rebinding.py` — DNS rebinding protection tests

## Requirements

### validate_llm_endpoint(url: str) -> None

Raises `SSRFValidationError` (subclass of `ValueError`) with a plain-language message for any rejection.

Step 1 — Domain allowlist check:

```python
ALLOWED_DOMAINS = [
    r".*\.openai\.azure\.com$",
    r"api\.openai\.com$",
    r"api\.anthropic\.com$",
    r"generativelanguage\.googleapis\.com$",
    r"api\.groq\.com$",
]
```

Parse the URL hostname. If no pattern matches, raise `SSRFValidationError("Endpoint domain is not on the approved provider list")`. Never expose the regex patterns in the error message.

Step 2 — RFC 1918 and special-range denylist:

```python
PRIVATE_RANGES = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",   # link-local / AWS metadata
    "127.0.0.0/8",      # loopback
    "::1/128",          # IPv6 loopback
    "fc00::/7",         # IPv6 unique local
]
```

If the hostname is a literal IP address, check it directly. If it falls in any private range, raise `SSRFValidationError("Endpoint URL must not point to a private or internal address")`.

Step 3 — DNS resolution and rebinding check:

Resolve the hostname to IP addresses using `socket.getaddrinfo`. For each resolved IP, check against `PRIVATE_RANGES`. If any resolved IP is private, raise the same error. This covers the DNS rebinding attack: even if the domain passes the allowlist, its resolved IPs must be public.

Use a short timeout for DNS resolution (2 seconds). If resolution fails entirely, raise `SSRFValidationError("Could not verify endpoint address — DNS resolution failed")`.

Note: Full DNS rebinding protection (time-of-use vs time-of-check) requires that the resolved IP is checked again at actual HTTP call time. The validator handles the save-time check. The HTTP client layer (B4 / InstrumentedLLMClient) must also call `validate_llm_endpoint` before any outbound call.

### Error class

```python
class SSRFValidationError(ValueError):
    def __init__(self, message: str, url: str = ""):
        super().__init__(message)
        self.url = url  # stored but never included in user-facing messages
```

### What to import in other modules

`from app.core.security.url_validator import validate_llm_endpoint, SSRFValidationError`

This import path must be stable — it is referenced in B7 (BYOLLM API), B3 (ProfileResolver), and B1 tests.

## Acceptance Criteria

- `validate_llm_endpoint("https://mydeployment.openai.azure.com/...")` passes without error
- `validate_llm_endpoint("http://169.254.169.254/latest/meta-data/")` raises `SSRFValidationError`
- `validate_llm_endpoint("http://10.0.0.1/internal")` raises `SSRFValidationError`
- `validate_llm_endpoint("http://192.168.1.1/api")` raises `SSRFValidationError`
- `validate_llm_endpoint("http://notallowed.example.com/api")` raises `SSRFValidationError`
- A hostname that resolves to a private IP raises `SSRFValidationError` (DNS rebinding case)
- Error messages never include the rejected URL, regex patterns, or internal network topology
- `test_ssrf_domain_allowlist.py`, `test_ssrf_private_ip.py`, `test_ssrf_dns_rebinding.py` all pass

## Retrofit: Existing byollm.py Endpoint

The existing `src/backend/app/modules/admin/byollm.py` has a `PATCH /admin/llm-config/byollm` endpoint that accepts an `endpoint` URL field. It validates provider type but does NOT call `validate_llm_endpoint`. This endpoint must be retrofitted with SSRF validation as part of this todo — not left until B7.

Add to `byollm.py` PATCH handler (before any DB write):

```python
from app.core.security.url_validator import validate_llm_endpoint, SSRFValidationError
...
if body.endpoint:
    try:
        validate_llm_endpoint(body.endpoint)
    except SSRFValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
```

## Dependencies

- 27 (schema migration) — none strictly, but must be done before B7 (BYOLLM API) goes live
