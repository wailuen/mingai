# 05 — Platform Admin Console: Implementation Plan

**Date**: 2026-03-05
**Depends on**: `01-analysis/10-platform-admin/` (all 5 files), `01-research/30-platform-admin-capability-spec.md`, `03-user-flows/11-platform-admin-ops-flows.md`

---

## 1. Scope and Boundaries

### What This Plan Covers

The platform admin console — the unified operations suite enabling a single operator to manage a multi-tenant AI SaaS platform:

1. **Tenant Lifecycle** — provisioning, suspension, offboarding, quota management
2. **Issue Queue** — intake, AI triage, routing, GitHub integration
3. **Analytics & Roadmap Signals** — health scores, at-risk detection, feature adoption
4. **LLM Profile Library** — profile creation, testing, publishing, deprecation
5. **Cost Monitoring** — token attribution, gross margin per tenant, infrastructure costs
6. **Agent Template Library** — template authoring, versioning, performance analytics
7. **Tool Catalog** — MCP tool registration, safety classification, health monitoring

### What This Plan Does NOT Cover

- Tenant admin console (separate product — tenant-facing)
- End-user interface changes
- RAG pipeline changes (covered in other plans)
- A2A protocol implementation (covered in Phase 4 of main roadmap)

---

## 2. Relationship to Main Roadmap

The main roadmap (`02-plans/01-implementation-roadmap.md`) defines 6 phases over 30 weeks. The platform admin console spans multiple phases:

| Roadmap Phase            | Platform Admin Touchpoints                               |
| ------------------------ | -------------------------------------------------------- |
| Phase 1 (Foundation)     | Basic tenant provisioning API, raw quota tracking        |
| Phase 2 (LLM Library)    | LLM profile management UI, model slot configuration      |
| Phase 3 (Auth)           | Platform RBAC, admin role enforcement                    |
| Phase 4 (Agentic)        | Issue triage agent, template library with A2A            |
| Phase 5 (Cloud Agnostic) | Multi-cloud cost monitoring, cloud-agnostic provisioning |
| Phase 6 (GA)             | Full console polish, partner enablement hardening        |

**This plan defines the admin console delivery track within those phases.**

---

## 3. Phase Breakdown

### Phase A — Foundation Console (Weeks 1-6)

**Goal**: A functional admin interface for the basics. Every capability here is table stakes — without it, operating multi-tenant is impossible.

**Sprint A1 (Weeks 1-3): Tenant Lifecycle Core**

Deliverables:

- [ ] Tenant data model (PostgreSQL): `tenants` table with status state machine (Draft → Active → Suspended → ScheduledDeletion → Deleted)
- [ ] Tenant provisioning API: POST `/admin/tenants` — applies PostgreSQL tenant schema (tenant row + RLS seed), creates Search index (OpenSearch/Azure AI Search per `CLOUD_PROVIDER`), Object Store bucket, Redis namespace, Stripe customer record
- [ ] Tenant provisioning UI: 4-step wizard (Basic Info → LLM Profile → Quotas → Review)
- [ ] Automated provisioning workflow: all 5 resource types provisioned in parallel, < 10 minutes SLA
- [ ] Tenant admin invite email: sends first login link to primary contact
- [ ] Tenants list view: table with status, plan, health score column (placeholder until scoring built)
- [ ] Tenant detail page: status, plan, contact info, creation date, LLM profile assignment
- [ ] Tenant suspension flow: UI + API, preserves data, blocks auth
- [ ] Grace period tracking: 30-day countdown, automated delete scheduling
- [ ] Quota management: view current usage, edit quota limits per tenant
- [ ] Basic audit log: all tenant state transitions logged with timestamp + actor

**Sprint A2 (Weeks 4-6): Platform RBAC and Basic Billing Visibility**

Deliverables:

- [ ] Platform role model: `platform_admin`, `platform_operator`, `platform_support`, `platform_security` — implementation from `24-platform-rbac-specification.md`
- [ ] Role enforcement: middleware checks for all `/admin/*` routes
- [ ] Billing view (read-only): show Stripe plan data, invoice history per tenant
- [ ] Token usage raw view: per-tenant token consumption by model deployment (from existing usage tracking)
- [ ] Cost estimation: LLM cost per tenant based on token volume × model pricing constants
- [ ] Plan tier configuration: define Starter/Professional/Enterprise limits in config, enforced at API level
- [ ] Tenant filter/sort: filter by plan, status, health (placeholder); sort by creation date, plan revenue

**Phase A Success Criteria**:

- New tenant provisioned end-to-end in < 10 minutes with zero manual steps
- Platform admin can suspend/reactivate tenant via UI without engineering involvement
- Token cost per tenant visible (even if estimated, not exact)
- Platform RBAC enforced — platform_support cannot modify tenant quotas

---

### Phase B — Intelligence and Visibility (Weeks 7-14)

**Goal**: The console becomes an operational intelligence tool, not just a management panel. Admins get the data they need to make decisions.

**Sprint B1 (Weeks 7-9): LLM Profile Library**

Deliverables:

- [ ] LLM profile data model: profile name, description, slot configurations (6 slots), status (Draft/Published/Deprecated)
- [ ] Profile creation UI: slot-by-slot configuration form matching `21-llm-model-slot-analysis.md` deployment slots
- [ ] Profile test harness: run 3 test queries against draft profile, view response + latency + token count + estimated cost
- [ ] Best practices notes: markdown editor for per-profile documentation visible to tenant admins
- [ ] Profile lifecycle: Draft → Published → Deprecated state machine
- [ ] Profile assignment: tenant can be assigned a profile at provisioning or changed later
- [ ] Profile enforcement: when tenant's profile changes, RAG pipeline slot config updates automatically within 60 seconds
- [ ] Profile selector (tenant-facing): tenant admin sees available published profiles with descriptions (no raw model names)
- [ ] Deprecation flow: deprecated profiles retain existing tenant assignments but cannot be newly selected

**Sprint B2 (Weeks 10-12): Tenant Health Scoring**

Deliverables:

- [ ] Health score algorithm: composite score from 4 inputs:
  - Usage trend (30-day window, weighted 30%)
  - Feature breadth — count of distinct features used in last 30 days (20%)
  - AI satisfaction rate — thumbs up/down ratio on AI responses (35%)
  - Error rate — 5xx responses as % of total queries (15%)
- [ ] Health score calculation: runs daily (nightly batch) per tenant, stored in PostgreSQL
- [ ] At-risk signal detection: flag tenants with health score declining 3+ consecutive weeks
- [ ] Dashboard overview: KPI cards (active tenants, at-risk count, platform satisfaction, open P0/P1 issues)
- [ ] Tenant health table: sortable by health score, color-coded (green/yellow/red), at-risk badge
- [ ] Health score drilldown: per-tenant breakdown of all 4 score components with trend sparkline
- [ ] Proactive outreach: platform notification system for admin → tenant admin messaging

**Sprint B3 (Weeks 13-14): Cost Monitoring and Gross Margin**

Deliverables:

- [ ] Exact token attribution pipeline: token count per query → attributed to tenant → aggregated daily
- [ ] LLM cost calculation: tokens × per-model cost rate → real dollar cost per tenant per period
- [ ] Cost dashboard: period selector, platform total, per-tenant breakdown table with gross margin column
- [ ] Margin calculation: (plan revenue − LLM cost − infrastructure estimate) / plan revenue
- [ ] Infrastructure cost attribution: Azure Cost Management API integration (pull actual costs, apply attribution model)
- [ ] Cost alert thresholds: configurable alerts when tenant margin drops below threshold or daily spend spikes
- [ ] Billing reconciliation export: CSV export of per-tenant cost data for billing review

**Phase B Success Criteria**:

- Platform admin can see gross margin per tenant, updated daily
- At-risk tenants automatically surfaced — no manual review of all tenants required
- LLM profile change by tenant admin propagates to RAG pipeline within 60 seconds
- Admin can create, test, and publish a new LLM profile without engineering help

---

### Phase C — Issue Intelligence and Templates (Weeks 15-22)

**Goal**: Close the feedback loops. Issue reporting feeds the issue queue; template analytics feed template improvement; both feed roadmap signals.

**Sprint C1 (Weeks 15-17): Issue Queue and Triage**

Deliverables:

- [ ] Issue intake: consume from Redis Stream `issue_reports:incoming` (populated by issue reporting feature from Plan 04)
- [ ] AI triage agent (Kaizen): severity classification (P0-P4), platform bug vs tenant config classification, duplicate detection
- [ ] Issue queue UI: sorted list with severity badge, tenant, status, AI classification
- [ ] Issue detail panel: all reporter context (session data, screenshot, browser info, AI assessment)
- [ ] GitHub integration: one-click issue creation from admin queue, pre-populated with all context
- [ ] Routing actions: "Route to Tenant" (sends notification to tenant admin), "Close as Duplicate" (link to original), "Request More Info"
- [ ] Status tracking: New → In Review → Escalated → Resolved → Closed
- [ ] Reporter notifications: SSE/notification delivery of status updates to original reporter
- [ ] Batch queue actions: filter by severity/tenant/category, bulk close/route

**Sprint C2 (Weeks 18-20): Agent Template Library**

Deliverables:

- [ ] Template data model: name, category, system prompt, variable definitions, guardrails, confidence threshold, version
- [ ] Template authoring UI: structured form with `{{variable}}` placeholder syntax, guardrail configuration
- [ ] Variable definition system: admin defines variable name, type, description, required/optional, example value
- [ ] Template test harness: run test scenarios against draft template, review AI responses
- [ ] Template versioning: v1 → v2 → v3 with changelog; published versions immutable in system prompt
- [ ] Template library: published templates available to tenant agents (tenant admin instantiates, fills variables)
- [ ] Tenant template instance management: tenant fills variables, deploys, cannot modify system prompt/guardrails

**Sprint C3 (Weeks 21-22): Template Analytics and Roadmap Signals**

Deliverables:

- [ ] Template performance tracking: per-template satisfaction rate, guardrail trigger rate, failure pattern categorization
- [ ] Template analytics dashboard: satisfaction by template, sorted by lowest performers
- [ ] Cross-tenant aggregation: aggregate template performance data across all tenants using same template
- [ ] Underperforming template alerts: flag templates with satisfaction < platform average − 10%
- [ ] Template upgrade notifications: admin can push "new version available" to tenant admins
- [ ] Roadmap signal board: aggregated feature requests from issue reports, ranked by frequency × plan weight
- [ ] Feature adoption table: per-feature tenant adoption rate, satisfaction, sessions/week
- [ ] Signal export: CSV export of roadmap signals for planning purposes

**Phase C Success Criteria**:

- Issue triage agent classifies severity correctly on ≥ 80% of issues (measured against admin corrections)
- Template analytics surfacing underperforming templates within 48 hours of data collection
- Admin can create and publish a complete agent template without engineering involvement
- Roadmap signal board shows actionable ranked feature requests with tenant attribution

---

### Phase D — Tool Catalog and Amplification (Weeks 23-28)

**Goal**: Complete the platform model. Tool governance makes the tool ecosystem manageable at scale. White-label hardening makes the console a partner product.

**Sprint D1 (Weeks 23-25): Tool Catalog**

Deliverables:

- [ ] Tool catalog data model: name, provider, MCP endpoint, auth type, capabilities, safety classification, health status, version
- [ ] Tool registration form: all fields from `30-platform-admin-capability-spec.md` §7
- [ ] Safety classification enforcement: Read-Only / Write / Destructive (immutable — can only escalate, never downgrade)
- [ ] Automated health check on registration: endpoint reachability, auth handshake, schema validation, sample invocation
- [ ] Continuous health monitoring: 5-minute ping cycle, degraded status after 3 failures, unavailable after 10
- [ ] Degraded mode fallback: agents receive fallback instruction when tool is degraded/unavailable
- [ ] Tenant catalog browser (tenant-facing): available tools with classification badge, opt-in per agent
- [ ] Tool usage analytics: invocation frequency, latency, error rate per tool per tenant
- [ ] Tool retirement flow: mark as deprecated/discontinued, notify affected tenant admins

**Sprint D2 (Weeks 26-28): Console Polish and Partner Enablement**

Deliverables:

- [ ] Console navigation: global nav with badge counts for issues, alerts, at-risk tenants
- [ ] Alert center: unified alert inbox (quota warnings, health degradations, cost spikes, tool failures, P0 issues)
- [ ] Daily digest: configurable summary email of overnight activity (new issues, health changes, cost variance)
- [ ] White-label branding: per-deployment color/logo configuration for console
- [ ] Partner onboarding test: can a non-technical partner provision a tenant, assign LLM profile, deploy agent template, and review costs in < 30 minutes without documentation?
- [ ] Admin preference settings: configurable alert thresholds, default sort orders, notification preferences
- [ ] Audit log UI: searchable event history with actor, timestamp, resource, action
- [ ] GDPR deletion workflow: verified deletion pipeline with confirmation report

**Phase D Success Criteria**:

- Tool registration to tenant-available: < 30 minutes end-to-end
- Tool health monitoring catches degradation before tenant admins notice
- Non-technical partner can complete full onboarding flow in < 30 minutes (user testing required)
- All audit events logged and searchable

---

## 4. Architecture Decisions

### 4.1 Admin Console Technology

- **Framework**: Next.js 14 (admin pages at `/admin/*` behind platform role middleware)
- **Component library**: Shadcn/UI (consistent with main app)
- **Charts**: Recharts for health/usage trend sparklines and cost dashboards
- **Tables**: TanStack Table with server-side pagination for tenant/issue lists

### 4.2 Data Sources for Admin Console

| Data Type            | Source                           | Update Frequency                  |
| -------------------- | -------------------------------- | --------------------------------- |
| Tenant metadata      | PostgreSQL                       | Real-time                         |
| Token usage          | PostgreSQL (usage_events table)  | Real-time (per query)             |
| Health score         | PostgreSQL (nightly batch)       | Daily at 02:00 UTC                |
| Satisfaction signals | PostgreSQL `user_feedback` table | Real-time (per rating submission) |
| LLM cost             | Calculated: tokens × model rate  | Daily batch                       |
| Infrastructure cost  | Azure Cost Management API        | Daily at 06:00 UTC                |
| Tool health          | Redis (last ping result)         | Every 5 minutes                   |
| Issue queue          | Redis Stream → PostgreSQL        | Real-time                         |
| Template analytics   | PostgreSQL (aggregated nightly)  | Daily                             |

### 4.3 Health Score Calculation

```
health_score = (
  usage_trend_score    × 0.30 +  # 0-100: usage_now vs usage_30d_avg, normalized
  feature_breadth_score × 0.20 + # 0-100: distinct_features / total_features × 100
  satisfaction_score   × 0.35 +  # 0-100: thumbs_up / (thumbs_up + thumbs_down) × 100
  error_rate_score     × 0.15    # 0-100: (1 - error_rate) × 100 (inverted)
)

at_risk_flag = health_score declining for 3+ consecutive weekly snapshots
               OR health_score < 40
               OR satisfaction_score < 50 for 2+ consecutive weeks
```

### 4.4 LLM Cost Constants

Stored in environment config (not hardcoded), updated when model pricing changes:

```
COST_PER_1K_INPUT_TOKENS_GPT52_CHAT=0.015
COST_PER_1K_OUTPUT_TOKENS_GPT52_CHAT=0.060
COST_PER_1K_INPUT_TOKENS_GPT5_MINI=0.00015
COST_PER_1K_OUTPUT_TOKENS_GPT5_MINI=0.00060
COST_PER_1M_TOKENS_TEXT_EMBEDDING_3_LARGE=0.13
```

### 4.5 Provisioning Architecture

Provisioning runs as an async background job (A2A worker pattern):

```
Admin submits form → API creates tenant record (status: Provisioning)
  → enqueues provisioning job to Redis Stream
  → Provisioning worker picks up job:
      1. Apply PostgreSQL tenant schema — insert tenant row, seed default roles, apply RLS policies (retry 3x)
      2. Create Search index (OpenSearch/Azure AI Search per CLOUD_PROVIDER) (retry 3x)
      3. Create Object Store bucket + scoped access policy (S3/Azure Blob/GCS per CLOUD_PROVIDER) (retry 3x)
      4. Register Redis namespace (retry 3x)
      5. Send invite email (retry 3x with exponential backoff)
      6. Update tenant status → Active
  → SSE notification to admin on completion
  → Rollback: if any step fails after 3 retries → mark as ProvisioningFailed
               → async cleanup job reverses completed steps
```

---

## 5. Success Metrics

### Phase A (Foundation)

| Metric                     | Target                                                                  |
| -------------------------- | ----------------------------------------------------------------------- |
| Tenant provisioning time   | < 10 minutes (P95)                                                      |
| Provisioning success rate  | > 99%                                                                   |
| Admin task completion rate | Platform admin can complete all basic tasks without engineering support |

### Phase B (Intelligence)

| Metric                  | Target                                                                     |
| ----------------------- | -------------------------------------------------------------------------- |
| Health score accuracy   | At-risk flag correlates with actual churn within 30 days in ≥ 70% of cases |
| Cost visibility         | Token cost per tenant accurate within ±5% of actual Azure charges          |
| LLM profile propagation | Profile change reflected in RAG pipeline within 60 seconds                 |

### Phase C (Issue Intelligence + Templates)

| Metric                     | Target                                                                   |
| -------------------------- | ------------------------------------------------------------------------ |
| AI triage accuracy         | ≥ 80% severity classification matches admin's eventual ruling            |
| Template creation time     | Admin creates + publishes template in < 2 hours                          |
| Template analytics latency | Underperforming templates surfaced within 48 hours of crossing threshold |

### Phase D (Tool Catalog + Polish)

| Metric                 | Target                                                    |
| ---------------------- | --------------------------------------------------------- |
| Tool registration time | Registration to tenant-available in < 30 minutes          |
| Tool health detection  | Degradation detected within 10 minutes of tool failure    |
| Partner onboarding     | Non-technical partner completes full flow in < 30 minutes |

---

## 6. Risk Register

| ID  | Risk                                                                          | Severity | Mitigation                                                                                                                                           |
| --- | ----------------------------------------------------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| R01 | Provisioning atomicity: partial failures leave orphaned cloud resources       | HIGH     | Implement rollback job; audit log every resource creation; manual cleanup UI for admin                                                               |
| R02 | LLM cost constants become stale when providers change pricing                 | MEDIUM   | Store in env config (not DB), alert when cost deviation > 20% from estimates                                                                         |
| R03 | Health score gaming: tenants spam thumbs-up to avoid at-risk flag             | LOW      | Weight satisfaction signals by query uniqueness; detect suspiciously high satisfaction from single users                                             |
| R04 | Azure Cost Management API has 24-48 hour delay                                | MEDIUM   | Clearly label infrastructure costs as "estimated" with timestamp; LLM costs are real-time from our own tracking                                      |
| R05 | AI triage agent prompt injection via malicious issue reports                  | CRITICAL | Triage agent processes reporter text in sandboxed context; never executes content; output is classification only                                     |
| R06 | Template system prompt injection via variable content                         | HIGH     | Variables are user-supplied text only; system prompt is platform-controlled; never concatenate raw variables into system prompt without sanitization |
| R07 | Over-engineering admin console for current scale (< 10 tenants)               | HIGH     | Phase A only for initial launch; Phase B-D gated on reaching 15+ active tenants                                                                      |
| R08 | Tool health monitoring creates overhead at scale (100+ tools, 5-min ping)     | MEDIUM   | Implement jitter in ping schedule; use cached health status; only alert on state changes                                                             |
| R09 | Gross margin calculation misleading for tenants with negotiated contracts     | MEDIUM   | Support per-tenant contract overrides in billing config; flag enterprise contract tenants with "custom pricing"                                      |
| R10 | Admin console UX complexity grows with every feature — cognitive load problem | HIGH     | Implement progressive disclosure; advanced features behind "Advanced" tabs; default views show only action-required items                            |

---

## 7. MVP Recommendation (Phase A Only for Launch)

Based on the risk analysis and scale reality, the minimum viable admin console for initial multi-tenant launch contains:

**In MVP** (Phase A — Weeks 1-6):

- Tenant provisioning wizard (automated, < 10 minutes)
- Tenant list with status, plan, basic usage indicator
- Tenant suspension / grace period / deletion
- Platform RBAC (4 roles enforced)
- LLM profile assignment (select from pre-defined profiles, no authoring UI yet)
- Raw quota tracking with manual quota override
- Basic billing view (Stripe plan data, no token cost attribution yet)

**Deferred to Phase B** (reach 15+ tenants first):

- Health scoring (not enough data to calibrate with < 15 tenants)
- Gross margin dashboard (token attribution pipeline is complex; build when margin visibility is urgent)
- LLM profile authoring UI (platform admin can author profiles via config until volume demands UI)

**Deferred to Phase C** (reach 25+ tenants or after issue reporting feature ships):

- Issue queue (depends on issue reporting feature from Plan 04)
- Template library with analytics (not enough cross-tenant data until scale)
- Roadmap signals (signal quality improves with volume — 5 tenants' data is noise)

This phasing avoids the over-engineering trap: building a sophisticated multi-tenant operations platform for a platform that is still single-tenant or in early multi-tenant stage.

---

## 8. Dependencies

| Dependency                                                                                                              | Type               | Owner                  |
| ----------------------------------------------------------------------------------------------------------------------- | ------------------ | ---------------------- |
| PostgreSQL tenant provisioning (Alembic migrations + RLS policy seeding)                                                | Infrastructure     | Platform team          |
| Search index management API (OpenSearch on AWS; Azure AI Search on Azure; Vertex AI Search on GCP — per CLOUD_PROVIDER) | Infrastructure     | Platform team          |
| Stripe customer + subscription API                                                                                      | External           | Billing integration    |
| Azure Cost Management API credentials                                                                                   | Infrastructure     | Platform team          |
| GitHub App installation (issue creation)                                                                                | External           | Engineering            |
| Issue reporting feature (Plan 04)                                                                                       | Feature dependency | Product team           |
| A2A worker infrastructure                                                                                               | Infrastructure     | Phase 4 (main roadmap) |
| Platform RBAC middleware                                                                                                | Architecture       | Auth team              |
| Satisfaction signal collection (thumbs up/down)                                                                         | Data pipeline      | Product team           |

---

## 9. Effort Estimates

| Phase     | Sprints | Duration     | Primary Engineering Focus                        |
| --------- | ------- | ------------ | ------------------------------------------------ |
| Phase A   | 2       | 6 weeks      | Backend provisioning APIs, basic UI, RBAC        |
| Phase B   | 3       | 8 weeks      | Data pipelines, health scoring, cost attribution |
| Phase C   | 3       | 8 weeks      | AI triage agent, template engine, analytics      |
| Phase D   | 2       | 6 weeks      | Tool catalog, monitoring, console polish         |
| **Total** | **10**  | **28 weeks** |                                                  |

Phase A can run in parallel with the main roadmap Phase 1-2 (they share the same tenant data model foundations). Phases C and D require main roadmap Phase 4 (A2A infrastructure) to be in progress.

---

## 10. What Success Looks Like at Each Stage

**End of Phase A**: One platform admin can provision a new tenant in < 10 minutes, suspend a non-paying tenant, and assign them to a pre-configured LLM profile — all without filing an engineering ticket.

**End of Phase B**: The same admin can see in real-time whether each tenant is profitable, which tenants are at risk of churning, and get alerted when intervention is needed — before the tenant notices a problem.

**End of Phase C**: Template quality improves month-over-month because the admin can see aggregate performance data across all tenant instances, not just one. Issue reports are triaged automatically and reach engineering in the right priority order.

**End of Phase D**: A non-technical partner can be given admin console access and independently operate their white-label mingai deployment — provisioning tenants, managing templates, monitoring costs — without calling the mingai team for help. This is the moment the admin console becomes a product feature, not just internal tooling.
