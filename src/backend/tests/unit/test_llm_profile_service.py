"""
Unit tests for LLMProfileService (TODO-29 / TODO-34).

Tests validate:
- Traffic split weight validation rules
- Plan tier validation
- Slot field extraction
- Error class hierarchy
"""
import pytest

from app.modules.llm_profiles.service import (
    LLMProfileConflictError,
    LLMProfileError,
    LLMProfileNotFoundError,
    LLMProfilePermissionError,
    LLMProfileValidationError,
    _build_slot_fields,
    _validate_traffic_split,
)


class TestTrafficSplitValidation:
    """_validate_traffic_split enforces weight rules."""

    def test_empty_split_is_valid(self):
        _validate_traffic_split([], "chat")  # must not raise

    def test_single_entry_weight_100_valid(self):
        split = [{"library_id": "abc", "weight": 100}]
        _validate_traffic_split(split, "chat")  # must not raise

    def test_single_entry_non_100_invalid(self):
        split = [{"library_id": "abc", "weight": 70}]
        with pytest.raises(LLMProfileValidationError, match="weight=100"):
            _validate_traffic_split(split, "chat")

    def test_two_entries_summing_to_100_valid(self):
        split = [
            {"library_id": "aaa", "weight": 70},
            {"library_id": "bbb", "weight": 30},
        ]
        _validate_traffic_split(split, "intent")  # must not raise

    def test_two_entries_not_summing_to_100_invalid(self):
        split = [
            {"library_id": "aaa", "weight": 60},
            {"library_id": "bbb", "weight": 30},
        ]
        with pytest.raises(LLMProfileValidationError, match="sum to 100"):
            _validate_traffic_split(split, "intent")

    def test_missing_weight_field_invalid(self):
        split = [{"library_id": "abc"}]
        with pytest.raises(LLMProfileValidationError, match="weight"):
            _validate_traffic_split(split, "chat")

    def test_missing_library_id_field_invalid(self):
        split = [{"weight": 100}]
        with pytest.raises(LLMProfileValidationError, match="library_id"):
            _validate_traffic_split(split, "chat")

    def test_weight_zero_invalid(self):
        """Single-entry split with weight=0 fails (must be 100 for single entries)."""
        split = [{"library_id": "abc", "weight": 0}]
        with pytest.raises(LLMProfileValidationError, match="weight=100"):
            _validate_traffic_split(split, "chat")

    def test_weight_100_in_multi_entry_invalid(self):
        """100 in a multi-entry split would sum > 100."""
        split = [
            {"library_id": "aaa", "weight": 100},
            {"library_id": "bbb", "weight": 1},
        ]
        with pytest.raises(LLMProfileValidationError):
            _validate_traffic_split(split, "chat")

    def test_non_integer_weight_invalid(self):
        split = [{"library_id": "abc", "weight": "70"}]
        with pytest.raises(LLMProfileValidationError):
            _validate_traffic_split(split, "chat")

    def test_three_entries_valid(self):
        split = [
            {"library_id": "a", "weight": 50},
            {"library_id": "b", "weight": 30},
            {"library_id": "c", "weight": 20},
        ]
        _validate_traffic_split(split, "vision")  # must not raise

    def test_negative_weight_invalid(self):
        """Negative weights must be rejected — they can bypass the sum-to-100 check
        when combined with a large positive weight (e.g. -50 + 150 = 100)."""
        split = [
            {"library_id": "a", "weight": -50},
            {"library_id": "b", "weight": 150},
        ]
        with pytest.raises(LLMProfileValidationError):
            _validate_traffic_split(split, "chat")

    def test_negative_single_weight_invalid(self):
        """Single entry with negative weight must be rejected."""
        split = [{"library_id": "a", "weight": -100}]
        with pytest.raises(LLMProfileValidationError):
            _validate_traffic_split(split, "intent")


class TestBuildSlotFields:
    """_build_slot_fields extracts and validates slot fields from input."""

    def test_empty_input_returns_empty_dict(self):
        result = _build_slot_fields({})
        assert result == {}

    def test_chat_library_id_extracted(self):
        result = _build_slot_fields({"chat_library_id": "abc123"})
        assert result["chat_library_id"] == "abc123"

    def test_all_four_slots_extracted(self):
        data = {
            "chat_library_id": "a",
            "intent_library_id": "b",
            "vision_library_id": "c",
            "agent_library_id": "d",
        }
        result = _build_slot_fields(data)
        assert result["chat_library_id"] == "a"
        assert result["intent_library_id"] == "b"
        assert result["vision_library_id"] == "c"
        assert result["agent_library_id"] == "d"

    def test_non_dict_params_raises(self):
        with pytest.raises(LLMProfileValidationError, match="JSON object"):
            _build_slot_fields({"chat_params": "not a dict"})

    def test_non_list_traffic_split_raises(self):
        with pytest.raises(LLMProfileValidationError, match="JSON array"):
            _build_slot_fields({"chat_traffic_split": {"key": "val"}})

    def test_invalid_traffic_split_raises(self):
        split = [{"library_id": "x", "weight": 50}]  # single entry, not 100
        with pytest.raises(LLMProfileValidationError):
            _build_slot_fields({"chat_traffic_split": split})

    def test_unknown_keys_ignored(self):
        """Extra keys not matching slot pattern are silently ignored."""
        result = _build_slot_fields({"name": "test", "chat_library_id": "abc"})
        assert "name" not in result
        assert result["chat_library_id"] == "abc"

    def test_params_dict_extracted(self):
        result = _build_slot_fields({"intent_params": {"temperature": 0.7}})
        assert result["intent_params"] == {"temperature": 0.7}


class TestErrorHierarchy:
    """Service error classes must form a coherent hierarchy."""

    def test_all_errors_inherit_from_base(self):
        assert issubclass(LLMProfileNotFoundError, LLMProfileError)
        assert issubclass(LLMProfilePermissionError, LLMProfileError)
        assert issubclass(LLMProfileValidationError, LLMProfileError)
        assert issubclass(LLMProfileConflictError, LLMProfileError)

    def test_base_inherits_from_exception(self):
        assert issubclass(LLMProfileError, Exception)

    def test_errors_instantiate_with_message(self):
        err = LLMProfileNotFoundError("profile abc not found")
        assert "abc" in str(err)

        err2 = LLMProfileValidationError("weight must be 100")
        assert "100" in str(err2)
