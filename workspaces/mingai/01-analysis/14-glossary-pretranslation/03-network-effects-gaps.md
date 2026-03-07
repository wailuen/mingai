# 14-03 — Network Effects & Gaps: Glossary Pre-Translation

## Assessment Framework

For each of the five network behaviors, the assessment covers:

- **Current State Score (1-10)**: How well the feature delivers this behavior today (post-migration)
- **Gap Description**: What is missing or underperforming
- **Evidence**: Concrete signals or scenarios
- **Phase for Gap Closure**: When the gap is addressed

---

## 1. Accessibility

**Definition:** Does the feature reduce friction for users to get value from the platform?

**Current State Score: 8/10**

**What works:**
Pre-translation is the highest-accessibility improvement in the platform's history. The friction it removes is fundamental: users no longer need to know that the LLM doesn't understand their company's vocabulary. A new employee on day one, using the acronyms they learned in their first week, receives the same response quality as a tenured employee who has learned to spell things out.

The improvement is entirely passive — the user takes no action to benefit. Accessibility improvements that require user awareness or behavior change are fragile; this one is not.

**What is missing (gap score: -2):**

**Gap A1: No feedback when expansion fails (MEDIUM)**
When a user queries "What is our POL policy?" and "POL" is not in the glossary, the response may be lower quality, but the user receives no signal that the term was unrecognized. The system cannot suggest "Did you mean to add 'POL' to the glossary?" because the glossary awareness is not surfaced in the UI.

**Gap A2: Glossary bootstrapping is a cold-start problem (HIGH)**
A new tenant's glossary is empty. For the first weeks after onboarding, pre-translation provides zero benefit because no terms exist. The feature's accessibility advantage is gated behind a glossary-building effort that may take weeks for a new admin to complete. This delays time-to-value.

**Remediation:**

- A2: CSV import from existing terminology documents at onboarding. A platform-provided industry starter pack (Phase 3). An "auto-suggest terms" feature that scans user queries for likely acronyms (Phase 2).

---

## 2. Engagement

**Definition:** Does the feature make interactions more accurate, useful, and satisfying — increasing return usage?

**Current State Score: 7/10**

**What works:**
Responses that correctly interpret domain terminology are materially better — more accurate, more directly applicable to the user's question, less likely to require follow-up clarification. Users who receive good responses return. Users who receive responses that misinterpret their question churn or stop using the platform.

Pre-translation directly improves response quality for the class of queries that include glossary-matched terms. For tenants with rich glossaries (50+ terms, high domain density), this is a significant proportion of queries.

**What is missing (gap score: -3):**

**Gap E1: Engagement improvement is invisible and unattributable (HIGH)**
Users do not know that a better response was due to glossary expansion. They cannot distinguish between "the AI is good" and "the AI is good because our admin built a great glossary." This breaks the feedback loop that would drive engagement.

A visible expansion indicator (e.g., "Interpreted: AWS as Annual Wage Supplement") would let users understand, validate, and correct the system — closing a feedback loop that improves both engagement and glossary quality.

**Gap E2: Bad expansions reduce engagement without a correction mechanism (HIGH)**
If "IT" expands to "Information Technology" when the user meant "it" (the pronoun), the response may be confused or irrelevant. The user will not understand why. They will assume "the AI is bad" and reduce usage. There is currently no correction pathway (see R02 in red team critique for detailed analysis of this case).

**Gap E3: No engagement analytics per term (MEDIUM)**
Without per-term analytics (which terms expand most, which expansions correlate with positive vs negative engagement signals), tenant admins cannot prioritise glossary curation. High-impact terms and low-quality terms look identical to the admin.

**Remediation:**

- E1, E2: User-visible expansion indicator (Phase 2 UI)
- E2: Case-sensitivity rules for short common words (Phase 1 algorithm hardening)
- E3: Expansion analytics dashboard (Phase 2)

---

## 3. Personalization

**Definition:** Is the experience tailored to the specific user, tenant, or context?

**Current State Score: 7/10**

**What works:**
Glossary pre-translation is inherently personalized at the tenant level — each tenant's glossary is completely isolated, and a term that expands for Tenant A has zero effect on Tenant B. This is the correct baseline for enterprise multi-tenancy: personalization begins with tenant isolation.

The feature also delivers indirect user-level personalization: when different user groups (HR, IT, Finance) submit queries, their domain-specific terms expand correctly for their context, because the glossary captures cross-functional vocabulary.

**What is missing (gap score: -3):**

**Gap P1: No per-agent glossary scoping (HIGH)**
The same glossary is applied to all agents within a tenant. If the HR agent and the IT agent share a glossary, "PO" might expand to "Performance Objective" for an IT user who meant "Purchase Order." Cross-agent acronym conflicts silently corrupt responses.

This is especially acute for large enterprises with multiple distinct business units, each using overlapping acronym spaces with different meanings.

**Gap P2: No user-group level personalization (MEDIUM)**
A junior analyst and a compliance officer may use the same acronym to mean different things. The glossary has no mechanism to scope a term to a specific user role or department. All users within a tenant share the same expansion behavior.

**Gap P3: No personalization by query history (LOW)**
If a user has previously clarified "when I say 'AWS' I mean 'Annual Wage Supplement, not Amazon Web Services'," this signal is not captured or used to influence future expansions for that user.

**Remediation:**

- P1: Per-agent glossary scoping (Phase 2 — `agent_id` context added to GlossaryExpander)
- P2: Role-scoped terms, off by default, admin-configurable (Phase 2)
- P3: User-preference layer for term disambiguation (Phase 3+, complex)

---

## 4. Connection

**Definition:** Is the glossary connected to external data sources, reducing manual maintenance burden?

**Current State Score: 3/10**

**What works:**
CSV import allows bulk loading of terms from existing documents. This is the only external connection currently available. It reduces the glossary-building effort from months of manual entry to hours of import and review.

**What is missing (gap score: -7):**

**Gap C1: No live sync with authoritative terminology sources (CRITICAL)**
Enterprises often have authoritative terminology sources: a corporate style guide, a regulatory glossary from a compliance body, an HR system with canonical job title abbreviations. None of these can push updates to the mingai glossary automatically. When a regulatory body changes an abbreviation or a company renames an internal product, the glossary goes stale silently.

**Gap C2: No connection to SharePoint / Google Drive document corpus (HIGH)**
The platform indexes documents from SharePoint and Google Drive. These documents contain the full-form terms alongside the acronyms. A "discover terms from documents" feature could auto-suggest glossary entries by finding patterns like "Annual Wage Supplement (AWS)" in indexed documents — a term extraction pipeline that seeds the glossary from the knowledge base itself.

This would eliminate the cold-start problem for new tenants and reduce ongoing maintenance burden for all tenants.

**Gap C3: No API for programmatic glossary management (HIGH)**
Enterprise IT teams often want to manage glossary terms programmatically — synced from an internal knowledge management system, generated from a legal/compliance database, or updated via a CI/CD pipeline when a product is renamed. There is no REST API for glossary CRUD operations.

**Gap C4: No webhook for glossary change events (LOW)**
When a glossary term is added, modified, or deleted, downstream systems (analytics, monitoring) receive no notification. This prevents integration with enterprise governance workflows that require approval audit trails.

**Remediation:**

- C1: Webhook-based push sync from external sources (Phase 2)
- C2: Document corpus term extraction pipeline (Phase 2)
- C3: REST API for glossary management (Phase 2)
- C4: Event webhooks for glossary changes (Phase 3)

---

## 5. Collaboration

**Definition:** Do multiple stakeholders contribute to a shared knowledge resource that benefits all users?

**Current State Score: 6/10**

**What works:**
The glossary is fundamentally a collaborative resource: any tenant admin can add terms, and all end users benefit from those contributions. A compliance officer adds a regulatory term; every employee querying about that regulation benefits from correct interpretation. This is genuine, platform-mediated collaboration across roles.

The multi-admin model (multiple tenant admins can manage the glossary) allows different domain experts to own their respective vocabulary domains within a shared resource.

**What is missing (gap score: -4):**

**Gap L1: No end-user contribution pathway (HIGH)**
End users (the people who actually encounter missing or incorrect terms during queries) have no mechanism to flag a term as missing, report a bad expansion, or suggest a new term. The contribution loop runs exclusively through admins, who are rarely the ones discovering gaps in real use.

A "flag this term" or "suggest a term" UI would connect the people closest to the problem (end users) with the people who can fix it (admins).

**Gap L2: No approval workflow for new terms by default (MEDIUM)**
Multiple admins can add terms without oversight. In regulated industries (banking, healthcare, legal), unvetted terminology additions could introduce compliance risks if a wrong full_form is added for a regulatory abbreviation. An optional approval workflow (any admin can add, a designated "glossary owner" must approve) is missing.

**Gap L3: No change history or term ownership tracking (MEDIUM)**
When a term is wrong or causes a bad expansion, there is no audit trail to understand who added it, when, and why. This makes glossary quality management reactive (fixing problems after they surface) rather than proactive (reviewing recent additions before they affect users).

**Gap L4: No cross-tenant collaboration mechanism (LOW)**
Industry peers (two banks using mingai) cannot share glossary insights. This is intentional for data isolation, but an opt-in industry template contribution mechanism (anonymised, aggregated) would accelerate glossary quality across the platform.

**Remediation:**

- L1: End-user "report expansion issue" or "suggest term" CTA in chat (Phase 2)
- L2: Optional approval workflow, off by default (Phase 1 — already in 80/15/5 mapping as 15%)
- L3: Term change history and author tracking (Phase 2)
- L4: Industry template contribution (Phase 3+)

---

## 6. Gap Priority Matrix

| Gap ID | Description                                          | Impact | Effort | Priority | Phase |
| ------ | ---------------------------------------------------- | ------ | ------ | -------- | ----- |
| C1     | No live sync with external terminology sources       | HIGH   | HIGH   | P1       | 2     |
| E1     | Expansion invisible to users — no feedback loop      | HIGH   | MEDIUM | P1       | 2     |
| E2     | Bad expansions degrade engagement with no correction | HIGH   | LOW    | P1       | 1     |
| L1     | No end-user contribution / flagging pathway          | HIGH   | LOW    | P1       | 2     |
| P1     | No per-agent glossary scoping                        | HIGH   | MEDIUM | P1       | 2     |
| C2     | No auto-term discovery from document corpus          | HIGH   | HIGH   | P2       | 2     |
| C3     | No REST API for programmatic glossary management     | HIGH   | MEDIUM | P2       | 2     |
| A2     | Cold-start problem for new tenants                   | HIGH   | MEDIUM | P2       | 2-3   |
| E3     | No per-term engagement analytics                     | MEDIUM | MEDIUM | P3       | 2     |
| L2     | No approval workflow for term additions              | MEDIUM | LOW    | P3       | 1     |
| L3     | No term change history / audit trail                 | MEDIUM | LOW    | P3       | 2     |
| P2     | No user-group level personalization                  | MEDIUM | HIGH   | P4       | 3     |
| A1     | No feedback when expansion fails (unmatched term)    | MEDIUM | MEDIUM | P4       | 2     |
| C4     | No webhooks for glossary change events               | LOW    | LOW    | P5       | 3     |
| L4     | No cross-tenant collaboration mechanism              | LOW    | HIGH   | P5       | 3+    |
| P3     | No user-history personalization for disambiguation   | LOW    | HIGH   | P6       | 3+    |

**Priority matrix key:**

- P1: High impact, address in next release cycle
- P2: High impact, plan for following cycle
- P3-P4: Medium priority, backlog
- P5-P6: Low priority, future roadmap

---

## 7. Network Effect Scorecard

| Network Behavior | Score      | Ceiling   | Delta    | Top Gap                             |
| ---------------- | ---------- | --------- | -------- | ----------------------------------- |
| Accessibility    | 8/10       | 10/10     | -2       | Cold-start problem (A2)             |
| Engagement       | 7/10       | 10/10     | -3       | Expansion invisible to users (E1)   |
| Personalization  | 7/10       | 10/10     | -3       | No per-agent scoping (P1)           |
| Connection       | 3/10       | 10/10     | -7       | No external source sync (C1)        |
| Collaboration    | 6/10       | 10/10     | -4       | No end-user contribution (L1)       |
| **Overall**      | **6.2/10** | **10/10** | **-3.8** | Connection is the weakest dimension |

**Key finding:** Connection is the dominant gap. The glossary is a closed, manually maintained system with no integration into the enterprise's existing terminology infrastructure. Until the glossary can pull from authoritative external sources (C1, C2, C3), it will require disproportionate admin effort, limiting adoption and depth in large enterprise tenants.
