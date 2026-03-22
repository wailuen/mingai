"""
Tool generator for the PA MCP Builder (TODO-22).

Generates tool catalog records from parsed API endpoint definitions.
Records are structured for insertion into the tool catalog table.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog

from app.modules.agents.api_doc_parser import ParsedEndpoint

logger = structlog.get_logger()


def generate_tool_record(
    endpoint: ParsedEndpoint,
    tool_name: str,
    description: str,
    base_url: str,
    credential_schema: list[dict[str, Any]],
    credential_source: str,
    rate_limit: Optional[dict[str, Any]] = None,
    plan_required: Optional[str] = None,
) -> dict[str, Any]:
    """
    Generate a tool catalog record from a parsed API endpoint.

    Args:
        endpoint: The parsed endpoint definition.
        tool_name: The snake_case tool identifier.
        description: Human-readable description for the tool.
        base_url: The base URL of the API (without trailing slash).
        credential_schema: List of credential field definitions.
        credential_source: One of 'none', 'platform_managed', 'tenant_managed'.
        rate_limit: Optional rate limit config, e.g. {'requests_per_minute': 60}.
        plan_required: Optional plan tier required to use this tool.

    Returns:
        A dict representing the tool catalog record.
    """
    # Construct the full endpoint URL from base_url + endpoint path
    endpoint_url = base_url.rstrip("/") + endpoint.path

    record: dict[str, Any] = {
        "tool_name": tool_name,
        "description": description,
        "executor": "http_wrapper",
        "endpoint_url": endpoint_url,
        "http_method": endpoint.method,
        "scope": "platform",
        "credential_schema": credential_schema,
        "credential_source": credential_source,
        "parameters_schema": {
            "type": "object",
            "properties": {
                p["name"]: {
                    "type": p.get("schema", {}).get("type", "string"),
                    "description": p.get("description", ""),
                }
                for p in endpoint.parameters
            },
            "required": [p["name"] for p in endpoint.parameters if p.get("required", False)],
        },
    }

    if rate_limit is not None:
        record["rate_limit"] = rate_limit

    if plan_required is not None:
        record["plan_required"] = plan_required

    logger.info(
        "tool_record_generated",
        tool_name=tool_name,
        endpoint_url=endpoint_url,
        executor="http_wrapper",
    )

    return record
