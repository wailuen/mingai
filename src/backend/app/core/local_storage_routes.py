"""
Local dev-only: internal screenshot upload/serve endpoints.

These routes back the local presigned URL flow when CLOUD_PROVIDER=local.
In production (aws/azure/gcp), clients upload directly to the cloud provider
and these routes are never called.

Routes:
  PUT /api/v1/internal/screenshots/{token}  — upload with HMAC-signed token
  GET /api/v1/internal/screenshots/{path}   — serve stored file

Security:
  - Upload: HMAC-signed token verified before write; expiry enforced
  - Upload: Content-type validated against token payload
  - Serve: Only files under LOCAL_SCREENSHOT_DIR are accessible (no traversal)
  - Both routes are unauthenticated by design (token IS the auth for upload)
    because the client uses the URL directly without an Authorization header,
    matching how real presigned URLs work.

Storage: LOCAL_SCREENSHOT_DIR env var (default /tmp/mingai_screenshots).
"""
import os
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, Response

from app.core.storage import (
    ALLOWED_CONTENT_TYPES,
    verify_local_serve_token,
    verify_local_upload_token,
)

logger = structlog.get_logger()

router = APIRouter(tags=["internal"])

_LOCAL_SCREENSHOT_DIR = Path(
    os.environ.get("LOCAL_SCREENSHOT_DIR", "/tmp/mingai_screenshots")
)


def _resolve_safe_path(relative_key: str) -> Path:
    """
    Resolve a storage key to an absolute path, rejecting path traversal.

    Uses Path.is_relative_to() (Python 3.9+) to prevent prefix-collision attacks
    where a sibling directory (e.g. /tmp/mingai_screenshots_evil) would pass a
    naive startswith() check against /tmp/mingai_screenshots.

    Raises:
        ValueError: If the resolved path escapes LOCAL_SCREENSHOT_DIR.
    """
    base = _LOCAL_SCREENSHOT_DIR.resolve()
    candidate = (base / relative_key).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError(f"Path traversal attempt detected: {relative_key!r}")
    return candidate


@router.put("/internal/screenshots/{token:path}", status_code=status.HTTP_200_OK)
async def local_screenshot_upload(token: str, request: Request):
    """
    Accept a local-presigned screenshot upload.

    Clients send: PUT {upload_url} with image bytes as body.
    The upload_url carries an HMAC-signed token encoding {key, exp, ct}.

    - Verifies HMAC signature and expiry
    - Validates Content-Type against the token's ct field
    - Writes file bytes to LOCAL_SCREENSHOT_DIR/{key}
    """
    try:
        payload = verify_local_upload_token(token)
    except ValueError as exc:
        logger.warning("local_upload_token_invalid", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired upload token",
        )

    # Enforce content-type is both in the allowlist AND matches the token's ct claim.
    # The token's ct was validated at presign time; accepting a different content-type
    # at upload time would violate the cryptographic contract and may cause downstream
    # processing errors (e.g., the blur service expects PNG from a PNG presign).
    request_ct = request.headers.get("content-type", "").split(";")[0].strip()
    # Require Content-Type to be present — omitting it would bypass all content validation.
    if not request_ct:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Content-Type header is required for screenshot uploads",
        )
    if request_ct not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Content-Type must be image/png or image/jpeg, got: {request_ct!r}",
        )
    if request_ct != payload["ct"]:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Content-Type {request_ct!r} does not match "
                f"presigned content-type {payload['ct']!r}"
            ),
        )

    object_key = payload["key"]

    try:
        dest = _resolve_safe_path(object_key)
    except ValueError as exc:
        logger.error("local_upload_path_traversal", key=object_key, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid storage key",
        )

    dest.parent.mkdir(parents=True, exist_ok=True)

    body = await request.body()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must not be empty",
        )

    # Guard: reject oversized files (10 MB matches blur_service limit)
    max_bytes = 10 * 1024 * 1024
    if len(body) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {max_bytes // 1024 // 1024} MB",
        )

    dest.write_bytes(body)
    logger.info(
        "local_screenshot_stored",
        key=object_key,
        size_bytes=len(body),
        dest=str(dest),
    )
    return Response(status_code=status.HTTP_200_OK)


@router.get("/internal/screenshots/{token:path}", status_code=status.HTTP_200_OK)
async def local_screenshot_serve(token: str):
    """
    Serve a previously uploaded local screenshot.

    Clients use the blob_url (== upload_url) returned by presign to fetch the file.
    The token carries the same HMAC signature as the upload URL, cryptographically
    binding the storage path. Expiry is NOT enforced — blob URLs are permanent.

    Security:
    - HMAC signature is verified before resolving any file path
    - Path traversal is rejected by _resolve_safe_path (Path.is_relative_to)
    - Only files that actually exist on disk can be served
    """
    try:
        payload = verify_local_serve_token(token)
    except ValueError as exc:
        logger.warning("local_serve_token_invalid", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid blob URL",
        )

    object_key = payload["key"]

    try:
        dest = _resolve_safe_path(object_key)
    except ValueError as exc:
        logger.error("local_serve_path_traversal", key=object_key, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid storage key",
        )

    if not dest.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Screenshot not found",
        )

    # Use content-type from the token (declared at presign time) rather than extension guessing
    media_type = payload.get("ct", "image/png")
    if media_type not in ALLOWED_CONTENT_TYPES:
        media_type = "image/png"

    logger.info("local_screenshot_served", key=object_key, dest=str(dest))
    return FileResponse(str(dest), media_type=media_type)
