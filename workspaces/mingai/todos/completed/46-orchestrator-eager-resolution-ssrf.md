---
id: TODO-46
title: Orchestrator eager resolution + SSRF allowed_domains validation
status: pending
priority: high
phase: B1
dependencies: [TODO-42, TODO-44]
---

## Goal

Modify `app/modules/chat/orchestrator.py` to eagerly resolve platform credentials at the start of every orchestration for `platform_credentials` templates, pass a `CredentialScrubber` through the tool execution context, and validate each tool's endpoint URL against the credential's `allowed_domains` before injecting the credential value.

## Context

Currently, no credential resolution happens in the orchestrator. Any agent deployed with `auth_mode = 'platform_credentials'` would execute tool calls without credentials, silently producing auth failures or using no credentials at all.

Four P0 risks are addressed here:
- C-01: CredentialScrubber prevents values leaking through tool error messages
- C-02: `allowed_domains` check prevents SSRF via credential injection to attacker-controlled endpoints
- C-04: Eager resolution (before first tool call) ensures missing credentials fail fast rather than mid-stream

Reference: `workspaces/mingai/01-analysis/19-platform-credential-vault/02-requirements-and-adr.md` — Security Requirements section.

## Implementation

### Eager resolution at orchestration start

In the orchestrator's main entry point (the method that begins a new orchestration session for a given agent + tenant), add the following logic near the top, before any tool execution:

```python
# resolved_credentials: {key: {"value": str, "injection_config": dict}}
resolved_credentials: dict[str, dict] = {}
scrubber: CredentialScrubber | None = None

if template.auth_mode == "platform_credentials":
    required_keys = template.required_credentials or []
    if required_keys:
        try:
            resolved_credentials = await credential_manager.resolve_platform_credentials(
                template_id=template.id,
                required_keys=required_keys,
                tenant_id=tenant_id,
                request_id=request_id,
            )
        except MissingPlatformCredentialError as exc:
            logger.warning(
                "platform_credentials.missing",
                template_id=template.id,
                missing_keys=exc.missing_keys,
                tenant_id=tenant_id,
            )
            raise HTTPException(
                status_code=503,
                detail="Agent temporarily unavailable — contact your administrator.",
            )
        except VaultUnavailableError:
            raise HTTPException(
                status_code=503,
                detail="Agent temporarily unavailable — contact your administrator.",
            )
        # Extract plain values for the scrubber — injection_config is not a secret
        scrubber = CredentialScrubber(
            {k: v["value"] for k, v in resolved_credentials.items()}
        )
```

The resolved credentials are stored in a request-scoped local variable, NOT in a class attribute or module-level cache. They must not persist beyond the current request.

### Build auth_config from resolved credentials

The resolved credentials dict now has the form `{key: {"value": str, "injection_config": dict}}`. Use the following builder to construct the auth arguments expected by `MCPClient.call_tool()` and `HttpWrapperExecutor`:

```python
def _build_auth_config(resolved_credentials: dict[str, dict]) -> tuple[dict, dict]:
    """
    Build (auth_config, query_params) for MCPClient.call_tool() from resolved platform credentials.

    resolved_credentials format: {key: {"value": str, "injection_config": dict}}

    Supports:
      - bearer: Authorization: Bearer {value}
      - header: Custom header injection (e.g., X-Api-Key, Authorization: ApiKey {value})
      - query_param: URL query parameter injection
      - basic_auth: Authorization: Basic base64({value})
    """
    credentials = {}  # raw values for MCPClient default bearer handling
    header_map = {}   # custom headers for MCPClient header_map pattern
    query_params = {} # query parameter injection

    for key, cred_data in resolved_credentials.items():
        value = cred_data["value"]
        config = cred_data.get("injection_config", {})
        injection_type = config.get("type", "header")

        if injection_type == "bearer":
            # MCPClient recognizes "bearer_token" key → Authorization: Bearer {value}
            credentials["bearer_token"] = value
        elif injection_type == "header":
            header_name = config.get("header_name", "Authorization")
            header_format = config.get("header_format", "{value}")
            header_map[header_name] = header_format.replace("{value}", value)
        elif injection_type == "query_param":
            param_name = config.get("param_name", key.lower())
            query_params[param_name] = value
        elif injection_type == "basic_auth":
            import base64
            encoded = base64.b64encode(value.encode()).decode()
            header_map["Authorization"] = f"Basic {encoded}"

    auth_config = {}
    if credentials:
        auth_config["credentials"] = credentials
    if header_map:
        auth_config["header_map"] = header_map

    return auth_config, query_params
```

For `HttpWrapperExecutor`, use `injection_config.header_name` + `injection_config.header_format` from the resolved credential's `injection_config` to build headers directly, bypassing the `credential_schema` header_name when `auth_mode = 'platform_credentials'`.

### Pass scrubber + credentials to tool executor

When calling the tool executor (or building the tool context), pass `resolved_credentials` and `scrubber`. The tool executor uses these to:
1. Inject credential values into HTTP headers / API key fields for matching tools
2. Scrub all error messages before returning them to the caller

In the tool execution layer (wherever tool results, errors, and LLM context injections are assembled), apply:

```python
if scrubber:
    error_message = scrubber.scrub(error_message)
    tool_output = scrubber.scrub(tool_output)
```

This must be applied to:
- Raw HTTP error bodies from third-party tool calls
- Any exception message that might propagate to the LLM context
- Log entries that include tool output (use structlog bind, do NOT log raw tool output if scrubber is active)

### SSRF allowed_domains validation

Before injecting a credential into a tool call, validate the tool's endpoint URL against the credential's `allowed_domains`:

```python
def _validate_endpoint_for_credential(
    endpoint_url: str,
    credential_key: str,
    allowed_domains: list[str],
    template_id: str,
    tenant_id: str,
    request_id: str,
) -> None:
    """Block credential injection if endpoint domain is not in allowed_domains.
    Writes a 'blocked' audit record and raises CredentialInjectionBlockedError."""
    from urllib.parse import urlparse
    parsed = urlparse(endpoint_url)
    hostname = parsed.hostname or ""

    # Exact match or subdomain match
    for allowed in allowed_domains:
        if hostname == allowed or hostname.endswith("." + allowed):
            return

    # Write audit record: action='blocked'
    _write_audit(
        action="blocked",
        template_id=template_id,
        key=credential_key,
        tenant_id=tenant_id,
        request_id=request_id,
        metadata={"endpoint_url": endpoint_url, "reason": "domain_not_in_allowed_list"},
    )
    raise CredentialInjectionBlockedError(
        f"Credential '{credential_key}' cannot be injected into '{endpoint_url}': "
        f"domain not in allowed_domains for template '{template_id}'."
    )
```

Add `CredentialInjectionBlockedError` to the exception classes (can live in `credential_manager.py` or the exceptions module).

When `CredentialInjectionBlockedError` is raised, the orchestrator should return a 400 or 422 to the tenant (not 503) because this is a template configuration problem, not a transient outage.

### Audit tenant context propagation

The `resolve_platform_credentials` call must receive `tenant_id` and `request_id` so that audit records include the tenant that triggered the resolution. Extract `tenant_id` from the active session/request context. Extract `request_id` from the HTTP request headers or generate one if absent (standard correlation ID pattern).

### No cross-request caching

The `resolved_credentials` dict is local to the orchestration call. It must not be stored in any instance variable, Redis key, or module-level dict. Each request resolves credentials fresh.

## Acceptance Criteria

- [ ] For `auth_mode = 'platform_credentials'` templates, `resolve_platform_credentials` is called before the first tool invocation
- [ ] Missing credential raises 503 with message `"Agent temporarily unavailable — contact your administrator."` (value not disclosed)
- [ ] Vault unavailable raises 503 with the same message
- [ ] Resolved credentials are not cached across requests (no instance-level or module-level storage)
- [ ] `CredentialScrubber` is instantiated with resolved credentials and applied to tool errors and outputs
- [ ] Tool call to a domain not in `allowed_domains` is blocked and writes `action='blocked'` audit record with `metadata: {"endpoint_url": str}`
- [ ] `action='resolve'` audit records include `tenant_id` and `request_id`
- [ ] For `auth_mode = 'none'` or `'tenant_credentials'`, no platform credential resolution occurs
- [ ] For `platform_credentials` template with empty `required_credentials`, no resolution is attempted and orchestration proceeds
- [ ] No credential value appears in any structlog output (scrubber applied before logging)
