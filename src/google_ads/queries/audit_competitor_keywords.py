"""GAQL builders + row parsers for audit_competitor_keywords (Sprint 3b.31)."""

from typing import Any

from src.google_ads.competitor_analysis import KeywordRow, SearchTermRow
from src.google_ads.queries._common import micros_to_currency


def build_positive_keywords_query() -> str:
    """GAQL pra keyword_view: positive ENABLED keywords (state-based, sem date filter).

    Hardcoded filters per spec section 2:
    - ad_group_criterion.status = 'ENABLED' (current actionable only)
    - ad_group_criterion.negative = FALSE (apenas positive criteria — negative
      criteria não pagam, então não interessam pra audit de waste).
    """
    return (
        "SELECT "
        # F90 (classe F52): ad_group.status revela a keyword ENABLED dentro de
        # ad_group REMOVED — ela nao compete em leilao, entao entrava no
        # "gasto em concorrencia" como item inerte, inflando a narrativa.
        "ad_group.id, ad_group.name, ad_group.status, campaign.name, "
        "ad_group_criterion.criterion_id, "
        "ad_group_criterion.keyword.text, "
        "ad_group_criterion.keyword.match_type "
        "FROM keyword_view "
        "WHERE ad_group_criterion.status = 'ENABLED' "
        "AND ad_group_criterion.negative = FALSE"
    )


def build_search_terms_query(*, start_date: str, end_date: str) -> str:
    """GAQL pra search_term_view: search terms entregues no date window.

    Args:
        start_date, end_date: YYYY-MM-DD (resolved via resolve_date_window upstream).
    """
    return (
        "SELECT "
        "search_term_view.search_term, "
        "ad_group.name, campaign.name, "
        "metrics.impressions, metrics.clicks, metrics.cost_micros "
        "FROM search_term_view "
        f"WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'"
    )


def parse_positive_keyword_row(row: Any) -> dict[str, Any]:
    """Parse SDK row → dict matching KeywordRow fields (run_report contract)."""
    match_type_str = row.ad_group_criterion.keyword.match_type.name
    return {
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
        "campaign_name": row.campaign.name,
        "keyword_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": row.ad_group_criterion.keyword.text,
        "match_type": match_type_str,
        # `.name` do enum, nao str(enum) — proto-plus repr (licao UX-2).
        "ad_group_status": row.ad_group.status.name,
    }


def parse_search_term_row(row: Any) -> dict[str, Any]:
    """Parse SDK row → dict matching SearchTermRow fields."""
    return {
        "search_term": row.search_term_view.search_term,
        "ad_group_name": row.ad_group.name,
        "campaign_name": row.campaign.name,
        "impressions": row.metrics.impressions,
        "clicks": row.metrics.clicks,
        "cost_brl": micros_to_currency(row.metrics.cost_micros),
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
        ad_group_status=d["ad_group_status"],
    )


def dict_to_search_term_row(d: dict[str, Any]) -> SearchTermRow:
    """Convert parsed dict back to SearchTermRow dataclass at tool wrapper boundary."""
    return SearchTermRow(
        search_term=d["search_term"],
        ad_group_name=d["ad_group_name"],
        campaign_name=d["campaign_name"],
        impressions=d["impressions"],
        clicks=d["clicks"],
        cost_brl=d["cost_brl"],
    )
