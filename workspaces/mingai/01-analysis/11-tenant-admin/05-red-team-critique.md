# 11-05 — Tenant Admin: Red Team Critique

**Date**: 2026-03-05
**Method**: Maximum adversarial pressure. Every claim tested against enterprise deployment reality. No credit given for aspirational statements.

---

## Executive Verdict

**The tenant admin analysis is optimistic to the point of misrepresentation.**

Three foundational assumptions are false: (1) that a "non-technical admin" persona capable of self-service AI deployment exists in enterprise, (2) that "< 1 hour" setup claims survive enterprise procurement and IT approval processes, and (3) that Agent Studio will see meaningful adoption when the target user does not exist at scale. The underlying product value is real — the claims around it are not.

**AAA Recalibration**:

- Current state (no product): **1.7/10**
- Phase 1 complete (workspace + SharePoint + user management): **3.0/10**
- Phase 3 complete (SSO + RBAC + glossary): **5.5/10**
- Phase 5 complete (full vision): **7.7/10**

---

## Risk Register

### CRITICAL Risks

---

**R01 — Microsoft distribution moat makes displacement near-impossible**

**Claim attacked**: "mingai wins when: Organization wants custom agent behaviors (Copilot is fixed)"

**Reality**: Microsoft's distribution advantage is not a product gap — it is a structural barrier. Copilot is already licensed for >80% of Fortune 1000 organizations through existing M365 E3/E5 agreements. The CISO does not approve a new AI vendor when Copilot already satisfies the InfoSec checklist (data residency, DLP, eDiscovery, Purview integration). The buying decision is made at the Microsoft account level, not the department head level.

**The moat**: Not product features. Procurement relationships. IT admin familiarity. Single-vendor security review. Zero marginal cost (already paying). The competitive analysis correctly identifies when mingai wins — but those scenarios represent <5% of the Fortune 1000 addressable market.

**Impact**: Primary ICP displacement strategy is flawed for large enterprise. The true ICP is mid-market SMB (100-500 employees), Google Workspace-first organizations, and organizations not yet standardized on M365. The analysis treats large enterprise as the primary market; it should treat it as aspirational.

**Severity**: CRITICAL — affects addressable market sizing, ICP definition, and GTM strategy

**Action Required**: Restate ICP as mid-market Google Workspace organizations. Remove large Fortune 1000 enterprise from primary TAM calculation.

---

**R02 — The "non-technical admin" persona does not exist at scale**

**Claim attacked**: "A knowledge manager or IT admin with no AI expertise can deploy, configure, and maintain an AI workspace without filing engineering tickets."

**Reality**: In enterprise organizations large enough to need AI workspace governance (>200 employees), IT decisions are made by IT departments with change management processes. The "knowledge manager who also configures SSO and writes RBAC rules" is a startup persona, not an enterprise persona.

**Evidence**:

- SSO configuration (SAML 2.0, OIDC) requires the IdP administrator — typically an IAM or Identity team with a 3-10 business day ticket queue
- Azure Entra App Registration requires either a Global Administrator or an Application Administrator — roles that are controlled by IT security
- Google DWD grant requires a Super Administrator in Google Workspace — a tightly guarded role, not a knowledge manager role
- RBAC design (which roles access which KBs) requires input from compliance, HR legal, security — not a single admin

**The actual persona that will use this product**:

- Persona A (real): IT admin delegated to operate a departmental AI tool. They will configure SSO, connect SharePoint, and manage users. They will NOT build agents or manage glossaries.
- Persona B (aspirational): Knowledge manager who builds agents and manages organizational terminology. This person does not exist with sufficient frequency in enterprises to validate Agent Studio investment.

**Severity**: CRITICAL — the entire Agent Studio section of the plan (Phase C, weeks 15-22) is built on an unvalidated persona.

**Action Required**: Conduct 5-10 customer discovery interviews with actual IT admins and knowledge managers before investing in Agent Studio. Gate Phase C on persona validation.

---

**R03 — RBAC enforcement gap creates a data breach scenario**

**Claim attacked**: "Control both which knowledge an agent can access AND which users can access which agents — from a single interface."

**Reality gap**: The USP is correct that the architecture CAN enforce dual-layer RBAC. The risk is in implementation: if KB access control is enforced at assignment time (when the admin configures it) rather than at query time (when the user executes it), a misconfigured agent leaks sensitive KB content to unauthorized users.

**Attack scenario**:

1. Admin creates Agent Y (HR Policy) and assigns it KB Z (HR documents) with access restricted to HR group
2. Admin accidentally assigns Agent Y to "All Users" instead of "HR Group"
3. Every employee can now query Agent Y, which draws from the HR-restricted KB Z
4. Sensitive HR data (compensation bands, PIPs, terminations) is exposed to all employees

**Why this is likely**: The admin interface separates agent access control from KB access control. A misconfiguration in one does not automatically correct the other. The data shows that >60% of cloud misconfiguration incidents involve access control assignments that were "correct at configuration time but wrong in context."

**The fix**: Enforce KB access at query time via JWT claims, not assignment time. When a user queries Agent Y, the system must verify: (1) user has access to Agent Y AND (2) user has access to KB Z. If either check fails, the query is blocked. This is described in Plan 06 but not in the architecture spec.

**Severity**: CRITICAL — this is a data breach waiting to happen if implementation skips query-time enforcement

**Action Required**: Mandate query-time double-check (agent access + KB access) in the API layer specification. Write an automated test that specifically validates this enforcement path.

---

### HIGH Risks

---

**R04 — "< 1 hour" setup time is dishonest; enterprise reality is 3-7 business days**

**Claim attacked**: "SSO: tenant admin completes SAML/OIDC config in < 2 hours following the in-app wizard" and "SharePoint: permission provisioning wizard... < 1 hour"

**Enterprise approval chain reality**:

1. SAML/OIDC config requires IdP admin (IAM team ticket: 3-5 business days)
2. Azure App Registration requires Application Administrator role (IT Security approval: 1-3 business days)
3. Sites.Read.All admin consent requires Global Administrator (separate approval: 1-2 business days)
4. GDrive DWD requires Super Administrator (most restricted role in Workspace: 1-3 business days)
5. New vendor approval in enterprise: security review, DPA signing, procurement PO: 2-6 weeks

**Actual timeline for a mid-sized enterprise (500-2000 employees)**: 1-3 weeks from decision to deployed AI workspace. For large enterprise (10,000+ employees): 4-8 weeks.

**Why this matters**: Sales conversations that promise "< 1 hour" lead to customer disappointment and churn when the enterprise IT approval process takes 3 weeks. The product documentation should set honest expectations.

**Revised claim**: "The technical steps take < 2 hours. Enterprise approval processes typically add 1-3 weeks depending on your IT governance structure. We provide a setup checklist to run approvals in parallel."

**Severity**: HIGH — sales and onboarding credibility risk; churn driver when reality doesn't match promise

---

**R05 — Glossary context injection blows the token budget at any meaningful scale**

**Claim attacked**: "500-term glossary... organization-specific AI accuracy without prompt engineering"

**Math**:

- 500 terms × 200 characters/term = 100,000 characters ≈ 25,000 tokens
- Professional tier context budget (margin-critical): ≤2,000 tokens per query
- Injecting 500 terms consumes 12.5× the entire query budget

**Even filtered injection is risky**:

- If relevance filtering selects 50 terms per query: 50 × 200 chars = 10,000 chars ≈ 2,500 tokens
- This alone exceeds the Professional tier budget before any user query, retrieved context, or system prompt

**The fix requires re-architecture**:

- Hard cap: maximum 20 terms injected per query
- Relevance filter: only inject terms that appear in the query OR retrieved context (not just "related terms")
- Term compression: enforce 80-character maximum per term (not 200)
- Measurement gate: track average glossary injection tokens per query; alert when exceeding 800 tokens

**Severity**: HIGH — without token budgeting, glossary injection makes the Professional tier economically unviable

---

**R06 — Agent Studio adoption will be <5% without the knowledge manager persona**

**Claim attacked**: "Knowledge managers can build custom AI agents using a visual configuration interface — system prompt, KB attachment, guardrails, testing — without writing code."

**Reality**: Building a production-quality AI agent requires:

1. Understanding prompt engineering (system prompts, temperature, guardrails)
2. Understanding retrieval (which KBs to attach, retrieval parameters)
3. Understanding failure modes (hallucination, prompt injection, scope creep)
4. Testing methodology (what constitutes a passing agent test?)

None of these skills are in the job description of a knowledge manager. The Agent Studio UI simplifies the interface, not the cognitive work. The persona who can actually use Agent Studio is a "technical knowledge manager" — someone who exists in AI-forward organizations but represents <5% of enterprise IT orgs today.

**Evidence from analogous tools**: Copilot Studio adoption in enterprises with Power Platform investment sits at ~12% of licensed users after 2 years. Majority use is by technically inclined employees, not knowledge managers.

**Severity**: HIGH — over-investment in Agent Studio (Phase C, 7 weeks) for <5% usage

---

**R07 — Google Drive DWD documentation underestimates enterprise resistance**

**Claim attacked**: "Google DWD setup guide embedded in the UI — < 1 hour for Workspace admins"

**Enterprise reality**:

1. DWD requires Super Administrator. Most enterprise Workspace orgs have 2-5 Super Admins, all in IT Security.
2. DWD grants an application access to ALL users' data (not just the sync service user's data). Enterprise security teams treat DWD as a highest-risk permission grant.
3. The scope includes `https://www.googleapis.com/auth/drive.readonly` — security teams see "read all Drive data" and escalate to CISO review.
4. In heavily regulated industries (financial services, healthcare, legal), DWD approval may require a formal security exception signed by the CISO. Timeline: 4-8 weeks.

**The 31-tenant-admin-capability-spec.md correctly documents the steps but not the organizational friction.**

**Severity**: HIGH — Google Drive integration may be blocked in regulated industries; this affects TAM for that segment

---

**R08 — Sync failure error messages are non-actionable for non-technical admins**

**Claim attacked**: Gap 2 in the platform model analysis acknowledges this. The gap is understated.

**Reality of sync failures**:

- "Permission denied" — requires knowing which service account needs which permission on which SharePoint site
- "Rate limited" — requires understanding Microsoft Graph API throttling policies
- "Index quota exceeded" — requires knowing Azure AI Search pricing tiers
- "Document too large" — requires knowing the chunking strategy to understand why a 50MB PDF fails
- "Encoding error" — requires developer intervention

**None of these failures are diagnosable by a non-technical admin without detailed engineering guidance that goes beyond what any wizard can provide.** The "actionable failure diagnosis" claim is achievable only for the subset of errors with known, scripted fixes (e.g., "permission denied on site X — re-run permission wizard for this site").

**Severity**: HIGH — admin satisfaction is heavily influenced by sync failure UX; poor failure UX triggers support tickets and churn

---

**R09 — SAML configuration requires IdP admin, not tenant admin**

**Claim attacked**: "SSO: tenant admin completes SAML/OIDC config in < 2 hours following the in-app wizard"

**Reality**: The tenant admin fills in fields in the mingai console. But the other half of SAML configuration happens in the IdP (Azure Entra, Okta, Google Workspace). That half requires the IdP administrator:

- Creating an Enterprise Application in Entra ID with correct reply URLs, SAML signing certificates, and attribute claims
- Creating an Application in Okta with SAML 2.0 settings
- Creating a SAML app in Google Workspace Admin Console

The IdP admin is almost never the same person as the tenant admin. The configuration requires coordination between two different IT roles. The "< 2 hours" claim assumes both roles are one person — valid for a 20-person startup, not for a 200+ person enterprise.

**Severity**: HIGH — primary deployment blocker for enterprise customers

---

**R10 — No fallback when SSO provider is down**

**Claim attacked**: The SSO section describes JIT provisioning and group sync but does not address IdP unavailability.

**Scenario**: Enterprise IdP goes down (Entra outages: ~4x/year; Okta outages: ~2x/year). All tenant users who rely on SSO cannot log in. The tenant admin cannot override this. Users cannot access agents they need for work.

**Required**: Emergency admin access with username/password bypass + audit log. "Break glass" account for operational continuity.

**Severity**: HIGH — operational reliability during IdP incidents

---

**R11 — Audit log does not capture what matters to compliance teams**

**Claim attacked**: "Audit log captures every configuration change with actor and timestamp"

**What compliance teams (SOC 2, ISO 27001, HIPAA) actually require**:

- Every user query (not just admin config changes)
- The exact documents retrieved for each query (data lineage)
- User access grants and revocations with approver identity
- Agent configuration changes with before/after state
- Failed access attempts (who tried to access what and was denied)
- Data export events

Configuration change logging is 10% of the compliance requirement. The user query audit trail is 90%.

**Severity**: HIGH — SOC 2 Type II audit failure without comprehensive query-level audit log

---

**R12 — Bulk user invite via CSV creates orphaned access assignments**

**Claim attacked**: "Bulk invite CSV → roles + KB assignments in one operation — batch operation"

**Reality**: When users are offboarded from the IdP but NOT removed from the mingai CSV-assigned access list, they retain AI access after employment termination. This is an access zombie scenario.

**The fix**: SSO group sync correctly handles this (remove from IdP group → access revoked). But CSV-invited users who were NOT SSO-provisioned create a separate access record that is NOT synced with the IdP. These orphaned records persist until manually deleted.

**Required**: Bulk de-provisioning workflow; reconciliation report between IdP users and mingai users; automated alert when a user has active AI access but no IdP session for >30 days.

**Severity**: HIGH — terminated employee AI access is a security and compliance violation

---

**R13 — The 80/15/5 analysis is aspirational, not descriptive**

**Claim attacked**: "This 80/15/5 split is genuine and strong."

**Counter-argument**: The "80% agnostic" layer includes SSO configuration, SharePoint connection, and Google Drive connection. These are not 80% agnostic — they are 80% structurally identical but 100% organization-specific in execution. Every SharePoint connection has different site URLs, permission structures, and organizational hierarchies. Claiming these are "agnostic" confuses the code structure with the operational reality.

The 15% "self-service configurable" layer includes glossary content and agent configurations — these are 100% organization-specific and represent the majority of the ongoing operational work, not 15% of it.

**Actual split**:

- 60% reusable infrastructure (sync pipelines, RBAC middleware, SSO handlers)
- 35% organization-specific configuration that must be done for every tenant
- 5% bespoke customization

**Severity**: MEDIUM — affects investor/customer communication and onboarding time estimates

---

**R14 — Agent template library creates false quality expectations**

**Claim attacked**: "Agent adoption from library: browse, fill variables, publish — < 30 minutes"

**Reality**: A template with pre-defined system prompts was written for a generic version of the use case. When a tenant fills the variables and publishes, the resulting agent:

- Uses the generic system prompt written by platform admin
- Queries the tenant's actual documents (which may be poorly structured)
- Responds with terminology that may not match the organization's glossary (if glossary is not yet configured)

The template creates an expectation of production-quality output. The actual first-run experience is often "the AI gives wrong answers about our company." This generates support tickets, not adoption.

**Required**: Templates must include an explicit "test before publishing" gate, not just a test harness. Publishing should require at least 5 test queries with positive rating before enabling for users.

**Severity**: MEDIUM — agent adoption friction, support ticket driver

---

**R15 — No rate limiting on the tenant admin API surface**

**Claim attacked**: The plan does not address rate limiting on admin APIs.

**Scenario**: A misconfigured automation (or a compromised tenant admin credential) triggers bulk user invites, bulk KB assignments, or bulk agent deployments. Without rate limits, this can saturate the provisioning pipeline, affect other tenants, and create billing anomalies.

**Required**: Per-tenant admin API rate limits (e.g., max 100 user invites/minute, max 10 KB connections/hour, max 5 agent deployments/hour).

**Severity**: MEDIUM — operational reliability and multi-tenant isolation risk

---

**R16 — Satisfaction score is gameable by disabling feedback collection**

**Claim attacked**: "Per-agent satisfaction collected at the response level"

**Scenario**: An agent configured with controversial or low-quality content will generate negative satisfaction scores. If the tenant admin can disable satisfaction collection per-agent (or if users stop rating), the metric becomes meaningless.

**Required**: Platform admin can see per-tenant feedback collection rates. Tenants with <20% feedback collection rate receive an alert ("Your feedback collection is low — satisfaction data may be unreliable").

**Severity**: MEDIUM — platform analytics quality

---

**R17 — Google Drive OAuth (non-DWD) creates token refresh dependency**

**Claim attacked**: The analysis presents DWD and OAuth as equivalent alternatives for Google Drive.

**Reality**: DWD grants permanent access via service account. OAuth grants time-limited access via user-approved tokens. OAuth tokens expire (typically 7 days for Google Apps refresh tokens in enterprise). When the token expires:

- The sync service loses access silently (no webhook notification)
- The next sync cycle fails with "token_expired"
- Documents are not indexed until the tenant admin re-authorizes

For enterprise deployments, silent token expiry causing sync failures is a critical operational gap. DWD is the correct architecture for enterprise; OAuth should be deprecated in favor of service account + DWD for all Google Workspace customers.

**Severity**: MEDIUM — operational reliability for OAuth-based Google Drive connections

---

**R18 — No tenant-level sync pause for document store migrations**

**Claim attacked**: The sync monitoring dashboard surfaces failures but cannot pause sync for planned migrations.

**Scenario**: A company is migrating from SharePoint Online to SharePoint Premium. During migration, they need to pause sync to prevent the AI from indexing partially migrated documents (which would degrade response quality). There is no sync pause mechanism.

**Required**: Per-source sync pause/resume with optional re-index trigger. Estimated build: 2 sprints.

**Severity**: MEDIUM — operational requirement for organizations doing document store migrations

---

**R19 — Issue queue ownership is ambiguous for multi-admin tenants**

**Claim attacked**: The issue queue is described as the tenant admin's responsibility.

**Reality**: Larger tenants may have 3-5 tenant admins (IT admin, knowledge manager, HR admin, etc.). When a user reports an issue, which admin receives it? If all admins receive all issues, a user complaint about HR agent content is visible to the IT admin who should not see HR-sensitive feedback. If routing is not configured, issues fall through the cracks.

**Required**: Issue routing rules (e.g., route HR agent issues to HR admin, SharePoint sync issues to IT admin). Default: route all issues to all admins (with note that routing can be configured).

**Severity**: MEDIUM — operational workflow for multi-admin tenants; compliance risk for sensitive issue content

---

**R20 — No data retention policy for user queries and feedback**

**Claim attacked**: The plan describes audit log and feedback collection but does not address data retention.

**Reality**: User queries contain organizational data, potentially including personal data (GDPR Article 4). Retention of user query logs beyond what is necessary for the stated purpose (quality monitoring) may violate GDPR's data minimization principle. There is no stated retention period in the analysis.

**Required**: User query logs: default 90-day retention, configurable per-tenant. User feedback: default 1-year retention. Admin audit log: minimum 7-year retention (financial compliance). Explicit GDPR Article 17 deletion workflow.

**Severity**: MEDIUM — GDPR compliance gap affecting EU market

---

## Recommended MVP Scope (Red Team Perspective)

The current Phase A plan attempts to build 3 domains in 6 weeks:

- Workspace activation
- User management
- Document store connectors (SharePoint + Google Drive)

**Red team recommendation: reduce to 3 capabilities, defer Google Drive**

**Phase A MVP (weeks 1-6)**:

1. Workspace setup (name, branding, timezone) — 2 days
2. User management (invite, roles, suspend, delete) — 5 days
3. SharePoint connection (Entra app, sync, monitoring) — 10 days
4. Basic user access to at least one connected KB — 3 days

**Defer**:

- Google Drive connection (DWD approval friction blocks fast pilots)
- SSO (requires IAM team involvement; gate on customer request)
- Glossary (gate on Phase B, after token budget architecture is solved)
- RBAC granularity (start with workspace-wide access, add granularity in Phase B)

**Rationale**: The first paying customer needs one working document source and working user management. Adding Google Drive in Phase A duplicates integration complexity without doubling customer value. SharePoint covers >70% of enterprise document stores.

---

## Priority Action Items

1. **[P0] Validate Persona B (knowledge manager as agent builder)** — 5-10 customer interviews before investing in Agent Studio. Gate Phase C entirely on this validation.

2. **[P0] Implement query-time RBAC enforcement** — Do not ship KB access control without query-time JWT claim verification. This is a data breach risk.

3. **[P0] Revise all "< 1 hour" claims to "< 2 hours of technical work + 1-3 weeks of enterprise approvals"** — In all customer-facing materials and sales collateral.

4. **[P1] Design glossary token budget** — Maximum 20 terms per query, 80 chars per term, relevance-filtered. Alert when injection exceeds 800 tokens.

5. **[P1] Add break-glass admin access** — Username/password bypass with MFA for IdP outage scenarios. Required for operational reliability SLA.

6. **[P1] Restate ICP** — Primary ICP: mid-market (100-500 employees), Google Workspace-first, non-M365 standardized. Remove Fortune 1000 from primary TAM.

7. **[P1] Defer Google Drive to Phase B** — Reduce Phase A scope to SharePoint + user management. Fast-track first customer pilots.

8. **[P2] Define comprehensive audit log scope** — Must include user query events, document retrieval records, and access attempt failures for SOC 2 compliance.

9. **[P2] Add SSO group/user reconciliation report** — Weekly report of users with AI access but no active IdP session (access zombie detection).

10. **[P2] Implement data retention policy** — 90-day default for user queries, 7-year for admin audit logs, GDPR deletion workflow.

---

---

## Red Team Round 2 — Architecture Review (R21-R27)

_Source: Deep analysis of `33-agent-library-studio-architecture.md`, `34-rag-quality-feedback-architecture.md`, and `06-tenant-admin-plan.md`. These risks are NEW — not covered in R01-R20._

---

**R21 — Confidence score formula is scientifically indefensible and will corrupt tenant admin decisions**

**Claim attacked**: USP 3 ("AI Quality Ownership") is built on the confidence score surfaced to tenant admins in the quality dashboard.

**Reality**: The formula in doc 34 measures retrieval quality (vector similarity), not answer quality (factual accuracy). A response can score 0.92 confidence while being factually wrong if the retrieved chunk was semantically similar but topically misleading. Additionally: (a) source diversity is rewarded regardless of document quality — 3 low-quality files score higher than 1 authoritative canonical document, which is the standard enterprise pattern; (b) coverage ratio rewards verbosity — long rambling responses score higher than concise correct ones.

**Impact**: The alert system and the entire satisfaction-to-root-cause correlation feature are built on this score. Corrupt input → corrupt diagnosis → tenant admin takes wrong corrective action (adds documents that are not the problem, changes glossary terms that are not the cause). The USP differentiator becomes a misinformation loop.

**Severity**: CRITICAL — USP 3 validity depends on score reliability

**Action Required**: Caveat the score as a "retrieval confidence proxy" in the UI, not "answer quality". Add LLM-as-judge faithfulness evaluation as Phase 4 upgrade (score answer faithfulness against retrieved context). Do not ship as a standalone quality signal without user testing to validate it correlates with human ratings.

---

**R22 — Coverage gap detection requires query volumes that will not exist at launch**

**Claim attacked**: Coverage gap detection surfaces actionable KB improvement signals.

**Reality**: `MIN_OCCURRENCES_FOR_GAP = 3` over 14 days requires 3+ semantically similar queries at similarity > 0.88 within two weeks. For a 10-query/day agent (realistic for initial tenants), low-confidence responses at 10% = 1/day. The probability of 3 similar queries hitting the same gap within 14 days is statistically very low. The feature will show "No coverage gaps detected" for every small tenant — exactly the customers being onboarded in Phase C.

**Severity**: HIGH — Phase C launches with a feature that silently fails for target customers

**Action Required**: Document minimum volume thresholds for each analytics feature. Show "Not enough data yet (needs ~100 queries)" for small tenants. Lower `MIN_OCCURRENCES_FOR_GAP` to 2, extend window to 30 days for low-volume tenants.

---

**R23 — Agent credential vault: guessable paths, no rotation monitoring, silent pass on missing tests**

**Three issues in doc 33**:

1. Vault path is `{tenant_id}/agents/{instance_id}/{credential_key}` where `credential_key` is the literal name from the public template definition. A compromised admin session can enumerate all credential vault paths by reading the catalog API.

2. Credential test returns `passed=True, message="No credential test available"` when no test class exists. Any template without a credential test silently reports "Connected" when nothing was validated.

3. No scheduled credential health check. Bloomberg API keys, CapIQ credentials, Oracle JWTs all expire. Silent expiry causes agent failures with cryptic errors — not flagged until users start complaining.

**Severity**: HIGH — security vulnerability (1), reliability (2, 3)

**Action Required**: (a) Change missing-test default to `passed=None, message="Credential validation unavailable"` — never silently pass. (b) Add daily scheduled credential health check for all instances with stored credentials. (c) Use opaque vault path identifiers rather than predictable credential key names.

---

**R24 — Glossary token cap has three contradictory specifications**

**Plan 06 Sprint B2**: max 50 terms (keyword match)
**Doc 33 section 4.2 code**: max 20 terms, no character limit in code loop
**Existing red team R05**: max 20 terms, 80 chars/term, 800 token ceiling

Three documents, three different specs. The plan's 50-term × 200-char spec = ~2,500 tokens, which the existing red team already flagged as exceeding the Professional tier margin budget.

**Severity**: HIGH — implementation will use one of these specs inconsistently; guaranteed token budget overrun in some configurations

**Action Required**: Create a single authoritative glossary injection specification (can be a section in doc 31 or doc 23). Lock in: 20 terms max, 80 chars/definition, relevance-filtered by query embedding similarity (not keyword match), hard 800-token ceiling with measurement. Reference this single spec from the plan, the architecture doc, and the RAG pipeline.

---

**R25 — 5-minute batch aggregation creates write amplification storm on Cosmos DB**

**Architecture (doc 34 section 2.2)**: Aggregation worker runs on a 5-minute timer, updating all agent_stats and kb_stats documents for all tenants — even when zero new events arrived in the window.

At 50 tenants × (5 agents + 3 KBs) = 400 Cosmos DB upserts every 5 minutes regardless of activity. At 200 tenants this is 1,600 upserts per cycle = constant write load on Cosmos DB even during zero-usage off-hours.

**Severity**: MEDIUM — operational cost and scale risk

**Action Required**: Switch to event-driven aggregation (update stats only when new events arrive), with a 30-second coalescing buffer. Add a "no events, no update" guard. Add crash recovery by replaying unacknowledged Redis Stream entries.

---

**R26 — Agent Studio test mode enables unaudited user impersonation and data exfiltration**

**Architecture (doc 33 section 4.1)**: Test mode accepts `test_as_user_id`, executes agent as that user's RBAC context, and explicitly does NOT write to conversation history ("no audit trail").

Combined effect: a tenant admin can impersonate any user, query KBs restricted to that user's role, read sensitive content, and leave zero trace. This is exactly the data exfiltration vector that SOC 2 Type II audits test for (R11 in the existing critique flagged the audit log gap; this is the attack vector that exploits it).

**Severity**: HIGH — SOC 2 blocker; exploitable in multi-admin tenants where IT admin should not see HR content

**Action Required**: (a) Test mode queries MUST be written to the audit log with `mode: test` flag and the admin's actual identity. (b) Restrict `test_as_user_id` to: self, or a synthetic test role (not real user impersonation). If real user impersonation is needed for debugging, require platform admin approval and log it.

---

**R27 — Phase C has a 7-week blocking dependency on platform admin templates with no fallback**

**Plan (section 9 dependencies)**: Phase C Sprint C1 (Agent Library) requires platform admin to have published agent templates. If platform admin plan is delayed, Sprint C1 has nothing to display.

Three cascading failures:

1. Sprint C1 (weeks 15-17): Agent library browser has zero templates
2. Sprint C2 (weeks 18-20): "Clone from template" workflow is dead
3. Sprint C3 (weeks 21-22): No feedback data because no agents are deployed

The plan has no fallback or mitigation documented.

**Severity**: MEDIUM — 7-week sprint block with no mitigation

**Action Required**: Create 3-5 "seed templates" (HR Policy, IT Helpdesk, General Assistant) as hardcoded platform defaults shipped in the codebase — not dependent on platform admin curation. Gate Sprint C1 on template availability, not calendar weeks. If seed templates are ready early, move Sprint C2 forward to avoid the dependency.

---

## Updated Priority Action Items (including R21-R27)

> **Status as of 2026-03-05**: R21, R22, R23, R24, R25, R26, R27 all remediated in docs 33 v1.1, 34 v1.1, and plan 06. R03 (RBAC enforcement) remains open — it is a platform-level concern addressed in the main RAG pipeline, not in tenant admin console docs.

1. **[P0] R21 — REMEDIATED**: `34-rag-quality-feedback-architecture.md` v1.1 §1.2 — confidence score labeled as "retrieval confidence proxy" throughout; LLM-as-judge `answer_faithfulness_score` added as Phase 4 addition; UI label changed from "high confidence" to "high retrieval confidence".

2. **[P0] R26 — REMEDIATED**: `33-agent-library-studio-architecture.md` v1.1 §4.1 — test mode now writes mandatory audit log with `mode: test`; `test_as_user_id` restricted to requesting admin's own ID or synthetic test role.

3. **[P0] R03 — OPEN**: Query-time RBAC enforcement (existing priority — confirmed critical by doc 33 architecture §4.3 — implementation in main RAG pipeline, not tenant admin plan scope).

4. **[P1] R24 — REMEDIATED**: `06-tenant-admin-plan.md` §4.2 — canonical spec locked: 20 terms injected per query (relevance-ranked by embedding similarity), 200 chars/definition, 800-token ceiling for glossary block; R03 risk register updated to match. Old "50 terms" figure is explicitly superseded.

5. **[P1] R23 — REMEDIATED**: `33-agent-library-studio-architecture.md` v1.1 §8 — `CredentialTestResult.passed` defaults to `None` (not `True`) for missing test classes; §8.1 added daily credential health check job with admin notification on failure.

6. **[P1] R22 — REMEDIATED**: `34-rag-quality-feedback-architecture.md` v1.1 §3.3 — `CoverageGapDetector` docstring explicitly notes the volume threshold requirement and specifies "Not enough data to detect coverage gaps yet" dashboard state for small tenants.

7. **[P2] R27 — REMEDIATED**: `06-tenant-admin-plan.md` Sprint C1 — 4 seed templates (`tmpl_seed_hr_policy`, `tmpl_seed_it_helpdesk`, `tmpl_seed_procurement`, `tmpl_seed_onboarding`) now shipped in codebase as `status: seed`, removing 7-week platform admin dependency.

8. **[P2] R25 — REMEDIATED**: `34-rag-quality-feedback-architecture.md` v1.1 §2.2 — aggregation changed from 5-minute timer poll to event-driven with 30-second coalescing buffer; `CoverageGapDetector` only triggers when low-confidence events exist in the batch.

---

## AAA Recalibration Summary

| Phase                                     | Automate | Augment | Amplify | Overall | Gating Condition      |
| ----------------------------------------- | -------- | ------- | ------- | ------- | --------------------- |
| Current (no product)                      | 1.0      | 1.5     | 2.5     | 1.7     | —                     |
| Phase 1 (workspace + SharePoint + users)  | 3.0      | 2.5     | 3.5     | 3.0     | First paying customer |
| Phase 3 (SSO + RBAC + glossary)           | 5.5      | 5.0     | 6.0     | 5.5     | 10+ active tenants    |
| Phase 5 (full vision, agents + analytics) | 7.5      | 8.0     | 7.5     | 7.7     | 50+ active tenants    |

The gap between Phase 1 (3.0) and the analysis vision (7.3) is 4.3 points — 18+ months of product development. Investors and customers should be anchored to Phase 1 reality, not Phase 5 vision.
