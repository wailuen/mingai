# 34. RAG Quality and Feedback Pipeline Architecture

> **Status**: Architecture Design
> **Date**: 2026-03-05
> **Purpose**: Technical architecture for collecting, processing, and surfacing RAG response quality signals — from the moment a user rates a response to the actionable dashboard the tenant admin sees.
> **Depends on**: `04-rag-pipeline.md`, `29-issue-reporting-architecture.md`, `31-tenant-admin-capability-spec.md`

---

## 1. Quality Signal Taxonomy

Three signal types are collected. Together they give a complete picture of AI quality.

| Signal Type           | Source                          | Granularity  | Reliability                 |
| --------------------- | ------------------------------- | ------------ | --------------------------- |
| **Explicit feedback** | User thumbs up/down             | Per response | High (user intent clear)    |
| **Confidence score**  | RAG pipeline internal           | Per response | Medium (proxy for coverage) |
| **Implicit signal**   | Behavioral (follow-up, abandon) | Per session  | Low (noisy, inferred)       |

### 1.1 Explicit Feedback: Thumbs Up / Down

Collected inline after each AI response. Users see the thumbs UI only after the response completes streaming.

- **Thumbs up**: User is satisfied with the response
- **Thumbs down**: User is dissatisfied. Optional short-form reason:
  - "Incorrect information"
  - "Outdated information"
  - "Didn't answer my question"
  - "Other" (free text, max 200 chars)

**What is NOT collected**: The user's query and the response content are associated with the feedback event for admin review purposes only — never surfaced to the platform admin or other tenants.

### 1.2 Confidence Score

> **CRITICAL ARCHITECTURAL CAVEAT (R21)**: The confidence score measures **retrieval quality**, not **answer quality**. A high score means the system found relevant documents — it does NOT mean the LLM produced a correct or faithful answer. Scores should be labeled in the UI and dashboard as "retrieval confidence" to avoid misrepresenting what the system actually knows. Phase 4 should add LLM-as-judge answer validation as a separate signal alongside this retrieval proxy.

Every RAG response includes an internally computed retrieval confidence score (0.0 – 1.0):

```python
def compute_confidence(
    retrieved_chunks: list[RetrievedChunk],
    synthesis_tokens_used: int,
    max_context_tokens: int
) -> float:
    """
    Retrieval confidence proxy — a weighted combination of retrieval signals.
    IMPORTANT: This measures retrieval quality (did we find relevant documents?),
    NOT answer quality (did the LLM produce a correct answer?).
    For answer quality validation, use LLM-as-judge (Phase 4 addition).
    - Top chunk relevance score (semantic similarity from Azure AI Search)
    - Average relevance across top-5 chunks
    - Source diversity (single source vs multiple corroborating sources)
    - Context coverage (tokens used vs available context window)
    """
    if not retrieved_chunks:
        return 0.0

    top_relevance = retrieved_chunks[0].score  # e.g., 0.91 from Azure AI Search
    avg_relevance = sum(c.score for c in retrieved_chunks[:5]) / min(5, len(retrieved_chunks))
    source_count = len(set(c.source_file for c in retrieved_chunks[:5]))
    coverage_ratio = min(synthesis_tokens_used / max_context_tokens, 1.0)

    # Weighted formula
    score = (
        0.50 * top_relevance +
        0.25 * avg_relevance +
        0.15 * min(source_count / 3, 1.0) +   # Normalise: 3+ sources = full score
        0.10 * coverage_ratio
    )
    return round(min(score, 1.0), 3)
```

The retrieval confidence score is:

- Stored with every response in Cosmos DB
- Shown to the user as a subtle indicator ("Sources: 3 found — high retrieval confidence")
  (not "high confidence" — label must reflect what is actually being measured)
- Aggregated per-agent and per-KB for the quality dashboard (as "avg retrieval confidence")
- Used to trigger "I'm not sure" guardrail responses when below agent-configured threshold
- **Not a substitute for answer correctness** — satisfaction (thumbs up/down) remains the primary quality signal

**Phase 4 addition — LLM-as-judge answer validation**:
After synthesis, pass a sample of responses through a separate fast LLM call:
`f"Given this question: {query}\nAnd this retrieved context: {context[:500]}\nIs the following answer faithful and correct? Answer: {response[:300]}\nFaithfulness score (0.0-1.0):"`.
Store as `answer_faithfulness_score` alongside `confidence_score`. Decouple the two signals in dashboards to prevent retrieval metrics from masking answer quality issues.

### 1.3 Implicit Signals

Collected passively, used for trend analysis only (not shown to tenant admin directly):

| Signal               | Collection Method                                               | Inference                             |
| -------------------- | --------------------------------------------------------------- | ------------------------------------- |
| Session abandon      | User closes chat without rating after a low-confidence response | Possible dissatisfaction              |
| Follow-up rephrasing | User asks same question differently within 60 seconds           | Likely unsatisfactory first response  |
| Conversation length  | Short conversation (1-2 exchanges) with no follow-up            | Either satisfied quickly or abandoned |
| Export / copy        | User copies response text to clipboard                          | Positive signal (response was useful) |

Implicit signals are stored as session events and aggregated weekly. They are NOT shown at response granularity — only as trend modifiers in the dashboard.

---

## 2. Data Collection Pipeline

### 2.1 Feedback Event Structure

```python
@dataclass
class FeedbackEvent:
    id: str                    # feedback_uuid
    tenant_id: str
    user_id: str               # anonymized in cross-tenant benchmarks
    conversation_id: str
    response_id: str           # links to the specific RAG response
    agent_instance_id: str     # which agent produced this response
    kb_index_ids: list[str]    # which KBs were queried (for per-KB aggregation)
    confidence_score: float    # from RAG pipeline
    feedback_type: str         # "thumbs_up" | "thumbs_down" | "no_rating"
    feedback_reason: str | None # only on thumbs_down
    feedback_text: str | None   # free text reason
    response_length_tokens: int
    latency_ms: int
    created_at: datetime
```

### 2.2 Write Path

```
User submits thumbs up/down
    │
    ▼
POST /api/v1/feedback
    Body: { response_id, feedback_type, feedback_reason?, feedback_text? }
    │
    ├─ Validate: response_id belongs to requesting user's tenant (RBAC check)
    ├─ Enrich: load response metadata (agent_id, kb_ids, confidence_score) from Cosmos DB
    ├─ Write FeedbackEvent to Cosmos DB (partition: tenant_{tenant_id}/feedback)
    └─ Push lightweight event to Redis Stream:
          XADD mingai:{tenant_id}:feedback:stream * response_id=... agent_id=... type=thumbs_up

Redis Stream Consumer (background worker, reads per-tenant streams)
    │
    ├─ Event-driven aggregation with 30-second coalescing buffer:
    │    On event received → start/reset 30-second coalesce timer for that tenant
    │    On timer expiry → flush buffered events → aggregate into rolling stats documents
    │    (Replaces naive 5-minute poll: eliminates ~400 idle Cosmos DB upserts/cycle
    │     when no feedback events occurred)
    └─ Aggregate into rolling stats documents (see §3)
```

**Non-blocking**: The feedback API returns 200 immediately after the Cosmos DB write. The Redis stream write and aggregation are fire-and-forget for the user request.

**Rate limiting**: Max 1 feedback event per response_id (idempotent). Second submission overwrites the first (user changed their mind from thumbs-up to thumbs-down).

### 2.3 Confidence Score Write Path

Confidence scores are written by the RAG pipeline itself, not by the feedback API:

```python
# In RAG synthesis stage (rag_pipeline.py)
response_record = {
    "id": response_id,
    "tenant_id": tenant_id,
    "user_id": user_id,
    "agent_instance_id": agent_id,
    "kb_index_ids": [chunk.index_id for chunk in retrieved_chunks],
    "query_text": query,           # stored for admin diagnostic review only
    "response_text": response,     # stored for admin diagnostic review only
    "confidence_score": confidence,
    "source_chunks": [
        {
            "index_id": c.index_id,
            "score": c.score,
            "source_file": c.source_file,
            "content_preview": c.content[:200]
        }
        for c in retrieved_chunks[:5]
    ],
    "feedback_type": "no_rating",  # default, updated by feedback API
    "created_at": utcnow()
}
await cosmos.upsert(response_record, partition=f"tenant_{tenant_id}")
```

---

## 3. Aggregation Architecture

Rolling stats documents are maintained per-agent and per-KB. They are updated by the background aggregation worker on every 5-minute batch cycle.

### 3.1 Per-Agent Stats Document

```json
{
  "id": "stats_agent_inst_a1b2c3d4e5f6",
  "type": "agent_stats",
  "tenant_id": "tenant-uuid",
  "agent_instance_id": "inst_a1b2c3d4e5f6",
  "agent_name": "Acme Procurement Assistant",
  "period_days": 30,
  "updated_at": "2026-03-05T14:00:00Z",
  "metrics": {
    "total_responses": 234,
    "rated_responses": 189, // responses with explicit feedback
    "rating_rate": 0.808, // 80.8% of responses got a rating
    "thumbs_up": 162,
    "thumbs_down": 27,
    "satisfaction_rate": 0.857, // thumbs_up / (thumbs_up + thumbs_down)
    "avg_confidence": 0.76,
    "low_confidence_count": 23, // responses with confidence < 0.65
    "low_confidence_rate": 0.098,
    "avg_latency_ms": 2340
  },
  "satisfaction_trend": [
    // Last 14 days, daily buckets
    { "date": "2026-02-20", "satisfaction_rate": 0.91, "responses": 18 },
    { "date": "2026-02-21", "satisfaction_rate": 0.88, "responses": 15 },
    // ...
    { "date": "2026-03-05", "satisfaction_rate": 0.63, "responses": 12 }
  ],
  "top_thumbs_down_reasons": [
    { "reason": "Outdated information", "count": 14 },
    { "reason": "Didn't answer my question", "count": 8 },
    { "reason": "Incorrect information", "count": 5 }
  ],
  "low_confidence_topics": [
    // Extracted by clustering low-confidence query embeddings
    {
      "topic": "preferred vendor list",
      "occurrences": 12,
      "avg_confidence": 0.41
    },
    { "topic": "approval thresholds", "occurrences": 7, "avg_confidence": 0.52 }
  ]
}
```

### 3.2 Per-KB Stats Document

```json
{
  "id": "stats_kb_idx_sp_abc123",
  "type": "kb_stats",
  "tenant_id": "tenant-uuid",
  "index_id": "idx_sp_abc123",
  "kb_name": "Procurement Policies",
  "period_days": 30,
  "updated_at": "2026-03-05T14:00:00Z",
  "metrics": {
    "times_queried": 189, // how often this KB contributed to a response
    "contributed_to_responses": 167, // responses where this KB returned chunks
    "coverage_rate": 0.884, // contributed / queried (how often KB had relevant content)
    "avg_chunk_score": 0.73, // avg relevance of top returned chunk
    "avg_satisfaction_when_contributing": 0.86, // satisfaction rate for responses that used this KB
    "coverage_gap_score": 0.42 // LOW = poor coverage (high miss rate for queries directed here)
  },
  "coverage_gaps": [
    // Topics frequently queried against this KB with low results
    {
      "topic": "preferred vendor list",
      "miss_count": 12,
      "last_hit": "2026-02-28"
    },
    { "topic": "international procurement", "miss_count": 8, "last_hit": null }
  ]
}
```

### 3.3 Coverage Gap Detection

A "coverage gap" is a topic that users repeatedly ask about where the KB returns low-confidence results. Detection algorithm:

```python
class CoverageGapDetector:
    """
    Triggered by the aggregation worker after each 30-second coalesce flush.
    Only runs when the flushed batch includes low-confidence responses
    (skips entirely if no low-confidence events in the batch — no idle computation).
    Groups low-confidence responses by query embedding similarity
    to identify recurring topic clusters with poor KB coverage.
    NOTE: Requires MIN_OCCURRENCES_FOR_GAP=3 similar queries before flagging.
    Small tenants (<100 responses/month) may never reach this threshold —
    surface "Not enough data to detect coverage gaps yet" in the dashboard
    rather than showing an empty gaps list.
    """
    LOW_CONFIDENCE_THRESHOLD = 0.65
    MIN_OCCURRENCES_FOR_GAP = 3     # At least 3 similar queries before flagging
    SIMILARITY_THRESHOLD = 0.88     # Two queries are "same topic" if cosine sim > 0.88
    WINDOW_DAYS = 14                # Look back 14 days

    async def detect_gaps(self, tenant_id: str, index_id: str) -> list[CoverageGap]:
        # 1. Fetch all low-confidence responses for this KB in the window
        low_conf_responses = await self.get_low_confidence_responses(
            tenant_id, index_id, self.WINDOW_DAYS
        )

        # 2. Cluster by query embedding similarity (approximate NN)
        clusters = self.cluster_by_embedding(
            [r.query_embedding for r in low_conf_responses],
            threshold=self.SIMILARITY_THRESHOLD
        )

        # 3. Surface clusters with >= MIN_OCCURRENCES
        gaps = []
        for cluster in clusters:
            if len(cluster.members) >= self.MIN_OCCURRENCES_FOR_GAP:
                representative = cluster.most_central_member
                gaps.append(CoverageGap(
                    topic=representative.query_text[:100],
                    occurrences=len(cluster.members),
                    avg_confidence=sum(m.confidence for m in cluster.members) / len(cluster.members),
                    last_occurrence=max(m.created_at for m in cluster.members),
                    suggested_action=self.suggest_action(cluster)
                ))
        return sorted(gaps, key=lambda g: g.occurrences, reverse=True)

    def suggest_action(self, cluster: QueryCluster) -> str:
        avg_conf = sum(m.confidence for m in cluster.members) / len(cluster.members)
        if avg_conf < 0.30:
            return "No documents found — consider adding documents covering this topic"
        elif avg_conf < 0.50:
            return "Poor coverage — check if relevant documents are indexed"
        else:
            return "Low relevance — consider adding glossary terms or updating document titles"
```

---

## 4. Admin Dashboard Data

The quality dashboard is read-only for the tenant admin. All data is pre-aggregated — no ad-hoc queries at dashboard load time.

### 4.1 Workspace Quality Summary

```
GET /api/v1/admin/analytics/quality/summary
  ?period=30d

Response:
  {
    "period_days": 30,
    "total_responses": 1450,
    "overall_satisfaction_rate": 0.83,
    "overall_satisfaction_delta": +0.03,    // vs previous 30 days
    "overall_avg_confidence": 0.79,
    "coverage_gap_count": 5,                // number of open gaps across all KBs
    "agents_with_alerts": ["inst_f9e8d7c6b5a4"],  // agents below alert threshold
    "benchmark": {
      "percentile": 72,                     // anonymized benchmark (see §5)
      "label": "Above average for your organization size"
    }
  }
```

### 4.2 Per-Agent Quality

```
GET /api/v1/admin/analytics/quality/agents
  ?period=30d&sort=satisfaction_rate&order=asc

Response: sorted list of agent stats objects (§3.1)
```

### 4.3 Per-KB Quality

```
GET /api/v1/admin/analytics/quality/kbs
  ?period=30d

Response: sorted list of KB stats objects (§3.2)
```

### 4.4 Individual Negative Feedback Review

```
GET /api/v1/admin/analytics/quality/feedback
  ?type=thumbs_down
  &agent_id={optional}
  &period=7d
  &page=1&page_size=20

Response:
  {
    "items": [
      {
        "feedback_id": "...",
        "created_at": "...",
        "agent_name": "Procurement Assistant",
        "feedback_reason": "Outdated information",
        "feedback_text": "The vendor list is from 2024",
        "confidence_score": 0.41,
        "query_preview": "Is Acme's preferred vendor for IT...",   // truncated
        "response_preview": "I don't have current information...", // truncated
        "source_chunks": [ ... ],  // which documents were cited
        "sync_context": {
          "kb_name": "Procurement Policies",
          "last_sync_at": "2026-01-15T00:00:00Z",   // 49 days ago!
          "sync_status": "active"
        }
      }
    ],
    "total": 27
  }
```

**Privacy constraint**: `query_preview` and `response_preview` are truncated at 200 characters. Full query and response text are shown only when admin explicitly expands a feedback item. User identity is not shown — admin sees the feedback reason and AI context, not who asked what.

---

## 5. Alerting

### 5.1 Alert Rules

Alerts are evaluated by a background job every 30 minutes against the rolling stats documents.

```python
class QualityAlertRules:
    """
    Tenant-configurable threshold defaults.
    Alerts write to: tenant_notifications collection in Cosmos DB
    Delivered via: in-app notification + email to tenant_admin
    """

    DEFAULT_RULES = [
        AlertRule(
            name="agent_satisfaction_drop",
            condition="agent.satisfaction_rate < 0.70 AND agent.rated_responses >= 10",
            severity="warning",
            message="Agent '{agent_name}' satisfaction rate dropped to {satisfaction_rate:.0%} "
                    "(last 7 days, {rated_responses} rated responses)",
            cooldown_hours=24    # Don't re-alert for same agent within 24h
        ),
        AlertRule(
            name="coverage_gap_detected",
            condition="coverage_gap.occurrences >= 5",
            severity="info",
            message="Coverage gap detected in '{kb_name}': '{topic}' queried {occurrences} times "
                    "with {avg_confidence:.0%} average confidence. Consider adding relevant documents.",
            cooldown_hours=72
        ),
        AlertRule(
            name="kb_stale_with_quality_drop",
            condition="kb.days_since_sync >= 7 AND kb.coverage_rate < 0.70",
            severity="warning",
            message="'{kb_name}' hasn't synced in {days_since_sync} days and coverage is low. "
                    "Documents may be outdated.",
            cooldown_hours=48
        ),
        AlertRule(
            name="no_feedback_collected",
            condition="agent.total_responses >= 50 AND agent.rating_rate < 0.10",
            severity="info",
            message="Agent '{agent_name}' has low feedback collection (only {rating_rate:.0%} "
                    "responses rated). Consider surfacing the feedback UI more prominently.",
            cooldown_hours=168   # Weekly
        )
    ]
```

### 5.2 Correlation: Sync Events → Quality Drop

A key architectural connection: when a sync completes (or fails), the system checks whether quality metrics changed before/after the sync:

```python
# Triggered by sync_complete event
async def correlate_sync_with_quality(
    index_id: str,
    sync_completed_at: datetime,
    tenant_id: str
):
    """
    After each sync, compute before/after satisfaction rates for agents
    that query this KB. Surface notable changes to the tenant admin.
    """
    before_window = (sync_completed_at - timedelta(days=7), sync_completed_at)
    after_window  = (sync_completed_at, sync_completed_at + timedelta(days=1))  # 24h after

    # Wait 24 hours (scheduled job) before evaluating 'after' metrics
    # ...

    for agent in await get_agents_using_kb(index_id, tenant_id):
        before_rate = await get_satisfaction_rate(agent.id, before_window)
        after_rate  = await get_satisfaction_rate(agent.id, after_window)
        delta = after_rate - before_rate

        if abs(delta) >= 0.10:  # 10% swing = notable
            if delta < 0:
                message = (
                    f"Agent '{agent.name}' satisfaction dropped {abs(delta):.0%} after "
                    f"the {kb_name} sync on {sync_completed_at.date()}. "
                    f"Check if the sync introduced incorrect or outdated documents."
                )
            else:
                message = (
                    f"Agent '{agent.name}' satisfaction improved {delta:.0%} after "
                    f"the {kb_name} sync — the new documents are helping."
                )
            await notify_tenant_admin(tenant_id, message, severity="info")
```

This is the architectural foundation for USP 3 (AI Quality Ownership): the connection between sync events and quality signals is only possible because one system owns both the sync pipeline and the quality collection pipeline.

---

## 6. Data Retention and Privacy

| Data                                     | Retention                 | Reason                                              |
| ---------------------------------------- | ------------------------- | --------------------------------------------------- |
| Individual FeedbackEvent records         | 90 days rolling           | Admin diagnostic review                             |
| Response records (query + response text) | 90 days rolling           | Admin can review negative feedback context          |
| Per-agent/per-KB stats documents         | 13 months                 | Year-over-year comparison for tenant admin          |
| Satisfaction trend (daily buckets)       | 13 months                 | Long-term trend visibility                          |
| Coverage gap events                      | Until resolved or 30 days | Admin action queue                                  |
| Implicit signals (behavioral)            | 30 days                   | Used only in aggregation; not individually surfaced |

**Tenant data isolation**: All records are partitioned by `tenant_id`. No cross-tenant query is ever executed. Platform admin cannot query individual tenant feedback records — they can only see aggregate, tenant-anonymized benchmarks.

**PII minimization**:

- `user_id` in feedback records is a platform-internal UUID, never an email
- User identity is not exposed in the admin dashboard (admin sees feedback reason + AI context, not who submitted)
- Benchmark comparisons anonymize tenant identity (platform sees average; tenants see percentile)

---

## 7. Anonymous Benchmark

The platform computes cross-tenant satisfaction percentiles to give tenant admins a quality reference point. This is one of the three gaps identified in `04-platform-model-aaa.md`:

```python
class BenchmarkService:
    """
    Runs weekly. Computes percentile ranks for each tenant.
    Tenant admins see: "Your satisfaction rate is in the 72nd percentile
    for organizations of your size and industry."
    Platform admin sees: aggregate distribution only.
    Neither party can identify any individual tenant's data.
    """

    async def compute_benchmark(self) -> None:
        # Collect anonymized satisfaction rates from all active tenants
        tenant_rates = await self.collect_anonymized_rates()
        # tenant_rates = [(satisfaction_rate, size_bucket, industry_bucket), ...]

        for tenant in active_tenants:
            peer_rates = [
                r.satisfaction_rate for r in tenant_rates
                if r.size_bucket == tenant.size_bucket
                # industry matching optional — only if 10+ tenants in same bucket
            ]
            if len(peer_rates) >= 10:
                percentile = compute_percentile(tenant.satisfaction_rate, peer_rates)
                label = self.percentile_label(percentile)
                await self.store_benchmark(tenant.id, percentile, label)

    def percentile_label(self, p: float) -> str:
        if p >= 0.90: return "Top 10% of similar organizations"
        if p >= 0.75: return "Above average for your organization size"
        if p >= 0.50: return "Average for your organization size"
        if p >= 0.25: return "Below average — quality improvement recommended"
        return "Significantly below average — review agent configuration and KB coverage"
```

**Minimum cohort requirement**: Benchmark is only shown when there are 10+ peer tenants in the same size bucket. Below that threshold, "Benchmark not yet available (requires more organizations of your size)".

---

## 8. Cosmos DB Schema Summary

| Collection          | Partition Key        | Documents                                                     |
| ------------------- | -------------------- | ------------------------------------------------------------- |
| `responses`         | `tenant_{tenant_id}` | RAG response records (with confidence score, query, response) |
| `feedback_events`   | `tenant_{tenant_id}` | One per user feedback submission                              |
| `agent_stats`       | `tenant_{tenant_id}` | One per active agent instance (rolling 30-day aggregation)    |
| `kb_stats`          | `tenant_{tenant_id}` | One per KB index (rolling 30-day aggregation)                 |
| `quality_alerts`    | `tenant_{tenant_id}` | Fired alerts (with sent_at, cooldown tracking)                |
| `benchmark_results` | `tenant_{tenant_id}` | Weekly benchmark percentile for this tenant                   |

---

## 9. Phase Delivery

| Phase                        | Quality Feedback Capabilities                                                                  |
| ---------------------------- | ---------------------------------------------------------------------------------------------- |
| **Phase 1 (Foundation)**     | Thumbs up/down UI; FeedbackEvent storage; per-agent satisfaction rate in admin dashboard       |
| **Phase 2 (Analytics)**      | Per-KB stats; satisfaction trend charts; basic alerting (agent satisfaction drop)              |
| **Phase 4 (Agentic)**        | Coverage gap detection; negative feedback review with source context; sync↔quality correlation |
| **Phase 5 (Cloud Agnostic)** | Cross-tenant anonymous benchmark; implicit signal collection                                   |
| **Phase 6 (GA)**             | Agent configuration impact analysis (before/after satisfaction on config change)               |

---

**Document Version**: 1.1
**Last Updated**: 2026-03-05
**Changelog**: v1.1 — R21: confidence score labeled as retrieval proxy (not answer quality); added Phase 4 LLM-as-judge recommendation. R22: CoverageGapDetector includes volume threshold guard ("not enough data" state for small tenants). R25: aggregation switched from 5-minute timer to event-driven with 30-second coalescing buffer.
