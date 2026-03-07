# 16 — Teams Collaboration User Flows

**Feature**: Native Teams + Team Working Memory
**Analysis refs**: 15-01 through 15-05
**Plan ref**: 10-teams-collaboration-plan.md

---

## Overview

Eight primary flows covering the complete teams collaboration lifecycle. Flows cover team creation, Auth0 sync, team working memory usage, active team selection, tenant admin management, and GDPR.

---

## Flow 1: Tenant Admin Creates a Team (Manual)

**Actor**: Tenant admin
**Location**: Tenant Admin > Teams

```
Admin navigates to Tenant Admin > Teams
  │
  ├─ Current state: no teams exist (new tenant)
  │
  ├─ Clicks "+ Create Team"
  │    ├─ Form: Name [Q4 Finance Review], Description [Team investigating Q4 budget variance]
  │    └─ [Save]
  │
  ├─ POST /admin/teams → team created (source: manual)
  │
  ├─ Admin clicks team → Add Members
  │    ├─ Search users: type "Sarah" → results: Sarah K. (Finance Analyst), Sarah T. (IT)
  │    ├─ Select Sarah K. → POST /admin/teams/{id}/members
  │    └─ Add 3 more members → team has 4 members
  │
  └─ Team ready. Next login for any member → active_team available in chat.
```

---

## Flow 2: Auth0 Group Sync (First Login)

**Actor**: System (triggered by user login)
**Trigger**: User logs in for first time; JWT contains `groups` claim

```
User (Sarah K.) logs into mingai via Auth0 (Azure AD SSO)
  │
  ├─ Auth0 JWT: { sub: "auth0|...", email: "sarah@company.com",
  │               groups: ["Finance", "Q4-Budget-Team", "All-Staff", "VPN-Users"] }
  │
  ├─ Login handler checks groups claim
  │    │
  │    ├─ "Finance" → no existing team with auth0_group_name "Finance"
  │    │    └─ Auto-create: tenant_teams { name: "Finance", source: auth0_sync, auth0_group_name: "Finance" }
  │    │
  │    ├─ "Q4-Budget-Team" → no existing team
  │    │    └─ Auto-create: tenant_teams { name: "Q4-Budget-Team", source: auth0_sync }
  │    │
  │    ├─ "All-Staff" → auto-created (tenant admin can archive this noise team later)
  │    │
  │    └─ "VPN-Users" → auto-created (noise — tenant admin can archive)
  │
  ├─ team_memberships: Sarah added to all 4 auto-created teams
  │
  └─ Login complete. Tenant Admin > Teams now shows 4 teams with [Synced] badge.
       └─ Tenant admin can: archive noise teams, merge teams, convert to manual
```

---

## Flow 3: Team Working Memory Accumulates

**Actor**: System (triggered by team member queries)
**Trigger**: Multiple team members query with same active team

```
[Monday 9am] Sarah K. (active team: Q4-Budget-Team) asks:
  "How do I calculate Q4 variance against the AOP?"
  │
  └─ Team memory updated: { topics: ["Q4", "variance", "AOP"],
                             queries: ["How do I calculate Q4 variance against the AOP?
                                        — Sarah K."] }

[Monday 11am] James L. (active team: Q4-Budget-Team) asks:
  "What's the deadline for Q4 close?"
  │
  └─ Team memory updated: { topics: ["Q4", "variance", "AOP", "deadline", "close"],
                             queries: ["What's the deadline for Q4 close? — James L.",
                                       "How do I calculate Q4 variance against the AOP? — Sarah K."] }

[Monday 2pm] Rachel T. (active team: Q4-Budget-Team) asks:
  "What reporting template should we use?"
  │
  ├─ Prompt Layer 4b includes team memory:
  │    "Team working context (Q4-Budget-Team):
  │     Recent topics: Q4, variance, AOP, deadline, close
  │     Recent queries: What's the deadline for Q4 close? — James L.;
  │                     How do I calculate Q4 variance against the AOP? — Sarah K."
  │
  └─ LLM response: "For your Q4 close reporting, the standard template that covers AOP
                    variance analysis would be..." (proactively bridges to team's context)
```

---

## Flow 4: Active Team Selection in Chat

**Actor**: End user
**Location**: Chat interface

```
User (Sarah K.) opens chat with Finance agent
  │
  ├─ Chat header shows: [Active team: Q4-Budget-Team ▼]
  │    (default = last used team; first time = most recently created team)
  │
  ├─[Sarah wants to switch context to individual work]
  │    ├─ Clicks team dropdown → options: [No team context] [Finance] [Q4-Budget-Team] [All-Staff]
  │    ├─ Selects "No team context"
  │    └─ Session updated: active_team = null
  │         └─ Layer 4b omitted from next query's prompt
  │
  └─[Sarah switches to Finance team]
       ├─ Selects "Finance" from dropdown
       └─ Session updated: active_team = Finance team ID
            └─ Next query uses Finance team memory (different topics from Q4-Budget-Team)
```

---

## Flow 5: Team Memory in Personalized Response

**Actor**: End user (new team member)
**Trigger**: New team member asks question; benefits from existing team memory

```
[Week 1] David P. joins Q4-Budget-Team (was on leave, no prior context)
  │
  ├─ David opens chat with Finance agent, active team: Q4-Budget-Team
  │
  ├─ David asks: "What's the status of the Q4 close?"
  │
  ├─ Prompt includes:
  │    Layer 4a (David's individual memory): empty (new team member)
  │    Layer 4b (Q4-Budget-Team memory): { topics: [Q4, variance, AOP, deadline, close],
  │                                         queries: [team's accumulated context] }
  │
  └─ LLM response: "Based on your team's recent work on Q4 variance and AOP reporting,
                    here's the current status of Q4 close..." (as if David was there from the start)
```

**User experience**: New or returning team members get up to speed instantly. Zero manual briefing.

---

## Flow 6: Tenant Admin Manages Teams

**Actor**: Tenant admin
**Location**: Tenant Admin > Teams

```
Admin views teams list:
  │
  │  | Name              | Members | Source   | Memory Age | Actions         |
  │  |-------------------|---------|----------|------------|-----------------|
  │  | Q4-Budget-Team    | 4       | Manual   | 3 days     | Edit / Archive  |
  │  | Finance           | 12      | Synced   | 1 day      | Edit / Archive  |
  │  | All-Staff         | 150     | Synced   | 1 hour     | Edit / Archive  |
  │  | VPN-Users         | 89      | Synced   | 1 hour     | Edit / Archive  |
  │
  ├─[Admin archives "VPN-Users" and "All-Staff"] → teams still exist, not visible in chat UI
  │    └─ members removed from team memory injection for these teams
  │
  ├─[Admin clicks "Finance" team]
  │    ├─ Members list: 12 members
  │    ├─ Memory preview: topics, recent queries
  │    ├─ [Clear team memory] button → clears Redis bucket
  │    └─ [Convert to manual] → source: manual, no longer synced from Auth0
  │
  └─[Admin configures Auth0 sync filter]
       └─ Settings > Teams > Auto-sync groups: [Enabled] Filter: exclude groups containing
          "VPN", "WiFi", "All-" → prevents noise group auto-creation
```

---

## Flow 7: GDPR — User Erasure and Team Memory

**Actor**: End user (exercises right to erasure)
**Trigger**: User submits erasure request via Settings > Privacy > [Clear all data]

```
User: Settings > Privacy > [Clear all learning data]
  │
  ├─ Warning: "This will permanently delete your learned profile, memory notes,
  │            working memory, and your contributions to shared team memories.
  │            Your team members will also lose shared context that included your queries."
  │
  ├─[Confirm]
  │    ├─ clear_profile_data(user_id, tenant_id)
  │    │    ├─ Delete user_profiles row
  │    │    ├─ Delete all memory_notes rows
  │    │    ├─ Delete all profile_learning_events rows
  │    │    ├─ Delete Redis: profile cache, individual working memory, query counter
  │    │    └─ For each team in team_memberships:
  │    │         └─ DEL Redis: {tenant_id}:team_memory:{team_id}  ← team memory cleared
  │    │
  │    └─ Confirmation: "All data cleared. Team context for 3 teams has also been reset."
  │
  └─ Team admin notified (optional): "Q4-Budget-Team shared context was reset due to a
                                       member's privacy request"
```

---

## Flow 8: Auth0 Group Membership Change

**Actor**: System (triggered by login after group change)
**Trigger**: User's Azure AD group membership changes (propagated via Auth0)

```
[Context] Sarah K. was in Q4-Budget-Team (auth0_sync). She moves to a new project.
  IT admin removes her from "Q4-Budget-Team" Azure AD group.

[Next login] Sarah logs in via Auth0
  │
  ├─ JWT groups: ["Finance", "All-Staff", "H1-Planning-Team"]  ← Q4-Budget-Team absent
  │
  ├─ Login handler compares JWT groups with existing auth0_sync memberships:
  │    ├─ "Q4-Budget-Team" was in memberships (source: auth0_sync) → remove membership
  │    └─ "H1-Planning-Team" not found → auto-create team + add Sarah
  │
  └─ Sarah's active_team session is reset if it was Q4-Budget-Team
       └─ Next chat: active team defaults to most recently active valid team
```

---

## Edge Cases

### EC-1: User in No Teams

Active team selector shows "No team context". Layer 4b silently skipped. No error.

### EC-2: Team Deleted While User Has It Active

Next query: active_team_id not found → gracefully fall back to "no team context". Toast: "Your active team was removed. Team context cleared for this session."

### EC-3: Team Memory Exceeds Token Budget

Team memory formatted to 150 token limit. If topics list is very long, truncate to top 10 topics. Recent queries truncated to last 3 with 100-char limit each (same as individual working memory truncation).

### EC-4: Two Teams Have Same Auth0 Group Name (Edge Case)

If tenant admin manually renamed an auth0_sync team, the `auth0_group_name` field still holds the original name. On next sync, the original group name matches the existing team → updates membership correctly, doesn't create duplicate.
