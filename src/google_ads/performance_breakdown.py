"""Pure module for get_performance_breakdown (Fase 2A).

Consolida os 8 reports Google numa tool (level + breakdown opcional).
Zero google-ads imports — opera via duck-typing nos protos (testável com
SimpleNamespace). Espelha src/meta_ads/insights.py (M.4).
"""

from datetime import date
from typing import Any

from src.google_ads.queries._common import micros_to_currency
from src.google_ads.queries.performance import (
    ad_group_performance_query,
    campaign_performance_query,
    device_performance_query,
    geo_performance_query,
    hourly_performance_query,
)
from src.google_ads.queries.tactical import (
    ad_performance_query,
    audience_performance_query,
    keyword_performance_query,
)


def _validate_combo(level: str, breakdown: str | None) -> str | None:
    """Retorna mensagem PT-BR se o combo (level, breakdown) for inválido, senão None.

    Matriz válida (8 = os 8 reports atuais): entity+sem-breakdown; account+breakdown.
    Exceção: campaign+hourly (Task 4).
    """
    if level == "account":
        if breakdown is None:
            return (
                "level='account' exige um breakdown (device/geo/hourly). "
                "Pra visão geral da conta com comparativo de período use get_account_overview."
            )
        return None
    # campaign + hourly e o unico combo entity+breakdown aberto: o agregado de
    # conta esconde o que decide (medido na MO-JP: 18,47 numa campanha contra
    # 24,46 na outra, mesma faixa). `geo` segue fora — la o problema e regra de
    # merge (geoTargetConstant duplicado), nao nivel.
    if level == "campaign" and breakdown == "hourly":
        return None
    # entity level
    if breakdown is not None:
        return (
            f"breakdown só é suportado em level='account' no v0 (você pediu level='{level}'). "
            "Use level='account' + breakdown, ou remova o breakdown."
        )
    return None


def _common_metrics(m: Any) -> dict[str, Any]:
    impr = int(m.impressions)
    clicks = int(m.clicks)
    cost_micros = int(m.cost_micros)
    return {
        "impressions": impr,
        "clicks": clicks,
        "cost_brl": micros_to_currency(cost_micros),
        "conversions": round(float(m.conversions), 2),
        "conversions_value_brl": round(float(m.conversions_value), 2),
        "ctr": round(clicks / impr, 4) if impr else 0.0,
        "cpc_brl": micros_to_currency(cost_micros / clicks) if clicks else 0.0,
    }


def build_performance_breakdown_query(
    level: str, breakdown: str | None, status: str, start: date, end: date, limit: int
) -> str:
    if level == "account":
        if breakdown == "device":
            return device_performance_query(start, end)
        if breakdown == "geo":
            return geo_performance_query(start, end, limit)
        if breakdown == "hourly":
            return hourly_performance_query(start, end)
        raise ValueError(f"breakdown invalido pra account: {breakdown!r}")
    if level == "campaign" and breakdown == "hourly":
        raise ValueError(
            "campaign+hourly nao passa por este builder: a tool monta a conjunta "
            "com day_hour_metrics_query, que exige campaign_ids explicitos."
        )
    if level == "campaign":
        return campaign_performance_query(start, end, status, limit)
    if level == "ad_group":
        return ad_group_performance_query(start, end, status, limit)
    if level == "ad":
        return ad_performance_query(start, end, status, limit)
    if level == "keyword":
        return keyword_performance_query(start, end, status, limit)
    if level == "audience":
        return audience_performance_query(start, end, limit)
    raise ValueError(f"level invalido: {level!r}")


def parse_performance_row(row: Any, level: str, breakdown: str | None) -> dict[str, Any]:
    """Transforma uma linha GAQL (proto) em dict com unit conversions.

    Cobre os 5 entity levels (campaign/ad_group/ad/keyword/audience).
    Task 4 cobre account+breakdown.
    """
    base = _common_metrics(row.metrics)

    if level == "account":
        if breakdown == "device":
            return {"breakdown": {"device": row.segments.device.name}, **base}
        if breakdown == "geo":
            return {
                "breakdown": {
                    "country_criterion_id": str(row.geographic_view.country_criterion_id)
                },
                **base,
            }
        if breakdown == "hourly":
            return {
                "breakdown": {
                    "hour": int(row.segments.hour),
                    "day_of_week": row.segments.day_of_week.name,
                },
                **base,
            }
        raise ValueError(f"breakdown invalido pra account: {breakdown!r}")

    if level == "campaign":
        return {
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "status": row.campaign.status.name,
            "type": row.campaign.advertising_channel_type.name,
            **base,
        }
    if level == "ad_group":
        return {
            "ad_group_id": str(row.ad_group.id),
            "ad_group_name": row.ad_group.name,
            "status": row.ad_group.status.name,
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            **base,
        }
    if level == "ad":
        ad = row.ad_group_ad.ad
        rsa = ad.responsive_search_ad
        headlines = [h.text for h in rsa.headlines] if rsa else []
        descriptions = [d.text for d in rsa.descriptions] if rsa else []
        final_urls = list(ad.final_urls) if ad.final_urls else []
        return {
            "ad_id": str(ad.id),
            "status": row.ad_group_ad.status.name,
            "type": ad.type.name,
            "ad_strength": row.ad_group_ad.ad_strength.name,
            "headlines": headlines,
            "descriptions": descriptions,
            "final_urls": final_urls,
            "ad_group_id": str(row.ad_group.id),
            "ad_group_name": row.ad_group.name,
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            **base,
        }
    if level == "keyword":
        qi = row.ad_group_criterion.quality_info
        pe = row.ad_group_criterion.position_estimates
        return {
            "criterion_id": str(row.ad_group_criterion.criterion_id),
            "keyword_text": row.ad_group_criterion.keyword.text,
            "match_type": row.ad_group_criterion.keyword.match_type.name,
            "status": row.ad_group_criterion.status.name,
            "negative": bool(row.ad_group_criterion.negative),
            "quality_score": int(qi.quality_score) if qi.quality_score else None,
            "quality_creative": qi.creative_quality_score.name
            if qi.creative_quality_score
            else None,
            "quality_post_click": qi.post_click_quality_score.name
            if qi.post_click_quality_score
            else None,
            "quality_search_predicted_ctr": qi.search_predicted_ctr.name
            if qi.search_predicted_ctr
            else None,
            "first_page_cpc_brl": micros_to_currency(pe.first_page_cpc_micros)
            if pe.first_page_cpc_micros
            else None,
            "top_of_page_cpc_brl": micros_to_currency(pe.top_of_page_cpc_micros)
            if pe.top_of_page_cpc_micros
            else None,
            "ad_group_id": str(row.ad_group.id),
            "ad_group_name": row.ad_group.name,
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            **base,
        }
    if level == "audience":
        cr = row.ad_group_criterion
        user_list = cr.user_list.user_list if cr.user_list and cr.user_list.user_list else None
        user_interest = (
            str(cr.user_interest.user_interest_category)
            if cr.user_interest and cr.user_interest.user_interest_category
            else None
        )
        return {
            "resource_name": row.ad_group_audience_view.resource_name,
            "criterion_id": str(cr.criterion_id),
            "user_list": user_list,
            "user_interest_category": user_interest,
            "ad_group_id": str(row.ad_group.id),
            "ad_group_name": row.ad_group.name,
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            **base,
        }
    raise ValueError(f"level invalido em parse: {level!r}")
