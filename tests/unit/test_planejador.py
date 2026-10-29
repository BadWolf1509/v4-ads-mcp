"""Modulo puro do planejador: presenca de campo, sazonalidade e uniao por origem.

Usa as mensagens reais do SDK (v25), nao mocks: MagicMock aceitaria qualquer
atributo e mascararia a leitura sem presenca.
"""

from __future__ import annotations

from google.ads.googleads.v25.common.types.keyword_plan_common import (
    KeywordPlanHistoricalMetrics,
    MonthlySearchVolume,
)
from google.ads.googleads.v25.enums.types.keyword_plan_competition_level import (
    KeywordPlanCompetitionLevelEnum,
)
from google.ads.googleads.v25.enums.types.month_of_year import MonthOfYearEnum

from src.google_ads.planejador import (
    Metricas,
    metricas_do_proto,
    ordenar_e_cortar,
    sazonalidade,
    unir,
    volume_maximo,
)

_COMP = KeywordPlanCompetitionLevelEnum.KeywordPlanCompetitionLevel
_MES = MonthOfYearEnum.MonthOfYear
_TODOS_NONE = {
    "volume_mensal": None,
    "concorrencia": None,
    "indice_concorrencia": None,
    "cpc_topo_min_brl": None,
    "cpc_topo_max_brl": None,
    "sazonalidade": None,
}


def _mes(ano: int, mes: int, buscas: int) -> MonthlySearchVolume:
    # enum Google: JANUARY=2 ... DECEMBER=13
    return MonthlySearchVolume(year=ano, month=_MES(mes + 1), monthly_searches=buscas)


def _doze(valores: list[int]) -> list[MonthlySearchVolume]:
    # nov/2025 .. out/2026
    meses = [(2025, 11), (2025, 12)] + [(2026, m) for m in range(1, 11)]
    return [_mes(a, m, v) for (a, m), v in zip(meses, valores, strict=True)]


def _m(volume: int | None) -> Metricas:
    return {**_TODOS_NONE, "volume_mensal": volume}  # type: ignore[typeddict-item]


def test_bloco_ausente_e_tudo_none() -> None:
    assert metricas_do_proto(None) == _TODOS_NONE


def test_volume_presente_e_lido() -> None:
    m = KeywordPlanHistoricalMetrics(
        avg_monthly_searches=8100,
        competition=_COMP.HIGH,
        competition_index=76,
        low_top_of_page_bid_micros=3_000_000,
        high_top_of_page_bid_micros=12_500_000,
    )
    r = metricas_do_proto(m)
    assert r["volume_mensal"] == 8100
    assert r["concorrencia"] == "HIGH"
    assert r["indice_concorrencia"] == 76
    assert r["cpc_topo_min_brl"] == 3.0
    assert r["cpc_topo_max_brl"] == 12.5


def test_volume_ausente_nao_vira_zero() -> None:
    r = metricas_do_proto(KeywordPlanHistoricalMetrics())
    assert r["volume_mensal"] is None
    assert r["concorrencia"] is None
    assert r["indice_concorrencia"] is None
    assert r["cpc_topo_min_brl"] is None
    assert r["cpc_topo_max_brl"] is None


def test_volume_zero_medido_continua_zero() -> None:
    m = KeywordPlanHistoricalMetrics(avg_monthly_searches=0)
    assert metricas_do_proto(m)["volume_mensal"] == 0


def test_sazonalidade_pico_vale_variacao() -> None:
    r = sazonalidade(_doze([100 + 10 * i for i in range(12)]))
    assert r is not None
    assert r["mes_pico"] == "2026-10"
    assert r["mes_vale"] == "2025-11"
    assert r["variacao_12m_pct"] == 110.0


def test_sazonalidade_primeiro_zero_e_none() -> None:
    r = sazonalidade(_doze([0] + [50] * 11))
    assert r is not None
    assert r["variacao_12m_pct"] is None


def test_sazonalidade_menos_de_12_meses_e_none() -> None:
    assert sazonalidade(_doze([10] * 12)[:11]) is None


def test_sazonalidade_empate_fica_com_o_mais_recente() -> None:
    r = sazonalidade(_doze([5, 9, 9, 1, 1, 3, 3, 3, 3, 3, 3, 3]))
    assert r is not None
    assert r["mes_pico"] == "2026-01"
    assert r["mes_vale"] == "2026-03"


def test_unir_mesma_ideia_duas_origens() -> None:
    m = _m(40)
    r = unir(
        [
            ("semente", "JP", [("aluguel de andaime", m)]),
            ("site", "JP", [("aluguel de andaime", m)]),
        ]
    )
    assert len(r) == 1
    assert r[0].origens == ["semente", "site"]


def test_unir_origem_nao_repete() -> None:
    m = _m(1)
    r = unir([("semente", "JP", [("a", m)]), ("semente", "CG", [("a", m)])])
    assert r[0].origens == ["semente"]


def test_unir_normaliza_acento_e_caixa() -> None:
    m = _m(1)
    r = unir(
        [
            ("semente", "JP", [("Locação de andaimes", m)]),
            ("site", "JP", [("locacao  de andaimes", m)]),
        ]
    )
    assert len(r) == 1
    assert r[0].termo == "Locação de andaimes"


def test_unir_duas_cidades() -> None:
    r = unir(
        [
            ("semente", "João Pessoa (PB)", [("andaime", _m(40))]),
            ("semente", "Campina Grande (PB)", [("andaime", _m(20))]),
        ]
    )
    assert len(r) == 1
    assert {c: x["volume_mensal"] for c, x in r[0].por_cidade.items()} == {
        "João Pessoa (PB)": 40,
        "Campina Grande (PB)": 20,
    }
    assert volume_maximo(r[0]) == 40
    assert not hasattr(r[0], "total")


def test_unir_primeira_metrica_da_cidade_vence() -> None:
    r = unir(
        [
            ("semente", "JP", [("a", _m(7))]),
            ("site", "JP", [("a", _m(99))]),
        ]
    )
    assert r[0].por_cidade["JP"]["volume_mensal"] == 7


def test_volume_maximo_ignora_none() -> None:
    r = unir([("s", "JP", [("a", _m(None))]), ("s", "CG", [("a", _m(5))])])
    assert volume_maximo(r[0]) == 5
    r2 = unir([("s", "JP", [("b", _m(None))])])
    assert volume_maximo(r2[0]) is None


def test_ordem_none_por_ultimo_e_corte() -> None:
    ideias = unir(
        [
            (
                "s",
                "JP",
                [("d", _m(None)), ("c", _m(10)), ("a", _m(8100)), ("b", _m(40))],
            )
        ]
    )
    cortada, truncated = ordenar_e_cortar(ideias, 2)
    assert [volume_maximo(i) for i in cortada] == [8100, 40]
    assert truncated is True


def test_ordem_desempate_por_termo_e_sem_corte() -> None:
    ideias = unir([("s", "JP", [("b", _m(5)), ("a", _m(5))])])
    cortada, truncated = ordenar_e_cortar(ideias, 10)
    assert [i.termo for i in cortada] == ["a", "b"]
    assert truncated is False
