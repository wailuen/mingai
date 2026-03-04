# Caching UX Flows: User Experience Across Cache States

**Date**: March 4, 2026
**Focus**: How caching affects user and admin experiences
**Status**: UX Design Phase

---

## 1. End User Flows

### Flow EU-C1: Standard Query with Semantic Cache Hit

**Persona**: Knowledge worker (e.g., Finance Analyst)
**Context**: Asking a common policy question that another colleague asked earlier in the day

```
User Types: "How many vacation days do new employees get?"

↓ (System: query embedding generated in 150ms; embedding cache miss)
↓ (System: semantic cache lookup in 15ms; finds "What is the PTO policy for new hires?" with 0.96 similarity)

[Chat UI Response — appears within 250ms]

┌─────────────────────────────────────────────────────────────────────────────┐
│ ⚡ Fast response                                              3h ago · [↺]   │
│ ─────────────────────────────────────────────────────────────────────────── │
│ New employees receive 15 days of paid time off in their first year,         │
│ prorated based on start date. Starting from year 2, the allotment           │
│ increases to 20 days.                                                       │
│                                                                             │
│ **Sources**: [HR Handbook] [Employee Benefits Guide]                        │
│                                                                             │
│ **Confidence**: HIGH (87%) · 2 sources agree                                │
│ ─────────────────────────────────────────────────────────────────────────── │
│ [👍] [👎]                                          [↺ Get fresh answer]     │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key UX Decisions**:

- `⚡ Fast response` label indicates cache-assisted (no LLM call)
- `3h ago` shows when the response was originally generated
- `[↺]` allows user to force a fresh LLM response (breaks cache for this query)
- No jargon: "Fast response" not "Cache hit"

---

### Flow EU-C2: Standard Query with Cache Miss (Live LLM)

**Persona**: Knowledge worker
**Context**: First time this question has been asked on this tenant

```
User Types: "What is the procedure for international travel approval?"

↓ (System: semantic cache miss)
↓ (System: full RAG pipeline: intent→embedding→search→LLM)
↓ (System: streaming SSE response begins)

[Chat UI Response — streaming begins within 1s]

┌─────────────────────────────────────────────────────────────────────────────┐
│ [Progress bar animates: Searching knowledge base... → Generating answer...] │
│                                                                             │
│ 🟢 Live response                                                             │
│ ─────────────────────────────────────────────────────────────────────────── │
│ International travel must be approved 2 weeks in advance. The process      │
│ requires... [streaming text appears here]                                   │
│                                                                             │
│ **Sources**: [Travel Policy 2026] [Finance Guidelines]                      │
│ ─────────────────────────────────────────────────────────────────────────── │
│ [👍] [👎]                                                                    │
└─────────────────────────────────────────────────────────────────────────────┘

[After response: response silently cached for future queries]
```

**Key UX Decisions**:

- `🟢 Live response` indicates real-time LLM generation
- Progress stages shown during pipeline execution
- No `[↺ Get fresh answer]` button — this IS the fresh answer
- Response is silently cached; no user notification needed

---

### Flow EU-C3: User Forces Cache Refresh

**Persona**: Knowledge worker who needs current information
**Context**: Believes the cached response may be outdated (e.g., recent policy update)

```
User sees: ⚡ Fast response | 4h ago | [↺]

User clicks [↺ Get fresh answer]

↓ System: Bypass cache, run full pipeline
↓ System: Invalidate cached entry after new response stored

[Chat UI]

┌─────────────────────────────────────────────────────────────────────────────┐
│ ♻️ Refreshed response                                        Just now        │
│ ─────────────────────────────────────────────────────────────────────────── │
│ [Fresh LLM response content...]                                             │
│ ─────────────────────────────────────────────────────────────────────────── │
│ The previous cached answer has been updated.                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Caching Behavior**:

- Force-refresh query bypasses semantic cache
- New response replaces old cached response (cache write-through)
- If user gives thumbs-down → same force-refresh behavior triggered automatically

---

### Flow EU-C4: Real-Time Data Query (Bloomberg Intelligence Agent)

**Persona**: Finance analyst checking market data
**Context**: Query that requires live Bloomberg data via A2A agent

```
User Types: "What is Apple's current stock price?"

↓ (System: intent detection identifies requires_real_time = true)
↓ (System: semantic cache SKIPPED for real-time query)
↓ (System: Bloomberg Intelligence Agent invoked via A2A; result cached for 30 seconds)

[Chat UI]

┌─────────────────────────────────────────────────────────────────────────────┐
│ 🟡 Live data                                        as of 14:32:15 EST      │
│ ─────────────────────────────────────────────────────────────────────────── │
│ Apple Inc. (AAPL) is currently trading at $189.47, up 1.2% today.          │
│                                                                             │
│ **Source**: Bloomberg Terminal (live feed)                                  │
│ ─────────────────────────────────────────────────────────────────────────── │
│ ⚠️ Market data refreshes every 30 seconds                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key UX Decisions**:

- `🟡 Live data` distinct from `🟢 Live response` — signifies real-time feed
- Exact timestamp shown for financial data (required by compliance)
- Refresh frequency disclosed to user
- Semantic cache explicitly bypassed for this query category

---

### Flow EU-C5: Thumbs-Down Feedback on Cached Response

**Persona**: Knowledge worker who receives incorrect cached response
**Context**: Cached response contains outdated or incorrect information

```
User sees: ⚡ Fast response | 2h ago | [↺]
User clicks: [👎]

↓ System: Flag response as incorrect
↓ System: Delete cache entry (invalidated)
↓ System: Optionally trigger expert review queue

[Chat UI]

┌─────────────────────────────────────────────────────────────────────────────┐
│ Thank you for your feedback.                                                │
│                                                                             │
│ This response has been flagged. Would you like:                             │
│ [🔄 Get a fresh answer now]  [📧 Ask an expert]  [✕ Dismiss]               │
└─────────────────────────────────────────────────────────────────────────────┘

If user clicks "Get a fresh answer now":
→ Same as EU-C3 (force refresh)
→ New response stored in cache with increased confidence bar
```

**Caching Behavior**:

- Thumbs-down → immediate cache invalidation
- System does NOT continue serving the incorrect response to other users
- Thumbs-down count tracked: if 3+ users downvote same cached response → automatic escalation

---

## 2. Tenant Admin Flows

### Flow TA-C1: Reviewing Cache Performance Dashboard

**Persona**: Tenant Administrator
**Context**: Monthly review of platform performance and costs

```
[Admin Portal → Analytics → Cache Performance]

┌─────────────────────────────────────────────────────────────────────────────────┐
│ Cache Performance — March 2026                                                   │
│ ─────────────────────────────────────────────────────────────────────────────── │
│                                                                                 │
│  CACHE HIT RATE                  COST SAVED                 QUERIES SERVED      │
│  ┌──────────────┐                ┌──────────────┐           ┌──────────────┐    │
│  │   38%        │                │  $342.50     │           │   4,820      │    │
│  │ ████████░░   │                │  this month  │           │   this month │    │
│  └──────────────┘                └──────────────┘           └──────────────┘    │
│                                                                                 │
│  BY PIPELINE STAGE                           HIT RATE TREND                    │
│  ┌──────────────────────────────┐            ┌────────────────────────────┐    │
│  │ Embedding cache  │ 82%       │            │  Week 1: 12%               │    │
│  │ Intent cache     │ 71%       │            │  Week 2: 24%               │    │
│  │ Search cache     │ 64%       │            │  Week 3: 31%               │    │
│  │ Semantic cache   │ 38%       │            │  Week 4: 38%   ↗           │    │
│  └──────────────────────────────┘            └────────────────────────────┘    │
│                                                                                 │
│  TOP CACHED QUERY CATEGORIES                 COST SAVED BY INDEX                │
│  ┌──────────────────────────────┐            ┌────────────────────────────┐    │
│  │ HR Policy        43% of hits │            │ HR-Policies: $142.30       │    │
│  │ IT Help Desk     28% of hits │            │ IT-Docs:     $98.50        │    │
│  │ Finance FAQ      19% of hits │            │ Finance:     $75.40        │    │
│  │ Other            10% of hits │            │ Other:       $26.30        │    │
│  └──────────────────────────────┘            └────────────────────────────┘    │
│                                                                                 │
│  [⚙ Configure Cache Settings]    [📥 Export Report]    [📧 Monthly Email]      │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Admin Actions Available**:

- Configure cache settings per index (→ Flow TA-C2)
- Export cost savings report (PDF for CFO)
- Schedule monthly email report to stakeholders

---

### Flow TA-C2: Configuring Cache Settings Per Index

**Persona**: Tenant Administrator
**Context**: Adjusting cache TTL for a frequently-updated knowledge base

```
[Admin Portal → Indexes → HR-Policies → Cache Settings]

┌─────────────────────────────────────────────────────────────────────────────────┐
│ Cache Settings: HR-Policies Knowledge Base                                       │
│ ─────────────────────────────────────────────────────────────────────────────── │
│                                                                                 │
│  SEARCH RESULT CACHE                                                            │
│  ○ Disabled (always fresh)                                                      │
│  ○ 15 minutes                                                                   │
│  ○ 30 minutes                                                                   │
│  ● 4 hours           ◄ Selected                                                 │
│  ○ 8 hours                                                                      │
│  ○ 24 hours                                                                     │
│                                                                                 │
│  Recommended for: Policy documents updated monthly                              │
│  Current hit rate: 64% · Avg staleness when hit: 1.2 hours                     │
│                                                                                 │
│  ─────────────────────────────────────────────────────────────────────────── │
│                                                                                 │
│  SEMANTIC RESPONSE CACHE                                                        │
│  Enable semantic caching for this index: [✓ ON]                                │
│                                                                                 │
│  Similarity threshold:                                                          │
│  Less precise [──────────────●────────] More precise                            │
│                0.85          0.95        0.99                                   │
│  Current: 0.95 · "Similar queries" matched this week: 312                      │
│                                                                                 │
│  Response cache duration:                                                       │
│  ○ 1 hour   ● 4 hours   ○ 8 hours   ○ 24 hours   ○ Disabled                   │
│                                                                                 │
│  ─────────────────────────────────────────────────────────────────────────── │
│                                                                                 │
│  PREVIEW IMPACT                                                                 │
│  If you change TTL from 4h → 8h:                                               │
│  Expected hit rate: 64% → 72% (+8%)                                            │
│  Expected savings: +$24.50/month                                                │
│  Risk: Responses may be up to 8h stale                                         │
│                                                                                 │
│  [Save Changes]                [Reset to Defaults]                              │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Key UX Decisions**:

- Preview impact before saving — shows cost/freshness tradeoff
- Current hit rate shown to inform decision
- Similarity threshold slider with clear labels ("Less precise" / "More precise")
- Contextual help text ("Recommended for: Policy documents...")

---

### Flow TA-C3: Investigating a Cache Freshness Complaint

**Persona**: Tenant Administrator
**Context**: User reported receiving outdated cached information

```
[Admin Portal → Analytics → Cache → Incident Investigation]

1. Admin searches for the specific query:
   "How many vacation days do new employees get?"

2. System shows cache history for this query:

   ┌──────────────────────────────────────────────────────────────────────┐
   │ Query: "vacation days new employees"  · HR-Policies index             │
   │ ─────────────────────────────────────────────────────────────────────│
   │ 14:23 — Cache entry created (LLM response generated)                  │
   │ 14:31 — Served to user@company.com [👍]                               │
   │ 16:45 — Served to user2@company.com [👍]                              │
   │ 18:22 — Served to user3@company.com [👎] ← complaint flagged here    │
   │ 18:22 — Cache entry INVALIDATED (thumbs-down)                         │
   │ 18:23 — Fresh LLM response generated                                  │
   │ ─────────────────────────────────────────────────────────────────────│
   │ Root cause: Policy updated in SharePoint at 17:15,                    │
   │ but cache TTL = 4h. Cache was not invalidated by document update.     │
   │                                                                        │
   │ Resolution: SharePoint webhook event missed (sync lag 65 minutes)     │
   │ ─────────────────────────────────────────────────────────────────────│
   │ [Reduce TTL for this index]  [Review SharePoint sync config]          │
   └──────────────────────────────────────────────────────────────────────┘

3. Admin takes action: reduces TTL from 4h to 1h for HR-Policies index
   (until SharePoint sync reliability is confirmed)
```

---

## 3. Platform Admin Flows

### Flow PA-C1: Monitoring Cache Health Across All Tenants

**Persona**: Platform Administrator (mingai staff)
**Context**: Daily health check of cache performance across the platform

```
[Platform Admin Portal → Infrastructure → Cache Monitor]

┌─────────────────────────────────────────────────────────────────────────────────┐
│ Cache Health — All Tenants                                    Last 24h          │
│ ─────────────────────────────────────────────────────────────────────────────── │
│                                                                                 │
│  REDIS HEALTH          SEMANTIC CACHE (pgvector)     TOTAL COST SAVED          │
│  ● Healthy             ● Healthy                     $1,247.30 today           │
│  Memory: 4.2GB / 8GB   DB size: 22GB / 100GB                                  │
│                                                                                 │
│  TOP TENANTS BY CACHE HIT RATE        LOW PERFORMERS (< 20% hit rate)          │
│  ┌───────────────────────────────┐    ┌───────────────────────────────────┐    │
│  │ Tenant A (FinanceCo): 48%     │    │ Tenant X (StartupCo): 8%          │    │
│  │ Tenant B (LegalFirm): 44%     │    │   → Low volume, cache not warm    │    │
│  │ Tenant C (HealthCo): 41%      │    │ Tenant Y (NewCo): 12%             │    │
│  └───────────────────────────────┘    │   → Mostly unique queries         │    │
│                                        └───────────────────────────────────┘    │
│                                                                                 │
│  ⚠️ ALERTS                                                                      │
│  Tenant D: Redis memory > 80% quota → Consider upgrade to Professional          │
│  Tenant E: Cache invalidation rate elevated → Check SharePoint sync health      │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Edge Case Flows

### Flow EDGE-C1: Cache Disabled / Redis Down

**Scenario**: Redis becomes unavailable (network issue, memory pressure)
**Expected behavior**: System degrades gracefully to full RAG pipeline — no errors

```
Redis unavailable
↓
CacheService.get() → returns None (treated as cache miss)
CacheService.set() → silently fails, logs warning
↓
Full RAG pipeline executes normally
↓
User receives live LLM response
↓
No cache state indicator shown (or show "🟢 Live response")
↓
Incident: platform admin alerted via Redis health monitor
```

**UX**: User never sees an error. Performance degrades (2.5s vs 0.5s) but functionality intact.

### Flow EDGE-C2: Stale Cache After Document Update

**Scenario**: Document updated in SharePoint but webhook delivery delayed (>TTL)
**Expected behavior**: TTL serves as final safety net

```
SharePoint document updated (PTO policy changed)
↓
Webhook fires → delayed 3 minutes (network issue)
↓
During delay: cached responses served (up to TTL maximum)
↓
Webhook received → version counter incremented → next lookup invalidates stale entries
↓
Fresh responses served from that point
```

**Worst case**: User receives response up to max TTL old (e.g., 4h for HR policies). Acceptable for policy documents; not acceptable for real-time financial data (TTL = 30s max).

### Flow EDGE-C3: Semantic Cache Threshold Edge Case

**Scenario**: Two queries with 0.94 similarity (below default 0.95 threshold)

```
Query A: "What is the PTO policy for part-time employees?"
Query B: "How many days off do contractors get?"

Cosine similarity: 0.93 (< 0.95 threshold)
```

**Expected behavior**: Cache miss → full pipeline for Query B. Correct: contractors and part-time employees have different policies.

**Why this is correct**: The 0.95 threshold correctly identifies this as a different question. The system errs on the side of fresh responses for edge cases.

---

## 5. UX Principles for Cache Integration

1. **Never surprise the user**: Cache hits should feel like fast responses, not suspicious ones
2. **Transparency builds trust**: Always show response age; never hide that caching occurred
3. **Control is power**: Always provide a way to get a fresh response
4. **Fail gracefully**: Cache unavailability must never surface as an error to the user
5. **Feedback closes the loop**: Thumbs-down immediately invalidates cache — user action has impact
6. **Admin visibility, not complexity**: Admins see ROI and control quality; implementation details hidden
7. **Cost savings as a feature**: Make the dollar savings visible and concrete — this is the product

---

**Document Version**: 1.0
**User Personas Covered**: End User (4 flows), Tenant Admin (3 flows), Platform Admin (1 flow), Edge Cases (3 flows)
