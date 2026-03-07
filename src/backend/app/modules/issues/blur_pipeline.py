"""
Async blur pipeline for uploaded screenshots (INFRA-019).

Downloads a screenshot from blob storage, applies blur via ScreenshotBlurService,
and overwrites the original with the blurred version. Designed to be called
after issue creation -- blur failure is non-fatal (logged, returns False).

For local provider: reads/writes directly from LOCAL_SCREENSHOT_DIR.
"""
import os
from pathlib import Path
from typing import Optional

import structlog

from app.modules.issues.blur_service import BlurRegion, ScreenshotBlurService

logger = structlog.get_logger()


async def apply_blur_to_uploaded_screenshot(
    blob_url: str,
    content_type: str,
    blur_regions: Optional[list[BlurRegion]] = None,
) -> bool:
    """
    Download, blur, and overwrite a screenshot at the given blob URL.

    For local storage provider: reads the file from LOCAL_SCREENSHOT_DIR
    based on the object key extracted from the signed URL path.

    Args:
        blob_url: The permanent blob URL of the uploaded screenshot.
        content_type: MIME type (image/png or image/jpeg).
        blur_regions: Optional list of BlurRegion with relative coords (0.0-1.0).

    Returns:
        True on success, False on failure (non-fatal -- logged).
    """
    try:
        image_bytes, file_path = _read_screenshot(blob_url)
        size_before = len(image_bytes)

        service = ScreenshotBlurService()
        blurred_bytes = service.blur(image_bytes, content_type, regions=blur_regions)
        size_after = len(blurred_bytes)

        _write_screenshot(file_path, blurred_bytes)

        logger.info(
            "screenshot_blurred",
            key=file_path,
            size_bytes_before=size_before,
            size_bytes_after=size_after,
        )
        return True

    except Exception:
        logger.error(
            "screenshot_blur_failed",
            blob_url=blob_url,
            content_type=content_type,
            exc_info=True,
        )
        return False


def _read_screenshot(blob_url: str) -> tuple[bytes, str]:
    """
    Read screenshot bytes from storage.

    Currently supports local provider only (reads from LOCAL_SCREENSHOT_DIR).
    Cloud providers (AWS S3, Azure Blob, GCP GCS) would use their respective
    SDKs to download the blob.

    Args:
        blob_url: The permanent blob URL.

    Returns:
        Tuple of (image_bytes, resolved_file_path).

    Raises:
        FileNotFoundError: If the local file does not exist.
        RuntimeError: If LOCAL_SCREENSHOT_DIR is not configured.
    """
    screenshot_dir = os.environ.get("LOCAL_SCREENSHOT_DIR")
    if not screenshot_dir:
        raise RuntimeError(
            "LOCAL_SCREENSHOT_DIR is not set. Cannot read screenshot for blur processing."
        )

    # Extract the object key from the blob URL.
    # Local blob URLs look like: http://localhost:8022/api/v1/internal/screenshots/{token}.{sig}
    # The actual file is stored at LOCAL_SCREENSHOT_DIR/{object_key}
    # where object_key = screenshots/{tenant_id}/{uuid}/{filename}
    #
    # For local provider, we need to decode the token to get the key.
    # Import here to avoid circular imports at module level.
    from app.core.storage import verify_local_serve_token

    # Extract the token.signature part from the URL path
    url_path = blob_url.rstrip("/")
    token_with_sig = url_path.rsplit("/", 1)[-1]

    payload = verify_local_serve_token(token_with_sig)
    object_key = payload["key"]

    file_path = os.path.join(screenshot_dir, object_key)
    resolved = Path(file_path).resolve()
    base_dir = Path(screenshot_dir).resolve()

    if not str(resolved).startswith(str(base_dir)):
        raise ValueError(
            f"Path traversal detected: resolved path {resolved} is outside {base_dir}"
        )

    if not resolved.exists():
        raise FileNotFoundError(f"Screenshot file not found: {resolved}")

    return resolved.read_bytes(), str(resolved)


def _write_screenshot(file_path: str, data: bytes) -> None:
    """
    Overwrite a screenshot file with blurred data.

    Args:
        file_path: Absolute path to the file.
        data: Blurred image bytes.

    Raises:
        OSError: If the file cannot be written.
    """
    Path(file_path).write_bytes(data)
