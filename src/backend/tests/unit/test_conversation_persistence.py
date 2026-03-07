"""
Unit tests for ConversationPersistenceService (AI-059).

Tests conversation and message persistence logic.
Tier 1: Fast, isolated, mocks database.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestConversationPersistenceService:
    """Test conversation persistence operations."""

    @pytest.mark.asyncio
    async def test_save_exchange_creates_conversation_if_none(self):
        """If conversation_id is None, a new conversation is created."""
        from app.modules.chat.persistence import ConversationPersistenceService

        service = ConversationPersistenceService.__new__(ConversationPersistenceService)
        service._db = AsyncMock()
        service._db.execute = AsyncMock(
            side_effect=[
                # First call: insert conversation, return new ID
                MagicMock(scalar_one=MagicMock(return_value="conv-new-123")),
                # Second call: insert user message
                MagicMock(scalar_one=MagicMock(return_value="msg-user-1")),
                # Third call: insert assistant message
                MagicMock(scalar_one=MagicMock(return_value="msg-asst-1")),
            ]
        )

        msg_id, conv_id = await service.save_exchange(
            user_id="user-1",
            tenant_id="tenant-1",
            conversation_id=None,
            query="What is the leave policy?",
            response="The leave policy states...",
            sources=[],
        )

        assert conv_id == "conv-new-123"
        assert msg_id == "msg-asst-1"

    @pytest.mark.asyncio
    async def test_save_exchange_reuses_existing_conversation(self):
        """If conversation_id is provided, messages are added to it."""
        from app.modules.chat.persistence import ConversationPersistenceService

        service = ConversationPersistenceService.__new__(ConversationPersistenceService)
        service._db = AsyncMock()
        service._db.execute = AsyncMock(
            side_effect=[
                # First call: insert user message
                MagicMock(scalar_one=MagicMock(return_value="msg-user-2")),
                # Second call: insert assistant message
                MagicMock(scalar_one=MagicMock(return_value="msg-asst-2")),
            ]
        )

        msg_id, conv_id = await service.save_exchange(
            user_id="user-1",
            tenant_id="tenant-1",
            conversation_id="existing-conv",
            query="Follow up question",
            response="Here is the answer...",
            sources=[],
        )

        assert conv_id == "existing-conv"
        assert msg_id == "msg-asst-2"

    @pytest.mark.asyncio
    async def test_save_exchange_requires_user_id(self):
        """save_exchange raises ValueError if user_id is empty."""
        from app.modules.chat.persistence import ConversationPersistenceService

        service = ConversationPersistenceService.__new__(ConversationPersistenceService)
        service._db = AsyncMock()

        with pytest.raises(ValueError, match="user_id"):
            await service.save_exchange(
                user_id="",
                tenant_id="t1",
                conversation_id=None,
                query="test",
                response="test",
                sources=[],
            )

    @pytest.mark.asyncio
    async def test_save_exchange_requires_tenant_id(self):
        """save_exchange raises ValueError if tenant_id is empty."""
        from app.modules.chat.persistence import ConversationPersistenceService

        service = ConversationPersistenceService.__new__(ConversationPersistenceService)
        service._db = AsyncMock()

        with pytest.raises(ValueError, match="tenant_id"):
            await service.save_exchange(
                user_id="u1",
                tenant_id="",
                conversation_id=None,
                query="test",
                response="test",
                sources=[],
            )

    @pytest.mark.asyncio
    async def test_save_exchange_requires_query(self):
        """save_exchange raises ValueError if query is empty."""
        from app.modules.chat.persistence import ConversationPersistenceService

        service = ConversationPersistenceService.__new__(ConversationPersistenceService)
        service._db = AsyncMock()

        with pytest.raises(ValueError, match="[Qq]uery"):
            await service.save_exchange(
                user_id="u1",
                tenant_id="t1",
                conversation_id=None,
                query="",
                response="test",
                sources=[],
            )

    @pytest.mark.asyncio
    async def test_save_exchange_requires_response(self):
        """save_exchange raises ValueError if response is empty."""
        from app.modules.chat.persistence import ConversationPersistenceService

        service = ConversationPersistenceService.__new__(ConversationPersistenceService)
        service._db = AsyncMock()

        with pytest.raises(ValueError, match="[Rr]esponse"):
            await service.save_exchange(
                user_id="u1",
                tenant_id="t1",
                conversation_id=None,
                query="test",
                response="",
                sources=[],
            )
