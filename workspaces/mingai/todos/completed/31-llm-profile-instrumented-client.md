---
id: 31
title: LLM Profile Redesign — Phase B4: Slot-Aware InstrumentedLLMClient
status: pending
priority: critical
phase: B
estimated_days: 1.5
---

# LLM Profile Redesign — Phase B4: Slot-Aware InstrumentedLLMClient

## Context

`InstrumentedLLMClient` is the single point through which all LLM calls in the backend flow. Making it slot-aware is what activates the profile system end-to-end — once this is done, every LLM call automatically uses the slot defined in the tenant's active profile.

The `slot` parameter is added as REQUIRED with no default. This is intentional: forcing all call sites to explicitly name their slot surfaces any ambiguous callers that were implicitly using a single model. The B0 enumeration step (documented here) must be completed first so every call site is identified before any code changes.

The traffic splitting logic (weighted random selection over `chat_traffic_split`) also lives here for the chat slot.

Decrypted API keys must never persist beyond the request. The `finally` block zeroing the key is mandatory.

## Scope

### B0 — Call-site enumeration (must be completed before modifying the client)

Before touching `InstrumentedLLMClient`, run:

```
grep -rn "InstrumentedLLMClient" src/backend/
grep -rn "get_openai_client\|get_intent_openai_client\|get_doc_openai_client" src/backend/
```

Document every call site in a comment block at the top of `profile_resolver.py` under the heading `# CALL SITE INVENTORY (B0)`. This inventory must be committed before any B4 changes begin.

Files to modify (confirmed only after B0 enumeration — the following are expected):

- wherever `InstrumentedLLMClient` is defined in `src/backend/app/core/llm/`
- every call site identified in B0

## Requirements

### SlotName parameter on \_resolve_adapter

Add `slot: SlotName` as the first positional parameter to `_resolve_adapter(self, slot: SlotName)`. No default. Existing callers that don't pass a slot name will fail at import time (intentional — forces every call site to be explicit).

`SlotName = Literal["chat", "intent", "vision", "agent"]` — import from `profile_resolver.py` or a shared types module.

### Resolution logic in \_resolve_adapter

When `resolved_profile.use_legacy_routing` is True:

- Fall back to existing env-var logic (unchanged)
- Log a DEBUG message: "Using legacy LLM routing for tenant {tenant_id}"

When `use_legacy_routing` is False:

- Look up `resolved_profile.slots[slot]`
- If slot is None (not assigned in the profile), raise `SlotNotConfiguredError(tenant_id, slot)`
- Apply traffic splitting for chat slot (see below)
- Decrypt `resolved_slot.api_key_encrypted` → store in local variable `decrypted_key`
- Build adapter using `endpoint_url`, `decrypted_key`, `api_version`, `model_name`, `provider`, merged `params`
- In `finally` block: `decrypted_key = ""` (zero the key)

### Traffic splitting for chat slot

When `resolved_slot.traffic_split` is non-empty (dict of `{library_id: weight}`):

- Total weight = sum of all weights
- Use `random.random() * total_weight` to select a library entry by weight
- Look up that library entry from the resolved profile (pre-loaded by resolver)
- Use the selected entry's credentials instead of the primary chat entry
- Log the selected library_id at DEBUG level for observability

When `traffic_split` is empty: use the primary chat library entry (no splitting).

### SSRF re-validation at call time

Before building the HTTP client for any BYOLLM library entry (`is_byollm=True` on the resolved profile):

- Call `validate_llm_endpoint(resolved_slot.endpoint_url)`
- If it raises `SSRFValidationError`: raise `SlotNotConfiguredError` with a safe message (do not propagate SSRF details to caller)

This is the time-of-use check complementing the time-of-save check in B1.

### Error classes

```python
class SlotNotConfiguredError(Exception):
    def __init__(self, tenant_id: UUID, slot: str):
        ...
```

This raises a 503 to the API caller with message "LLM service not available for this operation". Never expose slot name or tenant details to end users.

### Update all call sites (from B0 inventory)

Each identified call site must be updated to pass an explicit `slot=` argument:

- Chat completion calls: `slot="chat"`
- Intent detection calls: `slot="intent"`
- Vision processing calls: `slot="vision"`
- Agent tool calls: `slot="agent"`

### Scope Boundary: embed() Is NOT Slot-Aware (GAP-07b)

The `embed()` method in `InstrumentedLLMClient` handles document and KB embeddings. These are excluded from `llm_profiles` (the plan explicitly excludes `doc_embedding` and `kb_embedding` slots from the profile system because changing embedding models requires full re-indexing).

**Decision**: `embed()` is NOT made slot-aware in this phase. It continues to use the existing env-var resolution path (`AZURE_OPENAI_EMBEDDING_DEPLOYMENT`, etc.) unchanged. The `slot` parameter does NOT apply to `embed()`.

Document this decision in a comment at the top of `embed()`: `# Embedding slots are platform-managed and excluded from llm_profiles. See plan doc 55 §4.` This ensures future developers don't accidentally bring embeddings into the slot system without understanding the re-indexing consequence.

## Acceptance Criteria

- B0 inventory comment exists in `profile_resolver.py` before any B4 code changes are committed
- `_resolve_adapter()` signature requires `slot: SlotName` with no default
- All call sites from B0 inventory have been updated with explicit slot names
- When `use_legacy_routing=True`: existing env-var behaviour is unchanged
- When `use_legacy_routing=False` and slot is None: `SlotNotConfiguredError` raised (no fallback)
- Decrypted key is zeroed in `finally` block — verified by code inspection
- Traffic splitting selects according to weights (unit testable with seeded random)
- BYOLLM endpoints re-validated at call time via `validate_llm_endpoint`
- No LLM call in the system bypasses `InstrumentedLLMClient` (confirmed by B0 enumeration)

## Dependencies

- 28 (SSRF middleware) — `validate_llm_endpoint` imported here
- 29 (LLMProfileService) — service owns profiles, not client
- 30 (ProfileResolver) — client calls resolver.resolve() to get the active profile
