"""
API-014: Cloud-provider-agnostic presigned URL generation for screenshot uploads.

Generates a time-limited presigned upload URL for direct client-to-storage PUT
and a permanent blob URL for subsequent retrieval.

CLOUD_PROVIDER env var controls the backend:
  aws   -> S3 presigned PUT URL (requires boto3)
  azure -> Azure Blob SAS URL (requires azure-storage-blob)
  gcp   -> GCS signed URL (requires google-cloud-storage)
  local -> Local filesystem via internal FastAPI endpoints (dev/test only)

Storage path: screenshots/{tenant_id}/{uuid}/{safe_filename}
Expiry: 300 seconds (5 minutes)
Allowed content types: image/png, image/jpeg
"""
import base64
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()

ALLOWED_CONTENT_TYPES = frozenset({"image/png", "image/jpeg"})
PRESIGN_EXPIRES_IN = 300  # seconds


@dataclass
class PresignedUpload:
    """Result of a presigned upload URL generation."""

    upload_url: str
    blob_url: str
    expires_in: int


def generate_presigned_upload(
    tenant_id: str,
    filename: str,
    content_type: str,
    expires_in: int = PRESIGN_EXPIRES_IN,
) -> PresignedUpload:
    """
    Generate a presigned upload URL and permanent blob URL for a screenshot.

    Args:
        tenant_id: Tenant scope — storage path is isolated per tenant.
        filename: Original client filename (sanitized before use).
        content_type: Must be image/png or image/jpeg.
        expires_in: URL validity in seconds (default 300).

    Returns:
        PresignedUpload with upload_url, blob_url, and expires_in.

    Raises:
        ValueError: If content_type is not allowed.
        RuntimeError: If required cloud provider SDK is not installed.
    """
    if content_type not in ALLOWED_CONTENT_TYPES:
        allowed = ", ".join(sorted(ALLOWED_CONTENT_TYPES))
        raise ValueError(f"content_type must be one of: {allowed}")

    safe_filename = _sanitize_filename(filename)
    object_key = f"screenshots/{tenant_id}/{uuid.uuid4()}/{safe_filename}"

    provider = os.environ.get("CLOUD_PROVIDER", "local").lower()

    logger.info(
        "presign_generating",
        provider=provider,
        tenant_id=tenant_id,
        content_type=content_type,
    )

    if provider == "aws":
        return _presign_aws(object_key, content_type, expires_in)
    elif provider == "azure":
        return _presign_azure(object_key, content_type, expires_in)
    elif provider == "gcp":
        return _presign_gcp(object_key, content_type, expires_in)
    else:
        return _presign_local(object_key, content_type, expires_in)


def _sanitize_filename(filename: str) -> str:
    """Strip path traversal and keep only safe characters for object key."""
    basename = os.path.basename(filename)
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", basename)
    return safe[:200] or "screenshot"


def _presign_aws(
    object_key: str, content_type: str, expires_in: int
) -> PresignedUpload:
    """Generate S3 presigned PUT URL."""
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError(
            "CLOUD_PROVIDER=aws requires boto3: pip install boto3"
        ) from exc

    bucket = os.environ["AWS_S3_BUCKET"]
    region = os.environ.get("AWS_REGION", "us-east-1")

    s3 = boto3.client("s3", region_name=region)
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": object_key, "ContentType": content_type},
        ExpiresIn=expires_in,
    )
    blob_url = f"https://{bucket}.s3.{region}.amazonaws.com/{object_key}"
    return PresignedUpload(
        upload_url=upload_url, blob_url=blob_url, expires_in=expires_in
    )


def _presign_azure(
    object_key: str, content_type: str, expires_in: int
) -> PresignedUpload:
    """Generate Azure Blob SAS URL."""
    try:
        from datetime import datetime, timedelta, timezone

        from azure.storage.blob import (
            BlobSasPermissions,
            generate_blob_sas,
        )
    except ImportError as exc:
        raise RuntimeError(
            "CLOUD_PROVIDER=azure requires azure-storage-blob: "
            "pip install azure-storage-blob"
        ) from exc

    account_name = os.environ["AZURE_STORAGE_ACCOUNT"]
    account_key = os.environ["AZURE_STORAGE_KEY"]
    container = os.environ["AZURE_STORAGE_CONTAINER"]
    expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container,
        blob_name=object_key,
        account_key=account_key,
        permission=BlobSasPermissions(write=True),
        expiry=expiry,
        content_type=content_type,
    )
    upload_url = (
        f"https://{account_name}.blob.core.windows.net"
        f"/{container}/{object_key}?{sas_token}"
    )
    blob_url = f"https://{account_name}.blob.core.windows.net/{container}/{object_key}"
    return PresignedUpload(
        upload_url=upload_url, blob_url=blob_url, expires_in=expires_in
    )


def _presign_gcp(
    object_key: str, content_type: str, expires_in: int
) -> PresignedUpload:
    """Generate GCS v4 signed PUT URL."""
    try:
        from google.cloud import storage as gcs
    except ImportError as exc:
        raise RuntimeError(
            "CLOUD_PROVIDER=gcp requires google-cloud-storage: "
            "pip install google-cloud-storage"
        ) from exc

    bucket_name = os.environ["GCS_BUCKET"]
    client = gcs.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_key)
    upload_url = blob.generate_signed_url(
        version="v4",
        expiration=expires_in,
        method="PUT",
        content_type=content_type,
    )
    blob_url = f"https://storage.googleapis.com/{bucket_name}/{object_key}"
    return PresignedUpload(
        upload_url=upload_url, blob_url=blob_url, expires_in=expires_in
    )


def _presign_local(
    object_key: str, content_type: str, expires_in: int
) -> PresignedUpload:
    """
    Local dev presigned URL using HMAC-signed tokens.

    Both upload_url and blob_url use the same signed path:
      {backend}/api/v1/internal/screenshots/{encoded_payload}.{signature}

    PUT to this path -> upload handler: verifies HMAC + expiry + content-type,
                        then writes file to LOCAL_SCREENSHOT_DIR.
    GET to this path -> serve handler: verifies HMAC (skips expiry for permanent
                        access), then serves the file.

    The HMAC signature over the payload {key, exp, ct} ensures the storage path
    cannot be tampered with, preventing path traversal via manipulated tokens.
    """
    secret = _get_local_secret()
    expires_at = int(time.time()) + expires_in
    payload = json.dumps(
        {"key": object_key, "exp": expires_at, "ct": content_type},
        separators=(",", ":"),
    )
    encoded_payload = base64.urlsafe_b64encode(payload.encode()).decode()
    signature = _hmac_sign(secret, payload)

    backend_base = os.environ.get("BACKEND_URL", "http://localhost:8022")
    signed_path = (
        f"{backend_base}/api/v1/internal/screenshots/{encoded_payload}.{signature}"
    )
    # Both upload (PUT) and retrieval (GET) use the same signed URL.
    return PresignedUpload(
        upload_url=signed_path, blob_url=signed_path, expires_in=expires_in
    )


def _get_local_secret() -> bytes:
    """
    Use JWT_SECRET_KEY as HMAC secret for local presign tokens.

    Raises RuntimeError if JWT_SECRET_KEY is not set, consistent with how
    the JWT auth path behaves — an absent secret must never silently fall back
    to a known string that would make presign tokens forgeable.
    """
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Local presigned URL generation requires "
            "this env var. Set it in your .env file."
        )
    return secret.encode()


def _hmac_sign(secret: bytes, payload: str) -> str:
    """Return URL-safe base64-encoded HMAC-SHA256 signature (no padding)."""
    sig = hmac.new(secret, payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def _verify_local_token_signature(token_with_sig: str) -> tuple[dict, str]:
    """
    Verify HMAC signature and decode a local token. Does NOT check expiry.

    Returns:
        (payload_dict, encoded_payload) — caller decides whether to enforce expiry.

    Raises:
        ValueError: If token is malformed or signature is invalid.
    """
    try:
        encoded_payload, signature = token_with_sig.rsplit(".", 1)
    except ValueError as exc:
        raise ValueError("Malformed token: missing signature") from exc

    try:
        payload_str = base64.urlsafe_b64decode(
            encoded_payload + "=="  # restore stripped padding
        ).decode()
    except Exception as exc:
        raise ValueError("Malformed token: cannot decode payload") from exc

    secret = _get_local_secret()
    expected_sig = _hmac_sign(secret, payload_str)
    if not hmac.compare_digest(signature, expected_sig):
        raise ValueError("Invalid upload token signature")

    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError as exc:
        raise ValueError("Malformed token: invalid JSON payload") from exc

    return payload, encoded_payload


def verify_local_upload_token(token_with_sig: str) -> dict:
    """
    Verify and decode a local presign upload token, enforcing expiry.

    Token format: {encoded_payload}.{signature}

    Returns:
        Decoded payload dict with keys: key, exp, ct

    Raises:
        ValueError: If token is malformed, signature invalid, or expired.
    """
    payload, _ = _verify_local_token_signature(token_with_sig)
    if int(time.time()) > payload["exp"]:
        raise ValueError("Upload token has expired")
    return payload


def verify_local_serve_token(token_with_sig: str) -> dict:
    """
    Verify and decode a local presign serve token. Expiry is NOT enforced —
    blob URLs are permanent references valid for as long as the file exists.

    Token format: {encoded_payload}.{signature}

    Returns:
        Decoded payload dict with keys: key, exp, ct

    Raises:
        ValueError: If token is malformed or signature is invalid.
    """
    payload, _ = _verify_local_token_signature(token_with_sig)
    return payload
