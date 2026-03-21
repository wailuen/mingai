# TODO-LLM-015: Update docs/00-authority/CLAUDE.md with Credential Handling Patterns

## Status

Active

## Summary

Add a "LLM Library Credential Patterns" section to `docs/00-authority/CLAUDE.md` documenting the correct patterns for: using `app.core.crypto`, the security invariants around `api_key_encrypted`, and the provider-specific field requirements. This prevents future implementers from re-introducing the broken env-var pattern.

## Context

`CLAUDE.md` in the authority docs directory is the canonical pattern reference for Claude Code agents working on this project. The LLM Library redesign introduces two patterns that must be captured: (1) how to use `app.core.crypto` for API key storage in any future module that needs credential storage, and (2) the "never return encrypted bytes" invariant that must be enforced at the response model layer. Without documenting these, future features may repeat the mistake.

## Acceptance Criteria

- [ ] `docs/00-authority/CLAUDE.md` has a new section: "## LLM Library — Credential Storage Pattern"
- [ ] Section explains the concept: library entry = self-contained connection, not a catalog entry
- [ ] Section shows the correct import and usage of `app.core.crypto.encrypt_api_key` / `decrypt_api_key`
- [ ] Section states the security invariant explicitly: `api_key_encrypted` (BYTEA) is NEVER included in any Pydantic response model or JSON response
- [ ] Section states the key-clear invariant: `decrypted_key = ""` in `finally` block after use
- [ ] Section shows the `api_key_last4` derivation pattern: `key[-4:] if len(key) >= 4 else key`
- [ ] Section documents the `last_test_passed_at` reset rule: updating `api_key` resets this timestamp to NULL
- [ ] Section references the publish gate logic for where per-provider validation lives
- [ ] No new files created — update the existing `CLAUDE.md`

## Implementation Notes

File to locate: run `find . -name "CLAUDE.md" -path "*/00-authority/*"` to confirm the exact path.

The section should be approximately 40-60 lines, concise and pattern-focused (not a tutorial). Include a minimal code example for the encrypt/decrypt round-trip pattern, not a full route implementation.

Example pattern block to include:

```python
# CORRECT: Store API key
from app.core.crypto import encrypt_api_key, decrypt_api_key

encrypted = encrypt_api_key(plaintext_key)
last4 = plaintext_key[-4:] if len(plaintext_key) >= 4 else plaintext_key
# Store encrypted (BYTEA) and last4 in DB. Discard plaintext.

# CORRECT: Use API key for a network call
decrypted_key = ""
try:
    decrypted_key = decrypt_api_key(encrypted_bytes)
    # ... use decrypted_key to construct client ...
finally:
    decrypted_key = ""  # Always clear

# WRONG: Never return encrypted bytes in response model
class BadResponse(BaseModel):
    api_key_encrypted: bytes  # BLOCKED — encrypted bytes must never be in responses

# CORRECT: Return only safe metadata
class GoodResponse(BaseModel):
    key_present: bool    # Derived: api_key_encrypted IS NOT NULL
    api_key_last4: str   # Stored plaintext last-4 chars
```

## Dependencies

- Depends on: LLM-002 (crypto module exists before documenting it)
- Blocks: nothing (documentation)

## Test Requirements

- [ ] Manual review: patterns in CLAUDE.md match the actual implementation in `app/core/crypto.py` and `llm_library/routes.py`
- [ ] No stubs or placeholder text in the new section
