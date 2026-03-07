"""
Unit tests for app.core.storage — presigned URL generation (API-014).

Tests:
- _sanitize_filename: path traversal, special chars, length truncation
- generate_presigned_upload: content-type validation, routing to local provider
- _presign_local: HMAC token structure, payload contents, blob_url == upload_url
- verify_local_upload_token: valid token, invalid signature, expired token, malformed
- verify_local_serve_token: valid token, invalid signature (expiry is not checked)
- CLOUD_PROVIDER dispatch (aws/azure/gcp raise RuntimeError on missing SDK)

Tier 1: No real infrastructure required.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from unittest.mock import patch

import pytest

from app.core.storage import (
    ALLOWED_CONTENT_TYPES,
    PresignedUpload,
    _get_local_secret,
    _hmac_sign,
    _presign_local,
    _sanitize_filename,
    generate_presigned_upload,
    verify_local_serve_token,
    verify_local_upload_token,
)


# ---------------------------------------------------------------------------
# _sanitize_filename
# ---------------------------------------------------------------------------


class TestSanitizeFilename:
    def test_strips_path_traversal(self):
        result = _sanitize_filename("../../etc/passwd")
        assert ".." not in result
        assert "/" not in result
        assert result == "passwd"

    def test_replaces_special_chars(self):
        result = _sanitize_filename("my file (1).png")
        assert " " not in result
        assert "(" not in result
        assert ")" not in result

    def test_preserves_alphanumeric_dot_dash_underscore(self):
        result = _sanitize_filename("screenshot-2026_01.png")
        assert result == "screenshot-2026_01.png"

    def test_truncates_at_200_chars(self):
        long_name = "a" * 300 + ".png"
        result = _sanitize_filename(long_name)
        assert len(result) <= 200

    def test_empty_filename_becomes_screenshot(self):
        result = _sanitize_filename("")
        assert result == "screenshot"

    def test_strips_directory_component(self):
        result = _sanitize_filename("/uploads/tenant-1/shot.png")
        assert result == "shot.png"


# ---------------------------------------------------------------------------
# generate_presigned_upload — content type validation
# ---------------------------------------------------------------------------


class TestGeneratePresignedUpload:
    def test_rejects_invalid_content_type(self):
        with pytest.raises(ValueError, match="content_type must be one of"):
            generate_presigned_upload(
                tenant_id="t1", filename="shot.gif", content_type="image/gif"
            )

    def test_rejects_pdf_content_type(self):
        with pytest.raises(ValueError):
            generate_presigned_upload(
                tenant_id="t1", filename="shot.pdf", content_type="application/pdf"
            )

    def test_allowed_content_types_constant(self):
        assert "image/png" in ALLOWED_CONTENT_TYPES
        assert "image/jpeg" in ALLOWED_CONTENT_TYPES
        assert "image/gif" not in ALLOWED_CONTENT_TYPES

    def test_local_provider_returns_presigned_upload(self):
        """With CLOUD_PROVIDER=local, returns PresignedUpload without error."""
        with patch.dict(
            os.environ, {"CLOUD_PROVIDER": "local", "JWT_SECRET_KEY": "test-secret"}
        ):
            result = generate_presigned_upload(
                tenant_id="tenant-abc",
                filename="shot.png",
                content_type="image/png",
            )
        assert isinstance(result, PresignedUpload)
        assert result.expires_in == 300
        assert result.upload_url.startswith("http")
        assert result.blob_url.startswith("http")

    def test_storage_path_includes_tenant_id(self):
        """Object key in presigned URL is scoped to tenant_id."""
        with patch.dict(
            os.environ, {"CLOUD_PROVIDER": "local", "JWT_SECRET_KEY": "test-secret"}
        ):
            result = generate_presigned_upload(
                tenant_id="tenant-xyz",
                filename="shot.png",
                content_type="image/png",
            )

        # Decode the HMAC-signed payload from the upload URL to verify tenant scoping.
        # The token format is {encoded_payload}.{signature} — split on the last dot.
        upload_path = result.upload_url.split("/internal/screenshots/")[1]
        encoded_payload = upload_path.rsplit(".", 1)[0]
        payload_str = base64.urlsafe_b64decode(encoded_payload + "==").decode()
        payload = json.loads(payload_str)
        assert "tenant-xyz" in payload["key"]

    def test_aws_provider_raises_without_boto3(self):
        """aws provider raises RuntimeError when boto3 is not installed."""
        with patch.dict(os.environ, {"CLOUD_PROVIDER": "aws"}):
            with patch.dict("sys.modules", {"boto3": None}):
                with pytest.raises((RuntimeError, ImportError)):
                    generate_presigned_upload(
                        tenant_id="t1", filename="shot.png", content_type="image/png"
                    )

    def test_jpeg_content_type_accepted(self):
        """image/jpeg is a valid content type."""
        with patch.dict(
            os.environ, {"CLOUD_PROVIDER": "local", "JWT_SECRET_KEY": "test-secret"}
        ):
            result = generate_presigned_upload(
                tenant_id="t1",
                filename="photo.jpg",
                content_type="image/jpeg",
            )
        assert isinstance(result, PresignedUpload)


# ---------------------------------------------------------------------------
# _presign_local — token structure
# ---------------------------------------------------------------------------


class TestPresignLocal:
    def test_upload_url_equals_blob_url(self):
        """Both URLs are the same signed path; PUT = upload, GET = serve."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret"}):
            result = _presign_local("screenshots/t1/uuid/shot.png", "image/png", 300)
        assert result.upload_url == result.blob_url

    def test_upload_url_contains_signature(self):
        """Upload URL has format {encoded_payload}.{signature}."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret"}):
            result = _presign_local("screenshots/t1/uuid/shot.png", "image/png", 300)

        upload_path = result.upload_url.split("/internal/screenshots/")[1]
        # Should have at least one "." separator between payload and signature
        assert "." in upload_path

    def test_blob_url_contains_signature(self):
        """Blob URL (== upload URL) carries the HMAC signature for path integrity."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret"}):
            result = _presign_local("screenshots/t1/uuid/shot.png", "image/png", 300)

        blob_path = result.blob_url.split("/internal/screenshots/")[1]
        # Should have the signed format: {encoded_payload}.{signature}
        assert "." in blob_path
        encoded_payload = blob_path.rsplit(".", 1)[0]
        payload_str = base64.urlsafe_b64decode(encoded_payload + "==").decode()
        payload = json.loads(payload_str)
        assert "key" in payload

    def test_payload_contains_expiry_and_content_type(self):
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret"}):
            before = int(time.time())
            result = _presign_local("screenshots/t1/uuid/shot.png", "image/png", 300)
            after = int(time.time())

        upload_path = result.upload_url.split("/internal/screenshots/")[1]
        encoded = upload_path.rsplit(".", 1)[0]
        payload = json.loads(base64.urlsafe_b64decode(encoded + "==").decode())

        assert payload["ct"] == "image/png"
        assert before + 300 <= payload["exp"] <= after + 300

    def test_backend_url_used_in_upload_url(self):
        """upload_url uses BACKEND_URL env var."""
        env = {"JWT_SECRET_KEY": "test-secret", "BACKEND_URL": "http://myserver:9000"}
        with patch.dict(os.environ, env):
            result = _presign_local("screenshots/t/u/shot.png", "image/png", 300)

        assert result.upload_url.startswith("http://myserver:9000")
        assert result.blob_url.startswith("http://myserver:9000")


# ---------------------------------------------------------------------------
# verify_local_upload_token
# ---------------------------------------------------------------------------


class TestVerifyLocalUploadToken:
    def _make_token(
        self, key="screenshots/t/u/shot.png", ct="image/png", exp_offset=300
    ):
        secret = b"test-verify-secret"
        expires_at = int(time.time()) + exp_offset
        payload = json.dumps(
            {"key": key, "exp": expires_at, "ct": ct},
            separators=(",", ":"),
        )
        encoded = base64.urlsafe_b64encode(payload.encode()).decode()
        sig = hmac.new(secret, payload.encode(), hashlib.sha256).digest()
        signature = base64.urlsafe_b64encode(sig).decode().rstrip("=")
        return f"{encoded}.{signature}", secret

    def test_valid_token_returns_payload(self):
        token, secret = self._make_token()
        with patch.dict(os.environ, {"JWT_SECRET_KEY": secret.decode()}):
            payload = verify_local_upload_token(token)
        assert payload["key"] == "screenshots/t/u/shot.png"
        assert payload["ct"] == "image/png"

    def test_invalid_signature_raises(self):
        token, secret = self._make_token()
        tampered = token[:-4] + "XXXX"
        with patch.dict(os.environ, {"JWT_SECRET_KEY": secret.decode()}):
            with pytest.raises(ValueError, match="Invalid upload token signature"):
                verify_local_upload_token(tampered)

    def test_expired_token_raises(self):
        token, secret = self._make_token(exp_offset=-10)  # already expired
        with patch.dict(os.environ, {"JWT_SECRET_KEY": secret.decode()}):
            with pytest.raises(ValueError, match="expired"):
                verify_local_upload_token(token)

    def test_malformed_token_no_dot_raises(self):
        with pytest.raises(ValueError, match="Malformed"):
            verify_local_upload_token("nodotinthisstring")

    def test_malformed_base64_payload_raises(self):
        with pytest.raises(ValueError, match="Malformed"):
            verify_local_upload_token("!!invalid!!.signature")

    def test_token_tampering_key_raises_signature_error(self):
        """Mutating the payload after signing invalidates the signature check."""
        token, secret = self._make_token(key="screenshots/t/u/original.png")
        # Modify the encoded payload to a different key
        parts = token.split(".", 1)
        new_payload = json.dumps(
            {
                "key": "screenshots/attacker/evil.png",
                "exp": int(time.time()) + 300,
                "ct": "image/png",
            },
            separators=(",", ":"),
        )
        tampered_encoded = base64.urlsafe_b64encode(new_payload.encode()).decode()
        tampered_token = f"{tampered_encoded}.{parts[1]}"
        with patch.dict(os.environ, {"JWT_SECRET_KEY": secret.decode()}):
            with pytest.raises(ValueError, match="Invalid upload token signature"):
                verify_local_upload_token(tampered_token)


# ---------------------------------------------------------------------------
# verify_local_serve_token — same HMAC but expiry is NOT enforced
# ---------------------------------------------------------------------------


class TestVerifyLocalServeToken:
    def _make_token(self, exp_offset=300):
        secret = b"test-serve-secret"
        expires_at = int(time.time()) + exp_offset
        payload = json.dumps(
            {"key": "screenshots/t/u/shot.png", "exp": expires_at, "ct": "image/png"},
            separators=(",", ":"),
        )
        encoded = base64.urlsafe_b64encode(payload.encode()).decode()
        sig = hmac.new(secret, payload.encode(), hashlib.sha256).digest()
        signature = base64.urlsafe_b64encode(sig).decode().rstrip("=")
        return f"{encoded}.{signature}", secret

    def test_valid_token_returns_payload(self):
        token, secret = self._make_token()
        with patch.dict(os.environ, {"JWT_SECRET_KEY": secret.decode()}):
            payload = verify_local_serve_token(token)
        assert payload["key"] == "screenshots/t/u/shot.png"

    def test_expired_token_still_works_for_serve(self):
        """Serve tokens ignore expiry — blob URLs are permanent after upload."""
        token, secret = self._make_token(exp_offset=-100)  # already expired
        with patch.dict(os.environ, {"JWT_SECRET_KEY": secret.decode()}):
            payload = verify_local_serve_token(token)  # must NOT raise
        assert payload["key"] == "screenshots/t/u/shot.png"

    def test_invalid_signature_rejected_by_serve(self):
        """Forged signatures are rejected even without expiry enforcement."""
        token, secret = self._make_token()
        tampered = token[:-4] + "XXXX"
        with patch.dict(os.environ, {"JWT_SECRET_KEY": secret.decode()}):
            with pytest.raises(ValueError, match="Invalid upload token signature"):
                verify_local_serve_token(tampered)
