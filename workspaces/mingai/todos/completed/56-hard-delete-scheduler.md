---
id: TODO-56
title: Platform credential hard-delete background scheduler
status: pending
priority: high
phase: A-post
dependencies: [TODO-41, TODO-42, TODO-43]
---

## Goal

Implement the hard-delete background scheduler for soft-deleted platform credentials. The `retention_until` column requires a scheduler that purges credentials after 30 days.

## Context

The migration (`v061`) creates `retention_until = deleted_at + 30 days` on soft-delete. Without a scheduler, soft-deleted records accumulate indefinitely and `retention_until` is a no-op.

This is listed as Phase 1 scope in `02-requirements-and-adr.md` under "Hard-delete scheduler (background task, 30-day retention)".

## Implementation

### 1. Add purge function to `credential_manager.py`

```python
async def purge_expired_platform_credentials(db_session) -> int:
    """Hard-delete platform credential metadata rows past retention_until.

    Called by the background scheduler. Does NOT delete vault values
    (those are deleted at soft-delete time). Only removes the metadata row.

    Returns: count of rows deleted.
    """
    from sqlalchemy import text
    from datetime import datetime, timezone

    result = await db_session.execute(
        text("""
            DELETE FROM platform_credential_metadata
            WHERE deleted_at IS NOT NULL
            AND retention_until < :now
            RETURNING id, template_id, key
        """),
        {"now": datetime.now(timezone.utc)}
    )
    rows = result.fetchall()
    count = len(rows)
    if count > 0:
        logger.info("platform_credentials_hard_deleted", count=count)
    return count
```

### 2. Add scheduler to `app/main.py` lifespan

In the startup section of `lifespan()`, add:

```python
from app.modules.agents.credential_manager import purge_expired_platform_credentials

async def _run_credential_purge_scheduler():
    """Daily hard-delete scheduler for expired platform credentials."""
    import asyncio
    while True:
        try:
            await asyncio.sleep(86400)  # 24 hours
            async with get_async_session_context() as session:
                count = await purge_expired_platform_credentials(session)
                if count:
                    logger.info("credential_purge_complete", deleted=count)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("credential_purge_failed", error=str(exc))
            # Don't crash the scheduler — retry on next cycle

_credential_purge_task = asyncio.create_task(_run_credential_purge_scheduler())
```

In the shutdown/finally section:

```python
_credential_purge_task.cancel()
try:
    await _credential_purge_task
except asyncio.CancelledError:
    pass
```

### 3. Testing guard

Wrap in `if not _testing:` (same pattern as the startup validation check) to avoid running the scheduler in tests:

```python
if not _testing:
    _credential_purge_task = asyncio.create_task(_run_credential_purge_scheduler())
```

## Acceptance Criteria

- [ ] `purge_expired_platform_credentials()` deletes rows where `deleted_at IS NOT NULL AND retention_until < NOW()`
- [ ] Returns count of deleted rows
- [ ] Logs `platform_credentials_hard_deleted` with count when rows are deleted; silent when count is zero
- [ ] Background task created in `main.py` lifespan
- [ ] Task cancelled cleanly on shutdown (no asyncio warnings in test output)
- [ ] Wrapped in `if not _testing:` guard — scheduler does not run during pytest
- [ ] Integration test: soft-delete a credential → set `retention_until` to a past timestamp via direct DB update → call `purge_expired_platform_credentials()` → verify row is gone from `platform_credential_metadata`
- [ ] Hard-delete does NOT attempt to delete vault values (vault deletion happens at soft-delete time in DELETE route)
- [ ] Rows with `retention_until` in the future are not deleted
- [ ] Rows with `deleted_at IS NULL` (active credentials) are never deleted regardless of `retention_until`
