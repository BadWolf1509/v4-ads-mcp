"""CRUD for `meta_ad_accounts`. Populated by Meta sync job (M.2+)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg


@dataclass(slots=True, frozen=True)
class MetaAdAccount:
    ad_account_id: str
    business_id: str | None
    business_name: str | None
    account_name: str
    currency: str | None
    timezone_name: str | None
    account_status: int | None
    is_active: bool
    synced_at: datetime


def _row_to_account(row: asyncpg.Record) -> MetaAdAccount:
    return MetaAdAccount(
        ad_account_id=row["ad_account_id"],
        business_id=row["business_id"],
        business_name=row["business_name"],
        account_name=row["account_name"],
        currency=row["currency"],
        timezone_name=row["timezone_name"],
        account_status=row["account_status"],
        is_active=row["is_active"],
        synced_at=row["synced_at"],
    )


async def upsert_many(
    conn: asyncpg.Connection,
    accounts: list[dict[str, Any]],
) -> int:
    """Insert or update accounts in bulk; returns count touched.

    Each dict accepts: ad_account_id, business_id, business_name,
    account_name, currency, timezone_name, account_status.
    """
    if not accounts:
        return 0
    rows = [
        (
            a["ad_account_id"],
            a.get("business_id"),
            a.get("business_name"),
            a["account_name"],
            a.get("currency"),
            a.get("timezone_name"),
            a.get("account_status"),
        )
        for a in accounts
    ]
    await conn.executemany(
        """
        INSERT INTO meta_ad_accounts
            (ad_account_id, business_id, business_name, account_name,
             currency, timezone_name, account_status, is_active, synced_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, true, now())
        ON CONFLICT (ad_account_id) DO UPDATE SET
            business_id = EXCLUDED.business_id,
            business_name = EXCLUDED.business_name,
            account_name = EXCLUDED.account_name,
            currency = EXCLUDED.currency,
            timezone_name = EXCLUDED.timezone_name,
            account_status = EXCLUDED.account_status,
            is_active = true,
            synced_at = now()
        """,
        rows,
    )
    return len(rows)


async def mark_inactive_except(
    conn: asyncpg.Connection,
    *,
    business_id: str,
    keep_ad_account_ids: list[str],
) -> int:
    """Mark accounts under business_id as inactive if not in keep list (deletion detection)."""
    if not keep_ad_account_ids:
        result = await conn.execute(
            "UPDATE meta_ad_accounts SET is_active = false "
            "WHERE business_id = $1 AND is_active = true",
            business_id,
        )
    else:
        result = await conn.execute(
            """
            UPDATE meta_ad_accounts SET is_active = false
            WHERE business_id = $1
              AND is_active = true
              AND ad_account_id <> ALL($2::text[])
            """,
            business_id,
            keep_ad_account_ids,
        )
    return int(result.split()[-1]) if result.startswith("UPDATE") else 0


async def list_all(conn: asyncpg.Connection) -> list[MetaAdAccount]:
    rows = await conn.fetch(
        "SELECT * FROM meta_ad_accounts WHERE is_active = true ORDER BY account_name"
    )
    return [_row_to_account(r) for r in rows]


async def get_by_id(conn: asyncpg.Connection, ad_account_id: str) -> MetaAdAccount | None:
    row = await conn.fetchrow(
        "SELECT * FROM meta_ad_accounts WHERE ad_account_id = $1",
        ad_account_id,
    )
    return _row_to_account(row) if row else None
