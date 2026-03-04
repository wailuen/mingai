# Data Models & Database Architecture

## Cosmos DB Overview

**Database**: Single multi-container NoSQL database
**Name**: `mingai-dev` (dev) or `aihub-prod` (production)
**Consistency**: Session (default), configurable to Strong for critical operations
**Partition Strategy**: Per-container partition keys (see table below)

---

## Container Structure (23 Total, 2 Deprecated)

| #   | Container               | Partition Key    | TTL        | Purpose                            | Indexes                                       |
| --- | ----------------------- | ---------------- | ---------- | ---------------------------------- | --------------------------------------------- |
| 1   | users                   | /id              | None       | User accounts                      | user_id, email                                |
| 2   | roles                   | /id              | None       | Role definitions                   | role_id, name                                 |
| 3   | user_roles              | /user_id         | None       | User-to-role assignments           | user_id, role_id                              |
| 4   | group_roles             | /group_id        | None       | Azure AD group roles               | group_id, role_id                             |
| 5   | group_membership_cache  | /group_id        | 24h        | Cached Azure AD memberships        | group_id, user_ids                            |
| 6   | indexes                 | /id              | None       | Search index metadata              | index_id, name, is_active                     |
| 7   | conversations           | /user_id         | None       | Chat threads                       | conversation_id, created_at                   |
| 8   | messages                | /conversation_id | None       | Chat messages                      | message_id, created_at, role                  |
| 9   | user_preferences        | /user_id         | None       | User settings                      | user_id, preference_name                      |
| 10  | glossary_terms          | /scope           | None       | Enterprise glossary                | term, category, scope (composite)             |
| 11  | user_profiles           | /user_id         | None       | Learned user profiles              | user_id, profile_version                      |
| 12  | profile_learning_events | /user_id         | 30d        | User behavior events               | user_id, timestamp                            |
| 13  | consent_events          | /user_id         | 1y         | Consent audit trail                | user_id, timestamp, consent_type              |
| 14  | feedback                | /user_id         | 1y         | User feedback                      | user_id, message_id, rating                   |
| 15  | conversation_documents  | /conversation_id | None       | Uploaded doc metadata              | conversation_id, document_id                  |
| 16  | document_chunks         | /conversation_id | None       | Document chunk vectors             | conversation_id, chunk_id                     |
| 17  | audit_logs              | /user_id         | 2y         | DEPRECATED - historical only       | user_id, timestamp, action                    |
| 18  | usage_events            | /partition_key   | 90d        | DEPRECATED - pending migration     | user_id:YYYY-MM partition                     |
| 19  | usage_daily             | /date            | 2y         | Daily aggregations                 | date, service, dimension                      |
| 20  | events                  | /partition_key   | Configured | Unified events (audit + analytics) | user_id:YYYY-MM partition (composite indexes) |
| 21  | question_categories     | /date            | 2y         | Pre-computed categories            | date, category                                |
| 22  | mcp_servers             | /id              | None       | MCP server configs                 | server_id, name, is_active                    |
| 23  | notifications           | /user_id         | 30d        | Real-time notifications            | user_id, type, created_at                     |

---

## Data Models (Detailed)

### 1. users Container

```json
{
  "id": "uuid",
  "email": "user@company.com",
  "full_name": "John Doe",
  "first_name": "John",
  "last_name": "Doe",
  "azure_oid": "azure-object-id",
  "is_active": true,
  "is_admin": false,
  "department": "Finance",
  "job_title": "Finance Analyst",
  "manager_email": "manager@company.com",
  "office_location": "New York",
  "phone": "+1-555-0123",
  "profile_picture_url": "https://...",
  "last_login": "2026-03-04T10:00:00Z",
  "created_at": "2025-01-01T00:00:00Z",
  "updated_at": "2026-03-04T00:00:00Z",
  "created_by": "admin-user-id",
  "updated_by": "admin-user-id"
}
```

---

### 2. roles Container

```json
{
  "id": "uuid",
  "name": "finance_team",
  "display_name": "Finance Team",
  "description": "Access to finance indexes and reports",
  "is_system_role": false,
  "is_active": true,
  "permissions": {
    "index_ids": ["hr-policies", "finance-reports", "public-kb"],
    "system_functions": [
      "chat:query",
      "conversation:read",
      "feedback:write",
      "user:read-self"
    ],
    "data_access": {
      "conversations": "own_only",
      "profiles": "own_only",
      "analytics": "none"
    }
  },
  "created_at": "2025-01-01T00:00:00Z",
  "updated_at": "2026-03-04T00:00:00Z",
  "created_by": "admin-user-id"
}
```

**System Roles** (predefined):

- `default` - All new users
- `role_admin` - Manage roles
- `index_admin` - Manage indexes
- `user_admin` - Manage users
- `analytics_viewer` - View analytics
- `audit_viewer` - View audit logs

---

### 3. user_roles Container

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "role_id": "uuid",
  "assignment_type": "direct" | "group",
  "source_group_id": "azure-group-id",  // if assignment_type == "group"
  "assigned_at": "2025-06-15T00:00:00Z",
  "assigned_by": "admin-user-id",
  "expires_at": null  // optional: time-limited roles
}
```

---

### 4. group_roles Container

```json
{
  "id": "uuid",
  "group_id": "azure-group-id",
  "group_name": "Finance Department",
  "role_id": "uuid",
  "is_active": true,
  "assigned_at": "2025-01-01T00:00:00Z",
  "assigned_by": "admin-user-id",
  "last_synced": "2026-03-04T12:00:00Z"
}
```

---

### 5. indexes Container

```json
{
  "id": "uuid",
  "name": "HR_Policies",
  "display_name": "HR Policies & Benefits",
  "description": "Employee handbook, benefits, policies, PTO guidelines",
  "category": "human_resources",
  "source_type": "sharepoint" | "knowledge_base" | "custom",
  "source_url": "https://tenant.sharepoint.com/sites/HR",
  "is_active": true,
  "is_system_index": false,
  "search_config": {
    "endpoint": "https://search-service.search.windows.net",
    "index_name": "hr-policies",
    "api_key": "encrypted-key",
    "embedding_deployment": "text-embedding-3-large",
    "top_k": 5,
    "min_score": 0.6
  },
  "metadata": {
    "doc_count": 145,
    "chunk_count": 2847,
    "total_size_mb": 487,
    "language": "en"
  },
  "last_sync": "2026-03-04T02:00:00Z",
  "sync_interval_hours": 24,
  "next_sync": "2026-03-05T02:00:00Z",
  "stats": {
    "queries_this_month": 1247,
    "avg_confidence": 0.78,
    "errors_this_week": 2
  },
  "created_at": "2025-01-01T00:00:00Z",
  "updated_at": "2026-03-04T12:00:00Z",
  "created_by": "admin-user-id"
}
```

---

### 6. conversations Container

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "title": "HR Questions - Feb 2026",
  "summary": "Questions about PTO policy, 401k matching, healthcare",
  "index_ids": ["hr-policies"],
  "message_count": 8,
  "tokens_used": 3247,
  "cost_usd": 0.12,
  "metadata": {
    "language": "en",
    "sentiment": "neutral",
    "has_escalation": false,
    "user_satisfaction": 4 // 1-5 rating
  },
  "created_at": "2026-03-01T14:30:00Z",
  "updated_at": "2026-03-04T10:00:00Z",
  "archived_at": null
}
```

---

### 7. messages Container

```json
{
  "id": "uuid",
  "conversation_id": "uuid",
  "user_id": "uuid",
  "role": "user" | "assistant",
  "content": "What is the PTO policy for new hires?",
  "content_length": 45,
  "sources": [
    {
      "title": "Employee Handbook - Time Off",
      "score": 0.87,
      "url": "https://...",
      "chunk_id": "chunk-123"
    }
  ],
  "confidence": 0.82,
  "confidence_breakdown": {
    "source_agreement": 0.9,
    "vector_similarity": 0.85,
    "coverage": 0.75
  },
  "tokens_used": {
    "input": 156,
    "output": 245
  },
  "cost_usd": 0.01,
  "response_time_ms": 2847,
  "intent": "policy_question",
  "intent_score": 0.94,
  "indexes_searched": ["hr-policies"],
  "used_internet_search": false,
  "created_at": "2026-03-04T10:00:00Z",
  "edited_at": null,
  "feedback": {
    "rating": 5,
    "type": "helpful"
  }
}
```

---

### 8. events Container (Unified - TODO-54)

```json
{
  "id": "uuid",
  "partition_key": "user-id:2026-03",
  "user_id": "uuid",
  "email": "user@company.com",
  "timestamp": "2026-03-04T10:00:00Z",
  "event_type": "query" | "response" | "error" | "login" | "role_assigned" | "export" | "sync" | "feedback",
  "action": "chat_query",  // detailed action name
  "result": "success" | "failure" | "partial",
  "session_id": "uuid",
  "conversation_id": "uuid",
  "message_id": "uuid",
  "ip_address": "192.168.1.1",
  "user_agent": "Mozilla/5.0...",
  "details": {
    // Event-specific details
    "query_text": "What is PTO policy?",
    "query_length": 20,
    "intent": "policy_question",
    "indexes_searched": ["hr-policies"],
    "results_count": 5,
    "response_time_ms": 2847,
    "tokens_used": 401,
    "total_cost_usd": 0.01
  },
  "error": null,  // if result == "failure"
  "tags": ["pii-absent", "verified"],
  "country": "US",
  "region": "NY",
  "organization_id": "current-org-id"  // for future multi-tenancy
}
```

**Indexes**:

- Composite: (user_id ASC, timestamp DESC) - Timeline queries
- Composite: (event_type ASC, timestamp DESC) - Event aggregation
- Composite: (action ASC, timestamp DESC) - Audit filtering
- Composite: (conversation_id ASC, timestamp ASC) - Conversation drill-down
- Composite: (session_id ASC, timestamp ASC) - Session replay
- Composite: (email ASC, timestamp DESC) - Admin audit lookup

---

### 9. glossary_terms Container

```json
{
  "id": "uuid",
  "scope": "enterprise",  // partition key
  "term": "PTO",
  "definition": "Paid Time Off - employee vacation/sick time",
  "category": "human_resources",
  "synonyms": ["vacation", "time off", "paid leave"],
  "embedding": [0.123, 0.456, ...],  // 3072-dim vector
  "usage_count": 247,
  "usage_contexts": [
    "HR policy questions",
    "Benefits discussions"
  ],
  "related_terms": ["401k", "benefits", "leave"],
  "confidence": 0.95,
  "created_at": "2025-01-15T00:00:00Z",
  "updated_at": "2026-03-04T00:00:00Z",
  "created_by": "admin-user-id",
  "last_used": "2026-03-04T10:00:00Z"
}
```

---

### 10. user_profiles Container (TODO-05)

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "profile_version": 1,
  "interests": {
    "finance": 0.9,
    "hr": 0.3,
    "engineering": 0.1
  },
  "expertise_level": "intermediate",
  "communication_style": "formal",
  "preferred_response_length": "medium",
  "query_history": {
    "total_queries": 450,
    "favorite_topics": [
      { "topic": "401k", "count": 45 },
      { "topic": "tax", "count": 38 }
    ]
  },
  "learned_preferences": {
    "prefers_examples": true,
    "prefers_citations": true,
    "follow_up_tendency": 0.7
  },
  "learning_score": 0.82,
  "next_model_update": "2026-04-04T00:00:00Z",
  "created_at": "2026-02-01T00:00:00Z",
  "updated_at": "2026-03-04T00:00:00Z"
}
```

---

### 11. mcp_servers Container

```json
{
  "id": "uuid",
  "name": "bloomberg_mcp",
  "display_name": "Bloomberg Terminal Data",
  "description": "Access to Bloomberg financial data, market news, company info",
  "server_type": "external",
  "is_active": true,
  "connection_url": "ws://mcp-bloomberg:8000",
  "tools": [
    {
      "name": "get_company_data",
      "description": "Get company financial metrics",
      "parameters": {
        "ticker": { "type": "string", "description": "Stock ticker" },
        "metrics": { "type": "array", "items": { "type": "string" } }
      }
    }
  ],
  "requires_auth": true,
  "auth_config": {
    "type": "api_key",
    "key_secret": "encrypted-value"
  },
  "retry_policy": {
    "max_retries": 3,
    "backoff_ms": 100
  },
  "rate_limits": {
    "requests_per_minute": 60,
    "calls_per_day": 10000
  },
  "created_at": "2025-06-01T00:00:00Z",
  "updated_at": "2026-03-04T00:00:00Z"
}
```

---

### 12. notifications Container (TODO-58)

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "type": "query_complete" | "sync_done" | "error" | "mention" | "role_change",
  "title": "Your document sync completed",
  "body": "Sync of 'Finance Reports' index finished: 247 new documents indexed",
  "action_url": "/indexes/finance-reports",
  "action_label": "View Index",
  "priority": "normal" | "high" | "low",
  "status": "unread" | "read",
  "created_at": "2026-03-04T10:00:00Z",
  "read_at": null,
  "expires_at": "2026-04-03T10:00:00Z",  // 30 days TTL
  "ttl": 2592000,  // seconds until deletion
  "delivery_channels": {
    "in_app": true,
    "email": true,
    "web_push": false
  },
  "metadata": {
    "source": "sync_worker",
    "index_id": "finance-reports"
  }
}
```

---

## Query Patterns & Performance

### Hot Paths (Optimized with Caching)

1. **User Login**
   - Query: `users` by email + azure_oid
   - Cached: 5 minutes
   - Fallback: Direct read

2. **Get User Permissions**
   - Query: `user_roles` (user_id) + `roles` (role_id)
   - Cached: 1 hour in Redis
   - Invalidated: On role assignment changes

3. **Get Accessible Indexes**
   - Query: User permissions → indexes with is_active=true
   - Cached: 30 minutes
   - Used on: Every chat query

4. **List User Conversations**
   - Query: `conversations` where user_id = X, ORDER BY updated_at DESC
   - Pagination: OFFSET/LIMIT
   - Cached: 5 minutes

### Expensive Queries (Mitigated)

1. **Conversation Timeline**
   - Query: `messages` where conversation_id = X, ORDER BY created_at
   - Strategy: Load last 20, paginate backwards
   - Index: conversation_id + created_at

2. **User Activity Timeline**
   - Query: `events` where partition_key = user_id:YYYY-MM, ORDER BY timestamp DESC
   - Strategy: Partition by month, load 100 at a time
   - Composite index: user_id ASC, timestamp DESC

3. **Analytics Aggregation**
   - Query: `events` grouped by event_type, date
   - Strategy: Pre-compute nightly, store in `usage_daily`
   - Batch: 1000 events at a time

---

## Data Privacy & Security

### PII Handling

- User emails stored plaintext (required for auth)
- Names stored plaintext (required for UX)
- Manager emails stored plaintext (org context)
- Phone/office locations: Optional, can be redacted

### Encryption

- API keys for search/OpenAI: Encrypted at rest in Cosmos DB
- Sensitive fields: Consider Azure Key Vault for production
- Transit: Always TLS 1.2+

### TTL Policies

```
events: Configurable (default 90 days)
notifications: 30 days
usage_events: 90 days (deprecated)
consent_events: 1 year
audit_logs: 2 years (deprecated, read-only)
profile_learning_events: 30 days
```

### Compliance

- GDPR: User deletion cascade (implement soft-delete)
- HIPAA: Data residency, audit logging, access controls
- SOC 2: Audit trail via events container

---

## Scaling Considerations

### RU/s (Request Units per Second) Provisioning

**Estimate by Container**:
| Container | Monthly Reads | Monthly Writes | Est. RU/s | Notes |
|-----------|---|---|---|---|
| users | 10M | 100K | 50 | Cached heavily |
| conversations | 5M | 500K | 150 | Growth with users |
| messages | 20M | 1M | 300 | Highest traffic |
| events | 2M | 2M | 200 | Analytics writes |
| indexes | 1M | 10K | 20 | Rarely changes |
| glossary_terms | 500K | 100 | 10 | Static |

**Total**: ~730 RU/s (low), scales to 2000+ for large orgs

### Database Sharding Strategy (Future)

- Single database sufficient for <1M users
- Multi-database per tenant for >1M users
- Tenant routing in API gateway

---

## Migration Path (Single → Multi-Tenant)

**Current State**: No tenant_id field anywhere

**Changes Required**:

1. Add `tenant_id` field to all containers
2. Update partition keys to include tenant_id (if needed)
3. Add tenant extraction to auth middleware
4. Update all queries to filter by tenant_id
5. Create tenant isolation indexes
6. Implement tenant-aware migrations

**Risk**: Requires careful data migration to avoid data leakage

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
