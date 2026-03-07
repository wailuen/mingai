# 38. Auth0 Unified SSO Architecture

**Status**: Canonical — supersedes doc 13-04 multi-source OrgContextSource abstraction
**Date**: 2026-03-06

---

## Decision

mingai uses Auth0 as a hard dependency for all tenants. All SSO providers (Azure AD, Okta, Google Workspace, SAML, username/password) are federated through Auth0. mingai receives a standard Auth0 OIDC JWT regardless of the upstream provider.

The three-source abstraction from doc 13-04 (`AzureADOrgContextSource`, `OktaOrgContextSource`, `GenericSAMLOrgContextSource`) is eliminated in favour of a single `Auth0OrgContextSource`. This reduces implementation surface, removes conditional SSO provider logic from the application layer, and places identity normalization where it belongs: the identity middleware (Auth0).

---

## 1. Auth0 as Identity Middleware

### Normalization

Auth0 normalizes identity from all upstream providers into a consistent OIDC JWT. mingai integrates with Auth0 only — it has no direct connection to Azure AD, Okta, ADFS, or any other IdP. The upstream provider is an Auth0 configuration detail, invisible to the mingai application layer.

### Auth0 Organizations

Auth0 Organizations map 1:1 to mingai tenants:

- Each mingai tenant has one Auth0 Organization
- Organization ID is stored in the `tenants` table (`auth0_org_id VARCHAR(64)`)
- JWT contains `org_id` claim identifying which organization (tenant) the user belongs to

### Tenant Selection Flow

```
User visits mingai login page
    │
    ▼
Auth0 Universal Login — detects organization (via subdomain or org picker)
    │
    ▼
Auth0 routes to tenant's configured IdP connection
(Azure AD / Okta / Google Workspace / SAML / username+password)
    │
    ▼
IdP authenticates user
    │
    ▼
Auth0 receives assertion, normalizes claims, generates JWT
(optional: Auth0 Action enriches JWT with org context fields)
    │
    ▼
JWT returned to mingai via OIDC callback
    │
    ▼
mingai validates JWT, extracts tenant_id from org_id claim
```

mingai receives: `sub` (user identifier), `org_id` (Auth0 organization = tenant), and any custom claims added by the tenant's Auth0 Action.

---

## 2. Auth0OrgContextSource

Single implementation replacing the 3-source abstraction:

```python
class Auth0OrgContextSource:
    """
    Single SSO source for mingai. Auth0 normalizes all upstream providers.

    JWT-first path: reads org attributes from JWT claims if tenant has configured
    an Auth0 Action to include these fields.

    Management API fallback: calls Auth0 Management API for app_metadata on
    cache miss. Rate-limited to ~10-15 req/sec per tenant by Auth0 — Redis cache
    is mandatory, not optional.
    """

    def __init__(
        self,
        redis: Redis,
        auth0_mgmt: Auth0ManagementClient,
        db: AsyncSession,
    ):
        self.redis = redis
        self.auth0_mgmt = auth0_mgmt
        self.db = db

    async def get_org_context(
        self,
        user_sub: str,
        jwt_claims: dict,
        tenant_id: str,
    ) -> OrgContextData:
        # Fast path: JWT claims (tenant must configure Auth0 Action to include these)
        if "department" in jwt_claims or "job_title" in jwt_claims:
            return OrgContextData(
                job_title=jwt_claims.get("job_title"),
                department=jwt_claims.get("department"),
                country=jwt_claims.get("country"),
                company=jwt_claims.get("company"),
                manager_name=jwt_claims.get("manager_name"),
            )

        # Cache check
        cache_key = f"{tenant_id}:org_context:{user_sub}"
        cached = await self.redis.get(cache_key)
        if cached:
            return OrgContextData.parse_raw(cached)

        # Fallback: Auth0 Management API
        user_data = await self.auth0_mgmt.get_user(user_sub)
        field_mapping = await self._get_tenant_field_mapping(tenant_id)
        org_data = self._map_to_org_context(
            user_data.get("app_metadata", {}),
            field_mapping,
        )

        # Cache for 24h
        await self.redis.setex(cache_key, 86400, org_data.json())
        return org_data

    async def _get_tenant_field_mapping(self, tenant_id: str) -> dict:
        result = await self.db.execute(
            select(Tenant.org_context_field_mapping).where(Tenant.id == tenant_id)
        )
        mapping = result.scalar_one_or_none()
        return mapping or DEFAULT_FIELD_MAPPING

    def _map_to_org_context(self, app_metadata: dict, field_mapping: dict) -> OrgContextData:
        return OrgContextData(
            job_title=app_metadata.get(field_mapping.get("job_title", "job_title")),
            department=app_metadata.get(field_mapping.get("department", "department")),
            country=app_metadata.get(field_mapping.get("country", "country")),
            company=app_metadata.get(field_mapping.get("company", "company")),
            manager_name=app_metadata.get(field_mapping.get("manager_name", "manager_name")),
        )


DEFAULT_FIELD_MAPPING = {
    "job_title": "job_title",
    "department": "department",
    "country": "country",
    "company": "company",
    "manager_name": "manager_name",
}
```

### OrgContextData Model

```python
class OrgContextData(BaseModel):
    job_title: Optional[str] = None
    department: Optional[str] = None
    country: Optional[str] = None
    company: Optional[str] = None
    manager_name: Optional[str] = None
```

All fields optional. Missing fields simply omit those tokens from the Layer 2 org context prompt segment.

---

## 3. Per-Tenant Field Mapping

Different enterprises store org attributes under different field names in their directory (and therefore in Auth0 `app_metadata`). The field mapping configuration allows each tenant to declare which `app_metadata` key maps to which mingai org context field.

### Database Column

```sql
ALTER TABLE tenants
ADD COLUMN org_context_field_mapping JSONB DEFAULT NULL;
```

`NULL` means use `DEFAULT_FIELD_MAPPING`. No migration needed for existing tenants.

### Default Mapping

```json
{
  "job_title": "job_title",
  "department": "department",
  "country": "country",
  "company": "company",
  "manager_name": "manager_name"
}
```

### Custom Mapping Examples

Enterprise with Azure AD `extensionAttribute` naming:

```json
{
  "job_title": "title",
  "department": "ou",
  "country": "l",
  "company": "o",
  "manager_name": "manager"
}
```

Enterprise with Okta profile fields:

```json
{
  "job_title": "title",
  "department": "department",
  "country": "countryCode",
  "company": "organization",
  "manager_name": "manager"
}
```

### Tenant Admin UI

Location: Settings > SSO > Org Context Field Mapping

Displayed as a table:

| mingai Field | Source Attribute (app_metadata key) |
| ------------ | ----------------------------------- |
| Job Title    | `title` (editable)                  |
| Department   | `ou` (editable)                     |
| Country      | `l` (editable)                      |
| Company      | `o` (editable)                      |
| Manager Name | `manager` (editable)                |

Each row has an editable text field. Save triggers a PATCH to `/api/v1/tenant/settings/sso/field-mapping`. Changes take effect at next login (cache TTL controls how quickly active sessions update).

A "Test Mapping" button (available to tenant admins) triggers a dry-run against the admin's own Auth0 user record and displays which org context fields were resolved.

---

## 4. Redis Cache Strategy

### Cache Key

```
{tenant_id}:org_context:{user_sub}
```

### TTL

86,400 seconds (24 hours). Org context data (job title, department) changes infrequently. 24h TTL provides good freshness without excessive Management API calls.

### Why Cache Is Mandatory

Auth0 Management API rate limits: approximately 10-15 requests per second per tenant on standard plans. A tenant with 500 users generating 100 concurrent queries would hit rate limits without caching. The cache is not an optimization — it is required for correct operation at any meaningful scale.

### Cache Invalidation

| Event                                                    | Action                                                                |
| -------------------------------------------------------- | --------------------------------------------------------------------- |
| User logs in                                             | Background task triggers cache warm (refresh cache for this user_sub) |
| User updates profile preferences (PATCH /me/preferences) | Cache invalidated for this user_sub                                   |
| Tenant admin changes field mapping                       | Cache invalidated for ALL user_subs in that tenant                    |
| Auth0 Management API webhook: user.updated               | Cache invalidated for affected user_sub                               |

### Cache Warming at Login

After JWT validation completes and session is created, trigger a background task to refresh the org context cache for the user:

```python
async def on_login(user_sub: str, jwt_claims: dict, tenant_id: str):
    # Session creation (synchronous, in critical path)
    session = await create_session(user_sub, tenant_id)

    # Cache warming (async, background — does not block login response)
    background_tasks.add_task(
        refresh_org_context_cache,
        user_sub=user_sub,
        jwt_claims=jwt_claims,
        tenant_id=tenant_id,
    )

    return session
```

This ensures the first post-login query hits the cache rather than the Management API.

---

## 5. Auth0 Actions for JWT Enrichment

Tenants who want zero-latency org context (no Management API call, no cache dependency) can configure an Auth0 Action to include org context fields directly in the JWT.

### What is an Auth0 Action

An Auth0 Action is a serverless JavaScript function that runs during the login flow. It can read from external sources (directory, HRMS API) and append custom claims to the access token.

### Reference Action Template

mingai provides a reference template in the tenant documentation:

```javascript
// Auth0 Action: Enrich Access Token with Org Context
exports.onExecutePostLogin = async (event, api) => {
  // Example: read from Azure AD via Microsoft Graph
  // (Tenant customizes to their data source)
  const user = event.user;

  api.accessToken.setCustomClaim(
    "job_title",
    user.user_metadata?.title || null,
  );
  api.accessToken.setCustomClaim(
    "department",
    user.user_metadata?.department || null,
  );
  api.accessToken.setCustomClaim(
    "country",
    user.user_metadata?.country || null,
  );
  api.accessToken.setCustomClaim(
    "company",
    user.user_metadata?.company || null,
  );
  api.accessToken.setCustomClaim(
    "manager_name",
    user.user_metadata?.manager || null,
  );
};
```

### mingai JWT-First Detection

`Auth0OrgContextSource.get_org_context()` checks for the presence of `department` or `job_title` in JWT claims. If either is present, the JWT-first path is taken and no Management API call or cache lookup occurs. This is the lowest-latency path (0 external calls).

Tenants without an Auth0 Action use the Management API fallback path with Redis cache.

---

## 6. Auth0 Group Claims for Team Sync

Auth0 can pass group memberships from upstream IdP into the JWT via an Auth0 Action. mingai uses this for automatic team membership management.

### JWT Claim

```json
{
  "sub": "auth0|user123",
  "org_id": "org_abc",
  "groups": ["Finance", "Q4-Project-Team", "All-Staff"]
}
```

The `groups` claim is populated by an Auth0 Action that reads group memberships from the upstream directory (Azure AD `memberOf`, Okta group memberships, etc.).

### mingai Processing at Login

On JWT validation, if `groups` claim is present:

1. Extract group names from `groups` claim
2. Pass to `TeamSyncService.sync_user_teams(user_id, tenant_id, group_names)`
3. `TeamSyncService` creates/updates team memberships (see doc 39 for full specification)

### Tenant Control

Tenants can disable group sync in Settings > SSO > Group Sync (default: enabled if `groups` claim is detected). Disabling group sync means `groups` claim is ignored; teams are managed manually only.

---

## 7. Tenant Onboarding: SSO Configuration Flow

Step-by-step sequence for enabling SSO for a tenant:

**Step 1: Platform Admin Provisions Tenant**

Platform admin creates tenant record via Platform Admin UI. System auto-generates:

- `tenant_id` (UUID)
- Subdomain (e.g., `acme.mingai.com`)

**Step 2: Platform Admin Creates Auth0 Organization**

Platform admin (or provisioning automation) creates an Auth0 Organization:

- Organization name: tenant display name
- Organization ID stored in `tenants.auth0_org_id`
- Auth0 Organization linked to tenant subdomain for organization routing

**Step 3: Tenant Admin Receives Configuration Instructions**

System emails the tenant admin with:

- Auth0 connection setup guide (IdP-specific: Azure AD, Okta, Google Workspace, SAML)
- Link to Auth0 configuration portal
- Reference Auth0 Action templates for JWT enrichment and group sync

**Step 4: Tenant Admin Configures IdP Connection in Auth0**

Tenant admin (or their IT team) creates an IdP connection in Auth0 and links it to the tenant's Auth0 Organization. Auth0 documentation covers provider-specific setup; mingai does not need to replicate this.

**Step 5 (Optional): Configure Auth0 Action for JWT Enrichment**

Tenant admin deploys the reference Auth0 Action (customized for their data source) to include org context fields in JWT claims. This is optional — the Management API fallback works without it.

**Step 6 (Optional): Configure Field Mapping in mingai**

If `app_metadata` uses non-default field names, tenant admin sets the field mapping in Tenant Admin > Settings > SSO > Org Context Field Mapping.

**Step 7: Validate SSO Configuration**

Tenant admin performs a test login. The "Test Mapping" tool in Tenant Admin > Settings > SSO confirms that org context fields are resolving correctly. Chat shows the user's org context in the profile indicator (job title, department visible in session debug mode for admins).

---

## 8. Sprint 4 Impact

Original Sprint 4 scope (from tenant admin plan doc 06) included implementing 3 separate SSO source adapters:

- `AzureADOrgContextSource`: Azure AD Graph API integration
- `OktaOrgContextSource`: Okta Users API integration
- `GenericSAMLOrgContextSource`: SAML assertion parsing

With the Auth0 unification decision, Sprint 4 scope changes:

**Remove (estimated -6h):**

- `AzureADOrgContextSource` implementation (~2h)
- `OktaOrgContextSource` implementation (~2h)
- `GenericSAMLOrgContextSource` implementation (~2h)

**Add (estimated +4h):**

- `Auth0OrgContextSource` implementation (JWT-first + Management API fallback) (~2h)
- Tenant field mapping API endpoints and database column (~1h)
- Field mapping UI in Tenant Admin > Settings > SSO (~1h)

**Net Sprint 4 effort reduction: ~2h**

The Auth0 Management API client is shared infrastructure (used for Auth0 Organizations management in platform admin provisioning), so no new client setup is needed.

---

## 9. Removed Abstractions

The following abstractions from doc 13-04 are eliminated:

| Removed                            | Replaced By                                |
| ---------------------------------- | ------------------------------------------ |
| `OrgContextSourceFactory`          | `Auth0OrgContextSource` (direct injection) |
| `AzureADOrgContextSource`          | (eliminated)                               |
| `OktaOrgContextSource`             | (eliminated)                               |
| `GenericSAMLOrgContextSource`      | (eliminated)                               |
| `OrgContextSource` (abstract base) | (eliminated)                               |

The `OrgContextData` model and `SystemPromptBuilder` Layer 2 integration are unchanged. The interface into the prompt builder is identical; only the source implementation changes.
