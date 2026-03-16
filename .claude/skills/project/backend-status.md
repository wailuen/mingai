---
name: backend-status
trigger: /backend-status
description: Quick status check of the mingai backend — shows module coverage, test count, and key pending items.
---

Run the following to get the current backend status:

```bash
cd /Users/cheongwailuen/Development/mingai/src/backend

# Test count (unit only — fast, no Docker needed)
python -m pytest tests/unit/ -q --tb=no 2>&1 | tail -3

# Test count (all tiers — requires Docker)
python -m pytest tests/ -q --tb=no 2>&1 | tail -3

# Module coverage
ls app/modules/

# Recent commits
git log --oneline -5
```

Then report:

1. Test pass count (unit and total if Docker running)
2. Which modules exist vs are missing
3. Last 5 commits
4. Any obvious stubs (grep for TODO/NotImplementedError in non-test files)

```bash
grep -r "TODO\|NotImplementedError\|STUB" app/ --include="*.py" | grep -v __pycache__
```

## Phase 1+2+3 (TA Phase B-D) Status (as of 2026-03-16)

Phase 1, Phase 2, and TA Phase B-D (backend) are **COMPLETE**. Last commits: `c9cd155`, `9baaabe`.

2087+ unit tests passing. Integration test files: test_cross_tenant_isolation, test_triage_pipeline_integration, test_migration_rollback, test_prompt_builder_pipeline, test_glossary_rollout_flag, and more.

Key backend milestones:

- 31 Alembic migrations (v001–v029)
- HAR A2A protocol: app/modules/har/ — signed event chain, no double-insert
- Group sync: app/modules/auth/group_sync.py — sync_auth0_groups() pure function
- Blur pipeline: app/modules/issues/blur_service.py + blur_pipeline.py
- Cache: app/core/cache.py — CacheService, @cached, pub/sub invalidation
- Analytics: app/modules/admin/analytics.py — satisfaction, per-agent, glossary impact (TA-026–030)
- Onboarding: app/modules/admin/onboarding.py — tenant_configs JSONB (TA-031)
- Bulk actions: app/modules/admin/bulk_user_actions.py — self-lockout + KB ownership check (TA-032)
- KB sources: app/modules/admin/kb_sources.py — health, search, detach (TA-034)
- KB access control: app/modules/admin/kb_access_control.py — visibility modes (TA-011/007)
- Glossary: version history + rollback (TA-012/013) — atomic commit=False pattern

Deferred (blocked on Auth0 external dependency):

- TEST-004: JWT v1/v2 HTTP-level integration test (unit coverage confirmed)
- TEST-005: Auth0 integration tests (requires Auth0 test tenant)

Blocked on external dependencies (no action needed):

- TA-001–005: SSO P3AUTH items
- TA-016: Full re-index with cost estimate (P2LLM-011)
- TA-025: Agent Studio (product-gated — 5-10 persona interviews required)
- TA-033: User import from SSO (P3AUTH-001)
- TA-035: Tenant admin role delegation (P3AUTH-002)
