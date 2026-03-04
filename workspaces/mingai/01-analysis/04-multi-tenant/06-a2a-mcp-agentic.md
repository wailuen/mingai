# A2A, MCP, and Agentic Architecture

**Date**: March 4, 2026
**Status**: Architecture Design
**Scope**: Agent-to-Agent protocol, MCP server management, and agentic RAG for multi-tenant

---

## Overview

The current system has 9 MCP (Model Context Protocol) servers providing external data access (Bloomberg, CapIQ, Perplexity, etc.) with a flat access model. Multi-tenancy requires tenant-scoped MCP server routing, a platform-level MCP server registry, and an evolved agentic architecture where specialized agents coordinate to answer complex queries. This document designs the A2A (Agent-to-Agent) protocol, tenant-level MCP access control, and the migration from classic RAG to agentic RAG.

---

## Current MCP Architecture

### Evidence from Source Code

**9 MCP servers** in `/Users/wailuen/Development/aihub2/src/mcp-servers/`:

| MCP Server        | Directory            | External API          | Purpose                           |
| ----------------- | -------------------- | --------------------- | --------------------------------- |
| **Azure AD**      | `azure-ad-mcp/`      | MS Graph API          | Calendar, email, directory, Teams |
| **Bloomberg**     | `bloomberg-mcp/`     | Bloomberg DL API      | Market data, fundamentals, FX     |
| **CapIQ**         | `capiq-mcp/`         | S&P Capital IQ        | Company financials, comparables   |
| **Perplexity**    | `perplexity-mcp/`    | Perplexity API        | Internet search, research         |
| **Oracle Fusion** | `oracle-fusion-mcp/` | Oracle Cloud REST     | ERP data, financials              |
| **AlphaGeo**      | `alphageo-mcp/`      | AlphaGeo API          | Geographic/location data          |
| **Teamworks**     | `teamworks-mcp/`     | Teamworks API         | Collaboration platform            |
| **PitchBook**     | `pitchbook-mcp/`     | PitchBook/Morningstar | PE/VC deal data                   |
| **iLevel**        | `ilevel-mcp/`        | iLevel API            | Enterprise data                   |

### MCP Service Layer (app/modules/mcp/service.py:47-100)

```python
# service.py:47-68 -- MCPService class
class MCPService:
    """
    Orchestration service for MCP agent invocations.

    This service provides:
    - RBAC-based filtering of available MCP sources for users
    - Agent invocation with circuit breaker protection
    - SSE event emission for real-time progress updates
    """

    def __init__(self) -> None:
        self._agent_registry = get_agent_registry()

    async def _ensure_agents_loaded(self) -> None:
        """
        Sync MCP agents with database configs.
        1. Adds new agents for enabled configs not in registry
        2. Removes stale agents that are no longer in enabled configs
        """
        from app.modules.mcp.models import MCPServerModel
        from app.modules.mcp.generic_agent import GenericMCPAgent
        from app.modules.mcp.cache import MCPCacheService

        configs_data = await MCPCacheService.get_enabled_configs()
        # ... sync logic
```

### Current MCP Invocation Flow (app/modules/chat/operations/mcp.py:51-80)

```python
# operations/mcp.py:51-63 -- search_mcp function
async def search_mcp(
    message: str,
    user_id: str,
    conversation_id: str,
    message_id: str,
    user_token: Optional[str],         # OBO token for delegated auth
    format_event: Callable,
    mcp_ids: Optional[List[str]] = None,
    conversation_history: Optional[List[Dict]] = None,
    user_roles: Optional[List[str]] = None,
    timezone: Optional[str] = None,
    user_context: Optional["UserContext"] = None,
) -> AsyncGenerator[Union[str, "MCPResult"], None]:
    """Invoke MCP agents and yield SSE events in real-time."""
```

### Current Access Control

MCP access is controlled through the same RBAC system as knowledge bases (service.py:9):

```python
# service.py:7-9
# MCP servers are unified with KB indexes as "knowledge sources":
# - Access controlled by role's index_permissions (same as KB indexes)
# - Each MCP has its own circuit breaker for fault isolation
```

### Current Credential Management (10-kaizen-extension-analysis.md:450-479)

Each MCP server independently loads credentials from its own `.env` file:

```python
# Pattern from each MCP server's config.py
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    PROVIDER_API_KEY: str        # Bloomberg, CapIQ, etc.
    PROVIDER_CLIENT_ID: str      # If OAuth
    PROVIDER_CLIENT_SECRET: str  # If OAuth

    # Optional Azure OpenAI for agentic orchestration
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_KEY: str = ""
    AZURE_OPENAI_DEPLOYMENT: str = "mcp-<server-name>"
```

### Current Limitations

1. **Flat access model**: All users with MCP access can see all enabled MCP servers
2. **No tenant scoping**: MCP server enable/disable is global, not per-tenant
3. **Independent credentials**: Each server manages its own API keys, no centralized credential store
4. **No A2A coordination**: MCP servers operate independently, no cross-agent communication
5. **Single-step invocation**: One query maps to one MCP server, no multi-agent orchestration
6. **Global circuit breakers**: Breaker state is shared across all tenants

---

## Target Architecture: Tenant-Scoped MCP with A2A

### Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Platform Admin Layer                              │
│  Manages global MCP server catalog                                   │
│  POST /v1/platform/mcp-servers                                       │
│  ├─ bloomberg-mcp   ✅ active  (platform credentials)               │
│  ├─ capiq-mcp       ✅ active  (platform credentials)               │
│  ├─ perplexity-mcp  ✅ active  (platform credentials)               │
│  ├─ azure-ad-mcp    ✅ active  (per-user OBO token)                 │
│  ├─ pitchbook-mcp   ✅ active  (platform credentials)               │
│  ├─ custom-mcp-1    ✅ active  (enterprise tenant custom)           │
│  └─ 4 more...                                                        │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     Tenant Admin Layer                                │
│  Selects which MCP servers are available to their organization       │
│                                                                      │
│  Tenant "Acme Corp" (Professional plan):                             │
│  ├─ ✅ bloomberg-mcp  (platform key)                                │
│  ├─ ✅ perplexity-mcp (platform key)                                │
│  ├─ ✅ azure-ad-mcp   (per-user OBO)                               │
│  ├─ ❌ capiq-mcp      (not enabled)                                 │
│  └─ ❌ pitchbook-mcp  (not enabled)                                 │
│                                                                      │
│  Tenant "BigCorp" (Enterprise plan):                                 │
│  ├─ ✅ All standard MCP servers                                     │
│  ├─ ✅ custom-erp-mcp (BigCorp's own MCP server)                   │
│  └─ ✅ custom-crm-mcp (BigCorp's own MCP server)                   │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│            Agentic Orchestrator (Per-Request)                         │
│                                                                      │
│  User query: "Compare Bloomberg's view of AAPL with CapIQ data      │
│               and summarize recent news from Perplexity"             │
│                                                                      │
│  ┌─────────────┐                                                     │
│  │ Intent Agent │ ← Classifies query, identifies required agents     │
│  └──────┬──────┘                                                     │
│         │ A2A dispatch                                               │
│         ├──────────────────┬──────────────────┐                      │
│         ▼                  ▼                  ▼                      │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │ Bloomberg   │  │ CapIQ        │  │ Perplexity   │               │
│  │ Agent       │  │ Agent        │  │ Agent        │               │
│  │ (market)    │  │ (financial)  │  │ (news)       │               │
│  └──────┬──────┘  └──────┬───────┘  └──────┬───────┘               │
│         │                │                  │                        │
│         └────────────────┼──────────────────┘                        │
│                          ▼                                           │
│                  ┌──────────────┐                                     │
│                  │ Synthesis    │ ← Combines results from all agents │
│                  │ Agent        │                                     │
│                  └──────┬───────┘                                     │
│                         │                                            │
│                         ▼                                            │
│                  ┌──────────────┐                                     │
│                  │ Validation   │ ← Fact-checks, deduplicates       │
│                  │ Agent        │                                     │
│                  └──────────────┘                                     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## MCP Server Registry: Platform Level

### Global MCP Server Data Model

Stored in PostgreSQL `mcp_servers` table with RLS (extends current model from `app/modules/mcp/models.py`):

```python
# mcp_servers container (PK: /id)
{
    "id": "bloomberg-mcp",
    "display_name": "Bloomberg Market Data",
    "description": "Real-time and historical market data from Bloomberg DL API",
    "category": "financial_data",          # financial_data | research | productivity | custom
    "is_platform_managed": True,           # Platform admin manages credentials
    "is_enabled": True,                    # Globally enabled
    "endpoint": "http://bloomberg-mcp:8010",
    "health_check_url": "http://bloomberg-mcp:8010/health",
    "capabilities": {
        "streaming_events": True,          # Supports real-time SSE
        "requires_user_token": False,      # Uses platform credentials, not OBO
        "supports_conversation_history": False,
        "tools": [
            "get_market_data",
            "get_fundamentals",
            "get_historical_prices",
            "get_fx_rates",
            "get_company_comparables",
        ],
    },
    "credential_config": {
        "type": "platform",                # platform | per_user_obo | tenant_byokey
        "vault_ref": "vault://aihub/bloomberg-credentials",
    },
    "rate_limits": {
        "requests_per_minute": 100,
        "window_seconds": 60,
    },
    "system_prompt": "You are a financial data specialist...",
    "icon_url": "/assets/mcp/bloomberg.svg",
    "plan_requirement": "professional",    # starter | professional | enterprise
    "created_at": "2026-03-04T00:00:00Z",
    "updated_at": "2026-03-04T00:00:00Z",
}
```

### MCP Credential Types

| Type            | Description                       | Example                     | Stored Where              |
| --------------- | --------------------------------- | --------------------------- | ------------------------- |
| `platform`      | Platform admin provides API key   | Bloomberg, CapIQ, PitchBook | Key Vault (platform)      |
| `per_user_obo`  | Each user's delegated token       | Azure AD (calendar, email)  | Redis (session-scoped)    |
| `tenant_byokey` | Tenant provides their own API key | Custom/enterprise MCP       | Key Vault (tenant-scoped) |

### Platform Admin API (from `01-admin-hierarchy.md:147`)

```python
@router.get("/api/v1/platform/mcp-servers")
async def list_global_mcp_servers(
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """List all registered MCP servers with health status."""
    servers = await MCPServerModel.get_all()
    health = await check_mcp_health_batch([s.health_check_url for s in servers])

    return [
        {
            "id": s.id,
            "display_name": s.display_name,
            "category": s.category,
            "is_enabled": s.is_enabled,
            "plan_requirement": s.plan_requirement,
            "health": health.get(s.id, "unknown"),
            "tenant_count": await count_tenants_using_mcp(s.id),
        }
        for s in servers
    ]


@router.post("/api/v1/platform/mcp-servers")
async def register_mcp_server(
    request: MCPServerRegisterRequest,
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """
    Register a new MCP server globally.

    Steps:
    1. Validate endpoint is reachable
    2. Discover capabilities via MCP protocol
    3. Store credentials in vault
    4. Create server record
    5. Make available for tenant selection
    """
    # Health check
    is_healthy = await check_mcp_endpoint(request.endpoint)
    if not is_healthy:
        raise HTTPException(400, "MCP server endpoint not reachable")

    # Discover capabilities
    capabilities = await discover_mcp_capabilities(request.endpoint)

    # Store credentials
    vault_ref = None
    if request.api_key:
        vault_ref = await vault_service.store_secret(
            name=f"mcp-{request.id}",
            value=request.api_key,
        )

    server = await MCPServerModel.create({
        "id": request.id,
        "display_name": request.display_name,
        "endpoint": request.endpoint,
        "capabilities": capabilities,
        "credential_config": {
            "type": request.credential_type,
            "vault_ref": vault_ref,
        },
        "is_enabled": True,
        "plan_requirement": request.plan_requirement,
    })

    return server
```

---

## Tenant-Level MCP Access Control

### Tenant MCP Configuration

Stored in the tenant record:

```python
# tenants container -- mcp_config field
{
    "id": "tenant-uuid",
    "name": "Acme Corporation",
    # ... other tenant fields ...
    "mcp_config": {
        "enabled_servers": [
            {
                "mcp_id": "bloomberg-mcp",
                "credential_type": "platform",     # Uses platform credentials
                "custom_config": None,
            },
            {
                "mcp_id": "perplexity-mcp",
                "credential_type": "platform",
                "custom_config": {
                    "max_searches_per_day": 500,   # Tenant-specific limit
                },
            },
            {
                "mcp_id": "azure-ad-mcp",
                "credential_type": "per_user_obo",
                "custom_config": None,
            },
        ],
        "custom_servers": [                        # Enterprise only
            {
                "mcp_id": "custom-erp-mcp",
                "display_name": "Internal ERP",
                "endpoint": "https://erp-mcp.acme.internal:8090",
                "credential_type": "tenant_byokey",
                "vault_ref": "vault://aihub/tenant-acme/custom-erp-key",
            },
        ],
        "max_concurrent_mcp_calls": 3,
        "mcp_timeout_seconds": 30,
    },
}
```

### Tenant Admin API (from `01-admin-hierarchy.md:259-261`)

```python
@router.get("/api/v1/admin/mcp-servers")
async def list_tenant_mcp_servers(
    admin: TenantAdmin = Depends(require_tenant_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """List MCP servers available to and enabled for this tenant."""
    tenant = await TenantService.get(tenant_id)

    # Get platform servers available for this plan
    all_servers = await MCPServerModel.get_enabled()
    plan_servers = [
        s for s in all_servers
        if plan_allows_mcp(tenant.plan, s.plan_requirement)
    ]

    # Get tenant's enabled list
    enabled_ids = {s["mcp_id"] for s in tenant.mcp_config.get("enabled_servers", [])}

    return {
        "available_servers": [
            {
                "id": s.id,
                "display_name": s.display_name,
                "category": s.category,
                "description": s.description,
                "is_enabled": s.id in enabled_ids,
                "credential_type": s.credential_config["type"],
                "tools": s.capabilities.get("tools", []),
            }
            for s in plan_servers
        ],
        "custom_servers": tenant.mcp_config.get("custom_servers", []),
        "can_add_custom": tenant.plan == "enterprise",
    }


@router.post("/api/v1/admin/mcp-servers/{mcp_id}/enable")
async def enable_mcp_server(
    mcp_id: str,
    admin: TenantAdmin = Depends(require_tenant_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Enable a platform MCP server for this tenant."""
    tenant = await TenantService.get(tenant_id)

    # Validate plan access
    server = await MCPServerModel.get(mcp_id)
    if not server or not server.is_enabled:
        raise HTTPException(404, "MCP server not available")
    if not plan_allows_mcp(tenant.plan, server.plan_requirement):
        raise HTTPException(403, f"MCP server requires {server.plan_requirement} plan")

    # Check tenant quota
    current_count = len(tenant.mcp_config.get("enabled_servers", []))
    max_mcp = get_mcp_limit(tenant.plan)  # starter:3, professional:all, enterprise:all
    if current_count >= max_mcp:
        raise HTTPException(403, f"Maximum {max_mcp} MCP servers on {tenant.plan} plan")

    # Add to tenant's enabled list
    await TenantService.enable_mcp(tenant_id, mcp_id, server.credential_config["type"])

    # Invalidate tenant's MCP cache
    await invalidate_tenant_mcp_cache(tenant_id)
```

### Per-Request MCP Filtering

The current `MCPService._ensure_agents_loaded()` loads all enabled MCP servers globally. This must be scoped by tenant:

```python
class TenantMCPService:
    """Tenant-scoped MCP service."""

    async def get_available_agents(self, tenant_id: str, user_id: str) -> List[str]:
        """
        Get MCP servers available for this tenant + user combination.

        Filters:
        1. Tenant has enabled the MCP server
        2. User's role has permission for this MCP
        3. MCP server is healthy (circuit breaker not open)
        """
        # Get tenant's enabled MCP servers
        tenant = await TenantService.get(tenant_id)
        enabled_mcps = tenant.mcp_config.get("enabled_servers", [])
        custom_mcps = tenant.mcp_config.get("custom_servers", [])
        all_enabled_ids = [m["mcp_id"] for m in enabled_mcps + custom_mcps]

        # Filter by user's RBAC permissions
        from app.modules.auth.permission_service import get_permission_service
        permission_service = get_permission_service()
        user_permissions = await permission_service.get_user_permissions_by_id(user_id, tenant_id)
        user_mcp_access = user_permissions.kb_sources  # MCPs are in kb_sources

        # Intersection: tenant-enabled AND user-permitted
        available = [
            mcp_id for mcp_id in all_enabled_ids
            if mcp_id in user_mcp_access
        ]

        # Filter by circuit breaker health
        healthy = []
        for mcp_id in available:
            breaker = get_mcp_circuit_breaker(f"{tenant_id}:{mcp_id}")  # Per-tenant breaker
            if not breaker.is_open:
                healthy.append(mcp_id)

        return healthy
```

---

## Multi-Agent Coordination: A2A Protocol

### Agent Roles

| Agent                | Role                                         | When Invoked               |
| -------------------- | -------------------------------------------- | -------------------------- |
| **Intent Agent**     | Classifies query, selects agents             | Every query                |
| **Search Agent(s)**  | Execute KB search, MCP calls                 | When data retrieval needed |
| **Synthesis Agent**  | Combines results from multiple sources       | Multi-source queries       |
| **Validation Agent** | Fact-checks, deduplicates, scores confidence | Before final response      |
| **Planner Agent**    | Plans multi-step research                    | Complex/research queries   |

### Current vs Agentic Flow

**Current (Single-Step RAG)** from `app/modules/chat/service.py`:

```
User Query
    ↓
Intent Detection (single LLM call)
    ↓
Router selects ONE handler:
    ├─ AutoHandler: KB search → LLM generate
    ├─ ManualHandler: specific index → LLM generate
    ├─ PureLLMHandler: direct LLM (no RAG)
    └─ ResearchAgentHandler: multi-step tool calling
    ↓
Single LLM Response (streaming)
```

**New (Multi-Agent Agentic RAG)**:

```
User Query
    ↓
Intent Agent (classifies complexity + required sources)
    ├─ Simple query → Single agent path (backward compatible)
    └─ Complex query → Multi-agent orchestration:
        ↓
    Planner Agent (generates execution plan)
        ↓
    Parallel Dispatch:
        ├─ KB Search Agent(s) → search tenant's indexes
        ├─ MCP Agent(s) → invoke relevant MCP servers
        └─ Internet Agent → Tavily/Perplexity search
        ↓
    Synthesis Agent (combines, cross-references)
        ↓
    Validation Agent (fact-check, confidence scoring)
        ↓
    Streaming Response to User
```

### A2A Message Protocol

```python
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum

class AgentRole(Enum):
    INTENT = "intent"
    PLANNER = "planner"
    KB_SEARCH = "kb_search"
    MCP_SEARCH = "mcp_search"
    INTERNET_SEARCH = "internet_search"
    SYNTHESIS = "synthesis"
    VALIDATION = "validation"

class MessageType(Enum):
    TASK_REQUEST = "task_request"       # Orchestrator -> Agent
    TASK_RESULT = "task_result"         # Agent -> Orchestrator
    PROGRESS_EVENT = "progress_event"   # Agent -> Frontend (via SSE)
    ERROR = "error"                     # Agent -> Orchestrator

@dataclass
class A2AMessage:
    """Inter-agent message format."""
    id: str                             # Unique message ID
    type: MessageType
    source_agent: AgentRole
    target_agent: AgentRole
    tenant_id: str                      # Tenant context for isolation
    user_id: str                        # User context for permissions
    conversation_id: str                # Conversation for tracking

    # Task-specific payload
    query: str                          # Original user query
    context: Dict[str, Any] = field(default_factory=dict)
    results: Optional[List[Dict]] = None
    error: Optional[str] = None

    # Metadata
    timestamp: str = ""
    latency_ms: Optional[int] = None
    token_usage: Optional[Dict[str, int]] = None


@dataclass
class ExecutionPlan:
    """Plan generated by Planner Agent."""
    steps: List["PlanStep"]
    estimated_agents: List[AgentRole]
    parallel_groups: List[List[int]]    # Groups of step indices to run in parallel
    timeout_seconds: int = 30

@dataclass
class PlanStep:
    """Single step in execution plan."""
    step_id: int
    agent: AgentRole
    action: str                         # "search_kb", "invoke_mcp", "search_internet"
    parameters: Dict[str, Any]
    depends_on: List[int] = field(default_factory=list)  # Step IDs this depends on
```

### Orchestrator Implementation

```python
class AgenticOrchestrator:
    """
    Multi-agent orchestrator for complex queries.

    Coordinates multiple specialized agents to handle queries
    that require data from multiple sources.
    """

    def __init__(
        self,
        tenant_id: str,
        user_id: str,
        llm_manager: "LLMClientManager",
        mcp_service: "TenantMCPService",
    ):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.llm_manager = llm_manager
        self.mcp_service = mcp_service

    async def execute(
        self,
        query: str,
        conversation_history: List[dict],
        available_mcp_ids: List[str],
        available_kb_ids: List[str],
        sse_callback: Optional[Callable] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Execute multi-agent query processing.

        Steps:
        1. Intent classification (complexity + required agents)
        2. If simple → delegate to single agent (backward compatible)
        3. If complex → plan → parallel dispatch → synthesis → validate
        """
        # Step 1: Intent classification
        intent = await self._classify_intent(query, conversation_history)

        if intent.complexity == "simple":
            # Backward compatible: single agent handles it
            async for chunk in self._execute_simple(
                query, intent, conversation_history, sse_callback
            ):
                yield chunk
            return

        # Step 2: Plan
        plan = await self._create_plan(
            query, intent, available_mcp_ids, available_kb_ids
        )

        if sse_callback:
            await sse_callback({
                "type": "agent_plan",
                "plan": {
                    "steps": len(plan.steps),
                    "agents": [a.value for a in plan.estimated_agents],
                },
            })

        # Step 3: Execute plan steps (parallel where possible)
        all_results = []
        for group in plan.parallel_groups:
            steps = [plan.steps[i] for i in group]
            group_results = await asyncio.gather(*[
                self._execute_step(step, query, all_results, sse_callback)
                for step in steps
            ], return_exceptions=True)

            for result in group_results:
                if isinstance(result, Exception):
                    logger.warning(f"Agent step failed: {result}")
                else:
                    all_results.append(result)

        # Step 4: Synthesis
        if sse_callback:
            await sse_callback({"type": "agent_synthesis", "status": "started"})

        async for chunk in self._synthesize(query, all_results, conversation_history):
            yield chunk

    async def _classify_intent(self, query, history) -> "IntentResult":
        """Use intent agent to classify query complexity."""
        provider, model = await self.llm_manager.get_provider(
            self.tenant_id, use_case="intent_detection"
        )
        # Classification prompt
        messages = [
            {"role": "system", "content": INTENT_CLASSIFICATION_PROMPT},
            {"role": "user", "content": query},
        ]
        response_text = ""
        async for chunk in provider.chat_completion(messages, model, temperature=0):
            response_text += chunk
        return parse_intent_result(response_text)

    async def _execute_step(self, step, query, prior_results, sse_callback):
        """Execute a single plan step."""
        if step.agent == AgentRole.KB_SEARCH:
            return await self._search_kb(step.parameters, query)
        elif step.agent == AgentRole.MCP_SEARCH:
            return await self._invoke_mcp(step.parameters, query, sse_callback)
        elif step.agent == AgentRole.INTERNET_SEARCH:
            return await self._search_internet(step.parameters, query)

    async def _synthesize(self, query, results, history) -> AsyncGenerator[str, None]:
        """Synthesis agent combines results from all sources."""
        provider, model = await self.llm_manager.get_provider(
            self.tenant_id, use_case="chat_response"
        )

        context_parts = []
        for i, result in enumerate(results, 1):
            source_type = result.get("source_type", "unknown")
            data = result.get("data", "")
            context_parts.append(f"[Source {i} - {source_type}]\n{data}\n")

        context = "\n".join(context_parts)
        messages = [
            {"role": "system", "content": SYNTHESIS_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"},
        ]
        if history:
            messages = [messages[0]] + history[-6:] + [messages[-1]]

        async for chunk in provider.chat_completion(messages, model, stream=True):
            yield chunk
```

---

## Agentic RAG vs Classic RAG Pipeline

### Classic RAG (Current)

```
Query → Embed → Search Indexes → Retrieve Top-K → Build Prompt → LLM → Response
```

Limitations:

- Single-pass retrieval (no iterative refinement)
- No cross-source verification
- No query decomposition for complex questions
- Fixed top-K, no adaptive retrieval

### Agentic RAG (New)

```
Query
  ↓
Intent Agent: "This requires market data + KB search + fact-checking"
  ↓
Planner Agent: {
  step 1: Decompose into sub-queries
  step 2: [parallel] Search KB for company policy, Invoke Bloomberg for market data
  step 3: [parallel] Verify numbers with CapIQ, Search Perplexity for recent news
  step 4: Synthesize all results
  step 5: Validate and score confidence
}
  ↓
Execution Engine: runs plan, collects results
  ↓
Synthesis Agent: produces coherent response from all sources
  ↓
Validation Agent: checks for contradictions, assigns confidence
  ↓
Streaming Response with source attribution
```

### Key Differences

| Aspect         | Classic RAG              | Agentic RAG                  |
| -------------- | ------------------------ | ---------------------------- |
| Retrieval      | Single-pass, fixed top-K | Iterative, adaptive          |
| Query handling | Literal query to search  | Decomposed sub-queries       |
| Sources        | One type per query       | Multiple sources in parallel |
| Verification   | None                     | Cross-source fact-checking   |
| Confidence     | Search score only        | Multi-factor confidence      |
| Fallback       | No results = no answer   | Try alternative sources      |
| Cost           | 1 LLM call + 1 search    | 3-8 LLM calls + N searches   |

### When to Use Agentic RAG

| Scenario                     | Classic RAG | Agentic RAG   |
| ---------------------------- | ----------- | ------------- |
| Simple factual question      | Yes         | No (overkill) |
| Multi-source comparison      | No          | Yes           |
| Data verification needed     | No          | Yes           |
| Complex research query       | No          | Yes           |
| Time-sensitive + KB combined | No          | Yes           |
| Single KB, clear answer      | Yes         | No            |

The Intent Agent decides which pipeline to use based on query complexity classification.

---

## Tenant-Scoped Circuit Breakers

### Current: Global Circuit Breakers (services/circuit_breaker.py)

Circuit breaker state is shared across all requests. If one tenant triggers a breaker, all tenants lose access.

### New: Per-Tenant Circuit Breakers

```python
class TenantCircuitBreaker:
    """
    Per-tenant circuit breaker for MCP servers.

    Each tenant has independent circuit breaker state so that
    one tenant's issues don't affect others.
    """

    def __init__(self, tenant_id: str, mcp_id: str, redis_client):
        self.key = f"aihub:{tenant_id}:breaker:{mcp_id}"
        self.redis = redis_client
        self.failure_threshold = 5     # Failures before opening
        self.recovery_timeout = 60     # Seconds before half-open
        self.success_threshold = 2     # Successes to close

    async def is_open(self) -> bool:
        state = await self.redis.hgetall(self.key)
        if not state:
            return False
        if state.get("state") == "open":
            opened_at = float(state.get("opened_at", 0))
            if time.time() - opened_at > self.recovery_timeout:
                return False  # Half-open, allow trial
            return True
        return False

    async def record_success(self):
        await self.redis.hincrby(self.key, "successes", 1)
        state = await self.redis.hgetall(self.key)
        if int(state.get("successes", 0)) >= self.success_threshold:
            await self.redis.delete(self.key)  # Close breaker

    async def record_failure(self):
        await self.redis.hincrby(self.key, "failures", 1)
        state = await self.redis.hgetall(self.key)
        if int(state.get("failures", 0)) >= self.failure_threshold:
            await self.redis.hset(self.key, mapping={
                "state": "open",
                "opened_at": str(time.time()),
            })
            await self.redis.expire(self.key, self.recovery_timeout * 2)
```

---

## Custom MCP Servers (Enterprise Tier)

Enterprise tenants can register their own MCP servers:

### Registration Flow

```python
@router.post("/api/v1/admin/mcp-servers/custom")
async def register_custom_mcp(
    request: CustomMCPRequest,
    admin: TenantAdmin = Depends(require_tenant_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Register a tenant-owned custom MCP server.

    Enterprise plan only. The MCP server must:
    1. Be accessible from the platform network
    2. Implement standard MCP protocol
    3. Pass health check
    """
    tenant = await TenantService.get(tenant_id)
    if not tenant.features.get("custom_mcp_servers"):
        raise HTTPException(403, "Custom MCP servers require Enterprise plan")

    # Validate endpoint reachability
    is_reachable = await check_mcp_endpoint(request.endpoint)
    if not is_reachable:
        raise HTTPException(400, "MCP server not reachable from platform")

    # Discover capabilities
    capabilities = await discover_mcp_capabilities(request.endpoint)

    # Store credentials in tenant-scoped vault
    vault_ref = None
    if request.api_key:
        vault_ref = await vault_service.store_secret(
            name=f"custom-mcp-{tenant_id}-{request.id}",
            value=request.api_key,
        )

    # Add to tenant's custom servers list
    custom_server = {
        "mcp_id": f"custom-{tenant_id}-{request.id}",
        "display_name": request.display_name,
        "endpoint": request.endpoint,
        "capabilities": capabilities,
        "credential_type": "tenant_byokey",
        "vault_ref": vault_ref,
    }

    await TenantService.add_custom_mcp(tenant_id, custom_server)
```

---

## Plan Tier MCP Access

From `01-admin-hierarchy.md:447-459`:

| Feature                   | Starter | Professional     | Enterprise        |
| ------------------------- | ------- | ---------------- | ----------------- |
| Standard MCP servers      | 3 max   | All enabled      | All enabled       |
| Custom MCP servers        | No      | No               | Yes (unlimited)   |
| Multi-agent orchestration | No      | Basic (2 agents) | Full (unlimited)  |
| A2A coordination          | No      | No               | Yes               |
| Custom MCP credentials    | No      | No               | Yes (BYOKEY)      |
| MCP usage analytics       | Basic   | Detailed         | Detailed + export |

---

## MCP Server Health Dashboard

### Platform Admin View

```python
@router.get("/api/v1/platform/mcp-servers/health")
async def get_mcp_health_dashboard(
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """
    Real-time MCP server health dashboard.

    Returns health status, latency, error rates for all MCP servers
    across all tenants.
    """
    servers = await MCPServerModel.get_all()
    health_data = []

    for server in servers:
        # Aggregate circuit breaker state across all tenants
        breaker_states = await get_all_tenant_breaker_states(server.id)
        open_count = sum(1 for s in breaker_states if s == "open")

        # Recent latency from usage tracking
        latency = await get_mcp_latency_p95(server.id, window_minutes=15)

        # Error rate
        error_rate = await get_mcp_error_rate(server.id, window_minutes=15)

        health_data.append({
            "id": server.id,
            "display_name": server.display_name,
            "status": "healthy" if error_rate < 0.05 else "degraded" if error_rate < 0.2 else "unhealthy",
            "p95_latency_ms": latency,
            "error_rate": error_rate,
            "tenants_affected": open_count,
            "total_tenants": len(breaker_states),
        })

    return health_data
```

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
