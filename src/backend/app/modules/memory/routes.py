"""
Memory API routes (API-099 to API-105).

Endpoints:
- GET    /memory/notes          — List memory notes
- POST   /memory/notes          — Create memory note (max 200 chars)
- DELETE /memory/notes/{id}     — Delete memory note
- DELETE /memory/notes           — Clear ALL notes for user
- PATCH  /memory/privacy        — Update privacy preferences
- GET    /memory/profile        — Get user profile
- DELETE /memory/profile        — GDPR comprehensive erasure
- GET    /memory/working        — Get working memory summary
- DELETE /memory/working        — Clear working memory
- GET    /memory/export         — Export profile data (GDPR)
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.core.session import get_async_session
from app.modules.memory.notes import MAX_NOTE_CONTENT_LENGTH

logger = structlog.get_logger()

router = APIRouter(prefix="/memory", tags=["memory"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateNoteRequest(BaseModel):
    """POST /api/v1/memory/notes request body."""

    content: str = Field(..., min_length=1, max_length=MAX_NOTE_CONTENT_LENGTH)


class UpdatePrivacyRequest(BaseModel):
    """PATCH /api/v1/memory/privacy request body."""

    profile_learning_enabled: bool
    working_memory_enabled: bool


# ---------------------------------------------------------------------------
# DB / service helper functions (mockable in unit tests)
# ---------------------------------------------------------------------------


async def list_notes_db(user_id: str, tenant_id: str, db) -> list:
    """List all memory notes for the user."""
    result = await db.execute(
        text(
            "SELECT id, content, source, created_at FROM memory_notes "
            "WHERE user_id = :user_id AND tenant_id = :tenant_id "
            "ORDER BY created_at DESC"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    return [
        {"id": str(r[0]), "content": r[1], "source": r[2], "created_at": str(r[3])}
        for r in result.fetchall()
    ]


async def create_note_db(
    user_id: str,
    tenant_id: str,
    content: str,
    db,
) -> dict:
    """Insert a new memory note."""
    note_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO memory_notes (id, user_id, tenant_id, content, source) "
            "VALUES (:id, :user_id, :tenant_id, :content, 'user_directed')"
        ),
        {"id": note_id, "user_id": user_id, "tenant_id": tenant_id, "content": content},
    )
    await db.commit()
    logger.info("memory_note_created", note_id=note_id, user_id=user_id)
    return {"id": note_id, "content": content, "source": "user_directed"}


async def delete_note_db(note_id: str, user_id: str, tenant_id: str, db) -> bool:
    """Delete a memory note owned by the user."""
    result = await db.execute(
        text(
            "DELETE FROM memory_notes "
            "WHERE id = :id AND user_id = :user_id AND tenant_id = :tenant_id"
        ),
        {"id": note_id, "user_id": user_id, "tenant_id": tenant_id},
    )
    await db.commit()
    return (result.rowcount or 0) > 0


async def get_profile_data(user_id: str, tenant_id: str, db) -> dict:
    """Get user profile from L1->L2->L3 cache chain."""
    from app.modules.profile.learning import ProfileLearningService

    service = ProfileLearningService(db_session=db)
    profile = await service.get_profile_context(user_id, tenant_id)
    if profile is None:
        return {"user_id": user_id}
    return {"user_id": user_id, **profile}


async def get_working_memory_data(
    user_id: str,
    tenant_id: str,
    agent_id: str,
    db,
) -> dict:
    """Get working memory summary for a user/agent pair."""
    from app.modules.memory.working_memory import WorkingMemoryService

    service = WorkingMemoryService()
    context = await service.get_context(user_id, tenant_id, agent_id)
    return {
        "user_id": user_id,
        "agent_id": agent_id,
        "topics": context.get("topics", []) if context else [],
        "recent_queries": context.get("queries", []) if context else [],
    }


async def clear_working_memory_data(
    user_id: str,
    tenant_id: str,
    db,
) -> None:
    """Clear all working memory keys for the user across all agents."""
    from app.core.redis_client import get_redis

    redis = get_redis()
    pattern = f"mingai:{tenant_id}:working_memory:{user_id}:*"
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        if keys:
            await redis.delete(*keys)
        if cursor == 0:
            break
    logger.info("working_memory_cleared", user_id=user_id, tenant_id=tenant_id)


async def clear_all_notes_db(user_id: str, tenant_id: str, db) -> None:
    """Delete ALL memory notes for a user within a tenant."""
    await db.execute(
        text(
            "DELETE FROM memory_notes "
            "WHERE user_id = :user_id AND tenant_id = :tenant_id"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    await db.commit()
    logger.info("memory_notes_cleared_all", user_id=user_id, tenant_id=tenant_id)


async def upsert_privacy_settings(
    user_id: str,
    tenant_id: str,
    profile_learning_enabled: bool,
    working_memory_enabled: bool,
    db,
) -> dict:
    """Upsert user privacy settings (ON CONFLICT update)."""
    settings_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO user_privacy_settings "
            "(id, user_id, tenant_id, profile_learning_enabled, working_memory_enabled) "
            "VALUES (:id, :user_id, :tenant_id, :profile_learning, :working_memory) "
            "ON CONFLICT (user_id, tenant_id) DO UPDATE SET "
            "profile_learning_enabled = :profile_learning, "
            "working_memory_enabled = :working_memory"
        ),
        {
            "id": settings_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "profile_learning": profile_learning_enabled,
            "working_memory": working_memory_enabled,
        },
    )
    await db.commit()
    logger.info(
        "privacy_settings_updated",
        user_id=user_id,
        tenant_id=tenant_id,
        profile_learning_enabled=profile_learning_enabled,
        working_memory_enabled=working_memory_enabled,
    )
    return {
        "profile_learning_enabled": profile_learning_enabled,
        "working_memory_enabled": working_memory_enabled,
    }


async def get_privacy_settings(user_id: str, tenant_id: str, db) -> dict:
    """Get privacy settings for a user, returning defaults if none exist."""
    result = await db.execute(
        text(
            "SELECT profile_learning_enabled, working_memory_enabled "
            "FROM user_privacy_settings "
            "WHERE user_id = :user_id AND tenant_id = :tenant_id"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return {
            "profile_learning_enabled": True,
            "working_memory_enabled": True,
        }
    return {
        "profile_learning_enabled": row[0],
        "working_memory_enabled": row[1],
    }


async def gdpr_clear_working_memory(user_id: str, tenant_id: str) -> None:
    """Clear working memory via WorkingMemoryService (GDPR -- aihub2 bug fix)."""
    from app.modules.memory.working_memory import WorkingMemoryService

    wm = WorkingMemoryService()
    await wm.clear_memory(user_id, tenant_id)
    logger.info("gdpr_working_memory_cleared", user_id=user_id, tenant_id=tenant_id)


async def gdpr_clear_profile(user_id: str, tenant_id: str, db) -> None:
    """Delete profile data from user_profiles table."""
    await db.execute(
        text(
            "DELETE FROM user_profiles "
            "WHERE user_id = :user_id AND tenant_id = :tenant_id"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    await db.commit()
    logger.info("gdpr_profile_cleared", user_id=user_id, tenant_id=tenant_id)


async def gdpr_clear_l1_cache(user_id: str) -> None:
    """Clear L1 in-process cache for profile learning."""
    from app.modules.profile.learning import ProfileLearningService

    service = ProfileLearningService()
    await service.clear_l1_cache(user_id)
    logger.info("gdpr_l1_cache_cleared", user_id=user_id)


async def gdpr_reset_privacy_settings(user_id: str, tenant_id: str, db) -> None:
    """Soft-delete privacy settings by resetting to defaults (keep row)."""
    await db.execute(
        text(
            "UPDATE user_privacy_settings "
            "SET profile_learning_enabled = true, working_memory_enabled = true "
            "WHERE user_id = :user_id AND tenant_id = :tenant_id"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    await db.commit()
    logger.info("gdpr_privacy_settings_reset", user_id=user_id, tenant_id=tenant_id)


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/notes")
async def list_memory_notes(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-099: List all memory notes for the current user."""
    result = await list_notes_db(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    return result


@router.post("/notes", status_code=status.HTTP_201_CREATED)
async def create_memory_note(
    request: CreateNoteRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-100: Create a new memory note (max 200 characters).

    The 200-char limit is enforced by Pydantic Field(max_length=200)
    AND by validate_memory_note_content() for defense in depth.
    """
    from app.modules.memory.notes import (
        validate_memory_note_content,
        MemoryNoteValidationError,
    )

    try:
        clean_content = validate_memory_note_content(request.content)
    except MemoryNoteValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.message,
        )

    result = await create_note_db(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        content=clean_content,
        db=session,
    )
    return result


@router.delete("/notes", status_code=status.HTTP_204_NO_CONTENT)
async def clear_all_notes(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-103: Clear ALL memory notes for the current user."""
    await clear_all_notes_db(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    return None


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory_note(
    note_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-101: Delete a memory note by ID."""
    deleted = await delete_note_db(
        note_id=note_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory note '{note_id}' not found",
        )
    return None


@router.get("/profile")
async def get_user_profile(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-102: Get the current user's learned profile."""
    result = await get_profile_data(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    return result


@router.get("/working")
async def get_working_memory(
    agent_id: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-103: Get working memory summary for current user (optionally filtered by agent)."""
    effective_agent_id = agent_id or "default"
    result = await get_working_memory_data(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        agent_id=effective_agent_id,
        db=session,
    )
    return result


@router.delete("/working", status_code=status.HTTP_204_NO_CONTENT)
async def clear_working_memory(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-104: Clear all working memory for the current user across all agents."""
    await clear_working_memory_data(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    return None


@router.patch("/privacy")
async def update_privacy_settings(
    request: UpdatePrivacyRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-100: Update user privacy preferences."""
    result = await upsert_privacy_settings(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        profile_learning_enabled=request.profile_learning_enabled,
        working_memory_enabled=request.working_memory_enabled,
        db=session,
    )
    return result


@router.get("/export")
async def export_profile_data(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-104: Export all user profile data (GDPR data portability)."""
    profile = await get_profile_data(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    notes = await list_notes_db(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    working_memory = await get_working_memory_data(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        agent_id="default",
        db=session,
    )
    privacy_settings = await get_privacy_settings(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    return {
        "profile": profile,
        "notes": notes,
        "working_memory": working_memory,
        "privacy_settings": privacy_settings,
    }


@router.delete("/profile", status_code=status.HTTP_204_NO_CONTENT)
async def gdpr_erase_profile(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-105: GDPR comprehensive erasure.

    Clears all user data: notes, working memory, profile, L1 cache,
    and resets privacy settings to defaults.
    CRITICAL: This fixes the aihub2 bug where working memory was NOT cleared.
    """
    # 1. Clear memory notes
    await clear_all_notes_db(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )

    # 2. Clear working memory (aihub2 bug fix -- this was missing)
    await gdpr_clear_working_memory(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )

    # 3. Clear profile data
    await gdpr_clear_profile(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )

    # 4. Clear L1 in-process cache
    await gdpr_clear_l1_cache(user_id=current_user.id)

    # 5. Soft-delete privacy settings (reset to defaults)
    await gdpr_reset_privacy_settings(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )

    logger.info(
        "gdpr_erasure_complete",
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )
    return None
