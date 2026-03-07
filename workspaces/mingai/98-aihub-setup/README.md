# aihub2 → mingai Tenant Setup Guide

## Overview

This workspace contains step-by-step instructions to manually provision the **IMC / Tsao Pao Chee Group** tenant in mingai, based on the existing aihub2 production deployment.

**Source**: aihub2 CosmosDB (`aihub-dev`) + `.env` — Southeast Asia region
**Target**: mingai PostgreSQL backend — platform admin UI + REST API

---

## What aihub2 Is

aihub2 is a **single-tenant** enterprise AI platform serving the IMC Industrial Group and its portfolio companies (Tsao Pao Chee, Octave Living, Aurora Tankers, IMC Shipping, Unithai, etc.). In mingai's multi-tenant model, the entire aihub2 deployment maps to **one tenant**.

### Scale at migration point (2026-03-07)

| Entity                              | Count                           |
| ----------------------------------- | ------------------------------- |
| Real users                          | ~60 (excl. test/local accounts) |
| Knowledge bases → agent cards       | 29 enabled (of 33 total)        |
| Access roles → teams                | 15 custom teams                 |
| Documents indexed (Azure AI Search) | ~80,000+                        |

---

## Key Architecture Decision: No RAG in Phase 1

mingai Phase 1 has **no built-in RAG pipeline**. Each aihub2 KB index maps directly to a
mingai `agent_card`. The agent card's `capabilities` JSONB stores the Azure AI Search
endpoint + index name so the chat backend can search on demand when a user picks that agent.

```
aihub2 KB index  →  mingai agent_card
                     ├── name / description / system_prompt  (from KB)
                     └── capabilities.search_config          (Azure AI Search coords)
```

The `integrations` / `sync_jobs` tables are NOT used in Phase 1.

The `glossary_terms` table **can** be pre-loaded in Phase 1 via SQL, but the GlossaryExpander injection
pipeline (which makes terms active in AI responses) ships in Phase B Sprint B2. Terms inserted now are
data-ready but will not affect AI responses until Phase B is deployed.

---

## Setup Phases

| Phase | Actor          | Steps                                         |
| ----- | -------------- | --------------------------------------------- |
| 1     | Platform Admin | Create tenant, assign LLM profile, set quotas |
| 2     | Platform Admin | Invite first tenant admin                     |
| 3     | Tenant Admin   | Bulk-invite all users (3 batches)             |
| 4     | Tenant Admin   | Create 15 teams (from aihub2 roles)           |
| 5     | Tenant Admin   | Create 29 KB agent cards + set team access    |
| 6     | Tenant Admin   | Populate glossary (19 terms)                  |

---

## Files in This Workspace

| File                    | Content                                                       |
| ----------------------- | ------------------------------------------------------------- |
| `00-audit.md`           | Product doc audit — correctness verification and gap analysis |
| `01-tenant-creation.md` | Phase 1 — Create tenant record + LLM profile + quotas         |
| `02-users.md`           | Phase 2-3 — All users to invite, with roles                   |
| `03-teams.md`           | Phase 4 — 15 team definitions from aihub2 roles               |
| `04-knowledge-base.md`  | Phase 5 — All 29 KB agent cards with full SQL + capabilities  |
| `05-glossary-agents.md` | Phase 6 — Glossary terms (active Phase B; pre-load now)       |

---

## Key Credentials (from aihub2)

These are extracted from aihub2 `.env` for reference during setup. Do **not** commit these to git.

| Item                   | Value                                         |
| ---------------------- | --------------------------------------------- |
| Azure AD Tenant ID     | `2311a55c-d508-4e3a-aeb8-47a08b156aa5`        |
| Azure AD App Client ID | `7cf2d9cf-7c24-45c3-aeb2-1e33fbfa9160`        |
| SharePoint Tenant ID   | `2311a55c-d508-4e3a-aeb8-47a08b156aa5` (same) |
| SharePoint Client ID   | `7cf2d9cf-7c24-45c3-aeb2-1e33fbfa9160` (same) |
| Legacy Azure AI Search | `https://cogsearchopenai.search.windows.net`  |
| New Azure AI Search    | `https://aihub2-ai-search.search.windows.net` |

---

## LLM Strategy

Per instruction: use the **platform pre-configured OpenAI** for this tenant. Do NOT create a custom LLM profile pointing to aihub2's own Azure OpenAI. The platform profile uses:

- **Primary model**: `agentic-worker` (gpt-5.2 on eastus2)
- **Intent model**: `agentic-router` (gpt-5-mini on eastus2)
- **Embedding model**: `text-embedding-3-small` (eastus2)
- **Endpoint**: `https://eastus2.api.cognitive.microsoft.com/`

The platform admin should link this platform LLM profile to the tenant after creation.
