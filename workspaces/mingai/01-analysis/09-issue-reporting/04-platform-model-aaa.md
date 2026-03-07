# 09-04 — Issue Reporting: Platform Model & AAA Framework Evaluation

**Date**: 2026-03-05

---

## 1. Platform Model Thinking

A platform facilitates seamless direct transactions between producers, consumers, and partners.

### 1.1 Role Identification

**Consumers** (receive value from the transaction):

- End users of mingai who encounter bugs, UX problems, or have improvement ideas
- They consume the VALUE of having their issues resolved and being kept informed
- They are not paying for the issue reporting directly — it's part of their platform subscription

**Producers** (create value in the transaction):

- Engineering teams who fix issues and ship improvements
- They PRODUCE the resolution
- Platform operators who triage, prioritize, and schedule

**Partners** (facilitate the transaction):

- GitHub / GitLab: The issue repository and workflow tool (stores and tracks the work)
- AI Triage Agent: Translates consumer reports into producer-actionable items
- Notification system: Closes the loop between producer actions and consumer awareness
- Azure Blob: Stores screenshots so context is preserved across time

### 1.2 Transaction Analysis

The core "transaction" in this platform is:

```
Consumer (user) REPORTS a problem
→ Partner (AI agent) TRANSLATES and enriches it
→ Partner (GitHub) STORES and tracks it
→ Producer (engineer) RESOLVES it
→ Partner (notification system) CLOSES THE LOOP back to consumer
```

**Transaction friction points today (WITHOUT this feature)**:

1. Consumer has no clear channel to report → friction point
2. Consumer report is incomplete → translation overhead for producer
3. Producer has no systematic way to notify consumer → loop stays open
4. Consumer never knows if issue was resolved → trust erodes

**Transaction facilitation WITH this feature**:

1. Zero-friction reporting (one click, automatic context) → consumer activation
2. AI translation removes ambiguity → producer efficiency
3. GitHub webhook → notification closes loop → consumer trust
4. Upvote on duplicate issues → collective signal → producer prioritization quality

### 1.3 Network Effects Assessment

**Same-side network effects** (more users → more value for other users):

- More end users reporting → better duplicate detection → higher-priority bugs get fixed faster → ALL users benefit from quality improvements
- This is a positive externality from each individual report

**Cross-side network effects** (more producers → more value for consumers):

- More engineering capacity applied to well-triaged issues → faster resolution → consumers get fixes sooner
- As more consumer reports flow in, producers have better signal → allocate time to highest-impact fixes

**Data network effects** (our strongest moat):

- More tenants using the system → larger cross-tenant embedding index → better duplicate detection for all tenants
- Historical issue data builds a knowledge base of how bugs manifest in AI RAG systems → future triage agent is more accurate
- Each resolved issue + its session context trains the system's understanding of failure modes

### 1.4 Network Behavior Coverage

Per the product design principles, features must cover:

#### Accessibility

**How easy is it for users to complete the transaction (report an issue)?**

- Floating report button visible on all pages → always one click away
- Keyboard shortcut (Ctrl+Shift+F) for power users
- Auto-triggered dialog on detected error states (API failure, 5xx response)
- No login or authentication required beyond existing session
- Mobile-responsive reporter widget

**Assessment**: HIGH accessibility. Multiple entry points, zero additional authentication.

#### Engagement

**What information helps users complete the transaction?**

- My Reports dashboard: user can see all their submitted reports, status, and SLA
- Notification bell: unread status updates surfaced prominently
- Duplicate consolidation: "12 other users reported this" → tells user their issue is known and prioritized
- Status timeline: "Reported → Triaged → In Progress → Resolved" visual progress indicator

**Assessment**: HIGH engagement. Users are pulled back to the platform to check status, creating habitual engagement with the quality loop.

#### Personalization

**What information is curated for the user's specific context?**

- The AI triage agent personalizes the GitHub issue with the user's specific session state (not generic)
- Notification preferences: user can choose email vs in-app vs both
- Report history shows the user's own reports, not others' (except upvote counts)
- SLA calculation based on severity (user receives a personally-relevant timeline)

**Assessment**: MEDIUM personalization. Strong on context enrichment; could improve on personalized issue recommendations ("you might want to report this") based on session patterns.

#### Connection

**What data sources are connected to the platform?**

- GitHub / GitLab bidirectional: issues pushed to repo, webhooks received for status
- Azure AI Search: duplicate detection index
- Azure Blob: screenshot storage
- Redis: real-time queue for async processing
- SendGrid: email notifications
- WebSocket / SSE: real-time in-app notifications

**Assessment**: HIGH connection. Multiple systems integrated bidirectionally.

#### Collaboration

**Can producers and consumers jointly work together?**

- Comment thread on issue (user can respond to follow-up questions from engineering)
- Upvoting: multiple users can add signal to the same issue
- User can provide additional context after initial report ("I found a workaround")
- Engineering can ask clarifying questions via in-app notification thread

**Assessment**: MEDIUM collaboration. Basic collaboration present; could be enhanced with richer in-app conversation threading.

---

## 2. AAA Framework Evaluation

### 2.1 Automate (Reduce Operational Costs)

**What manual operations does this feature automate?**

| Manual Process                                             | Automated Replacement                                              | Cost Saved               |
| ---------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------ |
| Reading user bug report emails, asking follow-up questions | AI triage agent enriches with session context; no follow-up needed | 30-60 min/issue          |
| Creating GitHub issues from user reports                   | Automatic GitHub issue creation with structured template           | 15-20 min/issue          |
| Assigning severity to issues                               | AI severity scoring (P0-P4) based on context + description         | 10-15 min/issue          |
| Checking for duplicate reports                             | Semantic embedding duplicate detection                             | 15-30 min/week           |
| Sending status update emails to reporters                  | Automated via GitHub webhooks + notification system                | 5-10 min/issue/milestone |
| Calculating SLA commitments                                | Automatic SLA calculation based on severity classification         | 5 min/issue              |

**Total operational cost reduction estimate**:

- At 50 issues/month: ~80-150 minutes per issue saved → 67-125 hours/month recovered
- At an engineering blended rate of $100/hour: $6,700-$12,500/month in recovered time
- Annual: $80K-$150K in operational savings for a mid-size team

**Automation score**: 9/10 — highly automatable process, well-matched to AI capabilities.

### 2.2 Augment (Reduce Decision-Making Costs)

**What decisions does this feature improve?**

| Decision                                               | Without Feature                               | With Feature                                                       | Quality Improvement                   |
| ------------------------------------------------------ | --------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------- |
| "Which bugs should we fix this sprint?"                | Based on who shouted loudest, incomplete data | AI severity score + report volume + SLA urgency                    | Objective, data-driven prioritization |
| "Is this a retrieval bug or an LLM bug?"               | Manual investigation required                 | AI triage using session context (confidence score, search results) | Root cause category given immediately |
| "Is this a new bug or a known issue?"                  | Manual search through GitHub issues           | Semantic duplicate detection across tenants                        | Instant deduplication                 |
| "Should we commit to fixing this in 1 week?"           | Gut feel based on sprint capacity             | SLA matrix based on severity + historical resolution time          | Calibrated commitment                 |
| "What was the user actually doing when this happened?" | Incomplete user description                   | Full session context: query, model, sources, confidence, errors    | Complete reproduction picture         |

**Augmentation score**: 8/10 — strongly improves decision quality for engineering and product prioritization.

### 2.3 Amplify (Reduce Expertise Costs for Scaling)

**How does this enable a smaller team to handle more?**

| Scaling Challenge                                           | Without Feature                                               | With Feature                                              |
| ----------------------------------------------------------- | ------------------------------------------------------------- | --------------------------------------------------------- |
| 10 tenants, each with 20 reporters → 200 reports/month      | Need 2-3 dedicated support engineers for triage               | 1 engineer reviews AI pre-triaged queue                   |
| P0 bug affects all tenants simultaneously                   | Discovery is fragmented (each tenant CS rep calls separately) | Single cross-tenant deduplicated issue raised immediately |
| New engineering team member needs to understand bug context | Read 10 email threads to reconstruct context                  | Read one GitHub issue with complete context               |
| Product manager needs quality signal across tenants         | Weekly support ticket analysis                                | Real-time dashboard with issue heatmap                    |

**Amplification score**: 8/10 — a 3-person engineering team can handle what previously required 6 with this system. Critical for early-stage scaling.

---

## 3. Synthesis: Platform Readiness Assessment

| Dimension                      | Score    | Evidence                                                                                |
| ------------------------------ | -------- | --------------------------------------------------------------------------------------- |
| Producer-consumer facilitation | 9/10     | Clear transaction, low friction, closed loop                                            |
| Network effects                | 7/10     | Cross-tenant dedup creates genuine cross-tenant NE; within-tenant NE moderate           |
| AAA — Automate                 | 9/10     | Highly automatable process                                                              |
| AAA — Augment                  | 8/10     | Improves prioritization and diagnosis decisions                                         |
| AAA — Amplify                  | 8/10     | Enables smaller team to handle more                                                     |
| Network behaviors              | 7/10     | High on accessibility, engagement, connection; medium on personalization, collaboration |
| **Overall**                    | **8/10** | Strong platform fit — proceed with implementation                                       |

### 3.1 Critical Gaps to Address

**Gap 1: Personalization is weak**
The reporter widget is not personalized to what the user was doing. Opportunity: trigger contextual prompts ("You just got a low-confidence response — was this helpful?") rather than waiting for the user to click report.

**Gap 2: Collaboration is thin**
A basic comment thread is not enough for collaborative diagnosis. Consider: engineer can request a screen recording, user can share additional screenshots in follow-up.

**Gap 3: No producer incentive structure**
Engineers who resolve issues and update status should receive recognition (dashboards showing issues resolved, SLA adherence rate). Without this, the automated notification system will degrade as status updates get ignored.

**Gap 4: Feedback analytics for product teams**
The platform team needs a dashboard showing:

- Issue volume by category and tenant
- Average time to resolution by severity
- SLA adherence rate
- Top 10 recurring bugs by report volume
- Trend: is quality improving or degrading over time?

This is the "intelligence layer" that makes the system a product quality management tool, not just a bug report collector.
