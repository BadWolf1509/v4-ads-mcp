"""Saldo do orcamento de conta Google (spec saldo-da-conta §1, §3.2). Puro, sem I/O.

Recebe as linhas de `account_budget` ja formatadas e o gasto diario; decide `sem_teto` /
`indeterminada` aqui e delega o resto a `src.saldo.classificar`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from src.google_ads.queries._common import micros_to_currency
from src.saldo import classificar, media_7d, media_dias_com_gasto

_AVISO_VIGENTES = (
    "mais de um orçamento de conta vigente; usado o de início mais recente (não medido, spec §1.5)"
)


def _data(texto: str) -> date:
    """`'2021-02-26 15:37:54'` (ou so a data) -> date. Compara datas, nao instantes."""
    return datetime.fromisoformat(texto).date()


def _vigente(o: dict[str, Any], hoje: date) -> bool:
    if _data(o["inicio"]) > hoje:
        return False
    return o["fim"] is None or _data(o["fim"]) >= hoje


def montar_saldo_google(
    orcamentos: list[dict[str, Any]], gastos: Mapping[date, float], *, hoje: date
) -> dict[str, Any]:
    ontem = hoje - timedelta(days=1)
    media7 = media_7d(gastos, ontem=ontem)
    base: dict[str, Any] = {
        "situacao": "indeterminada",
        "motivo": None,
        "tipo_de_teto": None,
        "restante_brl": None,
        "limite_ajustado_brl": None,
        "gasto_acumulado_brl": None,
        "ajustes_brl": None,
        "dias_restantes": None,
        "dias_ate_fim": None,
        "data_fim": None,
        "trava_primeiro": None,
        "media_diaria_7d_brl": media7,
        "orcamento_pendente": False,
        "aproximado": True,
        "avisos": [],
    }
    if not orcamentos:
        return {**base, "motivo": "conta sem orçamento de conta"}

    avisos: list[str] = []
    if sum(1 for o in orcamentos if _vigente(o, hoje)) >= 2:
        avisos.append(_AVISO_VIGENTES)
    # a query ja ordena, mas o modulo nao depende disso: escolhe pelo inicio mais recente
    # entre os vigentes; sem nenhum (ex.: todos encerrados) cai no mais recente de todos,
    # e o encerrado sai como esgotada. Inicio futuro nunca esconde o vigente.
    candidatos = [o for o in orcamentos if _vigente(o, hoje)] or orcamentos
    atual = max(candidatos, key=lambda o: _data(o["inicio"]))
    base = {
        **base,
        "avisos": avisos,
        "orcamento_pendente": bool(atual["pendente"]),
        "data_fim": atual["fim"],
    }

    if atual["tipo_limite"] == "INFINITE":
        return {**base, "situacao": "sem_teto", "tipo_de_teto": "sem_teto"}

    limite = atual["limite_ajustado_micros"]
    if limite is None:
        return {**base, "motivo": "orçamento de conta sem limite lido"}
    restante = micros_to_currency(limite - atual["gasto_micros"])
    dias_ate_fim = (_data(atual["fim"]) - hoje).days if atual["fim"] else None
    c = classificar(
        restante=restante,
        media7=media7,
        media_com_gasto=media_dias_com_gasto(gastos, ontem=ontem),
        dias_ate_fim=dias_ate_fim,
    )
    return {
        **base,
        "situacao": c.situacao,
        "motivo": c.motivo,
        "tipo_de_teto": "finito",
        "restante_brl": restante,
        "limite_ajustado_brl": micros_to_currency(limite),
        "gasto_acumulado_brl": micros_to_currency(atual["gasto_micros"]),
        "ajustes_brl": micros_to_currency(atual["ajustes_micros"]),
        "dias_restantes": c.dias_restantes,
        "dias_ate_fim": dias_ate_fim,
        "trava_primeiro": "data_fim" if c.trava_por_data else "saldo",
    }
