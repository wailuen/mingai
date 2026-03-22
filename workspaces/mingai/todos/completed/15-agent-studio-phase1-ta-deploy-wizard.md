# TODO-15: Agent Studio Phase 1 — TA Agent Deployment Wizard

**Status**: ACTIVE
**Priority**: HIGH
**Estimated Effort**: 3 days
**Phase**: Phase 1 — Tenant Admin Surfaces

---

## Description

Tenant admins deploy platform template agents through a 4-step wizard. Step 4 (credentials) is conditional: only shown when the template's `auth_mode` is `tenant_credentials`. The wizard produces a deployed agent instance with: KB bindings wired to the agent's vector search, access control rows inserted, tenant vault credentials stored, and the agent immediately visible in the end-user chat selector.

This todo implements the full deployment wizard — the `AgentDeployWizard` modal plus all back-end changes required to make deployment work end-to-end.

---

## Acceptance Criteria

- [ ] Step 1: TA selects which template to deploy (if not pre-selected from catalog); sees capabilities, auth requirements, and plan gate check
- [ ] Step 2: TA binds KBs — recommended-category KBs sorted to top with accent dot; TA can multi-select; KB search input; toggle between parallel and priority KB search mode
- [ ] Step 2: Agent name field (pre-filled from template name, editable); system prompt variable fill inputs rendered from template `variable_schema`
- [ ] Step 3: Access control — workspace wide / role restricted / user list radio; role/user multi-select when applicable; rate limit numeric input
- [ ] Step 4 (conditional, only when auth_mode = tenant_credentials): Dynamic credential input form generated from template `required_credentials` schema; sensitive fields rendered as password inputs with eye toggle; [Test Connection] button with 15s timeout and progress indicator; skip allowed with warning
- [ ] Deploy button creates agent instance with all config
- [ ] Success overlay shows: agent name, bound KB count, tool count, access mode
- [ ] [Go to Agents] button navigates to agent list; [Deploy Another] resets wizard
- [ ] Deployed agent visible in end-user chat agent selector within 5 seconds (cache invalidated)
- [ ] End users only see agents they are authorized for (access control enforced on `GET /agents`)
- [ ] Template update banner shown on agent card if newer template version is published later

---

## Backend Changes

### Modify POST /admin/agents/deploy

File: `src/backend/app/modules/agents/routes.py`

Current endpoint exists but needs extension:

1. Accept `variable_values` dict — interpolate into `system_prompt_template` for the instance, validate all required variables are provided, strip control characters per `_CTRL_CHAR_RE` from each value
2. Accept `kb_search_mode: "parallel" | "priority"` — store in instance capabilities JSONB
3. Accept `rate_limit_per_minute: int` — store in instance capabilities JSONB
4. After INSERT into `agent_cards` (instance), INSERT into `agent_access_control` with:
   - `visibility_mode` mapped from `_ACCESS_CONTROL_MAP`
   - `allowed_roles` array (if role mode)
   - `allowed_user_ids` array (if user mode)
5. If `auth_mode = tenant_credentials`: validate all required credentials present per template schema, call `credential_manager.store_credentials()`, return `credential_test_result`
6. Publish Redis pub/sub invalidation for agent list cache key on deploy success

### New Module: credential_manager.py

File: `src/backend/app/modules/agents/credential_manager.py`

```python
async def store_credentials(
    tenant_id: str,
    agent_id: str,
    credentials: dict[str, str],
    schema: list[dict]  # template's required_credentials
) -> None:
    """Validate credential keys against schema, store via VaultClient.
    Vault path: {tenant_id}/agents/{agent_id}/{credential_key}
    Sensitive fields encrypted at rest by vault.
    NEVER log credential values."""

async def test_credentials(
    template_id: str,
    credentials: dict[str, str]
) -> CredentialTestResult:
    """Run credential validation by making a test call to the tool endpoint.
    Hard timeout: 15 seconds. Returns CredentialTestResult(passed, error_message, latency_ms)."""

async def get_credential(
    tenant_id: str,
    agent_id: str,
    credential_key: str
) -> str:
    """Retrieve credential for runtime injection into tool calls.
    Called by Tool Executor at query time, not at agent load time."""
```

### Extend GET /agents (end-user chat list)

File: `src/backend/app/modules/agents/routes.py`

- Join `agent_access_control` on `agent_id` + requesting user's `tenant_id`, `user_id`, `roles`
- Filter to only return agents the user is authorized for
- Return `icon`, `name`, `description`, `template_type` per agent (needed for chat selector identity)
- Return `template_version` and `latest_template_version` so client can show update banner

### Cache Invalidation

File: `src/backend/app/modules/agents/routes.py` (deploy handler)

After successful deploy:
```python
await redis.publish(
    f"cache:invalidate:agents:{tenant_id}",
    json.dumps({"event": "agent_deployed", "agent_id": str(new_agent_id)})
)
```

Verify all mutation paths (deploy, update, pause, archive, access control update) publish invalidation.

---

## Frontend Changes

### New Components

#### `AgentDeployWizard.tsx`

Location: `src/web/components/agents/AgentDeployWizard.tsx`

- Modal, 640px wide, `rounded-card bg-bg-surface`
- Progress bar at top: 4 segments (or 3 if no credentials step), accent fill
- Step labels below progress bar: "Template", "Knowledge", "Access", "Credentials"
- Back/Next navigation footer: ghost [Back] + primary [Next →] or [Deploy] on final step
- × close in top-right corner
- `isOpen` / `onClose` / `templateId?` props (templateId pre-selects step 1)

#### `WizardStep1Template.tsx`

Location: `src/web/components/agents/wizard/WizardStep1Template.tsx`

- If `templateId` prop provided: show selected template card (read-only) with capability summary
- If no `templateId`: show scrollable list of published templates (reuse `AgentTemplateCard` in compact mode)
- [Change template] link when pre-selected
- Show: capabilities summary, auth requirements, plan gate warning if gated

#### `WizardStep2Knowledge.tsx`

Location: `src/web/components/agents/wizard/WizardStep2Knowledge.tsx`

- Agent name input (top): `bg-bg-elevated rounded-control`, pre-filled from template name
- Variable fill section: render one input per `variable_schema` entry from template; required variables shown with asterisk; optional shown as `text-text-faint`
- KB list: fetch from `GET /admin/kb-sources`; recommended-category KBs at top with `• ` accent dot prefix; checkbox per KB; search input filters list
- KB search mode: radio group ("Search all KBs in parallel" / "Search by priority order") — only shown when multiple KBs selected

#### `WizardStep3Access.tsx`

Location: `src/web/components/agents/wizard/WizardStep3Access.tsx`

- Access mode radio: "All workspace members", "Specific roles", "Specific users"
- Role multi-select: shown when role mode selected; fetches roles from `GET /admin/roles`
- User multi-select: shown when user mode; fetches users from `GET /admin/users` with search
- Rate limit input: numeric, label "Requests per user per minute", helper text "Your plan maximum: N"
- Guardrail summary (read-only): collapsible section showing template guardrail rules

#### `WizardStep4Credentials.tsx`

Location: `src/web/components/agents/wizard/WizardStep4Credentials.tsx`

- Only rendered when `template.auth_mode === 'tenant_credentials'`
- Dynamic form generated from `template.required_credentials` schema array
- Each field: label (from schema), input type based on `sensitive: true` → password input with eye toggle; `type: 'string'` → text input
- [Test Connection] button: calls `POST /admin/agents/test-credentials` with form values; 15s timeout with elapsed-time counter; shows success (accent checkmark) or error (alert message)
- "Skip test, save credentials" link with warning tooltip: "Credentials will be stored but not verified"

#### `DeploySuccessOverlay.tsx`

Location: `src/web/components/agents/DeploySuccessOverlay.tsx`

- Full-modal overlay on successful deploy
- Checkmark animation (SVG, 600ms draw)
- Agent name in `text-page-title`
- Summary: "Bound to N knowledge bases", "N tools available", "Access: {mode}"
- Two buttons: [Go to Agents] (primary) and [Deploy Another] (ghost, resets wizard)

### Update Chat Agent Selector

File: `src/web/components/chat/ChatEmptyState.tsx` and `ChatActiveState.tsx`

- When `GET /agents` returns agents, render each in mode selector with icon (40x40), name, one-line description
- Currently only name is shown — add icon and description rendering

---

## Dependencies

- TODO-13 (DB schema) — credential schema columns in agent_cards
- TODO-14 (Agent Library) — wizard triggered from library [Deploy] button; template data used in Step 1

---

## Risk Assessment

- **HIGH**: Credential test timeout (15s) feels slow — mitigate with elapsed-time counter and skip option
- **MEDIUM**: Cache invalidation race condition — agent might not appear in chat selector immediately; add 2s retry on cache miss
- **LOW**: Variable fill inputs — template may declare variables not in system_prompt (benign but confusing); validate variable_schema against system_prompt tokens server-side

---

## Testing Requirements

- [ ] Unit test: `POST /admin/agents/deploy` creates agent + access control rows atomically
- [ ] Unit test: deploy with `auth_mode='tenant_credentials'` and missing credentials returns 422
- [ ] Unit test: `GET /agents` filters by access control — user with no matching roles sees empty list
- [ ] Unit test: credential_manager.store_credentials stores to vault, never logs values
- [ ] Unit test: credential_manager.test_credentials enforces 15s timeout
- [ ] Integration test: full deploy cycle — template → KB bind → access → deploy → appears in chat
- [ ] Integration test: access control enforced — user with wrong role cannot see agent in chat
- [ ] E2E test: TA deploys HR template; end user opens chat and sees "HR Policy Assistant" in selector

---

## Definition of Done

- [ ] All 4 wizard steps render correctly
- [ ] Step 4 conditional on auth_mode
- [ ] Deploy creates agent, access control rows, vault credentials atomically
- [ ] Deployed agent visible in end-user chat selector within 5 seconds
- [ ] Access control enforced on chat agent list
- [ ] Cache invalidation fires on deploy
- [ ] All acceptance criteria met
- [ ] No stubs — credential vault integration fully implemented

---

## Gap Patches Applied

### Gap 7: Credential scope decision — per-agent-instance vault paths

The `credential_manager.py` module must use per-agent-instance vault paths, not per-tenant-tool paths. This is a deliberate design decision with the following rationale and constraints:

**Vault key path: `{tenant_id}/agents/{agent_id}/{credential_key}`**

Implications for `credential_manager.py`:

```python
# Correct vault path construction
vault_path = f"{tenant_id}/agents/{agent_id}/{credential_key}"

# NOT this (incorrect — creates implicit cross-agent sharing):
# vault_path = f"{tenant_id}/tools/{tool_id}/{credential_key}"
```

**Rationale:**
- Different deployed instances of the same template may use different API accounts (e.g., three agents all using PitchBook but each with a different seat licence)
- Per-tenant-tool paths would force all agents sharing a tool to use the same credentials, which is wrong for enterprise multi-team deployments
- Per-agent-instance path is the only approach that supports isolated credential management without coupling

**UX consequence:**
- If a tenant deploys the same template three times, they enter credentials three separate times in the wizard (once per agent)
- This is the intended behaviour in v1
- The deploy wizard Step 4 copy must make this clear: "These credentials are stored for this agent only. Other agents using the same tools will have their own credentials."

**Phase 3 consideration:**
- If customer feedback in Phase 2 shows that re-entering the same credentials repeatedly is a pain point, add a "shared credential" concept in Phase 3: a tenant-level credential that can be referenced by multiple agents
- Design that as an opt-in at deploy time, not the default

**Testing additions:**
- [ ] Unit test: `credential_manager.store_credentials` uses `{tenant_id}/agents/{agent_id}/{key}` path format — verify vault key does NOT contain `tools/`
- [ ] Unit test: two agents deployed from the same template each get isolated vault paths — credential update on agent A does not affect agent B
- [ ] Unit test: `credential_manager.get_credential` called with agent_id A does not return credentials stored under agent_id B
