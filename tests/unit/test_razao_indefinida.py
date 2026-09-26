"""Razao sem denominador e indefinida, nao zero (spec 2026-09-25, §4.2).

CPA R$ 0,00 com gasto e zero conversao se le como o melhor CPA possivel; CPC
R$ 0,00 sem clique, como clique de graca. A regra e uma so (`razao()`), e o guard
AST abaixo impede a forma `x / y if y else 0` de voltar em qualquer tool Google.
"""

from __future__ import annotations

import ast
import importlib
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.google_ads.queries._common import arredondado, em_moeda, percentual, razao
from tests.unit import _guard_harness as h


def test_razao_sem_denominador_e_none() -> None:
    assert razao(5, 0) is None
    assert razao(5, 0.0) is None
    assert razao(None, 3) is None


def test_os_repassadores_deixam_none_passar() -> None:
    assert arredondado(None, 2) is None
    assert em_moeda(None) is None
    assert percentual(None) is None


@pytest.mark.parametrize("a,b", [(3, 7), (1, 3), (5_000_000, 3), (2, 9.5)])
def test_fora_do_zero_o_valor_e_o_de_antes(a: float, b: float) -> None:
    """Controle: a troca nao pode mudar numero que ja existia."""
    assert arredondado(razao(a, b), 4) == round(a / b, 4)
    assert em_moeda(razao(a, b)) == round((a / b) / 1_000_000.0, 2)
    assert arredondado(percentual(razao(a, b)), 2) == round(a / b * 100, 2)


def _divisoes_que_viram_zero(arv: ast.AST) -> list[int]:
    """`<algo que divide> if <cond> else <0|0.0|None>`, nas duas orientacoes —
    a forma que a regra proibe. F4: conta tambem quando quem divide e o
    `orelse` (`0 if not y else x / y`) e quando a constante do outro lado e
    `None`, nao so `0`/`0.0`."""
    achados = []
    for no in ast.walk(arv):
        if not isinstance(no, ast.IfExp):
            continue
        for quem_divide, constante in ((no.body, no.orelse), (no.orelse, no.body)):
            if (
                isinstance(constante, ast.Constant)
                and not isinstance(constante.value, bool)
                and constante.value in (0, 0.0, None)
                and any(
                    isinstance(s, ast.BinOp) and isinstance(s.op, ast.Div)
                    for s in ast.walk(quem_divide)
                )
            ):
                achados.append(no.lineno)
                break
    return achados


def test_o_detector_enxerga_a_forma_proibida() -> None:
    """Controle positivo: sem ele, o guard abaixo passaria verde por nao casar nada."""
    arv = ast.parse("x = {'ctr': round(c / i, 4) if i else 0.0, 'n': 0}")
    assert _divisoes_que_viram_zero(arv) == [1]

    invertida = ast.parse("x = 0 if not i else c / i")
    assert _divisoes_que_viram_zero(invertida) == [1]

    com_none = ast.parse("x = c / i if i else None")
    assert _divisoes_que_viram_zero(com_none) == [1]


def test_nenhuma_razao_vira_zero_quando_o_denominador_some() -> None:
    ofensores = [
        f"{h.rel(p)}:{linha}"
        for raiz in (h.SRC / "mcp" / "tools", h.SRC / "google_ads")
        for p in h.fontes_py(raiz)
        for linha in _divisoes_que_viram_zero(h.arvore(p))
    ]
    assert not ofensores, f"regra de denominador zero escrita a mao — use `razao()`: {ofensores}"


_FORMATADORES_POR_LINHA = [
    "get_ad_group_performance",
    "get_ad_performance",
    "get_audience_performance",
    "get_campaign_performance",
    "get_device_performance",
    "get_geo_performance",
    "get_hourly_performance",
    "get_keyword_performance",
    "get_search_terms_report",
]


@pytest.mark.parametrize("modulo", _FORMATADORES_POR_LINHA)
def test_linha_sem_impressao_nem_clique_tem_razoes_indefinidas(modulo: str) -> None:
    """O guard prova que a forma sumiu; este prova que a linha zerada NAO derruba a
    tool (um `clicks / impr` cru passaria no guard e daria ZeroDivisionError)."""
    mod = importlib.import_module(f"src.mcp.tools.{modulo}")
    row = MagicMock()
    row.metrics.impressions = 0
    row.metrics.clicks = 0
    row.metrics.cost_micros = 5_000_000
    row.metrics.conversions = 0.0
    row.metrics.conversions_value = 0.0
    out = mod._row_formatter(row)
    assert out["ctr"] is None
    assert out["cpc_brl"] is None


def test_breakdown_com_metrica_zerada_tem_razoes_indefinidas() -> None:
    from src.google_ads.performance_breakdown import _common_metrics

    m = SimpleNamespace(
        impressions=0, clicks=0, cost_micros=0, conversions=0.0, conversions_value=0.0
    )
    out = _common_metrics(m)
    assert out["ctr"] is None
    assert out["cpc_brl"] is None


def test_overview_sem_linha_nenhuma_diz_que_nao_ha_dado() -> None:
    from src.mcp.tools.get_account_overview import _aggregate

    out = _aggregate([])
    assert out["sem_dados_no_periodo"] is True
    assert out["impressions"] == 0
    for chave in ("ctr", "average_cpc_brl", "cost_per_conversion_brl", "roas"):
        assert out[chave] is None


def test_overview_com_gasto_e_zero_conversao_nao_tem_cpa() -> None:
    from src.mcp.tools.get_account_overview import _aggregate

    out = _aggregate(
        [
            {
                "impressions": 100,
                "clicks": 10,
                "cost_micros": 5_000_000,
                "conversions": 0.0,
                "conversions_value": 0.0,
            }
        ]
    )
    assert out["sem_dados_no_periodo"] is False
    assert out["cost_per_conversion_brl"] is None  # era 0.0: "o melhor CPA possivel"
    assert out["ctr"] == 0.1
    assert out["average_cpc_brl"] == 0.5


def test_overview_com_custo_abaixo_de_meio_centavo_nao_quebra_o_roas() -> None:
    """F2: `cost_micros` entre 1 e 4.999 arredonda pra 0.0 em `micros_to_currency`.

    O guarda antigo era `if cost` (em micros, entao truthy) dividindo por esse
    0.0: `ZeroDivisionError`. `razao()` confere o denominador JA convertido —
    `cost_brl` fica 0.0 (verdade: o custo real e menor que 1 centavo) e `roas`
    vira `None` (indefinido), sem levantar.
    """
    from src.mcp.tools.get_account_overview import _aggregate

    out = _aggregate(
        [
            {
                "impressions": 100,
                "clicks": 10,
                "cost_micros": 3_000,
                "conversions": 1.0,
                "conversions_value": 50.0,
            }
        ]
    )
    assert out["sem_dados_no_periodo"] is False
    assert out["cost_brl"] == 0.0
    assert out["roas"] is None


def test_funil_distingue_zero_medido_de_indefinido() -> None:
    from src.mcp.tools.get_funnel_metrics import _build_funnel

    out = _build_funnel(
        [
            {
                "impressions": 100,
                "clicks": 0,
                "cost_micros": 0,
                "conversions": 0.0,
                "conversions_value": 0.0,
            }
        ]
    )
    assert out["stages"][1]["rate_from_prev_pct"] == 0.0  # 0 cliques / 100 impr: zero MEDIDO
    assert out["stages"][2]["rate_from_prev_pct"] is None  # 0 conv / 0 cliques: indefinido
    assert out["totals"]["roas"] is None
    assert out["totals"]["cost_per_conversion_brl"] is None
    assert out["totals"]["average_order_value_brl"] is None


def test_pacing_sem_orcamento_nao_vira_zero_porcento() -> None:
    from src.mcp.tools.get_budget_pacing import _project

    (c,) = _project(
        [
            {
                "campaign_id": "1",
                "campaign_name": "c",
                "daily_budget_brl": 0.0,
                "delivery_method": "STANDARD",
                "cost_micros_today": 3_100_000_000,
            }
        ],
        today=date(2026, 8, 31),
    )
    assert c["spent_pct_of_monthly_budget"] is None
    assert c["projection_vs_budget_pct"] is None
    # a projecao do GASTO existe: nao depende do orcamento
    assert c["projected_monthly_brl"] == 3100.0


_FRASE_DA_RAZAO = "Razao com denominador zero vem null (indefinida), nao 0."
# O `delta_pct` do preview de orcamento (e o de `apply_recommendation`, que
# depois do F4 tambem chama `razao()` no mesmo `_delta_pct`) tambem pode vir
# null; quem explica e o `blast_summary`/resumo da mutacao ("variacao
# indefinida"), nao a description da tool de mutacao.
_MUTACAO_COM_RAZAO = {"update_campaign_budget", "apply_recommendation"}


def _tools_com_razao() -> set[str]:
    """Tool cuja resposta carrega razao: o modulo importa `razao`, ou monta a linha
    pelo `performance_breakdown`, que calcula a razao la dentro."""
    achadas = set()
    for p in h.fontes_py(h.SRC / "mcp" / "tools"):
        for no in ast.walk(h.arvore(p)):
            if isinstance(no, ast.ImportFrom) and (
                no.module == "src.google_ads.performance_breakdown"
                or (
                    no.module == "src.google_ads.queries._common"
                    and any(a.name == "razao" for a in no.names)
                )
            ):
                achadas.add(p.stem)
    return achadas - _MUTACAO_COM_RAZAO


def test_toda_tool_com_razao_avisa_na_description() -> None:
    """O contrato mudou de numero para null: quem le a tool (o LLM) tem de saber.

    A lista sai da varredura, nao da memoria: tool nova que use `razao` cai aqui.
    """
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    nomes = _tools_com_razao()
    assert len(nomes) >= 13, f"piso medido em 26/09: 13 tools; a varredura achou {sorted(nomes)}"
    sem_aviso = []
    for nome in sorted(nomes):
        tool = get_tool(nome)
        assert tool is not None, f"`{nome}` nao esta no registry com o nome do modulo"
        if _FRASE_DA_RAZAO not in tool.description:
            sem_aviso.append(nome)
    assert not sem_aviso, f"tool com razao cuja description nao avisa do null: {sem_aviso}"
