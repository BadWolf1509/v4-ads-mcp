"""CRUD for `meta_rate_counters` — Meta API BUC tracking per (app, account, day).

Different from Google rate_counters: Meta has Business Use Case (BUC) limits
per ad_account + app-level + user-level (multi-dimensional). V0 tracks per
(app_id, ad_account_id, date). app_id is HASHED externally (SHA-256 truncated)
before persisting for storage privacy.
"""

from dataclasses import dataclass
from datetime import date

import asyncpg


@dataclass(slots=True, frozen=True)
class MetaRateCounter:
    app_id: str
    ad_account_id: str
    date: date
    calls_used: int
    last_throttle_pct: int


async def increment_calls(
    conn: asyncpg.Connection,
    *,
    app_id: str,
    ad_account_id: str,
    date: date,
    by: int = 1,
) -> int:
    """Increment calls_used + return new total. Inserts row if first time."""
    row = await conn.fetchrow(
        """
        INSERT INTO meta_rate_counters (app_id, ad_account_id, date, calls_used)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (app_id, ad_account_id, date) DO UPDATE SET
            calls_used = meta_rate_counters.calls_used + EXCLUDED.calls_used
        RETURNING calls_used
        """,
        app_id,
        ad_account_id,
        date,
        by,
    )
    assert row is not None
    return int(row["calls_used"])


async def update_throttle(
    conn: asyncpg.Connection,
    *,
    app_id: str,
    ad_account_id: str,
    date: date,
    throttle_pct: int,
) -> None:
    """Update last observed throttle %. Inserts row if first time (calls_used=0)."""
    await conn.execute(
        """
        INSERT INTO meta_rate_counters (app_id, ad_account_id, date, last_throttle_pct)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (app_id, ad_account_id, date) DO UPDATE SET
            last_throttle_pct = EXCLUDED.last_throttle_pct
        """,
        app_id,
        ad_account_id,
        date,
        throttle_pct,
    )
