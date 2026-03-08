"""
Public Agent Registry API routes (API-089 to API-098).

Endpoints:
- POST   /registry/agents                          - Register agent to global registry (API-089)
- GET    /registry/agents                          - Search/list public registry (API-090)
- GET    /registry/agents/{agent_id}               - Get agent card detail (API-091)
- PUT    /registry/agents/{agent_id}               - Update agent card (API-092)
- DELETE /registry/agents/{agent_id}               - Deregister agent (API-093)
- POST   /registry/transactions                    - Initiate A2A transaction (API-094)
- GET    /registry/transactions/{txn_id}           - Get transaction status + audit trail (API-095)
- POST   /registry/transactions/{txn_id}/approve   - Approve transaction (API-096)
- POST   /registry/transactions/{txn_id}/reject    - Reject transaction (API-097)
- GET    /registry/analytics                       - Registry discovery analytics (API-098)
"""
import json
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    CurrentUser,
    get_current_user,
    require_platform_admin,
    require_tenant_admin,
)
from app.core.redis_client import build_redis_key, get_redis
from app.core.session import get_async_session
from app.modules.har.signing import verify_event_signature
from app.modules.har.state_machine import get_transaction, transition_state

logger = structlog.get_logger()

router = APIRouter(prefix="/registry", tags=["registry"])

# ---------------------------------------------------------------------------
# Allowlists — SQL injection prevention
# ---------------------------------------------------------------------------

_VALID_MESSAGE_TYPES = {"RFQ", "CAPABILITY_QUERY"}
_VALID_PERIODS = {"7d", "30d", "90d"}

# Approval window for registry-initiated transactions: 48 hours
_REGISTRY_APPROVAL_WINDOW_HOURS = 48

# Default trust score for new agents with no transaction history
_DEFAULT_TRUST_SCORE = 80


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class RegisterAgentRequest(BaseModel):
    agent_id: str = Field(
        ..., min_length=1, description="Existing agent_cards.id to register"
    )
    a2a_endpoint: str = Field(
        ..., min_length=8, description="HTTPS A2A protocol endpoint"
    )
    transaction_types: List[str] = Field(default_factory=list)
    industries: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    health_check_url: Optional[str] = Field(None)


class UpdateAgentRequest(BaseModel):
    description: Optional[str] = Field(None)
    transaction_types: Optional[List[str]] = Field(None)
    industries: Optional[List[str]] = Field(None)
    languages: Optional[List[str]] = Field(None)
    a2a_endpoint: Optional[str] = Field(None)
    health_check_url: Optional[str] = Field(None)


class InitiateTransactionRequest(BaseModel):
    from_agent_id: str = Field(..., min_length=1)
    to_agent_id: str = Field(..., min_length=1)
    message_type: str = Field(..., description="RFQ or CAPABILITY_QUERY")
    payload: Optional[dict] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# DB helpers (all mockable in unit tests)
# ---------------------------------------------------------------------------


async def get_agent_card_db(agent_id: str, db: AsyncSession) -> Optional[dict]:
    """Fetch a single agent_cards row by id (no tenant filter — public read)."""
    result = await db.execute(
        text(
            "SELECT id, tenant_id, name, description, status, is_public, "
            "a2a_endpoint, transaction_types, industries, languages, "
            "health_check_url, public_key, trust_score, capabilities, "
            "created_at, updated_at "
            "FROM agent_cards WHERE id = :agent_id"
        ),
        {"agent_id": agent_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return _agent_row_to_dict(row)


async def get_agent_card_by_tenant_db(
    agent_id: str, tenant_id: str, db: AsyncSession
) -> Optional[dict]:
    """Fetch a single agent_cards row by id scoped to tenant."""
    result = await db.execute(
        text(
            "SELECT id, tenant_id, name, description, status, is_public, "
            "a2a_endpoint, transaction_types, industries, languages, "
            "health_check_url, public_key, trust_score, capabilities, "
            "created_at, updated_at "
            "FROM agent_cards WHERE id = :agent_id AND tenant_id = :tenant_id"
        ),
        {"agent_id": agent_id, "tenant_id": tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return _agent_row_to_dict(row)


async def register_agent_db(
    agent_id: str,
    tenant_id: str,
    a2a_endpoint: str,
    transaction_types: List[str],
    industries: List[str],
    languages: List[str],
    health_check_url: Optional[str],
    db: AsyncSession,
) -> Optional[dict]:
    """Mark agent as public registry entry by setting is_public=true and registry fields."""
    # Verify agent belongs to this tenant
    existing = await get_agent_card_by_tenant_db(agent_id, tenant_id, db)
    if existing is None:
        return None

    await db.execute(
        text(
            "UPDATE agent_cards SET "
            "is_public = true, "
            "a2a_endpoint = :a2a_endpoint, "
            "transaction_types = CAST(:transaction_types AS text[]), "
            "industries = CAST(:industries AS text[]), "
            "languages = CAST(:languages AS text[]), "
            "health_check_url = :health_check_url, "
            "updated_at = NOW() "
            "WHERE id = :agent_id AND tenant_id = :tenant_id"
        ),
        {
            "a2a_endpoint": a2a_endpoint,
            "transaction_types": transaction_types,
            "industries": industries,
            "languages": languages,
            "health_check_url": health_check_url,
            "agent_id": agent_id,
            "tenant_id": tenant_id,
        },
    )
    await db.commit()
    return await get_agent_card_by_tenant_db(agent_id, tenant_id, db)


async def list_public_agents_db(
    query: Optional[str],
    industry: Optional[str],
    transaction_type: Optional[str],
    language: Optional[str],
    min_trust_score: Optional[int],
    page: int,
    page_size: int,
    db: AsyncSession,
) -> dict:
    """List agent_cards where is_public=true and status='published'."""
    offset = (page - 1) * page_size

    # Build WHERE clause fragments (hardcoded, no f-string user data)
    where_parts = ["is_public = true", "status = 'published'"]
    params: dict = {"limit": page_size, "offset": offset}

    if query:
        where_parts.append("(name ILIKE :query OR description ILIKE :query)")
        # Escape LIKE metacharacters to prevent wildcard injection before wrapping
        escaped_query = (
            query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        params["query"] = f"%{escaped_query}%"

    if industry:
        where_parts.append(":industry = ANY(industries)")
        params["industry"] = industry

    if transaction_type:
        where_parts.append(":transaction_type = ANY(transaction_types)")
        params["transaction_type"] = transaction_type

    if language:
        where_parts.append(":language = ANY(languages)")
        params["language"] = language

    if min_trust_score is not None:
        where_parts.append("trust_score >= :min_trust_score")
        params["min_trust_score"] = min_trust_score

    where_sql = " AND ".join(where_parts)

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM agent_cards WHERE {where_sql}"),
        params,
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        text(
            "SELECT id, tenant_id, name, description, status, is_public, "
            "a2a_endpoint, transaction_types, industries, languages, "
            "health_check_url, public_key, trust_score, capabilities, "
            f"created_at, updated_at FROM agent_cards WHERE {where_sql} "
            "ORDER BY trust_score DESC, created_at DESC "
            "LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    items = [_agent_row_to_dict(row) for row in rows_result.mappings()]
    return {"items": items, "total": total}


async def update_agent_registry_db(
    agent_id: str,
    tenant_id: str,
    updates: UpdateAgentRequest,
    db: AsyncSession,
) -> Optional[dict]:
    """Update registry-visible fields on an agent card. Ownership checked by tenant_id."""
    # Build SET clause from hardcoded fragments only
    set_parts = ["updated_at = NOW()"]
    params: dict = {"agent_id": agent_id, "tenant_id": tenant_id}

    if updates.description is not None:
        set_parts.append("description = :description")
        params["description"] = updates.description

    if updates.a2a_endpoint is not None:
        set_parts.append("a2a_endpoint = :a2a_endpoint")
        params["a2a_endpoint"] = updates.a2a_endpoint

    if updates.health_check_url is not None:
        set_parts.append("health_check_url = :health_check_url")
        params["health_check_url"] = updates.health_check_url

    if updates.transaction_types is not None:
        set_parts.append("transaction_types = CAST(:transaction_types AS text[])")
        params["transaction_types"] = updates.transaction_types

    if updates.industries is not None:
        set_parts.append("industries = CAST(:industries AS text[])")
        params["industries"] = updates.industries

    if updates.languages is not None:
        set_parts.append("languages = CAST(:languages AS text[])")
        params["languages"] = updates.languages

    set_sql = ", ".join(set_parts)
    result = await db.execute(
        text(
            f"UPDATE agent_cards SET {set_sql} "
            "WHERE id = :agent_id AND tenant_id = :tenant_id"
        ),
        params,
    )
    if (result.rowcount or 0) == 0:
        return None
    await db.commit()
    return await get_agent_card_by_tenant_db(agent_id, tenant_id, db)


async def deregister_agent_db(agent_id: str, tenant_id: str, db: AsyncSession) -> bool:
    """Soft-delete: set is_public=false. Returns True if found and updated."""
    result = await db.execute(
        text(
            "UPDATE agent_cards SET is_public = false, updated_at = NOW() "
            "WHERE id = :agent_id AND tenant_id = :tenant_id"
        ),
        {"agent_id": agent_id, "tenant_id": tenant_id},
    )
    if (result.rowcount or 0) == 0:
        await db.rollback()
        return False
    await db.commit()
    return True


async def abandon_open_transactions_db(
    agent_id: str, tenant_id: str, db: AsyncSession
) -> int:
    """Mark OPEN/NEGOTIATING transactions involving this agent as ABANDONED."""
    result = await db.execute(
        text(
            "UPDATE har_transactions SET state = 'ABANDONED', updated_at = NOW() "
            "WHERE (initiator_agent_id = :agent_id OR counterparty_agent_id = :agent_id) "
            "AND tenant_id = :tenant_id "
            "AND state IN ('OPEN', 'NEGOTIATING')"
        ),
        {"agent_id": agent_id, "tenant_id": tenant_id},
    )
    count = result.rowcount or 0
    await db.commit()
    return count


async def create_registry_transaction_db(
    tenant_id: str,
    from_agent_id: str,
    to_agent_id: str,
    message_type: str,
    payload: dict,
    requires_human_approval: bool,
    approval_deadline: Optional[datetime],
    db: AsyncSession,
) -> dict:
    """Insert a har_transactions row for a registry-initiated A2A transaction."""
    # HAR format transaction ID: HAR-{YYYYMMDD}-{6 random digits}
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    suffix = "".join(random.choices(string.digits, k=6))
    txn_id = str(uuid.uuid4())
    har_txn_id = f"HAR-{today}-{suffix}"

    payload_with_har_id = {
        **payload,
        "har_txn_id": har_txn_id,
        "message_type": message_type,
    }
    payload_json = json.dumps(payload_with_har_id)

    message_id = str(uuid.uuid4())

    await db.execute(
        text(
            "INSERT INTO har_transactions "
            "(id, tenant_id, initiator_agent_id, counterparty_agent_id, state, "
            "amount, currency, payload, requires_human_approval, approval_deadline) "
            "VALUES (:id, :tenant_id, :initiator_agent_id, :counterparty_agent_id, 'OPEN', "
            "NULL, NULL, CAST(:payload AS jsonb), :requires_human_approval, :approval_deadline)"
        ),
        {
            "id": txn_id,
            "tenant_id": tenant_id,
            "initiator_agent_id": from_agent_id,
            "counterparty_agent_id": to_agent_id,
            "payload": payload_json,
            "requires_human_approval": requires_human_approval,
            "approval_deadline": approval_deadline,
        },
    )
    await db.commit()

    logger.info(
        "registry_transaction_created",
        txn_id=txn_id,
        har_txn_id=har_txn_id,
        tenant_id=tenant_id,
        from_agent_id=from_agent_id,
        to_agent_id=to_agent_id,
        message_type=message_type,
        requires_human_approval=requires_human_approval,
    )

    return {
        "txn_id": har_txn_id,
        "internal_id": txn_id,
        "status": "OPEN",
        "message_id": message_id,
    }


async def get_registry_transaction_db(txn_id: str, db: AsyncSession) -> Optional[dict]:
    """
    Fetch a transaction by HAR-format ID (stored in payload.har_txn_id) or by UUID.
    Returns full transaction with events list.
    """
    # Try UUID first
    if _is_uuid(txn_id):
        result = await db.execute(
            text(
                "SELECT id, tenant_id, initiator_agent_id, counterparty_agent_id, "
                "state, payload, requires_human_approval, approval_deadline, "
                "chain_head_hash, created_at, updated_at "
                "FROM har_transactions WHERE id = :id"
            ),
            {"id": txn_id},
        )
    else:
        # HAR-YYYYMMDD-NNNNNN format — lookup by payload field
        result = await db.execute(
            text(
                "SELECT id, tenant_id, initiator_agent_id, counterparty_agent_id, "
                "state, payload, requires_human_approval, approval_deadline, "
                "chain_head_hash, created_at, updated_at "
                "FROM har_transactions "
                "WHERE payload->>'har_txn_id' = :har_txn_id"
            ),
            {"har_txn_id": txn_id},
        )

    row = result.mappings().first()
    if row is None:
        return None

    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)

    internal_id = str(row["id"])
    har_txn_id = payload.get("har_txn_id", internal_id)

    # Fetch events
    events_result = await db.execute(
        text(
            "SELECT id, event_type, actor_agent_id, actor_user_id, "
            "payload, signature, nonce, prev_event_hash, event_hash, created_at "
            "FROM har_transaction_events "
            "WHERE transaction_id = :txn_id ORDER BY created_at ASC"
        ),
        {"txn_id": internal_id},
    )
    events = []
    for ev in events_result.mappings():
        ev_payload = ev["payload"]
        if isinstance(ev_payload, str):
            ev_payload = json.loads(ev_payload)
        events.append(
            {
                "id": str(ev["id"]),
                "event_type": ev["event_type"],
                "actor_agent_id": str(ev["actor_agent_id"])
                if ev["actor_agent_id"]
                else None,
                "actor_user_id": str(ev["actor_user_id"])
                if ev["actor_user_id"]
                else None,
                "payload": ev_payload or {},
                "signature": ev["signature"],
                "nonce": ev["nonce"],
                "prev_event_hash": ev["prev_event_hash"],
                "event_hash": ev["event_hash"],
                "created_at": str(ev["created_at"]),
                "verified": False,  # will be populated async below
            }
        )

    return {
        "txn_id": har_txn_id,
        "internal_id": internal_id,
        "tenant_id": str(row["tenant_id"]),
        "from_agent_id": str(row["initiator_agent_id"]),
        "to_agent_id": str(row["counterparty_agent_id"]),
        "status": row["state"],
        "payload": payload,
        "requires_human_approval": row["requires_human_approval"],
        "approval_deadline": str(row["approval_deadline"])
        if row["approval_deadline"]
        else None,
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "events": events,
    }


async def compute_trust_score_db(agent_id: str, db: AsyncSession) -> int:
    """Compute trust score from HAR transaction success ratio."""
    result = await db.execute(
        text(
            "SELECT "
            "COUNT(*) FILTER (WHERE state = 'COMPLETED') AS successful, "
            "COUNT(*) AS total "
            "FROM har_transactions "
            "WHERE initiator_agent_id = :agent_id OR counterparty_agent_id = :agent_id"
        ),
        {"agent_id": agent_id},
    )
    row = result.mappings().first()
    if row is None or (row["total"] or 0) == 0:
        return _DEFAULT_TRUST_SCORE
    total = int(row["total"])
    successful = int(row["successful"] or 0)
    return int(round((successful / total) * 100))


async def get_tenant_name_db(tenant_id: str, db: AsyncSession) -> Optional[str]:
    """Fetch tenant name by id."""
    result = await db.execute(
        text("SELECT name FROM tenants WHERE id = :tenant_id"),
        {"tenant_id": tenant_id},
    )
    row = result.mappings().first()
    return row["name"] if row else None


async def get_transaction_count_db(agent_id: str, db: AsyncSession) -> int:
    """Count total har_transactions for an agent."""
    result = await db.execute(
        text(
            "SELECT COUNT(*) FROM har_transactions "
            "WHERE initiator_agent_id = :agent_id OR counterparty_agent_id = :agent_id"
        ),
        {"agent_id": agent_id},
    )
    return result.scalar() or 0


async def set_approval_db(
    internal_txn_id: str, approver_id: str, db: AsyncSession
) -> None:
    """Set human_approved_at and human_approved_by on a transaction."""
    await db.execute(
        text(
            "UPDATE har_transactions "
            "SET human_approved_at = NOW(), human_approved_by = :approver_id, updated_at = NOW() "
            "WHERE id = :id"
        ),
        {"approver_id": approver_id, "id": internal_txn_id},
    )
    await db.commit()


async def get_analytics_db(
    tenant_id: str,
    period_days: int,
    agent_id_filter: Optional[str],
    db: AsyncSession,
) -> list:
    """Fetch analytics for agents owned by tenant_id."""
    params: dict = {"tenant_id": tenant_id}
    agent_filter_sql = ""
    if agent_id_filter:
        agent_filter_sql = " AND id = :agent_id_filter"
        params["agent_id_filter"] = agent_id_filter

    result = await db.execute(
        text(
            "SELECT id, name FROM agent_cards "
            f"WHERE tenant_id = :tenant_id AND is_public = true{agent_filter_sql} "
            "ORDER BY name ASC"
        ),
        params,
    )
    agents = result.mappings().all()

    period_start = datetime.now(timezone.utc) - timedelta(days=period_days)
    prev_period_start = period_start - timedelta(days=period_days)

    analytics = []
    for agent in agents:
        aid = str(agent["id"])
        aname = agent["name"]

        # Current period transaction count
        curr_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM har_transactions "
                "WHERE (initiator_agent_id = :aid OR counterparty_agent_id = :aid) "
                "AND created_at >= :period_start"
            ),
            {"aid": aid, "period_start": period_start},
        )
        curr_count = curr_result.scalar() or 0

        # Previous period transaction count for trend
        prev_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM har_transactions "
                "WHERE (initiator_agent_id = :aid OR counterparty_agent_id = :aid) "
                "AND created_at >= :prev_start AND created_at < :period_start"
            ),
            {"aid": aid, "prev_start": prev_period_start, "period_start": period_start},
        )
        prev_count = prev_result.scalar() or 0

        trust_score = await compute_trust_score_db(aid, db)

        if prev_count == 0:
            trend = "stable"
        elif curr_count > prev_count:
            trend = "up"
        elif curr_count < prev_count:
            trend = "down"
        else:
            trend = "stable"

        analytics.append(
            {
                "agent_id": aid,
                "name": aname,
                "discovery_count": 0,  # populated from Redis below
                "transaction_count": int(curr_count),
                "trust_score": trust_score,
                "trust_score_trend": trend,
            }
        )

    return analytics


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _validate_https_url(url: str) -> None:
    if not url.startswith("https://"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Endpoint URL must use HTTPS.",
        )


def _agent_row_to_dict(row) -> dict:
    """Convert an agent_cards row to a serializable dict."""
    capabilities = row["capabilities"]
    if isinstance(capabilities, str):
        capabilities = json.loads(capabilities)

    tx_types = row["transaction_types"]
    if tx_types is None:
        tx_types = []
    industries = row["industries"]
    if industries is None:
        industries = []
    languages = row["languages"]
    if languages is None:
        languages = []

    return {
        "agent_id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "is_public": row["is_public"],
        "a2a_endpoint": row["a2a_endpoint"],
        "transaction_types": list(tx_types),
        "industries": list(industries),
        "languages": list(languages),
        "health_check_url": row["health_check_url"],
        "public_key": row["public_key"],
        "trust_score": row["trust_score"] or _DEFAULT_TRUST_SCORE,
        "capabilities": capabilities if isinstance(capabilities, list) else [],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _period_to_days(period: str) -> int:
    mapping = {"7d": 7, "30d": 30, "90d": 90}
    return mapping.get(period, 30)


def _increment_discovery_counter(tenant_id: str, agent_id: str) -> None:
    """Fire-and-forget Redis discovery counter increment. Errors are logged, not raised."""
    try:
        redis = get_redis()
        key = build_redis_key(tenant_id, "registry", "discovery", agent_id)
        import asyncio

        async def _incr():
            try:
                await redis.incr(key)
            except Exception as exc:
                logger.warning(
                    "registry_discovery_counter_failed",
                    agent_id=agent_id,
                    tenant_id=tenant_id,
                    error_type=type(exc).__name__,
                )

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_incr())
        except RuntimeError:
            pass
    except Exception as exc:
        logger.warning(
            "registry_discovery_counter_setup_failed",
            agent_id=agent_id,
            error_type=type(exc).__name__,
        )


async def _get_discovery_count(tenant_id: str, agent_id: str) -> int:
    """Read discovery count from Redis. Returns 0 on any error."""
    try:
        redis = get_redis()
        key = build_redis_key(tenant_id, "registry", "discovery", agent_id)
        val = await redis.get(key)
        return int(val) if val else 0
    except Exception:
        return 0


async def _get_health_status(agent_id: str) -> str:
    """Read health status from Redis. Returns 'healthy' if key absent."""
    try:
        redis = get_redis()
        # Key uses registry-scoped namespace without tenant (global registry health)
        # Use agent_id as both tenant-equivalent and key part
        key = f"mingai:registry:health:{agent_id}"
        val = await redis.get(key)
        return val if val else "healthy"
    except Exception:
        return "healthy"


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post("/agents", status_code=status.HTTP_201_CREATED)
async def register_agent(
    body: RegisterAgentRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-089: Register an existing agent card to the global public registry."""
    _validate_https_url(body.a2a_endpoint)
    if body.health_check_url:
        _validate_https_url(body.health_check_url)

    agent = await register_agent_db(
        agent_id=body.agent_id,
        tenant_id=current_user.tenant_id,
        a2a_endpoint=body.a2a_endpoint,
        transaction_types=body.transaction_types,
        industries=body.industries,
        languages=body.languages,
        health_check_url=body.health_check_url,
        db=session,
    )
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{body.agent_id}' not found or does not belong to your tenant.",
        )

    logger.info(
        "registry_agent_registered",
        agent_id=body.agent_id,
        tenant_id=current_user.tenant_id,
    )

    return {
        "agent_id": agent["agent_id"],
        "name": agent["name"],
        "status": agent["status"],
        "registered_at": agent["updated_at"],
    }


@router.get("/agents")
async def list_registry_agents(
    query: Optional[str] = Query(
        None, description="Text search on name and description"
    ),
    industry: Optional[str] = Query(None),
    transaction_type: Optional[str] = Query(None),
    language: Optional[str] = Query(None),
    min_trust_score: Optional[int] = Query(None, ge=0, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_async_session),
):
    """API-090: Search/list public registry — no auth required."""
    result = await list_public_agents_db(
        query=query,
        industry=industry,
        transaction_type=transaction_type,
        language=language,
        min_trust_score=min_trust_score,
        page=page,
        page_size=page_size,
        db=session,
    )

    # Enrich each agent with live trust score and health status
    for item in result["items"]:
        item["trust_score"] = await compute_trust_score_db(item["agent_id"], session)
        item["health_status"] = await _get_health_status(item["agent_id"])

    return {"items": result["items"], "total": result["total"]}


@router.get("/agents/{agent_id}")
async def get_agent_detail(
    agent_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """API-091: Get full agent card detail — no auth required."""
    agent = await get_agent_card_db(agent_id, session)
    if agent is None or not agent["is_public"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found in public registry.",
        )

    # Enrich with tenant name and live stats
    tenant_name = await get_tenant_name_db(agent["tenant_id"], session)
    transaction_count = await get_transaction_count_db(agent_id, session)
    trust_score = await compute_trust_score_db(agent_id, session)
    health_status = await _get_health_status(agent_id)

    # Increment discovery counter (fire-and-forget)
    _increment_discovery_counter(agent["tenant_id"], agent_id)

    return {
        **agent,
        "tenant_name": tenant_name,
        "transaction_count": transaction_count,
        "trust_score": trust_score,
        "health_status": health_status,
    }


@router.put("/agents/{agent_id}")
async def update_agent_card(
    agent_id: str,
    body: UpdateAgentRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-092: Update agent card — must be owning tenant."""
    if body.a2a_endpoint is not None:
        _validate_https_url(body.a2a_endpoint)
    if body.health_check_url is not None:
        _validate_https_url(body.health_check_url)

    # Verify ownership first
    existing = await get_agent_card_by_tenant_db(
        agent_id, current_user.tenant_id, session
    )
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent not found or you do not own it.",
        )

    updated = await update_agent_registry_db(
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        updates=body,
        db=session,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found.",
        )

    logger.info(
        "registry_agent_updated",
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
    )

    return {
        "agent_id": agent_id,
        "updated_at": updated["updated_at"],
    }


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deregister_agent(
    agent_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-093: Deregister agent — soft-delete, abandon open transactions."""
    # Verify ownership
    existing = await get_agent_card_by_tenant_db(
        agent_id, current_user.tenant_id, session
    )
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent not found or you do not own it.",
        )

    # Mark open/negotiating transactions as ABANDONED
    abandoned_count = await abandon_open_transactions_db(
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    if abandoned_count > 0:
        logger.info(
            "registry_agent_transactions_abandoned",
            agent_id=agent_id,
            tenant_id=current_user.tenant_id,
            abandoned_count=abandoned_count,
        )

    success = await deregister_agent_db(
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
        db=session,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found.",
        )

    logger.info(
        "registry_agent_deregistered",
        agent_id=agent_id,
        tenant_id=current_user.tenant_id,
    )


@router.post("/transactions", status_code=status.HTTP_201_CREATED)
async def initiate_transaction(
    body: InitiateTransactionRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-094: Initiate A2A transaction via registry — from_agent must belong to user's tenant."""
    if body.message_type not in _VALID_MESSAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"message_type must be one of: {sorted(_VALID_MESSAGE_TYPES)}",
        )

    # Verify from_agent belongs to user's tenant (ownership check)
    from_agent = await get_agent_card_by_tenant_db(
        body.from_agent_id, current_user.tenant_id, session
    )
    if from_agent is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="from_agent_id not found or does not belong to your tenant.",
        )

    # Verify to_agent exists in public registry
    to_agent = await get_agent_card_db(body.to_agent_id, session)
    if to_agent is None or not to_agent["is_public"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"to_agent_id '{body.to_agent_id}' not found in public registry.",
        )

    # Determine if approval is required
    payload = body.payload or {}
    amount = payload.get("amount")
    requires_approval = body.message_type == "RFQ" or (
        amount is not None and float(amount) > 5000
    )
    approval_deadline = None
    if requires_approval:
        approval_deadline = datetime.now(timezone.utc) + timedelta(
            hours=_REGISTRY_APPROVAL_WINDOW_HOURS
        )

    txn = await create_registry_transaction_db(
        tenant_id=current_user.tenant_id,
        from_agent_id=body.from_agent_id,
        to_agent_id=body.to_agent_id,
        message_type=body.message_type,
        payload=payload,
        requires_human_approval=requires_approval,
        approval_deadline=approval_deadline,
        db=session,
    )

    return {
        "txn_id": txn["txn_id"],
        "status": txn["status"],
        "message_id": txn["message_id"],
    }


@router.get("/transactions/{txn_id}")
async def get_transaction_status(
    txn_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """API-095: Get transaction status + audit trail — must be participant."""
    txn = await get_registry_transaction_db(txn_id, session)
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction '{txn_id}' not found.",
        )

    # Participation check: from_agent or to_agent must belong to user's tenant
    from_agent = await get_agent_card_db(txn["from_agent_id"], session)
    to_agent = await get_agent_card_db(txn["to_agent_id"], session)

    user_is_participant = (
        from_agent and from_agent["tenant_id"] == current_user.tenant_id
    ) or (to_agent and to_agent["tenant_id"] == current_user.tenant_id)
    if not user_is_participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant in this transaction.",
        )

    # Verify signatures for each event
    for event in txn["events"]:
        if event.get("signature"):
            event["verified"] = await verify_event_signature(event["id"], session)
        else:
            event["verified"] = False

    return {
        "txn_id": txn["txn_id"],
        "status": txn["status"],
        "from_agent": from_agent,
        "to_agent": to_agent,
        "events": txn["events"],
        "approval_required": txn["requires_human_approval"],
        "approval_deadline": txn["approval_deadline"],
    }


@router.post("/transactions/{txn_id}/approve")
async def approve_transaction(
    txn_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-096: Approve a pending registry transaction — tenant_admin of initiating tenant."""
    txn = await get_registry_transaction_db(txn_id, session)
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction '{txn_id}' not found.",
        )

    if txn["status"] not in ("OPEN", "NEGOTIATING"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve transaction in state '{txn['status']}'.",
        )

    if not txn["requires_human_approval"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction does not require human approval.",
        )

    # Check deadline
    if txn["approval_deadline"]:
        deadline_str = txn["approval_deadline"]
        try:
            deadline = datetime.fromisoformat(
                deadline_str.replace("+00:00", "")
            ).replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > deadline:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Approval deadline has passed.",
                )
        except (ValueError, AttributeError):
            pass

    # Verify caller is admin of initiating tenant
    from_agent = await get_agent_card_db(txn["from_agent_id"], session)
    if from_agent is None or from_agent["tenant_id"] != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be admin of the initiating agent's tenant to approve.",
        )

    # Set approval fields
    await set_approval_db(txn["internal_id"], current_user.id, session)

    # State machine: OPEN -> NEGOTIATING -> COMMITTED
    # If still in OPEN, must first move to NEGOTIATING before COMMITTED
    current_status = txn["status"]
    if current_status == "OPEN":
        await transition_state(
            transaction_id=txn["internal_id"],
            new_state="NEGOTIATING",
            actor_agent_id=None,
            actor_user_id=current_user.id,
            tenant_id=txn["tenant_id"],
            db=session,
        )

    # Transition to COMMITTED
    updated = await transition_state(
        transaction_id=txn["internal_id"],
        new_state="COMMITTED",
        actor_agent_id=None,
        actor_user_id=current_user.id,
        tenant_id=txn["tenant_id"],
        db=session,
    )

    logger.info(
        "registry_transaction_approved",
        txn_id=txn_id,
        approver_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )

    return {
        "txn_id": txn["txn_id"],
        "status": updated["state"],
        "approved_at": updated["human_approved_at"]
        or datetime.now(timezone.utc).isoformat(),
    }


@router.post("/transactions/{txn_id}/reject")
async def reject_transaction(
    txn_id: str,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-097: Reject a pending registry transaction — tenant_admin of initiating tenant."""
    txn = await get_registry_transaction_db(txn_id, session)
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction '{txn_id}' not found.",
        )

    if txn["status"] not in ("OPEN", "NEGOTIATING", "DRAFT"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reject transaction in state '{txn['status']}'.",
        )

    # Verify caller is admin of initiating tenant
    from_agent = await get_agent_card_db(txn["from_agent_id"], session)
    if from_agent is None or from_agent["tenant_id"] != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be admin of the initiating agent's tenant to reject.",
        )

    updated = await transition_state(
        transaction_id=txn["internal_id"],
        new_state="ABANDONED",
        actor_agent_id=None,
        actor_user_id=current_user.id,
        tenant_id=txn["tenant_id"],
        db=session,
    )

    logger.info(
        "registry_transaction_rejected",
        txn_id=txn_id,
        rejector_id=current_user.id,
        tenant_id=current_user.tenant_id,
    )

    return {
        "txn_id": txn["txn_id"],
        "status": updated["state"],
    }


@router.get("/analytics")
async def get_registry_analytics(
    period: str = Query("30d", description="7d, 30d, or 90d"),
    agent_id: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """API-098: Registry discovery analytics for current tenant's agents."""
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"period must be one of: {sorted(_VALID_PERIODS)}",
        )

    period_days = _period_to_days(period)
    agents = await get_analytics_db(
        tenant_id=current_user.tenant_id,
        period_days=period_days,
        agent_id_filter=agent_id,
        db=session,
    )

    # Enrich with Redis discovery counts
    for item in agents:
        item["discovery_count"] = await _get_discovery_count(
            current_user.tenant_id, item["agent_id"]
        )

    return {"agents": agents}


# ---------------------------------------------------------------------------
# Dispute allowlists (GAP-036 / API-124, API-125)
# ---------------------------------------------------------------------------

_VALID_DISPUTE_CATEGORIES = {"quality", "delivery", "billing", "terms", "other"}
_VALID_DISPUTE_RESOLUTIONS = {"buyer_favor", "seller_favor", "mutual", "void"}

# States that allow a new dispute to be filed
_DISPUTABLE_STATES = {"OPEN", "NEGOTIATING", "COMMITTED", "EXECUTING"}

# Terminal COMPLETED transactions older than this cannot be disputed
_DISPUTE_COMPLETED_WINDOW_DAYS = 30


# ---------------------------------------------------------------------------
# Dispute request/response schemas (GAP-036)
# ---------------------------------------------------------------------------


class FileDisputeRequest(BaseModel):
    reason: str = Field(..., min_length=10, description="Dispute reason (min 10 chars)")
    category: str = Field(..., description="quality|delivery|billing|terms|other")
    evidence_urls: List[str] = Field(default_factory=list)
    desired_resolution: str = Field(
        ..., min_length=10, description="Desired outcome (min 10 chars)"
    )

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        if v not in _VALID_DISPUTE_CATEGORIES:
            raise ValueError(
                f"category must be one of: {sorted(_VALID_DISPUTE_CATEGORIES)}"
            )
        return v


class ResolveDisputeRequest(BaseModel):
    resolution: str = Field(..., description="buyer_favor|seller_favor|mutual|void")
    resolution_notes: str = Field(
        ..., min_length=10, description="Resolution explanation (min 10 chars)"
    )
    action_taken: str = Field(..., min_length=1, description="Action taken description")

    @field_validator("resolution")
    @classmethod
    def validate_resolution(cls, v: str) -> str:
        if v not in _VALID_DISPUTE_RESOLUTIONS:
            raise ValueError(
                f"resolution must be one of: {sorted(_VALID_DISPUTE_RESOLUTIONS)}"
            )
        return v


# ---------------------------------------------------------------------------
# Dispute DB helpers (mockable in unit tests)
# ---------------------------------------------------------------------------


async def create_dispute_db(
    transaction_id: str,
    filed_by_tenant_id: str,
    reason: str,
    category: str,
    evidence_urls: List[str],
    desired_resolution: str,
    db: AsyncSession,
) -> dict:
    """Insert a new dispute row and return the created dispute as a dict."""
    dispute_id = str(uuid.uuid4())
    evidence_json = json.dumps(evidence_urls)

    await db.execute(
        text(
            "INSERT INTO disputes "
            "(id, transaction_id, filed_by_tenant_id, reason, category, "
            "evidence_urls, desired_resolution, status) "
            "VALUES (:id, :transaction_id, :filed_by_tenant_id, :reason, :category, "
            "CAST(:evidence_urls AS jsonb), :desired_resolution, 'open')"
        ),
        {
            "id": dispute_id,
            "transaction_id": transaction_id,
            "filed_by_tenant_id": filed_by_tenant_id,
            "reason": reason,
            "category": category,
            "evidence_urls": evidence_json,
            "desired_resolution": desired_resolution,
        },
    )
    await db.commit()

    # Re-fetch to return canonical row
    result = await db.execute(
        text(
            "SELECT id, transaction_id, status, filed_at FROM disputes WHERE id = :id"
        ),
        {"id": dispute_id},
    )
    row = result.mappings().first()
    return {
        "dispute_id": str(row["id"]),
        "transaction_id": str(row["transaction_id"]),
        "status": row["status"],
        "filed_at": row["filed_at"].isoformat() if row["filed_at"] else None,
    }


async def get_open_dispute_db(transaction_id: str, db: AsyncSession) -> Optional[dict]:
    """Fetch the open dispute for a transaction. Returns None if not found."""
    result = await db.execute(
        text(
            "SELECT id, transaction_id, filed_by_tenant_id, status, filed_at "
            "FROM disputes WHERE transaction_id = :transaction_id AND status = 'open' "
            "ORDER BY filed_at DESC LIMIT 1"
        ),
        {"transaction_id": transaction_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return {
        "dispute_id": str(row["id"]),
        "transaction_id": str(row["transaction_id"]),
        "filed_by_tenant_id": str(row["filed_by_tenant_id"]),
        "status": row["status"],
        "filed_at": row["filed_at"].isoformat() if row["filed_at"] else None,
    }


async def resolve_dispute_db(
    dispute_id: str,
    resolved_by: str,
    resolution: str,
    resolution_notes: str,
    db: AsyncSession,
) -> dict:
    """Update dispute to resolved status. Returns updated dispute dict."""
    await db.execute(
        text(
            "UPDATE disputes SET "
            "status = 'resolved', "
            "resolved_by = :resolved_by, "
            "resolution = :resolution, "
            "resolution_notes = :resolution_notes, "
            "resolved_at = NOW() "
            "WHERE id = :dispute_id AND status = 'open'"
        ),
        {
            "dispute_id": dispute_id,
            "resolved_by": resolved_by,
            "resolution": resolution,
            "resolution_notes": resolution_notes,
        },
    )
    await db.commit()

    result = await db.execute(
        text(
            "SELECT id, resolution, resolved_at, resolved_by FROM disputes WHERE id = :id"
        ),
        {"id": dispute_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dispute disappeared after update — data integrity error",
        )
    return {
        "dispute_id": str(row["id"]),
        "resolution": row["resolution"],
        "resolved_at": row["resolved_at"].isoformat() if row["resolved_at"] else None,
        "resolved_by": str(row["resolved_by"]) if row["resolved_by"] else None,
    }


async def log_dispute_audit_event_db(
    transaction_id: str,
    tenant_id: str,
    event_type: str,
    actor_user_id: str,
    payload: dict,
    db: AsyncSession,
) -> None:
    """
    Insert an unsigned audit event in har_transaction_events for dispute actions.
    Mirrors the unsigned-event path in state_machine.record_transition_event().
    """
    import hashlib as _hashlib

    event_id = str(uuid.uuid4())
    # Get chain head for linking
    head_result = await db.execute(
        text("SELECT chain_head_hash FROM har_transactions " "WHERE id = :id"),
        {"id": transaction_id},
    )
    head_row = head_result.mappings().first()
    prev_event_hash = head_row["chain_head_hash"] if head_row else None

    hash_input = json.dumps(
        {
            "event_id": event_id,
            "event_type": event_type,
            "payload": payload,
            "prev_event_hash": prev_event_hash,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        sort_keys=True,
    )
    event_hash = _hashlib.sha256(hash_input.encode()).hexdigest()

    await db.execute(
        text(
            "INSERT INTO har_transaction_events "
            "(id, tenant_id, transaction_id, event_type, actor_agent_id, actor_user_id, "
            "payload, signature, nonce, prev_event_hash, event_hash) "
            "VALUES (:id, :tenant_id, :transaction_id, :event_type, "
            "NULL, :actor_user_id, "
            "CAST(:payload AS jsonb), NULL, NULL, :prev_event_hash, :event_hash)"
        ),
        {
            "id": event_id,
            "tenant_id": tenant_id,
            "transaction_id": transaction_id,
            "event_type": event_type,
            "actor_user_id": actor_user_id,
            "payload": json.dumps(payload),
            "prev_event_hash": prev_event_hash,
            "event_hash": event_hash,
        },
    )
    await db.execute(
        text("UPDATE har_transactions SET chain_head_hash = :hash WHERE id = :id"),
        {"hash": event_hash, "id": transaction_id},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# API-124: POST /registry/transactions/{transaction_id}/dispute
# ---------------------------------------------------------------------------


@router.post(
    "/transactions/{transaction_id}/dispute",
    status_code=status.HTTP_201_CREATED,
)
async def file_dispute(
    transaction_id: str,
    body: FileDisputeRequest,
    current_user: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-124 (GAP-036): File a dispute on a registry transaction.

    Auth: tenant_admin of either the from or to agent's tenant.
    The transaction must be in OPEN, NEGOTIATING, COMMITTED, or EXECUTING state.
    COMPLETED transactions older than 30 days cannot be disputed.
    Already-DISPUTED or RESOLVED transactions cannot be disputed again.
    """
    # Fetch transaction (no tenant filter — dispute filer may be counter-party)
    txn = await get_registry_transaction_db(transaction_id, session)
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction '{transaction_id}' not found.",
        )

    internal_id = txn["internal_id"]
    current_state = txn["status"]

    # Cannot dispute already-DISPUTED or RESOLVED transactions
    if current_state in ("DISPUTED", "RESOLVED"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transaction is already in state '{current_state}' and cannot be disputed.",
        )

    # COMPLETED transactions: only disputable within 30-day window
    if current_state == "COMPLETED":
        updated_at_str = txn.get("updated_at", "")
        try:
            updated_at = datetime.fromisoformat(
                updated_at_str.replace("+00:00", "")
            ).replace(tzinfo=timezone.utc)
            window = timedelta(days=_DISPUTE_COMPLETED_WINDOW_DAYS)
            if datetime.now(timezone.utc) - updated_at > window:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cannot dispute a COMPLETED transaction older than "
                        f"{_DISPUTE_COMPLETED_WINDOW_DAYS} days."
                    ),
                )
        except HTTPException:
            raise
        except (ValueError, AttributeError):
            # If we cannot parse the date, block the dispute to be safe
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot determine transaction completion date.",
            )
    elif current_state not in _DISPUTABLE_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Transaction in state '{current_state}' cannot be disputed. "
                f"Disputable states: {sorted(_DISPUTABLE_STATES)}"
            ),
        )

    # Verify requester's tenant is a party to the transaction
    from_agent = await get_agent_card_db(txn["from_agent_id"], session)
    to_agent = await get_agent_card_db(txn["to_agent_id"], session)

    requester_is_party = (
        from_agent and from_agent["tenant_id"] == current_user.tenant_id
    ) or (to_agent and to_agent["tenant_id"] == current_user.tenant_id)

    if not requester_is_party:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a party to this transaction.",
        )

    # Create dispute record
    dispute = await create_dispute_db(
        transaction_id=internal_id,
        filed_by_tenant_id=current_user.tenant_id,
        reason=body.reason,
        category=body.category,
        evidence_urls=body.evidence_urls,
        desired_resolution=body.desired_resolution,
        db=session,
    )

    # Transition transaction state to DISPUTED
    await transition_state(
        transaction_id=internal_id,
        new_state="DISPUTED",
        actor_agent_id=None,
        actor_user_id=current_user.id,
        tenant_id=txn["tenant_id"],
        db=session,
    )

    # Log dispute-filed audit event
    await log_dispute_audit_event_db(
        transaction_id=internal_id,
        tenant_id=txn["tenant_id"],
        event_type="dispute_filed",
        actor_user_id=current_user.id,
        payload={
            "dispute_id": dispute["dispute_id"],
            "category": body.category,
            "filed_by_tenant_id": current_user.tenant_id,
        },
        db=session,
    )

    logger.info(
        "registry_dispute_filed",
        transaction_id=transaction_id,
        dispute_id=dispute["dispute_id"],
        filed_by_tenant_id=current_user.tenant_id,
        category=body.category,
    )

    return dispute


# ---------------------------------------------------------------------------
# API-125: POST /registry/transactions/{transaction_id}/dispute/resolve
# ---------------------------------------------------------------------------


@router.post("/transactions/{transaction_id}/dispute/resolve")
async def resolve_dispute(
    transaction_id: str,
    body: ResolveDisputeRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """
    API-125 (GAP-036): Resolve a transaction dispute.

    Auth: platform_admin only.
    Transaction must be in DISPUTED state with an open dispute record.
    """
    # Fetch transaction (no tenant filter — platform admin has global access)
    txn = await get_registry_transaction_db(transaction_id, session)
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction '{transaction_id}' not found.",
        )

    if txn["status"] != "DISPUTED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Transaction is in state '{txn['status']}', not DISPUTED. "
                "Only DISPUTED transactions can be resolved."
            ),
        )

    internal_id = txn["internal_id"]

    # Verify open dispute record exists
    dispute = await get_open_dispute_db(internal_id, session)
    if dispute is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No open dispute found for this transaction.",
        )

    # Resolve the dispute record
    resolved = await resolve_dispute_db(
        dispute_id=dispute["dispute_id"],
        resolved_by=current_user.id,
        resolution=body.resolution,
        resolution_notes=body.resolution_notes,
        db=session,
    )

    # Transition transaction state to RESOLVED
    await transition_state(
        transaction_id=internal_id,
        new_state="RESOLVED",
        actor_agent_id=None,
        actor_user_id=current_user.id,
        tenant_id=txn["tenant_id"],
        db=session,
    )

    # Log dispute-resolved audit event
    await log_dispute_audit_event_db(
        transaction_id=internal_id,
        tenant_id=txn["tenant_id"],
        event_type="dispute_resolved",
        actor_user_id=current_user.id,
        payload={
            "dispute_id": dispute["dispute_id"],
            "resolution": body.resolution,
            "action_taken": body.action_taken,
            "resolved_by": current_user.id,
        },
        db=session,
    )

    logger.info(
        "registry_dispute_resolved",
        transaction_id=transaction_id,
        dispute_id=dispute["dispute_id"],
        resolution=body.resolution,
        resolved_by=current_user.id,
    )

    return resolved
