# bucket: defer
"""Tool: update_ad_schedule — define a GRADE COMPLETA de veiculacao (spec §4).

Conjunto, nao incremento: o que fica de fora para de servir (§4.1). O diff e
calculado AQUI, no dry-run, por conteudo (§4.4), e viaja no payload pendente —
o builder e burro, e o que o gestor confirma e exatamente o que se aplica.
Dry-run normativo (§4.2): CPA do que sai lado a lado com o que fica.
"""

from typing import Any

from src.db import connection
from src.google_ads.account_clock import resolve_account_today
from src.google_ads.ad_schedule import (
    MetricCell,
    Window,
    diff_schedule,
    partition_metrics,
    schedule_fingerprint,
    summarize_current,
    validate_windows,
    window_from_input,
)
from src.google_ads.queries._common import InvalidDateRangeError, resolve_date_window
from src.google_ads.queries.ad_schedule import (
    GRADE_LIMIT,
    ad_schedule_query,
    campaign_budget_query,
    campaigns_on_budgets_query,
    day_hour_metrics_query,
    parse_ad_schedule_row,
    parse_campaign_budget_row,
    parse_campaign_on_budget_row,
    parse_day_hour_row,
)
from src.google_ads.reports import run_report
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import error_envelope, preview_envelope
from src.mcp.tools._registry import register_tool
from src.mcp.tools.get_ad_schedule import rows_to_current

_JANELA = {
    "type": "object",
    "properties": {
        "day_of_week": {
            "type": "string",
            "enum": [
                "MONDAY",
                "TUESDAY",
                "WEDNESDAY",
                "THURSDAY",
                "FRIDAY",
                "SATURDAY",
                "SUNDAY",
            ],
        },
        "start_hour": {"type": "integer", "minimum": 0, "maximum": 23},
        "start_minute": {"type": "integer", "enum": [0, 15, 30, 45], "default": 0},
        "end_hour": {"type": "integer", "minimum": 0, "maximum": 24},
        "end_minute": {"type": "integer", "enum": [0, 15, 30, 45], "default": 0},
    },
    "required": ["day_of_week", "start_hour", "end_hour"],
    "additionalProperties": False,
}

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "campaign_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
            "maxItems": 20,
        },
        "windows": {
            "type": "array",
            "items": _JANELA,
            "minItems": 1,
            "maxItems": 168,
            "description": "A GRADE COMPLETA desejada. O que nao estiver aqui deixa de servir.",
        },
        "bid_modifier": {
            "type": "number",
            "minimum": 0.1,
            "maximum": 10.0,
            "description": "Opcional; aplica as janelas novas e ATUALIZA (sem recriar) as existentes que tenham valor diferente.",
        },
        "date_range": {
            "type": "string",
            "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "LAST_90_DAYS"],
            "default": "LAST_30_DAYS",
            "description": "Janela das metricas do preview (decisao 03/09: 30 dias com override).",
        },
        "start_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
        "end_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
    },
    "required": ["customer_id", "campaign_ids", "windows"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[DEFER] Define a GRADE COMPLETA de veiculacao (ad schedule) de 1-20 campanhas. "
    "CONJUNTO, nao incremento: `windows[]` e a grade inteira desejada; o que nao "
    "estiver nela DEIXA DE SERVIR (mandar so 'seg-sex 07-17' numa campanha que servia "
    "24x7 desliga o fim de semana). Always-CONFIRM: devolve preview + confirmation_token; "
    "aplique via apply_change. O preview mostra, por campanha, as janelas que entram e "
    "que saem e — regra normativa — cost_brl, conversions e CPA do que SAI lado a lado "
    "com o CPA do que FICA (custo sozinho nao responde 'o que estou desligando e melhor "
    "ou pior do que fica?'; na MO-JP o fim de semana tinha CPA R$18,59 contra R$23,59). "
    "Campanha REMOVED e recusada; PAUSED passa com `aviso_status` (metricas historicas, "
    "grade sem efeito em entrega enquanto pausada). "
    "Metricas por hora cheia (janelas com minutos sao aproximadas), janela default de 30 "
    "dias com override por date_range/start_date+end_date. Grade identica a atual = "
    "`status: no_changes`, ZERO operacoes, sem token (recriar criterios identicos custa "
    "~14 dias de re-learning). Mudar so bid_modifier faz UPDATE do criterio, nao recria. "
    "Orcamento compartilhado: desligar faixa NAO economiza, REALOCA gasto para as faixas "
    "e campanhas irmas do mesmo orcamento (inclusive as fora do lote) — o preview lista "
    "`shared_budgets` com as irmas; nao recusa. Minutos so 0/15/30/45 (API); `end_hour: 24` "
    "= ate o fim do dia. Lote com partial_failure: cada campanha reportada; sem rollback. "
    "Pos-apply, apply_change reconsulta a grade por GAQL e devolve `resulting_schedule`."
)


@register_tool(
    name="update_ad_schedule", description=_DESCRIPTION, input_schema=_SCHEMA, bucket="defer"
)
async def update_ad_schedule(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    campaign_ids: list[str] = args["campaign_ids"]
    bid_modifier = args.get("bid_modifier")

    erro = validate_windows(args["windows"])
    if erro:
        return error_envelope("update_ad_schedule", erro, customer_id=customer_id)
    desired = [window_from_input(w) for w in args["windows"]]

    today = await resolve_account_today(customer_id)
    try:
        start, end = resolve_date_window(
            date_range=args.get("date_range", "LAST_30_DAYS"),
            start_date=args.get("start_date"),
            end_date=args.get("end_date"),
            today=today,
        )
    except InvalidDateRangeError as e:
        return error_envelope(
            "update_ad_schedule", f"periodo invalido: {e}", customer_id=customer_id
        )

    async def _consulta(query: str, parser: Any, *, audited: bool = False) -> list[dict[str, Any]]:
        return await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=query,
            row_formatter=parser,
            operation_name="update_ad_schedule",
            audit_this_call=audited,
            params_summary=(
                {"campaign_ids": campaign_ids, "windows": len(desired)} if audited else None
            ),
        )

    grade_rows = await _consulta(
        ad_schedule_query(campaign_ids=campaign_ids, status="enabled", limit=GRADE_LIMIT),
        parse_ad_schedule_row,
        audited=True,
    )
    if len(grade_rows) > GRADE_LIMIT:
        # F98: a query pede limit+1 justamente para o corte ser visivel. Diffar grade
        # truncada erra nas DUAS direcoes — `add` de janela que ja existe e `remove`
        # omitido de janela nunca lida — e isto e caminho de escrita.
        return error_envelope(
            "update_ad_schedule",
            f"a grade atual destas campanhas passa de {GRADE_LIMIT} janelas e nao coube "
            "na leitura: o diff sairia parcial e apagaria janelas que nao foram lidas. "
            "Nenhuma operacao foi montada — reduza campaign_ids e refaca por lotes.",
            customer_id=customer_id,
        )
    orcamentos = await _consulta(
        campaign_budget_query(campaign_ids=campaign_ids), parse_campaign_budget_row
    )
    status_da_campanha = {o["campaign_id"]: o["status"] for o in orcamentos}
    faltando = [cid for cid in campaign_ids if cid not in status_da_campanha]
    if faltando:
        # A mensagem antiga dizia "(ou removidas)" — mas com `campaign_ids` a query NAO
        # derruba REMOVED, entao removida e ENCONTRADA. Afirmar checagem que nao existe
        # e o defeito; a checagem de REMOVED vem logo abaixo, agora de verdade.
        return error_envelope(
            "update_ad_schedule",
            f"campaign_ids nao encontradas nesta conta: {faltando}. Nenhuma operacao foi montada.",
            customer_id=customer_id,
        )
    removidas = [cid for cid in campaign_ids if status_da_campanha[cid] == "REMOVED"]
    if removidas:
        return error_envelope(
            "update_ad_schedule",
            f"campaign_ids com status REMOVED: {removidas}. Campanha removida nao volta "
            "a servir e nao aceita mudanca de grade. Nenhuma operacao foi montada.",
            customer_id=customer_id,
        )
    metricas = await _consulta(
        day_hour_metrics_query(campaign_ids=campaign_ids, start=start, end=end),
        parse_day_hour_row,
    )

    atual = rows_to_current(grade_rows)
    ops: list[dict[str, Any]] = []
    preview: dict[str, Any] = {}
    for cid in campaign_ids:
        current = atual.get(cid, [])
        diff = diff_schedule(current, desired, bid_modifier)
        before = [c.window for c in current] if current else None  # None = 24x7
        cells = [
            MetricCell(m["day_of_week"], m["hour"], m["cost_micros"], m["conversions"])
            for m in metricas
            if m["campaign_id"] == cid
        ]
        preview[cid] = {
            "was_24x7": not current,
            "campaign_status": status_da_campanha[cid],
            "aviso_status": _aviso_status(status_da_campanha[cid]),
            "current": summarize_current(current),
            "windows_added": [_w(w) for w in diff.to_add],
            "windows_removed": [_w(c.window) for c in diff.to_remove],
            "bid_modifier_updated": [_w(c.window) for c in diff.to_update],
            "metrics": partition_metrics(cells, before, desired),
        }
        ops += [
            {"kind": "add", "campaign_id": cid, "window": _w(w), "bid_modifier": bid_modifier}
            for w in diff.to_add
        ]
        ops += [{"kind": "remove", "resource_name": c.resource_name} for c in diff.to_remove]
        ops += [
            {"kind": "update", "resource_name": c.resource_name, "bid_modifier": bid_modifier}
            for c in diff.to_update
        ]

    if not ops:
        return {
            "status": "no_changes",
            "operation": "update_ad_schedule",
            "customer_id": customer_id,
            "no_changes": True,
            "message": (
                "A grade desejada e identica a atual em todas as campanhas: nenhuma "
                "operacao emitida (recriar criterios identicos custaria re-learning)."
            ),
            "current_schedule": {cid: preview[cid]["current"] for cid in campaign_ids},
        }

    shared_budgets = await _blocos_de_orcamento_compartilhado(_consulta, orcamentos, campaign_ids)

    target_count = len(ops)
    risk = classify(operation="update_ad_schedule", params={"target_count": target_count})
    resumo = (
        f"Redefinir a grade de {len(campaign_ids)} campanha(s): "
        f"{sum(len(p['windows_added']) for p in preview.values())} janela(s) entram, "
        f"{sum(len(p['windows_removed']) for p in preview.values())} saem, "
        f"{sum(len(p['bid_modifier_updated']) for p in preview.values())} mudam bid_modifier "
        f"({target_count} operacoes). Janelas fora da grade DEIXAM de servir."
    )
    payload = {
        "campaign_ids": campaign_ids,
        # A grade PEDIDA e o baseline OBSERVADO viajam com o delta. Sem a primeira,
        # apply_change nao tem contra o que comparar a grade resultante (§4.6 + §7);
        # sem o segundo, ele aplica resource_names de ate 10 min atras contra um
        # estado que ninguem verificou (Ruling 10 — concorrencia otimista).
        "windows": [_w(w) for w in desired],
        "current_keys": schedule_fingerprint(atual, campaign_ids),
        "ops": ops,
        "__target_count__": target_count,
        "__partial_failure__": True,
        "__params_summary__": {
            "target_count": target_count,
            "campaigns": len(campaign_ids),
            "window_days": (end - start).days + 1,
        },
    }
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_ad_schedule",
            payload=payload,
            blast_summary=resumo,
        )
    return preview_envelope(
        "update_ad_schedule",
        customer_id,
        resumo,
        token,
        confirmation_reason=risk.reason,
        target_count=target_count,
        preview=preview,
        shared_budgets=shared_budgets,
        metrics_window={
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": (end - start).days + 1,
        },
    )


def _aviso_status(status: str) -> str | None:
    """PAUSED nao recusa — avisa (F52/F90). Toda a narrativa de CPA da §4.2 pode estar
    descrevendo campanha inerte, e a grade nova nao muda entrega enquanto ela nao voltar."""
    if status == "ENABLED":
        return None
    if status == "PAUSED":
        return (
            "campanha PAUSED: as metricas abaixo sao historicas e a grade nao afeta "
            "entrega enquanto ela estiver pausada"
        )
    return (
        f"campanha {status}: nao esta servindo, entao as metricas abaixo sao historicas "
        "e a grade nova nao afeta entrega enquanto o status nao voltar a ENABLED"
    )


def _w(w: Window) -> dict[str, Any]:
    return {
        "day_of_week": w.day_of_week,
        "start_hour": w.start_hour,
        "start_minute": w.start_minute,
        "end_hour": w.end_hour,
        "end_minute": w.end_minute,
    }


async def _blocos_de_orcamento_compartilhado(
    consulta: Any, orcamentos: list[dict[str, Any]], campaign_ids: list[str]
) -> list[dict[str, Any]]:
    """Spec §4.3 + decisao 03/09: um bloco por orcamento compartilhado, com as irmas fora do lote. Avisa; nao recusa."""
    compartilhados = {o["budget_resource_name"]: o for o in orcamentos if o["explicitly_shared"]}
    if not compartilhados:
        return []
    irmas = await consulta(
        campaigns_on_budgets_query(budget_resource_names=list(compartilhados)),
        parse_campaign_on_budget_row,
    )
    no_lote = set(campaign_ids)
    blocos: list[dict[str, Any]] = []
    for rn, o in compartilhados.items():
        todas = [i for i in irmas if i["budget_resource_name"] == rn]
        dentro = sorted(i["campaign_id"] for i in todas if i["campaign_id"] in no_lote)
        fora = [
            {
                "campaign_id": i["campaign_id"],
                "campaign_name": i["campaign_name"],
                "status": i["status"],
            }
            for i in todas
            if i["campaign_id"] not in no_lote
        ]
        ativas = sum(1 for i in todas if i["status"] == "ENABLED")
        ativas_fora_do_lote = sum(1 for i in fora if i["status"] == "ENABLED")
        blocos.append(
            {
                "budget_id": o["budget_id"],
                "budget_resource_name": rn,
                "explicitly_shared": True,
                "amount_brl": o["amount_brl"],
                "campaigns_in_batch": dentro,
                "campaigns_outside_batch": fora,
                "ativas_fora_do_lote": ativas_fora_do_lote,
                "warning_pt": (
                    f"Orcamento compartilhado {o['budget_id']} (R$ {o['amount_brl']:.2f}/dia) "
                    f"e de {len(todas)} campanha(s), {ativas} ativa(s); {len(dentro)} no lote, "
                    f"{len(fora)} fora ({ativas_fora_do_lote} ativa(s)). Desligar faixas aqui "
                    "NAO devolve dinheiro: realoca a pressao para as faixas e campanhas irmas "
                    "ATIVAS que sobram, inclusive as fora do lote. Em quanto tempo e com que "
                    "completude a verba se redistribui e pacing do Google — nao ha como medir "
                    "por API."
                ),
            }
        )
    return blocos
