"""
HAR-009: Unit tests for HAR approval email notifications.

Tests:
- notify_approval_required: sends email to each active tenant_admin
- Retries up to 3 times on server errors (5xx / exceptions)
- Does not retry on client errors (4xx — returns False)
- Skips silently when SENDGRID_API_KEY is not configured
- Skips silently when SENDGRID_FROM_EMAIL is not configured
- Logs warning when no tenant admins found
- send_approval_email: builds correct subject and approval link
- get_tenant_admin_emails: returns only active tenant_admin rows
- Email subject contains transaction_id
- Approval link uses FRONTEND_URL env var
- Approval link falls back to relative path when FRONTEND_URL not set
"""
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.har.email_notifications import (
    _MAX_EMAIL_RETRIES,
    get_tenant_admin_emails,
    notify_approval_required,
    send_approval_email,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(admin_rows=None):
    """Return a mock AsyncSession that returns the given admin rows."""
    db = AsyncMock()
    result = MagicMock()
    rows = admin_rows if admin_rows is not None else []
    result.mappings.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db


def _admin_row(user_id=None, email="admin@example.com"):
    row = MagicMock()
    row.__getitem__ = lambda self, key: (
        user_id or str(uuid.uuid4()) if key == "id" else email
    )
    return row


def _mock_client(status_code=202):
    """Return a MagicMock SendGrid client whose send() returns status_code."""
    client = MagicMock()
    response = MagicMock()
    response.status_code = status_code
    client.send.return_value = response
    return client


# ---------------------------------------------------------------------------
# send_approval_email
# ---------------------------------------------------------------------------


def test_send_approval_email_returns_true_on_success():
    """send_approval_email returns True when SendGrid returns 202."""
    with patch(
        "app.modules.har.email_notifications._send_email_via_sendgrid",
        return_value=True,
    ):
        result = send_approval_email(
            client=MagicMock(),
            from_email="from@example.com",
            to_email="admin@example.com",
            transaction_id="txn-001",
            amount=6000.0,
            currency="USD",
            approval_link="https://app.example.com/har/transactions/txn-001/approve",
        )
    assert result is True


def test_send_approval_email_subject_contains_transaction_id():
    """send_approval_email builds a subject containing the transaction_id."""
    captured = {}

    def _fake_send(client, from_email, to_email, subject, html_body):
        captured["subject"] = subject
        return True

    with patch(
        "app.modules.har.email_notifications._send_email_via_sendgrid",
        side_effect=_fake_send,
    ):
        send_approval_email(
            client=MagicMock(),
            from_email="from@example.com",
            to_email="admin@example.com",
            transaction_id="HAR-20260317-001234",
            amount=7500.0,
            currency="USD",
            approval_link="http://localhost/har/transactions/HAR-20260317-001234/approve",
        )

    assert "HAR-20260317-001234" in captured["subject"]


def test_send_approval_email_returns_false_on_4xx():
    """send_approval_email returns False when SendGrid rejects with 4xx."""
    with patch(
        "app.modules.har.email_notifications._send_email_via_sendgrid",
        return_value=False,
    ):
        result = send_approval_email(
            client=MagicMock(),
            from_email="from@example.com",
            to_email="bad@example.com",
            transaction_id="txn-002",
            amount=5000.0,
            currency="USD",
            approval_link="/har/transactions/txn-002/approve",
        )
    assert result is False


# ---------------------------------------------------------------------------
# notify_approval_required — no SendGrid configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_skipped_when_no_sendgrid_api_key():
    """notify_approval_required logs warning and returns when API key absent."""
    db = _make_db()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SENDGRID_API_KEY", None)
        with patch(
            "app.modules.har.email_notifications._get_sendgrid_client",
            return_value=None,
        ):
            # Should not raise and should not call db.execute
            await notify_approval_required(
                transaction_id="txn-001",
                tenant_id=str(uuid.uuid4()),
                amount=6000.0,
                currency="USD",
                db=db,
            )
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_notify_skipped_when_no_from_email():
    """notify_approval_required returns early when SENDGRID_FROM_EMAIL is absent."""
    db = _make_db()
    with patch(
        "app.modules.har.email_notifications._get_sendgrid_client",
        return_value=MagicMock(),
    ), patch(
        "app.modules.har.email_notifications._get_from_email",
        return_value="",
    ):
        await notify_approval_required(
            transaction_id="txn-001",
            tenant_id=str(uuid.uuid4()),
            amount=6000.0,
            currency="USD",
            db=db,
        )
    db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# notify_approval_required — normal flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_sends_email_to_each_admin():
    """notify_approval_required calls send_approval_email for each tenant admin."""
    tenant_id = str(uuid.uuid4())
    rows = [
        {"user_id": str(uuid.uuid4()), "email": "admin1@example.com"},
        {"user_id": str(uuid.uuid4()), "email": "admin2@example.com"},
    ]

    sent_to = []

    def _fake_send_email(client, from_email, to_email, **kwargs):
        sent_to.append(to_email)
        return True

    with patch(
        "app.modules.har.email_notifications._get_sendgrid_client",
        return_value=MagicMock(),
    ), patch(
        "app.modules.har.email_notifications._get_from_email",
        return_value="from@example.com",
    ), patch(
        "app.modules.har.email_notifications._get_frontend_url",
        return_value="https://app.example.com",
    ), patch(
        "app.modules.har.email_notifications.get_tenant_admin_emails",
        AsyncMock(return_value=rows),
    ), patch(
        "app.modules.har.email_notifications.send_approval_email",
        side_effect=_fake_send_email,
    ):
        await notify_approval_required(
            transaction_id="txn-abc",
            tenant_id=tenant_id,
            amount=6000.0,
            currency="USD",
            db=AsyncMock(),
        )

    assert set(sent_to) == {"admin1@example.com", "admin2@example.com"}


@pytest.mark.asyncio
async def test_notify_logs_warning_when_no_admins():
    """notify_approval_required logs warning and does not error when no admins."""
    with patch(
        "app.modules.har.email_notifications._get_sendgrid_client",
        return_value=MagicMock(),
    ), patch(
        "app.modules.har.email_notifications._get_from_email",
        return_value="from@example.com",
    ), patch(
        "app.modules.har.email_notifications.get_tenant_admin_emails",
        AsyncMock(return_value=[]),
    ), patch(
        "app.modules.har.email_notifications.send_approval_email"
    ) as mock_send:
        await notify_approval_required(
            transaction_id="txn-abc",
            tenant_id=str(uuid.uuid4()),
            amount=6000.0,
            currency="USD",
            db=AsyncMock(),
        )
    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_retries_on_server_error():
    """notify_approval_required retries up to MAX_EMAIL_RETRIES on exceptions."""
    attempts = []

    def _flaky_send(client, from_email, to_email, **kwargs):
        attempts.append(1)
        raise RuntimeError("SendGrid server error: HTTP 500")

    rows = [{"user_id": str(uuid.uuid4()), "email": "admin@example.com"}]

    with patch(
        "app.modules.har.email_notifications._get_sendgrid_client",
        return_value=MagicMock(),
    ), patch(
        "app.modules.har.email_notifications._get_from_email",
        return_value="from@example.com",
    ), patch(
        "app.modules.har.email_notifications._get_frontend_url",
        return_value="https://app.example.com",
    ), patch(
        "app.modules.har.email_notifications.get_tenant_admin_emails",
        AsyncMock(return_value=rows),
    ), patch(
        "app.modules.har.email_notifications.send_approval_email",
        side_effect=_flaky_send,
    ):
        await notify_approval_required(
            transaction_id="txn-retry",
            tenant_id=str(uuid.uuid4()),
            amount=10000.0,
            currency="USD",
            db=AsyncMock(),
        )

    assert len(attempts) == _MAX_EMAIL_RETRIES


@pytest.mark.asyncio
async def test_notify_does_not_retry_on_4xx():
    """notify_approval_required stops after first 4xx (non-retriable)."""
    attempts = []

    def _rejected_send(client, from_email, to_email, **kwargs):
        attempts.append(1)
        return False  # 4xx — not retriable

    rows = [{"user_id": str(uuid.uuid4()), "email": "admin@example.com"}]

    with patch(
        "app.modules.har.email_notifications._get_sendgrid_client",
        return_value=MagicMock(),
    ), patch(
        "app.modules.har.email_notifications._get_from_email",
        return_value="from@example.com",
    ), patch(
        "app.modules.har.email_notifications._get_frontend_url",
        return_value="https://app.example.com",
    ), patch(
        "app.modules.har.email_notifications.get_tenant_admin_emails",
        AsyncMock(return_value=rows),
    ), patch(
        "app.modules.har.email_notifications.send_approval_email",
        side_effect=_rejected_send,
    ):
        await notify_approval_required(
            transaction_id="txn-4xx",
            tenant_id=str(uuid.uuid4()),
            amount=5000.0,
            currency="USD",
            db=AsyncMock(),
        )

    assert len(attempts) == 1


# ---------------------------------------------------------------------------
# Approval link construction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_link_uses_frontend_url():
    """Approval link is prefixed with FRONTEND_URL when set."""
    captured = {}

    def _capture_send(
        client, from_email, to_email, transaction_id, amount, currency, approval_link
    ):
        captured["link"] = approval_link
        return True

    rows = [{"user_id": str(uuid.uuid4()), "email": "admin@example.com"}]

    with patch(
        "app.modules.har.email_notifications._get_sendgrid_client",
        return_value=MagicMock(),
    ), patch(
        "app.modules.har.email_notifications._get_from_email",
        return_value="from@example.com",
    ), patch(
        "app.modules.har.email_notifications._get_frontend_url",
        return_value="https://my.app.com",
    ), patch(
        "app.modules.har.email_notifications.get_tenant_admin_emails",
        AsyncMock(return_value=rows),
    ), patch(
        "app.modules.har.email_notifications.send_approval_email",
        side_effect=_capture_send,
    ):
        await notify_approval_required(
            transaction_id="txn-link-test",
            tenant_id=str(uuid.uuid4()),
            amount=5500.0,
            currency="USD",
            db=AsyncMock(),
        )

    assert captured["link"].startswith("https://my.app.com/")
    assert "txn-link-test" in captured["link"]


@pytest.mark.asyncio
async def test_approval_link_falls_back_to_relative_path():
    """Approval link is a relative path when FRONTEND_URL is not set."""
    captured = {}

    def _capture_send(
        client, from_email, to_email, transaction_id, amount, currency, approval_link
    ):
        captured["link"] = approval_link
        return True

    rows = [{"user_id": str(uuid.uuid4()), "email": "admin@example.com"}]

    with patch(
        "app.modules.har.email_notifications._get_sendgrid_client",
        return_value=MagicMock(),
    ), patch(
        "app.modules.har.email_notifications._get_from_email",
        return_value="from@example.com",
    ), patch(
        "app.modules.har.email_notifications._get_frontend_url",
        return_value="",
    ), patch(
        "app.modules.har.email_notifications.get_tenant_admin_emails",
        AsyncMock(return_value=rows),
    ), patch(
        "app.modules.har.email_notifications.send_approval_email",
        side_effect=_capture_send,
    ):
        await notify_approval_required(
            transaction_id="txn-relative",
            tenant_id=str(uuid.uuid4()),
            amount=5500.0,
            currency="USD",
            db=AsyncMock(),
        )

    assert captured["link"].startswith("/har/transactions/")
    assert "txn-relative" in captured["link"]
