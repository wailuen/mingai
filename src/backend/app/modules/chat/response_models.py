"""
CACHE-009: Two-tier response model split for cacheable vs. personalized content.

CacheableResponse holds the content that is safe to cache and share across
users asking the same question (sources, raw answer, confidence, model, latency).

PersonalizedResponse wraps CacheableResponse and adds user-specific fields that
must NOT be cached (greeting, memory context flag, conversation_id).

The split ensures:
- Cache stores only CacheableResponse (no user PII in cached payloads)
- Chat route assembles PersonalizedResponse after cache hit/miss
"""
from pydantic import BaseModel


class Source(BaseModel):
    """A single source document used to generate the answer."""

    document_id: str
    chunk_text: str
    score: float
    document_name: str | None = None
    url: str | None = None


class CacheableResponse(BaseModel):
    """
    The cacheable portion of a chat response.

    This object is stored in the semantic cache and may be served to any
    tenant user who asks a semantically equivalent query.

    Fields are deterministic given the query + knowledge base — they do not
    contain any user-specific information.
    """

    sources: list[Source]
    raw_answer: str
    confidence: float
    model: str
    latency_ms: int


class PersonalizedResponse(BaseModel):
    """
    Full response including user-specific additions.

    The cacheable core is embedded. User-specific fields are added by the
    chat route after cache lookup — they are never stored in the cache.
    """

    # Core cacheable content
    cacheable: CacheableResponse

    # User-specific additions (not cached)
    user_greeting: str | None = None
    memory_context_applied: bool = False
    conversation_id: str | None = None
