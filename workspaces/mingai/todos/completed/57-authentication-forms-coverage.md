---
id: TODO-57
title: Platform credential vault — full authentication forms coverage
status: pending
priority: high
phase: A3-B1
dependencies: [TODO-42, TODO-43, TODO-46]
---

## Goal

Ensure the platform credential vault covers ALL authentication patterns used by tools and MCP servers in the platform. Based on the aihub2 MCP server reference (`mcp_client.py`, `mcp_servers/pitchbook/router.py`, `tools/executor.py`).

## Authentication Patterns in Use

### 1. Bearer Token (MCPClient default)

```
Authorization: Bearer {value}
```

MCPClient handles this when credentials dict contains `api_key`, `token`, or `bearer_token` key.
**Used by**: Generic OAuth APIs, many REST services.

### 2. Custom Header — Raw Value (MCPClient header_map + HttpWrapperExecutor)

```
X-Api-Key: {value}
X-API-Key: {value}
```

MCPClient: `header_map: {"X-Api-Key": "PITCHBOOK_API_KEY"}` → raw value in header.
HttpWrapperExecutor: `credential_schema[].header_name` with raw value.
**Used by**: PitchBook API (`X-API-Key`), many enterprise APIs.

### 3. Custom Header — Prefixed Value

```
Authorization: ApiKey {value}
Authorization: Token {value}
```

MCPClient: `header_map: {"Authorization": "ApiKey CREDENTIAL_KEY"}`.
**Used by**: Jira, some REST APIs.

### 4. Query Parameter

```
GET /endpoint?api_key={value}
```

**Used by**: Some legacy APIs that do not support header-based auth.

### 5. Basic Auth (username:password)

```
Authorization: Basic base64({username}:{password})
```

Store as compound `"username:password"` value with `injection_config: {"type": "basic_auth"}`.
**Used by**: Many enterprise APIs with HTTP Basic Auth.

## Changes Required

### 1. `platform_credential_metadata.injection_config` JSONB

This column is added by TODO-41 and consumed here. The supported schema:

```json
{"type": "bearer"}
{"type": "header", "header_name": "X-Api-Key"}
{"type": "header", "header_name": "Authorization", "header_format": "ApiKey {value}"}
{"type": "query_param", "param_name": "api_key"}
{"type": "basic_auth"}
```

Default when `injection_config` is omitted: `{"type": "bearer"}`.

### 2. POST /credentials request body

`injection_config` is optional. Validation: `type` must be one of `bearer`, `header`, `query_param`, `basic_auth` — 400 on unknown type. This is already covered by TODO-43.

Example for PitchBook:

```json
{
  "key": "PITCHBOOK_API_KEY",
  "value": "sk-live-...",
  "description": "PitchBook Data API",
  "allowed_domains": ["api.pitchbook.com"],
  "injection_config": {
    "type": "header",
    "header_name": "X-Api-Key"
  }
}
```

### 3. Orchestrator `_build_auth_config()` function

The full implementation is specified in TODO-46. Summary:

```python
def _build_auth_config(resolved_credentials: dict[str, dict]) -> tuple[dict, dict]:
    """Build (auth_config, query_params) from resolved platform credentials.

    resolved_credentials: {key: {"value": str, "injection_config": dict}}

    Returns:
        auth_config: dict with optional "credentials" and "header_map" keys for MCPClient
        query_params: dict of URL query parameters to inject
    """
    credentials = {}
    header_map = {}
    query_params = {}

    for key, cred_data in resolved_credentials.items():
        value = cred_data["value"]
        config = cred_data.get("injection_config", {})
        injection_type = config.get("type", "bearer")

        if injection_type == "bearer":
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

### 4. HTTP tool injection precedence

For `HttpWrapperExecutor`, when `auth_mode = 'platform_credentials'`, use `injection_config` from the resolved credential directly. Do not fall back to `credential_schema[].header_name` for platform credentials — `injection_config` is the authoritative source.

Precedence:
1. If `auth_mode = 'platform_credentials'` → use `injection_config` from resolved credential
2. If `auth_mode = 'tenant_credentials'` → use `credential_schema[].header_name` (existing behaviour)

### 5. Frontend CredentialsTab injection_config UI

In the `CredentialInlineForm` component (Template Studio Panel Credentials tab, TODO-50), add an injection method selector below the password input.

**Visual treatment** (Obsidian Intelligence design system):

```
Injection method
  ○ Bearer token      →  Authorization: Bearer <value>
  ○ Custom header     →  [Header Name: ______] <value>
  ○ Prefixed header   →  [Header Name: ______] [Prefix: ______] <value>
  ○ Query parameter   →  ?[Param Name: ______]=<value>
  ○ Basic Auth        →  Authorization: Basic <base64(value)>
```

Design tokens:
- Container: `bg-elevated`, border `border-faint`, `border-radius: var(--r-sm)`, padding 12px
- Label "Injection method": 11px / 500 / uppercase / `text-faint`, letter-spacing 0.06em
- Radio labels: 13px / 400 / `text-muted` (Plus Jakarta Sans)
- Conditional text inputs (header_name, prefix, param_name): DM Mono, 13px, `bg-elevated`, border `border`
- Active radio label: `text-primary`
- Conditional inputs revealed with `transition: opacity 220ms ease` (do not use `display:none` — use opacity + pointer-events)

### 6. Tests

All injection-form tests are part of test case 14 in TODO-55. Cross-reference: `test_injection_config_bearer`, `test_injection_config_custom_header`, `test_injection_config_basic_auth`, `test_injection_config_query_param`, `test_scrubber_covers_all_injection_types`.

The `CredentialScrubber` must redact values regardless of which injection type was used. The scrubber operates on plain string values — injection type is irrelevant to scrubbing, but this must be explicitly verified.

## Acceptance Criteria

- [ ] `injection_config` column exists in `platform_credential_metadata` with correct default (TODO-41)
- [ ] POST /credentials accepts `injection_config` and validates `type` — unknown type → 400 (TODO-43)
- [ ] GET /credentials returns `injection_config` per credential (TODO-43)
- [ ] Orchestrator `_build_auth_config()` handles all five types: bearer, header, header+prefix, query_param, basic_auth
- [ ] Bearer type → `auth_config["credentials"]["bearer_token"] = value`
- [ ] Custom header type → `auth_config["header_map"][header_name] = value` (or `format.replace("{value}", value)`)
- [ ] Basic auth type → `auth_config["header_map"]["Authorization"] = "Basic {base64(value)}"`
- [ ] Query param type → returned as separate `query_params` dict
- [ ] HttpWrapperExecutor uses `injection_config` for platform credentials, `credential_schema` for tenant credentials
- [ ] CredentialInlineForm shows injection method selector with all five options
- [ ] Injection method selector uses correct Obsidian Intelligence tokens (bg-elevated, DM Mono for inputs)
- [ ] Conditional inputs (header_name, prefix, param_name) appear only when relevant type is selected
- [ ] All injection types pass through `CredentialScrubber` before any logging
- [ ] `test_allowed_domains_blocks_attacker_endpoint` passes for all injection types (SSRF check is injection-type-agnostic)
- [ ] Integration test for each injection type (test case 14 in TODO-55)
