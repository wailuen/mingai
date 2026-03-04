# mingai - Technical Architecture Executive Summary

**Date**: March 4, 2026
**Project**: mingai
**Status**: Single-Tenant MVP with Multi-Tenant Foundation

---

## Overview

mingai is a sophisticated **Retrieval-Augmented Generation (RAG)** platform designed for enterprise-scale intelligent document search and conversation management. It integrates Azure AI services (OpenAI, AI Search, Cosmos DB) with enterprise identity (Azure Entra ID) and role-based access control.

**Current State**: Single-tenant application with organizational context awareness
**Tech Stack**: Next.js 14 (frontend) + FastAPI (backend) + Azure (infrastructure)

---

## Key Capabilities

### 1. Intelligent Document Retrieval

- **Hybrid Search**: Vector + keyword search across enterprise knowledge bases
- **Multi-Index Queries**: Simultaneously query HR, Finance, Engineering, and custom indexes
- **Confidence Scoring**: Probabilistic metrics on answer quality
- **Source Attribution**: Clear citations for all retrieved information

### 2. Enterprise Authentication

- **Dual-Mode Auth**: Azure Entra ID SSO + Local authentication
- **RBAC Model**: Index-level, system-function-level, and data-level access controls
- **Azure AD Groups**: Dynamic role assignment via organizational groups
- **JWT Tokens**: 8-hour access tokens + 7-day refresh tokens

### 3. RAG Pipeline

```
Query → Intent Detection → Index Selection → Vector Search → Embedding Generation → LLM Synthesis → Confidence Scoring → Response
```

### 4. SharePoint Integration

- **Document Sync**: Automatic sync from SharePoint sites to search indexes
- **Change Tracking**: Incremental updates, change detection, delta sync
- **Access Isolation**: Per-user document visibility based on SharePoint permissions

### 5. Real-Time Collaboration

- **WebSocket Support**: Server-Sent Events (SSE) for streaming responses
- **Conversation Threads**: Multi-turn context management
- **Activity Tracking**: User behavior analytics and audit logs

---

## System Architecture

### Frontend Layer (Next.js 14)

- **Port**: 3022
- **Stack**: React 19 + TypeScript + TailwindCSS + shadcn/ui
- **State Management**: TanStack Query (React Query)
- **Real-Time**: WebSocket + SSE for streaming chat responses

### API Gateway (FastAPI)

- **Port**: 8022 (8021 internal)
- **Responsibilities**: Authentication, routing, rate limiting, CORS
- **Modularity**: All backend in single service (extractable into microservices)

### Microservices (Consolidated in One Container)

- **Auth Module**: JWT validation, Azure AD integration, token refresh
- **User Module**: User profiles, preferences, organizational context
- **Role Module**: RBAC enforcement, permission resolution
- **Chat Module**: RAG orchestration, LLM interaction, streaming
- **Conversation Module**: Thread management, message history
- **Index Module**: Search index configuration, metadata, access control
- **SharePoint Module**: Document sync, change tracking
- **Analytics Module**: Usage metrics, user behavior analysis
- **Admin Module**: Role management, system configuration
- **MCP Module**: Model Context Protocol server integration

### Data Layer

#### Azure Cosmos DB (NoSQL)

**Database**: `mingai-dev` or production equivalent

**Containers** (Partition Keys):
| Container | Partition Key | Purpose |
|-----------|---------------|---------|
| users | /id | User accounts, emails, profiles |
| roles | /id | Role definitions and permissions |
| user_roles | /user_id | User-to-role assignments |
| group_roles | /group_id | Azure AD group role mappings |
| indexes | /id | Search index metadata & credentials |
| conversations | /user_id | Chat conversation threads |
| messages | /conversation_id | Individual chat messages |
| events | /partition_key (user_id:YYYY-MM) | Unified audit & analytics events |
| glossary_terms | /scope | Enterprise glossary with embeddings |
| mcp_servers | /id | MCP server configurations |
| notifications | /user_id | Real-time push notifications (30-day TTL) |

#### Azure Search (Vector + Keyword)

- **Hybrid Search**: BM25 (keyword) + vector similarity
- **Embeddings**: text-embedding-3-large (3072 dimensions)
- **Top-K**: 5 results per index (configurable)
- **Min Score**: 0.6 (60% relevance threshold)
- **Indexes Created Dynamically**: Per knowledge base / SharePoint site

#### Redis Cache

- **Primary Use**: Session caching, rate limiting, cache warming
- **Key Prefix**: `aihub2:`
- **Pub/Sub**: Cross-instance cache invalidation (for multi-deployment scenarios)

#### Azure OpenAI (LLM)

- **Primary**: GPT-5.2-chat (chat, synthesis) - slow but highest quality
- **Auxiliary**: GPT-5 Mini (intent detection, fast operations)
- **Embeddings**: text-embedding-3-large (for document chunks)
- **Vision**: Separate vision model for image analysis
- **Token Limits**: 8K max output tokens, 0.7 temperature

---

## RAG Pipeline Deep-Dive

### Stage 1: Intent Analysis

- **Model**: GPT-5 Mini (fast, cheap)
- **Task**: Understand user intent, select relevant indexes
- **Output**: Selected indexes, language detection, internet search flag
- **Latency**: <1s

### Stage 2: Parallel Search

- **Vector Search**: Query each selected index in parallel
- **Top-K Aggregation**: 5 chunks per index, total 15-20 chunks
- **Scoring**: Vector similarity + keyword relevance
- **Deduplication**: Remove duplicate documents

### Stage 3: Response Synthesis (RAG)

- **Model**: GPT-5.2-chat (aihub2-main deployment)
- **Task**: Generate answer from retrieved chunks
- **Context**: Conversation history (last 10 messages, summarized >5K tokens)
- **Constraints**: Must cite sources, avoid hallucination

### Stage 4: Confidence Scoring

- **Metrics**:
  - Source agreement (multiple sources corroborate)
  - Vector similarity (avg relevance score)
  - Text analysis (confidence keywords)
  - Coverage assessment (all aspects covered)
- **Confidence Levels**: HIGH (>0.8), MEDIUM (0.6-0.8), LOW (<0.6)

---

## Authentication & Authorization

### JWT Token Structure

```json
{
  "user_id": "uuid",
  "email": "user@company.com",
  "roles": ["default", "finance_team"],
  "exp": 1234567890,
  "iat": 1234567000,
  "token_type": "access"
}
```

### RBAC Model

- **Default Role**: All new users automatically assigned
- **System Roles**: role_admin, index_admin, user_admin, analytics_viewer, audit_viewer
- **Additive Permissions**: User permissions = union of all assigned roles
- **Index Access**: User can only query indexes their roles permit
- **Azure AD Groups**: Dynamic assignment via group membership

### Permission Resolution

1. Load user from database
2. Get assigned roles (direct + Azure AD groups)
3. Get permissions for each role (index access, system functions)
4. Union all permissions
5. Enforce access control

---

## Current Single-Tenant Architecture

### How Tenant Isolation Works Today

**Reality**: No tenant field in any data model. System assumes single organization.

**Isolation Mechanisms**:

1. **Azure AD Tenant**: All users from one Azure Entra ID tenant
2. **Role-Based Filtering**: RBAC acts as de facto access control
3. **Data Partitioning**: Cosmos DB partition keys use user_id, not tenant_id
4. **Index Configuration**: Search indexes created per knowledge base, not per tenant
5. **SharePoint Integration**: Single SharePoint tenant configured in .env

### What Would Break for Multi-Tenancy

1. **No tenant_id field** in users, roles, indexes, conversations, etc.
2. **No tenant isolation** in Cosmos DB queries (partition key doesn't include tenant)
3. **No tenant routing** in API gateway
4. **No tenant-specific LLM deployments** (shared Azure OpenAI account)
5. **No tenant-aware search indexes** (indexes globally scoped)
6. **No cross-tenant data filtering** (would require code refactor)

---

## MCP (Model Context Protocol) Integration

The system includes MCP servers for external data sources:

- **Bloomberg MCP**: Financial data via Bloomberg Terminal API
- **CapIQ MCP**: Credit intelligence and company data
- **Perplexity MCP**: Web search integration
- **Oracle Fusion MCP**: ERP system integration
- **AlphaGeo MCP**: Geospatial intelligence
- **Teamworks MCP**: Project management integration
- **PitchBook MCP**: M&A and market intelligence
- **Azure AD MCP**: User/group lookup from Azure Entra ID
- **iLevel MCP**: Investment analytics

MCP servers expose tools callable during chat interactions for real-time data retrieval.

---

## Deployment

### Local Development

- **Docker Compose**: Defines frontend, API service, sync worker, Cosmos DB emulator, Redis, Mailhog
- **Network**: Bridge network + external enterprise network
- **Health Checks**: Each service has /health endpoint

### Production Readiness

- **Azure Resources**: Cosmos DB, Search, OpenAI, Blob Storage, App Service
- **Secrets Management**: Azure Key Vault
- **Monitoring**: Azure Application Insights
- **Scaling**: Horizontal scale via App Service instances

---

## Key Technical Decisions

| Aspect         | Decision                 | Rationale                                     |
| -------------- | ------------------------ | --------------------------------------------- |
| **Frontend**   | Next.js 14               | SSR, route segments, built-in optimization    |
| **Backend**    | FastAPI (single service) | Async/await native, fast, modular             |
| **Database**   | Cosmos DB                | Global scale, multi-region, Azure native      |
| **Search**     | Azure AI Search          | Vector + keyword hybrid, managed service      |
| **LLM**        | Azure OpenAI             | Enterprise SLA, dedicated capacity, RBAC      |
| **Identity**   | Azure Entra ID           | Enterprise standard, group-based RBAC         |
| **Auth**       | JWT + Azure AD OAuth     | Dual-mode flexibility, stateless              |
| **Caching**    | Redis                    | Session storage, rate limiting, cache warming |
| **Containers** | Docker Compose           | Local dev, easy on-ramp                       |

---

## Notable Gaps & TODOs

The system has 60+ tracked TODOs for future enhancements:

**Critical Path**:

- TODO-02C: Unified role-based access consolidation
- TODO-05: User profile learning (behavioral profiling)
- TODO-08: Usage analytics and cost tracking
- TODO-24: Distributed observability (Azure Monitor integration)
- TODO-54: Unified events system (audit & analytics consolidation)

**Infrastructure**:

- TODO-28: Cache warming and cross-instance invalidation
- TODO-51: GPT-5 migration (intent detection scaling)
- TODO-58: Real-time notifications (WebSocket push)

**Compliance**:

- TODO-04Q: HIPAA data handling compliance
- TODO-04T: Data residency and sovereignty options

---

## What's Missing for Multi-Tenancy

To become a true multi-tenant SaaS platform:

1. **Data Model Changes**: Add tenant_id to all containers
2. **Partition Key Changes**: Include tenant in partition keys for query optimization
3. **Cosmos DB Scaling**: Switch to shared provisioned throughput with tenant isolation policies
4. **Search Indexes**: Tenant-specific index creation, per-tenant analyzers
5. **Azure OpenAI**: Separate deployments or token-based quotas per tenant
6. **API Gateway**: Tenant extraction from JWT / subdomain / API key
7. **Sync Worker**: Tenant-aware SharePoint site selection
8. **Database Migration**: Separate databases per tenant OR robust row-level security
9. **Cost Tracking**: Per-tenant billing, resource quotas
10. **Onboarding**: Automated tenant provisioning, schema initialization

---

## Performance Characteristics

| Operation           | Target | Current          |
| ------------------- | ------ | ---------------- |
| Chat Response (RAG) | <3s    | ~2-3s (observed) |
| Intent Detection    | <1s    | <0.5s            |
| Vector Search       | <1s    | <0.5s            |
| Index Search        | <2s    | ~1-2s            |
| JWT Validation      | <10ms  | <1ms             |
| Role Resolution     | <50ms  | <10ms            |

---

## Security Posture

✅ **Implemented**:

- JWT token validation
- RBAC enforcement
- Azure AD integration
- HTTPS/TLS required
- CORS restrictions
- CSRF protection
- Input validation
- Rate limiting

⚠️ **In Progress**:

- Azure Key Vault secrets management
- Audit logging (migrating to unified events)
- Data encryption at rest
- Cross-region failover

❌ **Not Yet**:

- Multi-tenant row-level security
- Tenant-aware encryption keys
- Compliance certifications (SOC 2, HIPAA)

---

## Next Steps for Product Owners

1. **Validate Single-Tenant Roadmap**: Confirm MVP features before multi-tenant investment
2. **Plan Multi-Tenant Architecture**: Decide on isolation strategy (databases vs row-level security)
3. **Design Go-To-Market**: Pricing model, deployment options, customer onboarding
4. **Assess Scaling Needs**: Expected tenant count, data volume, concurrent users
5. **Plan Security Compliance**: Required certifications, data residency constraints

---

**Document Generated**: March 4, 2026
**For**: mingai Technical Review
**Prepared by**: Tech Explorer Agent
