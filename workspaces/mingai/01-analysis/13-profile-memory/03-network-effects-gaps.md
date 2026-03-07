# 13-03 — Network Effects Deep Dive & Feature Gaps

**Feature**: Profile & Memory System
**Focus**: How each sub-feature drives network behaviors; what is missing

---

## 1. Accessibility Analysis (Friction to Complete a Transaction)

### Current State

The primary transaction = user asks question → gets useful answer in first exchange.

Profile/memory reduces friction at multiple points:

- **Pre-query**: User doesn't need to set context (profile pre-loaded)
- **Query interpretation**: LLM has expertise level and communication style → interprets query at right depth
- **Response delivery**: Already calibrated to user's preferred format (concise vs. detailed)

### Accessibility Score: 9/10

Key metric: **First-Exchange Utility Rate** (queries answered usefully in one exchange).

Without profile: ~40% (user must clarify role/context in follow-ups)
With full profile stack: ~75–85% estimated (based on aihub2 architecture logic)

### Gap

Working memory topic extraction is keyword-only (no semantic understanding). "AWS bonus" and "annual wage supplement" are both common ways to refer to the same thing — they would appear as separate topics. Semantic deduplication would improve accessibility further.

---

## 2. Engagement Analysis (Information Useful for Completing Transactions)

### Current State: Working Memory

- Recent topics injected for returning users (>1 hour gap)
- Last 3 queries shown as "Previous questions"
- "Returning user from earlier session" signal

### Engagement Drivers

1. **Recognition effect**: User feels the AI "knows them" — psychologically sticky
2. **Topic bridging**: AI can proactively surface related prior work ("You asked about AWS last time — this connects to...")
3. **Implicit reminders**: Working memory can surface incomplete tasks from prior sessions

### Engagement Score: 8/10

### Gaps

**Gap 1: No proactive memory surfacing**
Working memory is included in the prompt but the AI is not instructed to proactively reference it. It relies on the LLM to notice and use the context. Should add explicit instructions in Layer 4 template: "If the user's current question relates to their recent topics, reference the connection."

**Gap 2: 7-day TTL may be too short for weekly users**
A user who queries on Monday and returns the following Tuesday has no working memory continuity. Enterprise knowledge workers often return to investigations 10-14 days later. Recommend configurable TTL (7 days default, 30 days max).

**Gap 3: No conversation linking**
Working memory stores `last_conversation_id` but does not link to the actual conversation content. For returning users, surfacing the last 1-2 messages from the prior conversation would dramatically increase continuity. Currently, only topic keywords are retained.

---

## 3. Personalization Analysis (Information Curated for Intended Use)

### Current State: Full Profile Stack

Four layers of personalization create the richest profile of any enterprise RAG platform:

| Layer            | Signal Type                           | Update Frequency | Cost         |
| ---------------- | ------------------------------------- | ---------------- | ------------ |
| Org Context      | Static identity (role, dept, country) | On login         | $0           |
| Profile Learning | Behavioral preferences                | Every 10 queries | ~$0.01/cycle |
| Memory Notes     | Explicit facts                        | On demand        | $0           |
| Working Memory   | Session context                       | Every query      | $0           |

### Personalization Score: 9/10

### Gaps

**Gap 1: No agent-scoped personalization**
In aihub2, profile/memory is global across all agents. In mingai's multi-agent architecture, this creates problems:

- User's HR-agent profile bleeds into Finance-agent context (irrelevant signal)
- Memory note "I prefer conservative risk thresholds" means nothing to the HR agent
- Solution: Introduce `agent_id` scope for profile learning and working memory

**Gap 2: No confidence decay on profile attributes**
Once an attribute is learned (e.g., `technical_level: beginner`), it never decays. A user who grows from beginner to expert over 6 months will have a stale profile. Need time-weighted recency in merge strategy.

**Gap 3: No negative preference learning**
The system learns what users like but not what they dislike. "Never give me tables" or "don't explain basics" are preferences that must be explicit memory notes — they can't be auto-extracted. Could extend auto-extraction prompt to include `negative_preferences` field.

**Gap 4: No multi-language profile**
`communication_style` includes `formal/casual` but no language preference detection. For multinational tenants, a user querying in French should be profiled as a French speaker. Working memory topic extraction is English-only (stop words list is English).

---

## 4. Connection Analysis (Information Sources Connected to Platform)

### Current State

One-way connection: Azure AD → Org Context → System Prompt

Data flow:

```
Login event → Azure AD sync → user_profiles container → org_context.py → Layer 2
```

### Connection Score: 7/10

### Gaps

**Gap 1: One-way connection only**
Platform learns from Azure AD but never writes back. Potential two-way signals:

- User's inferred expertise level → could update Workday/HRMS "skills" profile
- User's frequent topics → could trigger learning path recommendations in LMS
- High-engagement areas → could inform content management system priorities

This is a Phase 3+ feature, but architecturally it would create a powerful two-way data connection that no competitor offers.

**Gap 2: No real-time org context refresh**
If user's job title changes mid-day (promotion, role change), org context is stale until next login. For HRIS events that are critical (e.g., employee becomes manager), this latency matters.

**Gap 3: No external data source connections for memory**
Memory notes are manually entered or auto-extracted from conversation. There is no connector to:

- User's calendar (upcoming meetings → working memory context)
- User's email subject lines (active projects → topic enrichment)
- Project management tools (Jira/Asana issues → ongoing tasks)

These would dramatically enrich working memory without user effort.

---

## 5. Collaboration Analysis (Producers and Consumers Work Together)

### Current State: NONE

Zero collaboration features. Memory is 100% individual.

### Collaboration Score: 3/10

### Gap 1: No Team-Level Working Memory (Critical)

**Problem**: Teams working on the same project fragment their AI context. Each member must independently build their own context — no shared knowledge state.

**Solution**: Team Memory — a shared Redis bucket scoped to `{tenant_id}:{team_id}` that stores:

- Shared topics the team has investigated
- Team-level memory notes (set by anyone, visible to all)
- Shared working documents being researched

**Implementation path**: Extend `WorkingMemoryService` with `team_memory` scope alongside `user_memory` scope. Team ID sourced from Azure AD group membership.

### Gap 2: No Collaborative Memory Note Editing

If a manager creates a memory note relevant to their team ("our department uses Q4 as primary planning period"), all team members should benefit from it. Currently, notes are user-siloed.

### Gap 3: No Memory Sharing Between Sessions/Users

In consulting scenarios, a consultant may hand off a research thread to a colleague. There is no way to share memory context between users. A "share my memory context" feature would enable thread handoff.

---

## 6. Gap Priority Matrix

| Gap                                  | Network Behavior | Impact               | Effort    | Priority |
| ------------------------------------ | ---------------- | -------------------- | --------- | -------- |
| Agent-scoped memory                  | Personalization  | High                 | Medium    | **P1**   |
| Team-level working memory            | Collaboration    | Very High            | Medium    | **P1**   |
| Confidence decay on profile          | Personalization  | Medium               | Low       | **P2**   |
| Proactive memory surfacing in prompt | Engagement       | High                 | Very Low  | **P2**   |
| Configurable working memory TTL      | Engagement       | Medium               | Very Low  | **P2**   |
| Semantic topic deduplication         | Accessibility    | Medium               | Medium    | **P3**   |
| Negative preference learning         | Personalization  | Medium               | Medium    | **P3**   |
| Calendar/email context connection    | Connection       | High                 | High      | **P4**   |
| Two-way identity platform connection | Connection       | Very High            | Very High | **P5**   |
| Multi-language profile               | Personalization  | Low (Tier 1 tenants) | High      | **P5**   |

---

## 7. Feature Roadmap Implications

### Phase 1 (MVP — Carry from aihub2)

- Profile learning (auto-extracted every 10 queries)
- Working memory (Redis, 7-day TTL)
- Memory notes (user-directed + auto-extracted)
- Org context (Azure AD)
- GDPR controls (view/edit/delete/export)
- Multi-tenant isolation (all keys scoped by tenant_id)

### Phase 2 (Differentiation)

- Agent-scoped memory (P1)
- Team-level working memory (P1)
- Proactive memory surfacing in prompt template (P2)
- Configurable TTL (P2)
- Profile confidence decay (P2)

### Phase 3 (Moat Building)

- Negative preference learning (P3)
- Semantic topic deduplication (P3)
- Memory thread sharing (P3)

### Phase 4+ (Platform Connection)

- Calendar/email enrichment (P4)
- Two-way identity platform integration (P5)
