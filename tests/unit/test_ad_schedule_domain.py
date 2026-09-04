"""Dominio puro do ad_schedule (spec §4.1, §8.1): janela, validacao, cobertura.

Restricoes lidas do SDK v24 por import, nao por analogia: `MinuteOfHour` so
aceita ZERO|FIFTEEN|THIRTY|FORTY_FIVE; `DayOfWeek` e MONDAY..SUNDAY.
"""

from __future__ import annotations

import pytest

from src.google_ads.ad_schedule import (
    DIAS,
    MINUTO_ENUM,
    CurrentWindow,
    MetricCell,
    Window,
    covers,
    diff_schedule,
    hours_per_week,
    partition_metrics,
    summarize_current,
    validate_windows,
    window_from_input,
)


def _w(day="MONDAY", sh=7, sm=0, eh=17, em=0) -> dict:
    return {
        "day_of_week": day,
        "start_hour": sh,
        "start_minute": sm,
        "end_hour": eh,
        "end_minute": em,
    }


def test_dias_e_minutos_espelham_o_sdk() -> None:
    assert DIAS == ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
    assert MINUTO_ENUM == {0: "ZERO", 15: "FIFTEEN", 30: "THIRTY", 45: "FORTY_FIVE"}


def test_window_from_input_default_de_minuto_e_zero() -> None:
    w = window_from_input({"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17})
    assert w == Window("MONDAY", 7, 0, 17, 0)
    assert w.key() == ("MONDAY", 7, 0, 17, 0)


def test_minuto_fora_do_quarto_de_hora_e_recusado_citando_os_quatro_validos() -> None:
    """Spec §8.1: 07:10 nao existe na API; recusar na entrada, nao deixar o Google recusar."""
    err = validate_windows([_w(sm=10)])
    assert err is not None
    for v in ("0", "15", "30", "45"):
        assert v in err


@pytest.mark.parametrize(
    "bad", [_w(sh=-1), _w(eh=25), _w(sh=17, eh=7), _w(sh=7, eh=7), _w(day="MONDAI")]
)
def test_hora_invertida_fora_de_faixa_ou_dia_invalido_e_recusado(bad: dict) -> None:
    assert validate_windows([bad]) is not None


def test_fim_as_24_00_e_valido() -> None:
    """24:00 e o unico jeito de dizer 'ate o fim do dia' — o Google aceita end_hour=24."""
    assert validate_windows([_w(sh=18, eh=24)]) is None


def test_janelas_sobrepostas_no_mesmo_dia_sao_recusadas() -> None:
    assert validate_windows([_w(sh=7, eh=12), _w(sh=11, eh=17)]) is not None


def test_janelas_adjacentes_no_mesmo_dia_sao_aceitas() -> None:
    assert validate_windows([_w(sh=7, eh=12), _w(sh=12, eh=17)]) is None


def test_mesma_faixa_em_dias_diferentes_nao_e_sobreposicao() -> None:
    assert validate_windows([_w(day="MONDAY"), _w(day="TUESDAY")]) is None


def test_hours_per_week_soma_as_janelas() -> None:
    ws = [window_from_input(_w(day=d, sh=7, eh=17)) for d in ("MONDAY", "TUESDAY")]
    assert hours_per_week(ws) == 20.0
    assert hours_per_week([window_from_input(_w(sh=7, sm=30, eh=8))]) == 0.5


@pytest.mark.parametrize(
    "malformado",
    [
        {"day_of_week": "MONDAY", "start_hour": "abc", "end_hour": 17},
        {"day_of_week": "MONDAY", "end_hour": 17},
        {"day_of_week": "MONDAY", "start_hour": None, "end_hour": 17},
    ],
)
def test_dict_malformado_vira_mensagem_nao_excecao(malformado: dict) -> None:
    err = validate_windows([malformado])
    assert err is not None and "windows[0]" in err


def _cur(day="MONDAY", sh=7, eh=17, bm=None, rn=None) -> CurrentWindow:
    w = Window(day, sh, 0, eh, 0)
    return CurrentWindow(
        window=w,
        resource_name=rn or f"customers/1/campaignCriteria/9~{day}{sh}",
        criterion_id="1",
        bid_modifier=bm,
    )


def test_grade_completa_e_conjunto_uma_janela_remove_as_outras_quatro() -> None:
    """Spec §8.2 — a guarda do erro conjunto-vs-incremento. Falha contra qualquer
    implementacao que trate a entrada como delta."""
    current = [_cur(day=d) for d in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")]
    diff = diff_schedule(current, [Window("MONDAY", 7, 0, 17, 0)], None)
    assert diff.to_add == ()
    assert {c.window.day_of_week for c in diff.to_remove} == {
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
    }


def test_grade_identica_nao_emite_operacao_nenhuma() -> None:
    """Spec §8.9 — reenviar a grade atual e no-op; recriar identicos queima re-learning."""
    current = [_cur(day="MONDAY"), _cur(day="TUESDAY")]
    diff = diff_schedule(current, [c.window for c in current], None)
    assert diff.is_empty() and diff.op_count() == 0


def test_diff_e_por_conteudo_nao_por_criterion_id() -> None:
    """O id muda quando o Google recria; a chave e (dia, horas, minutos)."""
    current = [_cur(day="MONDAY", rn="customers/1/campaignCriteria/9~111")]
    diff = diff_schedule(current, [Window("MONDAY", 7, 0, 17, 0)], None)
    assert diff.is_empty()


def test_janela_nova_entra_e_janela_ausente_sai() -> None:
    current = [_cur(day="MONDAY")]
    diff = diff_schedule(current, [Window("TUESDAY", 8, 0, 12, 0)], None)
    assert diff.to_add == (Window("TUESDAY", 8, 0, 12, 0),)
    assert [c.window.day_of_week for c in diff.to_remove] == ["MONDAY"]


def test_bid_modifier_diferente_vira_update_nao_recria() -> None:
    """Mudar so o bid_modifier de uma janela existente e `update` com mask — nao remove+create."""
    current = [_cur(day="MONDAY", bm=1.0)]
    diff = diff_schedule(current, [Window("MONDAY", 7, 0, 17, 0)], 1.2)
    assert diff.to_add == () and diff.to_remove == ()
    assert [c.window.day_of_week for c in diff.to_update] == ["MONDAY"]


def test_bid_modifier_igual_ou_nao_informado_nao_gera_update() -> None:
    current = [_cur(day="MONDAY", bm=1.2)]
    assert diff_schedule(current, [Window("MONDAY", 7, 0, 17, 0)], 1.2).is_empty()
    assert diff_schedule(current, [Window("MONDAY", 7, 0, 17, 0)], None).is_empty()


def _cell(day: str, hour: int, cost: float, conv: float) -> MetricCell:
    return MetricCell(day, hour, int(cost * 1_000_000), conv)


def test_sem_criterio_cobre_24x7() -> None:
    """Spec §3: campanha sem AD_SCHEDULE serve sempre — vazio quer dizer 'tudo', nao 'nada'."""
    assert covers(None, "SUNDAY", 3) is True
    assert covers([], "SUNDAY", 3) is False


def test_cobertura_e_meio_aberta_e_por_hora_cheia() -> None:
    w = [Window("MONDAY", 7, 0, 17, 0)]
    assert covers(w, "MONDAY", 7) and covers(w, "MONDAY", 16)
    assert not covers(w, "MONDAY", 17) and not covers(w, "TUESDAY", 8)
    # 07:30-08:00: a celula 07:00 NAO esta em [07:30, 08:00) -> aproximacao documentada
    assert not covers([Window("MONDAY", 7, 30, 8, 0)], "MONDAY", 7)


def test_preview_separa_o_que_sai_do_que_fica_com_cpa_dos_dois_lados() -> None:
    """Spec §4.2/§8.3: custo sozinho nao responde; CPA de quem sai vs quem fica."""
    cells = [
        _cell("SATURDAY", 10, 100.0, 5.0),  # sai (fim de semana) — CPA 20
        _cell("SUNDAY", 11, 50.0, 5.0),  # sai — CPA 10
        _cell("MONDAY", 9, 300.0, 10.0),  # fica — CPA 30
    ]
    depois = [
        Window(d, 0, 0, 24, 0) for d in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")
    ]
    r = partition_metrics(cells, None, depois)
    assert r["leaving"]["cost_brl"] == 150.0 and r["leaving"]["conversions"] == 10.0
    assert r["leaving"]["cpa_brl"] == 15.0
    assert r["staying"]["cost_brl"] == 300.0 and r["staying"]["cpa_brl"] == 30.0
    assert "conversions" in r["leaving"] and "conversions" in r["staying"]


def test_cpa_e_none_sem_conversao_nunca_divisao_por_zero() -> None:
    r = partition_metrics([_cell("SUNDAY", 3, 10.0, 0.0)], None, [Window("MONDAY", 0, 0, 24, 0)])
    assert r["leaving"]["cpa_brl"] is None and r["leaving"]["cost_brl"] == 10.0


def test_celula_que_ja_nao_era_servida_nao_entra_em_nenhum_lado() -> None:
    antes = [Window("MONDAY", 7, 0, 17, 0)]
    r = partition_metrics([_cell("SUNDAY", 3, 10.0, 1.0)], antes, antes)
    assert r["leaving"]["cost_brl"] == 0.0 and r["staying"]["cost_brl"] == 0.0


def test_summarize_current_sem_grade_e_24x7() -> None:
    assert summarize_current([]) == {"has_schedule": False, "windows": 0, "hours_per_week": 168.0}
    s = summarize_current([_cur(day="MONDAY"), _cur(day="TUESDAY")])
    assert s == {"has_schedule": True, "windows": 2, "hours_per_week": 20.0}
