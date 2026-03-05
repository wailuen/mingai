# 28. A2A Extensibility Security: BYOMCP Sandboxing and Marketplace Consent

> **Status**: Architecture Design
> **Date**: 2026-03-05
> **Priority**: P1 (BYOMCP Sandboxing) / P2 (Marketplace Consent Model)
> **Purpose**: Define the security architecture for tenant-built custom agents (BYOMCP) and the marketplace data residency consent model for external A2A agent integrations.
> **Builds on**: `04-multi-tenant/06-a2a-mcp-agentic.md`, `18-a2a-agent-architecture.md`

---

## 1. BYOMCP Sandboxing

### The Threat Model

Enterprise plan tenants can register custom MCP servers — their own data sources built into the A2A platform. This is a first-class extensibility feature. But custom tenant MCP servers introduce a threat that platform-built agents do not:

**Threat 1: Capability spoofing** — A tenant MCP server declares safe capabilities (e.g., "read-only HR data") but implements write operations. The platform has no runtime verification of declared vs. actual behavior.

**Threat 2: Data exfiltration** — A misconfigured or malicious tenant MCP server receives the orchestrator's task message (which contains the user's query and context) and forwards it to an external endpoint. The platform cannot control what happens inside a tenant container.

**Threat 3: Resource abuse** — A runaway tenant MCP server makes unlimited API calls to its backend data source, consumes excessive CPU/memory, or creates latency that degrades neighboring tenants.

**Threat 4: Cross-tenant data contamination** — If tenant MCP containers share network namespaces or infrastructure, a misconfigured MCP could attempt to access another tenant's data by guessing endpoint patterns.

### Sandboxing Architecture

```
Tenant BYOMCP Registration Flow:

Tenant Admin → registers custom MCP server URL + capability schema
    │
    ▼
Platform Registry → runs registration-time security checks:
    ├── (1) Capability declaration audit (LLM-based, same as guardrail audit)
    ├── (2) Domain allowlist check (container network egress)
    └── (3) Admin approval gate (platform admin must approve BYOMCP registrations)
    │
    ▼
Approved BYOMCP → deployed into isolated tenant agent container
    ├── Network: tenant-scoped namespace (cannot reach other tenants)
    ├── Rate limits: per-tenant, per-MCP
    └── Resource quotas: CPU/memory per agent container
```

### (1) Capability Declaration Audit

When a tenant registers a BYOMCP, they submit a capability declaration:

```json
{
  "mcp_id": "tenant-123-erp",
  "name": "Custom ERP Agent",
  "description": "Read-only access to internal ERP financial data",
  "capabilities": ["read"],
  "endpoints": [
    {
      "path": "/financials",
      "method": "GET",
      "description": "Get financial records"
    },
    {
      "path": "/employees",
      "method": "GET",
      "description": "Get employee headcount"
    }
  ],
  "egress_domains": ["erp-api.acme-corp.internal"]
}
```

The platform audits the declaration using an LLM check:

```python
BYOMCP_CAPABILITY_AUDIT_PROMPT = """
You are a security auditor reviewing a custom MCP server registration.

CLAIMED CAPABILITIES: {capabilities}
DECLARED ENDPOINTS: {endpoints}
EGRESS DOMAINS: {egress_domains}

Evaluate:
1. Does the endpoint list include any write operations (POST, PUT, DELETE, PATCH)
   that are not declared in the capabilities? (YES/NO + specific endpoint)
2. Do the egress domains include any public internet domains (not .internal)?
   (YES/NO + domain)
3. Does the description suggest data exfiltration risk? (YES/NO + reason)
4. Is the capability scope consistent with an enterprise read-only data agent?
   (YES/NO + concern)

Respond in JSON:
{{
    "passes": true | false,
    "findings": [{{"concern": "...", "severity": "critical|high|medium"}}]
}}
"""
```

Write operations are NOT prohibited — some legitimate custom agents need write access (e.g., create a task in an internal project system). But write capabilities must be **explicitly declared** in the registration, and write-capable BYOMCP registrations require enhanced platform admin review (see Admin Approval Gate).

### (2) Network Isolation per Tenant

Each tenant's A2A agent containers (including BYOMCP) run in a **tenant-scoped network namespace**:

```yaml
# Kubernetes NetworkPolicy for tenant BYOMCP containers
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: tenant-{tenant_id}-byomcp-isolation
  namespace: tenant-agents
spec:
  podSelector:
    matchLabels:
      tenant_id: "{tenant_id}"
      agent_type: "byomcp"
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Only allow traffic from this tenant's orchestrator
    - from:
        - podSelector:
            matchLabels:
              tenant_id: "{tenant_id}"
              component: "orchestrator"
  egress:
    # Allow DNS resolution (required for all outbound)
    - ports:
        - protocol: UDP
          port: 53
    # NOTE: Standard Kubernetes NetworkPolicy ipBlock cannot perform FQDN-based filtering.
    # It operates at the IP layer and does not resolve DNS names — a tenant declaring
    # "erp-api.acme-corp.internal" would need the IP at policy creation time, which may change.
    # Actual implementation uses Cilium CiliumNetworkPolicy with toFQDNs (see below).
```

This ensures a tenant's BYOMCP can only:

- Receive traffic from its own tenant's orchestrator
- Send traffic to the FQDNs declared at registration time (Cilium-tracked, DNS-aware)

**Cilium FQDN-based egress policy** (replaces static ipBlock — which cannot resolve DNS names):

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: tenant-{tenant_id}-byomcp-egress
  namespace: tenant-agents
spec:
  endpointSelector:
    matchLabels:
      tenant_id: "{tenant_id}"
      agent_type: "byomcp"
  egress:
    - toFQDNs:
        # Populated at registration from tenant's declared egress domains
        - matchPattern: "*.acme-corp.internal"
    - toPorts:
        - ports:
            - port: "443"
              protocol: TCP
  egressDeny:
    - toEntities:
        - world # Deny all non-allowlisted external traffic
```

If Cilium is not available, use an Envoy sidecar proxy with FQDN-allowlist as an alternative (Envoy resolves DNS and enforces allowlisting at L7).

**Cross-tenant isolation**: Even if a tenant BYOMCP attempts to reach another tenant's orchestrator or data, the network policy blocks it at the infrastructure layer.

### (4) Runtime Behavioral Monitoring

Registration-time controls are insufficient alone — a BYOMCP that passes registration could exhibit unexpected runtime behavior (DNS rebinding, anomalous traffic patterns, data exfiltration via allowed channels). Runtime monitoring adds a detection layer:

- **Egress traffic logging**: All DNS queries and outbound connection attempts from BYOMCP containers are logged to the security audit trail. Connections to domains not in the registered allowlist trigger an alert (should be blocked by Cilium, but logged independently as defense-in-depth).
- **Request rate anomaly**: Alert when a BYOMCP's outbound request rate deviates >3σ from the 7-day baseline. Rate spikes may indicate a triggered data exfiltration attempt.
- **Payload size anomaly**: Alert when outbound payload size is disproportionate to the inbound task message size (potential data amplification exfiltration).

This monitoring is passive (no blocking) but provides the signal needed to suspend a BYOMCP agent if anomalous behavior is detected by the platform security team.

### (5) Resource Quotas

Each BYOMCP container has enforced resource limits:

```python
BYOMCP_RESOURCE_LIMITS = {
    "professional": {
        "cpu":              "0.5 cores",
        "memory":           "512Mi",
        "max_concurrent_requests": 10,
        "rate_limit_rps":   50,      # Requests per second to the MCP server
        "timeout_ms":       30_000,  # Hard timeout per task
    },
    "enterprise": {
        "cpu":              "2 cores",
        "memory":           "2Gi",
        "max_concurrent_requests": 50,
        "rate_limit_rps":   200,
        "timeout_ms":       60_000,
    },
}
```

Rate limits are enforced by a sidecar proxy (Envoy) on the BYOMCP container, not by the MCP server itself (tenant-controlled code cannot self-limit).

### (4) Platform Admin Approval Gate

BYOMCP registrations require explicit platform admin approval before activation:

```
Platform Admin Notification:
"New BYOMCP registration from FinanceCo (Enterprise):
  MCP: Custom ERP Agent
  Capabilities: read + WRITE (flagged)
  Egress domains: erp-api.finco.internal
  Capability audit: ✓ Passed (write capability explicitly declared)

  [Approve]  [Request More Info]  [Reject]"
```

Write-capable registrations trigger mandatory human review. Read-only registrations that pass the automated audit can be auto-approved (configurable per platform).

### BYOMCP Registration UI (Tenant Admin)

```
[Custom Agents]  >  [Register New Agent]

Agent Name:        [Custom ERP Intelligence     ]
Description:       [Read-only access to internal ERP financial data]

Capabilities:      [✓] Read    [ ] Write    [ ] Delete

Endpoints (list what your MCP server exposes):
  Method  Path           Description
  [GET ▼] [/financials ] [Get quarterly financial records]    [+ Add]
  [GET ▼] [/employees  ] [Get headcount by department]        [Remove]

Egress Domains (where your MCP server makes external calls):
  [erp-api.acme-corp.internal                            ]    [+ Add]

[Submit for Review]   [Save Draft]
                         ↑
             Platform admin reviews within 24h.
             Write-capable agents: 48h review + enhanced check.
```

---

## 2. Marketplace Data Residency and Consent Model

### The Problem

When a user query is dispatched as an A2A Task to a marketplace agent (externally hosted, outside platform infrastructure), the task message leaves platform infrastructure. The task message contains:

- The user's query (may contain business-sensitive terms, deal names, internal project codes)
- Contextual metadata (tenant_id, user_id, conversation history excerpt)

A one-time blanket consent (tenant admin enables the agent once) is insufficient for enterprise environments:

- Users are unaware their queries are being sent to an external service
- GDPR Article 13 requires data subjects to know which third parties receive their data
- Financial services regulations (MiFID II, SOX) require audit trails of data flows to third parties

### Consent Architecture: Three Levels

```
Level 1 — Publisher Trust Verification (Platform admin, one-time)
Level 2 — Tenant Admin Consent Configuration (per agent, configurable policy)
Level 3 — End User Query Disclosure (per query, configurable)
```

### Level 1: Publisher Trust Verification

Before any marketplace agent is visible to any tenant, the platform verifies the publisher:

```
Platform Admin: Marketplace Agent Verification Checklist

Publisher: Reuters News Ltd
Agent URL: https://reuters-agent.reuters.com/a2a
AgentCard: /.well-known/agent.json ✓ verified

Verification steps:
  [✓] Domain ownership verified (DNS TXT record: mingai-verify=...)
  [✓] AgentCard capabilities match implementation (capability probe passed)
  [✓] Privacy policy URL present and reachable
  [✓] Data Processing Agreement (DPA) submitted to platform legal team
  [✓] Capability probe: no undeclared write operations detected
      (Method: send A2A test Tasks with read-only intent; verify response schema matches declared output schema;
       check response does not include mutation confirmation fields like `created_id`, `updated_at`, `rows_affected`)
  [✓] Data egress test: query content not stored beyond request TTL
      (Method: send A2A test Task with a unique canary string; poll publisher's public data channels 24h later
       to verify canary does not appear; or require publisher to present third-party security audit certification)

Verification status: ✓ Approved
Data residency: EU and US (tenant selects at enable time)
Plan tier: Enterprise only

[Publish to Marketplace]
```

A DPA between the platform and the marketplace agent publisher is a mandatory prerequisite. This creates legal standing for data flows.

### Level 2: Tenant Admin Consent Configuration

When a tenant admin enables a marketplace agent, they configure the data sharing policy for their organization:

```
[Marketplace Agent: Reuters News]
Status: Enabling...

Data Sharing Notice:
  When users query this agent, their query content will be sent to:
  Reuters News Ltd (reuters.com)
  Region: EU data center (Frankfurt)
  Data retention by Reuters: Not retained beyond the request (per DPA §3.2)

  Select your organization's policy for this agent:

  ○ Always allow — one-time disclosure to each user on first query; silent thereafter
                    (GDPR Article 13 requires informing data subjects at time of collection —
                     post-response indicator alone is insufficient; one-time notice satisfies this)
  ○ Notify users — show a brief banner when Reuters is used for a response
  ● Always prompt users — users confirm before each query is sent to Reuters
                           (Recommended for regulated industries)
  ○ Disable — this marketplace agent is not available to org users (no queries dispatched)

  [Save Policy]  [View DPA]  [Cancel]
```

The policy is stored in `tenant_agent_instances.marketplace_consent_policy`.

### Level 3: End User Query Disclosure

Based on the tenant's configured policy, the user sees different behaviors:

**"Always allow" policy** — One-time per-user GDPR disclosure on first query involving this agent, then silent. Each user sees the notice once:

```
[First use — shown once per user per external agent, never repeated]
Reuters News is used to answer questions in this category. Reuters processes
your queries in the EU and does not retain them beyond the request. [Got it]
```

After acknowledgement, subsequent responses include only a compact source indicator:

```
[Reuters] Based on Reuters news data (external service) as of 2026-03-05
```

**"Notify users" policy** — Response includes a disclosure:

```
ℹ This response includes content retrieved from Reuters News (external service).
  Your query was sent to Reuters for processing.
```

**"Always prompt users" policy** — Before dispatching to Reuters:

```
┌─────────────────────────────────────────────────────────┐
│  External Data Source Notice                            │
│                                                         │
│  To answer this question, your query will be sent to:   │
│  Reuters News Ltd (external service, EU region)         │
│                                                         │
│  Your query: "Latest news on Apple's AI strategy"       │
│                                                         │
│  [Send to Reuters]          [Answer without Reuters]    │
└─────────────────────────────────────────────────────────┘
```

If the user selects "Answer without Reuters", the orchestrator replans the DAG excluding marketplace agents and proceeds with platform-only sources.

### Data Egress Audit Log

Every query dispatch to a marketplace agent is logged to the compliance audit trail:

```python
{
    "event_type": "marketplace_agent_dispatch",
    "tenant_id": "tenant-uuid",
    "user_id": "user-uuid",
    "agent_id": "reuters-agent",
    "publisher": "Reuters News Ltd",
    "task_id": "task-uuid",
    "dag_run_id": "run-uuid",
    "query_sent": false,       # True only if tenant has audit content logging enabled
    "consent_policy": "always_prompt",
    "user_consented": true,
    "data_region": "eu-west",
    "timestamp": "2026-03-05T14:32:00Z"
}
```

`query_sent: false` means the actual query content is NOT stored in the audit log by default (privacy-preserving). Tenants with compliance logging enabled can opt in to storing query content in their own audit store.

### GDPR / Data Sovereignty Controls

```python
class MarketplaceAgentFilter:
    """
    Applied at plan time before DAG execution.
    Filters out marketplace agents that don't meet the tenant's data sovereignty requirements.
    """

    def filter_available_agents(
        self,
        agents: list[AgentRegistryEntry],
        tenant: Tenant,
    ) -> list[AgentRegistryEntry]:
        return [
            agent for agent in agents
            if self._passes_sovereignty_check(agent, tenant)
        ]

    def _passes_sovereignty_check(
        self,
        agent: AgentRegistryEntry,
        tenant: Tenant,
    ) -> bool:
        # Platform-built agents always pass
        if agent.tier == "platform":
            return True

        # Marketplace agents: check data residency
        if tenant.data_residency_region == "eu":
            # EU tenants can only use marketplace agents with EU data centers
            if "eu" not in agent.data_regions:
                return False

        # Check if tenant has explicitly blocked this publisher
        if agent.publisher_id in tenant.blocked_publishers:
            return False

        return True
```

### Plan Tier Feature Matrix for Marketplace

| Feature                      | Starter | Professional | Enterprise |
| ---------------------------- | ------- | ------------ | ---------- |
| Platform-built agents        | Yes     | Yes          | Yes        |
| Marketplace agents           | No      | No           | Yes        |
| Consent policy configuration | N/A     | N/A          | Yes        |
| Per-query user prompt        | N/A     | N/A          | Yes        |
| Data egress audit log        | N/A     | N/A          | Yes        |
| GDPR data residency filter   | N/A     | N/A          | Yes        |
| Custom publisher blocklist   | N/A     | N/A          | Yes        |
| DPA review access            | N/A     | N/A          | Yes        |

Marketplace access is Enterprise-only by design. The data governance requirements make it unsuitable for lower tiers where tenant admins may not have compliance infrastructure.

---

## 3. Product & USP Analysis

### BYOMCP: Extensibility as Enterprise Lock-In (Positive)

Custom agent registration turns the platform into a **proprietary enterprise hub**:

- Enterprise tenants invest engineering effort to build custom MCP servers
- Those custom agents are wired into the platform's orchestration and billing
- Migration to a competitor means losing the custom agent investment
- The 5% custom layer creates integration-depth lock-in that pure SaaS competitors cannot offer

**AAA Framework:**

- **Automate**: BYOMCP lets tenants automate access to any proprietary internal data source
- **Amplify**: One custom agent built by the enterprise engineering team serves all eligible users in the org

### Marketplace: The Open Platform Moat

The marketplace is the long-term network effect moat. The consent model is what makes it enterprise-viable:

- Without consent architecture: Regulated enterprise buyers (finance, healthcare) cannot use marketplace agents → marketplace is hobbled for the highest-value segment
- With consent architecture: Every enterprise tier tenant can safely access marketplace agents → marketplace scales to the segment that pays the most

**Network Effects: Connection**
The marketplace consent model enables the **Connection** behavior: enterprise data publishers (Reuters, Refinitiv, domain-specific data vendors) connect to the platform knowing that tenant data flows are governed, audited, and legally covered by DPAs. Publishers prefer platforms with clear data governance over uncontrolled API access.

### 80/15/5 Alignment

| Layer | Who Owns It            | What                                                                                 |
| ----- | ---------------------- | ------------------------------------------------------------------------------------ |
| 80%   | Platform               | Sandboxing infrastructure, network policies, capability audit, consent policy engine |
| 15%   | Tenant Admin           | Consent policy selection, BYOMCP declaration, egress domain configuration            |
| 5%    | Enterprise Engineering | Custom MCP server implementation                                                     |

The security architecture makes the 5% custom layer safe to offer as a product feature — without it, BYOMCP would be too risky to enable.

---

**Document Version**: 1.0
**Last Updated**: 2026-03-05
