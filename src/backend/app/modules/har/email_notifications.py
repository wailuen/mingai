"""
HAR-009: Email notification for HAR transaction approval.

Sends a notification email via SendGrid when a HAR transaction requires
human approval (amount >= threshold). Emails are sent to all tenant_admin
users for the transaction's tenant.

Retries up to _MAX_EMAIL_RETRIES times on transient failures (HTTP 5xx
or network errors). Client errors (4xx) are not retried.

All env vars consumed:
- SENDGRID_API_KEY    — SendGrid API key (required)
- SENDGRID_FROM_EMAIL — Verified sender address (required)
- FRONTEND_URL        — Base URL for approval link (optional, defaults to '')
"""
from __future__ import annotations

import html
import os
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

_MAX_EMAIL_RETRIES = 3

# ---------------------------------------------------------------------------
# SendGrid client helpers (importable façade — isolated for testability)
# ---------------------------------------------------------------------------


def _get_sendgrid_client():
    """Return an initialised SendGrid API client, or None if not configured."""
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        logger.error("sendgrid_api_key_not_configured")
        return None

    try:
        from sendgrid import SendGridAPIClient  # type: ignore[import-not-found]

        return SendGridAPIClient(api_key)
    except ImportError:
        logger.error("sendgrid_not_installed")
        return None


def _get_from_email() -> str:
    """Return the verified sender address from environment."""
    return os.environ.get("SENDGRID_FROM_EMAIL", "")


def _get_frontend_url() -> str:
    """Return the frontend base URL from environment."""
    return os.environ.get("FRONTEND_URL", "")


# ---------------------------------------------------------------------------
# Tenant admin e-mail lookup
# ---------------------------------------------------------------------------


async def get_tenant_admin_emails(
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """
    Return a list of {user_id, email} dicts for all active tenant_admin
    users belonging to the given tenant.
    """
    result = await db.execute(
        text(
            "SELECT id, email FROM users "
            "WHERE tenant_id = :tenant_id "
            "AND role = 'tenant_admin' "
            "AND status = 'active'"
        ),
        {"tenant_id": tenant_id},
    )
    rows = result.mappings().all()
    return [{"user_id": str(r["id"]), "email": r["email"]} for r in rows]


# ---------------------------------------------------------------------------
# Email send (single recipient, with retry)
# ---------------------------------------------------------------------------


def _send_email_via_sendgrid(
    client,
    from_email: str,
    to_email: str,
    subject: str,
    html_body: str,
) -> bool:
    """
    Send a single email via SendGrid.

    Returns True on success, False on client error (4xx — not retriable).
    Raises on server error (5xx — retriable) or network exception.
    """
    from sendgrid.helpers.mail import Mail  # type: ignore[import-not-found]

    message = Mail(
        from_email=from_email,
        to_emails=to_email,
        subject=subject,
        html_content=html_body,
    )
    response = client.send(message)
    status_code = response.status_code if hasattr(response, "status_code") else 202

    if 200 <= status_code < 300:
        return True

    if 400 <= status_code < 500:
        logger.error(
            "sendgrid_client_error",
            to_email=to_email,
            status_code=status_code,
        )
        return False

    # 5xx — raise so the caller can retry
    raise RuntimeError(f"SendGrid server error: HTTP {status_code}")


def send_approval_email(
    client,
    from_email: str,
    to_email: str,
    transaction_id: str,
    amount: float,
    currency: str,
    approval_link: str,
) -> bool:
    """
    Build and send the PO approval email to a single recipient.

    Returns True if sent, False if permanently rejected (4xx).
    Raises on retriable server errors.
    """
    safe_txn_id = html.escape(transaction_id)
    safe_currency = html.escape(currency)
    safe_approval_link = html.escape(approval_link)
    subject = f"[mingai] HAR Transaction Approval Required — {safe_txn_id}"
    html_body = (
        f"<p>A HAR transaction requires your approval.</p>"
        f"<ul>"
        f"<li><strong>Transaction ID:</strong> {safe_txn_id}</li>"
        f"<li><strong>Amount:</strong> {amount:,.2f} {safe_currency}</li>"
        f"</ul>"
        f"<p>"
        f'<a href="{safe_approval_link}" style="'
        f"background:#4fffb0;color:#0c0e14;padding:10px 20px;"
        f'text-decoration:none;border-radius:7px;font-weight:600;">'
        f"Review &amp; Approve"
        f"</a>"
        f"</p>"
        f'<p style="color:#8892a4;font-size:12px;">'
        f"This approval link expires in 48 hours. "
        f"Do not share this email."
        f"</p>"
    )
    return _send_email_via_sendgrid(client, from_email, to_email, subject, html_body)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def notify_approval_required(
    transaction_id: str,
    tenant_id: str,
    amount: float,
    currency: str,
    db: AsyncSession,
) -> None:
    """
    Send PO approval notification emails to all active tenant_admin users.

    Called by the HAR routes when a transaction is created with
    requires_human_approval=True.

    Each recipient is attempted up to _MAX_EMAIL_RETRIES times.
    Errors are logged but never propagated — a failed email MUST NOT
    block the transaction creation response.
    """
    client = _get_sendgrid_client()
    if client is None:
        logger.warning(
            "har_approval_email_skipped_no_sendgrid",
            transaction_id=transaction_id,
            tenant_id=tenant_id,
        )
        return

    from_email = _get_from_email()
    if not from_email:
        logger.error(
            "sendgrid_from_email_not_configured",
            transaction_id=transaction_id,
        )
        return

    frontend_url = _get_frontend_url()
    approval_link = (
        f"{frontend_url}/har/transactions/{transaction_id}/approve"
        if frontend_url
        else f"/har/transactions/{transaction_id}/approve"
    )

    try:
        recipients = await get_tenant_admin_emails(tenant_id, db)
    except Exception as exc:
        logger.error(
            "har_approval_email_lookup_failed",
            transaction_id=transaction_id,
            tenant_id=tenant_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return

    if not recipients:
        logger.warning(
            "har_approval_email_no_tenant_admins",
            transaction_id=transaction_id,
            tenant_id=tenant_id,
        )
        return

    for recipient in recipients:
        user_id = recipient["user_id"]
        to_email = recipient["email"]
        sent = False

        for attempt in range(1, _MAX_EMAIL_RETRIES + 1):
            try:
                result = send_approval_email(
                    client=client,
                    from_email=from_email,
                    to_email=to_email,
                    transaction_id=transaction_id,
                    amount=amount,
                    currency=currency or "USD",
                    approval_link=approval_link,
                )
                if result:
                    logger.info(
                        "har_approval_email_sent",
                        transaction_id=transaction_id,
                        user_id=user_id,
                        attempt=attempt,
                    )
                    sent = True
                    break
                else:
                    # 4xx — client error, do not retry
                    logger.error(
                        "har_approval_email_rejected",
                        transaction_id=transaction_id,
                        user_id=user_id,
                    )
                    break
            except Exception as exc:
                logger.warning(
                    "har_approval_email_attempt_failed",
                    transaction_id=transaction_id,
                    user_id=user_id,
                    attempt=attempt,
                    max_retries=_MAX_EMAIL_RETRIES,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

        if not sent:
            logger.error(
                "har_approval_email_all_retries_exhausted",
                transaction_id=transaction_id,
                user_id=user_id,
            )
