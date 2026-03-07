# 06 — Tenant Admin Console: Implementation Plan

**Date**: 2026-03-05
**Depends on**: `01-analysis/11-tenant-admin/` (all 5 files), `01-research/31-tenant-admin-capability-spec.md`, `03-user-flows/12-tenant-admin-flows.md`
**Relationship**: This plan defines the tenant-facing admin interface. It runs in parallel with `05-platform-admin-plan.md` but is conceptually downstream — the platform admin creates the LLM profiles and templates that tenant admins consume.

---

## 1. Scope and Boundaries

### What This Plan Covers

The tenant admin interface — the self-service workspace management console that enables an organization's IT admin, knowledge manager, or department head to:

1. **Workspace Setup** — initial wizard, branding, auth mode
2. **SSO Configuration** — SAML 2.0, OIDC, JIT provisioning, group-to-role sync
3. **Document Store Integration** — SharePoint (Entra App), Google Drive (DWD + OAuth), guided permission provisioning
4. **Sync Monitoring** — health dashboard, failure diagnosis, manual controls
5. **Glossary Management** — term CRUD, bulk import, miss signals, analytics
6. **User RBAC** — invite, role assignment, KB access, agent access, bulk operations
7. **Agent Workspace** — library adoption, Agent Studio authoring, deployment
8. **Feedback Monitoring** — satisfaction dashboard, issue queue, resolution workflow

### What This Plan Does NOT Cover

- The RAG pipeline itself (existing platform)
- Platform admin console (Plan 05)
- End-user chat interface
- Billing (owned by platform admin)

---

## 2. Relationship to Main Roadmap

| Roadmap Phase            | Tenant Admin Touchpoints                                    |
| ------------------------ | ----------------------------------------------------------- |
| Phase 1 (Foundation)     | Basic workspace settings, user invite, KB access assignment |
| Phase 2 (LLM Library)    | LLM profile selector (consume platform-admin profiles)      |
| Phase 3 (Auth)           | SSO configuration wizard, group-to-role mapping             |
| Phase 4 (Agentic)        | Agent library adoption, Agent Studio, feedback monitoring   |
| Phase 5 (Cloud Agnostic) | Cloud-agnostic document store adapters                      |
| Phase 6 (GA)             | Full console polish, guided setup, onboarding wizard        |

---

## 3. Phase Breakdown

### Phase A — Foundation Console (Weeks 1-6)

**Goal**: Tenant admin can activate their workspace, manage users, and see basic workspace status. Every feature here unblocks end-user access.

**Sprint A1 (Weeks 1-3): Workspace Activation and User Management**

Deliverables:

- [ ] Workspace activation flow: accept invite, set password/SSO, workspace name, logo, timezone
- [ ] Tenant admin dashboard: health summary, setup checklist, quick actions
- [ ] User directory: list all users with role, status, last login
- [ ] User invite: single + bulk CSV invite, role assignment
- [ ] Role management: change user role (immediate effect via JWT invalidation)
- [ ] User suspension: block access, preserve data
- [ ] User deletion: remove access, anonymize conversations
- [ ] LLM profile selector: choose from platform-admin-published profiles (no authoring)
- [ ] Basic audit log: admin actions logged and viewable
- [ ] Workspace settings: display name, logo, timezone, locale, notification preferences

**Sprint A2 (Weeks 4-6): Document Store Connection (MVP)**

Deliverables:

- [ ] SharePoint connection: guided wizard with step-by-step Azure permission provisioning instructions, credential entry form, connection test
- [ ] SharePoint site selector: list accessible sites post-connection, multi-select
- [ ] Google Drive connection: DWD path (service account JSON upload + sync user entry) + OAuth path
- [ ] Google Drive folder selector: tree view of accessible drives/folders
- [ ] Basic sync status: per-source: indexed count, last sync time, failed count
- [ ] Manual sync trigger: "Sync Now" button per source
- [ ] Sync failure list: per-file error with system-generated diagnosis and fix suggestion
- [ ] "Add to exclusion list" action for permission-denied files

**Phase A Success Criteria**:

- Tenant admin completes workspace activation in < 30 minutes from receiving invite
- SharePoint connection completed in < 2 hours of technical wizard steps (enterprise IT approvals add 1-3 weeks; communicate this expectation to customers upfront)
- Google Drive OAuth connection completed in < 1 hour following wizard instructions (DWD deferred to Phase B)
- IT admin (no AI expertise) can complete all Phase A tasks without support ticket

---

### Phase B — Intelligence Layer (Weeks 7-14)

**Goal**: The tenant admin can see whether the AI is working well, manage organizational terminology, and control access at a granular level.

**Sprint B1 (Weeks 7-9): SSO and RBAC**

Deliverables:

- [ ] SAML 2.0 configuration wizard: SP metadata download, IdP metadata upload, attribute mapping UI, test login flow
- [ ] OIDC configuration wizard: client credentials entry, auto-discovery, test flow
- [ ] JIT provisioning: auto-create account on first SSO login with configured default role
- [ ] Group-to-role mapping: table UI mapping IdP group names to mingai roles
- [ ] SSO enable/disable toggle: graceful switch between SSO and platform-managed auth
- [ ] KB access control: per-KB visibility mode (workspace-wide / role-restricted / user-specific / agent-only)
- [ ] Agent access control: per-agent visibility mode with same options
- [ ] Access request workflow: enable/disable toggle + approval flow (user requests → admin approves/denies)
- [ ] Access request notification: admin notified of pending requests

**Sprint B2 (Weeks 10-12): Glossary Management**

Deliverables:

- [ ] Glossary CRUD: add, edit, delete terms individually
- [ ] Glossary fields: term, full form, definition (200 char limit), context tags, scope
- [ ] Bulk import: CSV upload with validation, preview, conflict resolution
- [ ] Bulk export: CSV download of all terms
- [ ] Glossary search: full-text search within term + definition
- [ ] Version history: per-term edit history with rollback
- [ ] Glossary miss signals: surface top terms appearing in queries without coverage
- [ ] Character limit enforcement: counter + warning at 180, block at 200
- [ ] Glossary injection integration: terms injected into system message at query time (requires RAG pipeline change)
- [ ] Prompt injection protection: glossary content sanitized before injection

**Sprint B3 (Weeks 13-14): Sync Health and Monitoring**

Deliverables:

- [ ] Sync health dashboard: per-source status cards with freshness indicators
- [ ] Sync schedule configuration: per-source frequency selector (plan-tier limited)
- [ ] Full re-index with cost estimate: shows estimated embedding cost before proceeding
- [ ] Freshness indicator: green/yellow/red based on time since last sync
- [ ] Sync failure detail view: per-file error with root-cause diagnosis
- [ ] Credential expiry monitoring: 30-day warning for SharePoint client secret, OAuth token refresh alerts
- [ ] Reconnect wizard: guided flow to update expired credentials

**Phase B Success Criteria**:

- SSO setup completed in < 2 hours by an IT admin without SSO implementation experience
- Glossary terms active in AI responses within 60 seconds of saving
- Sync failures diagnosed with actionable fix suggestions (no raw API errors shown to admin)
- KB and agent access control changes reflected in user permissions within 60 seconds

---

### Phase C — Agent Workspace (Weeks 15-22)

**Goal**: Tenant admin can deploy agents from the platform library and build custom agents in Agent Studio.

**Sprint C1 (Weeks 15-17): Agent Library Adoption**

> **R27 fix**: Phase C was previously 100% gated on the platform admin publishing templates (a 7-week external dependency with no fallback). Sprint C1 now ships with 3–5 seed templates hardcoded in the codebase to ensure tenant admins can test the Agent Library workflow immediately — independently of platform admin operations.

Deliverables:

- [ ] **Seed templates (shipped in codebase — not platform-admin-dependent)**:
  - `tmpl_seed_hr_policy` — HR policy Q&A (system prompt + KB binding, no external credentials)
  - `tmpl_seed_it_helpdesk` — IT helpdesk assistant (KB binding, standard Q&A)
  - `tmpl_seed_procurement` — Procurement policy assistant (KB binding)
  - `tmpl_seed_onboarding` — Employee onboarding guide (KB binding)
  - Seeds are tagged `status: seed` and automatically visible without platform admin action
- [ ] Agent library browser: filter by category, satisfaction score, plan tier eligibility
- [ ] Template preview: read-only system prompt view, variables list, example conversations
- [ ] Agent deployment form: fill required/optional variables, set name, select KBs, set access control
- [ ] Deployed agent list: all agents in workspace with version, satisfaction summary, status
- [ ] Template upgrade workflow: notification when new version available, upgrade opt-in
- [ ] Agent access control UI: set visibility on deployment (workspace-wide / role / user)
- [ ] Agent test chat: pre-deployment test in admin console before publishing

**Sprint C2 (Weeks 18-20): Agent Studio**

Deliverables:

- [ ] Agent Studio form: name, description, category, avatar selection
- [ ] System prompt editor: large textarea with `{{variable}}` syntax highlighting
- [ ] AI-assisted prompt improvement: optional suggestions surfaced inline
- [ ] Example conversation builder: add up to 5 Q&A pairs
- [ ] KB attachment: select from available workspace KBs; grounded/extended mode toggle
- [ ] Tool enablement: select enabled tools from platform catalog (Professional+ plan only)
- [ ] Guardrail configuration: blocked topics, required elements, confidence threshold, max length
- [ ] Agent test harness: chat interface with "Show sources" toggle, confidence score display
- [ ] Save as Draft / Publish / Unpublish lifecycle
- [ ] Agent duplication: clone existing agent as starting point

**Sprint C3 (Weeks 21-22): Feedback Monitoring**

Deliverables:

- [ ] Satisfaction dashboard: 7-day rolling rate, per-agent breakdown, trend chart
- [ ] Agent performance detail: satisfaction over time, low-confidence responses list, guardrail trigger log
- [ ] Root cause correlation: connect satisfaction drop to sync freshness change (timestamp comparison)
- [ ] Issue queue (tenant view): reports routed from platform admin + tenant-config issues
- [ ] Issue response workflow: respond to reporter, resolve with note, escalate to platform
- [ ] Glossary performance analytics: per-term satisfaction comparison (with vs without term)
- [ ] User engagement analytics: DAU/WAU/MAU per agent, inactive users, feature adoption

**Phase C Success Criteria**:

- Agent deployed from library in < 30 minutes (including variable configuration)
- Custom agent created in Agent Studio and published in < 2 hours for a non-technical admin
- Satisfaction dashboard shows meaningful data within 48 hours of agent being used
- Root cause diagnosis surfaces a fix suggestion for satisfaction drops caused by stale sync

---

### Phase D — Polish and Scale (Weeks 23-28)

**Goal**: The tenant admin experience is polished, onboarding is frictionless, and the console handles real enterprise scale (500+ users, multiple KBs, many agents).

**Sprint D1 (Weeks 23-25): Onboarding Wizard and Setup Experience**

Deliverables:

- [ ] Full onboarding wizard: 6-step guided setup (workspace → auth → LLM profile → document store → agents → users)
- [ ] Progress persistence: wizard state saved, resumable if interrupted
- [ ] Post-setup checklist: "remaining setup tasks" dashboard card until all recommended steps complete
- [ ] Contextual help: inline tooltips and "Why do I need this?" explanations throughout admin console
- [ ] Setup completion celebration: milestone notification "Your AI workspace is ready!"

**Sprint D2 (Weeks 26-28): Enterprise Scale and Polish**

Deliverables:

- [ ] Bulk user operations: suspend, role change, KB assignment changes in batch
- [ ] User import from SSO: import user directory from IdP for pre-provisioning
- [ ] Multiple document source support: 5+ SharePoint sites, multiple Google drives, uploaded files — all in one workspace
- [ ] KB search across sources: unified document search in admin (find which KB a document is in)
- [ ] Agent analytics aggregation: compare performance across all agents side-by-side
- [ ] Tenant admin role delegation: allow a second tenant admin (HR admin co-manages HR KB, IT admin manages infrastructure)
- [ ] Notification center: centralized inbox for all alerts (sync failures, access requests, issue reports, upgrade notifications)
- [ ] Mobile-responsive admin console: basic mobile support for monitoring (not authoring)
- [ ] Data export: export user list, audit log, glossary, agent config

**Phase D Success Criteria**:

- Non-technical admin (knowledge manager, no IT background) completes full setup wizard to working AI workspace in < 4 hours
- Workspace with 500 users, 5 KBs, 10 agents managed without performance degradation
- Second tenant admin can be added and restricted to specific domains (HR admin manages HR KB only)

---

## 4. Architecture Decisions

### 4.1 SSO Architecture

- **SAML 2.0**: Use `python3-saml` or `python-social-auth` for SP implementation
- **OIDC**: Use `authlib` with auto-discovery via `/.well-known/openid-configuration`
- **JIT provisioning**: On first SSO token receipt, create user record if not exists
- **Group sync**: On each login, evaluate IdP group claims → update role if mapping changed
- **Token invalidation**: Store short-lived JWTs (15-minute expiry); role changes effective within 1 login cycle; "Force logout" endpoints Redis-invalidate existing tokens

### 4.2 Glossary Pipeline Integration

> **Canonical Specification (R24 fix)**: The authoritative glossary injection limits are: **max 20 terms injected per query**, **max 200 chars per definition**, **800-token hard cap for the entire glossary block**. Earlier drafts cited 50 terms — that figure is incorrect and superseded by this spec. The storage tier limits (100/1,000/Unlimited terms stored) are separate from the injection limit, which is always 20.

```
Glossary stored: PostgreSQL per-tenant glossary table
At query time:
  1. Load active glossary terms for tenant (Redis-cached, 60-second TTL)
  2. Filter by embedding similarity to current query → top 20 most relevant terms
     (NOT keyword match — relevance-ranked by cosine similarity to query embedding)
  3. Hard stop: enforce 800-token budget for entire glossary block
     (if 20 terms would exceed 800 tokens, reduce to fewer terms)
  4. Inject into system message ONLY (never into user message — prompt injection prevention):
     "[ORGANIZATIONAL TERMINOLOGY]
     EMEA: Europe, Middle East, and Africa — our primary revenue region
     QBR: Quarterly Business Review
     ..."
  5. System message is platform-controlled — user cannot override or inject content
```

### 4.3 KB and Agent RBAC Enforcement

- JWT contains: `tenant_id`, `user_id`, `role`, `kb_permissions[]`, `agent_permissions[]`
- At every query: middleware verifies `kb_id` in `kb_permissions[]`
- At every agent invocation: middleware verifies `agent_id` in `agent_permissions[]`
- Agent accessing KB: agent's `allowed_kb_ids` configuration checked against `user.kb_permissions[]` — user must have access to ALL KBs the agent would query
- Enforcement is at query execution, not just UI visibility

### 4.4 Document Store Credential Management

```
Credential flow:
  Tenant admin enters credentials in UI
  → API validates (test connection)
  → On success: encrypted with AES-256 using tenant-scoped key
  → Stored in Azure Key Vault (path: secrets/tenant-{id}/sharepoint-client-secret)
  → Sync worker fetches from vault at sync time (never stored in application DB)
  → Credentials never returned in API responses
```

### 4.5 Agent Studio vs Template System

| Aspect                  | Agent Library (Template)                       | Agent Studio (Custom)          |
| ----------------------- | ---------------------------------------------- | ------------------------------ |
| System prompt           | Platform-controlled                            | Tenant-controlled              |
| Guardrails              | Platform-set minimum + tenant additions        | Tenant-controlled              |
| Analytics               | Contributes to platform cross-tenant analytics | Tenant-only analytics          |
| Upgrade                 | Platform admin publishes new version           | Tenant admin manages versions  |
| Quality guarantee       | Platform-tested                                | Tenant-responsibility          |
| Security responsibility | Platform (prompt injection protection)         | Tenant (admin-authored prompt) |

---

## 5. Success Metrics

### Phase A

| Metric                           | Target                                                                                                          |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Workspace activation time        | < 30 minutes from invite receipt                                                                                |
| SharePoint connection time       | < 2 hours of technical wizard steps (enterprise IT approvals add 1-3 weeks depending on governance structure)   |
| Google Drive DWD connection time | < 2 hours of technical wizard steps (enterprise IT approvals add 1-3 weeks; DWD requires Workspace Super Admin) |
| Support ticket rate for setup    | < 10% of new tenants require support during Phase A tasks                                                       |

### Phase B

| Metric                            | Target                                                           |
| --------------------------------- | ---------------------------------------------------------------- |
| SSO setup time                    | < 2 hours by IT admin without SAML expertise                     |
| Glossary injection latency        | < 60 seconds from save to active in queries                      |
| SSO JIT provisioning success rate | > 99% of first-time SSO logins result in correct role assignment |
| Sync failure diagnosis accuracy   | > 80% of failures show actionable fix suggestion                 |

### Phase C

| Metric                      | Target                                                                     |
| --------------------------- | -------------------------------------------------------------------------- |
| Agent library adoption time | < 30 minutes from browse to deployed                                       |
| Agent Studio publish time   | < 2 hours for first custom agent                                           |
| Issue resolution rate       | > 70% of tenant-config issues resolved by tenant admin without escalation  |
| Feedback data latency       | Satisfaction data appears in dashboard within 1 hour of first user ratings |

### Phase D

| Metric                    | Target                                                                |
| ------------------------- | --------------------------------------------------------------------- |
| Non-technical admin setup | < 4 hours from invite to working AI workspace                         |
| Partner self-sufficiency  | Non-technical partner operates deployment without vendor support call |

---

## 6. Risk Register

| ID  | Risk                                                                                    | Severity | Mitigation                                                                                                                                                                           |
| --- | --------------------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| R01 | Entra App Registration is too complex for non-IT admins                                 | HIGH     | In-product screenshot guidance + test connection validates before saving; support fallback for stuck users                                                                           |
| R02 | Google Drive DWD requires Workspace Super Admin — not all tenant admins have this       | HIGH     | OAuth fallback path for non-Workspace or no-Admin-access scenarios; clearly communicate prerequisite                                                                                 |
| R03 | Glossary injection consumes context window budget                                       | CRITICAL | Hard cap: max 20 terms injected per query (relevance-ranked), max 200 chars per definition, 800-token budget ceiling for glossary block; monitor context usage; alert if over budget |
| R04 | SAML misconfiguration causes login failures for all users                               | HIGH     | SSO test login before enabling; rollback via platform admin emergency access; keep email/password as override                                                                        |
| R05 | Agent Studio allows prompt injection by tenant admin (supply chain risk)                | HIGH     | Agent Studio agents scoped to the tenant only; platform reviews flagged agents; no agent can access cross-tenant data regardless                                                     |
| R06 | KB access control bypass: agent queries KB user shouldn't see                           | CRITICAL | Enforce at query execution (JWT claims checked against agent KB list); UI warning when agent KB includes user-restricted KBs                                                         |
| R07 | Client secret expiry causes silent sync failure for months                              | MEDIUM   | 30-day warning before expiry; credential health check daily; alert on 401 response                                                                                                   |
| R08 | Glossary prompt injection: malicious admin injects instructions via glossary definition | HIGH     | Sanitize glossary content before injection; definition field stripped of system instructions                                                                                         |
| R09 | Satisfaction cold start: new tenants see empty analytics for weeks                      | MEDIUM   | Show "not enough data" state explicitly rather than empty charts; set expectation: "Analytics available after 50 rated responses"                                                    |
| R10 | Agent Studio used for high-risk use cases without guardrails                            | HIGH     | Platform admin can review and flag custom agents; minimum guardrail requirements enforced at publish (confidence threshold must be set)                                              |

---

## 7. MVP Recommendation (Phase A for Launch)

**In MVP** (Phase A — Weeks 1-6):

- Workspace activation wizard (simplified: name, logo, auth mode choice)
- User invite + role assignment (single and bulk)
- User suspension and deletion
- SharePoint connection with permission wizard
- Google Drive connection (OAuth path initially; DWD in Phase B)
- Basic sync status (document count, last sync time, error count)
- KB access control (workspace-wide vs restricted)
- LLM profile selection (consume platform admin profiles)
- Basic audit log

**Deferred to Phase B** (after 3+ tenants are using the platform):

- SSO (most early tenants will use email auth; SSO demand comes at 50+ users)
- SAML/OIDC wizard complexity is disproportionate for small tenants
- Glossary (high impact but requires satisfation data to demonstrate value)
- Google Drive DWD (OAuth covers initial use cases)
- KB-level access control granularity (workspace-wide / restricted is enough for MVP)

**Deferred to Phase C** (after use patterns are established):

- Agent Studio (library adoption comes first; custom agents are advanced use case)
- Feedback monitoring dashboard (needs data to show)
- Issue queue (depends on issue reporting feature from Plan 04)

---

## 8. Dependencies

| Dependency                                                       | Type                                                                                                                                                 | Owner                    |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| Multi-tenant migration (PostgreSQL RLS, per-tenant Search index) | Architecture                                                                                                                                         | Platform team            |
| Platform admin LLM profiles (for profile selector)               | Feature dependency                                                                                                                                   | Platform admin (Plan 05) |
| Platform agent template library (for agent adoption)             | Feature dependency — **Resolved by seed templates in codebase (see Sprint C1). Phase C is no longer blocked on platform admin template publishing.** | Platform admin (Plan 05) |
| Satisfaction signal collection (thumbs up/down)                  | Data pipeline                                                                                                                                        | Product team             |
| Issue reporting feature (Plan 04)                                | Feature dependency                                                                                                                                   | Product team             |
| Glossary injection pipeline (RAG pipeline change)                | Architecture                                                                                                                                         | Engineering              |
| Microsoft Graph API credentials (for SharePoint wizard)          | External                                                                                                                                             | Tenant-provided          |
| Google Drive API credentials (for DWD wizard)                    | External                                                                                                                                             | Tenant-provided          |
| SSO provider support (SAML 2.0, OIDC)                            | Library                                                                                                                                              | Engineering              |

---

## 9. Effort Estimates

| Phase     | Sprints | Duration     | Primary Engineering Focus                                        |
| --------- | ------- | ------------ | ---------------------------------------------------------------- |
| Phase A   | 2       | 6 weeks      | Workspace activation, user management, document store connectors |
| Phase B   | 3       | 8 weeks      | SSO, RBAC granularity, glossary pipeline, sync monitoring        |
| Phase C   | 3       | 8 weeks      | Agent library, Agent Studio, feedback monitoring                 |
| Phase D   | 2       | 6 weeks      | Onboarding polish, enterprise scale, mobile                      |
| **Total** | **10**  | **28 weeks** |                                                                  |

Phase A runs in parallel with Platform Admin Plan Phase A (they share user management infrastructure). Phase C requires Platform Admin Phase C (template library must exist before agent adoption is possible).

---

## 10. What Success Looks Like at Each Stage

**End of Phase A**: A customer organization's IT admin receives an invite, activates their workspace, connects their SharePoint, invites their team, and the AI is answering questions from their actual documents — all in a single day, without filing a support ticket or engaging engineering.

**End of Phase B**: The same IT admin configures SSO so new employees automatically get AI access when they join the company. The knowledge manager maintains a glossary of organizational terms. The AI uses the right language for the organization without per-user configuration.

**End of Phase C**: An HR manager (non-IT) deploys the HR Policy agent from the library, customizes it with their company's specific variables, and monitors whether their team finds it useful — without involving IT or engineering.

**End of Phase D**: A non-technical partner (reseller) can provision a client, complete the full setup wizard, and hand over a working AI workspace to the client — all without calling the mingai support team. This is the partner enablement test.
