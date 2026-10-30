"""Números do painel que o dashboard e o overview de admin mostram — um corpo só.

O dashboard (`routes/sessions.py`) e o overview (`routes/admin_overview.py`)
liam as mesmas contas por cópia, e cada cópia carregava o mesmo erro:

- "Quota MCP hoje" somava TODAS as linhas de `rate_counters`. Uma mutação reserva
  duas (o token global e `mgr:<uuid>`, F73), então contava em dobro.
- "Gestores ativos" contava só `status = 'active'`, ignorando `is_active` (F84:
  as duas colunas divergem e nada as sincroniza).
- O "dia" das séries era `occurred_at::date`, no fuso da sessão do banco (UTC):
  de 21h à meia-noite em Maceió/João Pessoa o evento caía no dia seguinte.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import asyncpg

FUSO_PAINEL = ZoneInfo("America/Sao_Paulo")


def dias_do_painel(n: int, *, now: datetime | None = None) -> list[date]:
    """Os `n` dias que terminam HOJE no fuso do painel, do mais antigo ao mais novo."""
    hoje = (now or datetime.now(UTC)).astimezone(FUSO_PAINEL).date()
    return [hoje - timedelta(days=i) for i in range(n - 1, -1, -1)]


def inicio_do_dia(d: date) -> datetime:
    """Meia-noite de `d` no fuso do painel, como instante absoluto."""
    return datetime(d.year, d.month, d.day, tzinfo=FUSO_PAINEL)


async def contagem_por_dia(
    conn: asyncpg.Connection,
    dias: list[date],
    *,
    manager_id: UUID | None = None,
) -> list[int]:
    """Chamadas de audit por dia de `dias`, com zero nos dias vazios.

    O filtro é um intervalo sobre `occurred_at` (sargável: usa o índice); o
    `AT TIME ZONE` só aparece no GROUP BY, onde converte a linha já filtrada.
    """
    rows = await conn.fetch(
        """SELECT (occurred_at AT TIME ZONE 'America/Sao_Paulo')::date AS d, count(*) AS c
           FROM audit_log
           WHERE occurred_at >= $1 AND occurred_at < $2
             AND ($3::uuid IS NULL OR manager_id = $3)
           GROUP BY 1""",
        inicio_do_dia(dias[0]),
        inicio_do_dia(dias[-1] + timedelta(days=1)),
        manager_id,
    )
    por_dia = {r["d"]: r["c"] for r in rows}
    return [por_dia.get(d, 0) for d in dias]


async def admin_ops(conn: asyncpg.Connection) -> dict[str, Any]:
    """Quota MCP de hoje, erros 24h e gestores ativos/total."""
    return {
        # `mgr:<uuid>` é o cap por gestor (F73): reserva PARALELA à do token, não
        # soma a ela. Contar as duas contava cada mutação em dobro.
        "quota_used": await conn.fetchval(
            "SELECT COALESCE(SUM(operations_used), 0) FROM rate_counters "
            "WHERE date = current_date AND developer_token_id NOT LIKE 'mgr:%'"
        )
        or 0,
        "errors_24h": await conn.fetchval(
            "SELECT count(*) FROM audit_log "
            "WHERE status='error' AND occurred_at > now() - interval '24 hours'"
        )
        or 0,
        # F84: desativado é is_active=false OU status='inactive'. Não se
        # sincronizam as colunas; o predicado é Manager.is_deactivated, e este é
        # o seu complemento em SQL ('invited' também fica de fora).
        "active_managers": await conn.fetchval(
            "SELECT count(*) FROM managers WHERE status = 'active' AND is_active"
        )
        or 0,
        "total_managers": await conn.fetchval("SELECT count(*) FROM managers") or 0,
    }
