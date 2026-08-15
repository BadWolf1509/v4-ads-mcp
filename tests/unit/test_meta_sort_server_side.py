"""F88 (parte final): a ordenacao por gasto passa a ser SERVER-SIDE.

Ate aqui as tools Meta liam ate 5 paginas e ordenavam no cliente. Funciona, mas
o `truncated` carregava um aviso pesado: numa conta que excedesse o teto, o "top
gastadores" podia legitimamente NAO conter o maior gastador — o corte acontecia
antes de qualquer ordenacao existir.

Com `sort=spend_descending` o servidor ordena ANTES de cortar, entao a 1a pagina
JA e o topo. O `truncated` deixa de significar "o ranking pode estar errado" e
passa a significar so "existem mais linhas abaixo do topo" — que e informacao de
completude, nao risco de correcao. E a mesma forma do lado Google
(`ORDER BY metrics.cost_micros DESC LIMIT n`).

Validado empiricamente contra a API real antes desta implementacao
(`scripts/probe_meta_sort.py`), incluindo o teste que decide: um valor invalido
de `sort` devolve **HTTP 400** `The parameter value of "sort" is invalid`. Sem
isso, um 200 nao provaria nada — a Graph API tem historico de aceitar calada
param que nao entende, que foi como F53/F54/F55 nasceram. A combinacao com
`breakdowns` (incluindo `hourly_stats_aggregated_by_advertiser_time_zone`, 48
linhas) tambem foi sondada antes de aplicar o sort la.
"""

from __future__ import annotations

from datetime import date

from src.meta_ads.insights import build_insights_call


def _params(**extra):
    _edge, params = build_insights_call(
        level="campaign",
        ad_account_id="act_123",
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
        limit=50,
        **extra,
    )
    return params


def test_query_pede_ordenacao_por_gasto_ao_servidor() -> None:
    """F88: sem isto, o `limit` corta um conjunto nao-ordenado."""
    assert _params()["sort"] == "spend_descending"


def test_ordenacao_vale_tambem_com_breakdown() -> None:
    """F88: o builder e compartilhado com `meta_get_performance_breakdown`.

    A combinacao foi sondada antes (3 breakdowns + hourly) — nao entrou por
    analogia com a query sem breakdown.
    """
    params = _params(breakdowns=["publisher_platform"])
    assert params["sort"] == "spend_descending"
    assert params["breakdowns"] == "publisher_platform"


def test_truncated_nao_afirma_mais_que_o_ranking_pode_estar_errado() -> None:
    """F88: o aviso antigo vira MENTIRA quando o servidor ordena antes de cortar.

    Dizer "o ranking pode nao incluir o maior gastador" quando ele
    necessariamente inclui e pior que nao avisar nada: manda o gestor
    desconfiar de um dado correto.
    """
    from src.mcp.tools import _meta_performance, meta_get_performance_breakdown

    for modulo in (_meta_performance, meta_get_performance_breakdown):
        fonte = __import__("inspect").getsource(modulo)
        assert "pode não incluir o maior gastador" not in fonte, (
            f"{modulo.__name__}: aviso obsoleto — com sort server-side o topo "
            "SEMPRE vem; `truncated` agora e so completude"
        )


def test_descriptions_nao_prometem_o_comportamento_antigo() -> None:
    """F88: a description e o contrato que o cliente LLM le antes de chamar."""
    import importlib

    tools = (
        "meta_get_campaign_performance",
        "meta_get_ad_set_performance",
        "meta_get_ad_performance",
        "meta_get_performance_breakdown",
    )
    for nome in tools:
        fonte = __import__("inspect").getsource(importlib.import_module(f"src.mcp.tools.{nome}"))
        assert "o topo pode estar incompleto" not in fonte, (
            f"{nome}: description ainda descreve o ranking antigo (client-side)"
        )
