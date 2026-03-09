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

## Phase 1+2 Status (as of 2026-03-09)

Phase 1 and Phase 2 are **COMPLETE**. Last commits: `a89efa2`, `c8efd5d` (Session 16).

1134 unit tests passing. Integration test files: test_cross_tenant_isolation, test_triage_pipeline_integration, test_migration_rollback, test_prompt_builder_pipeline, test_glossary_rollout_flag, and more.

Key backend milestones:

- 5 Alembic migrations: v001 (schema, 22 tables), v002 (RLS), v003 (HAR), v004, v005
- HAR A2A protocol: app/modules/har/ — signed event chain, no double-insert
- Group sync: app/modules/auth/group_sync.py — sync_auth0_groups() pure function
- Blur pipeline: app/modules/issues/blur_service.py + blur_pipeline.py
- Cache: app/core/cache.py — CacheService, @cached, pub/sub invalidation

Deferred (blocked on Auth0 external dependency):

- TEST-004: JWT v1/v2 HTTP-level integration test (unit coverage confirmed)
- TEST-005: Auth0 integration tests (requires Auth0 test tenant)
