"""
Memory API routes (API-099 to API-105).

Endpoints:
- GET    /memory/notes          — List memory notes
- POST   /memory/notes          — Create memory note (max 200 chars)
- DELETE /memory/notes/{id}     — Delete memory note
- GET    /memory/profile        — Get user profile
- GET    /memory/working        — Get working memory summary
- DELETE /memory/working        — Clear working memory
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.dependencies import CurrentUser, get_current_user
from app.modules.memory.notes import MAX_NOTE_CONTENT_LENGTH

logger = structlog.get_logger()

router = APIRouter(prefix="/memory", tags=["memory"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateNoteRequest(BaseModel):
    """POST /api/v1/memory/notes request body."""

    content: str = Field(..., min_length=1, max_length=MAX_NOTE_CONTENT_LENGTH)


# ---------------------------------------------------------------------------
# DB / service helper functions (mockable in unit tests)
# ---------------------------------------------------------------------------


async def list_notes_db(user_id: str, tenant_id: str, db) -> list:
    """List all memory notes for the user."""
    result = await db.execute(
        "SELECT id, content, source, created_at FROM memory_notes "
        "WHERE user_id = :user_id AND tenant_id = :tenant_id "
        "ORDER BY created_at DESC",
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    return [
        {"id": r[0], "content": r[1], "source": r[2], "created_at": str(r[3])}
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
        "INSERT INTO memory_notes (id, user_id, tenant_id, content, source) "
        "VALUES (:id, :user_id, :tenant_id, :content, 'user_directed')",
        {"id": note_id, "user_id": user_id, "tenant_id": tenant_id, "content": content},
    )
    logger.info("memory_note_created", note_id=note_id, user_id=user_id)
    return {"id": note_id, "content": content, "source": "user_directed"}


async def delete_note_db(note_id: str, user_id: str, tenant_id: str, db) -> bool:
    """Delete a memory note owned by the user."""
    result = await db.execute(
        "DELETE FROM memory_notes "
        "WHERE id = :id AND user_id = :user_id AND tenant_id = :tenant_id",
        {"id": note_id, "user_id": user_id, "tenant_id": tenant_id},
    )
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


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/notes")
async def list_memory_notes(
    current_user: CurrentUser = Depends(get_current_user),
):
    """API-099: List all memory notes for the current user."""
    result = await list_notes_db(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=None,
    )
    return result


@router.post("/notes", status_code=status.HTTP_201_CREATED)
async def create_memory_note(
    request: CreateNoteRequest,
    current_user: CurrentUser = Depends(get_current_user),
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
        db=None,
    )
    return result


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory_note(
    note_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """API-101: Delete a memory note by ID."""
    deleted = await delete_note_db(
        note_id=note_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=None,
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
):
    """API-102: Get the current user's learned profile."""
    result = await get_profile_data(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=None,
    )
    return result


@router.get("/working")
async def get_working_memory(
    agent_id: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    """API-103: Get working memory summary for current user (optionally filtered by agent)."""
    effective_agent_id = agent_id or "default"
    result = await get_working_memory_data(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        agent_id=effective_agent_id,
        db=None,
    )
    return result


@router.delete("/working", status_code=status.HTTP_204_NO_CONTENT)
async def clear_working_memory(
    current_user: CurrentUser = Depends(get_current_user),
):
    """API-104: Clear all working memory for the current user across all agents."""
    await clear_working_memory_data(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=None,
    )
    return None
