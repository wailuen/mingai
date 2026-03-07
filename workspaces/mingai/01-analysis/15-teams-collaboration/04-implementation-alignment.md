# 15-04 — Implementation Alignment: Teams Collaboration

**Feature**: Native Teams + Team Working Memory
**Focus**: Data model, service specification, prompt integration, sprint placement, token budget
**Research date**: 2026-03-07
**Dependency**: aihub2 has no teams feature — this is entirely net-new implementation

---

## 1. Data Model

### 1.1 Teams Tables (PostgreSQL DDL)

```sql
-- Platform-managed team definitions
CREATE TABLE tenant_teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    source VARCHAR(20) NOT NULL DEFAULT 'manual',
        -- 'manual': created by tenant admin
        -- 'auth0_sync': auto-created from Auth0 groups claim on login
    source_group_id VARCHAR(255),
        -- stores the IdP group identifier when source = 'auth0_sync'
        -- NULL for manual teams
    is_active BOOLEAN NOT NULL DEFAULT true,
    team_memory_ttl_days INTEGER NOT NULL DEFAULT 7,
        -- overridable per team; range 1-30 days
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, name),
    UNIQUE (tenant_id, source_group_id)
        -- prevents duplicate teams from same IdP group
);

CREATE INDEX idx_tenant_teams_tenant ON tenant_teams(tenant_id, is_active);
CREATE INDEX idx_tenant_teams_source ON tenant_teams(tenant_id, source, source_group_id);

-- Team membership assignments
CREATE TABLE team_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES tenant_teams(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        -- denormalized for efficient scoped queries without join to tenant_teams
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL DEFAULT 'member',
        -- 'member': standard team member
        -- 'owner': can manage team membership (Phase 2)
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    added_by UUID REFERENCES users(id) ON DELETE SET NULL,
        -- NULL when source is auth0_sync
    source VARCHAR(20) NOT NULL DEFAULT 'manual',
        -- 'manual': added by tenant admin
        -- 'auth0_sync': added via Auth0 groups claim sync
    UNIQUE (team_id, user_id)
);

CREATE INDEX idx_team_memberships_user ON team_memberships(tenant_id, user_id);
CREATE INDEX idx_team_memberships_team ON team_memberships(team_id);
```

### 1.2 Team Memory Audit Table (GDPR Support)

```sql
-- Tracks which users have contributed to which team memory buckets
-- Required for contribution-specific erasure (GDPR right to erasure)
CREATE TABLE team_memory_contributions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES tenant_teams(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    contributed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        -- record created when user's query writes to team memory bucket
        -- does NOT store query content — only membership signal for GDPR
);

CREATE INDEX idx_team_memory_contributions_user ON team_memory_contributions(tenant_id, user_id);
CREATE INDEX idx_team_memory_contributions_team ON team_memory_contributions(team_id);
```

---

## 2. TeamWorkingMemoryService Specification

### 2.1 Redis Key

```
Key:   {tenant_id}:team_memory:{team_id}
Type:  Redis Hash
TTL:   {team_memory_ttl_days} days (default 7, configurable per team in tenant_teams table)
```

The hash stores:

- `topics`: JSON list of topic strings (max 10, newest first, deduped)
- `recent_queries`: JSON list of `{ query: str, user_display_name: str, timestamp: ISO8601 }` (max 5, newest first)
- `last_active_user_id`: UUID string (for attribution display)
- `last_updated`: ISO8601 timestamp

### 2.2 Service Interface

```python
class TeamWorkingMemoryService:

    async def get_team_memory(
        self,
        tenant_id: str,
        team_id: str
    ) -> Optional[TeamMemoryContext]:
        """
        Fetch current team working memory from Redis.
        Returns None if no team memory exists (key missing or empty).
        Caller must check for None before injecting into prompt.
        """

    async def update_team_memory(
        self,
        tenant_id: str,
        team_id: str,
        user_id: str,
        user_display_name: str,
        new_topics: List[str],
        new_query: str
    ) -> None:
        """
        Atomic update of team memory.
        - Merges new_topics into existing topic list (union, dedup, cap at 10, newest first)
        - Prepends new query to recent_queries list (cap at 5)
        - Resets TTL to team's configured ttl_days
        - Records contribution in team_memory_contributions table (async, non-blocking)
        """

    async def clear_team_memory(
        self,
        tenant_id: str,
        team_id: str
    ) -> None:
        """
        Fully delete the Redis key for this team's memory.
        Called on: (a) tenant admin request, (b) team deletion.
        Does NOT automatically clear on user GDPR erasure — see clear_user_contributions().
        """

    async def clear_user_contributions(
        self,
        tenant_id: str,
        user_id: str
    ) -> None:
        """
        GDPR user erasure handler.
        1. Query team_memory_contributions for all team_ids where user contributed.
        2. For each team_id, remove the user's query attribution from recent_queries
           (filter out entries where user_display_name matches user's display name).
        3. Topics contributed by the user CANNOT be individually removed — they are
           aggregated into the bucket. Topics are preserved (acceptable: they are
           non-PII keywords). Only the attributed query records are removed.
        4. Delete all team_memory_contributions records for this user.
        Called from the GDPR erasure pipeline in clear_profile_data().
        """
```

### 2.3 Topic Merge Algorithm

```python
def _merge_topics(
    existing: List[str],
    new_topics: List[str],
    cap: int = 10
) -> List[str]:
    """
    Merge new topics into existing topic list.
    Rules:
    - Lowercase and strip both lists before comparison
    - New topics prepended (newest-first ordering)
    - Dedup: if a new topic already exists in the list, remove the old entry
      and prepend the new one (promotes recently-re-investigated topics to top)
    - Cap at 10 total topics (drop oldest)
    """
    existing_lower = {t.lower(): t for t in existing}
    result = []
    for topic in new_topics:
        key = topic.lower().strip()
        if key:
            existing_lower.pop(key, None)  # remove duplicate if present
            result.append(topic.strip())
    result.extend(existing_lower.values())
    return result[:cap]
```

### 2.4 Redis Write Strategy (Concurrent Safety)

Team memory writes are concurrent — multiple team members may query simultaneously. Redis atomic operations are used:

```python
async def update_team_memory(self, ...):
    key = f"{tenant_id}:team_memory:{team_id}"
    async with self.redis.pipeline() as pipe:
        # WATCH for optimistic locking on concurrent updates
        await pipe.watch(key)
        pipe.multi()
        # Read current state
        current = await self.redis.hgetall(key)
        existing_topics = json.loads(current.get("topics", "[]"))
        existing_queries = json.loads(current.get("recent_queries", "[]"))
        # Merge
        merged_topics = self._merge_topics(existing_topics, new_topics)
        updated_queries = ([{
            "query": new_query[:100],  # truncate at 100 chars
            "user_display_name": user_display_name,
            "timestamp": datetime.utcnow().isoformat()
        }] + existing_queries)[:5]
        # Write atomically
        pipe.hset(key, mapping={
            "topics": json.dumps(merged_topics),
            "recent_queries": json.dumps(updated_queries),
            "last_active_user_id": user_id,
            "last_updated": datetime.utcnow().isoformat()
        })
        pipe.expire(key, team_ttl_seconds)
        await pipe.execute()
```

---

## 3. Auth0 Group Claim Sync

### 3.1 Login Handler Changes

The Auth0 post-login callback (`/auth/callback`) processes the JWT. When a `groups` claim is present, the sync engine runs:

```python
async def sync_auth0_groups(
    tenant_id: str,
    user_id: str,
    groups_claim: List[str],
    groups_claim_field: str = "groups"  # configurable per tenant
) -> None:
    """
    1. Filter groups_claim through tenant's noise filter
       (exclude groups matching blocklist patterns; include only those matching allowlist patterns)
    2. For each qualifying group name:
       a. UPSERT tenant_teams with source='auth0_sync', source_group_id={group_name}
       b. UPSERT team_memberships for user_id in this team
    3. For teams the user previously belonged to (source='auth0_sync') where the
       group is now absent from the claim: remove the team membership
       (team itself is NOT deleted — only membership removed)
    4. Manual teams (source='manual') are NEVER modified by Auth0 sync
    """
```

### 3.2 Noise Filter Configuration

Stored in `tenant_settings` under key `auth0_team_sync`:

```json
{
  "groups_claim_field": "groups",
  "enabled": true,
  "mode": "blocklist",
  "blocklist_patterns": [
    "all-*",
    "*-vpn",
    "*-wifi",
    "everyone",
    "domain-users"
  ],
  "allowlist_patterns": []
}
```

When `mode = "allowlist"`, only groups matching `allowlist_patterns` create teams. When `mode = "blocklist"`, all groups create teams except those matching `blocklist_patterns`. Default is `blocklist` with common noise patterns pre-populated.

### 3.3 Deduplication Strategy

- A manually-created team with name "Finance Team" and an Auth0 group "Finance Team" do NOT merge automatically — they remain as two separate entries (`source: manual` and `source: auth0_sync`).
- Tenant admin can manually link the two if desired (Phase 2 feature).
- This avoids unintended merging of platform-managed teams with directory-managed teams.

---

## 4. SystemPromptBuilder Layer 4b

### 4.1 Layer Position in Stack

```
Layer 0:  Agent base prompt
Layer 1:  Platform base (safety, standards)
Layer 2:  Org Context (100 tokens)
Layer 3:  Profile Context (200 tokens)
Layer 4:  Individual Working Memory (100 tokens)
Layer 4b: Team Working Memory (150 tokens)   ← NEW
Layer 5:  RAG Context (up to remaining budget)
```

Note: Glossary is no longer injected into the system prompt. It is handled as inline query expansion (pre-translation) at pipeline step 3b via `GlossaryExpander` — zero tokens consumed in the system prompt.

Layer 4b is injected between individual working memory and RAG context. This ordering ensures:

- Individual context (who you are, what you've done) is closer to the system prompt base
- Team context (what your team has been working on) is between individual and knowledge base
- RAG content is the outermost layer — most query-specific, least prompt-global

### 4.2 Team Memory Prompt Template

```python
TEAM_MEMORY_TEMPLATE = """
## Team Context: {team_name}

Your team has been investigating the following topics:
{topic_list}

Recent team activity:
{recent_queries}
"""

def format_team_memory_for_prompt(
    team_name: str,
    memory: TeamMemoryContext,
    budget_tokens: int = 150
) -> str:
    """
    Format team memory for system prompt injection.
    Truncates to budget_tokens if needed (topics first, then queries).
    Returns empty string if memory has no meaningful content (no topics, no queries).
    """
    topics_str = "\n".join(f"- {t}" for t in memory.topics[:5]) if memory.topics else "(none yet)"
    queries_str = "\n".join(
        f"- {q.user_display_name}: \"{q.query[:60]}...\"" if len(q.query) > 60 else
        f"- {q.user_display_name}: \"{q.query}\""
        for q in memory.recent_queries[:3]
    ) if memory.recent_queries else "(none yet)"

    prompt = TEAM_MEMORY_TEMPLATE.format(
        team_name=team_name,
        topic_list=topics_str,
        recent_queries=queries_str
    )
    return truncate_to_token_budget(prompt, budget_tokens)
```

### 4.3 Example Prompt Injection (Layer 4b)

For a Finance team mid-project investigating Acme Inc:

```
## Team Context: M&A Due Diligence — Acme Inc

Your team has been investigating the following topics:
- GDPR exposure
- data processing agreements
- NDA structure
- German regulatory requirements
- material disclosure thresholds

Recent team activity:
- Sarah K.: "What are Acme's obligations under Article 28?"
- James L.: "Standard NDA provisions for IP assignment"
- Sarah K.: "DPA requirements for data processors in Germany"
```

This injection is ~120 tokens — well within the 150-token Layer 4b budget.

---

## 5. Active Team in Session

### 5.1 Redis Session Key

```
Key:   {tenant_id}:session:{session_id}:active_team_id
Type:  Redis String (UUID value)
TTL:   session duration (24 hours)
```

### 5.2 Default Active Team Selection Logic

```python
async def get_default_active_team(
    tenant_id: str,
    user_id: str
) -> Optional[str]:
    """
    Selection priority:
    1. User's explicitly selected active team for this session (session key)
    2. If user belongs to exactly one team: auto-activate it
    3. If user belongs to multiple teams: return None (user must select in UI)
    4. If user belongs to no teams: return None (no team memory injected)
    """
    session_key = f"{tenant_id}:session:{session_id}:active_team_id"
    cached = await redis.get(session_key)
    if cached:
        return cached.decode()

    memberships = await get_user_team_memberships(tenant_id, user_id)
    if len(memberships) == 1:
        return memberships[0].team_id
    return None
```

### 5.3 Active Team Selector in Chat UI

When the user has multiple team memberships, a team selector is shown in the chat header bar:

- Compact: a `[Team: M&A Acme]` chip with a dropdown arrow
- Dropdown: lists all teams the user belongs to + "No team" option
- Selection updates the session's `active_team_id` Redis key immediately
- Empty state (no teams): chip is hidden entirely

---

## 6. Sprint Placement

All work is net-new (no aihub2 equivalent). Sprint numbers reference the Profile & Memory plan cadence for consistency.

| Sprint       | Work                                                                                                                    | Dependencies                   |
| ------------ | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| **Sprint 1** | `tenant_teams` + `team_memberships` + `team_memory_contributions` tables; schema migration                              | Plan 06 teams management added |
| **Sprint 2** | Teams management REST API (`/teams`, `/teams/{id}/members`); tenant admin permission checks                             | Sprint 1 tables                |
| **Sprint 3** | `TeamWorkingMemoryService` (Redis CRUD, topic merge, concurrent writes)                                                 | Sprint 1 tables, Redis infra   |
| **Sprint 4** | Auth0 group claim sync engine; noise filter config in tenant_settings                                                   | Sprint 1–2                     |
| **Sprint 5** | Layer 4b in `SystemPromptBuilder`; active team session key; query pipeline update (write to team memory after response) | Sprint 3                       |
| **Sprint 6** | Active team selector in chat UI (frontend); team memory in query context                                                | Sprint 5                       |
| **Sprint 7** | Teams management UI in Tenant Admin (create, assign members, sync settings)                                             | Sprint 2                       |
| **Sprint 8** | GDPR: `clear_user_contributions()`; hook into erasure pipeline in `clear_profile_data()`                                | Sprint 3                       |

**Prerequisite gate before Sprint 1**: Plan 06 must be updated to include teams management scope.

---

## 7. Carry-Forward vs. Net-New

This feature is 100% net-new. aihub2 has no teams concept. No code can be ported.

| Component                          | Source  | Notes                                                |
| ---------------------------------- | ------- | ---------------------------------------------------- |
| `tenant_teams` table               | Net-new | No equivalent in aihub2                              |
| `team_memberships` table           | Net-new | No equivalent in aihub2                              |
| `TeamWorkingMemoryService`         | Net-new | Modeled after `WorkingMemoryService` but team-scoped |
| Auth0 group claim sync             | Net-new | Auth0 is new in mingai vs. Azure AD in aihub2        |
| Layer 4b in `SystemPromptBuilder`  | Net-new | Additional layer beyond aihub2's 6-layer stack       |
| Active team session key            | Net-new | No per-session team selection in aihub2              |
| GDPR contribution erasure          | Net-new | `clear_profile_data()` extension                     |
| Teams management UI (Tenant Admin) | Net-new | Not in Plan 06 current scope                         |

`TeamWorkingMemoryService` can reuse the `_extract_topics()` logic from `WorkingMemoryService` — the extraction algorithm is identical; only the Redis key and merge strategy differ.

---

## 8. Updated Token Budget Table

The following table shows the complete system prompt token budget at 2K user budget, incorporating the glossary removal from primary overhead and the addition of team memory Layer 4b.

| Layer                                   | Description                                    | Old Budget                                | New Budget (Canonical)                     | Change   |
| --------------------------------------- | ---------------------------------------------- | ----------------------------------------- | ------------------------------------------ | -------- |
| Layer 2                                 | Org Context                                    | 500 tokens (budgeted) ~70 tokens (actual) | 100 tokens (right-sized; 30-token buffer)  | **-400** |
| Layer 3                                 | Profile Context (profile + memory notes top 5) | 200 tokens                                | 200 tokens                                 | —        |
| Layer 4a                                | Individual Working Memory                      | 100 tokens                                | 100 tokens                                 | —        |
| Layer 4b                                | Team Working Memory (new)                      | —                                         | 150 tokens                                 | **+150** |
| Layer 6                                 | Glossary Context                               | 500 tokens                                | 0 tokens (removed — pre-translated inline) | **-500** |
| **Total Overhead** (memory layers only) |                                                | **~1,300 tokens**                         | **550 tokens**                             | **-750** |
| **RAG Context Available at 2K budget**  |                                                | **~700 tokens**                           | **1,450 tokens**                           | **+750** |
| **RAG Context Available at 4K budget**  |                                                | **~2,700 tokens**                         | **3,450 tokens**                           | **+750** |

Note: Layer 0 (Agent base, ~100 tokens) and Layer 1 (Platform base, ~100 tokens) are fixed and not included in the overhead total above. Total overhead = memory/context layers only (Layers 2–4b), consistent with the canonical budget specification.

**Key insight**: The removal of the inflated Org Context budget (500 → 100 tokens, aligning with actual usage per H06 in 13-05) and the removal of the glossary from prompt overhead **more than compensates** for the addition of team memory. RAG context at the 2K budget increases from ~700 tokens to 1,450 tokens — a 107% improvement. The team memory feature is a net gain for response quality.

**Note on Glossary**: Glossary is not eliminated — terms are expanded inline in the user query at pipeline step 3b (pre-translation via `GlossaryExpander`). This means glossary context is zero-cost in the system prompt, targeted (only matched terms expanded), and moves from system-prompt trust level to user-message trust level.

**Token budget at 4K (Enterprise tier)**:

- Memory overhead: 550 tokens
- RAG context available: 3,450 tokens
- This is the sweet spot for comprehensive RAG with full personalization stack
