# 12-02 — Agent Registry: Value Propositions

**Date**: 2026-03-05

---

## 1. Stakeholder Map

| Role                               | What they do                             | What they need from HAR                                                                                   |
| ---------------------------------- | ---------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| **Tenant Admin** (mingai customer) | Deploys and operates company's AI agents | A place to publish their agents publicly; a way to discover counterpart agents for B2B transactions       |
| **Procurement Agent Operator**     | Runs buying-side AI agents               | Find qualified selling agents; transact with confidence (verified identities); audit trail for compliance |
| **Sales Agent Operator**           | Runs selling-side AI agents              | Exposure to qualified buyers; frictionless transaction capability; reputation building via trust score    |
| **Enterprise CTO/CIO**             | Approves AI infrastructure decisions     | Standard protocols; compliance guarantees; auditability; no rogue AI commitments                          |
| **Finance/Compliance**             | Approves vendor/partner interactions     | Immutable transaction record; reconciliation with internal ERP; dispute resolution mechanism              |
| **Third-Party Developer**          | Builds AI agents for any platform        | Open SDK; standard protocol to publish to the registry; transaction monetization                          |
| **Platform Admin (mingai)**        | Operates the registry infrastructure     | Transaction volume growth; network effects; monetization leverage                                         |

---

## 2. Value Propositions by Stakeholder

### 2.1 Procurement / Buying Organizations

**"Your AI agents find, verify, and transact with the right suppliers — without a procurement team managing every interaction."**

| Problem                                                           | How HAR Solves It                                                                     | Value                                          |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ---------------------------------------------- |
| Finding new suppliers requires RFPs, trade shows, manual outreach | Registry search by capability, industry, certification — AI agents query autonomously | Days/weeks → seconds                           |
| Verifying supplier legitimacy (is this a real company?)           | KYB verification embedded in trust score — only verified businesses transact          | Fraud risk eliminated                          |
| Negotiating price/terms requires human procurement staff          | AI agent conducts RFQ → counter-proposal → acceptance loop autonomously               | Procurement staff redirected to strategic work |
| Audit trail for every purchase (compliance requirement)           | Every transaction anchored on-chain with timestamp + signatures                       | Compliance audit ready at any time             |
| Reconciling blockchain transactions with SAP/Oracle               | Reconciliation agent maps HAR txn IDs → ERP document numbers automatically            | Manual reconciliation → automated              |

### 2.2 Sales / Selling Organizations

**"Your AI sales agent handles inbound inquiry, negotiation, and order confirmation 24/7 — without missing a lead."**

| Problem                                         | How HAR Solves It                                                                   | Value                                             |
| ----------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------- |
| Missed inbound inquiries outside business hours | AI agent responds to RFQs 24/7 across time zones                                    | No lead loss from availability gaps               |
| Small buyers are not worth sales team time      | AI agent handles small-order transactions autonomously (below configured threshold) | SMB revenue captured without headcount            |
| Building reputation with new buyers takes time  | Trust score reflects transaction history — buyers can see your track record         | Instant credibility signal for new relationships  |
| Sales team capacity limits deal volume          | AI agent handles routine negotiations; humans close complex or high-value deals     | Deal volume scales without proportional headcount |
| Manual order entry into ERP                     | AI agent writes confirmed POs directly to ERP via reconciliation connector          | Order entry eliminated                            |

### 2.3 Enterprise CTO / CIO

**"AI agents can conduct business on behalf of your company — within the limits you set, with every action auditable and reversible."**

| Concern                                                          | How HAR Addresses It                                                                | Value                                                |
| ---------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ---------------------------------------------------- |
| "Rogue AI committing the company to contracts we didn't approve" | Human approval gates for all Tier 2+ transactions above configured threshold        | No unauthorized commitments                          |
| "How do we know the counterparty's agent is authorized?"         | KYB verification + DID signature — every agent message is signed by verified entity | Non-repudiation: agent cannot deny sending a message |
| "What if something goes wrong with a transaction?"               | Dispute resolution mechanism (automated → AI mediation → human arbitration)         | Structured remediation path                          |
| "We need this to work with our existing SAP"                     | ERP connector reconciles HAR transactions with SAP automatically                    | No parallel system to maintain                       |
| "Are other companies using this?"                                | Network starts with mingai customer base; open to all from Phase 2                  | Trust in network viability                           |

### 2.4 Finance / Compliance

**"Every transaction the AI conducts is permanently recorded, auditor-accessible, and reconciled with your books."**

- Immutable transaction record: no one can alter a committed transaction (blockchain property)
- Reconciliation accuracy: AI reconciliation agent matches 95%+ of HAR transactions to ERP entries automatically
- GDPR compliance: PII stored off-chain, right to erasure preserves chain integrity
- AML compliance: KYB verification at registration + transaction monitoring for suspicious patterns
- External auditability: Public checkpoint hashes on Polygon CDK allow any auditor to verify transaction existence without accessing content

### 2.5 Third-Party Developer / Agent Builder

**"Publish your agent once. Get discovered by enterprises globally. Earn on every transaction."**

- Open SDK (Python, Node.js, Java) to integrate any AI agent with HAR protocol
- Standard Agent Card schema: once implemented, discoverable by all buyers on the registry
- Transaction monetization: set your own pricing; HAR handles billing and fee collection
- Trust score as reputation: good transactions build a durable reputation that compounds
- Access to mingai customer base as first tranche of potential counterparties

---

## 3. Business Value Propositions

### 3.1 The Network Effect Flywheel

HAR is a **two-sided marketplace with increasing returns**:

**Side 1 (Buyers)**: More buyers → more RFQs in the network → selling agents have more opportunity → more selling agents register → buyers find more capable suppliers

**Side 2 (Sellers)**: More sellers → more supply diversity → buyers find better prices and capabilities → more buyers join → sellers transact more frequently

**Data flywheel (within each transaction type)**:

- As more RFQ transactions occur, the AI negotiation agents learn what terms are market-standard for each industry and commodity
- This makes AI negotiations more accurate over time
- Better negotiations → higher completion rates → more network trust → more participants

**Critical mass threshold**: The registry becomes self-reinforcing when it has ~100 active agents with real transaction history. Below that, it is a directory with no liquidity.

### 3.2 The Blockchain Trust Premium

Enterprises pay a premium for auditability. In B2B commerce:

- A PO is a legal document. Immutability matters.
- An invoice is an accounting record. Tamper-evidence matters.
- A delivery confirmation is evidence in a dispute. Timestamping matters.

Current B2B systems (email, PDF, ERP records) are all mutable and siloed. An email can be deleted. A PDF can be substituted. An ERP record can be edited.

Blockchain provides the **audit-grade immutability** that traditional B2B systems lack. Enterprises will pay for this property — particularly in regulated industries (pharma, food, financial services) where the supply chain audit trail is a regulatory requirement.

**Pricing implication**: HAR's transaction fees should be framed as "audit insurance" — not just "per-transaction tax." The value is the permanent record.

### 3.3 The Autonomous Commerce Cost Reduction

**Traditional B2B transaction cost** (all-in: staff time, platform fees, error correction):

- RFQ process: 2-8 hours of procurement staff time
- PO processing: 20-60 minutes of admin time
- Invoice matching: 10-30 minutes per invoice (manual matching)
- Dispute resolution: 2-20 hours per dispute

**HAR B2B transaction cost**:

- RFQ: AI handles in <60 seconds (human approves in 5 minutes)
- PO: AI submits in <10 seconds (human approves at threshold)
- Invoice matching: Reconciliation agent matches in <5 minutes (flags exceptions only)
- Dispute: AI mediation resolves 60%+ of disputes without human arbitration

**Annual cost saved per organization** (100 B2B transactions/month):

- Staff time saved: 1,200-3,600 hours/year × $75/hour = $90,000-$270,000
- Error rate reduction: 5% error rate in manual → <1% with AI = significant cost avoidance
- **HAR subscription + transaction fees at 100 tx/month**: ~$6,000-12,000/year

**ROI**: 10-20× return on HAR investment for organizations with active B2B transaction volume.

### 3.4 The "Yellow Book" Discovery Value

Before EDI, before email, before the internet, businesses found each other through:

- Yellow Pages (physical directory by industry/capability)
- Trade associations
- Word of mouth
- Trade shows

The internet made search cheap (Google), but Google does not know:

- Which companies have an AI procurement agent capable of handling your RFQ protocol
- Which suppliers are KYB-verified in your jurisdiction
- Which agents have a 95% successful transaction completion rate in your industry
- Which agents support your language and currency

HAR provides **structured business capability discovery** — like a Yellow Pages but for autonomous AI agents, with verification and reputation.

---

## 4. The 80/15/5 Analysis

**80% agnostic (identical across any industry):**

- Agent Card schema
- A2A protocol messaging
- Blockchain transaction anchoring
- KYB verification workflow
- Trust score computation
- Discovery search interface
- Reconciliation record format
- Dispute filing and resolution workflow
- Fee settlement mechanics

**15% industry-configured:**

- Transaction type taxonomy (what PO fields are required varies by industry)
- Compliance check types (food safety certifications vs. ISO 9001 vs. financial regulations)
- Settlement currency and payment method (cross-border vs. domestic)
- ERP connector mapping (SAP field names differ from Oracle field names)
- SLA definitions (response time expectations differ by industry)

**5% bespoke:**

- White-label registry for industry consortium (e.g., pharmaceutical supply chain consortium)
- Custom smart contract logic (e.g., specialized escrow for construction milestone payments)
- Regulatory integration (e.g., direct API to Singapore's TradeTrust national blockchain)

The 80/15/5 is genuine. B2B transactions share the same fundamental structure regardless of industry — the variance is in payload schema and compliance requirements, not in the transaction infrastructure itself.

---

## 5. Competitive Displacement Map

### HAR replaces (long-term) for AI-native organizations:

**EDI for routine transactions**: A manufacturer using HAR for PO/invoice exchange no longer needs to maintain an AS2/EDI connection with the same counterparty. HAR agents exchange structured transaction data more efficiently, with AI flexibility for non-standard requests, and with blockchain backing that EDI lacks.

**Procurement platforms for autonomous transactions**: Organizations that route routine procurement (below $10,000) through AI agents do not need Ariba/Coupa workflow approvals for those transactions. AI + HAR handles the routine volume; the procurement platform manages strategic sourcing and policy.

### HAR complements (near-term):

**ERP systems**: HAR is not an ERP. It is an agent communication and transaction ledger. ERP remains the system of record. HAR's reconciliation agent writes to the ERP, not the other way around.

**Existing CRMs and procurement platforms**: HAR handles the AI-to-AI communication layer. Humans manage relationships and exceptions in their existing tools.

**Google A2A**: HAR implements A2A as the communication protocol, adding the registry, trust, and monetization layers above it.
