"""F89: o parser nao pode devolver campo que a query nunca pediu.

Os F53/F54 removeram `effective_status`, `billing_event`, `daily_budget` e
`creative_id` das listas `INSIGHTS_FIELDS_*` porque a Meta Insights API os
rejeita (sao metadata de entidade, vivem em /campaigns, /adsets, /ads — F55).
Mas o fix parou na query: `parse_insights_row` continuou LENDO os quatro. Como
nunca chegam no row, o resultado era constante em 100% das linhas de 4 tools:

    effective_status       -> "UNKNOWN"
    effective_status_label -> "DESCONHECIDO"
    billing_event          -> None
    daily_budget_brl       -> None
    creative_id            -> None

Pra um consumidor LLM isso e PIOR que a ausencia do campo: ele reporta "status
desconhecido" com confianca, ou preenche a lacuna sozinho. E a description do
`meta_get_campaign_performance` ainda instruia o gestor a "filtrar client-side
via prompt natural" por status — impossivel, o campo e literal fixo.

O guard no fim fecha a classe: todo campo que o parser le do row tem que estar
na lista que a query pede.
"""

from __future__ import annotations

import ast

import pytest

from src.meta_ads.insights import (
    INSIGHTS_FIELDS_AD,
    INSIGHTS_FIELDS_ADSET,
    INSIGHTS_FIELDS_CAMPAIGN,
    parse_insights_row,
)
from tests.unit import _guard_harness as h

_ROW_CAMPAIGN = {
    "campaign_id": "23851",
    "campaign_name": "Prospec | JP",
    "objective": "OUTCOME_LEADS",
    "spend": "411.83",
    "impressions": "12000",
    "clicks": "340",
    "ctr": "2.83",
    "cpc": "1.21",
    "reach": "9000",
    "frequency": "1.33",
}


@pytest.mark.parametrize("campo", ["effective_status", "effective_status_label"])
def test_status_fantasma_sai_do_resultado_em_todos_os_niveis(campo: str) -> None:
    """F89: era constante em 100% das linhas — melhor ausente que inventado."""
    for level in ("campaign", "adset", "ad"):
        out = parse_insights_row(dict(_ROW_CAMPAIGN), level)  # type: ignore[arg-type]
        assert campo not in out, f"{campo} ainda presente no nivel {level}"


def test_adset_nao_devolve_billing_event_nem_daily_budget() -> None:
    """F54 removeu os dois da query; o parser seguia lendo -> None sempre."""
    out = parse_insights_row(dict(_ROW_CAMPAIGN), "adset")
    assert "billing_event" not in out
    assert "daily_budget_brl" not in out


def test_ad_nao_devolve_creative_id() -> None:
    out = parse_insights_row(dict(_ROW_CAMPAIGN), "ad")
    assert "creative_id" not in out


def test_metricas_reais_seguem_intactas() -> None:
    """Regressao: tirar os fantasmas nao pode levar junto o que funciona."""
    out = parse_insights_row(dict(_ROW_CAMPAIGN), "campaign")
    assert out["campaign_name"] == "Prospec | JP"
    assert out["objective"] == "OUTCOME_LEADS"
    assert out["spend_brl"] == 411.83
    assert out["impressions"] == 12000
    assert out["clicks"] == 340
    assert out["ctr"] == 0.0283  # Meta manda %, expomos decimal
    assert out["reach"] == 9000


def test_breakdown_continua_exposto() -> None:
    row = dict(_ROW_CAMPAIGN) | {"publisher_platform": "instagram"}
    out = parse_insights_row(row, "campaign", breakdown_keys=["publisher_platform"])
    assert out["breakdown"] == {"publisher_platform": "instagram"}


def test_parser_nao_le_campo_que_a_query_nao_pede() -> None:
    """Guard da classe F89: `row.get("x")` exige que "x" esteja em INSIGHTS_FIELDS_*.

    E o que faltava pra fechar F53/F54 — aqueles fixes corrigiram a QUERY e
    deixaram o parser pedindo campo inexistente. Le o AST de `parse_insights_row`
    e cruza cada literal lido com a uniao das listas que a query realmente manda.
    Chaves de breakdown sao dinamicas (`row.get(key)`), entao nao aparecem como
    constante e ficam naturalmente fora do check.
    """
    pedidos = set(INSIGHTS_FIELDS_CAMPAIGN) | set(INSIGHTS_FIELDS_ADSET) | set(INSIGHTS_FIELDS_AD)

    fonte = (h.SRC / "meta_ads" / "insights.py").read_text(encoding="utf-8")
    tree = ast.parse(fonte)
    alvo = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "parse_insights_row"
    )

    lidos: set[str] = set()
    for node in ast.walk(alvo):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "row"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            lidos.add(node.args[0].value)

    fantasmas = sorted(lidos - pedidos)
    assert not fantasmas, (
        f"F89 — parse_insights_row le campo que a query nao pede: {fantasmas}. "
        "Campo ausente do row vira valor constante (None/'UNKNOWN') em 100% das "
        "linhas e o consumidor LLM reporta como se fosse dado. Ou inclua o campo "
        "em INSIGHTS_FIELDS_* (se a Meta Insights aceitar — ver F53/F54), ou pare "
        "de le-lo no parser."
    )
