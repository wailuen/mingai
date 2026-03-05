# Service Architecture & Microservices

## Overview

mingai implements a **modular monolith architecture**: All backend functionality runs in a single FastAPI container, organized into logical modules that can be extracted into independent microservices in the future.

**Current Deployment**: Single Docker container (`mingai_api_service`)
**Port**: 8022 (externally) → 8021 (internally)
**Language**: Python 3.12
**Framework**: FastAPI + Uvicorn (async/await)

---

## Service-to-Service Communication

```
┌──────────────────┐
│  Frontend (3022) │
└────────┬─────────┘
         │ HTTP/REST
         ▼
┌──────────────────────────────────────────────────────────────────────┐
│                          API SERVICE (8021)                          │
├──────────────────────────────────────────────────────────────────────┤
│                         FASTAPI ROUTER                               │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  GET/POST/PUT endpoints on /api/v1/*                          │  │
│  │  Middleware: Auth, Logging, CORS, CSRF, Security Headers      │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌─────────────────────────┬──────────────────────┬───────────────┐  │
│  │   Auth Module           │  User Module         │  Role Module  │  │
│  │ (Token validation)      │ (User CRUD)          │ (RBAC logic)  │  │
│  └─────────────────────────┴──────────────────────┴───────────────┘  │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Chat Module (RAG orchestration, intent detection, synthesis)  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Conversation, Index, SharePoint, Analytics, Admin, MCP, etc.  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │               Shared Service Library                           │  │
│  │  • Azure Search client                                         │  │
│  │  • Azure OpenAI client                                         │  │
│  │  • Cosmos DB utilities                                         │  │
│  │  • Redis operations                                            │  │
│  │  • LLM orchestration                                           │  │
│  │  • RAG pipeline components                                     │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Cosmos DB       │  │  Azure Search    │  │  Azure OpenAI    │
│  (Data)          │  │  (Full-text &    │  │  (LLM)           │
│                  │  │   vector search) │  │                  │
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

### Internal Service Communication

**Within same container** (not over network):

- Modules import and call each other directly
- Example: `ChatService` calls `IndexService.get_user_accessible_indexes()`
- No HTTP overhead
- Direct Python function calls

### Sync Worker (Separate Container)

```
┌────────────────────────────────┐
│  SYNC WORKER (port 8025)       │
├────────────────────────────────┤
│ Purpose: SharePoint doc sync   │
│ Trigger: Scheduled (cron) +    │
│          Manual via API        │
│                                │
│ Components:                    │
│ • SharePoint client            │
│ • Document processor           │
│ • Azure Search indexing        │
│ • Change tracking              │
│ • Incremental sync             │
└───────────┬────────────────────┘
            │
            ├─→ Cosmos DB (write document metadata)
            ├─→ Azure Search (create/update index)
            ├─→ Azure OpenAI (generate embeddings)
            └─→ SharePoint (read documents)
```

---

## Core Modules (18 Total)

### 1. Auth Module (`app/modules/auth/`)

**Responsibility**: Authentication, JWT token management, Azure AD integration

**Key Components**:

- `router.py` - Login, logout, token refresh endpoints
- `azure_ad_service.py` - Azure Entra ID OAuth flow
- `token_refresh_worker.py` - Background token refresh (proactive expiry handling)
- `schemas.py` - Request/response models

**Endpoints**:

```
POST   /api/v1/auth/login              (Azure AD OAuth initiation)
POST   /api/v1/auth/callback           (OAuth callback handler)
POST   /api/v1/auth/token/refresh      (JWT refresh)
POST   /api/v1/auth/logout             (Invalidate token)
GET    /api/v1/auth/current            (Get current user profile)
POST   /api/v1/auth/local/login        (Local dev authentication)
```

**Dependencies**: JWT (shared lib), Cosmos DB (users table)

---

### 2. User Module (`app/modules/users/`)

**Responsibility**: User profiles, preferences, organizational context

**Key Components**:

- `router.py` - User CRUD endpoints
- `user_service.py` - User business logic
- `user_endpoints.py` - Detailed user operations
- `org_context.py` - Build organizational profile strings
- `user_profile_service.py` - Learned profiles (TODO-05)

**Endpoints**:

```
GET    /api/v1/users/{user_id}         (Get user profile)
PUT    /api/v1/users/{user_id}         (Update profile)
GET    /api/v1/users                   (List users - admin only)
POST   /api/v1/users                   (Create user)
DELETE /api/v1/users/{user_id}         (Soft delete user)
GET    /api/v1/users/{user_id}/preferences
PUT    /api/v1/users/{user_id}/preferences
```

**Dependencies**: Cosmos DB (users container), Azure AD (group lookups), shared lib

---

### 3. Role Module (`app/modules/roles/`)

**Responsibility**: Role-based access control, permission resolution

**Key Components**:

- `router.py` - Role CRUD, assignment endpoints
- `rbac_service.py` - Permission evaluation logic
- `role_service.py` - Role business logic
- `permission_cache.py` - Redis-backed permission caching
- `group_sync_service.py` - Azure AD group → role mapping

**Endpoints**:

```
GET    /api/v1/roles                   (List roles)
POST   /api/v1/roles                   (Create role)
GET    /api/v1/roles/{role_id}         (Get role)
PUT    /api/v1/roles/{role_id}         (Update role)
DELETE /api/v1/roles/{role_id}         (Delete role)
GET    /api/v1/users/{user_id}/roles   (Get user's roles)
POST   /api/v1/users/{user_id}/roles   (Assign role to user)
DELETE /api/v1/users/{user_id}/roles/{role_id}
GET    /api/v1/roles/{role_id}/permissions
```

**Key Logic**:

```python
def get_user_permissions(user_id: str) -> dict:
    # 1. Load user from Cosmos DB
    user = users_collection.read_item(user_id, user_id)

    # 2. Get assigned roles (direct + Azure AD groups)
    roles = get_user_roles(user_id)  # union of direct + group roles

    # 3. Aggregate permissions (union of all role permissions)
    permissions = {}
    for role in roles:
        role_def = roles_collection.read_item(role.id, role.id)
        permissions.update(role_def.permissions)

    # 4. Cache in Redis for 1 hour
    cache.set(f"perms:{user_id}", permissions, 3600)

    return permissions
```

**Dependencies**: Cosmos DB, Redis, Azure AD (group lookups), shared lib

---

### 4. Chat Module (`app/modules/chat/`)

**Responsibility**: RAG orchestration, LLM interaction, streaming responses

**Key Components**:

- `router.py` - Chat streaming endpoint
- `search_orchestrator.py` - Multi-index parallel search
- `intent_service.py` - Intent detection & index selection
- `llm_generation.py` - GPT-5.2-chat response synthesis
- `confidence_scoring.py` - Answer quality metrics
- `message_persistence.py` - Store chat messages
- `context_window.py` - Conversation history management
- `handlers/` - Specialized chat handlers (web search, document upload, escalation)
- `agents/` - LLM-powered agents (context builder, query reformulation)

**Main Endpoint**:

```
POST /api/v1/chat/stream
Content-Type: application/json

{
  "conversation_id": "uuid",
  "query": "What are our HR policies?",
  "index_ids": ["optional", "index", "filter"],
  "use_internet_search": true
}

Response: Server-Sent Events (SSE)
- {"type": "status", "stage": "searching"}
- {"type": "sources", "sources": [{"title": "...", "score": 0.85}]}
- {"type": "response_chunk", "text": "To address your question..."}
- {"type": "metadata", "confidence": 0.82, "tokens_used": 450}
```

**RAG Pipeline**:

1. **Intent Analysis** (GPT-5 Mini): Detect intent, select indexes
2. **Parallel Search** (Azure Search): Query selected indexes
3. **Deduplication**: Remove duplicate documents
4. **Context Building** (agents): Inject user/org context
5. **Synthesis** (GPT-5.2-chat): Generate answer from sources
6. **Confidence Scoring**: Calculate answer quality
7. **Streaming**: Send response chunks via SSE

**Dependencies**: Azure Search, Azure OpenAI, Cosmos DB, shared lib, vector embeddings

---

### 5. Conversation Module (`app/modules/conversations/`)

**Responsibility**: Thread management, message persistence, history

**Key Components**:

- `router.py` - Conversation CRUD
- `conversation_service.py` - Business logic
- `message_service.py` - Message operations
- `history_manager.py` - Load/trim conversation history

**Endpoints**:

```
GET    /api/v1/conversations           (List user's conversations)
POST   /api/v1/conversations           (Create conversation)
GET    /api/v1/conversations/{conv_id} (Get conversation)
DELETE /api/v1/conversations/{conv_id} (Delete conversation)
GET    /api/v1/conversations/{conv_id}/messages
POST   /api/v1/conversations/{conv_id}/messages
PUT    /api/v1/conversations/{conv_id}/messages/{msg_id}
DELETE /api/v1/conversations/{conv_id}/messages/{msg_id}
```

**Data Model** (Cosmos DB):

```
conversations:
  - id: uuid
  - user_id: uuid (partition key)
  - title: string
  - created_at: timestamp
  - updated_at: timestamp
  - message_count: int
  - index_ids: list[str]

messages:
  - id: uuid
  - conversation_id: uuid (partition key)
  - user_id: uuid
  - role: "user" | "assistant"
  - content: string
  - sources: list[{title, score, url}]
  - confidence: float
  - tokens_used: int
  - created_at: timestamp
```

**Dependencies**: Cosmos DB, shared lib

---

### 6. Index Module (`app/modules/indexes/`)

**Responsibility**: Search index configuration, metadata, access control

**Key Components**:

- `router.py` - Index CRUD, configuration
- `index_service.py` - Index management
- `index_selector.py` - Intelligently select indexes for query

**Endpoints**:

```
GET    /api/v1/indexes                 (List accessible indexes)
POST   /api/v1/indexes                 (Create index - admin)
GET    /api/v1/indexes/{index_id}      (Get index metadata)
PUT    /api/v1/indexes/{index_id}      (Update index)
DELETE /api/v1/indexes/{index_id}      (Delete index - admin)
GET    /api/v1/indexes/{index_id}/stats (Index statistics)
GET    /api/v1/users/{user_id}/accessible-indexes
POST   /api/v1/indexes/{index_id}/sync (Trigger resync)
```

**Data Model** (Cosmos DB):

```
indexes:
  - id: uuid
  - name: string (e.g., "HR_Policies")
  - description: string
  - search_endpoint: string (Azure Search URL)
  - search_api_key: string (encrypted in Cosmos DB)
  - embedding_deployment: string
  - is_active: boolean
  - created_at: timestamp
  - updated_at: timestamp
  - stats: {doc_count, chunk_count, last_sync}
```

**Dependencies**: Azure Search, Cosmos DB, shared lib, encryption

---

### 7. SharePoint Module (`app/modules/sharepoint/`)

**Responsibility**: SharePoint site configuration, sync status, integration

**Key Components**:

- `router.py` - SharePoint configuration endpoints
- SharePoint client (in shared lib)
- Document processor (in shared lib)

**Endpoints**:

```
GET    /api/v1/sharepoint/status       (Connection status)
POST   /api/v1/sharepoint/connect      (Test connection)
GET    /api/v1/sharepoint/sites        (List available sites)
POST   /api/v1/sharepoint/sync         (Trigger sync job)
GET    /api/v1/sharepoint/sync-status  (Sync progress)
```

**Dependencies**: SharePoint Online (Microsoft Graph), shared lib

---

### 8. Analytics Module (`app/modules/analytics/`)

**Responsibility**: Usage metrics, user behavior, cost tracking

**Key Components**:

- `router.py` - Analytics query endpoints
- `usage_router.py` - Usage statistics
- `analytics_service.py` - Query execution
- `event_service.py` - Event collection (TODO-54)
- `usage_aggregation_service.py` - Daily/monthly aggregations

**Endpoints**:

```
GET    /api/v1/analytics/usage         (Overall usage stats)
GET    /api/v1/analytics/daily         (Daily breakdown)
GET    /api/v1/analytics/queries       (Top queries)
GET    /api/v1/analytics/indexes       (Index usage)
GET    /api/v1/analytics/costs         (Cost breakdown)
GET    /api/v1/analytics/users         (User metrics - admin)
```

**Data Collection**:

- **Event Types**: query, response, error, login, export, etc.
- **Partition**: `user_id:YYYY-MM` (for efficient timeline queries)
- **TTL**: 90 days (usage_events), configurable for events container
- **Aggregation**: Daily summaries computed at night

**Dependencies**: Cosmos DB (events, usage_daily), shared lib

---

### 9. Admin Module (`app/modules/admin/`)

**Responsibility**: System configuration, audit logs, admin operations

**Sub-modules**:

- `azure_router.py` - Azure resource monitoring
- `audit_router.py` - Audit log queries
- `system_router.py` - System health, config

**Endpoints**:

```
GET    /api/v1/admin/system/health     (System health)
GET    /api/v1/admin/audit/logs        (Audit log query)
GET    /api/v1/admin/audit/events      (Unified events)
GET    /api/v1/admin/azure/status      (Azure services status)
PUT    /api/v1/admin/system/config     (Update system config)
```

**Audit Logging**:

```python
# All significant actions logged to events container
event = {
  "id": uuid.uuid4(),
  "partition_key": f"{user_id}:{date.today().isoformat()}",
  "user_id": user_id,
  "email": user.email,
  "timestamp": datetime.now(UTC),
  "action": "role_assigned",  # or query, export, etc.
  "result": "success" | "failure",
  "details": {...}
}
```

**Dependencies**: Cosmos DB, shared lib, Azure Monitor

---

### 10. Feedback Module (`app/modules/feedback/`)

**Responsibility**: User feedback on AI responses (TODO-05C)

**Endpoints**:

```
POST   /api/v1/feedback                (Submit feedback)
GET    /api/v1/feedback                (List feedback - admin)
```

**Data Model**:

```
{
  "message_id": uuid,
  "rating": 1-5,
  "comment": string,
  "feedback_type": "accuracy" | "helpfulness" | "irrelevant",
  "created_at": timestamp
}
```

---

### 11. Notification Module (`app/modules/notifications/`)

**Responsibility**: Real-time notifications (TODO-58)

**Features**:

- Web push notifications (VAPIR keys configured)
- SSE stream to connected clients
- In-app notification display

**Endpoints**:

```
GET    /api/v1/notifications           (Get pending notifications)
DELETE /api/v1/notifications/{notif_id} (Mark as read)
```

**Data Model** (30-day TTL):

```
notifications:
  - id: uuid
  - user_id: uuid (partition key)
  - type: "query_complete" | "sync_done" | "error", etc.
  - title: string
  - body: string
  - action_url: string (optional)
  - created_at: timestamp
  - ttl: 2592000 (30 days in seconds)
```

---

### 12. Glossary Module (`app/modules/glossary/`)

**Responsibility**: Enterprise glossary with semantic search

**Endpoints**:

```
GET    /api/v1/glossary/terms          (List terms)
POST   /api/v1/glossary/terms          (Add term - admin)
GET    /api/v1/glossary/search         (Search glossary)
```

**Features** (TODO-04A):

- Embeddings for semantic similarity
- Multi-level categories
- Usage tracking
- Auto-detection in queries

---

### 13. KB Module (`app/modules/kb/`)

**Responsibility**: Knowledge base configuration (separate from indexes)

**Endpoints**:

```
GET    /api/v1/kb                      (List knowledge bases)
POST   /api/v1/kb                      (Create KB)
GET    /api/v1/kb/{kb_id}              (Get KB)
POST   /api/v1/kb/{kb_id}/documents    (Upload documents)
```

---

### 14. MCP Module (`app/modules/mcp/`)

**Responsibility**: Model Context Protocol server integration

**Features**:

- Dynamically invoke external MCP tools during chat
- Tool registry and schema validation
- Result streaming and error handling

**MCP Servers Supported**:

- Bloomberg (BBGDB)
- CapIQ
- Perplexity (web search)
- Oracle Fusion
- AlphaGeo
- Teamworks
- PitchBook
- Azure AD
- iLevel

**Endpoints**:

```
GET    /api/v1/mcp/servers             (List available servers)
GET    /api/v1/mcp/servers/{id}/tools (Get server tools)
```

---

### 15. Sync Worker Module (`app/modules/sync_worker/`)

**Responsibility**: Coordinate document sync (lives in separate container)

**Triggers**:

- Scheduled: Every 24 hours (configurable)
- Manual: API endpoint
- On-demand: User request

**Process**:

1. List SharePoint sites
2. Detect new/modified documents
3. Download documents
4. Extract text and images
5. Generate embeddings
6. Index into Azure Search
7. Store metadata in Cosmos DB
8. Update sync status

---

### 16. Async Tasks Module (`app/modules/async_tasks/`)

**Responsibility**: Long-running background operations

**Examples**:

- Document processing
- Bulk index updates
- Report generation
- Email sending

**Endpoints**:

```
GET    /api/v1/tasks/{task_id}         (Get task status)
```

---

### 17. Events Module (`app/modules/events/`)

**Responsibility**: Unified event collection (TODO-54)

**Status**: In progress - migrating from audit_logs + usage_events

**Event Types**:

- `query`: User search query
- `response`: AI response generated
- `error`: System error occurred
- `login`: User authentication
- `role_assigned`: RBAC change
- `export`: Data export
- `sync`: Document sync
- `feedback`: User feedback

---

### 18. API Health Router (`app/api/health_router.py`)

**Responsibility**: Service health checks

**Endpoint**:

```
GET /health

{
  "status": "healthy" | "degraded" | "unhealthy",
  "version": "1.0.0",
  "timestamp": "2026-03-04T00:00:00Z",
  "dependencies": {
    "database": {"status": "healthy", "response_time_ms": 5},
    "cache": {"status": "healthy", "response_time_ms": 2},
    "search": {"status": "healthy", "response_time_ms": 50},
    "openai": {"status": "healthy", "response_time_ms": 100}
  }
}
```

---

## Shared Service Library (`src/backend/shared/mingai_shared/`)

Reusable components across modules:

### Authentication (`auth/`)

- `jwt.py` - JWT creation/validation
- `middleware.py` - Request authentication
- `decorators.py` - Permission checking

### Database (`database/`)

- Connection pooling
- Query builders
- Transaction helpers

### Config (`config/`)

- Settings loader
- Environment validation

### Services (`services/`)

- **openai_client.py**: Azure OpenAI wrapper (embeddings, chat completion, vision)
- **embeddings.py**: Text embedding generation (cached)
- **document_processor.py**: PDF/DOC text extraction
- **sharepoint_client.py**: SharePoint API operations
- **vision_description.py**: Image analysis
- **image_extraction.py**: Extract images from documents
- **graph_utils.py**: Microsoft Graph utilities

### Models (`models/`)

- **base.py**: Pydantic base classes (UserBase, RoleBase, etc.)
- **schemas.py**: Common request/response schemas

### Logging (`logging/`)

- Structured JSON logging
- Request ID tracking
- Performance metrics

### Errors (`errors/`)

- Custom exception classes
- Error response formatting

### Redis (`redis/`)

- Connection pooling
- Cache operations
- Pub/Sub helpers

---

## Data Flow Examples

### Example 1: User Queries "HR Policies"

```
1. Frontend sends:
   POST /api/v1/chat/stream
   Authorization: Bearer <JWT>
   {"query": "What are our PTO policies?"}

2. Chat Router middleware:
   - Extract JWT
   - Validate signature
   - Load user from token payload
   - Get user's roles

3. Chat Service:
   a. Get accessible indexes
      - Call RoleModule.get_user_permissions()
      - Return indexes user can query

   b. Intent Detection
      - Send to Azure OpenAI (GPT-5 Mini)
      - Get: intent="HR_policy_question", indexes=["HR_Policies"]

   c. Search
      - Generate embedding for query (Azure OpenAI)
      - Vector search in Azure Search (hr-policies index)
      - Return top 5 chunks with scores

   d. Synthesis
      - Build prompt with retrieved chunks
      - Add conversation history (last 5 messages)
      - Add user's org context (department, job title)
      - Send to Azure OpenAI (GPT-5.2-chat)
      - Stream response via SSE

   e. Confidence Scoring
      - Analyze sources (all HR docs, credible)
      - Check source agreement (consistent across docs)
      - Generate confidence score
      - Send metadata

4. Store in Cosmos DB:
   - Save message in messages container
   - Record event in events container
   - Update conversation last_updated

5. Frontend receives SSE stream:
   - Display sources
   - Stream response text
   - Show confidence badge
```

### Example 2: Admin Assigns Role to User

```
1. Frontend sends:
   POST /api/v1/users/{user_id}/roles
   Authorization: Bearer <admin_JWT>
   {"role_id": "finance_team"}

2. Role Router:
   - Validate JWT
   - Extract user_id from token
   - Check permission: "role:manage"

3. Role Service:
   - Load role definition
   - Add user-to-role mapping in Cosmos DB
   - Invalidate user's permission cache
   - Log event to events container

4. Pub/Sub notification:
   - Publish to Redis: "cache_invalidate:perms:{user_id}"
   - Any other API instances listening will invalidate cache
```

---

## Deployment & Scaling

### Current (Single Container)

- All modules in one Docker container
- Scales horizontally (multiple instances)
- Shared database & cache
- Load balancer distributes requests

### Future (Microservices)

Extract modules into independent services:

- Chat Service (heaviest resource use)
- Search Service (parallel searches)
- Sync Worker (separate already)
- Analytics Service (batch processing)
- Admin Service (critical operations)

---

## Performance Considerations

### Hot Paths (Optimize)

- JWT validation (on every request) → Redis cache
- Role resolution (on every query) → 1-hour Redis cache
- User lookups → 5-minute cache
- Index lists → 30-minute cache

### Expensive Operations (Async)

- Document sync → Background task
- Bulk analytics aggregation → Nightly job
- Token refresh → Background worker
- Audit log writing → Async to Redis, batched to Cosmos

### Bottlenecks

1. **Azure OpenAI quota** - Rate limiting, queue management
2. **Cosmos DB throughput** - RU/s provisioning per container
3. **Azure Search latency** - Depends on index size, queries
4. **Network round-trips** - Parallel searches, batch operations

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
