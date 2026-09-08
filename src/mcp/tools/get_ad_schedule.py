# bucket: always
"""Tool: get_ad_schedule — grade de veiculacao (dia x hora) por campanha (spec §3).

Campanha SEM criterio de AD_SCHEDULE serve 24x7. Essa distincao nao pode
ficar implicita numa lista vazia — mesma classe do F131 (vazio que quer dizer
duas coisas). Por isso `schedule_summary` existe por campanha, mesmo sem janela.
"""

import asyncio
from collections.abc import Iterable
from typing import Any

from src.google_ads.account_clock import resolve_account_today
from src.google_ads.ad_schedule import (
    BLOCOS_PADRAO,
    CurrentWindow,
    MetricCell,
    Window,
    partition_by_blocks,
    summarize_current,
)
from src.google_ads.queries._common import resolve_date_window
from src.google_ads.queries.ad_schedule import (
    ad_schedule_query,
    campaign_budget_query,
    day_hour_metrics_query,
    parse_ad_schedule_row,
    parse_campaign_budget_row,
    parse_day_hour_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._common import aplicar_limite
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "campaign_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
            "maxItems": 50,
            "description": "Opcional. Default: conta inteira.",
        },
        "status": {
            "type": "string",
            "enum": ["enabled", "paused", "removed", "all"],
            "default": "enabled",
            "description": "Status dos CRITERIOS de agenda (nao da campanha).",
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
        "include_metrics": {
            "type": "boolean",
            "default": False,
            "description": "Traz CPA por bloco horario (comercial / fora de hora / fim de semana) por campanha. Custa uma consulta conjunta dia x hora a mais.",
        },
        "date_range": {
            "type": "string",
            "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "LAST_90_DAYS"],
            "default": "LAST_30_DAYS",
            "description": "Janela das metricas de include_metrics (ignorado sem a flag); override por start_date+end_date.",
        },
        "start_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
        "end_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[CORE] Grade de veiculacao (ad schedule) por campanha: uma linha por janela "
    "(day_of_week, start_hour/minute, end_hour/minute, bid_modifier, status, "
    "criterion_id, resource_name) e um `schedule_summary` por campanha com "
    "`has_schedule`, `hours_per_week`, `budget_is_shared` e `campaign_status` "
    "(grade de campanha PAUSED nao afeta entrega). ATENCAO: campanha "
    "SEM nenhuma janela serve 24x7 — `has_schedule: false` e `hours_per_week: 168` "
    "dizem isso explicitamente; nao leia lista vazia como 'nao serve'. Isso vale SO "
    "quando a resposta nao veio cortada: sob `truncated: true`, tem `has_schedule: "
    "null`, `hours_per_week: null`, `windows: null` e "
    "`schedule_desconhecida_por_truncamento: true` no resumo (1) toda campanha cuja "
    "grade caiu inteira alem do corte do `limit` e (2) a campanha da BORDA do corte "
    "— a ultima que ainda tem linha na resposta, cuja grade pode ter sido cortada no "
    "meio; as linhas vem ordenadas por campanha, entao havendo corte existe sempre "
    "exatamente uma nessa posicao, e nao da para saber se ela veio inteira. "
    "`null` significa 'nao sei se tem grade ou nao, aumente o `limit`', "
    "nunca leia `null` como false nem como 24x7. Janela cobre "
    "[inicio, fim); `end_hour: 24` = ate o fim do dia; minutos so 0/15/30/45 (API). "
    "Uma campanha pode ter ate 7x24 janelas: `limit` (default 200, teto 1000) corta e "
    "`truncated: true` avisa. `budget_is_shared` vem de campaign_budget.explicitly_shared "
    "— importa porque desligar faixa em orcamento compartilhado REALOCA gasto, nao "
    "economiza (ver update_ad_schedule). `include_metrics: true` acrescenta "
    "`metrics_por_bloco` por campanha — custo/conversoes/CPA particionados em comercial "
    "(seg-sex 08-18h), fora_de_hora e fim_de_semana (BLOCOS_PADRAO) mais um balde `outros` "
    "— a mesma conjunta cara dia x hora que antes so aparecia no dry-run do "
    "update_ad_schedule, agora sem exigir intencao de mutar. Exige `campaign_ids` (a "
    "conjunta nao roda sobre a conta inteira); janela default 30 dias, override por "
    "date_range/start_date+end_date. Com a flag, o retorno tambem traz `period` "
    "(from/to) com a janela concreta que o preset resolveu no fuso da conta. SEM a "
    "flag nenhuma consulta dia x hora sai, e `period` tambem fica de fora — metade "
    "do valor da flag e essa ausencia."
)


def rows_to_current(rows: list[dict[str, Any]]) -> dict[str, list[CurrentWindow]]:
    """Linhas do parser -> CurrentWindow por campanha (reusado pelo update_ad_schedule)."""
    por_campanha: dict[str, list[CurrentWindow]] = {}
    for r in rows:
        # Fix M6 (revisao final): popular o bid_modifier tambem no `Window`, nao
        # so no `CurrentWindow` que o envolve — antes ficava sempre `None` aqui
        # enquanto `CurrentWindow.bid_modifier` tinha o valor real. Nenhum
        # call-site le `c.window.bid_modifier` hoje, mas `modificador_efetivo`
        # aceita qualquer `Window` e devolveria o escalar em silencio se algum
        # dia alguem passasse `c.window` por engano em vez de `c`.
        w = Window(
            r["day_of_week"],
            r["start_hour"],
            r["start_minute"],
            r["end_hour"],
            r["end_minute"],
            r["bid_modifier"],
        )
        por_campanha.setdefault(r["campaign_id"], []).append(
            CurrentWindow(
                window=w,
                resource_name=r["resource_name"],
                criterion_id=r["criterion_id"],
                bid_modifier=r["bid_modifier"],
            )
        )
    return por_campanha


def campanhas_com_grade_incerta(
    rows: list[dict[str, Any]],
    *,
    truncated: bool,
    campanhas: Iterable[str],
) -> set[str]:
    """Campanhas cuja grade NAO pode ser afirmada depois de uma leitura cortada.

    `rows` sao as linhas que SOBREVIVERAM ao corte (pos-`aplicar_limite`).
    Duas familias, e a segunda e a que faltava (residuo do F147):

    - a **ausente**: nenhuma linha dela sobreviveu, entao `summarize_current([])`
      a chamaria de "sem grade" — que na §3 quer dizer 24x7, o oposto do que a
      grade dela pode dizer;
    - a da **borda**: a dona da ULTIMA linha lida. `ad_schedule_query` ordena por
      `campaign.id`, entao as linhas chegam agrupadas e o corte cai DENTRO da
      grade de exatamente uma campanha — sempre existe uma nessa posicao quando
      houve corte. O resumo dela sairia calculado sobre a PARTE lida:
      `hours_per_week` subestimado, sem `null` e sem sinal nenhum.

    Nao ha como saber se o corte caiu no fim da grade da campanha da borda ou no
    meio dela — a resposta so tem as linhas que couberam. Adivinhar "esta
    completa" e o defeito original com outra roupa, entao a borda entra SEMPRE
    que houve corte.

    Fora de truncamento devolve conjunto vazio: nada aqui muda a leitura
    completa.
    """
    if not truncated:
        return set()
    lidas = {r["campaign_id"] for r in rows}
    incertas = {cid for cid in campanhas if cid not in lidas}
    if rows:
        incertas.add(rows[-1]["campaign_id"])
    return incertas & set(campanhas)


@register_tool(
    name="get_ad_schedule", description=_DESCRIPTION, input_schema=_SCHEMA, bucket="always"
)
async def get_ad_schedule(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    campaign_ids = args.get("campaign_ids")
    status = args.get("status", "enabled")
    limit = args.get("limit", 200)

    async def _consulta(query: str, parser: Any, *, audited: bool = False) -> list[dict[str, Any]]:
        return await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=query,
            row_formatter=parser,
            operation_name="get_ad_schedule",
            audit_this_call=audited,
            params_summary=(
                {"campaign_ids": campaign_ids, "status": status, "limit": limit}
                if audited
                else None
            ),
        )

    grade_rows, orcamentos = await asyncio.gather(
        _consulta(
            ad_schedule_query(campaign_ids=campaign_ids, status=status, limit=limit),
            parse_ad_schedule_row,
            audited=True,
        ),
        _consulta(campaign_budget_query(campaign_ids=campaign_ids), parse_campaign_budget_row),
    )
    grade_rows, truncated = aplicar_limite(grade_rows, limit)

    atual = rows_to_current(grade_rows)
    summary: dict[str, dict[str, Any]] = {}
    for o in orcamentos:
        cid = o["campaign_id"]
        summary[cid] = {
            "campaign_name": o["campaign_name"],
            # F52/F90: grade de campanha PAUSED nao afeta entrega. Sem o status, o
            # resumo descreve horas servidas de uma campanha que nao serve nenhuma.
            "campaign_status": o["status"],
            **summarize_current(atual.get(cid, [])),
            "budget_is_shared": o["explicitly_shared"],
        }

    # Task 4 (PR 4): `atual.get(cid, [])` acima nao distingue "campanha sem
    # nenhuma janela" de "campanha com janelas que cairam alem do corte do
    # `limit`" — as duas chegam como lista vazia, e `summarize_current([])`
    # sempre le a primeira. Sob `truncated`, toda campanha AUSENTE de `atual`
    # cai nesse limbo: nao sabemos se ela serve 24x7 ou se so nao coube na
    # pagina. `false`/`168` aqui e uma afirmacao sobre ENTREGA — nao se chuta
    # isso a partir de uma leitura parcial (mesma familia do F131: vazio que
    # quer dizer duas coisas).
    #
    # A2 (revisao final, residuo do F147): a campanha da BORDA cai no mesmo
    # limbo por outro caminho — parte da grade dela sobreviveu ao corte e o
    # resto nao, e o resumo sairia calculado sobre a parte, com
    # `hours_per_week` subestimado e nenhum sinal. As duas familias vivem em
    # `campanhas_com_grade_incerta`, que os DOIS gemeos chamam: separar as
    # clausulas de novo e como o F128 nasceu.
    incertas = campanhas_com_grade_incerta(grade_rows, truncated=truncated, campanhas=summary)
    for cid, resumo in summary.items():
        if cid in incertas:
            resumo["has_schedule"] = None
            resumo["hours_per_week"] = None
            # `windows` tambem, senao o resumo se contradiz: `has_schedule: null`
            # ao lado de `windows: 0` le como "zero janelas", que e justamente a
            # afirmacao que este bloco existe para nao fazer. Tres campos que
            # descrevem a mesma coisa desconhecida tem que dizer desconhecido
            # juntos.
            resumo["windows"] = None
            resumo["schedule_desconhecida_por_truncamento"] = True

    # Fix Important 2 (revisao final): period so existe quando include_metrics
    # pede a janela — aditivo, senao muda o contrato de quem so le a grade.
    period: dict[str, str] | None = None
    if args.get("include_metrics", False):
        if not campaign_ids:
            # `day_hour_metrics_query` recusa lista vazia (ValueError), e varrer a
            # conta inteira nesta conjunta dia x hora e caro sem necessidade — metade
            # do valor desta task e a consulta cara NAO sair sem campaign_ids
            # explicito (nota do brief). As duas consultas baratas de cima ja
            # rodaram; o que fica de fora e so a conjunta cara.
            return {
                "status": "error",
                "error_message": "include_metrics exige campaign_ids: a conjunta dia x hora "
                "e cara e nao roda sobre a conta inteira.",
            }
        today = await resolve_account_today(customer_id)
        start, end = resolve_date_window(
            date_range=args.get("date_range", "LAST_30_DAYS"),
            start_date=args.get("start_date"),
            end_date=args.get("end_date"),
            today=today,
        )
        period = {"from": start.isoformat(), "to": end.isoformat()}
        celulas = await _consulta(
            day_hour_metrics_query(campaign_ids=campaign_ids, start=start, end=end),
            parse_day_hour_row,
        )
        for cid, resumo in summary.items():
            do_cid = [
                MetricCell(m["day_of_week"], m["hour"], m["cost_micros"], m["conversions"])
                for m in celulas
                if m["campaign_id"] == cid
            ]
            resumo["metrics_por_bloco"] = partition_by_blocks(do_cid, BLOCOS_PADRAO)

    result: dict[str, Any] = {
        "customer_id": customer_id,
        "windows": grade_rows,
        "schedule_summary": summary,
        "truncated": truncated,
    }
    if period is not None:
        result["period"] = period
    return result
