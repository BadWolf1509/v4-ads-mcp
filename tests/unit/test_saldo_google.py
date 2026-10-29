"""Saldo Google: queries do orcamento de conta e a montagem pura (spec saldo §1, §3.2)."""

from datetime import date
from typing import Any

from src.google_ads.queries.overview import gasto_diario_conta_query, saldo_orcamento_conta_query
from src.google_ads.saldo import montar_saldo_google

HOJE = date(2026, 10, 28)
HOSP: dict[str, Any] = {
    "tipo_limite": "UNSPECIFIED",
    "limite_ajustado_micros": 34_782_190_000,
    "gasto_micros": 34_468_970_000,
    "ajustes_micros": 161_190_000,
    "inicio": "2021-02-26 15:37:54",
    "fim": None,
    "tipo_fim": "FOREVER",
    "pendente": False,
}


def test_hosp_ocular_bate_com_fundos_disponiveis() -> None:
    r = montar_saldo_google([HOSP], {}, hoje=HOJE)
    assert r["restante_brl"] == 313.22  # aprovado daria 152.03: o teste falha se trocar
    assert r["limite_ajustado_brl"] == 34782.19
    assert r["ajustes_brl"] == 161.19
    assert r["aproximado"] is True
    assert r["tipo_de_teto"] == "finito"


def test_infinite_e_sem_teto() -> None:
    r = montar_saldo_google(
        [{**HOSP, "tipo_limite": "INFINITE", "limite_ajustado_micros": None}], {}, hoje=HOJE
    )
    assert (r["situacao"], r["restante_brl"], r["dias_restantes"]) == ("sem_teto", None, None)
    assert r["tipo_de_teto"] == "sem_teto"


def test_sem_linha_e_indeterminada() -> None:
    r = montar_saldo_google([], {}, hoje=HOJE)
    assert r["situacao"] == "indeterminada"
    assert r["motivo"] == "conta sem orçamento de conta"


def test_dois_vigentes_avisa_e_usa_o_mais_recente() -> None:
    antigo = {**HOSP, "inicio": "2020-01-01 00:00:00", "limite_ajustado_micros": 999_000_000_000}
    r = montar_saldo_google([antigo, HOSP], {}, hoje=HOJE)
    assert r["avisos"] == [
        "mais de um orçamento de conta vigente; usado o de início mais recente "
        "(não medido, spec §1.5)"
    ]
    assert r["limite_ajustado_brl"] == 34782.19  # o de 2021, nao o de 2020


def test_um_encerrado_e_um_vigente_usa_o_vigente_sem_aviso() -> None:
    encerrado = {**HOSP, "inicio": "2020-01-01 00:00:00", "fim": "2021-02-01 00:00:00"}
    r = montar_saldo_google([HOSP, encerrado], {}, hoje=HOJE)
    assert r["avisos"] == []
    assert r["restante_brl"] == 313.22


def test_inicio_futuro_nao_esconde_o_vigente() -> None:
    futuro = {**HOSP, "inicio": "2026-12-01 00:00:00", "limite_ajustado_micros": 999_000_000_000}
    r = montar_saldo_google([futuro, HOSP], {}, hoje=HOJE)
    assert r["limite_ajustado_brl"] == 34782.19
    assert r["avisos"] == []


def test_data_de_fim_trava_primeiro() -> None:
    # saldo de 1000 a 50/dia = 20 dias; o orcamento acaba em 3
    orc = {
        **HOSP,
        "limite_ajustado_micros": 2_000_000_000,
        "gasto_micros": 1_000_000_000,
        "fim": "2026-10-31 00:00:00",
    }
    gastos = {date(2026, 10, 27 - i): 50.0 for i in range(7)}
    r = montar_saldo_google([orc], gastos, hoje=HOJE)
    assert r["trava_primeiro"] == "data_fim"
    assert r["dias_ate_fim"] == 3
    assert r["dias_restantes"] == 3.0
    assert r["situacao"] == "acabando"


def test_saldo_trava_primeiro_sem_fim() -> None:
    gastos = {date(2026, 10, 27 - i): 50.0 for i in range(7)}
    r = montar_saldo_google([HOSP], gastos, hoje=HOJE)
    assert r["trava_primeiro"] == "saldo"
    assert r["data_fim"] is None


def test_orcamento_encerrado_e_esgotada() -> None:
    orc = {**HOSP, "fim": "2026-10-20 00:00:00"}
    r = montar_saldo_google([orc], {}, hoje=HOJE)
    assert (r["situacao"], r["dias_restantes"]) == ("esgotada", None)


def test_pendente_e_repassado() -> None:
    assert montar_saldo_google([{**HOSP, "pendente": True}], {}, hoje=HOJE)["orcamento_pendente"]


def test_queries_sao_validas_e_declaram_filtros() -> None:
    gaql, filtros = saldo_orcamento_conta_query()
    assert "adjusted_spending_limit_micros" in gaql and "ORDER BY" in gaql
    assert "account_budget.status = 'APPROVED'" in gaql
    assert "approved_spending_limit_micros" not in gaql
    assert filtros == {"status": "APPROVED"}


def test_gasto_diario_declara_a_janela() -> None:
    gaql, filtros = gasto_diario_conta_query(date(2026, 9, 28), date(2026, 10, 27))
    assert "FROM customer" in gaql and "LIMIT 40" in gaql
    assert "BETWEEN '2026-09-28' AND '2026-10-27'" in gaql
    assert filtros == {"date_range": {"start": "2026-09-28", "end": "2026-10-27"}}
