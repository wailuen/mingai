"""
Memory notes service - CRUD operations with 200-char enforcement.

CRITICAL: aihub2 did NOT enforce the 200-character limit server-side.
mingai MUST enforce it. This is a GDPR compliance requirement.

Canonical limits:
- Max note content: 200 chars (enforced here, not just in DB)
- Max notes per user: 15 (oldest pruned automatically)
- Notes injected to prompt: top 5, newest first
"""
import structlog

logger = structlog.get_logger()

MAX_NOTE_CONTENT_LENGTH = 200
MAX_NOTES_PER_USER = 15
MAX_NOTES_IN_PROMPT = 5
VALID_SOURCES = {"user_directed", "auto_extracted"}


class MemoryNoteValidationError(Exception):
    """Raised when memory note validation fails."""

    def __init__(self, message: str, status_code: int = 422):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def validate_memory_note_content(content: str) -> str:
    """
    Validate and sanitize memory note content.

    Rules:
    - Must not be None or empty (after stripping whitespace)
    - Must not exceed 200 characters (after stripping)
    - Leading/trailing whitespace is stripped

    Returns the cleaned content string.
    Raises MemoryNoteValidationError with descriptive message on failure.
    """
    if content is None or not isinstance(content, str):
        raise MemoryNoteValidationError(
            "Memory note content must not be empty. "
            "Provide a non-empty string up to 200 characters."
        )

    stripped = content.strip()

    if not stripped:
        raise MemoryNoteValidationError(
            "Memory note content must not be empty after trimming whitespace. "
            "Provide a non-empty string up to 200 characters."
        )

    if len(stripped) > MAX_NOTE_CONTENT_LENGTH:
        raise MemoryNoteValidationError(
            f"Memory note content must not exceed {MAX_NOTE_CONTENT_LENGTH} characters. "
            f"Got {len(stripped)} characters. "
            f"This limit is enforced server-side for data quality."
        )

    return stripped


def validate_note_source(source: str) -> str:
    """
    Validate the note source type.

    Valid sources:
    - user_directed: explicitly created by user ("remember that...")
    - auto_extracted: extracted by profile learning service

    Raises MemoryNoteValidationError if source is invalid.
    """
    if source not in VALID_SOURCES:
        raise MemoryNoteValidationError(
            f"Invalid note source '{source}'. "
            f"Must be one of: {', '.join(sorted(VALID_SOURCES))}"
        )
    return source
