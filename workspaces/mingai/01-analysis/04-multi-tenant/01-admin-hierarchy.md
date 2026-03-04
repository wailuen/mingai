# Platform Admin vs Tenant Admin Architecture

**Date**: March 4, 2026
**Status**: Architecture Design
**Scope**: Admin hierarchy for multi-tenant mingai

---

## Overview

The multi-tenant platform requires two distinct admin tiers:

1. **Platform Admin (Super Admin)** -- operates the entire SaaS platform
2. **Tenant Admin (Org Admin)** -- manages a single tenant/organization

These tiers form a strict hierarchy where Platform Admins have cross-tenant visibility and Tenant Admins are scoped to their own organization.

---

## RBAC Model

### Role Hierarchy

```
Platform Admin (Super Admin)
  |
  +-- Platform Operator (read-only platform view)
  |
  +-- Tenant Admin (per-tenant)
       |
       +-- Tenant Manager (user/role management)
       |
       +-- Tenant Analyst (analytics, read-only)
       |
       +-- Regular User (default)
```

### Role Definitions

```python
# Platform-level roles (stored in platform database, not tenant-scoped)
PLATFORM_ROLES = {
    "platform_admin": {
        "display_name": "Platform Administrator",
        "scope": "platform",
        "permissions": [
            "platform:manage",           # Full platform control
            "tenant:create",             # Provision new tenants
            "tenant:suspend",            # Suspend/unsuspend tenants
            "tenant:delete",             # Delete tenants
            "tenant:read_all",           # View all tenant data
            "provider:manage",           # Manage LLM providers globally
            "provider:credentials",      # Set/rotate provider API keys
            "mcp:manage_global",         # Register global MCP servers
            "billing:manage",            # Platform billing and quotas
            "compliance:audit",          # Cross-tenant audit access
            "system:health",             # System monitoring
            "system:config",             # Platform configuration
        ],
    },
    "platform_operator": {
        "display_name": "Platform Operator",
        "scope": "platform",
        "permissions": [
            "tenant:read_all",
            "system:health",
            "compliance:audit",
            "billing:read",
        ],
    },
}

# Tenant-level roles (stored per-tenant)
TENANT_ROLES = {
    "tenant_admin": {
        "display_name": "Organization Administrator",
        "scope": "tenant",
        "permissions": [
            "tenant:settings",           # Configure tenant settings
            "user:manage",               # CRUD users within tenant
            "user:invite",               # Invite new users
            "role:manage",               # Create/assign tenant roles
            "sso:configure",             # Set up SSO connection
            "provider:select",           # Select from platform-approved LLMs
            "provider:byollm",           # Configure BYOLLM keys
            "mcp:select",               # Enable/disable MCP servers
            "mcp:configure",             # Configure MCP settings
            "index:manage",              # Create/configure search indexes
            "kb:manage",                 # Manage knowledge bases
            "analytics:view_all",        # View all tenant analytics
            "audit:view",                # View tenant audit logs
            "billing:view",              # View tenant usage/billing
        ],
    },
    "tenant_manager": {
        "display_name": "Organization Manager",
        "scope": "tenant",
        "permissions": [
            "user:manage",
            "user:invite",
            "role:manage",
            "analytics:view_all",
        ],
    },
    "tenant_analyst": {
        "display_name": "Analytics Viewer",
        "scope": "tenant",
        "permissions": [
            "analytics:view_all",
            "audit:view",
            "billing:view",
        ],
    },
    "default": {
        "display_name": "User",
        "scope": "tenant",
        "permissions": [
            "chat:query",
            "conversation:read_own",
            "conversation:write_own",
            "feedback:write",
            "user:read_self",
            "user:update_self",
        ],
    },
}
```

---

## Platform Admin

### Available Actions

| Action             | API Endpoint                                          | Description                  |
| ------------------ | ----------------------------------------------------- | ---------------------------- |
| List tenants       | `GET /api/v1/platform/tenants`                        | List all tenants with status |
| Create tenant      | `POST /api/v1/platform/tenants`                       | Provision new tenant         |
| Get tenant details | `GET /api/v1/platform/tenants/{tenant_id}`            | View tenant config           |
| Update tenant      | `PUT /api/v1/platform/tenants/{tenant_id}`            | Modify tenant settings       |
| Suspend tenant     | `POST /api/v1/platform/tenants/{tenant_id}/suspend`   | Suspend access               |
| Unsuspend tenant   | `POST /api/v1/platform/tenants/{tenant_id}/unsuspend` | Restore access               |
| Delete tenant      | `DELETE /api/v1/platform/tenants/{tenant_id}`         | Permanent deletion           |
| List providers     | `GET /api/v1/platform/providers`                      | LLM providers list           |
| Configure provider | `PUT /api/v1/platform/providers/{id}`                 | Set credentials/endpoints    |
| Enable provider    | `POST /api/v1/platform/providers/{id}/enable`         | Make available to tenants    |
| Global MCP servers | `GET/POST /api/v1/platform/mcp-servers`               | Register global MCP          |
| Platform health    | `GET /api/v1/platform/health`                         | System-wide health           |
| Platform metrics   | `GET /api/v1/platform/metrics`                        | Cross-tenant metrics         |
| Billing overview   | `GET /api/v1/platform/billing`                        | Platform-wide billing        |
| Tenant billing     | `GET /api/v1/platform/billing/{tenant_id}`            | Per-tenant cost              |
| Set quotas         | `PUT /api/v1/platform/tenants/{tenant_id}/quotas`     | Set tenant limits            |
| Compliance audit   | `GET /api/v1/platform/audit`                          | Cross-tenant audit logs      |

### Data Visibility

Platform Admins can see:

- All tenants and their configurations
- Aggregated usage metrics across all tenants
- Cross-tenant billing and cost breakdown
- Global LLM provider usage and quotas
- Platform-wide health and error rates
- All MCP server registrations
- Compliance audit trail

Platform Admins **cannot** see:

- Individual conversation contents (privacy boundary)
- Individual user passwords or SSO tokens
- Tenant-specific encrypted BYOLLM API keys (can rotate, not read)

### API Design

```python
# Platform Admin API Router
# All endpoints require platform_admin or platform_operator role

@router.post("/api/v1/platform/tenants")
async def create_tenant(
    request: TenantCreateRequest,
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """
    Provision a new tenant.

    Steps:
    1. Validate tenant name uniqueness
    2. Create tenant record in platform database
    3. Create tenant database/containers (if dedicated DB strategy)
    4. Create default roles for tenant
    5. Create initial tenant admin user
    6. Send welcome email to tenant admin
    7. Log provisioning event
    """
    tenant = await TenantService.provision(
        name=request.name,
        admin_email=request.admin_email,
        plan=request.plan,  # "starter", "professional", "enterprise"
        sso_config=request.sso_config,
        provisioned_by=admin.user_id,
    )
    return tenant


@router.put("/api/v1/platform/providers/{provider_id}")
async def configure_provider(
    provider_id: str,
    request: ProviderConfigRequest,
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """
    Configure a global LLM provider.

    Stores credentials in vault, not in database.
    """
    await ProviderService.configure(
        provider_id=provider_id,
        endpoint=request.endpoint,
        api_key=request.api_key,  # stored in vault
        models=request.models,
        rate_limits=request.rate_limits,
        configured_by=admin.user_id,
    )
```

### UI Screens

1. **Platform Dashboard**: Tenant count, total users, aggregate costs, system health
2. **Tenant Management**: Table of tenants with status, plan, user count, last active
3. **Tenant Detail**: Individual tenant config, usage, quotas, billing
4. **Provider Management**: LLM provider list, credentials status, model catalog
5. **Global MCP Servers**: Registered servers, health, tenant access matrix
6. **Billing Overview**: Cost breakdown by tenant, provider, time period
7. **System Health**: Service health, latency metrics, error rates
8. **Compliance Audit**: Cross-tenant audit log viewer with filters

---

## Tenant Admin

### Available Actions

| Action              | API Endpoint                                    | Description             |
| ------------------- | ----------------------------------------------- | ----------------------- |
| Get tenant settings | `GET /api/v1/admin/settings`                    | View org configuration  |
| Update settings     | `PUT /api/v1/admin/settings`                    | Modify org settings     |
| List users          | `GET /api/v1/admin/users`                       | All users in tenant     |
| Invite user         | `POST /api/v1/admin/users/invite`               | Send invitation         |
| Update user         | `PUT /api/v1/admin/users/{user_id}`             | Modify user             |
| Deactivate user     | `POST /api/v1/admin/users/{user_id}/deactivate` | Disable access          |
| List roles          | `GET /api/v1/admin/roles`                       | Tenant's roles          |
| Create role         | `POST /api/v1/admin/roles`                      | New custom role         |
| Assign role         | `POST /api/v1/admin/users/{user_id}/roles`      | Assign role             |
| Configure SSO       | `PUT /api/v1/admin/sso`                         | Set up SSO connection   |
| List providers      | `GET /api/v1/admin/providers`                   | Available LLM providers |
| Select provider     | `POST /api/v1/admin/providers/{id}/enable`      | Enable for org          |
| BYOLLM config       | `PUT /api/v1/admin/providers/byollm`            | Own API keys            |
| List MCP servers    | `GET /api/v1/admin/mcp-servers`                 | Available MCP servers   |
| Enable MCP          | `POST /api/v1/admin/mcp-servers/{id}/enable`    | Enable for org          |
| Manage indexes      | `GET/POST/PUT/DELETE /api/v1/admin/indexes`     | Search index CRUD       |
| View analytics      | `GET /api/v1/admin/analytics/*`                 | Usage analytics         |
| View billing        | `GET /api/v1/admin/billing`                     | Cost and usage          |
| View audit          | `GET /api/v1/admin/audit`                       | Tenant audit logs       |

### Data Visibility

Tenant Admins can see:

- All users within their organization
- All roles and permissions within their tenant
- All conversations metadata (not contents unless compliance mode)
- All search indexes for their tenant
- All analytics for their tenant
- Their tenant's LLM usage and costs
- Their tenant's audit logs
- Available (platform-approved) LLM providers and MCP servers

Tenant Admins **cannot** see:

- Other tenants' data (any data)
- Platform-level configuration
- Global provider credentials
- Other tenants' usage or billing
- Platform health metrics

### API Design

```python
# Tenant Admin API Router
# All endpoints automatically scoped by tenant_id from JWT

@router.post("/api/v1/admin/users/invite")
async def invite_user(
    request: InviteUserRequest,
    admin: TenantAdmin = Depends(require_tenant_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Invite a user to the organization.

    Steps:
    1. Validate email not already in tenant
    2. Check user quota (plan limit)
    3. Create invitation record
    4. Send invitation email
    5. Log event
    """
    invitation = await UserService.invite(
        tenant_id=tenant_id,
        email=request.email,
        roles=request.roles or ["default"],
        invited_by=admin.user_id,
    )
    return invitation


@router.put("/api/v1/admin/providers/byollm")
async def configure_byollm(
    request: BYOLLMRequest,
    admin: TenantAdmin = Depends(require_tenant_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Configure Bring Your Own LLM keys.

    Keys are encrypted and stored in vault, scoped to tenant.
    """
    await ProviderService.configure_byollm(
        tenant_id=tenant_id,
        provider=request.provider,  # "openai", "anthropic", etc.
        api_key=request.api_key,   # encrypted in vault
        models=request.models,
        configured_by=admin.user_id,
    )
```

### UI Screens

1. **Organization Dashboard**: User count, query volume, costs, top indexes
2. **User Management**: User list with roles, last active, invite button
3. **Role Management**: Custom roles, permission matrix, assignment view
4. **SSO Configuration**: Provider selection, connection test, user mapping
5. **LLM Providers**: Available providers, enabled status, BYOLLM config
6. **MCP Servers**: Available servers, enabled/disabled toggle, configuration
7. **Search Indexes**: Index list, sync status, document counts
8. **Analytics**: Usage charts, cost breakdown, query analysis
9. **Billing**: Current usage, plan limits, upgrade options
10. **Audit Logs**: Activity log with filters (user, action, date)

---

## Permission Resolution Flow

```python
async def resolve_permissions(user_id: str, tenant_id: str) -> EffectivePermissions:
    """
    Resolve effective permissions for a user in a tenant.

    Order of evaluation:
    1. Check if user is platform admin (overrides tenant permissions)
    2. Load tenant-level roles for user
    3. Load SSO group-based roles
    4. Union all permissions
    5. Apply tenant plan limits (e.g., no BYOLLM on starter plan)
    """
    # 1. Platform admin check
    platform_role = await get_platform_role(user_id)
    if platform_role in ("platform_admin", "platform_operator"):
        return PlatformPermissions(role=platform_role)

    # 2. Direct role assignments
    direct_roles = await get_user_roles(user_id, tenant_id)

    # 3. SSO group-based roles
    group_roles = await get_group_roles(user_id, tenant_id)

    # 4. Union all permissions
    all_roles = direct_roles + group_roles
    permissions = EffectivePermissions()
    for role in all_roles:
        role_def = await get_role_definition(role.role_id, tenant_id)
        permissions.merge(role_def.permissions)

    # 5. Apply plan limits
    tenant = await get_tenant(tenant_id)
    permissions.apply_plan_limits(tenant.plan)

    return permissions
```

---

## Tenant Data Model

```python
# Platform database: tenants container
{
    "id": "tenant-uuid",
    "name": "Acme Corporation",
    "slug": "acme-corp",                  # URL-safe identifier
    "plan": "professional",               # "starter", "professional", "enterprise"
    "status": "active",                   # "active", "suspended", "pending", "deleted"
    "created_at": "2026-03-04T00:00:00Z",
    "created_by": "platform-admin-uuid",
    "settings": {
        "display_name": "Acme Corp AI Hub",
        "logo_url": "https://...",
        "primary_color": "#1a73e8",
        "custom_domain": "ai.acmecorp.com",
    },
    "sso_config": {
        "provider": "auth0",
        "connection_id": "con_abc123",
        "connection_type": "azure_ad",    # or "google", "okta", "saml"
        "domain": "acmecorp.com",
    },
    "quotas": {
        "max_users": 500,
        "max_indexes": 50,
        "max_queries_per_day": 10000,
        "max_storage_gb": 100,
        "llm_monthly_budget_usd": 5000,
        "byollm_allowed": True,
    },
    "features": {
        "mcp_enabled": True,
        "sharepoint_sync": True,
        "custom_mcp_servers": False,       # Enterprise only
        "dedicated_database": False,       # Enterprise only
        "sla_tier": "standard",
    },
    "admin_user_id": "admin-user-uuid",
    "billing": {
        "stripe_customer_id": "cus_abc123",
        "current_period_start": "2026-03-01",
        "current_period_end": "2026-03-31",
    },
}
```

---

## Plan Tiers and Feature Matrix

| Feature       | Starter       | Professional | Enterprise     |
| ------------- | ------------- | ------------ | -------------- |
| Max users     | 25            | 500          | Unlimited      |
| Max indexes   | 5             | 50           | Unlimited      |
| Queries/day   | 1,000         | 10,000       | Unlimited      |
| Storage       | 10 GB         | 100 GB       | Unlimited      |
| LLM budget/mo | $500          | $5,000       | Custom         |
| SSO           | Password only | Any SSO      | Any SSO + SAML |
| BYOLLM        | No            | Yes          | Yes            |
| MCP servers   | 3             | All standard | All + custom   |
| Dedicated DB  | No            | No           | Yes            |
| Custom domain | No            | Yes          | Yes            |
| SLA           | Best effort   | 99.9%        | 99.99%         |
| Support       | Email         | Priority     | Dedicated      |

---

## Tenant Context in JWT

```json
{
  "sub": "user-uuid",
  "email": "user@acmecorp.com",
  "tenant_id": "tenant-uuid",
  "tenant_slug": "acme-corp",
  "roles": ["tenant_admin", "default"],
  "scope": "tenant",
  "plan": "professional",
  "exp": 1709587200,
  "iat": 1709558400,
  "iss": "aihub-platform",
  "aud": "aihub-api"
}
```

For platform admins operating on a specific tenant:

```json
{
  "sub": "platform-admin-uuid",
  "email": "admin@aihub-platform.com",
  "tenant_id": null,
  "scope": "platform",
  "platform_role": "platform_admin",
  "acting_tenant_id": "tenant-uuid",
  "exp": 1709587200,
  "iat": 1709558400,
  "iss": "aihub-platform",
  "aud": "aihub-api"
}
```

---

## Middleware: Tenant Isolation Enforcement

```python
async def tenant_context_middleware(request: Request, call_next):
    """
    Extract and enforce tenant context on every request.

    1. Extract tenant_id from JWT token
    2. Validate tenant exists and is active
    3. Inject tenant_id into request state
    4. All downstream queries MUST use request.state.tenant_id
    """
    token = extract_jwt(request)

    if token.scope == "platform":
        # Platform admin - may operate on any tenant
        if token.acting_tenant_id:
            request.state.tenant_id = token.acting_tenant_id
        else:
            request.state.tenant_id = None  # Platform-wide view
        request.state.is_platform = True
    else:
        # Tenant user - always scoped to their tenant
        tenant = await get_tenant(token.tenant_id)
        if not tenant or tenant.status != "active":
            raise HTTPException(403, "Tenant not active")
        request.state.tenant_id = token.tenant_id
        request.state.is_platform = False

    response = await call_next(request)
    return response
```

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
