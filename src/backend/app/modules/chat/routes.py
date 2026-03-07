"""
Chat API routes (API-007 to API-014).

Endpoints:
- POST /stream         — SSE streaming chat
- POST /feedback       — Submit thumbs up/down feedback
- GET  /conversations  — List conversations (paginated)
- GET  /conversations/{id} — Get conversation with messages
- DELETE /conversations/{id} — Delete conversation
- POST /issues         — Submit issue report
- GET  /issues/{id}    — Get issue
"""
import json
import uuid
from typing import AsyncGenerator, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends as _Depends

from app.core.dependencies import CurrentUser, get_current_user
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(tags=["chat"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """POST /api/v1/chat/stream request body."""

    query: str = Field(..., min_length=1, max_length=10000)
    agent_id: str = Field(..., min_length=1, max_length=100)
    conversation_id: Optional[str] = None
    active_team_id: Optional[str] = None


class FeedbackRequest(BaseModel):
    """POST /api/v1/chat/feedback request body."""

    message_id: str = Field(..., min_length=1, max_length=200)
    rating: Literal["up", "down"]
    comment: Optional[str] = Field(None, max_length=2000)


class IssueRequest(BaseModel):
    """POST /api/v1/issues request body."""

    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(..., min_length=1, max_length=10000)
    message_id: Optional[str] = Field(None, max_length=200)


# ---------------------------------------------------------------------------
# Helper functions (mockable for unit tests)
# ---------------------------------------------------------------------------


def build_orchestrator(db, redis):
    """
    Build a ChatOrchestrationService wired with all dependencies.

    All sub-services are constructed here with the request-scoped
    db session and redis connection.
    """
    from app.modules.chat.embedding import EmbeddingService
    from app.modules.chat.orchestrator import ChatOrchestrationService
    from app.modules.chat.persistence import ConversationPersistenceService
    from app.modules.chat.prompt_builder import SystemPromptBuilder
    from app.modules.chat.vector_search import VectorSearchService
    from app.modules.glossary.expander import GlossaryExpander
    from app.modules.memory.org_context import OrgContextService
    from app.modules.memory.working_memory import WorkingMemoryService
    from app.modules.profile.learning import ProfileLearningService

    class _ConfidenceCalc:
        def calculate(self, sources: list) -> float:
            if not sources:
                return 0.0
            return min(1.0, len(sources) * 0.2)

    return ChatOrchestrationService(
        embedding_service=EmbeddingService(),
        vector_search_service=VectorSearchService(db_session=db),
        profile_service=ProfileLearningService(db_session=db),
        working_memory_service=WorkingMemoryService(),
        org_context_service=OrgContextService(db_session=db),
        glossary_expander=GlossaryExpander(),
        prompt_builder=SystemPromptBuilder(),
        persistence_service=ConversationPersistenceService(db_session=db),
        confidence_calculator=_ConfidenceCalc(),
    )


async def save_feedback(
    message_id: str,
    rating: str,
    comment: Optional[str],
    user_id: str,
    tenant_id: str,
    db,
) -> dict:
    """Persist user feedback to user_feedback table."""
    feedback_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO user_feedback (id, message_id, user_id, tenant_id, rating, comment) "
            "VALUES (:id, :message_id, :user_id, :tenant_id, :rating, :comment)"
        ),
        {
            "id": feedback_id,
            "message_id": message_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "rating": rating,
            "comment": comment,
        },
    )
    await db.commit()
    logger.info("feedback_saved", feedback_id=feedback_id, rating=rating)
    return {"id": feedback_id, "rating": rating}


async def list_conversations(
    user_id: str,
    tenant_id: str,
    page: int,
    page_size: int,
    db,
) -> dict:
    """List conversations for user, newest first."""
    offset = (page - 1) * page_size
    count_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM conversations WHERE user_id = :user_id AND tenant_id = :tenant_id"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        text(
            "SELECT id, title, created_at, updated_at FROM conversations "
            "WHERE user_id = :user_id AND tenant_id = :tenant_id "
            "ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"
        ),
        {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "limit": page_size,
            "offset": offset,
        },
    )
    rows = rows_result.fetchall()
    items = [
        {
            "id": str(r[0]),
            "title": r[1],
            "created_at": str(r[2]),
            "updated_at": str(r[3]),
        }
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def get_conversation(
    conversation_id: str,
    user_id: str,
    tenant_id: str,
    db,
) -> Optional[dict]:
    """Get a conversation with all messages."""
    conv_result = await db.execute(
        text(
            "SELECT id, title, created_at FROM conversations "
            "WHERE id = :id AND user_id = :user_id AND tenant_id = :tenant_id"
        ),
        {"id": conversation_id, "user_id": user_id, "tenant_id": tenant_id},
    )
    row = conv_result.fetchone()
    if row is None:
        return None

    msgs_result = await db.execute(
        text(
            "SELECT id, role, content, created_at FROM messages "
            "WHERE conversation_id = :conv_id ORDER BY created_at ASC"
        ),
        {"conv_id": conversation_id},
    )
    messages = [
        {"id": str(m[0]), "role": m[1], "content": m[2], "created_at": str(m[3])}
        for m in msgs_result.fetchall()
    ]
    return {
        "id": str(row[0]),
        "title": row[1],
        "created_at": str(row[2]),
        "messages": messages,
    }


async def delete_conversation(
    conversation_id: str,
    user_id: str,
    tenant_id: str,
    db,
) -> bool:
    """Delete a conversation. Returns True if deleted, False if not found."""
    result = await db.execute(
        text(
            "DELETE FROM conversations WHERE id = :id AND user_id = :user_id AND tenant_id = :tenant_id"
        ),
        {"id": conversation_id, "user_id": user_id, "tenant_id": tenant_id},
    )
    await db.commit()
    return (result.rowcount or 0) > 0


async def create_issue(
    title: str,
    description: str,
    message_id: Optional[str],
    user_id: str,
    tenant_id: str,
    db,
) -> dict:
    """Create an issue report."""
    issue_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO issue_reports (id, tenant_id, user_id, title, description, "
            "source_message_id, status) "
            "VALUES (:id, :tenant_id, :user_id, :title, :description, :message_id, 'open')"
        ),
        {
            "id": issue_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "title": title,
            "description": description,
            "message_id": message_id,
        },
    )
    await db.commit()
    logger.info("issue_created", issue_id=issue_id, user_id=user_id)
    return {"id": issue_id, "status": "open", "title": title}


async def get_issue(
    issue_id: str,
    user_id: str,
    tenant_id: str,
    db,
) -> Optional[dict]:
    """Get an issue report."""
    result = await db.execute(
        text(
            "SELECT id, title, description, status, created_at FROM issue_reports "
            "WHERE id = :id AND tenant_id = :tenant_id AND user_id = :user_id"
        ),
        {"id": issue_id, "tenant_id": tenant_id, "user_id": user_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "title": row[1],
        "description": row[2],
        "status": row[3],
        "created_at": str(row[4]),
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post("/chat/stream")
async def stream_chat(
    request: ChatRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    API-007: SSE streaming chat endpoint.

    Executes the 8-stage RAG pipeline and streams events back to the client.
    Rate limit: 30 requests/min (enforced at gateway / middleware layer).
    """
    # Import inline to allow mocking in tests
    from app.core.database import validate_tenant_id

    validate_tenant_id(current_user.tenant_id)

    jwt_claims = {
        "sub": current_user.id,
        "tenant_id": current_user.tenant_id,
        "roles": current_user.roles,
        "scope": current_user.scope,
        "plan": current_user.plan,
    }

    orchestrator = build_orchestrator(db=None, redis=None)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for event in orchestrator.stream_response(
                query=request.query,
                user_id=current_user.id,
                tenant_id=current_user.tenant_id,
                agent_id=request.agent_id,
                conversation_id=request.conversation_id,
                active_team_id=request.active_team_id,
                jwt_claims=jwt_claims,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            logger.error(
                "stream_error",
                user_id=current_user.id,
                error=str(exc),
            )
            yield f"data: {json.dumps({'type': 'error', 'message': 'Stream error'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/chat/feedback")
async def submit_feedback(
    request: FeedbackRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-008: Submit thumbs up/down feedback on an AI response.
    """
    result = await save_feedback(
        message_id=request.message_id,
        rating=request.rating,
        comment=request.comment,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    return result


@router.get("/conversations")
async def list_user_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-009: List conversations for the authenticated user (paginated).
    """
    result = await list_conversations(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        page=page,
        page_size=page_size,
        db=session,
    )
    return result


@router.get("/conversations/{conversation_id}")
async def get_conversation_detail(
    conversation_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-010: Get a conversation with all messages.
    """
    result = await get_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found",
        )
    return result


@router.delete(
    "/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_user_conversation(
    conversation_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-011: Delete a conversation and all its messages.
    """
    deleted = await delete_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found",
        )
    return None


@router.post("/issues", status_code=status.HTTP_201_CREATED)
async def submit_issue(
    request: IssueRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-012: Submit an issue report linked to a chat message.
    """
    result = await create_issue(
        title=request.title,
        description=request.description,
        message_id=request.message_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    return result


@router.get("/issues/{issue_id}")
async def get_issue_detail(
    issue_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-013: Get an issue report by ID.
    """
    result = await get_issue(
        issue_id=issue_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue '{issue_id}' not found",
        )
    return result
