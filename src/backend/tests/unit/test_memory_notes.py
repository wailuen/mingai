"""
TEST-050: Memory notes 200-char enforcement - unit tests

Coverage target: 100% (GDPR-critical)
Target count: 8 tests

Validates that memory notes enforce the 200 character limit
server-side (aihub2 did NOT enforce this - mingai MUST).
"""
import pytest


class TestMemoryNoteValidation:
    """TEST-050: 200-char limit enforcement."""

    def test_note_at_exactly_200_chars_accepted(self):
        """200 characters is the maximum allowed."""
        from app.modules.memory.notes import validate_memory_note_content

        content = "x" * 200
        result = validate_memory_note_content(content)
        assert result == content

    def test_note_at_201_chars_rejected(self):
        """201 characters must be rejected."""
        from app.modules.memory.notes import validate_memory_note_content, MemoryNoteValidationError

        content = "x" * 201
        with pytest.raises(MemoryNoteValidationError, match="200"):
            validate_memory_note_content(content)

    def test_note_at_1000_chars_rejected(self):
        """Very long notes must be rejected."""
        from app.modules.memory.notes import validate_memory_note_content, MemoryNoteValidationError

        content = "x" * 1000
        with pytest.raises(MemoryNoteValidationError, match="200"):
            validate_memory_note_content(content)

    def test_empty_note_rejected(self):
        """Empty notes must be rejected."""
        from app.modules.memory.notes import validate_memory_note_content, MemoryNoteValidationError

        with pytest.raises(MemoryNoteValidationError, match="empty"):
            validate_memory_note_content("")

    def test_whitespace_only_note_rejected(self):
        """Whitespace-only notes must be rejected."""
        from app.modules.memory.notes import validate_memory_note_content, MemoryNoteValidationError

        with pytest.raises(MemoryNoteValidationError, match="empty"):
            validate_memory_note_content("   \n\t  ")

    def test_none_note_rejected(self):
        """None content must be rejected."""
        from app.modules.memory.notes import validate_memory_note_content, MemoryNoteValidationError

        with pytest.raises(MemoryNoteValidationError, match="empty"):
            validate_memory_note_content(None)

    def test_note_is_stripped_before_validation(self):
        """Leading/trailing whitespace is stripped before length check."""
        from app.modules.memory.notes import validate_memory_note_content

        content = "  hello world  "
        result = validate_memory_note_content(content)
        assert result == "hello world"

    def test_valid_source_types(self):
        """Valid source types: user_directed, auto_extracted."""
        from app.modules.memory.notes import validate_note_source, MemoryNoteValidationError

        assert validate_note_source("user_directed") == "user_directed"
        assert validate_note_source("auto_extracted") == "auto_extracted"

        with pytest.raises(MemoryNoteValidationError, match="source"):
            validate_note_source("invalid")

    def test_max_notes_per_user(self):
        """Maximum of 15 notes per user (oldest pruned)."""
        from app.modules.memory.notes import MAX_NOTES_PER_USER

        assert MAX_NOTES_PER_USER == 15

    def test_notes_injected_to_prompt_limit(self):
        """Only top 5 notes (newest first) injected to prompt."""
        from app.modules.memory.notes import MAX_NOTES_IN_PROMPT

        assert MAX_NOTES_IN_PROMPT == 5
