# 09 — Glossary Pre-Translation Implementation Plan

**Feature**: Glossary Inline Expansion (replacing Layer 6 system prompt injection)
**Analysis refs**: 14-01 through 14-05
**Architecture ref**: 37-glossary-pretranslation-architecture.md

## 1. Scope

Replace glossary system prompt injection (Layer 6) with inline query expansion. The glossary term is preserved in the query, full_form appended in parentheses. No change to glossary data model, admin UI, or cache strategy.

**What changes**: GlossaryExpander component (new), SystemPromptBuilder Layer 6 removal, query pipeline integration
**What stays**: glossary_terms table, Redis cache, admin CRUD UI, analytics events, CSV import/export

## 2. Sprint Plan

### Sprint 1 — GlossaryExpander Component (Week 1)

| Task                                                                                            | Effort | Notes                                                                                              |
| ----------------------------------------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------- |
| Implement `GlossaryExpander.expand(query, tenant_id) -> str`                                    | 4h     | Exact + alias match, case-insensitive                                                              |
| Handle multi-word term matching                                                                 | 2h     | Longest match wins                                                                                 |
| Handle ambiguity (multiple matches for same string)                                             | 2h     | Skip on ambiguity (no-op)                                                                          |
| CJK support: full-width parentheses for CJK queries                                             | 2h     | Unicode block detection                                                                            |
| Deduplication: expand first occurrence only                                                     | 1h     |                                                                                                    |
| Full_form length guard: skip if full_form > 50 chars                                            | 0.5h   | Security: no long injections                                                                       |
| Implement stop-word exclusion list (platform config): block common English words from expansion | 1h     | Hardcoded list: as, it, or, by, at, be, do, go, in, is, on, to, up, us, we, no, so, an, am, my, of |
| Uppercase-only rule for ≤3 char terms: only expand if token appears in ALL CAPS in query        | 1h     | Prevents pronoun false positives                                                                   |
| "Terms interpreted" indicator in chat (mandatory): shows all expansions applied below response  | 3h     | Mandatory Day 1 — not optional. User can click to see full expansion list                          |
| Unit tests (20 tests)                                                                           | 4h     | All edge cases                                                                                     |

### Sprint 2 — Pipeline Integration (Week 2)

| Task                                                         | Effort | Notes                                         |
| ------------------------------------------------------------ | ------ | --------------------------------------------- |
| Wire GlossaryExpander into chat preprocessing pipeline       | 2h     | After intent detection                        |
| Confirm RAG embedding uses ORIGINAL query (pre-expansion)    | 1h     | Critical: preserve retrieval accuracy         |
| Confirm LLM call uses EXPANDED query                         | 1h     |                                               |
| Remove Layer 6 (glossary injection) from SystemPromptBuilder | 2h     |                                               |
| Preserve `glossary_term_matched` analytics event firing      | 1h     | Decouple from injection                       |
| Integration tests (10 tests)                                 | 4h     | Full pipeline: original → RAG, expanded → LLM |

### Sprint 3 — Migration & Observability (Week 3)

| Task                                                                      | Effort | Notes                      |
| ------------------------------------------------------------------------- | ------ | -------------------------- |
| Add `glossary_expansions_applied` field to query response metadata        | 1h     | For debugging/transparency |
| Tenant admin: glossary analytics updated (expansion count vs match count) | 2h     |                            |
| Rollout flag: `glossary_pretranslation_enabled` per tenant                | 1h     | Gradual rollout            |
| Integration tests for mixed scenarios                                     | 2h     |                            |

## 3. Definition of Done

- [ ] `GlossaryExpander` operational with full edge case coverage
- [ ] Layer 6 removed from SystemPromptBuilder
- [ ] RAG embedding confirmed to use original query
- [ ] LLM call confirmed to use expanded query
- [ ] Analytics events preserved
- [ ] Token budget freed (500 tokens): documented in system config
- [ ] Stop-word exclusion list enforced (common English words never expanded)
- [ ] Uppercase-only rule enforced for ≤3 char acronyms
- [ ] "Terms interpreted" indicator visible on every response with at least one expansion
- [ ] All unit tests passing (20+)
- [ ] Integration tests passing (10+)
- [ ] Rollout flag operational for gradual deployment

## 4. Token Budget Update

After this plan completes, the system prompt overhead changes:

- Before: ~1,300 tokens (including 500 glossary)
- After: ~950 tokens (team memory added at 150, glossary removed)
- Net RAG gain at 2K: +500 tokens (700 → 1,200 for RAG before team memory; 1,050 after team memory added)

Update all token budget documentation after deployment.

## 5. Risks

| Risk                                                               | Severity | Mitigation                                                           |
| ------------------------------------------------------------------ | -------- | -------------------------------------------------------------------- |
| Existing tenant behavior changes (responses differ post-migration) | Medium   | Rollout flag per tenant; validate with pilot tenants first           |
| Acronym false positives (pronoun "it" matched to "IT")             | Medium   | Minimum term length: 2 chars uppercase-only for single-word acronyms |
| Query length growth affecting context window                       | Low      | Max 10 expansions per query; each adds ~3-6 words                    |
