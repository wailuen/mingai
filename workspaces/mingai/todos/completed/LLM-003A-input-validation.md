# TODO-LLM-003A: Input validation for endpoint_url and api_version

## Status

Active

## Summary

Add Pydantic validators to CreateLLMLibraryRequest and UpdateLLMLibraryRequest so invalid endpoint URLs and api_version strings are rejected at creation time with clear error messages, rather than only failing at test time with a confusing network error.

## Context

Without validation, a platform admin could save `endpoint_url = "not a url"` or `api_version = "latest"` and only discover the error when the test fails with a cryptic network/HTTP exception. Fail fast with clear messages at the API layer.

## Acceptance Criteria

- [ ] `endpoint_url` must start with `https://` — reject `http://`, bare hostnames, empty strings with 422 + message "endpoint_url must be a valid HTTPS URL (e.g. https://resource.cognitiveservices.azure.com/)"
- [ ] `endpoint_url` must be a valid URL format (hostname, not just a string)
- [ ] `api_version` must match format `YYYY-MM-DD` or `YYYY-MM-DD-preview` (e.g. `2024-12-01-preview`) — reject freeform strings
- [ ] Validation errors return 422 with a human-readable field-level message
- [ ] `endpoint_url` and `api_version` are only validated when provided (Optional fields — null/absent is allowed at create time, enforced at publish time)

## Implementation Notes

Use Pydantic @field_validator on CreateLLMLibraryRequest and UpdateLLMLibraryRequest:

```python
import re
from pydantic import field_validator

_API_VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(-preview)?$")

@field_validator("endpoint_url")
@classmethod
def validate_endpoint_url(cls, v):
    if v is not None and not v.startswith("https://"):
        raise ValueError("endpoint_url must start with https://")
    return v

@field_validator("api_version")
@classmethod
def validate_api_version(cls, v):
    if v is not None and not _API_VERSION_RE.match(v):
        raise ValueError("api_version must match YYYY-MM-DD or YYYY-MM-DD-preview format")
    return v
```

## Dependencies

- Depends on: LLM-003
- Blocks: LLM-007 (publish gate assumes valid formats)

## Test Requirements

- Unit test: invalid endpoint_url (http://, no scheme, empty) rejected with 422
- Unit test: invalid api_version (freeform, wrong format) rejected with 422
- Unit test: valid values pass through unchanged
