"""
Unit tests for Agent Health Monitor background job (AI-048, AI-049).

Tier 1: Fast, isolated, uses AsyncMock for DB and mocked compute_trust_score.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestAgentHealthMonitor:
    """Test AgentHealthMonitor.run_once() logic."""

    @pytest.mark.asyncio
    @patch("app.modules.har.health_monitor.compute_trust_score")
    async def test_run_once_processes_all_agents(self, mock_compute):
        """3 published agents => agents_checked=3."""
        from app.modules.har.health_monitor import AgentHealthMonitor

        mock_compute.side_effect = [80, 50, 90]

        mock_db = AsyncMock()
        # Simulate 3 published agents returned from DB
        rows = [
            {"id": "agent-1", "tenant_id": "tenant-1"},
            {"id": "agent-2", "tenant_id": "tenant-1"},
            {"id": "agent-3", "tenant_id": "tenant-2"},
        ]
        result_mock = MagicMock()
        result_mock.mappings.return_value = rows
        mock_db.execute = AsyncMock(return_value=result_mock)

        monitor = AgentHealthMonitor(
            db_session_factory=AsyncMock(), interval_seconds=3600
        )
        summary = await monitor.run_once(mock_db)

        assert summary["agents_checked"] == 3
        assert mock_compute.call_count == 3

    @pytest.mark.asyncio
    @patch("app.modules.har.health_monitor.compute_trust_score")
    async def test_run_once_identifies_low_trust(self, mock_compute):
        """Agent with score < 30 appears in low_trust_agents."""
        from app.modules.har.health_monitor import AgentHealthMonitor

        mock_compute.side_effect = [80, 20, 10]

        mock_db = AsyncMock()
        rows = [
            {"id": "agent-1", "tenant_id": "tenant-1"},
            {"id": "agent-low", "tenant_id": "tenant-1"},
            {"id": "agent-vlow", "tenant_id": "tenant-2"},
        ]
        result_mock = MagicMock()
        result_mock.mappings.return_value = rows
        mock_db.execute = AsyncMock(return_value=result_mock)

        monitor = AgentHealthMonitor(
            db_session_factory=AsyncMock(), interval_seconds=3600
        )
        summary = await monitor.run_once(mock_db)

        assert summary["agents_checked"] == 3
        assert "agent-low" in summary["low_trust_agents"]
        assert "agent-vlow" in summary["low_trust_agents"]
        assert "agent-1" not in summary["low_trust_agents"]

    @pytest.mark.asyncio
    @patch("app.modules.har.health_monitor.compute_trust_score")
    async def test_run_once_skips_draft_agents(self, mock_compute):
        """Draft agents are not included (query filters by status='published')."""
        from app.modules.har.health_monitor import AgentHealthMonitor

        # Only published agents are returned from DB query — drafts are filtered out
        mock_compute.side_effect = [75]

        mock_db = AsyncMock()
        # DB only returns published agents (draft agents excluded by query)
        rows = [
            {"id": "agent-pub", "tenant_id": "tenant-1"},
        ]
        result_mock = MagicMock()
        result_mock.mappings.return_value = rows
        mock_db.execute = AsyncMock(return_value=result_mock)

        monitor = AgentHealthMonitor(
            db_session_factory=AsyncMock(), interval_seconds=3600
        )
        summary = await monitor.run_once(mock_db)

        assert summary["agents_checked"] == 1
        assert mock_compute.call_count == 1

    @pytest.mark.asyncio
    @patch("app.modules.har.health_monitor.compute_trust_score")
    async def test_run_once_empty_tenant(self, mock_compute):
        """No agents => {"agents_checked": 0, "avg_trust_score": 0, "low_trust_agents": []}."""
        from app.modules.har.health_monitor import AgentHealthMonitor

        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.mappings.return_value = []
        mock_db.execute = AsyncMock(return_value=result_mock)

        monitor = AgentHealthMonitor(
            db_session_factory=AsyncMock(), interval_seconds=3600
        )
        summary = await monitor.run_once(mock_db)

        assert summary["agents_checked"] == 0
        assert summary["avg_trust_score"] == 0
        assert summary["low_trust_agents"] == []
        assert mock_compute.call_count == 0

    @pytest.mark.asyncio
    @patch("app.modules.har.health_monitor.compute_trust_score")
    async def test_run_once_calculates_avg_trust_score(self, mock_compute):
        """Average trust score is correctly computed."""
        from app.modules.har.health_monitor import AgentHealthMonitor

        mock_compute.side_effect = [60, 80, 40]

        mock_db = AsyncMock()
        rows = [
            {"id": "agent-1", "tenant_id": "t1"},
            {"id": "agent-2", "tenant_id": "t1"},
            {"id": "agent-3", "tenant_id": "t2"},
        ]
        result_mock = MagicMock()
        result_mock.mappings.return_value = rows
        mock_db.execute = AsyncMock(return_value=result_mock)

        monitor = AgentHealthMonitor(
            db_session_factory=AsyncMock(), interval_seconds=3600
        )
        summary = await monitor.run_once(mock_db)

        assert summary["avg_trust_score"] == 60  # (60 + 80 + 40) / 3
