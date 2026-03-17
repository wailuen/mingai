"""
HAR A2A Transaction API routes (AI-043, AI-044, AI-045).

Endpoints:
- POST   /har/transactions                       - Create a new HAR transaction
- GET    /har/transactions                       - List transactions (filterable by state)
- GET    /har/transactions/{txn_id}              - Get transaction detail
- POST   /har/transactions/{txn_id}/transition   - Apply state transition
- POST   /har/transactions/{txn_id}/approve      - Human approval gate
- POST   /har/transactions/{txn_id}/reject       - Reject (→ ABANDONED)
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_tenant_admin
from app.core.session import get_async_session
from app.modules.har.state_machine import (
    ALL_STATES,
    check_requires_approval,
    get_transaction,
    transition_state,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/har", tags=["har"])

# Approval window: 48 hours
APPROVAL_WINDOW_HOURS = 48


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateTransactionRequest(BaseModel):
    initiator_agent_id: str = Field(..., min_length=1)
    counterparty_agent_id: str = Field(..., min_length=1)
    amount: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field(None, max_length=10)
    payload: Optional[dict] = Field(default_factory=dict)


_VALID_STATES_PATTERN = "^(DRAFT|OPEN|NEGOTIATING|COMMITTED|EXECUTING|COMPLETED|ABANDONED|DISPUTED|RESOLVED)$"


class TransitionRequest(BaseModel):
    new_state: str = Field(..., pattern=_VALID_STATES_PATTERN)


# ---------------------------------------------------------------------------
# DB helper functions (mockable in unit tests)
# ---------------------------------------------------------------------------


async def create_transaction_db(
    tenant_id: str,
    initiator_agent_id: str,
    counterparty_agent_id: str,
    amount: Optional[float],
    currency: Optional[str],
    payload: dict,
    requires_human_approval: bool,
    approval_deadline: Optional[datetime],
    db: AsyncSession,
) -> dict:
    """Insert a new har_transactions row in DRAFT state."""
    txn_id = str(uuid.uuid4())
    payload_json = json.dumps(payload or {})
    await db.execute(
        text(
            "INSERT INTO har_transactions "
            "(id, tenant_id, initiator_agent_id, counterparty_agent_id, state, "
            "amount, currency, payload, requires_human_approval, approval_deadline) "
            "VALUES (:id, :tenant_id, :initiator_agent_id, :counterparty_agent_id, 'DRAFT', "
            ":amount, :currency, CAST(:payload AS jsonb), :requires_human_approval, :approval_deadline)"
        ),
        {
            "id": txn_id,
            "tenant_id": tenant_id,
            "initiator_agent_id": initiator_agent_id,
            "counterparty_agent_id": counterparty_agent_id,
            "amount": amount,
            "currency": currency,
            "payload": payload_json,
            "requires_human_approval": requires_human_approval,
            "approval_deadline": approval_deadline,
        },
    )
    await db.commit()
    logger.info(
        "har_transaction_created",
        txn_id=txn_id,
        tenant_id=tenant_id,
        initiator_agent_id=initiator_agent_id,
        counterparty_agent_id=counterparty_agent_id,
        requires_human_approval=requires_human_approval,
    )
    txn = await get_transaction(txn_id, tenant_id, db)
    if txn is None:
        raise RuntimeError(f"Transaction {txn_id} disappeared after insert")
    return txn


async def get_transaction_db(
    txn_id: str, tenant_id: str, db: AsyncSession
) -> Optional[dict]:
    """Fetch a transaction by id and tenant_id."""
    return await get_transaction(txn_id, tenant_id, db)


async def list_transactions_db(
    tenant_id: str,
    page: int,
    page_size: int,
    state_filter: Optional[str],
    db: AsyncSession,
) -> dict:
    """List har_transactions for a tenant with optional state filter."""
    if state_filter and state_filter not in ALL_STATES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid state '{state_filter}'. Valid states: {ALL_STATES}",
        )
    offset = (page - 1) * page_size
    base_params: dict = {"tenant_id": tenant_id, "limit": page_size, "offset": offset}

    if state_filter:
        count_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM har_transactions "
                "WHERE tenant_id = :tenant_id AND state = :state"
            ),
            {**base_params, "state": state_filter},
        )
    else:
        count_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM har_transactions " "WHERE tenant_id = :tenant_id"
            ),
            base_params,
        )
    total = count_result.scalar() or 0

    _cols = (
        "id, tenant_id, initiator_agent_id, counterparty_agent_id, "
        "state, amount, currency, payload, requires_human_approval, "
        "human_approved_at, human_approved_by, approval_deadline, "
        "chain_head_hash, created_at, updated_at"
    )
    if state_filter:
        rows_result = await db.execute(
            text(
                f"SELECT {_cols} FROM har_transactions "
                "WHERE tenant_id = :tenant_id AND state = :state "
                "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            {**base_params, "state": state_filter},
        )
    else:
        rows_result = await db.execute(
            text(
                f"SELECT {_cols} FROM har_transactions "
                "WHERE tenant_id = :tenant_id "
                "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            base_params,
        )
    items = []
    for row in rows_result.mappings():
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        items.append(
            {
                "id": str(row["id"]),
                "tenant_id": str(row["tenant_id"]),
                "initiator_agent_id": str(row["initiator_agent_id"]),
                "counterparty_agent_id": str(row["counterparty_agent_id"]),
                "state": row["state"],
                "amount": float(row["amount"]) if row["amount"] is not None else None,
                "currency": row["currency"],
                "payload": payload or {},
                "requires_human_approval": row["requires_human_approval"],
                "human_approved_at": str(row["human_approved_at"])
                if row["human_approved_at"]
                else None,
                "human_approved_by": str(row["human_approved_by"])
                if row["human_approved_by"]
                else None,
                "approval_deadline": str(row["approval_deadline"])
                if row["approval_deadline"]
                else None,
                "chain_head_hash": row["chain_head_hash"],
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
        )
    return {"items": items, "total": total}


async def approve_transaction_db(
    txn_id: str, tenant_id: str, approver_id: str, db: AsyncSession
) -> None:
    """Set human_approved_at and human_approved_by on a transaction."""
    await db.execute(
        text(
            "UPDATE har_transactions "
            "SET human_approved_at = NOW(), human_approved_by = :approver_id, updated_at = NOW() "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"approver_id": approver_id, "id": txn_id, "tenant_id": tenant_id},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post("/transactions", status_code=status.HTTP_201_CREATED)
async def create_transaction(
    body: CreateTransactionRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """AI-043: Create a new HAR transaction in DRAFT state."""
    requires_approval = await check_requires_approval(
        body.amount, current_user.tenant_id, session
    )
    approval_deadline = None
    if requires_approval:
        approval_deadline = datetime.now(timezone.utc) + timedelta(
            hours=APPROVAL_WINDOW_HOURS
        )

    txn = await create_transaction_db(
        tenant_id=current_user.tenant_id,
        initiator_agent_id=body.initiator_agent_id,
        counterparty_agent_id=body.counterparty_agent_id,
        amount=body.amount,
        currency=body.currency,
        payload=body.payload or {},
        requires_human_approval=requires_approval,
        approval_deadline=approval_deadline,
        db=session,
    )

    # HAR-009: send approval email to all tenant_admin users (non-blocking)
    if requires_approval and body.amount is not None:
        from app.modules.har.email_notifications import notify_approval_required

        try:
            await notify_approval_required(
                transaction_id=txn["id"],
                tenant_id=current_user.tenant_id,
                amount=body.amount,
                currency=body.currency or "USD",
                db=session,
            )
        except Exception as exc:
            logger.error(
                "har_approval_email_hook_failed",
                transaction_id=txn["id"],
                tenant_id=current_user.tenant_id,
                error_type=type(exc).__name__,
            )

    return txn


@router.get("/transactions")
async def list_transactions(
    state: Optional[str] = Query(None, description="Filter by state"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """AI-043: List HAR transactions for the tenant."""
    result = await list_transactions_db(
        tenant_id=current_user.tenant_id,
        page=page,
        page_size=page_size,
        state_filter=state,
        db=session,
    )
    return {
        "items": result["items"],
        "total": result["total"],
        "page": page,
        "page_size": page_size,
    }


@router.get("/transactions/{txn_id}")
async def get_transaction_endpoint(
    txn_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """AI-043: Get HAR transaction detail."""
    txn = await get_transaction_db(txn_id, current_user.tenant_id, session)
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction '{txn_id}' not found",
        )
    return txn


@router.post("/transactions/{txn_id}/transition")
async def transition_transaction(
    txn_id: str,
    body: TransitionRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """AI-043: Apply a state transition to a HAR transaction."""
    return await transition_state(
        transaction_id=txn_id,
        new_state=body.new_state,
        actor_agent_id=None,
        actor_user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )


@router.post("/transactions/{txn_id}/approve")
async def approve_transaction(
    txn_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """AI-045: Human approval gate — approve a pending transaction."""
    txn = await get_transaction_db(txn_id, current_user.tenant_id, session)
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction '{txn_id}' not found",
        )
    if txn["state"] not in ("NEGOTIATING", "OPEN"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve transaction in state '{txn['state']}'. "
            "Must be NEGOTIATING or OPEN.",
        )

    await approve_transaction_db(
        txn_id, current_user.tenant_id, current_user.id, session
    )

    updated = await transition_state(
        transaction_id=txn_id,
        new_state="COMMITTED",
        actor_agent_id=None,
        actor_user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    updated["human_approved_by"] = current_user.id
    logger.info(
        "har_transaction_approved",
        txn_id=txn_id,
        approver_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )
    return updated


@router.post("/transactions/{txn_id}/reject")
async def reject_transaction(
    txn_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """AI-045: Human rejection gate — reject a pending transaction (→ ABANDONED)."""
    txn = await get_transaction_db(txn_id, current_user.tenant_id, session)
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction '{txn_id}' not found",
        )
    if txn["state"] not in ("NEGOTIATING", "OPEN", "DRAFT"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reject transaction in state '{txn['state']}'.",
        )

    updated = await transition_state(
        transaction_id=txn_id,
        new_state="ABANDONED",
        actor_agent_id=None,
        actor_user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    logger.info(
        "har_transaction_rejected",
        txn_id=txn_id,
        rejector_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )
    return updated
