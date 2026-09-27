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

import json
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


# ============================================================================
# Meta Ads — Business Use Case (BUC) tracking (Sprint M.2a Task 7)
# ============================================================================


def _parse_buc_header_pct(buc_header: str | None, *, ad_account_id: str) -> int | None:
    """Parse X-Business-Use-Case-Usage header + return max usage pct for ad_account.

    BUC format: {"<numeric_ad_account_id>": [{"type":"ads_insights",
                  "call_count": 42, "total_cputime": 12, "total_time": 35,
                  "estimated_time_to_regain_access": 0}]}

    Strategy: max(call_count, total_cputime, total_time) across all entries
    for the matching ad_account.

    Spec 2026-09-26 §5: cabecalho vazio, JSON malformado, nao-dict ou sem a chave da
    conta devolve **None** — "nao sei", nunca `0`. O `0` antigo era indistinguivel de
    uma conta ociosa e sobrescrevia o ultimo valor medido.
    """
    if not buc_header:
        return None
    try:
        parsed = json.loads(buc_header)
    except (ValueError, TypeError):
        return None

    if not isinstance(parsed, dict):
        return None

    numeric_id = ad_account_id.replace("act_", "")
    pcts: list[int] = []
    for acct_key, usages in parsed.items():
        if acct_key != numeric_id:
            continue
        if not isinstance(usages, list):
            continue
        for u in usages:
            if not isinstance(u, dict):
                continue
            # Campo ausente ou valor que nao e numero nao conta como 0: a entrada
            # sem nenhum dos tres lia como conta ociosa, e um valor nao numerico
            # levantava no int() antes de o contador de chamadas gravar.
            for chave in ("call_count", "total_cputime", "total_time"):
                try:
                    pcts.append(int(float(u[chave])))
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
    return max(pcts) if pcts else None


def _parse_insights_throttle(header: str | None) -> dict[str, float] | None:
    """Parse X-FB-Ads-Insights-Throttle -> {"app_id_util_pct": x, "acc_id_util_pct": y}.

    Medido em 26/09 (`scripts/probe_meta_metricas.py`): em chamada /insights o
    `x-app-usage` NAO vem; a quota do APP vem aqui, junto da da conta. Devolve so os
    dois campos numericos que vierem; nenhum, ou cabecalho ausente/malformado -> None.
    """
    if not header:
        return None
    try:
        parsed = json.loads(header)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    sinais: dict[str, float] = {}
    for chave in ("app_id_util_pct", "acc_id_util_pct"):
        valor = parsed.get(chave)
        if isinstance(valor, int | float) and not isinstance(valor, bool):
            sinais[chave] = float(valor)
    return sinais or None


async def record_actual_meta(
    *,
    app_id: str,
    ad_account_id: str,
    buc_header: str | None,
    insights_throttle_header: str | None = None,
    calls: int = 1,
) -> None:
    """Conta as chamadas e registra o uso medido — so o MEDIDO.

    Spec 2026-09-26 §5: BUC nao lido nao grava nada no `last_throttle_pct` (o ultimo
    valor medido fica) e vira o evento `meta_buc_nao_lido`. O aviso
    `meta_rate_limit_warning` dispara quando QUALQUER sinal medido passa de 75% — o
    BUC da conta, ou a quota do app/conta do `x-fb-ads-insights-throttle` — e diz
    quais: a quota que barra e a que tem menos folga (F110).

    Hashes app_id (SHA-256 truncated 32-char) before persisting for storage privacy.
    """
    import hashlib
    from datetime import date

    from src.db import connection
    from src.db.repositories import meta_rate_counters

    throttle_pct = _parse_buc_header_pct(buc_header, ad_account_id=ad_account_id)
    insights = _parse_insights_throttle(insights_throttle_header)
    app_id_hash = hashlib.sha256(app_id.encode()).hexdigest()[:32]
    today = date.today()

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await meta_rate_counters.increment_calls(
            conn,
            app_id=app_id_hash,
            ad_account_id=ad_account_id,
            date=today,
            by=calls,
        )
        if throttle_pct is not None:
            await meta_rate_counters.update_throttle(
                conn,
                app_id=app_id_hash,
                ad_account_id=ad_account_id,
                date=today,
                throttle_pct=throttle_pct,
            )

    if throttle_pct is None:
        # WARNING, nao info: e o unico sinal que avisa que o token COMPARTILHADO vai
        # ser limitado, e em 26/09 ele veio em toda chamada /insights medida — ausente
        # ou ilegivel e anomalia (formato mudou), nao rotina.
        log.warning(
            "meta_buc_nao_lido",
            ad_account_id=ad_account_id,
            motivo="ausente" if not buc_header else "nao_entendido",
        )

    medidos: dict[str, float] = dict(insights or {})
    if throttle_pct is not None:
        medidos["buc_conta_pct"] = float(throttle_pct)
    acima = {nome: valor for nome, valor in medidos.items() if valor > 75}
    if acima:
        log.warning(
            "meta_rate_limit_warning",
            ad_account_id=ad_account_id,
            acima_de_75=acima,
        )
