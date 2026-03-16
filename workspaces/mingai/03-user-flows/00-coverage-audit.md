# Product Doc + User Flow Coverage Audit

**Date**: 2026-03-07
**Scope**: All 16 user flow files cross-referenced against `30-platform-admin-capability-spec.md` and `31-tenant-admin-capability-spec.md`
**Method**: Full read of all flow files; capability-by-capability coverage check; inter-file consistency check

---

## Coverage Matrix

### Platform Admin — 7 Domains

| Domain              | Capability                                          | Covered In        | Status  |
| ------------------- | --------------------------------------------------- | ----------------- | ------- |
| 1. Tenant Lifecycle | Provisioning wizard                                 | 01, 11, 12        | COVERED |
| 1. Tenant Lifecycle | Suspension/deprovisioning                           | 01, 11            | COVERED |
| 1. Tenant Lifecycle | Plan upgrade/downgrade                              | 18 (F6)           | COVERED |
| 1. Tenant Lifecycle | Invoice/billing admin                               | 18 (F7, F8)       | COVERED |
| 1. Tenant Lifecycle | Quota alert → increase approval                     | 11 (F9), 02 (F10) | COVERED |
| 2. Issue Queue      | User reports issue                                  | 10, 03 (F10)      | COVERED |
| 2. Issue Queue      | Duplicate detection                                 | 10                | COVERED |
| 2. Issue Queue      | Platform admin triage + GitHub                      | 10, 11            | COVERED |
| 2. Issue Queue      | Tenant admin config                                 | 10, 12 (F10)      | COVERED |
| 3. Analytics        | Usage analytics                                     | 11                | COVERED |
| 3. Analytics        | Roadmap signals — admin acts on them                | 11 (F4 Steps 5-7) | COVERED |
| 3. Analytics        | Cache performance                                   | 05                | COVERED |
| 3. Analytics        | Glossary analytics                                  | 08, 12            | COVERED |
| 4. LLM Config       | Provider config + BYOLLM                            | 01, 02, 11        | COVERED |
| 4. LLM Config       | Tenant selects LLM profile                          | 12 (F1 Step 4)    | COVERED |
| 4. LLM Config       | Profile version update → tenant notification        | 18 (F2)           | COVERED |
| 4. LLM Config       | LLM profile test before activating                  | 18 (F1)           | COVERED |
| 5. Cost/Token       | Cross-tenant cost monitoring                        | 11, 05            | COVERED |
| 5. Cost/Token       | Per-tenant cost drill-down                          | 02 (F6), 11       | COVERED |
| 5. Cost/Token       | Chargeback to billing                               | 18 (F8)           | COVERED |
| 6. Agent Templates  | Template library management                         | 11                | COVERED |
| 6. Agent Templates  | Tenant deploys template                             | 12 (F7)           | COVERED |
| 6. Agent Templates  | Template versioning (v2 publish + tenant migration) | 18 (F3)           | COVERED |
| 6. Agent Templates  | Platform admin QA before publish                    | 18 (F4)           | COVERED |
| 7. Tool Catalog     | Tool registration                                   | 11                | COVERED |
| 7. Tool Catalog     | Tenant admin browses + enables tools                | 18 (F5)           | COVERED |

### Tenant Admin — 7 Domains

| Domain                  | Capability                                | Covered In       | Status  |
| ----------------------- | ----------------------------------------- | ---------------- | ------- |
| 1. Workspace Setup      | Onboarding wizard                         | 02, 12 (F1)      | COVERED |
| 1. Workspace Setup      | SSO (SAML 2.0, OIDC)                      | 02, 12 (F1)      | COVERED |
| 1. Workspace Setup      | MFA enforcement for non-SSO users         | 19 (F1)          | COVERED |
| 1. Workspace Setup      | Workspace branding (ongoing, post-wizard) | 19 (F5)          | COVERED |
| 2. Identity + Doc Store | SharePoint connection wizard              | 02 (F5), 12 (F2) | COVERED |
| 2. Identity + Doc Store | Google Drive DWD wizard                   | 07, 12 (F3)      | COVERED |
| 2. Identity + Doc Store | Azure AI Search index                     | 02 (F5)          | COVERED |
| 2. Identity + Doc Store | SSO group → RBAC role mapping             | 02 (F8)          | COVERED |
| 2. Identity + Doc Store | Document-level permission verification    | 19 (F2)          | COVERED |
| 3. Sync Monitoring      | Sync health dashboard                     | 12 (F4)          | COVERED |
| 3. Sync Monitoring      | Failure investigation + retry             | 07 (F5), 12 (F4) | COVERED |
| 3. Sync Monitoring      | Cache invalidation on doc update          | 05               | COVERED |
| 4. Glossary             | CRUD (add/edit/delete)                    | 08, 12 (F5), 15  | COVERED |
| 4. Glossary             | Bulk import CSV                           | 08               | COVERED |
| 4. Glossary             | Approval workflow (Enterprise)            | 08 (F4)          | COVERED |
| 4. Glossary             | Analytics review                          | 08 (F6), 12 (F5) | COVERED |
| 4. Glossary             | Multilingual query expansion              | 15, 19 (F6)      | COVERED |
| 5. RBAC                 | User invite + role assignment             | 02 (F4), 12 (F6) | COVERED |
| 5. RBAC                 | Custom role builder                       | 02 (F7)          | COVERED |
| 5. RBAC                 | Access request workflow                   | 12 (F6 Step 4)   | COVERED |
| 5. RBAC                 | SSO group → role auto-mapping             | 02 (F8)          | COVERED |
| 5. RBAC                 | Agent cloning/duplication                 | 19 (F3)          | COVERED |
| 6. Agent Workspace      | Deploy from library                       | 12 (F7)          | COVERED |
| 6. Agent Workspace      | Agent Studio (custom build)               | 12 (F8)          | COVERED |
| 6. Agent Workspace      | BYOMCP registration                       | 09 (F7)          | COVERED |
| 6. Agent Workspace      | Enable A2A agents                         | 02 (F5), 09      | COVERED |
| 6. Agent Workspace      | Agent version update (live agent)         | 19 (F4)          | COVERED |
| 7. Feedback             | Thumbs up/down                            | 03 (F9), 05      | COVERED |
| 7. Feedback             | Feedback review dashboard                 | 12 (F9)          | COVERED |
| 7. Feedback             | 3+ negative ratings → admin review queue  | 05, 12 (F11)     | COVERED |
| 7. Feedback             | Issue queue + resolution                  | 10, 12 (F10)     | COVERED |

### End User

| Capability                            | Covered In   | Status  |
| ------------------------------------- | ------------ | ------- |
| First login + onboarding              | 03 (F1)      | COVERED |
| Standard chat (RAG pipeline)          | 03 (F2)      | COVERED |
| Research mode                         | 03 (F3)      | COVERED |
| Document upload (all methods)         | 06           | COVERED |
| Agent delegation                      | 03 (F5)      | COVERED |
| Internet fallback (Tavily)            | 03 (F6)      | COVERED |
| Conversation history                  | 03 (F7)      | COVERED |
| Failure paths                         | 03 (F8)      | COVERED |
| Feedback (thumbs up/down)             | 03 (F9)      | COVERED |
| Issue reporting                       | 03 (F10), 10 | COVERED |
| Cache UX (fast response / refresh)    | 05           | COVERED |
| A2A multi-agent queries               | 09           | COVERED |
| Profile learning + memory             | 14           | COVERED |
| Teams collaboration                   | 16           | COVERED |
| Glossary pretranslation (transparent) | 15           | COVERED |
| Internal agent browsing/discovery     | 03 (F11)     | COVERED |
| Conversation search                   | 20 (F1)      | COVERED |
| Conversation sharing                  | 20 (F2)      | COVERED |
| Conversation export                   | 20 (F3)      | COVERED |
| Session expiry + recovery             | 20 (F5)      | COVERED |
| Personal memory management            | 20 (F6)      | COVERED |

---

## Critical Inconsistencies (Fixed Below)

### IC-1: Role Naming Mismatch — FIXED

`02-tenant-admin-flows.md` uses non-canonical role names:

| File | System Roles Used                                    | Canonical (spec + 12)                 |
| ---- | ---------------------------------------------------- | ------------------------------------- |
| `02` | User, Tenant Admin, Tenant Manager, Analytics Viewer | viewer, reader, analyst, tenant_admin |
| `12` | Viewer, Reader, Analyst, Tenant Admin                | viewer, reader, analyst, tenant_admin |
| Spec | tenant_admin, analyst, reader, viewer                | tenant_admin, analyst, reader, viewer |

**Fix**: Updated `02-tenant-admin-flows.md` Flows 4 and 7 to use canonical role names.

### IC-2: Glossary Entry Limit Mismatch — FIXED

| File                   | Stated Limit                |
| ---------------------- | --------------------------- |
| `31-spec`              | 500 active terms max        |
| `08-glossary-flows.md` | "Max 5,000 rows per import" |

These are contradictory. A tenant cannot import 5,000 rows if the active term limit is 500. The spec value (500) is canonical.

**Fix**: Updated `08-glossary-flows.md` bulk import to state "Max 500 rows per import" with a note that import will reject rows exceeding the active term limit.

### IC-3: Google Drive Phase Misalignment

| File                       | Phase for Google Drive                       |
| -------------------------- | -------------------------------------------- |
| `07-google-drive-flows.md` | Phase 4                                      |
| `12-tenant-admin-flows.md` | Included in onboarding wizard (no phase tag) |
| `02-tenant-admin-flows.md` | Not included (SharePoint only)               |

**Status**: `12` is the comprehensive tenant admin flow file (supersedes `02` in scope). Google Drive in the wizard should be marked Phase 4 with a note that it's available from the setup wizard once Phase 4 ships. No fix needed in flows — this is a product phasing decision documented in `07`.

### IC-4: LLM Profile Selection vs BYOLLM Confusion

`12` Step 4 of wizard ("Choose LLM Profile") presents platform-managed profiles. `02` Flow 3 ("BYOLLM Setup") covers tenant-provided keys. These are distinct and correctly separated — but neither cross-references the other. Readers of one file may not realize the distinction exists.

**Status**: Documented. No flow change needed; worth noting in code comments during implementation.

### IC-5: Missing 3-Negative-Rating Admin Review Queue (non-cache)

`05-caching-ux-flows.md` defines: "3+ users downvote same cached response → automatic escalation."
`31-spec` states: "flag messages with 3+ negative ratings for admin review."

The broader non-cache version of this feature (any response, not just cached ones) has no dedicated flow. The spec requirement is partially met by the cache file but the general case is not covered.

**Fix**: Added Flow 11 (3-Rating Admin Escalation) to `03-end-user-flows.md` and `12-tenant-admin-flows.md`.

---

## Missing Flows — Added

The following flows were identified as absent and have been added to the appropriate files:

| Flow                                | Added To                   | Description                                |
| ----------------------------------- | -------------------------- | ------------------------------------------ |
| SSO group → RBAC role mapping       | `02-tenant-admin-flows.md` | How admin maps IdP groups to tenant roles  |
| End user internal agent discovery   | `03-end-user-flows.md`     | How users browse and select agents         |
| Non-cache 3-rating admin escalation | `12-tenant-admin-flows.md` | Admin review queue for low-rated responses |
| Tenant plan upgrade/downgrade       | `02-tenant-admin-flows.md` | Self-service plan change flow              |

---

## Missing Flows — Added (2026-03-10)

Previously blocked gaps have been resolved with product decisions and written:

| Flow                                             | Added To                              | Resolution                                                            |
| ------------------------------------------------ | ------------------------------------- | --------------------------------------------------------------------- |
| LLM profile test before activating               | `18-advanced-platform-admin-flows.md` | Flow 1: test harness with standard 5-case suite + comparison to live  |
| LLM profile version update → tenant notification | `18-advanced-platform-admin-flows.md` | Flow 2: recommended migration (tenant-controlled) + auto-migrate gate |
| Agent template versioning (v2 publish)           | `18-advanced-platform-admin-flows.md` | Flow 3: create v2, QA, publish, notify, track upgrade adoption        |
| Platform admin QA before publishing template     | `18-advanced-platform-admin-flows.md` | Flow 4: mandatory 6-section QA checklist gate                         |
| Tool catalog tenant browsing + enabling          | `18-advanced-platform-admin-flows.md` | Flow 5: tenant browses catalog, configures OAuth/credentials, enables |
| Billing plan upgrade/downgrade                   | `18-advanced-platform-admin-flows.md` | Flow 6: proration, quota, margin visibility                           |
| Chargeback to billing                            | `18-advanced-platform-admin-flows.md` | Flows 7-8: SLA credits, invoice export, per-dept chargeback           |
| MFA enforcement flow                             | `19-advanced-tenant-admin-flows.md`   | Flow 1: enforcement policy, grace period, enrollment, compliance      |
| Document-level permission verification           | `19-advanced-tenant-admin-flows.md`   | Flow 2: access test tool, audit log, SharePoint alignment check       |
| Agent cloning/duplication                        | `19-advanced-tenant-admin-flows.md`   | Flow 3: clone with config customization, independent after clone      |
| Agent live version update                        | `19-advanced-tenant-admin-flows.md`   | Flow 4: versioned updates, rollback, 24h monitoring                   |
| Workspace branding (ongoing, post-wizard)        | `19-advanced-tenant-admin-flows.md`   | Flow 5: name, logo, accent color, email templates                     |
| Multilingual query expansion (full)              | `19-advanced-tenant-admin-flows.md`   | Flow 6: setup, glossary translations, query pipeline, quality review  |
| KB access request workflow                       | `19-advanced-tenant-admin-flows.md`   | Flow 7: user requests, admin approve/deny, time-limited grants        |
| Conversation search                              | `20-conversation-management-flows.md` | Flow 1: real-time search, snippets, advanced filters                  |
| Conversation sharing                             | `20-conversation-management-flows.md` | Flow 2: link-based, workspace-scoped, fork for recipient              |
| Conversation export                              | `20-conversation-management-flows.md` | Flow 3: PDF/Markdown/JSON, bulk download, compliance logging          |
| Conversation organization                        | `20-conversation-management-flows.md` | Flow 4: rename, delete, star, bulk management                         |
| Session expiry + recovery                        | `20-conversation-management-flows.md` | Flow 5: silent refresh, forced re-login, crash recovery               |
| Personal memory management                       | `20-conversation-management-flows.md` | Flow 6: view, edit, delete notes, opt-out of learning                 |

---

## Phase Coverage by File

| File                                | Flows                      | Phases Covered             |
| ----------------------------------- | -------------------------- | -------------------------- |
| 01-platform-admin-flows.md          | 8                          | Phase 1-2                  |
| 02-tenant-admin-flows.md            | 9 (7 original + 2 added)   | Phase 1-2                  |
| 03-end-user-flows.md                | 11 (10 original + 1 added) | Phase 1-3                  |
| 04-platform-model-flows.md          | Strategic analysis         | Phase 4-6                  |
| 05-caching-ux-flows.md              | 11                         | Phase 2-3                  |
| 06-document-upload-flows.md         | 6                          | Phase 1                    |
| 07-google-drive-flows.md            | 6                          | Phase 4-5                  |
| 08-glossary-flows.md                | 7                          | Phase 1-2 (4 for approval) |
| 09-a2a-dag-flows.md                 | 10                         | Phase 2-4                  |
| 10-issue-reporting-flows.md         | 7                          | Phase 1-2                  |
| 11-platform-admin-ops-flows.md      | 12+                        | Phase 1-3                  |
| 12-tenant-admin-flows.md            | 11 (10 original + 1 added) | Phase 1-4                  |
| 13-agent-registry-flows.md          | 8                          | Phase 2-6 (HAR)            |
| 14-profile-memory-flows.md          | 9                          | Phase 2-3                  |
| 15-glossary-pretranslation-flows.md | 4                          | Phase 1-2                  |
| 16-teams-collaboration-flows.md     | 8                          | Phase 2-3                  |
| 17-role-first-login-flows.md        | (role onboarding)          | Phase 1                    |
| 18-advanced-platform-admin-flows.md | 8                          | Phase 2-6                  |
| 19-advanced-tenant-admin-flows.md   | 7                          | Phase 1-5                  |
| 20-conversation-management-flows.md | 6                          | Phase 1-3                  |

---

**Audit completed**: 2026-03-07
**Updated**: 2026-03-10 — all previously-missing flows written (files 18, 19, 20)
**Inconsistencies fixed**: IC-1 (role names), IC-2 (glossary limit)
**Flows added (original audit)**: SSO group→RBAC, agent discovery, 3-rating escalation, plan upgrade
**Flows added (2026-03-10 comprehensive review)**: 20 new flows across 3 new files — see "Missing Flows — Added" table above
