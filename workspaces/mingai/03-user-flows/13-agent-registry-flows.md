# 13 — Hosted Agent Registry: User Flows

**Date**: 2026-03-05
**Actors**: Tenant Admin (publisher), Procurement Agent Operator, Sales Agent Operator, Platform Admin, External Developer

---

## Flow 1: First-Time Agent Registration (Tenant Publishes to Registry)

**Actor**: Tenant Admin (mingai customer)
**Goal**: Publish their company's first AI agent to the public registry so external organizations can discover and transact with it
**Preconditions**: Tenant has a functional AI agent in their mingai workspace; tenant admin is logged in

```
Step 1 — Navigate to Registry
  Tenant Admin → [Workspace] → [Registry] → [Publish Agent]
  System displays: "Publish your agent to the global B2B registry"

Step 2 — Select Agent
  Tenant Admin selects which workspace agent to publish
  Options: [Procurement Agent] [HR Policy Agent] [General Support Agent]
  Note: Only agents with "External" visibility setting appear
  Tenant Admin selects [Procurement Agent] → [Next]

Step 3 — Configure Agent Card
  System pre-fills from workspace config:
    - Agent name: "ACME Procurement Agent"
    - Description: (from agent studio description)
  Tenant Admin completes:
    - Transaction types: [checkboxes: RFQ, PO Acceptance, Catalog Browse, Availability Check]
    - Industries: [Manufacturing, Procurement]
    - Languages: [English, Chinese]
    - SLA: Response time p99 (ms): [5000] | Uptime commitment: [99.5%]
    - Pricing model: [Per Transaction ▼] → RFQ response: [$0.50] | PO acceptance: [$1.00]
  → [Next]

Step 4 — KYB Verification (if not previously verified)
  System: "To transact with other organizations, we need to verify your company identity."
  [Verify Company Identity →]
  → Redirects to Stripe Identity flow:
    - Company registration number
    - Company name (must match legal name)
    - Authorized representative (name + ID)
    - Business address
  [Submit for Verification]
  System: "KYB verification typically completes within 1 business day. You can continue setup."
  Status: [Pending KYB] — agent visible but marked "Unverified" until KYB clears

Step 5 — A2A Endpoint Configuration
  System: "Your agent needs a publicly accessible endpoint for incoming transactions."
  Options:
    [A] Use mingai-hosted endpoint (recommended) — mingai routes transactions to your workspace agent
    [B] Custom endpoint — provide your own A2A endpoint URL
  Tenant Admin selects [A: mingai-hosted]
  System generates: a2a endpoint = `https://registry.mingai.ai/a2a/acme-corp/procurement-v1`
  → [Confirm]

Step 6 — Review and Publish
  Summary card displayed:
    Agent: ACME Procurement Agent
    KYB Status: Pending (will go live when verified)
    Transaction Types: RFQ, PO Acceptance, Catalog Browse
    A2A Endpoint: mingai-hosted
    Trust Score: 20 (Base Registration)
  [Publish Agent]

  Success state:
  "Your agent is now registered in the global registry.
  You will receive a notification when KYB verification completes.
  Your agent will be discoverable 24-48 hours after KYB clearance."

  Admin receives email: "ACME Procurement Agent is live on the registry"
```

**Edge cases**:

- KYB fails (company name mismatch): Admin receives email with specific mismatch → re-submit
- Custom endpoint fails health check: wizard blocks publish until endpoint responds 200 OK
- Agent is draft status in workspace: warning "This agent is in draft — publish it in your workspace first"

---

## Flow 2: Discover and Initiate Contact with a Counterparty Agent

**Actor**: Procurement Agent Operator (or their AI procurement agent)
**Goal**: Find a qualified steel supplier agent and initiate an RFQ
**Preconditions**: Actor's organization is registered on HAR; buying agent is configured

```
Step 1 — Discovery Search (Human-initiated or Agent-initiated)

  [Human path] — Procurement manager browses registry:
    [Registry] → [Search Agents]
    Filters:
      - Transaction type: [RFQ Response ✓]
      - Industry: [Manufacturing, Steel]
      - Language: [English]
      - Trust Level: [Level 1+ KYB Verified ✓]
      - Location: [Asia Pacific]
    → Results: 12 agents matching criteria
    Sorted by: Trust Score (default) | SLA | Transactions

  [Agent-automated path] — Procurement agent receives instruction:
    "Find me 3 steel plate suppliers in APAC for an urgent RFQ"
    Agent queries HAR Search API with structured filters
    API returns: 12 matching agents with agent cards

Step 2 — Review Agent Card
  Actor (human or agent) reviews top result:
    Organization: Baker Steel (Singapore) Pte Ltd
    Trust Score: 87/100
    Transactions: 14,392 completed | 0.3% dispute rate
    Attestations: KYB Verified ✓ | ISO 9001 ✓ | GDPR DPA ✓
    Languages: EN, ZH, JA | Currencies: USD, SGD, JPY
    Response SLA: p99 < 5s | Uptime: 99.7%
    [View Transaction History] [Send RFQ]

Step 3 — Initiate RFQ
  [Send RFQ] →
  RFQ form (structured schema):
    - Item: Steel Plate Grade A36
    - SKU: [optional]
    - Quantity: 1,000 units
    - Unit: MT (metric ton)
    - Delivery location: Singapore Port
    - Required by: 2026-03-30
    - Payment terms: Net-30
    - Notes: [optional freetext, 500 char max]
  [Send RFQ]

  System:
    - Records RFQ initiation on-chain (Tier 1 transaction fee: $0.10)
    - Routes RFQ to Baker Steel's A2A endpoint
    - Returns: Transaction ID: HAR-2026-031405-0042

Step 4 — Await Response (SLA: p99 5s for automated agents)
  Real-time status panel:
    HAR-2026-031405-0042 | Status: AWAITING RESPONSE
    Sent to: Baker Steel Procurement Agent
    [↻ Refreshing... 3s]

  Baker Steel's agent responds:
    Unit price: USD 45.50/MT
    Lead time: 14 days
    Incoterms: CIF Singapore
    Payment terms: Net-30 accepted
    Valid until: 2026-03-12

  Status updates: QUOTE_RECEIVED
  Notification: email + in-app alert to procurement manager

Step 5 — Accept or Counter-Propose
  [Review Quote] →
  Quote summary displayed with comparison to last 3 market prices on network:
    Baker quote: $45.50/MT
    Network median (APAC steel, last 30 days): $44.20/MT
    [This quote is 3% above market median]

  Options:
    [Accept Quote] → advances to PO Placement (Flow 3)
    [Counter-Propose] → opens counter-offer form
    [Decline] → closes RFQ (transaction recorded as ABANDONED)

  Actor selects [Counter-Propose]:
    Counter price: $44.00/MT
    Note: "Matching market rate; flexible on delivery terms"
    [Send Counter-Proposal]
    Tier 1 event recorded on-chain: COUNTER_PROPOSED

Step 6 — Negotiation Loop (if applicable)
  Baker Steel's agent evaluates counter-proposal:
    Internal logic: $44.00 below floor price ($44.50); offer $44.75 as final
    Counter: $44.75/MT, delivery extended to 16 days
    Note: "Final offer. Price includes insurance to Singapore port."

  Actor evaluates: $44.75 within budget → [Accept at $44.75]
  Status: QUOTE_ACCEPTED
  On-chain record: RFQ HAR-2026-031405-0042 ACCEPTED at $44.75/MT × 1,000MT = $44,750

Human approval gate triggered (above $5,000 threshold — default configurable per tenant):
  [Approval Request → Procurement Manager John Tan]
  Email: "ACME Procurement Agent has negotiated a purchase from Baker Steel.
  Item: 1,000MT Steel Plate A36 | Price: $44,750
  [Approve and Send PO] [Reject] [Modify Terms]"
  John Tan: [Approve and Send PO]
```

---

## Flow 3: Autonomous PO Placement and Confirmation

> **Phase note**: This flow represents **Phase 2+ behavior**. Phase 0-1 behavior differs: HAR signs transactions on behalf of agents (no BYOK/DID); audit log is a traditional signed chain (no blockchain). Features requiring BYOK, DID headers, or blockchain records are Phase 2+ only.

**Actor**: Procurement Agent (with human approval)
**Goal**: Convert accepted RFQ into a binding PO
**Preconditions**: Quote accepted; human approval received (Flow 2 Step 6)

```
Step 1 — PO Generation
  System generates PO from accepted RFQ:
    PO Number: ACME-PO-2026-0441
    To: Baker Steel (Singapore) Pte Ltd
    From: ACME Corporation Pte Ltd
    Item: Steel Plate Grade A36 | Qty: 1,000 MT | Price: $44.75/MT
    Total: $44,750.00 USD
    Delivery: CIF Singapore Port | By: 2026-03-30
    Payment: Net-30 from delivery confirmation
    Both parties' DID + public keys in header

Step 2 — PO Transmission (A2A)
  ACME's agent sends PO to Baker Steel's A2A endpoint:
    Signed with ACME's agent private key
    Encrypted with Baker Steel's agent public key
    Contains: structured PO JSON + human approval evidence

  HAR records: PO_SENT on-chain
  Baker Steel's agent receives + verifies signature
  Baker Steel's agent: matches to pending RFQ HAR-2026-031405-0042 → auto-accepts

Step 3 — PO Acknowledgement
  Baker Steel's agent signs acknowledgement:
    "PO ACME-PO-2026-0441 accepted. Confirmation #BS-2026-1872.
    Production slot allocated. Delivery confirmed by 2026-03-28."
  Sends signed ACK to ACME's agent

  HAR records: PO_ACKNOWLEDGED on-chain
  Transaction state: COMMITTED
  Both parties receive: "Purchase order is confirmed and binding.
  HAR Transaction ID: HAR-2026-031405-0042
  Blockchain record: Block #48291, Hash: 0x3f9a..."

Step 4 — ERP Integration (automatic)
  ACME's reconciliation agent:
    Reads HAR transaction record
    Creates SAP purchase order: PO-9981 linked to HAR-2026-031405-0042
    Status: "Awaiting Delivery"

  Baker Steel's reconciliation agent (if integrated):
    Creates SAP sales order linked to acknowledgement BS-2026-1872
```

---

## Flow 4: Delivery Confirmation and Payment Settlement

> **Phase note**: This flow represents **Phase 2+ behavior**. Phase 0-1 behavior differs: HAR signs transactions on behalf of agents (no BYOK/DID); audit log is a traditional signed chain (no blockchain). Features requiring BYOK, DID headers, or blockchain records are Phase 2+ only.

**Actor**: Both agents, with finance team notification
**Goal**: Confirm delivery and trigger payment

```
Step 1 — Delivery Confirmation
  Delivery date: 2026-03-27
  Baker Steel logistics integration sends event: "Goods delivered to Singapore Port"
  Baker Steel's agent submits DELIVERY_CONFIRMATION:
    PO: ACME-PO-2026-0441 | Date: 2026-03-27 | Location: Singapore Port
    Quantity: 1,000 MT | Reference: AWB/BL number
    Quality report: [attached IPFS hash: QmXc3...]
  HAR records: DELIVERY_CONFIRMED on-chain

Step 2 — ACME Verifies Delivery
  ACME's agent receives delivery confirmation
  Validates: quantity matches PO (1,000MT ✓) | delivery date within window (✓)
  Triggers: goods receipt posting in SAP (GR against PO-9981)
  HAR status: DELIVERY_ACCEPTED

Step 3 — Invoice Submission
  Baker Steel's agent submits invoice:
    Invoice #BS-2026-INV-1002
    Amount: $44,750.00 USD + $3,132.50 GST (7%) = $47,882.50
    Payment terms: Net-30 from delivery (due: 2026-04-26)
    Bank details: [encrypted, not on-chain]
  HAR records: INVOICE_SUBMITTED on-chain

Step 4 — Invoice Matching (Automatic)
  ACME's reconciliation agent:
    Matches invoice to PO-9981 and GR in SAP
    3-way match: PO ✓ | Goods Receipt ✓ | Invoice ✓
    GST calculation: correct (7% SG rate) ✓
    Posts: Accounts Payable entry in SAP
    Flags: "Cleared for payment on 2026-04-26"
  HAR records: INVOICE_MATCHED on-chain

Step 5 — Payment (Finance Team Approval)
  Finance team receives notification: "Payment due 2026-04-26 for HAR-2026-031405-0042, $47,882.50"
  Finance team approves payment instruction
  Payment via bank wire (external to HAR)
  ACME's agent posts: PAYMENT_INITIATED on-chain with reference

Step 6 — Payment Confirmation and Closure
  Baker Steel's agent confirms: payment received
  HAR records: PAYMENT_CONFIRMED, TRANSACTION_COMPLETE
  Trust score update: both agents +1 completed transaction; dispute rate unchanged
  Both receive: "Transaction HAR-2026-031405-0042 is complete and closed."
```

---

## Flow 5: External Developer Registers Non-mingai Agent

**Actor**: Developer at a non-mingai company
**Goal**: Publish a custom-built agent to the HAR registry using the open SDK

```
Step 1 — Developer Registration
  developer.agent-registry.mingai.ai → [Sign Up as Developer]
  Email, company name, use case description
  Agree to HAR Developer Terms (includes: Agent Card schema compliance, A2A protocol compliance, no spam/fraud)
  Account created → receive API credentials

Step 2 — Download SDK
  [Get Started] → Documentation page
  pip install har-sdk  OR  npm install @mingai/har-sdk  OR  (Maven: com.mingai:har-sdk)
  SDK includes: agent card builder, A2A message handler, signature utility, test harness

Step 3 — Build Agent Card
  # Python example
  from har_sdk import AgentCard, TransactionType

  card = AgentCard(
      name="Baker Steel Sales Agent",
      description="Handles steel product RFQs and purchase orders",
      owner_company="Baker Steel (Singapore) Pte Ltd",
      transaction_types=[TransactionType.RFQ_RESPONSE, TransactionType.PO_ACCEPTANCE],
      industries=["manufacturing", "steel"],
      languages=["en", "zh"],
      a2a_endpoint="https://agents.bakersteel.com/sales/v1/a2a",
      sla_response_time_p99_ms=5000
  )

Step 4 — Test with HAR Sandbox
  har_sdk test --card card.json --sandbox
  # Runs simulated transaction flows against HAR sandbox
  # Tests: signature validation, A2A protocol compliance, response schema

Step 5 — Submit for Review
  [Developer Portal] → [Submit Agent Card]
  Uploads card.json + A2A endpoint URL
  Automated checks:
    ✓ JSON schema validation
    ✓ A2A endpoint health check (GET /health → 200 OK)
    ✓ Test transaction handshake (sandbox RFQ → response)

  If all pass: "Agent Card approved. Proceed to KYB verification."

Step 6 — KYB Verification
  Same as Flow 1 Step 4 (Stripe Identity)
  KYB required for Level 1 trust (Tier 2+ transactions)

  After KYB clearance:
  "Baker Steel Sales Agent is live on the global registry.
  Initial trust score: 40 (Level 1 KYB Verified)"
```

---

## Flow 6: Dispute Filing and Resolution

**Actor**: Buying Agent Operator, Selling Agent Operator, HAR Dispute System
**Goal**: Resolve a quantity dispute after delivery
**Precondition**: Transaction HAR-2026-031405-0042 is COMPLETED; delivery confirmed; payment made

```
Step 1 — Dispute Initiation
  ACME quality control discovers: received 950MT, not 1,000MT (50MT short)
  ACME Procurement Manager: [Registry] → [Transaction History] → HAR-2026-031405-0042 → [File Dispute]

  Dispute form:
    Type: [Quantity Discrepancy ▼]
    Claimed amount: 50MT short | Value: $2,237.50
    Evidence:
      [Upload weighbridge certificate] → IPFS hash: QmYd7...
      [Upload delivery note showing 950MT] → IPFS hash: QmWe4...
    Description: "Delivery received 950MT vs PO quantity 1,000MT. See attached weighbridge certificate."
  [Submit Dispute]

  HAR records: DISPUTE_FILED on-chain
  Baker Steel's agent notified immediately

Step 2 — Automated Stage 1 (0-24 hours)
  HAR smart contract evaluates:
    PO quantity: 1,000MT ✓
    Delivery confirmation (signed by Baker Steel): 1,000MT ← discrepancy flagged
    ACME's evidence: weighbridge 950MT

  Automated finding: "Delivery confirmation and weighbridge certificate conflict.
  Cannot auto-resolve. Advancing to AI mediation."

  HAR records: DISPUTE_ESCALATED_TO_AI

Step 3 — AI Mediation (24-72 hours)
  HAR dispute AI reviews:
    All on-chain transaction records
    Evidence submitted by both parties (accessed via IPFS hashes)
    Applicable Incoterms (CIF: risk transfers at loading port)
    Baker Steel's transaction history (dispute rate: 0.3%)
    ACME's history (previous disputes: 0)

  AI recommendation generated:
    "Evidence supports ACME's claim. Baker Steel's delivery confirmation appears to contain an error.
    Recommended resolution: Baker Steel issues credit note for 50MT at $44.75/MT = $2,237.50.
    Alternative: Baker Steel ships the 50MT balance within 5 business days at original pricing.
    Confidence: 78%."

  Both parties presented with recommendation:
    [Accept Credit Note] [Accept Shipment of Balance] [Escalate to Human Arbitration]

  Baker Steel's agent: reviews with human → [Accept Credit Note - we made a loading error]
  ACME's agent: [Accept Credit Note]

  HAR records: DISPUTE_RESOLVED_AI on-chain
  Baker Steel submits credit note: $2,237.50
  Trust score: Baker Steel -0.5 (resolved dispute; no penalty for honest error)

Step 4 — Closure
  Both parties: "Dispute HAR-DISP-2026-0028 resolved.
  Credit note $2,237.50 applied to your next invoice.
  Transaction history updated."
```

---

## Flow 7: Platform Admin Monitors Registry Health

**Actor**: Platform Admin (mingai)
**Goal**: Review registry activity, identify problem agents, manage trust scores

```
Step 1 — Registry Dashboard
  [Platform Admin] → [Registry Dashboard]

  Overview:
    Total registered agents: 87
    KYB verified: 61 (70%)
    Active (transaction in last 30 days): 34
    Transactions this month: 1,842 (↑ 23% MoM)
    Dispute rate: 0.4% (healthy)
    Pending KYB: 12
    Suspended agents: 2

Step 2 — Flag Review
  [Flagged Agents] tab:
    - TechCorp Sales Agent: 3 disputes in 14 days (dispute rate: 8%) [Review]
    - Unknown Supplier v1: failed 4 consecutive A2A health checks [Review]
    - FastShip Logistics: KYB expired 7 days ago (renewal reminder sent) [Review]

Step 3 — Trust Score Adjustment
  Platform Admin reviews TechCorp Sales Agent:
    Transaction history: 38 transactions, 3 disputes
    Dispute reasons: all customer claims of "wrong quantity delivered"
    Baker Steel (reputable) is counterparty in 2 of 3 disputes

  Admin action: [Suspend Pending Investigation]
  Reason: "Dispute rate exceeds 5% threshold; under review"
  System: trust score → 0, agent hidden from search, existing transactions unaffected
  TechCorp notified: "Your agent has been suspended. Contact support@mingai.ai"

Step 4 — KYB Renewal Management
  [KYB Expiry Queue]:
    FastShip Logistics: expired 7 days ago
    Action: [Send Reminder] [Suspend After 14 Days]
  Platform Admin: [Send Reminder] → automated email to FastShip admin
  If 14 days pass without renewal: auto-suspend applied
```

---

## Flow 8: ERP Reconciliation Review (Monthly)

**Actor**: Finance Team member
**Goal**: Review HAR transactions against SAP entries; resolve exceptions

```
Step 1 — Reconciliation Dashboard
  [Finance] → [HAR Reconciliation] → [November 2026]

  Summary:
    Total HAR transactions: 142
    Auto-matched to SAP: 137 (96.5%)
    Exceptions requiring review: 5
    Total transaction value: $2,847,320
    HAR fees paid: $7,118 (0.25%)

Step 2 — Exception Review
  Exception 1:
    HAR-2026-110902-0019 | PO $87,500 | Status: No SAP PO found
    Reason: SAP PO was created in wrong company code (1000 vs 2000)
    [Assign to SAP PO] → [Select PO: 10042-2000] → [Match]
    → Auto-matched. Exception cleared.

  Exception 2:
    HAR-2026-113001-0087 | Invoice $12,400 | Status: Amount mismatch
    HAR amount: $12,400 | SAP invoice: $12,800
    Reason: FX conversion applied in SAP (SGD to USD) vs USD in HAR
    [Adjust SAP entry] [Accept HAR amount] [Flag for AP team]
    Finance team: [Flag for AP team] → AP ticket created

Step 3 — Export Report
  [Export to Excel] → reconciliation_nov2026.xlsx
  Contains: all 142 transactions, match status, exception notes
  Used for: month-end close, audit preparation
```

---

## Edge Cases

**EC-1: A2A endpoint goes down during active negotiation**

- Baker Steel's endpoint returns 503 during negotiation
- HAR retries 3× with exponential backoff (5s, 15s, 45s)
- If all retries fail: transaction state → SUSPENDED; both parties notified
- HAR holds state for 24 hours; Baker Steel can reconnect and resume
- After 24 hours: transaction expires; ACME receives: "Negotiation expired — Baker Steel's system was unavailable"
- No fee charged for failed transactions

**EC-2: AI agent commits to a price it was not authorized for**

- ACME's AI agent accepts $100/MT (correct is $45/MT) due to LLM error
- This is caught by the human approval gate (above $5,000 default threshold)
- Human sees: $100,000 PO for 1,000MT steel plate — recognizes error
- Human selects [Reject]
- Transaction state: REJECTED by buyer
- No on-chain commitment made (rejection occurs before PO_SENT)
- ACME reviews agent configuration to identify why agent accepted incorrect price

**EC-3: KYB verification reveals sanctions list match**

- During KYB, Stripe Identity flags company as potential sanctions match
- HAR: immediate hold on registration (not rejected — may be false positive)
- Platform Admin receives alert: "Sanctions screening flag for [Company X] — requires manual review"
- HAR legal team reviews (24-48 hours): determine false positive vs. true match
- True match: reject registration; do not disclose reason beyond "KYB not approved"
- False positive: manually clear; registration proceeds

**EC-4: Dispute escalates to human arbitration and loser refuses to comply**

- Human arbiter rules: Baker Steel owes credit note
- Baker Steel disputes the ruling (contract law angle)
- HAR records the ruling on-chain (immutable)
- HAR freezes Baker Steel's trust score at 50 until compliance
- If non-compliance for 30 days: Baker Steel suspended from registry
- Legal enforcement: parties must pursue in their own jurisdiction (HAR is not a court)
- HAR ToS requires binding arbitration agreement as condition of registration

**EC-5: Third-party developer publishes malicious agent (spam/fraud)**

- Agent sends mass capability queries to harvest agent card data
- HAR rate limiter: max 100 queries/minute per agent (Level 0: 10/minute)
- Rate limit hit → agent flagged for review
- Automated suspension after 3× rate limit violations in 24 hours
- Developer account suspended; agent removed from registry
- KYB identity on file — enables legal recourse if needed

**EC-6: mingai tenant's workspace agent is deleted after being published**

- Tenant deletes the workspace agent that was publishing to the registry
- HAR detects: A2A endpoint health check fails
- HAR status: agent marked UNAVAILABLE (not deleted — transaction history preserved)
- Tenant admin notified: "Your published agent [Agent Name] is no longer responding"
- After 72 hours UNAVAILABLE: listing hidden from search (not deleted)
- Tenant can republish or permanently deregister
- Historical transaction records remain immutable on-chain
