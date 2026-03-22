# LLM Profile Redesign — Red Team Findings

**Date**: 2026-03-22
**Source**: Red team review of `55-llm-profile-redesign-analysis.md`, `17-llm-profile-redesign-plan.md`, `25-llm-profile-redesign-flows.md`

---

## Critical Findings (Block Implementation)

### S01 — BYOLLM Credential Storage Underspecified [CRITICAL]

Storing tenant API keys as BYOLLM entries in `llm_library` table alongside platform credentials is a breach risk. The design says "Fernet encryption" but does not specify:

- Separate encryption envelope per tenant (required for isolation)
- NEVER return credentials in GET responses (must be enforced at ORM level)
- Credential rotation flow (tenant cannot update key without deleting + recreating entry)

**Resolution**:

- Column-level encryption with tenant-scoped key material
- Write-only credential fields: accepted on POST/PATCH, never returned in GET
- Add `PATCH /admin/llm-config/byollm-entries/{id}/rotate-key` endpoint
- Integration test: assert GET `/platform/llm-library` and `/admin/llm-config` never include `api_key_encrypted` or plaintext key in response body

### M01 — Migration Auto-Create Ambiguity [CRITICAL]

"Find-or-create Library entries for existing raw model name strings" will create duplicates:

- `gpt-4o` on Azure East US vs Azure West Europe → same string, different deployments
- Typos in existing profile rows (trailing spaces, capitalization)
- Sunset model names (gpt-4-32k) creating deprecated entries

**Resolution**:

- Migration generates a **reconciliation manifest** (YAML) for human review BEFORE applying FKs
- Manifest format: `{ raw_string, matched_library_id, confidence, action: link|create|deprecate }`
- Platform admin reviews and approves manifest, THEN migration applies it
- NO auto-create of Library entries; only auto-link when exact match found

### RT01 — InstrumentedLLMClient Slot Refactor Touches Every Query [CRITICAL]

Adding `slot` parameter to `_resolve_adapter()` requires updating every call site. Missed call sites = silent wrong-model resolution or runtime crash on every user query.

**Resolution**:

1. Make `slot` a **required parameter** with no default (type-checker catches missed call sites)
2. Pre-implementation: `grep` all instantiations of `InstrumentedLLMClient` and LLM completion calls — document exhaustive list in plan
3. Implement behind a feature flag (`LLM_PROFILE_SLOT_ROUTING = false` default)
4. Canary rollout: enable flag for 1 tenant → monitor error rate → expand
5. Startup self-test: verify all 4 slots resolve to valid Library entries on boot

---

## High Findings (Must Address Before Launch)

### R01 — 4-Slot Model Has No Extensibility Mechanism [HIGH]

New slots (reranking, guardrails, summarization, code generation) require schema migrations with no escape valve.

**Resolution**: Add `custom_slots JSONB DEFAULT '{}'` to `llm_profiles` now. Define 4 canonical slots as constants. Allow Enterprise tenants to define additional named slots. Trivial now; painful to retrofit.

### R02 — Per-Agent Override Lifecycle Undefined [HIGH]

- No row limit per tenant
- No CASCADE behavior when agent is deleted
- No invalidation when a referenced Library entry is deprecated

**Resolution**: Add `ON DELETE CASCADE` on `agent_card_id` FK. Set per-tenant limit of 100 overrides. Background job validates all overrides when Library entry status changes.

### R03 — No Profile Version History [HIGH]

Profile changes are immediate and irreversible. No rollback.

**Resolution**: Add `llm_profile_history` table (profile_id, slot_assignments JSONB, changed_by, changed_at). Rollback = copy history row back to profile. 4 columns, trivial.

### S02 — Plan Tier Bypass via Direct API [HIGH]

UI-level gating is not security. A Starter tenant can call `PATCH /admin/llm-config/slots/chat` directly.

**Resolution**: Middleware validates JWT `plan_tier` claim on EVERY mutation endpoint. Integration tests for all 3 tier bypass attempts.

### S03 — Tenant Isolation in Profile Resolution [HIGH]

Cache key must include `tenant_id`. Resolution must validate tenant ownership of every Library entry.

**Resolution**:

- Cache key: `mingai:{tenant_id}:llm_profile:effective` (already correct in plan)
- Add cross-tenant isolation check: resolution validates `owner_tenant_id IS NULL OR owner_tenant_id = requesting_tenant_id`
- Integration test: Tenant A cannot resolve Tenant B's BYOLLM Library entries

### S04 — BYOLLM SSRF Not Mitigated [HIGH]

`deployment_url` is not validated. Tenant can probe internal services and cloud metadata endpoints.

**Resolution** (already noted in flows, must be in plan):

1. Validate against allowlist of public provider domains: `*.openai.azure.com`, `api.openai.com`, `api.anthropic.com`, `generativelanguage.googleapis.com`
2. Deny private IP ranges (10.x, 172.16-31.x, 192.168.x, 169.254.x, localhost)
3. Resolve DNS and validate resolved IP is not private (prevents DNS rebinding)
4. Implement in Phase B before BYOLLM endpoints go live

### M02 — FK Migration on Live System [HIGH]

Dropping legacy string columns while serving requests risks NullPointerException if deployment timing is off.

**Resolution**:

- Dual-read: new code reads FK first, falls back to string column if FK is NULL
- Remove string columns only in a **subsequent release** (one release per phase, not immediate drops)
- Feature flag to revert to string-based resolution in emergency

### RT02 — Race Condition on Profile Update [HIGH]

Soft-delete Library entries only (never hard delete). If FK points to a deleted entry, resolution must fall back gracefully.

**Resolution**:

- Library entries: soft delete only (status = 'deleted')
- Resolution code: null/deleted FK → fall back to platform default for that slot → log WARNING + alert admin
- Add emergency cache flush capability (not waiting for 60s TTL) for urgent model deprecation

### RT03 — Redis Failure Mode [HIGH]

No fallback defined for Redis unavailability on the critical query path.

**Resolution**: Three-tier resolution:

1. Redis (primary, <5ms)
2. Local in-memory LRU cache per worker (fallback, <1ms, 5-minute TTL, max 1000 entries)
3. DB query (last resort, <50ms, never fails-open to no profile)

Add `NEVER fail-open` invariant: if all tiers fail, use hardcoded platform default profile ID from env var.

### UX01 — Professional Tier Slot Visibility [HIGH]

Hiding Vision/Agent slots kills upsell discovery.

**Resolution**: Show all 4 slots on every tier. Locked slots = read-only value + "Enterprise" badge + "Upgrade" link. Never hide.

### B01 — No A/B Model Testing [HIGH]

Enterprise buyers expect gradual rollout for model changes. All-or-nothing switch is unacceptable for production workloads.

**Resolution** (Phase B extension):
Add `traffic_split` field to slot assignments (JSONB):

```json
[
  { "library_entry_id": "uuid-A", "weight": 90 },
  { "library_entry_id": "uuid-B", "weight": 10 }
]
```

Resolution picks by weighted random. Enables gradual migration, A/B testing, instant rollback.

### D01 — Library Entry Deprecation Lifecycle Incomplete [HIGH]

Two lifecycle states needed, not one:

- `deprecated`: stop assigning new, still serving existing (with warning)
- `disabled`: stop serving immediately (emergency — requires migration)

**Resolution**: Three states: `active` → `deprecated` → `disabled`. Deprecation shows affected profile count + bulk migration button. Disable requires all affected profiles to be migrated first.

---

## Medium Findings (Address in Plan, Not Blockers)

| ID   | Finding                         | Resolution                                                                    |
| ---- | ------------------------------- | ----------------------------------------------------------------------------- |
| T01  | No concurrent update test       | Add `test_concurrent_profile_update.py` with optimistic lock assertion        |
| T02  | No tier bypass integration test | Add for all 3 tier × endpoint combinations                                    |
| T03  | No cross-tenant isolation test  | Add `test_byollm_cross_tenant_isolation.py`                                   |
| T04  | No Redis failure test           | Add with Redis mock down → DB fallback verified                               |
| T05  | No migration rollback test      | Add DOWN migration test                                                       |
| T06  | No stale cache test             | Add deprecated-entry-in-cache test                                            |
| T07  | No load test                    | Add for profile resolution: 1000 concurrent, verify <5ms p99                  |
| S05  | No audit trail                  | Add `llm_profile_audit_log` table; every mutation writes to it                |
| UX02 | Empty library bootstrapping     | Add PA-0 flow; seed 3 default entries on platform init                        |
| UX03 | BYOLLM validation feedback      | Structured error messages: 401/404/429/timeout → plain language               |
| UX04 | No "Test This Profile" action   | Add to Platform Admin profile detail panel (Sprint 3)                         |
| R04  | Embedding slot visibility       | Show doc_embedding/kb_embedding as read-only rows in profile UI               |
| B02  | No cost visibility per slot     | Show estimated cost/1K queries on slot change. Delta % on confirmation dialog |
| M03  | Redis flush during migration    | Migration script must DEL all `llm_profile:*` keys before Phase B deploys     |
| M04  | No rollback plan                | Document DOWN migration + feature flag revert for each phase                  |

---

## Summary: Changes Required to Research (55)

1. Add RT01 resolution (required parameter + feature flag + canary)
2. Add three-tier Redis fallback to Section 6 (performance)
3. Add Library entry three-state lifecycle (active/deprecated/disabled) to Section 3
4. Add SSRF validation spec to BYOLLM section
5. Add `custom_slots JSONB` to profile schema
6. Add `llm_profile_history` table
7. Add audit log requirement
8. Upgrade R6 (BYOLLM failure) with fail-fast-not-silent policy confirmed
9. Update plan tier table: show locked (not hidden) slots for Professional

## Summary: Changes Required to Plan (17)

1. Phase A: Add `custom_slots JSONB`, `llm_profile_history` table, SSRF validation middleware
2. Phase B: Add exhaustive call-site enumeration, feature flag, canary plan for RT01
3. Phase B: Add tier enforcement middleware + integration tests
4. Phase B: Add cross-tenant isolation tests
5. Phase B: Add three-tier fallback for Redis failure
6. Phase B: Add `traffic_split` JSONB to slot assignments
7. Phase B: Reconciliation manifest for migration (not auto-create)
8. Phase E: Add audit log table and writes in all mutation paths
9. All phases: Add DOWN migrations + rollback procedures
