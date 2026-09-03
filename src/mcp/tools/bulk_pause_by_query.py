# bucket: always
"""Tool: bulk_pause_by_query - pause N entities matching a GAQL filter (dry-run).

Workflow:
  1. gestor passes target_type + filter + optional date_range
  2. tool validates filter (no ;, no SELECT/FROM, <=1000 chars)
  3. tool builds GAQL with LIMIT 101 (overflow detection)
  4. run_report executes; tool branches on row count:
     - 0          → status:'no_op'
     - 1..100     → status:'dry_run' with confirmation_token + preview
     - 101+       → status:'error' asking to refine filter
  5. gestor calls apply_change(token) → mutate via build_bulk_pause

Always 'sempre confirm' (spec §7.1) — even count==1 goes through dry-run.
Cap: 100 entities (MVP, hard-reject; re-tune from telemetry after 4 weeks).
"""

import hashlib
from typing import Any

from src.db import connection
from src.google_ads.account_clock import resolve_account_today
from src.google_ads.queries._common import (
    InvalidDateRangeError,
    micros_to_currency,
    resolve_date_window,
)
from src.google_ads.queries.bulk_pause import (
    FilterValidationError,
    bulk_pause_query,
    validate_filter,
)
from src.google_ads.reports import run_report
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import error_envelope, preview_envelope
from src.mcp.tools._registry import register_tool

_MAX_ENTITIES = 100
_SAMPLE_SIZE = 10

_TARGET_TYPES = ["keyword", "ad", "campaign", "ad_group"]

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

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "target_type": {"type": "string", "enum": _TARGET_TYPES},
        "filter": {"type": "string", "minLength": 1, "maxLength": 1000},
        "date_range": {
            "type": "string",
            "enum": _DATE_PRESETS,
            "default": "LAST_30_DAYS",
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
    },
    "required": ["customer_id", "target_type", "filter"],
    "additionalProperties": False,
}


def _hash_filter(filter_clause: str) -> str:
    """SHA-256 of the filter — for audit telemetry without leaking the raw filter."""
    h = hashlib.sha256(filter_clause.encode("utf-8")).hexdigest()
    return f"sha256:{h}"


def _row_formatter_keyword(row: Any) -> dict[str, Any]:
    return {
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": str(row.ad_group.name),
        "criterion_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": str(row.ad_group_criterion.keyword.text),
        "campaign_id": str(row.campaign.id),
        "campaign_name": str(row.campaign.name),
        "cost_brl": micros_to_currency(row.metrics.cost_micros),
    }


def _row_formatter_ad(row: Any) -> dict[str, Any]:
    return {
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": str(row.ad_group.name),
        "ad_id": str(row.ad_group_ad.ad.id),
        "campaign_id": str(row.campaign.id),
        "campaign_name": str(row.campaign.name),
        "cost_brl": micros_to_currency(row.metrics.cost_micros),
    }


def _row_formatter_campaign(row: Any) -> dict[str, Any]:
    return {
        "campaign_id": str(row.campaign.id),
        "campaign_name": str(row.campaign.name),
        "cost_brl": micros_to_currency(row.metrics.cost_micros),
    }


def _row_formatter_ad_group(row: Any) -> dict[str, Any]:
    return {
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": str(row.ad_group.name),
        "campaign_id": str(row.campaign.id),
        "campaign_name": str(row.campaign.name),
        "cost_brl": micros_to_currency(row.metrics.cost_micros),
    }


_FORMATTERS = {
    "keyword": _row_formatter_keyword,
    "ad": _row_formatter_ad,
    "campaign": _row_formatter_campaign,
    "ad_group": _row_formatter_ad_group,
}


def _build_sample_entry(target_type: str, row: dict[str, Any]) -> dict[str, Any]:
    """Compact sample entry for the preview block."""
    if target_type == "keyword":
        return {
            "id": row["criterion_id"],
            "label": row["keyword_text"],
            "context": f"{row['campaign_name']} > {row['ad_group_name']}",
            "cost_brl": row["cost_brl"],
        }
    if target_type == "ad":
        return {
            "id": row["ad_id"],
            "label": f"ad {row['ad_id']}",
            "context": f"{row['campaign_name']} > {row['ad_group_name']}",
            "cost_brl": row["cost_brl"],
        }
    if target_type == "campaign":
        return {
            "id": row["campaign_id"],
            "label": row["campaign_name"],
            "context": "",
            "cost_brl": row["cost_brl"],
        }
    # ad_group
    return {
        "id": row["ad_group_id"],
        "label": row["ad_group_name"],
        "context": row["campaign_name"],
        "cost_brl": row["cost_brl"],
    }


def _build_entities(target_type: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact entity payload for the captured dry-run (apply_change reads this)."""
    if target_type == "keyword":
        return [{"ad_group_id": r["ad_group_id"], "criterion_id": r["criterion_id"]} for r in rows]
    if target_type == "ad":
        return [{"ad_group_id": r["ad_group_id"], "ad_id": r["ad_id"]} for r in rows]
    if target_type == "campaign":
        return [{"campaign_id": r["campaign_id"]} for r in rows]
    # ad_group
    return [{"ad_group_id": r["ad_group_id"]} for r in rows]


@register_tool(
    name="bulk_pause_by_query",
    description=(
        "[CORE] Pausa em batch entidades (keyword|ad|campaign|ad_group) matched por um GAQL "
        "filter. Sempre dry-run obrigatório (spec §7.1): retorna preview com até 10 "
        "amostras + custo total + confirmation_token (TTL 10min). Apply via "
        "apply_change(token). Limite hard: 100 entidades por chamada (se exceder, "
        "rejeita pedindo refinar). filter eh apenas o corpo da WHERE clause (sem "
        "SELECT/FROM/LIMIT). date_range default LAST_30_DAYS auto-injeta segments.date "
        "BETWEEN quando filter usa metrics.*. RECOMENDACAO: pra evitar incluir "
        "entidades ja pausadas, adicione `AND <target>.status = 'ENABLED'` no filter "
        "(ex: `ad_group_criterion.status = 'ENABLED'` pra keywords). "
        "Nota: <entity>.status pode lagar alguns minutos entre queries Google Ads — "
        "preview pode mostrar entidades ja pausadas/REMOVED. Re-query antes de apply."
    ),
    input_schema=_SCHEMA,
    bucket="always",
)
async def bulk_pause_by_query(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    target_type = args["target_type"]
    filter_clause = args["filter"]
    date_range_arg = args.get("date_range", "LAST_30_DAYS")
    start_date_arg = args.get("start_date")
    end_date_arg = args.get("end_date")

    # Pre-flight filter validation (raises FilterValidationError → friendly PT-BR)
    try:
        validate_filter(filter_clause)
    except FilterValidationError as e:
        return error_envelope("bulk_pause_by_query", str(e))

    try:
        today = await resolve_account_today(customer_id)
        start, end = resolve_date_window(
            date_range=date_range_arg,
            start_date=start_date_arg,
            end_date=end_date_arg,
            today=today,
        )
    except InvalidDateRangeError as e:
        return error_envelope("bulk_pause_by_query", f"periodo invalido: {e}")
    query = bulk_pause_query(
        target_type=target_type,
        filter_clause=filter_clause,
        start=start,
        end=end,
    )

    filter_hash = _hash_filter(filter_clause)
    formatter = _FORMATTERS[target_type]

    # params_summary is captured at call-time; we don't yet know matched_count.
    # Just metadata (target_type + filter_hash). Counts live in the apply audit
    # row (run_mutation default puts payload.keys, which includes
    # __target_count__ and filter_hash).
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=formatter,
        operation_name="bulk_pause_by_query_dry_run",
        audit_this_call=True,
        params_summary={
            "target_type": target_type,
            "filter_hash": filter_hash,
        },
    )

    count = len(rows)

    # Branch: zero matches
    if count == 0:
        return {
            "status": "no_op",
            "operation": "bulk_pause_by_query",
            "customer_id": customer_id,
            "matched_count": 0,
            "message": "Nenhuma entidade matched o filtro. Nada a pausar.",
        }

    # Branch: overflow (LIMIT 101 hit)
    if count > _MAX_ENTITIES:
        return error_envelope(
            "bulk_pause_by_query",
            (
                f"Sua query matched {_MAX_ENTITIES}+ entidades — acima do limite de "
                f"{_MAX_ENTITIES} por chamada (decisão MVP). Refine o filtro pra "
                f"reduzir alcance, ou divida em multiplas chamadas. Ex: adicionar "
                f"AND segments.date DURING LAST_7_DAYS, filtrar campaign.id "
                f"especifico, ou metricas mais restritivas."
            ),
            customer_id=customer_id,
            matched_count=f"{_MAX_ENTITIES}+",
        )

    # Branch: valid count (1..100) — capture + create token
    total_cost = sum(r.get("cost_brl", 0.0) for r in rows)
    sample = [_build_sample_entry(target_type, r) for r in rows[:_SAMPLE_SIZE]]
    entities = _build_entities(target_type, rows)

    payload = {
        "target_type": target_type,
        "entities": entities,
        "total_cost_brl": round(total_cost, 2),
        "filter_hash": filter_hash,
        "__target_count__": count,
        "__partial_failure__": True,
    }
    summary = (
        f"Pausar {count} {target_type}(s). Custo total R$ {total_cost:.2f} no periodo. "
        f"Amostra: " + ", ".join(f"'{s['label']}' ({s['context']})" for s in sample[:3])
    )

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="bulk_pause_by_query",
            payload=payload,
            blast_summary=summary,
        )

    return preview_envelope(
        "bulk_pause_by_query",
        customer_id,
        summary,
        token,
        preview={
            "target_type": target_type,
            "matched_count": count,
            "total_cost_brl": round(total_cost, 2),
            "sample": sample,
        },
    )
