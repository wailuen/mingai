# 10 — Teams Collaboration Implementation Plan

**Feature**: Native Teams + Team Working Memory
**Analysis refs**: 15-01 through 15-05
**Architecture ref**: 39-teams-collaboration-architecture.md

## 1. Scope

### Phase 1: Core Teams (ships with Profile & Memory Plan 08)

1. **Native team management** — Tenant admin creates/manages teams
2. **Auth0 group claim sync** — Auto-create teams from JWT groups on login
3. **Team working memory** — Shared Redis bucket, Layer 4b in prompt
4. **Active team selection** — Chat UI team selector

## 2. Sprint Plan (integrated with Plan 08 sprints)

### Sprint 1 (Data Layer — Week 1-2 of Plan 08)

Add to existing Sprint 1 scope:

| Task                                  | Effort | Notes                                    |
| ------------------------------------- | ------ | ---------------------------------------- |
| Add `tenant_teams` DataFlow model     | 2h     | With `source`, `auth0_group_name` fields |
| Add `team_memberships` DataFlow model | 1h     | Composite PK, indexes                    |
| Alembic migration for both tables     | 1h     |                                          |
| Unit tests (CRUD per model)           | 2h     |                                          |

**Deliverable**: Tables in DB, empty until Sprint 3+ activates them.

### Sprint 3 (Working Memory Backend — Week 5 of Plan 08)

Add to existing Sprint 3 scope:

| Task                                                                                                                       | Effort | Notes                                                                                       |
| -------------------------------------------------------------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------- |
| Implement `TeamWorkingMemoryService`                                                                                       | 5h     | Redis key `{tenant_id}:team_memory:{team_id}`                                               |
| Topic union-merge with dedup (cap 10)                                                                                      | 2h     |                                                                                             |
| Query history with anonymous attribution (cap 5): stores "a team member" — no user ID or display name in team memory Redis | 1h     | Anonymous attribution is intentional: team memory is an AI context tool, not an audit trail |
| Auth0 group claim sync on login — allowlist-gated (only sync groups matching tenant allowlist)                             | 3h     | Read `groups` JWT claim → create/update teams for allowlisted groups only                   |
| Tenant allowlist config: store allowed group names/patterns in tenant_settings                                             | 1h     | Default: empty (no sync until configured)                                                   |
| Team membership removal on login (sync-managed records only)                                                               | 1h     |                                                                                             |
| Active team session key: `{tenant_id}:session:{user_id}:active_team`                                                       | 1h     |                                                                                             |
| Unit tests (30 tests)                                                                                                      | 5h     | Team service + auth0 sync                                                                   |

**Deliverable**: Team working memory operational, auth0 sync functional.

### Sprint 6 (Prompt Builder — Week 10-11 of Plan 08)

Add to existing Sprint 6 scope:

| Task                                                                    | Effort | Notes            |
| ----------------------------------------------------------------------- | ------ | ---------------- |
| Add Layer 4b (team working memory) to `SystemPromptBuilder`             | 2h     | 150 token budget |
| Format team memory for prompt: topics + recent queries with attribution | 1h     |                  |
| Active team injection: fetch from session, skip if no active team       | 1h     |                  |
| GDPR: `clear_profile_data()` also clears team memory buckets            | 1h     |                  |
| Integration tests: prompt with team memory layer                        | 2h     |                  |

### Sprint 7 (Frontend — Week 12-13 of Plan 08)

Add to existing Sprint 7 scope:

| Task                                                       | Effort | Notes                                        |
| ---------------------------------------------------------- | ------ | -------------------------------------------- |
| Active team selector in chat UI (dropdown in chat header)  | 4h     | Shows current team, switch → updates session |
| Team context indicator: "Using Finance Team context" badge | 1h     | Visible when team memory injected            |
| Playwright E2E test: team memory flows                     | 2h     |                                              |

### Sprint 8 (Tenant Admin — Week 14 of Plan 08)

Add to existing Sprint 8 scope:

| Task                                                                                        | Effort | Notes                                                           |
| ------------------------------------------------------------------------------------------- | ------ | --------------------------------------------------------------- |
| Teams management page: list, create, edit, delete teams                                     | 5h     | Shows source badge (manual/synced)                              |
| Team members: add/remove members, bulk add from user list                                   | 3h     |                                                                 |
| Auth0 sync settings: enable/disable, filter out noise groups                                | 2h     |                                                                 |
| Team working memory controls: TTL, enable/disable                                           | 2h     |                                                                 |
| API endpoints: GET/POST/PUT/DELETE /admin/teams                                             | 3h     |                                                                 |
| API endpoints: GET/POST/DELETE /admin/teams/{id}/members                                    | 2h     |                                                                 |
| Membership audit log: record every team membership add/remove with actor, source, timestamp | 2h     | Visible in Tenant Admin > Teams > {team} > Audit Log            |
| Auth0 sync allowlist UI: configure which Auth0 group names to sync                          | 2h     | Default empty; supports group name strings and simple wildcards |
| Integration tests                                                                           | 3h     |                                                                 |

**Deliverable**: Full team management UI for tenant admins.

## 3. Definition of Done

### Backend

- [ ] `tenant_teams`, `team_memberships` tables migrated
- [ ] `TeamWorkingMemoryService` operational (read/write/clear)
- [ ] Auth0 group claim sync on login (auto-create, membership sync, removal)
- [ ] Layer 4b in SystemPromptBuilder (150 token budget)
- [ ] Active team in session (Redis)
- [ ] GDPR: team memory cleared on user erasure
- [ ] All API endpoints operational
- [ ] Unit tests passing (30+ for team services)
- [ ] Integration tests passing (10+)

### Frontend

- [ ] Active team selector in chat header
- [ ] Team context indicator badge
- [ ] Teams management page in Tenant Admin
- [ ] Auth0 sync controls in Tenant Admin
- [ ] E2E tests: 3 critical team flows

### Security

- [ ] Team memory access requires user to be a member of the team
- [ ] Team IDs are tenant-scoped (no cross-tenant access)
- [ ] Auth0 group sync: only creates `auth0_sync` records, never overwrites `manual` records
- [ ] Active team session key includes tenant_id prefix
- [ ] Team memory query history uses anonymous attribution ("a team member") — no personal identifiers in Redis
- [ ] Auth0 group sync is allowlist-gated (empty allowlist = no auto-sync by default)
- [ ] Membership audit log operational and visible in Tenant Admin

## 4. Risks

| Risk                                                          | Severity | Mitigation                                                                       |
| ------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------- |
| Auth0 group sync creates noise teams (vpn-users, all-company) | High     | Tenant admin can archive/delete auto-created teams; filter list in sync settings |
| User erasure disrupts team working memory                     | Medium   | Accept tradeoff; document in privacy policy; notify team admin                   |
| Team memory topic quality degrades with off-topic queries     | Medium   | Team admin can manually clear team memory bucket                                 |
| Active team UX confusion                                      | Medium   | Clear indicator in chat; onboarding tooltip on first team assignment             |
