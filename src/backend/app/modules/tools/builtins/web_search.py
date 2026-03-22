"""
Built-in web_search tool.

Wraps the platform's configured web search capability. Falls back to a
structured empty result if no search API is configured, so agents degrade
gracefully rather than raising exceptions.

Input:  { query: str, max_results: int = 5 }
Output: { results: list[{ title: str, url: str, snippet: str }] }
"""
import os
from typing import Any

import structlog

logger = structlog.get_logger()

_MAX_RESULTS_LIMIT = 20


async def web_search(
    query: str,
    max_results: int = 5,
    **_kwargs: Any,
) -> dict:
    """
    Perform a web search and return structured results.

    Uses the SEARCH_API_KEY / SEARCH_ENGINE_ID environment variables if
    configured (Google Custom Search JSON API compatible). If not configured,
    returns an empty result set with a notice so the calling LLM can handle
    the degraded state gracefully.

    Args:
        query: Search query string.
        max_results: Number of results to return (1–20).

    Returns:
        dict with 'results' list, each item having title, url, snippet.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not isinstance(max_results, int) or not (1 <= max_results <= _MAX_RESULTS_LIMIT):
        max_results = min(max(1, int(max_results)), _MAX_RESULTS_LIMIT)

    query = query.strip()[:500]  # Hard cap to prevent prompt injection via long queries

    search_api_key = os.environ.get("SEARCH_API_KEY")
    search_engine_id = os.environ.get("SEARCH_ENGINE_ID")

    if not search_api_key or not search_engine_id:
        logger.warning(
            "web_search_not_configured",
            has_api_key=bool(search_api_key),
            has_engine_id=bool(search_engine_id),
        )
        return {
            "results": [],
            "notice": (
                "Web search is not configured. "
                "SEARCH_API_KEY and SEARCH_ENGINE_ID must be set to use this tool."
            ),
        }

    try:
        import httpx

        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": search_api_key,
            "cx": search_engine_id,
            "q": query,
            "num": min(max_results, 10),  # Google CSE max is 10 per call
        }
        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=False,  # Never follow redirects (SSRF vector)
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        items = data.get("items", [])
        results = [
            {
                "title": item.get("title", "")[:256],
                "url": item.get("link", ""),
                "snippet": item.get("snippet", "")[:512],
            }
            for item in items[:max_results]
            if isinstance(item, dict)
        ]

        logger.info(
            "web_search_completed",
            result_count=len(results),
        )
        return {"results": results}

    except Exception as exc:
        logger.warning(
            "web_search_failed",
            error=str(exc),
        )
        return {
            "results": [],
            "error": f"Web search failed: {str(exc)[:200]}",
        }
