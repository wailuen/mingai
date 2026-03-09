# Glossary Management User Flows

**Personas**: Tenant Admin, Glossary Editor, Knowledge Worker (consumer)
**Scope**: Creating, managing, and using the tenant-level glossary
**Roles**: `tenant_admin`, users with `glossary:write` or `glossary:approve` permissions
**Date**: 2026-03-05

---

## Phase Mapping

| Flow | Flow Name                     | Built in Phase | Notes                                  |
| ---- | ----------------------------- | -------------- | -------------------------------------- |
| 01   | First Glossary Setup          | Phase 1        | Tenant admin creates initial terms     |
| 02   | Add / Edit Term               | Phase 1        | CRUD for individual terms              |
| 03   | Bulk Import via CSV           | Phase 1        | Upload many terms at once              |
| 04   | Approval Workflow             | Phase 4        | Enterprise: draft → approved flow      |
| 05   | Glossary in Action (End User) | Phase 1        | How the end user sees glossary effects |
| 06   | Glossary Analytics Review     | Phase 2        | Admin reviews term usage stats         |
| 07   | Bulk Archive / Cleanup        | Phase 2        | Remove outdated terms                  |

---

## 1. First Glossary Setup

**Trigger**: Tenant admin logs in for the first time and sees Knowledge Base Setup wizard.

```
Start: Tenant Admin completes index setup, wizard suggests glossary
  |
  v
[Onboarding Wizard — Step 4: Domain Glossary]

"Help the AI understand your organization's terminology.
 Add terms that are specific to your industry or company."

Examples shown:
  • "What terms does your organization use that might be misunderstood?"
  • "Acronyms? Internal project names? Industry jargon?"

[ Skip for now ]   [ Add Terms Now ]

  +-- BRANCH: Skip
  |     └── Wizard proceeds. Glossary stays empty.
  |         "You can add glossary terms anytime in Admin > Glossary."
  |
  +-- BRANCH: Add Terms Now
        |
        v
      [Inline glossary editor — simplified version]

      Term: [            ]  Definition: [                                    ]
                                         [+ Add another term]

      Quick add:
        [LTV] [Loan-to-Value] ← pre-filled from common finance terms (if finance index detected)

      [Save and Continue]

        └── Saves terms as "approved" (no approval workflow on Starter/Pro)
        └── Shows: "3 terms added. The AI will use these when answering questions."
        └── Wizard proceeds to next step
```

---

## 2. Add / Edit Individual Term

**Trigger**: Admin navigates to Admin Panel > Glossary > [+ Add Term] or clicks existing term.

```
[Glossary Management]

[+ Add Term]  [Import CSV]  [Export CSV]

Filter: [All ▼]  [All Status ▼]  [Search: ________]

| Term   | Full Form            | Category   | Status   | Actions      |
|--------|----------------------|------------|----------|--------------|
| LTV    | Loan-to-Value        | Finance    | Approved | [Edit] [⋯]   |
| KYC    | Know Your Customer   | Compliance | Approved | [Edit] [⋯]   |
| BIPO   | BIPO HRMS Platform   | HR         | Draft    | [Edit] [⋯]   |

  |
  +-- FLOW: Add New Term
  |     |
  |     v
  |   [Add Term Form]
  |
  |   Term *:          [LTV                              ]
  |   Full Form:       [Loan-to-Value                    ]
  |   Category:        [Finance               ▼]
  |   Language:        [English (en)          ▼]
  |
  |   Definition *:
  |   [The ratio of a loan amount to the appraised value of the asset used as collateral,
  |    expressed as a percentage. Higher LTV = higher risk.                              ]
  |
  |   Aliases (one per line or comma-separated):
  |   [loan to value, loan-to-value ratio, LTV ratio                                    ]
  |
  |   Applies to indexes: (leave empty = all indexes)
  |   [✓] Finance Index    [✓] Mortgage Index    [ ] HR Index
  |
  |   Translations:
  |   [+ Add Translation]
  |   Language: [Chinese (zh) ▼]
  |   Term: [贷款价值比    ]  Definition: [贷款金额与抵押资产评估价值之比。       ]
  |
  |   [Save as Draft]  [Publish Immediately]  [Cancel]
  |
  |     +-- CASE: Approval workflow OFF (Starter/Professional)
  |     |     "Publish Immediately" → status: approved → active in RAG immediately
  |     |
  |     +-- CASE: Approval workflow ON (Enterprise)
  |           "Publish Immediately" → disabled; only "Save as Draft" available
  |           → term goes to approval queue
  |           → approver notified by email
  |
  +-- FLOW: Edit Existing Term
        |-- Click term name or [Edit] button
        └── Same form as Add, pre-filled with current values
            Any change to an approved term → status reverts to "draft" if approval workflow on
```

---

## 3. Bulk Import via CSV

**Trigger**: Admin clicks [Import CSV] on Glossary page.

```
[Import Glossary Terms]

Step 1: Download template
  [Download CSV Template]
  → Provides: term,full_form,definition,category,aliases,language,status

Step 2: Prepare your CSV file
  Guidelines shown:
  • "term" and "definition" are required
  • Separate multiple aliases with | (pipe character)
  • Status: "approved" or "draft" (defaults to draft if omitted)
  • Language: ISO 639-1 code (en, zh, ms, etc.)
  • Max 500 rows per import (platform limit: 500 active terms per tenant)
  • Import will reject rows that would exceed your active term limit

Step 3: Upload file
  [Drag CSV file here or click to browse]
  └── Accepts: .csv, .xlsx

  |
  v
[Upload processing — preview shown]

Preview (first 5 rows):

| Term    | Full Form            | Definition              | Status   | Aliases            |
|---------|----------------------|-------------------------|----------|--------------------|
| LTV     | Loan-to-Value        | Ratio of loan to asset  | approved | loan to value      |
| KYC     | Know Your Customer   | Customer identity verif.| approved |                    |
| EBITDA  | Earnings Before...   | Operating profit metric | approved | ebitda margin      |
| ???BIPO | (missing)            | (missing definition)    | ERROR    | ← Missing required |
| TBD     |                      | To be determined        | draft    |                    |

Validation Summary:
  ✓ 4,987 rows valid
  ✗ 13 rows with errors (see details)

  Error details:
    Row 4: Missing "definition" field
    Row 17: Invalid language code "ENG" (use "en")
    Row 89: Term "LTV" already exists — will UPDATE existing record
    ...

  Options for conflicts (existing terms):
    (•) Update existing terms
    ( ) Skip duplicates (keep existing)

[Import Valid Rows (4,987)]  [Fix Errors First]  [Cancel]

  |
  v
[Import progress]
  Processing ████████░░ 4,234 / 4,987 rows...

  |
  v
[Import complete]

✓ 4,974 terms imported successfully
⚠  13 terms skipped (errors)

If approval workflow is ON: "All imported terms saved as Draft. Review in approval queue."
If approval workflow is OFF: "All terms immediately active in search."

[Download Error Report]   [View Glossary]
```

---

## 4. Approval Workflow (Enterprise)

**Trigger**: Enterprise tenant has enabled "Require approval before publishing glossary terms".

### 4a. Submitter Flow (non-admin user with `glossary:write`)

```
[User submits new term]
  Term: "TWRR"
  Definition: "Time-weighted rate of return — used in portfolio performance measurement"
  Category: Finance
  Status: saved as "Draft"

  → Email sent to all users with glossary:approve permission:
    Subject: "New glossary term submitted: TWRR"
    "A new term has been submitted for approval. Review it in the Admin Panel."
    [Review Now →]
```

### 4b. Approver Flow

```
[Admin Panel > Glossary > Pending Approval (3)]

| Term  | Submitted by    | Submitted at | Definition preview                    | Actions                    |
|-------|-----------------|--------------|---------------------------------------|----------------------------|
| TWRR  | alice@acme.com  | 2026-03-05   | "Time-weighted rate of return..."     | [Approve] [Reject] [Edit]  |
| BIPO  | bob@acme.com    | 2026-03-04   | "BIPO HR Management System..."        | [Approve] [Reject] [Edit]  |
| PMVP  | carol@acme.com  | 2026-03-03   | "Platform minimum viable product..."  | [Approve] [Reject] [Edit]  |

  |
  +-- FLOW: Approve
  |     [Confirm approval?]  [Approve]
  |     → status: approved → active in RAG immediately
  |     → submitter notified: "Your term 'TWRR' was approved."
  |
  +-- FLOW: Reject
  |     [Rejection reason (optional): ___________________________]
  |     [Reject]
  |     → status: archived
  |     → submitter notified: "Your term 'PMVP' was not approved. Reason: [reason]"
  |
  +-- FLOW: Edit then Approve
        [Click Edit → modify definition → Approve]
        → Edited version becomes approved
        → Original submitter notified of modification
```

---

## 5. Glossary in Action — End User Experience

**Trigger**: Knowledge worker submits a query that contains a glossary term.

```
[User types query in chat]
  "What is the current LTV requirement for new mortgage applications?"
  [Send]

  |
  v
[System enriches query with matching glossary terms — invisible to user]
  Matched: LTV → "Loan-to-Value: The ratio of a loan amount to the appraised value..."

  |
  v
[AI searches indexes with enriched context]
  Searching: Finance Index, Mortgage Index

  |
  v
[AI generates response]

  Based on current mortgage policy documents, the LTV requirement for new mortgage
  applications is 85% for residential properties and 75% for commercial properties.
  This applies to all new applications submitted after January 2026.

  Sources:
  • Mortgage Policy 2026.pdf (Finance Index) — page 4  ▲ 0.94 relevance
  • Credit Guidelines Q1 2026.docx — section 3.2      ▲ 0.91 relevance
```

**What the user sees**:

- Response uses "LTV" correctly in context — no explanation needed in the response because the user already knows the term
- Source documents reference LTV correctly without the AI needing to define it in the answer
- Clean, precise response without unnecessary definition preamble

**What the user does NOT see** (invisible background enrichment):

- The query was enriched with "LTV = Loan-to-Value ratio" context
- The system prompt contained "Domain Glossary: LTV: The ratio of a loan amount..."
- These make the AI precise without cluttering the response

---

## 6. Glossary Analytics Review

**Trigger**: Admin navigates to Admin Panel > Glossary > Analytics.

```
[Glossary Analytics]  Last 30 days

Top Matched Terms:
  | Term    | Matches | Queries Helped | Definition Coverage |
  |---------|---------|----------------|---------------------|
  | LTV     | 2,341   | 89%            | High ●●●●●          |
  | KYC     | 1,892   | 91%            | High ●●●●●          |
  | EBITDA  | 987     | 82%            | Medium ●●●●○        |
  | BIPO    | 234     | 94%            | High ●●●●●          |
  | TWRR    | 12      | 67%            | Low ●●○○○           |

Terms Never Matched (consider reviewing):
  | Term    | Added       | Never matched in 60+ days |
  |---------|-------------|---------------------------|
  | PMVP    | 2026-01-15  | Consider archiving?        |
  | BEPS    | 2026-02-01  | Consider archiving?        |

Total coverage:
  68% of queries matched at least one glossary term ← up from 52% last month

  [Export Analytics]
```

---

## 7. Bulk Archive / Cleanup

**Trigger**: Admin wants to clean up stale or incorrect terms.

```
[Glossary Management > Bulk Actions]

Select: [All] [None] [Never Matched] [Outdated (>1 year)]

☑ PMVP   — never matched — Added 2026-01-15 — [Platform Minimum Viable Product]
☑ BEPS   — never matched — Added 2026-02-01 — [Base Erosion and Profit Shifting]
☐ LTV    — 2,341 matches — Active

[Archive Selected (2)]  [Delete Selected]

  |
  v
[Confirm bulk archive]
  "Archive 2 terms? They will be hidden from the AI but not deleted.
   You can restore them later."

  [Archive 2 Terms]   [Cancel]

  |
  v
✓ 2 terms archived. Removed from AI context immediately.
  [Undo]   [Done]
```

---

**Document Version**: 1.0
**Last Updated**: 2026-03-05
