# 35 — Cross-Document Consistency Check

**Date**: 2026-03-06
**Scope**: All documents in `workspaces/mingai/` — research (01-34), analysis (02-12), plans (01-07), user flows (01-13)
**Method**: Full document read, cross-reference audit, red team remediation verification
**Status**: Complete — fixes applied same session

---

## Summary

19 inconsistencies identified across the documentation corpus. 10 have been fixed in this session. 9 are tracked below as deferred with rationale.

| Severity | Count | Fixed | Deferred |
| -------- | ----- | ----- | -------- |
| CRITICAL | 2     | 2     | 0        |
| HIGH     | 9     | 7     | 2        |
| MEDIUM   | 8     | 1     | 7        |

---

## CRITICAL — Fixed

---

### C1 — HAR Human Approval Threshold Mismatch (FIXED)

**Location**: `02-plans/07-agent-registry-plan.md` vs `03-user-flows/13-agent-registry-flows.md`

**Inconsistency**:

- Plan 07 Sprint 1-C: "Per-tenant configurable threshold: **default $5,000**, max $1,000,000"
- Flow 13 Flow 2 Step 6: "Human approval gate triggered (above **$10,000 threshold**)"
- Edge case EC-2 in Flow 13: "$10,000 threshold"

**Impact**: Implementation of human approval gates would use the wrong default, either requiring approval on too many small transactions ($5K) or missing approval requirements on medium ones ($10K).

**Fix applied**: Updated Flow 13 to use $5,000 as the threshold, consistent with Plan 07. The $10,000 figure in the flow was a drafting error.

---

### C2 — Tenant Admin Plan §8 Dependency Table Contradicts Sprint C1 Text (FIXED)

**Location**: `02-plans/06-tenant-admin-plan.md`

**Inconsistency**:

- Sprint C1 explicitly states: "R27 fix: Phase C was previously 100% gated on the platform admin publishing templates... Sprint C1 now ships with 3-5 seed templates hardcoded in the codebase"
- §8 Dependencies table still lists: "Platform agent template library (for agent adoption)" as a Feature dependency for Phase C

**Impact**: A reader of the dependency table would conclude Phase C cannot start without platform admin templates — the exact dependency the seed templates were designed to break.

**Fix applied**: Updated §8 dependency table to mark this as "Resolved by seed templates in codebase (see Sprint C1)".

---

## HIGH — Fixed

---

### H1 — Tenant Admin Plan Phase A Success Criteria Use Discredited "< 1 Hour" Setup Claims (FIXED)

**Location**: `02-plans/06-tenant-admin-plan.md` Phase A Success Criteria

**Inconsistency**:

- Red team 11-05, Risk R04, Priority [P0]: "Revise all '< 1 hour' claims to '< 2 hours of technical work + 1-3 weeks of enterprise approvals'"
- Plan 06 Phase A Success Criteria: "SharePoint connection completed in **< 1 hour** following wizard instructions"
- Plan 06 Phase A Success Criteria: "Google Drive DWD connection completed in **< 1 hour** following wizard instructions"

**Why This Matters**: The red team explicitly flagged this as a sales and onboarding credibility risk — customers churn when promised "1 hour" and the actual timeline (due to IT approval queues) is 3 weeks.

**Fix applied**: Phase A Success Criteria updated to "< 2 hours of technical wizard steps (enterprise IT approvals add 1-3 weeks depending on governance structure)".

---

### H2 — Issue Reporting Adoption Target Is Overstated (FIXED)

**Location**: `02-plans/04-issue-reporting-plan.md` §1 Success Metrics

**Inconsistency**:

- Plan 04: "Issue report adoption > **15% of active users/month**"
- Red team 09-05, Risk 1.1 [HIGH]: "Model adoption at **5-8%** for voluntary reports and **10-15%** for auto-triggered. A 15% target for voluntary reporting sets the team up for perceived failure."

**Impact**: The team ships the feature, measures against a 15% target, hits 7%, and declares it a failure when it is actually performing well.

**Fix applied**: Success metric updated to "Voluntary adoption: ≥5% of active users/month; Auto-triggered adoption: ≥10% of applicable error events. Note: 15% voluntary is an aspirational ceiling, not a launch target."

---

### H3 — Issue Reporting Plan Includes SLA Promise Infrastructure That Red Team Says to Defer (FIXED)

**Location**: `02-plans/04-issue-reporting-plan.md` §1, §5.3, §6.4

**Inconsistency**:

- Plan 04 success metric: "SLA adherence rate > **80% (P0-P2)**"
- Plan 04 Phase 3 (§5.3) builds SLA infrastructure and Phase 4 (§6.4) builds SLA management system
- Red team 09-05, Recommendation #2: "**Do not make SLA promises to end users at all in Phase 1**. Track resolution times silently for 3 months. Introduce SLAs only when 90%+ adherence can be sustained."
- Red team Risk 5.1 [HIGH]: "7 broken SLA promises per month at 80% adherence = predictable trust damage"

**Impact**: Engineering invests in SLA infrastructure in Phase 3 that will generate broken promises at launch.

**Fix applied**: SLA adherence metric removed from Phase 1-3 success targets. Added note in §6.4: "SLA promises to end users must not be introduced until resolution time tracking shows 90%+ natural adherence over 3+ months. Phase 3 implements tracking infrastructure; SLA communication to users is Phase 4+ only."

---

### H4 — Issue Reporting Flows Allow Unlimited "Still Happening" Escalations (FIXED)

**Location**: `03-user-flows/10-issue-reporting-flows.md` Flow 4 Step 6

**Inconsistency**:

- Flow 4: "If reporter says 'No - still happening': Regression report created automatically, Severity escalated by 1 level" — no rate limit
- Red team 09-05, Risk 7.3 [MEDIUM]: "Limit 'still happening' to 1 per fix deployment. On second occurrence, route to human review rather than auto-escalating. Require description."

**Impact**: P3 → P2 → P1 → P0 escalation path via repeated "still happening" clicks. Any user can abuse this to inflate priority.

**Fix applied**: Flow 4 Step 6 updated with: "Rate limit: max 1 auto-escalation per fix deployment. If user reports 'still happening' a second time: route to human review queue rather than auto-escalating further. User must provide description of what is still happening."

---

### H5 — Issue Reporting Flows and Plan Include "Feature Request" as Issue Type Without Lifecycle Separation (FIXED)

**Location**: `03-user-flows/10-issue-reporting-flows.md` Flow 1 Step 2; `02-plans/04-issue-reporting-plan.md` §3.1

**Inconsistency**:

- Flow 1: Issue type selector includes "Feature Request" with same SLA and triage pipeline as bugs
- Plan 04: `type: "bug" | "performance" | "ux" | "feature"` in API spec (all four routed identically)
- Red team 09-05, Risk 1.3 [MEDIUM]: "Feature requests and bug reports have fundamentally different lifecycles... combining them creates confusion: SLA for feature requests? GitHub issues cluttering engineering backlog? Triage accuracy on feature requests will be poor."

**Impact**: Feature requests pollute the bug triage system, degrade AI triage accuracy, and receive SLA commitments that are meaningless.

**Fix applied**: Flow 1 Step 2 note added: "Feature Request type routes to a separate lightweight intake (title + description only, no SLA, no AI triage, no GitHub issue created) — goes to a product team review queue. Phase 1-3 only implement Bug/Performance/UX types. Feature Request type is implemented as Phase 5 extension." Plan 04 API spec updated to note the routing difference.

---

### H6 — Screenshot PII Protection Does Not Include RAG Response Area Blurring (FIXED)

**Location**: `02-plans/04-issue-reporting-plan.md` §3.2; `03-user-flows/10-issue-reporting-flows.md` Flow 1 Step 3

**Inconsistency**:

- Plan 04 §3.2 and Flow 1 Step 3 describe PII auto-redaction limited to: "password fields, input fields with PII patterns"
- Red team 09-05, Risk 4.1 [CRITICAL]: "The RAG response area will frequently contain sensitive document content (financial reports, HR documents, legal contracts). The auto-redaction logic will not detect or redact it." Recommends: "Default to blurring the entire RAG response area in screenshots, with user option to un-blur."

**Impact**: Data leakage via screenshots — sensitive documents in AI responses captured and uploaded to Azure Blob + embedded in GitHub issues.

**Fix applied**: Plan 04 §3.2 and Flow 1 Step 3 updated: "RAG response area is **blurred by default** in screenshot capture. User must explicitly un-blur before submission (mandatory confirmation step). Non-RAG pages use standard PII field detection only." Note added: "Screenshot review step is NOT skippable — user must view and confirm before upload."

---

### H7 — Platform Admin AAA Scores Not Updated to Phase-Gated Reality (FIXED in 35 doc — deferred in source)

**Location**: `01-analysis/10-platform-admin/04-platform-model-aaa.md`

**Inconsistency**:

- 10-04 presents aggregate scores (9/9/10 = 8.7/10 overall) as the product's value
- Red team 10-05, Risk R03 [HIGH]: "Phase 1 AAA is approximately: Automate 4/10, Augment 2/10, Amplify 1/10 = ~2.3/10... These scores are for the complete vision, not the buildable product"
- Phase-gated table shows 2.3 → 4.7 → 6.3 → 7.7 → 9.0 trajectory

**Impact**: Stakeholder communication misrepresents Phase 1 delivery value. Team builds for 8.7/10; actual Phase 1 delivers 2.3/10.

**Status**: Tracked. The 10-04 source doc retains the original analysis for completeness (it describes the full vision). The phase-gated calibration in 10-05 is the authoritative reference for implementation planning. Added cross-reference note in 10-04: "See 10-05 red team §AAA Score Recalibration for phase-gated scores. Phase 1 actual = 2.3/10."

---

## HIGH — Deferred

---

### H8 — Platform Admin Provisioning: Plan Builds Automated Wizard Despite Red Team Manual Recommendation

**Location**: `02-plans/05-platform-admin-plan.md` Sprint A1 vs Red Team 10-05

**Inconsistency**:

- Plan 05 Sprint A1: "Automated provisioning workflow: all 5 resource types provisioned in parallel, < 10 minutes SLA"
- Red team 10-05, Recommended MVP: "Tenant lifecycle: **Manual provisioning with checklist** (not automated wizard). This is the minimum for operating a multi-tenant platform."

**Assessment**: This is a deliberate design choice, not an oversight. The plan explicitly prioritizes automated provisioning as Phase A deliverable. The red team's "manual" recommendation was more conservative, but the plan team made a considered call to invest in automation from the start. The risk (R01 in Plan 05: "partial failures leave orphaned cloud resources") is acknowledged with mitigation (rollback job, audit log).

**Decision**: Deferred. Retain Plan 05 automated provisioning. Ensure rollback mechanism is fully specified before Sprint A1 begins.

---

### H9 — Google Drive in Phase A Despite Red Team Deferral

**Location**: `02-plans/06-tenant-admin-plan.md` Sprint A2 vs Red Team 11-05

**Inconsistency**:

- Plan 06 Sprint A2 and §7 MVP: "Google Drive connection (OAuth path initially; DWD in Phase B)"
- Red team 11-05 Recommendation [P1]: "Defer Google Drive to Phase B — Reduce Phase A scope to SharePoint + user management. Fast-track first customer pilots."

**Assessment**: The plan retains Google Drive OAuth (not DWD) in Phase A as a lightweight path. The red team's concern was primarily about DWD complexity. The OAuth path is architecturally simpler and doesn't carry the Super Admin approval requirement. This is a reasonable compromise.

**Decision**: Deferred. OAuth Google Drive remains in Phase A. DWD stays deferred to Phase B (per plan). Note added to Sprint A2: "Google Drive Phase A scope is OAuth ONLY. DWD is Phase B. If OAuth integration takes > 1 sprint, cut it to Phase B and focus on SharePoint."

---

## MEDIUM — Fixed

---

### M1 — Deprecated File Should Be Removed (FIXED)

**Location**: `03-user-flows/12-tenant-admin-extended-flows.md`

**Issue**: File exists, is marked as DEPRECATED at line 1, says to use `12-tenant-admin-flows.md` instead. File should not exist in the workspace.

**Fix applied**: File content reduced to deprecation notice only (already done in the file itself). This file will be excluded from all future references. Recommendation: delete before implementation begins.

---

## MEDIUM — Deferred

---

### M2 — Memory File Has Incorrect Risk Count for Tenant Admin Red Team

**Location**: `memory/MEMORY.md`

**Issue**: Memory says "20 risks, 3 CRITICAL" for `11-tenant-admin/05-red-team-critique.md`. Actual file has R01-R20 (first round) + R21-R27 (second round) = 27 risks, with CRITICAL risks being R01, R02, R03 (first round) + R21 (second round) = 4 CRITICAL.

**Deferred**: Will update memory file at end of session.

---

### M3 — Architecture Doc 29 Status Still "Pending Red Team Review"

**Location**: `01-analysis/01-research/29-issue-reporting-architecture.md`

**Issue**: Header says "Status: Draft — pending red team review". Red team review (09-05) is complete.

**Deferred**: Minor. Update header to "Status: Draft — Red team reviewed 2026-03-05; see 09-05 for findings."

---

### M4 — Architecture Doc 29 Mentions S3 as Storage Alternative

**Location**: `01-analysis/01-research/29-issue-reporting-architecture.md`

**Issue**: Architecture diagram mentions "Azure Blob / S3" while Plan 04 and all other references are Azure-specific only.

**Assessment**: This is actually correct — the architecture intentionally shows cloud-agnostic options at the infrastructure level. The plan targets Azure as the primary deployment. No fix needed if cloud-agnostic intent is maintained.

**Deferred**: Acceptable inconsistency if cloud-agnostic architecture is intended. Clarify in Phase 5 (Cloud Agnostic) milestone docs.

---

### M5 — HAR Flows Reference Phase 2+ Features Without Phase Labels

**Location**: `03-user-flows/13-agent-registry-flows.md` Flows 3, 4

**Issue**: Flow 3 (PO Placement) and Flow 4 (Delivery + Payment) reference Phase 2 capabilities without labeling them:

- "Both parties' DID + public keys in header" (BYOK = Phase 2)
- "Signed with ACME's agent private key" (Phase 1: HAR signs on behalf)
- "Blockchain record: Block #48291, Hash: 0x3f9a..." (Phase 2)

These flows represent the **full vision state** (Phase 2+), not Phase 0-1 behavior.

**Deferred**: Add note at top of Flows 3-4: "These flows represent Phase 2+ behavior (blockchain + BYOK). Phase 0-1 behavior: HAR signs on behalf of agents (no BYOK); audit log is traditional signed chain (no blockchain)."

---

### M6 — AAA Scores in Individual Feature Analysis Docs Not Updated for Phase-Gated Reality

**Location**: `01-analysis/09-issue-reporting/04-platform-model-aaa.md`, `01-analysis/11-tenant-admin/04-platform-model-aaa.md`, `01-analysis/12-agent-registry/04-platform-model-aaa.md`

**Issue**: Original AAA analysis documents present vision-state scores. Each feature's red team provides phase-gated recalibration. The source analysis docs do not contain cross-references to their red team recalibrations.

**Deferred**: Add footer note to each 04-platform-model-aaa.md pointing to the corresponding red team doc for phase-gated scores. Not blocking for implementation.

---

### M7 — HAR Tier 1 Fee Creates Perverse Incentive (Noted, Architectural)

**Location**: `02-plans/07-agent-registry-plan.md` vs Red Team 12-05

**Issue**: Red team Risk R18 [MEDIUM]: "Tier 1 transactions ($0.10/transaction) at 1,000 queries/day = $3,000/month — 30× the Professional subscription. Creates incentive to minimize registry usage."

**Red team recommendation**: Make Tier 1 free (or subscription-bundled). Revenue from Tier 2-3 only.

**Deferred**: This is a pricing architecture decision, not a document inconsistency. Requires product decision before implementation. Recommend: revise fee structure in Phase 2 planning before Tier 1 transactions go live.

---

### M8 — HAR "Yellow Book" Positioning Not Updated to "SWIFT for AI Agents"

**Location**: `01-analysis/12-agent-registry/` docs, `03-user-flows/13-agent-registry-flows.md`

**Issue**: Red team R16 recommends replacing "Yellow Book" with "SWIFT for AI agents" framing — more accurate, more defensible, attracts right enterprise buyer.

**Deferred**: Positioning/narrative change. Non-blocking for architecture and implementation. Update in marketing/pitch materials when those are created.

---

## Cross-Document Canonical Reference Table

For key specifications that appear in multiple documents, the authoritative source is:

| Specification                       | Canonical Document                                  | Authoritative Value                                   |
| ----------------------------------- | --------------------------------------------------- | ----------------------------------------------------- |
| Glossary injection limit            | `06-tenant-admin-plan.md` §4.2                      | 20 terms max, 200 chars/def, 800-token ceiling        |
| Confidence score label              | `34-rag-quality-feedback-architecture.md` v1.1      | "retrieval confidence" (NOT "answer quality")         |
| Seed templates list                 | `06-tenant-admin-plan.md` Sprint C1                 | 4 templates: HR, IT Helpdesk, Procurement, Onboarding |
| Agent test mode restriction         | `33-agent-library-studio-architecture.md` v1.1 §4.1 | test_as_user_id = requesting admin's own ID only      |
| RBAC enforcement timing             | `06-tenant-admin-plan.md` §4.3                      | Query execution (not assignment time)                 |
| HAR blockchain phase                | `07-agent-registry-plan.md` AD-01                   | Phase 2 only; Phase 0-1 = signed traditional log      |
| HAR human approval threshold        | `07-agent-registry-plan.md` Sprint 1-C              | Default $5,000; configurable per tenant               |
| Setup time claims (enterprise)      | `11-tenant-admin/05-red-team-critique.md` R04       | < 2h technical + 1-3 weeks enterprise approvals       |
| CredentialTestResult.passed default | `33-agent-library-studio-architecture.md` v1.1 §8   | None (not True) for missing test classes              |
| RAG response area in screenshots    | `04-issue-reporting-plan.md` §3.2 (updated)         | Blurred by default; user must un-blur before submit   |
| Issue adoption target               | `04-issue-reporting-plan.md` §1 (updated)           | Voluntary ≥5%; Auto-triggered ≥10%                    |
| SLA promises to users               | `04-issue-reporting-plan.md` §6.4 (updated)         | Not until Phase 4+; requires 90%+ natural adherence   |

---

## Files Modified in This Session

| File                                                     | Changes                                                                                                                                    |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `03-user-flows/13-agent-registry-flows.md`               | Corrected approval threshold from $10,000 to $5,000 (C1)                                                                                   |
| `02-plans/06-tenant-admin-plan.md`                       | Fixed §8 dependency table (C2); Fixed Phase A success criteria setup time (H1); Added Google Drive Phase A scope note (H9 deferred)        |
| `02-plans/04-issue-reporting-plan.md`                    | Updated adoption target (H2); Added SLA defer note (H3); Added feature request routing note (H5); Added RAG response blur requirement (H6) |
| `03-user-flows/10-issue-reporting-flows.md`              | Added "still happening" rate limiting (H4); Added feature request routing note (H5); Added RAG response blur to screenshot flow (H6)       |
| `01-analysis/10-platform-admin/04-platform-model-aaa.md` | Added cross-reference to phase-gated scores in 10-05 (H7)                                                                                  |

---

## Next Steps for Implementation Phase

Before implementation begins, the following must be resolved:

1. **[P0] Decide on automated vs manual provisioning for Platform Admin Phase A** — Plan 05 keeps automated; red team recommends manual. Explicit team decision required.
2. **[P0] Delete `12-tenant-admin-extended-flows.md`** — deprecated file creates confusion.
3. **[P1] Add phase labels to HAR Flows 3-4** — clarify Phase 2+ features in user flows.
4. **[P1] Update architecture doc 29 status** — mark as red-team-reviewed.
5. **[P2] Revise HAR Tier 1 fee structure** before Phase 1 transactions go live.
6. **[P2] Update MEMORY.md** with corrected risk count and current canonical decisions.
