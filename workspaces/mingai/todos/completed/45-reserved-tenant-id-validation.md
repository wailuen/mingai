---
id: TODO-45
title: Reserved tenant ID validation at tenant creation
status: pending
priority: high
phase: A3
dependencies: [TODO-41]
---

## Goal

Prevent the platform vault namespace from being hijacked by rejecting tenant IDs that collide with the `platform/` vault path prefix. Add input validation to the tenant creation endpoint that blocks the reserved IDs: `platform`, `system`, `__platform__`, and any ID starting with `__`.

## Context

The platform credential vault uses vault path `platform/templates/{template_id}/{key}`. If a tenant were created with `tenant_id = "platform"`, its agent credentials (`platform/agents/{agent_id}/{key}`) would be stored under the same vault prefix as platform credentials, creating a namespace collision that could allow tenant agents to exfiltrate platform credentials.

This is risk C-07 (P0) from the gap analysis. The fix is a simple validation rule at tenant creation time — no schema changes required.

Reference: `workspaces/mingai/01-analysis/19-platform-credential-vault/01-gap-and-risk-analysis.md` — C-07.

## Implementation

### Locate the tenant creation endpoint

Find the tenant creation handler in `app/modules/platform/routes.py` or wherever tenant POST is handled. Identify the point where `tenant_id` (or equivalent slug/identifier) is accepted from the request body.

### Add validation function

New function (add to `app/core/validators.py` if that file exists, otherwise add inline to the tenant creation module):

```python
import re

_RESERVED_TENANT_IDS = frozenset({"platform", "system", "__platform__"})
_DOUBLE_UNDERSCORE_PREFIX = re.compile(r"^__")


def validate_tenant_id(tenant_id: str) -> None:
    """Raise ValueError if tenant_id is reserved.

    Reserved IDs:
      - 'platform', 'system', '__platform__' (exact match, case-insensitive)
      - Any ID starting with '__' (double underscore)

    These IDs would collide with the platform credential vault namespace.
    """
    lower = tenant_id.lower()
    if lower in _RESERVED_TENANT_IDS:
        raise ValueError(
            f"Tenant ID '{tenant_id}' is reserved and cannot be used."
        )
    if _DOUBLE_UNDERSCORE_PREFIX.match(tenant_id):
        raise ValueError(
            f"Tenant IDs starting with '__' are reserved: '{tenant_id}'."
        )
```

### Wire into tenant creation

In the tenant creation route handler, call `validate_tenant_id(tenant_id)` before any database write. On `ValueError`, return HTTP 422 with a clear message: `"Tenant ID is reserved: [reason]"`.

The validation should be case-insensitive for the exact-match list (`PLATFORM`, `Platform`, etc. are all rejected) but the `__` prefix check is case-sensitive (double underscore prefix is already a reserved convention).

### Validate in Pydantic schema if applicable

If the tenant creation request uses a Pydantic model, add the validator there as a `@field_validator`. This provides early rejection before the handler is called.

## Acceptance Criteria

- [ ] `POST /platform/tenants` with `tenant_id = "platform"` returns 422
- [ ] `POST /platform/tenants` with `tenant_id = "PLATFORM"` returns 422 (case-insensitive)
- [ ] `POST /platform/tenants` with `tenant_id = "system"` returns 422
- [ ] `POST /platform/tenants` with `tenant_id = "__platform__"` returns 422
- [ ] `POST /platform/tenants` with `tenant_id = "__anything"` returns 422
- [ ] `POST /platform/tenants` with a normal tenant ID (e.g., `"acme-corp"`) succeeds
- [ ] Error response includes a human-readable message explaining why the ID is reserved
- [ ] `validate_tenant_id` is a pure function with no side effects (unit testable without DB)
- [ ] Validation runs before any database write is attempted
- [ ] Existing tenants with normal IDs are unaffected (no migration needed)
