"""O contrato das métricas Meta (spec 2026-09-26, §3) — sobre as formas MEDIDAS.

Cada teste aqui é uma medição de 26/09 que o código anterior errava: `purchases: 0`
sobre 10 compras, lead somado 7 vezes, conversa iniciada invisível, `reach` e ROAS
inventados como zero, `ctr` em duas escalas.
"""

from __future__ import annotations

from src.meta_ads.metricas import (
    ACAO_COMPRA,
    ACAO_CONVERSA,
    ACAO_LEAD,
    metricas_da_linha,
    metricas_sem_linha,
)
from tests.unit._meta_formas_medidas import LINHA_COMPRA_E_LEAD, LINHA_HORARIA, LINHA_SO_CONVERSAS

_CHAVES = {
    "spend_brl",
    "impressions",
    "clicks",
    "ctr",
    "cpc_brl",
    "reach",
    "frequency",
    "purchases",
    "purchases_value_brl",
    "purchase_roas",
    "leads",
    "messaging_conversations_started",
}


def test_compra_sob_cinco_nomes_conta_uma_vez() -> None:
    """M2: o total canônico é `omni_purchase`; os outros 4 nomes são recortes dele."""
    m = metricas_da_linha(LINHA_COMPRA_E_LEAD)
    assert m["purchases"] == 10


def test_lead_sob_sete_nomes_conta_uma_vez() -> None:
    """M2: somar os 7 nomes daria 91 — o mesmo lead contado sete vezes."""
    m = metricas_da_linha(LINHA_COMPRA_E_LEAD)
    assert m["leads"] == 13


def test_conversa_iniciada_e_campo_proprio() -> None:
    """M3: 14 de 14 contas com gasto medem conversa iniciada."""
    assert metricas_da_linha(LINHA_COMPRA_E_LEAD)["messaging_conversations_started"] == 3531
    assert metricas_da_linha(LINHA_SO_CONVERSAS)["messaging_conversations_started"] == 37


def test_evento_que_a_conta_nao_reporta_e_null_nao_zero() -> None:
    """A Meta omite o tipo com zero ocorrência: null = zero OU não rastreado."""
    m = metricas_da_linha(LINHA_SO_CONVERSAS)
    assert m["purchases"] is None
    assert m["leads"] is None


def test_valor_e_roas_ausentes_sao_null() -> None:
    """M4: `action_values` e `purchase_roas` vazios em 14 de 14 contas."""
    m = metricas_da_linha(LINHA_COMPRA_E_LEAD)
    assert m["purchases_value_brl"] is None
    assert m["purchase_roas"] is None


def test_roas_le_a_entrada_do_total_canonico_nao_a_primeira() -> None:
    """Antes o trio pegava `purchase_roas[0]` sem olhar o tipo."""
    linha = {
        "purchase_roas": [
            {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "9.9"},
            {"action_type": ACAO_COMPRA, "value": "4.45"},
        ]
    }
    assert metricas_da_linha(linha)["purchase_roas"] == 4.45


def test_reach_e_frequency_ausentes_no_horario_sao_null() -> None:
    """M5: ausentes em 50 de 50 linhas do breakdown horário."""
    m = metricas_da_linha(LINHA_HORARIA)
    assert m["reach"] is None
    assert m["frequency"] is None
    assert m["spend_brl"] == 12.3


def test_ctr_sai_em_fracao() -> None:
    """M1: a Meta manda porcentagem (1.777474 = 1,78%)."""
    assert metricas_da_linha(LINHA_COMPRA_E_LEAD)["ctr"] == 0.0178
    assert metricas_da_linha({})["ctr"] is None


def test_contagem_arredonda_nao_trunca() -> None:
    linha = {"actions": [{"action_type": ACAO_LEAD, "value": "2.9"}], "impressions": "99.6"}
    m = metricas_da_linha(linha)
    assert m["leads"] == 3
    assert m["impressions"] == 100


def test_valor_que_nao_converte_e_null() -> None:
    linha = {"spend": "n/a", "actions": [{"action_type": ACAO_CONVERSA, "value": "x"}]}
    m = metricas_da_linha(linha)
    assert m["spend_brl"] is None
    assert m["messaging_conversations_started"] is None


def test_numero_nao_finito_e_null_e_nao_derruba_a_linha() -> None:
    """`float("nan")` e `float("inf")` convertem, e o round() da contagem levantava."""
    linha = {
        "spend": "inf",
        "impressions": "nan",
        "actions": [
            {"action_type": ACAO_COMPRA, "value": "nan"},
            {"action_type": ACAO_LEAD, "value": "-inf"},
        ],
    }
    m = metricas_da_linha(linha)
    assert m["spend_brl"] is None
    assert m["impressions"] is None
    assert m["purchases"] is None
    assert m["leads"] is None


def test_zero_que_a_meta_manda_segue_zero() -> None:
    """Null é só para o que não veio: o zero medido continua zero."""
    linha = {"spend": "0", "actions": [{"action_type": ACAO_COMPRA, "value": "0"}]}
    m = metricas_da_linha(linha)
    assert m["spend_brl"] == 0.0
    assert m["purchases"] == 0


def test_linha_vazia_da_todas_as_chaves_em_null() -> None:
    m = metricas_da_linha({})
    assert set(m) == _CHAVES
    assert all(v is None for v in m.values())


def test_sem_linha_entrega_zero_e_eventos_null() -> None:
    """M7: sem entrega, a Meta não manda linha. Entrega 0 é verdade; o resto é null."""
    m = metricas_sem_linha()
    assert set(m) == _CHAVES
    assert (m["spend_brl"], m["impressions"], m["clicks"], m["reach"]) == (0.0, 0, 0, 0)
    for chave in ("purchases", "leads", "messaging_conversations_started", "ctr", "frequency"):
        assert m[chave] is None, chave
