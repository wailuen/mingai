"""ATA-001 unit tests: v045 migration schema fields in Pydantic models."""
import pytest
from pydantic import ValidationError

from app.modules.agents.routes import DeployAgentRequest, _ACCESS_CONTROL_MAP


def test_deploy_agent_request_has_allowed_roles():
    """DeployAgentRequest must include allowed_roles and allowed_user_ids."""
    req = DeployAgentRequest(
        name="Test Agent",
        access_control="workspace",
        allowed_roles=["hr_manager"],
        allowed_user_ids=[],
    )
    assert req.allowed_roles == ["hr_manager"]
    assert req.allowed_user_ids == []


def test_deploy_agent_request_defaults():
    req = DeployAgentRequest(name="Test", access_control="workspace")
    assert req.kb_ids == []
    assert req.allowed_roles == []
    assert req.allowed_user_ids == []


def test_deploy_agent_request_default_access_control():
    """access_control defaults to 'workspace' when not specified."""
    req = DeployAgentRequest(name="Test")
    assert req.access_control == "workspace"


def test_access_control_map_completeness():
    """_ACCESS_CONTROL_MAP must cover all 3 access_control values."""
    assert _ACCESS_CONTROL_MAP["workspace"] == "workspace_wide"
    assert _ACCESS_CONTROL_MAP["role"] == "role_restricted"
    assert _ACCESS_CONTROL_MAP["user"] == "user_specific"


def test_access_control_map_has_three_keys():
    """Exactly three keys — no extra entries."""
    assert len(_ACCESS_CONTROL_MAP) == 3


def test_deploy_agent_request_invalid_access_control():
    """access_control must be one of the three literals."""
    with pytest.raises(ValidationError):
        DeployAgentRequest(name="Test", access_control="admin")
