"""
ProfileLearningService (DEF-004).

Handles collection of user behaviour signals for profile learning.
Before collecting any signals, checks user_privacy_settings.profile_learning_enabled.
If disabled, on_query_completed() returns early without collecting data.
"""
import json
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class ProfileLearningService:
    """Service for passive profile learning from user query patterns.

    DEF-004: All collection methods check profile_learning_enabled privacy
    setting before storing any signals. When disabled, they are no-ops.
    """

    async def on_query_completed(
        self,
        user_id: str,
        tenant_id: str,
        query: str,
        agent_id: str,
        db: AsyncSession,
    ) -> None:
        """Called after each successful query to collect learning signals.

        Checks profile_learning_enabled before collecting any data.
        Returns early (no-op) if the user has disabled profile learning.

        Args:
            user_id: User who submitted the query.
            tenant_id: Tenant scope for RLS.
            query: The user's query text.
            agent_id: Agent that handled the query.
            db: Async session for privacy setting check.
        """
        from app.modules.users.privacy_settings import (  # noqa: PLC0415 — deferred to avoid circular import
            _check_privacy_setting,
        )

        enabled = await _check_privacy_setting(
            db, tenant_id, user_id, "profile_learning_enabled"
        )
        if not enabled:
            logger.debug(
                "profile_learning_skipped_privacy",
                user_id=user_id,
                tenant_id=tenant_id,
            )
            return

        # Record query signal to analytics_events for profile learning.
        # Downstream analytics jobs aggregate these events to build
        # interest vectors (topic affinity, agent preference, query patterns).

        await db.execute(
            text(
                "INSERT INTO analytics_events "
                "  (id, tenant_id, user_id, feature_name, event_type, metadata, created_at) "
                "VALUES (:id, :tenant_id, :user_id, 'profile_learning', 'query', "
                "        CAST(:metadata AS jsonb), :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "user_id": user_id,
                "metadata": json.dumps({"agent_id": agent_id, "query_len": len(query)}),
                "created_at": datetime.now(timezone.utc),
            },
        )
        await db.commit()
        logger.debug(
            "profile_learning_signal_recorded",
            user_id=user_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            query_len=len(query),
        )
