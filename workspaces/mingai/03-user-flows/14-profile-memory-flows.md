# 14 — Profile & Memory User Flows

**Feature**: User Profile Learning + Working Memory + Memory Notes + Org Context
**Analysis refs**: 13-01 through 13-05
**Plan ref**: 08-profile-memory-plan.md

---

## Overview

Nine primary user flows covering the complete profile/memory lifecycle. Flows are organized by user role (end user, tenant admin) and by feature (profile learning, memory notes, working memory, org context, GDPR).

---

## Flow 1: First-Time Profile Transparency Disclosure

**Actor**: End user (new to platform)
**Trigger**: First login or first time navigating to Settings > Privacy

```
User navigates to Settings > Privacy
  │
  ├─[Profile Learning card visible, status: ON by default]
  │
  └─[User clicks "How does this work?"]
       │
       └─ PrivacyDisclosureDialog opens
            │
            ├─ Shows: "The AI learns from your conversations to personalize responses.
            │          This is based on legitimate interest — improving your work experience.
            │          You can disable or clear this data at any time."
            ├─ Shows: "What is collected: topics, expertise level, communication preferences"
            │
            ├─[User clicks "Got it"] → disclosure_shown_at recorded (audit, not consent) → dialog closes
            │
            └─[User clicks "Disable"] → profile_learning_enabled = false → dialog closes → toggle OFF
```

**State stored**:

- `user_profiles.profile_learning_enabled`
- `profile_learning_events.disclosure_shown_at` (audit record of disclosure)

**Privacy principle**: Opt-out default (enabled by default) under Article 6(1)(f) Legitimate Interest. Users have the right to object via the toggle at any time (Article 21). First-time disclosure is informational, not a consent gate.

---

## Flow 2: Automatic Profile Learning (Background)

**Actor**: System (triggered by user query activity)
**Trigger**: User reaches 10 queries in a session or across sessions

```
User submits query #10
  │
  ├─ Chat response delivered normally (no latency impact)
  │
  └─ Background: on_query_completed() fires
       │
       ├─ Increment Redis counter: {tenant_id}:profile_learning:query_count:{user_id}
       │    (Phase 1: global counter across all agents)
       │
       ├─[Counter < 10] → no action
       │
       └─[Counter = 10] → reset counter → launch async learning job
            │
            ├─ Check: profile_learning_enabled = true?
            │    └─[false] → abort, no update
            │
            ├─ Fetch last 10 conversations from DB
            │
            ├─ Call intent LLM model with EXTRACTION_PROMPT
            │    └─ Extracts: interests, expertise_areas, technical_level,
            │                 communication_style, common_tasks, memory_notes
            │
            ├─ Merge with existing profile (additive, not destructive)
            │    ├─ Arrays: union with deduplication, capped at limits
            │    ├─ technical_level: weighted average with recency bias
            │    └─ communication_style: most recent wins
            │
            ├─ Store profile_learning_event (audit trail)
            │
            └─ Invalidate L1 and L2 caches for this user
```

**User experience**: Invisible. No notification. Profile silently improves.

**Error handling**: Any failure in the background job is logged and skipped. Next trigger at query #20.

---

## Flow 3: Personalized Chat Response (Profile Active)

**Actor**: End user (returning, profile populated)
**Trigger**: User submits a chat query to an agent

```
User types: "What is the Q4 budget process?"
  │
  ├─ Parallel async fetch:
  │    ├─ Org context: job_title=Finance Analyst, dept=Finance, country=Singapore
  │    ├─ Profile: technical_level=intermediate, communication_style=concise
  │    │           interests=[budget, variance analysis, FP&A]
  │    │           memory_notes=["I prefer answers in bullet points"]
  │    └─ Working memory: topics=[Q4, budget, variance], last_query="Q4 actual vs plan"
  │
  ├─ Prompt assembled (6 layers):
  │    Layer 2: "Finance Analyst in Singapore Finance department..."
  │    Layer 3: "User is intermediate. Prefers concise responses.
  │              Memory notes: I prefer answers in bullet points"
  │    Layer 4: "Returning user. Recent topics: Q4, budget, variance.
  │              Previous question: Q4 actual vs plan"
  │    Layer 5: [RAG retrieved documents about budget process]
  │    Layer 6: [Tenant glossary: Q4 = October-December fiscal quarter]
  │
  ├─ LLM call → streams response in bullets, Singapore-specific, intermediate depth
  │
  ├─ SSE event: profile_context_used = true → ProfileIndicator shown in UI
  │
  └─ Background: working memory updated with new topics [Q4, budget, process]
```

**User experience**: Response arrives calibrated to their role, preferences, and session context. ProfileIndicator shows "Personalized" badge.

---

## Flow 4: Explicit Memory Note via Chat

**Actor**: End user
**Trigger**: User types a "remember" command in chat

```
User types: "Remember that I always need to include IRAS implications for Singapore users"
  │
  ├─ Chat router: regex match on "remember that..."
  │
  ├─[Match found] → fast path (no LLM call)
  │    │
  │    ├─ Extract fact: "always need to include IRAS implications for Singapore users"
  │    │
  │    ├─ Call add_memory_note(user_id, tenant_id, content, source="user_directed")
  │    │    └─ If 15-note limit reached → oldest note pruned
  │    │
  │    └─ Return SSE memory_saved event
  │         └─ Frontend: show "Memory saved" toast in chat
  │
  └─[No match] → normal LLM pipeline
```

**State stored**: New row in `memory_notes` table.

**Immediate effect**: Note appears in next query's system prompt (Layer 3, top 5 newest).

---

## Flow 5: View and Manage Memory Notes

**Actor**: End user
**Location**: Settings > Privacy > Memory card

```
User navigates to Settings > Privacy
  │
  ├─ Memory card renders with all notes (newest first)
  │    ├─ Note 1: "Always include IRAS implications..." [saved by you] [Delete] [2026-03-01]
  │    ├─ Note 2: "Prefers concise bullet points" [auto-extracted] [Delete] [2026-02-28]
  │    └─ [Clear All] button
  │
  ├─[User clicks Delete on Note 1]
  │    ├─ DELETE /me/memory/{note_id}
  │    ├─ Note removed from DB
  │    └─ UI updates (note disappears)
  │
  ├─[User clicks Clear All]
  │    ├─ Confirmation dialog: "Delete all 2 memory notes? This cannot be undone."
  │    ├─[Confirm] → DELETE /me/memory → all notes removed
  │    └─[Cancel] → no action
  │
  └─[Notes list is empty]
       └─ Empty state: "No memories saved. Say 'remember that...' in a chat to save a fact."
            └─ CTA: "Go to Chat →"
```

---

## Flow 6: Working Memory Session Continuity

**Actor**: End user (returning after >1 hour gap)
**Trigger**: User returns to chat after a gap

Note: working memory is agent-scoped. Returning user continuity applies within the same agent. Switching agents starts a fresh session context for that agent.

```
[Day 1, 10am] User asks 3 questions about "Q4 budget variance"
  └─ Working memory: {topics: [Q4, budget, variance], queries: [...], updated_at: 10am}

[Day 1, 3pm] User opens a new chat with the **Finance agent** (same agent as Day 1 morning)
  │
  ├─ Prompt assembled
  │    ├─ Layer 4 (returning user, gap > 1 hour):
  │    │    "Returning user from earlier session
  │    │     Recent topics: Q4, budget, variance
  │    │     Previous questions: How do I calculate Q4 variance?; What counts as Q4?"
  │    └─ [other layers...]
  │
  └─ User asks: "What about the reporting template?"
       └─ LLM response: "For your Q4 variance reporting, the standard template includes..."
            (Proactively bridges current question to prior Q4 context)
```

**Continuity rules**:

- Gap < 1 hour: No "returning user" signal. Only last query shown.
- Gap > 1 hour: "Returning user" signal + last 2 queries shown.
- Gap > 7 days: Working memory expired. Blank slate (fresh session).

---

## Flow 7: GDPR Data Management (Clear + Export)

**Actor**: End user
**Trigger**: User wants to exercise data rights

### 7a: Clear All Profile Data

```
User: Settings > Privacy > [Clear all learning data]
  │
  ├─ Warning: "This will permanently delete your learned profile, all memory notes,
  │            and working memory. Your org context from your company directory will
  │            not be affected."
  │
  ├─[Confirm]
  │    ├─ clear_profile_data(user_id, tenant_id)
  │    │    ├─ Delete user_profiles row (or reset to defaults)
  │    │    ├─ Delete all memory_notes rows
  │    │    ├─ Delete all profile_learning_events rows
  │    │    ├─ Delete Redis: profile cache, working memory, query counter
  │    │    └─ Invalidate L1 in-memory cache
  │    │
  │    └─ Confirmation toast: "All profile data cleared"
  │
  └─[Cancel] → no action
```

### 7b: Export Profile Data

```
User: Settings > Privacy > [Export my data]
  │
  ├─ export_profile_data(user_id, tenant_id)
  │    ├─ Collects: technical_level, communication_style, interests, expertise_areas,
  │    │            common_tasks, memory_notes (all, with source + timestamp),
  │    │            profile_learning_events (audit trail)
  │    └─ Returns JSON file
  │
  └─ Browser downloads: profile_export_{timestamp}.json
```

---

## Flow 8: Tenant Admin Memory Policy Configuration

**Actor**: Tenant admin
**Location**: Tenant Admin > Settings > Memory Policy

```
Tenant admin navigates to Settings > Memory Policy
  │
  ├─ Current settings displayed:
  │    ├─ Profile learning: [ON] — enabled for all users
  │    ├─ Working memory TTL: [7 days]
  │    ├─ Max memory notes: [15]
  │    ├─ Allow auto-extracted notes: [ON]
  │    └─ Org context: [ON]
  │
  ├─[Admin disables auto-extracted notes]
  │    ├─ PATCH /admin/memory-policy { auto_extract_notes: false }
  │    └─ Auto-extraction skipped for all users in this tenant on next learning cycle
  │
  ├─[Admin changes TTL to 30 days]
  │    ├─ PATCH /admin/memory-policy { working_memory_ttl_days: 30 }
  │    └─ New working memory entries expire in 30 days (existing entries unaffected)
  │
  └─[Admin disables profile learning for all users]
       ├─ PATCH /admin/memory-policy { profile_learning_enabled: false }
       └─ All on_query_completed() calls check tenant policy → skip learning
```

---

## Flow 9: Org Context Personalization with Privacy Control

**Actor**: End user with Azure AD identity
**Trigger**: User wants to disable org context from responses

```
[Normal operation]
User: "What approvals do I need for a software purchase?"
System: [Injects org context: IT Manager, Engineering dept, Singapore]
Response: "As IT Manager approving software purchases in Singapore, you'll need..."

[User wants to disable org context]
User: Settings > Privacy > Work Profile
  │
  ├─ "Use my work profile to personalize responses" [ON → OFF]
  │    └─ PATCH /me/preferences { org_context_enabled: false }
  │
  └─ [Next query] System skips Layer 2 entirely
       Response: "Software purchase approvals typically require..."
                 (Generic, no role/country framing)

[User re-enables, but disables manager info]
User: Settings > Privacy > Work Profile > "Include my manager info" [ON → OFF]
  └─ PATCH /me/preferences { share_manager_info: false }
       └─ Org context still injected, but manager_name excluded
```

---

## Edge Cases

### EC-1: New User with No Profile (Cold Start)

All four memory layers return empty/None on first session. System prompt uses only:

- Agent base prompt
- Platform base
- Domain context (RAG)
- Glossary

No profile-based personalization until at least 10 queries accumulated. Acceptable degradation.

### EC-2: User with SSO but No Org Data Fields

Some SSO providers don't send `department` or `country`. Org context builder handles missing fields gracefully:

- All-null org data → Layer 2 silently skipped
- Partial org data → only populated fields injected

### EC-3: Memory Note Auto-Extraction Returns Low-Quality Notes

If LLM extracts spurious "facts" (e.g., "User asked about budget" — not a personal fact), user can delete these from Settings > Privacy > Memory. No harmful state — just noise.

### EC-4: Token Budget Overflow

If all six layers exceed the configured token budget, truncation priority order:

1. Working memory (first to truncate — lowest information density)
2. Memory notes (truncate oldest first, keep newest 3)
3. Interests (truncate to top 5)
4. Org context (truncate to 200 tokens)
5. Glossary (truncate to 300 tokens)

Domain/RAG context is NEVER truncated by the memory system (handled by RAG pipeline separately).

### EC-5: "Remember That" Matches Too Eagerly

User says: "I want to remember that I left my coffee mug in the office" (personal reminder, not a professional fact).

Current regex: fires on any "remember that". The fact is stored. User can delete it from Settings. No harm.

Future improvement: LLM-based intent classification before storing ("Is this a work-relevant fact to remember?"). Phase 3 enhancement.

### EC-6: Agent Discontinued (Phase 2)

If an agent is deleted, `agent_id`-scoped memory notes have `ON DELETE SET NULL` → they become global notes. This is intentional — user data is preserved even if the agent is removed.
