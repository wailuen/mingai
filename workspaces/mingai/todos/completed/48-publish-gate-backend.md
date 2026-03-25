---
id: TODO-48
title: Publish gate — block template publish when required credentials are missing
status: pending
priority: high
phase: B3
dependencies: [TODO-41, TODO-42, TODO-43]
---

## Goal

Add a credential completeness check to the template publish flow in `app/modules/platform/routes.py`. When a platform admin attempts to publish a template with `auth_mode = 'platform_credentials'` and one or more required credentials are not stored, reject the publish with 422 and list the missing key names.

## Context

Without this gate, a template can be published (made visible to tenant admins for deployment) before its credentials are configured. Tenants would deploy the agent and receive 503 errors on every query. The gate ensures the platform admin configures credentials before tenants are affected.

Reference: `workspaces/mingai/02-plans/18-platform-credential-vault-plan.md` — Sprint B3. FR-06 from requirements.

## Implementation

### Locate the publish endpoint

In `app/modules/platform/routes.py`, find the endpoint that changes a template's status to `"published"`. This is likely a `PATCH /platform/templates/{template_id}` or `POST /platform/templates/{template_id}/publish` endpoint.

### Add pre-publish credential check

In the publish handler, after validating the status transition but before committing the status change to the database:

```python
async def _check_publish_credentials(
    template_id: str,
    template: AgentTemplate,
    credential_manager: CredentialManager,
) -> None:
    """Raise HTTPException 422 if required credentials are not configured."""
    if template.auth_mode != "platform_credentials":
        return  # Only applies to platform_credentials templates

    required_keys = template.required_credentials or []
    if not required_keys:
        return  # No credentials required — publish proceeds

    health = await credential_manager.get_platform_credential_health(
        template_id=template_id,
        required_keys=required_keys,
    )

    missing = [
        key for key, status in health["keys"].items()
        if status in ("missing", "revoked")
    ]

    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot publish: missing platform credentials: {missing}",
        )
```

Call `await _check_publish_credentials(...)` immediately before the DB write that sets `status = 'published'`.

### Error message format

The error message `"Cannot publish: missing platform credentials: ['KEY_A']"` must match exactly what the frontend publish gate warning UI (TODO-53) parses to display the count and names.

### Templates with no required_credentials

If `required_credentials` is `None` or `[]`, the check must pass silently. The `auth_mode = 'platform_credentials'` setting alone does not block publish.

### Templates with auth_mode != 'platform_credentials'

No check is performed. `auth_mode = 'none'` and `auth_mode = 'tenant_credentials'` templates are unaffected.

### No change to other publish validations

Existing validations (name required, description required, etc.) must continue to run. The credential check is additive.

## Acceptance Criteria

- [ ] Publishing a `platform_credentials` template with all required credentials stored succeeds
- [ ] Publishing a `platform_credentials` template with any missing/revoked credential returns 422
- [ ] The 422 body lists the specific missing key names: `"Cannot publish: missing platform credentials: ['KEY_A', 'KEY_B']"`
- [ ] Publishing a `platform_credentials` template with empty `required_credentials` succeeds
- [ ] Publishing a `none` or `tenant_credentials` template is not affected by this change
- [ ] The credential check uses `get_platform_credential_health()`, not a direct DB query
- [ ] Integration test `test_publish_gate_missing_credentials` (TODO-55) passes
- [ ] The check runs before the status update is committed to the database
