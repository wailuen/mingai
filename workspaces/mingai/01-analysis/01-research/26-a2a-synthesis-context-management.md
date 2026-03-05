# 26. A2A Synthesis Context Management

> **Status**: Architecture Design
> **Date**: 2026-03-05
> **Priority**: P0 — Blocks 3+ agent DAG queries from working reliably
> **Purpose**: Define the structured-extraction pipeline that converts raw A2A Artifacts into synthesis-ready context, preventing context window overflow in multi-agent DAG execution.
> **Builds on**: `04-multi-tenant/06-a2a-mcp-agentic.md` Open Question #9

---

## 1. The Problem: Raw Artifacts Blow the Synthesis Context Window

When a 5-agent DAG completes, the orchestrator collects 5 Artifacts and passes them to the synthesis LLM. The raw Artifacts can be very large:

| Agent         | Typical Raw Artifact Size | Contents                                              |
| ------------- | ------------------------- | ----------------------------------------------------- |
| Bloomberg     | 8,000–15,000 tokens       | Full financial statements, time series, earnings data |
| CapIQ         | 5,000–10,000 tokens       | Credit analysis, peer comps table, M&A history        |
| Oracle Fusion | 3,000–8,000 tokens        | ERP records, GL entries, headcount data               |
| Perplexity    | 2,000–4,000 tokens        | Search results with snippets, URLs, publication dates |
| Azure AD      | 500–1,000 tokens          | User directory entries, org chart path                |
| iLevel        | 4,000–8,000 tokens        | Portfolio company financials, fund metrics            |
| PitchBook     | 5,000–12,000 tokens       | Deal history, investor rounds, valuation multiples    |
| AlphaGeo      | 2,000–5,000 tokens        | Location analytics, demographic overlays              |
| Teamworks     | 1,000–2,000 tokens        | Project status, task assignments, milestones          |

**Worst case**: 5 agents × 10,000 tokens = 50,000 tokens of Artifact content before adding query, conversation history, and glossary context. This exceeds the effective synthesis window of all current LLM models at scale.

**The failure mode is silent**: The LLM either truncates context silently (loses critical Artifacts) or errors out entirely. Both are unacceptable in production.

---

## 2. Structured Extraction Pipeline

Before the synthesis LLM call, each Artifact passes through an **Extraction Service** that distills it to a synthesis-ready summary using a lightweight extraction schema.

```
Raw Artifact from Agent
    │
    ▼
ExtractionService.extract(artifact, query_context)
    │   ├── Apply per-agent extraction schema
    │   ├── Filter to query-relevant fields only
    │   └── Produce structured SynthesisContext object
    ▼
SynthesisContext (300–800 tokens per agent)
    │
    ▼
Synthesis LLM call (all SynthesisContexts as structured context)
    │
    ▼
Final response streamed to user
```

### Context Budget Calculation

```python
SYNTHESIS_CONTEXT_BUDGET = {
    # Available context = model's window - safety margin
    # Using GPT-5.2-chat: 128K window - 20K safety margin = 108K available

    "max_total_context_tokens": 108_000,

    # Fixed allocations:
    "system_prompt_tokens":    2_000,  # Agent identity + guardrails
    "query_tokens":            1_000,  # User query + conversation context
    "glossary_tokens":           500,  # Matched glossary terms
    "response_headroom":       8_000,  # Reserved for synthesis output

    # Practical extraction output sizes (from per-agent schemas):
    # Bloomberg: ~1,500 tokens, CapIQ: ~1,500 tokens, Perplexity: ~1,200 tokens,
    # Azure AD: ~400 tokens, Oracle: ~1,000 tokens, others: ~800-1,200 tokens
    # 5-agent DAG: ~6,600 tokens extracted → well within budget
    # 10-agent DAG: ~11,000 tokens extracted → still within budget

    # Hard per-agent ceiling (pathological cases: agents returning anomalously large data):
    "max_tokens_per_agent":    4_000,  # Hard ceiling; schema targets are well below this

    # Safety margin rationale: ~8K tokens covers tokenizer estimation error (±5%)
    # and response streaming headroom. Not a "context degradation" buffer.
}
```

With these budgets, even a 10-agent DAG fits comfortably within the synthesis window for current models. The extraction schemas below enforce the per-agent cap.

---

## 3. Per-Agent Extraction Schemas

Each agent has a defined extraction schema: what fields to extract, how to prioritize relevance, and what the token target is.

### Bloomberg Extraction Schema

```python
BLOOMBERG_EXTRACTION_SCHEMA = ExtractionSchema(
    agent_id="bloomberg",
    target_tokens=1_500,
    fields=[
        ExtractionField("ticker_summary", priority="required",
            description="Symbol, company name, exchange"),
        ExtractionField("price_metrics", priority="required",
            description="Current price, market cap, 52-week range"),
        ExtractionField("valuation_metrics", priority="required",
            description="P/E, P/B, EV/EBITDA, dividend yield"),
        ExtractionField("revenue_ttm", priority="required",
            description="TTM revenue and YoY growth"),
        ExtractionField("earnings_summary", priority="query_dependent",
            description="Latest earnings, EPS, beat/miss vs consensus",
            include_if_query_contains=["earnings", "EPS", "results"]),
        ExtractionField("analyst_consensus", priority="query_dependent",
            description="Buy/hold/sell consensus, price target range",
            include_if_query_contains=["analyst", "target", "consensus"]),
        ExtractionField("time_series", priority="omit",
            description="Skip raw time series data in extraction"),
    ],
    source_attribution="Bloomberg Data License",
    format="structured_text",  # Not JSON — reduces token overhead
)
```

### CapIQ Extraction Schema

```python
CAPIQ_EXTRACTION_SCHEMA = ExtractionSchema(
    agent_id="capiq",
    target_tokens=1_500,
    fields=[
        ExtractionField("company_profile", priority="required",
            description="Company, sector, sub-sector, HQ"),
        ExtractionField("credit_metrics", priority="required",
            description="Credit rating, debt/equity, interest coverage"),
        ExtractionField("peer_comps", priority="required",
            description="3–5 closest peers: revenue, margin, EV/EBITDA"),
        ExtractionField("ma_history", priority="query_dependent",
            description="Recent M&A activity (buyer/target/value/year)",
            include_if_query_contains=["M&A", "acquisition", "deal", "merger"]),
        ExtractionField("raw_financials_table", priority="omit",
            description="Skip raw financial table data"),
    ],
    source_attribution="S&P Capital IQ",
    format="structured_text",
)
```

### Oracle Fusion Extraction Schema

```python
ORACLE_FUSION_EXTRACTION_SCHEMA = ExtractionSchema(
    agent_id="oracle-fusion",
    target_tokens=1_000,
    pii_filter=True,  # Strip any PII before synthesis (belt-and-suspenders on top of guardrails)
    fields=[
        ExtractionField("record_summary", priority="required",
            description="Entity type, record ID (not PII), status"),
        ExtractionField("key_metrics", priority="required",
            description="The 3–5 most query-relevant numeric fields"),
        ExtractionField("approval_chain", priority="query_dependent",
            description="Approval status, approver names (anonymized if PII setting)",
            include_if_query_contains=["approval", "status", "pending"]),
        ExtractionField("raw_gl_entries", priority="omit",
            description="Never include raw GL entries in synthesis context"),
    ],
    source_attribution="Oracle Fusion",
    format="structured_text",
)
```

### Perplexity Extraction Schema

```python
PERPLEXITY_EXTRACTION_SCHEMA = ExtractionSchema(
    agent_id="perplexity",
    target_tokens=1_200,
    fields=[
        ExtractionField("top_findings", priority="required",
            description="3–5 most relevant facts from search results"),
        ExtractionField("source_list", priority="required",
            description="Source name + URL for each finding (attribution)"),
        ExtractionField("publication_dates", priority="required",
            description="Date of each source (recency signal)"),
        ExtractionField("full_snippets", priority="omit",
            description="Skip full search result snippets"),
    ],
    source_attribution="Perplexity AI (web search)",
    format="structured_text",
)
```

### Azure AD Extraction Schema

```python
AZURE_AD_EXTRACTION_SCHEMA = ExtractionSchema(
    agent_id="azure-ad",
    target_tokens=400,
    pii_filter=True,
    fields=[
        ExtractionField("user_summary", priority="required",
            description="Display name, job title, department, manager"),
        ExtractionField("org_path", priority="query_dependent",
            description="Reporting chain from user to VP/C-level",
            include_if_query_contains=["reports to", "manager", "org", "hierarchy"]),
        ExtractionField("group_memberships", priority="query_dependent",
            description="Relevant security/distribution groups",
            include_if_query_contains=["access", "group", "team", "permission"]),
    ],
    source_attribution="Azure Active Directory",
    format="structured_text",
)
```

### iLevel Extraction Schema

```python
ILEVEL_EXTRACTION_SCHEMA = ExtractionSchema(
    agent_id="ilevel",
    target_tokens=1_200,
    fields=[
        ExtractionField("fund_summary", priority="required",
            description="Fund name, vintage year, strategy (buyout/growth/venture), AUM"),
        ExtractionField("portfolio_company_summary", priority="required",
            description="Company name, sector, investment date, cost basis, current NAV"),
        ExtractionField("performance_metrics", priority="required",
            description="IRR, TVPI, MOIC, DPI — gross and net where available"),
        ExtractionField("valuation_metrics", priority="query_dependent",
            description="Current valuation methodology, comparable multiples, EV/EBITDA",
            include_if_query_contains=["valuation", "fair value", "marks", "write-up", "write-down"]),
        ExtractionField("distribution_schedule", priority="query_dependent",
            description="Expected distributions, capital call schedule, unfunded commitment",
            include_if_query_contains=["distribution", "capital call", "unfunded", "liquidity"]),
        ExtractionField("raw_transaction_history", priority="omit",
            description="Skip raw transaction log and full LP stack"),
    ],
    source_attribution="iLevel Portfolio Intelligence",
    format="structured_text",
)
```

### PitchBook Extraction Schema

```python
PITCHBOOK_EXTRACTION_SCHEMA = ExtractionSchema(
    agent_id="pitchbook",
    target_tokens=1_500,
    fields=[
        ExtractionField("company_profile", priority="required",
            description="Company name, founded, HQ, sector/industry, employee count, description"),
        ExtractionField("funding_summary", priority="required",
            description="Total raised, last round type and amount, lead investors, post-money valuation"),
        ExtractionField("valuation_multiples", priority="required",
            description="Revenue multiple, EV/EBITDA, price/book — latest and series-over-series trend"),
        ExtractionField("investor_list", priority="query_dependent",
            description="Top 5 investors by ownership percentage, board seats",
            include_if_query_contains=["investor", "shareholder", "cap table", "ownership", "board"]),
        ExtractionField("ma_activity", priority="query_dependent",
            description="Recent M&A: buyer, target, deal value, close date",
            include_if_query_contains=["M&A", "acquisition", "merger", "deal", "exit"]),
        ExtractionField("comparable_transactions", priority="query_dependent",
            description="3–5 comparable transactions in same sector: revenue multiple, deal size",
            include_if_query_contains=["comps", "comparable", "benchmark", "precedent"]),
        ExtractionField("raw_deal_table", priority="omit",
            description="Skip full cap table and raw deal history"),
    ],
    source_attribution="PitchBook",
    format="structured_text",
)
```

### AlphaGeo Extraction Schema

```python
ALPHAGEO_EXTRACTION_SCHEMA = ExtractionSchema(
    agent_id="alphageo",
    target_tokens=800,
    fields=[
        ExtractionField("location_summary", priority="required",
            description="Location name, coordinates, administrative boundary (city/state/country)"),
        ExtractionField("key_demographic_signals", priority="required",
            description="Top 3–5 demographic metrics most relevant to query: income, age distribution, population density"),
        ExtractionField("competitive_density", priority="query_dependent",
            description="Count and proximity of competitor locations within defined radius",
            include_if_query_contains=["competition", "competitor", "density", "nearby", "proximity"]),
        ExtractionField("trade_area_metrics", priority="query_dependent",
            description="Trade area size, daytime vs. nighttime population, foot traffic index",
            include_if_query_contains=["trade area", "foot traffic", "catchment", "retail", "site"]),
        ExtractionField("raw_polygon_data", priority="omit",
            description="Skip raw GeoJSON polygon data and full demographic tables"),
    ],
    source_attribution="AlphaGeo",
    format="structured_text",
)
```

### Teamworks Extraction Schema

```python
TEAMWORKS_EXTRACTION_SCHEMA = ExtractionSchema(
    agent_id="teamworks",
    target_tokens=600,
    fields=[
        ExtractionField("project_summary", priority="required",
            description="Project name, status (on track / at risk / delayed / completed), owner, due date"),
        ExtractionField("milestone_status", priority="required",
            description="Next 3 upcoming milestones: name, due date, completion percentage"),
        ExtractionField("open_tasks_summary", priority="query_dependent",
            description="Count of open/overdue tasks by assignee; top 3 overdue tasks",
            include_if_query_contains=["tasks", "overdue", "blocking", "open", "action items"]),
        ExtractionField("team_assignments", priority="query_dependent",
            description="Team member names, roles, current task assignments",
            include_if_query_contains=["team", "assigned", "who", "responsibility", "owner"]),
        ExtractionField("raw_task_list", priority="omit",
            description="Skip full task list and complete comment history"),
    ],
    source_attribution="Teamworks",
    format="structured_text",
)
```

---

## 4. ExtractionService Implementation

```python
class ExtractionService:
    """
    Converts raw A2A Artifacts to synthesis-ready SynthesisContext objects.
    Uses lightweight LLM call (intent/planning tier model — NOT synthesis tier)
    to perform intelligent extraction based on query context.
    """

    EXTRACTION_SCHEMAS: dict[str, ExtractionSchema] = {
        "bloomberg":    BLOOMBERG_EXTRACTION_SCHEMA,
        "capiq":        CAPIQ_EXTRACTION_SCHEMA,
        "oracle-fusion": ORACLE_FUSION_EXTRACTION_SCHEMA,
        "perplexity":   PERPLEXITY_EXTRACTION_SCHEMA,
        "azure-ad":     AZURE_AD_EXTRACTION_SCHEMA,
        "ilevel":       ILEVEL_EXTRACTION_SCHEMA,
        "pitchbook":    PITCHBOOK_EXTRACTION_SCHEMA,
        "alphageo":     ALPHAGEO_EXTRACTION_SCHEMA,
        "teamworks":    TEAMWORKS_EXTRACTION_SCHEMA,
    }

    async def extract_batch(
        self,
        artifacts: list[A2AArtifact],
        original_query: str,
        tenant_id: str,
    ) -> list[SynthesisContext]:
        """
        Extract all artifacts in parallel before synthesis call.
        Each extraction uses the intent-tier LLM (cost-efficient).
        """
        tasks = [
            self.extract_single(artifact, original_query, tenant_id)
            for artifact in artifacts
        ]
        return await asyncio.gather(*tasks)

    async def extract_single(
        self,
        artifact: A2AArtifact,
        original_query: str,
        tenant_id: str,
    ) -> SynthesisContext:
        schema = self.EXTRACTION_SCHEMAS[artifact.agent_id]

        # Skip extraction for small artifacts (under threshold)
        raw_tokens = count_tokens(artifact.content)
        if raw_tokens <= schema.target_tokens * 1.2:
            return SynthesisContext(
                agent_id=artifact.agent_id,
                content=artifact.content,
                source_attribution=schema.source_attribution,
                token_count=raw_tokens,
                extracted=False,  # Passed through without extraction
            )

        # Apply PII filter before any LLM processing
        content = artifact.content
        if schema.pii_filter:
            content = PIIFilter.scrub(content)

        # Determine which query-dependent fields to include
        # IMPORTANT: use intent_service output (normalized semantics), NOT raw query string.
        # Raw query substring matching allows users to force expensive field inclusion
        # by embedding trigger keywords irrelevantly ("ignore M&A history, just the weather").
        # The intent object has already normalized query semantics.
        intent_topics = await self.intent_service.get_topics(original_query)  # e.g., ["M&A", "earnings"]
        active_fields = [
            f for f in schema.fields
            if f.priority == "required"
            or (f.priority == "query_dependent"
                and any(kw.lower() in intent_topics
                        for kw in f.include_if_query_contains))
        ]
        # Omit fields marked as "omit"

        extraction_prompt = self._build_extraction_prompt(
            schema=schema,
            active_fields=active_fields,
            raw_content=content,
            original_query=original_query,
            target_tokens=schema.target_tokens,
        )

        # Use intent-tier model (lighter, cheaper) — NOT synthesis-tier
        try:
            extracted = await self.llm_client.complete(
                messages=[{"role": "user", "content": extraction_prompt}],
                use_case="intent",  # Maps to tenant's lighter LLM selection
                max_tokens=schema.target_tokens + 200,
            )
            extracted_text = extracted.text
        except Exception as e:
            # Extraction LLM failure: fall back to truncated raw artifact (degraded but non-crashing)
            logger.warning(
                "Extraction LLM failed for agent %s — falling back to truncated pass-through",
                artifact.agent_id, exc_info=e
            )
            extracted_text = truncate_to_tokens(content, SYNTHESIS_CONTEXT_BUDGET["max_tokens_per_agent"])

        # Post-extraction PII check: extraction LLM may synthesize PII from fragmented signals
        if schema.pii_filter:
            extracted_text = PIIFilter.scrub(extracted_text)

        return SynthesisContext(
            agent_id=artifact.agent_id,
            content=extracted_text,
            source_attribution=schema.source_attribution,
            token_count=count_tokens(extracted_text),
            extracted=True,
        )
```

---

## 5. Multi-Pass Synthesis for Very Large DAGs

For DAGs exceeding 8 agents, or when combined extraction still approaches the budget, a two-pass synthesis strategy runs:

```
Pass 1 — Domain grouping:
  Group agents by domain:
    Financial domain: Bloomberg + CapIQ + iLevel + PitchBook
    Operational domain: Oracle Fusion + Teamworks + Azure AD
    Research domain: Perplexity + AlphaGeo

  Synthesize each group → intermediate summary (1,500–2,000 tokens each)

Pass 2 — Final synthesis:
  Input: 2–3 intermediate summaries + original query
  Output: Final user response (streaming)
```

This keeps each LLM call within its effective context window regardless of agent count.

```python
class SynthesisOrchestrator:
    # Multi-pass threshold is token-based, not agent-count-based.
    # An agent count threshold can trigger unnecessary multi-pass (7 tiny agents)
    # or miss required multi-pass (5 large-artifact agents under count but over token budget).
    SINGLE_PASS_TOKEN_THRESHOLD = int(
        SYNTHESIS_CONTEXT_BUDGET["max_total_context_tokens"] * 0.80
    )  # 80% of budget; beyond this, use multi-pass for safety headroom

    async def synthesize(
        self,
        synthesis_contexts: list[SynthesisContext],
        original_query: str,
        tenant: Tenant,
    ) -> AsyncGenerator[str, None]:
        total_tokens = sum(c.token_count for c in synthesis_contexts)

        if total_tokens <= self.SINGLE_PASS_TOKEN_THRESHOLD:
            async for chunk in self._single_pass_synthesis(
                synthesis_contexts, original_query, tenant
            ):
                yield chunk
        else:
            async for chunk in self._multi_pass_synthesis(
                synthesis_contexts, original_query, tenant
            ):
                yield chunk

    # Note: multi-pass is triggered at 80% of context budget regardless of agent count.
    # This correctly handles both 7-agent small-artifact DAGs (may not trigger)
    # and 5-agent large-artifact DAGs (will trigger if combined tokens exceed threshold).
```

---

## 6. Source Attribution in Synthesis

The extraction schema's `source_attribution` field ensures the synthesis LLM always knows and cites the data origin:

```
Synthesis LLM context block:

[Bloomberg Data License]
Apple (AAPL): Price $192.30, P/E 28.5, Market Cap $2.9T, Revenue TTM $385B

[S&P Capital IQ]
Peer comparison: Apple vs Microsoft vs Alphabet
  Apple: EV/EBITDA 22x, Net Margin 25.3%, BBB+ credit rating
  ...

[Perplexity AI (web search)]
Recent news (sources: Reuters 2026-03-03, Bloomberg Terminal 2026-03-02):
  - Apple reported Q1 FY2026 earnings beat by $0.12 EPS
  ...
```

The `[Source Name]` headers before each block guide the synthesis LLM to cite sources in its response without additional prompting.

---

## 7. Extraction Cost Analysis

Extraction adds LLM cost per multi-agent query. The cost is justified:

| Scenario                    | Without Extraction                       | With Extraction                                                                          |
| --------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------- |
| 5-agent DAG, raw artifacts  | 1 synthesis call: 50K input + 3K output  | 5 extraction calls: ~10K input + 1K output each; 1 synthesis call: 8K input + 3K output  |
| Token cost breakdown        | 50K in + 3K out (reasoning-tier)         | 50K in + 5K out (intent-tier) + 8K in + 3K out (reasoning-tier)                          |
| Approximate cost multiplier | 1× baseline (reasoning-tier throughout)  | Input cost: intent-tier ≈ 10× cheaper than reasoning-tier; net ~40–60% total cost saving |
| Quality impact              | Context truncation risk on large returns | Reliable synthesis with filtered, structured data                                        |

**Cost note**: The extraction step sends the raw artifact as input to the intent-tier LLM (~10K tokens per agent for large artifacts), so extraction input tokens are not free. However, the intent-tier model is typically 10–20× cheaper per token than the reasoning-tier synthesis model. The net saving depends on the provider's pricing differential. **Conservative estimate: 40% total cost saving** (accounting for extraction input costs); **optimistic estimate: 60%+** (when intent-tier is significantly cheaper and synthesis output is verbose).

The extraction calls use the intent-tier model (cheaper). The synthesis call uses the reasoning-tier model (expensive). Extraction reliably reduces the synthesis input token count by 80%+, which is the primary cost lever since reasoning-tier input pricing dominates the total bill.

---

## 8. Product & USP Analysis

### Reliability as a Product Feature

Context management is invisible to users but critical to enterprise reliability:

- **Without extraction**: 5-agent queries silently fail or truncate on large data returns from financial APIs
- **With extraction**: 5-agent queries reliably succeed regardless of raw data volume

Enterprise buyers running Bloomberg + CapIQ + Oracle Fusion queries in parallel cannot tolerate silent degradation. The extraction pipeline is what makes multi-agent DAG queries production-grade.

### 80/15/5 Alignment

- Platform defines extraction schemas per agent template (80%) — no tenant involvement
- Extraction schemas are versioned alongside agent templates
- New agent templates must ship with extraction schemas before marketplace registration

### Network Effects: Engagement

The extraction pipeline enables the **Engagement** network behavior: it ensures users always receive synthesized, well-structured answers from multi-agent queries, not raw data dumps or error messages. This drives the engagement loop that builds platform stickiness.

---

**Document Version**: 1.0
**Last Updated**: 2026-03-05
**Priority**: P0 — Required before 3+ agent DAG queries enter production
