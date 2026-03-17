"""
HAR-008: JSON Schema validator for A2A message payloads.

Loads schemas from the schemas/ directory and validates payloads
using jsonschema (draft 2020-12).

Validates inbound A2A messages at the receive endpoint and
outbound messages in route_message() before signing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import structlog

try:
    from jsonschema import Draft202012Validator

    _JSONSCHEMA_AVAILABLE = True
except ImportError:
    Draft202012Validator = None  # type: ignore[assignment,misc]
    _JSONSCHEMA_AVAILABLE = False

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Schema registry
# ---------------------------------------------------------------------------

_SCHEMA_DIR = Path(__file__).parent

# Mapping from message_type (uppercase) to JSON schema file name
_SCHEMA_FILES: dict[str, str] = {
    "CAPABILITY_QUERY": "capability_query.json",
    "RFQ": "rfq.json",
    "QUOTE_RESPONSE": "quote_response.json",
    "PO_PLACEMENT": "po_placement.json",
    "PO_ACKNOWLEDGEMENT": "po_acknowledgement.json",
    "DELIVERY_CONFIRMATION": "delivery_confirmation.json",
}

# Lazy-loaded schema cache (loaded on first validation request)
_schema_cache: dict[str, dict] = {}


def _load_schema(message_type: str) -> Optional[dict]:
    """Load and cache the JSON schema for a given message_type."""
    if message_type in _schema_cache:
        return _schema_cache[message_type]

    filename = _SCHEMA_FILES.get(message_type)
    if filename is None:
        return None

    schema_path = _SCHEMA_DIR / filename
    if not schema_path.exists():
        logger.error(
            "a2a_schema_file_missing",
            message_type=message_type,
            path=str(schema_path),
        )
        return None

    with open(schema_path) as f:
        schema = json.load(f)

    _schema_cache[message_type] = schema
    return schema


# ---------------------------------------------------------------------------
# Public validation function
# ---------------------------------------------------------------------------


def validate_message_payload(
    message_type: str,
    payload: dict,
) -> list[dict]:
    """
    Validate a message payload against its JSON schema.

    Args:
        message_type: One of the _SCHEMA_FILES keys (case-insensitive).
        payload:      The payload dict to validate.

    Returns:
        List of error dicts with keys 'path' and 'message'.
        Empty list means the payload is valid.
        Returns a single error if message_type is unknown.

    Does NOT raise — returns errors for the caller to handle.
    """
    normalised_type = message_type.upper()

    schema = _load_schema(normalised_type)
    if schema is None:
        return [
            {
                "path": "message_type",
                "message": (
                    f"Unknown message_type '{message_type}'. "
                    f"Supported types: {sorted(_SCHEMA_FILES.keys())}"
                ),
            }
        ]

    try:
        if not _JSONSCHEMA_AVAILABLE or Draft202012Validator is None:
            # jsonschema not available — log warning and skip validation
            logger.warning(
                "a2a_schema_validation_skipped_jsonschema_not_available",
                message_type=message_type,
            )
            return []

        validator = Draft202012Validator(schema)
        errors = list(validator.iter_errors(payload))
        if not errors:
            return []

        return [
            {
                "path": ".".join(str(p) for p in err.absolute_path) or "(root)",
                "message": err.message,
            }
            for err in errors
        ]
    except Exception as exc:
        logger.error(
            "a2a_schema_validation_error",
            message_type=message_type,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return []


def get_supported_message_types() -> list[str]:
    """Return list of all supported A2A message types."""
    return sorted(_SCHEMA_FILES.keys())
