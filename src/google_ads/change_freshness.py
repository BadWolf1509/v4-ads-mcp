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


def _em_curso(account_frontier: datetime, today: date) -> str:
    return (
        f"A janela pedida alcanca o dia corrente da conta ({today.isoformat()}) ou passa "
        f"dele, e o dia ainda nao fechou. A conta esta indexada ate {_fmt(account_frontier)}, "
        "mas isso e o evento mais recente VISTO, nao garantia de que nada aconteceu depois "
        "dele. Eventos posteriores podem existir e ainda nao estar indexados. Para o dia "
        "corrente, use run_gaql como leading indicator; para um veredito fechado, consulte "
        "uma janela que termine ontem ou antes."
    )


def assess_freshness(
    *,
    account_frontier: datetime | None,
    slice_frontier: datetime | None,
    window_end: date,
    today: date,
) -> dict[str, Any]:
    """Classifica a confiabilidade da resposta contra a fronteira de indexacao.

    Args:
        account_frontier: evento mais recente indexado na conta INTEIRA, sem
            filtro. `None` quando a sonda nao devolveu linha nenhuma.
        slice_frontier: evento mais recente entre as linhas que a query
            principal devolveu. `None` quando o recorte veio vazio.
        window_end: fim (inclusive) da janela que o usuario pediu.
        today: dia corrente NO FUSO DA CONTA (F141). Nao o do servidor.

    Returns:
        dict com `account_frontier`/`slice_frontier` serializados, `status` e
        `warning` em PT-BR (`None` so quando status e `confiavel`).

    Status, na ordem em que sao decididos — a ordem e parte do contrato:

    - `indeterminado`: sem fronteira. A sonda nao viu evento nenhum na retencao.
    - `nao_coberto` (F143, ex-`atrasado`): a fronteira e anterior ao fim da
      janela. E um FATO com duas explicacoes — lag de indexacao OU conta sem
      atividade — e o texto admite as duas em vez de afirmar a primeira. Em
      conta de baixa atividade, a segunda domina; rotulo que afirmava lag em
      condicao normal treinava a ignorar o rotulo.
    - `em_curso` (F144): a janela alcanca o dia corrente da conta ou passa
      dele. Janela ALEM de hoje e decidida ANTES de `nao_coberto` (dias que nao
      aconteceram nao sao lag nem silencio); janela ATE hoje, DEPOIS. `account_frontier` diz "o mais recente que eu vi", NAO "vi tudo
      ate aqui": com o dia aberto, sempre pode haver evento posterior a
      fronteira e anterior ao fim do dia. Uma remocao de campanha real ficou
      fora da resposta com `confiavel` por isso. Decidido DEPOIS de
      `nao_coberto` de proposito: fronteira velha e o fato mais grave e ganha
      o rotulo; `em_curso` fica sendo o caso estreito "tao fresco quanto da,
      mas o dia nao fechou".
    - `ambiguo`: conta em dia, recorte vazio. Ou nao houve mudanca com estes
      filtros, ou este tipo de recurso especifico lagou.
    - `confiavel`: janela fechada no passado, fronteira depois dela, recorte
      com linhas.
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

    # Janela ALEM de hoje: nao e lag nem silencio, sao dias que nao aconteceram.
    # Tem que vir antes de `nao_coberto`, senao o texto afirmaria "lag ou conta
    # parada" sobre o futuro. (O teste do RED pegou isto antes do codigo sair.)
    if window_end > today:
        return {**base, "status": "em_curso", "warning": _em_curso(account_frontier, today)}

    if account_frontier.date() < window_end:
        return {
            **base,
            "status": "nao_coberto",
            "warning": (
                f"O evento mais recente indexado nesta conta e de {_fmt(account_frontier)}, "
                f"anterior ao fim da janela pedida ({window_end.isoformat()}). Isso e "
                "compativel com duas coisas: lag de indexacao do change_event (sem "
                "contrato — ja medido de ~6 min a >4 dias) OU ausencia de atividade na "
                "conta desde entao. Em conta de baixa atividade, a segunda e a mais "
                "provavel. Ausencia de linhas no trecho final nao prova nem uma nem "
                "outra. Para validar estado atual, use run_gaql como leading indicator."
            ),
        }

    # Janela ATE hoje, com a fronteira ja em hoje: tao fresco quanto da, mas o dia
    # nao fechou. Decidido DEPOIS de `nao_coberto` de proposito — fronteira de
    # ontem + janela ate hoje e o fato mais grave e ganha o rotulo.
    if window_end == today:
        return {**base, "status": "em_curso", "warning": _em_curso(account_frontier, today)}

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
