# 12-01 — Agent Registry: Competitive Analysis

**Date**: 2026-03-05

---

## 1. Market Framing

The Hosted Agent Registry (HAR) sits at the intersection of five existing market categories, but no existing player occupies all five simultaneously. This creates a genuine whitespace — but also means mingai must build market awareness for a category that doesn't fully exist yet.

**Adjacent markets**:

1. **EDI Networks** (Electronic Data Interchange): GXS/OpenText, AS2/X12/EDIFACT, SWIFT — structured B2B document exchange
2. **B2B API Marketplaces**: RapidAPI, AWS Marketplace, Azure Marketplace — API discovery and monetization
3. **Procurement Platforms**: SAP Ariba, Coupa, Jaggaer — digital procurement workflows
4. **Business Directories**: D&B (Dun & Bradstreet), Kompass, LinkedIn — company and capability discovery
5. **Blockchain B2B Networks**: TradeLens (discontinued), Marco Polo, Komgo — supply chain finance on blockchain

**The whitespace**: All of the above are either (a) human-operated, (b) passive APIs (not autonomous agents), or (c) specific vertical applications rather than general-purpose agent infrastructure. HAR is the first infrastructure layer for **autonomous AI agents conducting B2B commerce**.

---

## 2. Competitor Profiles

### 2.1 EDI Networks (GXS / OpenText / AS2 Networks)

**What they do**: Structured document exchange for purchase orders, invoices, advance ship notices. The backbone of B2B commerce for 40+ years.

**Strengths**:

- 99.999% uptime track record
- ANSI X12 and EDIFACT standards universally accepted
- 50,000+ trading partner connections
- Deeply embedded in ERP systems (SAP IDOC, Oracle E-Business Suite)
- Legal standing: EDI documents are legally binding contracts in most jurisdictions

**Weaknesses**:

- Document-centric, not agent-centric — EDI sends structured documents, not AI
- No intelligence: cannot negotiate, cannot make decisions, cannot adapt
- Requires manual document template setup for each trading partner
- Legacy technology: 30-40 year old infrastructure, no modern API support in many cases
- Expensive: $500-5,000/month for EDI VAN (Value Added Network) access
- No discovery: finding trading partners requires out-of-band relationship building

**Threat to HAR**: None in the near term. HAR is not replacing EDI — it is a new layer on top of EDI that adds AI intelligence. Long term, HAR transactions (Tier 2-3) may replace EDI for modern organizations.

**Opportunity**: HAR should offer EDI bridge connectors (X12, EDIFACT) so that HAR-native AI agents can transact with legacy EDI-connected companies that have no AI agents.

---

### 2.2 API Marketplaces (RapidAPI, AWS Marketplace)

**What they do**: Passive API discovery and subscription. Companies publish API endpoints; developers discover, subscribe, and call them.

**Strengths**:

- Large developer communities (50,000+ APIs on RapidAPI)
- Standardized authentication (API keys, OAuth)
- Monetization infrastructure (usage-based billing)
- Strong for developer discovery

**Weaknesses**:

- APIs are passive: they respond to calls, they do not initiate
- No autonomy: APIs cannot negotiate, cannot decide, cannot adapt
- No B2B transaction semantics: no PO, no invoice, no contract — just REST calls
- No trust layer: no KYB, no legal entity verification, no dispute resolution
- No blockchain audit trail

**Threat to HAR**: Low. RapidAPI and AWS Marketplace serve developers building integrations; HAR serves businesses deploying autonomous agents. Different personas, different value proposition.

**Opportunity**: HAR agent endpoints can be discoverable via API marketplaces (list the A2A endpoint on RapidAPI). This creates additional inbound discovery channels without duplicating infrastructure.

---

### 2.3 Procurement Platforms (SAP Ariba, Coupa)

**What they do**: Digital procurement workflows — vendor management, catalog management, PO approval workflows, invoice matching.

**Strengths**:

- SAP Ariba: 4M+ connected suppliers, largest B2B network by transaction volume
- Deep ERP integration (SAP S/4HANA native, Oracle connectors)
- Established legal and compliance frameworks
- Comprehensive procurement workflow coverage (RFQ → PO → receipt → invoice → payment)
- AI features emerging (Ariba Guided Buying, Coupa AI)

**Weaknesses**:

- Buyer-centric: designed for the buying organization, not the selling organization
- Not autonomous: humans make approval decisions, AI only suggests
- Not a marketplace: you discover suppliers, not AI agents
- High cost: SAP Ariba contracts start at $150,000+/year
- Slow to innovate: procurement platforms move at enterprise software speed
- No blockchain: immutability is a database concern, not a protocol guarantee

**Threat to HAR**: SAP Ariba is the most dangerous competitor, but from a different angle. Ariba could add AI agent capabilities to their existing network of 4M suppliers. If Ariba ships "autonomous AI procurement agents" for their network, they have an enormous installed base advantage.

**Mitigation**: HAR must establish itself in the AI-native organizations (tech companies, digital-first businesses) before Ariba's AI features mature. HAR's edge is speed-to-market with AI-first architecture. Ariba's AI will be a feature added to a legacy platform; HAR is AI-native.

---

### 2.4 Blockchain B2B Networks (Marco Polo, Komgo, TradeLens)

**What they do**: Supply chain finance and trade finance on permissioned blockchain. Letter of credit automation, receivables finance, supply chain visibility.

**Strengths**:

- Proven permissioned blockchain for B2B (R3 Corda or Hyperledger Fabric)
- Financial-grade compliance (KYC, AML, sanctions screening)
- Bank-backed credibility (Marco Polo: ING, BNP Paribas, Commerzbank)
- Legal framework for blockchain-based trade finance

**Weaknesses**:

- **TradeLens (Maersk + IBM): shut down in 2022** — demonstrated the challenge of building a neutral multi-party network
- Vertically focused: Marco Polo = trade finance, Komgo = commodity trade — not general purpose
- No AI: blockchain records transactions but no AI agents negotiate or decide
- Complex onboarding: Hyperledger Fabric network membership is technically demanding
- No SMB access: all focused on large enterprise and financial institutions

**Critical lesson from TradeLens failure**: A B2B blockchain network requires a truly neutral operator. Maersk's involvement made competitors (other shipping lines) unwilling to join. HAR must position mingai as a neutral infrastructure provider, not a participant.

**Threat to HAR**: Low. These are complementary — HAR could use Marco Polo for the financial settlement layer while running its own registry and AI agent layer.

---

### 2.5 AI Agent Platforms (Google A2A Protocol, Anthropic Claude API, OpenAI Assistants)

**What they do**: AI infrastructure for building and running AI agents. Google A2A (Agent-to-Agent) protocol is the most directly relevant.

**Google A2A Protocol (announced March 2025)**:

- Open standard for AI agent interoperability
- Agent Cards: similar to HAR's concept
- A2A messaging: structured agent-to-agent communication
- No registry: A2A is a communication protocol, not a discovery registry
- No blockchain: no immutable audit trail
- No monetization: no transaction fee infrastructure
- No KYB/trust: no identity verification layer

**OpenAI GPT Actions / Assistant API**:

- API-based agent execution
- No discovery
- No B2B semantics
- No blockchain

**Threat to HAR**: Google A2A is the most significant threat. Google has the developer distribution to make A2A the dominant agent communication protocol. If HAR builds on top of A2A (compatible with Google's standard), HAR becomes the registry and trust layer on top of a widely-adopted protocol — a strong position. If Google builds their own registry, HAR's discovery value is threatened.

**Mitigation**: HAR must explicitly support Google A2A protocol for agent communication while adding the registry, trust, blockchain, and monetization layers that Google A2A lacks. Be A2A-compatible; compete on the layers above A2A.

---

### 2.6 Emerging AI Agent Marketplaces (Agentverse, Fetch.ai, Autonolas)

**What they do**: Web3-native agent marketplaces. Fetch.ai runs an "Agentverse" where autonomous AI agents can find each other and transact using the Fetch.ai blockchain.

**Fetch.ai / Agentverse**:

- Agent registration and discovery
- Blockchain-based transaction recording (Cosmos SDK chain)
- uAgent framework for building agents
- DeltaV: conversational interface to discover agents
- Token economy: FET token for transactions

**Strengths**:

- First mover in blockchain-based agent registry
- Web3-native architecture (correct technical approach)
- Growing developer community (50,000+ agents registered)

**Weaknesses**:

- Web3-native = enterprise adoption barrier (crypto tokens, wallets, gas fees)
- No KYB: agents can be anonymous entities (not suitable for B2B enterprise)
- No legal standing: FET token transactions are not legally binding contracts
- SMB-to-consumer focus: not enterprise procurement
- No ERP integration: no SAP/Oracle connectors
- Trust is token-staking, not KYB verification (different trust model)

**Threat to HAR**: LOW in enterprise. HIGH in developer and tech-forward SMB market. Agentverse has a first-mover advantage with AI-native developers. HAR should watch this carefully.

**Mitigation**: Enterprise positioning. HAR is "the B2B agent registry for verified businesses" — not for anonymous Web3 participants. Different trust model, different compliance posture, different buyer.

---

### 2.7 Messaging/Workflow Platforms (Slack, Microsoft Teams, Zapier, Make)

**What they do**: Human-to-software integration platforms where agents increasingly operate as bots and automation workers.

**Threat to HAR**: Minimal. These platforms are human-communication-centric, not B2B transaction-centric. Zapier automating a Slack message to SAP is not an AI agent conducting B2B commerce.

---

## 3. Competitive Feature Matrix

| Capability                             | HAR (mingai)  | SAP Ariba           | GXS/EDI      | RapidAPI     | Google A2A    | Fetch.ai       |
| -------------------------------------- | ------------- | ------------------- | ------------ | ------------ | ------------- | -------------- |
| Agent discovery                        | Yes           | Supplier dir only   | No           | API dir only | No registry   | Yes            |
| Autonomous negotiation                 | Yes           | No                  | No           | No           | Protocol only | Limited        |
| B2B transaction semantics (PO/Invoice) | Yes           | Yes                 | Yes          | No           | No            | No             |
| Blockchain audit trail                 | Yes           | No                  | No           | No           | No            | Yes (crypto)   |
| KYB verification                       | Yes           | Partial             | No           | No           | No            | No             |
| Trust scoring                          | Yes           | Ariba Network score | No           | No           | No            | Token staking  |
| ERP integration                        | Yes           | Native (SAP)        | Yes          | No           | No            | No             |
| GDPR compliant                         | Yes           | Yes                 | Yes          | Yes          | Yes           | Unclear        |
| Enterprise pricing (non-crypto)        | Yes           | Yes                 | Yes          | Yes          | Free          | Crypto         |
| Open to non-platform agents            | Yes (Phase 2) | No                  | Via EDI only | No           | Yes           | Yes            |
| Dispute resolution                     | Yes           | Human workflow      | No           | No           | No            | Smart contract |
| Financial settlement                   | Yes (Phase 2) | Via ERP             | Via EDI      | No           | No            | Token          |

---

## 4. Market Gaps Validated

**Gap 1: No enterprise-grade AI agent registry exists**

SAP Ariba has suppliers; RapidAPI has APIs; Google A2A has a protocol. No platform combines: (1) machine-readable agent capability discovery, (2) verified business identity (KYB), (3) autonomous transaction execution with immutable audit trail. This gap is real and validated by the competitive scan.

**Gap 2: Blockchain B2B networks failed because of politics, not technology**

TradeLens proved that permissioned blockchain is technically viable for B2B. It failed because Maersk's ownership prevented competitors from joining. A neutral operator (mingai) with no skin in the industry game solves the political problem. The technology is proven.

**Gap 3: No trust layer for AI-to-AI commerce**

When two AI agents from different companies interact, there is no standardized way to verify: is this agent authorized by a real, verified company? What is its track record? Google A2A addresses communication; it does not address identity, authorization, or reputation. HAR addresses all three.

**Gap 4: EDI is too expensive and static for SMB; modern APIs are too passive for autonomous commerce**

SMB manufacturers (10-200 employees) cannot afford SAP Ariba. They use Excel and email. AI agents give them a path to digital B2B commerce at EDI quality without EDI cost. HAR's accessible pricing tier ($99/month Starter) serves this segment.

---

## 5. Strategic Positioning

**HAR's defensible position**: The intersection of enterprise compliance (KYB, GDPR, audit trail) with AI-native architecture (agent cards, A2A protocol, autonomous transactions) — a combination no current player offers.

**Positioning statement**: "The enterprise-grade B2B agent registry: where verified AI agents conduct real business transactions, backed by an immutable audit trail that any auditor can verify."

**Differentiation from each competitor**:

- vs. SAP Ariba: AI-native (autonomous), not human-workflow-dependent; 100× lower cost for SMB
- vs. GXS/EDI: AI agents replace static documents; AI can negotiate, adapt, and respond to context
- vs. Google A2A: adds the missing layers — registry, identity, trust, monetization, blockchain
- vs. Fetch.ai: enterprise-grade KYB and legal standing; ERP integration; no crypto requirement
- vs. Marco Polo: general purpose (not trade finance only); adds AI agent layer; open to all industries

**The "yellow book" metaphor is accurate and powerful**: A yellow pages for autonomous AI agents. Discovery by capability. Trust by verification. Transactions by protocol. Immutable record by blockchain.
