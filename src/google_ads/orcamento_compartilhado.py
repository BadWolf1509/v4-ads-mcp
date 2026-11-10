"""Bloco de aviso de orcamento compartilhado (spec §4.3): avisa, nao recusa.

Duas tools de mutate montam o MESMO bloco — `update_campaign_budget` (preview
`shared_budget`, um bloco) e `update_ad_schedule` (preview `shared_budgets`, lista).
As 8 chaves moram aqui, num lugar so: quem aprendeu a ler o aviso numa reconhece na
outra, e uma chave nova nasce nas duas.

A funcao e PURA. A leitura das irmas (`campaigns_on_budgets_query`) e a ordenacao
do `campaigns_in_batch` ficam nas tools: cada uma tem o seu criterio de "lote" e o
seu texto de consequencia.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def montar_bloco(
    *,
    budget_id: str,
    budget_resource_name: str,
    amount_brl: float,
    irmas: list[dict[str, Any]],
    no_lote: Callable[[str], bool],
    sufixo_aviso: str,
) -> dict[str, Any]:
    """Monta o bloco de UM orcamento compartilhado.

    `irmas`: todas as campanhas vivas desse orcamento (rows de
    `parse_campaign_on_budget_row`). `no_lote(campaign_id)` diz se a campanha e
    alvo da mutacao. `sufixo_aviso` e a parte do `warning_pt` que descreve a
    consequencia, que difere entre as tools (mudar o valor ATINGE; desligar
    faixa REALOCA).

    `campaigns_in_batch` sai na ordem de `irmas`; quem precisa de ordem estavel
    ordena a entrada.
    """
    dentro = [c["campaign_id"] for c in irmas if no_lote(c["campaign_id"])]
    fora = [
        {
            "campaign_id": c["campaign_id"],
            "campaign_name": c["campaign_name"],
            "status": c["status"],
        }
        for c in irmas
        if not no_lote(c["campaign_id"])
    ]
    ativas = sum(1 for c in irmas if c["status"] == "ENABLED")
    ativas_fora_do_lote = sum(1 for c in fora if c["status"] == "ENABLED")
    return {
        "budget_id": budget_id,
        "budget_resource_name": budget_resource_name,
        "explicitly_shared": True,
        "amount_brl": amount_brl,
        "campaigns_in_batch": dentro,
        "campaigns_outside_batch": fora,
        "ativas_fora_do_lote": ativas_fora_do_lote,
        "warning_pt": (
            f"Orcamento compartilhado {budget_id} (R$ {amount_brl:.2f}/dia) "
            f"e de {len(irmas)} campanha(s), {ativas} ativa(s); {len(dentro)} no lote, "
            f"{len(fora)} fora ({ativas_fora_do_lote} ativa(s)). {sufixo_aviso}"
        ),
    }
