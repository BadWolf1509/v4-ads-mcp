"""Saldo da conta Meta (spec saldo-da-conta §1.6-1.11, §3.1). Puro, sem I/O.

Recebe o JSON cru de `GET /act_<id>` e o gasto diario; reune os dois freios (saldo pre-pago e
limite de gastos), escolhe o que trava primeiro e delega o resto a `src.saldo.classificar`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from src.meta_ads.labels import META_ACCOUNT_STATUS_LABELS
from src.saldo import classificar, media_7d, media_dias_com_gasto

_PADRAO_SALDO = re.compile(r"Saldo disponível \(R\$\s?(\d{1,3}(?:\.\d{3})*,\d{2}) BRL\)")


def saldo_do_texto(display_string: str | None) -> Decimal | None:
    """`'Saldo disponível (R$1.234,56 BRL)'` -> Decimal. Qualquer outro formato -> None.

    Nunca levanta e nunca devolve numero parcial: so o formato pt-BR exato casa.
    """
    if not isinstance(display_string, str):
        return None
    m = _PADRAO_SALDO.fullmatch(display_string)
    if m is None:
        return None
    return Decimal(m.group(1).replace(".", "").replace(",", "."))


def _brl(centavos: int) -> float:
    return round(centavos / 100, 2)


def montar_saldo_meta(
    conta: dict[str, Any], gastos: Mapping[date, float], *, hoje: date
) -> dict[str, Any]:
    moeda = conta.get("currency")
    if moeda != "BRL":
        raise ValueError(
            f"conta Meta em moeda {moeda!r}: o saldo só é calculado para contas em BRL"
        )

    ontem = hoje - timedelta(days=1)
    media7 = media_7d(gastos, ontem=ontem)
    prepago = bool(conta["is_prepay_account"])
    cap = int(conta["spend_cap"])
    gasto = int(conta["amount_spent"])
    freio_limite = _brl(cap - gasto) if cap > 0 else None
    fsd = conta.get("funding_source_details") or {}
    texto = fsd.get("display_string")
    status = int(conta["account_status"])
    label = META_ACCOUNT_STATUS_LABELS.get(status, str(status))

    avisos: list[str] = []
    if status != 1:
        avisos.append(
            f"conta com status {label}: os anúncios podem estar parados independente do saldo"
        )

    base: dict[str, Any] = {
        "situacao": "indeterminada",
        "motivo": None,
        "status_conta": status,
        "status_conta_label": label,
        "disable_reason": conta.get("disable_reason"),
        "forma_de_pagamento": "pre_pago" if prepago else "pos_pago",
        "forma_de_pagamento_texto": texto,
        "a_faturar_brl": None if prepago else _brl(int(conta["balance"])),
        "cupons": list(fsd.get("coupons") or []),
        "restante_brl": None,
        "dias_restantes": None,
        "trava_primeiro": None,
        "freio_saldo_brl": None,
        "freio_limite_brl": freio_limite,
        "media_diaria_7d_brl": media7,
        "aproximado": True,
        "avisos": avisos,
    }

    freio_saldo: float | None = None
    if prepago:
        saldo = saldo_do_texto(texto)
        if saldo is None:
            return {
                **base,
                "motivo": "saldo pré-pago ilegível",
                "saldo_prepago_texto": texto,
                "teto_pelo_limite_brl": freio_limite,
                "avisos": [*avisos, "saldo_prepago_ilegivel"],
            }
        freio_saldo = round(float(saldo), 2)
        base["freio_saldo_brl"] = freio_saldo

    freios = [
        (v, nome)
        for v, nome in ((freio_saldo, "saldo_prepago"), (freio_limite, "limite_de_gastos"))
        if v is not None
    ]
    if not freios:
        return {**base, "situacao": "sem_teto"}

    # min() devolve o primeiro em empate: saldo_prepago vem antes na lista
    restante, trava = min(freios, key=lambda f: f[0])
    c = classificar(
        restante=restante,
        media7=media7,
        media_com_gasto=media_dias_com_gasto(gastos, ontem=ontem),
    )
    return {
        **base,
        "situacao": c.situacao,
        "motivo": c.motivo,
        "restante_brl": restante,
        "dias_restantes": c.dias_restantes,
        "trava_primeiro": trava,
    }
