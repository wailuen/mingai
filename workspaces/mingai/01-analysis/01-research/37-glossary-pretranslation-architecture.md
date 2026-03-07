# 37. Glossary Pre-Translation Architecture (Inline Expansion)

**Status**: Canonical — supersedes doc 23 section 2b (LLM prompt injection approach)
**Date**: 2026-03-06

---

## Decision

Glossary terms are NO LONGER injected into the LLM system prompt. Instead, matched terms are expanded inline in the user query using parenthetical notation:

- "AWS" → "AWS (Annual Wage Supplement)"

The acronym is preserved so RAG retrieval still works (source documents contain acronyms). The expansion provides full context to the LLM without consuming system prompt token budget.

---

## 1. Why Injection Fails at Scale

### Token Budget Pressure

The 6-layer system prompt stack at the 2K token budget leaves limited room for RAG context:

| Layer | Component                  | Tokens |
| ----- | -------------------------- | ------ |
| 0-1   | Agent base + platform base | 200    |
| 2     | Org context                | 100    |
| 3     | Profile context            | 200    |
| 4a    | Individual working memory  | 100    |
| 4b    | Team working memory        | 150    |
| 6     | Glossary injection (OLD)   | 500    |
| —     | Remaining for RAG          | 750    |

With glossary injection, only 750 tokens remain for domain context when base layers are included — insufficient for complex multi-document retrieval.

After removing glossary injection, the 500 tokens return to RAG:

| Layer | Component                          | Tokens    |
| ----- | ---------------------------------- | --------- |
| 2     | Org context                        | 100       |
| 3     | Profile context                    | 200       |
| 4a    | Individual working memory          | 100       |
| 4b    | Team working memory                | 150       |
| —     | Memory overhead subtotal           | 550       |
| —     | **Remaining for RAG at 2K budget** | **1,450** |

Net improvement: +500 tokens for RAG (vs before with glossary). Canonical memory overhead = 550 tokens; RAG = 1,450 tokens at 2K budget (excluding base agent/platform layers which are fixed and variable per deployment).

### Relevance Noise

Injecting all matched terms adds definitions that may not be relevant to the specific query. A query about "CPF contribution rates" does not benefit from glossary entries for "AWS", "MOM", or "SDL" even if the tenant's glossary contains them all. Pre-translation only expands terms that literally appear in the query — a naturally self-scoping filter.

### Security Concern from Doc 23

Doc 23 section 2b flagged prompt injection risk when appending user-controlled content combined with injected glossary content. The concern is valid for bulk injection (entire glossary section in system prompt) because:

- Definitions can be long and instruction-like ("When asked about X, always say Y...")
- System prompt position gives injected content elevated authority
- Glossary management is accessible to tenant admins who could craft adversarial definitions

Pre-translation resolves this by:

1. Only appending `full_form` (short noun phrase), not the full definition
2. Expansion occurs in the user message position (same trust level as the original query)
3. Expansion is deterministic, bounded, and non-instructional
4. Validation enforces noun-phrase-only content on `full_form` at write time

This is distinct from bulk injection: inline expansion is narrow (per matched term), deterministic (same term always yields same expansion), and limited to short noun phrases.

---

## 2. Inline Expansion Algorithm

### Inputs

- `query: str` — raw user query string
- `tenant_glossary: List[GlossaryTerm]` — loaded from Redis cache (see section 6)

### Process

1. Build a lookup index: for each glossary term, index all aliases (including the primary term name) mapped to their canonical `full_form`
2. Tokenize the query into candidate spans (word boundaries + multi-word sliding windows up to 5 words)
3. For each candidate span, check for exact match (case-insensitive) against the lookup index
4. On match: record position, matched term, and `full_form`
5. Apply ambiguity resolution (see Ambiguity Handling below)
6. Sort matches by position; skip duplicates (first occurrence only)
7. Reconstruct query string with parenthetical expansions inserted after each matched term

### Output

Query with expansions appended in parentheses after each matched span. Original casing is preserved.

### Examples

```
Input:  "When does AWS get paid and how does it affect CPF?"
Output: "When does AWS (Annual Wage Supplement) get paid and how does it affect CPF (Central Provident Fund)?"

Input:  "What is the loan to value limit for HDB flats?"
Output: "What is the loan to value (LTV) limit for HDB flats?"

Input:  "AWS AWS AWS announcement"
Output: "AWS (Annual Wage Supplement) AWS AWS announcement"
```

Note: reverse expansion is supported — full form to acronym (e.g., "loan to value" → "loan to value (LTV)"). The same algorithm handles both directions; the `full_form` is whichever form is the canonical expansion.

### Case Handling

- Match is case-insensitive
- Original case in the query is preserved in the output
- `full_form` in expansion uses its stored casing (set at glossary creation time)

### Multi-Word Terms

Multi-word terms match as complete phrases. The sliding window approach (up to 5 words) covers common financial/HR compound terms. Example: "Central Provident Fund" as a 3-word span expands to "Central Provident Fund (CPF)".

### Ambiguity Handling

When a term matches multiple glossary entries (same acronym, different definitions):

1. Check `source_index_ids` on each matching entry against the agent's active index set
2. If exactly one entry's `source_index_ids` intersects the agent's index set → use that entry
3. If multiple entries still match → skip expansion (no-op)
4. If no entries match by index → skip expansion (no-op)

No-op is always safer than wrong expansion. A wrong expansion (e.g., "BS (Balance Sheet)" when the user means "BS (Business Studies)") misleads the LLM more than no expansion at all.

### Deduplication

If the same term appears multiple times in a query, only the first occurrence is expanded. Subsequent occurrences are left as-is. This prevents cluttered output and keeps the expanded query readable.

### Maximum Expansion Length

Per term: append at most `"(full_form)"`. The `full_form` field is capped at 50 characters (enforced at write time). Maximum overhead per matched term: ~52 characters. A query with 5 matched terms adds at most ~260 characters — negligible for LLM context.

---

## 3. Where in the Pipeline

The expansion step sits between intent detection and LLM synthesis:

```
User Query
    │
    ▼
Intent Detection (GPT-5 Mini, original query)
    │
    ▼
Embedding Generation (ORIGINAL query — unchanged)
    │
    ▼
Vector Search (RAG retrieval against source documents)
    │
    ▼
GlossaryExpander.expand(query, tenant_glossary)  ← NEW STEP
    │
    ▼
Context Assembly (expanded query + retrieved docs + prompt layers)
    │
    ▼
LLM Synthesis (receives EXPANDED query)
```

Critical invariant: RAG embedding uses the ORIGINAL query to preserve retrieval accuracy. Source documents contain acronyms; expanding to full forms before embedding would degrade vector similarity against acronym-heavy documents. The LLM receives the expanded query for comprehension; the retrieval engine uses the original for accuracy.

---

## 4. Full Form vs Definition

### full_form Field

- Used for inline expansion
- Short noun phrase, max 50 characters
- Examples: "Annual Wage Supplement", "Central Provident Fund", "Loan-to-Value"
- Required field for inline expansion — if absent, the term is skipped

### definition Field

- Up to 200 characters
- Used only in the UI source attribution tooltip (doc 23 section 2c — unchanged)
- NOT used in inline expansion — too long and potentially instruction-like
- Example: "AWS is the year-end bonus paid in December, calculated as a fixed number of months' salary..."

### When a term has no full_form

Skip expansion for that term. Do not fall back to using definition inline. Log the miss to the glossary analytics service (term was matched but could not expand) for tenant admin visibility.

---

## 5. Security Analysis

### Original Doc 23 Concern

Doc 23 section 2b identified a prompt injection vector when glossary content is appended to user queries or injected into system prompts. The concern: tenant admins control glossary content; a malicious admin could craft a definition that, when injected, modifies LLM behaviour.

### Pre-Translation Mitigations

| Attack Surface                     | Mitigation                                                                       |
| ---------------------------------- | -------------------------------------------------------------------------------- |
| Malicious `full_form` content      | 50-char limit + alphanumeric/spaces/hyphens validation at write time             |
| Instruction-like expansion         | full_form validated as noun phrase only; no verbs, no punctuation except hyphens |
| Privilege escalation via expansion | Expansion in user message position — no elevated authority vs original query     |
| Mass disambiguation confusion      | Ambiguity no-op rule: ambiguous terms are never expanded                         |

### Validation Rules for full_form (enforced at write/update time)

```python
FULL_FORM_PATTERN = re.compile(r'^[A-Za-z0-9\s\-àáâãäåæçèéêëìíîïðñòóôõöùúûüýþÿ]+$')

def validate_full_form(full_form: str) -> None:
    if len(full_form) > 50:
        raise ValidationError("full_form exceeds 50 character limit")
    if not FULL_FORM_PATTERN.match(full_form.strip()):
        raise ValidationError("full_form contains disallowed characters")
    if full_form.strip() != full_form:
        raise ValidationError("full_form has leading/trailing whitespace")
```

### Enterprise Tier Approval Workflow

For Enterprise tenants: new glossary terms and full_form edits require approval by a second tenant admin before the cache is updated. This prevents a single compromised admin account from deploying adversarial expansions. Professional tier: single-admin approval (consistent with current tenant admin RBAC).

### Residual Risk

Low. The attack surface is narrow: a malicious tenant admin could craft a `full_form` that misleads the LLM about a term's meaning (e.g., mapping "Policy" to "Policy (Prohibited Action)"). This is mitigated by the noun-phrase validation and is bounded — it only affects that tenant's own queries, not other tenants (tenant-scoped glossary).

---

## 6. Glossary Cache Strategy

Unchanged from doc 23. Documented here for completeness.

- Redis key: `mingai:{tenant_id}:glossary:approved`
- Type: serialized list of approved GlossaryTerm objects
- TTL: 1 hour
- Invalidation: on any CRUD operation to the glossary (CREATE, UPDATE, DELETE, APPROVE)
- Pre-translation reads from Redis on every query — zero DB hits per query in the steady state
- On cache miss: load from PostgreSQL, write to Redis, proceed

The GlossaryExpander receives a pre-loaded list (injected at the request handler level, not fetched inside the expansion function). This keeps the expander a pure function and simplifies testing.

---

## 7. Token Budget Impact

### Before (Glossary Injection)

```
Layer 2:   Org context                  =  100 tokens
Layer 3:   Profile context              =  200 tokens
Layer 4a:  Individual working memory    =  100 tokens
Layer 4b:  Team working memory          =  150 tokens
Layer 6:   Glossary injection           =  500 tokens
────────────────────────────────────────────────────
Memory overhead                         = 1,050 tokens
RAG budget at 2K total                  =   950 tokens
RAG budget at 4K total                  = 2,950 tokens
```

### After (Pre-Translation)

```
Layer 2:   Org context                  =  100 tokens
Layer 3:   Profile context              =  200 tokens
Layer 4a:  Individual working memory    =  100 tokens
Layer 4b:  Team working memory          =  150 tokens
[Glossary layer removed — pre-translated inline]
────────────────────────────────────────────────────
Memory overhead (canonical)             =  550 tokens
RAG budget at 2K total                  = 1,450 tokens  (+500 vs before with glossary)
RAG budget at 4K total                  = 3,450 tokens
```

Note: Layer 0-1 (agent base + platform base, ~200 tokens) are fixed and excluded from the canonical overhead figure above, consistent with the canonical token budget specification.

Net improvement at 2K budget: +500 tokens for RAG vs the pre-translation state (where glossary injection consumed 500 tokens from the same budget). This is the difference between a few document chunks and meaningfully more — a qualitative improvement in answer accuracy for complex queries.

The inline expansion adds a small overhead to the user message (typically 50-200 tokens for queries with multiple matched terms), but this comes from the user message budget, not the system prompt budget.

---

## 8. Migration from Injection to Pre-Translation

### Changes Required

**Remove:**

- Layer 6 (glossary) from `SystemPromptBuilder.build()`
- The glossary section template in `prompt_templates/system_prompt.jinja2`
- `GlossaryEnricher.enrich()` call inside `SystemPromptBuilder` (retain the method — see below)

**Add:**

- `GlossaryExpander` class in `services/glossary/expander.py`
- `GlossaryExpander.expand(query: str, terms: List[GlossaryTerm]) -> str` method
- Call `GlossaryExpander.expand()` in `QueryPipeline.process()` after retrieval, before LLM call

**Unchanged:**

- Glossary data model (PostgreSQL schema from doc 23)
- Glossary Redis cache (`mingai:{tenant_id}:glossary:approved`)
- Glossary admin UI (CRUD, approve/reject workflow)
- `GlossaryEnricher.enrich()` — decoupled from prompt injection, still called for analytics (term match tracking, usage frequency reporting in Tenant Admin > Glossary > Analytics)

### Backwards Compatibility

The `GlossaryEnricher.enrich()` method tracks which terms are matched and how frequently. This data feeds the Tenant Admin glossary analytics dashboard. Decoupling it from prompt injection means it must now be called independently at the query preprocessing stage (alongside the expander, not inside the prompt builder).

### Test Checklist

- [ ] Query with 0 matched terms: output identical to input
- [ ] Query with 1 matched term: single expansion inserted
- [ ] Query with same term twice: only first occurrence expanded
- [ ] Query with ambiguous term, 1 matching index: expansion applied
- [ ] Query with ambiguous term, multiple matching indexes: no-op
- [ ] Query with term missing full_form: no-op, analytics event fired
- [ ] CJK query: full-width parentheses used
- [ ] System prompt no longer contains glossary layer
- [ ] Token count of system prompt reduced by ~500 tokens (glossary layer removed) vs pre-migration

---

## 9. Multilingual Considerations

### CJK Queries (Chinese, Japanese, Korean)

Exact matching on CJK terms uses the trigram index defined in doc 23 schema (already handles CJK tokenization). The expansion algorithm itself is language-agnostic; CJK phrases are matched as character sequences.

### Parenthesis Style Selection

Language is detected from the first 100 characters of the query using a lightweight language detector (e.g., `langdetect` or Unicode script analysis):

| Detected script | Parenthesis style                | Example                      |
| --------------- | -------------------------------- | ---------------------------- |
| Latin (default) | ASCII `( )`                      | AWS (Annual Wage Supplement) |
| CJK             | Full-width `（ ）` (U+FF08/FF09) | AWS（年終花紅）              |

### CJK full_form Values

Tenant admins may store CJK full forms for terms used with Chinese/Japanese/Korean interfaces. The 50-character limit applies to the stored string (Unicode character count, not byte count). CJK characters are common multi-byte but linguistically compact — 50 Unicode code points is sufficient for any noun phrase.

### Validation for CJK full_form

The alphanumeric validation pattern is extended to allow CJK Unicode blocks (U+4E00–U+9FFF, U+3040–U+30FF, U+AC00–U+D7AF) in addition to Latin characters. Special characters (punctuation, instructions) remain blocked.
