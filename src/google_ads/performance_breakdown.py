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

_ENTITY_LEVELS = ("campaign", "ad_group", "ad", "keyword", "audience")
_BREAKDOWNS = ("device", "geo", "hourly")


def _validate_combo(level: str, breakdown: str | None) -> str | None:
    """Retorna mensagem PT-BR se o combo (level, breakdown) for inválido, senão None.

    Matriz válida (8 = os 8 reports atuais): entity+sem-breakdown; account+breakdown.
    """
    if level == "account":
        if breakdown is None:
            return (
                "level='account' exige um breakdown (device/geo/hourly). "
                "Pra visão geral da conta com comparativo de período use get_account_overview."
            )
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
