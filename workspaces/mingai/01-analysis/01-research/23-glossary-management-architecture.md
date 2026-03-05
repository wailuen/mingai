# 23. Tenant-Level Glossary Management Architecture

> **Status**: Architecture Design
> **Date**: 2026-03-05
> **Purpose**: Define the complete architecture for tenant-level glossary management — how domain-specific terminology is stored, surfaced, and injected into the RAG pipeline.
> **Source**: Extends existing mingai `glossary` module analysis from `01-research/01-service-architecture.md`.

---

## 1. What Is the Tenant Glossary?

A tenant glossary is a curated dictionary of organization-specific terms, acronyms, and domain concepts that:

1. **Help the LLM understand domain language**: "BIPO" means HRMS platform, not "bipo" in another context; "LTV" means loan-to-value in financial context, not lifetime value.
2. **Improve query routing**: Glossary terms help intent detection correctly route queries to the right indexes.
3. **Reduce hallucination**: When the LLM sees a defined term, it uses the canonical definition rather than guessing.
4. **Enable multilingual disambiguation**: A term may have different meanings in different languages; the glossary provides authoritative translations.

### What a Glossary Entry Contains

```json
{
  "id": "gloss-uuid",
  "tenant_id": "tenant-uuid",
  "term": "LTV",
  "full_form": "Loan-to-Value",
  "definition": "The ratio of a loan amount to the appraised value of the asset used as collateral.",
  "category": "finance",
  "aliases": ["loan to value", "loan-to-value ratio"],
  "related_terms": ["LTV ratio", "collateral", "mortgage"],
  "language": "en",
  "translations": {
    "zh": {
      "term": "贷款价值比",
      "definition": "贷款金额与抵押资产评估价值之比。"
    },
    "ms": { "term": "Nisbah Pinjaman kepada Nilai" }
  },
  "source_index_ids": ["index-finance", "index-mortgages"],
  "created_by": "user-uuid",
  "approved_by": "admin-uuid",
  "status": "approved", // draft | approved | archived
  "created_at": "2026-03-05T00:00:00Z",
  "updated_at": "2026-03-05T00:00:00Z"
}
```

---

## 2. How the Glossary is Used in the RAG Pipeline

The glossary is injected at **two points** in the RAG pipeline:

### 2a. Query Enrichment (Pre-Search)

Before intent detection and embedding, the query passes through the `GlossaryEnricher`:

```python
class GlossaryEnricher:
    async def enrich(self, query: str, tenant_id: str) -> EnrichedQuery:
        """
        1. Scan query for known glossary terms (exact match + alias match).
        2. Return matched terms — do NOT concatenate with user query.

        SECURITY: Glossary context MUST be injected into the LLM system message,
        not appended to the user query string. Concatenating user-controlled query
        content with injected context creates a prompt injection attack surface:
        a malicious user could craft queries that spoof or override the domain context.

        The EnrichedQuery.matched_terms are consumed by the prompt builder, which
        injects them into the system message boundary — structurally separated from
        the user query (user message).
        """
        matched_terms = await self.glossary_repo.find_matches(
            query=query,
            tenant_id=tenant_id,
        )
        return EnrichedQuery(original=query, terms=matched_terms)
        # The `enriched` field is removed — consumers use matched_terms only.
```

### 2b. LLM Prompt Injection (Pre-Synthesis)

Before sending context to the LLM for answer synthesis, relevant glossary terms are injected into the system prompt:

```python
SYSTEM_PROMPT_TEMPLATE = """
You are an AI assistant for {org_name}.

{glossary_section}

When answering, use the domain terminology above precisely. Do not redefine these terms.
"""

def build_system_prompt(tenant: Tenant, matched_terms: list[GlossaryTerm]) -> str:
    if matched_terms:
        glossary_section = "Domain Glossary (use these definitions):\n" + "\n".join([
            f"- {t.term}: {t.definition}"
            for t in matched_terms
        ])
    else:
        glossary_section = ""

    return SYSTEM_PROMPT_TEMPLATE.format(
        org_name=tenant.display_name,
        glossary_section=glossary_section,
    )
```

### 2c. Source Attribution Enhancement

When a source document mentions a glossary term, the source attribution UI can show a tooltip with the term definition:

```
[Source: Mortgage Policy 2025.pdf, page 3]
↳ Mentions: LTV ℹ (Loan-to-Value: The ratio of a loan amount to the appraised value...)
```

---

## 3. Existing mingai Implementation

The mingai codebase has a `glossary` module with:

- `GET/POST/PUT/DELETE /admin/glossary` endpoints
- `GlossaryEntry` model with: `id`, `term`, `definition`, `category`, `aliases` (array), `created_at`
- Basic CRUD without approval workflow
- No multi-tenant isolation (global glossary, not per-tenant)
- No translation support
- No RAG pipeline integration (stored but not used in prompts)

**Gaps to fix in mingai multi-tenant:**

1. Add `tenant_id` to all glossary records + RLS enforcement
2. Add approval workflow (`draft → approved`)
3. Add translation support for multilingual enterprises
4. Wire into RAG pipeline (query enrichment + prompt injection)
5. Add import/export (CSV bulk management)
6. Add per-index scoping (optional: only inject terms relevant to matched indexes)

---

## 4. Data Model

### PostgreSQL Table: `glossary_terms`

```sql
CREATE TABLE glossary_terms (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    term            TEXT NOT NULL,
    full_form       TEXT,
    definition      TEXT NOT NULL,
    category        TEXT,
    aliases         TEXT[] DEFAULT '{}',
    related_terms   TEXT[] DEFAULT '{}',
    language        TEXT NOT NULL DEFAULT 'en',
    translations    JSONB DEFAULT '{}',
    source_index_ids UUID[] DEFAULT '{}',  -- empty = applies to all indexes
    status          TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'archived')),
    created_by      UUID REFERENCES users(id),
    approved_by     UUID REFERENCES users(id),
    approved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tenant isolation via RLS
ALTER TABLE glossary_terms ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON glossary_terms
    USING (tenant_id = current_setting('app.tenant_id')::UUID);

-- Efficient term lookup (full-text + exact + trigram for multilingual)
CREATE INDEX idx_glossary_terms_tenant ON glossary_terms(tenant_id);
CREATE INDEX idx_glossary_terms_status ON glossary_terms(tenant_id, status);

-- Latin-script FTS (English, Malay, etc.): use 'simple' config for language-agnostic matching
-- 'english' config applies English stemming and would corrupt non-English terms.
-- 'simple' does only lowercasing + whitespace splitting — safe for all Latin-script languages.
CREATE INDEX idx_glossary_terms_fts ON glossary_terms USING gin(
    to_tsvector('simple', term || ' ' || coalesce(full_form, '') || ' ' || coalesce(array_to_string(aliases, ' '), ''))
);

-- CJK and other non-Latin-script languages: use trigram index (pg_trgm extension required).
-- Chinese, Japanese, Korean terms cannot be tokenized by any standard FTS config.
-- Trigram matching handles substring matching across all scripts.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_glossary_terms_trigram ON glossary_terms USING gin(
    (term || ' ' || coalesce(full_form, '') || ' ' || coalesce(array_to_string(aliases, ' '), '')) gin_trgm_ops
);
-- The GlossaryRepo.find_matches() uses FTS for Latin-script queries and
-- trigram similarity for CJK queries (detected via unicode block analysis).
```

### Redis Cache

```
Key:  mingai:{tenant_id}:glossary:approved
Type: Hash (term → JSON serialized GlossaryTerm)
TTL:  1 hour (refreshed on any CRUD operation)
```

Approved glossary terms are cached to avoid database lookups on every query. Cache invalidated when any term is created, updated, approved, or archived.

---

## 5. Admin UI: Glossary Management

### Term List View

```
[Glossary Management]                           [+ Add Term]  [Import CSV]  [Export CSV]

Filter: [All Categories ▼]  [All Status ▼]  [Search terms...]

| Term    | Full Form       | Category | Status   | Used in          | Last Updated |
|---------|-----------------|----------|----------|------------------|--------------|
| LTV     | Loan-to-Value   | Finance  | Approved | Finance, Mortgage| 2026-03-01   |
| KYC     | Know Your Customer | Compliance | Approved | All indexes   | 2026-02-28   |
| BIPO    | BIPO HRMS       | HR       | Draft    | HR               | 2026-03-05   |
| EBITDA  | —               | Finance  | Approved | Finance          | 2026-02-15   |
```

### Term Detail / Edit Form

```
Term: [LTV                ]  Full Form: [Loan-to-Value      ]
Category: [Finance ▼]        Status: [Approved ▼]
Language: [English (en) ▼]

Definition:
[The ratio of a loan amount to the appraised value of the asset used as collateral,
 expressed as a percentage. E.g., a $80K loan on a $100K property = 80% LTV.       ]

Aliases (comma-separated):
[loan to value, loan-to-value ratio, LTV ratio                                       ]

Related Terms (comma-separated):
[collateral, mortgage, LTV covenant                                                   ]

Applies to indexes:
[✓] Finance Index    [✓] Mortgage Index    [ ] HR Index    [ ] All Indexes

Translations:
  [+ Add Translation]
  Chinese (zh): Term [贷款价值比] Definition [贷款金额与抵押资产评估价值之比。]

[Save as Draft]  [Submit for Approval]     [Cancel]
```

### Approval Workflow (Enterprise / Compliance tenants)

```
Tenant Admin Settings > Glossary > Approval Workflow: [Enabled ▼]

When enabled:
- Users with glossary:write can create terms as "Draft"
- Users with glossary:approve can approve/reject drafts
- Approved terms are injected into RAG pipeline
- Draft terms are NOT injected (visible only in admin UI)

Notification: Approver gets email when new draft submitted
```

**Feature flag**: Approval workflow is optional. Default for Starter/Professional = no approval (immediate publish). Enterprise can enable it.

---

## 6. API Endpoints

### Tenant Admin Endpoints

| Endpoint                              | Method | Description                                          |
| ------------------------------------- | ------ | ---------------------------------------------------- |
| `/api/v1/admin/glossary`              | GET    | List terms (with filter/search, paginated)           |
| `/api/v1/admin/glossary`              | POST   | Create term (status: draft or approved per settings) |
| `/api/v1/admin/glossary/{id}`         | GET    | Get single term                                      |
| `/api/v1/admin/glossary/{id}`         | PUT    | Update term                                          |
| `/api/v1/admin/glossary/{id}`         | DELETE | Soft-delete (→ archived)                             |
| `/api/v1/admin/glossary/{id}/approve` | POST   | Approve draft term                                   |
| `/api/v1/admin/glossary/{id}/archive` | POST   | Archive approved term                                |
| `/api/v1/admin/glossary/import`       | POST   | Bulk import from CSV                                 |
| `/api/v1/admin/glossary/export`       | GET    | Export all terms as CSV                              |
| `/api/v1/admin/glossary/analytics`    | GET    | Usage stats (how often each term matched)            |

### Internal RAG Pipeline Endpoints (not user-facing)

| Endpoint                                   | Method | Description                             |
| ------------------------------------------ | ------ | --------------------------------------- |
| `/api/v1/internal/glossary/enrich`         | POST   | Enrich a query with matching terms      |
| `/api/v1/internal/glossary/terms/approved` | GET    | Get approved terms for prompt injection |

---

## 7. CSV Import/Export Format

### CSV Import Columns

```
term,full_form,definition,category,aliases,language,status
LTV,Loan-to-Value,"The ratio of a loan amount to the appraised value...",Finance,"loan to value|loan-to-value ratio",en,approved
KYC,Know Your Customer,"Customer identity verification process required by regulations",Compliance,,en,approved
```

- Aliases delimited by `|` within the column
- Status defaults to `draft` if not specified
- `full_form` and `category` are optional
- `language` defaults to `en`

### Import Validation

- Duplicate `term` within tenant → update existing record (upsert)
- Missing required field (`term`, `definition`) → row error, skip row, report
- Invalid `status` value → default to `draft`
- Max 5,000 terms per import batch

---

## 8. Glossary Analytics

Track term usage to prioritize maintenance:

```python
# Stored in usage_events table (existing analytics infrastructure)
{
    "event_type": "glossary_term_matched",
    "tenant_id": "tenant-uuid",
    "term_id": "gloss-uuid",
    "term": "LTV",
    "query_id": "conv-uuid/msg-uuid",
    "matched_at": "2026-03-05T10:30:00Z"
}
```

Analytics dashboard shows:

- **Top matched terms** (last 30 days): which glossary terms are most frequently triggered
- **Terms never matched**: candidates for archiving or re-definition
- **Terms pending approval**: approval queue metric
- **Coverage**: percentage of queries that matched at least one glossary term

---

## 9. Integration with Multi-Tenant Platform

### Tenant Plan Features

| Feature                   | Starter | Professional      | Enterprise      |
| ------------------------- | ------- | ----------------- | --------------- |
| Max glossary terms        | 100     | 1,000             | Unlimited       |
| Multilingual translations | No      | Yes (5 languages) | Yes (unlimited) |
| Approval workflow         | No      | No                | Yes             |
| CSV import/export         | Yes     | Yes               | Yes             |
| Per-index scoping         | No      | Yes               | Yes             |
| Analytics                 | Basic   | Full              | Full            |

### Provisioning

When a new tenant is provisioned, the glossary is initialized empty. No pre-seeding. Tenants build their own glossary.

Platform admin cannot see or modify tenant glossary terms. Each tenant's glossary is fully isolated via RLS.

---

**Document Version**: 1.0
**Last Updated**: 2026-03-05
