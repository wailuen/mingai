"""
HAR-011: Fee record creation on HAR transaction completion.

When a HAR transaction transitions to COMPLETED state, a fee record is
inserted into har_fee_records with:
  - Standard platform fee rate: 0.5% of transaction amount
  - Fee is denominated in the same currency as the transaction
  - If amount is None (non-monetary transactions), fee_amount = 0.0

Called by state_machine.transition_state() on COMPLETED transitions.
Errors are caught by the caller and logged — fee record failure must NOT
prevent the state transition from being returned to the client.
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# Platform fee rate (0.5%)
_FEE_RATE = 0.005


def _compute_fee(amount: Optional[float]) -> float:
    """Return the platform fee for a transaction amount."""
    if amount is None or amount <= 0:
        return 0.0
    return round(amount * _FEE_RATE, 6)


async def create_fee_record(
    transaction_id: str,
    tenant_id: str,
    amount: Optional[float],
    currency: Optional[str],
    db: AsyncSession,
) -> str:
    """
    Insert a new har_fee_records row for a completed transaction.

    Column mapping (matches v030 migration schema):
      fee_type    = 'platform_fee'
      amount_usd  = computed fee amount
      currency    = transaction currency
      fee_basis   = descriptive string (rate applied)
      status      = 'accrued'

    Returns the new fee record ID.
    Raises on DB errors (caller should catch and log).
    """
    fee_id = str(uuid.uuid4())
    fee_amount = _compute_fee(amount)
    effective_currency = currency or "USD"
    fee_basis = (
        f"{_FEE_RATE * 100:.1f}% platform fee on {amount or 0:.2f} {effective_currency}"
    )

    await db.execute(
        text(
            "INSERT INTO har_fee_records "
            "(id, tenant_id, transaction_id, fee_type, amount_usd, currency, fee_basis, status) "
            "VALUES (:id, :tenant_id, :transaction_id, 'platform_fee', "
            ":amount_usd, :currency, :fee_basis, 'accrued')"
        ),
        {
            "id": fee_id,
            "tenant_id": tenant_id,
            "transaction_id": transaction_id,
            "amount_usd": fee_amount,
            "currency": effective_currency,
            "fee_basis": fee_basis,
        },
    )
    await db.commit()

    logger.info(
        "har_fee_record_created",
        fee_id=fee_id,
        transaction_id=transaction_id,
        tenant_id=tenant_id,
        fee_amount=fee_amount,
        currency=effective_currency,
    )
    return fee_id
