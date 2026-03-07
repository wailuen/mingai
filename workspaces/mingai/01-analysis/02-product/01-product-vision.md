# Product Vision & Intent

## Problem Statement

Enterprise knowledge is fragmented across dozens of systems -- SharePoint libraries, Azure AI Search indexes, internal databases, third-party APIs (Bloomberg, Oracle Fusion, BIPO HRMS), and personal documents in OneDrive. Employees waste significant time hunting for answers across these disparate sources, often not knowing which system to search or whether they even have access to the right data.

The core problems are:

1. **Knowledge fragmentation**: Information lives in silos with no unified access point
2. **Access control complexity**: Different data sources have different permission models, making it hard to enforce consistent RBAC
3. **Search inadequacy**: Traditional keyword search fails for complex, multi-faceted enterprise questions that require synthesizing information from multiple sources
4. **Expert bottlenecks**: Subject matter experts are repeatedly interrupted for questions that could be answered by existing documentation
5. **Lost institutional knowledge**: When employees leave, their tacit knowledge about where to find information disappears

## Target Users (Personas)

### Primary Users

**Knowledge Worker (Primary persona)**

- Role: Any employee seeking information -- analysts, managers, support staff, engineers
- Pain: Spends 20-30% of time searching for information across multiple systems
- Need: Single natural-language interface to query all authorized enterprise content
- Scale: Initially <50 concurrent, growing to hundreds/thousands

**Senior Analyst / Cross-functional Researcher**

- Role: Needs to correlate data across domains (finance + HR, engineering + product)
- Pain: Manual cross-referencing across different indexes and systems
- Need: Multi-index search with intelligent routing and synthesis

**Manager / Team Lead**

- Role: Needs quick access to policies, reports, and team-relevant documents
- Pain: Personal documents (strategy drafts, meeting notes) are unsearchable alongside enterprise data
- Need: Personal document upload with private search integration

### Administrative Users

**Role Administrator (role_admin)**

- Manages roles, assigns users/groups, configures system function permissions
- Creates custom roles bundling index access with admin capabilities

**Index/KB Administrator (index_admin)**

- Registers and configures Azure AI Search indexes
- Manages SharePoint knowledge base connections
- Maintains glossary terms and index metadata

**Analytics Viewer (analytics_viewer)**

- Monitors system usage, query patterns, content gaps
- Reviews unanswered query reports to drive content creation

**Integration Admin (integration_admin)**

- Manages A2A agent catalog (Bloomberg Intelligence, Oracle Fusion, iLevel Portfolio, etc.)
- Monitors A2A agent health and availability

**Sync Admin (sync_admin)**

- Monitors background sync workers for SharePoint indexing
- Triggers manual sync runs and reviews error logs

**Feedback Viewer (feedback_viewer)**

- Reviews user feedback on AI responses
- Tracks feedback analytics to improve response quality

## Core Value Proposition

**"One intelligent interface to all your enterprise knowledge, with the access controls your organization requires."**

The product sits at the intersection of three capabilities:

1. **Unified Knowledge Access**: A single conversational interface that spans Azure AI Search indexes, SharePoint libraries, MCP-connected external systems, personal documents, and internet sources -- eliminating the "which system do I search?" problem
2. **Intelligent Access Control**: RBAC that respects the enterprise permission model -- users see only what they are authorized to see, enforced consistently across all data sources
3. **AI-Powered Synthesis**: Rather than returning a list of documents, the system synthesizes answers from multiple sources with full source attribution, confidence scoring, and multi-language support

## Current Product Scope

As implemented (based on codebase analysis), the product includes:

### Fully Implemented

| Capability                   | Description                                                                                            |
| ---------------------------- | ------------------------------------------------------------------------------------------------------ |
| Azure AD SSO                 | Enterprise authentication with group-based role sync                                                   |
| RBAC with 9 system functions | Fine-grained admin access via synthetic role IDs in JWT                                                |
| AI Chat with SSE streaming   | Real-time conversational AI with GPT-5.2-chat via Azure OpenAI                                         |
| Multi-index search           | Parallel search across multiple Azure AI Search indexes                                                |
| Intelligent index routing    | LLM-driven index selection based on query analysis                                                     |
| Internet fallback (Tavily)   | Automatic web search when enterprise content is insufficient                                           |
| Source attribution           | Every response shows sources with relevance scores                                                     |
| Multi-language support       | Auto-detect query language, respond in same language                                                   |
| Conversation management      | Persistent history, context window management, retention policies                                      |
| User profiling               | LLM learns user preferences and organizational context                                                 |
| Personal document upload     | Upload to user's OneDrive with vector indexing and private search                                      |
| Admin UI                     | Role management, user management, index management, analytics                                          |
| A2A agent integration        | 9 autonomous A2A agents (Bloomberg Intelligence, Oracle Fusion, CapIQ, etc.) each internally using MCP |
| SharePoint indexing          | Background sync workers for SharePoint library content                                                 |
| Glossary management          | Enterprise glossary for domain-specific terminology                                                    |
| Feedback system              | Thumbs up/down on AI responses with admin review                                                       |
| Analytics & cost tracking    | Query analytics, LLM/search/Tavily usage tracking, cost allocation                                     |
| Audit logging                | Comprehensive audit trail with 3-year retention                                                        |
| Notification system          | Real-time SSE notifications and email triage                                                           |
| Agent communication channels | Email channel for AI-initiated communications (meeting confirmations, follow-ups)                      |
| Unsolicited email triage     | Multi-layer routing for inbound emails to shared agent mailbox                                         |
| Unified KB management        | Consolidated knowledge base management across sources                                                  |
| Background job scheduling    | Group sync, retention cleanup, SharePoint sync, question categorization                                |
| Circuit breaker pattern      | Fault tolerance for external service calls                                                             |
| Cache warming & invalidation | Redis pub/sub for cross-instance cache consistency                                                     |

### Planned / In Research

| Capability                    | Status                                              |
| ----------------------------- | --------------------------------------------------- |
| MS Teams bot integration      | Phase 2, designed but not built                     |
| Oracle Fusion A2A agent       | Research phase (detailed API analysis complete)     |
| Bloomberg data integration    | Research phase (SDK and API exploration)            |
| BIPO HRMS integration         | Research phase (SAML SSO and API documented)        |
| Expert escalation / HITL routing | Removed from scope — deferred to future pivot |

## Intended Use Cases

### Primary Use Cases

1. **Enterprise Q&A**: "What is our travel reimbursement policy?" -- Searches HR policies index, returns synthesized answer with policy document link
2. **Cross-domain research**: "Compare Q3 revenue projections with engineering headcount growth" -- Routes to Finance and HR indexes simultaneously, synthesizes cross-domain answer
3. **Private document Q&A**: Manager uploads strategy draft, asks "What are the key initiatives in my Q4 strategy?" -- Searches personal docs alongside enterprise content
4. **Content gap discovery**: Analytics dashboard reveals 85 queries about "remote work equipment policies" with no results -- drives content creation
### Emerging Use Cases (from research folder)

6. **Financial data Q&A**: Integrate Bloomberg data and Oracle Fusion financials via MCP for real-time financial queries
7. **HR self-service**: Connect BIPO HRMS for leave balances, employee data via AI chat
8. **AI-assisted email triage**: Agent mailbox receives inbound emails, routes them to appropriate users via multi-layer matching
9. **Proactive notifications**: Background tasks complete, agent sends notifications to users via email/SSE

## Product Stage Assessment

The product is in a **mature MVP / early production** stage for single-tenant deployment. It has comprehensive functionality covering the full lifecycle of enterprise knowledge search -- from authentication through analytics. The architecture is production-ready with security hardening (CSRF, rate limiting, secret validation, security headers), observability (OpenTelemetry, structured logging), and operational features (circuit breakers, cache warming, background jobs).

The primary gap is **multi-tenancy** -- the current architecture serves a single enterprise. Expanding to a platform that serves multiple enterprises would require significant architectural changes to data isolation, configuration management, and tenant administration.
