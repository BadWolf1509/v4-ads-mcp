"""GAQL builder for audit_zombie_keywords tool (Sprint 3b.36).

Single query sobre keyword_view com:
- Date range filter (gaql_date_clause helper)
- status=ENABLED + negative=FALSE hardcoded server-side
- Optional ad_group_ids filter
- 11 fields SELECT (keyword + ad_group + campaign + metrics)
"""

from datetime import date
from typing import Any

from src.google_ads.flag_zombie_keywords import KeywordRow
from src.google_ads.queries._common import gaql_date_clause, micros_to_currency


def build_audit_zombie_keywords_query(
    *,
    start_date: str,
    end_date: str,
    ad_group_ids: list[str] | None,
) -> str:
    """GAQL pra keyword_view com fields necessários (audit_zombie_keywords).

    Filters: date range via gaql_date_clause + status=ENABLED +
    negative=FALSE + optional ad_group_ids IN clause.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    date_clause = gaql_date_clause(start, end)

    ad_group_clause = ""
    if ad_group_ids:
        ids = ",".join(ad_group_ids)
        ad_group_clause = f" AND ad_group.id IN ({ids})"

    return f"""
        SELECT
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group_criterion.status,
          ad_group.id,
          ad_group.name,
          ad_group.status,
          campaign.name,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions
        FROM keyword_view
        WHERE {date_clause}
          AND ad_group_criterion.status = 'ENABLED'
          AND ad_group_criterion.negative = FALSE{ad_group_clause}
    """.strip()


def parse_keyword_view_row(row: Any) -> dict[str, Any]:
    """Parse keyword_view GAQL row → dict (boundary).

    Uses `.name` on match_type/status enums (Sprint 3b.7 lesson: proto-plus
    v20+ repr regression — `str(enum)` retorna integer, `.name` retorna 'BROAD').

    F52: include ad_group.status pra revelar órfãs cosméticas (keywords
    ENABLED em ad_group REMOVED — no-op pra batch update real).
    """
    return {
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
        "ad_group_status": row.ad_group.status.name,
        "campaign_name": row.campaign.name,
        "keyword_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": row.ad_group_criterion.keyword.text,
        "match_type": row.ad_group_criterion.keyword.match_type.name,
        "impressions": int(row.metrics.impressions),
        "clicks": int(row.metrics.clicks),
        "cost_brl": micros_to_currency(row.metrics.cost_micros),
        "conversions": int(row.metrics.conversions),
        "status": row.ad_group_criterion.status.name,
    }


def dict_to_keyword_row(d: dict[str, Any]) -> KeywordRow:
    """Convert keyword_view row dict to KeywordRow dataclass (defensive)."""
    return KeywordRow(
        ad_group_id=str(d.get("ad_group_id", "")),
        ad_group_name=str(d.get("ad_group_name", "")),
        ad_group_status=str(d.get("ad_group_status", "")),
        campaign_name=str(d.get("campaign_name", "")),
        keyword_id=str(d.get("keyword_id", "")),
        keyword_text=str(d.get("keyword_text", "")),
        match_type=str(d.get("match_type", "")),
        impressions=int(d.get("impressions", 0)),
        clicks=int(d.get("clicks", 0)),
        cost_brl=float(d.get("cost_brl", 0.0)),
        conversions=int(d.get("conversions", 0)),
        status=str(d.get("status", "")),
    )
