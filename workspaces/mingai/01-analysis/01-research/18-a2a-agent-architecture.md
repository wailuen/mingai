# A2A Agent Architecture: Canonical Reference

**Date**: March 4, 2026
**Status**: Architecture Decision — Authoritative
**Source**: `04-multi-tenant/06-a2a-mcp-agentic.md`
**Purpose**: Correct terminology errors in prior research documents; provide canonical reference

---

## CRITICAL CORRECTION TO PRIOR DOCUMENTS

Multiple earlier research documents (`06-mcp-servers.md`, `00-executive-summary.md`, `01-service-architecture.md`) describe the 9 data integrations as **"MCP servers"** that users configure. **This is incorrect for the product direction.**

**Incorrect framing (mingai legacy)**:

> "Users register MCP servers. The LLM calls MCP tools directly."

**Correct framing (mingai product)**:

> "Platform ships agent templates. Tenants configure A2A agents by providing credentials. Agents internally use MCP — users never configure MCP."

This document is the authoritative reference. All other documents must be read in light of this correction.

---

## 1. Architecture Summary

mingai's external data integration is built on **three architectural layers**:

```
┌──────────────────────────────────────────────────────────────────────────┐
│  LAYER 1: A2A AGENTS (autonomous, LLM-powered — what tenants configure)  │
│                                                                          │
│  Bloomberg   CapIQ    Perplexity   Oracle Fusion   AlphaGeo              │
│  Teamworks   PitchBook   Azure AD   iLevel                               │
│  + Tenant custom agents (Enterprise plan)                                │
│  + External EATP-verified marketplace agents                             │
│                                                                          │
│  Each agent: Task in → LLM reasoning → internal MCP calls → Artifact out │
│                       ↑ USERS SEE THIS                                   │
├──────────────────────────────────────────────────────────────────────────┤
│  LAYER 2: TOOL CATALOG (deterministic, direct — no LLM, no A2A)         │
│                                                                          │
│  Tavily (internet search)  ·  Calculator  ·  Weather                    │
│  Platform Admin registers · Tenant Admin enables per org                 │
├──────────────────────────────────────────────────────────────────────────┤
│  LAYER 3: ORCHESTRATOR (DAG owner — dispatches tasks to agents)          │
│                                                                          │
│  Plans execution graph → dispatches A2A Tasks → collects Artifacts       │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key principle**: MCP is the **internal protocol** each agent uses to call its data source. It is never user-facing. Users configure agents; agents use MCP internally.

---

## 2. The 9 A2A Agents (Not MCP Servers)

| Agent                  | Internal Data Source       | Credential Type      | Who Owns Credential         |
| ---------------------- | -------------------------- | -------------------- | --------------------------- |
| Bloomberg Intelligence | Bloomberg Data License API | OAuth2 BSSO          | Tenant                      |
| CapIQ Intelligence     | S&P Capital IQ             | API key              | Tenant                      |
| Perplexity Web Search  | Perplexity API             | API key              | Platform (shared) or Tenant |
| Oracle Fusion          | Oracle Cloud REST          | JWT assertion        | Tenant                      |
| AlphaGeo               | AlphaGeo API               | API key              | Tenant                      |
| Teamworks              | Teamworks API              | API key              | Tenant                      |
| PitchBook Intelligence | PitchBook/Morningstar      | API key              | Tenant                      |
| Azure AD Directory     | MS Graph API               | OBO (user-delegated) | User (runtime)              |
| iLevel Portfolio       | iLevel API                 | API key              | Tenant                      |

**What tenants configure**: Agent credentials (OAuth tokens, API keys). Platform provides the agent logic, prompts, guardrails, and MCP configuration.

**What tenants do NOT configure**: MCP server URLs, MCP tool schemas, internal agent prompts (guardrails are platform-enforced and cannot be overridden).

---

## 3. What Users See vs. What Is Internal

### User-Facing (Tenant Admin UI)

```
Agent Catalog:
├── Bloomberg Intelligence Agent  [Enable] [Configure credentials]
├── CapIQ Intelligence Agent      [Enable] [Configure credentials]
├── Perplexity Web Search         [Enable] (platform-managed credentials)
├── Oracle Fusion Agent           [Enable] [Configure credentials]
└── [Request custom agent]
```

### Internal Platform Architecture (Not User-Visible)

```
Bloomberg Agent container:
├── Agent prompt + guardrails (platform-defined, immutable)
├── Bloomberg MCP server URL: http://bloomberg-mcp:9000
├── Tool schema: get_company_data, get_market_news, get_financials
└── Credential injection: vault token → Bloomberg OAuth2 flow
```

---

## 4. Credential Architecture

```
PLATFORM defines:   Agent template → credential SCHEMA (field names, types)
TENANT provides:    Credential VALUES (Bloomberg OAuth2 credentials, API keys)
USER provides:      OBO token for Azure AD (auto-delegated at runtime)
```

**Credential injection pattern** (credentials never stored in agent container):

1. Orchestrator resolves tenant credential from credential vault
2. Generates short-lived vault token (TTL = request timeout)
3. Injects into A2A Task request as encrypted header: `X-Agent-Credential: <vault-token>`
4. Agent exchanges vault token for actual credential via vault sidecar (in-memory only)
5. Agent calls its internal MCP server with credential
6. Vault token expires after request completes

---

## 5. Agent Communication Protocol: Google A2A v0.3

All agent communication uses Google A2A v0.3 (Linux Foundation standard, July 2025):

- **Task**: Natural language instruction from orchestrator to agent
- **Artifact**: Structured result returned by agent to orchestrator
- **AgentCard**: Published at `/.well-known/agent.json` for discovery
- **Transport**: HTTP+SSE+JSON-RPC 2.0

**Internal agent tool protocol**: Anthropic MCP (used by each agent to call its data source — invisible to orchestrator and users).

**External agent trust**: EATP (Enterprise Agent Trust Protocol) for marketplace verification.

---

## 6. Agent Template System (80/15/5)

**Platform-defined (80%)**: Agent prompt, guardrails, MCP configuration, AgentCard skills, LLM use-case assignment

**Tenant-configurable (15%)**: Credential values, role access control (which roles can invoke this agent), custom system prompt extension (optional)

**Custom development (5%)**: Custom agent implementation (Enterprise: BYOMCP — bring your own MCP server, wrapped as A2A agent)

---

## 7. Impact on Caching Architecture

### Correct Terminology for Caching Layer

**Incorrect** (from `14-caching-architecture-overview.md`, CACHE-C):

> "MCP Tool Response Cache — cache MCP tool call results"

**Correct**:

> "A2A Agent Response Cache — cache A2A Artifact responses returned by agents"

**Why this distinction matters**:

- MCP tool results are fetched internally by the agent; the orchestrator never sees raw MCP data
- The cacheable unit is the **A2A Artifact** (agent's synthesized response), not the raw MCP tool output
- Cache key must be based on the A2A Task description (natural language), not the internal MCP tool call parameters

### A2A Agent Cache TTL Policy (Replaces "MCP Tool TTL")

| Agent                  | Data Freshness          | Recommended Cache TTL |
| ---------------------- | ----------------------- | --------------------- |
| Bloomberg Intelligence | Real-time market prices | 15-60 seconds         |
| CapIQ Intelligence     | Company financials      | 4-12 hours            |
| Perplexity Web Search  | News and web content    | 1-4 hours             |
| Oracle Fusion          | ERP operational records | 15-60 minutes         |
| AlphaGeo               | Geospatial data         | 24 hours              |
| Teamworks              | Project status          | 5-15 minutes          |
| PitchBook Intelligence | M&A data                | 4-24 hours            |
| Azure AD Directory     | User/group membership   | 5-15 minutes          |
| iLevel Portfolio       | Investment records      | 30-60 minutes         |

**Key difference from MCP tool caching**: The A2A Artifact is already synthesized by the agent's internal LLM. The cached response is a reasoned answer, not raw data. Cache invalidation is time-based only (TTL) — not version-based, because agent responses reflect point-in-time analysis.

---

## 8. Documents Requiring Correction

The following documents contain incorrect "MCP server" terminology in user-facing contexts:

| Document                                                 | Line Range           | Correction Needed                                                                 |
| -------------------------------------------------------- | -------------------- | --------------------------------------------------------------------------------- |
| `01-research/00-executive-summary.md`                    | Lines 219-232        | "MCP servers" → "A2A agents"; list as agents not servers                          |
| `01-research/06-mcp-servers.md`                          | Entire file          | File describes OLD mingai architecture; superseded by this document               |
| `01-research/14-caching-architecture-overview.md`        | CACHE-C section      | "MCP Tool Response Cache" → "A2A Agent Response Cache"                            |
| `02-plans/01-implementation-roadmap.md`                  | Phase 4              | "MCP server registry" → "A2A agent registry"; "MCP routing" → "A2A agent routing" |
| `03-user-flows/01-platform-admin-flows.md`               | Section 4            | "Global MCP Server Management" → "Global A2A Agent Management"                    |
| `03-user-flows/02-tenant-admin-flows.md`                 | "Enable MCP Servers" | → "Enable A2A Agents"                                                             |
| `03-user-flows/04-platform-model-flows.md`               | Partners section     | "MCP server" → "A2A agent" for external data partners                             |
| `03-user-flows/05-caching-ux-flows.md`                   | EU-C4                | "MCP / Bloomberg" → "Bloomberg Intelligence Agent (A2A)"                          |
| `01-analysis/06-caching-product/01-value-proposition.md` | Connection section   | "MCP server health" → "A2A agent health"                                          |

---

## 9. What Stays the Same (Not Affected by A2A Change)

- All 9 data integrations are still present (Bloomberg, CapIQ, etc.) — only the framing changes
- Data freshness and cache TTL policies remain identical
- Tenant credential configuration is still required
- RBAC access control per agent (which roles can invoke which agents) is unchanged
- Cost attribution per agent invocation is unchanged

The A2A vs. MCP framing change is a **product language** and **architecture clarity** change, not a feature change.

---

**Document Version**: 1.0
**Authority Level**: Canonical — supersedes `06-mcp-servers.md` for product-facing terminology
**Source**: `04-multi-tenant/06-a2a-mcp-agentic.md` (Architecture Design v2.0)
