# Current Tenant Model & Multi-Tenancy Roadmap

## Current State: Single-Tenant MVP

**Reality**: The system is designed for a single organization.

**Evidence**:

- No `tenant_id` field in any data model
- Azure AD tenant is configured globally in `.env`
- SharePoint tenant is configured globally in `.env`
- Azure OpenAI account is shared (no tenant isolation)
- Search indexes are not partitioned by tenant
- Cosmos DB partition keys don't include tenant_id

---

## Tenant Isolation Today (How It Works)

### 1. Azure AD Tenant Level

```
- All users must be from the SAME Azure Entra ID tenant
- AZURE_AD_TENANT_ID = "our-company-tenant-id"
- Users from other organizations cannot log in
- This is the primary isolation mechanism
```

### 2. Role-Based Access Control (RBAC)

```
- Users can only access indexes their roles permit
- All users see the same set of indexes
- RBAC filters which documents user can query
- But: No fundamental database isolation
```

### 3. Data Partitioning (Cosmos DB)

```
Current partition keys:
- users: /id (partitioned by user ID, not tenant)
- conversations: /user_id (partitioned by user ID, not tenant)
- messages: /conversation_id (partitioned by conversation, not tenant)
- events: /partition_key (user_id:YYYY-MM format)

Result: All tenants' data in same container
If you know user_id, you can query their data
```

### 4. Search Indexes (Azure Search)

```
Current: One index per knowledge base
- hr-policies
- finance-reports
- engineering-docs

Index structure: No tenant field
Anyone with access to hr-policies can search all docs in it
No per-tenant document filtering
```

---

## What Would Break with Multi-Tenancy

### 1. User Isolation

```
Current:
  - /api/v1/auth/current → Returns user from JWT token
  - Any tenant can have a "user@company.com" user
  - Database doesn't enforce tenant isolation

Multi-tenant fix:
  - Extract tenant_id from JWT
  - Verify user.tenant_id == JWT.tenant_id
  - Query: SELECT * FROM users WHERE id = @id AND tenant_id = @tenant_id
```

### 2. Conversation Isolation

```
Current:
  GET /api/v1/conversations/{conv_id}
  → Query: SELECT * FROM conversations WHERE id = @conv_id
  → No tenant check

Multi-tenant fix:
  GET /api/v1/conversations/{conv_id}
  → Query: SELECT * FROM conversations
           WHERE id = @conv_id AND tenant_id = @tenant_id
```

### 3. Search Index Access

```
Current:
  - indexes container: [
      {id: "hr-policies", endpoint: "https://...", api_key: "..."},
      {id: "finance-reports", ...}
    ]
  - All users query same indexes

Multi-tenant fix:
  - Add tenant_id to indexes
  - Query: SELECT * FROM indexes
           WHERE tenant_id = @tenant_id AND is_active = true
  - Each tenant has their own index instances in Azure Search
```

### 4. Cosmos DB Partition Keys

```
Current:
  conversations: /user_id
  messages: /conversation_id
  events: /partition_key (user_id:YYYY-MM)

Issue: Cross-partition queries required to enforce tenant isolation
  SELECT * FROM conversations
  WHERE user_id IN (@user_ids) AND tenant_id = @tenant_id
  (Cross-partition query = slow)

Multi-tenant fix:
  conversations: /tenant_id  (primary partition)
  Add secondary partition or composite key for query optimization
  → Queries faster but requires schema migration
```

### 5. Azure OpenAI & Search Quotas

```
Current:
  - Single Azure OpenAI account (shared tokens/quota)
  - Single Azure Search account (shared RU/s)
  - No per-tenant limits

Multi-tenant fix:
  Option A: Separate Azure accounts per tenant (expensive)
  Option B: Token/RU quotas per tenant (complex quota tracking)
  Option C: Shared with soft limits (enforced in application)
```

---

## Multi-Tenancy Migration Plan

### Phase 1: Schema Updates (Weeks 1-2)

```python
# Cosmos DB is NoSQL -- SQL DDL (ALTER TABLE, CREATE INDEX) does not apply.
# Adding tenant_id requires modifying documents via the SDK, not SQL DDL.

# Step 1: Add tenant_id field to all documents in each container
async def backfill_tenant_id(container_client, default_tenant_id: str):
    """Add tenant_id to all existing documents in a container."""
    query = "SELECT * FROM c WHERE NOT IS_DEFINED(c.tenant_id)"
    items = container_client.query_items(query=query, enable_cross_partition_query=True)
    async for item in items:
        item["tenant_id"] = default_tenant_id
        await container_client.replace_item(item=item["id"], body=item)

# Containers to backfill: users, conversations, messages, roles, indexes, etc.

# Step 2: Partition key changes (requires container recreation)
# Cosmos DB does NOT support changing partition keys on existing containers.
# Must: create new container -> copy data -> delete old container -> rename.
# users: /id -> /tenant_id (if tenant-scoped isolation)
#         or keep /id and add composite index on (tenant_id, id)

# Step 3: Add composite indexing policy for tenant queries
indexing_policy = {
    "compositeIndexes": [
        [
            {"path": "/tenant_id", "order": "ascending"},
            {"path": "/id", "order": "ascending"},
        ],
        [
            {"path": "/tenant_id", "order": "ascending"},
            {"path": "/user_id", "order": "ascending"},
        ],
    ]
}
```

### Phase 2: API Gateway & Auth (Weeks 3-4)

```python
# Extract tenant from JWT or context
def get_current_tenant() -> str:
    # Option A: Include tenant_id in JWT
    token = get_jwt_token()
    return token.get("tenant_id")

    # Option B: Extract from subdomain
    # subdomain.mingai.ai → tenant_id = subdomain
    # return request.headers.get("X-Tenant-ID")

    # Option C: Extract from API key
    # api_key = request.headers.get("Authorization")
    # return api_key.split(":")[0]  # tenant_id:api_key

# Middleware: Enforce tenant isolation
@app.middleware("http")
async def tenant_middleware(request: Request, call_next):
    tenant_id = extract_tenant(request)
    request.state.tenant_id = tenant_id
    return await call_next(request)

# All endpoints must use tenant context
@app.get("/api/v1/conversations")
async def list_conversations(request: Request):
    tenant_id = request.state.tenant_id
    conversations = cosmos_db.conversations.query_items(
        query="SELECT * FROM c WHERE c.tenant_id = @tenant_id",
        parameters=[{"name": "@tenant_id", "value": tenant_id}]
    )
    return conversations
```

### Phase 3: Data Segregation (Weeks 5-6)

```
Strategy 1: Single Database (Recommended for <100 tenants)
  - Add tenant_id to all containers
  - Composite indexes on (tenant_id, other_fields)
  - Cosmos DB enforces logical isolation
  - Cross-tenant queries blocked at application layer
  - Cost: Minimal; Complexity: Low
  - Risk: Accidental cross-tenant data leakage (app bug)

Strategy 2: Database per Tenant (Recommended for >100 tenants)
  - Create separate Cosmos DB database per tenant
  - Connect to tenant's database based on extracted tenant_id
  - True physical isolation
  - Cost: Higher (multiple databases); Complexity: Medium
  - Risk: Database provisioning bottleneck

Strategy 3: Hybrid (Recommended for scale)
  - Shared database for first 50 tenants
  - Separate databases for enterprise tenants (>1M users)
  - Tenant routing in API gateway
```

### Phase 4: Search Indexes (Week 7)

```
Current: Global indexes (hr-policies, finance-reports)
Multi-tenant: Tenant-prefixed indexes
  - tenant-123-hr-policies
  - tenant-123-finance-reports
  - tenant-456-hr-policies

Or: Use search index sub-resources (if supported)
  - Index metadata includes tenant_id filter

Or: Row-level filtering in search queries
  - Add tenant_id field to all documents
  - Filter: tenant_id = "tenant-123" in search query
```

### Phase 5: Deployment Topology (Week 8)

```
Option A: Single deployment for all tenants
  - All tenants query same API Gateway
  - Tenant extracted from JWT or subdomain
  - Cost-efficient; Multi-tenant awareness required

Option B: Dedicated deployment per tenant
  - tenant-123.mingai.ai → dedicated API instance
  - Separate infrastructure per tenant
  - Cost: Higher; Isolation: Complete

Option C: Hybrid (Recommended)
  - Small tenants: Shared infrastructure
  - Enterprise tenants: Dedicated deployment
  - Fallback: Automatic scale-out
```

---

## Onboarding Flow (Multi-Tenant)

```
1. Tenant Signup
   POST /api/v1/admin/tenants
   {
     "name": "Acme Corp",
     "azure_tenant_id": "acme-azure-id",
     "admin_email": "admin@acmecorp.com"
   }
   → Create tenant record in admins database
   → Generate tenant_id (UUID)
   → Create tenant's database (if Strategy 2)
   → Return tenant_id + connection string

2. Admin Setup
   - Create initial admin user
   - Configure indexes (HR, Finance, etc.)
   - Set up Azure AD group mappings
   - Configure Azure Search indexes

3. User Onboarding
   - Sync users from tenant's Azure AD
   - Create user records with tenant_id
   - Assign default role
   - Send welcome email

4. Data Sync
   - Configure SharePoint tenants (per tenant)
   - Start document sync to tenant's search indexes
```

---

## Cost Impact

### Single Database Strategy

```
Fixed costs:
  - Cosmos DB: ~$100-200/month (baseline)
  - Azure Search: ~$200-300/month
  - Azure OpenAI: Pay per token (shared across tenants)

Variable costs per tenant:
  - Additional RU/s: ~$5-10/tenant/month
  - Additional storage: Negligible

Example: 100 tenants
  - Fixed: $300-500
  - Variable: $500-1000
  - Total: $800-1500/month
```

### Separate Database Strategy

```
Per-tenant costs:
  - Cosmos DB: $100-200/month per database
  - Azure Search: $150-250/month per instance
  - Isolation: Complete

Example: 100 tenants
  - Cosmos DB: $10,000-20,000/month
  - Search: $15,000-25,000/month
  - Total: $25,000-45,000/month

Breakeven: Only viable for enterprise tenants (>$1000/month MRR)
```

---

## Risk Assessment

### Data Leakage Risk (Single Database)

```
Risk: Bug in multi-tenant filtering → cross-tenant data access
Examples:
  - SELECT * FROM conversations (missing WHERE tenant_id)
  - Role permission check doesn't verify tenant_id
  - Search index query lacks tenant filter

Mitigation:
  1. Row-level security (RLS) at database level
  2. Unit tests: Every query must include tenant_id
  3. Code review: Check all database access
  4. Integration tests: Verify isolation
  5. Monitoring: Alert on cross-tenant queries
```

### Compliance Risk

```
GDPR: User deletion must cascade to all tenant data
HIPAA: Tenant data must be isolated & encrypted
SOC 2: Audit logs must include tenant_id

Mitigation:
  - Add compliance checks in data migration
  - Encryption per-tenant (different keys per tenant)
  - Audit logging includes tenant context
```

### Performance Risk

```
With 1000 tenants sharing database:
  - Cross-partition queries slower
  - Indexing complexity increases
  - Cost optimization becomes critical

Mitigation:
  - Comprehensive composite indexes
  - Query optimization (monitor slow queries)
  - Rate limiting per tenant
  - Gradual rollout (start with 10 tenants)
```

---

## Recommended Path Forward

### Short Term (MVP → 10 tenants)

```
1. Remain single-tenant
2. Document multi-tenancy requirements
3. Plan Phase 1 schema changes
4. Build onboarding flow (manual)
```

### Medium Term (10-50 tenants)

```
1. Implement Phase 1-3 (Schema + API)
2. Migrate to single database with tenant_id
3. Automate tenant onboarding
4. Build admin dashboard (tenant management)
```

### Long Term (50+ tenants)

```
1. Implement Strategy 2/3 (separate databases for enterprise)
2. Build tenant provisioning service
3. Implement compliance & audit
4. Scale operations (DevOps for multi-tenant)
```

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
