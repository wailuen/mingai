# 15-05 — Red Team Critique: Teams Collaboration

**Feature**: Native Teams + Team Working Memory
**Reviewed documents**: 15-01 through 15-04, 13-series (Profile & Memory), Plan 06 (Tenant Admin)
**Review date**: 2026-03-07
**Reviewer**: Red Team Agent (deep-analyst)

---

## Executive Summary

Teams Collaboration is architecturally sound and addresses a genuine product gap. However, this critique identifies **3 CRITICAL**, **5 HIGH**, **6 MEDIUM**, and **4 LOW** risks totaling **18 findings**. The most severe issues are: (1) team membership misconfiguration creates a confidential information leakage path — a user added to the wrong team can see other members' investigation topics through AI responses; (2) the GDPR erasure approach preserves team memory topic keywords after user erasure, which may constitute retained personal data under certain regulatory interpretations; and (3) Auth0 group sync can auto-create tens to hundreds of irrelevant platform teams on first login of any SSO tenant, creating a noise pollution problem that degrades the tenant admin experience.

| Severity  | Count  | IDs           |
| --------- | ------ | ------------- |
| CRITICAL  | 3      | R01, R02, R03 |
| HIGH      | 5      | H01–H05       |
| MEDIUM    | 6      | M01–M06       |
| LOW       | 4      | L01–L04       |
| **Total** | **18** |               |

---

## 1. CRITICAL Risks (R01–R03)

### R01 — Team Membership Misconfiguration Creates Confidential Information Leakage

- **Category**: Security / Privacy
- **Description**: Team working memory stores a shared bucket of investigation topics and recent queries with user attribution. Any member of a team can receive AI responses informed by all other members' investigation history. If a tenant admin accidentally adds a user to the wrong team (e.g., adds a junior analyst to the M&A Due Diligence team for Acme Inc), that user immediately gains access to the team's investigation history — including query attributions like "Sarah K.: What are Acme's undisclosed liabilities?" This is information that the junior analyst should not have, delivered passively through AI responses without any access control alert.
- **Evidence**: `04-implementation-alignment.md` §4.3 — team memory injection includes user attribution with `user_display_name`. `02-platform-model-aaa.md` §1.1 — "Every new team member immediately inherits the team's investigation context." There is no access check beyond team membership at response time.
- **Impact**: Enterprise tenants often work on confidential projects (M&A, litigation, HR matters) where team membership is itself sensitive. A wrongly-assigned team membership exposes not just knowledge base content (which has RBAC) but AI investigation context — which has no equivalent access control. This is worse than a document access misconfiguration because the investigation context is not itself a document with an audit trail; it is an aggregated AI memory bucket.
- **Remediation**: (a) **Require explicit confirmation when adding a user to a team** in the tenant admin UI: "This user will have access to [Team Name]'s AI investigation history. Confirm." (b) Add a **team membership audit log** — every add/remove is logged with the user affected, team, action (added/removed), actor (who made the change), source (manual/auth0_sync), and timestamp. Audit log is visible to tenant admin in Tenant Admin > Teams > Audit Log at any time. No real-time alert is sent to the affected user (would be noisy), but the tenant admin can review the full history. (c) Implement **team memory visibility delay**: new team members only see team memory contributions made after their join date (not historical context). This is the most protective option and aligns with least-privilege principles. (d) For high-confidentiality use cases, allow tenant admin to create "private" teams where team memory is not shared — only individual working memory applies.
- **Priority for remediation**: Item (b) is mandatory pre-launch and ships in Sprint 8 (Tenant Admin) alongside the team management UI. Item (a) is strongly recommended. Item (c) should be a Phase 1 configuration option.
- **Status**: RESOLVED — audit log (item b) ships in Sprint 8 (Tenant Admin) alongside team management UI.

---

### R02 — GDPR Erasure: Topic Keywords May Constitute Personal Data Under Regulatory Interpretation

- **Category**: Privacy / Compliance
- **Description**: The proposed GDPR erasure approach (`clear_user_contributions()`) removes user-attributed query records from Redis but preserves topic keywords. The rationale is that topics are non-PII keywords (e.g., "GDPR", "NDA"). However, under GDPR Article 4(1), personal data is "any information relating to an identified or identifiable natural person." In a team context where a user was the only or primary contributor of certain topics, those topics may be traceable back to the user ("We know Alice investigated this topic because only she was working on it"). The topics effectively identify Alice's professional activity.
- **Evidence**: `04-implementation-alignment.md` §2.2 — `clear_user_contributions()` spec: "Topics contributed by the user CANNOT be individually removed — they are aggregated into the bucket. Topics are preserved (acceptable: they are non-PII keywords)." This assumption is legally fragile.
- **Impact**: A regulatory interpretation in FR/DE/NL that treats aggregated query topics as identifiable professional activity data would require full topic removal on erasure. If the platform's DPA (Data Processing Agreement) makes commitments about complete data deletion, retaining topics violates those commitments. Risk: regulatory inquiry or DPA complaint.
- **Remediation**: (a) Query attribution in team memory is **anonymized by design**: the `recent_queries` Redis hash field stores `{ "query": "...", "contributor": "a team member", "timestamp": "..." }` — no user ID and no display name are stored in team memory. This eliminates the personal data risk in the injection layer. (b) Analytics and the membership audit log (a separate PostgreSQL system) can still track who contributed what, but the working memory injection layer never carries personal identifiers. (c) Document the rationale in GDPR Article 30 records: "team memory is an AI context tool, not an audit trail; personal identifiers are deliberately excluded." (d) Short-term mitigation: set team working memory TTL to match individual working memory TTL (7 days) — meaning all topics naturally expire within 7 days without long-term retention concern.
- **Status**: RESOLVED — anonymous attribution ("a team member") is the canonical spec. 39-teams-collaboration-architecture.md and 10-teams-collaboration-plan.md updated accordingly.

---

### R03 — Auth0 Group Sync Auto-Creates Hundreds of Irrelevant Teams on First SSO Login

- **Category**: Product / Architecture
- **Description**: For enterprises with mature Active Directory environments, the `groups` claim in the Auth0 JWT may contain 50–200 group memberships per user — including distribution lists, security groups, system groups, license groups, and organizational units. The Auth0 sync engine as specified creates a platform team for each qualifying group. Even with the default blocklist (`all-*`, `*-vpn`, etc.), many enterprise environments have hundreds of groups that don't match common noise patterns (e.g., `prj-2023-budget-approval`, `dl-london-office`, `sec-sox-compliance-read`). The first SSO tenant login event triggers mass team creation.
- **Evidence**: `04-implementation-alignment.md` §3.2 — noise filter pre-populated with 5 blocklist patterns. This is insufficient for enterprise LDAP environments where group naming conventions vary widely across organizations.
- **Impact**: A tenant admin logs in for the first time and discovers 150 teams created automatically, most of which are irrelevant to AI collaboration. The tenant admin experience is severely degraded. Worse: each of these teams begins accumulating team working memory from the first query, polluting the Redis keyspace and the system with team memory for "dl-london-office" and "sec-sox-compliance-read."
- **Remediation**: Auth0 group sync changes from **auto-create (original design) to opt-in allowlist**. (a) Tenant admin must configure which Auth0 group names to sync BEFORE any user logs in. Configuration: Tenant Admin > Teams > Auth0 Sync Settings > Group Allowlist (comma-separated group names or simple wildcard patterns, e.g. `Q4-*`). (b) **Default: allowlist is EMPTY** — no auto-sync occurs until the tenant admin explicitly populates the allowlist. (c) On login: only groups matching the allowlist are synced; all other groups are silently ignored — no team is auto-created for non-allowlisted groups. (d) Auto-create behavior is preserved for allowlisted groups: if the group matches the allowlist and no team exists yet, the team is created automatically. (e) **Preview before sync**: when a tenant admin enables Auth0 sync, show a preview of which groups from the most recent login would have been synced. Allow them to adjust the allowlist before committing. (f) **Team creation rate limit** (retained): maximum 20 teams created per sync event per tenant.
- **Status**: RESOLVED — opt-in allowlist replaces auto-create. 39-teams-collaboration-architecture.md and 10-teams-collaboration-plan.md updated accordingly.

---

## 2. HIGH Risks (H01–H05)

### H01 — One Active Team Per Session Is a Power User Pain Point

- **Category**: UX / Product
- **Description**: A user working across multiple active project teams in a single session must manually switch their active team each time they shift focus. For knowledge workers who context-switch between projects multiple times per day (common in consulting, law, finance), this is a persistent friction point. Worse: if the user forgets to switch, their queries from Project A contribute to Project B's team memory. This is not just UX friction — it is a data quality and information integrity issue.
- **Evidence**: `04-implementation-alignment.md` §5 — active team is per-session, stored in `{tenant_id}:session:{session_id}:active_team_id`. No mechanism for per-agent active team or per-conversation active team. `03-network-effects-gaps.md` Gap E-2 identifies this as a P2 gap, but the severity is higher than P2 for power users.
- **Impact**: For a management consultant who is on 3 project teams simultaneously: mis-attributed team memory entries accumulate; context switches require manual team switching; the feature creates noise rather than signal for multi-team users.
- **Remediation**: (a) In Phase 1, add a **"private query" toggle** that excludes the query from team memory contribution (from Gap COL-3 remediation). This is the minimal safety valve. (b) In Phase 2, implement per-conversation active team (each new conversation inherits the active team from the previous but can be changed independently). (c) In Phase 2, investigate auto-team-detection: if the query topics match one team's memory bucket more strongly than others, suggest switching to that team.

---

### H02 — Team Memory Quality Degrades With Off-Topic Usage

- **Category**: Product / Data Quality
- **Description**: When a user selects a team as their active team, ALL queries in that session contribute to the team's working memory bucket — regardless of topic relevance to the team's work. A Finance team member who asks "what is the Python difference between a list and a tuple?" while the Finance team is active contributes "Python", "list", "tuple", "difference" to the Finance team's memory. Over time, all team memory buckets collect noise from unrelated queries.
- **Evidence**: `04-implementation-alignment.md` §2.2 — `update_team_memory()` calls `WorkingMemoryService._extract_topics()` on every query. No relevance filter between query topics and team's known topic domain.
- **Impact**: Team memory degrades into a generic cache of all topics any team member ever asked about. The USP ("team AI gets smarter as the team uses it") erodes into "team AI accumulates noise over time." For teams that use the AI for both project work and general questions, this happens quickly.
- **Remediation**: (a) **Minimum topic frequency filter**: a topic is only promoted to the team memory bucket if it appears in at least 2 queries within 48 hours. Single-occurrence topics are discarded. (b) **Team domain anchoring (Phase 2)**: when creating a team, admin can specify 3–5 seed topics that define the team's domain. Topics are only added to team memory if they have semantic similarity to at least one seed topic. (c) **"Private query" toggle** (from H01 remediation) allows users to opt out for clearly off-topic queries.

---

### H03 — Concurrent Redis Writes: Race Condition Under High Team Activity

- **Category**: Architecture
- **Description**: The Redis write strategy in `04-implementation-alignment.md` §2.4 uses WATCH for optimistic locking. Under high team activity (e.g., 50 team members querying simultaneously during an all-hands sprint), the optimistic lock will fail frequently — the WATCH transaction will need to retry multiple times. The spec does not define retry behavior, maximum retry count, or fallback when retries are exhausted.
- **Evidence**: `04-implementation-alignment.md` §2.4 — WATCH pipeline is specified but no retry loop or error handling is defined. `async with self.redis.pipeline() as pipe: await pipe.watch(key); pipe.multi()...` — if another write occurs between WATCH and EXECUTE, the transaction throws `WatchError`.
- **Impact**: Under load, team memory updates may silently fail if the retry strategy is not implemented. Some queries stop contributing to team memory without any error signal. The team's investigation topics accumulate more slowly than expected.
- **Remediation**: Implement a retry loop with a maximum of 3 attempts and 10ms jitter between retries. If all 3 retries fail (extremely rare — would require 3 concurrent writes to the exact same key within milliseconds), log a warning and skip the write silently (the response is not affected; only the team memory update fails). Document the maximum-retry path as acceptable degradation. For teams larger than 20 members, consider using a Redis Lua script instead of WATCH (atomic by definition, no retry needed).

---

### H04 — Auth0 Sync Login-Triggered Only: Security Window for Removed Members

- **Category**: Security
- **Description**: When an employee is removed from an AD group (e.g., leaving a confidential project team), the platform's team membership only updates on their next login. During the window between AD group removal and the user's next login (which could be days or weeks), the user continues to have their queries contribute to the team's working memory bucket — and continues to receive responses informed by the team's context.
- **Evidence**: `04-implementation-alignment.md` §3.1 — sync runs "On receipt" of Auth0 login callback. No webhook or push mechanism for group removal events. `03-network-effects-gaps.md` Gap C-2 identifies this as P1 but the security severity is higher than P1.
- **Impact**: Confidential project data (team investigation history) is accessible to a user who has been removed from the project team at the IdP level. For regulated industries (finance, legal, healthcare), this is a compliance failure.
- **Remediation**: Implement Auth0 Management API webhook listener for user-group removal events. On receipt: immediately call `remove_team_membership()` for the affected user and team. This is an Auth0 Management Event webhook (available in Auth0 Pro plans). Must be implemented before Auth0 sync goes to production for regulated tenants.

---

### H05 — Plan 06 Gap Blocks Feature Delivery But Has No Formal Tracking

- **Category**: Process / Architecture
- **Description**: `03-network-effects-gaps.md` Gap COL-4 identifies that Tenant Admin Plan 06 does not include teams management UI or API. This is a **blocking dependency** — without tenant admin capability to create teams, no team can exist, and team working memory provides zero value. However, this blocker is identified in the analysis docs but not formally tracked in Plan 06 or any sprint plan.
- **Evidence**: `03-network-effects-gaps.md` Gap COL-4: "Priority: BLOCKING — teams management must be added to Plan 06 before implementation can begin." `04-implementation-alignment.md` Sprint 1: "Plan 06 teams management added" listed as dependency. Plan 06 itself has not been updated.
- **Impact**: If this dependency is not formally tracked and resolved before implementation begins, Sprint 1 of this feature will stall. The sprint dependency chain (Sprint 1 → Sprint 2 → Sprint 5 → Sprint 6) means a Plan 06 delay cascades through the entire feature.
- **Remediation**: Before any sprint planning for this feature: (a) Update Plan 06 to add teams management as a component (2 sprint estimate). (b) Assign teams management as a prerequisite milestone that gates Sprint 1. (c) Add to the formal backlog with issue tracking.

---

## 3. MEDIUM Issues (M01–M06)

### M01 — Token Budget Claim "950 Total" Contradicts Detailed Layer Math

- **Category**: Architecture / Documentation
- **Description**: The feature brief states "total overhead drops from ~1,300 to 950 (glossary removed) + 150 team memory = 950 total." This math is internally inconsistent — 950 overhead and then adding 150 team memory should yield 1,100, not 950. The analysis doc `04-implementation-alignment.md` §8 calculates overhead at ~750 tokens. Three different numbers (1,300 in 13-series, 950 in the feature brief, 750 in this analysis) create confusion about what the authoritative token budget is.
- **Evidence**: Feature brief: "overhead drops from ~1,300 to 950 + 150 team memory = 950 total." `04-implementation-alignment.md` §8: Total Overhead = ~750 tokens (after removing Org Context overallocation and glossary). 13-05 R02: "At a 2K budget, this leaves only 500 tokens for RAG."
- **Impact**: Token budget is margin-critical (per MEMORY.md). An incorrect budget calculation could result in RAG content being truncated more aggressively than expected, degrading response quality.
- **Remediation**: Establish a single canonical token budget document. `04-implementation-alignment.md` §8 should be the authoritative reference. All other references should link to this table, not re-derive the numbers. The authoritative number is: overhead ~750 tokens, RAG available at 2K = ~1,250 tokens.

---

### M02 — USP-1 Depends on Keyword Extraction Quality — Same Weakness as Individual Working Memory

- **Category**: Product
- **Description**: USP-1 ("team AI gets smarter as the team uses it") is evaluated as holding, but the verdict notes it is "execution-dependent" and "limited by keyword extraction quality." The keyword extraction in `WorkingMemoryService._extract_topics()` is ASCII-only and English-only (per H04 in 13-05). Team memory inherits this weakness. For multinational teams, the USP does not hold.
- **Evidence**: 13-05 H04: "Non-Latin scripts (Chinese, Japanese, Korean, Arabic) produce zero topics." `04-implementation-alignment.md` §7 states `_extract_topics()` from `WorkingMemoryService` is reused directly with no modification.
- **Impact**: The collaboration story breaks for multinational enterprise tenants — exactly the highest-value enterprise segment.
- **Remediation**: Before shipping team memory, implement the Unicode-aware regex and multi-language stop word lists from 13-05 H04 remediation. This is a prerequisite, not a Phase 2 improvement, for multinational viability.

---

### M03 — No Minimum Team Activity Threshold Before Team Memory Injection

- **Category**: Product / UX
- **Description**: Layer 4b is injected whenever an active team is selected and the Redis key exists, even if the team memory contains only 1 topic from 1 query. "Team Context: Project Alpha — Topics: Excel" is noise, not signal. Injecting trivially thin team memory consumes 150 tokens of prompt budget without delivering value.
- **Evidence**: `04-implementation-alignment.md` §2.2 `get_team_memory()`: "Returns None if no team memory exists (key missing or empty)." But there is no threshold for "meaningfully populated" — a key with 1 topic will be returned and injected.
- **Remediation**: Implement a minimum content threshold in `get_team_memory()`: return None (suppress injection) if team memory has fewer than 3 topics OR fewer than 2 distinct contributors. This ensures Layer 4b is only active when there is genuine shared context to inject.

---

### M04 — "source = auth0_sync" Teams Are Invisible to Users; Confusion About Team Origin

- **Category**: UX
- **Description**: When Auth0 sync creates a team from an AD group, the team appears in the user's active team selector in chat. The user may not understand why this team exists, who created it, or what it's for. An AD group called "dl-london-office" appearing as an AI collaboration team context is confusing.
- **Evidence**: `04-implementation-alignment.md` §5 — active team selector "lists all teams the user belongs to." No UI differentiation between manual teams and auto-synced teams.
- **Remediation**: In the team selector UI: display a badge next to auto-synced teams ("Synced from directory"). In the Tenant Admin teams list: show the `source_group_id` and `source` column. Allow tenant admin to rename auto-synced teams without breaking the sync link.

---

### M05 — team_memory_contributions Table Grows Unbounded

- **Category**: Architecture / Scalability
- **Description**: The `team_memory_contributions` table creates one record every time any user's query writes to any team memory bucket. For a team of 10 members doing 20 queries/day, this is 200 records/day per team. At 100 teams, 20,000 records/day. After 6 months, the table has ~3.6M records. The table has no TTL, no archival strategy, and no purge mechanism.
- **Evidence**: `04-implementation-alignment.md` §1.2 — table definition has no partitioning, no TTL, no `ON DELETE` policy for aged records.
- **Impact**: Table growth degrades query performance for `clear_user_contributions()` (which must scan all user's contributions). For large tenants at scale, this becomes a slow GDPR erasure operation.
- **Remediation**: (a) Add `contributed_at` index (already specified). (b) Add a background cleanup job: delete `team_memory_contributions` records older than 30 days (team memory TTL max is 30 days, so contributions older than 30 days cannot affect any active Redis bucket). (c) Add table partitioning by `contributed_at` (monthly partitions) for production scalability.

---

### M06 — Cold Start Gap Is Not Addressed in Implementation Plan

- **Category**: Product
- **Description**: `03-network-effects-gaps.md` Gap A-1 identifies that on project day 1, team memory is empty and the accessibility benefit does not exist. The recommended mitigation is "allow tenant admin or team owner to pre-seed team memory with key terms when creating a team." This is mentioned in the gap doc but does not appear in the data model, service specification, or sprint plan in `04-implementation-alignment.md`.
- **Evidence**: `03-network-effects-gaps.md` Gap A-1 remediation: "Allow tenant admin to pre-seed team memory with key terms when creating a team." `04-implementation-alignment.md` §2.2 — `TeamWorkingMemoryService` has no `seed_team_memory()` method. Sprint table has no seed-memory sprint.
- **Remediation**: Add `seed_team_memory(tenant_id, team_id, seed_topics: List[str])` to `TeamWorkingMemoryService`. Call this from the "Create Team" flow in the tenant admin UI with an optional "seed topics" field. Seeds are added with `user_display_name: "Team Admin"` attribution. Add to Sprint 2 (alongside teams management API).

---

## 4. LOW / Nice-to-Have (L01–L04)

### L01 — No Team Memory Export for Project Archives or Compliance

- **Category**: Product
- **Description**: When a project concludes, the team's investigation history in working memory expires within 7 days. There is no way to archive or export team memory before it expires. For compliance-sensitive projects, the team's AI investigation log may need to be preserved.
- **Evidence**: `01-product-opportunity.md` §6 — 5% customization includes "team memory export/archive." Not in any implementation sprint.
- **Remediation**: Add to Phase 3 roadmap. `GET /teams/{id}/memory/export` returns the current Redis hash contents as JSON. Add a "Freeze team memory" option that extends TTL to 365 days when a project concludes.

---

### L02 — Platform Model Score Self-Assessment Lacks Validation Criteria

- **Category**: Business
- **Description**: Platform model scores (7.0 → 8.5) are theoretical projections. No validation criteria are defined. When does the 8.5 score become confirmed?
- **Evidence**: `02-platform-model-aaa.md` §1.5 — score table is forward-looking with no measurement plan.
- **Remediation**: Define validation criteria: "Platform model score 8.5 confirmed when (a) >50% of tenants with teams have at least one team with >5 members actively using team memory, AND (b) team-active users show >15% higher 30-day retention than non-team users, as measured by usage analytics."

---

### L03 — Auth0 Sync Creates Two Sources of Truth for Team Membership

- **Category**: Architecture
- **Description**: Manual teams (source=manual) and auth0-synced teams (source=auth0_sync) are separate entities even if they represent the same group. If the Finance department has a manually-created team and a synced AD group "Finance-Dept", they accumulate separate team memory buckets with no connection. Teams in different buckets means the collaboration value is fragmented.
- **Evidence**: `04-implementation-alignment.md` §3.3 — "A manually-created team and an Auth0 group do NOT merge automatically."
- **Remediation**: For Phase 2: add a "link to directory group" action in the tenant admin team settings. Linking merges the two entities (manually-created team inherits the auth0_sync source_group_id). The two Redis buckets are merged (union of topics, concatenation of recent_queries).

---

### L04 — No Feedback Loop on Team Memory Utility

- **Category**: Product / Analytics
- **Description**: There is no mechanism to measure whether team memory is actually improving team query quality. The platform cannot distinguish between "team memory injection helped" and "team memory injection was irrelevant" for any given query.
- **Evidence**: No analytics specification in any 15-series document.
- **Remediation**: Add to platform analytics: track "team_memory_active" as a query attribute (boolean). Compare First-Exchange Utility Rate for queries with and without team memory active. Target: team_memory_active queries show >10% higher single-turn resolution rate. Instrument in Sprint 5 alongside the Layer 4b implementation.

---

## Mandatory Pre-Launch Fixes (CRITICAL + HIGH)

| #   | Risk | Fix Required Before                                                                                   | Owner                                      |
| --- | ---- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| 1   | R01  | Membership confirmation UI + team membership audit log (Sprint 8) + join-date visibility boundary     | MVP launch — audit log RESOLVED (Sprint 8) |
| 2   | R02  | Anonymous attribution canonical spec ("a team member") — no user ID/display name in Redis team memory | RESOLVED                                   |
| 3   | R03  | Auth0 sync opt-in allowlist (empty default, no auto-sync until configured) — architecture updated     | RESOLVED — Sprint 4 updated                |
| 4   | H01  | "Private query" toggle to exclude from team memory contribution                                       | MVP launch                                 |
| 5   | H02  | Minimum topic frequency filter (2 queries/48h before topic promotion)                                 | MVP launch                                 |
| 6   | H03  | Redis write retry loop (max 3 attempts, 10ms jitter); Lua script for teams >20                        | MVP launch                                 |
| 7   | H04  | Auth0 Management API webhook listener for group removal events                                        | Pre-production for regulated tenants       |
| 8   | H05  | Formally update Plan 06 with teams management; set as prerequisite gate for Sprint 1                  | Before Sprint 1                            |
