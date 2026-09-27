"""Janela de cada preset: uma regra só para o Google e a Meta (F195).

O `LAST_N_DAYS` das tools Meta terminava HOJE, com o dia corrente pela metade; o do Google
terminava ontem. Mesmo nome de preset, janelas deslocadas de um dia — e no comparativo do
overview Meta o sinal da variação invertia (medido em 27/09 na MI Imports: gasto −19,6% onde
os 7 dias cheios davam +1,14%). As duas pontas passam a delegar para `src.janelas`; a
paridade abaixo é o guard de que não divergem de novo, por qualquer caminho.
"""

from datetime import date, timedelta

import pytest

from src import janelas
from src.google_ads.queries._common import parse_date_range
from src.janelas import PRESETS, janela_do_preset
from src.meta_ads.account_overview import resolve_meta_date_window

# Os presets que as tools Meta aceitam (o enum dos input schemas das 5 tools de métrica).
_PRESETS_META = (
    "TODAY",
    "YESTERDAY",
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
    "LAST_90_DAYS",
)
# Viradas de mês e de ano, uma segunda-feira, um domingo, fevereiro.
_HOJES = (
    date(2026, 9, 27),
    date(2026, 9, 28),
    date(2026, 10, 1),
    date(2026, 1, 1),
    date(2026, 3, 1),
)


@pytest.mark.parametrize("hoje", _HOJES)
@pytest.mark.parametrize("preset", _PRESETS_META)
def test_meta_e_google_resolvem_o_mesmo_preset_na_mesma_janela(preset: str, hoje: date) -> None:
    meta = resolve_meta_date_window(preset, None, None, hoje)
    assert meta == parse_date_range(preset, today=hoje), (preset, hoje, meta)


def test_last_n_days_sao_os_n_dias_completos_ate_ontem_como_na_propria_meta() -> None:
    """A regra da própria Meta, sondada em 27/09 na Cheiro | Conta 01 (fuso da conta,
    America/Sao_Paulo): `date_preset=last_7d` devolveu 20/09–26/09 e `last_30d`,
    28/08–26/09; `today`, 27/09–27/09."""
    hoje = date(2026, 9, 27)
    assert resolve_meta_date_window("LAST_7_DAYS", None, None, hoje) == (
        date(2026, 9, 20),
        date(2026, 9, 26),
    )
    assert resolve_meta_date_window("LAST_30_DAYS", None, None, hoje) == (
        date(2026, 8, 28),
        date(2026, 9, 26),
    )
    assert resolve_meta_date_window("TODAY", None, None, hoje) == (hoje, hoje)


def test_preset_desconhecido_e_value_error_que_a_tool_ja_trata() -> None:
    """As tools Meta capturam `ValueError` e devolvem erro legível; `KeyError` escapava."""
    with pytest.raises(ValueError, match="LAST_8_DAYS"):
        resolve_meta_date_window("LAST_8_DAYS", None, None, date(2026, 9, 27))


# Tres anos corridos a partir de 01/01/2026: toda virada de mes e de semana, e o 29/02/2028.
_TODO_DIA = [date(2026, 1, 1) + timedelta(days=n) for n in range(3 * 366)]


def test_toda_janela_de_preset_e_valida_em_todo_dia() -> None:
    """F196: inicio <= fim <= hoje, para todo preset, em todo dia.

    E a regra que o intervalo custom ja cumpria (`from` depois de `to` e erro em
    `parse_date_range`) e o preset nao: em 01/10 o `THIS_MONTH` devolvia 01/10-30/09. A GAQL
    responde `BETWEEN` invertido com 0 linhas e sem erro (medido em 27/09), e as 15 tools
    Google que aceitam o preset diriam "zero no mes". Varrer o calendario pega o proximo
    preset que tropecar numa virada, nao so o exemplo de hoje.
    """
    violacoes = [
        (preset, hoje, janela)
        for hoje in _TODO_DIA
        for preset in sorted(PRESETS)
        for janela in [janelas._janela_crua(preset, today=hoje)]
        if not janela[0] <= janela[1] <= hoje
    ]
    assert violacoes == [], violacoes[:5]


def test_this_month_no_dia_1_e_so_hoje_como_o_this_week_na_segunda() -> None:
    """No dia 1 ainda nao ha dia completo no mes: a janela e so hoje — o que o `THIS_WEEK`
    ja fazia na segunda-feira, e o que o `DURING THIS_MONTH` do Google devolve nesse dia."""
    dia_1 = date(2026, 10, 1)
    assert janela_do_preset("THIS_MONTH", today=dia_1) == (dia_1, dia_1)
    assert janela_do_preset("THIS_MONTH", today=date(2026, 10, 2)) == (dia_1, dia_1)
    assert janela_do_preset("THIS_MONTH", today=date(2026, 9, 27)) == (
        date(2026, 9, 1),
        date(2026, 9, 26),
    )
    segunda = date(2026, 9, 28)
    assert janela_do_preset("THIS_WEEK", today=segunda) == (segunda, segunda)


def test_janela_invertida_falha_alto_em_vez_de_virar_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A checagem na fonte: se uma regra de preset produzir janela invertida, a resolucao
    falha — na GAQL ela seria 0 linhas sem erro, e o "zero" seria lido como medicao."""
    monkeypatch.setattr(
        janelas, "_janela_crua", lambda preset, *, today: (today, today - timedelta(days=1))
    )
    with pytest.raises(ValueError, match="invertida"):
        janela_do_preset("THIS_MONTH", today=date(2026, 10, 1))


def test_intervalo_custom_meta_invertido_e_recusado_como_no_google() -> None:
    """O gemeo do lado Meta: o custom do Google recusa `from` depois de `to`; o da Meta
    devolvia a janela invertida adiante."""
    with pytest.raises(ValueError, match="depois"):
        resolve_meta_date_window(None, "2026-10-01", "2026-09-30", date(2026, 10, 1))
