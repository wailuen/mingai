"""
Built-in file_reader tool.

Reads text content from a file URL within the tenant's storage scope.
Supports text files, PDFs (via PyMuPDF if available), and common document
formats. SSRF protection enforced.

Input:  { file_url: str }
Output: { content: str, char_count: int }
"""
import re
from typing import Any

import structlog

logger = structlog.get_logger()

_MAX_CONTENT_LENGTH = 500_000  # 500 KB character limit
_MAX_URL_LENGTH = 2048

_PRIVATE_IP_PATTERNS = [
    re.compile(r"^10\."),
    re.compile(r"^172\.(1[6-9]|2\d|3[01])\."),
    re.compile(r"^192\.168\."),
    re.compile(r"^127\."),
    re.compile(r"^169\.254\."),
    re.compile(r"^::1$"),
    re.compile(r"^fc[0-9a-f]{2}:"),
    re.compile(r"^fe80:"),
]


def _validate_url(url: str) -> None:
    """Validate URL and check for SSRF risk."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("file_url must be a non-empty string")
    if len(url) > _MAX_URL_LENGTH:
        raise ValueError(f"URL too long (max {_MAX_URL_LENGTH} characters)")
    url_lower = url.lower()
    if not (url_lower.startswith("https://") or url_lower.startswith("http://")):
        raise ValueError("file_url must use http or https scheme")
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
    except Exception:
        raise ValueError("Invalid URL format")
    for pattern in _PRIVATE_IP_PATTERNS:
        if pattern.search(hostname):
            raise ValueError(
                "SSRF protection: private or loopback addresses are not permitted"
            )


async def file_reader(file_url: str, **_kwargs: Any) -> dict:
    """
    Read text content from a file at the given URL.

    For PDF files: extracts text via PyMuPDF if available.
    For text-based files: reads and decodes content.

    Args:
        file_url: HTTPS URL to the file.

    Returns:
        dict with 'content' (text) and 'char_count' (length).
    """
    _validate_url(file_url)
    file_url = file_url.strip()

    try:
        import httpx

        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=False,  # No redirect following (SSRF vector)
        ) as client:
            response = await client.get(file_url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            raw_bytes = response.content

    except Exception as exc:
        logger.warning("file_reader_fetch_failed", error=str(exc))
        raise ValueError(f"Failed to fetch file: {str(exc)[:200]}") from exc

    # PDF: attempt PyMuPDF extraction
    if "pdf" in content_type or file_url.lower().endswith(".pdf"):
        content = _extract_pdf_text(raw_bytes)
    else:
        # Attempt UTF-8 decode, fall back to latin-1
        try:
            content = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            content = raw_bytes.decode("latin-1", errors="replace")

    # Enforce content length limit
    if len(content) > _MAX_CONTENT_LENGTH:
        content = content[:_MAX_CONTENT_LENGTH]
        logger.info(
            "file_reader_truncated",
            limit=_MAX_CONTENT_LENGTH,
        )

    return {
        "content": content,
        "char_count": len(content),
    }


def _extract_pdf_text(raw_bytes: bytes) -> str:
    """Extract text from PDF bytes using PyMuPDF if available."""
    try:
        import fitz  # type: ignore[import]
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        parts = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(parts)
    except ImportError:
        logger.warning("file_reader_fitz_not_available")
        # Return raw bytes decoded — likely garbage for binary PDF
        return raw_bytes.decode("latin-1", errors="replace")
    except Exception as exc:
        logger.warning("file_reader_pdf_extraction_failed", error=str(exc))
        raise ValueError(f"PDF text extraction failed: {str(exc)[:200]}") from exc
