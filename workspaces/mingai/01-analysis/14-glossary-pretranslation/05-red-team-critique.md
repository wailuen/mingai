# 14-05 — Red Team Critique: Glossary Pre-Translation

## Methodology

This critique applies adversarial, first-principles reasoning to the Glossary Pre-Translation architecture. Each finding is evaluated independently of implementation enthusiasm. The goal is to surface every failure mode before production deployment.

Findings are classified:

- **CRITICAL**: Must be resolved before Phase 1 launch
- **HIGH**: Must be resolved before broad tenant rollout (within 1-2 sprints)
- **MEDIUM**: Backlog priority within Phase 2
- **LOW**: Noted for completeness; acceptable technical debt

---

## R01 — CRITICAL: Acronym False Positives for Common Short Words

**Category:** CRITICAL

**Description:**
The expansion algorithm will match all-caps or recognisably acronym-like tokens — but natural English text contains many short uppercase sequences that are not acronyms. "IT" is the canonical failure case: a glossary entry "IT = Information Technology" would match the pronoun "it" if the user types in all caps or at sentence start ("IT was unclear..."), or if the case-sensitivity rules are not implemented correctly.

More subtle failure: "US" (United States) could be a glossary entry, but "us" (first-person plural pronoun) could be typed at sentence start as "Us". "HR" could be a term but "her" abbreviated in informal text starts with "H". "PM" means Project Manager in IT glossaries, but "PM" in a query about medication means afternoon in time notation.

**Evidence/Scenario:**

```
User types: "IT was unclear from the policy whether..."
Glossary contains: IT → Information Technology
Expansion: "Information Technology (Information Technology) was unclear..."
LLM receives: nonsensical repetition
```

**Impact:**
Response quality degradation. User cannot understand why the response is confused. Invisible failure — no error is surfaced. Erosion of trust in the AI system.

**Remediation:**

1. **Uppercase-only rule for ≤3 character terms:** For any glossary entry whose acronym is 1–3 characters (single-word acronyms), expansion only fires if the matched token appears in ALL CAPS in the user's query. "IT" (all caps) expands to "Information Technology"; "it" and "It" do not. This is the most important single rule and eliminates pronoun false positives at the source.
2. **Platform-maintained stop-word exclusion list:** A hardcoded list of common English words that are never expanded regardless of glossary entry. Stored in platform config (not per-tenant). Current list: `as`, `it`, `or`, `by`, `at`, `be`, `do`, `go`, `in`, `is`, `on`, `to`, `up`, `us`, `we`, `no`, `so`, `an`, `am`, `my`, `of`. Even if a tenant creates a glossary entry matching one of these tokens, the stop-word check takes precedence and suppresses expansion.
3. Sentence-initial token handling: the first token of a sentence that starts with a capital letter should not be treated as an acronym unless it is all-caps and length >= 2 and passes the stop-word check.
4. Require tenant admins to explicitly whitelist short-token glossary entries, with a platform warning displayed at time of creation for tokens <= 3 characters.

**Status:** RESOLVED — both controls (uppercase-only rule and stop-word exclusion list) ship in Sprint 1 of Plan 09.

---

## R02 — CRITICAL: Invisible Failure Mode — Wrong Expansion, No Correction Path

**Category:** CRITICAL

**Description:**
When GlossaryExpander produces a wrong expansion (false positive: matched the wrong term, or matched the right term with a stale `full_form`), the LLM receives incorrect context and produces a wrong or confused response. The user sees the wrong response and has no mechanism to understand the cause or correct it.

The glossary expansion is not visible in the chat UI. The user cannot see "I expanded 'LTV' to 'Loan-to-Value ratio'" and therefore cannot say "actually I meant 'Long-Term Vision'." The correction loop is broken.

This creates a class of response failures that are:

1. Invisible to the user (they don't know expansion happened)
2. Invisible to the admin (no signal that an expansion caused a bad response)
3. Invisible to the platform (no way to correlate expansion events with negative feedback)

**Evidence/Scenario:**

```
Glossary: AWS → Annual Wage Supplement (tenant context)
User query: "Can you compare AWS Lambda pricing with Azure Functions?"
Expansion: "Can you compare AWS (Annual Wage Supplement) Lambda pricing..."
LLM response: confused — "Annual Wage Supplement Lambda" is not a product
```

The user receives a bad response. They retry or give up. The admin never discovers the cause. The AWS entry remains in the glossary.

**Impact:**
Trust erosion. Response quality degradation for queries about external entities (AWS, Microsoft, etc.) that share acronyms with internal glossary terms. No self-correction mechanism.

**Remediation:**

1. **Phase 1 (algorithm):** Implement a "likely-external-entity" heuristic: if the token matches a well-known brand name or product acronym (maintain a platform-level exclusion list of ~200 common technology/company acronyms), do not expand even if the tenant glossary matches. The exclusion list takes precedence.
2. **Mandatory Day 1 (UX):** Every chat response that involved at least one glossary expansion shows a small "Terms interpreted" indicator below the response — e.g., "AWS → Annual Wage Supplement · CPF → Central Provident Fund." The indicator is visible on every qualifying response; it is not optional or toggleable. User can click the indicator to see the full list of all expansions applied to their query. This is a Sprint 1 mandatory deliverable, not a Phase 2 enhancement.
3. **Phase 2 (feedback loop):** User can click "incorrect" on an individual expansion in the indicator to flag it. Flagging sends a `glossary_expansion_flagged` event to the admin dashboard. Admin dashboard shows flagged expansions; admin can mark a term as ambiguous (disabling expansion) or update the full_form.

**Status:** RESOLVED — expansion indicator is MANDATORY in Sprint 1 (not optional, not deferred to Phase 2). Phase 1 exclusion list also required.

---

## R03 — HIGH: Embedding Strategy May Harm Retrieval for Full-Form Document Corpora

**Category:** HIGH

**Description:**
The implementation decision (§3.2 of 04-implementation-alignment) is to embed the original (pre-expansion) query for vector search. This preserves semantic fidelity with the user's phrasing.

However, this decision has a non-obvious failure mode: if the knowledge base contains documents that always spell out the full form and never use the acronym, the embedding of the acronym ("AWS") will not align well with document embeddings of "Annual Wage Supplement." The vector search will underperform.

This is the inverse of the current problem (LLM doesn't understand acronyms). With pre-translation, the LLM understands the query correctly, but the retrieval layer may miss relevant documents.

**Evidence/Scenario:**

```
KB document: "The Annual Wage Supplement is payable in December..."
User query: "What is the AWS payout?"
Embedding of "AWS": semantic space near {Amazon, cloud, storage...}
NOT near {annual, wage, supplement, payable}
→ Relevant document not retrieved
→ LLM has correct understanding of query intent but no document context to answer
```

**Impact:**
For tenants whose knowledge base was written in formal full-form language (legal documents, HR policies, regulatory filings), RAG recall may be poor for acronym-heavy queries. The LLM has the right frame (thanks to expansion) but insufficient evidence (due to poor retrieval). Response is confident but thin.

**Remediation:**

1. **Phase 1 analysis:** Before migrating each tenant, sample their query log and document corpus to assess acronym density. If documents use full forms predominantly (>70% of occurrences), recommend embedding the expanded query instead.
2. **Phase 2 configuration:** Add an optional `embed_expanded` flag per tenant (off by default). Tenants with full-form-dominant corpora enable this. A/B test within the tenant to validate improvement.
3. **Phase 2 algorithm:** Hybrid embedding — embed both original and expanded query, take the union of top-K results from both, re-rank. This eliminates the retrieval coverage gap without requiring a per-tenant configuration decision.

**Status:** Must be evaluated per tenant as part of migration readiness assessment. Do not assume the "embed original" default is correct for all corpora.

---

## R04 — HIGH: Stale Glossary Silently Degrades All Responses at Scale

**Category:** HIGH

**Description:**
The amplification quality of pre-translation is entirely dependent on glossary accuracy. A stale or incorrect glossary term does not fail visibly — it expands silently to the wrong full_form and corrupts the LLM's context on every query that contains that acronym.

Unlike the Layer 6 injection approach (where a wrong definition is one of many in a block, and the LLM may dilute its influence), an inline wrong expansion directly overwrites the user's query semantics. The LLM is more likely to anchor on the wrong full_form.

**Evidence/Scenario:**

```
Company renames "AWS" from "Annual Wage Supplement" to "Annual Wage Support" (policy update)
Admin updates policy documents but forgets to update the glossary
Glossary still: AWS → Annual Wage Supplement
Every query about "AWS" for the next 6 months expands to the old term
LLM may cite the old term name in responses
Compliance risk: official communications use wrong term name
```

**Impact:**
Silent mass degradation of all queries containing the stale term. In regulated industries, incorrect terminology can create compliance exposure. No signal to the admin that stale terms exist until a user manually reports it.

**Remediation:**

1. **Phase 1:** Add `last_validated_at` field to `GlossaryTerm`. Admin console shows "last validated" date for each term; terms not validated in >90 days show a yellow warning indicator.
2. **Phase 2:** Implement a scheduled "glossary health scan" that cross-references terms against indexed documents: does the `acronym` appear in recent documents? Does the `full_form` appear alongside the acronym in recent documents? Flag discrepancies for admin review.
3. **Phase 2:** Analytics dashboard showing expansion frequency per term — terms with high expansion rates are high-risk if stale; highlight these for prioritised review.

**Status:** Requires `last_validated_at` schema addition in Phase 1 (schema migration is small but needed before launch to avoid a second migration later).

---

## H01 — HIGH: Multi-Term Overlap Creates Double Expansion Edge Cases

**Category:** HIGH

**Description:**
When a query contains a phrase that matches both a standalone acronym and a multi-word glossary entry, the expansion logic must correctly apply the longest-match rule. If this rule is not robustly implemented, the same acronym could be expanded twice, or the multi-word expansion could corrupt the standalone expansion's positioning.

**Evidence/Scenario:**

```
Glossary:
  LTV → Loan-to-Value ratio
  LTV limit → Loan-to-Value ratio limit (for regulatory use)

User query: "What is the current LTV limit for residential mortgages?"

Correct expansion: "What is the current LTV limit (Loan-to-Value ratio limit) for residential mortgages?"
Buggy expansion 1: "What is the current LTV (Loan-to-Value ratio) limit (Loan-to-Value ratio limit) for residential mortgages?"
Buggy expansion 2: "What is the current LTV (Loan-to-Value ratio) limit for residential mortgages?" (shorter match wins incorrectly)
```

**Impact:**
Query becomes malformed (double parenthetical) or loses the more precise multi-word expansion. Moderate quality degradation. User-visible if expansion indicator is implemented in Phase 2.

**Remediation:**
Implement longest-match-first algorithm with explicit phrase tokenization before individual token matching. Sort all candidate matches by match length (descending) before applying expansions. Mark covered positions to prevent overlap. Unit test coverage for all overlap combinations.

**Status:** Must be fully implemented and tested in Phase 1. The algorithm in §2.2, Step 6 of 04-implementation-alignment covers this, but implementation must be validated against edge cases.

---

## H02 — HIGH: Backwards Compatibility — Existing Tenants May See Response Changes

**Category:** HIGH

**Description:**
Existing tenants have been receiving responses generated with the glossary injected into the system prompt. Switching to pre-translation changes the mechanism by which glossary context reaches the LLM. Even if the semantic information is equivalent, the LLM's processing path is different — and LLM responses are sensitive to prompt structure.

Responses may change in tone, completeness, or accuracy for glossary-heavy queries. Some tenants may have tuned their agent system prompts assuming the glossary is in a specific part of the context. Removing Layer 6 could break these assumptions.

**Evidence/Scenario:**

```
Tenant A's agent system prompt (custom, written by tenant admin):
"You are an HR assistant. Use the terminology definitions provided below to interpret acronyms."

Previously: "below" referred to Layer 6 which appeared after this instruction
After migration: "below" refers to nothing — Layer 6 is gone
LLM may hallucinate or underperform on acronym interpretation
```

**Impact:**
Tenant-visible response quality changes without warning. Enterprise tenants with strict procurement governance may treat unexpected behavior changes as SLA violations. This is a trust and contract risk, not just a technical risk.

**Remediation:**

1. **Pre-migration:** Audit tenant agent system prompts for references to glossary injection (e.g., "use the terminology provided," "definitions below"). Identify at-risk tenants.
2. **Migration:** Offer at-risk tenants a staged migration with side-by-side comparison of response quality (shadow mode: run both old and new pipeline on the same queries, log differences for admin review).
3. **Communication:** Notify all tenants of the architecture change 2 weeks before migration. Frame it as a "quality improvement" with the token budget benefit as the headline. Provide a 30-day rollback option.
4. **Documentation:** Update all tenant admin documentation to remove references to "terminology definitions in system prompt."

**Status:** Communication and audit plan must be completed before migration begins.

---

## H03 — HIGH: Query Expansion Inflates Token Count for Complex Multi-Term Queries

**Category:** HIGH

**Description:**
The analysis assumes worst-case expansion of ~50 tokens (8 terms × 5-6 tokens each). However, this calculation assumes short full_forms. In practice, regulatory and legal glossaries contain multi-word full_forms that are significantly longer.

**Evidence/Scenario:**

```
Glossary term: GDPR → General Data Protection Regulation (4 tokens)
Glossary term: CCPA → California Consumer Privacy Act (5 tokens)
Glossary term: DPIA → Data Protection Impact Assessment (5 tokens)
Glossary term: DPO → Data Protection Officer (4 tokens)
Glossary term: SCCs → Standard Contractual Clauses (4 tokens)
Glossary term: BCRs → Binding Corporate Rules (4 tokens)
Glossary term: PIA → Privacy Impact Assessment (4 tokens)
Glossary term: RoPA → Records of Processing Activities (5 tokens)

Query from compliance user: "Under GDPR, does a DPIA require a DPO sign-off before SCCs and BCRs are processed? Check our PIA and RoPA policies."

Expansions: 8 terms → ~35 additional tokens
Expanded query length: ~50 tokens (original) + ~35 (expansions) = ~85 tokens

This is within budget, but note: the full_form max character limit (80 chars, §2.5 of impl doc)
could allow a full_form of ~20 tokens. At 8 matches: 8 × 20 = 160 additional tokens.
```

**Impact:**
For compliance-heavy tenants with long full_forms and complex queries, expansion overhead can reach 160+ tokens — significantly higher than the assumed 50-token ceiling. While still within the recovered budget (500 tokens freed), this is not negligible and was not fully accounted for in the architecture.

**Remediation:**

1. Enforce `full_form` character limit of 80 characters (already specified). This limits expansion to ~20 tokens per term maximum.
2. Add a platform-level token budget monitor that measures actual expansion overhead per query. Alert operations if average expansion overhead exceeds 100 tokens for a tenant.
3. Consider a `full_form_short` field for tenants who want a concise expansion for pre-translation, with the full definition still stored but not used in expansion.

**Status:** 80-character limit must be enforced at the data model level (validation in GlossaryTerm model), not just documented.

---

## M01 — MEDIUM: Definition Truncation — Full Form Insufficient for Obscure Terms

**Category:** MEDIUM

**Description:**
The architecture decision to use only `full_form` (not the glossary `definition`) for expansion is correct from a security standpoint (prevents injection) and a token standpoint (short expansion). However, for highly specialised or obscure terms, the full form alone may not provide the LLM with sufficient context to interpret the term correctly.

**Evidence/Scenario:**

```
Glossary term: ECAP → Economic Capital Adequacy Process
full_form: "Economic Capital Adequacy Process"

User query: "Has our ECAP threshold changed since the merger?"
Expanded: "Has our ECAP (Economic Capital Adequacy Process) threshold changed since the merger?"

LLM knows: "Economic Capital Adequacy Process" — this is standard banking terminology
LLM can infer: what a threshold would mean in this context
→ Sufficient

vs.

Glossary term: FALCON → Financial Automated Lending Control Operations Network (internal system name)
full_form: "Financial Automated Lending Control Operations Network"
definition: "Our internal loan underwriting platform, deployed in 2019, manages credit decisions for consumer products."

User query: "Is there a FALCON outage affecting approvals?"
Expanded: "Is there a FALCON (Financial Automated Lending Control Operations Network) outage affecting approvals?"

LLM knows: the full name is a proper noun, not a standard term
LLM may not know: that FALCON is an internal system for underwriting
→ Potentially insufficient for domain reasoning
```

**Impact:**
Moderate quality degradation for queries about internal systems, proprietary processes, or bespoke acronyms that a general-purpose LLM cannot infer from the full name alone. The LLM knows the name but not the context.

**Remediation:**

1. **Phase 1:** Accept this limitation. For obscure terms, the definition needs to reach the LLM through the knowledge base (a document describing FALCON should be indexed and retrieved). This is the correct long-term solution — definitions belong in the knowledge base, not in the query or system prompt.
2. **Phase 2:** Consider an optional `brief_context` field (max 50 characters) appended after the full_form: "FALCON (Financial Automated Lending Control Operations Network, our loan underwriting platform)." This is a small, controlled injection that stays within the noun-phrase security boundary.
3. **Phase 2 analysis:** Identify which tenant glossary terms are "opaque" (full form does not disambiguate sufficiently) by checking whether the full form appears in indexed documents. Terms not in the corpus may need brief_context.

---

## M02 — MEDIUM: User Visibility Gap Prevents Quality Feedback Loop

**Category:** MEDIUM

**Description:**
In the current architecture, expansion is completely invisible to the user. This breaks the feedback loop that drives glossary quality:

1. User submits query with term X
2. Expansion fires, expanding X to wrong full_form
3. LLM gives wrong response
4. User perceives "AI is bad" — not "expansion was wrong"
5. User does not report the expansion error
6. Admin never learns the term is wrong
7. Wrong expansion persists

This is a governance failure masked as a UX omission.

**Impact:**
Glossary quality stagnates or degrades over time. High-volume bad expansions accumulate without admin awareness. The amplification effect of the feature amplifies misinformation at scale.

**Remediation (Phase 2):**
Implement a collapsible "interpretation" section in the chat response UI:

```
[Response text here]

▶ Interpreted 2 terms: AWS → Annual Wage Supplement · LTV → Loan-to-Value ratio  [Report issue]
```

- Collapsed by default (does not disrupt chat flow)
- "Report issue" link opens a mini-form: "Which interpretation was wrong? [AWS] [LTV]"
- Admin receives aggregated flagging report weekly

**Status:** Deferred to Phase 2 by design. Must be shipped before glossary quality issues accumulate.

---

## M03 — MEDIUM: No Governance for Glossary Term Lifecycle (Create → Deprecate → Archive)

**Category:** MEDIUM

**Description:**
The current glossary model supports `is_active` (binary: on/off). There is no concept of:

- **Pending**: term added but not yet approved
- **Deprecated**: term scheduled for removal (old product name no longer in use)
- **Superseded**: term replaced by another entry (rename: "SAP" → "S/4HANA" after migration)

Without a lifecycle, inactive terms accumulate (increasing glossary noise), deprecated terms are deleted rather than archived (losing audit history), and superseded terms create no trail connecting old and new terminology.

**Impact:**
Governance risk in regulated industries. Analytics lose historical continuity when terms are deleted. Admins have no safe way to retire a term without hard deletion.

**Remediation:**
Add `status` enum to `GlossaryTerm`: `{draft, active, deprecated, archived}`. Deprecation shows a warning in the admin UI but the term is not expanded. Archived terms are excluded from the active glossary cache but preserved in the DB. This is a small schema change with high governance value.

**Status:** Schema should be added in Phase 1 migration to avoid a second migration later.

---

## L01 — LOW: CJK Parenthesis Format Not Universally Preferred

**Category:** LOW

**Description:**
The CJK full-width parenthesis rule (using ｛full-width｝ brackets for CJK locales) assumes all CJK users prefer this format. In practice, many technical documents in Japanese, Chinese, and Korean enterprises use ASCII parentheses even for CJK text. Some LLMs tokenize full-width characters differently from ASCII, which could affect token count calculations.

**Impact:**
Minor: cosmetic inconsistency. Potential token count miscalculation (full-width characters may count as 1-2 tokens vs ASCII parentheses which are typically 1 token). Not a correctness issue.

**Remediation:**
Make the parenthesis format configurable per tenant (default: ASCII; optional: CJK full-width). Phase 2 configuration item.

---

## L02 — LOW: Analytics Event `glossary_term_matched` Semantics Change Is Undocumented

**Category:** LOW

**Description:**
The `glossary_term_matched` event previously indicated "this term was included in the system prompt context for this query." Post-migration, it means "this term was found in the user's query and expanded inline." These are different things: the first fires for every query where the term exists in the glossary; the second fires only when the term appears in the specific query.

Existing tenant admin dashboards and analytics integrations that use this event may misinterpret the data after migration. Historical event counts will appear to drop (because the old event fired for every query; the new event fires only for matched queries).

**Impact:**
Analytics continuity break. Tenant admins with custom dashboards may raise support tickets. No correctness risk.

**Remediation:**
Document the semantic change in the migration release notes. Add an `event_version` field to the event payload (`v1` = injection-era, `v2` = pre-translation era) so analytics consumers can differentiate historical and post-migration data.

---

## Summary Table

| ID  | Category | Title                                                       | Phase Required                                             |
| --- | -------- | ----------------------------------------------------------- | ---------------------------------------------------------- |
| R01 | CRITICAL | Acronym false positives for short common words              | RESOLVED — Sprint 1 (uppercase-only rule + stop-word list) |
| R02 | CRITICAL | Invisible failure — wrong expansion, no correction path     | RESOLVED — Sprint 1 (mandatory expansion indicator)        |
| R03 | HIGH     | Embedding strategy may harm retrieval for full-form corpora | Phase 1 (assessment) + Phase 2 (config)                    |
| R04 | HIGH     | Stale glossary silently degrades responses at scale         | Phase 1 (schema) + Phase 2 (analytics)                     |
| H01 | HIGH     | Multi-term overlap — double expansion edge cases            | Phase 1                                                    |
| H02 | HIGH     | Backwards compatibility — existing tenant response changes  | Pre-migration (communication plan)                         |
| H03 | HIGH     | Token inflation for complex multi-term queries              | Phase 1 (enforce 80-char limit)                            |
| M01 | MEDIUM   | Full form insufficient for obscure proprietary terms        | Accept in Phase 1; Phase 2 optional field                  |
| M02 | MEDIUM   | User visibility gap prevents quality feedback loop          | Phase 2                                                    |
| M03 | MEDIUM   | No glossary term lifecycle (draft/deprecated/archived)      | Phase 1 schema (small change)                              |
| L01 | LOW      | CJK parenthesis format preference varies                    | Phase 2 config option                                      |
| L02 | LOW      | Analytics event semantics change undocumented               | Migration release notes                                    |

**Critical path for Phase 1 launch:**

- R01: RESOLVED — uppercase-only rule (≤3 char terms) + platform stop-word exclusion list, both in Sprint 1
- R02: RESOLVED — mandatory "Terms interpreted" indicator in Sprint 1; platform-level brand acronym exclusion list also required
- H01: Longest-match algorithm fully tested
- H02: Tenant communication plan and audit of custom system prompts
- H03: 80-character `full_form` limit enforced at model level
- R04: `last_validated_at` field added to schema
- M03: `status` enum added to schema

**Cannot defer to Phase 2 without risk:**
R01 and R02 are existential to the feature — false positives and invisible failures will erode trust faster than the token budget improvement builds it. These must be resolved in Phase 1 or the feature should not be deployed to production tenants.
