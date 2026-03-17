#!/usr/bin/env python3
"""
Migrate existing mingai users to Auth0.

Maps local users (by email) to Auth0 user IDs via Management API.
Updates users.auth0_user_id column for matched users.
Generates CSV report.

Usage:
    python scripts/migrate_users_to_auth0.py [--dry-run] [--tenant-id <uuid>]

Options:
    --dry-run       Show what would change without writing to DB
    --tenant-id     Only migrate users for specified tenant (default: all tenants)
    --batch-size    Auth0 API batch size (default: 50)
"""
import argparse
import asyncio
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import structlog

# ---------------------------------------------------------------------------
# Bootstrap: load .env from src/backend/.env before any other import
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _SCRIPT_DIR.parent

# Add backend root to path so app.* imports work
sys.path.insert(0, str(_BACKEND_ROOT))

from dotenv import load_dotenv  # noqa: E402

_env_path = _BACKEND_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    # Fall back to .env.example for environment stubs in CI
    _env_example = _BACKEND_ROOT / ".env.example"
    if _env_example.exists():
        load_dotenv(_env_example)

logger = structlog.get_logger()

# Auth0 rate limit guard: 100ms delay between user-by-email lookups
_AUTH0_CALL_DELAY_SECONDS = 0.1

# Status codes written to the CSV report
_STATUS_MIGRATED = "migrated"
_STATUS_NOT_FOUND = "not_found"
_STATUS_ERROR = "error"
_STATUS_SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _fetch_unmigrated_users(
    tenant_id: str | None,
) -> list[dict]:
    """
    Return all users where auth0_user_id IS NULL.

    When *tenant_id* is given only users for that tenant are returned.
    Skips rows whose email is NULL (service accounts without an email address).
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Configure it in .env before running this script."
        )

    engine = create_async_engine(database_url, echo=False)

    params: dict = {}
    where_clauses = [
        "auth0_user_id IS NULL",
        "email IS NOT NULL",
    ]

    if tenant_id:
        where_clauses.append("tenant_id = :tenant_id")
        params["tenant_id"] = tenant_id

    where_sql = " AND ".join(where_clauses)
    query = text(
        f"SELECT id, email, tenant_id FROM users WHERE {where_sql} ORDER BY id"
    )

    async with engine.connect() as conn:
        result = await conn.execute(query, params)
        rows = result.fetchall()

    await engine.dispose()

    return [
        {"id": str(row[0]), "email": str(row[1]), "tenant_id": str(row[2])}
        for row in rows
    ]


async def _update_auth0_user_id(
    user_id: str,
    auth0_user_id: str,
) -> None:
    """Persist auth0_user_id for a single user row."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    database_url = os.environ.get("DATABASE_URL", "")
    engine = create_async_engine(database_url, echo=False)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE users SET auth0_user_id = :auth0_user_id "
                "WHERE id = CAST(:user_id AS uuid)"
            ),
            {"auth0_user_id": auth0_user_id, "user_id": user_id},
        )

    await engine.dispose()


# ---------------------------------------------------------------------------
# Auth0 lookup
# ---------------------------------------------------------------------------


async def _lookup_auth0_user_by_email(email: str) -> str | None:
    """
    Call Auth0 Management API GET /api/v2/users-by-email?email={email}.

    Returns the Auth0 user_id string on match, or None if no user found.
    Raises RuntimeError if the API call fails (caller records as error).

    Uses the management_api_request() helper which handles token caching via
    Redis (best-effort) and client_credentials grant refresh.
    """
    from urllib.parse import quote

    from app.modules.auth.management_api import management_api_request

    encoded_email = quote(email, safe="")
    results = await management_api_request(
        "GET", f"users-by-email?email={encoded_email}"
    )

    # Management API returns a list of matching users
    if not isinstance(results, list):
        logger.warning(
            "auth0_users_by_email_unexpected_response",
            email_len=len(email),
            response_type=type(results).__name__,
        )
        return None

    if not results:
        return None

    # Take the first match (email is unique in well-configured Auth0 tenants)
    auth0_user = results[0]
    user_id = auth0_user.get("user_id")
    if not user_id:
        logger.warning(
            "auth0_user_missing_user_id_field",
            email_len=len(email),
        )
        return None

    return str(user_id)


# ---------------------------------------------------------------------------
# CSV report
# ---------------------------------------------------------------------------


def _write_csv_report(
    records: list[dict],
    report_path: Path,
) -> None:
    """
    Write migration results to a CSV file.

    Columns: email, auth0_user_id, status, timestamp
    """
    with report_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["email", "auth0_user_id", "status", "timestamp"],
        )
        writer.writeheader()
        writer.writerows(records)


# ---------------------------------------------------------------------------
# Core migration logic
# ---------------------------------------------------------------------------


async def run_migration(
    dry_run: bool,
    tenant_id: str | None,
    batch_size: int,
) -> None:
    """
    Main migration coroutine.

    1. Fetch unmigrated users from DB (auth0_user_id IS NULL).
    2. For each user: query Auth0 by email.
    3. On match: update DB (unless --dry-run).
    4. Write CSV report.
    5. Print summary.
    """
    log = logger.bind(dry_run=dry_run, tenant_id=tenant_id or "all")
    log.info("migration_started")

    # --- Fetch users ---
    try:
        users = await _fetch_unmigrated_users(tenant_id)
    except Exception as exc:
        log.error("fetch_users_failed", error=str(exc))
        print(f"ERROR: Could not fetch users from database: {exc}", file=sys.stderr)
        sys.exit(1)

    total = len(users)
    log.info("unmigrated_users_fetched", count=total)
    print(f"Found {total} user(s) to process.")

    if total == 0:
        print("Nothing to do — all users already have auth0_user_id set.")
        return

    records: list[dict] = []
    migrated: list[str] = []
    not_found: list[str] = []
    errors: list[str] = []

    timestamp_str = datetime.now(timezone.utc).isoformat()

    for idx, user in enumerate(users, start=1):
        user_id = user["id"]
        email = user["email"]

        # Rate-limit guard between Auth0 API calls (skip delay on first call)
        if idx > 1:
            await asyncio.sleep(_AUTH0_CALL_DELAY_SECONDS)

        auth0_user_id: str | None = None
        status = _STATUS_NOT_FOUND

        try:
            auth0_user_id = await _lookup_auth0_user_by_email(email)
        except Exception as exc:
            log.warning(
                "auth0_lookup_failed",
                user_id=user_id,
                error=str(exc),
            )
            errors.append(user_id)
            status = _STATUS_ERROR
            records.append(
                {
                    "email": email,
                    "auth0_user_id": "",
                    "status": status,
                    "timestamp": timestamp_str,
                }
            )
            print(f"  [{idx}/{total}] ERROR  user_id={user_id}")
            continue

        if auth0_user_id is None:
            not_found.append(user_id)
            status = _STATUS_NOT_FOUND
            log.debug("auth0_user_not_found", user_id=user_id)
            print(f"  [{idx}/{total}] NOT_FOUND  user_id={user_id}")
        else:
            if dry_run:
                # Dry-run: record what would happen but do not write
                migrated.append(user_id)
                status = _STATUS_MIGRATED
                log.info(
                    "dry_run_would_migrate",
                    user_id=user_id,
                    auth0_user_id=auth0_user_id,
                )
                print(
                    f"  [{idx}/{total}] DRY-RUN  user_id={user_id} "
                    f"→ {auth0_user_id}"
                )
            else:
                try:
                    await _update_auth0_user_id(user_id, auth0_user_id)
                    migrated.append(user_id)
                    status = _STATUS_MIGRATED
                    log.info(
                        "user_migrated",
                        user_id=user_id,
                        auth0_user_id=auth0_user_id,
                    )
                    print(
                        f"  [{idx}/{total}] MIGRATED  user_id={user_id} "
                        f"→ {auth0_user_id}"
                    )
                except Exception as exc:
                    errors.append(user_id)
                    status = _STATUS_ERROR
                    auth0_user_id = ""
                    log.error(
                        "db_update_failed",
                        user_id=user_id,
                        error=str(exc),
                    )
                    print(
                        f"  [{idx}/{total}] ERROR (db update)  user_id={user_id}: {exc}"
                    )

        records.append(
            {
                "email": email,
                "auth0_user_id": auth0_user_id or "",
                "status": status,
                "timestamp": timestamp_str,
            }
        )

    # --- CSV report ---
    ts_file = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = _SCRIPT_DIR / f"migration_report_{ts_file}.csv"
    _write_csv_report(records, report_path)

    # --- Summary ---
    print()
    print("=" * 60)
    print(f"Migration {'(DRY RUN) ' if dry_run else ''}complete")
    print(f"  Total processed : {total}")
    print(f"  Migrated        : {len(migrated)}")
    print(f"  Not found       : {len(not_found)}")
    print(f"  Errors          : {len(errors)}")
    print(f"  Skipped         : 0")
    print(f"  Report          : {report_path}")
    print("=" * 60)

    log.info(
        "migration_complete",
        total=total,
        migrated=len(migrated),
        not_found=len(not_found),
        errors=len(errors),
        dry_run=dry_run,
        report=str(report_path),
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate existing mingai users to Auth0 by populating "
            "users.auth0_user_id via Management API email lookup."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would change without writing to the database.",
    )
    parser.add_argument(
        "--tenant-id",
        metavar="UUID",
        default=None,
        help=(
            "Only migrate users belonging to this tenant UUID. " "Default: all tenants."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        metavar="N",
        help="Auth0 API batch size (informational; default: 50).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # Validate --tenant-id if supplied
    tenant_id: str | None = None
    if args.tenant_id:
        import uuid

        try:
            tenant_id = str(uuid.UUID(args.tenant_id))
        except ValueError:
            print(
                f"ERROR: --tenant-id '{args.tenant_id}' is not a valid UUID.",
                file=sys.stderr,
            )
            sys.exit(1)

    asyncio.run(
        run_migration(
            dry_run=args.dry_run,
            tenant_id=tenant_id,
            batch_size=args.batch_size,
        )
    )


if __name__ == "__main__":
    main()
