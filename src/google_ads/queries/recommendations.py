"""GAQL query for the recommendations tool."""


def recommendations_query() -> str:
    """All pending recommendations for the account."""
    return """
        SELECT
          recommendation.resource_name,
          recommendation.type,
          recommendation.impact.base_metrics.impressions,
          recommendation.impact.base_metrics.clicks,
          recommendation.impact.base_metrics.cost_micros,
          recommendation.impact.potential_metrics.impressions,
          recommendation.impact.potential_metrics.clicks,
          recommendation.impact.potential_metrics.cost_micros,
          recommendation.dismissed
        FROM recommendation
        WHERE recommendation.dismissed = false
    """.strip()
