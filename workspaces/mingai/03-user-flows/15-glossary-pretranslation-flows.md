# 15 — Glossary Pre-Translation User Flows

**Feature**: Glossary Inline Expansion
**Analysis refs**: 14-01 through 14-05
**Plan ref**: 09-glossary-pretranslation-plan.md

---

## Overview

Four user flows covering the glossary pre-translation lifecycle: transparent query expansion, tenant admin glossary management, analytics review, and edge case handling.

---

## Flow 1: Transparent Query Expansion (End User, Happy Path)

**Actor**: End user
**Trigger**: User submits a query containing a known glossary term

```
User types: "What is the AWS payout for part-time employees?"
  │
  ├─ Chat router receives query
  │
  ├─ Intent detection runs on ORIGINAL query
  │    └─ Routes to HR agent
  │
  ├─ RAG embedding runs on ORIGINAL query: "What is the AWS payout for part-time employees?"
  │    └─ Vector search retrieves docs containing "AWS" (acronym preserved in original)
  │
  ├─ GlossaryExpander runs (parallel with RAG, uses Redis cache):
  │    ├─ Scan for glossary matches: "AWS" → found → full_form: "Annual Wage Supplement"
  │    ├─ "employees" → no match
  │    └─ Expanded query: "What is the AWS (Annual Wage Supplement) payout for part-time employees?"
  │
  ├─ LLM call uses EXPANDED query + RAG context:
  │    └─ Response: "The Annual Wage Supplement (AWS) for part-time employees is typically..."
  │                  (LLM uses full term naturally in response)
  │
  ├─ Analytics event fired: glossary_term_matched { term_id, term: "AWS", query_id }
  │
  └─ (Optional) UI indicator: small tooltip "1 term interpreted" visible in chat
```

**User experience**: Response is accurate for domain terminology. User doesn't need to know they should spell out "AWS". No visible interruption.

---

## Flow 2: Term Not in Glossary (End User, Fallback)

**Actor**: End user
**Trigger**: User uses a term that's not in the glossary

```
User types: "What's the FY25 headcount plan?"
  │
  ├─ GlossaryExpander: "FY25" → no match in glossary → no expansion
  │
  ├─ Query sent to LLM as-is: "What's the FY25 headcount plan?"
  │
  └─ LLM response: either knows "FY25" from training data, or asks for clarification
```

**State**: No expansion. No error. GlossaryExpander is silent on no-match.
**Improvement path**: Tenant admin can add "FY25" to glossary → future queries expand automatically.

---

## Flow 3: Tenant Admin Adds a New Term (Admin, Happy Path)

**Actor**: Tenant admin
**Location**: Tenant Admin > Glossary > Add Term

```
Admin navigates to Tenant Admin > Glossary
  │
  ├─ Clicks "+ Add Term"
  │
  ├─ Form: Term [CPF], Full Form [Central Provident Fund], Definition [Singapore mandatory...],
  │         Category [HR], Language [English]
  │
  ├─[Admin clicks "Save as Approved"] (Starter/Professional tier — no approval workflow)
  │    ├─ POST /admin/glossary → creates term with status: approved
  │    ├─ Redis cache invalidated: mingai:{tenant_id}:glossary:approved
  │    └─ Confirmation toast: "Term 'CPF' added and active"
  │
  └─ Next user query containing "CPF" → expands to "CPF (Central Provident Fund)"
```

**Latency**: Cache invalidation is immediate. Next query after cache refresh picks up the new term (within 1 hour if cache not invalidated, instant if invalidated).

---

## Flow 4: Ambiguous Term Expansion (End User, Edge Case)

**Actor**: End user
**Trigger**: User types a term that matches multiple glossary entries

```
Tenant glossary:
  - "MAS" → "Monetary Authority of Singapore" (category: compliance)
  - "MAS" → "Management Accounting System" (category: finance) [hypothetical conflict]

User types: "What are the MAS guidelines for loan disclosure?"
  │
  ├─ GlossaryExpander: "MAS" → 2 matches found
  │
  ├─[Agent context = Compliance agent]
  │    ├─ Score MAS (compliance) higher → expand to "MAS (Monetary Authority of Singapore)"
  │    └─ Single winner → proceed with expansion
  │
  └─[Agent context = unknown / tie] → NO expansion (no-op, safer than wrong expansion)
       └─ Query sent to LLM as-is: "What are the MAS guidelines for loan disclosure?"
```

---

## Edge Cases

### EC-1: Term at Query Start

"AWS affects CPF calculations" → "AWS (Annual Wage Supplement) affects CPF (Central Provident Fund) calculations"
First occurrence of each term expanded.

### EC-2: Same Term Multiple Times

"AWS for permanent employees vs AWS for contract employees" → "AWS (Annual Wage Supplement) for permanent employees vs AWS for contract employees"
Only first occurrence expanded (no repetition of parenthetical).

### EC-3: Full Form Already Spelled Out

"Annual Wage Supplement (AWS) payments" → no expansion needed. GlossaryExpander detects full form already present → skip.

### EC-4: Term in Title Case vs All Caps

Glossary term: "it" (Information Technology). User query: "What IT systems require approval?"
GlossaryExpander: "IT" (uppercase) → matches. "it" (lowercase in middle of sentence) → no match (requires uppercase-only for 2-char acronyms to avoid pronoun false positives).
