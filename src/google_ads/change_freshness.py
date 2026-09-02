"""F131: fronteira de indexacao do `change_event` — puro, sem SDK nem I/O.

`change_event` e audit log LAGGING. O lag nao tem contrato: medido de ~3h
(conta 786-223-0676, 2026-09-02) a >4 dias (dogfood 25/05) na MESMA conta. Sem
uma fronteira medida, "zero linhas" e a mesma resposta para "nada mudou" e
"mudou e ainda nao indexou" — e quem consome isso e o `detect_drift`, que e
tool de seguranca.

Duas fronteiras entram aqui, com custos bem diferentes:

- **da conta**: sonda propria, SEM os filtros do usuario. Herdar
  `resource_types` reproduziria a cegueira que se quer medir.
- **do recorte**: `max` das linhas que a query principal ja devolveu — custo
  zero, o dado ja veio.

O estado que justifica as duas e o AMBIGUO (conta fresca, recorte vazio): sem
a fronteira da conta ele se parece com "nada mudou"; sem a do recorte ele se
parece com "esta tudo certo".
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

# Formato em que o Google devolve change_date_time (sem os microssegundos, que
# nao ajudam o gestor a decidir nada).
_FMT = "%Y-%m-%d %H:%M:%S"


def _fmt(dt: datetime | None) -> str | None:
    return dt.strftime(_FMT) if dt is not None else None


def assess_freshness(
    *,
    account_frontier: datetime | None,
    slice_frontier: datetime | None,
    window_end: date,
) -> dict[str, Any]:
    """Classifica a confiabilidade da resposta contra a fronteira de indexacao.

    Args:
        account_frontier: evento mais recente indexado na conta INTEIRA, sem
            filtro. `None` quando a sonda nao devolveu linha nenhuma.
        slice_frontier: evento mais recente entre as linhas que a query
            principal devolveu. `None` quando o recorte veio vazio.
        window_end: fim (inclusive) da janela que o usuario pediu.

    Returns:
        dict com `account_frontier`/`slice_frontier` serializados, `status`
        (`confiavel` | `ambiguo` | `atrasado` | `indeterminado`) e `warning`
        em PT-BR (`None` so quando status e `confiavel`).
    """
    base: dict[str, Any] = {
        "account_frontier": _fmt(account_frontier),
        "slice_frontier": _fmt(slice_frontier),
    }

    if account_frontier is None:
        return {
            **base,
            "status": "indeterminado",
            "warning": (
                "Nao foi possivel estabelecer o frescor: a conta nao tem nenhum "
                "change_event indexado na janela de retencao. Um resultado vazio "
                "aqui NAO significa que nada mudou. Para validar estado atual, "
                "use run_gaql como leading indicator."
            ),
        }

    if account_frontier.date() < window_end:
        return {
            **base,
            "status": "atrasado",
            "warning": (
                f"A janela pedida termina em {window_end.isoformat()}, mas o evento "
                f"mais recente indexado nesta conta e de {_fmt(account_frontier)}. "
                "O trecho final da janela ainda nao indexou, entao ausencia de "
                "linhas nao prova ausencia de mudanca. O lag do change_event nao "
                "tem contrato (ja medido de ~3h a >4 dias na mesma conta). Para "
                "validar estado atual, use run_gaql como leading indicator."
            ),
        }

    if slice_frontier is None:
        return {
            **base,
            "status": "ambiguo",
            "warning": (
                "A conta esta indexada ate o fim da janela pedida, mas este recorte "
                "voltou vazio. Isso e ambiguo: ou nao houve mudanca com estes "
                "filtros, ou este tipo de recurso especifico lagou. Se a resposta "
                "for usada para decidir, confirme por run_gaql."
            ),
        }

    return {**base, "status": "confiavel", "warning": None}
