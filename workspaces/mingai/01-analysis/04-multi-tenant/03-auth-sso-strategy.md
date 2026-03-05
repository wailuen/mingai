# Auth & SSO Strategy for Multi-Tenant

**Date**: March 4, 2026
**Status**: Architecture Design
**Scope**: Authentication architecture for multi-tenant mingai

---

## Overview

The current system uses Azure AD (Entra ID) as the sole SSO provider, with a local auth fallback for non-SSO users. Multi-tenancy requires supporting **multiple SSO providers per tenant** while maintaining a unified authentication flow. This document designs the migration from single-tenant Entra-only to a multi-tenant SSO broker architecture using Auth0 Organizations.

---

## Current Authentication Architecture

### What Exists Today

Evidence from `app/modules/auth/router.py` (lines 1-597) and `app/core/config.py` (lines 57-67):

```python
# config.py:57-67 -- Current Azure AD configuration
azure_ad_tenant_id: str = Field(default="")
azure_ad_client_id: str = Field(default="")
azure_ad_client_secret: str = Field(default="")
azure_ad_redirect_uri: str = Field(default="http://localhost:3000/auth/callback")
azure_ad_scopes: str = Field(default="openid profile email offline_access User.Read")

# Auth modes
auth_mode: str = Field(default="dual")  # dual | azure_ad_only | local_only
local_auth_enabled: bool = Field(default=True)
```

**Current Auth Flow:**

```
User → Frontend → GET /v1/auth/login/azure → Azure AD authorize URL
                                                ↓
                  POST /v1/auth/login/azure/callback ← Azure AD redirect
                                                ↓
                  AuthService.handle_azure_callback()
                    ├─ Exchange code for Azure tokens
                    ├─ Extract user claims (oid, email, name)
                    ├─ Create/update user in CosmosDB
                    ├─ Fetch MS Graph profile (department, jobTitle)
                    ├─ Resolve roles via RoleService
                    ├─ Generate JWT + refresh token
                    └─ Return LoginResponse
```

### Auth Endpoints (auth/router.py:111-597)

| Endpoint                        | Method | Purpose                                   |
| ------------------------------- | ------ | ----------------------------------------- |
| `/v1/auth/mode`                 | GET    | Returns auth mode config (lines 111-123)  |
| `/v1/auth/login/local`          | POST   | Email+password login (lines 126-170)      |
| `/v1/auth/login/azure`          | GET    | Get Azure AD SSO URL (lines 173-193)      |
| `/v1/auth/login/azure/silent`   | GET    | Silent re-auth via iframe (lines 196-232) |
| `/v1/auth/login/azure/callback` | POST   | OAuth callback handler (lines 235-296)    |
| `/v1/auth/refresh`              | POST   | Token refresh (lines 298-369)             |
| `/v1/auth/logout`               | POST   | Logout + token blacklist (lines 372-411)  |
| `/v1/auth/validate`             | POST   | Token validation (lines 414-422)          |
| `/v1/auth/me`                   | GET    | Current user info (lines 425-456)         |
| `/v1/auth/ms-token-status`      | GET    | MS token OBO check (lines 459-515)        |
| `/v1/auth/embed/token`          | POST   | SharePoint embed exchange (lines 522-597) |

### Current Limitations

1. **Single Azure AD tenant**: `azure_ad_tenant_id` is a global setting (config.py:57) -- all users authenticate against one Entra ID tenant
2. **No tenant_id in JWT**: Current JWT contains `sub`, `email`, `roles` but no tenant claim (auth/service.py:52-62)
3. **Hardcoded Azure AD authority**: `config.py:469-471` constructs URL from single tenant ID
4. **No SSO provider abstraction**: Auth service directly calls Azure AD OAuth endpoints
5. **MS Graph dependency**: Profile enrichment (department, jobTitle) assumes MS Graph availability (auth/service.py, msgraph.py)
6. **`@lru_cache` on Settings**: Config immutable at runtime (config.py:489-492)

---

## Target Architecture: Auth0 as Universal SSO Broker

### Why Auth0 Organizations

Auth0 Organizations provide per-tenant SSO without building a custom identity broker:

| Feature                 | Auth0 Organizations   | Custom Implementation   |
| ----------------------- | --------------------- | ----------------------- |
| Multi-IdP per tenant    | Built-in              | Months of development   |
| SAML 2.0 support        | Built-in              | Complex XML parsing     |
| Okta/Google/Entra       | Pre-built connectors  | Custom OAuth for each   |
| Tenant isolation        | Organization-level    | Must build from scratch |
| MFA per-tenant          | Policy-based          | Custom logic            |
| Branding per-tenant     | Organization branding | Template engine needed  |
| Compliance (SOC2/HIPAA) | Certified             | Self-attestation        |

### Architecture Overview

```
┌───────────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                          │
│  User clicks "Sign In" → redirect to Auth0 Universal Login        │
└───────────────┬───────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────────┐
│                    Auth0 (SSO Broker)                              │
│                                                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ Organization │  │ Organization │  │ Organization │              │
│  │  "acme-corp" │  │ "bigcorp"   │  │ "finco"     │              │
│  │             │  │             │  │             │              │
│  │ Connection: │  │ Connection: │  │ Connection: │              │
│  │ Entra ID    │  │ Okta        │  │ Google WS   │              │
│  │ (acme's AD) │  │ (bigcorp's) │  │ (finco's)   │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                      │
│  Auth0 Issues ID Token + Access Token with:                      │
│  { org_id, org_name, tenant_id, email, roles }                   │
└─────────┬────────────────┬────────────────┬──────────────────────┘
          │                │                │
          ▼                ▼                ▼
┌───────────────────────────────────────────────────────────────────┐
│                    API Service (FastAPI)                           │
│                                                                   │
│  POST /v1/auth/login/sso/callback                                │
│  ├─ Validate Auth0 ID token (JWKS)                               │
│  ├─ Extract org_id → map to tenant_id                            │
│  ├─ Create/update user with tenant_id                            │
│  ├─ Resolve tenant-specific roles                                │
│  ├─ Issue platform JWT with tenant_id claim                      │
│  └─ Return LoginResponse                                         │
└───────────────────────────────────────────────────────────────────┘
```

---

## Tenant-Selectable SSO Providers

### Supported Connections

| Connection Type        | Auth0 Connection         | Use Case                            |
| ---------------------- | ------------------------ | ----------------------------------- |
| **Microsoft Entra ID** | `enterprise/azure-ad`    | Enterprise M365 tenants             |
| **Google Workspace**   | `enterprise/google-apps` | Google-first organizations          |
| **Okta**               | `enterprise/okta`        | Existing Okta deployments           |
| **SAML 2.0 Generic**   | `enterprise/samlp`       | Any SAML IdP (Ping, OneLogin, ADFS) |
| **OIDC Generic**       | `enterprise/oidc`        | Any OIDC provider                   |
| **Local Auth**         | `database`               | Non-SSO tenants, test accounts      |

### Per-Tenant SSO Configuration

Stored in the tenant record (see `01-admin-hierarchy.md` tenant data model):

```python
# Platform database: tenants container
{
    "id": "tenant-uuid",
    "name": "Acme Corporation",
    "sso_config": {
        "provider": "auth0",                       # SSO broker
        "org_id": "org_acme123",                   # Auth0 Organization ID
        "connection_id": "con_entra_acme",         # Auth0 Connection ID
        "connection_type": "azure_ad",             # entra | google | okta | saml | oidc
        "domain": "acmecorp.com",                  # Email domain for auto-routing
        "idp_metadata": {                          # IdP-specific config
            "azure_tenant_id": "acme-entra-uuid",  # For Entra connections
            "saml_metadata_url": null,             # For SAML connections
            "discovery_url": null,                 # For OIDC connections
        },
        "allow_local_fallback": False,             # Can users use email+password?
        "mfa_required": True,                      # Enforce MFA at Auth0 level
        "jit_provisioning": True,                  # Auto-create users on first login
    },
}
```

### Tenant Admin SSO Configuration Flow

```
Tenant Admin → Settings → SSO Configuration
    │
    ├─ Step 1: Choose connection type
    │   [ ] Microsoft Entra ID
    │   [ ] Google Workspace
    │   [ ] Okta
    │   [ ] SAML 2.0
    │   [ ] OIDC
    │
    ├─ Step 2: Provide IdP details (varies by type)
    │   Entra ID: Azure Tenant ID, Client ID (from IdP app registration)
    │   Google:   Google Workspace domain
    │   Okta:     Okta domain, Client ID, Client Secret
    │   SAML:     Metadata URL or XML upload
    │   OIDC:     Discovery URL, Client ID, Client Secret
    │
    ├─ Step 3: Domain verification
    │   Verify ownership of email domain (DNS TXT record)
    │
    ├─ Step 4: Test connection
    │   Admin performs test login through new connection
    │
    └─ Step 5: Activate
        Enable SSO for all tenant users
        Optionally disable local auth fallback
```

### API Endpoints for SSO Configuration

```python
# Tenant Admin SSO Management
@router.put("/api/v1/admin/sso")
async def configure_sso(
    request: SSOConfigRequest,
    admin: TenantAdmin = Depends(require_tenant_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Configure SSO connection for tenant.

    Steps:
    1. Validate connection type and IdP details
    2. Create Auth0 Connection for this Organization
    3. Enable connection on Auth0 Organization
    4. Store connection_id in tenant record
    5. Optionally verify domain ownership
    """
    # Create connection in Auth0
    auth0_mgmt = get_auth0_management_client()
    connection = await auth0_mgmt.connections.create({
        "name": f"tenant-{tenant_id}-{request.connection_type}",
        "strategy": AUTH0_STRATEGY_MAP[request.connection_type],
        "options": build_connection_options(request),
        "enabled_clients": [AUTH0_CLIENT_ID],
    })

    # Enable on Organization
    await auth0_mgmt.organizations.add_connection(
        org_id=tenant.sso_config.org_id,
        connection_id=connection["id"],
    )

    # Update tenant record
    await TenantService.update_sso_config(
        tenant_id=tenant_id,
        connection_id=connection["id"],
        connection_type=request.connection_type,
    )

AUTH0_STRATEGY_MAP = {
    "azure_ad": "waad",          # Windows Azure AD
    "google": "google-apps",
    "okta": "okta",
    "saml": "samlp",
    "oidc": "oidc",
}
```

---

## JWT Structure for Multi-Tenant

### Current JWT (from `01-admin-hierarchy.md:463-496`)

The existing design already includes `tenant_id`, `scope`, and `plan` fields. The full structure:

```json
{
  "sub": "user-uuid",
  "email": "user@acmecorp.com",
  "tenant_id": "tenant-uuid",
  "tenant_slug": "acme-corp",
  "roles": ["tenant_admin", "default"],
  "scope": "tenant",
  "plan": "professional",
  "permissions": ["chat:query", "kb:manage", "user:manage"],
  "sso_connection": "azure_ad",
  "org_id": "org_acme123",
  "session_id": "session-uuid",
  "exp": 1709587200,
  "iat": 1709558400,
  "iss": "mingai-platform",
  "aud": "mingai-api"
}
```

### JWT Claim Details

| Claim            | Type     | Source                     | Purpose                  |
| ---------------- | -------- | -------------------------- | ------------------------ |
| `sub`            | string   | User record ID             | Unique user identifier   |
| `email`          | string   | IdP claim                  | User email               |
| `tenant_id`      | string   | Auth0 org metadata         | Tenant isolation key     |
| `tenant_slug`    | string   | Tenant record              | URL routing              |
| `roles`          | string[] | Tenant role assignment     | RBAC                     |
| `scope`          | string   | `"tenant"` or `"platform"` | Admin tier               |
| `plan`           | string   | Tenant record              | Feature gating           |
| `permissions`    | string[] | Resolved at login          | Flattened permission set |
| `sso_connection` | string   | Auth0 connection type      | Audit trail              |
| `org_id`         | string   | Auth0 Organization ID      | Auth0 correlation        |
| `session_id`     | string   | Generated at login         | Session tracking         |

### Token Generation Changes

```python
# Current: auth/service.py generates JWT without tenant context
# New: Include tenant_id and plan from tenant record

async def _generate_tokens(
    cls,
    user_id: str,
    email: str,
    roles: List[str],
    tenant_id: str,           # NEW
    tenant_slug: str,         # NEW
    plan: str,                # NEW
    sso_connection: str,      # NEW
) -> TokensResponse:
    """Generate JWT with multi-tenant claims."""
    token_data = {
        "sub": user_id,
        "email": email,
        "tenant_id": tenant_id,
        "tenant_slug": tenant_slug,
        "roles": roles,
        "scope": "tenant",
        "plan": plan,
        "sso_connection": sso_connection,
        "session_id": str(uuid.uuid4()),
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token({"sub": user_id, "tenant_id": tenant_id})
    csrf_token = generate_csrf_token()

    return TokensResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        csrf_token=csrf_token,
        expires_in=settings.jwt_expire_minutes * 60,
    )
```

---

## Auth0 Organizations for Tenant Isolation

### Organization Provisioning

When a platform admin creates a new tenant, an Auth0 Organization is created:

```python
async def provision_tenant(
    name: str,
    admin_email: str,
    plan: str,
    sso_config: Optional[SSOConfig],
) -> Tenant:
    """
    Provision new tenant with Auth0 Organization.

    Steps:
    1. Create Auth0 Organization
    2. Create tenant record in platform database
    3. Set up default SSO connection (or local auth)
    4. Create initial admin user
    5. Configure Organization branding
    """
    auth0_mgmt = get_auth0_management_client()

    # 1. Create Auth0 Organization
    slug = slugify(name)
    org = await auth0_mgmt.organizations.create({
        "name": slug,
        "display_name": name,
        "metadata": {
            "tenant_id": str(uuid.uuid4()),
            "plan": plan,
        },
        "branding": {
            "colors": {"primary": "#1a73e8"},
        },
    })

    # 2. Create tenant record
    tenant = await create_tenant_record(
        id=org["metadata"]["tenant_id"],
        name=name,
        slug=slug,
        plan=plan,
        auth0_org_id=org["id"],
    )

    # 3. Configure SSO connection
    if sso_config:
        await configure_sso_connection(tenant, sso_config, auth0_mgmt)
    else:
        # Enable local auth (Auth0 database connection)
        await auth0_mgmt.organizations.add_connection(
            org_id=org["id"],
            connection_id=AUTH0_DATABASE_CONNECTION_ID,
        )

    # 4. Create admin user invitation
    await invite_tenant_admin(tenant, admin_email)

    return tenant
```

### Organization Login Flow

```
1. User navigates to acme.mingai.ai (or clicks "Sign In")
2. Frontend detects tenant from subdomain or shows org picker
3. Frontend redirects to Auth0 with organization parameter:
   GET https://mingai.auth0.com/authorize
     ?client_id=MINGAI_CLIENT_ID
     &organization=org_acme123
     &redirect_uri=https://acme.mingai.ai/auth/callback
     &scope=openid profile email
     &response_type=code
4. Auth0 shows Acme's configured SSO (e.g., Entra ID login)
5. User authenticates with their corporate IdP
6. Auth0 redirects back with code
7. Backend exchanges code, gets Auth0 ID token with org claims:
   {
     "sub": "auth0|user123",
     "email": "user@acmecorp.com",
     "org_id": "org_acme123",
     "org_name": "acme-corp",
     "org_metadata": {"tenant_id": "tenant-uuid", "plan": "professional"}
   }
8. Backend generates platform JWT with tenant_id
```

### Domain-Based Organization Routing

```python
async def resolve_organization_from_email(email: str) -> Optional[str]:
    """
    Resolve Auth0 Organization from user's email domain.

    Used when user enters email before choosing organization.
    Maps email domain -> tenant -> Auth0 org_id.
    """
    domain = email.split("@")[1].lower()

    # Check domain -> tenant mapping
    tenant = await lookup_tenant_by_domain(domain)
    if tenant and tenant.sso_config:
        return tenant.sso_config.org_id

    return None  # No org found, show org picker


async def resolve_organization_from_subdomain(host: str) -> Optional[str]:
    """
    Resolve Auth0 Organization from request subdomain.

    acme.mingai.ai -> org_acme123
    """
    subdomain = host.split(".")[0] if "." in host else None
    if subdomain and subdomain not in ("www", "api", "app"):
        tenant = await lookup_tenant_by_slug(subdomain)
        if tenant and tenant.sso_config:
            return tenant.sso_config.org_id

    return None
```

---

## Local Auth Fallback for Non-SSO Tenants

### When Local Auth is Used

1. **Starter plan tenants**: SSO not included in starter plan (see `01-admin-hierarchy.md:453`)
2. **Development/test environments**: No IdP available
3. **Tenant admin override**: `sso_config.allow_local_fallback = True`
4. **Emergency access**: Platform admin bypass when IdP is down

### Implementation

```python
# Enhanced auth mode endpoint -- now tenant-aware
@router.get("/mode", response_model=AuthModeResponse)
async def get_auth_mode(
    request: Request,
    tenant_id: Optional[str] = None,
):
    """
    Get authentication mode for a specific tenant.

    Replaces the current global auth_mode with tenant-specific config.
    """
    if tenant_id:
        tenant = await get_tenant(tenant_id)
        if not tenant:
            raise HTTPException(404, "Tenant not found")

        return AuthModeResponse(
            mode="sso" if tenant.sso_config and tenant.sso_config.connection_id else "local",
            sso_enabled=bool(tenant.sso_config and tenant.sso_config.connection_id),
            local_enabled=tenant.sso_config.allow_local_fallback if tenant.sso_config else True,
            sso_provider=tenant.sso_config.connection_type if tenant.sso_config else None,
            sso_recommended=bool(tenant.sso_config and tenant.sso_config.connection_id),
        )

    # Platform-level default
    return AuthModeResponse(
        mode="dual",
        sso_enabled=True,
        local_enabled=True,
        sso_recommended=True,
    )
```

### Local Auth + Tenant Association

For tenants without SSO, users authenticate via email+password but are still scoped to a tenant:

```python
@router.post("/login/local", response_model=LoginResponse)
async def login_local(request: LocalLoginRequest, response: Response):
    """
    Local login with tenant context.

    Tenant resolution order:
    1. Email domain -> tenant mapping
    2. User record -> tenant_id
    3. Explicit tenant_id in request (for multi-tenant users)
    """
    user, tokens = await AuthService.login_local(
        email=request.email,
        password=request.password,
    )

    # User record already has tenant_id assigned at invitation time
    # JWT will include tenant_id from user record
    return LoginResponse(user=user, tokens=tokens)
```

---

## Migration Path: Entra-Only to Auth0 Broker

### Phase 1: Auth0 Setup (No User Impact)

```
Week 1-2:
├─ Create Auth0 tenant (mingai.auth0.com)
├─ Configure Auth0 Application (SPA + Regular Web App)
├─ Create "default" Organization for existing Entra users
├─ Add Entra ID Enterprise Connection to Auth0
│   ├─ Auth0 becomes the OIDC client to Entra
│   ├─ Use existing Azure AD app registration
│   └─ Map Entra claims to Auth0 user profile
├─ Test: Auth0 → Entra → Auth0 round-trip works
└─ No production impact (old endpoints still active)
```

### Phase 2: Dual-Mode Operation

```
Week 3-4:
├─ Deploy new SSO endpoints alongside existing ones:
│   ├─ POST /v1/auth/login/sso/callback  (Auth0 callback)
│   ├─ GET  /v1/auth/login/sso           (Auth0 authorize URL)
│   └─ Existing Azure endpoints remain active
├─ Frontend feature flag: USE_AUTH0_SSO=false (off by default)
├─ Internal testing with Auth0 flow
├─ Migrate test users to Auth0 Organization
└─ Both paths generate identical JWT structure
```

### Phase 3: Gradual Rollout

```
Week 5-6:
├─ Enable Auth0 for new tenant sign-ups
├─ Migrate existing users in waves:
│   ├─ Wave 1: Internal/dev users
│   ├─ Wave 2: Pilot tenants (opt-in)
│   └─ Wave 3: Remaining tenants
├─ User experience: same Entra login, different broker
│   (Auth0 redirects to Entra transparently)
└─ Monitor: login success rate, latency, error rate
```

### Phase 4: Deprecate Direct Azure AD

```
Week 7-8:
├─ Remove old /v1/auth/login/azure endpoints
├─ All SSO flows go through Auth0
├─ Remove Azure AD config from api-service .env
│   (Entra config moves to Auth0 Connection)
├─ Keep MS Graph integration via OBO token
│   (Auth0 passes Entra access token for Graph API)
└─ Complete migration
```

### Migration Compatibility

During dual-mode operation, both old and new JWTs must work:

```python
async def validate_jwt(token: str) -> TokenData:
    """
    Validate JWT from either old or new auth flow.

    Detection:
    - Old JWT: has no tenant_id claim
    - New JWT: has tenant_id claim
    """
    payload = verify_token(token)

    if "tenant_id" in payload:
        # New multi-tenant JWT
        return TokenData(
            user_id=payload["sub"],
            email=payload["email"],
            tenant_id=payload["tenant_id"],
            roles=payload["roles"],
            scope=payload.get("scope", "tenant"),
        )
    else:
        # Legacy single-tenant JWT -- assign to default tenant
        return TokenData(
            user_id=payload["sub"],
            email=payload["email"],
            tenant_id=DEFAULT_TENANT_ID,  # Existing users go to default tenant
            roles=payload.get("roles", ["default"]),
            scope="tenant",
        )
```

---

## MS Graph Integration After Migration

### OBO Token Flow with Auth0

The current system uses MS Graph for profile enrichment (auth/service.py) and the Azure AD MCP server uses OBO (On-Behalf-Of) for calendar/email access (ms_token_store.py). This must continue to work after migration.

```
User → Auth0 → Entra ID → Auth0 → Backend
                  │
                  └─ Auth0 receives Entra access token
                     Auth0 can pass it downstream via:
                     1. Custom Auth0 Action (post-login)
                     2. Token exchange endpoint

Backend → Auth0 Management API → Get user's IdP token
        → Use IdP token for MS Graph calls (OBO)
```

### Auth0 Action for Entra Token Forwarding

```javascript
// Auth0 Post-Login Action
exports.onExecutePostLogin = async (event, api) => {
  if (event.connection.strategy === "waad") {
    // Store Entra access token in Auth0 user metadata
    const entraToken = event.secrets.ENTRA_ACCESS_TOKEN;
    api.user.setAppMetadata("entra_access_token", entraToken);
    api.user.setAppMetadata(
      "entra_refresh_token",
      event.secrets.ENTRA_REFRESH_TOKEN,
    );
  }
};
```

### Backend Retrieval

```python
async def get_entra_token_for_user(auth0_user_id: str) -> Optional[str]:
    """
    Get Entra access token for MS Graph operations.

    Used by:
    - Profile enrichment at login (department, jobTitle)
    - Azure AD MCP server (calendar, email via OBO)
    """
    auth0_mgmt = get_auth0_management_client()
    user = await auth0_mgmt.users.get(auth0_user_id)
    app_metadata = user.get("app_metadata", {})
    return app_metadata.get("entra_access_token")
```

---

## Security Considerations

### Token Security

| Concern                  | Mitigation                                                                     |
| ------------------------ | ------------------------------------------------------------------------------ |
| JWT tenant_id spoofing   | tenant_id derived from Auth0 org, not user input                               |
| Cross-tenant token reuse | Middleware validates tenant_id on every request (02-data-isolation.md:503-531) |
| Refresh token theft      | httpOnly, secure, sameSite=none cookies (auth/router.py:46-57)                 |
| CSRF                     | Double-submit cookie pattern (auth/router.py:60-71)                            |
| Token blacklisting       | Redis-based blacklist on logout (auth/service.py)                              |

### Auth0 Security Features

| Feature                     | Configuration                      |
| --------------------------- | ---------------------------------- |
| Brute force protection      | Enabled per Organization           |
| Suspicious IP throttling    | Auth0 Anomaly Detection            |
| Breached password detection | Auth0 credential guard             |
| MFA enforcement             | Per-Organization policy            |
| Session limits              | Max 5 concurrent sessions per user |

### Audit Trail

```python
# Every authentication event logged with tenant context
await AuditService.log_auth_event(
    action="login_sso",
    user_id=user_id,
    email=email,
    tenant_id=tenant_id,
    sso_provider=connection_type,     # "azure_ad", "okta", "google"
    auth0_org_id=org_id,
    ip_address=ip_address,
    user_agent=user_agent,
    result="success",
)
```

---

## Configuration Changes Summary

### Environment Variables: Old vs New

| Old (Single-Tenant)      | New (Multi-Tenant)               | Notes                      |
| ------------------------ | -------------------------------- | -------------------------- |
| `AZURE_AD_TENANT_ID`     | Removed (per-tenant in Auth0)    | No longer global           |
| `AZURE_AD_CLIENT_ID`     | `AUTH0_CLIENT_ID`                | Auth0 application ID       |
| `AZURE_AD_CLIENT_SECRET` | `AUTH0_CLIENT_SECRET`            | Auth0 application secret   |
| `AZURE_AD_REDIRECT_URI`  | `AUTH0_CALLBACK_URL`             | Auth0 callback URL         |
| `AZURE_AD_SCOPES`        | Removed (Auth0 manages)          | Scopes per connection      |
| `AUTH_MODE`              | Removed (per-tenant)             | Tenant-level setting       |
| N/A                      | `AUTH0_DOMAIN`                   | Auth0 tenant domain        |
| N/A                      | `AUTH0_MANAGEMENT_CLIENT_ID`     | Management API credentials |
| N/A                      | `AUTH0_MANAGEMENT_CLIENT_SECRET` | Management API credentials |
| N/A                      | `AUTH0_DATABASE_CONNECTION_ID`   | Local auth connection      |

### New API Endpoints

| Endpoint                       | Method   | Auth           | Purpose                  |
| ------------------------------ | -------- | -------------- | ------------------------ |
| `/v1/auth/login/sso`           | GET      | Public         | Get Auth0 authorize URL  |
| `/v1/auth/login/sso/callback`  | POST     | Public         | Auth0 callback handler   |
| `/v1/admin/sso`                | GET      | Tenant Admin   | Get SSO configuration    |
| `/v1/admin/sso`                | PUT      | Tenant Admin   | Configure SSO connection |
| `/v1/admin/sso/test`           | POST     | Tenant Admin   | Test SSO connection      |
| `/v1/admin/sso/domains`        | GET/POST | Tenant Admin   | Domain verification      |
| `/v1/platform/sso/connections` | GET      | Platform Admin | All connections          |

---

## Plan Tier SSO Matrix

From `01-admin-hierarchy.md:447-459`:

| Feature                     | Starter | Professional | Enterprise |
| --------------------------- | ------- | ------------ | ---------- |
| Local auth (email+password) | Yes     | Yes          | Yes        |
| Entra ID SSO                | No      | Yes          | Yes        |
| Google Workspace SSO        | No      | Yes          | Yes        |
| Okta SSO                    | No      | Yes          | Yes        |
| SAML 2.0 Generic            | No      | No           | Yes        |
| Custom OIDC                 | No      | No           | Yes        |
| MFA enforcement             | No      | Optional     | Required   |
| Custom branding on login    | No      | Yes          | Yes        |
| Domain verification         | N/A     | Required     | Required   |

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
