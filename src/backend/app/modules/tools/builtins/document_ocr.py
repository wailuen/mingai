"""
Built-in document_ocr tool.

Extracts text from PDF or image files by URL. Wraps the OCR service used
in the document ingestion pipeline, falling back to a simple PDF text
extraction when no dedicated OCR service is configured.

Input:  { document_url: str, page_range: str | None }
Output: { text: str, page_count: int }
"""
import os
import re
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

# SSRF protection: block private IP ranges
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

_ALLOWED_SCHEMES = {"https", "http"}
_MAX_URL_LENGTH = 2048


def _validate_url(url: str) -> None:
    """Basic URL validation with SSRF protection."""
    if len(url) > _MAX_URL_LENGTH:
        raise ValueError(f"URL too long (max {_MAX_URL_LENGTH} characters)")
    url_lower = url.lower()
    if not any(url_lower.startswith(f"{s}://") for s in _ALLOWED_SCHEMES):
        raise ValueError("URL must use http or https scheme")
    # Extract hostname for SSRF check
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


async def document_ocr(
    document_url: str,
    page_range: Optional[str] = None,
    **_kwargs: Any,
) -> dict:
    """
    Extract text from a PDF or image document at the given URL.

    Uses DOCUMENT_OCR_ENDPOINT environment variable if configured for a
    dedicated OCR service. Falls back to PyMuPDF (fitz) for PDFs if available.

    Args:
        document_url: HTTPS URL to the document.
        page_range: Optional page range like "1-3" or "2" (1-indexed).

    Returns:
        dict with 'text' (extracted text) and 'page_count' (total pages).
    """
    if not isinstance(document_url, str) or not document_url.strip():
        raise ValueError("document_url must be a non-empty string")
    document_url = document_url.strip()
    _validate_url(document_url)

    ocr_endpoint = os.environ.get("DOCUMENT_OCR_ENDPOINT")

    if ocr_endpoint:
        return await _call_ocr_service(ocr_endpoint, document_url, page_range)
    return await _extract_with_fallback(document_url, page_range)


async def _call_ocr_service(
    endpoint: str,
    document_url: str,
    page_range: Optional[str],
) -> dict:
    """Call a dedicated OCR service endpoint."""
    try:
        import httpx

        payload: dict = {"document_url": document_url}
        if page_range:
            payload["page_range"] = page_range

        async with httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=False,
        ) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()

        return {
            "text": str(data.get("text", "")),
            "page_count": int(data.get("page_count", 0)),
        }
    except Exception as exc:
        logger.warning("document_ocr_service_failed", error=str(exc))
        raise ValueError(f"OCR service call failed: {str(exc)[:200]}") from exc


async def _extract_with_fallback(
    document_url: str,
    page_range: Optional[str],
) -> dict:
    """
    Fallback extraction using PyMuPDF (fitz) if available.
    Only supports PDFs in fallback mode.
    """
    try:
        import fitz  # type: ignore[import]
        import httpx

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.get(document_url)
            response.raise_for_status()
            content = response.content

        doc = fitz.open(stream=content, filetype="pdf")
        page_count = len(doc)

        # Parse page_range if provided
        pages_to_extract: list[int] = list(range(page_count))
        if page_range:
            pages_to_extract = _parse_page_range(page_range, page_count)

        text_parts = []
        for page_idx in pages_to_extract:
            page = doc[page_idx]
            text_parts.append(page.get_text())

        doc.close()
        return {
            "text": "\n".join(text_parts),
            "page_count": page_count,
        }
    except ImportError:
        logger.warning("document_ocr_fitz_not_available")
        return {
            "text": "",
            "page_count": 0,
            "notice": (
                "Document OCR is not fully configured. "
                "Set DOCUMENT_OCR_ENDPOINT or install PyMuPDF."
            ),
        }
    except Exception as exc:
        logger.warning("document_ocr_fallback_failed", error=str(exc))
        raise ValueError(f"Document extraction failed: {str(exc)[:200]}") from exc


def _parse_page_range(page_range: str, total_pages: int) -> list[int]:
    """Parse '1-3' or '2' into 0-indexed page numbers."""
    page_range = page_range.strip()
    try:
        if "-" in page_range:
            parts = page_range.split("-", 1)
            start = max(1, int(parts[0].strip())) - 1
            end = min(total_pages, int(parts[1].strip()))
            return list(range(start, end))
        single = int(page_range) - 1
        if 0 <= single < total_pages:
            return [single]
    except (ValueError, IndexError):
        pass
    return list(range(total_pages))
