# LLM Provider Configuration — Red Team Critique

**Date**: March 17, 2026
**Status**: Pre-implementation Adversarial Review
**Scope**: Failure modes, attack surfaces, edge cases, migration risks

---

## Preface

This document assumes the architecture in `05-architecture-design.md` is implemented exactly as specified and then asks: "What breaks?" Each scenario is analyzed independently. Severity ratings are P0 (data loss / full outage), P1 (partial outage / security breach), P2 (degraded service), P3 (operational inconvenience).

---

## Scenario 1: `llm_providers` Table Is Empty and `.env` Fallback Is Removed

**Setup**: The platform reaches Phase 3 (env vars decommissioned from `.env`). A misconfiguration wipes the `llm_providers` table, or the DB migration for a new environment is incomplete.

**What happens**:

1. First LLM call → `ProviderService.get_provider_for_tenant()` finds no default in DB
2. Falls back to `get_env_fallback_provider()` → reads `AZURE_PLATFORM_OPENAI_API_KEY` from env
3. Env var is empty (Phase 3) → `get_env_fallback_provider()` returns `None`
4. `ProviderNotConfiguredError` is raised
5. `InstrumentedLLMClient._resolve_library_adapter()` propagates the exception
6. HTTP 500 for every chat request, every intent detection call, every document embedding

**Severity**: P0 — full platform outage.

**Mitigations**:

1. **Never truly remove the env vars from infrastructure in Phase 3.** The env vars should be kept as secrets in the deployment system but not loaded by the application unless `provider_status = 'error'` fires. The `get_env_fallback_provider()` method reads them if present — they serve as a break-glass recovery path, not a migration target for removal.

2. **Health check endpoint must include provider check**: `GET /health` should check whether `ProviderService.get_default_provider()` resolves. If it returns `None`, the health check returns HTTP 503 with reason `"no_provider_configured"`. Kubernetes liveness probes will then restart the pod AND surface the error before traffic hits users.

3. **Prevent table wipe with foreign key awareness**: The DB schema does not have an FK from `llm_providers` to anything that would prevent deletion. Add an `ON DELETE RESTRICT` trigger or application-level guard: if `llm_providers` would become empty, reject the operation unless admin explicitly confirms.

4. **Deployment checklist item**: Any new environment deployment must include provider configuration as a post-deploy step before health check gates pass. Document this in the deployment runbook.

---

## Scenario 2: API Key Rotation — In-Flight Requests Must Complete

**Setup**: Platform Admin rotates the API key at 14:00:00. At 14:00:00.050, 200 in-flight requests are mid-execution using the old key. At 14:00:00.100, the new key is saved to DB and Redis is invalidated.

**What happens**:

1. The 200 in-flight requests have already constructed their `ProviderConfig` with the old (now-revoked) key
2. The Azure OpenAI API may reject mid-call if the key is revoked mid-stream
3. New requests after 14:00:00.100 use the new key correctly
4. The in-flight SSE streams may receive 401 errors mid-stream

**Reality check**: Azure OpenAI key revocation is not instantaneous. Azure typically takes 2-5 minutes to propagate a key revocation across all Azure data center fronts. The gap between "Platform Admin saves new key in DB" and "old key stops working at Azure" is typically 2-5 minutes.

**Severity**: P2 — some in-flight requests may fail; brief spike in errors during rotation window.

**Mitigations**:

1. **The existing retry-on-401 pattern**: The `InstrumentedLLMClient` should handle 401/403 from the provider with a single immediate retry (rebuild `ProviderConfig` from fresh DB read, bypassing cache). This means: first attempt uses old key → 401 → invalidate cache → fetch new key from DB → retry succeeds. The user sees a slight delay but not a failure.

2. **Dual-key activation window**: For Azure OpenAI, there are two keys (Key 1 and Key 2) in the Azure Portal. The standard rotation procedure is:
   - Activate new key (Key 2) in mingai while Key 1 is still working
   - Revoke Key 1 in Azure Portal
   - Result: zero in-flight request failures because Key 2 was active before Key 1 was revoked

   The Platform Admin UI should communicate this two-key rotation pattern in the key rotation workflow.

3. **The Redis TTL argument**: The 300s TTL on `CachedProviderRef` does NOT store the API key. Only the provider_id is cached. The actual key is fetched from DB on every LLM call (the cache skips the "which provider" DB lookup, not the "what is the key" DB lookup). This means key rotation takes effect on the next LLM call after the DB write — no cache drain window for the key itself.

---

## Scenario 3: Platform Admin Enters Wrong Credentials

**Setup**: Platform Admin copies the wrong API key (e.g., a key from a different Azure subscription). Sets `is_default = true` immediately.

**What happens without test-before-save**:

1. Provider saved with wrong key, marked as default
2. All tenant LLM calls start returning 401
3. Platform Admin discovers the issue when users report failures
4. MTTR: 15-30 minutes (detect → diagnose → fix → wait for cache drain)

**What happens with test-before-save enforced**:

1. Platform Admin fills in form, clicks "Test Connection" before save
2. Test fires against all configured slots
3. Slot `chat` returns HTTP 401: `{"error": "Unauthorized — verify AZURE_PLATFORM_OPENAI_API_KEY"}`
4. UI shows red error state: "Chat slot: FAILED (401 Unauthorized)"
5. Admin cannot save until test passes (enforced in UI; not enforced at API level)

**Severity of the problem without mitigation**: P0 if the wrong-key provider is immediately set as default.

**Mitigations**:

1. **Test-before-save is required at the UI layer**: The "Save" button is disabled until the test has been run and returned `overall_status = "pass"`. The test timestamp is stored in `last_tested_at`; the UI checks that `last_tested_at` is within the last 10 minutes before enabling Save.

2. **The API layer does NOT enforce test-before-save**: The `POST /platform/providers` endpoint accepts a provider without requiring a test. This is intentional — the API must not be coupled to the test state. However, when `is_default = true` is set via the API and the provider has never been tested, the response includes a warning: `"warning": "Provider has not been tested. Recommend running POST /platform/providers/{id}/test before marking as default."`

3. **is_default requires active status**: The `PATCH /platform/providers/{id}/set-default` endpoint rejects providers with `provider_status = 'error'`. If the test was run and failed (status = 'error'), the provider cannot be set as default until it passes a test (status = 'active').

4. **The double-default guard**: When changing the default provider, the implementation performs a two-step operation: first verify new provider is `active` + `tested_within_1h`, then atomic swap. The verification step is the last gate before customer traffic is affected.

---

## Scenario 4: Security — Encrypted Key in DB, Threat Model

**Threat model**: What can an attacker do with access to the `llm_providers` table?

**What they get**:

- `encrypted_api_key`: A Fernet token — AES-128-CBC encrypted ciphertext with HMAC-SHA256 integrity check
- `key_last4`: Last 4 characters of the plaintext API key (not useful for reconstruction)
- `endpoint`: The Azure OpenAI endpoint URL (semi-public information)

**What they need to decrypt**:

- `JWT_SECRET_KEY` environment variable — required to derive the Fernet key via PBKDF2HMAC

**Attack scenarios**:

| Attack Vector                         | Feasibility                                   | Impact                                         | Defense                                                  |
| ------------------------------------- | --------------------------------------------- | ---------------------------------------------- | -------------------------------------------------------- |
| Read `encrypted_api_key` from DB dump | High (SQL injection, DB admin access)         | Zero — cannot decrypt without JWT_SECRET_KEY   | Fernet encryption + need for JWT_SECRET_KEY              |
| Brute-force decrypt the Fernet token  | Infeasible — PBKDF2 with 200k iterations      | N/A                                            | 200k PBKDF2 iterations raises cost to ~months per guess  |
| Steal `JWT_SECRET_KEY` from env       | Medium (server access, CI/CD secret exposure) | P0 — all encrypted secrets compromised         | Secrets management (e.g., Vault), env var access control |
| MITM between app and Azure OpenAI     | Low (TLS; Azure uses valid cert)              | P1 — intercept API key in transit              | TLS 1.3; certificate pinning option                      |
| Memory dump of running process        | Low (requires root/OS compromise)             | P1 — plaintext key in `ProviderConfig.api_key` | Minimize key lifetime in memory (construct, call, GC)    |

**Assessment**: The Fernet approach is sufficient for the threat model where the attacker has read access to the database but not the application server. If the attacker has server access (can read `JWT_SECRET_KEY`), they can decrypt stored keys — but they also have full shell access to the production server, which is a far more severe compromise. The encryption protects the DB-in-isolation scenario; it does not protect against full server compromise.

**Is Fernet sufficient?** Yes, for the stated threat model. The alternatives:

- AWS KMS / Azure Key Vault: stronger isolation (key derivation happens in hardware), but adds external service dependency and latency to every LLM call (key fetch per call). Not justified for this use case.
- Per-provider salt: Using `mingai-har-v1` as a fixed salt means all providers use the same derived key. A per-provider salt (e.g., `mingai-providers-{provider_id}`) would make each provider's key independent, so compromising one provider's decryption key doesn't compromise all. **Recommend**: change `_KDF_SALT` to `b"mingai-providers-v1"` for provider keys to achieve domain separation from HAR keys (which use `b"mingai-har-v1"`).

**Recommendation**: Create a `get_provider_fernet()` function in `har/crypto.py` that uses salt `b"mingai-providers-v1"` instead of `b"mingai-har-v1"`. This provides domain separation at zero additional operational cost.

---

## Scenario 5: DB Down When LLM Call Is Made

**Setup**: PostgreSQL is unavailable (network partition, maintenance, crash). The Redis cache may or may not be populated.

**What happens**:

Case A — Redis has a cached `CachedProviderRef` (TTL not expired):

1. Cache hit on provider_id
2. DB query for `encrypted_api_key` **fails** (DB down)
3. `ProviderService` cannot decrypt and build `ProviderConfig`
4. LLM call fails with DB connection error

Case B — Redis cache is cold:

1. Cache miss on provider ref
2. DB query for default provider **fails** (DB down)
3. Falls back to `get_env_fallback_provider()` — reads from env vars
4. If env vars are set: LLM call proceeds using env fallback
5. If env vars not set: LLM call fails

**Severity**: P1 for Case A (DB down + Redis has ref but no key). The Redis cache contains the non-secret provider metadata but NOT the encrypted key. The encrypted key is always fetched from DB at call time. This means DB downtime always prevents LLM calls, even with a warm Redis cache.

**The architectural tension**: The design deliberately avoids caching decrypted keys (security requirement). But this means DB downtime = LLM downtime.

**Mitigations**:

1. **Cache the encrypted key in Redis (encrypted) with very short TTL**: Store `encrypted_api_key` in Redis alongside the other provider metadata, with a 60-second TTL. This allows LLM calls to proceed for up to 60 seconds during a DB blip. The encrypted key in Redis is no less secure than in DB (same Fernet protection). After 60 seconds, the call fails — preventing stale key use after rotation.

   Trade-off: Slightly weakens the "Redis stores no secrets" property. The key is still Fernet-encrypted; Redis access alone is insufficient to compromise it (still needs JWT_SECRET_KEY). Recommendation: Accept this trade-off. A 60-second blast radius for DB downtime is operationally reasonable; a permanent LLM outage during any DB hiccup is not.

2. **PostgreSQL connection pool resilience**: Ensure the SQLAlchemy async engine has an `asyncpg` connection pool with `connect_timeout=2`, `command_timeout=5`, and pool-level retry. Many "DB down" scenarios are actually momentary connection timeouts, not full outages. A retry with exponential backoff at the DB layer absorbs 95% of DB blips transparently.

3. **The env fallback as last resort**: Keep `AZURE_PLATFORM_OPENAI_API_KEY` and `AZURE_PLATFORM_OPENAI_ENDPOINT` in the deployment secrets even after Phase 3, as read-only break-glass vars. The application logs a critical error when it falls back to env, triggering an alert. This is acceptable as a last resort without being the normal path.

---

## Scenario 6: Multi-Instance Deployment — Cache Invalidation

**Setup**: 3 backend pods (pod-1, pod-2, pod-3). Platform Admin updates a provider on pod-1.

**Sequence**:

1. Platform Admin sends `PATCH /platform/providers/{id}` → hits pod-1
2. pod-1 updates DB row
3. pod-1 executes `redis.delete("mingai:platform:provider:{id}")`
4. pod-2 and pod-3 have no in-process cache (all cache is Redis) — they will re-read from Redis on next request

**Is there a race condition?** No. Because:

- There is no per-pod in-memory cache. All pods read from Redis.
- Redis is a single shared store. The DEL from pod-1 is immediately visible to pod-2 and pod-3.
- The next LLM call on pod-2 after the DEL will miss Redis and re-read from DB, getting the updated credentials.

**The only gap**: Pod-2 is mid-call when pod-1 executes the DEL. The mid-call `ProviderConfig` is already in memory on pod-2 with the old key. That specific call completes with the old key. All subsequent calls on pod-2 use the new key. This is identical to Scenario 2 (in-flight key rotation) and is addressed by the retry-on-401 pattern.

**Assessment**: No additional multi-pod invalidation mechanism is needed. Redis DEL is sufficient.

**What WOULD cause a multi-pod problem**: If any code caches a `ProviderConfig` object (which contains the plaintext key) in a module-level or class-level variable (e.g., `_cached_provider = ProviderConfig(...)`). This must be strictly prohibited. `ProviderConfig` is a request-scoped object; it must never be held beyond the duration of one LLM call.

**Code review gate**: Any PR that introduces a module-level, class-level, or `@lru_cache`-decorated variable of type `ProviderConfig` must be rejected. The `frozen=True` dataclass decorator prevents accidental mutation but does not prevent inappropriate caching.

---

## Scenario 7: Provider Outage — Fallback Chain Design

**Setup**: The default Azure OpenAI provider is experiencing 40% error rates on the intent slot.

**What currently happens**: Intent detection fails for 40% of queries → chat responses degrade (no intent routing) → users see generic responses without agent routing.

**What should happen with the fallback chain**:

```
Intent slot call:
  → Try: default_provider.slot_mappings.intent ("agentic-router")
  → 40% fail rate detected (circuit breaker: 3 failures in 10 seconds)
  → Try: default_provider.slot_mappings.intent_fallback ("intent-detection")
  → If intent_fallback is None: fall back to chat slot for intent detection
  → If chat slot also fails: return default intent result ("chat_response") without routing

Provider-level fallback (future scope):
  → Circuit breaker trips on default provider
  → Check: is there a second provider with is_default = false and provider_status = 'active'?
  → Route to backup provider for the affected slot
  → Alert Platform Admin: "Auto-failover activated — intent slot routing to backup provider"
```

**Current implementation gap**: The `intent_fallback` slot exists in the schema but the circuit breaker logic is in `app/core/circuit_breaker.py`. The connection between the circuit breaker and `slot_mappings.intent_fallback` must be explicit in `InstrumentedLLMClient`. Currently, the fallback is env-var-driven.

**Severity**: P2 — degraded service without automatic provider-level failover.

**Minimum mitigation for this feature**: Ensure `intent_fallback` in `slot_mappings` is respected by the intent detection code. The full provider-level auto-failover (routing to a backup `is_default=false` provider) is a follow-on feature after Phase 1 is stable.

**Provider health monitoring as early warning**: Even without auto-failover, the provider health dashboard gives Platform Admin the data to make a manual decision: "Intent slot error rate at 40% for the last 5 minutes. I'm switching the default to the backup provider." Manual failover via UI + Redis propagation in ≤5 minutes is significantly better than the current SSH+restart scenario.

---

## Scenario 8: Migration Risk — Tenants on Env-Backed Library Mode

**Setup**: Production deployment has N tenants all using library mode (model_source = 'library', llm_library_id set or null). The `llm_providers` table is empty. A new deploy activates the `llm_providers` layer code.

**What happens immediately after deploy**:

1. First LLM call → `ProviderService.get_provider_for_tenant()` queries `llm_providers` → empty
2. Falls back to `get_env_fallback_provider()` → reads `AZURE_PLATFORM_OPENAI_API_KEY` from env
3. Builds synthetic `ProviderConfig` from env vars
4. Identical behavior to pre-deploy

**Zero-impact migration**: The env fallback path is designed to be behavior-identical to the current env-reading code in `InstrumentedLLMClient._resolve_library_adapter()`. The only visible difference is a warning log line and a `X-Provider-Source: env-fallback` header on `GET /platform/providers`.

**What could go wrong during migration**:

1. **The new code path has a bug**: The new `ProviderService.get_provider_for_tenant()` code might have an unhandled exception that does not occur in the old direct `os.environ.get()` path. **Mitigation**: The env fallback path must be covered by integration tests that exercise it with the `llm_providers` table empty.

2. **Timing of DB migration**: If the Alembic migration for `llm_providers` table creation runs after the new code is deployed (out-of-order), the first call to `ProviderService` may fail with "table does not exist" rather than gracefully falling back. **Mitigation**: Run DB migrations before code deploy (standard Alembic practice). Alternatively, catch `ProgrammingError` ("relation does not exist") in `get_provider_for_tenant()` and treat it as "empty table" → env fallback.

3. **`AzureOpenAIProvider` constructor change**: The architecture proposes that `AzureOpenAIProvider` receives a pre-built `_client` parameter rather than reading env vars in `__init__`. This is a breaking change to the constructor signature. Any other code that instantiates `AzureOpenAIProvider()` without arguments will break. **Mitigation**: Make `_client` an optional parameter; if not provided, fall back to env-var construction (preserves existing behavior). Deprecate the no-argument constructor in Phase 2.

4. **BYOLLM tenants**: Tenants with `model_source = 'byollm'` use `_resolve_byollm_adapter()`, which does NOT go through `ProviderService`. This path is unchanged by this feature. BYOLLM tenants are unaffected. **Verify**: The `_resolve_adapter()` method checks `model_source == 'byollm'` before calling `_resolve_library_adapter()`. This check must remain at the top of the routing logic.

**Migration risk rating**: P3 (operational inconvenience) assuming correct implementation. P1 if the constructor change is not backward-compatible or if the DB migration ordering is wrong.

---

## Scenario 9: What If Platform Admin Deletes the Only Provider

**Setup**: Only one provider configured (`is_default = true`). Platform Admin calls `DELETE /platform/providers/{id}`.

**Expected behavior**: The delete is blocked at the API layer with HTTP 409:

```json
{
  "detail": "Cannot delete the default provider. Set a new default first."
}
```

**What if this check is bypassed** (e.g., direct DB delete):

1. `llm_providers` table becomes empty
2. Env fallback activates (if env vars present) — service continues
3. Env fallback inactive (if env vars absent) — P0 outage

**Defense**: The UI must not expose a "Delete" button on the only/default provider — disable it with tooltip "Cannot delete default provider." The API-level check is the enforcement gate; the UI is a usability guide.

**Also**: There is no cascading delete from `llm_providers` to `tenant_configs`. If tenant_configs rows reference a now-deleted provider_id, those tenants will have a dangling FK reference. The next call to `get_provider_for_tenant()` will fail to find the referenced provider, fall back to default, and log a warning. This is acceptable degradation behavior. The fix is to add a DB-level FK constraint:

```sql
-- Add to the tenant_configs design (when the provider_id column is added):
-- FOREIGN KEY (provider_id) REFERENCES llm_providers(id) ON DELETE SET NULL
```

With `ON DELETE SET NULL`, deleting a provider automatically clears the reference in tenant_configs, causing those tenants to fall back to the default provider automatically.

---

## Scenario 10: Concurrent Default-Switch Race

**Setup**: Two Platform Admins simultaneously call `PATCH /platform/providers/{id-A}/set-default` and `PATCH /platform/providers/{id-B}/set-default` at the same time.

**Without atomic transaction**:

1. Both reads: no current default
2. Both set their own provider as default
3. Two rows have `is_default = true` — violates business rule

**With the partial unique index** (`CREATE UNIQUE INDEX ... WHERE is_default = true`):

1. Both transactions start concurrently
2. Both execute `UPDATE llm_providers SET is_default = false WHERE is_default = true` (clears existing default)
3. Both execute `UPDATE llm_providers SET is_default = true WHERE id = :id`
4. One transaction commits first (provider A becomes default)
5. The second transaction sees the unique index violation and raises `UniqueViolation`
6. The second transaction is rolled back
7. HTTP 409 is returned to the second caller

**This is correct behavior**: One of the two concurrent requests wins; the other fails cleanly. No data corruption. The losing caller gets a retryable error.

**Assessment**: The partial unique index is the critical correctness mechanism for concurrent default-switch. It must be included in the schema migration.

---

## Summary Risk Register

| Scenario                          | Severity | Status      | Key Mitigation                                                     |
| --------------------------------- | :------: | ----------- | ------------------------------------------------------------------ |
| Empty table, env vars removed     |    P0    | Addressable | Keep env vars as break-glass; health check includes provider check |
| Key rotation in-flight requests   |    P2    | Addressable | Retry-on-401; Azure dual-key rotation procedure                    |
| Wrong credentials set as default  |    P1    | Addressable | Test-before-save required in UI; status='error' blocks set-default |
| DB compromise, key exposed        |    P1    | Acceptable  | Fernet encryption; domain-separated salt                           |
| DB down during LLM call           |    P1    | Addressable | Cache encrypted key with 60s TTL; env fallback as last resort      |
| Multi-pod cache invalidation      |   None   | Resolved    | Redis DEL is sufficient; no in-process cache                       |
| Provider outage, no auto-failover |    P2    | Partial     | Manual failover via UI; intent_fallback slot for circuit breaker   |
| Migration breaking BYOLLM         |    P1    | Addressable | BYOLLM path does not go through ProviderService; verify isolation  |
| Delete only provider              |    P0    | Addressable | API + UI blocks delete of default/only provider                    |
| Concurrent default-switch         |    P3    | Resolved    | Partial unique index enforces single-default at DB level           |

---

**Document Version**: 1.0
**Author**: Analysis Agent
**Note**: Scenarios 5 (DB down) and 7 (provider outage fallback chain) require follow-on design decisions before implementation. All other scenarios are fully addressed by the architecture in `05-architecture-design.md`.
