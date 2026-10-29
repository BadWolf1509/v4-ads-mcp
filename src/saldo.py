"""Regra comum de saldo e dias restantes — uma conta so para o Google e a Meta.

Puro e sem I/O: recebe o gasto diario e o restante que o modulo da plataforma ja leu, e
devolve a situacao. Nao importa `google_ads` nem `meta_ads` (primitivo neutro, como
`janelas.py`); `sem_teto` e `indeterminada` sao decididos pelo modulo da plataforma antes
de chamar `classificar`. Spec: docs/superpowers/specs/2026-10-28-saldo-da-conta-design.md §3.1.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

Situacao = Literal["sem_teto", "esgotada", "acabando", "com_saldo", "sem_gasto", "indeterminada"]

_DIAS_MEDIA = 7
_DIAS_HISTORICO = 30
_LIMITE_ACABANDO = 7


@dataclass(frozen=True)
class Classificacao:
    situacao: Situacao
    dias_restantes: float | None
    dias_pelo_dinheiro: float | None
    trava_por_data: bool
    motivo: str | None


def serie_diaria(gastos: Mapping[date, float], *, ontem: date, dias: int) -> list[float]:
    """Os `dias` dias que terminam em `ontem` (do mais antigo ao mais novo); ausente = 0.0."""
    return [gastos.get(ontem - timedelta(days=i), 0.0) for i in range(dias - 1, -1, -1)]


def media_7d(gastos: Mapping[date, float], *, ontem: date) -> float:
    """Media diaria dos 7 dias completos ate `ontem`; dia sem gasto entra como zero."""
    serie = serie_diaria(gastos, ontem=ontem, dias=_DIAS_MEDIA)
    return round(sum(serie) / _DIAS_MEDIA, 2)


def media_dias_com_gasto(gastos: Mapping[date, float], *, ontem: date) -> float | None:
    """Media dos dias com gasto (> 0) nos 30 dias ate `ontem`; None se nao houve nenhum."""
    com_gasto = [g for g in serie_diaria(gastos, ontem=ontem, dias=_DIAS_HISTORICO) if g > 0]
    if not com_gasto:
        return None
    return round(sum(com_gasto) / len(com_gasto), 2)


def _esgotada(motivo: str | None) -> Classificacao:
    return Classificacao("esgotada", None, None, False, motivo)


def classificar(
    *,
    restante: float,
    media7: float,
    media_com_gasto: float | None,
    dias_ate_fim: int | None = None,
) -> Classificacao:
    """Situacao de uma conta COM teto e legivel, na ordem da spec §3.1."""
    if dias_ate_fim is not None and dias_ate_fim < 0:
        return _esgotada("orçamento da conta encerrado")
    if restante <= 0:
        return _esgotada(None)
    # "menos de um dia de gasto" usa a media dos dias com gasto em 30 dias: a conta que
    # acabou tem media de 7 dias ~0 e a regra de 7 dias nunca a chamaria de esgotada.
    if media_com_gasto is not None and restante < media_com_gasto:
        return _esgotada("restante menor que um dia de gasto")
    if media7 == 0:
        return Classificacao("sem_gasto", None, None, False, "sem gasto nos últimos 7 dias")

    dias_pelo_dinheiro = restante / media7
    trava_por_data = dias_ate_fim is not None and dias_ate_fim < dias_pelo_dinheiro
    dias_restantes = (
        float(dias_ate_fim) if trava_por_data and dias_ate_fim is not None else dias_pelo_dinheiro
    )
    situacao: Situacao = "acabando" if dias_restantes <= _LIMITE_ACABANDO else "com_saldo"
    return Classificacao(
        situacao,
        round(dias_restantes, 1),
        round(dias_pelo_dinheiro, 1),
        trava_por_data,
        None,
    )
