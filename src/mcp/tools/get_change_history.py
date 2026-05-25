"""Tool: get_change_history - audit-log of recent changes to the account.

Wraps the change_event GAQL resource with structured filters and a summary
block. Two V4 skills (auditoria-google-ads + analise-performance-google-ads)
call this as 'CRITICO antes de tudo' to detect:
- Auto-apply Recommendations (client_type=GOOGLE_ADS_RECOMMENDATIONS)
- Structural changes (geo settings, conversion actions, bidding strategy)
- Who changed what

Audited as a sensitive read.

Caveats (empirically verified against production change_event 2026-05-11,
re-confirmado em dogfood 2026-05-21 MO-JP, e refinado em dogfood 2026-05-25
MO-JP+CAB pós-reverts Pedro 21/05):
- Propagation lag: change_event é AUDIT LOG LAGGING, NOT real-time. Mutações
  via API ou UI tipicamente levam MINUTOS A **DIAS** (>4 dias já visto em
  produção — dogfood 25/05 reconfirmou 3 dos 4 reverts Pedro de 21/05 ainda
  não surfaceavam 4 dias depois) para surface em change_event. O lag afeta
  MÚLTIPLOS campos, não apenas `campaign.status` — também
  `ai_max_setting.enable_ai_max`, `asset_automation_settings`,
  `text_guidelines.messaging_restrictions`, etc.
- Padrão V4 pra validar estado ATUAL pós-mutação (revert/incident recovery):
  use `run_gaql FROM campaign` como LEADING indicator (real-time) e
  `get_change_history` como LAGGING (audit log). Se divergirem, confie no
  leading. Se um campo opcional não retornar no GAQL, está vazio/removido.
- 30-day window é a retenção documentada; alguns date_range presets podem
  bater limite ligeiramente menor. Nosso path usa explicit BETWEEN dates.
- Google não distingue 'user applied via Recommendations UI' de 'Google
  auto-apply' em change_event.client_type — ambos surface como
  GOOGLE_ADS_RECOMMENDATIONS. summary.auto_applied_count conta a união;
  cross-reference auto-apply settings se intent matters.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from src.google_ads.queries._common import parse_resource_path, resolve_date_window
from src.google_ads.queries.change_history import change_history_query
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

_RESOURCE_TYPES = [
    "CAMPAIGN",
    "AD_GROUP",
    "AD_GROUP_CRITERION",
    "AD_GROUP_AD",
    "CAMPAIGN_CRITERION",
    "CAMPAIGN_BUDGET",
    "BIDDING_STRATEGY",
    "CONVERSION_ACTION",
    "CUSTOMER_NEGATIVE_CRITERION",
    "ASSET",
    "CAMPAIGN_ASSET",
    "AD_GROUP_ASSET",
]

# ChangeClientType enum values from Google Ads API (verified empirically
# against production change_event 2026-05-11 — names DIFFER from common
# guesses like GOOGLE_ADS_UI / GOOGLE_ADS_RECOMMENDATIONS_AUTO_APPLY).
_CLIENT_TYPES = [
    "UNSPECIFIED",
    "UNKNOWN",
    "GOOGLE_ADS_WEB_CLIENT",  # Web UI (Google Ads website)
    "GOOGLE_ADS_AUTOMATED_RULES",
    "GOOGLE_ADS_SCRIPTS",
    "GOOGLE_ADS_BULK_UPLOAD",
    "GOOGLE_ADS_API",
    "GOOGLE_ADS_EDITOR",
    "GOOGLE_ADS_MOBILE_APP",
    "GOOGLE_ADS_RECOMMENDATIONS",  # Includes auto-apply Recommendations
    "SEARCH_ADS_360_SYNC",
    "SEARCH_ADS_360_POST",
    "INTERNAL_TOOL",
    "OTHER",
]

# Auto-apply Recommendations changes surface as GOOGLE_ADS_RECOMMENDATIONS
# (Google does not distinguish "applied by user via Recommendations UI"
# from "applied by Google auto-apply" in change_event.client_type). V4
# skills using auto_applied_count should cross-reference with the auto-apply
# Recommendations settings to confirm.
_AUTO_APPLY_CLIENT_TYPE = "GOOGLE_ADS_RECOMMENDATIONS"

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


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate counts. Auto-apply rows collapse into synthetic 'auto-apply' user bucket."""
    by_user: Counter[str] = Counter()
    by_resource_type: Counter[str] = Counter()
    by_operation: Counter[str] = Counter()
    auto_applied = 0
    for r in rows:
        if r["client_type"] == _AUTO_APPLY_CLIENT_TYPE:
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
        "Historico de mudancas (change_event) na conta nos ultimos 7-30 dias com "
        "filtros opcionais (resource_types, operation_types, user_emails, "
        "client_types). Util pra auditoria 'CRITICO antes de tudo': detectar "
        "auto-apply Recommendations, mudancas estruturais, e quem mexeu no que. "
        "ATENCAO: latency de indexacao pode chegar a DIAS (>4 dias ja visto em "
        "producao — dogfood 25/05 MO-JP) e afeta multiplos campos. Pra validar "
        "estado atual (revert/incident), use `run_gaql FROM campaign` como "
        "leading indicator. Inclui summary com totais por usuario/resource/"
        "operation. Janela maxima 30 dias (Google retention exclusivo — preset "
        "LAST_30_DAYS auto-clamped pra today-28 com warning F23). Audited."
    ),
    input_schema=_SCHEMA,
)
async def get_change_history(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]

    # F23 fix Sprint 3b.38: clamp APENAS quando o usuário passou preset string
    # (LAST_30_DAYS, etc). Custom dates — seja via start_date/end_date separados
    # OU via date_range dict {from, to} legacy — honra intent do usuário
    # (Google rejeita explicitamente se demais antigo, OU change_history_query
    # raise RangeTooWideError se > 30 dias).
    raw_date_range = args.get("date_range", "LAST_7_DAYS")
    has_custom_dates = (
        args.get("start_date") is not None and args.get("end_date") is not None
    ) or isinstance(raw_date_range, dict)

    start, end = resolve_date_window(
        date_range=raw_date_range,
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
    )

    today = datetime.now(UTC).date()
    earliest_allowed = today - timedelta(days=_RETENTION_SAFETY_DAYS)
    retention_warning: str | None = None
    if not has_custom_dates and start < earliest_allowed:
        original_start = start
        start = earliest_allowed
        retention_warning = (
            f"date_range coerced from {original_start.isoformat()} to "
            f"{start.isoformat()} (F23: Google change_event retention é 30 dias "
            "exclusivos — clamp pra today-28 evita rejeição na borda). Use "
            "start_date+end_date custom pra window precisa dentro do limite."
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

    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_row_formatter,
        operation_name="get_change_history",
        audit_this_call=True,
    )

    # Resolve campaign/ad_group names (0-2 extra ops)
    name_map = await _resolve_names(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        rows=rows,
    )
    # name_map only contains ('campaign', id) and ('ad_group', id) keys —
    # for other resource types (BIDDING_STRATEGY, CONVERSION_ACTION, ASSET, etc),
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

    response: dict[str, Any] = {
        "customer_id": customer_id,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "rows": rows,
        "summary": summary,
    }
    if retention_warning is not None:
        response["date_range_warning"] = retention_warning
    return response
