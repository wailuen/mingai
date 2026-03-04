# Authentication & Authorization (RBAC)

## Authentication Architecture

### Dual-Mode Authentication

The system supports two authentication modes configured via `AUTH_MODE` environment variable:

```
dual        (default) - Azure AD + Local
azure_ad_only        - Azure AD only (production)
local_only           - Local dev only (testing)
```

---

## Login Flow

### Azure Entra ID (SSO)

```
1. User clicks "Sign in with Microsoft"
   ↓
2. Frontend redirects to Azure AD login endpoint
   https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize
   ?client_id={client_id}
   &redirect_uri=http://localhost:3000/auth/callback
   &scope=openid profile email offline_access User.Read
   &response_type=code
   ↓
3. User enters credentials in Azure AD
   ↓
4. Azure redirects to callback with authorization code
   ↓
5. Backend exchanges code for tokens
   POST https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token
   {
     "grant_type": "authorization_code",
     "code": "auth_code",
     "redirect_uri": "http://localhost:3000/auth/callback",
     "client_id": "{client_id}",
     "client_secret": "{secret}"
   }
   ↓
6. Azure returns ID token + access token + refresh token
   {
     "access_token": "...",
     "refresh_token": "...",
     "id_token": "...",
     "expires_in": 3600
   }
   ↓
7. Backend validates ID token, extracts user info
   {
     "sub": "user-oid",
     "email": "user@company.com",
     "name": "John Doe",
     "oid": "user-object-id",
     "groups": ["group-id-1", "group-id-2"]
   }
   ↓
8. Backend checks if user exists in Cosmos DB
   - If yes: Load user record
   - If no: Create new user with default role
   ↓
9. Backend creates JWT token
   {
     "user_id": "uuid",
     "email": "user@company.com",
     "roles": ["default", "finance_team"],
     "exp": timestamp,
     "iat": timestamp,
     "token_type": "access"
   }
   ↓
10. Return JWT to frontend in HTTP-only cookie + Bearer token
    ↓
11. Frontend redirects to home page with valid token
```

### Local Authentication (Development)

```
POST /api/v1/auth/local/login
{
  "email": "[LOCAL_DEV_EMAIL from .env]",
  "password": "[LOCAL_DEV_PASSWORD from .env]"
}

↓

1. Validate email + password against hardcoded credentials
2. Look up user in Cosmos DB
3. Create JWT token
4. Return token
```

**Test Credentials** (from .env):

```
Email: [configured in .env as LOCAL_DEV_EMAIL]
Password: [configured in .env as LOCAL_DEV_PASSWORD]
```

---

## JWT Token Structure

### Access Token

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@company.com",
  "roles": ["default", "finance_team"],
  "exp": 1709587200, // Unix timestamp (8 hours)
  "iat": 1709558400, // Unix timestamp (issued at)
  "token_type": "access",
  "jti": "token-id" // JWT ID for revocation tracking
}
```

**Header**:

```json
{
  "alg": "HS256",
  "typ": "JWT"
}
```

**Signature**: HMAC-SHA256(base64url(header) + "." + base64url(payload), JWT_SECRET_KEY)

**Duration**: 8 hours (configurable via `JWT_EXPIRE_MINUTES`)

### Refresh Token

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@company.com",
  "roles": [], // Minimal claims
  "exp": 1710192000, // Unix timestamp (7 days)
  "iat": 1709558400,
  "token_type": "refresh"
}
```

**Duration**: 7 days (configurable via `JWT_REFRESH_EXPIRE_DAYS`)

---

## Token Management

### Token Validation (On Every Request)

```python
# Middleware: app/middleware/auth.py

def validate_jwt(token: str) -> TokenPayload:
    """
    1. Extract token from Authorization header
    2. Check Redis cache for revoked tokens
    3. Decode JWT signature
    4. Validate expiration
    5. Return TokenPayload with user_id, email, roles
    """
    try:
        # 1. Check revocation list
        if redis_client.exists(f"revoked_token:{jti}"):
            raise HTTPException(401, "Token revoked")

        # 2. Decode and validate
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )

        # 3. Check expiration
        if payload["exp"] < time.time():
            raise HTTPException(401, "Token expired")

        return TokenPayload(**payload)

    except JWTError as e:
        raise HTTPException(401, f"Invalid token: {str(e)}")
```

### Token Refresh

```python
# Endpoint: POST /api/v1/auth/token/refresh

def refresh_token(refresh_token: str) -> dict:
    """
    1. Validate refresh token
    2. Load user from database
    3. Generate new access token
    4. Return new tokens
    """
    # Decode refresh token
    payload = decode_token(refresh_token)

    if payload.token_type != "refresh":
        raise HTTPException(401, "Invalid token type")

    # Load user
    user = cosmos_db.users.read_item(payload.user_id, payload.user_id)

    # Generate new tokens
    new_access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        roles=get_user_roles(user.id)
    )

    # Optional: rotate refresh token for security
    new_refresh_token = create_refresh_token(
        user_id=user.id,
        email=user.email
    )

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": settings.jwt_expire_minutes * 60
    }
```

### Token Revocation (Logout)

```python
# Endpoint: POST /api/v1/auth/logout

def logout(token: str) -> dict:
    """
    1. Extract JTI from token
    2. Add to revocation list in Redis
    3. Clear HTTP-only cookie
    4. Return success
    """
    payload = decode_token(token)

    # Add to revocation list (24 hours TTL)
    redis_client.setex(
        f"revoked_token:{payload.jti}",
        86400,  # 24 hours
        "revoked"
    )

    return {"message": "Logged out successfully"}
```

---

## Role-Based Access Control (RBAC)

### Role Model

**System Roles** (Predefined, cannot be deleted):

| Role             | Permission                    | Assign Method   | Description     |
| ---------------- | ----------------------------- | --------------- | --------------- |
| default          | chat:query, conversation:read | Auto on signup  | All new users   |
| role_admin       | role:manage                   | System function | Manage roles    |
| index_admin      | index:manage, glossary:manage | System function | Manage indexes  |
| user_admin       | user:manage                   | System function | Manage users    |
| analytics_viewer | analytics:view                | System function | View analytics  |
| audit_viewer     | audit:view                    | System function | View audit logs |

**Custom Roles** (Created by role_admin):

- Finance_Team: HR policies, Finance reports
- Engineering: Engineering docs, Internal APIs
- Executive: All indexes

### Permission Resolution

```python
def get_user_permissions(user_id: str) -> UserPermissions:
    """
    1. Get user from database
    2. Get assigned roles (direct + Azure AD groups)
    3. Aggregate permissions from all roles
    4. Cache in Redis
    5. Return permission object
    """
    # Check cache first
    cached = redis_client.get(f"perms:{user_id}")
    if cached:
        return json.loads(cached)

    # Load user
    user = cosmos_db.users.read_item(user_id, user_id)

    # Get assigned roles
    user_roles_docs = cosmos_db.user_roles.query_items(
        query="SELECT * FROM c WHERE c.user_id = @user_id",
        parameters=[{"name": "@user_id", "value": user_id}]
    )

    # Get group-based roles
    user_groups = get_azure_ad_groups(user.azure_oid)
    group_roles = cosmos_db.group_roles.query_items(
        query="SELECT * FROM c WHERE c.group_id IN (@group_ids)",
        parameters=[{"name": "@group_ids", "value": user_groups}]
    )

    role_ids = [r.role_id for r in user_roles_docs] + [r.role_id for r in group_roles]

    # Get role definitions
    roles = cosmos_db.roles.query_items(
        query="SELECT * FROM c WHERE c.id IN (@role_ids)",
        parameters=[{"name": "@role_ids", "value": role_ids}]
    )

    # Aggregate permissions (union)
    permissions = UserPermissions()
    for role in roles:
        permissions.add_role_permissions(role)

    # Cache 1 hour
    redis_client.setex(
        f"perms:{user_id}",
        3600,
        json.dumps(permissions.to_dict())
    )

    return permissions
```

### Access Control Enforcement

#### Index-Level Access

```python
@app.post("/api/v1/chat/stream")
async def chat(request: ChatRequest, user: User = Depends(get_current_user)):
    """Verify user can access requested indexes"""

    # Get user permissions
    perms = get_user_permissions(user.user_id)

    # Check index access
    for index_id in request.index_ids:
        if index_id not in perms.accessible_indexes:
            raise HTTPException(403, f"Cannot access index {index_id}")

    # Proceed with chat...
```

#### System Function Access

```python
@app.post("/api/v1/roles")
async def create_role(role: RoleCreate, user: User = Depends(get_current_user)):
    """Verify user can manage roles"""

    perms = get_user_permissions(user.user_id)

    if "role:manage" not in perms.system_functions:
        raise HTTPException(403, "Cannot manage roles")

    # Proceed with role creation...
```

#### Data-Level Access

```python
# User can only see their own conversations
@app.get("/api/v1/conversations")
async def list_conversations(user: User = Depends(get_current_user)):
    """List user's conversations (partition key filters automatically)"""

    conversations = cosmos_db.conversations.query_items(
        query="SELECT * FROM c WHERE c.user_id = @user_id",
        parameters=[{"name": "@user_id", "value": user.user_id}]
    )

    return conversations
```

---

## Azure AD Group Integration

### Sync Flow

```
Every 24 hours (or on-demand):

1. Get user's Azure AD group memberships
   GET https://graph.microsoft.com/v1.0/me/memberOf
   (using token with GroupMember.Read.All permission)

2. Extract group IDs
   [
     "group-id-1",
     "group-id-2",
     ...
   ]

3. Query group_roles in Cosmos DB
   Find all roles assigned to these groups

4. Load role definitions
   Aggregate all permissions

5. Update cached permissions
   redis_client.setex(f"perms:{user_id}", 3600, ...)

6. Log sync event
```

### Group-Based Role Assignment

```python
# Admin assigns role to Azure AD group
@app.post("/api/v1/groups/{group_id}/roles")
async def assign_role_to_group(
    group_id: str,
    role_id: str,
    user: User = Depends(get_current_user)
):
    """
    1. Verify user is role_admin
    2. Create group_roles document
    3. Mark all group members' permissions as stale
    4. Return success
    """
    perms = get_user_permissions(user.user_id)
    if "role:manage" not in perms.system_functions:
        raise HTTPException(403, "Cannot manage roles")

    # Create assignment
    group_role = {
        "id": str(uuid.uuid4()),
        "group_id": group_id,
        "group_name": get_group_name(group_id),
        "role_id": role_id,
        "is_active": True,
        "assigned_at": datetime.now(UTC),
        "assigned_by": user.user_id,
        "last_synced": datetime.now(UTC)
    }

    cosmos_db.group_roles.create_item(group_role)

    # Invalidate permissions for all group members
    group_members = get_group_members(group_id)
    for member_id in group_members:
        redis_client.delete(f"perms:{member_id}")

    return {"message": "Role assigned to group"}
```

---

## Permission Cache Invalidation

### On-Demand Invalidation (Cross-Instance)

When a permission changes, all API instances must invalidate cache:

```python
def invalidate_user_permissions(user_id: str):
    """
    1. Delete from Redis (this instance)
    2. Publish to Redis Pub/Sub
    3. All other instances receive and invalidate
    """
    # Local delete
    redis_client.delete(f"perms:{user_id}")

    # Broadcast to other instances
    redis_client.publish(
        "cache_invalidation",
        json.dumps({
            "type": "permission_invalidated",
            "user_id": user_id,
            "timestamp": datetime.now(UTC).isoformat()
        })
    )

# Listener (runs on all instances)
async def listen_cache_invalidation():
    pubsub = redis_client.pubsub()
    pubsub.subscribe("cache_invalidation")

    while True:
        message = pubsub.get_message()
        if message and message["type"] == "message":
            event = json.loads(message["data"])
            if event["type"] == "permission_invalidated":
                # Already deleted locally, just log
                logger.info(f"Permission invalidated: {event['user_id']}")
```

---

## Security Best Practices

### JWT Secret Management

- ✅ Minimum 32 characters (enforced)
- ✅ Unique per environment
- ✅ Stored in .env (development) / Azure Key Vault (production)
- ✅ Rotated quarterly

### Token Expiration

- Access: 8 hours (short, reduce replay risk)
- Refresh: 7 days (longer, allow occasional refresh)
- Auto-extend: Not implemented (requires explicit refresh)

### CORS Protection

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,  # ["http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
```

### CSRF Protection

```python
# All state-changing operations require CSRF token
@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    if request.method in ["POST", "PUT", "DELETE"]:
        csrf_token = request.headers.get("X-CSRF-Token")
        if not csrf_token or not validate_csrf_token(csrf_token):
            return JSONResponse({"error": "CSRF token invalid"}, 403)
    return await call_next(request)
```

### Rate Limiting

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/api/v1/chat/stream")
@limiter.limit("10/minute")  # 10 requests per minute per IP
async def chat(...):
    ...
```

---

## Production Considerations

### Secret Rotation

```
Current: JWT_SECRET_KEY in .env
Action: Move to Azure Key Vault
Steps:
  1. Create new key version in Key Vault
  2. Update API instances to use new key
  3. Keep old key for 7 days (token validation overlap)
  4. Remove old key
```

### Token Revocation at Scale

```
Current: Redis in-memory list
Issue: Revoked tokens lost on restart
Solution:
  1. Use persistent revocation database
  2. Or: Keep tokens short (8 hours)
  3. Or: Maintain revocation list in Cosmos DB with TTL
```

### Azure AD Token Refresh

```
Scenario: Azure AD access token expires during long session
Solution: Background token refresh worker

Worker: app/modules/auth/token_refresh_worker.py
- Monitors Azure tokens in Redis (prefixed with ttl)
- Refreshes tokens 15 min before expiry
- Updates stored tokens
- Publishes invalidation event
```

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
