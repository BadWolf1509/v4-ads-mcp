"""Saldo Meta (spec saldo-da-conta §1.6-1.11, §3.1). JSON cru de `GET /act_<id>` da sondagem de 28/10."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from src.meta_ads.saldo import montar_saldo_meta, saldo_do_texto

HOJE = date(2026, 10, 28)
GASTOS = {HOJE - timedelta(days=i): 10.0 for i in range(1, 8)}

CANTINA: dict[str, Any] = {
    "name": "CA - Cantina Sabores da Vila",
    "account_status": 1,
    "disable_reason": 0,
    "is_prepay_account": True,
    "spend_cap": "80001",
    "amount_spent": "24352",
    "balance": "2167",
    "currency": "BRL",
    "funding_source_details": {
        "id": "29013939138295436",
        "display_string": "Saldo disponível (R$633,45 BRL)",
        "type": 20,
    },
    "id": "act_3709029949237406",
}
LAGOAS: dict[str, Any] = {
    "name": "3 Lagoas Locações",
    "account_status": 1,
    "disable_reason": 0,
    "is_prepay_account": True,
    "spend_cap": "15000",
    "amount_spent": "15000",
    "balance": "9",
    "currency": "BRL",
    "funding_source_details": {
        "id": "28737589395932228",
        "display_string": "Saldo disponível (R$0,00 BRL)",
        "type": 20,
    },
    "id": "act_1470682461507188",
}
MDO: dict[str, Any] = {
    "name": "CA - MDO João Pessoa",
    "account_status": 1,
    "disable_reason": 0,
    "is_prepay_account": True,
    "spend_cap": "0",
    "amount_spent": "0",
    "balance": "0",
    "currency": "BRL",
    "funding_source_details": {
        "id": "27991254403897884",
        "display_string": "Saldo disponível (R$0,00 BRL)",
        "type": 20,
    },
    "id": "act_27798855556414269",
}
MI_IMPORTSS: dict[str, Any] = {
    "name": "Mi importss Resv",
    "account_status": 3,
    "disable_reason": 0,
    "is_prepay_account": False,
    "spend_cap": "0",
    "amount_spent": "1995318",
    "balance": "121858",
    "currency": "BRL",
    "funding_source_details": {
        "id": "27104428372577650",
        "display_string": "VISA *6522",
        "type": 1,
    },
    "id": "act_1946490616005185",
}
DERICK: dict[str, Any] = {
    "name": "Dr. Dérick Vinhas",
    "account_status": 1,
    "disable_reason": 0,
    "is_prepay_account": False,
    "spend_cap": "0",
    "amount_spent": "1015260",
    "balance": "20016",
    "currency": "BRL",
    "funding_source_details": {
        "id": "24639722245716666",
        "coupons": [
            {
                "amount": 0,
                "currency": "BRL",
                "display_amount": "R$0,00 BRL",
                "expiration": "2027-01-13T09:53:20+0000",
                "start_date": "2026-07-14T21:53:20+0000",
                "coupon_id": "28079158008439719",
                "original_amount": 29,
                "original_display_amount": "R$0,29 BRL",
            }
        ],
        "display_string": "VISA *6742",
        "type": 1,
    },
    "id": "act_4051924171730156",
}


def test_texto_medido() -> None:
    assert saldo_do_texto("Saldo disponível (R$633,45 BRL)") == Decimal("633.45")


def test_milhar() -> None:
    assert saldo_do_texto("Saldo disponível (R$1.234,56 BRL)") == Decimal("1234.56")


def test_zero() -> None:
    assert saldo_do_texto("Saldo disponível (R$0,00 BRL)") == Decimal("0.00")


def test_ingles_e_none() -> None:
    assert saldo_do_texto("Available balance (R$633.45 BRL)") is None


@pytest.mark.parametrize("texto", ["", None, "VISA *6522", "Saldo disponível (R$633,4 BRL)"])
def test_vazio_e_none(texto: str | None) -> None:
    assert saldo_do_texto(texto) is None


def test_cantina_limite_trava_antes() -> None:
    r = montar_saldo_meta(CANTINA, GASTOS, hoje=HOJE)
    assert r["freio_saldo_brl"] == 633.45
    assert r["freio_limite_brl"] == 556.49
    assert r["trava_primeiro"] == "limite_de_gastos"
    assert r["restante_brl"] == 556.49
    assert r["forma_de_pagamento"] == "pre_pago"
    assert r["forma_de_pagamento_texto"] == "Saldo disponível (R$633,45 BRL)"
    assert r["a_faturar_brl"] is None
    assert r["aproximado"] is True
    assert r["situacao"] in ("com_saldo", "acabando")
    assert r["status_conta_label"] == "ATIVO"
    assert r["avisos"] == []


def test_prepago_saldo_menor_que_limite_trava_no_saldo() -> None:
    conta = {**CANTINA, "spend_cap": "200000"}
    r = montar_saldo_meta(conta, GASTOS, hoje=HOJE)
    assert r["trava_primeiro"] == "saldo_prepago"
    assert r["restante_brl"] == 633.45


def test_prepago_sem_limite_usa_so_o_saldo() -> None:
    conta = {**CANTINA, "spend_cap": "0"}
    r = montar_saldo_meta(conta, GASTOS, hoje=HOJE)
    assert r["freio_limite_brl"] is None
    assert r["trava_primeiro"] == "saldo_prepago"
    assert r["restante_brl"] == 633.45


def test_empate_prefere_saldo_prepago() -> None:
    conta = {**CANTINA, "spend_cap": "30000", "amount_spent": "0"}
    conta["funding_source_details"] = {
        **CANTINA["funding_source_details"],
        "display_string": "Saldo disponível (R$300,00 BRL)",
    }
    r = montar_saldo_meta(conta, GASTOS, hoje=HOJE)
    assert r["trava_primeiro"] == "saldo_prepago"


def test_3_lagoas_esgotada() -> None:
    r = montar_saldo_meta(LAGOAS, GASTOS, hoje=HOJE)
    assert r["situacao"] == "esgotada"
    assert r["freio_limite_brl"] == 0.0
    assert r["restante_brl"] == 0.0


def test_mdo_jp_prepago_sem_saldo_sem_limite() -> None:
    r = montar_saldo_meta(MDO, GASTOS, hoje=HOJE)
    assert r["situacao"] == "esgotada"
    assert r["freio_limite_brl"] is None
    assert r["freio_saldo_brl"] == 0.0


def test_mi_importss_pendente() -> None:
    r = montar_saldo_meta(MI_IMPORTSS, GASTOS, hoje=HOJE)
    assert r["situacao"] == "sem_teto"
    assert r["a_faturar_brl"] == 1218.58
    assert r["forma_de_pagamento"] == "pos_pago"
    assert r["status_conta"] == 3
    assert any("PAGAMENTO_PENDENTE" in a for a in r["avisos"])
    assert r["restante_brl"] is None


def test_pos_pago_com_limite_classifica_sobre_o_limite() -> None:
    conta = {**DERICK, "spend_cap": "1100000"}
    r = montar_saldo_meta(conta, GASTOS, hoje=HOJE)
    assert r["freio_limite_brl"] == 847.4
    assert r["restante_brl"] == 847.4
    assert r["trava_primeiro"] == "limite_de_gastos"
    assert r["situacao"] in ("com_saldo", "acabando")


def test_ilegivel_com_limite_e_indeterminada() -> None:
    conta = {
        **CANTINA,
        "funding_source_details": {"id": "1", "display_string": "Available balance (R$633.45 BRL)"},
    }
    r = montar_saldo_meta(conta, GASTOS, hoje=HOJE)
    assert r["situacao"] == "indeterminada"
    assert r["motivo"] == "saldo pré-pago ilegível"
    assert r["teto_pelo_limite_brl"] == 556.49
    assert r["restante_brl"] is None
    assert r["dias_restantes"] is None
    assert r["saldo_prepago_texto"] == "Available balance (R$633.45 BRL)"
    assert "saldo_prepago_ilegivel" in r["avisos"]


def test_ilegivel_sem_funding_source() -> None:
    conta = {k: v for k, v in CANTINA.items() if k != "funding_source_details"}
    r = montar_saldo_meta(conta, GASTOS, hoje=HOJE)
    assert r["situacao"] == "indeterminada"
    assert r["saldo_prepago_texto"] is None


def test_cupom_nao_entra_no_restante() -> None:
    r = montar_saldo_meta(DERICK, GASTOS, hoje=HOJE)
    assert r["situacao"] == "sem_teto"
    assert len(r["cupons"]) == 1
    assert r["restante_brl"] is None
    assert r["a_faturar_brl"] == 200.16


def test_moeda_diferente_de_brl_levanta() -> None:
    with pytest.raises(ValueError, match="USD"):
        montar_saldo_meta({**CANTINA, "currency": "USD"}, GASTOS, hoje=HOJE)


def test_chaves_identicas_em_todos_os_cenarios() -> None:
    ilegivel = {
        **CANTINA,
        "funding_source_details": {"id": "1", "display_string": "Available balance (R$633.45 BRL)"},
    }
    chaves = [
        set(montar_saldo_meta(c, GASTOS, hoje=HOJE)) for c in (CANTINA, MI_IMPORTSS, ilegivel)
    ]
    assert chaves[0] == chaves[1] == chaves[2]
    assert {"saldo_prepago_texto", "teto_pelo_limite_brl"} <= chaves[0]


def test_texto_cru_da_api_tem_espaco_nao_separavel() -> None:
    """Forma CRUA medida em 29/10 (repr da resposta da Graph): U+00A0 antes de BRL.

    O smoke de 29/10 pegou a Cantina e a 3 Lagoas como `indeterminada`: as fixtures tinham
    sido transcritas da saida impressa da sondagem, que mostra o U+00A0 como espaco comum.
    """
    assert saldo_do_texto("Saldo disponível (R$631,96 BRL)") == Decimal("631.96")
    assert saldo_do_texto("Saldo disponível (R$0,00 BRL)") == Decimal("0.00")
    assert saldo_do_texto("Saldo disponível (R$631,96 BRL)") == Decimal("631.96")
