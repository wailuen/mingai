# Product Doc Audit — aihub2 Setup Guide vs mingai Implementation

**Date**: 2026-03-07
**Docs audited**: `02-plans/05-06-09-10`, `03-user-flows/12`, `01-analysis/11-tenant-admin/04`
**Verdict per file**: ✓ Correct | ⚠ Needs note | ✗ Error

---

## Summary

| File                    | Status | Issues                                          |
| ----------------------- | ------ | ----------------------------------------------- |
| `01-tenant-creation.md` | ⚠      | LLM profile creation vs assignment ambiguity    |
| `02-users.md`           | ✓      | Fully correct                                   |
| `03-teams.md`           | ⚠      | Teams UI is Phase B — note SQL-direct approach  |
| `04-knowledge-base.md`  | ⚠      | Team→agent RBAC enforcement is Phase B          |
| `05-glossary-agents.md` | ✗      | Duplicate `MEP` term violates UNIQUE constraint |

---

## File-by-File Findings

### 01-tenant-creation.md — ⚠ Minor

**What is correct:**

- 4-step wizard (Basic Info → LLM Profile → Quotas → Review) matches Plan 05 Sprint A1 exactly
- `tenants` table schema (name, slug, plan, status, primary_contact_email, llm_profile_id) is correct
- State machine `draft → active` is correct
- Quota via `tenant_configs` with `config_type='quota'` is correct
- PATCH `/admin/tenants/{id}/status` and `/admin/tenants/{id}/quota` endpoints confirmed

**What to note:**

- Step 1.2 creates a new LLM profile via `POST /admin/llm-profiles`. This is correct for a fresh
  platform install. However: the Phase A provisioning wizard expects the tenant admin to SELECT from
  already-published platform profiles (Plan 05 Phase B Sprint B1 is when the full LLM Profile Library UI
  ships). For Phase 1 bootstrapping, creating via API is the right fallback — but if a platform profile
  pointing to eastus2 already exists from a previous tenant setup, ASSIGN that profile instead of
  creating a duplicate.

**Action**: Added note to Step 1.2 in the file.

---

### 02-users.md — ✓ Correct

**What is correct:**

- Invite creates user with `status='invited'` — confirmed in routes.py
- Roles: `user` or `tenant_admin` — confirmed in schema
- Bulk invite max 50/call — confirmed in routes.py (API-043 to API-046)
- SSO-first approach (Azure AD Entra ID) for real users — correct for aihub2 user base
- 3 batches (30 + 30 + 12) respects the 50/call limit

**No changes needed.**

---

### 03-teams.md — ⚠ Minor

**What is correct:**

- `tenant_teams` table with `source` field confirmed in Plan 10 Sprint 1
- `source='manual'` is the correct value for admin-created teams (vs `auth0_sync`)
- 15 team definitions and system role → `tenant_admin` mapping are correct

**What to note:**

- Teams management UI (list, create, edit, members) is Sprint 8 of Plan 10 — Phase B of the
  tenant admin console. In Phase 1, the SQL INSERT approach in this guide is the correct workaround.
- Plan 10 also defines `auth0_group_name` field on `tenant_teams` for SSO group sync. Not needed for
  manual setup. Leave NULL.

---

### 04-knowledge-base.md — ⚠ Minor

**What is correct:**

- KB as `agent_card` with `capabilities.search_config` JSONB is the correct Phase 1 architecture
- Differentiation between legacy (`cogsearchopenai`, ada-002, 1536 dims) and new (`aihub2-ai-search`,
  text-embedding-3-large, 3072 dims) indexes is correct
- `agent_cards` table columns (tenant_id, name, description, system_prompt, capabilities, status,
  version, created_by) match schema.py
- `status='active'` and `version=1` are correct defaults

**What to note:**

- Section 4.4 (Team → Agent Access) documents the intended RBAC mapping. This is **not enforced in
  Phase 1**. KB/agent access control (per-agent visibility modes: workspace-wide / role-restricted /
  user-specific) is Phase B Sprint B1 of the tenant admin plan. In Phase 1, all active agent cards are
  visible to all users in the tenant. Configure team permissions now so data is ready for Phase B,
  but do not expect enforcement until Phase B ships.

---

### 05-glossary-agents.md — ✗ Error (must fix)

**Critical bug:**
The SQL inserts TWO rows with `term = 'MEP'`:

```sql
('<tenant_id>', 'MEP', 'Mindful Emotion Program', '["MEP Coaching", "Mindful Emotion"]'),
...
('<tenant_id>', 'MEP', 'Management Excellence Programme', '[]'),
```

The `glossary_terms` table has a UNIQUE constraint on `(tenant_id, term)`. The second INSERT will
fail with a unique violation. **Fixed** — see corrected file.

**What to note:**

- Glossary CRUD UI and the injection pipeline (terms injected into the system message at query time)
  are **Phase B Sprint B2** of the tenant admin plan (Weeks 10-12). The `glossary_terms` table exists
  in Phase 1 so you can pre-load terms via SQL, but they will not be active in AI responses until the
  GlossaryExpander component ships in Phase B.
- Glossary has a `definition` field (200 char limit) in the product spec but it may not be in the
  Phase 1 schema. The current SQL uses only `term`, `full_form`, `aliases` — matching schema.py. Add
  definitions when the UI ships.
- Per Plan 09: ≤3 char terms (like 'AT', 'OI', 'OL') only expand when they appear ALL CAPS in the
  query. Single-character and common English words are excluded. This means some of our 1-2 char terms
  (AT, OI, OL) may not expand in practice unless users type them in all caps.

---

## Architectural Confirmations

These design decisions in the setup guide are confirmed correct by the product docs:

| Decision                                             | Product Doc Confirmation                                                                          |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| No RAG in Phase 1 — KB as agent_card                 | Confirmed: "integrations/sync_jobs NOT used in Phase 1"                                           |
| Skip SharePoint wizard for migration                 | Correct: wizard provisions NEW indexes; aihub2 uses existing indexes via agent_cards.capabilities |
| Platform eastus2 LLM profile (not aihub2 own AOAI)   | Confirmed in README and Plan 05                                                                   |
| Tenant status state machine draft→active             | Confirmed: Plan 05 Sprint A1                                                                      |
| Quota in `tenant_configs` with `config_type='quota'` | Confirmed: schema.py                                                                              |
| Auth0/JWT-based team sync via `auth0_group_name`     | Confirmed: Plan 10 — deferred, manual setup is correct for Phase 1                                |

---

## Phase Timeline for Features in This Guide

| Feature                   | Phase 1 (now)             | Phase B (Weeks 7-14)                |
| ------------------------- | ------------------------- | ----------------------------------- |
| Tenant provisioning       | ✓ Active                  | —                                   |
| User invite               | ✓ Active                  | —                                   |
| Teams (SQL)               | ✓ Table exists, SQL works | Teams UI ships                      |
| Agent cards (KB agents)   | ✓ Active                  | —                                   |
| Glossary (data load)      | ✓ Table exists, SQL works | Injection pipeline + UI ships       |
| KB/agent RBAC enforcement | —                         | ✓ Visibility modes + access control |
| SSO configuration         | —                         | ✓ SAML/OIDC wizard                  |
| Sync health dashboard     | —                         | ✓ (N/A for Phase 1 migration)       |
