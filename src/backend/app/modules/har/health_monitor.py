"""
Agent Health Monitor background job (AI-048, AI-049).

Periodically recomputes trust scores for all published agents.
Runs as a background asyncio task on app startup.
"""
import asyncio

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.har.trust import compute_trust_score

logger = structlog.get_logger()

_LOW_TRUST_THRESHOLD = 30


class AgentHealthMonitor:
    """
    Background job: recomputes trust scores for all published agents.

    Usage:
        monitor = AgentHealthMonitor(db_session_factory, interval_seconds=3600)
        asyncio.create_task(monitor.start())
    """

    def __init__(self, db_session_factory, interval_seconds: int = 3600):
        self._db_session_factory = db_session_factory
        self._interval_seconds = interval_seconds

    async def run_once(self, db: AsyncSession) -> dict:
        """
        Run one health check cycle:
          1. Fetch all agents with status='published' from agent_cards
          2. Recompute trust_score for each agent
          3. Identify low-trust agents (score < 30)
          4. Return summary dict

        Returns:
            {
                "agents_checked": int,
                "avg_trust_score": int,
                "low_trust_agents": list[str],  # agent IDs with score < threshold
            }
        """
        result = await db.execute(
            text("SELECT id, tenant_id FROM agent_cards WHERE status = 'published'")
        )
        agents = list(result.mappings())

        if not agents:
            logger.info("agent_health_monitor_run", agents_checked=0)
            return {
                "agents_checked": 0,
                "avg_trust_score": 0,
                "low_trust_agents": [],
            }

        scores: list[int] = []
        low_trust_agents: list[str] = []

        for agent in agents:
            agent_id = str(agent["id"])
            tenant_id = str(agent["tenant_id"])
            try:
                score = await compute_trust_score(agent_id, tenant_id, db)
                scores.append(score)
                if score < _LOW_TRUST_THRESHOLD:
                    low_trust_agents.append(agent_id)
            except Exception as exc:
                logger.error(
                    "agent_health_monitor_score_error",
                    agent_id=agent_id,
                    error=str(exc),
                )
                scores.append(0)
                low_trust_agents.append(agent_id)

        avg_score = round(sum(scores) / len(scores)) if scores else 0

        summary = {
            "agents_checked": len(agents),
            "avg_trust_score": avg_score,
            "low_trust_agents": low_trust_agents,
        }

        logger.info(
            "agent_health_monitor_run",
            **summary,
        )

        if low_trust_agents:
            logger.warning(
                "agent_health_monitor_low_trust_detected",
                low_trust_count=len(low_trust_agents),
                agent_ids=low_trust_agents,
            )

        return summary

    async def start(self) -> None:
        """Start the background monitoring loop."""
        logger.info(
            "agent_health_monitor_started",
            interval_seconds=self._interval_seconds,
        )
        while True:
            try:
                async with self._db_session_factory() as db:
                    await self.run_once(db)
                    await db.commit()
            except Exception as exc:
                logger.error(
                    "agent_health_monitor_cycle_error",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            await asyncio.sleep(self._interval_seconds)
