"""Pre-condicao de moeda das tools Meta que devolvem valores em BRL.

`exigir_brl` devolve `None` quando a conta e BRL e o envelope de erro quando nao e. As
excecoes da Graph (`MetaAccessDeniedError`, `MetaAdsFriendlyError`) sobem: quem chama
as converte com `meta_erro`, como antes.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from src.meta_ads.reports import run_meta_graph_get


async def exigir_brl(
    ad_account_id: str,
    *,
    manager_id: UUID,
    session_id: UUID,
    operacao: str,
    proposito: str,
) -> dict[str, Any] | None:
    """`None` se a conta esta em BRL; senao o envelope de erro de entrada.

    `operacao` e o nome da tool (audit e rate limit); `proposito` completa a frase
    "conta Meta em moeda X: <proposito> para contas em BRL".
    """
    conta = await run_meta_graph_get(
        manager_id=manager_id,
        session_id=session_id,
        ad_account_id=ad_account_id,
        edge=f"/{ad_account_id}",
        params={"fields": "currency"},
        operation_name=operacao,
        estimated_calls=1,
        audit_this_call=True,
        params_summary={"ad_account_id": ad_account_id, "call": "moeda"},
    )
    moeda = conta.get("currency")
    if moeda != "BRL":
        # Mesmo envelope de `erro_de_entrada` (src/mcp/tools/_meta_common.py): este modulo
        # fica abaixo da camada de tools e nao importa dela.
        return {
            "status": "error",
            "error_message": f"conta Meta em moeda {moeda!r}: {proposito} para contas em BRL",
        }
    return None
