"""C5: o top-N tem que ser cortado PELA metrica pedida, no Google.

A tool ordenava por custo e reordenava as N linhas ja cortadas no cliente. O
sintoma nao e ordem trocada — e **linha ausente**: a keyword barata que converte
muito nunca entrava no top-N por custo, entao nenhum `sorted()` posterior podia
traze-la de volta.

Por isso o duble de `run_report` aqui **le a query** e obedece ao `ORDER BY` e ao
`LIMIT` dela, como o Google faria. Um mock que devolvesse sempre a mesma lista
nao conseguiria expressar este defeito (modo de falha conhecido no repo): as duas
implementacoes, a boa e a quebrada, veriam as mesmas linhas.
"""

import re
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

# GAQL do `ORDER BY` -> chave da linha JA FORMATADA (o `row_formatter` roda
# dentro do `run_report`, entao o duble devolve o formato de saida).
_CHAVE_DA_ORDEM = {
    "metrics.cost_micros": "cost_brl",
    "metrics.conversions": "conversions",
    "metrics.clicks": "clicks",
    "metrics.impressions": "impressions",
}

_BARATA = "barata que converte"

# Universo de 4 keywords desenhado para que o vencedor seja DIFERENTE em cada
# uma das quatro metricas — com `top_n=3`, cada metrica deixa uma linha de fora,
# e sob custo a que fica de fora e justamente a que mais converte.
_KEYWORDS: list[dict[str, Any]] = [
    {
        "keyword_text": "queima orcamento",
        "cost_brl": 1000.0,
        "conversions": 1.0,
        "clicks": 120,
        "impressions": 4000,
    },
    {
        "keyword_text": "caro do meio",
        "cost_brl": 900.0,
        "conversions": 2.0,
        "clicks": 900,
        "impressions": 3000,
    },
    {
        "keyword_text": "caro de baixo",
        "cost_brl": 800.0,
        "conversions": 3.0,
        "clicks": 80,
        "impressions": 90000,
    },
    {
        "keyword_text": _BARATA,
        "cost_brl": 12.5,
        "conversions": 47.0,
        "clicks": 20,
        "impressions": 100,
    },
]

_CREATIVES: list[dict[str, Any]] = [
    {"ad_id": "caro-1", "cost_brl": 700.0, "conversions": 1.0, "clicks": 300, "impressions": 5000},
    {"ad_id": "caro-2", "cost_brl": 600.0, "conversions": 2.0, "clicks": 200, "impressions": 4000},
    {"ad_id": "caro-3", "cost_brl": 500.0, "conversions": 3.0, "clicks": 100, "impressions": 3000},
    {"ad_id": "barato-9", "cost_brl": 3.0, "conversions": 31.0, "clicks": 9, "impressions": 40},
]

_TOP_N = 3

_VENCEDOR_ESPERADO = {
    "cost": "queima orcamento",
    "conversions": _BARATA,
    "clicks": "caro do meio",
    "impressions": "caro de baixo",
}


def _fake_google(*_args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """Ordena e corta como o Google: pela clausula que a PROPRIA query pede."""
    query = kwargs["query"]
    ordem = re.search(r"ORDER BY (\S+) DESC", query)
    limite = re.search(r"LIMIT (\d+)", query)
    assert ordem and limite, f"query sem ORDER BY/LIMIT reconheciveis:\n{query}"
    chave = _CHAVE_DA_ORDEM[ordem.group(1)]  # metrica fora do mapa estoura aqui
    universo = _KEYWORDS if "FROM keyword_view" in query else _CREATIVES
    return sorted(universo, key=lambda linha: -linha[chave])[: int(limite.group(1))]


@pytest.fixture(autouse=True)
def _ctx():
    from datetime import date

    from src.mcp.context import McpRequestContext, clear_current, set_current

    async def _hoje(customer_id: str, *, now: Any = None) -> date:
        return date(2026, 5, 15)

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    # F141: a tool resolve `hoje` no fuso da conta lendo o DB; aqui nao ha pool.
    with patch("src.mcp.tools.get_top_keywords_creatives.resolve_account_today", _hoje):
        yield
    clear_current()


async def _rodar(metric: str) -> dict[str, Any]:
    from src.mcp.tools.get_top_keywords_creatives import get_top_keywords_creatives

    with patch(
        "src.mcp.tools.get_top_keywords_creatives.run_report",
        AsyncMock(side_effect=_fake_google),
    ):
        return await get_top_keywords_creatives(
            {
                "customer_id": "7862230676",
                "date_range": "LAST_7_DAYS",
                "top_n": _TOP_N,
                "metric": metric,
            }
        )


@pytest.mark.asyncio
async def test_top_por_conversoes_encontra_a_barata_que_converte() -> None:
    """A keyword de MENOR custo e MAIOR conversao: antes do fix ela ficava fora,
    porque o corte era por custo e o re-sort so reordenava o que sobrou.

    Este e o teste que falha contra o codigo pre-fix pelo MOTIVO CERTO: nao e
    ordem trocada, e linha ausente.
    """
    sob_custo = await _rodar("cost")
    ausente_sob_custo = [k["keyword_text"] for k in sob_custo["top_keywords"]]
    # Controle positivo: sem isto o teste passaria mesmo num universo em que a
    # barata entrasse no top-N por custo — ou seja, sem bug para provar.
    assert _BARATA not in ausente_sob_custo, (
        "controle: com top_n=3 a barata TEM que ficar fora do top por custo; "
        "so assim o caso e capaz de distinguir o corte certo do errado"
    )

    sob_conversoes = await _rodar("conversions")
    presentes = [k["keyword_text"] for k in sob_conversoes["top_keywords"]]
    assert _BARATA in presentes, (
        "a keyword de maior conversao NAO veio no top por conversoes — o corte "
        f"continua sendo por custo. Vieram: {presentes}"
    )


@pytest.mark.asyncio
async def test_cada_metrica_traz_o_seu_proprio_vencedor() -> None:
    """A generalizacao: para cada uma das quatro metricas, o topo devolvido e o
    topo DAQUELA coluna. Falha contra qualquer implementacao que fixe o corte em
    uma coluna so — inclusive a que fixasse em `conversions` para passar no teste
    de cima.
    """
    for metric, vencedor in _VENCEDOR_ESPERADO.items():
        resultado = await _rodar(metric)
        textos = [k["keyword_text"] for k in resultado["top_keywords"]]
        assert vencedor in textos, f"{metric}: {vencedor} nao veio; vieram {textos}"
        assert textos[0] == vencedor, f"{metric}: topo era {textos[0]}, esperado {vencedor}"


@pytest.mark.asyncio
async def test_creatives_sofrem_o_mesmo_corte_e_o_mesmo_fix() -> None:
    """Mesma falha, segunda superficie: `top_creatives_query` tambem cortava por
    custo. O RSA barato que converte tem que aparecer sob `conversions`.
    """
    sob_custo = await _rodar("cost")
    assert "barato-9" not in [a["ad_id"] for a in sob_custo["top_creatives"]], (
        "controle: o RSA barato tem que ficar fora do top por custo"
    )

    sob_conversoes = await _rodar("conversions")
    ids = [a["ad_id"] for a in sob_conversoes["top_creatives"]]
    assert ids[0] == "barato-9", f"top_creatives nao seguiu a metrica; vieram {ids}"


@pytest.mark.asyncio
async def test_devolve_exatamente_top_n_linhas() -> None:
    """`top_n` e contrato, nao teto: quem pede 3 recebe 3. Guarda contra um fix
    que passasse a pedir `top_n + 1` ao Google (a linha sentinela do
    `aplicar_limite`) — aqui nao ha ninguem aparando depois, entao ela vazaria
    direto para o gestor.
    """
    resultado = await _rodar("conversions")
    assert len(resultado["top_keywords"]) == _TOP_N
    assert len(resultado["top_creatives"]) == _TOP_N
    assert resultado["metric"] == "conversions"
