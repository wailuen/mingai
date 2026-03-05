# mingai Architecture Decision Records (ADRs) - Comprehensive Summary

**Document Version**: 1.0
**Date**: 2026-03-04
**Scope**: Summary of all existing ADRs (001-007) with implications for multi-tenant rebuild

---

## Executive Summary

mingai has 7 documented Architecture Decision Records (ADRs) that establish the core technical and organizational decisions made during initial development (2025-12-19 through 2026-02-07). These ADRs define:

1. **Technology Stack** (ADR-001): Python/FastAPI backend, React/Next.js frontend, Azure CosmosDB, Azure OpenAI
2. **Access Control** (ADR-002): RBAC with synthetic role IDs, Azure AD group integration, 10 design gaps identified in 2026-02 operational review
3. **Service Architecture** (ADR-003): 12-service microservices model with pragmatic boundaries
4. **Privacy Model** (ADR-004): Privacy-first design with OneDrive storage for personal documents, opt-in profiling
5. **LLM Orchestration** (ADR-005): Multi-stage pipeline (intent → search → synthesis → confidence scoring)
6. **Event System** (ADR-006): Unified events container consolidating audit + analytics (in migration)
7. **MCP UI Rendering** (ADR-007): Structured JSON responses for rich component rendering (proposed)

**Critical for Multi-Tenant Rebuild**:

- ADR-002 has 10 documented design gaps from operational review requiring fixes (TODO-73)
- ADR-006 shows data model is undergoing unification (dual-write period)
- ADR-001 assumes single-tenant; multi-tenant will require credential/config changes (see Kaizen analysis)
- All microservices assume single organizational context; tenant isolation will be needed

---

## ADR-001: Technology Stack Selection

**Status**: ✅ Accepted
**Date**: 2025-12-19
**Next Review**: 2026-06-19

### Decision Summary

| Layer          | Technology                                 | Rationale                                               |
| -------------- | ------------------------------------------ | ------------------------------------------------------- |
| **Frontend**   | React + Next.js + TypeScript               | Productivity, existing team expertise, rich ecosystem   |
| **Backend**    | Python 3.11+ + FastAPI                     | Python AI/ML libraries, async support, auto-docs        |
| **Database**   | Azure CosmosDB (NoSQL)                     | Flexible schema, scales horizontally, vector indexing   |
| **LLM**        | Azure OpenAI (GPT-5.2-chat, GPT-5 Mini)    | Azure integration, proven quality, enterprise support   |
| **Search**     | Azure AI Search (vector-enabled)           | Existing indexes, semantic search, embeddings           |
| **Auth**       | Azure AD + OAuth 2.0 + JWT                 | Enterprise SSO, org hierarchy, group management         |
| **Storage**    | OneDrive + Azure Blob + CDN                | User-owned personal docs, static assets, compliance     |
| **Deployment** | Azure Container Apps (serverless)          | Docker Compose local, Container Apps production         |
| **CI/CD**      | GitHub Actions                             | Native to GitHub, simple workflows                      |
| **Monitoring** | Azure Application Insights + OpenTelemetry | Distributed tracing, structured logging, custom metrics |

### Implications for Multi-Tenant Rebuild

**Positive**:

1. Azure-first design makes multi-tenant on Azure straightforward
2. CosmosDB can be partitioned by tenant_id at container level
3. Container Apps stateless design enables horizontal scaling per tenant
4. Azure AD can federate multiple enterprise tenants

**Challenges**:

1. **No Provider Abstraction** - Only Azure OpenAI; multi-tenant may want different providers per tenant (see Kaizen analysis)
2. **Shared Infrastructure** - All tenants share same Container Apps instances, CosmosDB account, Application Insights (requires isolation at application layer)
3. **Cost Model** - Pay-per-use is good for single tenant; multi-tenant needs chargeback per tenant
4. **Data Residency** - Single Azure region; multi-tenant may require different regions per customer

### Key Decisions to Preserve

- ✅ Keep FastAPI (excellent for microservices)
- ✅ Keep CosmosDB (flexible for evolving multi-tenant schema)
- ✅ Keep Container Apps (great for scaling services per tenant)
- ⚠️ Consider abstracting LLM provider (currently hardcoded to Azure OpenAI)
- ⚠️ Implement tenant isolation in application layer (separate workspaces, filtered queries)

---

## ADR-002: RBAC and Access Control Model

**Status**: ✅ Accepted (Revised 2026-02-27)
**Date**: 2025-12-19
**Next Review**: 2026-06-19

### Decision Summary

**Model**: Role-Based Access Control (RBAC) with flat role structure, additive permissions, synthetic role IDs

**Core Roles** (10 system roles):

1. **Default** - Auto-assigned, basic access
2. **role_admin** - Manages custom roles + assignments
3. **index_admin** - Manages knowledge bases + glossaries
4. **user_admin** - Manages users + role assignments
5. **analytics_viewer** - Views analytics dashboards
6. **audit_viewer** - Views audit logs
7. **integration_admin** - Manages MCP server configs
8. **glossary_admin** - Manages glossary terms
9. **feedback_viewer** - Views user feedback
10. **sync_admin** - Monitors sync worker jobs

**Permission Types**:

- **Index Permissions** - List of index IDs user can query
- **System Permissions** - Map to synthetic role IDs (e.g., `role:manage` → `role_admin`)

**Data Model**:

- Users table (name, email, department, attributes from Azure AD)
- Roles table (name, description, permissions)
- User Roles table (direct assignments)
- Group Roles table (Azure AD group assignments)

### Critical Design Gaps (Found 2026-02 Operational Review - TODO-73)

| Severity     | Gap                                              | Impact                                                         | Status                    |
| ------------ | ------------------------------------------------ | -------------------------------------------------------------- | ------------------------- |
| **Critical** | `integration:manage` had no synthetic role ID    | MCP admin nav hidden, 403 on all MCP routes                    | Phase 1 fix pending       |
| **Critical** | Nav items gated on bare `admin` only             | Delegated admin roles couldn't see sections they had access to | Phase 2 fix pending       |
| **High**     | `user:manage` didn't work in user_endpoints.py   | User admin couldn't manage users                               | Phase 2 fix pending       |
| **High**     | Azure AD search endpoints unprotected            | Any authenticated user could enumerate users/groups            | Phase 2 fix pending       |
| **High**     | 3 inconsistent permission-checking mechanisms    | Code complexity, divergence risk                               | Phase 3 unify pending     |
| **Medium**   | `glossary:manage`, `feedback:view` never checked | Cosmetic UI choices with no backend effect                     | Phase 1 validate          |
| **Medium**   | No validation of system function strings         | Typos persist silently, never grant access                     | Phase 4 hardening pending |
| **Low**      | `content_manager` role defined nowhere           | Dead code, confusion                                           | Phase 3 cleanup           |
| **Low**      | No unit tests for role expansion function        | Most critical function untested                                | Phase 4 hardening pending |
| **Low**      | System function list hardcoded in 3 places       | Must stay in sync manually                                     | Phase 4 hardening pending |

### 9-Phase Remediation Plan (TODO-73)

- **Phases 1-5** (original implementation, ✅ complete): Core RBAC, Azure AD, Admin UI, Testing, Docs
- **Phases 6-9** (2026-02 fixes, 🔄 in progress):
  - Phase 6: Complete system function → synthetic role ID mapping
  - Phase 7: Fix broken delegations (user endpoints, Azure AD search, glossary)
  - Phase 8: Unify backend permission checking patterns
  - Phase 9: Hardening (enum validation, unit tests, canonical list endpoint)

### Implications for Multi-Tenant Rebuild

**Must Fix Before Multi-Tenant**:

1. Complete TODO-73 remediations (all 9 phases)
2. Add tenant-level RBAC on top of existing model (e.g., tenant_admin role)
3. Implement role scope isolation (roles only valid within tenant)
4. Handle Azure AD groups that span multiple tenants

**Architectural Changes**:

- Add `tenant_id` to all role assignments (users, groups)
- Implement tenant-aware permission service (`get_effective_permissions(user_id, tenant_id)`)
- Separate role namespaces per tenant (avoid role ID conflicts)

### Recommendation

**DO NOT PROCEED** with multi-tenant implementation until ADR-002 TODO-73 remediation is 100% complete. The current gaps will multiply in multi-tenant (e.g., same gap affects all tenants equally, creating security issues).

---

## ADR-003: Microservices Architecture

**Status**: ✅ Accepted
**Date**: 2025-12-19
**Next Review**: 2026-03-19 (3 months - shorter for architectural significance)

### Decision Summary

**Model**: Pragmatic microservices with 12 domain-driven services

**Core Services**:

| Service                  | Technology          | Responsibility                        | Database                   | Load       |
| ------------------------ | ------------------- | ------------------------------------- | -------------------------- | ---------- |
| **API Gateway**          | FastAPI             | Route, auth, CORS, rate limit         | None                       | High       |
| **Auth Service**         | FastAPI             | OAuth2, JWT, session mgmt             | CosmosDB (sessions)        | High       |
| **User Service**         | FastAPI             | User CRUD, profiles, preferences      | CosmosDB (users)           | Medium     |
| **Role Service**         | FastAPI             | RBAC, permissions, assignments        | CosmosDB (roles, mappings) | Medium     |
| **Search Service**       | FastAPI             | AI Search queries, index selection    | None (Azure AI Search)     | High       |
| **LLM Orchestrator**     | FastAPI + LangChain | Intent, synthesis, confidence scoring | None (stateless)           | High       |
| **Conversation Service** | FastAPI             | Chat history, message storage         | CosmosDB (conversations)   | Medium     |
| **Document Service**     | FastAPI             | Upload, extract, vectorize, OneDrive  | None (OneDrive)            | Low-Medium |
| **Index Service**        | FastAPI             | Register indexes, metadata, health    | CosmosDB (indexes)         | Low        |
| **Analytics Service**    | FastAPI             | Query aggregation, metrics, reports   | CosmosDB (analytics)       | Low        |
| **Audit Service**        | FastAPI             | Event logging, compliance             | CosmosDB (audit_logs)      | Medium     |
| **Notification Service** | FastAPI (Phase 2)   | Email, Teams, escalations             | CosmosDB (queue)           | Low        |

**Communication**:

- **Sync (REST)**: Primary pattern, 5s timeout, 3x retry, circuit breaker
- **Async (Future)**: Azure Service Bus for analytics, notifications

**Data Architecture**:

- Physical: Single CosmosDB account
- Logical: Each service owns dedicated containers (equivalent to schema)
- Access: Service-to-service APIs only (no direct cross-service DB access)

**Deployment**:

- Local: Docker Compose with all services + CosmosDB Emulator
- Production: Azure Container Apps, each service auto-scales independently

### Implications for Multi-Tenant Rebuild

**Positive**:

1. Service boundaries are clear; tenant isolation can be implemented per-service
2. Stateless design (no in-memory state) enables independent scaling per tenant
3. Container Apps enables isolating workloads by tenant if needed

**Changes Required**:

1. **Tenant Context Propagation** - Pass `tenant_id` through all service-to-service calls (header or JWT claim)
2. **Database Partitioning** - Partition each service's CosmosDB containers by tenant_id
3. **Isolation Options**:
   - **Option A (Shared Infrastructure)**: Same services, query-level tenant filtering
   - **Option B (Isolated Services)**: Separate service instances per tenant (complex, expensive)
   - **Recommendation**: Option A with strong query-level filtering

### Recommendation

**ADR-003 is well-designed for multi-tenant**. No major changes needed. Focus on:

1. Implement tenant_id propagation in API Gateway
2. Update all services to partition data by tenant_id
3. Add integration tests for cross-tenant data isolation

---

## ADR-004: User Data and Privacy Approach

**Status**: ✅ Accepted
**Date**: 2025-12-19
**Next Review**: 2026-06-19

### Decision Summary

**Model**: Privacy-first design with user data ownership and opt-in features

**Data Categories**:

| Category             | Stored Where          | User Control   | Retention                |
| -------------------- | --------------------- | -------------- | ------------------------ |
| **Org Attributes**   | CosmosDB (users)      | Read-only      | Active + 3 years archive |
| **Conversations**    | CosmosDB (messages)   | Delete anytime | 3 years rolling          |
| **Personal Docs**    | User's OneDrive       | Full control   | Until deleted            |
| **Profile Learning** | CosmosDB (profiles)   | CRUD, opt-in   | Until deleted            |
| **Audit Logs**       | CosmosDB (audit_logs) | View only      | 3 years compliance hold  |
| **Analytics**        | CosmosDB (analytics)  | Anonymized     | 1 year                   |

**User Controls** (GDPR-aligned):

- **Right to Access** - Export all data (JSON)
- **Right to Rectification** - Edit profile, delete docs
- **Right to Erasure** - Delete conversations, profile, documents (not audit logs or anonymized analytics)
- **Right to Data Portability** - Export function
- **Right to Restrict** - Disable profiling anytime
- **Right to Object** - Limited (can disable profiling, cannot opt-out of core features)

**Profiling Model**:

- **Default**: OFF (opt-in required)
- **Consent**: Explicit consent notice before enabling
- **Data**: Learned interests, expertise, communication style
- **User Deletable**: Yes
- **Re-enable**: Users can re-enable and learn again

### Implications for Multi-Tenant Rebuild

**Positive**:

1. Privacy model is org-agnostic (works for any tenant)
2. OneDrive storage means no data lock-in per tenant
3. Clear data lifecycle (3-year retention) works for multi-tenant compliance

**Changes Required**:

1. Add `tenant_id` to all user data tables (users, profiles, conversations, audit_logs)
2. Implement tenant-aware data deletion (when tenant is deleted, cascade)
3. Support multi-tenant data residency (some tenants may require region-specific storage)

**Data Residency Consideration**:

- ADR-004 does not address multi-region requirements
- Multi-tenant may require GDPR compliance (EU data in EU, etc.)
- OneDrive is tied to user's organization; multi-tenant needs strategy for handling cross-org users

### Recommendation

**ADR-004 is compatible with multi-tenant**. Ensure:

1. Privacy policies are tenant-specific (enterprise can customize)
2. Data residency is configurable per tenant (region selection)
3. Compliance holds per tenant (some may need longer audit retention)

---

## ADR-005: LLM Orchestration Strategy

**Status**: ✅ Accepted
**Date**: 2025-12-19
**Next Review**: 2026-03-19 (3 months - LLM landscape evolving)

### Decision Summary

**Model**: 4-stage LLM pipeline for high-quality RAG

```
Query → [Stage 1: Intent] → [Stage 2: Search] → [Stage 3: Synthesis] → [Stage 4: Confidence] → Response
```

**Stage Details**:

| Stage         | LLM          | Duration | Cost   | Input                   | Output                    |
| ------------- | ------------ | -------- | ------ | ----------------------- | ------------------------- |
| 1. Intent     | GPT-5 Mini   | <1s      | $0.001 | Query, indexes, history | Index selection, language |
| 2. Search     | None (API)   | <2s      | $0     | Selected indexes        | Top chunks (20 max)       |
| 3. Synthesis  | GPT-5.2-chat | <3s      | $0.015 | Query, chunks, history  | Full answer + sources     |
| 4. Confidence | GPT-5 Mini   | <1s      | $0.001 | Query, answer, sources  | Score 0.0-1.0             |

**Architecture**:

- **Input**: Query + conversation history + user profile + org context
- **Output**: Answer + sources + confidence + metadata
- **Context Management**: History summarization for >10 messages, user profile (opt-in)
- **Multi-Language**: Language detection in Stage 1, response in detected language
- **Fallbacks**: Graceful degradation at each stage
- **Caching**: Redis for intent, search results (5m TTL), permissions (1h TTL)

**Cost Optimization**:

- GPT-5 Mini for cheap tasks (intent $0.001, confidence $0.001)
- GPT-5.2-chat only for synthesis ($0.015 per query)
- **Total cost**: ~$0.017 per query
- **Budget**: 1000 queries/day = ~$17/day = $510/month

### Implications for Multi-Tenant Rebuild

**Challenges**:

1. **Cost Attribution** - Need to track LLM spend per tenant/conversation
2. **Provider Selection** - Currently hardcoded to Azure OpenAI; multi-tenant may want different providers
3. **Rate Limiting** - Need per-tenant rate limits (don't let one tenant exhaust quota)
4. **Quality Variability** - Different LLM providers have different quality; users may compare

**Changes Required**:

1. Track `tenant_id` in all LLM calls for cost chargeback
2. Implement per-tenant LLM quotas/budgets
3. Support multiple LLM providers (see Kaizen analysis - currently missing)
4. A/B test LLM quality per tenant (allow tenant to select provider preference)

### Recommendation

**ADR-005 is compatible with multi-tenant with changes**:

1. Extend cost tracking to include tenant_id
2. Implement provider abstraction (don't hardcode Azure OpenAI)
3. Per-tenant LLM provider selection (once Kaizen integrations added)
4. Per-tenant budget/quota enforcement

---

## ADR-006: Unified Events System

**Status**: ✅ Accepted
**Date**: 2026-02-07
**Next Review**: 2026-05-01 (3 months)

### Decision Summary

**Problem**: Two separate event containers (`audit_logs`, `usage_events`) created:

- Data duplication (same action logged twice)
- Correlation difficulty (cross-container joins not supported)
- Dual-write complexity (two code paths)
- Granular event sprawl (too many small events)

**Solution**: Single unified `events` container with richer events

**Design**:

- **Schema**: Unified `UnifiedEvent` with common fields (user_id, session_id, conversation_id, timestamp, cost, etc.)
- **Partition Key**: `user_id:YYYY-MM` (monthly per-user partitions)
- **Retention**: Configurable (default 365 days)
- **11 Composite Indexes**: Optimized for common queries (user timeline, event type, admin filtering, conversation drill-down)

**Event Types** (high-level categories):

- `session` - Login/logout
- `chat` - Chat interactions (query + synthesis)
- `admin` - Role changes, permissions
- `kb_sync` - Knowledge base syncs
- `document` - Document uploads/deletes
- `conversation` - Conversation lifecycle
- `blob` - Blob storage ops

**Key Principle**: **Fewer, richer events** (e.g., one `chat_interaction` event replaces 4 granular events)

**Migration Strategy** (5 phases):

1. **Dual Write** (current): Both containers receive writes
2. **Historical Migration**: Migrate audit_logs to events
3. **Validation**: Verify consistency
4. **Cutover**: Admin UI reads from events only
5. **Analytics** (deferred, TODO-54J): Migrate usage_events to events

**Backward Compatibility**: Conversion methods for existing `AuditService.log_event()` and usage trackers

### Implications for Multi-Tenant Rebuild

**Positive**:

1. Unified events enable tenant-level analytics (per-tenant cost, usage)
2. Partition key can be extended (`tenant_id:user_id:YYYY-MM`)
3. Session correlation enables tracking user journeys per tenant

**Changes Required**:

1. Add `tenant_id` to all events
2. Update partition key strategy (include tenant_id)
3. Per-tenant event retention policies (some tenants may need longer/shorter)
4. Per-tenant analytics views (aggregate by tenant)

**Analytics Migration (TODO-54J)**:

- Currently deferred; multi-tenant should complete this before launch
- Analytics dashboards need tenant filtering + tenant-specific cost attribution

### Recommendation

**ADR-006 is well-positioned for multi-tenant**:

1. Ensure TODO-54J is completed before multi-tenant
2. Update partition key to include tenant_id
3. Implement tenant-scoped analytics views

---

## ADR-007: MCP Structured JSON Responses for Rich UI Rendering

**Status**: 🟡 Proposed (not yet implemented)
**Date**: 2026-01-01
**Next Review**: 2026-04-01 (3 months)

### Decision Summary

**Problem**: MCP tool results returned as unstructured data:

- Backend sends raw data but frontend only captures `dataType` hint
- Frontend can't render rich UI (calendars, grids, cards)
- No type safety between backend and frontend

**Solution**: Structured JSON envelope with UI type mapping

**JSON Envelope**:

```typescript
interface MCPStructuredResponse<T> {
  version: "1.0";
  success: boolean;
  ui_type: MCPUIType; // calendar_timeline, availability_grid, event_card, etc.
  data: T | null;
  metadata: { tool_name; server_id; latency_ms; item_count; truncated };
  error?: { code; message; recoverable; recovery_action };
}
```

**Supported UI Types** (with corresponding renderers):

1. `calendar_timeline` - CalendarTimeline.tsx
2. `availability_grid` - AvailabilityGrid.tsx
3. `event_card` - EventCard.tsx
4. `user_profile_card` - UserProfileCard.tsx
5. `action_confirmation` - ActionConfirmation.tsx
6. `data_table` - DataTable.tsx (generic)
7. `generic_json` - GenericResult.tsx (fallback)

**Implementation**:

- **Backend**: Wrap tool results in envelope before emitting via SSE
- **Frontend**: Capture `data` field in `useChatStream.ts`, use `MCPResultRenderer` to dispatch to appropriate component
- **Transformers**: Tool-specific transformers (e.g., `transform_calendar_events`) normalize raw Microsoft Graph data to schema

**4-Week Implementation Plan**:

- Week 1: Foundation (fix data capture, add schemas)
- Week 2: Calendar components
- Week 3: Collaboration (availability, confirmations)
- Week 4: Profile, table, documentation

### Implications for Multi-Tenant Rebuild

**Positive**:

1. Structured responses are org-agnostic (work for any tenant)
2. Rich UI helps multi-tenant adoption (better UX)
3. Extensible design (new UI types add incrementally)

**Considerations**:

1. Some MCP servers may be tenant-specific (not applicable)
2. Branding - Multi-tenant may want customized styling per tenant

### Recommendation

**ADR-007 should proceed in parallel with multi-tenant work**:

1. Not blocking for multi-tenant launch
2. Improves user experience (helps with adoption)
3. Implement as proposed; no tenant-specific changes needed

---

## Cross-ADR Implications for Multi-Tenant Rebuild

### Critical Dependencies

| Blocking        | ADR     | Issue                             | Fix Required                            |
| --------------- | ------- | --------------------------------- | --------------------------------------- |
| 🔴 **CRITICAL** | ADR-002 | RBAC has 10 design gaps           | Complete TODO-73 before multi-tenant    |
| 🟡 **HIGH**     | ADR-001 | LLM hardcoded to Azure OpenAI     | Implement provider abstraction (Kaizen) |
| 🟡 **HIGH**     | ADR-006 | Analytics still in `usage_events` | Complete TODO-54J migration             |
| 🟢 **LOW**      | ADR-007 | Not yet implemented               | Can proceed in parallel                 |

### Recommended Implementation Order

1. **Phase 1**: Fix ADR-002 (TODO-73 all phases) + ADR-006 (TODO-54J)
2. **Phase 2**: Implement Kaizen LLM provider abstraction (supports multi-tenant config)
3. **Phase 3**: Extend all services for tenant isolation:
   - Add tenant_id to all relevant tables/queries
   - Implement tenant context propagation (all 12 services)
   - Per-tenant RBAC scope
   - Per-tenant event/analytics partitioning
4. **Phase 4**: Implement multi-tenant platform features (admin console, tenant management, billing)
5. **Phase 5**: ADR-007 MCP rich UI (in parallel, not blocking)

### Data Model Evolution for Multi-Tenant

**Current (Single-Tenant)**:

- users (name, email, department...)
- roles (permissions, indexes)
- conversations (user_id, messages)
- events (user_id, timestamp, action)

**Multi-Tenant (Required)**:

- tenants (id, name, subscription_level, region, max_users)
- users (**tenant_id**, name, email, role_within_tenant)
- roles (**tenant_id**, permissions scoped to tenant)
- conversations (**tenant_id**, user_id, messages)
- events (**tenant_id**, user_id, session_id, conversation_id, action)
- llm_providers (**tenant_id**, provider_type, endpoint, key_encrypted)
- tenant_llm_settings (**tenant_id**, preferred_provider_id)

### Technology Stack - No Major Changes Needed

- ✅ Python/FastAPI - Works for multi-tenant
- ✅ React/Next.js - Works for multi-tenant
- ✅ Azure CosmosDB - Can partition by tenant_id
- ✅ Azure Container Apps - Scales per tenant if needed
- ⚠️ Azure OpenAI - Need multi-provider abstraction (Kaizen)
- ✅ Azure AD - Can federate multiple orgs

---

## Review Schedule

| ADR         | Status             | Last Review | Next Review | Owner                  |
| ----------- | ------------------ | ----------- | ----------- | ---------------------- |
| **ADR-001** | Accepted           | 2025-12-19  | 2026-06-19  | Architecture Team      |
| **ADR-002** | Accepted (Revised) | 2026-02-27  | 2026-06-19  | Engineering + Security |
| **ADR-003** | Accepted           | 2025-12-19  | 2026-03-19  | Engineering            |
| **ADR-004** | Accepted           | 2025-12-19  | 2026-06-19  | Legal + Compliance     |
| **ADR-005** | Accepted           | 2025-12-19  | 2026-03-19  | AI Team                |
| **ADR-006** | Accepted           | 2026-02-07  | 2026-05-01  | Engineering            |
| **ADR-007** | Proposed           | 2026-01-01  | 2026-04-01  | Frontend Team          |

---

## Key Takeaways for Architecture Team

### ADR-002: NOT READY for Multi-Tenant ❌

- 10 design gaps found in operational review (2026-02)
- TODO-73 remediation required (Phases 6-9)
- **Action**: Block multi-tenant until TODO-73 complete

### ADR-001, ADR-003, ADR-004: Ready ✅

- Technology stack is multi-tenant-friendly
- Minor additions needed (tenant_id propagation, partitioning)
- No major architectural changes

### ADR-005: Needs LLM Provider Abstraction ⚠️

- Currently hardcoded to Azure OpenAI
- See Kaizen analysis for implementation plan
- Multi-tenant needs per-tenant provider selection

### ADR-006: In Progress 🔄

- Dual-write period ongoing
- Analytics migration (TODO-54J) not yet scheduled
- **Action**: Complete before multi-tenant for unified cost attribution

### ADR-007: Parallel ▶️

- Can implement alongside multi-tenant work
- Improves user experience, not blocking

---

## Appendix: ADR Status Timeline

```
2025-12-19: ADR-001 through ADR-005 accepted (initial architecture)
2026-01-01: ADR-007 proposed (MCP rich UI)
2026-02-07: ADR-006 accepted (unified events)
2026-02-27: ADR-002 revised with 10 design gaps + 9-phase fix plan (TODO-73)
2026-03-04: This summary document created
```

---

**Document Complete**
Generated: 2026-03-04
Status: Ready for Architecture Review + Multi-Tenant Planning
Blocking Issues: ADR-002 (TODO-73), ADR-006 (TODO-54J)
