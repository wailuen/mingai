# TODO-24: Agent Studio Phase 2 — PA Platform A2A Registry

**Status**: ACTIVE
**Priority**: LOW (Phase 2)
**Estimated Effort**: 2 days
**Phase**: Phase 2 — Platform Admin Authoring Studio

---

## Description

Platform admins register external A2A agents at platform scope — these become available for eligible tenants to deploy (plan-gated), unlike tenant-registered A2A agents (TODO-19) which are private to one tenant. PA-registered A2A agents follow the same card-import flow as tenant registration but add plan gating, per-tenant wrapper configuration, and platform-level health monitoring.

PA also manages the platform-wide A2A registry: reviewing all registered agents (platform-scope and aggregate view of tenant-scope), setting guardrail overlays on platform agents, and monitoring A2A agent health.

---

## Acceptance Criteria

- [ ] PA navigates to Platform > Agent Templates > A2A Registry tab and sees all platform-registered A2A agents
- [ ] [+ Register A2A Agent] opens the same card import flow as TODO-19 but with additional PA-only fields: plan gate, guardrail overlay, assignment scope (all tenants / specific tenants)
- [ ] PA can set guardrails overlay on a platform A2A agent — these apply on top of whatever the external agent returns; tenant cannot remove them
- [ ] PA can assign to specific tenants (by tenant ID or tenant name) or make available to all matching plan
- [ ] Platform A2A agents appear in TA Agent Library (TODO-14) filtered by tenant's eligibility (plan + explicit assignment)
- [ ] PA sees health status for all platform A2A agents: last verified, uptime %, response latency P50
- [ ] PA can trigger manual health check on any platform A2A agent
- [ ] PA can deprecate a platform A2A agent: notification to all tenants who have deployed instances; 30-day deprecation window; agents continue to function until window closes
- [ ] Aggregate view: total platform A2A agents, total tenant A2A agents, total A2A agent invocations trailing 30d
- [ ] Tenant A2A section: aggregate only — "N tenants have registered X private A2A agents"

---

## Backend Changes

### Extend agent_cards for Platform A2A

Add new migration (v055): platform A2A specific columns.

```sql
ALTER TABLE agent_cards
    ADD COLUMN IF NOT EXISTS a2a_scope VARCHAR(32) NOT NULL DEFAULT 'tenant'
        CHECK (a2a_scope IN ('platform', 'tenant')),  -- 'platform' for PA-registered
    ADD COLUMN IF NOT EXISTS guardrail_overlay JSONB NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS assigned_tenants JSONB NOT NULL DEFAULT '[]',
    -- [] means available to all tenants matching plan_required
    ADD COLUMN IF NOT EXISTS deprecation_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deprecated_by UUID;
```

### Platform A2A Registry Endpoints

File: `src/backend/app/modules/agents/platform_a2a_routes.py`

```python
# PA-only
GET    /platform/a2a-agents                     # List platform A2A agents
POST   /platform/a2a-agents/register            # Register external A2A agent (platform scope)
GET    /platform/a2a-agents/{id}                # Agent detail + health stats
PUT    /platform/a2a-agents/{id}                # Update wrapper config (guardrail_overlay, plan_required, assigned_tenants)
POST   /platform/a2a-agents/{id}/verify         # Manual health check
POST   /platform/a2a-agents/{id}/deprecate      # Start deprecation window (30 days)
DELETE /platform/a2a-agents/{id}                # Hard delete (only if no tenant deployments)

# Aggregate view
GET    /platform/a2a-agents/registry-summary    # { platform_count, tenant_count (aggregate), total_invocations_30d }
```

### Extend TA Template Catalog (GET /agents/templates)

Modify query to include platform A2A agents in template list:
- Filter `template_type = 'registered_a2a'` AND `a2a_scope = 'platform'`
- Apply plan gate filter (tenant's plan >= plan_required)
- Apply assigned_tenants filter (tenant in assigned_tenants OR assigned_tenants is empty)
- Filter out agents past `deprecation_at`

### Deprecation Notification

On PA deprecating a platform A2A agent:
1. Find all tenant agent instances derived from this platform A2A agent
2. Notify affected tenant admins: "Platform A2A agent '{name}' is being deprecated on {date}. Your instances will continue to work until that date. Please migrate to an alternative."
3. Set `deprecation_at = NOW() + 30 days` on the agent_cards record

---

## Frontend Changes

### New Tab on Agent Templates Page

Add "A2A Registry" tab to PA Agent Templates page.

### New Components

#### `PAA2ARegistryTab.tsx`

Location: `src/web/app/(platform)/platform/agent-templates/elements/PAA2ARegistryTab.tsx`

- Summary bar: Platform A2A agents count, Tenant A2A agents (aggregate), Total invocations 30d
- Platform agents table: Name, Card URL (truncated), Plan Gate, Assignment Scope, Health, Last Verified, Actions
- Actions: [Edit], [Verify], [Deprecate], [Delete]
- Health column: green dot (verified < 1h ago), yellow dot (1-24h), red dot (>24h or unhealthy)
- Tenant section: "N tenants have registered X private A2A agents (aggregate — details not accessible)"

#### `PAA2ARegistrationPanel.tsx`

Location: `src/web/app/(platform)/platform/agent-templates/elements/PAA2ARegistrationPanel.tsx`

Extends tenant A2A registration (TODO-19) with PA-only fields:

Additional Section — Platform Configuration:
- Plan Gate dropdown (None / Starter / Professional / Enterprise)
- Assignment Scope radio: "All eligible tenants" / "Specific tenants"
- Tenant selector: multi-select (if specific tenants mode); search by tenant name

Additional Section — Guardrail Overlay:
- "These guardrails apply on top of the external agent's output; tenants cannot remove them"
- Reuse `GuardrailsEditor` (subset — only output filters and PII masking)
- Blocked topics chip input
- PII masking toggle

#### `A2AHealthMonitor.tsx`

Location: `src/web/app/(platform)/platform/agent-templates/elements/A2AHealthMonitor.tsx`

- Health status card for a single A2A agent
- Last verified timestamp
- Uptime %: calculated from health check history (pass/fail log)
- P50 latency: from health check timing
- [Verify Now] button

### New Hooks

File: `src/web/hooks/usePlatformA2ARegistry.ts`

```typescript
usePlatformA2AAgents()                          → { agents, isLoading }
registerPlatformA2AAgent(data)                  → mutation
updatePlatformA2AAgent(id, data)                → mutation
verifyPlatformA2AAgent(id)                      → mutation
deprecatePlatformA2AAgent(id)                   → mutation
useA2ARegistrySummary()                         → { summary, isLoading }
```

---

## Dependencies

- TODO-13 (DB schema) — agent_cards extended columns
- TODO-19 (TA A2A) — card fetcher reused; health check worker extended
- TODO-14 (TA Agent Library) — platform A2A agents must appear in TA template catalog

---

## Risk Assessment

- **HIGH**: SSRF in card fetcher — same protection as TODO-19 (already solved there; verify it's reused, not duplicated)
- **MEDIUM**: Guardrail overlay enforcement — must be applied in A2A proxy (TODO-19 `a2a_proxy.py`) when caller is a platform-registered agent; overlay fetched from agent_cards `guardrail_overlay` column
- **LOW**: Deprecation timing — 30-day window may not be enough for enterprise tenants; make configurable per-agent deprecation window

---

## Testing Requirements

- [ ] Unit test: platform A2A agent appears in `GET /agents/templates` only for tenants matching plan gate + assignment
- [ ] Unit test: `a2a_proxy.invoke` applies `guardrail_overlay` from agent_cards (not just template config)
- [ ] Unit test: deprecation sets `deprecation_at` and creates notifications
- [ ] Unit test: agents past `deprecation_at` excluded from `/agents/templates`
- [ ] Integration test: PA registers A2A agent; TA on eligible plan sees it in catalog
- [ ] Integration test: PA restricts to specific tenants; other tenants do not see agent
- [ ] E2E test: PA deprecates agent; affected TA sees deprecation warning on agent card

---

## Definition of Done

- [ ] PA A2A Registry tab functional with full management capabilities
- [ ] Registration panel with plan gate + assignment + guardrail overlay
- [ ] Platform A2A agents visible in TA catalog filtered by eligibility
- [ ] Guardrail overlay applied in A2A proxy invocations
- [ ] Deprecation workflow with tenant notification
- [ ] Health monitoring display
- [ ] All acceptance criteria met
