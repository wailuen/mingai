---
id: TODO-47
title: Deployment flow fix — remove 422 rejection, add credential health check pre-deployment
status: pending
priority: high
phase: B2
dependencies: [TODO-42, TODO-43]
---

## Goal

Remove the hard 422 rejection that currently blocks all deployment of `platform_credentials` templates in `app/modules/agents/routes.py`. Replace it with a credential health pre-check: deployment proceeds only if all required credentials are stored; if any are missing, return 422 with a descriptive message listing the missing key names.

## Context

`app/modules/agents/routes.py` lines 340-345 (approximate) unconditionally reject deployment with:
```
"auth_mode 'platform_credentials' is not yet supported"
```

This was a placeholder. The vault infrastructure (TODO-41 through TODO-44) and the credential health endpoint (TODO-43) together make it possible to replace this stub with a real pre-flight check.

Reference: `workspaces/mingai/02-plans/18-platform-credential-vault-plan.md` — Sprint B2.

## Implementation

### Locate the rejection block

In `app/modules/agents/routes.py`, find the deployment handler (the route that creates or updates an agent deployment — likely `POST /agents` or `POST /tenants/{id}/agents`). Find the block that checks `auth_mode == 'platform_credentials'` and returns 422 unconditionally.

### Replace with health pre-check

```python
if template.auth_mode == "platform_credentials":
    required_keys = template.required_credentials or []
    if required_keys:
        health = await credential_manager.get_platform_credential_health(
            template_id=template.id,
            required_keys=required_keys,
        )
        missing = [
            key for key, status in health["keys"].items()
            if status in ("missing", "revoked")
        ]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot deploy: missing platform credentials: {missing}",
            )
    # If required_keys is empty, auth_mode='platform_credentials' with no credentials
    # is treated as "not_required" and deployment proceeds.
```

The error message format `"Cannot deploy: missing platform credentials: ['KEY_A', 'KEY_B']"` is consumed by the integration test `test_deployment_missing_credentials` (TODO-55) and the frontend error display.

### No functional changes to the deployment flow itself

This todo only changes the pre-flight check. The deployment logic after the check passes — agent instance creation, tenant assignment, etc. — is unchanged.

### Handle template with no required_credentials

If `template.required_credentials` is `None` or empty list, skip the health check and proceed with deployment. The `auth_mode = 'platform_credentials'` setting alone does not block deployment.

### Handle missing template gracefully

If the template record cannot be fetched (should not happen during deployment but defensive programming), return 404 as the existing handler does.

### Fix module-level `test_credentials()` for platform_credentials auth_mode

The module-level `test_credentials()` function at `credential_manager.py` (approximately lines 538-576) is currently a stub that returns `CredentialTestResult(passed=True)` for `platform_credentials` templates without verifying vault state. Replace the stub with:

```python
if template_record.get("auth_mode") == "platform_credentials":
    required_keys = template_record.get("required_credentials") or []
    if required_keys:
        health = credential_manager.get_platform_credential_health(
            template_id=template_record["id"],
            required_keys=required_keys,
        )
        missing = [
            key for key, status in health["keys"].items()
            if status in ("missing", "revoked")
        ]
        if missing:
            return CredentialTestResult(
                passed=False,
                error_message=f"Missing platform credentials: {missing}",
            )
    return CredentialTestResult(passed=True, latency_ms=0)
```

Note: the function signature must accept `template_record: dict` (not just `template_id`) to inspect `auth_mode`.

## Acceptance Criteria

- [ ] The unconditional 422 rejection for `auth_mode = 'platform_credentials'` is removed
- [ ] Deployment with all required credentials stored succeeds (HTTP 2xx)
- [ ] Deployment with one or more missing/revoked credentials returns 422 with `"Cannot deploy: missing platform credentials: [key_names]"`
- [ ] Deployment with `required_credentials = []` or `null` proceeds without credential check
- [ ] Existing deployments for `auth_mode = 'none'` and `auth_mode = 'tenant_credentials'` are unaffected
- [ ] The credential health check uses `get_platform_credential_health()` from CredentialManager (not a direct DB query)
- [ ] The error message includes the specific key names that are missing
- [ ] Module-level `test_credentials()` returns `passed=False` with missing key names when `auth_mode='platform_credentials'` and any credentials are absent
- [ ] Module-level `test_credentials()` accepts `template_record: dict` to inspect `auth_mode`
- [ ] Integration test `test_deployment_missing_credentials` (TODO-55) passes
