# 09. A2A DAG Execution User Flows

> **Status**: Design
> **Date**: 2026-03-05
> **Purpose**: Define the end-user and admin experience for A2A multi-agent DAG execution, including partial failure states, guardrail interactions, marketplace consent, and DAG replay.
> **Based on**: `01-research/25`, `01-research/26`, `01-research/27`, `01-research/28`

---

## Flow 1: Single-Agent Query (Fast-Path)

**Persona**: End user (analyst)
**Trigger**: User submits a query that maps clearly to one agent
**Path**: Fast-path (skips DAG planner)

```
User: "What is Apple's current P/E ratio and market cap?"

[Chat interface: thinking indicator appears immediately]

─── Intent detection: Bloomberg (confidence 0.96) ────────── 5ms
─── Fast-path: bypass planner ────────────────────────────── 0ms
─── Bloomberg agent dispatched ───────────────────────────── 12ms
─── Bloomberg API → MCP → Artifact ─────────────────────── 1,800ms
─── Extraction: pass-through (under threshold) ───────────── 0ms
─── Synthesis LLM: stream starts ─────────────────────────── 250ms

[Response streams in]:
Apple (AAPL) — Bloomberg Data License

**P/E Ratio**: 28.5x (as of market close 2026-03-05)
**Market Cap**: $2.94 trillion

[Source: Bloomberg Data License]

Total time: ~2.1s
```

**Key UX**: Streaming starts well under 3 seconds. No DAG status indicator shown for single-agent queries — response appears to start immediately.

---

## Flow 2: Multi-Agent DAG Query (Full Path)

**Persona**: End user (portfolio analyst)
**Trigger**: User submits a complex multi-source research query

```
User: "Compare Apple vs Microsoft: financials, analyst sentiment, and latest news"

[Chat interface: multi-agent research indicator appears]
```

### 2a. DAG Status Indicator (User-Facing)

```
┌──────────────────────────────────────────────────────────────┐
│  Researching across 3 sources...                             │
│                                                              │
│  Bloomberg ████████████████████ Done (2.1s)                  │
│  CapIQ      ████████████████░░░░ Retrieving...               │
│  Perplexity ██████████████████░░ Processing...               │
│                                                              │
│  Estimated completion: ~3s remaining                         │
└──────────────────────────────────────────────────────────────┘
```

### 2b. Response After All Agents Complete

```
Apple vs Microsoft: Comparative Analysis

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Based on: Bloomberg ✓  |  CapIQ ✓  |  Perplexity ✓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**Financials** (Bloomberg):
| Metric      | Apple (AAPL) | Microsoft (MSFT) |
|-------------|--------------|------------------|
| Price       | $192.30      | $415.20          |
| P/E         | 28.5x        | 36.1x            |
| Market Cap  | $2.9T        | $3.1T            |
| Revenue TTM | $385B        | $245B            |

**Credit & Competitive Position** (CapIQ):
- Apple: BBB+ credit rating; EV/EBITDA 22x
- Microsoft: AAA credit rating; EV/EBITDA 28x; pricing premium reflects Azure growth

**Recent News** (Perplexity, web search):
- Apple: Q1 FY2026 earnings beat analyst estimates by $0.12 EPS (Reuters, Mar 3)
- Microsoft: Azure revenue growth accelerated to 33% YoY (WSJ, Mar 2)

[Sources cited above]  [View research details ▼]
```

The "View research details" expander opens the DAG run panel (Flow 5).

---

## Flow 3: Partial Failure — Supplementary Agent Unavailable

**Persona**: End user
**Scenario**: Perplexity web search is temporarily down during a multi-agent query

```
User: "Compare Apple vs Microsoft: financials, analyst sentiment, and latest news"

[Multi-agent research indicator]
  Bloomberg ████████████████████ Done (2.1s)
  CapIQ      ████████████████████ Done (3.2s)
  Perplexity ░░░░░░░░░░░░░░░░░░░░ Retrying...  ← retry in progress
  Perplexity ██████ Unavailable                 ← retry failed

[Synthesizing with available sources...]

[Response streams]:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Based on: Bloomberg ✓  |  CapIQ ✓  |  Perplexity ⚠ unavailable
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**Financials** (Bloomberg):
[... response based on Bloomberg and CapIQ ...]

⚠ Note: Perplexity web search was temporarily unavailable. Recent news
  context is not included in this response.
  [Retry with all sources]
```

The "Retry with all sources" button re-dispatches the identical DAG. The user decides whether to retry or accept the partial response.

---

## Flow 4: Hard Failure — Critical Agent Auth Expired

**Persona**: End user
**Scenario**: Bloomberg credentials have expired

```
User: "What is Apple's current P/E ratio?"

[Thinking indicator]

[Response]:
Bloomberg data could not be retrieved — your organization's Bloomberg
credentials have expired.

Please ask your administrator to reconfigure Bloomberg access in
Settings → Connected Data Sources → Bloomberg.

Would you like to search for this information from public sources instead?
  [Search with Perplexity]  [Skip]
```

If the user clicks "Search with Perplexity", the orchestrator replans the DAG with Perplexity as a supplementary substitute for general market information (not Bloomberg-grade precision — this is surfaced to the user):

```
[Searching public sources for Apple P/E data...]

Based on recent web sources (Bloomberg data unavailable):
Apple's P/E ratio is approximately 28-29x (source: Yahoo Finance, Perplexity search).
Note: For precise Bloomberg data, contact your administrator to renew credentials.

[Source: Perplexity web search — not Bloomberg Data License]
```

---

## Flow 5: Tenant Admin — DAG Replay and Debug

**Persona**: Tenant admin
**Trigger**: User reports "the answer was wrong" or admin investigates low-quality response

### 5a. Finding the DAG Run

```
[Tenant Admin Panel]  >  [Conversations]  >  [conv-12345]

Conversation: "Compare Apple vs Microsoft" — User: sarah.chen@finco.com
Messages: 12  |  Last active: 2026-03-05 14:32

[View Conversation]  [View DAG Runs]
```

### 5b. DAG Run Details

```
[DAG Runs for Message #8]

Run ID: run-xyz789  |  Status: ✓ Completed  |  Duration: 5.8s
Agents: Bloomberg ✓, CapIQ ✓, Perplexity ✓

─────────────────────────────────────────────────────────
Bloomberg Artifact                               [Expand ▼]
  Apple (AAPL): Price $192.30, P/E 28.5, Market Cap $2.9T
  Microsoft (MSFT): Price $415.20, P/E 36.1, Market Cap $3.1T
  ─ Extracted: 1,340 tokens  Original: 12,400 tokens

CapIQ Artifact                                   [Expand ▼]
  Apple: BBB+, EV/EBITDA 22x, Net Margin 25.3%
  Microsoft: AAA, EV/EBITDA 28x, Net Margin 36.8%
  ─ Extracted: 980 tokens  Original: 7,200 tokens

Perplexity Artifact                              [Expand ▼]
  Reuters (2026-03-03): Apple Q1 FY2026 earnings beat...
  WSJ (2026-03-02): Microsoft Azure growth accelerates...
  ─ Extracted: 1,100 tokens  Original: 3,400 tokens

Synthesis
  Model: GPT-5.2-chat  |  Input: 4,200 tok  |  Output: 890 tok
  [View Synthesis Input]  [View Full Response]
─────────────────────────────────────────────────────────

[Re-run this DAG]  [Export Artifacts as JSON]
```

### 5c. Re-running the DAG

```
[Re-run this DAG]

Re-running: "Compare Apple vs Microsoft: financials, analyst sentiment, and latest news"

This will dispatch the same query to:
  Bloomberg, CapIQ, Perplexity

Results will be saved as a new DAG run for comparison.

[Confirm Re-run]  [Cancel]
```

After re-run, the admin can compare the two DAG run outputs side-by-side to verify whether a credential fix, agent update, or platform change resolved the issue.

---

## Flow 6: Guardrail Block — Investment Advice Rejected

**Persona**: End user
**Scenario**: User asks Bloomberg agent for investment advice

```
User: "Should I add Apple stock to my portfolio?"

[Thinking indicator]

[Response]:
Bloomberg financial data for Apple (AAPL):
  Price: $192.30  |  P/E: 28.5x  |  Market Cap: $2.9T
  52-week range: $142.10 – $198.50

Investment recommendations are outside the scope of this platform's
Bloomberg data integration. Bloomberg Data License provides market data
only — not investment advice.

For investment guidance, please consult your portfolio manager or
licensed investment advisor.

[Get more financial data for AAPL]
```

**Tenant Admin view (guardrail audit trail)**:

```
[Agent Performance]  >  [Guardrail Events]

2026-03-05 14:35:21  |  Bloomberg  |  Rule: no_investment_advice
  Action: block  |  User: sarah.chen@finco.com
  Response sent: "Investment recommendations are outside scope..."
```

The user never knows the output was blocked and rewritten — they see a coherent, helpful response that explains the limitation.

---

## Flow 7: BYOMCP Registration (Enterprise Tenant Admin)

**Persona**: Enterprise tenant admin
**Trigger**: Engineering team has built a custom ERP MCP server

### 7a. Registration

```
[Tenant Admin]  >  [Custom Agents]  >  [Register New Agent]

Step 1: Agent Details
  Name: [Custom ERP Intelligence              ]
  Description: [Read-only access to Acme ERP financial data]

Step 2: Capabilities
  [✓] Read    [ ] Write    [ ] Delete

Step 3: Endpoints
  GET  /financials   Get quarterly financial records
  GET  /employees    Get headcount by department

Step 4: Egress Domains
  erp-api.acme-corp.internal

[Submit for Review]
```

### 7b. Approval Notification (to tenant admin)

```
Your custom agent "Custom ERP Intelligence" has been submitted for review.

Platform admin will review within 24 hours (read-only agents) or
48 hours (write-capable agents).

You will be notified when approved or if additional information is needed.
```

### 7c. After Approval

```
[Custom Agents]
  Custom ERP Intelligence   ✓ Approved — Active
    Enabled for roles: [Finance Analysts ✓] [Risk Team ✓] [All Users ✗]
    Last used: 2026-03-05 10:12  |  Queries this month: 234
    [Edit RBAC]  [View Audit Log]  [Disable]
```

---

## Flow 8: Marketplace Agent Consent — "Always Prompt" Policy

**Persona**: End user at a regulated financial services firm
**Scenario**: Tenant admin has configured "Always prompt users" for Reuters News agent

```
User: "What is the latest news on Apple's AI strategy?"

[Pre-dispatch consent dialog]:
┌─────────────────────────────────────────────────────────────┐
│  External Data Source Notice                                │
│                                                             │
│  To answer this question, part of your query will be sent  │
│  to Reuters News Ltd (external service, EU data center).   │
│                                                             │
│  Reuters will process your query to return news results.   │
│  Data is not retained beyond the request per our agreement.│
│                                                             │
│  [Send to Reuters and answer]   [Answer without Reuters]   │
└─────────────────────────────────────────────────────────────┘

[User selects: Send to Reuters and answer]

[Multi-agent research indicator]
  Reuters ████████████████████ Done (1.4s)

[Response]:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Based on: Reuters ✓ (external service, EU)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Reuters news summary about Apple AI strategy]
```

---

## Flow 9: Platform Admin — Marketplace Agent Verification and Publish

**Persona**: Platform admin
**Trigger**: Publisher submits a new agent template to the marketplace
**Path**: Publisher trust verification → capability probe → data egress test → marketplace publish

```
[Platform admin receives notification: "New marketplace submission — Reuters News Agent v1.2 by Reuters Ltd"]

[Admin opens: Platform > Marketplace > Pending Review]

Review queue:
┌──────────────────────────────────────────────────────────────────┐
│  Reuters News Agent v1.2                            [Review →]   │
│  Publisher: Reuters Ltd  |  Submitted: 2026-03-05                │
│  Capabilities declared: read-only  |  Egress: reuters.com only   │
│  Data retention: none per DPA      |  EU datacenter: ✓           │
└──────────────────────────────────────────────────────────────────┘

[Admin clicks Review →]

[Publisher trust panel]:
  ✓ Domain verified: reuters.com (DNS TXT record present)
  ✓ DPA signed: 2026-02-15 (Reuters EU Data Processing Agreement)
  ✓ Capability declaration: read-only, no write ops declared

[Capability probe — platform auto-runs]:
  Probe 1: Send test Task "latest news on AAPL"
    → Response received, schema valid
    → No mutation fields (created_id, updated_at, rows_affected): ✓
  Probe 2: Send Task with empty query
    → Graceful error returned (400), no crash: ✓
  Probe 3: Send malformed Task
    → Protocol error returned (400), no server crash: ✓
  Capability probe result: PASS — read-only confirmed

[Data egress test — admin initiates]:
┌──────────────────────────────────────────────────────────────────┐
│  Data Egress Verification                                        │
│                                                                  │
│  Method 1: Canary test (automated, 24h monitoring period)        │
│  Method 2: Third-party security audit certificate                │
│                                                                  │
│  Reuters Ltd has provided: [Security Audit Certificate]          │
│  Certificate: NCC Group audit 2026-01-22, scope covers A2A API   │
│  [Accept certificate]  [Run canary test instead]                 │
└──────────────────────────────────────────────────────────────────┘

[Admin selects: Accept certificate]

[Final review panel]:
  Publisher trust: ✓
  Capability probe: PASS
  Data egress verification: ✓ (third-party audit accepted)
  Declared egress destinations: reuters.com:443 (HTTPS only)

[Admin adds operator notes]:
  "Approved 2026-03-05. Renewal required 2027-01-01 per cert expiry.
   Re-verify on major version bump (v2.x+)."

  [Publish to Marketplace]  [Request Changes]  [Reject]

[Admin selects: Publish to Marketplace]

[Confirmation]:
  Reuters News Agent v1.2 is now live in the marketplace.
  All tenants can enable this agent from Agent Settings.
  Operator notes saved to verification audit log.
```

**Key UX**: Platform admin is a security gate, not a rubber stamp. The UI surfaces certificate evidence, probe results, and declared egress destinations so the admin makes an informed approval. Operator notes are append-only audit trail entries.

---

## Flow 10: Platform Admin — BYOMCP Approval (Write-Capable Agent)

**Persona**: Platform admin
**Trigger**: Tenant admin submits a BYOMCP registration for a write-capable agent
**Path**: Write-capability flag triggers enhanced review → platform admin approval gate

```
[Platform admin receives high-priority alert]:
  "BYOMCP submission requires enhanced review — write capability declared"
  Tenant: Apex Capital Management
  Agent: Internal Deal Tracker (CRM write access)

[Admin opens: Platform > BYOMCP > Pending Enhanced Review]

┌──────────────────────────────────────────────────────────────────┐
│  Internal Deal Tracker                         [Enhanced Review] │
│  Tenant: Apex Capital Management                                 │
│  MCP endpoint: mcp.apex-internal.com:8443                        │
│  Capabilities declared: READ + WRITE (CRM records)              │
│  Write scope declared: deal stage updates, contact notes         │
│  ⚠ WRITE capability — enhanced review required                   │
└──────────────────────────────────────────────────────────────────┘

[Network isolation review]:
  Declared egress: mcp.apex-internal.com (Apex private network)
  Cilium FQDN policy will restrict to: mcp.apex-internal.com:8443
  No public internet egress declared: ✓
  Cross-tenant isolation: Pod-level namespace separation confirmed

[Capability probe — write-mutation detection]:
  Probe 1: GET-style Task "list open deals"
    → Response: deal list returned, no mutation fields ✓
  Probe 2: Mutation-style Task "update deal stage for DealID-TEST"
    → Response includes: {"updated_at": "2026-03-05T10:00:00Z"} — write confirmed
    → Write capability: CONFIRMED (matches declaration ✓)
  Probe 3: Attempt out-of-scope write "delete contact"
    → Response: 403 Forbidden — scope enforcement working ✓

[Risk assessment]:
  ⚠ Write-capable agents carry elevated risk:
     - Irreversible data mutations possible via user queries
     - Requires tenant admin to configure explicit write-permission policy
     - Guardrail Layer 2 (output filter) must include write-block rules
       for any query contexts where mutations are unintended

[Admin adds mandatory operator notes]:
  "Write access approved for Apex Capital deal stage updates and contact
   notes only. Tenant admin must configure write-permission guardrail.
   Re-review required on any capability scope expansion."

  [Approve with conditions]  [Approve unrestricted]  [Reject]

[Admin selects: Approve with conditions]

[Conditions dialog]:
  Attached condition: "Tenant admin must configure write-guard guardrail
  rule before write-capable queries are processed. Platform will enforce
  30-day review cadence for write-capable BYOMCP registrations."

[Confirmation]:
  Internal Deal Tracker approved with conditions.
  Tenant admin notified: must configure write-guard guardrail to activate.
  Agent enters PENDING_TENANT_CONFIG status until guardrail is set.
  Review reminder scheduled: 2026-04-04.
```

**Key UX**: Write-capable BYOMCP registrations are never silently approved. The platform admin sees capability probe evidence, must add operator notes, and must choose "Approve with conditions" or "Approve unrestricted" — there is no default-approve path. The tenant receives a clear activation requirement before the agent goes live.

---

## Flow Summary

| Flow | Persona        | Trigger                             | Key UX Pattern                           |
| ---- | -------------- | ----------------------------------- | ---------------------------------------- |
| 1    | End user       | Simple single-agent query           | Fast, no status indicator                |
| 2    | End user       | Multi-source research query         | Per-agent progress indicator             |
| 3    | End user       | Supplementary agent down            | Partial response + retry option          |
| 4    | End user       | Critical agent auth expired         | Hard block + alternative option          |
| 5    | Tenant admin   | Quality investigation               | DAG run panel + artifact inspection      |
| 6    | End user       | Guardrail block                     | Transparent policy response              |
| 7    | Tenant admin   | BYOMCP registration                 | Review + approval workflow               |
| 8    | End user       | Marketplace agent                   | Per-query consent dialog                 |
| 9    | Platform admin | Marketplace agent verification      | Trust verification + capability probe    |
| 10   | Platform admin | BYOMCP write-capable agent approval | Enhanced review + condition-gated access |
