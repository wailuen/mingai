"""
ConversationPersistenceService (AI-059).

Saves conversations and messages to PostgreSQL.
Handles conversation creation, message insertion, and title generation.
All operations are tenant-scoped via RLS.
"""
import json

import structlog
from sqlalchemy import text

logger = structlog.get_logger()


class ConversationPersistenceService:
    """
    Persists chat exchanges to the conversations and messages tables.

    Creates new conversations when needed, adds user and assistant
    messages, and returns IDs for the SSE done event.
    """

    def __init__(self, db_session):
        """
        Initialize with a database session.

        Args:
            db_session: An async database session with execute() method.
        """
        self._db = db_session

    async def save_exchange(
        self,
        user_id: str,
        tenant_id: str,
        conversation_id: str | None,
        query: str,
        response: str,
        sources: list,
        guardrail_violations: list | None = None,
    ) -> tuple[str, str]:
        """
        Save a complete query-response exchange.

        Creates a conversation if conversation_id is None.
        Inserts both user message and assistant message.

        Args:
            user_id: The user who sent the query.
            tenant_id: Tenant for RLS scoping.
            conversation_id: Existing conversation ID, or None to create new.
            query: The user's query text.
            response: The assistant's response text.
            sources: List of SearchResult objects (for metadata).
            guardrail_violations: Optional list of guardrail violation dicts to
                merge into the assistant message metadata JSONB. Original blocked
                response text MUST NOT appear here (RULE A2A-01).

        Returns:
            Tuple of (assistant_message_id, conversation_id).

        Raises:
            ValueError: If required parameters are missing.
        """
        if not user_id:
            raise ValueError(
                "user_id is required for conversation persistence. "
                "Cannot save anonymous exchanges."
            )
        if not tenant_id:
            raise ValueError(
                "tenant_id is required for conversation persistence. "
                "All conversations must be tenant-scoped."
            )
        if not query or not query.strip():
            raise ValueError("Query text is required. Cannot persist an empty query.")
        if not response or not response.strip():
            raise ValueError(
                "Response text is required. Cannot persist an empty response."
            )

        # Create conversation if needed
        if conversation_id is None:
            title = self._generate_title(query)
            result = await self._db.execute(
                text(self._insert_conversation_sql()),
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "title": title,
                },
            )
            conversation_id = str(result.scalar_one())

            logger.info(
                "conversation_created",
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )

        # Insert user message
        result = await self._db.execute(
            text(self._insert_message_sql()),
            {
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "role": "user",
                "content": query,
            },
        )
        user_msg_id = result.scalar_one()

        # Insert assistant message
        source_metadata = [
            {
                "title": s.title if hasattr(s, "title") else str(s),
                "score": s.score if hasattr(s, "score") else 0.0,
            }
            for s in sources
        ]

        # Build metadata dict; merge guardrail_violations if non-empty (ATA-021)
        # RULE A2A-01: Original blocked response text must NEVER appear here.
        assistant_metadata: dict = {"sources": source_metadata}
        if guardrail_violations:
            assistant_metadata["guardrail_violations"] = guardrail_violations

        result = await self._db.execute(
            text(self._insert_assistant_message_sql()),
            {
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "role": "assistant",
                "content": response,
                "metadata": json.dumps(assistant_metadata),
            },
        )
        assistant_msg_id = result.scalar_one()

        await self._db.commit()

        logger.info(
            "exchange_persisted",
            conversation_id=conversation_id,
            user_msg_id=user_msg_id,
            assistant_msg_id=assistant_msg_id,
            tenant_id=tenant_id,
        )

        return str(assistant_msg_id), str(conversation_id)

    @staticmethod
    def _generate_title(query: str) -> str:
        """
        Generate a conversation title from the first query.

        Truncates to 100 characters max. Uses first sentence or
        first 100 chars, whichever is shorter.
        """
        title = query.strip()
        # Use first sentence
        for sep in [".", "?", "!"]:
            idx = title.find(sep)
            if 0 < idx < 100:
                title = title[: idx + 1]
                break
        # Truncate if still too long
        if len(title) > 100:
            title = title[:97] + "..."
        return title

    @staticmethod
    def _insert_conversation_sql() -> str:
        """SQL template for inserting a new conversation."""
        return (
            "INSERT INTO conversations (tenant_id, user_id, title) "
            "VALUES (:tenant_id, :user_id, :title) "
            "RETURNING id"
        )

    @staticmethod
    def _insert_message_sql() -> str:
        """SQL template for inserting a message (no metadata)."""
        return (
            "INSERT INTO messages (tenant_id, conversation_id, role, content) "
            "VALUES (:tenant_id, :conversation_id, :role, :content) "
            "RETURNING id"
        )

    @staticmethod
    def _insert_assistant_message_sql() -> str:
        """SQL template for inserting an assistant message with metadata."""
        return (
            "INSERT INTO messages (tenant_id, conversation_id, role, content, metadata) "
            "VALUES (:tenant_id, :conversation_id, :role, :content, CAST(:metadata AS jsonb)) "
            "RETURNING id"
        )
