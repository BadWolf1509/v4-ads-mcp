"""Tool: get_negative_keywords_audit - campaign-level negative keywords."""

from typing import Any

from src.google_ads.queries.tactical import negative_keywords_audit_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter(row: Any) -> dict[str, Any]:
    return {
        "criterion_id": str(row.campaign_criterion.criterion_id),
        "keyword_text": row.campaign_criterion.keyword.text,
        "match_type": row.campaign_criterion.keyword.match_type.name,
        "campaign_id": str(row.campaign.id),
        "campaign_name": row.campaign.name,
    }


@register_tool(
    name="get_negative_keywords_audit",
    description=(
        "Lista palavras-chave negativas aplicadas em nivel de campanha. Util pra "
        "auditoria de cobertura de negativas e identificar duplicacoes ou gaps."
    ),
    input_schema=_SCHEMA,
)
async def get_negative_keywords_audit(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=negative_keywords_audit_query(),
        row_formatter=_row_formatter,
        operation_name="get_negative_keywords_audit",
    )

    # Group by campaign for easier consumption
    by_campaign: dict[str, dict[str, Any]] = {}
    for r in rows:
        cid = r["campaign_id"]
        if cid not in by_campaign:
            by_campaign[cid] = {
                "campaign_id": cid,
                "campaign_name": r["campaign_name"],
                "negatives": [],
            }
        by_campaign[cid]["negatives"].append(
            {
                "criterion_id": r["criterion_id"],
                "keyword_text": r["keyword_text"],
                "match_type": r["match_type"],
            }
        )

    return {
        "customer_id": customer_id,
        "total_negatives": len(rows),
        "by_campaign": list(by_campaign.values()),
    }
