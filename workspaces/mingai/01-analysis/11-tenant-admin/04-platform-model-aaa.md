# 11-04 — Tenant Admin: Platform Model & AAA Framework

**Date**: 2026-03-05

---

## 1. Platform Model Analysis

### 1.1 Role Identification

**Producers** — create value that others consume:

- **Platform Admin**: produces LLM profiles, agent templates, the governed tool catalog. These are the foundation the tenant admin builds on top of. Without the platform admin's curation, the tenant admin faces a blank workspace.
- **Tenant Admin**: produces the organizational AI workspace — connects documents, configures glossary, builds agents, sets access rules. This curated workspace is what end users consume.
- **Document Sources** (SharePoint, Google Drive): produce the organizational knowledge that the RAG pipeline indexes and makes queryable.

**Consumers** — receive and use the value:

- **End Users**: consume the AI agents the tenant admin deployed, drawing from the knowledge the tenant admin connected, understood through the terminology the tenant admin documented.
- **Tenant Admin**: consumes platform-admin-curated LLM profiles and agent templates. They do not build AI infrastructure — they configure it.

**Partners** — facilitate transactions:

- **Identity Providers** (Entra ID, Okta, Google): authenticate users; tenant admin delegates identity to them.
- **Microsoft 365** (SharePoint): supplies document content via Graph API; tenant admin grants access.
- **Google Workspace**: supplies document content via Drive API; tenant admin configures sync user.
- **Platform Infrastructure**: Azure AI Search, Cosmos DB, Blob — invisible to tenant admin but critical to the service they deliver.

### 1.2 Core Transactions

Three transactions define the tenant admin's value creation:

**Transaction 1: Knowledge Curation**

```
Tenant Admin (producer) CONNECTS document sources
  → Sync worker INDEXES documents into per-tenant AI Search
  → Tenant Admin MONITORS sync health + fixes failures
  → End User QUERIES the indexed knowledge
  → Satisfaction signals FLOW BACK to tenant admin (which KBs produced good answers?)
```

Value created: organizational knowledge made queryable by AI, updated continuously, with quality visibility.

**Transaction 2: Access Governance**

```
Tenant Admin (producer) CONFIGURES KB access + agent access rules
  → Platform ENFORCES rules at query time (JWT scope + tenant RBAC middleware)
  → End User ACCESSES only the agents and knowledge bases they are authorized for
  → IT Security VALIDATES via audit log (what did who access?)
```

Value created: compliance-safe AI deployment where sensitive knowledge (HR, Legal, Finance) is controlled with the same rigour as the document systems they came from.

**Transaction 3: AI Experience Curation**

```
Tenant Admin (producer) BUILDS or ADOPTS agents
  → Tenant Admin CONFIGURES glossary (organizational context)
  → End User INTERACTS with domain-specific AI that knows their organization
  → Feedback signals FLOW BACK (satisfaction, low confidence, reported issues)
  → Tenant Admin IMPROVES configuration → all users immediately benefit
```

Value created: organizational AI that improves continuously rather than decaying as knowledge becomes stale or agent configurations drift from business needs.

### 1.3 Network Effects

**Same-side (more users → better glossary signals)**:
As more users query the AI, the system surfaces which organizational terms are appearing in queries without glossary coverage ("term miss" signals). More queries → faster discovery of missing glossary entries → better AI for all users. The learning is proportional to query volume.

**Cross-side (platform admin curation → tenant admin quality)**:
The platform admin's template library and LLM profiles are consumed by all tenant admins. When the platform admin improves a template (from cross-tenant analytics), all tenant admins who adopt that template benefit simultaneously. Tenant admin quality is a function of platform admin effort × number of tenants using the templates.

**Data flywheel (within tenant)**:
Each query → confidence score → glossary term usage → KB source quality signal. Over 6+ months, a well-managed tenant accumulates a high-quality glossary, well-tuned agent configurations, and clean knowledge bases. New organizations deploying the same AI platform start from scratch; established tenant admins have compound advantage from accumulated configuration investment.

### 1.4 Network Behavior Coverage

#### Accessibility

**How easily can the tenant admin complete operational transactions?**

- SSO setup: step-by-step wizard with exact IdP navigation instructions, < 2 hours
- SharePoint connection: guided form with specific Azure portal steps — designed for non-engineers
- Google Drive connection: guided form with specific GCP console steps + DWD explanation
- Glossary management: simple CRUD table with bulk import — any admin can use it
- User management: invite by email, role dropdown, KB/agent checkboxes — 5 minutes per user
- Agent adoption from library: browse, fill variables, publish — < 30 minutes
- Agent Studio: structured form with test harness — no AI expertise required, < 2 hours for first agent

**Assessment**: HIGH (target). The core accessibility gap is the document store permission provisioning, which requires non-trivial IT knowledge (Entra App Registration, DWD). The in-product guidance addresses this directly. Without guidance, this step is prohibitively complex for non-IT admins. With guidance, it is achievable in < 1 hour.

#### Engagement

**What information helps the tenant admin complete operations effectively?**

- Sync status dashboard: per-source document counts, freshness, failure list — action-oriented
- Glossary miss signals: which terms appeared in queries without coverage (surface new entries to add)
- User feedback dashboard: satisfaction rate by agent, flagged low-confidence responses
- Issue queue: inbound user reports with context, action buttons (respond, resolve, escalate)
- Engagement analytics: active users per agent, inactive user list, feature adoption rates
- Agent performance comparison: satisfaction before vs after configuration changes

**Assessment**: HIGH. Every metric connects to a concrete action the tenant admin can take. The feedback loop from AI quality to admin action is short and explicit.

#### Personalization

**Is the tenant admin experience tailored to their specific workspace state?**

- Dashboard prioritizes alerts: sync failures above all else, then low satisfaction agents, then inactive users
- Setup wizard remembers progress (can resume if interrupted)
- Agent studio shows recently modified agents first
- Glossary surfaces high-priority miss signals (terms with high query frequency but no coverage)
- Issue queue sorted by unresolved duration (oldest first)

**Assessment**: MEDIUM. Personalization is state-driven (surface what needs attention) but not preference-driven (learn what this admin cares about most). An IT admin cares about SSO and access control; a knowledge manager cares about glossary and agent quality. Current design treats all tenant admins identically.

#### Connection

**What data flows connect the tenant admin to the platform?**

- SharePoint: bidirectional — sync worker pulls documents, webhook receives change notifications
- Google Drive: bidirectional — service account pulls documents, webhook receives Drive change events
- Auth0/Entra (SSO): pulls identity + group attributes on each login
- Satisfaction signals: internal pipeline (user thumbs up/down → confidence scores → admin dashboard)
- Issue reports: internal pipeline (user report → Redis Stream → admin queue)
- Platform notifications: admin receives upgrade alerts, issue routing from platform admin

**Assessment**: HIGH. Multiple bidirectional connections. The SSO connection is particularly strong — group changes in the IdP flow through to AI access permissions automatically.

#### Collaboration

**Can the tenant admin and users work together through the platform?**

- Issue reporting → routing to tenant admin → resolution message back to user (complete loop)
- Access request workflow: user requests access → admin approves/denies → user notified
- Agent feedback: user thumbs up/down → admin sees per-agent quality → improves agent → all users benefit
- Glossary requests: (not yet built) users could suggest terms via in-app report for admin review
- Platform admin communication: platform admin can send notifications to tenant admin; tenant admin can escalate issues back up

**Assessment**: MEDIUM. Forward collaboration (admin configures for users) is strong. Reverse collaboration (users actively contribute to workspace improvement beyond issue reports) is thin. A structured "suggest a term" or "request a new agent" workflow would close this gap.

---

## 2. AAA Framework

### 2.1 Automate — Reduce Operational Costs

| Manual Process Today                          | Automated Replacement                                                   | Cost Saved                                |
| --------------------------------------------- | ----------------------------------------------------------------------- | ----------------------------------------- |
| Manually re-sync documents after changes      | Webhook-driven automatic sync within 15-30 minutes of source changes    | Hours/week → automated                    |
| Manually update access when employees leave   | SSO group removal → next login denied → access revoked automatically    | Manual HR coordination → automated        |
| Check if AI is using up-to-date documents     | Freshness indicator on sync dashboard                                   | Ad-hoc investigation → passive monitoring |
| Follow up with users who reported AI problems | Issue queue with status tracking + notification system                  | Email threads → structured workflow       |
| Export usage reports for department heads     | On-demand analytics dashboard with active users, satisfaction, adoption | Quarterly manual reports → real-time      |
| Add new user + configure all their access     | Bulk invite CSV → roles + KB assignments in one operation               | Per-user manual setup → batch operation   |

**Automation score**: 7/10 — tenant administration is less automatable than platform administration because it involves content curation and organizational judgment (what should be in the glossary? what should the HR agent say?). The operations that CAN be automated (sync, access revocation, notifications) are handled well.

### 2.2 Augment — Reduce Decision-Making Costs

| Decision                                              | Without Console                          | With Console                                          | Quality Improvement           |
| ----------------------------------------------------- | ---------------------------------------- | ----------------------------------------------------- | ----------------------------- |
| "Which agent is underperforming and needs attention?" | Unknown until users complain             | Satisfaction dashboard sorted by lowest performers    | Proactive, not reactive       |
| "Are our documents fresh enough for AI accuracy?"     | Manual investigation of sync status      | Freshness indicator per source with failure list      | Immediate, automatic          |
| "Is the AI missing our terminology?"                  | Random discovery through user complaints | Glossary miss signals: terms queried without coverage | Systematic, data-driven       |
| "Which users aren't using the AI yet?"                | Unknown or manual survey                 | Inactive user list with days-since-login              | Targeted outreach possible    |
| "Did my agent configuration change improve quality?"  | Qualitative impression                   | Before/after satisfaction rate comparison             | Objective, time-bounded       |
| "Which knowledge bases produce the best AI answers?"  | Unknown                                  | Satisfaction signals correlated to source KB          | Data-driven KB prioritization |

**Augmentation score**: 8/10 — every major operational decision has corresponding data that the console surfaces. The tenant admin makes better configuration decisions because they can see the AI's quality indicators, not just usage counts.

### 2.3 Amplify — Reduce Expertise Costs for Scaling

| Scaling Challenge                                                | Without Console                   | With Console                                                                                                 |
| ---------------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Adding 100 new employees requires configuring AI access for each | Per-user configuration            | SSO group sync: add to IdP group → access granted automatically                                              |
| Knowledge base grows from 500 to 5,000 documents                 | Manual re-check of AI quality     | Sync pipeline handles scale automatically; quality dashboard highlights any degradation                      |
| Department head wants a new agent without IT help                | Requires engineering involvement  | Agent Studio: knowledge manager builds + publishes without IT                                                |
| New terminology emerges during product launch                    | Manual prompt engineering         | Glossary: admin adds term → AI uses it in next query                                                         |
| Organization adopts a new policy — all agents need to reflect it | Update each agent individually    | If policy is in the SharePoint document (synced), all agents drawing from that KB reflect it after next sync |
| HR wants AI restricted to HR team only                           | Requires RBAC configuration by IT | Tenant admin configures KB + agent access in the console in < 10 minutes                                     |

**Amplification score**: 8/10 — the SSO group sync + document sync combination means the workspace scales with organizational growth without proportional admin effort. The key leverage: one document added to SharePoint reaches all authorized users through all agents that query that KB.

---

## 3. Synthesis: Platform Readiness Assessment

| Dimension                             | Score      | Rationale                                                                                                       |
| ------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------- |
| Producer-consumer transaction clarity | 8/10       | Three clear transactions with feedback loops                                                                    |
| Network effects                       | 6/10       | Within-tenant data flywheel strong; cross-tenant effects thin (tenant admin doesn't benefit from other tenants) |
| AAA — Automate                        | 7/10       | Sync and access management highly automatable; content curation requires human judgment                         |
| AAA — Augment                         | 8/10       | Strong quality signal surfacing; connects AI performance to admin decisions                                     |
| AAA — Amplify                         | 8/10       | SSO + document sync + template library enable scaling without proportional effort                               |
| Network behaviors                     | 7/10       | High accessibility + engagement + connection; medium personalization + collaboration                            |
| **Overall**                           | **7.3/10** | Strong product-market fit for the enterprise workspace admin persona                                            |

### Critical Observation

The tenant admin console scores lower on network effects (6/10) than the platform admin console (8/10) because tenant admins are isolated from each other — by design, for data privacy. The value accumulates within the tenant rather than across tenants. This is the correct design trade-off, but it means the platform's cross-tenant learning (USP 4 from platform admin analysis) does not benefit the individual tenant admin's experience.

This is partially compensated by the platform admin's template library: cross-tenant agent quality insights improve the templates available to all tenant admins, even though tenant admins cannot directly see each other's data.

### Gaps to Address

**Gap 1: No user-to-admin contribution workflows**
Users have no way to suggest glossary terms, request new agents, or contribute knowledge directly. The content quality improvement loop is one-directional (admin → users). Adding structured user contribution pathways (agent request, term suggestion) would strengthen collaboration.

**Gap 2: Sync failure diagnosis is non-technical but root cause is technical**
When 12 documents fail to sync ("Permission denied"), the tenant admin knows WHAT failed but not HOW to fix it without IT intervention. The console should diagnose the fix, not just the symptom: "These 12 files require your sync service account to be added as a member of the 'Finance Reports' shared drive."

**Gap 3: No AI quality benchmark or baseline**
The tenant admin has no reference for "is 78% satisfaction good?" They have no peer comparison, no benchmark, no historical baseline for their industry. Adding a non-identifiable benchmark ("Average for organizations of your size: 74%") would contextualize quality signals meaningfully.
