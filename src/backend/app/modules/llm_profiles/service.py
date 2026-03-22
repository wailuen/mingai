"""
LLMProfileService — business logic for LLM profile management (TODO-29).

Two-track architecture:
- Platform profiles: owner_tenant_id IS NULL, managed by platform admins
- BYOLLM profiles: owner_tenant_id = tenant_id, managed by tenant admins (enterprise only)

Slots: chat, intent, vision, agent (embedding is NOT part of profiles)

Traffic split format (per slot):
    [{"library_id": "<uuid>", "weight": 70}, {"library_id": "<uuid>", "weight": 30}]
    Weights must sum to 100. Empty list means use the primary slot library_id with weight=100.

Plan tier gating:
    platform profiles carry plan_tiers: list[str] — only tenants on a matching plan see them.
    Empty list = visible to all plans.

Audit log:
    Every create/update/deprecate action inserts a row into llm_profile_audit_log.
    Field diffs are stored as {"before": {...}, "after": {...}}.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Slot definitions
# ---------------------------------------------------------------------------

VALID_SLOTS = frozenset({"chat", "intent", "vision", "agent"})
VALID_PLAN_TIERS = frozenset({"starter", "professional", "enterprise"})
VALID_STATUSES = frozenset({"active", "deprecated"})

# ---------------------------------------------------------------------------
# Error classes
# ---------------------------------------------------------------------------


class LLMProfileError(Exception):
    """Base error for LLM profile operations."""


class LLMProfileNotFoundError(LLMProfileError):
    """Raised when a profile does not exist or is not visible to the caller."""


class LLMProfilePermissionError(LLMProfileError):
    """Raised when the caller is not allowed to perform the action."""


class LLMProfileValidationError(LLMProfileError):
    """Raised when input data fails validation."""


class LLMProfileConflictError(LLMProfileError):
    """Raised when a profile with the same name already exists for the owner."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_traffic_split(split: list[dict], slot: str) -> None:
    """Validate traffic split weights for a slot.

    Rules:
    - Each entry must have library_id (str) and weight (int 1-99)
    - Total weight of all entries must equal 100 if len >= 2
    - len == 0 is valid (use primary library_id)
    - len == 1 with weight == 100 is valid
    """
    if not split:
        return
    total = 0
    for entry in split:
        if "library_id" not in entry or "weight" not in entry:
            raise LLMProfileValidationError(
                f"Each {slot}_traffic_split entry must have 'library_id' and 'weight'"
            )
        w = entry["weight"]
        # For multi-entry splits: each weight must be 1-99 (so total can reach 100 with ≥2 entries)
        # For single-entry splits: weight must be exactly 100
        if not isinstance(w, int):
            raise LLMProfileValidationError(
                f"{slot}_traffic_split weights must be integers between 1 and 99"
            )
        if len(split) == 1 and w != 100:
            raise LLMProfileValidationError(
                f"{slot}_traffic_split with a single entry must have weight=100"
            )
        if len(split) > 1 and (w < 1 or w > 99):
            raise LLMProfileValidationError(
                f"{slot}_traffic_split weights must be integers between 1 and 99"
            )
        total += w
    if len(split) > 1 and total != 100:
        raise LLMProfileValidationError(
            f"{slot}_traffic_split weights must sum to 100 (got {total})"
        )


def _build_slot_fields(data: dict) -> dict:
    """Extract and validate slot-related fields from request data."""
    fields: dict[str, Any] = {}
    for slot in VALID_SLOTS:
        lib_key = f"{slot}_library_id"
        params_key = f"{slot}_params"
        split_key = f"{slot}_traffic_split"

        if lib_key in data:
            fields[lib_key] = data[lib_key]
        if params_key in data:
            if not isinstance(data[params_key], dict):
                raise LLMProfileValidationError(
                    f"{params_key} must be a JSON object"
                )
            fields[params_key] = data[params_key]
        if split_key in data:
            split = data[split_key]
            if not isinstance(split, list):
                raise LLMProfileValidationError(
                    f"{split_key} must be a JSON array"
                )
            _validate_traffic_split(split, slot)
            fields[split_key] = split
    return fields


async def _verify_library_id(
    library_id: str, tenant_id: Optional[str], db: AsyncSession
) -> None:
    """Verify that a library_id exists and is published.

    Platform callers pass tenant_id=None (skip RLS scope).
    Tenant callers pass their tenant_id for logging only.
    """
    result = await db.execute(
        text("SELECT status FROM llm_library WHERE id = :id"),
        {"id": library_id},
    )
    row = result.fetchone()
    if row is None:
        raise LLMProfileValidationError(
            f"llm_library entry {library_id} not found"
        )
    if row[0] not in ("published", "Published"):
        raise LLMProfileValidationError(
            f"llm_library entry {library_id} is not published (status: {row[0]})"
        )


async def _audit(
    actor_id: str,
    tenant_id: Optional[str],
    entity_type: str,
    entity_id: str,
    action: str,
    diff: dict,
    db: AsyncSession,
) -> None:
    """Insert a row into llm_profile_audit_log."""
    await db.execute(
        text(
            "INSERT INTO llm_profile_audit_log "
            "(id, entity_type, entity_id, actor_id, tenant_id, action, diff, logged_at) "
            "VALUES (:id, :etype, :eid, :actor, :tid, :action, CAST(:diff AS jsonb), NOW())"
        ),
        {
            "id": str(uuid.uuid4()),
            "etype": entity_type,
            "eid": entity_id,
            "actor": actor_id,
            "tid": tenant_id,
            "action": action,
            "diff": json.dumps(diff),
        },
    )


# ---------------------------------------------------------------------------
# LLMProfileService
# ---------------------------------------------------------------------------


class LLMProfileService:
    """Business logic for LLM profile CRUD and lifecycle management.

    All methods accept an AsyncSession that is already scoped (RLS set) by
    the route handler. This service does NOT commit — callers commit after
    all writes in a single transaction.
    """

    # ------------------------------------------------------------------
    # Platform profile operations (owner_tenant_id IS NULL)
    # ------------------------------------------------------------------

    async def create_platform_profile(
        self,
        *,
        name: str,
        description: Optional[str],
        plan_tiers: list[str],
        slot_data: dict,
        is_platform_default: bool,
        actor_id: str,
        db: AsyncSession,
    ) -> dict:
        """Create a new platform-owned LLM profile.

        Args:
            name: Unique profile name (unique across platform profiles).
            description: Optional description.
            plan_tiers: List of plan tiers that can use this profile.
            slot_data: Dict with optional keys: chat_library_id, intent_library_id,
                       vision_library_id, agent_library_id, and corresponding _params
                       and _traffic_split keys.
            is_platform_default: If True, this becomes the fallback for tenants without
                                  an explicit profile assignment. Only one may exist.
            actor_id: UUID of the platform admin performing the action.
            db: Async DB session (RLS already scoped to platform).

        Returns:
            Dict with the created profile's id and all fields.

        Raises:
            LLMProfileConflictError: If a platform profile with this name already exists.
            LLMProfileValidationError: On slot or traffic split validation failure.
        """
        # Validate plan tiers
        for tier in plan_tiers:
            if tier not in VALID_PLAN_TIERS:
                raise LLMProfileValidationError(
                    f"Invalid plan tier '{tier}'. Must be one of {sorted(VALID_PLAN_TIERS)}"
                )

        # Validate slot fields
        slot_fields = _build_slot_fields(slot_data)

        # Verify all library IDs exist and are published
        for slot in VALID_SLOTS:
            lib_id = slot_fields.get(f"{slot}_library_id")
            if lib_id:
                await _verify_library_id(lib_id, None, db)

        # Check name uniqueness (platform profiles: owner_tenant_id IS NULL)
        exists = await db.execute(
            text(
                "SELECT id FROM llm_profiles WHERE name = :name AND owner_tenant_id IS NULL"
            ),
            {"name": name},
        )
        if exists.fetchone():
            raise LLMProfileConflictError(
                f"A platform profile named '{name}' already exists"
            )

        profile_id = str(uuid.uuid4())

        # Atomically clear any existing default before setting the new one.
        # This prevents two profiles from having is_platform_default = true simultaneously.
        if is_platform_default:
            await db.execute(
                text(
                    "UPDATE llm_profiles "
                    "SET is_platform_default = false "
                    "WHERE is_platform_default = true AND owner_tenant_id IS NULL"
                )
            )

        await db.execute(
            text(
                "INSERT INTO llm_profiles "
                "(id, name, description, status, "
                "chat_library_id, intent_library_id, vision_library_id, agent_library_id, "
                "chat_params, intent_params, vision_params, agent_params, "
                "chat_traffic_split, intent_traffic_split, vision_traffic_split, agent_traffic_split, "
                "is_platform_default, plan_tiers, owner_tenant_id, created_by, created_at, updated_at) "
                "VALUES "
                "(:id, :name, :desc, 'active', "
                ":chat_lib, :intent_lib, :vision_lib, :agent_lib, "
                "CAST(:chat_p AS jsonb), CAST(:intent_p AS jsonb), "
                "CAST(:vision_p AS jsonb), CAST(:agent_p AS jsonb), "
                "CAST(:chat_s AS jsonb), CAST(:intent_s AS jsonb), "
                "CAST(:vision_s AS jsonb), CAST(:agent_s AS jsonb), "
                ":is_default, :plan_tiers, NULL, :actor, NOW(), NOW())"
            ),
            {
                "id": profile_id,
                "name": name,
                "desc": description,
                "chat_lib": slot_fields.get("chat_library_id"),
                "intent_lib": slot_fields.get("intent_library_id"),
                "vision_lib": slot_fields.get("vision_library_id"),
                "agent_lib": slot_fields.get("agent_library_id"),
                "chat_p": json.dumps(slot_fields.get("chat_params", {})),
                "intent_p": json.dumps(slot_fields.get("intent_params", {})),
                "vision_p": json.dumps(slot_fields.get("vision_params", {})),
                "agent_p": json.dumps(slot_fields.get("agent_params", {})),
                "chat_s": json.dumps(slot_fields.get("chat_traffic_split", [])),
                "intent_s": json.dumps(slot_fields.get("intent_traffic_split", [])),
                "vision_s": json.dumps(slot_fields.get("vision_traffic_split", [])),
                "agent_s": json.dumps(slot_fields.get("agent_traffic_split", [])),
                "is_default": is_platform_default,
                "plan_tiers": plan_tiers,
                "actor": actor_id,
            },
        )

        await _audit(
            actor_id=actor_id,
            tenant_id=None,
            entity_type="llm_profile",
            entity_id=profile_id,
            action="create",
            diff={"after": {"name": name, "plan_tiers": plan_tiers, "is_platform_default": is_platform_default}},
            db=db,
        )

        logger.info(
            "llm_profile_platform_created",
            profile_id=profile_id,
            actor_id=actor_id,
            is_platform_default=is_platform_default,
        )

        return await self._fetch_profile(profile_id, db)

    async def update_platform_profile(
        self,
        profile_id: str,
        *,
        updates: dict,
        actor_id: str,
        db: AsyncSession,
    ) -> dict:
        """Update a platform profile's metadata and/or slot assignments.

        Only the fields present in ``updates`` are changed; others are left
        untouched (sparse update).

        Raises:
            LLMProfileNotFoundError: Profile not found or not platform-owned.
            LLMProfileValidationError: On invalid field values.
        """
        existing = await self._fetch_platform_profile(profile_id, db)

        _UPDATABLE = frozenset({
            "name", "description", "plan_tiers", "is_platform_default", "status",
            "chat_library_id", "intent_library_id", "vision_library_id", "agent_library_id",
            "chat_params", "intent_params", "vision_params", "agent_params",
            "chat_traffic_split", "intent_traffic_split", "vision_traffic_split", "agent_traffic_split",
        })

        before_snapshot: dict = {}
        set_clauses: list[str] = []
        params: dict = {"id": profile_id}

        for key, value in updates.items():
            if key not in _UPDATABLE:
                raise LLMProfileValidationError(f"Field '{key}' cannot be updated")
            before_snapshot[key] = existing.get(key)

        # Validate status if present
        if "status" in updates:
            if updates["status"] not in ("active", "deprecated"):
                raise LLMProfileValidationError(
                    f"Invalid status '{updates['status']}'. Must be 'active' or 'deprecated'"
                )

        # Validate plan tiers if present
        if "plan_tiers" in updates:
            for tier in updates["plan_tiers"]:
                if tier not in VALID_PLAN_TIERS:
                    raise LLMProfileValidationError(
                        f"Invalid plan tier '{tier}'. Must be one of {sorted(VALID_PLAN_TIERS)}"
                    )

        # Validate slot fields
        slot_updates = _build_slot_fields(updates)
        for slot in VALID_SLOTS:
            lib_id = slot_updates.get(f"{slot}_library_id")
            if lib_id:
                await _verify_library_id(lib_id, None, db)

        # Build SET clause (allowlisted column names only)
        _JSONB_COLS = {
            "chat_params", "intent_params", "vision_params", "agent_params",
            "chat_traffic_split", "intent_traffic_split", "vision_traffic_split", "agent_traffic_split",
        }
        _ARRAY_COLS = {"plan_tiers"}
        _SCALAR_COLS = {
            "name", "description", "is_platform_default", "status",
            "chat_library_id", "intent_library_id", "vision_library_id", "agent_library_id",
        }

        for col in _SCALAR_COLS:
            if col in updates:
                set_clauses.append(f"{col} = :{col}")
                params[col] = updates[col]

        for col in _ARRAY_COLS:
            if col in updates:
                set_clauses.append(f"{col} = :{col}")
                params[col] = updates[col]

        for col in _JSONB_COLS:
            if col in updates:
                set_clauses.append(f"{col} = CAST(:{col} AS jsonb)")
                params[col] = json.dumps(updates[col])

        if not set_clauses:
            return existing

        set_clauses.append("updated_at = NOW()")
        sql = (
            f"UPDATE llm_profiles SET {', '.join(set_clauses)} "
            "WHERE id = :id AND owner_tenant_id IS NULL"
        )
        result = await db.execute(text(sql), params)
        if (result.rowcount or 0) == 0:
            raise LLMProfileNotFoundError(f"Platform profile {profile_id} not found")

        await _audit(
            actor_id=actor_id,
            tenant_id=None,
            entity_type="llm_profile",
            entity_id=profile_id,
            action="update",
            diff={"before": before_snapshot, "after": updates},
            db=db,
        )

        logger.info(
            "llm_profile_platform_updated",
            profile_id=profile_id,
            actor_id=actor_id,
            fields=sorted(updates.keys()),
        )

        return await self._fetch_profile(profile_id, db)

    async def deprecate_platform_profile(
        self,
        profile_id: str,
        *,
        actor_id: str,
        db: AsyncSession,
    ) -> dict:
        """Mark a platform profile as deprecated.

        Tenants currently assigned to this profile retain access until
        they are explicitly reassigned. No cascading change.

        Raises:
            LLMProfileNotFoundError: Profile not found.
            LLMProfileValidationError: If already deprecated.
        """
        existing = await self._fetch_platform_profile(profile_id, db)
        if existing["status"] == "deprecated":
            raise LLMProfileValidationError("Profile is already deprecated")

        result = await db.execute(
            text(
                "UPDATE llm_profiles SET status = 'deprecated', updated_at = NOW() "
                "WHERE id = :id AND owner_tenant_id IS NULL"
            ),
            {"id": profile_id},
        )
        if (result.rowcount or 0) == 0:
            raise LLMProfileNotFoundError(f"Platform profile {profile_id} not found")

        await _audit(
            actor_id=actor_id,
            tenant_id=None,
            entity_type="llm_profile",
            entity_id=profile_id,
            action="deprecate",
            diff={"before": {"status": "active"}, "after": {"status": "deprecated"}},
            db=db,
        )

        logger.info(
            "llm_profile_deprecated",
            profile_id=profile_id,
            actor_id=actor_id,
        )

        return await self._fetch_profile(profile_id, db)

    async def list_platform_profiles(
        self,
        *,
        plan_filter: Optional[str] = None,
        include_deprecated: bool = False,
        db: AsyncSession,
    ) -> list[dict]:
        """List platform profiles visible to a given plan.

        Args:
            plan_filter: If given, return only profiles where plan_tiers is empty
                         (visible to all) OR plan_filter is in plan_tiers.
            include_deprecated: Include deprecated profiles (default: active only).
            db: Async DB session.

        Returns:
            List of profile dicts, ordered by is_platform_default DESC, name ASC.
        """
        conditions = ["p.owner_tenant_id IS NULL"]
        params: dict = {}

        if not include_deprecated:
            conditions.append("p.status = 'active'")

        if plan_filter:
            conditions.append(
                "(p.plan_tiers = '{}' OR :plan = ANY(p.plan_tiers))"
            )
            params["plan"] = plan_filter

        where = " AND ".join(conditions)
        result = await db.execute(
            text(
                "SELECT p.id, p.name, p.description, p.status, "
                "p.chat_library_id, p.intent_library_id, p.vision_library_id, p.agent_library_id, "
                "p.chat_params, p.intent_params, p.vision_params, p.agent_params, "
                "p.chat_traffic_split, p.intent_traffic_split, p.vision_traffic_split, p.agent_traffic_split, "
                "p.is_platform_default, p.plan_tiers, p.owner_tenant_id, p.created_by, p.created_at, p.updated_at, "
                # Join llm_library to get model_name per slot
                "lc.model_name AS chat_model_name, lc.provider AS chat_provider, lc.health_status AS chat_health_status, "
                "li.model_name AS intent_model_name, li.provider AS intent_provider, li.health_status AS intent_health_status, "
                "lv.model_name AS vision_model_name, lv.provider AS vision_provider, lv.health_status AS vision_health_status, "
                "la.model_name AS agent_model_name, la.provider AS agent_provider, la.health_status AS agent_health_status, "
                # Count tenants assigned to this profile
                "(SELECT COUNT(*) FROM tenants t WHERE t.llm_profile_id = p.id) AS tenants_count "
                "FROM llm_profiles p "
                "LEFT JOIN llm_library lc ON p.chat_library_id = lc.id "
                "LEFT JOIN llm_library li ON p.intent_library_id = li.id "
                "LEFT JOIN llm_library lv ON p.vision_library_id = lv.id "
                "LEFT JOIN llm_library la ON p.agent_library_id = la.id "
                f"WHERE {where} "
                "ORDER BY p.is_platform_default DESC, p.name ASC"
            ),
            params,
        )
        rows = result.mappings().fetchall()
        profiles = []
        for row in rows:
            d = dict(row)
            # Rename positional keys to canonical names
            d = {
                "id": str(d["id"]),
                "name": d["name"],
                "description": d["description"],
                "status": d["status"],
                "chat_library_id": str(d["chat_library_id"]) if d["chat_library_id"] else None,
                "intent_library_id": str(d["intent_library_id"]) if d["intent_library_id"] else None,
                "vision_library_id": str(d["vision_library_id"]) if d["vision_library_id"] else None,
                "agent_library_id": str(d["agent_library_id"]) if d["agent_library_id"] else None,
                "chat_params": d.get("chat_params") or {},
                "intent_params": d.get("intent_params") or {},
                "vision_params": d.get("vision_params") or {},
                "agent_params": d.get("agent_params") or {},
                "chat_traffic_split": d.get("chat_traffic_split") or [],
                "intent_traffic_split": d.get("intent_traffic_split") or [],
                "vision_traffic_split": d.get("vision_traffic_split") or [],
                "agent_traffic_split": d.get("agent_traffic_split") or [],
                "is_platform_default": bool(d["is_platform_default"]),
                "plan_tiers": list(d["plan_tiers"]) if d["plan_tiers"] else [],
                "owner_tenant_id": str(d["owner_tenant_id"]) if d["owner_tenant_id"] else None,
                "created_by": str(d["created_by"]) if d["created_by"] else None,
                "created_at": d["created_at"].isoformat() if d["created_at"] else None,
                "updated_at": d["updated_at"].isoformat() if d["updated_at"] else None,
                "tenants_count": int(d.get("tenants_count") or 0),
            }
            # Build nested slots structure for frontend
            d["slots"] = {}
            for slot in ("chat", "intent", "vision", "agent"):
                lib_id = d.get(f"{slot}_library_id")
                model_name = row.get(f"{slot}_model_name")
                if lib_id and model_name:
                    d["slots"][slot] = {
                        "library_entry_id": lib_id,
                        "model_name": model_name,
                        "provider": row.get(f"{slot}_provider", ""),
                        "health_status": row.get(f"{slot}_health_status") or "unknown",
                        "test_passed_at": None,
                    }
                else:
                    d["slots"][slot] = None
            profiles.append(d)
        return profiles

    # ------------------------------------------------------------------
    # Tenant BYOLLM profile operations (owner_tenant_id = tenant_id)
    # ------------------------------------------------------------------

    async def create_byollm_profile(
        self,
        *,
        tenant_id: str,
        name: str,
        description: Optional[str],
        slot_data: dict,
        actor_id: str,
        db: AsyncSession,
    ) -> dict:
        """Create a BYOLLM profile owned by a tenant (enterprise only).

        The route handler is responsible for verifying enterprise plan before
        calling this method.

        Args:
            tenant_id: Owning tenant UUID.
            name: Profile name (unique per tenant).
            description: Optional description.
            slot_data: Slot assignment and param data.
            actor_id: UUID of the tenant admin.
            db: Async DB session (RLS scoped to tenant).

        Raises:
            LLMProfileConflictError: If a profile with this name already exists for the tenant.
            LLMProfileValidationError: On slot validation failure.
        """
        slot_fields = _build_slot_fields(slot_data)

        # Verify all library IDs
        for slot in VALID_SLOTS:
            lib_id = slot_fields.get(f"{slot}_library_id")
            if lib_id:
                await _verify_library_id(lib_id, tenant_id, db)

        # Check name uniqueness per tenant
        exists = await db.execute(
            text(
                "SELECT id FROM llm_profiles "
                "WHERE name = :name AND owner_tenant_id = :tid"
            ),
            {"name": name, "tid": tenant_id},
        )
        if exists.fetchone():
            raise LLMProfileConflictError(
                f"A profile named '{name}' already exists for this tenant"
            )

        profile_id = str(uuid.uuid4())

        await db.execute(
            text(
                "INSERT INTO llm_profiles "
                "(id, name, description, status, "
                "chat_library_id, intent_library_id, vision_library_id, agent_library_id, "
                "chat_params, intent_params, vision_params, agent_params, "
                "chat_traffic_split, intent_traffic_split, vision_traffic_split, agent_traffic_split, "
                "is_platform_default, plan_tiers, owner_tenant_id, created_by, created_at, updated_at) "
                "VALUES "
                "(:id, :name, :desc, 'active', "
                ":chat_lib, :intent_lib, :vision_lib, :agent_lib, "
                "CAST(:chat_p AS jsonb), CAST(:intent_p AS jsonb), "
                "CAST(:vision_p AS jsonb), CAST(:agent_p AS jsonb), "
                "CAST(:chat_s AS jsonb), CAST(:intent_s AS jsonb), "
                "CAST(:vision_s AS jsonb), CAST(:agent_s AS jsonb), "
                "false, '{}', :tid, :actor, NOW(), NOW())"
            ),
            {
                "id": profile_id,
                "name": name,
                "desc": description,
                "chat_lib": slot_fields.get("chat_library_id"),
                "intent_lib": slot_fields.get("intent_library_id"),
                "vision_lib": slot_fields.get("vision_library_id"),
                "agent_lib": slot_fields.get("agent_library_id"),
                "chat_p": json.dumps(slot_fields.get("chat_params", {})),
                "intent_p": json.dumps(slot_fields.get("intent_params", {})),
                "vision_p": json.dumps(slot_fields.get("vision_params", {})),
                "agent_p": json.dumps(slot_fields.get("agent_params", {})),
                "chat_s": json.dumps(slot_fields.get("chat_traffic_split", [])),
                "intent_s": json.dumps(slot_fields.get("intent_traffic_split", [])),
                "vision_s": json.dumps(slot_fields.get("vision_traffic_split", [])),
                "agent_s": json.dumps(slot_fields.get("agent_traffic_split", [])),
                "tid": tenant_id,
                "actor": actor_id,
            },
        )

        await _audit(
            actor_id=actor_id,
            tenant_id=tenant_id,
            entity_type="llm_profile",
            entity_id=profile_id,
            action="create",
            diff={"after": {"name": name, "owner_tenant_id": tenant_id}},
            db=db,
        )

        logger.info(
            "llm_profile_byollm_created",
            profile_id=profile_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
        )

        return await self._fetch_profile(profile_id, db)

    async def list_tenant_profiles(
        self,
        tenant_id: str,
        *,
        include_deprecated: bool = False,
        db: AsyncSession,
    ) -> list[dict]:
        """List BYOLLM profiles owned by a specific tenant."""
        conditions = ["owner_tenant_id = :tid"]
        params: dict = {"tid": tenant_id}
        if not include_deprecated:
            conditions.append("status = 'active'")
        where = " AND ".join(conditions)
        result = await db.execute(
            text(
                "SELECT id, name, description, status, "
                "chat_library_id, intent_library_id, vision_library_id, agent_library_id, "
                "chat_params, intent_params, vision_params, agent_params, "
                "chat_traffic_split, intent_traffic_split, vision_traffic_split, agent_traffic_split, "
                "is_platform_default, plan_tiers, owner_tenant_id, created_by, created_at, updated_at "
                f"FROM llm_profiles WHERE {where} ORDER BY name ASC"
            ),
            params,
        )
        return [_row_to_dict(row) for row in result.fetchall()]

    async def delete_byollm_profile(
        self,
        profile_id: str,
        *,
        tenant_id: str,
        actor_id: str,
        db: AsyncSession,
    ) -> None:
        """Hard-delete a BYOLLM profile owned by a tenant.

        Platform profiles cannot be deleted (only deprecated).

        Raises:
            LLMProfileNotFoundError: Profile not found or not owned by this tenant.
            LLMProfilePermissionError: Attempted to delete a platform profile.
        """
        existing_result = await db.execute(
            text(
                "SELECT owner_tenant_id FROM llm_profiles WHERE id = :id"
            ),
            {"id": profile_id},
        )
        row = existing_result.fetchone()
        if row is None:
            raise LLMProfileNotFoundError(f"Profile {profile_id} not found")
        if row[0] is None:
            raise LLMProfilePermissionError(
                "Platform profiles cannot be deleted — use deprecate instead"
            )
        if row[0] != tenant_id:
            raise LLMProfilePermissionError(
                "Profile does not belong to this tenant"
            )

        await db.execute(
            text("DELETE FROM llm_profiles WHERE id = :id AND owner_tenant_id = :tid"),
            {"id": profile_id, "tid": tenant_id},
        )

        await _audit(
            actor_id=actor_id,
            tenant_id=tenant_id,
            entity_type="llm_profile",
            entity_id=profile_id,
            action="delete",
            diff={"before": {"id": profile_id, "owner_tenant_id": tenant_id}},
            db=db,
        )

        logger.info(
            "llm_profile_byollm_deleted",
            profile_id=profile_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
        )

    # ------------------------------------------------------------------
    # Shared / read operations
    # ------------------------------------------------------------------

    async def get_profile(
        self,
        profile_id: str,
        *,
        db: AsyncSession,
    ) -> dict:
        """Fetch any profile by ID.

        Raises:
            LLMProfileNotFoundError: Profile does not exist.
        """
        return await self._fetch_profile(profile_id, db)

    async def get_platform_default(
        self,
        *,
        plan: Optional[str] = None,
        db: AsyncSession,
    ) -> Optional[dict]:
        """Return the platform default profile, or None if none is set.

        If plan is given, also checks plan_tiers eligibility.
        """
        conditions = [
            "owner_tenant_id IS NULL",
            "is_platform_default = true",
            "status = 'active'",
        ]
        params: dict = {}
        if plan:
            conditions.append("(plan_tiers = '{}' OR :plan = ANY(plan_tiers))")
            params["plan"] = plan

        result = await db.execute(
            text(
                "SELECT id, name, description, status, "
                "chat_library_id, intent_library_id, vision_library_id, agent_library_id, "
                "chat_params, intent_params, vision_params, agent_params, "
                "chat_traffic_split, intent_traffic_split, vision_traffic_split, agent_traffic_split, "
                "is_platform_default, plan_tiers, owner_tenant_id, created_by, created_at, updated_at "
                f"FROM llm_profiles WHERE {' AND '.join(conditions)} "
                "LIMIT 1"
            ),
            params,
        )
        row = result.fetchone()
        if row is None:
            return None
        return _row_to_dict(row)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _fetch_profile(self, profile_id: str, db: AsyncSession) -> dict:
        result = await db.execute(
            text(
                "SELECT p.id, p.name, p.description, p.status, "
                "p.chat_library_id, p.intent_library_id, p.vision_library_id, p.agent_library_id, "
                "p.chat_params, p.intent_params, p.vision_params, p.agent_params, "
                "p.chat_traffic_split, p.intent_traffic_split, p.vision_traffic_split, p.agent_traffic_split, "
                "p.is_platform_default, p.plan_tiers, p.owner_tenant_id, p.created_by, p.created_at, p.updated_at, "
                "lc.model_name AS chat_model_name, lc.provider AS chat_provider, lc.health_status AS chat_health_status, lc.last_test_passed_at AS chat_test_passed_at, lc.pricing_per_1k_tokens_in AS chat_price_in, lc.pricing_per_1k_tokens_out AS chat_price_out, "
                "li.model_name AS intent_model_name, li.provider AS intent_provider, li.health_status AS intent_health_status, li.last_test_passed_at AS intent_test_passed_at, li.pricing_per_1k_tokens_in AS intent_price_in, li.pricing_per_1k_tokens_out AS intent_price_out, "
                "lv.model_name AS vision_model_name, lv.provider AS vision_provider, lv.health_status AS vision_health_status, lv.last_test_passed_at AS vision_test_passed_at, lv.pricing_per_1k_tokens_in AS vision_price_in, lv.pricing_per_1k_tokens_out AS vision_price_out, "
                "la.model_name AS agent_model_name, la.provider AS agent_provider, la.health_status AS agent_health_status, la.last_test_passed_at AS agent_test_passed_at, la.pricing_per_1k_tokens_in AS agent_price_in, la.pricing_per_1k_tokens_out AS agent_price_out, "
                "(SELECT COUNT(*) FROM tenants t WHERE t.llm_profile_id = p.id) AS tenants_count "
                "FROM llm_profiles p "
                "LEFT JOIN llm_library lc ON p.chat_library_id = lc.id "
                "LEFT JOIN llm_library li ON p.intent_library_id = li.id "
                "LEFT JOIN llm_library lv ON p.vision_library_id = lv.id "
                "LEFT JOIN llm_library la ON p.agent_library_id = la.id "
                "WHERE p.id = :id"
            ),
            {"id": profile_id},
        )
        row = result.mappings().fetchone()
        if row is None:
            raise LLMProfileNotFoundError(f"Profile {profile_id} not found")
        d = _row_to_dict_from_mapping(dict(row))
        return d

    async def _fetch_platform_profile(self, profile_id: str, db: AsyncSession) -> dict:
        """Fetch a platform-owned profile; raise if not found or tenant-owned."""
        profile = await self._fetch_profile(profile_id, db)
        if profile.get("owner_tenant_id") is not None:
            raise LLMProfileNotFoundError(
                f"Platform profile {profile_id} not found"
            )
        return profile


# ---------------------------------------------------------------------------
# Row helper
# ---------------------------------------------------------------------------


def _row_to_dict(row) -> dict:
    """Convert a raw SQLAlchemy row to a dict with the canonical field names."""
    (
        id_, name, description, status,
        chat_lib, intent_lib, vision_lib, agent_lib,
        chat_p, intent_p, vision_p, agent_p,
        chat_s, intent_s, vision_s, agent_s,
        is_default, plan_tiers, owner_tid, created_by,
        created_at, updated_at,
    ) = row

    def _j(val):
        if val is None:
            return {}
        if isinstance(val, str):
            return json.loads(val)
        return val

    def _ja(val):
        if val is None:
            return []
        if isinstance(val, str):
            return json.loads(val)
        return val

    return {
        "id": str(id_),
        "name": name,
        "description": description,
        "status": status,
        "chat_library_id": str(chat_lib) if chat_lib else None,
        "intent_library_id": str(intent_lib) if intent_lib else None,
        "vision_library_id": str(vision_lib) if vision_lib else None,
        "agent_library_id": str(agent_lib) if agent_lib else None,
        "chat_params": _j(chat_p),
        "intent_params": _j(intent_p),
        "vision_params": _j(vision_p),
        "agent_params": _j(agent_p),
        "chat_traffic_split": _ja(chat_s),
        "intent_traffic_split": _ja(intent_s),
        "vision_traffic_split": _ja(vision_s),
        "agent_traffic_split": _ja(agent_s),
        "is_platform_default": bool(is_default),
        "plan_tiers": list(plan_tiers) if plan_tiers else [],
        "owner_tenant_id": str(owner_tid) if owner_tid else None,
        "created_by": str(created_by) if created_by else None,
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


def _row_to_dict_from_mapping(d: dict) -> dict:
    """Convert a mapping row (with JOIN columns) to canonical profile dict with enriched slots."""

    def _j(val):
        if val is None:
            return {}
        if isinstance(val, str):
            return json.loads(val)
        return val

    def _ja(val):
        if val is None:
            return []
        if isinstance(val, str):
            return json.loads(val)
        return val

    result = {
        "id": str(d["id"]),
        "name": d["name"],
        "description": d.get("description"),
        "status": d["status"],
        "chat_library_id": str(d["chat_library_id"]) if d.get("chat_library_id") else None,
        "intent_library_id": str(d["intent_library_id"]) if d.get("intent_library_id") else None,
        "vision_library_id": str(d["vision_library_id"]) if d.get("vision_library_id") else None,
        "agent_library_id": str(d["agent_library_id"]) if d.get("agent_library_id") else None,
        "chat_params": _j(d.get("chat_params")),
        "intent_params": _j(d.get("intent_params")),
        "vision_params": _j(d.get("vision_params")),
        "agent_params": _j(d.get("agent_params")),
        "chat_traffic_split": _ja(d.get("chat_traffic_split")),
        "intent_traffic_split": _ja(d.get("intent_traffic_split")),
        "vision_traffic_split": _ja(d.get("vision_traffic_split")),
        "agent_traffic_split": _ja(d.get("agent_traffic_split")),
        "is_platform_default": bool(d.get("is_platform_default")),
        "plan_tiers": list(d["plan_tiers"]) if d.get("plan_tiers") else [],
        "owner_tenant_id": str(d["owner_tenant_id"]) if d.get("owner_tenant_id") else None,
        "created_by": str(d["created_by"]) if d.get("created_by") else None,
        "created_at": d["created_at"].isoformat() if d.get("created_at") else None,
        "updated_at": d["updated_at"].isoformat() if d.get("updated_at") else None,
        "tenants_count": int(d.get("tenants_count") or 0),
    }

    slots = {}
    for slot in ("chat", "intent", "vision", "agent"):
        lib_id = d.get(f"{slot}_library_id")
        model_name = d.get(f"{slot}_model_name")
        if lib_id and model_name:
            test_at = d.get(f"{slot}_test_passed_at")
            price_in = d.get(f"{slot}_price_in")
            price_out = d.get(f"{slot}_price_out")
            slots[slot] = {
                "library_entry_id": str(lib_id),
                "model_name": model_name,
                "provider": d.get(f"{slot}_provider") or "",
                "health_status": d.get(f"{slot}_health_status") or "unknown",
                "test_passed_at": test_at.isoformat() if test_at else None,
                "pricing_per_1k_tokens_in": float(price_in) if price_in is not None else None,
                "pricing_per_1k_tokens_out": float(price_out) if price_out is not None else None,
            }
        else:
            slots[slot] = None
    result["slots"] = slots
    return result
