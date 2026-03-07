# Discussion: Agentic Enterprise Architecture

**Date**: 2026-03-06
**Status**: PARKED — active debate, NOT product documentation
**Do not promote to product docs without further discussion**

---

## Context

Debate on the core philosophical architecture of mingai's agentic enterprise vision. Two pillars:

1. **Internal**: Enable employees to operate without touching complicated systems of record (via agent abstraction)
2. **External**: Enable customers, suppliers, partners to conduct business in record time (agent handles learned routine work — both queries and actions)

---

## Agreed Architecture Model

Systems of record (SAP, Salesforce, Workday, etc.) remain. A2A agents wrap each SOR and expose their capabilities to mingai's orchestration layer. Authorization for actions is embedded in the A2A agent via mingai's authentication mechanism.

```
External Party / Internal User
        ↓ (authenticated intent)
   mingai Orchestrator  ← trust posture varies by context
        ↓ (A2A protocol)
  [SAP Agent]  [Salesforce Agent]  [Workday Agent]
      ↓               ↓                  ↓
    SAP          Salesforce           Workday
```

Key insight: **Authorization embedded in the agent, not just delegated from the user.** The agent IS the policy object. A "PO Approval Agent" carries its authority set (approve up to $10K, approved vendors, within budget codes) — any invocation automatically inherits those constraints.

---

## Open Question: Separate External Orchestrator?

**Position reached**: NOT a separate orchestrator. Same orchestrator, different trust posture configuration.

Rationale: External interactions constantly need internal context (customer's account, contract terms, AP status). Splitting the orchestrator creates duplication or complex handoff.

The split should be at:

- Auth layer (different identity verification paths for external vs internal)
- Capability layer (external-facing A2A agents expose bounded subset of SOR capabilities)
- NOT at the orchestrator level

External orchestrator behavior differs via configuration:

| Behavior                  | Internal              | External                                    |
| ------------------------- | --------------------- | ------------------------------------------- |
| Default authority         | Broad (employee role) | Narrow (relationship tier)                  |
| Multi-step plans          | Execute in full       | One step, confirm, then next                |
| HITL confidence threshold | Lower                 | Higher (external commits harder to reverse) |
| Identity continuity       | Per session           | Per message                                 |
| Commitment audit point    | At execution          | At commitment (before execution)            |
| Novelty handling          | Try, then escalate    | Escalate before trying                      |

---

## HITL Framework

### The Two Variables That Determine Autonomy

1. **Reversibility** — Can this action be undone if wrong?
2. **Consequence magnitude** — How bad is a wrong outcome?

Most external commitments are low reversibility by nature. The challenge: the cost of misclassification is higher externally than internally.

### Three-Tier Autonomy Model

**Tier 1 — Autonomous Zone**: Agent acts, logs, notifies. No human needed.

- High reversibility OR low consequence
- Established pattern, high agent confidence
- Examples: status queries, standard info provision, routine confirmations

**Tier 2 — Shadow Zone** (underappreciated):

- Agent prepares action, holds briefly (seconds to minutes), fires unless human intercepts
- Not HITL — doesn't require active approval. More like: "Doing X in 3 minutes unless you say no"
- Examples: non-standard discount (within exception band), tight delivery date commitment, payment term adjustments within policy

**Tier 3 — Approval Zone**: Cannot proceed without explicit human decision.

- Low reversibility + high consequence, no precedent, low agent confidence
- Examples: contract modifications, credits above tier limits, new supplier onboarding commitments

### HITL Rate Targets

| HITL Rate | Effect                                                           |
| --------- | ---------------------------------------------------------------- |
| > 30%     | Perceived as "fancy form with extra steps." Agentic vision lost. |
| 10-30%    | Useful but not transformative. Acceptable for Phase 1.           |
| 5-10%     | Vision becomes real. Humans handle genuine exceptions only.      |
| < 2%      | Dangerous unless action boundaries are extremely tight.          |

**Target steady-state**: 5-10% by volume, covering ~50%+ of dollar value. Many interactions, few approvals — but approvals cover the high-stakes material.

**Path**: Start at 30-40% HITL (conservative Phase 1), reduce as agent earns trust through track record. Do NOT grant autonomy upfront — earn it empirically.

### Exception-First Design (vs Permission-First)

**Permission-first HITL** (approve all orders over $10K): Static, volume-insensitive, creates approval fatigue. Humans rubber-stamp. Approval becomes theater. Kills the vision.

**Exception-first HITL** (escalate when uncertain): Agent acts autonomously by default. HITL triggered by:

1. Confidence below threshold (agent self-model says "not sure")
2. Anomaly detected (doesn't match known patterns for this party)
3. Authority ceiling hit (value/action type exceeds embedded authority)
4. Novelty signal (first time this external party requests this action type)
5. Contradiction detected (external request conflicts with internal SOR data)

This produces meaningful HITL — when a human sees a notification, it requires actual judgment, not rubber-stamping.

### The Two HITL Axes (often conflated)

**Axis 1 — Internal HITL**: Does the company's human need to approve before agent acts?
**Axis 2 — External HITL**: Does the external party need to confirm before agent commits?

External HITL should NOT always be minimized. High-value B2B relationships sometimes value deliberateness. A fully autonomous commitment can feel like disrespect in high-stakes contexts. The agent should calibrate based on relationship tier and history — not always optimize for speed.

---

## Unresolved Questions (to come back to)

### 1. Who builds and maintains SOR agents?

Three options:

- **mingai builds them**: R&D moat, but enormous investment
- **Enterprises build them**: Low barrier, inconsistent quality
- **Third parties on HAR**: Ecosystem play — HAR as "app store for enterprise system capabilities" not just AI agent marketplace. Cold start problem.

**Note**: This reframes HAR significantly. Worth dedicated discussion.

### 2. External party authentication bootstrap

Internal flow is clean (SSO → JWT → auth context flows to A2A agents).
External flow has a gap — supplier/customer isn't on your SSO.

Options considered:

- Supplier portal login (friction upfront)
- Email-domain + relationship data (frictionless, weaker security)
- OAuth via supplier's own IdP (elegant, complex, bilateral federation)
- One-time token via existing relationship (pragmatic, sessionless)

Cleanest model: construct limited identity assertion from existing business relationship data (email, account number, PO history). But this creates bootstrapping dependency — that relationship data lives in a SOR agent.

### 3. The emergent composition problem

Individual agents are authorized for individual actions. The orchestrator composes them. The _composed outcome_ might exceed anyone's explicit intent even if each step is authorized.

The orchestrator's reasoning — why it decided to compose those steps — needs to be as auditable as the individual actions. Otherwise you can reconstruct what happened but not why the agent decided it.

This requires: **orchestrator decision logging**, not just action logging. Not currently in the architecture.

### 4. Agent self-model for calibrated uncertainty

The exception-first design depends on the agent knowing what it doesn't know. This is the hardest component to build and the one currently missing an explicit architectural home.

An agent that knows its own confidence limits is the difference between a system that earns expanding autonomy and one that gets shut down after the first major error.

---

## Key Philosophical Tension Unresolved

**"Operate without using systems of record"** vs **"operate without needing to understand systems of record"**

These lead to different products, different risk models, different onboarding stories.

The second framing ("without needing to understand") is more defensible for enterprise procurement ("SOR still exists, still auditable, employees just don't need to learn it") and avoids the learned helplessness failure mode.

Need to decide which framing is canonical before this shapes product positioning.
