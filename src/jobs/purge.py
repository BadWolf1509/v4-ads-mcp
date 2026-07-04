"""Purge diário de rows transientes velhas nas tabelas de estado operacional.

NUNCA toca audit_log (decisão de produto: trilha de compliance, retenção
indefinida). Chamado best-effort no fim de account_resync.run() — falha de
purge não deve derrubar o job de resync.
"""

import asyncpg


async def purge_expired(pool: asyncpg.Pool) -> dict[str, int]:
    """Purga rows expiradas/antigas. Retorna contagem de rows deletadas por tabela.

    - pending_confirmations: expires_at < now() - 7 dias (consumidas ou não —
      o payload já perdeu valor operacional após o TTL de confirmação de 10min;
      7 dias dá margem forense antes de apagar).
    - rate_counters / meta_rate_counters: date < hoje - 90 dias.
    """
    async with pool.acquire() as conn:
        pending_result = await conn.execute(
            "DELETE FROM pending_confirmations WHERE expires_at < now() - interval '7 days'"
        )
        rate_result = await conn.execute("DELETE FROM rate_counters WHERE date < current_date - 90")
        meta_rate_result = await conn.execute(
            "DELETE FROM meta_rate_counters WHERE date < current_date - 90"
        )

    # asyncpg.execute retorna a tag de comando, ex. 'DELETE 12'.
    return {
        "pending_confirmations": _parse_delete_count(pending_result),
        "rate_counters": _parse_delete_count(rate_result),
        "meta_rate_counters": _parse_delete_count(meta_rate_result),
    }


def _parse_delete_count(result: str) -> int:
    return int(result.split()[-1]) if result.startswith("DELETE") else 0
