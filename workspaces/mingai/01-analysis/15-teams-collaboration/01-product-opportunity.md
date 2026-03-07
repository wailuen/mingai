# 15-01 — Product Opportunity: Teams Collaboration

**Feature**: Native Teams + Team Working Memory
**Research date**: 2026-03-07
**Stage**: Analysis → Plan

---

## 1. Problem Statement

### 1.1 The Core Pain (First Principles)

Enterprise AI tools are individual tools. A team of five analysts working on the same M&A due diligence each independently brief the AI about the project, the counterparty, and their specific angle. The AI knows nothing about what their colleagues have already investigated. Every session starts blank for every person.

The result is threefold waste:

1. **Redundant context-setting**: If Sarah spent two hours building working memory around "Acme Inc regulatory exposure," her colleagues start from scratch when they ask similar questions the next day. Estimated cost: 30–90 minutes per team member per active project, per week.
2. **Inconsistent AI responses**: Because each user has different working memory, the same question asked by two teammates in the same team may receive meaningfully different answers — calibrated to different individual contexts rather than the shared project context.
3. **Invisible prior investigation**: When a colleague has already thoroughly investigated a topic, that investigation is invisible to teammates. The team incurs duplicate AI cost and duplicate human time reaching the same destination independently.

### 1.2 The Scale of the Problem

This is not edge-case behavior — it is the default state of any team using an AI assistant:

- Knowledge teams (legal, finance, HR, compliance) routinely operate on shared projects
- Enterprise AI usage skews toward team-based workstreams, not individual lookups
- The failure compounds as team size increases: a 10-person team doing parallel research on the same topic incurs 10x the context-building overhead

### 1.3 Why the Current Architecture Makes This Worse

mingai's Profile & Memory stack (13-series) is meticulously tuned for individual personalization — org context, learned behavioral profile, explicit memory notes, session working memory. This is excellent for the individual.

But the platform provides no shared context layer. When Sarah and James are on the same team working on the same project, their AI sessions are siloed at the same depth as two strangers at competing firms.

The collaboration score in the current platform is explicitly acknowledged as 3/10 in analysis 13-02. The architecture gap is identified in 13-03 as the highest-priority network behavior gap.

### 1.4 What Teams Actually Need

Not just "same knowledge base" — teams already share the tenant knowledge base. What's missing is **shared investigation context**:

- Know what topics this team has already explored
- Know what questions team members have already asked
- Surface relevant prior team investigation when a new query touches a known topic
- Accumulate shared project context without requiring any explicit curation effort

---

## 2. Current State

### 2.1 Collaboration Capability Inventory

| Capability                         | Current State                                 | Score    |
| ---------------------------------- | --------------------------------------------- | -------- |
| Shared knowledge base              | YES — all team members query same KB          | 9/10     |
| Shared AI context / working memory | NO — individual only                          | 0/10     |
| Shared memory notes                | NO                                            | 0/10     |
| Team-aware responses               | NO                                            | 0/10     |
| Team structure in platform         | NO — teams come only from IdP groups at login | 0/10     |
| Active team selection per session  | NO                                            | 0/10     |
| **Overall collaboration**          |                                               | **3/10** |

The 3/10 score in 13-02 reflects shared knowledge base access as the sole collaboration primitive. Everything above the knowledge base is individual.

### 2.2 Current Working Memory Architecture (Baseline)

Individual working memory is injected at Layer 4 of the system prompt stack:

```
Layer 4: Working Memory (100 tokens, Redis, 7-day TTL)
Key: {tenant_id}:working_memory:{user_id}:{agent_id}
Content: recent topics (top 5), last 3 queries (with timestamps), returning-user flag
```

At a 2K token budget with the old full stack (including 500-token glossary allocation):

- Total overhead: ~1,300 tokens (Layers 2–4 + 6) + ~200 tokens base
- RAG context available: ~500 tokens

### 2.3 The Token Budget Opportunity

The brief specifies that the glossary is being removed from the primary overhead budget (confirmed in this feature spec). This creates headroom:

- Old overhead: ~1,300 tokens (with 500 glossary)
- New overhead with glossary removed: ~800 tokens (Org Context 100 + Profile 200 + Working Memory 100 + Agent/Platform base 200 + reserve 100)
- Team memory budget: 150 tokens (Layer 4b)
- New total overhead: ~950 tokens
- RAG context available at 2K: ~1,050 tokens (up from ~500 — a 110% increase)

This token budget improvement makes the team memory feature a net positive for response quality, not just a personalization add-on.

---

## 3. Competitive Landscape

### 3.1 Competitive Matrix

| Product            | Shared AI Context    | Team Memory        | Team-Aware Responses           | Notes                                             |
| ------------------ | -------------------- | ------------------ | ------------------------------ | ------------------------------------------------- |
| ChatGPT Enterprise | NO                   | NO                 | NO                             | Memory is per-user only                           |
| Microsoft Copilot  | NO                   | NO                 | Partial (via M365 Graph group) | Searches team content; no shared memory state     |
| Glean              | NO                   | NO                 | NO                             | Search is shared; no memory                       |
| Notion AI          | Partial (page-level) | NO                 | Only if same page open         | Not a memory system — just context                |
| Guru               | NO                   | NO                 | NO                             | Knowledge base tool, no memory                    |
| Slack AI           | NO                   | NO                 | NO                             | Channel-aware but no persistent memory            |
| Amazon Q Business  | NO                   | NO                 | NO                             | Group-based access; no shared memory              |
| **mingai**         | **YES (proposed)**   | **YES (proposed)** | **YES (proposed)**             | **First enterprise RAG with team working memory** |

### 3.2 Market Gap Assessment

No enterprise RAG platform ships persistent shared team AI context. This is confirmed whitespace.

The absence is explainable: building shared memory requires a team management layer that most AI assistant tools do not have. They either rely entirely on IdP groups (and thus cannot manage team membership independently) or provide no team concept at all. mingai's decision to build native team management — independent of SSO/IdP groups — creates the structural foundation that competitors lack.

**The gap = Shared Working Memory × Native Team Management × Enterprise Privacy**

---

## 4. Value Propositions

**VP-1: The team AI gets smarter as the team uses it** — every query from a team member contributes to shared team working memory. A new team member joining mid-project immediately benefits from what teammates have already investigated, with zero curation effort from anyone.

**VP-2: No more project context re-briefing** — when a team is actively working on a project, team working memory accumulates the key topics, terminology, and directions under investigation. Team members stop spending the first 2 minutes of every session re-explaining the project context to the AI.

**VP-3: Consistent team-wide AI responses** — because all team members share the same team context layer, the AI gives coherent, aligned responses across the team. The Finance team's AI does not tell Sarah one thing and James another about the same regulatory question.

**VP-4: Works without IdP dependency** — teams are managed natively in the platform. A team can be created in minutes without waiting for IT to configure an AD group. Username/password tenants without any SSO can have teams. Auth0 group claim sync is additive, not required.

**VP-5: Active team selection = intentional context** — users choose which team's memory to activate per session. A user who sits on three project teams can focus the AI on whichever project they're working on today. This is intentional context management, not ambient leakage.

**VP-6: GDPR-compliant by design** — team memory is scoped to tenants, cleared on tenant delete, and purged for a user's contributions when they request erasure. The architecture enforces privacy boundaries at the Redis key level.

**VP-7: Zero-configuration value** — team working memory populates automatically from normal team usage. No one has to curate it, update it, or manage it. The value compounds invisibly.

---

## 5. Unique Selling Points (Critical Scrutiny)

### USP-1: Shared AI Working Memory for Enterprise Teams

**Claim**: mingai is the only enterprise RAG platform that provides a persistent, shared AI working memory layer scoped to a team — accumulating team investigation context automatically from normal usage and injecting it into every team member's queries.

**Scrutiny**:

- Microsoft Copilot accesses M365 Graph group data but this is static metadata (org structure, document ownership), not a dynamically-accumulating memory of what the team has investigated with AI.
- Notion AI is page-aware but requires all team members to be on the same Notion page — it is context, not memory.
- Slack AI is channel-aware but has no persistent memory between sessions.
- No known competitor accumulates AI investigation context at the team level automatically.
- **Risk**: The USP depends on team working memory being genuinely useful. If the memory contains mostly noise (generic topics, non-team-specific queries), the value collapses. Topic quality is the execution risk.
- **Verdict**: USP holds, but is execution-dependent. The keyword extraction quality (from individual working memory architecture) is the ceiling for team memory quality. If topic extraction is poor for individual memory, it will be worse at the team aggregate level. This is a genuine USP only if extraction quality is good.

### USP-2: Platform-Native Team Management (IdP-Independent)

**Claim**: mingai manages teams natively — teams can be created in the platform by tenant admins without any dependency on IdP groups, AD configuration, or IT involvement. This works with username/password authentication and all SSO providers.

**Scrutiny**:

- Most enterprise AI tools either have no team concept (ChatGPT Enterprise, Glean) or rely entirely on IdP groups for their team structure (Microsoft Copilot). Neither is flexible.
- A tenant admin who wants to create a project team that crosses departmental lines (Finance + Legal + HR on an M&A) cannot do this via AD groups without IT involvement in most organizations.
- mingai's native team management makes cross-functional project teams a self-service action in minutes.
- **Risk**: Maintaining two sources of truth (IdP groups + platform teams) creates confusion. When does Auth0 sync create a team vs. a tenant admin creating one manually? The merge strategy for Auth0-synced teams vs. manually-created teams needs to be clear.
- **Verdict**: Genuine USP, particularly for smaller tenants without mature IAM infrastructure. Weaker USP for large enterprises with established AD group governance.

### Non-USP: Shared Knowledge Base

**Why this is not a USP**: Every enterprise RAG tool offers shared knowledge base access. This is table stakes, not differentiation.

### Non-USP: Team-Level Access Controls

**Why this is not a USP**: Role-based access to knowledge bases is a common enterprise feature. The USP is specifically in the AI memory layer, not the access control layer.

---

## 6. The 80/15/5 Mapping

### 80% — Reusable Core (Platform-Agnostic)

- `TeamWorkingMemoryService`: Redis key management, topic merge, query attribution, TTL management
- Auth0 group claim sync engine: parse `groups` claim, create/update teams, track sync source
- Layer 4b in `SystemPromptBuilder`: team memory formatting and injection
- Team membership data model: `tenant_teams` + `team_memberships` tables
- Active team session management: Redis session key, default selection logic
- GDPR team memory clear: user erasure cascade to team buckets where user was a member

### 15% — Tenant Self-Service Configuration

- Teams management UI in Tenant Admin: create teams, assign members, deactivate teams
- Auth0 group sync settings: enable/disable sync, configure which claim field to read (`groups` vs. custom claim)
- Team working memory TTL: override default 7-day TTL per team (e.g., longer for standing teams, shorter for project teams)
- Active team UI in chat: the team selector dropdown shown to end users

### 5% — True Customization

- Team memory export/archive: export team memory contents for compliance review or project handoff
- Auth0 group claim field name: configure for tenants using non-standard group claim fields (`roles`, `teams`, custom)
- GDPR contribution-only erasure: erase only the specific user's query contributions from team memory (vs. clearing the entire bucket) — requires contribution attribution log

---

## 7. Open Questions (For Plan)

1. **Auth0 sync team pollution**: Login events may carry 10–50 AD groups (all-company, VPN users, office floor, distribution lists). Creating a platform team for each would produce dozens of irrelevant teams. What is the filter/allowlist strategy for group-to-team promotion?
2. **Team memory quality**: Team working memory is aggregated from keyword extraction across all team members' queries. At low query volume (small team, early stage), the team memory may be too thin to be useful. What is the minimum team activity threshold before team memory is injected?
3. **Cross-agent team memory**: Should team working memory be scoped per agent (team × agent) or per team (team-wide across all agents)? Team-wide may be simpler and more useful; per-agent adds architectural complexity.
4. **Persistent active team**: The active team is per-session. Should it persist across sessions for standing teams? A user who always works as part of the Finance team should not have to re-select every login.
5. **Team memory visibility**: Can team members see the current contents of team working memory? A "team memory" panel in the UI would build trust and allow members to understand why responses reference certain context.
6. **Team admin vs. team owner**: Is there a team owner role (a user who can manage the team's settings, not just a tenant admin)? This would reduce admin burden for large organizations with many teams.
