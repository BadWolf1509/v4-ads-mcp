# bucket: always
"""Tool: get_change_history - audit-log of recent changes to the account.

Wraps the change_event GAQL resource with structured filters and a summary
block. Two V4 skills (auditoria-google-ads + analise-performance-google-ads)
call this as 'CRITICO antes de tudo' to detect:
- Auto-apply Recommendations (client_type em AUTO_APPLY_CLIENT_TYPES)
- Structural changes (geo settings, conversion actions, bidding strategy)
- Who changed what

Audited as a sensitive read.

Caveats (empirically verified against production change_event 2026-05-11,
re-confirmado em dogfood 2026-05-21 MO-JP, e refinado em dogfood 2026-05-25
MO-JP+CAB pós-reverts Pedro 21/05):
- Propagation lag: change_event é AUDIT LOG LAGGING, NOT real-time. **O lag
  não tem contrato**: medido de ~3h (conta 786-223-0676 em 2026-09-02 — writes
  às 11:28-11:43 invisíveis às 11:50 e presentes no fim da tarde) a >4 dias
  (dogfood 25/05, 3 dos 4 reverts Pedro de 21/05 ainda ausentes), na MESMA
  conta. F131: é por ser variável que a fronteira passou a ser MEDIDA a cada
  chamada e devolvida em `freshness`, em vez de prometida em prosa aqui. O lag
  afeta MÚLTIPLOS campos, não apenas `campaign.status` — também
  `ai_max_setting.enable_ai_max`, `asset_automation_settings`,
  `text_guidelines.messaging_restrictions`, etc.
- Padrão V4 pra validar estado ATUAL pós-mutação (revert/incident recovery):
  use `run_gaql FROM campaign` como LEADING indicator (real-time) e
  `get_change_history` como LAGGING (audit log). Se divergirem, confie no
  leading. Se um campo opcional não retornar no GAQL, está vazio/removido.
- 30-day window é a retenção documentada; alguns date_range presets podem
  bater limite ligeiramente menor. Nosso path usa explicit BETWEEN dates.
- Google não distingue 'user applied via Recommendations UI' de 'Google
  auto-apply' em change_event.client_type. summary.auto_applied_count
  conta a união dos dois valores de recommendations (F142);
  cross-reference auto-apply settings se intent matters.
"""

import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from src.google_ads.change_freshness import assess_freshness
from src.google_ads.drift_detection import AUTO_APPLY_CLIENT_TYPES
from src.google_ads.queries._common import parse_resource_path, resolve_date_window
from src.google_ads.queries.change_history import (
    change_event_frontier_query,
    change_history_query,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

# F23 fix Sprint 3b.38: Google's change_event retention is 30 days exclusive
# (start_date must be > today-30). Our LAST_30_DAYS preset resolves to
# yesterday-29 = today-30 = boundary case Google rejects with
# "The requested start date is too old."
#
# Mitigation: clamp resolved start_date to max(start, today-28) — 2-day
# safety margin against UTC drift + add warning to response payload.
# Non-breaking: existing callers receive valid data + new field they can ignore.
_RETENTION_SAFETY_DAYS = 28

_DATE_PRESETS = [
    "TODAY",
    "YESTERDAY",
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
    "LAST_90_DAYS",
    "THIS_MONTH",
    "LAST_MONTH",
    "THIS_WEEK",
    "LAST_WEEK",
]

# F135: espelha ChangeEventResourceType do SDK (v24, verificado 2026-09-02).
# NAO edite a mao sem rodar tests/unit/test_change_event_enum_guards.py — ele
# reconcilia esta lista com o enum do SDK e falha nas DUAS direcoes.
#
# A lista anterior era mantida a mao e divergiu em 13 posicoes: faltavam 10
# (entre elas `AD`, que e o que a API emite quando um RSA e editado, enquanto
# `AD_GROUP_AD` era o unico enum de anuncio oferecido — filtro por anuncio
# devolvia zero com 20 edicoes no dia) e sobravam 3 que a API rejeita com
# "Invalid enum value cannot be included in WHERE clause".
#
# Deliberadamente NAO derivado do SDK em runtime: o schema de uma tool MCP e
# contrato publico, e derivar faria um bump do lockfile mudar os valores
# aceitos sem diff nem revisao. Fonte autoritativa e o SDK; reconciliador e o
# guard no CI.
_RESOURCE_TYPES = [
    "AD",
    "AD_GROUP",
    "AD_GROUP_AD",
    "AD_GROUP_ASSET",
    "AD_GROUP_BID_MODIFIER",
    "AD_GROUP_CRITERION",
    "AD_GROUP_FEED",
    "ASSET",
    "ASSET_SET",
    "ASSET_SET_ASSET",
    "CAMPAIGN",
    "CAMPAIGN_ASSET",
    "CAMPAIGN_ASSET_SET",
    "CAMPAIGN_BUDGET",
    "CAMPAIGN_CRITERION",
    "CAMPAIGN_FEED",
    "CUSTOMER_ASSET",
    "FEED",
    "FEED_ITEM",
]

# ChangeClientType. Reconciliado com o enum do SDK pelo guard em
# `tests/unit/test_change_client_type_guards.py` — nao edite a mao sem
# rodar ele. A verificacao empirica de 2026-05-11 pegou os nomes certos
# mas deixou passar duas divergencias por dois meses (F142): um plural
# que nao existe e o valor de auto-apply por assinatura, que faltava.
_CLIENT_TYPES = [
    "UNSPECIFIED",
    "UNKNOWN",
    "GOOGLE_ADS_WEB_CLIENT",  # Web UI (Google Ads website)
    "GOOGLE_ADS_AUTOMATED_RULE",  # F142: era plural; a API rejeita o plural
    "GOOGLE_ADS_SCRIPTS",
    "GOOGLE_ADS_BULK_UPLOAD",
    "GOOGLE_ADS_API",
    "GOOGLE_ADS_EDITOR",
    "GOOGLE_ADS_MOBILE_APP",
    "GOOGLE_ADS_RECOMMENDATIONS",
    "GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION",  # F142: auto-apply por assinatura
    "SEARCH_ADS_360_SYNC",
    "SEARCH_ADS_360_POST",
    "INTERNAL_TOOL",
    "OTHER",
]

# A constante de auto-apply vive em `drift_detection` (fonte unica). Havia
# uma copia aqui, e copia divergente foi o vetor do F142.
#
# Google nao distingue "aplicado pelo gestor via UI de Recommendations" de
# "aplicado pelo auto-apply do Google" dentro de cada valor — skills que
# usam `auto_applied_count` devem cruzar com as settings de auto-apply.

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "date_range": {
            "type": "string",
            "enum": _DATE_PRESETS,
            "default": "LAST_7_DAYS",
            "description": "Periodo via preset. Para periodo custom, use start_date+end_date.",
        },
        "start_date": {
            "type": "string",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
            "description": (
                "Data inicial YYYY-MM-DD inclusive. Quando informado junto com end_date, "
                "sobrepoe date_range preset. Obriga end_date."
            ),
        },
        "end_date": {
            "type": "string",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
            "description": "Data final YYYY-MM-DD inclusive. Obrigatorio se start_date informado.",
        },
        "resource_types": {
            "type": "array",
            "items": {"type": "string", "enum": _RESOURCE_TYPES},
        },
        "operation_types": {
            "type": "array",
            "items": {"type": "string", "enum": ["CREATE", "UPDATE", "REMOVE"]},
        },
        "user_emails": {
            "type": "array",
            "items": {"type": "string", "format": "email"},
        },
        "client_types": {
            "type": "array",
            "items": {"type": "string", "enum": _CLIENT_TYPES},
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 200},
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    ce = row.change_event
    resource_path = str(ce.change_resource_name)
    _rtype, rid = parse_resource_path(resource_path)
    # changed_fields is a FieldMask (paths joined by '.'); split into list
    changed = list(ce.changed_fields.paths) if hasattr(ce.changed_fields, "paths") else []

    # campaign / ad_group references on change_event are resource paths; convert
    campaign_path = str(ce.campaign) if ce.campaign else ""
    ad_group_path = str(ce.ad_group) if ce.ad_group else ""
    _, campaign_id = parse_resource_path(campaign_path) if campaign_path else (None, None)
    _, ad_group_id = parse_resource_path(ad_group_path) if ad_group_path else (None, None)

    op_enum = ce.resource_change_operation
    op_str = op_enum.name if hasattr(op_enum, "name") else str(op_enum)
    rtype_enum = ce.change_resource_type
    rtype_str = rtype_enum.name if hasattr(rtype_enum, "name") else str(rtype_enum)
    ct_enum = ce.client_type
    ct_str = ct_enum.name if hasattr(ct_enum, "name") else str(ct_enum)

    return {
        "change_date_time": str(ce.change_date_time),
        "user_email": str(ce.user_email),
        "client_type": ct_str,
        "resource_type": rtype_str,
        "resource_id": rid or "",
        "resource_name": "",  # filled in by _resolve_names after the fact
        "_resource_path": resource_path,  # internal, removed before returning
        "operation": op_str,
        "changed_fields": changed,
        "campaign_id": campaign_id,
        "ad_group_id": ad_group_id,
    }


def _parse_change_dt(raw: str) -> datetime | None:
    """Converte o `change_date_time` do Google em datetime, tolerando o formato.

    O Google devolve "YYYY-MM-DD HH:MM:SS.ffffff", mas os microssegundos nem
    sempre vem. Formato desconhecido devolve None — e a fronteira vira
    "indeterminado", que e a resposta honesta, em vez de frescor inventado.
    """
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate counts. Auto-apply rows collapse into synthetic 'auto-apply' user bucket."""
    by_user: Counter[str] = Counter()
    by_resource_type: Counter[str] = Counter()
    by_operation: Counter[str] = Counter()
    auto_applied = 0
    for r in rows:
        if r["client_type"] in AUTO_APPLY_CLIENT_TYPES:
            by_user["auto-apply"] += 1
            auto_applied += 1
        else:
            by_user[r["user_email"]] += 1
        by_resource_type[r["resource_type"]] += 1
        by_operation[r["operation"]] += 1

    return {
        "total_changes": len(rows),
        "by_user": dict(by_user),
        "by_resource_type": dict(by_resource_type),
        "by_operation": dict(by_operation),
        "auto_applied_count": auto_applied,
    }


async def _resolve_names(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], str]:
    """Resolve (resource_type, resource_id) -> human name via 0-2 follow-up queries."""
    name_map: dict[tuple[str, str], str] = {}

    campaign_ids = sorted({r["campaign_id"] for r in rows if r["campaign_id"]})
    ad_group_ids = sorted({r["ad_group_id"] for r in rows if r["ad_group_id"]})

    if campaign_ids:
        ids_clause = ",".join(campaign_ids)
        q = f"SELECT campaign.id, campaign.name FROM campaign WHERE campaign.id IN ({ids_clause})"
        rows_c = await run_report(
            manager_id=manager_id,
            session_id=session_id,
            customer_id=customer_id,
            query=q,
            row_formatter=lambda r: {"id": str(r.campaign.id), "name": str(r.campaign.name)},
            operation_name="get_change_history_resolve_campaigns",
            audit_this_call=False,
        )
        for c in rows_c:
            name_map[("campaign", c["id"])] = c["name"]

    if ad_group_ids:
        ids_clause = ",".join(ad_group_ids)
        q = f"SELECT ad_group.id, ad_group.name FROM ad_group WHERE ad_group.id IN ({ids_clause})"
        rows_a = await run_report(
            manager_id=manager_id,
            session_id=session_id,
            customer_id=customer_id,
            query=q,
            row_formatter=lambda r: {"id": str(r.ad_group.id), "name": str(r.ad_group.name)},
            operation_name="get_change_history_resolve_ad_groups",
            audit_this_call=False,
        )
        for a in rows_a:
            name_map[("ad_group", a["id"])] = a["name"]

    return name_map


@register_tool(
    name="get_change_history",
    description=(
        "[CORE] Historico de mudancas (change_event) na conta nos ultimos 7-30 dias com "
        "filtros opcionais (resource_types, operation_types, user_emails, "
        "client_types). Util pra auditoria 'CRITICO antes de tudo': detectar "
        "auto-apply Recommendations, mudancas estruturais, e quem mexeu no que. "
        "ATENCAO: change_event e audit log LAGGING e o lag NAO tem contrato "
        "— medido de ~3h a >4 dias na MESMA conta. Por isso a resposta traz "
        "`freshness` com a fronteira MEDIDA: `account_frontier` (evento mais "
        "recente indexado na conta, sem filtro), `slice_frontier` (das linhas "
        "devolvidas) e `status` (confiavel|ambiguo|atrasado|indeterminado). "
        "Leia o status antes de concluir que nada mudou: lista vazia com "
        "status != confiavel NAO e prova de ausencia. Pra validar estado "
        "atual (revert/incident), use `run_gaql FROM campaign` como "
        "leading indicator. Inclui summary com totais por usuario/resource/"
        "operation. Janela maxima 30 dias (Google retention exclusivo — start_date "
        "alem disso e auto-clampado pra today-28 com warning F23, preset OU custom; "
        "janela inteira fora da retencao da erro claro). Audited."
    ),
    input_schema=_SCHEMA,
    bucket="always",
)
async def get_change_history(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]

    start, end = resolve_date_window(
        date_range=args.get("date_range", "LAST_7_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
    )

    # F23 fix Sprint 3b.38 (estendido): clampamos start_date — preset OU custom — pro
    # teto de retenção do change_event (30 dias exclusivos), em vez de deixar o Google
    # rejeitar com "start date too old". Devolve dados + warning. Se a janela inteira
    # está fora da retenção (end < limite), não há o que retornar → erro claro.
    today = datetime.now(UTC).date()
    earliest_allowed = today - timedelta(days=_RETENTION_SAFETY_DAYS)
    retention_warning: str | None = None
    if end < earliest_allowed:
        raise ValueError(
            f"A janela pedida ({start.isoformat()}..{end.isoformat()}) está inteira fora "
            f"da retenção de 30 dias do change_event do Google (dados só a partir de "
            f"{earliest_allowed.isoformat()}). Peça uma janela dentro dos últimos 30 dias."
        )
    if start < earliest_allowed:
        original_start = start
        start = earliest_allowed
        retention_warning = (
            f"date_range coerced from {original_start.isoformat()} to "
            f"{start.isoformat()} (F23: change_event do Google retém 30 dias exclusivos "
            "— clamp pra today-28 evita rejeição na borda; vale pra preset E custom)."
        )

    limit = args.get("limit", 200)

    query = change_history_query(
        start=start,
        end=end,
        resource_types=args.get("resource_types"),
        operation_types=args.get("operation_types"),
        user_emails=args.get("user_emails"),
        client_types=args.get("client_types"),
        limit=limit,
    )

    # F131: a sonda de fronteira vai EM PARALELO com a query principal — mesmo
    # padrao que o audit_competitor_keywords ja usa. Custa +1 chamada de quota
    # e ~0 de latencia, e e o que separa "nada mudou" de "ainda nao indexou".
    rows, frontier_rows = await asyncio.gather(
        run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=query,
            row_formatter=_row_formatter,
            operation_name="get_change_history",
            audit_this_call=True,
        ),
        run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            # A sonda deriva a propria janela (retencao inteira). Passar `start`/`end`
            # aqui era o bug: a fronteira da CONTA virava fronteira do PEDIDO.
            query=change_event_frontier_query(today=datetime.now(UTC).date()),
            row_formatter=lambda r: {"change_date_time": str(r.change_event.change_date_time)},
            operation_name="get_change_history_frontier",
            # Query de apoio, como o _resolve_names: nao polui a trilha do gestor.
            audit_this_call=False,
        ),
    )

    # Resolve campaign/ad_group names (0-2 extra ops)
    name_map = await _resolve_names(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        rows=rows,
    )
    # name_map only contains ('campaign', id) and ('ad_group', id) keys —
    # for other resource types (ASSET, CUSTOMER_ASSET, FEED, ASSET_SET, etc),
    # the raw resource path is used as resource_name per spec §4.5.
    for r in rows:
        resource_path = r.pop("_resource_path")
        key = (r["resource_type"].lower(), r["resource_id"])
        if key in name_map:
            r["resource_name"] = name_map[key]
        elif r["campaign_id"]:
            r["resource_name"] = name_map.get(("campaign", r["campaign_id"]), resource_path)
        else:
            r["resource_name"] = resource_path

    summary = _build_summary(rows)

    account_frontier = (
        _parse_change_dt(frontier_rows[0]["change_date_time"]) if frontier_rows else None
    )
    slice_dts = [
        dt for dt in (_parse_change_dt(r["change_date_time"]) for r in rows) if dt is not None
    ]

    response: dict[str, Any] = {
        "customer_id": customer_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "rows": rows,
        "summary": summary,
        # F131: sem isto, `total_changes: 0` e a mesma resposta para "nada
        # mudou" e para "mudou e ainda nao indexou".
        "freshness": assess_freshness(
            account_frontier=account_frontier,
            slice_frontier=max(slice_dts) if slice_dts else None,
            window_end=end,
        ),
    }
    if retention_warning is not None:
        response["date_range_warning"] = retention_warning
    return response
