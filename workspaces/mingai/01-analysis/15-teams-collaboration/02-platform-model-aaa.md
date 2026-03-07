# 15-02 — Platform Model & AAA: Teams Collaboration

**Feature**: Native Teams + Team Working Memory
**Framework**: Platform Model (Producers / Consumers / Partners) + AAA (Automate / Augment / Amplify)
**Research date**: 2026-03-07

---

## 1. Platform Model Analysis

### 1.1 Who Are the Players?

**Producers**: Every team member who submits a query.

In the team working memory model, the producer role has a dual nature that does not exist in the individual memory model:

1. The user produces a response for themselves (as in the individual case).
2. The user simultaneously **produces shared context** for their teammates. Every query contributes to the team's working memory bucket — enriching the shared pool of topics and investigation threads.

This is the critical structural difference from individual working memory. In the team model, consumption and production happen simultaneously from a single user action. A single query from Sarah not only gets Sarah a better answer; it makes the next query from James more contextually informed.

**Consumers**: All active members of the team.

Every team member benefits from the accumulated context produced by all other team members. The consumer gets:

- Team investigation history surfaced in their responses
- Topic coverage built by teammates they may not have collaborated with directly
- Reduced context-setting time because the team's ongoing project context is pre-loaded

A member who joins an active team mid-project immediately benefits from all prior team memory — the consumer benefit is available from the first query without any warm-up period.

**Partners**:

1. **Tenant Admins**: Create and manage teams, assign members, configure team settings. They are the platform's gateway for team structure. Without tenant admin action, no teams exist.
2. **Auth0 (SSO Provider)**: The `groups` claim sync engine makes Auth0 a structural partner — it can automatically create and populate teams from corporate directory data. Auth0 group membership becomes a production trigger.
3. **Team Members with "Owner" permission** (Phase 2): Team owners can manage team membership without being tenant admins, reducing administrative friction for large organizations.

### 1.2 The Core Transaction

**Primary transaction**: A team member asks a question → receives a response that is informed by both their individual context AND the team's accumulated investigation history.

The transaction improvement is layered:

```
WITHOUT team memory:
James: "What is the regulatory exposure for Acme Inc in Germany?"
→ Response based on knowledge base only; no project context
→ James must re-brief: "We're looking at acquiring Acme; focus is GDPR compliance and NDA structure"
→ 3-5 additional exchanges to reach a useful answer

WITH team memory (Sarah has been investigating Acme for two days):
Team memory: ["Acme Inc", "GDPR exposure", "data processing agreements", "NDA terms", "Germany"]
James: "What is the regulatory exposure for Acme Inc in Germany?"
→ Response already knows: this is an acquisition due diligence context; Sarah's topics are in scope
→ 1-exchange answer that surfaces GDPR, DPA requirements, standard NDA provisions
→ James notices the AI is already calibrated to the project
```

**Efficiency gain**: Team memory eliminates the project context re-briefing step for all team members after the first 2–3 sessions on a project. For a 5-person team doing 10 queries/day collectively, this saves approximately 15–30 minutes of context-building overhead daily.

### 1.3 Transaction Dynamics

The team memory model creates a **positive feedback loop** that individual memory cannot:

```
Team member queries → topics added to team bucket →
next team member gets enriched context → gets better answer faster →
continued usage → richer team bucket →
higher team-wide first-query utility rate
```

The loop has an important property: the feedback is **cross-user**. Individual working memory only compounds within one user's sessions. Team memory compounds across all team members — the more diverse the team's queries, the richer and more useful the shared context becomes.

**Breakeven point**: A team achieves net-positive team memory value (more value from shared context than the 150 tokens of overhead) after approximately 3–5 collective sessions across team members. For active project teams, this threshold is typically reached in the first week.

### 1.4 Network Effects Created by Team Memory

The platform model implications of team memory extend beyond the individual feature:

**Same-team compounding**: As analyzed above — intra-team cross-user signal creates a feedback loop not possible in individual-only architectures.

**Tenant retention moat**: Team working memory accumulates project context over time. A team that has been using mingai on a 3-month project has built up substantial shared context. Switching to a competitor resets this entirely. The switching cost is now **collective** — it affects the entire team, not just one user.

**Team size multiplier**: Each additional team member multiplies the rate of team memory enrichment. A 10-person team accumulates topic coverage ~10x faster than a 1-person team. The value of team memory scales with team size, creating a structural advantage as teams grow.

### 1.5 Platform Score: Before and After

| Dimension                  | Before (Individual Memory Only)  | After (+ Team Memory)                 | Change   |
| -------------------------- | -------------------------------- | ------------------------------------- | -------- |
| Producer quality           | High (individual context)        | Very High (collective context)        | +1       |
| Consumer value             | High (individual)                | Very High (team + individual)         | +1       |
| Partner enablement         | Medium                           | Medium-High (tenant admin teams mgmt) | +0.5     |
| Transaction efficiency     | Very High (individual)           | Very High + team context              | +0.5     |
| Switching cost / moat      | Medium-High (individual profile) | High (collective team memory)         | +1       |
| Cross-user network effects | Low (none)                       | Medium (within-team)                  | +2       |
| **Overall platform score** | **7.0/10**                       | **8.5/10**                            | **+1.5** |

This is the same improvement trajectory predicted in 13-02 §5: "With team memory feature, would reach 8.5/10."

---

## 2. AAA Framework Analysis

### 2.1 Automate — Reduce Operational Costs

| Without Team Memory                                             | With Team Memory                                         | Automation Gain                                      |
| --------------------------------------------------------------- | -------------------------------------------------------- | ---------------------------------------------------- |
| Each team member re-briefs AI about project context per session | Team memory accumulates project context automatically    | Zero-effort shared project briefing                  |
| Team lead must manually update shared project notes             | Investigation topics captured from normal query activity | Eliminates manual knowledge curation role            |
| New team members require extensive onboarding to AI context     | New members inherit team memory immediately on joining   | Eliminates onboarding-to-AI lag                      |
| Auth0 group admins must separately configure AI access teams    | Group claims sync creates platform teams automatically   | Eliminates duplicate team management for SSO tenants |

**Key automation insight**: The team memory feature converts knowledge curation from an explicit, effort-consuming task into an emergent property of normal team usage. Nobody has to "update the team's AI briefing document" — it happens as a side effect of the team using the platform normally.

**Automate Score: 8/10**
Justification: Strong automation of context-building and team management. Deduction: team structure still requires initial setup by tenant admin for non-SSO tenants; Auth0 group sync handles this automatically for SSO tenants.

### 2.2 Augment — Reduce Decision-Making Costs

Team memory augments decision quality at the team level in a way that individual memory cannot:

1. **Collective investigation context**: When James asks about a regulatory question, the response is informed not just by the knowledge base, but by what Sarah and the team have already been investigating — surfacing connections that James may not have thought to ask about.
2. **De-duplicated research effort**: The AI can recognize that a team member is asking a question their colleague already explored and frame the response accordingly ("Your team has been looking at Acme's GDPR exposure — here is the specific DPA structure...").
3. **Project-aware depth**: With team memory, the AI knows the project has been active for several sessions and can modulate response depth accordingly — less foundational explanation, more project-specific analysis.
4. **Consistency across team responses**: Because all team members share the same team context layer, the AI produces coherent responses across the team. A compliance officer and a finance analyst asking related questions get responses that are consistent with each other, not contradictory.

**Augment Score: 7/10**
Justification: Meaningful augmentation of team-level decision quality. Deduction: augmentation is limited by topic extraction quality (keyword-based, not semantic). The AI cannot yet infer "this query relates to the Acme project" — it must see exact keyword matches in team memory. Semantic gap limits how deep the augmentation actually goes.

### 2.3 Amplify — Reduce Expertise Costs

The amplification story for team memory is about **collective expertise surfacing**:

**Problem it solves**: In a team of five, one person has deep expertise on a topic they investigated last week. The remaining four are unaware this investigation happened. When they need to ask related questions, they start from scratch — the collective team expertise is invisible to the AI and to each other.

With team memory:

- Senior analyst's prior investigation topics are represented in team memory
- Junior analysts asking related questions automatically benefit from the surface-level coverage the senior's queries have contributed
- The AI can frame responses as building on known team context rather than starting from first principles

**Scale dimension**: For a knowledge-intensive team (legal, finance, strategy), the amplification compound works across the full team's query history. A team that has done 500 queries collectively across a 3-week project has built substantial shared context that each member can leverage — the equivalent of a shared briefing book that writes itself.

**Amplify Score: 7/10**
Justification: Real amplification of collective expertise. Deduction: team memory is working memory (7-day TTL, keyword-extracted), not structured knowledge. It amplifies the recent investigation surface, not deep domain expertise. The amplification ceiling is the quality and recency of team queries, not the depth of any individual's expertise.

---

## 3. Network Effects Analysis

Does team working memory create genuine network effects?

### 3.1 Within-Team Network Effect

**Verdict: Yes — strong within-team network effect.**

The mechanism:

- More team members → broader coverage of project topics in team memory
- Broader topic coverage → more useful context injection for each member
- More useful context → higher usage rate
- Higher usage rate → richer team memory → stronger effect

This is a genuine **same-side network effect** within the team: more team members using the platform increases the value of the platform for all existing team members.

**Strength**: Medium. The effect is real and compounds, but the team size is bounded (most project teams are 3–15 people). This is not a marketplace-scale network effect — it is a team-scale effect.

### 3.2 Cross-Team Network Effect

**Verdict: Weak — no meaningful cross-team network effect in Phase 1.**

Team memories are isolated by `{tenant_id}:team_memory:{team_id}`. One team's investigation history does not benefit another team. This is correct privacy behavior, but it means there is no cross-team network effect.

A cross-team signal would require aggregating topic coverage across teams (anonymized, at the tenant level) — a potential Phase 3+ feature. For example, "The Finance team and the Legal team are both investigating Acme Inc" could be surfaced to both teams.

### 3.3 Cross-Tenant Network Effect

**Verdict: None — by design.**

Tenant isolation is non-negotiable. No cross-tenant signal aggregation.

### 3.4 Auth0 Sync as Network Effect

Auth0 group sync is interesting as a structural network effect mechanism:

- As more tenants enable Auth0 group sync, the platform learns which group patterns are noise (all-company, VPN-users) vs. signal (project teams, working groups)
- A team noise-filter trained on cross-tenant group naming patterns could improve the sync quality for all tenants
- This is a potential platform-level network effect: more sync data → better noise filtering → better team creation → more value for all tenants with SSO

**Verdict: Weak latent network effect** — exists as a possibility but requires deliberate implementation of cross-tenant learning infrastructure.

---

## 4. Phase Model

### Phase 1 — Foundation (MVP)

**Scope**: Manual team management + team working memory core

- Tenant admin creates teams, assigns members via Tenant Admin UI
- `TeamWorkingMemoryService` — Redis-backed, 7-day TTL, topic merge, query attribution
- Layer 4b in `SystemPromptBuilder` — team memory injection
- Active team selector in chat UI (per-session, user-selects)
- GDPR team memory clear (user erasure + tenant delete)
- No Auth0 sync (manual teams only)

**Value delivery**: Teams created by tenant admin immediately get team working memory. After 3–5 sessions, team memory provides measurable context enrichment.

### Phase 2 — Automation

**Scope**: Auth0 group sync + team management improvements

- Auth0 `groups` claim sync on login: auto-create and update teams from IdP groups
- Group noise filter: allow-list/blocklist for group name patterns (configurable per tenant)
- Persistent active team: remember user's last active team across sessions
- Team memory visibility panel: show team members the current team memory contents
- Team ownership role: team owners can manage membership without being tenant admins

**Value delivery**: SSO tenants can create teams without any manual work. Auth0 sync makes teams a zero-friction feature for large enterprises with mature IAM.

### Phase 3 — Intelligence

**Scope**: Cross-team signals + advanced team memory features

- Team memory history timeline: see how team memory evolved over a project's lifecycle
- Shared team memory notes (persistent, not TTL-bounded, curated by team)
- Cross-team topic overlap detection within a tenant (opt-in)
- Team memory export for project archives or compliance

---

## 5. AAA Score Summary

| Dimension       | Score      | Key Driver                                                       |
| --------------- | ---------- | ---------------------------------------------------------------- |
| Automate        | 8/10       | Zero-effort shared project briefing; auto-sync from Auth0 groups |
| Augment         | 7/10       | Collective team investigation context in every query             |
| Amplify         | 7/10       | Senior expertise surface accessible to all team members          |
| **Overall AAA** | **7.3/10** | Limited by keyword extraction quality                            |

| Network Behavior    | Before     | After      | Gap                                                                    |
| ------------------- | ---------- | ---------- | ---------------------------------------------------------------------- |
| Accessibility       | 9/10       | 9/10       | No change — team memory doesn't change knowledge base access           |
| Engagement          | 8/10       | 8.5/10     | Team recognition effect slightly increases engagement                  |
| Personalization     | 9/10       | 9/10       | Team memory is additive; individual personalization unchanged          |
| Connection          | 7/10       | 7.5/10     | Auth0 sync adds a group membership connection                          |
| Collaboration       | 3/10       | **7/10**   | Primary target — this is the feature's primary network behavior impact |
| **Overall Network** | **7.2/10** | **8.2/10** | +1.0 gain, driven almost entirely by Collaboration                     |
