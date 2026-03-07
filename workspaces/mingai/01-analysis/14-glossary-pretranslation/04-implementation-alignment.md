# 14-04 — Implementation Alignment: Glossary Pre-Translation

## 1. Architecture Change Summary

### 1.1 What Changes

The current architecture injects glossary terms into Layer 6 of the system prompt (SystemPromptBuilder). The new architecture removes Layer 6 entirely and inserts a new preprocessing component — GlossaryExpander — into the query processing pipeline before embedding generation.

**Current flow:**

```
User query
  → IntentDetector
  → EmbeddingGenerator (query used as-is)
  → VectorSearch
  → SystemPromptBuilder [Layer 1-5 + Layer 6 (glossary injection ~500 tokens)]
  → LLM synthesis
```

**New flow:**

```
User query
  → IntentDetector
  → GlossaryExpander (NEW: expands acronyms inline, <5ms)
  → EmbeddingGenerator (uses ORIGINAL query — see §2.3)
  → VectorSearch
  → SystemPromptBuilder [Layer 1-5 only, Layer 6 REMOVED]
  → LLM synthesis (receives EXPANDED query)
```

### 1.2 What Does Not Change

- Glossary data model: `GlossaryTerm` table schema unchanged (`id`, `tenant_id`, `acronym`, `full_form`, `aliases`, `is_ambiguous`, `is_active`)
- GlossaryEnricher term matching logic: reused as the foundation for GlossaryExpander's match algorithm
- Analytics schema: `glossary_term_matched` event structure unchanged
- Redis glossary cache: `mingai:{tenant_id}:glossary:active` key structure unchanged
- Tenant admin UI for glossary management: no changes required

### 1.3 Token Budget Impact

| Component                    | Before      | After                        | Delta   |
| ---------------------------- | ----------- | ---------------------------- | ------- |
| System prompt Layers 1-5     | ~800 tokens | ~800 tokens                  | 0       |
| Layer 6 (glossary injection) | ~500 tokens | 0 tokens                     | -500    |
| RAG context budget           | ~700 tokens | ~1,200 tokens                | +500    |
| Query expansion overhead     | 0 tokens    | ~4-6 tokens per matched term | +varies |
| Net gain at 0 matches        | 0           | +500                         | +500    |
| Net gain at 10 matches       | 0           | +450                         | +450    |

At the Professional tier (2K budget), the worst-case expansion (10 terms × 5 tokens = 50 tokens) still yields a net gain of 450 tokens for RAG context. The pre-translation overhead is bounded; the injection cost was unbounded as glossary size grew.

---

## 2. GlossaryExpander Component Specification

### 2.1 Interface

```python
@dataclass
class GlossaryExpansion:
    original_query: str
    expanded_query: str
    matched_terms: list[MatchedTerm]  # for analytics
    expansion_count: int

@dataclass
class MatchedTerm:
    acronym: str
    full_form: str
    match_type: Literal["exact", "alias", "suffix_stripped"]
    position: int  # char offset in original query

class GlossaryExpander:
    def __init__(self, tenant_id: str, redis_client: Redis):
        self.tenant_id = tenant_id
        self.redis = redis_client

    async def expand(self, query: str, locale: str = "en") -> GlossaryExpansion:
        """
        Expand glossary terms inline in the query string.
        Must complete in <5ms on cache hit.
        Returns GlossaryExpansion with both original and expanded query.
        """
```

### 2.2 Match Algorithm

**Step 1: Load glossary from Redis**

```
key = f"mingai:{tenant_id}:glossary:active"
terms = redis.get(key)  # Pre-loaded dict: {acronym: GlossaryTerm}
```

Cache miss: load from PostgreSQL, write to Redis (TTL: 300s). If load fails, return GlossaryExpansion with original_query unchanged (fail open).

**Step 2: Tokenize query for match candidates**
Tokenize the query by whitespace and punctuation boundaries. Do not tokenize by character (avoid mid-word matches).

Example: "What's the AWS payout for FY24?" → tokens: ["What's", "the", "AWS", "payout", "for", "FY24"]

**Step 3: Match each token against glossary**

For each token, apply in order:

1. **Exact match** (case-sensitive): `"AWS" in terms` → match if `terms["AWS"].is_active and not terms["AWS"].is_ambiguous`
2. **Case-insensitive exact match**: `token.upper() in terms` → same conditions
3. **Alias match**: check token (case-insensitive) against `term.aliases` list for all terms
4. **Suffix-stripped match** (Phase 1 extension): strip trailing `'s`, `s` (possessive/plural), retry exact match

**Hard exclusions (applied before match attempt):**

- Token length <= 2 characters: skip (prevents "IT" → "Information Technology" for the pronoun "it" when written as lowercase; see §2.2.1)
- Token contains non-ASCII characters: skip unless CJK (CJK terms may be expanded using CJK parentheses)
- Token appears in a stop-word list: skip (common English words that happen to be acronyms)

**2.2.1 Case-Sensitivity Rule for Short Tokens**

A critical edge case: single-word acronyms of 2-3 characters that overlap with common English words.

Rule: For tokens of length <= 3, require exact case match (case-sensitive). For tokens of length >= 4, allow case-insensitive match.

Rationale: "IT" (all caps) is likely an acronym. "it" (all lower) is likely a pronoun. "AWS" (all caps) is likely an acronym. "aws" would not match. This heuristic covers ~95% of real cases without false positives.

**Step 4: Build expanded query**

For each matched term, find the token's position in the original query string and insert ` (full_form)` immediately after the token:

```
"What is the AWS payout?"
                   ↑ insert " (Annual Wage Supplement)" here
→ "What is the AWS (Annual Wage Supplement) payout?"
```

Multi-token replacement: if a multi-word glossary term matches (e.g., "LTV limit" as a single term), the expansion is appended after the last token of the phrase.

**Step 5: Ambiguity handling**

If `term.is_ambiguous == True`, skip expansion. Return the token unchanged. This is a no-op, not an error. Log `glossary_term_skipped_ambiguous` analytics event.

Rationale: a wrong expansion is worse than no expansion. Ambiguous terms must be explicitly resolved by the admin (marking them as non-ambiguous and selecting the canonical full_form) before they expand.

**Step 6: Conflict resolution for multi-term overlap**

If both "LTV" and "LTV limit" are glossary terms and the query contains "LTV limit":

- Prefer the longer match (most specific term wins)
- Expand "LTV limit" as a single term; do not also expand "LTV" within the matched phrase

This mirrors the longest-match principle used in NLP tokenization.

### 2.3 CJK Support

When `locale` contains a CJK locale code (e.g., `zh`, `ja`, `ko`), use full-width parentheses for expansion:

- Latin: `AWS (Annual Wage Supplement)` — standard ASCII parentheses
- CJK: `AWS（Annual Wage Supplement）` — U+FF08, U+FF09 (full-width)

CJK locale detection: from `Accept-Language` header or tenant-level `locale` setting in tenant config.

### 2.4 Performance Contract

- **Target latency**: <5ms on Redis cache hit
- **Maximum latency**: <50ms on cache miss (DB load + Redis write)
- **Failure mode**: If GlossaryExpander raises any exception, return original query unchanged. Log error. Do not fail the query pipeline.
- **Cache TTL**: 300 seconds (5 minutes). Invalidated on glossary write.
- **No external calls**: GlossaryExpander must not make HTTP calls or calls to external APIs.

### 2.5 Maximum Expansion Cap

To prevent runaway token inflation, cap the number of expansions per query at **8 terms**. If more than 8 terms match, expand the first 8 in left-to-right order. Log `glossary_expansion_cap_reached` event.

This cap is a platform constant, not tenant-configurable. The value 8 yields a worst-case overhead of ~48 tokens — well within budget at all tier levels.

---

## 3. Pipeline Integration

### 3.1 Insertion Point

GlossaryExpander is inserted **after IntentDetector, before EmbeddingGenerator**:

```python
# query_pipeline.py

async def process_query(query: str, tenant_id: str, session: Session) -> QueryResult:
    # Step 1: Intent detection (unchanged)
    intent = await intent_detector.detect(query)

    # Step 2: Glossary expansion (NEW)
    expansion = await glossary_expander.expand(query, locale=session.locale)
    expanded_query = expansion.expanded_query  # used for LLM call
    original_query = expansion.original_query  # used for embedding

    # Step 3: Embedding (uses ORIGINAL query — see §3.2)
    embedding = await embedding_generator.embed(original_query)

    # Step 4: Vector search (uses embedding of original query)
    chunks = await vector_search.search(embedding, tenant_id=tenant_id)

    # Step 5: System prompt build (Layer 6 REMOVED — see §4)
    system_prompt = await system_prompt_builder.build(session, chunks)

    # Step 6: LLM call (uses EXPANDED query)
    response = await llm.chat(
        system=system_prompt,
        user=expanded_query  # expanded form goes to LLM
    )

    # Step 7: Analytics
    if expansion.matched_terms:
        analytics.emit("glossary_term_matched", {
            "tenant_id": tenant_id,
            "session_id": session.id,
            "terms": [t.acronym for t in expansion.matched_terms],
            "expansion_count": expansion.expansion_count
        })

    return QueryResult(response=response, expansion=expansion)
```

### 3.2 Embedding Strategy: Original Query

**Decision: RAG embedding uses the original (pre-expansion) query.**

Rationale: The user's query as typed is the most semantically faithful representation of their intent. Embedding the original query ensures that vector search retrieves documents aligned with the user's phrasing — which is likely to match the phrasing in indexed enterprise documents (which also use acronyms, since they were written by the same employees who use them).

Expanded query goes only to the LLM, which needs the full context for interpretation but does not do vector search.

**Counterargument:** If the knowledge base contains only full-form documents (never uses acronyms), then embedding the expanded query would improve retrieval. This is an empirical question that requires A/B testing per tenant corpus composition.

**Phase 2 extension:** An optional `embed_expanded` flag per tenant, defaulting to `False`. Tenants with full-form-dominant corpora can opt into embedding the expanded query.

---

## 4. Layer 6 Removal

### 4.1 Current SystemPromptBuilder Layer 6

```python
# system_prompt_builder.py — CURRENT (to be removed)

def _build_layer_6_glossary(self, tenant_id: str) -> str:
    terms = self.glossary_service.get_active_terms(tenant_id)
    if not terms:
        return ""
    lines = [f"- {t.acronym}: {t.full_form}" for t in terms[:50]]
    return "Domain terminology:\n" + "\n".join(lines)
```

### 4.2 Post-Migration SystemPromptBuilder

Remove `_build_layer_6_glossary` entirely. Remove the call site in `build()`. Update `build()` to not reserve token budget for Layer 6.

The system prompt token budget recalculation:

- Before: 2,000 - 800 (Layers 1-5) - 500 (Layer 6) = 700 tokens for RAG
- After: 2,000 - 800 (Layers 1-5) = 1,200 tokens for RAG

The RAG chunk loader should be updated to allow up to 1,200 tokens of retrieved context at Professional tier.

---

## 5. Analytics Preservation

The `glossary_term_matched` event **continues to fire** in the new architecture. The difference is:

- **Before**: event fired because a term was injected into the system prompt (indicating "this term was in-scope for this query")
- **After**: event fires because a term was matched in the query and expanded inline (same semantic meaning, cleaner signal)

The event payload remains compatible. No analytics schema migration needed. No dashboards need updating.

New events added:

- `glossary_term_skipped_ambiguous`: term matched but was marked ambiguous; skipped
- `glossary_expansion_cap_reached`: query contained more than 8 glossary matches; truncated at 8
- `glossary_expander_fallback`: GlossaryExpander threw an exception; original query used (circuit breaker)

---

## 6. Migration Path

### 6.1 No Data Migration Required

The `GlossaryTerm` table schema is unchanged. All existing tenant glossary data is valid and immediately usable by GlossaryExpander without transformation.

### 6.2 Deploy Order (Zero Downtime)

**Step 1: Deploy GlossaryExpander (without removing Layer 6)**
Deploy the new GlossaryExpander component. Wire it into the pipeline between IntentDetector and EmbeddingGenerator. At this point, both pre-translation AND Layer 6 injection are active simultaneously.

This is safe: pre-translation adds inline context; Layer 6 still injects the glossary. There is brief double-coverage, but this is harmless (the LLM receives the full_form twice: once inline in the query, once in the system prompt).

Validate in staging: confirm expansion fires correctly, latency <5ms, analytics events emit.

**Step 2: Remove Layer 6 from SystemPromptBuilder**
Deploy the Layer 6 removal. From this point, only pre-translation is active. Monitor:

- Response quality (no regression on domain-specific queries)
- Token usage (confirm ~500-token reduction in system prompt)
- Latency (confirm no regression — GlossaryExpander should be sub-5ms)

**Step 3: Increase RAG context budget**
Update the RAG chunk loader to use the recovered 500 tokens. This is a configuration change (token budget constant), not a code change.

**Rollback plan:** Steps 1 and 2 are independently reversible. If Step 2 causes quality regression, re-enable Layer 6 without reverting Step 1.

---

## 7. Carry-Forward vs Net-New

### Carry-Forward (Reused Existing Code)

| Component                                                   | Reuse                            | Notes                                                |
| ----------------------------------------------------------- | -------------------------------- | ---------------------------------------------------- |
| `GlossaryEnricher` term matching logic                      | Adapts exact match + alias match | Port to GlossaryExpander; add case-sensitivity rules |
| Redis glossary cache (`mingai:{tenant_id}:glossary:active`) | Unchanged                        | GlossaryExpander reads same key                      |
| `GlossaryTerm` data model                                   | Unchanged                        | No schema migration                                  |
| `glossary_term_matched` analytics event                     | Unchanged schema                 | Event still fires; payload compatible                |
| Tenant admin glossary management UI                         | Unchanged                        | No UI changes in Phase 1                             |

### Net-New (New Code Required)

| Component                                      | Description                                             | Complexity |
| ---------------------------------------------- | ------------------------------------------------------- | ---------- |
| `GlossaryExpander` class                       | Core preprocessing component                            | MEDIUM     |
| Inline expansion formatting                    | `token + " (" + full_form + ")"` with position tracking | LOW        |
| CJK locale detection and parenthesis selection | `locale → parenthesis_type` lookup                      | LOW        |
| Suffix-stripped match (possessive/plural)      | Strip `'s`, `s` before retry                            | LOW        |
| Conflict resolution (longest-match)            | Multi-word term overlap handling                        | MEDIUM     |
| `glossary_term_skipped_ambiguous` event        | New analytics event                                     | LOW        |
| `glossary_expansion_cap_reached` event         | New analytics event                                     | LOW        |
| `glossary_expander_fallback` event             | Circuit breaker event                                   | LOW        |
| RAG context budget constant update             | Change token ceiling in chunk loader                    | TRIVIAL    |

**Estimated implementation effort:** 3-5 engineering days for a senior engineer familiar with the codebase. The algorithm complexity is low; the main effort is in the conflict resolution and thorough test coverage of edge cases (CJK, suffix stripping, ambiguity, cap enforcement).
