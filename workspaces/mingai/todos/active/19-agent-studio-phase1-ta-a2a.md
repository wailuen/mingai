# TODO-19: Agent Studio Phase 1 — TA A2A Agent Registration

**Status**: ACTIVE
**Priority**: LOW
**Estimated Effort**: 2 days
**Phase**: Phase 1 — Tenant Admin Surfaces

---

## Description

Tenant admins can register their own external A2A agents — services they own and operate externally. The platform wraps these agents via the A2A protocol without owning their runtime. Registered A2A agents are private to the tenant (Type 5, tenant scope). They become available in the end-user chat agent selector and can be invoked via the orchestrator.

This is distinct from platform-registered A2A agents (PA scope, Type 5, licensed by PA to tenants) — those are handled in TODO-24.

---

## Acceptance Criteria

- [ ] TA navigates to Workspace > Agents > A2A Agents tab and sees list of registered external agents
- [ ] [+ Register A2A Agent] button opens registration panel
- [ ] TA provides: Agent Card URL (HTTPS), display name, description, icon
- [ ] Platform fetches the A2A card from the URL, parses operations, and displays a preview for confirmation
- [ ] TA confirms the parsed operations contract and completes registration
- [ ] Registered agent appears in agent list with "External" type badge and verified/unverified status
- [ ] Platform performs periodic health check on registered A2A agents (every 15 min via background job)
- [ ] If health check fails: agent status = `unhealthy`; alert shown in TA agents list; agent removed from chat selector until healthy
- [ ] Registered A2A agent appears in end-user chat agent selector (if healthy + authorized)
- [ ] TA can set access control on the A2A agent wrapper (same workspace/role/user modes)
- [ ] TA can deregister an agent (removes from chat selector; existing conversations preserved in history)

---

## Backend Changes

### Extend agent_cards for A2A Registration

Ensure `template_type = 'registered_a2a'` and `source_card_url`, `imported_card` columns exist (added in TODO-13 migration v049). No additional schema migration needed.

### New Endpoints

File: `src/backend/app/modules/agents/routes.py`

```python
POST /admin/agents/a2a/register
    # Accepts: card_url, display_name, description, icon, access_rules
    # Fetches card from URL (10s timeout)
    # Validates A2A card schema (has operations, input/output schema)
    # Stores in agent_cards with template_type='registered_a2a'
    # Inserts access_control rows
    # Returns: registered agent with parsed card preview

GET  /admin/agents/a2a/{agent_id}/card
    # Returns the imported_card JSONB for display

POST /admin/agents/a2a/{agent_id}/verify
    # Re-fetches card and pings health endpoint
    # Updates status and last_verified_at

DELETE /admin/agents/a2a/{agent_id}
    # Removes registration; soft-delete (status='archived')
    # Redis cache invalidation
```

### A2A Card Fetcher

File: `src/backend/app/modules/agents/a2a_card_fetcher.py`

```python
async def fetch_and_validate_card(card_url: str, timeout: float = 10.0) -> A2ACard:
    """
    Fetch agent card from URL.
    Validate required fields: name, description, operations (array with at least 1 entry).
    Each operation must have: name, description, inputSchema, outputSchema.
    Raise A2ACardValidationError if card is invalid.
    NEVER follow redirects to non-HTTPS endpoints.
    Sanitize all string fields from card (strip HTML, limit lengths).
    """

async def health_check(agent_id: str, card_url: str) -> HealthCheckResult:
    """Ping card URL and verify it returns valid A2A card. 5s timeout."""
```

### Background Health Check Job

File: `src/backend/app/modules/agents/a2a_health_worker.py`

- Scheduled every 15 minutes (use existing background task mechanism in the platform)
- For each tenant_registered A2A agent: call `health_check()`
- On failure: UPDATE status = `unhealthy`, publish Redis cache invalidation
- On recovery: UPDATE status = `active`, publish Redis cache invalidation
- Log health check results to audit log

### A2A Proxy Invocation

File: `src/backend/app/modules/agents/a2a_proxy.py`

```python
async def invoke_a2a_agent(
    agent_id: str,
    operation_name: str,
    input_data: dict,
    tenant_id: str,
    user_id: str
) -> A2AResponse:
    """
    Forward request to external A2A agent endpoint.
    Include auth headers if configured.
    Enforce 30s timeout.
    Apply guardrails overlay from wrapper config before returning response.
    Write invocation to audit log.
    NEVER forward tenant credentials or internal IDs to external agent.
    """
```

This proxy is called from the chat orchestration pipeline when the routed agent is type `registered_a2a`.

---

## Frontend Changes

### New Tab: A2A Agents

Add "A2A Agents" tab to the workspace agents page (alongside "My Agents" and the agent library).

### New Components

#### `TenantA2AAgentsTab.tsx`

Location: `src/web/app/settings/agents/elements/TenantA2AAgentsTab.tsx`

- Table: Name, Status, Operations Count, Last Verified, Actions
- Status badge: Active (accent-dim), Unhealthy (alert-dim), Unverified (warn-dim)
- [+ Register A2A Agent] button in top-right
- Actions per row: [Re-verify], [Edit access], [Deregister]

#### `A2ARegistrationPanel.tsx`

Location: `src/web/app/settings/agents/elements/A2ARegistrationPanel.tsx`

- Slides in from right, 480px wide
- Header: "Register External A2A Agent" + × close
- Step 1 — Card URL:
  - Display name input
  - Description textarea
  - Icon picker (reuse `IconPicker` from TODO-18)
  - Agent Card URL input (HTTPS only, validated on blur)
  - [Fetch Card] button: calls fetch endpoint; shows spinner; on success shows card preview
- Step 2 — Confirm (shown after successful card fetch):
  - Card preview: agent name from card, description, operations list
  - Access control section (same `AccessControlEditor` from custom agents)
  - [Register] button
- Error state: "Could not fetch card: {error}. Check the URL and try again."

### New Hooks

File: `src/web/hooks/useA2AAgents.ts`

```typescript
useTenantA2AAgents()             → { agents, isLoading }
registerA2AAgent(data)           → mutation → { agent_id }
verifyA2AAgent(agentId)          → mutation
deregisterA2AAgent(agentId)      → mutation
fetchA2ACard(cardUrl)            → mutation → { card: A2ACard }
```

---

## Dependencies

- TODO-13 (DB schema) — `source_card_url`, `imported_card`, `template_type` columns in agent_cards
- TODO-15 (Deploy Wizard) — access control pattern reused

---

## Risk Assessment

- **HIGH**: SSRF vulnerability in card fetcher — must validate URL is HTTPS, not internal network range (block 10.x.x.x, 192.168.x.x, 127.x.x.x, 169.254.x.x); enforce allowlist or blocklist
- **HIGH**: External agent response injection — guardrails overlay must be applied before responses reach users; external agents cannot be trusted to self-censor
- **MEDIUM**: Health check job — if external agent is slow or flaky, health check flooding should be limited; add jitter and exponential backoff on repeated failures
- **LOW**: Card URL drift — PA may update card at original URL; periodic re-fetch policy needed (currently only on manual re-verify + health check)

---

## Testing Requirements

- [ ] Unit test: `fetch_and_validate_card` rejects HTTP (non-HTTPS) URLs
- [ ] Unit test: `fetch_and_validate_card` blocks internal IP ranges (SSRF protection)
- [ ] Unit test: `fetch_and_validate_card` sanitizes string fields from card (no HTML injection)
- [ ] Unit test: health check marks agent unhealthy on timeout
- [ ] Unit test: `a2a_proxy.invoke_a2a_agent` does not forward tenant credentials in request body
- [ ] Integration test: register → verify → appears in `/agents` for authorized users
- [ ] Integration test: unhealthy agent removed from `/agents` list
- [ ] E2E test: TA registers mock A2A agent, end user sees it in chat selector, invocation reaches proxy

---

## Definition of Done

- [ ] A2A registration panel works end-to-end (fetch card → confirm → register)
- [ ] SSRF protection validated in card fetcher
- [ ] Health check background job operational
- [ ] Unhealthy agents excluded from end-user chat selector
- [ ] Guardrails overlay applied on all A2A proxy responses
- [ ] Audit log written for all invocations
- [ ] All acceptance criteria met
