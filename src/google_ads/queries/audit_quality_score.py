"""GAQL builder + row parser for audit_quality_score tool (Sprint 3b.30)."""

from typing import Any

from src.google_ads.flag_keywords import KeywordRow


def build_audit_quality_score_query(
    *,
    start_date: str,
    end_date: str,
    ad_group_ids: list[str] | None = None,
) -> str:
    """Build GAQL query for keyword_view filtered by status/date/qs/optional ad_groups.

    Hardcoded filters (per spec section 2):
    - ad_group_criterion.status = 'ENABLED' (only current-actionable)
    - ad_group_criterion.quality_info.quality_score IS NOT NULL (exclude unset/new kw)

    Args:
        start_date, end_date: YYYY-MM-DD (resolved via resolve_date_window upstream).
        ad_group_ids: optional filter — None means scan account-wide.

    Returns:
        GAQL string ready for run_report.
    """
    query = (
        "SELECT "
        "ad_group.id, ad_group.name, campaign.name, "
        "ad_group_criterion.criterion_id, "
        "ad_group_criterion.keyword.text, "
        "ad_group_criterion.keyword.match_type, "
        "ad_group_criterion.quality_info.quality_score, "
        "metrics.impressions, metrics.clicks, "
        "metrics.conversions, metrics.cost_micros "
        "FROM keyword_view "
        "WHERE ad_group_criterion.status = 'ENABLED' "
        f"AND segments.date BETWEEN '{start_date}' AND '{end_date}' "
        "AND ad_group_criterion.quality_info.quality_score IS NOT NULL"
    )
    if ad_group_ids:
        ids_clause = ", ".join(f"'{id_}'" for id_ in ad_group_ids)
        query += f" AND ad_group.id IN ({ids_clause})"
    return query


def parse_keyword_view_row(row: Any) -> dict[str, Any]:
    """Parse GoogleAds SDK row into dict matching KeywordRow fields.

    Returns dict (run_report's row_formatter contract). Tool wrapper
    converts to KeywordRow dataclass before passing to flag_keywords.
    """
    # match_type enum em v24: 2=EXACT, 3=PHRASE, 4=BROAD
    # SDK exposes .name attribute on proto enum
    match_type_str = row.ad_group_criterion.keyword.match_type.name

    return {
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
        "campaign_name": row.campaign.name,
        "keyword_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": row.ad_group_criterion.keyword.text,
        "match_type": match_type_str,
        "quality_score": row.ad_group_criterion.quality_info.quality_score,
        "impressions": row.metrics.impressions,
        "clicks": row.metrics.clicks,
        "conversions": row.metrics.conversions,
        "cost_brl": row.metrics.cost_micros / 1_000_000.0,
    }


def dict_to_keyword_row(d: dict[str, Any]) -> KeywordRow:
    """Convert parsed dict back to KeywordRow dataclass at tool wrapper boundary."""
    return KeywordRow(
        ad_group_id=d["ad_group_id"],
        ad_group_name=d["ad_group_name"],
        campaign_name=d["campaign_name"],
        keyword_id=d["keyword_id"],
        keyword_text=d["keyword_text"],
        match_type=d["match_type"],
        quality_score=d["quality_score"],
        impressions=d["impressions"],
        clicks=d["clicks"],
        conversions=d["conversions"],
        cost_brl=d["cost_brl"],
    )
