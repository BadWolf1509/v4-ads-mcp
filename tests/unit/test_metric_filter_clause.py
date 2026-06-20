"""Helper GAQL pros filtros server-side da Onda 3 (dogfood)."""

from src.google_ads.queries._common import build_metric_filter_clause


def test_no_filters_returns_empty() -> None:
    assert build_metric_filter_clause() == ""


def test_cost_filter_uses_gte_and_micros() -> None:
    assert build_metric_filter_clause(min_cost_brl=3.0) == "AND metrics.cost_micros >= 3000000"


def test_clicks_filter_uses_gte_int() -> None:
    assert build_metric_filter_clause(min_clicks=5) == "AND metrics.clicks >= 5"


def test_conversions_filter_uses_strict_gt_float() -> None:
    # GAQL rejeita >= em metrics.conversions (double) — usa > ; 0 → "tem alguma conversão"
    assert build_metric_filter_clause(min_conversions=0) == "AND metrics.conversions > 0.0"


def test_all_three_combined_in_order() -> None:
    assert build_metric_filter_clause(min_cost_brl=3.0, min_clicks=5, min_conversions=1) == (
        "AND metrics.cost_micros >= 3000000 AND metrics.clicks >= 5 AND metrics.conversions > 1.0"
    )
