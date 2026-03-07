# 39. Native Teams & Team Working Memory Architecture

**Status**: Canonical — new capability, no prior doc superseded
**Date**: 2026-03-06
**Related**: Doc 38 (Auth0 SSO, group claim sync); Doc 23 (working memory architecture)

---

## 1. Problem Statement

### Individual Memory Silos

Current working memory is scoped to individual users. Each user independently builds conversational context with the AI. When multiple users work on the same project, investigation, or domain, they each re-brief the AI from scratch — or rely on inconsistent individual context.

Concrete example: three analysts in a Finance team are investigating Q4 variance. Each has different working memory. The AI gives subtly different answers to the same question depending on who asks, based on the accumulated individual context. There is no shared AI state for their shared investigation.

### Collaboration Score

The current platform collaboration score is 3/10. Platform-managed teams with shared working memory is the highest-leverage intervention for closing this gap.

### Why Not Just Use External Group Management

Options considered:

1. Azure AD groups → direct integration: requires each tenant to have Azure AD and to grant mingai directory read permissions. Excludes tenants using other IdPs or username/password.
2. Okta groups → direct integration: same issue, different provider.
3. Auth0 group claims → team sync: works for tenants with Auth0 Actions configured, but does not cover all tenants.
4. mingai-native teams: works for ALL tenants regardless of SSO configuration. Auth0 group sync is additive, not foundational.

Decision: mingai manages its own team/group concept. Auth0 group sync is an optional convenience layer on top.

---

## 2. Native Team Model

### Core Properties

- mingai manages teams independently of external IdP group structures
- Works for all tenants: Azure AD + SAML + Okta + Google Workspace + username/password
- Tenant admin creates and manages teams via Tenant Admin UI
- Team ID is a mingai-native UUID — not an Azure AD object ID, not an Okta group ID
- Auth0 group sync (doc 38 section 6) is an optional auto-population mechanism; it does not replace native team management

### Team Lifecycle

1. Tenant admin creates team (manual) OR Auth0 group sync creates team automatically on first user login containing that group
2. Members are added manually by tenant admin OR synced from Auth0 group claim on login
3. Team accumulates shared working memory as members use the platform
4. Tenant admin can archive a team (preserves history, stops new memory accumulation)
5. Tenant admin can delete a team (hard delete including memory bucket)

---

## 3. Data Model

```sql
CREATE TABLE tenant_teams (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name            VARCHAR(100) NOT NULL,
    description     TEXT,
    source          VARCHAR(20) NOT NULL DEFAULT 'manual',
    -- 'manual' | 'auth0_sync'
    -- auth0_sync: team was auto-created from an Auth0 group claim
    -- manual: team was created by a tenant admin directly
    auth0_group_name TEXT,
    -- The original group name from the Auth0 groups claim (used for sync matching)
    -- NULL for manually created teams
    is_archived     BOOLEAN NOT NULL DEFAULT FALSE,
    created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, name)
);

CREATE TABLE team_memberships (
    team_id     UUID NOT NULL REFERENCES tenant_teams(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    added_by    UUID REFERENCES users(id) ON DELETE SET NULL,
    source      VARCHAR(20) NOT NULL DEFAULT 'manual',
    -- 'manual' | 'auth0_sync'
    -- auth0_sync: membership was created/maintained by group claim sync
    -- manual: membership was set by a tenant admin
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (team_id, user_id)
);

-- Query: "what teams is this user in?" (used at query time to load team memory)
CREATE INDEX idx_team_memberships_user ON team_memberships(user_id, team_id);

-- Query: "list all teams for this tenant" (used in admin UI)
CREATE INDEX idx_tenant_teams_tenant ON tenant_teams(tenant_id, is_archived);

-- Query: "find team by auth0_group_name for sync" (used at login)
CREATE INDEX idx_tenant_teams_auth0_group ON tenant_teams(tenant_id, auth0_group_name)
    WHERE auth0_group_name IS NOT NULL;
```

### Source Field Semantics

`source = 'manual'` records are never touched by Auth0 sync. A tenant admin who manually adds a member to a team will not see that membership removed if the user's JWT no longer contains the corresponding group. This prevents sync operations from undoing intentional administrative decisions.

`source = 'auth0_sync'` records are managed by sync: created on login if the group claim is present, removed on login if the group claim is absent.

A tenant admin can "promote" an `auth0_sync` team to a `manual` team (setting `source = 'manual'`). After promotion, Auth0 sync will no longer auto-add or auto-remove members from this team. This is useful when a team has diverged from its IdP group.

---

## 4. Auth0 Group Claim Sync

Sync runs as part of the login handler, after JWT validation and session creation.

### Login Handler Sequence

```python
async def handle_login(jwt_claims: dict, tenant_id: str, user_id: str):
    # 1. Validate JWT (already done by auth middleware)
    # 2. Create/update session
    # 3. Warm org context cache (background task — see doc 38)
    # 4. Sync teams (if groups claim present)

    groups = jwt_claims.get("groups")
    if groups and await get_tenant_setting(tenant_id, "auth0_group_sync_enabled"):
        await team_sync_service.sync_user_teams(
            user_id=user_id,
            tenant_id=tenant_id,
            jwt_groups=groups,
        )
```

### TeamSyncService.sync_user_teams

```python
async def sync_user_teams(
    self,
    user_id: str,
    tenant_id: str,
    jwt_groups: List[str],
) -> None:
    """
    Reconcile user's team memberships against current JWT group claims.
    Only affects source='auth0_sync' records — manual records are never touched.
    Only syncs groups matching the tenant's auth0_group_allowlist.
    If the allowlist is empty (default), no sync occurs.
    """
    # Load tenant allowlist — default is empty (no sync)
    allowlist = await self.get_tenant_allowlist(tenant_id)
    if not allowlist:
        return  # No sync until tenant admin configures allowlist

    # Filter JWT groups against allowlist
    allowed_groups = [g for g in jwt_groups if self._matches_allowlist(g, allowlist)]

    # Ensure teams exist for all allowlisted groups in JWT
    for group_name in allowed_groups:
        team = await self.get_or_create_team_for_group(tenant_id, group_name)
        await self.ensure_membership(team.id, user_id, source="auth0_sync")

    # Remove auth0_sync memberships for groups no longer in JWT (or no longer allowlisted)
    current_sync_memberships = await self.get_user_sync_memberships(user_id, tenant_id)
    for membership in current_sync_memberships:
        team = await self.get_team(membership.team_id)
        if team.auth0_group_name not in allowed_groups:
            await self.remove_sync_membership(membership.team_id, user_id)

def _matches_allowlist(self, group_name: str, allowlist: List[str]) -> bool:
    """
    Exact string match or simple wildcard (* suffix).
    e.g., 'Q4-*' matches 'Q4-Budget', 'Q4-Planning'.
    """
    for pattern in allowlist:
        if pattern.endswith("*"):
            if group_name.startswith(pattern[:-1]):
                return True
        elif group_name == pattern:
            return True
    return False

async def get_or_create_team_for_group(
    self,
    tenant_id: str,
    group_name: str,
) -> TenantTeam:
    existing = await self.db.execute(
        select(TenantTeam).where(
            TenantTeam.tenant_id == tenant_id,
            TenantTeam.auth0_group_name == group_name,
        )
    )
    team = existing.scalar_one_or_none()
    if team:
        return team

    # Auto-create team for allowlisted group claim
    team = TenantTeam(
        tenant_id=tenant_id,
        name=group_name,  # Use group name as team name; admin can rename
        source="auth0_sync",
        auth0_group_name=group_name,
    )
    self.db.add(team)
    await self.db.flush()
    return team
```

### Membership Removal Scope

Removal via sync ONLY removes `source = 'auth0_sync'` memberships. If a user was manually added to a team (`source = 'manual'`), that membership is preserved even if the corresponding group is absent from the JWT. This is intentional: manual administrative decisions take precedence over directory sync.

### Team Name on Auto-Creation

Auto-created teams use the Auth0 group name as the team name. Tenant admins can rename teams without breaking sync (the sync key is `auth0_group_name`, not the display name).

---

## 4a. Auth0 Sync Allowlist

Default behavior: NO auto-sync. Tenant admin must configure the allowlist before any user logs in.

### Configuration

```
tenant_settings.auth0_group_allowlist TEXT[]  -- e.g., ['Finance', 'Engineering', 'Q4-*']
Default: empty array []
```

### On Login Sync

```
For each group in JWT groups claim:
  If group matches any pattern in allowlist → sync (create team if needed, update membership)
  If group NOT in allowlist → skip silently
```

### Pattern Matching

Exact string match or simple wildcard (_ suffix). e.g., `Q4-_`matches`Q4-Budget`, `Q4-Planning`.

### Tenant Admin UI

Location: Settings > Teams > Auth0 Sync > Group Allowlist

- Input: comma-separated group names or patterns
- Preview: shows which groups from the most recent login would have been synced given the current allowlist
- Save → immediately applies to next login

### Stored In

`tenant_settings` table, column `auth0_group_allowlist TEXT[]`. Default: empty array. Schema migration required alongside Sprint 3 Auth0 sync implementation.

---

## 5. Team Working Memory

### Redis Structure

```
Key:   {tenant_id}:team_memory:{team_id}
Type:  Hash

Fields:
  topics          JSON array of up to 10 recent topic strings (newest prepended)
  recent_queries  JSON array of up to 5 recent query objects with anonymous attribution
  updated_at      ISO 8601 timestamp of last write

TTL:  604,800 seconds (7 days, matching individual working memory TTL)
      Configurable per tenant: 1-30 days
```

### recent_queries Entry Format

```json
{
  "query": "What is the Q4 variance for APAC region?",
  "contributor": "a team member",
  "timestamp": "2026-03-06T14:22:00Z",
  "agent_id": "uuid-of-agent"
}
```

`contributor` is always the literal string `"a team member"` — no user ID, no display name is stored in team memory. Anonymous attribution is intentional: team memory is an AI context tool, not an audit trail. Accountability is handled by the membership audit log (PostgreSQL), which records who contributed what but is separate from the Redis injection layer.

### Write Path

Any team member's query updates the team's working memory alongside their individual working memory bucket.

```python
class TeamWorkingMemoryService:
    async def update_on_query(
        self,
        tenant_id: str,
        team_id: str,
        user_id: str,
        query: str,
        extracted_topics: List[str],
    ) -> None:
        key = f"{tenant_id}:team_memory:{team_id}"

        async with self.redis.pipeline() as pipe:
            # Load current state
            current = await self.redis.hgetall(key)

            current_topics = json.loads(current.get("topics", "[]"))
            current_queries = json.loads(current.get("recent_queries", "[]"))

            # Merge topics (union, deduplicate by text, cap at 10, newest first)
            all_topics = extracted_topics + [
                t for t in current_topics if t not in extracted_topics
            ]
            merged_topics = all_topics[:10]

            # Prepend new query, cap at 5
            # contributor is always "a team member" — no user ID or display name in team memory
            new_entry = {
                "query": query[:500],  # Truncate long queries
                "contributor": "a team member",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "agent_id": str(agent_id),
            }
            merged_queries = [new_entry] + current_queries[:4]

            # Write back — updated_by omitted (anonymous attribution)
            ttl = await self.get_tenant_ttl(tenant_id)
            pipe.hset(key, mapping={
                "topics": json.dumps(merged_topics),
                "recent_queries": json.dumps(merged_queries),
                "updated_at": datetime.utcnow().isoformat() + "Z",
            })
            pipe.expire(key, ttl)
            await pipe.execute()
```

### Read Path

At query time, fetch team working memory for the user's active team and merge with individual working memory for Layer 4 of the system prompt:

```python
async def get_combined_working_memory(
    self,
    tenant_id: str,
    user_id: str,
    active_team_id: Optional[str],
) -> WorkingMemoryContext:
    # Individual memory (always loaded)
    individual = await self.individual_wm_service.get(tenant_id, user_id)

    # Team memory (only if user has an active team)
    team = None
    if active_team_id:
        team = await self.get_team_memory(tenant_id, active_team_id)

    return WorkingMemoryContext(individual=individual, team=team)
```

---

## 6. Active Team Selection

### Constraint

Users can belong to multiple teams. Only ONE team's working memory is injected per session (token budget constraint: Layer 4b is capped at 150 tokens).

### Active Team State

Stored in the user's session (Redis):

```
Key:  {tenant_id}:session:{session_id}
Field: active_team_id
Value: UUID of the active team, or null
```

Defaults to the last-used team. On first login (no session history), defaults to null (no team context).

### Switching Active Team

User selects a different team via the chat UI team selector. This:

1. Updates `active_team_id` in the session hash
2. Does NOT clear individual working memory
3. Does NOT clear either team's working memory bucket
4. Takes effect on the next message sent in that session

### Chat UI: Team Selector

Location: chat header, adjacent to the agent name.

Display: "Team: Finance" with a dropdown arrow. Clicking shows the user's teams (up to 10 shown; all teams in a scrollable list if more). Selecting a team immediately updates the session.

If the user has no teams: the selector is hidden entirely (no empty state shown in header).

If team memory is disabled by tenant admin: the selector is hidden.

---

## 7. Prompt Stack Integration

Team working memory is inserted as Layer 4b between individual working memory and RAG context:

```
Layer 0:  Agent base prompt
          ─ defines the agent's persona, tone, and task scope

Layer 1:  Platform base
          ─ platform-wide safety rules and capabilities

Layer 2:  Org Context                              [~500 tokens]
          ─ job_title, department, country, company from Auth0

Layer 3:  Profile Context                          [~200 tokens]
          ─ user preferences, interaction history summary

Layer 4a: Individual Working Memory                [~100 tokens]
          ─ this user's recent topics and context

Layer 4b: Team Working Memory (NEW)                [~150 tokens]
          ─ shared context from this user's active team

Layer 5:  Domain Context (RAG)                     [no fixed limit]
          ─ retrieved document chunks

[Glossary layer removed — pre-translated in query per doc 37]
```

### Layer 4b Prompt Template

```
Current team context ({{team_name}}):
Recent shared topics: {{topics | join(", ")}}
Recent team queries: {{recent_queries | map(attribute="query") | join(" | ") | truncate(300)}}
```

Token budget for Layer 4b: 150 tokens. The template renders at most 150 tokens; truncation is applied if the rendered content exceeds budget.

### Total Overhead at 2K Budget

```
Layers 0-1:  200 tokens
Layer 2:     500 tokens
Layer 3:     200 tokens
Layer 4a:    100 tokens
Layer 4b:    150 tokens
────────────────────────
System overhead: 1,150 tokens
RAG budget:        850 tokens
```

Note: doc 37 section 7 calculated 950 tokens overhead (without Layer 4b). Adding Layer 4b raises overhead to 1,150, leaving 850 tokens for RAG at 2K budget. At 4K budget (recommended for complex queries), RAG gets 2,850 tokens.

---

## 8. GDPR Considerations

### Individual Erasure (Article 17)

When a user requests erasure:

1. Delete user record and all user-scoped data (standard erasure flow)
2. Remove user from all `team_memberships` records
3. For each team where the user was a member: **delete the entire team working memory bucket** (`DEL {tenant_id}:team_memory:{team_id}`)

Step 3 is conservative. The team memory bucket may contain contributions from multiple users, not just the requesting user. Rather than attempting to surgically remove only the requesting user's contributions (which is difficult to implement correctly given the merged topic structure), the entire bucket is cleared.

This tradeoff is documented and disclosed to tenant admins:

> "When a team member requests data erasure, the shared team memory for all teams they belong to is cleared. This is because team memory is a merged structure that cannot always be cleanly attributed to a single contributor. Other team members will notice the team context has reset — this is expected behaviour."

### Personal Data in Team Memory

`recent_queries` entries contain:

- `query`: may contain PII if the user typed PII into a query
- `contributor`: always `"a team member"` — not personal data (anonymous attribution)
- `timestamp`: timestamp of the query
- `agent_id`: not PII

The team memory bucket is NOT a backup of user data — it is a derived summary structure. Because `contributor` is always anonymous, the only potential personal data is `query` text (if the user included PII in their query). The bucket is still treated as personal data for GDPR purposes and cleared on erasure due to the `query` field.

### Sole Contributor Case

If a user is the sole contributor to a team's working memory (the only team member who has sent queries), erasure clears the bucket entirely and effectively ends that team's memory history. If other members then query, the bucket begins accumulating fresh context. No data is lost beyond the erased user's contributions.

### Retention Policy

Team working memory TTL is 7 days by default (configurable 1-30 days). Tenant admins can set shorter TTLs for sensitive industries (legal, healthcare) where historical query retention is a liability.

---

## 9. Tenant Admin Controls

New settings in Tenant Admin > Settings > Teams:

| Setting              | Default                                    | Options                        | Notes                                            |
| -------------------- | ------------------------------------------ | ------------------------------ | ------------------------------------------------ |
| Team working memory  | Enabled                                    | Enabled / Disabled             | Disabling hides team selector from all users     |
| Team memory TTL      | 7 days                                     | 1-30 days                      | Applies to all teams in this tenant              |
| Auth0 group sync     | Auto-detect                                | Enabled / Disabled             | Only shown if groups claim detected on any login |
| Max teams per tenant | Unlimited (Enterprise) / 10 (Professional) | Configurable by platform admin | Enforced at team creation time                   |

### Disabling Team Working Memory

When disabled:

- Layer 4b is omitted from system prompt builder (no error, no fallback)
- Team selector hidden in chat UI
- Existing team memory buckets are NOT deleted (reversible)
- Teams and memberships remain intact for re-enabling

### Manual Team Management UI

Location: Tenant Admin > Users & Teams > Teams

Features:

- List all teams (name, member count, source, last memory update)
- Create team (name, optional description)
- View/edit team members (add, remove, toggle source for auth0_sync members)
- Clear team memory (manual reset of working memory bucket)
- Archive team (soft delete — stops memory accumulation, hides from user selectors)
- Delete team (hard delete including memory bucket, requires confirmation)

---

## 10. Phase Placement in Implementation Plan

Team infrastructure is introduced early (Sprint 1) as empty tables, then built out progressively across sprints:

| Sprint                  | Deliverable                                                                                                                         |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Sprint 1                | Add `tenant_teams` + `team_memberships` tables to Alembic migration. Tables are empty — no API, no UI, no sync.                     |
| Sprint 3                | Add `TeamWorkingMemoryService` with read/write/clear operations. Alongside `WorkingMemoryService` (individual). No UI yet.          |
| Sprint 4                | Add `TeamSyncService` with Auth0 group claim sync. Runs silently at login — teams auto-created, no UI exposure yet.                 |
| Sprint 6                | Integrate Layer 4b into `SystemPromptBuilder`. Feature-flagged off by default at tenant level.                                      |
| Sprint 7 (Frontend)     | Add active team selector in chat header. Feature-flagged: only shown if team working memory is enabled for tenant.                  |
| Sprint 8 (Tenant Admin) | Add Teams management UI in Tenant Admin > Users & Teams > Teams. Enable team working memory via settings.                           |
| Sprint 9                | Expose team memory analytics in Tenant Admin > Analytics: team activity heatmap, memory reset frequency, contribution distribution. |

### Feature Flag Strategy

Team working memory is introduced with a tenant-level feature flag (`team_memory_enabled`, default `FALSE`). Platform admin enables it per tenant during rollout. After Sprint 9 stability validation, the default flips to `TRUE` for new tenants.

This allows early adopters to pilot the feature before it becomes the default, and gives the team time to validate the GDPR erasure flow with real data.
