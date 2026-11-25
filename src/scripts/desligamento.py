"""Desligamento auditado: credenciais de gestor desativado e descomissionamento de contas.

Núcleo dos subcomandos `admin revogar-conexoes-de-inativos` e `admin descomissionar`
(`src/scripts/admin.py`), separado para ser testável com uma conexão real. Os dois só
escrevem com `apply=True`, numa transação, e gravam audit com `had_effect` (F179) — inclusive
quando não havia nada a fazer. Nenhuma linha é apagada: revogação e desativação são soft.
"""

from __future__ import annotations

import asyncpg

from src.db.repositories import audit_log, google_oauth_connections


async def revogar_conexoes_de_inativos(
    conn: asyncpg.Connection, *, apply: bool
) -> list[asyncpg.Record]:
    """Conexões OAuth vivas de gestor desativado; com `apply`, revoga todas e audita.

    Backfill do que o toggle passou a fazer na desativação (desenho de 25/11): os gestores
    desativados antes disso ficaram com a conexão viva."""
    if not apply:
        return await google_oauth_connections.list_live_of_inactive_managers(conn)
    async with conn.transaction():
        alvo = await google_oauth_connections.list_live_of_inactive_managers(conn)
        for linha in alvo:
            await google_oauth_connections.revoke(conn, linha["id"])
        await audit_log.record(
            conn,
            manager_id=None,
            session_id=None,
            customer_id=None,
            action_type="system",
            operation="cli_revoke_inactive_connections",
            target_count=len(alvo),
            params_summary={
                "conexoes": [
                    {"manager_email": r["manager_email"], "google_email": r["google_email"]}
                    for r in alvo
                ]
            },
            had_effect=bool(alvo),
        )
    return alvo
