"""Pre-condicao de moeda das tools Meta que devolvem valores em BRL.

`exigir_brl` devolve `None` quando a conta e BRL e o envelope de erro quando nao e. A moeda
vem da coluna `meta_ad_accounts.currency` (decisao de 10/11: a conta ja esta no inventario
que o gate exige, entao nao ha chamada a Graph so para isto). Conta sem linha ou sem moeda
no inventario recebe o mesmo envelope de moeda nao-BRL, com `None` no lugar da moeda.

Leitura idempotente em hot path -> `run_with_reconnect` (F76/F77).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from src.db import connection
from src.db.repositories import meta_ad_accounts


async def exigir_brl(
    ad_account_id: str,
    *,
    manager_id: UUID,
    session_id: UUID,
    operacao: str,
    proposito: str,
) -> dict[str, Any] | None:
    """`None` se a conta esta em BRL; senao o envelope de erro de entrada.

    `operacao` e o nome da tool; `proposito` completa a frase
    "conta Meta em moeda X: <proposito> para contas em BRL". `manager_id` e `session_id`
    ficam na assinatura (contrato da tarefa) mas a leitura do inventario nao os usa: o
    gate de acesso roda na primeira leitura da Graph de cada tool.
    """
    moeda = await connection.run_with_reconnect(
        lambda conn: meta_ad_accounts.currency_of(conn, ad_account_id)
    )
    if moeda != "BRL":
        # Mesmo envelope de `erro_de_entrada` (src/mcp/tools/_meta_common.py): este modulo
        # fica abaixo da camada de tools e nao importa dela.
        return {
            "status": "error",
            "error_message": f"conta Meta em moeda {moeda!r}: {proposito} para contas em BRL",
        }
    return None
