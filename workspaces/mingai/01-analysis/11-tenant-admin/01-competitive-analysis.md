# 11-01 — Tenant Admin: Competitive Analysis

**Date**: 2026-03-05
**Product lens**: The tenant admin console as the self-service interface that enables an organization's IT admin or knowledge manager to deploy, operate, and govern their enterprise AI workspace — without needing platform engineers or AI expertise.

---

## 1. Framing: What Product Are We Analyzing?

The tenant admin console is the **enterprise workspace management interface** — the cockpit that a company's internal IT admin, knowledge manager, or department head uses to:

- Connect their organization's documents to the AI
- Control who sees which AI capabilities
- Build and deploy AI agents for their team
- Monitor whether users are getting value

**Customers of this interface**:

- Enterprise IT administrators managing AI deployment across 500+ users
- Department managers (HR, Legal, Finance) who own domain-specific AI agents
- Knowledge managers responsible for content accuracy and RAG quality
- Operations teams running AI-assisted workflows

**Critical distinction**: This is NOT a consumer product. Enterprise B2B buyers evaluate this against their existing IT tooling stack (Active Directory, SharePoint admin, Google Workspace admin) and against competing AI workspace platforms (Microsoft Copilot, Glean, Guru, Notion AI, etc.).

---

## 2. Competitive Landscape

### 2.1 Enterprise AI Knowledge Management Platforms

**Microsoft Copilot for Microsoft 365**

- Category: AI assistant deeply integrated into Microsoft 365
- Strengths: Zero new document ingestion required (uses existing SharePoint/Teams), familiar Microsoft admin center UX, SSO via Entra ID is trivial, enterprise security compliance (E3/E5 includes compliance), massive ecosystem
- Weaknesses for our lens: No agent builder for non-technical admins, no custom RAG knowledge bases outside M365 data, no multi-model support (GPT-4 only), no custom glossary, no per-document-source access control, very limited customization of AI behavior
- Admin experience: Microsoft 365 admin center — powerful but complex, designed for IT professionals not knowledge managers
- Integration effort: Near-zero if already on M365 — but locked into the Microsoft stack entirely

**Glean**

- Category: AI search + knowledge management for enterprises
- Strengths: 100+ native connectors (Confluence, Jira, Google Drive, SharePoint, Slack, etc.), strong enterprise search, good relevance, enterprise SSO out of the box
- Weaknesses: No agent builder, no custom LLM profiles, no glossary system, no agent-level access control (it's search, not an agent platform), search-only paradigm (not generative)
- Admin experience: Connector management dashboard, RBAC for search domains — competent but narrow
- Integration effort: LOW for connectors, but no agent capability

**Guru**

- Category: AI knowledge management / verified company knowledge
- Strengths: Structured content management (Cards), verification workflows, browser extension, Slack integration
- Weaknesses: Document-centric, not document-source-centric — requires humans to curate content, not a RAG indexer. No agent platform, no custom AI behavior, no SSO for AI responses
- Admin experience: Knowledge base management UX — simple but limited for our scope

**Notion AI**

- Category: Wiki + AI assistant within Notion
- Strengths: Simple to set up, familiar collaborative workspace, AI can query Notion pages
- Weaknesses: Siloed to Notion content only (no SharePoint, Google Drive, etc.), no enterprise RBAC beyond Notion's own, no custom agents, no LLM profile selection
- Admin experience: Notion workspace admin — basic permissions only

**Confluence + Atlassian Intelligence**

- Category: Wiki + AI assistant within Atlassian
- Strengths: Deep integration with Jira, good content organization, SAML SSO
- Weaknesses: Atlassian-ecosystem-only knowledge, no external document indexing, limited AI agent customization
- Admin experience: Confluence space admin — solid but not an AI governance tool

---

### 2.2 AI Agent Builders (from the Admin's Perspective)

**Microsoft Copilot Studio**

- Category: Low-code agent builder within the Microsoft ecosystem
- Strengths: Visual agent designer, connectors to Power Platform, SharePoint, Teams integration, enterprise licensing
- Weaknesses: Azure-only, Teams-centric, not designed for non-Microsoft knowledge sources, requires Power Platform licensing, limited RAG customization, agent performance analytics are basic
- Admin experience: Power Platform admin — technically capable users only

**ServiceNow AI Agents**

- Category: Enterprise workflow AI + knowledge management
- Strengths: Deep ITSM integration, strong enterprise RBAC, compliance features
- Weaknesses: Very expensive, IT/service desk focused, extremely limited to ServiceNow workflows, not a general-purpose knowledge AI

**Salesforce Agentforce**

- Category: CRM-native AI agent platform
- Strengths: Deep CRM integration, excellent for sales/customer service use cases
- Weaknesses: Salesforce-data-only context, no general knowledge base indexing, very high cost, requires Salesforce expertise to administer

**Relevance AI / VoiceFlow (SMB agent builders)**

- Category: No-code/low-code agent builders
- Strengths: Visual interface, easy to use, quick to deploy agents
- Weaknesses: Single-tenant (no multi-tenant RBAC), no enterprise SSO, no document sync, no corporate knowledge base integration, not enterprise-grade

---

### 2.3 Document-to-AI Platforms

**AWS Kendra / Azure AI Search (direct)**

- Category: Enterprise search infrastructure
- Strengths: Native document indexing, enterprise security integration, strong relevance
- Weaknesses: No admin UI for knowledge managers — requires engineering to configure and maintain. No agent platform. No feedback monitoring. Developer tool, not a business user tool.

**Box AI**

- Category: Content management + AI within Box
- Strengths: Strong DRM, enterprise file management, Box AI can answer questions about Box-stored documents
- Weaknesses: Box-only document sources, basic AI capabilities, limited RBAC for AI (inherits Box permissions), no agent builder

---

### 2.4 Feature Comparison Matrix

| Capability                   | Microsoft Copilot M365 | Glean            | Guru            | Copilot Studio | mingai Tenant Admin |
| ---------------------------- | ---------------------- | ---------------- | --------------- | -------------- | ------------------- |
| Connect SharePoint           | ✓ (native)             | ✓                | ✗               | ✓              | ✓                   |
| Connect Google Drive         | Partial                | ✓                | ✗               | Partial        | ✓                   |
| Custom RAG knowledge bases   | ✗                      | ✓                | Partial         | Partial        | ✓                   |
| Organizational glossary      | ✗                      | ✗                | Partial (Cards) | ✗              | ✓                   |
| SSO + group-to-role sync     | ✓ (Entra)              | ✓                | ✓               | ✓ (Entra)      | ✓ (SAML+OIDC)       |
| KB-level access control      | ✗                      | ✓ (domain-based) | ✓               | Partial        | ✓                   |
| Agent-level access control   | ✗                      | N/A              | N/A             | Partial        | ✓                   |
| Agent library (adopt)        | ✗                      | ✗                | ✗               | ✓              | ✓                   |
| Agent studio (build)         | ✗                      | ✗                | ✗               | ✓              | ✓                   |
| Custom LLM model selection   | ✗                      | ✗                | ✗               | ✗              | ✓ (via profiles)    |
| Sync health monitoring       | Basic                  | Basic            | N/A             | ✗              | ✓                   |
| User feedback monitoring     | ✗                      | ✗                | Partial         | ✗              | ✓                   |
| Issue reporting + resolution | ✗                      | ✗                | ✗               | ✗              | ✓                   |
| Cloud-agnostic deployment    | ✗ (Azure only)         | ✗ (cloud)        | ✗               | ✗ (Azure only) | ✓ (Phase 5)         |
| Non-technical admin UX       | MEDIUM                 | HIGH             | HIGH            | LOW            | HIGH (target)       |

---

## 3. The Tenant Admin's Core Job-to-be-Done

The tenant admin is not buying "document sync software" or "an agent builder." They are buying **"confidence that the AI deployment works correctly for my users."**

This breaks into three sub-jobs:

**Sub-job 1: Get the AI connected to our knowledge** (one-time setup)

- Connect the documents we have (SharePoint, Google Drive, uploads)
- Ensure our terminology is understood (glossary)
- Know it's working (sync health)

**Sub-job 2: Control who uses the AI for what** (ongoing governance)

- Make sure Finance's agent doesn't give Legal documents to Marketing users
- Onboard new users with correct access automatically (SSO + role sync)
- Remove ex-employees quickly (suspension)

**Sub-job 3: Make the AI better over time** (ongoing optimization)

- Know when the AI is giving bad answers (feedback monitoring)
- Know which agents are being used and which aren't (engagement)
- Fix configuration problems before users give up (issue resolution)

---

## 4. Market Gaps

### Gap 1: Enterprise AI Admin Is a New Role Without Tooling

Organizations deploying Microsoft Copilot or Glean put an IT admin in charge of the deployment. But "AI deployment administration" is a new role that doesn't have established tooling. IT admins are using the same dashboards designed for email administration (Exchange admin, AD) to manage AI deployments. None of these tools speak "AI quality" language (confidence scores, retrieval quality, satisfaction rates).

### Gap 2: Non-Technical Admin UX Is Weak Across the Board

Microsoft Copilot Studio requires Power Platform expertise. AWS Kendra requires engineering. Glean requires connector configuration expertise. The knowledge manager who owns the HR knowledge base — a non-technical person — has no tool that lets them: connect SharePoint, build an HR agent, see which users are satisfied with it, and fix it when it underperforms. All existing tools require either IT or engineering involvement.

### Gap 3: Cross-Source RBAC Does Not Exist

When an organization connects SharePoint + Google Drive + uploaded PDFs, they need fine-grained control over which users see which sources via which agents. Microsoft Copilot inherits M365 permissions (not always fine-grained enough). Glean does domain-level restrictions (not agent-level). No product does KB-level + agent-level access control simultaneously with a non-technical admin UI.

### Gap 4: AI Feedback Loop Is Missing from Admin Tooling

Existing platforms track usage metrics (queries, sessions, MAU). None surface: "HR Agent has 54% satisfaction this week vs 82% last week — the last document sync included a policy change that broke the HR Q&A." This connection between content changes and AI quality is unique to a system that owns both the document sync pipeline and the feedback collection layer.

### Gap 5: Agent Quality Governance for Business Users

An HR manager who deployed an HR Policy Agent has no way to see if it is giving correct, compliant answers. They can only find out when an employee complains. An admin console that surfaces: "3 low-confidence responses about maternity leave policy this week — your policy documents may not cover this topic" closes the feedback loop before damage is done.
