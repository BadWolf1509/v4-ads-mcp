"""CRUD for `google_ads_accounts`. Populated by the resync job."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg


@dataclass(slots=True, frozen=True)
class GoogleAdsAccount:
    customer_id: str
    mcc_id: str
    descriptive_name: str
    currency_code: str | None
    time_zone: str | None
    is_test_account: bool
    is_active: bool
    synced_at: datetime


def _row_to_account(row: asyncpg.Record) -> GoogleAdsAccount:
    return GoogleAdsAccount(
        customer_id=row["customer_id"],
        mcc_id=row["mcc_id"],
        descriptive_name=row["descriptive_name"],
        currency_code=row["currency_code"],
        time_zone=row["time_zone"],
        is_test_account=row["is_test_account"],
        is_active=row["is_active"],
        synced_at=row["synced_at"],
    )


async def upsert_many(
    conn: asyncpg.Connection,
    accounts: list[
        dict[str, Any]
    ],  # each: customer_id, mcc_id, descriptive_name, currency_code, time_zone, is_test_account
) -> int:
    """Insert or update accounts in bulk; returns count touched."""
    if not accounts:
        return 0
    rows = [
        (
            a["customer_id"],
            a["mcc_id"],
            a["descriptive_name"],
            a.get("currency_code"),
            a.get("time_zone"),
            bool(a.get("is_test_account", False)),
        )
        for a in accounts
    ]
    await conn.executemany(
        """
        INSERT INTO google_ads_accounts
            (customer_id, mcc_id, descriptive_name, currency_code,
             time_zone, is_test_account, is_active, synced_at)
        VALUES ($1, $2, $3, $4, $5, $6, true, now())
        ON CONFLICT (customer_id) DO UPDATE SET
            mcc_id = EXCLUDED.mcc_id,
            descriptive_name = EXCLUDED.descriptive_name,
            currency_code = EXCLUDED.currency_code,
            time_zone = EXCLUDED.time_zone,
            is_test_account = EXCLUDED.is_test_account,
            is_active = true,
            synced_at = now()
        """,
        rows,
    )
    return len(rows)


async def mark_inactive_except(
    conn: asyncpg.Connection,
    *,
    mcc_id: str,
    keep_customer_ids: list[str],
) -> int:
    """Mark accounts under mcc_id as inactive if not in keep list (deletion detection)."""
    if not keep_customer_ids:
        # All accounts for this MCC become inactive (no resync data).
        result = await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE mcc_id = $1 AND is_active = true",
            mcc_id,
        )
    else:
        result = await conn.execute(
            """
            UPDATE google_ads_accounts SET is_active = false
            WHERE mcc_id = $1
              AND is_active = true
              AND customer_id <> ALL($2::text[])
            """,
            mcc_id,
            keep_customer_ids,
        )
    # asyncpg.execute returns 'UPDATE N'
    return int(result.split()[-1]) if result.startswith("UPDATE") else 0


async def list_all(conn: asyncpg.Connection) -> list[GoogleAdsAccount]:
    rows = await conn.fetch(
        "SELECT * FROM google_ads_accounts WHERE is_active = true ORDER BY descriptive_name"
    )
    return [_row_to_account(r) for r in rows]
