"""
HAR-008: JSON Schema validation unit tests.

Tests valid and invalid payloads for all 6 A2A message types:
- CAPABILITY_QUERY
- RFQ
- QUOTE_RESPONSE
- PO_PLACEMENT
- PO_ACKNOWLEDGEMENT
- DELIVERY_CONFIRMATION

Also tests unknown message_type returns error.
"""
import pytest

from app.modules.registry.schemas.validator import (
    get_supported_message_types,
    validate_message_payload,
)


# ---------------------------------------------------------------------------
# CAPABILITY_QUERY
# ---------------------------------------------------------------------------


def test_capability_query_valid():
    """Valid CAPABILITY_QUERY passes schema validation."""
    payload = {
        "requester_agent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    }
    errors = validate_message_payload("CAPABILITY_QUERY", payload)
    assert errors == []


def test_capability_query_missing_required_field():
    """CAPABILITY_QUERY missing requester_agent_id returns error."""
    errors = validate_message_payload("CAPABILITY_QUERY", {})
    assert len(errors) > 0
    assert any("requester_agent_id" in e["message"] for e in errors)


# ---------------------------------------------------------------------------
# RFQ
# ---------------------------------------------------------------------------


def test_rfq_valid():
    """Valid RFQ passes schema validation."""
    payload = {
        "requester_agent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "items": [
            {"description": "Widget A", "quantity": 100}
        ],
    }
    errors = validate_message_payload("RFQ", payload)
    assert errors == []


def test_rfq_missing_items():
    """RFQ missing items returns error."""
    payload = {
        "requester_agent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    }
    errors = validate_message_payload("RFQ", payload)
    assert len(errors) > 0


def test_rfq_empty_items_list():
    """RFQ with empty items list returns validation error (minItems: 1)."""
    payload = {
        "requester_agent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "items": [],
    }
    errors = validate_message_payload("RFQ", payload)
    assert len(errors) > 0


def test_rfq_item_missing_quantity():
    """RFQ item without quantity returns validation error."""
    payload = {
        "requester_agent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "items": [{"description": "Widget A"}],  # missing quantity
    }
    errors = validate_message_payload("RFQ", payload)
    assert len(errors) > 0


# ---------------------------------------------------------------------------
# QUOTE_RESPONSE
# ---------------------------------------------------------------------------


def test_quote_response_valid():
    """Valid QUOTE_RESPONSE passes schema validation."""
    payload = {
        "rfq_transaction_id": "HAR-20260317-001234",
        "responder_agent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "line_items": [
            {"description": "Widget A", "quantity": 100, "unit_price": 5.50}
        ],
        "total_amount": 550.00,
        "currency": "USD",
    }
    errors = validate_message_payload("QUOTE_RESPONSE", payload)
    assert errors == []


def test_quote_response_missing_total_amount():
    """QUOTE_RESPONSE missing total_amount returns error."""
    payload = {
        "rfq_transaction_id": "HAR-20260317-001234",
        "responder_agent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "line_items": [
            {"description": "Widget A", "quantity": 100, "unit_price": 5.50}
        ],
        "currency": "USD",
        # missing total_amount
    }
    errors = validate_message_payload("QUOTE_RESPONSE", payload)
    assert len(errors) > 0


# ---------------------------------------------------------------------------
# PO_PLACEMENT
# ---------------------------------------------------------------------------


def test_po_placement_valid():
    """Valid PO_PLACEMENT passes schema validation."""
    payload = {
        "buyer_agent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "seller_agent_id": "b2c3d4e5-f6a7-8901-bcde-f23456789012",
        "po_number": "PO-2026-001",
        "line_items": [
            {"description": "Widget A", "quantity": 50, "unit_price": 5.50}
        ],
        "total_amount": 275.00,
        "currency": "USD",
    }
    errors = validate_message_payload("PO_PLACEMENT", payload)
    assert errors == []


def test_po_placement_missing_po_number():
    """PO_PLACEMENT missing po_number returns error."""
    payload = {
        "buyer_agent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "seller_agent_id": "b2c3d4e5-f6a7-8901-bcde-f23456789012",
        "line_items": [
            {"description": "Widget A", "quantity": 50, "unit_price": 5.50}
        ],
        "total_amount": 275.00,
        "currency": "USD",
    }
    errors = validate_message_payload("PO_PLACEMENT", payload)
    assert len(errors) > 0


# ---------------------------------------------------------------------------
# PO_ACKNOWLEDGEMENT
# ---------------------------------------------------------------------------


def test_po_acknowledgement_valid():
    """Valid PO_ACKNOWLEDGEMENT passes schema validation."""
    payload = {
        "seller_agent_id": "b2c3d4e5-f6a7-8901-bcde-f23456789012",
        "po_transaction_id": "HAR-20260317-001234",
        "acknowledged_po_number": "PO-2026-001",
        "status": "accepted",
    }
    errors = validate_message_payload("PO_ACKNOWLEDGEMENT", payload)
    assert errors == []


def test_po_acknowledgement_invalid_status():
    """PO_ACKNOWLEDGEMENT with invalid status returns error."""
    payload = {
        "seller_agent_id": "b2c3d4e5-f6a7-8901-bcde-f23456789012",
        "po_transaction_id": "HAR-20260317-001234",
        "acknowledged_po_number": "PO-2026-001",
        "status": "UNKNOWN_STATUS",  # invalid
    }
    errors = validate_message_payload("PO_ACKNOWLEDGEMENT", payload)
    assert len(errors) > 0


# ---------------------------------------------------------------------------
# DELIVERY_CONFIRMATION
# ---------------------------------------------------------------------------


def test_delivery_confirmation_valid():
    """Valid DELIVERY_CONFIRMATION passes schema validation."""
    payload = {
        "confirming_agent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "po_transaction_id": "HAR-20260317-001234",
        "po_number": "PO-2026-001",
        "delivery_date": "2026-03-20",
        "status": "delivered",
    }
    errors = validate_message_payload("DELIVERY_CONFIRMATION", payload)
    assert errors == []


def test_delivery_confirmation_missing_delivery_date():
    """DELIVERY_CONFIRMATION missing delivery_date returns error."""
    payload = {
        "confirming_agent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "po_transaction_id": "HAR-20260317-001234",
        "po_number": "PO-2026-001",
        "status": "delivered",
    }
    errors = validate_message_payload("DELIVERY_CONFIRMATION", payload)
    assert len(errors) > 0


# ---------------------------------------------------------------------------
# Unknown message type
# ---------------------------------------------------------------------------


def test_unknown_message_type_returns_error():
    """Unknown message_type returns a descriptive error."""
    errors = validate_message_payload("UNKNOWN_TYPE", {"foo": "bar"})
    assert len(errors) == 1
    assert "Unknown message_type" in errors[0]["message"]


def test_case_insensitive_message_type():
    """Message type lookup is case-insensitive."""
    payload = {
        "requester_agent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    }
    # Should work for both upper and lower case
    errors_upper = validate_message_payload("CAPABILITY_QUERY", payload)
    errors_lower = validate_message_payload("capability_query", payload)
    assert errors_upper == []
    assert errors_lower == []


# ---------------------------------------------------------------------------
# get_supported_message_types
# ---------------------------------------------------------------------------


def test_get_supported_message_types_returns_all_six():
    """get_supported_message_types returns all 6 message types."""
    types = get_supported_message_types()
    assert len(types) == 6
    expected = {
        "CAPABILITY_QUERY",
        "RFQ",
        "QUOTE_RESPONSE",
        "PO_PLACEMENT",
        "PO_ACKNOWLEDGEMENT",
        "DELIVERY_CONFIRMATION",
    }
    assert set(types) == expected
