"""
HAR Agent Trust Score computation (AI-046, AI-047).

Formula (0-100 scale):
  kyb_pts       = {0: 0, 1: 15, 2: 30, 3: 40}[kyb_level]
  txn_volume    = min(30, completed_transaction_count)   # 1pt per txn, cap 30
  dispute_pen   = min(30, disputed_transaction_count * 10)
  trust_score   = max(0, min(100, kyb_pts + txn_volume - dispute_pen))

After computing, persists updated trust_score to agent_cards table.
"""
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# KYB level → base points
_KYB_POINTS = {0: 0, 1: 15, 2: 30, 3: 40}
_MAX_KYB_LEVEL = 3

# Transaction volume cap (points)
_TXN_VOLUME_CAP = 30

# Dispute penalty per disputed transaction
_DISPUTE_PENALTY_PER = 10
_DISPUTE_PENALTY_CAP = 30


async def compute_trust_score(
    agent_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> int:
    """
    Compute and persist trust score for an agent.

    Makes 4 DB queries:
      1. SELECT kyb_level FROM agent_cards
      2. SELECT COUNT(*) COMPLETED transactions (initiator or counterparty)
      3. SELECT COUNT(*) DISPUTED transactions (initiator or counterparty)
      4. UPDATE agent_cards SET trust_score = <computed>

    Returns the computed trust_score integer (0-100).
    """
    # 1. KYB level — scoped to tenant for defence-in-depth
    kyb_result = await db.execute(
        text(
            "SELECT kyb_level FROM agent_cards "
            "WHERE id = :agent_id AND tenant_id = :tenant_id"
        ),
        {"agent_id": agent_id, "tenant_id": tenant_id},
    )
    kyb_level = kyb_result.scalar() or 0
    kyb_level = min(int(kyb_level), _MAX_KYB_LEVEL)
    kyb_pts = _KYB_POINTS.get(kyb_level, 0)

    # 2. Completed transaction volume — scoped to tenant
    completed_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM har_transactions "
            "WHERE tenant_id = :tenant_id AND state = 'COMPLETED' "
            "AND (initiator_agent_id = :agent_id OR counterparty_agent_id = :agent_id)"
        ),
        {"agent_id": agent_id, "tenant_id": tenant_id},
    )
    completed_count = completed_result.scalar() or 0
    txn_volume_score = min(_TXN_VOLUME_CAP, int(completed_count))

    # 3. Disputed transaction count — scoped to tenant
    disputed_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM har_transactions "
            "WHERE tenant_id = :tenant_id AND state IN ('DISPUTED', 'RESOLVED') "
            "AND (initiator_agent_id = :agent_id OR counterparty_agent_id = :agent_id)"
        ),
        {"agent_id": agent_id, "tenant_id": tenant_id},
    )
    disputed_count = disputed_result.scalar() or 0
    dispute_penalty = min(
        _DISPUTE_PENALTY_CAP, int(disputed_count) * _DISPUTE_PENALTY_PER
    )

    # Formula
    raw_score = kyb_pts + txn_volume_score - dispute_penalty
    trust_score = max(0, min(100, raw_score))

    # 4. Persist to agent_cards — scoped to tenant
    await db.execute(
        text(
            "UPDATE agent_cards "
            "SET trust_score = :trust_score, updated_at = NOW() "
            "WHERE id = :agent_id AND tenant_id = :tenant_id"
        ),
        {"trust_score": trust_score, "agent_id": agent_id, "tenant_id": tenant_id},
    )
    # Note: caller is responsible for commit — we don't commit here to allow batching

    logger.info(
        "agent_trust_score_computed",
        agent_id=agent_id,
        tenant_id=tenant_id,
        kyb_level=kyb_level,
        kyb_pts=kyb_pts,
        txn_volume_score=txn_volume_score,
        dispute_penalty=dispute_penalty,
        trust_score=trust_score,
    )

    return trust_score
