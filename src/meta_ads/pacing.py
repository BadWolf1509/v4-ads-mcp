"""Ritmo de gasto Meta contra o orcamento: calculo puro, sem I/O.

Mesmo calendario do pacing Google (`src.janelas.calendario_do_mes`, F199): a media sai dos
dias FECHADOS (ate ontem) e o dia corrente, parcial, fica fora. Orcamento e gasto
ausentes sao `None`, nunca zero; razao sem denominador e `None` (indefinida).
"""

from __future__ import annotations

from typing import Any

from src.razoes import arredondado, percentual, razao

OBS_VITALICIO = (
    "orçamento vitalício: o valor vale para a vida da campanha, não por dia; sem projeção mensal"
)


def projetar(
    *, gasto_fechado: float | None, dias_fechados: int, dias_no_mes: int
) -> dict[str, float | None]:
    """Media diaria dos dias fechados e a projecao do mes. Sem dia fechado, ambas `None`."""
    media = razao(gasto_fechado, dias_fechados)
    projecao = None if media is None else media * dias_no_mes
    return {"media_diaria": arredondado(media, 2), "projecao": arredondado(projecao, 2)}


def orcamento_total(*, campanha: float | None, conjuntos: list[float | None]) -> float | None:
    """Orcamento diario efetivo. O da campanha vale sozinho; sem ele, soma os conjuntos.

    Um conjunto sem orcamento legivel torna o total ilegivel (`None`): soma parcial nao e
    total. Sem campanha e sem conjunto nao ha o que somar: `None`, nao zero.
    """
    if campanha is not None:
        return campanha
    if not conjuntos or any(c is None for c in conjuntos):
        return None
    return round(sum(c for c in conjuntos if c is not None), 2)


def ritmo_de(
    *,
    daily_budget: float | None,
    lifetime_budget: float | None,
    gasto_fechado: float | None = None,
    dias_fechados: int = 0,
    dias_no_mes: int = 30,
) -> dict[str, Any]:
    """Ritmo de UMA entidade. Vitalicio nao projeta o mes; sem orcamento so projeta o gasto."""
    base = projetar(
        gasto_fechado=gasto_fechado, dias_fechados=dias_fechados, dias_no_mes=dias_no_mes
    )
    if daily_budget is None and lifetime_budget is not None:
        return {
            "tipo_orcamento": "vitalicio",
            "orcamento_mensal_brl": None,
            "media_diaria": base["media_diaria"],
            "projecao": None,
            "gasto_pct_do_orcamento_mensal": None,
            "projecao_vs_orcamento_pct": None,
            "observacao": OBS_VITALICIO,
        }
    if daily_budget is None:
        return {
            "tipo_orcamento": None,
            "orcamento_mensal_brl": None,
            "media_diaria": base["media_diaria"],
            "projecao": base["projecao"],
            "gasto_pct_do_orcamento_mensal": None,
            "projecao_vs_orcamento_pct": None,
            "observacao": "orçamento não legível: sem percentual contra o orçamento",
        }
    mensal = round(daily_budget * dias_no_mes, 2)
    return {
        "tipo_orcamento": "diario",
        "orcamento_mensal_brl": mensal,
        "media_diaria": base["media_diaria"],
        "projecao": base["projecao"],
        "gasto_pct_do_orcamento_mensal": arredondado(percentual(razao(gasto_fechado, mensal)), 1),
        "projecao_vs_orcamento_pct": arredondado(percentual(razao(base["projecao"], mensal)), 1),
        "observacao": None,
    }
