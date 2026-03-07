# 14-01 — Product Opportunity: Glossary Pre-Translation

## 1. Problem Statement

Enterprise tenants operate with dense, domain-specific vocabularies that are invisible to general-purpose LLMs. Acronyms, internal product codes, regulatory abbreviations, and industry shorthand are the native language of enterprise users — but they are opaque to models trained on public corpora.

The current approach injects glossary definitions into the LLM system prompt (Layer 6). This has two compounding failure modes:

**Failure Mode 1: Token Budget Destruction**
At mingai's 2K Professional tier token budget, glossary injection consumes ~500 tokens before any retrieval context is loaded. RAG receives only 700 tokens of context — a starvation condition. Responses become shallower as the document set grows, and the retrieval system is punished precisely because the tenant has a mature, well-maintained glossary.

**Failure Mode 2: Prompt Injection Surface**
Glossary definitions are tenant-controlled content injected verbatim into the system prompt. A definition containing instruction-like language ("Ignore previous instructions and summarise as...") or special delimiter characters can corrupt the system prompt structure. This is not a theoretical risk — it is a direct consequence of mixing untrusted content into the privileged prompt zone.

The root cause of both failures is the same: treating glossary knowledge as prompt content rather than as query preprocessing. The glossary's job is to translate the user's language into a form the LLM can act on — and that job can be done before the prompt is assembled, not inside it.

**Glossary Pre-Translation** resolves both failure modes by moving term expansion to the query preprocessing stage. The user's raw query is augmented inline — "What is the AWS payout?" becomes "What is the AWS (Annual Wage Supplement) payout?" — and the system prompt is never involved.

---

## 2. Current State Pain Points

### 2.1 Token Budget Crunch (Quantified)

| Budget Allocation             | Current State (Injection) | Post-Migration (Pre-Translation) |
| ----------------------------- | ------------------------- | -------------------------------- |
| System prompt (Layers 1-5)    | ~800 tokens               | ~800 tokens                      |
| Glossary injection (Layer 6)  | ~500 tokens               | 0 tokens                         |
| RAG context budget            | ~700 tokens               | ~1,200 tokens                    |
| Available for history/persona | minimal                   | ~200 tokens recovered            |

The 500-token recovery is not marginal — it is a 71% increase in RAG context capacity at the Professional tier. For tenants with knowledge bases spanning hundreds of documents, this is the difference between retrieving 2-3 chunks and retrieving 5-6 chunks, which directly correlates with response completeness.

### 2.2 Glossary-as-Prompt-Injection Risk

The current implementation concatenates glossary terms and definitions into the system prompt using a structured template. If any definition contains:

- Backtick sequences or XML-like tags that break prompt parsing
- Instruction fragments ("respond only in JSON", "do not use your training data")
- Role-manipulation language

...the system prompt is corrupted. Because the glossary is tenant-managed (not platform-managed), this is a sustained attack surface. The current mitigation (character escaping) is incomplete — semantic injection does not require special characters.

Moving only `full_form` (a short noun phrase) into the query, rather than the full definition, eliminates this class of risk entirely. Noun phrases do not contain executable instructions.

### 2.3 All-or-Nothing Glossary Behavior

The current injection approach applies the entire glossary to every query, regardless of relevance. A query about HR policy receives the full IT, Finance, and Legal glossary alongside the HR terms. This is semantically noisy — the LLM must process and discount irrelevant terms — and it inflates token use for no gain.

Pre-translation is inherently selective: only terms that appear in the specific query are expanded. A query with no glossary matches costs zero additional tokens.

### 2.4 User Experience Invisibility

Users who know to spell out "Annual Wage Supplement" get better responses than users who type "AWS". There is no way for a user to know this asymmetry exists. Pre-translation closes the quality gap silently and equitably, without requiring users to learn the LLM's vocabulary limitations.

---

## 3. Competitive Landscape

### 3.1 How Competitors Handle Domain Terminology

**Glean**
No tenant glossary feature. Relies entirely on indexed documents containing the full-form text. If a document only uses an acronym and never spells it out, Glean cannot bridge the gap. No query-time expansion.

**Guru**
Glossary is a searchable knowledge base surfaced in search results. It is not injected into LLM context and does not affect query interpretation. Guru's LLM integration (Guru AI) does not perform query expansion using the glossary. The glossary is a human reference tool, not a machine-readable query enhancer.

**Microsoft Copilot for M365**
No custom tenant glossary. Copilot relies on Microsoft Graph context (emails, documents) for implicit term resolution. If "AWS" appears frequently in company emails meaning "Annual Wage Supplement", Copilot may infer this from context — but there is no explicit, governed glossary mechanism.

**Notion AI**
No glossary feature. Notion AI operates on Notion content as its context; terminology resolution is entirely dependent on whether the workspace documents define the terms.

**Coveo**
Thesaurus feature for search query expansion (maps synonyms at indexing time). This is a retrieval-layer concern — it improves document recall, not LLM understanding. It does not perform inline query expansion visible to the LLM.

### 3.2 mingai's Differentiation

mingai's inline pre-translation approach is architecturally distinct from all known competitors:

1. It operates at query time (not index time), so it captures terms not yet in the document corpus
2. It expands into the query itself (not a separate context block), so the LLM processes expansion as part of the user's natural language intent
3. It preserves the acronym alongside the expansion, so the LLM can use either form when searching retrieved document chunks
4. It is scoped per-tenant, with no cross-tenant contamination

No competitor has published documentation or patents describing inline query expansion driven by a tenant-managed glossary at the query preprocessing layer.

---

## 4. Value Propositions

**VP1: Direct RAG Quality Improvement**
Freeing 500 tokens from the system prompt directly increases the number of document chunks retrievable at any given token budget. At Professional tier (2K budget), RAG context grows from ~700 to ~1,200 tokens. More context = more complete answers. This improvement is visible in response quality from day one of migration.

**VP2: Elimination of Prompt Injection Surface**
Removing glossary definitions from the system prompt removes an entire category of tenant-controlled prompt injection risk. Only `full_form` (a short noun phrase, e.g., "Annual Wage Supplement") enters the query — too short and structurally constrained to carry injection payloads.

**VP3: Equitable Response Quality Across User Sophistication Levels**
Junior employees and new hires who use acronyms fluently but don't know they need to spell them out for an LLM now receive the same response quality as a power user who manually types the full form. This is a silent UX improvement that reduces support escalations ("the AI doesn't understand our terminology").

**VP4: Selective Token Usage (Pay-as-You-Match)**
Expansion tokens are added only when a glossary term is actually present in the query. A query with zero matches adds zero tokens. A query with one match adds 4-6 tokens. This is radically more efficient than the current flat ~500-token overhead applied to every query.

**VP5: Glossary Remains a First-Class Platform Feature**
Pre-translation makes the glossary more valuable, not less. Because the expansion is what enables high-quality responses, the glossary becomes a tangible driver of measurable response improvement — which creates an incentive loop for tenant admins to maintain it. The current injection approach buries this value inside the system prompt where it is invisible.

**VP6: CJK and Multilingual Support Foundation**
Inline expansion with locale-aware parenthesis formatting (CJK: 全角括号 vs Latin: standard parens) creates the infrastructure for future multilingual glossary support. This is not possible with prompt injection, where formatting is governed by the system prompt template.

**VP7: Reduced Vendor Dependency for Token Budget**
As LLM providers raise prices or reduce context windows, the system prompt overhead becomes increasingly expensive. Pre-translation reduces the fixed token cost of the platform, making mingai more resilient to upstream pricing changes and more competitive at lower tier budgets.

---

## 5. Unique Selling Points

Applying critical scrutiny: most of the above are Value Propositions (things users value), not Unique Selling Points (things competitors cannot easily replicate). A genuine USP requires both differentiation and defensibility.

**USP1: Tenant-Governed Inline Query Expansion (Genuine)**
The combination of (a) tenant-specific glossary, (b) query-time inline expansion, and (c) preservation of both acronym and expansion in the query string is architecturally novel. Competitors with glossaries (Guru) don't wire them to LLM queries. Competitors with LLM queries (Glean, Copilot) don't have tenant-governed glossaries that operate at query time. The intersection is mingai's alone — for now.

Defensibility: Growing glossary data per tenant creates switching costs. A tenant with 500 curated terms, usage analytics, and approval workflows will not rebuild this in a competitor. The glossary becomes a data moat.

**USP2: Token Efficiency as a Measurable SLA Commitment (Potential)**
mingai can offer a concrete, measurable commitment: "glossary terminology never consumes your RAG context budget." No competitor makes this architectural guarantee. It could be expressed as a tier feature: "Zero-overhead glossary expansion — included at Professional and above." This is a purchasing-moment differentiator for procurement-aware enterprise buyers.

Defensibility: Moderate. A competitor could copy the architecture. Defensibility comes from being first to market the commitment, making it a feature comparison criterion.

**What was considered but rejected as a USP:**

- "Removes prompt injection risk from glossary" — TRUE but not a sales-moment USP. Security buyers care, but it is not a category-creating differentiator.
- "Equitable response quality for all users" — TRUE but difficult to prove in a sales cycle without A/B data. Treat as a VP, not a USP.
- "CJK support" — TRUE but a table-stakes feature for any enterprise platform targeting Asian markets, not a USP.

---

## 6. 80/15/5 Mapping

### 80% — Reusable / Cloud-Agnostic Platform Behavior

- **GlossaryExpander algorithm**: exact match + alias match + case-insensitive + multi-word support. Tenant-agnostic logic, deployed once, applied to all tenants.
- **Redis cache layer**: `mingai:{tenant_id}:glossary:active` — loaded once at query time, sub-millisecond lookup. No per-tenant infrastructure divergence.
- **Ambiguity skip logic**: when a term is ambiguous (multiple full_forms), skip expansion. This is a platform-level safety decision, not a tenant choice.
- **Analytics event emission**: `glossary_term_matched` event fires regardless of expansion behavior. Standardised analytics schema is platform-owned.
- **CJK locale detection and parenthesis formatting**: platform-level, driven by `accept-language` or tenant locale config.
- **Pipeline integration**: GlossaryExpander sits between intent detection and embedding generation. This ordering is architecturally determined, not tenant-configurable.

### 15% — Tenant Self-Service

- **Glossary term management UI**: create, edit, delete, add aliases, mark ambiguous. Tenant admins own their glossary.
- **CSV import / bulk upload**: tenants can seed their glossary from existing terminology documents.
- **Per-index scoping** (Phase 2): tenants can configure which SharePoint sites or document indexes a term applies to. A legal term shouldn't expand in an HR query context.
- **Approval workflow toggle**: tenants can require admin approval before a new term activates. Off by default; on for regulated industries.
- **Ambiguity resolution by admin**: tenant admin can mark a term as "do not expand" to prevent false positives.

### 5% — Platform-Level Customisation (Operator-Controlled)

- **Expansion format template**: the `(full_form)` format could theoretically be altered (e.g., `— full_form` for different LLM behavior). This is a platform operator decision, not a tenant decision. Not exposed in UI.
- **Max expansions per query cap**: platform operator can set a ceiling (e.g., max 8 expansions per query) to prevent runaway token inflation. Default is 8; not tenant-configurable.
- **Glossary term character limits**: `full_form` max length (default: 80 characters) is a platform constant. Prevents full_form from becoming a definition-in-disguise.

---

## 7. Open Questions

**OQ1: Embedding Strategy**
Should the RAG embedding use the original query or the expanded query? The current decision (original query for embedding) preserves semantic fidelity — the user's intent is captured before expansion. But expanded queries may improve retrieval for documents that always spell out the full form. This requires A/B testing to resolve empirically. See also 05-red-team-critique R03.

**OQ2: User Transparency**
Should users see which terms were expanded? A "terms interpreted" indicator (e.g., a small chip in the chat UI showing "AWS → Annual Wage Supplement") would help users debug bad expansions. The cost: additional UI complexity. The benefit: faster glossary quality improvement by surfacing errors to the user. Decision deferred to Phase 2 UX review.

**OQ3: Glossary Term Versioning**
If a glossary term's `full_form` changes after a user has seen an expanded response, the response history becomes misleading. Should expanded queries be stored with the expanded form (immutable record) or reconstructed at read time (always current)? Storage with expanded form is the safer choice but increases storage overhead.

**OQ4: Per-Agent Glossary Scoping**
Different agents (HR Agent, IT Helpdesk Agent, Procurement Agent) may have conflicting acronyms. "PO" = "Purchase Order" in procurement, but "Performance Objective" in HR. Should glossary expansion be scoped to the active agent? This would prevent cross-domain false positives. Architecture impact: GlossaryExpander needs `agent_id` in its context, not just `tenant_id`.

**OQ5: Confidence Threshold for Partial Matches**
The current spec calls for exact match + alias match only. Should fuzzy matching be supported (e.g., "AWS's" matching "AWS")? Possessive and plural forms are common in natural language. This adds complexity but reduces false negatives. Recommend allowing suffix-stripped matching (remove trailing 's, s) as a Phase 1 extension.
