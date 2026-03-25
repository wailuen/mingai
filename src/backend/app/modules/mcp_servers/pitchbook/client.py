"""Async HTTP client for the Pitchbook API.

Provides a thin, stateless async client. Rate limiting and caching are
intentionally omitted here — those concerns belong at the edge or in a
dedicated service layer.
"""

from __future__ import annotations

import structlog
from typing import Any

import httpx

logger = structlog.get_logger(__name__)

_DEFAULT_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PitchbookAPIError(Exception):
    """Base exception for all Pitchbook API errors."""

    def __init__(self, message: str, status_code: int = 0) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status_code={self.status_code}, message={self.message!r})"


class PitchbookRateLimitError(PitchbookAPIError):
    """Raised when the API returns HTTP 429 Too Many Requests."""

    def __init__(self, message: str, status_code: int = 429, retry_after: int | None = None) -> None:
        super().__init__(message, status_code)
        self.retry_after = retry_after


class PitchbookAuthError(PitchbookAPIError):
    """Raised when the API returns HTTP 401 or 403."""

    pass


class PitchbookNotFoundError(PitchbookAPIError):
    """Raised when the API returns HTTP 404."""

    pass


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class PitchbookClient:
    """Async HTTP client for Pitchbook API V2.

    The API key must be passed explicitly at construction time. The client
    does not read from environment variables — callers are responsible for
    sourcing the key from their preferred secret store.

    Usage::

        async with PitchbookClient(api_key="...") as client:
            data = await client.get("/companies/{pbId}/bio", {"pbId": "12345-67"})
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.pitchbook.com",
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a GET request to the Pitchbook API.

        Args:
            endpoint: API path, e.g. "/companies/12345-67/bio".
            params: Optional query string parameters.

        Returns:
            Parsed JSON response.

        Raises:
            PitchbookRateLimitError: On HTTP 429.
            PitchbookAuthError: On HTTP 401 or 403.
            PitchbookNotFoundError: On HTTP 404.
            PitchbookAPIError: On any other non-2xx status.
        """
        client = await self._get_client()
        url = f"{self._base_url}{endpoint}"
        logger.debug("pitchbook_api_get", url=url)
        try:
            response = await client.get(url, params=params, headers=self._headers)
        except httpx.TimeoutException:
            raise PitchbookAPIError("Request timed out", status_code=408)
        except httpx.RequestError as exc:
            raise PitchbookAPIError(f"Request failed: {exc}")
        return self._handle_response(response, endpoint)

    async def post(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        """Make a POST request to the Pitchbook API.

        Args:
            endpoint: API path.
            data: JSON body payload.

        Returns:
            Parsed JSON response.

        Raises:
            PitchbookRateLimitError: On HTTP 429.
            PitchbookAuthError: On HTTP 401 or 403.
            PitchbookNotFoundError: On HTTP 404.
            PitchbookAPIError: On any other non-2xx status.
        """
        client = await self._get_client()
        url = f"{self._base_url}{endpoint}"
        logger.debug("pitchbook_api_post", url=url)
        try:
            response = await client.post(url, json=data, headers=self._headers)
        except httpx.TimeoutException:
            raise PitchbookAPIError("Request timed out", status_code=408)
        except httpx.RequestError as exc:
            raise PitchbookAPIError(f"Request failed: {exc}")
        return self._handle_response(response, endpoint)

    # ------------------------------------------------------------------
    # Async context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "PitchbookClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        return self._client

    def _handle_response(self, response: httpx.Response, endpoint: str) -> dict[str, Any]:
        """Translate HTTP response status to the appropriate exception or data."""
        if response.status_code == 429:
            retry_after_raw = response.headers.get("Retry-After", "60")
            try:
                retry_after = int(retry_after_raw)
            except (ValueError, TypeError):
                retry_after = 60
            raise PitchbookRateLimitError(
                f"Rate limited; retry after {retry_after}s",
                retry_after=retry_after,
            )

        if response.status_code in (401, 403):
            raise PitchbookAuthError(
                f"Authentication failed ({response.status_code})",
                status_code=response.status_code,
            )

        if response.status_code == 404:
            raise PitchbookNotFoundError(
                f"Resource not found: {endpoint}",
                status_code=404,
            )

        if response.status_code == 204 or not response.content:
            return {}

        if response.status_code >= 400:
            error_msg = self._extract_error_message(response)
            logger.warning("pitchbook_api_error", status=response.status_code, message=error_msg)
            raise PitchbookAPIError(error_msg, status_code=response.status_code)

        try:
            return response.json()
        except Exception as exc:
            raise PitchbookAPIError(f"Failed to parse response: {exc}", status_code=response.status_code)

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            data = response.json()
            if "message" in data:
                return str(data["message"])
            if "error" in data:
                err = data["error"]
                return err.get("message", str(err)) if isinstance(err, dict) else str(err)
        except Exception:
            pass
        return response.text or f"HTTP {response.status_code}"
