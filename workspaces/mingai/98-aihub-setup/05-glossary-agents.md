# Step 5 — Glossary Terms

**Actor**: Tenant Admin
**Table**: `glossary_terms`

> **Note on agents**: All 29 KB agents were created in Step 4. This step covers only glossary terms — company-specific acronyms and terms the AI must resolve before answering.

---

## 5.1 Why Glossary Matters Here

aihub2 had no formal glossary feature. Terminology interpretation was baked into each KB's system prompt individually, leading to duplication and inconsistency. In mingai, the `glossary_terms` table provides a single lookup that resolves acronyms before any query hits an agent — improving accuracy across all 29 KB agents simultaneously.

---

## 5.2 Glossary Terms to Insert

```sql
INSERT INTO glossary_terms (tenant_id, term, full_form, aliases)
VALUES
  -- Group entities
  ('<tenant_id>', 'TPC',            'Tsao Pao Chee',                              '["Tsao Pao Chee Group", "TPC Group"]'),
  ('<tenant_id>', 'IMC',            'IMC Industrial Group',                        '["IMC Group", "IMC Pte Ltd"]'),
  ('<tenant_id>', 'PSS',            'PT Pelayaran Sumber Samudra',                 '["PSS", "IMC Indonesia"]'),
  ('<tenant_id>', 'UTSE',           'Unithai Stevedoring Enterprises',             '["UTSE", "Unithai"]'),
  ('<tenant_id>', 'AT',             'Aurora Tankers Management',                   '["Aurora Tankers", "AT"]'),
  ('<tenant_id>', 'OI',             'Octave Institute',                            '["Octave Institute", "The Octave Institute"]'),
  ('<tenant_id>', 'OL',             'Octave Living',                               '["Octave Living", "Sangha Retreat", "SANGHA"]'),
  ('<tenant_id>', 'MSI',            'MSI Ships',                                   '["MSI", "MSI Ship Management"]'),

  -- Programs and initiatives
  -- NOTE: MEP has two meanings. Merged into one row — UNIQUE(tenant_id, term) constraint forbids two 'MEP' rows.
  ('<tenant_id>', 'MEP',            'Mindful Emotion Program / Management Excellence Programme', '["MEP Coaching", "Mindful Emotion", "Management Excellence"]'),
  ('<tenant_id>', 'GIC',            'Group Investment Committee',                  '["Investment Committee", "IC"]'),
  ('<tenant_id>', 'Project Gemini', 'Oracle ERP Implementation Project (TPC)',     '["Gemini", "Oracle Gemini"]'),
  ('<tenant_id>', 'OKR',            'Objectives and Key Results',                  '[]'),

  -- Functions and departments
  ('<tenant_id>', 'HSSE',           'Health, Safety, Security and Environment',    '["HSE", "QHSSE", "HSSEQ"]'),
  ('<tenant_id>', 'CCC',            'Communication, Community and Culture',        '[]'),
  ('<tenant_id>', 'P&O',            'People and Organisation',                     '["People & Organisation", "HR", "Human Resources"]'),
  ('<tenant_id>', 'GSD',            'Group Strategic Development',                 '[]'),

  -- Systems and tools
  ('<tenant_id>', 'Infor',          'Infor Maritime ERP System',                   '["Infor Maritime", "Infor EAM"]'),
  ('<tenant_id>', 'Oracle Fusion',  'Oracle Fusion Cloud ERP',                     '["Oracle", "Fusion", "Cloud ERP"]');
```

> Note: `MEP` had two meanings — "Mindful Emotion Program" (coaching context) and "Management Excellence Programme" (leadership context). These have been merged into one row because the `glossary_terms` table enforces UNIQUE(tenant_id, term). Both meanings are listed in `full_form` separated by `/`. The GlossaryExpander will return both and let context disambiguate.

> **Phase timing**: The `glossary_terms` table exists in Phase 1 and the SQL below can be run immediately to pre-load terms. However, the GlossaryExpander injection pipeline (which makes these terms active in AI responses) ships in **Phase B Sprint B2** (Weeks 10-12 of the tenant admin plan). Terms inserted now will have no effect on AI responses until Phase B is deployed.

---

## 5.3 Glossary Miss Signals

After go-live, monitor the `glossary_miss_signals` table for unresolved terms appearing in user queries. Common candidates to add post-launch:

- Company codes (e.g., `IMCIG`, `ATMS`, `PLB`)
- Vessel names
- Port abbreviations (SGP, PLM, MNL, etc.)
- Project-specific codes from Oracle / Infor

---

## Verification Checklist

- [ ] 18 glossary terms inserted (MEP merged to 1 row — was 19 but duplicate removed)
- [ ] No duplicate term conflicts (check UNIQUE constraint on `tenant_id, term`)
- [ ] MEP row contains both meanings in `full_form` (merged)
- [ ] **Phase B**: Test glossary expansion once GlossaryExpander pipeline ships
- [ ] Post-launch: review `glossary_miss_signals` after first week of usage
