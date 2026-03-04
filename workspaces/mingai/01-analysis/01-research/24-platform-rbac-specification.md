# 24. Platform-Level RBAC Specification

> **Status**: Architecture Design
> **Date**: 2026-03-05
> **Purpose**: Complete specification of platform-level roles, permissions, JWT claims, enforcement middleware, and the interaction between platform and tenant RBAC layers.
> **Builds on**: `04-multi-tenant/01-admin-hierarchy.md` (admin hierarchy overview)

---

## 1. Why Platform-Level RBAC Is Different

Tenant RBAC (roles like `tenant_admin`, `default`) controls what a user can do **within their own organization**. Platform-level RBAC controls what members of the **platform operator team** can do **across all tenants**.

These are distinct security domains:

| Dimension                  | Tenant RBAC                              | Platform RBAC                                             |
| -------------------------- | ---------------------------------------- | --------------------------------------------------------- |
| **Who holds these roles**  | Customer employees                       | Platform engineering/operations team                      |
| **Scope of access**        | One tenant's data                        | All tenants + platform infrastructure                     |
| **Where roles are stored** | Per-tenant `user_roles` table (with RLS) | Separate `platform_members` table (no tenant_id)          |
| **JWT `scope` claim**      | `"tenant"`                               | `"platform"`                                              |
| **How authenticated**      | Customer SSO / local auth                | Platform team SSO (separate Auth0 tenant or internal IdP) |

---

## 2. Platform Role Definitions

### Role: `platform_admin`

Full control of the platform. Typically 1-2 people (founder / CTO). Requires hardware MFA.

| Permission             | Description                                                |
| ---------------------- | ---------------------------------------------------------- |
| `platform:manage`      | Full platform control including config changes             |
| `tenant:create`        | Provision new tenants                                      |
| `tenant:update`        | Modify tenant plan, quotas, settings                       |
| `tenant:suspend`       | Suspend access to a tenant                                 |
| `tenant:delete`        | Permanently delete a tenant (with confirmation)            |
| `tenant:read_all`      | View any tenant's configuration, usage, billing            |
| `tenant:impersonate`   | Act as tenant_admin within a specific tenant               |
| `provider:manage`      | Configure global LLM providers and API keys                |
| `provider:rotate_keys` | Rotate LLM provider API keys                               |
| `agent:manage_global`  | Register, update, and remove global A2A agents             |
| `billing:manage`       | Set plans, quotas, invoice, manage Stripe subscriptions    |
| `billing:read`         | View all billing and usage data                            |
| `compliance:audit`     | Access cross-tenant audit logs (read-only)                 |
| `system:config`        | Modify platform configuration (feature flags, limits)      |
| `system:health`        | View platform-wide metrics, error rates, health dashboards |
| `platform_team:manage` | Create/modify platform team member accounts                |

### Role: `platform_operator`

Day-to-day operations. SRE / customer success team. Cannot modify tenant data or make billing decisions.

| Permission          | Description                                    |
| ------------------- | ---------------------------------------------- |
| `tenant:read_all`   | View any tenant's config and usage (read-only) |
| `system:health`     | View platform health and metrics               |
| `compliance:audit`  | View cross-tenant audit logs                   |
| `billing:read`      | View usage and billing (cannot modify)         |
| `agent:read_global` | View registered A2A agents and health          |

### Role: `platform_support`

Customer success / technical support. Can assist specific tenants.

| Permission                  | Description                                                   |
| --------------------------- | ------------------------------------------------------------- |
| `tenant:read_assigned`      | View tenant config for tenants assigned to this support agent |
| `system:health`             | View platform health                                          |
| `compliance:audit_assigned` | View audit logs for assigned tenants only                     |

### Role: `platform_security`

Security team. Audit-focused, read-only.

| Permission         | Description                          |
| ------------------ | ------------------------------------ |
| `compliance:audit` | Full cross-tenant audit log access   |
| `tenant:read_all`  | View all tenant configurations       |
| `system:health`    | View metrics                         |
| `billing:read`     | View billing (for anomaly detection) |

---

## 3. Platform JWT Structure

### Platform Admin JWT (operating without tenant context)

```json
{
  "sub": "platform-user-uuid",
  "email": "ops@mingai-platform.com",
  "scope": "platform",
  "platform_role": "platform_admin",
  "tenant_id": null,
  "acting_tenant_id": null,
  "exp": 1709587200,
  "iat": 1709558400,
  "iss": "mingai-platform-auth",
  "aud": "mingai-api"
}
```

### Platform Admin JWT (impersonating a tenant)

When a platform admin clicks "Manage as Tenant Admin" on the platform dashboard, they get an impersonation token:

```json
{
  "sub": "platform-user-uuid",
  "email": "ops@mingai-platform.com",
  "scope": "platform",
  "platform_role": "platform_admin",
  "tenant_id": null,
  "acting_tenant_id": "tenant-uuid-to-impersonate",
  "acting_as": "tenant_admin",
  "impersonation_reason": "Customer support ticket #12345",
  "impersonation_expires_at": 1709565600, // 2-hour window
  "exp": 1709587200,
  "iat": 1709558400,
  "iss": "mingai-platform-auth",
  "aud": "mingai-api"
}
```

**Impersonation audit**: Every API call made under impersonation is logged to the compliance audit trail with both `platform_user_id` and `acting_tenant_id`.

---

## 4. Permission Enforcement Middleware

### Layer 1: JWT Scope Guard

```python
async def require_platform_scope(request: Request) -> PlatformUser:
    """
    Middleware that ensures the request carries a platform-scoped JWT.
    Applied to all /api/v1/platform/* routes.
    """
    token = extract_jwt(request)

    if token.scope != "platform":
        raise HTTPException(403, "Platform scope required")

    platform_user = await PlatformMemberRepository.get(token.sub)
    if not platform_user or not platform_user.is_active:
        raise HTTPException(403, "Platform user not found or inactive")

    return platform_user


async def require_platform_admin(request: Request) -> PlatformUser:
    """Requires platform_admin role specifically."""
    user = await require_platform_scope(request)
    if user.role != "platform_admin":
        raise HTTPException(403, "Platform admin role required")
    return user


async def require_platform_permission(permission: str):
    """Dependency factory: checks specific permission."""
    async def _check(user: PlatformUser = Depends(require_platform_scope)):
        if permission not in PLATFORM_ROLE_PERMISSIONS[user.role]:
            raise HTTPException(403, f"Missing permission: {permission}")
        return user
    return _check
```

### Layer 2: Tenant Access Guard (for cross-tenant operations)

```python
async def validate_tenant_access(
    tenant_id: str,
    platform_user: PlatformUser,
    required_permission: str = "tenant:read_all",
) -> Tenant:
    """
    Validates that the platform user has access to the requested tenant.
    For platform_support role, checks if the tenant is assigned to this support agent.
    """
    if required_permission not in PLATFORM_ROLE_PERMISSIONS[platform_user.role]:
        raise HTTPException(403, f"Missing permission: {required_permission}")

    if platform_user.role == "platform_support":
        # Support agents can only access assigned tenants
        assignment = await SupportAssignmentRepository.get(
            support_id=platform_user.id,
            tenant_id=tenant_id,
        )
        if not assignment:
            raise HTTPException(403, "Tenant not assigned to this support agent")

    tenant = await TenantRepository.get(tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    return tenant
```

### Layer 3: Database Isolation

Platform admin API routes operate on the **platform database** (no `tenant_id` context set). When a platform admin performs an operation on a specific tenant's data, they use a separate database connection with that tenant's context:

```python
async def get_tenant_db_connection(tenant_id: str) -> AsyncConnection:
    """
    Returns a PostgreSQL connection scoped to the tenant.
    Used when platform admin needs to read/write tenant-specific data.
    Always logged to compliance audit trail.

    SECURITY: Never use f-string interpolation in SET commands.
    Validate tenant_id as a UUID before this call to prevent SQL injection.
    Use parameterized execution for all dynamic values.
    """
    # Validate UUID format before any database interaction
    validated_tenant_id = str(uuid.UUID(tenant_id))  # raises ValueError on invalid input

    conn = await platform_db_pool.acquire()
    # Use $1 parameterized form — SET does not support $1 in all drivers,
    # so cast to UUID explicitly to prevent injection.
    await conn.execute(f"SET app.tenant_id = '{validated_tenant_id}'::text")
    await conn.execute("SET app.platform_access = 'true'")
    return conn
```

---

## 5. Platform Member Data Model

Platform team members are stored in a **separate table** from tenant users, in the **platform database**:

```sql
CREATE TABLE platform_members (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN (
                        'platform_admin', 'platform_operator',
                        'platform_support', 'platform_security'
                    )),
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    mfa_enrolled    BOOLEAN NOT NULL DEFAULT FALSE,
    mfa_required    BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    created_by      UUID REFERENCES platform_members(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- MFA enforcement for platform_admin
CREATE OR REPLACE FUNCTION enforce_platform_admin_mfa()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.role = 'platform_admin' AND NOT NEW.mfa_enrolled THEN
        RAISE EXCEPTION 'MFA enrollment required for platform_admin role';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_mfa_before_insert_update
    BEFORE INSERT OR UPDATE ON platform_members
    FOR EACH ROW EXECUTE FUNCTION enforce_platform_admin_mfa();
```

**Key point**: There is no `tenant_id` in `platform_members`. These users are entirely outside the tenant data model.

---

## 6. Platform Admin UI Screens

### Screen 1: Platform Dashboard (Home)

```
[mingai Platform Admin]         Logged in as: ops@mingai-platform.com [platform_admin]

┌─────────────────────────────────────────────────────────────────┐
│  Platform Health                              Last 24 hours      │
│  ● API:      99.98% uptime    ● DB:    99.99% uptime            │
│  ● LLM:      98.2% uptime     ● Cache: 100% uptime              │
├───────────────────┬────────────────────┬────────────────────────┤
│  Total Tenants    │  Active Users       │  Total Queries (24h)  │
│     47            │     2,341           │     89,204            │
├───────────────────┴────────────────────┴────────────────────────┤
│  LLM Cost Today                                                   │
│  Azure OpenAI: $234.50    OpenAI Direct: $89.20    Total: $323.70│
│  ████████████████░░░░░░ 76% of daily budget                      │
└─────────────────────────────────────────────────────────────────┘

Recent Activity:
• 2 minutes ago — Tenant "FinanceCo" provisioned by admin@platform.com
• 15 minutes ago — LLM API key rotated for Azure OpenAI (us-east)
• 1 hour ago — Tenant "RetailCorp" suspended (payment failure)
```

### Screen 2: Tenant Management

```
[Tenant Management]                               [+ Provision New Tenant]

Search: [________________]   Filter: [All Plans ▼]  [All Status ▼]

| Tenant Name    | Plan         | Status    | Users | Queries/Day | LLM Cost/Mo | Actions    |
|----------------|--------------|-----------|-------|-------------|-------------|------------|
| FinanceCo      | Enterprise   | Active    | 347   | 12,450      | $4,230      | [Manage ▼] |
| RetailCorp     | Professional | Suspended | 89    | 0           | $0          | [Manage ▼] |
| LegalFirm      | Professional | Active    | 124   | 3,200       | $890        | [Manage ▼] |
| StartupABC     | Starter      | Active    | 12    | 145         | $34         | [Manage ▼] |

Manage dropdown: [View Details] [Edit Settings] [Set Quotas] [Manage as Tenant Admin]
                 [Suspend] [Delete] [View Audit Logs] [Download Billing]
```

### Screen 3: LLM Provider Configuration (Platform LLM Library)

```
[Platform LLM Library]                            [+ Add Provider]

Providers:

Azure OpenAI (us-east)                                    [Active ✓]
  Models: GPT-5.2-chat, GPT-5 Mini, GPT-5 Vision, text-embedding-3-large
  Status: ● Healthy   Latency: 823ms (p95)   API Key: ●●●●●●●● [Rotate]
  Available to plans: Starter, Professional, Enterprise
  Monthly cost this month: $8,234.50

OpenAI Direct                                             [Active ✓]
  Models: gpt-4o, gpt-4o-mini, text-embedding-3-large
  Status: ● Healthy   Latency: 1,204ms (p95)   API Key: ●●●●●●●● [Rotate]
  Available to plans: Professional, Enterprise
  Monthly cost this month: $1,892.30

Anthropic Claude                                          [Inactive]
  Models: claude-sonnet-4-6, claude-haiku-4-5
  Status: ○ Not configured   API Key: [Not set] [Configure]
  Available to plans: Enterprise only
  Monthly cost this month: $0
```

---

## 7. Impersonation Flow

Platform admins can act as tenant admins to troubleshoot issues:

```
1. Platform Admin opens Tenant Detail page for "FinanceCo"
2. Clicks [Manage as Tenant Admin]
3. System prompts: "Reason for impersonation (logged for audit): [______________]"
4. Admin enters reason: "Customer support ticket #12345 - index sync issue"
5. System issues impersonation JWT:
     - scope: "platform"
     - acting_tenant_id: "finco-tenant-uuid"
     - impersonation_reason: "CS ticket #12345"
     - impersonation_expires_at: now + 2 hours
6. Admin is redirected to Tenant Admin UI for FinanceCo with a banner:
     ⚠ PLATFORM ACCESS: You are viewing FinanceCo as Tenant Admin
       All actions are logged. Session expires in 1:58:34
       [End Session]
7. All actions are logged with platform_user_id in compliance audit trail
8. After 2 hours, session automatically expires
```

---

## 8. Cross-Tenant Audit Log

The compliance audit log includes both tenant-scoped events and platform-level events:

### Event Types in Platform Audit Trail

| Event Type                             | Triggered By                                |
| -------------------------------------- | ------------------------------------------- |
| `platform.tenant.created`              | Platform admin provisions tenant            |
| `platform.tenant.suspended`            | Platform admin suspends tenant              |
| `platform.tenant.deleted`              | Platform admin deletes tenant               |
| `platform.impersonation.started`       | Platform admin begins impersonation session |
| `platform.impersonation.ended`         | Impersonation session ends                  |
| `platform.provider.configured`         | LLM provider API key set                    |
| `platform.provider.key_rotated`        | LLM provider API key rotated                |
| `platform.quota.updated`               | Tenant quota changed                        |
| `platform.member.created`              | New platform team member added              |
| `platform.member.role_changed`         | Platform team member role modified          |
| `platform.agent.registered`            | New global A2A agent registered             |
| `platform.tenant.impersonation_action` | Any action taken during impersonation       |

---

## 9. Security Constraints

1. **MFA mandatory for platform_admin**: Cannot issue platform_admin role without MFA enrolled. Database trigger enforces this.

2. **Platform admin direct access cannot read conversation content**: The `compliance:audit` permission gives access to audit log metadata (who queried what, when), never to conversation body content. **However**: When a platform admin uses impersonation (`acting_as: tenant_admin`), the impersonated session inherits tenant admin access including conversation history. All impersonated conversation access is written to the compliance audit trail. Enterprises requiring stricter separation (where even impersonated platform access cannot see conversation bodies) must request `platform_impersonation: true` claim enforcement — this causes conversation body retrieval endpoints to return 403 for impersonated sessions. This is an Enterprise-only configuration delivered as a tenant security setting.

3. **Impersonation is time-limited**: 2-hour sessions only. Cannot be extended without a new reason entry.

4. **Platform member credentials separate from tenant credentials**: Platform team authenticates against a separate IdP (not customer SSO). This ensures platform access cannot be gained by compromising a customer's Azure AD.

5. **No platform admin can delete their own account**: Requires another platform_admin to perform deletion.

6. **Tenant deletion is soft-delete with 30-day grace period**: Data is preserved for 30 days after deletion, allowing recovery. Permanent purge requires a second platform_admin confirmation.

---

**Document Version**: 1.0
**Last Updated**: 2026-03-05
