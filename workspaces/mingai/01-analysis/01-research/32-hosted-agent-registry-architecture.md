# 32 — Hosted Agent Registry: Architecture Research

**Date**: 2026-03-05
**Scope**: Technical architecture for a globally published B2B agent registry with blockchain-backed transaction ledger, B2B transaction taxonomy, reconciliation layer, and monetization model.

---

## 1. Concept Definition

The Hosted Agent Registry (HAR) is a public marketplace infrastructure where:

1. Organizations publish **agent cards** — structured descriptions of their AI agents' capabilities, interfaces, and pricing
2. Other organizations **discover** agents by capability, industry, or transaction type
3. Agents **transact autonomously** (negotiate, exchange, fulfill) using A2A protocols
4. Every transaction is **anchored to a permissioned blockchain** for audit immutability
5. The platform **monetizes** as a percentage of transaction value flowing through the network

This is conceptually the intersection of:

- An EDI network (electronic B2B document exchange) — but for AI agents
- An API marketplace (Postman, RapidAPI) — but with autonomous agents, not passive endpoints
- A payments network (SWIFT, Visa B2B) — but with programmable smart contracts
- A business directory (LinkedIn Company Pages, D&B) — but with machine-readable capability profiles

**The core insight**: As AI agents become autonomous business actors, the infrastructure for them to discover, trust, and transact with each other does not exist. HAR is that infrastructure.

---

## 2. Agent Card Standard

Each agent published to the registry is described by an **Agent Card** — a structured JSON document:

```json
{
  "agent_id": "did:mingai:tenant-acme:procurement-agent-v2",
  "version": "2.1.0",
  "owner": {
    "tenant_id": "acme-corp",
    "legal_name": "ACME Corporation Pte Ltd",
    "jurisdiction": "SG",
    "verification_level": "KYB_VERIFIED"
  },
  "identity": {
    "did": "did:mingai:tenant-acme:procurement-agent-v2",
    "public_key": "ed25519:4GqUmgPz...",
    "attestations": ["kyb_verified", "iso27001_certified", "gdpr_compliant"]
  },
  "capabilities": {
    "transaction_types": [
      "RFQ_RESPONSE",
      "PO_ACCEPTANCE",
      "INVOICE_SUBMISSION",
      "PAYMENT_TERMS_NEGOTIATION"
    ],
    "industries": ["manufacturing", "procurement", "logistics"],
    "languages": ["en", "zh", "ja"],
    "currencies": ["USD", "SGD", "JPY"]
  },
  "endpoints": {
    "a2a_endpoint": "https://agents.acme.com/procurement/v2/a2a",
    "webhook_url": "https://agents.acme.com/procurement/v2/webhooks",
    "health_check": "https://agents.acme.com/procurement/v2/health"
  },
  "sla": {
    "response_time_p99_ms": 5000,
    "uptime_sla_percent": 99.5,
    "supported_hours": "24x7"
  },
  "pricing": {
    "model": "per_transaction",
    "rfq_response_fee_usd": 0.5,
    "negotiation_session_fee_usd": 5.0,
    "contract_execution_fee_basis_points": 25
  },
  "trust_score": 87,
  "total_transactions": 14392,
  "created_at": "2025-06-01T00:00:00Z",
  "updated_at": "2026-02-28T14:22:00Z"
}
```

**Agent Card fields**:

- **DID (Decentralized Identifier)**: Globally unique, owner-controlled identity for the agent. Follows W3C DID Core spec.
- **Public key**: Used to verify signatures on messages from this agent. Enables non-repudiation.
- **Attestations**: Verifiable credentials from trusted issuers (KYB = Know Your Business, ISO 27001, GDPR DPA).
- **Capabilities**: Machine-readable capability taxonomy — what transaction types this agent handles.
- **Trust score**: Computed from transaction history, dispute rate, uptime, and attestation depth (0-100).

---

## 3. Blockchain Architecture Selection

### 3.1 Requirements

| Requirement      | Description                                                                   |
| ---------------- | ----------------------------------------------------------------------------- |
| Immutability     | Transaction records cannot be altered after anchoring                         |
| Finality         | Transactions must confirm within 5-10 seconds                                 |
| Cost             | Per-transaction cost must be <$0.01 for commercial viability                  |
| Privacy          | Transaction details should not be publicly visible (B2B data confidentiality) |
| Compliance       | Must support KYB/KYC, GDPR Article 17 (right to erasure), AML checks          |
| Throughput       | Must handle 1,000+ transactions/second at scale                               |
| Interoperability | Must be auditable by external parties (customers, regulators)                 |

### 3.2 Candidate Evaluation

**Option A: Ethereum Mainnet**

- Finality: ~12 seconds
- Cost: Gas varies, $2-50/transaction (unacceptable for <$0.01 requirement)
- Privacy: None (public)
- Compliance: No KYB/AML controls
- Verdict: REJECTED — cost and privacy disqualify for B2B enterprise

**Option B: Ethereum Layer 2 (Polygon, Arbitrum)**

- Finality: 1-3 seconds
- Cost: $0.001-0.01/transaction (acceptable)
- Privacy: Same as Ethereum mainnet (public)
- Compliance: No native KYB/AML controls
- Verdict: REJECTED — privacy and compliance gaps

**Option C: Hyperledger Fabric (Permissioned)**

- Finality: <1 second
- Cost: Infrastructure cost, no per-transaction gas ($0.0001 estimated)
- Privacy: Channels enable data isolation between participants
- Compliance: KYB/KYC enforced at membership level; GDPR data on off-chain storage
- Throughput: 3,000+ TPS
- Verdict: STRONG CANDIDATE — purpose-built for enterprise B2B

**Option D: R3 Corda (Permissioned)**

- Finality: <5 seconds
- Cost: Infrastructure cost only
- Privacy: Point-to-point: only parties to a transaction see the data
- Compliance: Financial-grade KYC/AML, used by SWIFT GPI, HSBC
- Throughput: 1,700 TPS
- Verdict: STRONG CANDIDATE — gold standard for financial B2B, strong in regulated industries

**Option E: Polygon CDK (App Chain)**

- Finality: 2-5 seconds
- Cost: ~$0.001/transaction
- Privacy: Configurable privacy via ZK proofs (Polygon zkEVM)
- Compliance: Smart contract-enforced access control; GDPR requires off-chain PII
- Throughput: 2,000+ TPS
- Verdict: VIABLE CANDIDATE — modern ZK-based privacy, EVM compatible (tooling richness)

### 3.3 Recommended Architecture: Hybrid

**Primary ledger**: Hyperledger Fabric (permissioned consortium)

- Membership: All HAR participants are registered members (KYB required)
- Channel design: One channel per transaction pair (ACME ↔ BAKER bilateral privacy)
- Chaincode (smart contracts): Transaction state machine, dispute resolution, fee settlement
- Ordering service: Raft consensus (crash fault tolerant, 3-of-5 orderer nodes)
- Anchor peers: mingai operates 3 anchor peers; enterprise members operate optional peers

**Public proof layer**: Ethereum (Polygon CDK app-chain)

- Periodic checkpoint anchoring: Fabric block hash → Polygon chain every 100 blocks
- Purpose: External auditability without exposing transaction details
- Public verifiability: Auditors can verify "transaction X occurred at time T" without seeing content

**Rationale**: Fabric provides enterprise-grade privacy and throughput. The Polygon checkpoint layer provides regulatory transparency — auditors and counterparties can verify integrity without accessing the full ledger.

---

## 4. B2B Transaction Taxonomy

### 4.1 Transaction Type Classification

**Tier 1 — Information Exchange (no financial commitment)**

| Type               | Description                        | Example                                                   | Typical Latency |
| ------------------ | ---------------------------------- | --------------------------------------------------------- | --------------- |
| CAPABILITY_QUERY   | Discover what an agent can do      | "Can you accept purchase orders for raw materials?"       | <1s             |
| RFQ                | Request for quote                  | "Price for 1,000 units of SKU-4421 delivered by March 30" | 1-60s           |
| CATALOG_BROWSE     | Browse available products/services | "Show me your current steel plate catalog"                | <1s             |
| COMPLIANCE_CHECK   | Verify supplier certifications     | "Are you ISO 9001 certified for aerospace parts?"         | <2s             |
| AVAILABILITY_CHECK | Check stock or capacity            | "Inventory for SKU-4421 in SG warehouse"                  | <2s             |

**Tier 2 — Commitment Initiation (binding intent, no funds movement)**

| Type                 | Description                    | Example                                          | Typical Latency |
| -------------------- | ------------------------------ | ------------------------------------------------ | --------------- |
| PO_PLACEMENT         | Place a purchase order         | Order for 1,000 units at $45/unit, Net-30        | 2-30s           |
| CONTRACT_NEGOTIATION | Negotiate terms autonomously   | Iterate on delivery terms, Incoterms, warranties | 30s-5min        |
| SERVICE_BOOKING      | Book a service appointment     | Schedule 3PL pickup for March 28                 | 5-30s           |
| NDA_EXCHANGE         | Exchange signed NDAs           | Bilateral NDA for contract negotiation           | 10-60s          |
| QUOTE_ACCEPTANCE     | Accept a received RFQ response | Accept BAKER's quote at $44.50/unit, MOQ 500     | <2s             |

**Tier 3 — Financial Transactions (funds movement or equivalent)**

| Type                   | Description                       | Example                                           | Typical Latency |
| ---------------------- | --------------------------------- | ------------------------------------------------- | --------------- |
| INVOICE_SUBMISSION     | Submit invoice for payment        | Invoice #2026-0042 for PO-9981: $44,500 + GST     | 2-10s           |
| PAYMENT_INITIATION     | Trigger payment instruction       | Authorize payment via BankAPI to BAKER's account  | 5-30s           |
| ESCROW_RELEASE         | Release smart contract escrow     | Release $44,500 on confirmed delivery             | 5-30s           |
| CREDIT_NOTE            | Issue credit for returns/disputes | $4,450 credit for defective batch                 | 5-30s           |
| PAYMENT_RECONCILIATION | Match payments to invoices        | Reconcile wire transfer with outstanding invoices | 2-10s           |

**Tier 4 — Post-Transaction (fulfilment and verification)**

| Type                  | Description                      | Example                                        | Typical Latency |
| --------------------- | -------------------------------- | ---------------------------------------------- | --------------- |
| DELIVERY_CONFIRMATION | Confirm physical delivery        | Goods received at SG warehouse, March 29       | 2-10s           |
| QUALITY_REPORT        | Submit quality/inspection report | Batch #B2026-0042 passes QC inspection         | 5-30s           |
| DISPUTE_FILING        | File transaction dispute         | Quantity short by 50 units vs PO-9981          | 10-60s          |
| DISPUTE_RESOLUTION    | Resolve filed dispute            | Agree partial credit $2,225 for short delivery | 1min-24hr       |
| CONTRACT_RENEWAL      | Renew expiring contract          | Extend supply agreement for 12 months at +2%   | 1-5min          |

### 4.2 Transaction State Machine

```
                     ┌────────────────────────────────────────────┐
                     │           TRANSACTION LIFECYCLE             │
                     └────────────────────────────────────────────┘

DRAFT ──publish──► OPEN ──respond──► NEGOTIATING ──agree──► COMMITTED
                     │                    │                      │
                  expire              abandon               EXECUTING
                     │                    │                      │
                  EXPIRED             ABANDONED            COMPLETED
                                                                  │
                                                             DISPUTED ──resolve──► RESOLVED
```

Every state transition is recorded on-chain with:

- Transaction ID (UUID + chain hash)
- Initiator DID + signature
- Responder DID + signature
- Timestamp (block timestamp)
- State transition payload (encrypted with participant keys)
- Platform fee deduction record

---

## 5. Smart Contract Architecture

### 5.1 Contract Suite

**AgentRegistryContract**

```solidity
// Pseudocode (Hyperledger Fabric Chaincode — Go)
func RegisterAgent(agentCard AgentCard) error
func UpdateAgent(agentID string, updates map[string]interface{}) error
func SuspendAgent(agentID string, reason string) error
func GetAgent(agentID string) (AgentCard, error)
func SearchAgents(filters SearchFilters) ([]AgentCard, error)
func UpdateTrustScore(agentID string, delta int, reason string) error
```

**TransactionContract**

```solidity
func InitiateTransaction(txn Transaction) (string, error)  // returns txnID
func RespondToTransaction(txnID string, response Response) error
func AdvanceState(txnID string, newState string, payload []byte) error
func GetTransaction(txnID string) (Transaction, error)
func GetTransactionHistory(txnID string) ([]StateChange, error)
func FileDispute(txnID string, dispute Dispute) error
func ResolveDispute(txnID string, resolution Resolution) error
```

**FeeSettlementContract**

```solidity
func RecordFee(txnID string, feeType string, amount float64) error
func BatchSettleFees(tenantID string, period string) (Settlement, error)
func GetFeeAccrual(tenantID string) (float64, error)
func ProcessPayout(tenantID string, amount float64) error
```

**EscrowContract**

```solidity
func LockFunds(txnID string, amount float64, currency string) error
func ReleaseFunds(txnID string, recipient string) error
func RefundFunds(txnID string, initiator string) error
func DisputeEscrow(txnID string) error
```

### 5.2 On-Chain vs Off-Chain Data

| Data                          | Storage                                   | Rationale                       |
| ----------------------------- | ----------------------------------------- | ------------------------------- |
| Transaction state transitions | On-chain (Fabric)                         | Immutability required           |
| Transaction fees              | On-chain (Fabric)                         | Audit and settlement            |
| Agent card hash               | On-chain (Fabric)                         | Integrity verification          |
| Agent card full content       | Off-chain (HAR database)                  | Size, GDPR flexibility          |
| Message payloads              | Off-chain (encrypted, IPFS or Azure Blob) | Size, confidentiality           |
| PII (company names, contacts) | Off-chain (HAR database)                  | GDPR compliance                 |
| Dispute evidence              | Off-chain (IPFS, content-addressed)       | Size, immutable by content hash |
| Public checkpoint hashes      | On-chain (Polygon CDK)                    | External verifiability          |

**GDPR Article 17 compliance**: Personal data never goes on-chain. The ledger records cryptographic hashes and identifiers. GDPR deletion requests remove off-chain data only. The on-chain record is a hash that becomes an orphaned reference — the content is gone, the audit trail remains.

---

## 6. Agent Identity and Trust

### 6.1 Decentralized Identifiers (DIDs)

Each agent has a DID following W3C DID Core:

```
did:mingai:<tenant-id>:<agent-slug>
```

Example: `did:mingai:acme-corp:procurement-agent-v2`

The DID document is stored in the HAR and resolves to:

- Agent's current public key(s)
- Service endpoints (A2A, webhook)
- Linked attestations (Verifiable Credentials)
- Controller (tenant's DID)

**Key rotation**: When a tenant rotates their agent's keys, they update the DID document. Historical transactions remain verifiable via the key version in the transaction record.

### 6.2 Verifiable Credentials (Trust Stack)

**Level 0 — Basic Registration**

- Agent card submitted; tenant email verified
- Trust score: 20-30

**Level 1 — KYB Verification**

- Know Your Business: company registration, authorized representative
- Trust score: 40-50
- Required for Tier 2+ transactions

**Level 2 — Industry Certification**

- ISO 27001, SOC 2, GDPR DPA signed
- Trust score: 60-70
- Required for regulated industry transactions

**Level 3 — Financial Grade**

- SWIFT BIC registered, bank account verified
- Trust score: 75-85
- Required for Tier 3 (financial) transactions

**Level 4 — Track Record**

- 100+ completed transactions, dispute rate <2%, uptime >99.5%
- Trust score: 85-100
- Premium placement in search

### 6.3 Trust Score Formula

```
TrustScore = (
  BaseAttestation × 0.30 +
  TransactionVolume_log10 × 0.20 +
  (1 - DisputeRate) × 0.25 +
  UptimeSLA × 0.15 +
  ResponseTimeRating × 0.10
) × 100

Constraints:
- MaxScore = 100
- MinScore = 0
- KYB_NOT_VERIFIED → score capped at 40
- ActiveDispute → score capped at 50
- SuspendedAgent → score = 0
```

---

## 7. Reconciliation Architecture

The reconciliation layer bridges the blockchain transaction ledger with each tenant's internal systems (ERP, accounting, procurement platforms).

### 7.1 Reconciliation Flow

```
Blockchain Ledger                    HAR Reconciliation Engine              Tenant Internal Systems
─────────────────                    ──────────────────────────             ───────────────────────
Transaction settled     ──event──►   ReconciliationWorker receives          ◄──webhook── ERP
Fee deducted           ──event──►   Maps txn → tenant internal IDs         ◄──webhook── Accounting
Dispute resolved       ──event──►   Generates reconciliation record         ◄──API──── SAP/NetSuite
Monthly settlement     ──event──►   Posts to tenant's webhook endpoint      ◄──SFTP──── Legacy EDI

                                     ReconciliationRecord {
                                       har_txn_id: "HAR-2026-0042",
                                       chain_hash: "0xabc...",
                                       tenant_ref: "PO-9981",          // mapped from context
                                       amount: 44500.00,
                                       currency: "USD",
                                       fee_deducted: 11.12,            // basis points
                                       status: "SETTLED",
                                       timestamp: "2026-03-05T14:22Z"
                                     }
```

### 7.2 Reconciliation Agent (AI-Powered)

For tenants with complex internal systems, an AI reconciliation agent runs as a sub-component:

**Inputs**:

- HAR transaction records (from chain)
- Tenant's ERP export (CSV, API, or EDI)
- Mapping rules (tenant-configured or AI-discovered)

**Functions**:

1. **Match**: Map HAR transaction IDs to internal document numbers (PO, invoice, delivery order)
2. **Validate**: Check amounts, quantities, dates match within configured tolerance
3. **Flag discrepancies**: Identify mismatches → generate exception report → alert tenant admin
4. **Post entries**: For tenants that authorize it, post reconciled entries to ERP (via connector)
5. **Currency conversion**: Apply FX rates for multi-currency transactions

**Reconciliation modes**:

- **Real-time**: Webhook-triggered on each transaction completion (low latency, higher API cost)
- **Batch daily**: Daily job exports and reconciles (default, lower cost)
- **Batch monthly**: End-of-month reconciliation (lowest cost, highest delay)

### 7.3 Supported Integration Connectors

| System                    | Method                       | Direction     |
| ------------------------- | ---------------------------- | ------------- |
| SAP S/4HANA               | BAPI/RFC over REST           | Bidirectional |
| Oracle NetSuite           | SuiteScript REST API         | Bidirectional |
| Microsoft Dynamics 365    | Dataverse API                | Bidirectional |
| QuickBooks Online         | QBO API                      | Bidirectional |
| Xero                      | Xero API                     | Bidirectional |
| Generic ERP               | Webhook (tenant-implemented) | Inbound       |
| Legacy EDI (X12, EDIFACT) | SFTP + parser                | Bidirectional |
| Flat file                 | CSV/Excel via SFTP           | Inbound       |

---

## 8. Monetization Model

### 8.1 Fee Structure

**Layer 1 — Registry Presence**

| Tier         | Price      | Transactions             | Features                                |
| ------------ | ---------- | ------------------------ | --------------------------------------- |
| Free         | $0/month   | 10 transactions/month    | Level 0 trust, read-only discovery      |
| Starter      | $99/month  | 100 transactions/month   | Level 1 trust, all transaction types    |
| Professional | $499/month | 1,000 transactions/month | Level 2 trust, reconciliation agent     |
| Enterprise   | Custom     | Unlimited                | Level 3-4 trust, dedicated support, SLA |

**Layer 2 — Transaction Fees (volume-based)**

| Transaction Tier          | Fee                                             |
| ------------------------- | ----------------------------------------------- |
| Tier 1 (Information)      | $0.10/transaction                               |
| Tier 2 (Commitment)       | $0.50-2.00/transaction                          |
| Tier 3 (Financial)        | 0.25% of transaction value, min $1.00, max $500 |
| Tier 4 (Post-transaction) | $0.25/transaction                               |

**Layer 3 — Value-Added Services**

| Service                                        | Price        |
| ---------------------------------------------- | ------------ |
| KYB verification                               | $25 one-time |
| Industry certification attestation             | $50/year     |
| Reconciliation agent (SAP/Oracle connector)    | $299/month   |
| Dedicated blockchain node                      | $500/month   |
| White-label registry for enterprise consortium | Custom       |

### 8.2 Unit Economics Projection

**Conservative scenario (Year 3)**:

- 500 tenant organizations registered
- Average 200 transactions/month/tenant
- 30% on Professional tier ($499/month): 150 × $499 = $74,850/month
- Transaction fees: 500 × 200 × $0.75 avg = $75,000/month
- Value-added services: $30,000/month
- **Total MRR**: $179,850 (~$2.2M ARR)

**Base scenario (Year 3)**:

- 2,000 tenant organizations
- 500 transactions/month/tenant
- Mix of tiers + transaction fees
- **Total MRR**: $850,000 (~$10M ARR)

**Growth scenario (Year 5, third-party agents included)**:

- 10,000 organizations (including non-mingai customers)
- 1,000 transactions/month/organization
- **Total MRR**: $5,000,000 (~$60M ARR)

---

## 9. Security Architecture

### 9.1 Agent Authentication

Every A2A message is signed by the initiating agent's private key:

```
Message {
  header: {
    from_did: "did:mingai:acme:procurement-v2",
    to_did: "did:mingai:baker:sales-v1",
    txn_id: "HAR-2026-0042",
    timestamp: "2026-03-05T14:22:00Z",
    nonce: "8f3a9c..."
  },
  payload: <encrypted with recipient's public key>,
  signature: <Ed25519 signature over header + payload hash>
}
```

The HAR validates:

1. Sender DID resolves to a registered, non-suspended agent
2. Signature is valid against sender's current public key
3. Timestamp is within ±5 minutes (replay attack prevention)
4. Nonce has not been seen before (replay attack prevention)
5. Sender has sufficient trust level for the transaction type

### 9.2 Prompt Injection Defense

When AI agents process transaction payloads, prompt injection is a critical attack vector. A malicious agent could inject instructions into a response payload that hijack the receiving agent's behavior.

**Defense layers**:

1. **Structured payload schema**: All transaction payloads conform to a strict JSON schema. Freetext fields are confined to `notes` and `description` fields, which are stripped before LLM processing.
2. **Payload sanitization middleware**: Before any AI agent processes an inbound payload, a sanitization filter removes common prompt injection patterns: `ignore previous`, `system:`, `<|im_start|>`, etc.
3. **Agent trust boundary**: AI agents process structured data, not raw freetext from counterparties. Natural language is only used for human-facing summaries, not for decision-making logic.
4. **Human approval gates**: For Tier 3 (financial) transactions >$10,000, human approval is required before execution. The AI agent prepares the transaction; a human approves it.

### 9.3 Sybil Attack Prevention

Without anti-Sybil measures, a single bad actor could register hundreds of fake agents to manipulate trust scores or spam the network.

**Countermeasures**:

- KYB verification required for Level 1+ (legal entity + company registration verified)
- One KYB identity per tenant (one real company = one tenant)
- Proof of payment required for Professional+ tiers
- Trust score degradation for agents with <10 real counterparties in 30 days
- Rate limiting: max 5 new agent registrations per tenant per day

---

## 10. Governance Model

### 10.1 Registry Governance

The HAR operates as a **managed consortium** in Phase 1:

- mingai controls all governance decisions (membership, standards, dispute policy)
- Advisory board from first 10-20 enterprise members
- Published standards: Agent Card schema, transaction type taxonomy, dispute resolution rules

**Phase 2 (Year 2-3)**: Transition toward consortium governance:

- Governance token (not speculative — utility-only, staked by members)
- Standards Working Group with elected member representatives
- Dispute resolution panel: 3 neutral members (rotating from top-trust-score participants)

**Phase 3 (Year 3+)**: Open standards publication:

- Agent Card spec published as open standard
- Any platform can implement compatible agents
- HAR is one of multiple interconnected registries

### 10.2 Dispute Resolution

**Stage 1 — Automated (0-24 hours)**:

- Smart contract checks: did delivery occur? was payment made? do amounts match?
- If clear violation (e.g., payment not made within agreed terms): automatic resolution

**Stage 2 — AI Mediation (24-72 hours)**:

- Dispute agent analyzes contract terms, transaction history, evidence submitted
- Generates resolution recommendation
- Both parties accept or escalate

**Stage 3 — Human Arbitration (3-14 days)**:

- Selected from the Registry's Dispute Resolution Panel
- Binding decision recorded on-chain
- Losing party incurs arbitration fee ($200-500)
- Repeated losers have trust score reduced

---

## 11. Open Registry Architecture (Non-mingai Agents)

For the registry to be a true "yellow book" for autonomous B2B commerce, it must accept agents from any platform, not just mingai tenants.

### 11.1 External Agent Onboarding

Non-mingai agents must implement:

1. **Agent Card** conforming to HAR v1 schema (JSON, published as open standard)
2. **A2A endpoint** implementing HAR A2A protocol v1 (request/response + webhook)
3. **DID resolution** via a compatible DID method (W3C DID Core)
4. **KYB verification** via HAR's verification partner (Dun & Bradstreet, Stripe Identity)
5. **Signed capability attestation** (what transaction types this agent handles)

**SDK availability**:

- `har-sdk-python`: Python SDK for agent integration
- `har-sdk-node`: Node.js/TypeScript SDK
- `har-sdk-java`: Java SDK (SAP ecosystem)

### 11.2 Cross-Registry Federation (Phase 3)

When multiple HAR-compatible registries exist (e.g., a European consortium registry, an APAC registry), federation allows agents on different registries to discover and transact:

```
ACME agent (on HAR-SG) wants to transact with BAKER agent (on HAR-EU)

1. ACME queries HAR-SG for BAKER → not found locally
2. HAR-SG queries HAR-EU federation endpoint → returns BAKER's agent card
3. Transaction is initiated; both registries record their portion
4. Fee split: HAR-SG takes initiator fee, HAR-EU takes responder fee
5. Cross-registry transactions anchored on shared Polygon CDK checkpoint chain
```

---

## 12. Implementation Phases

### Phase 0 — Foundation (Months 1-3)

- Agent Card schema v0.1 (internal)
- Basic registry (PostgreSQL, no blockchain yet)
- First 5 mingai tenants as pilot participants
- Manual KYB verification
- No transaction fees (pilot mode)

### Phase 1 — Blockchain Integration (Months 4-8)

- Hyperledger Fabric deployment (single-node for pilot)
- Transaction state machine on-chain
- Fee settlement contract
- KYB integration (Stripe Identity or Jumio)
- First Tier 1-2 transactions live
- Launch with mingai customers only

### Phase 2 — Open Registry (Months 9-15)

- Agent Card spec published as open standard
- External agent onboarding (non-mingai companies)
- Polygon CDK checkpoint layer
- Reconciliation agent (SAP, NetSuite connectors)
- Tier 3 (financial) transactions (requires payment partner integration)
- Trust score system live

### Phase 3 — Consortium Governance (Months 16-24)

- Standards Working Group
- Dispute Resolution Panel
- Cross-registry federation protocol
- Governance transition plan
- Publicly auditable checkpoint registry

---

## 13. Key Architectural Risks

| Risk                                                                                | Probability | Impact   | Mitigation                                                                                     |
| ----------------------------------------------------------------------------------- | ----------- | -------- | ---------------------------------------------------------------------------------------------- |
| Blockchain adoption friction (enterprise security teams reject permissioned chain)  | High        | High     | Start without blockchain (audit log only); add chain layer after first 10 customers            |
| Agent autonomy liability (agent commits company to contract without human approval) | High        | Critical | Mandatory human approval gates for Tier 2+; clear ToS on agent authorization scope             |
| KYB/AML compliance in multiple jurisdictions                                        | Medium      | High     | Partner with Stripe Identity (global KYB) from day 1; legal review per jurisdiction            |
| Prompt injection via counterparty payloads                                          | High        | High     | Structured schema enforcement; LLM never sees raw counterparty text                            |
| Low network liquidity (not enough agents = no discovery value)                      | High        | Critical | Seed network with mingai tenants; critical mass = ~100 active agents                           |
| Smart contract bugs leading to lost/frozen funds                                    | Medium      | Critical | Escrow contracts audited by Certik or Trail of Bits before Tier 3 goes live                    |
| Regulatory uncertainty (blockchain for B2B contracts)                               | Medium      | High     | Legal opinions in SG, EU, US before launch; use chain for audit trail only, not legal contract |
