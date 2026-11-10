"""Pre-condicao de moeda das tools Meta que devolvem valores em BRL.

`exigir_brl` devolve `None` quando a conta e BRL e o envelope de erro quando nao e. A moeda
vem da coluna `meta_ad_accounts.currency` (decisao de 10/11: o inventario ja guarda a moeda,
entao nao ha chamada a Graph so para isto). O gate de acesso so roda depois, dentro de
`run_meta_graph_get`; por isso a leitura consulta antes `can_manager_access`. Conta sem linha
ou sem moeda no inventario recebe o mesmo envelope de moeda nao-BRL, com `None` no lugar
da moeda.

Leitura idempotente em hot path -> `run_with_reconnect` (F76/F77).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from src.db import connection
from src.db.repositories import manager_meta_account_access, meta_ad_accounts


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
    "conta Meta em moeda X: <proposito> para contas em BRL".

    A moeda vem do inventario, lido ANTES do gate de `run_meta_graph_get`. Para nao revelar
    a moeda de conta que o gestor nao pode ver, consulta primeiro a mesma
    `can_manager_access` do gate; negado, devolve `None` sem ler a moeda e a leitura gateada
    seguinte da tool nega e audita. `session_id` fica na assinatura do contrato.
    """

    async def _ler(conn: Any) -> tuple[bool, str | None]:
        if not await manager_meta_account_access.can_manager_access(
            conn, manager_id, ad_account_id, level="read"
        ):
            return False, None
        return True, await meta_ad_accounts.currency_of(conn, ad_account_id)

    permitido, moeda = await connection.run_with_reconnect(_ler)
    if not permitido:
        return None
    if moeda != "BRL":
        # Mesmo envelope de `erro_de_entrada` (src/mcp/tools/_meta_common.py): este modulo
        # fica abaixo da camada de tools e nao importa dela.
        return {
            "status": "error",
            "error_message": f"conta Meta em moeda {moeda!r}: {proposito} para contas em BRL",
        }
    return None
