"""Cloud Run Job: refresh google_ads_accounts from the MCC.

Picks any active OAuth connection (admin's by default) and uses its
refresh token to call list_accessible_customers + customer_client
search on the MCC. Upserts results, marks deactivated accounts.

Entry point: `python -m src.jobs.account_resync`
"""

import asyncio
import sys
from typing import Any

import asyncpg
import structlog

from src.auth.tokens import decrypt_refresh_token, derive_master_key_from_settings
from src.config import get_settings
from src.db import connection
from src.db.repositories import (
    google_ads_accounts,
    google_oauth_connections,
    managers,
)
from src.google_ads.accounts import (
    fetch_account_details,
    list_accessible_customer_resource_names,
)
from src.google_ads.client import build_client

log = structlog.get_logger(__name__)


async def _pick_oauth_connection(conn: asyncpg.Connection) -> tuple[Any, Any]:
    """Return (manager, oauth_conn) for the first active admin's OAuth.

    Falls back to any active connection if no admin has one.
    """
    admins = await conn.fetch(
        "SELECT id FROM managers WHERE role = 'admin' AND is_active = true ORDER BY created_at"
    )
    for row in admins:
        oc = await google_oauth_connections.get_active_for_manager(conn, row["id"])
        if oc is not None:
            m = await managers.get_by_id(conn, row["id"])
            return m, oc

    # Fallback: any active connection.
    row = await conn.fetchrow(
        "SELECT manager_id FROM google_oauth_connections WHERE revoked_at IS NULL ORDER BY connected_at DESC LIMIT 1"
    )
    if row is None:
        return None, None
    oc = await google_oauth_connections.get_active_for_manager(conn, row["manager_id"])
    m = await managers.get_by_id(conn, row["manager_id"])
    return m, oc


async def run() -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            manager, oc = await _pick_oauth_connection(conn)
            if oc is None:
                log.error("resync_no_oauth_connection")
                print(
                    "No active OAuth connection — bootstrap an admin and have them complete /oauth/google/start first.",
                    file=sys.stderr,
                )
                return 1

        master_key = derive_master_key_from_settings(settings.aes_master_key)
        refresh_token = decrypt_refresh_token(oc.refresh_token_enc, master_key)

        client = build_client(
            refresh_token=refresh_token,
            developer_token=settings.google_ads_developer_token,
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            login_customer_id=settings.google_ads_login_customer_id,
        )

        # Discover accessible customers (mostly: just the MCC itself).
        resource_names = list_accessible_customer_resource_names(client)
        log.info("resync_accessible_customers", count=len(resource_names))

        # Pull descriptive details for all child customers under the MCC.
        accounts = fetch_account_details(
            client,
            login_customer_id=settings.google_ads_login_customer_id,
            customer_ids=[],  # empty → all
        )

        async with pool.acquire() as conn:
            n = await google_ads_accounts.upsert_many(conn, accounts)
            keep_ids = [a["customer_id"] for a in accounts]
            deactivated = await google_ads_accounts.mark_inactive_except(
                conn,
                mcc_id=settings.google_ads_login_customer_id,
                keep_customer_ids=keep_ids,
            )

        log.info("resync_complete", upserted=n, deactivated=deactivated)
        print(f"OK: upserted {n} accounts, deactivated {deactivated}")
        return 0
    finally:
        await connection.close_pool()


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
