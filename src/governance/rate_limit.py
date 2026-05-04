"""Daily Google Ads API rate limit tracking.

Counts operations per developer-token-hash per UTC day. Defaults to
Basic Access quota (15,000 ops/day). Use record_actual() after API
responds to reconcile the estimate against Google's actual usage
(taken from the SearchGoogleAdsResponse query_resource_consumption
field or the gRPC metadata X-Quota-Remaining header).

Threading model: SELECT ... FOR UPDATE serializes increments so
parallel callers don't double-count. Each function takes a single
asyncpg connection and runs in one transaction.
"""

from datetime import UTC, datetime
from typing import NamedTuple

import asyncpg
import structlog

DAILY_QUOTA_BASIC = 15_000
DAILY_QUOTA_STANDARD = 1_000_000
WARN_THRESHOLD_PCT = 80

log = structlog.get_logger(__name__)


class QuotaExhausted(Exception):  # noqa: N818
    """Raised when a call would exceed the daily quota."""


class Usage(NamedTuple):
    used: int
    limit: int
    pct: float


def _today() -> datetime:
    """UTC date as a datetime for date column."""
    return datetime.now(UTC)


async def before_call(
    conn: asyncpg.Connection,
    developer_token_id: str,
    *,
    estimated_ops: int,
    daily_limit: int = DAILY_QUOTA_BASIC,
) -> None:
    """Reserve estimated_ops in today's counter. Raises QuotaExhausted at 100%.

    Logs a one-time warning when crossing 80% threshold (uses
    `last_alert_pct` to dedupe within the day).
    """
    today = _today().date()

    async with conn.transaction():
        # Lock the row for this dev_token+day. ON CONFLICT does the upsert.
        await conn.execute(
            """
            INSERT INTO rate_counters (developer_token_id, date, operations_used, last_alert_pct)
            VALUES ($1, $2, 0, 0)
            ON CONFLICT (developer_token_id, date) DO NOTHING
            """,
            developer_token_id,
            today,
        )
        row = await conn.fetchrow(
            """
            SELECT operations_used, last_alert_pct
            FROM rate_counters
            WHERE developer_token_id = $1 AND date = $2
            FOR UPDATE
            """,
            developer_token_id,
            today,
        )
        assert row is not None
        used = row["operations_used"]
        last_alert = row["last_alert_pct"]

        new_used = used + estimated_ops
        if new_used > daily_limit:
            raise QuotaExhausted(
                f"quota diaria esgotada: {used}/{daily_limit} usadas, "
                f"+{estimated_ops} pediria {new_used}. Reset a meia-noite UTC."
            )

        new_pct = int((new_used / daily_limit) * 100)
        new_alert = last_alert
        if new_pct >= WARN_THRESHOLD_PCT and last_alert < WARN_THRESHOLD_PCT:
            log.warning(
                "rate_limit_80pct_reached",
                developer_token_id=developer_token_id,
                used=new_used,
                limit=daily_limit,
                pct=new_pct,
            )
            new_alert = WARN_THRESHOLD_PCT

        await conn.execute(
            """
            UPDATE rate_counters
            SET operations_used = $3, last_alert_pct = $4
            WHERE developer_token_id = $1 AND date = $2
            """,
            developer_token_id,
            today,
            new_used,
            new_alert,
        )


async def record_actual(
    conn: asyncpg.Connection,
    developer_token_id: str,
    *,
    actual_ops: int,
    estimated_ops: int,
) -> None:
    """Reconcile counter after API responds. Adjusts by (actual - estimated)."""
    today = _today().date()
    delta = actual_ops - estimated_ops
    if delta == 0:
        return  # estimate was right
    await conn.execute(
        """
        UPDATE rate_counters
        SET operations_used = GREATEST(0, operations_used + $3)
        WHERE developer_token_id = $1 AND date = $2
        """,
        developer_token_id,
        today,
        delta,
    )


async def get_today_usage(
    conn: asyncpg.Connection,
    developer_token_id: str,
    *,
    daily_limit: int = DAILY_QUOTA_BASIC,
) -> Usage:
    """Return (used, limit, pct) for today's counter. Returns (0, limit, 0) if no row."""
    today = _today().date()
    row = await conn.fetchrow(
        """
        SELECT operations_used FROM rate_counters
        WHERE developer_token_id = $1 AND date = $2
        """,
        developer_token_id,
        today,
    )
    used = int(row["operations_used"]) if row else 0
    return Usage(used=used, limit=daily_limit, pct=used / daily_limit if daily_limit else 0.0)


def hash_developer_token(token: str) -> str:
    """SHA-256 hex of the dev token; used as the row key in rate_counters.

    Allows future multi-token setups (e.g., test vs prod tokens) without
    leaking the actual token value into the row key.
    """
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
