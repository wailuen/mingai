# 04 — Platform Admin Phases B-D: Intelligence, Issue Queue, Tool Catalog

**Generated**: 2026-03-15
**Phase**: B (Weeks 7-14), C (Weeks 15-22), D (Weeks 23-28)
**Numbering**: PA-001 through PA-036
**Stack**: FastAPI + Kailash DataFlow + PostgreSQL + Redis + SendGrid
**Source plan**: `workspaces/mingai/02-plans/05-platform-admin-plan.md` Phases B-D

---

## Overview

Phase A (Platform Admin Phase 1 foundations) is COMPLETE. Phases B-D deliver:

- **Phase B**: LLM Profile Library management, Tenant Health Scoring, Cost Monitoring/Gross Margin
- **Phase C**: Issue Queue routing refinement, Agent Template Library, Template Analytics
- **Phase D**: Tool Catalog, Platform Daily Digest, GDPR Deletion, Audit Log UI

**Dependencies**: Phase B (PA-001–PA-016) depends on P2LLM-004/005 (LLM Library table and API). Phase C (PA-017–PA-029) depends on Phase B completion. Phase D (PA-030–PA-036) depends on Phase C.

---

## Phase B: Intelligence and Visibility (Weeks 7-14)

### Sprint B1: LLM Profile Library (Weeks 7-9)

### PA-001: LLM profile authoring UI extension

**Status**: ⬜ TODO
**Effort**: 8h
**Depends on**: P2LLM-004, P2LLM-005, P2LLM-013
**Description**: Extend existing `ProfileForm` (FE-043 — basic form) to support the full slot-by-slot configuration per `workspaces/mingai/01-analysis/21-llm-model-slot-analysis.md`. Slots: intent_model, primary_model, vision_model, embedding_model. Each slot: provider selector + deployment name field + optional override flag. Best-practices notes as markdown editor with preview toggle. Draft/Published/Deprecated lifecycle actions in form footer.
**Acceptance criteria**:

- [ ] ProfileForm shows 4 model slots with provider + deployment name per slot
- [ ] Markdown editor for `best_practices_md` with preview pane
- [ ] Draft→Publish action: validates all 4 slots have non-empty deployment names
- [ ] Publish→Deprecate action: shows confirmation dialog listing tenants currently on this profile
- [ ] Deprecated profiles shown with `--text-faint` styling (not red — deprecated is not an error)
- [ ] 0 TypeScript errors
- [ ] Matches Obsidian Intelligence design: no purple, DM Mono for model names

---

### PA-002: Profile test harness

**Status**: ✅ COMPLETED
**Effort**: 8h
**Depends on**: P2LLM-005, P2LLM-009
**Description**: Backend: `POST /platform/llm-profiles/{id}/test`. Runs 3 fixed test prompts against the draft profile's configured models (intent, primary, embedding). Returns: `{ "tests": [{ "prompt": "...", "response": "...", "tokens_in": N, "tokens_out": N, "latency_ms": N, "estimated_cost_usd": X }] }`. Requires `require_platform_admin`. Frontend: "Test Profile" button in ProfileForm that calls this endpoint and shows results in a slide-in panel.
**Backend**: `app/modules/platform/llm_library/routes.py`
**Tests**: `tests/unit/test_llm_library_test_harness.py`, `tests/integration/test_profile_assignment.py`
**Acceptance criteria**:

- [x] Endpoint calls all 3 test prompts against draft profile models
- [x] Correct token counts and latency in response
- [x] `estimated_cost_usd` calculated using pricing from `llm_library.pricing_per_1k_tokens_*`
- [x] Draft profile (not yet Published) testable via this endpoint
- [x] Frontend slide-in panel shows test results with DM Mono for token/latency/cost values
- [x] Latency shown in ms; cost in USD with 6 decimal places
- [x] `require_platform_admin` enforced
- [x] Timeout: 30s (LLM calls can be slow); 504 if exceeded

---

### PA-003: Profile assignment enforcement

**Status**: ⬜ TODO
**Effort**: 5h
**Depends on**: P2LLM-008, P2LLM-009
**Description**: When a tenant's LLM profile changes (via `PATCH /admin/llm-config`), the RAG pipeline must pick up the new config within 60 seconds. Implementation: `PATCH /admin/llm-config` writes to PostgreSQL, then DELetes Redis cache key `mingai:{tenant_id}:config`. `InstrumentedLLMClient` (P2LLM-009) reads tenant config on every call — cache TTL 15min, but DEL forces immediate miss → re-read from PostgreSQL. 60-second SLA met as long as DEL + cache TTL work correctly.
**Acceptance criteria**:

- [ ] Profile change PATCH triggers immediate Redis DEL for tenant config cache key
- [ ] Subsequent LLM calls (within 60s) use new profile (verified by model name in `usage_events`)
- [ ] Integration test: profile change → verify new model reflected in usage_events within 2 subsequent calls
- [ ] No restart required for config change propagation

---

### PA-004: Profile deprecation flow

**Status**: ✅ COMPLETED
**Effort**: 4h
**Depends on**: P2LLM-005
**Description**: `PATCH /platform/llm-profiles/{id}` with `status=deprecated`. Existing tenant assignments preserved (tenants continue using deprecated profile). Profile cannot be newly selected by tenant admins (filtered out from PATCH /admin/llm-config options). Backend: `GET /platform/llm-profiles/{id}/tenant-assignments` — lists tenants currently on this profile (used in confirmation dialog). Platform admin receives notification list so they can proactively reach out.
**Backend**: `app/modules/platform/llm_library/routes.py`
**Acceptance criteria**:

- [x] PATCH status=deprecated succeeds; existing assignments preserved
- [x] `GET /platform/llm-profiles/{id}/tenant-assignments` returns list of tenant IDs/names
- [x] Deprecated profiles excluded from `GET /admin/llm-config` available profiles list (tenant admin view)
- [x] Deprecated profiles still returned in `GET /platform/llm-library` (platform admin view — with deprecated status badge)
- [x] Confirmation dialog in frontend shows tenant count before deprecation

---

### PA-005: Tenant profile selector UI

**Status**: ✅ COMPLETED
**Effort**: 5h
**Depends on**: P2LLM-006, P2LLM-013
**Description**: Extend Tenant Admin `Settings → LLM` screen (P2LLM-014). Platform Admin view of same page: shows all tenants' current profile assignments in a table. `GET /platform/tenants/{id}/llm-config` returns tenant's current profile (profile display_name + best_practices_md, not raw model names). Tenant admin change workflow from P2LLM-014. This item covers the Platform Admin visibility side: a tenant LLM config table under Platform Admin → Tenants drilldown panel.
**Frontend**: `src/web/app/(platform)/platform/tenants/[id]/page.tsx`, `src/web/lib/hooks/useLLMLibrary.ts`
**Endpoint**: `GET /admin/llm-config/library-options` + `TenantLLMConfig` component in tenant drilldown
**Acceptance criteria**:

- [x] Tenant drilldown slide-in panel includes "LLM Config" section showing current profile
- [x] Profile shown as display_name (not raw model name)
- [x] Platform admin can see if tenant is on BYOLLM or Library mode
- [x] Best practices notes snippet (first 80 chars) shown in tooltip on profile name
- [x] 0 TypeScript errors

---

### Sprint B2: Tenant Health Scoring (Weeks 10-12)

### PA-006: `tenant_health_scores` table

**Status**: ✅ COMPLETED
**Effort**: 4h
**Depends on**: none (new migration)
**Description**: Alembic migration for `tenant_health_scores` table. Columns: `id` UUID PK, `tenant_id` UUID FK (tenants.id), `date` DATE (daily snapshot), `usage_trend_score` NUMERIC(5,2), `feature_breadth_score` NUMERIC(5,2), `satisfaction_score` NUMERIC(5,2), `error_rate_score` NUMERIC(5,2), `composite_score` NUMERIC(5,2), `at_risk_flag` BOOLEAN, `at_risk_reason` TEXT, `created_at` TIMESTAMPTZ. UNIQUE(tenant_id, date). Index on (tenant_id, date DESC). RLS: platform_admin only.
**Migration**: `alembic/versions/v014_tenant_health_scores.py`
**Acceptance criteria**:

- [x] Alembic migration file created (next version)
- [x] UNIQUE constraint on `(tenant_id, date)`
- [x] All score columns use NUMERIC(5,2) — range 0-100 with 2 decimal places
- [x] `at_risk_reason` TEXT nullable — human-readable explanation of why at_risk_flag is set
- [x] RLS: only `platform_admin` scope can access
- [x] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [x] Migration is reversible

---

### PA-007: Health score calculation batch job

**Status**: ✅ COMPLETED
**Effort**: 5h
**Depends on**: PA-006
**Note**: `app/modules/platform/health_score.py` already implements `calculate_health_score()` with all 4 component calculations. This item scopes to: (1) Create nightly batch job shell (`app/modules/platform/health_score_job.py`), (2) Wire existing `calculate_health_score()` into the job for each tenant, (3) Add at-risk detection logic (not in existing `calculate_health_score()`), (4) Write results to `tenant_health_scores` table (PA-006). Do NOT rewrite the calculation logic — it already exists.
**Description**: Nightly batch job at 02:00 UTC. For each active tenant: call existing `calculate_health_score()` to get 4 component scores. Composite = weighted sum. At-risk detection: composite < 40 OR satisfaction < 50 for 2+ consecutive weeks OR composite declining 3+ consecutive weeks. Insert into `tenant_health_scores` (upsert on date conflict).
**Backend**: `app/modules/platform/health_score_job.py`
**Tests**: `tests/unit/test_health_score_job.py`
**Acceptance criteria**:

- [x] All 4 component scores calculated from real data sources
- [x] Weighted composite = `(usage*0.30) + (breadth*0.20) + (satisfaction*0.35) + (error*0.15)`
- [x] At-risk detection logic covers all 3 conditions (composite < 40, sat < 50 for 2w, declining 3w)
- [x] `at_risk_reason` populated with specific trigger ("composite_low", "satisfaction_declining", "usage_trending_down")
- [x] Upsert pattern: `INSERT ... ON CONFLICT (tenant_id, date) DO UPDATE`
- [x] Job runtime < 5 minutes for 100 active tenants
- [x] Job failure for one tenant does not abort others (per-tenant try/except)
- [x] Unit test: score calculation formula verified for edge cases (0 usage, 100% satisfaction)

---

### PA-008: At-risk signal detection API

**Status**: ✅ COMPLETED
**Effort**: 4h
**Depends on**: PA-006, PA-007
**Description**: `GET /platform/tenants/at-risk`. Returns tenants with `at_risk_flag=true` from latest `tenant_health_scores` snapshot. Response per tenant: `tenant_id`, `name`, `composite_score`, `at_risk_reason`, `weeks_at_risk` (how many consecutive weeks at_risk_flag has been true), `component_breakdown`. `require_platform_admin`.
**Backend**: `app/modules/tenants/routes.py`
**Implementation notes**: Uses `at_risk_flag=TRUE` filter, DISTINCT ON ISO-week for weeks_at_risk
**Tests**: `tests/integration/test_health_score_api.py`
**Acceptance criteria**:

- [x] Returns only tenants with `at_risk_flag=true` in most recent snapshot
- [x] `weeks_at_risk` calculated from consecutive at_risk_flag=true rows ordered by date DESC
- [x] `component_breakdown` returns all 4 component scores
- [x] Response sorted by `composite_score ASC` (worst first)
- [x] Empty array returned (not 404) when no at-risk tenants
- [x] `require_platform_admin` enforced

---

### PA-009: Health score drilldown API

**Status**: ✅ COMPLETED
**Effort**: 5h
**Depends on**: PA-006, PA-007
**Description**: `GET /platform/tenants/{id}/health`. Returns 12-week trend for sparklines. Response: `{ "current": { component_breakdown, composite }, "trend": [{ "week": "2026-W10", "composite": 73.5, "usage_trend": 80, "satisfaction": 68 }] }`. Also: `GET /platform/tenants/at-risk` (PA-008) links here for drilldown. `require_platform_admin`.
**Backend**: `app/modules/tenants/routes.py`
**Implementation notes**: 12-week ISO-week trend
**Tests**: `tests/integration/test_health_score_api.py`
**Acceptance criteria**:

- [x] 12 weekly data points returned in `trend` array (ISO week format)
- [x] Missing weeks (no data) represented as null values (not omitted)
- [x] All 4 component scores in both current and trend data
- [x] Composite score consistent with PA-007 weighted formula
- [x] Response time < 500ms

---

### PA-010: Dashboard health table

**Status**: ✅ COMPLETED
**Effort**: 6h
**Depends on**: PA-008, PA-009
**Description**: Extend existing `TenantHealthTable` (FE-040 — COMPLETE with static data) with real health score data. Wire to `GET /platform/tenants/at-risk` and `GET /platform/tenants/{id}/health`. Color coding: composite >= 70 → `--accent` green, 50-69 → `--warn` yellow, < 50 → `--alert` orange. Sparkline in each row (12-week trend). At-risk badge (`AtRiskBadge` component from FE-040 already exists).
**Frontend**: `src/web/lib/hooks/useHealthScores.ts`, `src/web/lib/chartColors.ts` (healthScoreColor helper), `src/web/app/(platform)/platform/elements/TenantHealthTable.tsx`, `src/web/app/(platform)/platform/tenants/[id]/elements/HealthBreakdown.tsx`
**Acceptance criteria**:

- [x] Table wired to real API data (no static mocks)
- [x] Color coding matches design system health thresholds
- [x] Sparkline shows 12-week composite trend (miniature line chart)
- [x] At-risk badge visible for tenants with `at_risk_flag=true`
- [x] Row click navigates to tenant drilldown with health section open
- [x] Loading skeleton during API fetch
- [x] 0 TypeScript errors

---

### PA-011: Proactive outreach

**Status**: ✅ COMPLETED
**Effort**: 5h
**Depends on**: PA-008
**Description**: `POST /platform/tenants/{id}/message`. Platform admin sends in-app notification to tenant admin(s). Request: `{ "subject": "string", "body": "string", "send_via": ["in_app", "email"] }`. In-app: inserts into `notifications` table. Email: SendGrid template via existing email service. Records outreach in `audit_log`. `require_platform_admin`.
**Backend**: `app/modules/tenants/routes.py` (proactive_outreach route + helpers), `alembic/versions/v015_notifications_platform_outreach.py`
**Tests**: `tests/unit/test_platform_outreach.py` — 15/15 passing
**Acceptance criteria**:

- [x] In-app notification created in `notifications` table with `from_platform_admin=true` flag
- [x] Email sent via SendGrid if `"email"` in `send_via` list
- [x] Outreach logged to `audit_log` (actor=platform_admin, target=tenant_id, action="proactive_outreach")
- [x] `require_platform_admin` enforced
- [x] 422 if both `subject` and `body` are blank
- [x] Frontend: "Message Tenant" button in at-risk tenant drilldown panel with compose modal

---

### Sprint B3: Cost Monitoring and Gross Margin (Weeks 13-14)

### PA-012: Token attribution pipeline

**Status**: ✅ COMPLETED
**Effort**: 8h
**Depends on**: P2LLM-010, P2LLM-011
**Completed**: 2026-03-16 — commit ef68d18
**Description**: Nightly batch job that aggregates `usage_events` → `cost_summary_daily` table (new table: `tenant_id`, `date`, `total_tokens_in`, `total_tokens_out`, `total_cost_usd`, `model_breakdown` JSONB). `model_breakdown` = per-model cost aggregation. Token × model cost rate calculation already in P2LLM-011. This batch job pre-aggregates for performance (cost dashboard queries hit this table, not raw `usage_events`).
**Evidence**: `alembic/versions/v016_cost_summary_daily.py` migration, `app/modules/platform/cost_summary_job.py` nightly batch (RLS bypass via both `app.user_role` + `app.current_scope`), `tests/unit/test_cost_summary_job.py` passing.
**Acceptance criteria**:

- [x] `cost_summary_daily` table Alembic migration included
- [x] Nightly batch job populates `cost_summary_daily` from `usage_events`
- [x] Upsert on `(tenant_id, date)` conflict
- [x] `model_breakdown` JSONB structure: `[{ "model": "...", "provider": "...", "tokens_in": N, "tokens_out": N, "cost_usd": X }]`
- [x] Job runtime < 10 minutes for 100 tenants × 30 days backfill
- [x] Unit test: aggregation formula verified against known `usage_events` fixture

---

### PA-013: Gross margin calculation

**Status**: ✅ COMPLETED
**Effort**: 6h
**Depends on**: PA-012
**Completed**: 2026-03-16 — commit ef68d18
**Description**: Extend `cost_summary_daily` with margin calculation. Add columns: `plan_revenue_usd` NUMERIC(10,2) (from plan tier pricing constants in env), `infra_cost_estimate_usd` NUMERIC(10,2) (fixed cost per active tenant per day from env), `gross_margin_pct` NUMERIC(5,2). Formula: `(plan_revenue - llm_cost - infra_cost) / plan_revenue * 100`. Add to `GET /platform/tenants/{id}/cost-usage` response. Add per-tenant margin to cost analytics dashboard.
**Evidence**: `alembic/versions/v017_cost_summary_gross_margin.py` migration, `app/modules/platform/cost_analytics.py` returns `gross_margin_pct` in totals, `tests/unit/test_gross_margin.py` passing. 46 unit tests total across test_cost_summary_job.py + test_gross_margin.py.
**Acceptance criteria**:

- [x] `gross_margin_pct` column in `cost_summary_daily`
- [x] Plan revenue loaded from env: `PLAN_REVENUE_STARTER_DAILY_USD`, `PLAN_REVENUE_PRO_DAILY_USD`, `PLAN_REVENUE_ENTERPRISE_DAILY_USD`
- [x] Infra cost loaded from env: `INFRA_COST_PER_TENANT_DAILY_USD`
- [x] Margin capped at 100% and floored at -100% in DB (reality check)
- [x] Returned in cost API response as `gross_margin_pct`
- [x] Frontend: margin % displayed with `--accent` if > 60%, `--warn` if 30-60%, `--alert` if < 30%

---

### PA-014: Azure Cost Management API integration

**Status**: ✅ COMPLETED
**Effort**: 10h
**Depends on**: PA-012
**Completed**: 2026-03-16 — commit 224993a
**Description**: Pull actual Azure infrastructure costs from Azure Cost Management REST API. Endpoint: `https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.CostManagement/query`. Credentials: `AZURE_SUBSCRIPTION_ID`, `AZURE_COST_MGMT_CLIENT_ID`, `AZURE_COST_MGMT_CLIENT_SECRET` env vars. Schedule: daily pull with 24-48h delay acknowledged. Label costs as "estimated" with `last_updated_at` timestamp. Update `infra_cost_estimate_usd` in `cost_summary_daily` from real Azure data when available (fallback to env constant).
**Evidence**: `alembic/versions/v018_azure_cost_mgmt.py` migration (infra_is_estimated, infra_last_updated_at columns added to cost_summary_daily), `app/modules/platform/azure_cost_job.py` nightly pull at 03:45 UTC (OAuth, graceful degradation, RLS bypass fixed), `app/modules/platform/cost_analytics.py` updated with infra_is_estimated + infra_last_updated_at in response. 24 unit tests passing.
**Acceptance criteria**:

- [x] Azure Cost Management API queried daily (scheduled job)
- [x] Credentials from env vars — never hardcoded
- [x] 24-48h data delay handled: query for `TODAY - 2 days` (always available)
- [x] Cost data labeled with `last_updated_at` and `is_estimated: false` in API response (vs env constant fallback `is_estimated: true`)
- [x] Attribution model: total Azure spend divided by active tenant count (proportional by usage)
- [x] Fallback to env constant if Azure API unavailable (do not crash batch job)
- [x] Integration test with Azure API mock (real Azure calls in CI would incur cost)

---

### PA-015: Cost alert thresholds

**Status**: ✅ COMPLETED
**Effort**: 6h
**Depends on**: PA-012, PA-013
**Completed**: 2026-03-16 — commit 224993a
**Description**: Configurable cost alerts. `POST /platform/tenants/{id}/cost-alerts` — set per-tenant alert: `{ "daily_spend_threshold_usd": X, "margin_floor_pct": Y }`. Global defaults via `PATCH /platform/cost-alerts/defaults`. Alert evaluation: nightly batch job (post PA-012 run) checks thresholds and inserts notifications. Platform admin sees alerts in Issue Queue with severity=P2.
**Evidence**: `alembic/versions/v019_cost_alert_configs.py` migration (global default + per-tenant cost_alert_configs table), `app/modules/platform/cost_alerts.py` 4 endpoints (POST per-tenant, GET per-tenant, GET defaults, PATCH defaults) with UUID validation, atomic upsert+audit, require_platform_admin, `app/modules/platform/cost_alert_job.py` nightly P2 alerts at 04:00 UTC (duplicate suppression, all 3 RLS vars). 23 unit tests passing.
**Acceptance criteria**:

- [x] Per-tenant and global cost alert thresholds configurable
- [x] Stored in `tenant_configs` under `cost_alerts` key
- [x] Nightly check: if daily_spend > threshold → create P2 issue + notification
- [x] Nightly check: if margin_floor < threshold → create P2 issue + notification
- [x] Duplicate suppression: max 1 alert per tenant per calendar day per alert type
- [x] `require_platform_admin` on both routes
- [x] Frontend: cost alert config in tenant drilldown "Finance" section

---

### PA-016: Billing reconciliation export

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: PA-012, PA-013
**Description**: `GET /platform/cost-analytics/export` with query params `period` (month/custom) and `format=csv`. CSV columns: tenant_id, tenant_name, plan_tier, total_tokens_in, total_tokens_out, total_cost_usd, gross_margin_pct, plan_revenue_usd, period_start, period_end. `require_platform_admin`. Response: `Content-Type: text/csv` with `Content-Disposition: attachment; filename=billing-{period}.csv`.
**Acceptance criteria**:

- [ ] CSV export includes all specified columns
- [ ] Period filter: `month=YYYY-MM` or `from=YYYY-MM-DD&to=YYYY-MM-DD`
- [ ] CSV properly escaped (commas in tenant names handled)
- [ ] `require_platform_admin` enforced
- [ ] Download works in browser (correct Content-Type and Content-Disposition headers)

---

## Phase C: Issue Intelligence and Templates (Weeks 15-22)

### Sprint C1: Issue Queue Routing (verify Phase 1 wiring)

### PA-017: Issue queue routing refinement

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: none (audit and wire-up task)
**Description**: Audit current Phase 1 issue queue backend (issues/routes.py). Verify frontend wiring for: "Route to Tenant" action (sends in-app notification to tenant admin — does backend `POST /platform/issues/{id}/route` exist and is it wired in frontend?), "Close as Duplicate" action (links to original issue — does `PATCH /platform/issues/{id}` accept `duplicate_of` field?), "Request More Info" action (sends in-app message to reporter — does this endpoint exist?). Implement any missing backend and wire missing frontend actions.
**Acceptance criteria**:

- [ ] "Route to Tenant" action exists in backend + wired in `IssueActionBar.tsx` (FE-054)
- [ ] "Close as Duplicate" PATCH accepts `{ "status": "closed", "duplicate_of": UUID }` and links issues
- [ ] "Request More Info" sends notification to original reporter via notifications table
- [ ] All 3 actions wired in frontend `IssueActionBar.tsx` with correct API calls
- [ ] 0 TypeScript errors after wiring

---

### PA-018: Batch queue actions

**Status**: ⬜ TODO
**Effort**: 3h
**Depends on**: none (verify FE-054 wiring)
**Description**: Verify `BatchActionBar.tsx` (FE-054 — COMPLETE) is wired to batch action API endpoint. `POST /platform/issues/batch-action` with `{ "issue_ids": [UUID], "action": "close|route|escalate", "payload": {} }`. If endpoint missing from Phase 1, implement it. If frontend not wired, wire it.
**Acceptance criteria**:

- [ ] `POST /platform/issues/batch-action` endpoint exists and processes all issue_ids
- [ ] Supported actions: close, route, escalate (with target tenant/team in payload)
- [ ] Frontend `BatchActionBar.tsx` calls this endpoint on batch action selection
- [ ] Partial success handled: returns `{ "succeeded": [UUIDs], "failed": [{ "id": UUID, "error": "..." }] }`
- [ ] `require_platform_admin` enforced

---

### Sprint C2: Agent Template Library (Weeks 18-20)

### PA-019: `agent_templates` table

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: none
**Description**: Alembic migration for `agent_templates` table. Columns: `id` UUID PK, `name` VARCHAR, `category` VARCHAR (hr|it|finance|legal|procurement|custom), `system_prompt` TEXT, `variable_definitions` JSONB (array of `{ name, type, label, default, required }`), `guardrails` JSONB, `confidence_threshold` NUMERIC(3,2), `version` INTEGER, `status` VARCHAR CHECK(Draft|Published|Deprecated|seed), `changelog` TEXT, `created_at` TIMESTAMPTZ, `updated_at` TIMESTAMPTZ. No `tenant_id` column (platform-level table). Platform admin full access; tenant admin read Published+seed.
**Acceptance criteria**:

- [ ] Alembic migration with all columns and constraints
- [ ] `status` CHECK constraint includes 'seed' value (for hardcoded seed templates in TA-020)
- [ ] `version` INTEGER starting at 1 (incremented on each update after first publish)
- [ ] `variable_definitions` JSONB validated at API layer (not DB constraint)
- [ ] RLS: platform_admin full CRUD; tenant scope SELECT WHERE status IN ('Published', 'seed')
- [ ] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [ ] Migration is reversible

---

### PA-020: Agent template CRUD API

**Status**: ⬜ TODO
**Effort**: 8h
**Depends on**: PA-019
**Description**: `POST /platform/agent-templates` (create Draft), `GET /platform/agent-templates` (list with status filter), `GET /platform/agent-templates/{id}` (detail), `PATCH /platform/agent-templates/{id}` (update Draft fields only — Published versions immutable for system_prompt). Variable definition system: JSONB array with type validation (text|number|select). Status lifecycle: Draft → Published → Deprecated (same pattern as LLM Library).
**Acceptance criteria**:

- [ ] All 5 endpoints implemented and registered
- [ ] Published templates: `system_prompt` is immutable — PATCH with new `system_prompt` returns 409 (create new version instead)
- [ ] Variable definitions validated: each entry has `name`, `type`, `label`, `required` fields
- [ ] `GET /platform/agent-templates` supports `?status=` and `?category=` filters
- [ ] `require_platform_admin` on POST/PATCH; no auth on GET (tenant admins also access)
- [ ] Changelog field required on Publish action (`system_prompt` changes must be documented)

---

### PA-021: Template test harness API

**Status**: ⬜ TODO
**Effort**: 6h
**Depends on**: PA-020, P2LLM-009
**Description**: `POST /platform/agent-templates/{id}/test`. Accepts `{ "variable_values": { "role": "HR Manager" }, "test_prompts": ["What is our parental leave policy?"] }`. Substitutes variables into system_prompt, runs each test prompt via `InstrumentedLLMClient`, returns AI responses + token counts + guardrail trigger log.
**Acceptance criteria**:

- [ ] Variable substitution: `{{variable_name}}` pattern in system_prompt replaced with values
- [ ] Missing required variable returns 422 with field name
- [ ] Max 5 test prompts per request (429 if exceeded)
- [ ] Response includes per-prompt: `{ "prompt": "...", "response": "...", "tokens_in": N, "tokens_out": N, "guardrail_triggered": bool, "guardrail_reason": "..." }`
- [ ] Guardrail triggers logged (if guardrails JSONB has patterns)
- [ ] Timeout: 30s per prompt; partial results returned if some timeout
- [ ] `require_platform_admin` enforced

---

### PA-022: Template versioning

**Status**: ⬜ TODO
**Effort**: 5h
**Depends on**: PA-020
**Description**: `POST /platform/agent-templates/{id}/new-version`. Creates a new Draft version (incremented `version` field) copying all fields from current Published version. New version can have different `system_prompt`. `GET /platform/agent-templates/{id}/versions` returns version history. Published versions never modified — create new version to change system_prompt.
**Acceptance criteria**:

- [ ] `POST /platform/agent-templates/{id}/new-version` creates Draft with version=N+1
- [ ] New Draft version copies all fields from source (including variable_definitions, guardrails)
- [ ] `GET /platform/agent-templates/{id}/versions` returns all versions sorted by version DESC
- [ ] Version history includes: version, status, published_at, changelog, first 100 chars of system_prompt
- [ ] `require_platform_admin` enforced on write endpoints

---

### PA-023: Tenant template instance deployment API

**Status**: ⬜ TODO
**Effort**: 6h
**Depends on**: PA-020, PA-019
**Description**: `POST /admin/agents` — tenant admin deploys an agent from a template. Request: `{ "template_id": UUID, "name": "Our HR Bot", "variable_values": { "role": "HR Manager" }, "kb_ids": [UUID], "description": "..." }`. Creates agent instance in `agent_cards` table with `template_id` FK, resolved system_prompt (variables substituted), no system_prompt override allowed. `GET /admin/agents` lists deployed agents with version, satisfaction summary, status.
**Acceptance criteria**:

- [ ] POST validates all required variables in template are provided
- [ ] System_prompt stored in `agent_cards.system_prompt` with variables substituted (not template references)
- [ ] `template_id` stored in `agent_cards` for future version tracking (PA-024)
- [ ] GET `/admin/agents` returns: name, template_name, version, status, satisfaction_rate, created_at
- [ ] `require_tenant_admin` on both routes
- [ ] `kb_ids` validated: each KB must belong to calling tenant (403 if cross-tenant)

---

### PA-024: Agent template library frontend wiring

**Status**: ⬜ TODO
**Effort**: 8h
**Depends on**: PA-020, PA-021, PA-022, PA-023
**Description**: Verify `TemplateAuthoringForm.tsx` (FE-044 — COMPLETE in Phase 1) is wired to new API endpoints. If FE-044 has mock data, replace with real API calls. Add: test harness UI (submit 1-5 prompts, show results panel), version history drawer, publish/deprecate lifecycle buttons. Also: Tenant Admin template browser UI — card grid of Published templates with category filter and [Deploy] button leading to deployment wizard.
**Acceptance criteria**:

- [ ] `TemplateAuthoringForm.tsx` wired to POST/PATCH `/platform/agent-templates` (real API)
- [ ] Test harness: text area for prompts, Submit button, results slide-in panel with token/latency DM Mono
- [ ] Version history: drawer showing version list with changelog
- [ ] Tenant Admin template browser: card grid, category filter chips, [Deploy] button
- [ ] Deployment wizard: variable value inputs (one per required variable), KB selector, name field
- [ ] 0 TypeScript errors

---

### Sprint C3: Template Analytics and Roadmap Signals (Weeks 21-22)

### PA-025: Template performance tracking

**Status**: ⬜ TODO
**Effort**: 6h
**Depends on**: PA-023
**Description**: Nightly batch job aggregates per-template satisfaction rate, guardrail trigger rate, failure pattern. Sources: `user_feedback.rating` linked to conversation → agent → template; issue reports with `agent_id` linked to template; guardrail events (add to analytics_events). Store results in new `template_performance_daily` table (template_id, date, satisfaction_rate, guardrail_trigger_rate, failure_count, session_count).
**Acceptance criteria**:

- [ ] `template_performance_daily` table Alembic migration included
- [ ] Satisfaction rate: positive feedback / total feedback for sessions using this template
- [ ] Guardrail trigger rate: guardrail events / total sessions
- [ ] Failure count: `user_feedback.rating = -1` count (thumbs down)
- [ ] Session count: distinct conversation_ids using this template
- [ ] Batch job nightly; upsert on (template_id, date)
- [ ] Unit test: aggregation formula verified

---

### PA-026: Template analytics API

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: PA-025
**Description**: `GET /platform/agent-templates/{id}/analytics`. Returns satisfaction rate over time (30-day rolling), cross-tenant aggregation (usage count across all tenants using this template), guardrail trigger rate trend, failure pattern top-3. `require_platform_admin`.
**Acceptance criteria**:

- [ ] 30-day daily data points in response
- [ ] Cross-tenant aggregation (template used by multiple tenants — aggregate, do not expose per-tenant data)
- [ ] Failure patterns: top 3 common issue categories from issue reports linked to this template
- [ ] Response time < 1s
- [ ] `require_platform_admin` enforced

---

### PA-027: Underperforming template alerts

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: PA-025, PA-026
**Description**: Flag templates with satisfaction_rate < (platform average − 10%). Detection: nightly batch job post PA-025. If condition met for 7+ consecutive days: create P2 issue in issue queue with `category="template_performance"`, add to platform admin notification. Alert cleared automatically when satisfaction recovers.
**Acceptance criteria**:

- [ ] Platform average satisfaction calculated across all Published templates nightly
- [ ] Threshold: `template_satisfaction < platform_avg - 0.10`
- [ ] P2 issue created in issue queue with template_id reference
- [ ] Alert fires only after 7 consecutive days below threshold (prevents noise)
- [ ] Auto-clear: issue closed when satisfaction recovers above threshold for 3 consecutive days
- [ ] Duplicate prevention: max 1 open alert per template

---

### PA-028: Roadmap signal board API

**Status**: ⬜ TODO
**Effort**: 5h
**Depends on**: none (sources from existing issue_reports)
**Description**: `GET /platform/roadmap-signals`. Aggregated feature requests ranked by frequency × plan weight. Weight: enterprise=3, professional=2, starter=1. Source: `issue_reports` with `category="feature_request"`. Grouping: cluster similar requests by keyword similarity (simple TF-IDF approach — no LLM needed for MVP). Response: ranked list of `{ "signal": "text", "count": N, "weighted_score": X, "plan_breakdown": {} }`.
**Acceptance criteria**:

- [ ] Feature request issues extracted from `issue_reports WHERE category='feature_request'`
- [ ] Weighted score = SUM(plan_weight) for each distinct feature cluster
- [ ] Simple grouping acceptable for MVP: exact title match + manual merge
- [ ] Plan breakdown shows count per plan tier
- [ ] `require_platform_admin` enforced
- [ ] Sorted by `weighted_score DESC`

---

### PA-029: Feature adoption table API

**Status**: ⬜ TODO
**Effort**: 5h
**Depends on**: none (sources from analytics_events)
**Description**: `GET /platform/feature-adoption`. Per-feature tenant adoption rate, satisfaction rate, sessions/week. Features tracked: chat, glossary, agent_templates, knowledge_base, SSO, cost_analytics, cache_analytics. Adoption = percent of active tenants using each feature in last 30 days. Source: `analytics_events` grouped by `feature_name` attribute.
**Acceptance criteria**:

- [ ] All 7 features listed with adoption %, satisfaction rate, avg sessions/week/tenant
- [ ] Adoption threshold: at least 1 session in last 30 days = "adopted"
- [ ] `require_platform_admin` enforced
- [ ] Data sourced from `analytics_events` (not hardcoded)
- [ ] Response time < 2s

---

## Phase D: Tool Catalog and Polish (Weeks 23-28)

### PA-030: `tool_catalog` table

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: none
**Description**: Alembic migration for `tool_catalog` table. Columns: `id` UUID PK, `name` VARCHAR, `provider` VARCHAR, `mcp_endpoint` VARCHAR, `auth_type` VARCHAR CHECK(none|api_key|oauth2), `capabilities` JSONB, `safety_classification` VARCHAR CHECK(ReadOnly|Write|Destructive) NOT NULL (immutable after creation), `health_status` VARCHAR CHECK(healthy|degraded|unavailable), `version` VARCHAR, `last_health_check` TIMESTAMPTZ, `health_check_url` VARCHAR, `created_at` TIMESTAMPTZ. No tenant_id (platform-level). RLS: platform_admin full access; tenant admin SELECT healthy tools only.
**Acceptance criteria**:

- [ ] `safety_classification` immutable: no UPDATE on this column allowed after INSERT (CHECK trigger or application-layer enforcement)
- [ ] `health_status` CHECK constraint enforces healthy|degraded|unavailable
- [ ] `capabilities` JSONB: array of capability strings
- [ ] RLS: tenant scope can SELECT WHERE health_status = 'healthy'
- [ ] RLS policy (tenant_isolation + platform_admin_bypass) added in THIS migration file — do not rely on v002's frozen `_V001_TABLES` list
- [ ] Migration is reversible

---

### PA-031: Tool registration API

**Status**: ⬜ TODO
**Effort**: 8h
**Depends on**: PA-030
**Description**: `POST /platform/tools`. On registration: automated health check sequence — (1) endpoint reachability, (2) auth handshake (if auth_type != none), (3) schema validation (GET /schema from MCP endpoint), (4) sample invocation (low-risk capability). Registration succeeds only if all 4 checks pass. `require_platform_admin`. Also: `GET /platform/tools` (list), `GET /platform/tools/{id}` (detail), `DELETE /platform/tools/{id}` (removes from catalog; tenants with active assignments notified).
**Acceptance criteria**:

- [ ] Registration endpoint runs all 4 health check steps sequentially
- [ ] If any step fails: return 422 with step name + error details; no row inserted
- [ ] `safety_classification` set at registration time — cannot be changed later
- [ ] `DELETE /platform/tools/{id}` sends notification to tenants with active tool assignments
- [ ] `require_platform_admin` on write endpoints
- [ ] Health check timeout: 10s per step

---

### PA-032: Continuous tool health monitoring

**Status**: ⬜ TODO
**Effort**: 6h
**Depends on**: PA-030, PA-031
**Description**: Background job pings `health_check_url` every 5 minutes with ±30s jitter (to avoid thundering herd). Degraded: 3 consecutive failures. Unavailable: 10 consecutive failures. Healthy: 1 success resets counter. On status change: update `tool_catalog.health_status` and `last_health_check`. On Unavailable: create P1 issue in issue queue. On recovery: close open P1 issue.
**Acceptance criteria**:

- [ ] Jitter: random offset ±30s added to each 5-min interval
- [ ] Degraded after 3 consecutive failures (not 3 total)
- [ ] Unavailable after 10 consecutive failures
- [ ] Status change logged to `audit_log`
- [ ] P1 issue created on Unavailable transition (not on each failure)
- [ ] P1 issue auto-closed on Healthy transition
- [ ] Health check uses HEAD request (not GET — avoids triggering actual tool logic)

---

### PA-033: Tool usage analytics API

**Status**: ⬜ TODO
**Effort**: 4h
**Depends on**: PA-031
**Description**: `GET /platform/tools/{id}/analytics`. Invocation frequency (daily count), latency (p50, p95), error rate over last 30 days per tool per tenant (aggregated). Source: tool invocation events from `analytics_events` with `event_type="tool_invocation"`. `require_platform_admin`.
**Acceptance criteria**:

- [ ] Invocation frequency: daily count time series
- [ ] Latency percentiles: p50 and p95 from latency_ms in analytics_events
- [ ] Error rate: failed invocations / total invocations per day
- [ ] Cross-tenant aggregation (total, not per-tenant breakdown — privacy)
- [ ] `require_platform_admin` enforced

---

### PA-034: Platform daily digest email

**Status**: ⬜ TODO
**Effort**: 6h
**Depends on**: PA-008, PA-015, PA-027
**Description**: Configurable daily summary email sent to platform admin(s) at configured time (default 07:00 UTC). Content: new issues since last digest, health status changes (tenants moved to/from at-risk), cost variance (daily spend vs 7-day avg), underperforming template alerts. SendGrid dynamic template. Config: `PATCH /platform/digest/config` with `{ "enabled": true, "time": "07:00", "recipients": ["admin@example.com"] }`.
**Acceptance criteria**:

- [ ] SendGrid dynamic template created with digest layout
- [ ] Digest includes: new issues count, at-risk changes, cost variance %, alert count
- [ ] `POST /platform/digest/preview` returns digest content without sending (for testing)
- [ ] Config endpoint: `PATCH /platform/digest/config` stores in platform_configs (new table or extend tenant_configs for platform scope)
- [ ] Scheduled cron respects configured time (UTC)
- [ ] `require_platform_admin` on all digest endpoints

---

### PA-035: GDPR deletion workflow API

**Status**: ⬜ TODO
**Effort**: 8h
**Depends on**: DEF-002 (consent_events table — deletion report must enumerate consent records that were deleted)
**Description**: `POST /platform/tenants/{id}/gdpr-delete`. Verified deletion pipeline: (1) verify tenant has no active subscriptions (billing check), (2) soft-delete tenant record (set `deleted_at`), (3) hard-delete all user PII (name, email → anonymized), (4) delete conversation content from messages table, (5) delete memory notes, (6) delete document content, (7) retain anonymized usage_events and audit_log for legal hold (tenant_id preserved, user_id anonymized). Generate confirmation report: `{ "deleted_tables": [...], "retained_for_legal_hold": [...], "completed_at": "..." }`.
**Acceptance criteria**:

- [ ] All 7 pipeline steps execute in order; atomic (all or nothing via transaction)
- [ ] User PII: `name` → "DELETED*USER*{uuid*prefix}", `email` → "deleted*{uuid}@gdpr.invalid"
- [ ] `conversations.content` and `messages.content` deleted (not anonymized)
- [ ] `usage_events` and `audit_log` retained with anonymized user_id
- [ ] Confirmation report returned in API response AND stored as `audit_log` entry
- [ ] `require_platform_admin` enforced
- [ ] Dry-run mode: `?dry_run=true` returns report without executing deletion

---

### PA-036: Audit log searchable UI

**Status**: ⬜ TODO
**Effort**: 5h
**Depends on**: none (verify FE-056 wiring)
**Description**: Verify `AuditLogTable.tsx` (FE-056 — COMPLETE in Phase 1) works with real `audit_log` table data. Add actor/resource/action filter to backend `GET /platform/audit-log` if not already present. Wire filters to frontend filter chips. Add date range picker. Ensure audit log entries from all Phase 2+ actions (profile changes, health score updates, GDPR deletions) are present.
**Acceptance criteria**:

- [ ] `GET /platform/audit-log` supports `?actor=`, `?resource_type=`, `?action=`, `?from=`, `?to=` query params
- [ ] `AuditLogTable.tsx` frontend filter chips wired to these query params
- [ ] Date range picker integrated (default: last 7 days)
- [ ] Pagination: 50 rows per page with cursor-based `?after=` param
- [ ] All Phase 2+ audit events visible (profile changes, GDPR, health alerts)
- [ ] 0 TypeScript errors

---

## Dependencies Map

```
Phase B:
  P2LLM-004/005 (LLM Library) → PA-001/002/003/004/005
  PA-006 (health_scores table) → PA-007 (batch job) → PA-008/009/010/011
  PA-012 (token attribution) → PA-013 (gross margin) → PA-014/015/016

Phase C:
  Phase B complete → PA-017/018 (issue queue)
  PA-019 (agent_templates table) → PA-020 (CRUD API) → PA-021/022/023/024
  PA-023 (tenant deploy) → PA-025 (performance tracking) → PA-026/027
  PA-028/029 (signals/adoption) — independent

Phase D:
  PA-030 (tool_catalog table) → PA-031 (registration) → PA-032/033
  PA-034 (digest) ← PA-008, PA-015, PA-027
  PA-035 (GDPR) — independent
  PA-036 (audit UI) — independent
```

---

## Notes

- FE-040 (`TenantHealthTable`), FE-044 (`TemplateAuthoringForm`), FE-054 (`BatchActionBar`), FE-056 (`AuditLogTable`) are all COMPLETE from Phase 1 — Phase B/C/D items are primarily backend + API wiring
- `safety_classification` immutability on `tool_catalog` is a security requirement — Destructive tools cannot be retroactively reclassified as ReadOnly
- GDPR deletion workflow must NOT be reversible — implement confirmation step with admin password re-entry
- Phase C Sprint C2 (Agent Studio) is product-gated (TA-025 in 05-tenant-admin-phase-b-d.md) — do not implement agent authoring UI until persona interviews complete
