# bucket: defer
"""Tool: get_my_rate_limit_status — current daily quota usage for V4's dev token."""

import time
from datetime import UTC, datetime
from typing import Any

import structlog

from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log
from src.governance.rate_limit import (
    DAILY_QUOTA_BASIC,
    WARN_THRESHOLD_PCT,
    get_today_usage,
    hash_developer_token,
)
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

log = structlog.get_logger(__name__)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


@register_tool(
    name="get_my_rate_limit_status",
    description=(
        "[DEFER] Quota diaria do Google Ads developer token da V4: usado/limite/percentual "
        "para o dia UTC atual. Sem parametros — quota e por dev token (atravessa "
        "todas as 23 contas). Reset a meia-noite UTC."
    ),
    input_schema=_INPUT_SCHEMA,
    bucket="defer",
)
async def get_my_rate_limit_status(_args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    started = time.monotonic()
    settings = get_settings()
    token_hash = hash_developer_token(settings.google_ads_developer_token)

    # NOTE: DAILY_QUOTA_BASIC hardcoded. After Standard Access (case 26521440673)
    # approves, update DAILY_QUOTA_BASIC constant in rate_limit.py to
    # DAILY_QUOTA_STANDARD value (1_000_000). 1-line change, out of scope here.
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        usage = await get_today_usage(conn, token_hash, daily_limit=DAILY_QUOTA_BASIC)

    duration_ms = int((time.monotonic() - started) * 1000)

    # Audit consistent com list_my_accounts (account-wide read).
    async with pool.acquire() as conn:
        await audit_log.record(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=None,
            action_type="read",
            operation="get_my_rate_limit_status",
            target_count=1,
            params_summary=None,
            status="success",
            duration_ms=duration_ms,
        )

    log.info(
        "tool_get_my_rate_limit_status",
        used=usage.used,
        limit=usage.limit,
        pct=usage.pct,
        duration_ms=duration_ms,
    )

    return {
        "developer_token_id_hash": token_hash,
        "date_utc": datetime.now(UTC).date().isoformat(),
        "used": usage.used,
        "limit": usage.limit,
        "remaining": usage.limit - usage.used,
        "pct": round(usage.pct, 4),
        "pct_display": f"{usage.pct * 100:.1f}%",
        "warning_threshold_pct": WARN_THRESHOLD_PCT,
    }
