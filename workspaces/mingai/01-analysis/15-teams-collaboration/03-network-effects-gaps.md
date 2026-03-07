# 15-03 — Network Effects & Gaps: Teams Collaboration

**Feature**: Native Teams + Team Working Memory
**Focus**: Network behavior scoring + gap analysis for each dimension
**Research date**: 2026-03-07

---

## 1. Accessibility (Friction to Complete a Transaction)

### Current State: 9/10 (Unchanged)

Team working memory does not change how knowledge base content is retrieved or surfaced. Accessibility — defined as the friction a user faces in getting to a useful answer — is already strong from the individual personalization stack (org context + profile + individual working memory).

Team memory's accessibility contribution is indirect: it reduces the context-setting dialogue that precedes the first useful query when starting a new team session. If the AI already knows the team has been investigating Acme Inc's GDPR exposure, a new team member's first question lands in a richer context without any friction-adding setup steps.

**Estimated contribution**: Team memory reduces context-priming exchanges from 2–3 to 0–1 for team members returning to an active project. This is meaningful but secondary to the existing personalization stack.

### Accessibility Score with Team Memory: 9/10 (no change)

The team memory feature does not move the accessibility score. Individual personalization already achieves 9/10. Team memory is additive context, not an accessibility improvement.

### Gap

**Accessibility Gap A-1: Cold start — no team memory on project day 1**

For a new team or a new project, team working memory is empty. The accessibility benefit does not exist until the team has accumulated 3–5 sessions of collective queries. For project kickoffs, the team must still brief the AI conventionally.

Mitigation: Allow tenant admin or team admin to pre-seed team memory with key terms when creating a team (e.g., "Acme, M&A, GDPR, Q3 2026"). This immediately activates the accessibility benefit for all team members from session 1.

---

## 2. Engagement (Shared Context That Keeps Teams Coming Back)

### Current State (Without Team Memory): 8/10

Individual working memory creates engagement through recognition ("returning user from earlier session"). The 7-day TTL and per-user scoping means engagement is driven by individual session continuity.

### With Team Memory: 8.5/10

Team working memory adds a new engagement driver: **team recognition**. When a team member's query receives a response that references team investigation history, the experience signals "this AI is tracking our project, not just my individual sessions." This is qualitatively different from individual recognition — it creates a sense of collective AI intelligence, which is a stickier engagement hook.

**Specific engagement signals**:

- Returning team member lands in a session where the AI already knows the project context
- Response references a topic a teammate investigated ("Your team has been looking at DPA structures...")
- New team member joins and immediately experiences team-aware responses

### Engagement Score with Team Memory: 8.5/10 (+0.5)

### Gaps

**Engagement Gap E-1: No notification when team memory updates significantly**

If Sarah investigates a major new topic area that gets added to team memory, James has no way of knowing this happened. The shared context updated silently. A lightweight notification ("Your Finance team's AI context was updated — topics: vendor contracts, SOC 2") would increase engagement by making the invisible visible.

**Priority: P3** — nice-to-have; does not block core feature value.

**Engagement Gap E-2: Active team is per-session, not persistent**

Users must re-select their active team on every new session. A user who is always working as part of the M&A team must take this action every login. The friction is small but repetitive. For standing teams (permanent functional teams, not project teams), this re-selection adds no value.

**Priority: P2** — high annoyance-to-fix ratio. Implementing "remember last active team" per user per tenant is a small Redis write. The UX impact is significant for daily active users.

**Engagement Gap E-3: No team memory visibility for users**

Team members cannot see the current state of their team's working memory. They receive responses informed by team memory, but cannot inspect what is currently in the team context. A "team memory panel" (similar to a working memory debug view) would let users understand why their responses include certain contextual framing.

**Priority: P3** — transparency and trust feature. Important for enterprise adoption (users need to trust the system's context).

---

## 3. Personalization (Team Context Is Personalized to the Team's Work)

### Current State (Without Team Memory): 9/10

Individual personalization is comprehensive: org context (Layer 2), profile learning (Layer 3), individual working memory (Layer 4), memory notes (Layer 3 injected). The 9/10 score reflects genuine depth of individual personalization.

### With Team Memory: 9/10 (no change to the score, but new dimension added)

Team memory does not improve individual personalization — it adds a new personalization dimension: **team-level context**. The individual personalization stack remains unchanged. Team memory adds a Layer 4b that injects collective team investigation context below individual working memory and above RAG results.

This is additive, not a replacement. A user gets both:

- Individual personalization (profile, org context, individual working memory)
- Team personalization (shared team investigation history)

### Personalization Score with Team Memory: 9/10 (unchanged, team adds a new dimension)

### Gaps

**Personalization Gap P-1: Team memory is not personalized per agent**

Team working memory in Phase 1 is team-wide: one bucket per team, injected regardless of which agent the team member is chatting with. This means the M&A team's legal investigation topics are injected when team members use the HR agent.

This is noise, not signal. The individual working memory system addresses this with agent-scoped keys (`{tenant_id}:working_memory:{user_id}:{agent_id}`). Team memory should have an equivalent agent-scoped variant for Phase 2.

**Priority: P2** — architectural improvement, not a blocking gap for Phase 1.

**Personalization Gap P-2: Team memory topic quality degrades with off-topic usage**

If team members use the platform for personal or unrelated queries while the team active selector is engaged, their queries contribute noise to team memory. A Finance team member asking "what is Python list comprehension" would add "Python", "list", "comprehension" to the Finance team's bucket.

No filtering mechanism exists today. The individual working memory has the same vulnerability (no topic quality filter), but at the team level the problem is amplified — all team members' noise accumulates in one place.

**Priority: P2** — needs an opt-out or filter. See Gap P-2 remediation in §7.

**Personalization Gap P-3: Team memory treats all topics equally — no relevance weighting**

The team memory bucket accumulates topics via union with dedup. A topic mentioned once by one team member 6 days ago has equal representation to a topic mentioned 20 times by 5 team members over 3 days. The most actively investigated topics should be weighted higher in the team memory injection.

**Priority: P3** — nuanced improvement to extraction quality.

---

## 4. Connection (Integration with External Project Context Sources)

### Current State (Without Team Memory): 7/10

Individual connection is one-way: Azure AD → Org Context → prompt. No external project data sources are connected to working memory.

### With Team Memory: 7.5/10 (+0.5)

Auth0 group claim sync is the primary connection improvement:

- Auth0 `groups` claim → team structure automatically mirrors the corporate directory
- Group membership changes at the IdP level sync to platform team membership on next login
- This creates a live one-way connection: IdP → platform teams → team working memory

The connection score improves slightly because the platform's team structure is now connected to external identity data rather than being entirely manual.

### Connection Score with Team Memory: 7.5/10

### Gaps

**Connection Gap C-1: No integration with project management tools**

The most powerful team context connection would be to project management systems (Jira, Asana, Linear, Monday.com). If the AI knew the active issues and milestones of the team's current project, team memory could be seeded and enriched with structured project data — not just query keyword extraction.

Example: Team is working on "Jira Epic: GDPR Compliance for EU Launch." The Jira epic's title, description, and linked issues become seed context for team working memory. Every team member's AI session is immediately calibrated to the project without any queries being made.

**Priority: P4** — powerful but requires external API integration work. Not Phase 1 or 2.

**Connection Gap C-2: Auth0 group claim sync is one-way and login-triggered**

When an employee is removed from an AD group (offboarded from a project team), their removal from the platform team only takes effect on their next login. In a security-sensitive scenario (e.g., a contractor is removed from a confidential project team), their continued platform team membership means they could still have their queries contribute to team working memory until their next session.

**Priority: HIGH** — security-adjacent. Auth0 sync must include a webhook-triggered removal path for security scenarios, not just login-triggered sync.

**Connection Gap C-3: No calendar integration for meeting-aware team context**

A team with a meeting in 30 minutes about a specific topic could benefit from auto-seeded team memory based on the meeting agenda. Calendar integration (Google Calendar, Outlook) is a natural next connection.

**Priority: P5** — future feature, well beyond current scope.

---

## 5. Collaboration (Producers and Consumers Work Together via Shared AI Context)

### Current State (Without Team Memory): 3/10

Zero collaboration features. Every user is isolated. The 3/10 reflects only shared knowledge base access.

### With Team Memory: 7/10 (+4.0)

Team working memory is the primary collaboration mechanism. The collaboration score improvement is the feature's core value delivery. The jump from 3 to 7 reflects:

- Producers (team members querying) now create shared value for all Consumers (all team members)
- The platform accumulates collective intelligence at the team level
- Every new team member immediately inherits the team's investigation context

The score does not reach 8+ because:

- No shared persistent memory notes (team-curated, TTL-unbounded facts) — only session-scoped working memory
- No direct collaboration signals (team members cannot see each other's active sessions)
- No structured team knowledge (no wiki or shared notes structure)

### Collaboration Score with Team Memory: 7/10

### Gaps

**Collaboration Gap COL-1: No shared team memory notes (permanent, curated)**

Team working memory has a 7-day TTL. For standing teams (not project teams), this is a fundamental limitation: context built up over months is lost after a week of inactivity. A "shared team notes" feature — persistent facts that team admins curate and pin to the team — would provide durable shared context.

Example: The M&A team has permanent notes: "Our due diligence standard is KPMG framework. All financial models use EUR reporting currency. Regulatory threshold = €500K for material disclosure."

These facts should not expire after 7 days. They should be permanent until a team admin removes them.

**Priority: P1** — highest impact collaboration gap. Addresses the TTL limitation for standing teams. This is essentially "team memory notes" analogous to individual memory notes.

**Collaboration Gap COL-2: No per-team query attribution visibility**

Users can see that the AI is using team context, but cannot see who contributed a specific topic or what queries informed the team memory. Attribution transparency ("Sarah investigated: regulatory exposure, DPA structure") would increase team trust in the shared context.

**Priority: P3** — trust and transparency feature.

**Collaboration Gap COL-3: No team memory contribution opt-out for users**

A user might be doing exploratory research that they don't want to contribute to the team memory (e.g., sensitive HR-related query while the active team is the Finance team). There is no per-query opt-out from team memory contribution. The only option is to deactivate the team entirely for the session.

**Priority: P2** — important for user trust. A "private query" toggle that excludes a session from team memory contribution would address this.

**Collaboration Gap COL-4: Team admin controls missing from current Tenant Admin plan (06)**

Plan 06 (Tenant Admin) covers workspace setup, user management, integrations, and agent management. It does not include teams management. This is a blocking gap: the feature cannot be deployed without tenant admin UI to create and manage teams.

**Priority: BLOCKING** — teams management must be added to Plan 06 before implementation can begin.

---

## 6. Gap Priority Matrix

| Gap                                                 | Network Behavior | Impact          | Effort    | Priority     |
| --------------------------------------------------- | ---------------- | --------------- | --------- | ------------ |
| Team admin controls missing from Plan 06            | Collaboration    | BLOCKING        | Medium    | **BLOCKING** |
| Auth0 sync webhook-triggered removal                | Connection       | High (security) | Medium    | **P1**       |
| Shared team memory notes (persistent)               | Collaboration    | Very High       | Medium    | **P1**       |
| Accessibility cold-start — pre-seed team memory     | Accessibility    | High            | Low       | **P1**       |
| Per-query opt-out from team memory contribution     | Collaboration    | High            | Low       | **P2**       |
| Persistent active team (remember last selection)    | Engagement       | High            | Very Low  | **P2**       |
| Team memory agent-scoped variant                    | Personalization  | Medium          | Medium    | **P2**       |
| Team memory topic quality filter (noise prevention) | Personalization  | Medium          | Medium    | **P2**       |
| Topic relevance weighting in team memory            | Personalization  | Medium          | Medium    | **P3**       |
| Team memory visibility panel                        | Engagement       | Medium          | Low       | **P3**       |
| Team memory notifications ("context updated")       | Engagement       | Low             | Medium    | **P3**       |
| Team memory attribution visibility                  | Collaboration    | Medium          | Low       | **P3**       |
| Project management tool integration (Jira/Asana)    | Connection       | Very High       | Very High | **P4**       |
| Calendar integration                                | Connection       | Medium          | High      | **P5**       |

---

## 7. Gap Remediations (Priority P1 and P2)

### COL-4 Remediation (BLOCKING): Add Teams Management to Tenant Admin Plan 06

Before any implementation sprint, Plan 06 must be updated to include:

- Teams list view (create, view, edit, deactivate teams)
- Team members assignment UI (add/remove users from teams)
- Auth0 sync settings (enable/disable, claim field configuration)
- Team working memory settings (TTL override per team)

Estimated addition to Plan 06: 2 sprints (UI + API). This becomes a prerequisite gate for the feature.

### C-2 Remediation (P1): Auth0 Webhook-Triggered Team Membership Removal

Implement an Auth0 post-login action that also fires on user deactivation/group-removal events (via Auth0 Management API webhooks). On receipt:

1. Look up platform teams synced from the removed group
2. Remove the user from the team membership
3. Team memory is NOT cleared — only membership changes
4. If user was the only member, put team in "inactive" state

### COL-1 Remediation (P1): Shared Team Memory Notes

Extend the `tenant_teams` feature with a `team_memory_notes` table:

- Persistent (no TTL)
- Created by team members (any member) or team admins
- Top 5 most recent + most-referenced notes injected into Layer 4b alongside team working memory
- Injected in prompt at 50-token budget (within the 150-token Layer 4b allocation)

### P-2 Remediation (P2): Team Memory Quality Filter

Add an `exclude_from_team_memory` flag to the query request. Surface as a toggle in the chat UI (icon or toggle). When set, the query's topics are not written to team memory. The response is still informed by team memory.

A separate approach: implement a minimum topic relevance threshold. Topics that appear in <2 queries within a 24-hour window are not promoted to team memory. This passively filters one-off noise without requiring user action.
