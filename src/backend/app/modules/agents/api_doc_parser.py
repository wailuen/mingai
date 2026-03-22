"""
API doc parser for the PA MCP Builder (TODO-22).

Parses OpenAPI 3.x JSON/YAML documents and extracts endpoint definitions
that can be used to generate tool catalog records.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class ParsedEndpoint:
    """A single API endpoint extracted from an API document."""

    method: str
    path: str
    summary: str
    description: str
    parameters: list[dict[str, Any]]
    request_body_schema: Optional[dict[str, Any]]
    response_schema: Optional[dict[str, Any]]
    operation_id: Optional[str] = None
    tags: list[str] = field(default_factory=list)


@dataclass
class ParsedAPIDoc:
    """Result of parsing an API document."""

    title: str
    version: str
    endpoints: list[ParsedEndpoint]
    base_url: Optional[str] = None


class APIDocParser:
    """
    Parses API documentation (OpenAPI 3.x) into structured endpoint definitions.

    Supports:
    - OpenAPI 3.x (JSON)
    """

    def parse(self, content: str, format_hint: str = "openapi") -> ParsedAPIDoc:
        """
        Parse an API document string.

        Args:
            content: The document content as a string (JSON).
            format_hint: Document format hint. Currently only 'openapi' is supported.

        Returns:
            ParsedAPIDoc with extracted endpoints.
        """
        if format_hint == "openapi":
            return self._parse_openapi(content)
        raise ValueError(f"Unsupported format: {format_hint!r}. Only 'openapi' is supported.")

    def _parse_openapi(self, content: str) -> ParsedAPIDoc:
        """Parse an OpenAPI 3.x document."""
        try:
            doc = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in API document: {exc}") from exc

        info = doc.get("info", {})
        title = info.get("title", "Unknown API")
        version = info.get("version", "1.0.0")

        # Extract base URL from servers if available
        base_url: Optional[str] = None
        servers = doc.get("servers", [])
        if servers:
            base_url = servers[0].get("url")

        endpoints: list[ParsedEndpoint] = []
        paths = doc.get("paths", {})

        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method in ("get", "post", "put", "patch", "delete", "head", "options"):
                operation = path_item.get(method)
                if not isinstance(operation, dict):
                    continue

                summary = operation.get("summary", "") or ""
                description = operation.get("description", "") or ""
                operation_id = operation.get("operationId")
                tags = operation.get("tags", [])

                # Extract parameters
                parameters: list[dict[str, Any]] = []
                for param in operation.get("parameters", []):
                    parameters.append({
                        "name": param.get("name", ""),
                        "in": param.get("in", "query"),
                        "required": param.get("required", False),
                        "description": param.get("description", ""),
                        "schema": param.get("schema", {}),
                    })

                # Extract request body schema
                request_body_schema: Optional[dict[str, Any]] = None
                request_body = operation.get("requestBody")
                if request_body:
                    content_types = request_body.get("content", {})
                    json_content = content_types.get("application/json", {})
                    request_body_schema = json_content.get("schema")

                # Extract response schema (from 200/201 response)
                response_schema: Optional[dict[str, Any]] = None
                responses = operation.get("responses", {})
                for status_code in ("200", "201"):
                    resp = responses.get(status_code)
                    if isinstance(resp, dict):
                        content_types = resp.get("content", {})
                        json_content = content_types.get("application/json", {})
                        response_schema = json_content.get("schema")
                        if response_schema:
                            break

                endpoints.append(
                    ParsedEndpoint(
                        method=method.upper(),
                        path=path,
                        summary=summary,
                        description=description,
                        parameters=parameters,
                        request_body_schema=request_body_schema,
                        response_schema=response_schema,
                        operation_id=operation_id,
                        tags=tags,
                    )
                )

        logger.info(
            "api_doc_parsed",
            title=title,
            endpoint_count=len(endpoints),
        )

        return ParsedAPIDoc(
            title=title,
            version=version,
            endpoints=endpoints,
            base_url=base_url,
        )
