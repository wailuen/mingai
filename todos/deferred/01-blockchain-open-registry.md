---
**File**: `todos/deferred/01-blockchain-open-registry.md`
**Moved to long-term deferred**: 2026-03-17
**Items**: HAR-013 through HAR-017
**Phase**: 2 (Blockchain) + 3 (Open Registry)
**Source**: `todos/completed/06-agent-registry.md`
---

## Why Deferred

These items require external conditions that are not expected to be met in the near term:

- **HAR-013–015**: Require a Hyperledger Fabric deployment and 100+ real completed A2A transactions. Blockchain infrastructure is a significant operational commitment with cost, ops, and compliance overhead disproportionate to current transaction volume.
- **HAR-016–017**: Require Phase 2 complete + 500+ transactions. External developer portal and third-party agent onboarding have no near-term product demand.

These are not gated on engineering capacity — they are gated on product/market signals that do not exist yet.

---

## HAR-013: Hyperledger Fabric deployment

**Status**: LONG-TERM DEFERRED
**Gate condition**: 100+ real transactions in `har_transactions` with status=COMPLETED AND deliberate product decision to add blockchain infrastructure
**Description**: Hyperledger Fabric network deployment for immutable A2A transaction ledger.
**Effort**: ~40h
**Notes**: Do NOT implement speculatively. The existing PostgreSQL `har_transactions` table with Ed25519 signing is sufficient for Phase 1 trust guarantees. Fabric adds immutability and external auditability — only needed when a customer contractually requires it.

---

## HAR-014: Polygon CDK checkpoint layer

**Status**: LONG-TERM DEFERRED
**Gate condition**: HAR-013 complete
**Description**: Polygon CDK checkpoint from Fabric to L2 blockchain for external verifiability. Adds public verifiability of transaction finality.
**Effort**: ~30h
**Depends on**: HAR-013

---

## HAR-015: Tier 3 financial transactions

**Status**: LONG-TERM DEFERRED
**Gate condition**: HAR-013 + HAR-014 complete
**Description**: High-value financial transaction support with blockchain-backed finality. Requires full Phase 2 blockchain stack to be in production.
**Effort**: ~20h
**Depends on**: HAR-013, HAR-014

---

## HAR-016: Developer portal and SDKs

**Status**: LONG-TERM DEFERRED
**Gate condition**: Phase 2 blockchain complete AND 500+ real transactions
**Description**: External developer portal for third-party agent registration. Python + JavaScript SDKs for A2A integration.
**Effort**: ~60h
**Depends on**: HAR-013, HAR-014, HAR-015

---

## HAR-017: External agent onboarding

**Status**: LONG-TERM DEFERRED
**Gate condition**: HAR-016 complete
**Description**: Self-service onboarding for external (non-mingai) agents. Requires developer portal and SDK published.
**Effort**: ~30h
**Depends on**: HAR-016

---

## Pickup Criteria

Resume this file when **all** of the following are true:

1. `SELECT COUNT(*) FROM har_transactions WHERE status = 'COMPLETED'` returns ≥ 100
2. Product leadership explicitly approves blockchain infrastructure budget
3. A paying customer has contractually required immutable audit trail OR external verifiability

Until then: no codegen, no planning, no speculative work.
