# 27. A2A Execution Hardening: Failure Policy, Fast-Path, and Observability

> **Status**: Architecture Design
> **Date**: 2026-03-05
> **Priority**: P1 (Partial Failure Policy, Fast-Path) / P2 (Distributed Tracing, Replay UI)
> **Purpose**: Define the DAG partial failure policy, single-agent planning fast-path optimization, distributed tracing design, and DAG replay/debug UI for production-grade A2A execution.
> **Builds on**: `04-multi-tenant/06-a2a-mcp-agentic.md`

---

## 1. DAG Partial Failure Policy

### Why a Defined Policy Is Required

When a multi-agent DAG executes and one agent fails, the orchestrator must decide:

- Does synthesis proceed with partial data, or does it block?
- Does a failed node cascade to dependent nodes?
- What does the user see?

Without a defined policy, the behavior is non-deterministic (depends on which agent failed and why). Enterprise users cannot trust a system that silently degrades — they need predictable, disclosed partial results.

### Failure Class Taxonomy

Agents fail for different reasons with different implications:

| Failure Class     | Examples                                | User Impact                           | Default Policy                                        |
| ----------------- | --------------------------------------- | ------------------------------------- | ----------------------------------------------------- |
| `auth_failure`    | Credential expired, permission denied   | Cannot retrieve data from this source | Block + surface gap                                   |
| `infra_failure`   | Agent container down, API timeout       | Transient; may recover                | Retry once, then soft-fail or hard-fail per domain    |
| `rate_limited`    | Bloomberg/CapIQ API rate limit hit      | Temporary; recoverable                | Queue + retry after Retry-After; inform user of delay |
| `data_not_found`  | Ticker not in Bloomberg, user not in AD | Expected for some queries             | Soft-fail with message                                |
| `guardrail_block` | Output filter blocked the response      | Policy decision                       | Block + explain limitation                            |

### Node Criticality Classification

Each node in a DAG is classified as **critical** or **supplementary** based on its role in answering the user's query:

```python
class NodeCriticality(Enum):
    CRITICAL     = "critical"     # Response is invalid without this node
    SUPPLEMENTARY = "supplementary"  # Response is valid but less rich without this node
```

The DAG planner assigns criticality at plan time. Rules:

| Agent              | Default Criticality | Override Condition                              |
| ------------------ | ------------------- | ----------------------------------------------- |
| Bloomberg          | CRITICAL            | When query is explicitly financial data         |
| CapIQ              | CRITICAL            | When query requests credit metrics or comps     |
| Oracle Fusion      | CRITICAL            | When query requests ERP data                    |
| iLevel / PitchBook | CRITICAL            | When query requests investment/deal data        |
| Perplexity         | SUPPLEMENTARY       | Background research; synthesis works without it |
| Azure AD           | SUPPLEMENTARY       | User context enrichment; not required           |
| Teamworks          | SUPPLEMENTARY       | Project context; not required                   |
| AlphaGeo           | SUPPLEMENTARY       | Location context; not required                  |

**Exception**: A `SUPPLEMENTARY` node that another node depends on is automatically promoted to `CRITICAL` for that DAG run (because failing it blocks its dependent nodes).

### Failure Propagation Rules

```python
class FailurePropagationPolicy:
    """
    Called by orchestrator when a node completes with non-success status.
    Determines whether to proceed, abort, or surface partial results.
    """

    MAX_RATE_LIMIT_WAIT_SECONDS = 60  # Beyond this, fail the node rather than queue indefinitely

    def evaluate(
        self,
        failed_node: DAGNode,
        failure_class: FailureClass,
        dag_state: DAGState,
    ) -> FailureDecision:

        # Rule 1: auth_failure on CRITICAL node → hard block, explain gap
        if (failure_class == FailureClass.AUTH_FAILURE
                and failed_node.criticality == NodeCriticality.CRITICAL):
            return FailureDecision(
                action=FailureAction.BLOCK_SYNTHESIS,
                user_message=(
                    f"{failed_node.agent_display_name} data could not be retrieved — "
                    f"credentials have expired. Please contact your administrator to "
                    f"reconfigure {failed_node.agent_display_name} access."
                ),
                cancel_dependent_nodes=True,
            )

        # Rule 2: auth_failure on SUPPLEMENTARY node → proceed with disclosure
        if (failure_class == FailureClass.AUTH_FAILURE
                and failed_node.criticality == NodeCriticality.SUPPLEMENTARY):
            return FailureDecision(
                action=FailureAction.PROCEED_WITH_PARTIAL,
                synthesis_disclosure=(
                    f"Note: {failed_node.agent_display_name} data was unavailable "
                    f"(credentials expired) and is not included in this response."
                ),
                cancel_dependent_nodes=True,
            )

        # Rule 3: infra_failure on CRITICAL node → retry once, then hard block
        if (failure_class == FailureClass.INFRA_FAILURE
                and failed_node.criticality == NodeCriticality.CRITICAL):
            if not failed_node.retry_attempted:
                return FailureDecision(action=FailureAction.RETRY_NODE)
            return FailureDecision(
                action=FailureAction.BLOCK_SYNTHESIS,
                user_message=(
                    f"{failed_node.agent_display_name} is temporarily unavailable. "
                    f"Please try again in a few minutes."
                ),
                cancel_dependent_nodes=True,
            )

        # Rule 4: infra_failure on SUPPLEMENTARY node → proceed with disclosure
        if (failure_class == FailureClass.INFRA_FAILURE
                and failed_node.criticality == NodeCriticality.SUPPLEMENTARY):
            if not failed_node.retry_attempted:
                return FailureDecision(action=FailureAction.RETRY_NODE)
            return FailureDecision(
                action=FailureAction.PROCEED_WITH_PARTIAL,
                synthesis_disclosure=(
                    f"Note: {failed_node.agent_display_name} data is temporarily "
                    f"unavailable and is not included in this response."
                ),
                cancel_dependent_nodes=True,
            )

        # Rule 5: rate_limited → queue with user notification, bounded by max wait
        if failure_class == FailureClass.RATE_LIMITED:
            retry_after = failed_node.last_retry_after or 30
            if retry_after > self.MAX_RATE_LIMIT_WAIT_SECONDS:
                # Rate limit wait exceeds threshold → treat as soft/hard fail per criticality
                return self.evaluate(
                    failed_node,
                    FailureClass.INFRA_FAILURE,  # Re-evaluate as infra failure
                    dag_state,
                )
            return FailureDecision(
                action=FailureAction.QUEUE_AND_RETRY,
                retry_after_seconds=retry_after,
                user_notification=(
                    f"Waiting for {failed_node.agent_display_name} — "
                    f"rate limit reached, retrying in {retry_after}s..."
                ),
            )

        # Rule 6: data_not_found → always soft-fail
        if failure_class == FailureClass.DATA_NOT_FOUND:
            return FailureDecision(
                action=FailureAction.PROCEED_WITH_PARTIAL,
                synthesis_disclosure=(
                    f"Note: {failed_node.agent_display_name} returned no data "
                    f"for this query."
                ),
                cancel_dependent_nodes=False,  # Downstream may still be valid
            )
```

### User-Facing Partial Result Communication

When synthesis proceeds with partial data, the response includes a structured disclosure block:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Based on: Bloomberg ✓  |  CapIQ ✓  |  Perplexity ⚠ unavailable
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Apple (AAPL) vs Microsoft (MSFT) comparison:

[Synthesized answer using Bloomberg and CapIQ data]

⚠ Note: Perplexity web search was temporarily unavailable.
  Recent news context is not included in this response.
  [Retry with all sources]
```

The "Retry with all sources" button re-dispatches the same DAG. This is the user-facing surface of the replay capability (see Section 4).

---

## 2. Planning LLM Fast-Path

### The Problem

Every user query, including trivially simple single-agent queries, currently routes through:

1. Planning LLM call (build DAG) — ~500–1,000ms
2. Schema validation + cycle detection — ~10ms
3. Agent dispatch — agent execution time

For simple queries like "What is Apple's P/E ratio?", the planning LLM adds overhead without value. The intent detection step (already in the pipeline) can identify these queries before they reach the planner.

### Fast-Path Criteria

A query qualifies for the fast-path when:

1. Intent detection identifies **exactly one** agent as the target (confidence ≥ 0.92)
2. No cross-agent dependency is implied in the query
3. No aggregation across multiple sources is required
4. The identified agent is healthy and credentialed

Examples:

- "What is Apple's P/E ratio?" → Bloomberg (single, no dependency)
- "Who is Sarah Chen's manager?" → Azure AD (single, no dependency)
- "What are Apple's open Teamworks projects?" → Teamworks (single, no dependency)

Counter-examples that do NOT qualify (require full DAG):

- "Compare Apple and Microsoft across financials and news" → Bloomberg + Perplexity
- "Get Apple's financials and check if our CEO holds shares" → Bloomberg + Azure AD
- Any query with "and", "also", "compare", "vs" → likely multi-agent

**Invariant: Fast-path skips the DAG planner only, never the output filter.** The guardrail output filter (Doc 25, Layer 2) executes on every agent response regardless of routing path. A fast-path Bloomberg response to "Should I buy Apple?" still passes through the `no_investment_advice` output filter before reaching the user. Fast-path and full-DAG path converge at the agent's SSE response, which flows through the same filter pipeline.

**Synthesis-skip optimization (future consideration)**: For single-agent fast-path responses where the agent's Artifact is already a well-formed, short natural-language answer (e.g., Perplexity returning a pre-formatted news summary), the synthesis LLM call adds minimal value — it reformats already-formatted text. A future optimization could allow agents to declare `artifact_type: "synthesis_ready"` in their AgentCard, signaling that the extraction pipeline can pass the Artifact directly to the user (with source attribution header prepended) instead of passing it through the synthesis LLM. **This optimization is NOT implemented in v1** because it requires a trust contract with each agent's output quality, and synthesis LLM also applies guardrail framing — bypassing it requires the output filter to be sufficient. Track as a v2 latency optimization once guardrail coverage is validated.

### Fast-Path Implementation

```python
class QueryRouter:
    """
    Routes queries to either fast-path (single-agent, skip planner)
    or full DAG planning path.
    """

    FAST_PATH_CONFIDENCE_THRESHOLD = 0.92

    async def route(
        self,
        query: str,
        tenant_id: str,
        user_id: str,
    ) -> RoutingDecision:
        intent = await self.intent_service.detect(query, tenant_id)

        if (len(intent.matched_agents) == 1
                and intent.top_agent_confidence >= self.FAST_PATH_CONFIDENCE_THRESHOLD
                and not intent.requires_aggregation
                and await self.registry.is_healthy(
                    intent.top_agent_id, tenant_id)):
            return RoutingDecision(
                path="fast",
                agent_id=intent.top_agent_id,
                skip_planner=True,
            )

        return RoutingDecision(
            path="dag",
            intent=intent,
            skip_planner=False,
        )
```

### Performance Impact

| Query Type                  | Without Fast-Path | With Fast-Path | Saving |
| --------------------------- | ----------------- | -------------- | ------ |
| Single-agent (P50 estimate) | 1,800ms total     | 1,050ms total  | ~42%   |
| Multi-agent DAG             | 2,500–8,000ms     | No change      | —      |

Single-agent queries likely represent 55–70% of query volume in early tenant usage. Fast-path directly improves the most common user experience.

### Threshold Calibration Methodology

`FAST_PATH_CONFIDENCE_THRESHOLD = 0.92` is not arbitrary — it must be validated and may need per-deployment tuning:

**Initial calibration process**:

1. Collect 500–1,000 representative queries from UAT or beta users
2. For each query, record the intent model's `top_agent_confidence` score
3. Run all queries through the full DAG planner (no fast-path)
4. Compare DAG planner output vs fast-path single-agent assignment for queries with confidence ≥ threshold
5. **False positive rate**: proportion of queries where fast-path would have chosen wrong agent (DAG planner selected different or multiple agents)
6. Target false positive rate: **≤2%** at the chosen threshold

**Expected result**: The intent model should assign confidence ≥0.92 only when the query is unambiguously single-agent (e.g., "Apple's P/E ratio" → Bloomberg is obvious). At 0.92, false positive rate is empirically low for financial query intent models. If your false positive rate exceeds 2% at 0.92, raise the threshold to 0.94–0.95.

**Production monitoring**: Log `fast_path_triggered` and `fast_path_result_quality` (user thumbs-up/down) in OTel traces. If fast-path queries have lower quality ratings than full-DAG queries, re-evaluate the threshold.

**Tenant-specific tuning**: Tenants with highly specialized query vocabularies (e.g., a tenant that only queries Oracle Fusion) may benefit from a lower threshold (0.88–0.90) because their query space is more predictable. Threshold is a platform constant in v1 — per-tenant tuning is a v2 feature.

---

## 3. Distributed Tracing (OpenTelemetry)

### Why Tracing Is Required

With parallel DAG execution, a slow response can be caused by:

- A slow external agent (Bloomberg API latency)
- A slow synthesis LLM call
- A slow extraction pass
- A context budget overflow causing a multi-pass synthesis
- A guardrail violation adding a retry round

Without trace correlation, operators cannot distinguish these cases. "The query took 8 seconds" is not actionable. "The query took 8 seconds because Bloomberg returned 50s p95 API latency on this request" is actionable.

### Trace Structure

```
TraceID: [top-level user request trace]
│
├── Span: intent_detection (50ms)
│
├── Span: query_routing (fast-path | dag) (5ms)
│
├── Span: dag_planning (0ms if fast-path; 600ms if full DAG) [planner LLM call]
│
├── Span: dag_execution
│   ├── Span: node_A:bloomberg (2,100ms)
│   │   ├── Span: agent_dispatch (HTTP POST to bloomberg-agent)
│   │   └── Span: sse_receive (streaming Artifact)
│   ├── Span: node_B:perplexity (1,400ms)  [parallel]
│   ├── Span: node_C:capiq (3,200ms)       [parallel — slowest, determines DAG completion]
│   └── Span: tool_call:azure_ad_mcp (80ms) [parallel]
│
├── Span: extraction_batch (180ms)
│   ├── Span: extract:bloomberg (65ms)
│   ├── Span: extract:perplexity (42ms)
│   └── Span: extract:capiq (73ms)
│
└── Span: synthesis (1,850ms) [synthesis LLM call, streaming]
```

### W3C Trace Context Propagation

The orchestrator injects W3C `traceparent` and `tracestate` headers into every A2A Task dispatch. Each agent container propagates these headers to its downstream MCP calls:

```http
POST https://bloomberg-agent.{tenant}.mingai.internal/tasks
Authorization: Bearer {jwt}
traceparent: 00-{trace_id}-{parent_span_id}-01
tracestate: mingai=dag_run_id={run_id},node_id={node_id}
Content-Type: application/json

{ ... task body ... }
```

The `tracestate` extension carries orchestrator-internal IDs so that agent-side spans can be correlated back to the specific DAG run and node.

### Agent-Side Instrumentation Requirement

Each A2A agent container MUST instrument its execution spans:

```python
from opentelemetry import trace

tracer = trace.get_tracer("mingai.bloomberg-agent")

async def handle_task(request: A2ATaskRequest) -> A2ATaskResponse:
    # Extract trace context from incoming request
    ctx = extract_trace_context(request)

    with tracer.start_as_current_span(
        "bloomberg_agent.handle_task",
        context=ctx,
        attributes={
            "agent.id": "bloomberg",
            "task.id": request.task_id,
            "tenant.id": request.metadata["tenant_id"],
        }
    ) as span:
        # MCP call to Bloomberg
        with tracer.start_as_current_span("bloomberg_mcp.query") as mcp_span:
            result = await bloomberg_mcp.query(request.message)
            mcp_span.set_attribute("bloomberg.api.latency_ms", result.latency_ms)
            mcp_span.set_attribute("bloomberg.tickers_returned", len(result.tickers))

        return build_artifact(result)
```

### Trace Export

All spans are exported to the platform's observability backend (OpenTelemetry collector → Jaeger / Grafana Tempo):

```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318

exporters:
  jaeger:
    endpoint: jaeger:14250
    tls:
      # Production: mTLS required. Trace data contains tenant_id, user_id, task_id.
      # insecure: true is dev-only. Production config:
      cert_file: /etc/otel/certs/client.crt
      key_file: /etc/otel/certs/client.key
      ca_file: /etc/otel/certs/ca.crt

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [jaeger]
```

### Platform Admin: Trace Search UI

```
[Platform Observability]  >  [A2A Trace Explorer]

Search: [dag_run_id: run-xyz789 ▼]  [tenant: FinanceCo ▼]  [date: today ▼]

Trace: run-xyz789  |  Duration: 5.8s  |  Tenant: FinanceCo  |  Status: completed

Waterfall:
 0ms   ████░░░░░░░░░░░░░░░░░░░░░░░░░░░  intent_detection (52ms)
 55ms  ████░░░░░░░░░░░░░░░░░░░░░░░░░░░  dag_planning (588ms)
643ms  ████████████████████░░░░░░░░░░░  node_A:bloomberg (2,108ms)  ← CRITICAL PATH
643ms  ██████████░░░░░░░░░░░░░░░░░░░░░  node_B:perplexity (1,402ms)
643ms  ████████████████████████████░░░  node_C:capiq (3,215ms)  ← SLOWEST NODE
643ms  ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  tool:azure_ad_mcp (82ms)
3858ms ████░░░░░░░░░░░░░░░░░░░░░░░░░░░  extraction_batch (183ms)
4041ms █████████████████░░░░░░░░░░░░░░  synthesis (1,849ms)

Total: 5,890ms  |  Critical path: CapIQ (3.2s)  |  Synthesis: 1.8s
```

---

## 4. DAG Replay and Debug UI

### Why Replay Is Needed

Enterprise tenants will encounter:

- Bad synthesis quality ("the answer cited the wrong P/E ratio")
- Partial failures ("Bloomberg was missing from the response")
- Unexpected guardrail blocks ("the agent refused to answer")

Without replay capability, tenant admins cannot diagnose these issues. They file a support ticket. The platform team has no visibility into which agent produced which content. This creates a support burden that scales with tenant count.

### Replay Architecture

```
DAG state is persisted to PostgreSQL for 30 days:

Table: dag_runs
  id, tenant_id, user_id, query, status, total_duration_ms, created_at

Table: dag_nodes
  id, dag_run_id, node_id, agent_id, task_id, status, artifact_json,
  error_class, retry_count, duration_ms, trace_span_id

Table: dag_synthesis
  id, dag_run_id, synthesis_input_json, synthesis_output, model, tokens_in, tokens_out
```

Artifacts and synthesis inputs are stored per-run, enabling full replay from stored state.

**Data compliance constraints on stored content**:

- `artifact_json` stores post-extraction `SynthesisContext` content, **not raw agent Artifacts**. For licensed financial data (Bloomberg, CapIQ), raw terminal-grade data is never persisted to the database — only the extracted, compressed synthesis context. Legal review required for retention periods at data provider contract time.
- `artifact_json` stores post-PII-filter content only. Oracle Fusion and Azure AD artifacts are PII-scrubbed before storage (both pre- and post-extraction passes from Doc 26 Section 4).
- `synthesis_input_json` stores the assembled extraction context sent to the synthesis LLM — same PII/licensing constraints apply.

**DAG run durability on orchestrator restart**: DAG runs are checkpointed at each node completion (intermediate node artifacts written to `dag_nodes` immediately on completion). On orchestrator restart, in-flight runs are detected via `status = 'in_progress'`. Completed nodes are not re-dispatched; incomplete nodes are either retried (if `retry_count < max_retry`) or failed with user notification. This ensures deployment interruptions result in partial failures (with user notification), never silent drops.

### Tenant Admin: DAG Debug Panel

```
[Conversation: #conv-12345]  >  [Message: #msg-89]  >  [DAG Run: run-xyz789]

[DAG Run Details]
Query: "Compare Apple vs Microsoft: financials, news, and analyst sentiment"
Status: ✓ Completed  |  Duration: 5.8s  |  Agents used: 3
---

[Bloomberg]  ✓ Completed (2.1s)
  Artifact: [Expand ▼]
    Apple (AAPL): Price $192.30, P/E 28.5, Market Cap $2.9T
    Microsoft (MSFT): Price $415.20, P/E 36.1, Market Cap $3.1T

[CapIQ]  ✓ Completed (3.2s)
  Artifact: [Expand ▼]
    Apple: BBB+, EV/EBITDA 22x, Net Margin 25.3%
    Microsoft: AAA, EV/EBITDA 28x, Net Margin 36.8%

[Perplexity]  ✓ Completed (1.4s)
  Artifact: [Expand ▼]
    Reuters (2026-03-03): Apple Q1 FY2026 earnings beat...
    WSJ (2026-03-02): Microsoft Azure growth accelerates...

[Synthesis]
  Model: GPT-5.2-chat  |  Tokens: 4,200 in / 890 out
  Input: [Expand ▼]  Output: [View Full Response]

[Actions]
  [Re-run this DAG]  [Export Artifacts as JSON]  [File Support Ticket]
```

**Re-run retrieves current data, not historical data**: Re-running dispatches the same query to agents at the current time, returning current Bloomberg/CapIQ data, not the data from the original run. This is intentional for testing fixes. For investigating a past answer, use the stored `artifact_json` (the original captured extraction context) — available via "View stored artifacts" mode which displays the original data without re-querying.

Two modes:

- **Re-run with current data**: dispatches live agents, saves as new DAG run for comparison
- **View stored artifacts** (default): displays `artifact_json` from original run, no agent dispatch

### DAG State Retention Policy

| Tenant Plan  | DAG State Retention | Artifact Storage                    |
| ------------ | ------------------- | ----------------------------------- |
| Starter      | 7 days              | Metadata only (no Artifact content) |
| Professional | 30 days             | Full Artifact content               |
| Enterprise   | 90 days             | Full Artifact content + exportable  |

---

## 5. Product & USP Analysis

### Partial Failure Policy: Trust Through Transparency

The policy rule that matters most to enterprise users: **never silently degrade**. When Bloomberg data is unavailable, the response says so. This builds user trust — they know the platform is honest about its data coverage, not papering over gaps.

**AAA Framework:**

- **Automate**: Failure policy executes automatically — no human decision required per failure
- **Augment**: Users see exactly which sources contributed to each answer
- **Amplify**: One defined policy applies to all agents across all tenants

### Fast-Path: P50 Latency as a Selling Point

55–70% of enterprise queries are single-agent. Fast-path makes the most common queries 40%+ faster. In user demos, this is the difference between a query that feels instant and one that feels like it's "thinking."

### Tracing: Enterprise Observability as a Requirement

For regulated enterprise customers, tracing is not optional — it is a procurement requirement. Healthcare and financial services buyers will ask: "Can you show us an audit trail of every data retrieval for a given query?" The trace explorer provides this.

### Replay UI: Self-Service Support

Every support ticket escalated by a tenant about "wrong answer quality" is $X in platform support cost. The replay UI converts this to self-service in 80% of cases. The tenant admin can see which agent provided which data, identify the gap, and reconfigure (e.g., update credentials or adjust topic scope) without platform team intervention.

### Network Effects: Collaboration

The DAG run visualization and artifact export enable **Collaboration** behavior: tenant admins can share DAG run exports with their data vendors (Bloomberg, CapIQ) when troubleshooting integration issues, and with their internal compliance teams for audit reviews.

---

**Document Version**: 1.0
**Last Updated**: 2026-03-05
